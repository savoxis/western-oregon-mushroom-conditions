#!/bin/bash
# shrooms-agent.sh - Unraid side of shrooms.strong.beer: the VPS is the ACTIVE primary, home (this server) is the fallback.
#
# What it does (cron every minute):
#   * content sync: every ~10 min, while the VPS is healthy, pulls the generated static site VPS -> home through a
#     read-only forced-command key (rrsync -ro /opt/shrooms/site), then checks home's index.html is identical to what the VPS
#     serves and that the data is fresh. The fallback is a plain nginx container (nginx-shrooms) on its own LAN address.
#   * watchdog: the DNS A record shrooms.strong.beer is the role register (VPS_IP = VPS active). If the VPS origin fails for
#     FAIL_AFTER seconds AND the home path (through Nginx Proxy Manager, with a valid certificate) is healthy, it flips the
#     A record to the home IP (TTL 60). When the VPS has been healthy for RETURN_AFTER seconds and a recent sync succeeded it
#     flips back (VPS is the preferred primary). Static content, nothing to reconcile.
#   * ENABLE_FLIP=0 -> observe and report only.
# Touches only the A record named shrooms.strong.beer. Blast radius: that one record + files under
# /mnt/cache/appdata/nginx-shrooms/www. Usage: shrooms-agent.sh [run|status|sync]   DRY_RUN=1 -> decide and log, change nothing.
set -uo pipefail
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
. /boot/config/gn/shrooms.env
ST="${SH_ST:-/tmp/shrooms-agent}"; LOG=/var/log/shrooms-agent.log; mkdir -p "$ST"      # SH_ST: isolated state dir, used only by drills
KH=/root/.ssh/known_hosts_vps
SSHO="-o IdentitiesOnly=yes -o BatchMode=yes -o UserKnownHostsFile=$KH -o StrictHostKeyChecking=yes -o ConnectTimeout=15"
RS="ssh -i /root/.ssh/shrooms_pull_ed25519 $SSHO"
FAIL_AFTER="${FAIL_AFTER:-300}"; RETURN_AFTER="${RETURN_AFTER:-600}"; COOLDOWN="${COOLDOWN:-600}"; SYNC_EVERY="${SYNC_EVERY:-600}"
MAX_DATA_AGE="${MAX_DATA_AGE:-259200}"       # 3 days: the nightly build runs every day
DRY="${DRY_RUN:-0}"; FLIP="${ENABLE_FLIP:-0}"
API=https://api.cloudflare.com/client/v4

now() { date +%s; }
log() { echo "$(date '+%F %T') $*" | tee -a "$LOG" >&2; }
kp() { [ -n "${1:-}" ] || return 0; curl -fsS -m 15 -G --data-urlencode "status=$2" --data-urlencode "msg=$3" --data-urlencode "ping=" "$KUMA_BASE/$1" >/dev/null 2>&1 || log "warn: kuma push failed"; }
k_state() { kp "${TOKEN_STATE:-}" "$1" "$2"; }
k_sync() { kp "${TOKEN_SYNC:-}" "$1" "$2"; }
cf() { curl -fsS -m 20 -H "Authorization: Bearer $CF_TOKEN" -H "Content-Type: application/json" "$@"; }
read_rec() {
  local j; j="$(cf "$API/zones/$ZONE_ID/dns_records?type=A&name=$RECORD_NAME")" || return 1
  [ "$(jq -r '.success' <<<"$j")" = "true" ] || return 1
  [ "$(jq -r '.result|length' <<<"$j")" = "1" ] || return 2
  [ "$(jq -r '.result[0].name' <<<"$j")" = "$RECORD_NAME" ] || return 2
  REC_ID="$(jq -r '.result[0].id' <<<"$j")"; REC_IP="$(jq -r '.result[0].content' <<<"$j")"
  REC_MOD="$(date -d "$(jq -r '.result[0].modified_on' <<<"$j")" +%s)"
}
set_rec() {
  if [ "$DRY" = 1 ]; then log "DRY: would set $RECORD_NAME A -> $1 (ttl 60)"; return 0; fi
  local r; r="$(cf -X PATCH "$API/zones/$ZONE_ID/dns_records/$REC_ID" --data "{\"content\":\"$1\",\"ttl\":60}")" || return 1
  [ "$(jq -r '.success' <<<"$r")" = "true" ] && [ "$(jq -r '.result.content' <<<"$r")" = "$1" ]
}
home_ip() { curl -fsS -m 10 -H 'accept: application/dns-json' "https://cloudflare-dns.com/dns-query?name=$HOME_DDNS_HOST&type=A" 2>/dev/null | jq -r '[.Answer[]?|select(.type==1)|.data][0] // empty'; }
check() {  # mode(vps|home|homedirect) -> 0 if the page returns 200 and a plausible size
  local out
  # DRILL ONLY: FORCE_VPS_DOWN=1 makes the VPS look dead to the agent while it is really fine (zero visitor impact)
  [ "$1" = vps ] && [ "${FORCE_VPS_DOWN:-0}" = 1 ] && return 1
  case "$1" in
    vps) out="$(curl -sS -m 8 --resolve "$RECORD_NAME:443:$VPS_IP" -o "$ST/p.html" -w '%{http_code} %{size_download}' "https://$RECORD_NAME/" 2>/dev/null)" || return 1;;
    home) out="$(curl -sS -m 8 --resolve "$RECORD_NAME:${NPM_PORT:-443}:$NPM_IP" -o "$ST/p.html" -w '%{http_code} %{size_download}' "https://$RECORD_NAME:${NPM_PORT:-443}/" 2>/dev/null)" || return 1;;   # through NPM, certificate validated
    homedirect) out="$(curl -sS -m 8 -o "$ST/p.html" -w '%{http_code} %{size_download}' "$HOME_DIRECT" 2>/dev/null)" || return 1;;
  esac
  [ "${out%% *}" = 200 ] && [ "${out##* }" -ge 5000 ]
}
data_age() {  # seconds since the locally served data was generated (from data/c/about.json), empty if unreadable
  local g; g="$(jq -r '.[0].generated_at // empty' "$WWW/data/c/about.json" 2>/dev/null)"; [ -n "$g" ] || return 1
  echo $(( $(now) - $(date -d "$g" +%s) ))
}

sync() {
  if [ "$DRY" = 1 ]; then log "DRY: would rsync the site from the VPS"; return 0; fi
  rsync -a --delete --delay-updates --max-delete=500 --no-owner --no-group -e "$RS" "shsync@$VPS_IP:./" "$WWW/" || { log "sync: rsync failed"; k_sync down "rsync from the VPS failed"; return 1; }
  chown -R 99:100 "$WWW" 2>/dev/null; now > "$ST/last_sync"
  [ -s "$WWW/index.html" ] && [ -s "$WWW/data/c/zones.json" ] || { log "sync: files missing after rsync"; k_sync down "site files missing after sync"; return 1; }
  local age; age="$(data_age)" || { log "sync: about.json unreadable"; k_sync down "about.json unreadable after sync"; return 1; }
  if [ "$age" -gt "$MAX_DATA_AGE" ]; then log "sync: data is ${age}s old (builder stalled?)"; k_sync down "data on the VPS is stale: $(( age / 3600 )) h old (nightly build stalled?)"; return 1; fi
  local a b; a="$(sha256sum "$WWW/index.html" | cut -c1-16)"; b="$(curl -sS -m 8 --resolve "$RECORD_NAME:443:$VPS_IP" "https://$RECORD_NAME/" 2>/dev/null | sha256sum | cut -c1-16)"
  if [ "$a" = "$b" ]; then now > "$ST/last_sync_ok"; k_sync up "synced; identical index.html ($a); data $(( age / 3600 )) h old"; log "sync ok; index.html identical ($a); data ${age}s old"
  else log "sync: index.html differs ($a vs $b)"; k_sync down "home index.html differs from the VPS after sync"; return 1; fi
}

status() {
  read_rec; echo "record: $RECORD_NAME A $REC_IP (modified $(( $(now) - REC_MOD ))s ago)"
  [ "$REC_IP" = "$VPS_IP" ] && echo "role: VPS active" || echo "role: home (DNS not on the VPS)"
  check vps && echo "vps origin: healthy" || echo "vps origin: NOT healthy"
  check homedirect && echo "home container (direct): healthy" || echo "home container (direct): NOT healthy"
  check home && echo "home via NPM (valid cert): healthy" || echo "home via NPM (valid cert): NOT healthy"
  echo "data age: $(data_age || echo unknown)s; flip logic: $([ "$FLIP" = 1 ] && echo ENABLED || echo disabled)"
  [ -f "$ST/last_sync_ok" ] && echo "last good sync: $(( $(now) - $(cat "$ST/last_sync_ok") ))s ago"
}

main() {
  case "${1:-run}" in status) status; return;; sync) sync; return;; esac
  exec 9>/var/run/shrooms-agent.lock; flock -n 9 || return 0
  read_rec; local rc=$?
  if [ $rc -ne 0 ]; then log "DNS record lookup problem (rc=$rc)"; k_state down "DNS record lookup problem (rc=$rc; is $RECORD_NAME an A record?) - agent blind"; return 1; fi
  local role; [ "$REC_IP" = "$VPS_IP" ] && role=vps || role=home
  local cool_ok=1; [ $(( $(now) - REC_MOD )) -lt "$COOLDOWN" ] && cool_ok=0
  local vps_ok=0 home_ok=0 hdir_ok=0; check vps && vps_ok=1; check home && home_ok=1; check homedirect && hdir_ok=1
  local ls=0; [ -f "$ST/last_sync" ] && ls="$(cat "$ST/last_sync")"
  if [ "$vps_ok" = 1 ] && [ $(( $(now) - ls )) -ge $(( SYNC_EVERY - 20 )) ]; then sync; fi
  local why=""; [ "$home_ok" = 0 ] && { [ "$hdir_ok" = 1 ] && why=" (container OK but the NPM host/cert path fails)" || why=" (container down)"; }

  if [ "$FLIP" != 1 ]; then
    k_state up "observing only (flip disabled): DNS $([ "$role" = vps ] && echo "on VPS" || echo "at home"); vps healthy=$vps_ok home healthy=$home_ok$why"; return
  fi
  if [ "$role" = vps ]; then
    if [ "$vps_ok" = 1 ]; then
      rm -f "$ST/vps_bad_since"
      if [ "$home_ok" = 1 ]; then k_state up "VPS active and healthy; home fallback healthy"; else k_state down "VPS active, but the HOME FALLBACK is not healthy$why"; fi
    else
      [ -f "$ST/vps_bad_since" ] || now > "$ST/vps_bad_since"
      local el=$(( $(now) - $(cat "$ST/vps_bad_since") )); log "VPS origin failing for ${el}s (fallback at ${FAIL_AFTER}s; home healthy=$home_ok)"
      if [ "$el" -ge "$FAIL_AFTER" ] && [ "$home_ok" = 1 ] && [ "$cool_ok" = 1 ]; then
        local hip; hip="$(home_ip)"
        if [ -n "$hip" ] && set_rec "$hip"; then now > "$ST/flip_at"; rm -f "$ST/vps_bad_since"; log "FALLBACK: $RECORD_NAME -> home $hip"; k_state down "FALLBACK active: serving from HOME ($hip); VPS was down >${FAIL_AFTER}s"
        else log "FALLBACK failed (home ip '$hip' / DNS update error)"; k_state down "FALLBACK FAILED (could not update DNS)"; fi
      else k_state down "VPS origin failing ${el}s (home healthy=$home_ok$why; fallback at ${FAIL_AFTER}s)"; fi
    fi
  else
    if [ "$vps_ok" = 1 ]; then
      [ -f "$ST/vps_good_since" ] || now > "$ST/vps_good_since"
      local g=$(( $(now) - $(cat "$ST/vps_good_since") ))
      local lso=0; [ -f "$ST/last_sync_ok" ] && lso="$(cat "$ST/last_sync_ok")"
      if [ "$g" -ge "$RETURN_AFTER" ] && [ "$cool_ok" = 1 ] && [ $(( $(now) - lso )) -le 900 ]; then
        if set_rec "$VPS_IP"; then now > "$ST/flip_at"; rm -f "$ST/vps_good_since"; log "RETURN: $RECORD_NAME -> VPS $VPS_IP (healthy ${g}s)"; k_state up "VPS active again (healthy ${g}s before returning)"
        else log "RETURN failed: DNS update error"; k_state down "RETURN to VPS FAILED (DNS update error)"; fi
      else k_state down "serving from HOME; VPS healthy for ${g}s (returns at ${RETURN_AFTER}s, needs a recent good sync)"; fi
    else rm -f "$ST/vps_good_since"; k_state down "serving from HOME; VPS unhealthy"; fi
  fi
}
main "$@"
