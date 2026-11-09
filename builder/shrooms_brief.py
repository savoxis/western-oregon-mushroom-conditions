"""shrooms_brief.py - optional nightly plain-English brief written by Gemini from the site's own numbers.

Safety design:
  * Gemini only ever sees the public numbers already shown on the site (zone names, scores, weather aggregates).
    No home location, no secrets, no user data.
  * The key is read from /etc/shrooms/gemini.json (root:mushroom 640), never logged, never written to the site tree.
  * The model is told to use ONLY the supplied numbers, to give no identification or edibility advice and no place names
    that are not in the data. The mandatory fine print is appended by code, not by the model.
  * The text is stored in the database (briefs table) and published as plain text; the page renders it with textContent.
  * Any failure (no key, network, quota, empty answer) just means the site shows no brief that night.
"""
import json
import re
import time
import urllib.error
import urllib.request
from datetime import datetime

CONF = "/etc/shrooms/gemini.json"      # {"api_key": "...", "model": "gemini-flash-latest"}
NOTE = "Written by an AI model from the numbers on this site. It can be wrong; the scores and the fine print are what count."

SYSTEM = (
    "You write a short nightly conditions brief for a public Oregon mushroom-forecast website. "
    "Use ONLY the data in the user message. Do not invent places, trailheads, numbers, dates or weather. "
    "Do not give identification, edibility or safety-to-eat advice. Do not promise mushrooms: scores are likelihoods "
    "from a weather model. Plain text only, no markdown, no lists, no emoji. Maximum 110 words, 2 short paragraphs: "
    "(1) where conditions look best right now and why, citing 2-3 of the supplied numbers (soil temperature, rain, "
    "humidity, soil moisture); (2) what the 10-day forecast changes. If nothing scores above 'marginal', say so plainly."
)


def _conf():
    try:
        c = json.load(open(CONF))
        return c["api_key"], c.get("model", "gemini-flash-latest")
    except Exception:
        return None, None


def _digest(live, zones, con):
    names = {z["id"]: z["name"] for z in zones}
    rows = []
    for zid, e in live["zones"].items():
        for sp, r in e["species"].items():
            rows.append((r["score"], zid, sp, r["label"], e.get("forecast") or {}))
    rows.sort(reverse=True)
    wx = {}
    for zid, d, rh, vpd, sm, st, pr in con.execute(
            "SELECT zone, MAX(date), rh_mean, vpd_kpa, soil_m_shallow, soil_t_shallow_f, precip_in FROM weather_daily "
            "WHERE source='forecast' GROUP BY zone"):
        wx[zid] = {"date": d, "rh_mean_pct": rh, "vpd_kpa": vpd, "soil_moisture": sm, "soil_temp_f": st, "precip_in": pr}
    lines = ["Date: %s" % datetime.now().strftime("%Y-%m-%d"), "Top zone x species scores (0-100):"]
    for score, zid, sp, label, fc in rows[:8]:
        w = wx.get(zid, {})
        lines.append("- %s | %s | score %s (%s) | latest day: soil temp %s F, soil moisture %s, humidity %s%%, vpd %s kPa | "
                     "10-day forecast rain %s in, daily highs %s-%s F" % (
                         names.get(zid, zid), sp, score, label,
                         _r(w.get("soil_temp_f")), _r(w.get("soil_moisture"), 2), _r(w.get("rh_mean_pct")), _r(w.get("vpd_kpa"), 2),
                         fc.get("rain_10d_in"), fc.get("daily_high_lowest_f"), fc.get("daily_high_highest_f")))
    n_on = sum(1 for r in rows if r[0] >= 60)
    lines.append("Zone x species combos scoring 60 or more: %d of %d in season." % (n_on, len(rows)))
    return "\n".join(lines), rows


def _r(v, n=0):
    return "n/a" if v is None else round(v, n)


def make_brief(live, zones, con, log, force=False):
    """force=True writes a fresh brief even if one is stored for today (used after a live rescore so text and scores agree)."""
    key, model = _conf()
    if not key:
        return None
    today = datetime.now().strftime("%F")
    have = con.execute("SELECT model, text FROM briefs WHERE date=? AND scope='oregon'", (today,)).fetchone()
    if have and not force:                     # one Gemini call per day unless a rescore asks for a fresh brief
        log("brief: reusing today's stored brief (no API call)")
        return {"date": today, "model": have[0], "text": have[1], "note": NOTE}
    prompt, rows = _digest(live, zones, con)
    if not rows:
        return None
    body = {"systemInstruction": {"parts": [{"text": SYSTEM}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.3, "maxOutputTokens": 4096}}   # headroom: newer Gemini models spend tokens thinking
    req = urllib.request.Request(
        "https://generativelanguage.googleapis.com/v1beta/models/%s:generateContent" % model,
        data=json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json", "x-goog-api-key": key})
    resp = None
    for attempt in range(4):                    # Gemini answers 503 now and then when busy; a failed call is not billed
        try:
            with urllib.request.urlopen(req, timeout=150) as r:
                resp = json.loads(r.read().decode())
            break
        except urllib.error.HTTPError as exc:
            if exc.code not in (429, 500, 502, 503, 504) or attempt == 3:
                raise
            log("brief: Gemini HTTP %s, retrying" % exc.code)
            time.sleep(30 * (attempt + 1))
        except (TimeoutError, urllib.error.URLError) as exc:
            if attempt == 3:
                raise
            log("brief: Gemini timeout/network error, retrying")
            time.sleep(20)
    cand = resp["candidates"][0]
    if cand.get("finishReason") not in (None, "STOP"):
        log("brief: not published, finishReason=%s" % cand.get("finishReason"))
        return None
    parts = cand["content"]["parts"]
    text = " ".join(p.get("text", "") for p in parts if not p.get("thought")).strip()
    text = re.sub(r"[*_#`<>]", "", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)[:900]
    if len(text) < 40:
        return None
    con.execute("INSERT OR REPLACE INTO briefs VALUES (?,?,?,?)", (today, "oregon", model, text))
    con.commit()
    log("brief written by %s (%d chars)" % (model, len(text)))
    return {"date": today, "model": model, "text": text, "note": NOTE}
