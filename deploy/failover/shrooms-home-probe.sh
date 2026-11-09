#!/bin/bash
# shrooms-home-probe.sh - runs on the VPS every 5 min. Checks the HOME fallback copy of shrooms.strong.beer the way a visitor
# would reach it if DNS pointed at home: resolve the home IP (DDNS name), connect to it from the internet with SNI + certificate
# validation, and read data/c/about.json (also checks the data is fresh). Reports to the Kuma push monitor
# "shrooms home fallback (from internet)". Read-only: it changes nothing. Logs only problems to /var/log/shrooms-home-probe.log.
set -uo pipefail
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
. /etc/shrooms-failover.env
HOST=shrooms.strong.beer; MAXAGE=259200; TMP="$(mktemp)"; trap 'rm -f "$TMP"' EXIT
push() { curl -fsS -m 15 -G --data-urlencode "status=$1" --data-urlencode "msg=$2" --data-urlencode "ping=" "$KUMA_BASE/$TOKEN_REACH" >/dev/null 2>&1 || true
         [ "$1" = up ] || echo "$(date '+%F %T') $1: $2" >> /var/log/shrooms-home-probe.log; }
HIP="$(curl -fsS -m 10 -H 'accept: application/dns-json' "https://cloudflare-dns.com/dns-query?name=$HOME_DDNS_HOST&type=A" 2>/dev/null | jq -r '[.Answer[]?|select(.type==1)|.data][0] // empty')"
[ -n "$HIP" ] || { push down "could not resolve $HOME_DDNS_HOST (the home IP)"; exit 0; }
out="$(curl -sS -m 15 --resolve "$HOST:443:$HIP" -o "$TMP" -w '%{http_code} %{ssl_verify_result}' "https://$HOST/data/c/about.json" 2>&1)" || { push down "home fallback unreachable on $HIP:443 (${out:0:120})"; exit 0; }
code="${out%% *}"; ver="${out##* }"
if [ "$code" != 200 ]; then push down "home fallback answered HTTP $code (NPM host missing or container down?)"; exit 0; fi
if [ "$ver" != 0 ]; then push down "home fallback certificate does not validate for $HOST (ssl verify code $ver)"; exit 0; fi
gen="$(jq -r '.[0].generated_at // empty' "$TMP" 2>/dev/null)"; [ -n "$gen" ] || { push down "home fallback served data without generated_at"; exit 0; }
age=$(( $(date +%s) - $(date -d "$gen" +%s) ))
if [ "$age" -gt "$MAXAGE" ]; then push down "home fallback data is $(( age / 3600 )) h old (sync stalled?)"; exit 0; fi
push up "home fallback reachable at $HIP with a valid certificate; data $(( age / 3600 )) h old"
