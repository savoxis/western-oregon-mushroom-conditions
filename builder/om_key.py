"""Open-Meteo commercial API key support for the shrooms builder and (through omshim/sitecustomize.py) the unmodified skill scripts.

The key is read from the environment (OPENMETEO_API_KEY) or from /etc/shrooms-openmeteo.env (root:mushroom, mode 640). It is never
logged. Behavior:
  - api.open-meteo.com (forecast, elevation)  ->  customer-api.open-meteo.com + apikey    (API Standard plan and up)
  - archive-api.open-meteo.com (ERA5 history) ->  customer-archive-api.open-meteo.com     only when OPENMETEO_ARCHIVE_CUSTOMER=1
    (the Historical Weather API needs the API Professional plan; with only Standard it answers 403, so it is off by default)
  - if the customer host rejects the key or the plan (HTTP 400/401/402/403), the call is repeated once on the free host so the site keeps
    working, and one line goes to stderr.
Stdlib only.
"""
import os
import sys
import urllib.parse
import urllib.request
import urllib.error

KEYFILE = os.environ.get("OPENMETEO_ENV_FILE", "/etc/shrooms-openmeteo.env")
_cache = {}
_warned = set()


def _conf(name):
    if name in _cache:
        return _cache[name]
    val = os.environ.get(name, "")
    if not val:
        try:
            with open(KEYFILE) as fh:
                for line in fh:
                    line = line.strip()
                    if line.startswith(name + "="):
                        val = line.split("=", 1)[1].strip().strip("'\"")
        except OSError:
            pass
    _cache[name] = val
    return val


def key():
    return _conf("OPENMETEO_API_KEY")


def rewrite(url):
    """Returns the customer-host URL with the key attached, or the URL unchanged when no key / not an Open-Meteo data host."""
    k = key()
    if not k or "apikey=" in url:
        return url
    p = urllib.parse.urlsplit(url)
    host = p.hostname
    if host == "api.open-meteo.com":
        new = "customer-api.open-meteo.com"
    elif host == "archive-api.open-meteo.com" and _conf("OPENMETEO_ARCHIVE_CUSTOMER") == "1":
        new = "customer-archive-api.open-meteo.com"
    else:
        return url
    q = p.query + ("&" if p.query else "") + "apikey=" + urllib.parse.quote(k, safe="")
    return urllib.parse.urlunsplit((p.scheme, new, p.path, q, p.fragment))


def _warn(host, code):
    if host not in _warned:
        _warned.add(host)
        sys.stderr.write("om_key: %s answered HTTP %s; using the free host for this run\n" % (host, code))


def urlopen(url_or_req, *a, _orig=None, **kw):
    """Drop-in for urllib.request.urlopen: tries the customer host first, falls back to the free host on a key or plan error."""
    op = _orig or urllib.request.urlopen
    is_req = hasattr(url_or_req, "full_url")
    orig_url = url_or_req.full_url if is_req else url_or_req
    new_url = rewrite(orig_url) if isinstance(orig_url, str) else orig_url
    if new_url == orig_url:
        return op(url_or_req, *a, **kw)
    if is_req:
        url_or_req.full_url = new_url
    else:
        url_or_req = new_url
    try:
        return op(url_or_req, *a, **kw)
    except urllib.error.HTTPError as exc:
        if exc.code in (400, 401, 402, 403):
            _warn(urllib.parse.urlsplit(new_url).hostname, exc.code)
            if is_req:
                url_or_req.full_url = orig_url
            else:
                url_or_req = orig_url
            return op(url_or_req, *a, **kw)
        raise
