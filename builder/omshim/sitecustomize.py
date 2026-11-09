"""Loaded automatically by Python when this folder is on PYTHONPATH (the builder sets it for the skill subprocesses).
Routes the unmodified skill scripts' Open-Meteo calls through om_key (customer host + API key, free-host fallback)."""
import sys

try:
    if "/opt/shrooms" not in sys.path:
        sys.path.append("/opt/shrooms")
    import urllib.request as _ur
    import om_key as _om
    _orig = _ur.urlopen

    def _urlopen(url, *a, **kw):
        return _om.urlopen(url, *a, _orig=_orig, **kw)

    _ur.urlopen = _urlopen
except Exception:
    pass
