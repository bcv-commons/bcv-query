#!/usr/bin/env bash
# Report the expiry of every certificate Caddy serves (one per site address in the Caddyfile); exit 1 if one has
# fewer than WARN_DAYS left (default 21). Caddy renews at ~30 days left, so a warning here means a renewal FAILED
# (typically the ACME http-01 path blocked on port 80: a Cloudflare rule, a redirect, a firewall).
#
# Installed on the host as /usr/local/sbin/check-cert-expiry, run daily by the systemd timer check-cert-expiry.timer.
# A failing run shows up in `systemctl --failed` and the journal (journalctl -u check-cert-expiry).
#   sudo /usr/local/sbin/check-cert-expiry          # table
set -uo pipefail
WARN_DAYS="${WARN_DAYS:-21}"; CADDYFILE="${CADDYFILE:-/etc/caddy/Caddyfile}"
hosts=$(grep -E '^[a-z0-9][a-z0-9.-]+\.[a-z]+ \{' "$CADDYFILE" | sed 's/ {$//')
rc=0; now=$(date +%s)
for h in $hosts; do
  end=$(echo | openssl s_client -connect 127.0.0.1:443 -servername "$h" 2>/dev/null | openssl x509 -noout -enddate 2>/dev/null | cut -d= -f2)
  if [ -z "$end" ]; then printf '%-32s NO CERTIFICATE SERVED\n' "$h"; rc=1; continue; fi
  days=$(( ($(date -d "$end" +%s) - now) / 86400 ))
  flag=ok; [ "$days" -lt "$WARN_DAYS" ] && { flag="WARNING: renewal overdue"; rc=1; }
  printf '%-32s expires %s  (%3d days)  %s\n' "$h" "$(date -d "$end" +%F)" "$days" "$flag"
done
exit $rc
