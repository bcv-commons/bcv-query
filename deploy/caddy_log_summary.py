#!/usr/bin/env python3
"""Summarize the Caddy access logs of the API hosts (/var/log/caddy/access.log*, JSON, rotated).

Who calls, how much, and who is hitting the limits: requests, bytes, status mix, top clients, top user
agents, top paths, and the clients with the most 429/403 responses. Run it on the host (needs sudo to read
the log, which is 0640 caddy:caddy):

  ssh lgunnars@37.27.81.207 'sudo python3 - --hours 24' < deploy/caddy_log_summary.py

Query text and the X-Api-Key header are redacted in the log itself (see the Caddyfile, snippet api-log).
"""
import argparse
import collections
import glob
import ipaddress
import json
import re
import time


def cloudflare_ranges(path: str = "/etc/caddy/cloudflare-ips.caddy") -> list:
    """The Cloudflare ranges Caddy trusts (empty if the file is absent)."""
    try:
        text = open(path).read()
    except OSError:
        return []
    m = re.search(r"remote_ip ([^\n]+)", text)
    return [ipaddress.ip_network(x) for x in m.group(1).split()] if m else []


def client_ip(req: dict, cf: list) -> str:
    """remote_ip, except behind Cloudflare: then the visitor's CF-Connecting-IP (honoured only from its ranges)."""
    ip = req.get("remote_ip", "?")
    hdr = (req.get("headers", {}).get("Cf-Connecting-Ip") or [None])[0]
    try:
        if hdr and any(ipaddress.ip_address(ip) in net for net in cf):
            return hdr
    except ValueError:
        pass
    return ip


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=float, default=24)
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--log", default="/var/log/caddy/access.log")
    a = ap.parse_args()
    since = time.time() - a.hours * 3600
    cf = cloudflare_ranges()
    n = 0
    by_host, status, ips, uas, paths, bad, bytes_by_ip = (collections.Counter() for _ in range(7))
    first = last = None
    for f in sorted(glob.glob(a.log + "*")):
        if f.endswith(".gz"):
            continue
        with open(f, errors="replace") as fh:
            for line in fh:
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                ts = d.get("ts", 0)
                if ts < since:
                    continue
                r = d.get("request", {})
                ip, host = client_ip(r, cf), r.get("host", "?")
                ua = (r.get("headers", {}).get("User-Agent") or ["-"])[0][:70]
                path = r.get("uri", "?").split("?")[0]
                path = "/".join(path.split("/")[:3])                      # group /verse/GEN/1/1 -> /verse/GEN
                st = d.get("status", 0)
                n += 1
                first = ts if first is None else min(first, ts)
                last = ts if last is None else max(last, ts)
                by_host[host] += 1
                status[st] += 1
                ips[ip] += 1
                uas[ua] += 1
                paths[f"{host}{path}"] += 1
                bytes_by_ip[ip] += d.get("size", 0)
                if st in (429, 403, 401):
                    bad[(ip, st)] += 1
    if not n:
        print(f"no requests in the last {a.hours:g} h")
        return
    span = (last - first) / 3600 or 1
    print(f"{n} requests in {span:.1f} h ({n / span:.0f}/h)")
    print("hosts:", dict(by_host.most_common()))
    print("status:", dict(sorted(status.items())))
    for title, c in (("top clients", ips), ("top user agents", uas), ("top paths", paths)):
        print(f"\n{title}:")
        for k, v in c.most_common(a.top):
            extra = f"  {bytes_by_ip[k] / 1e6:.1f} MB" if c is ips else ""
            print(f"  {v:7d}  {k}{extra}")
    if bad:
        print("\nrefused (429 rate limit / 403 blocked crawler / 401 no key), by client:")
        for (ip, st), v in bad.most_common(a.top):
            print(f"  {v:7d}  {ip}  status {st}")


if __name__ == "__main__":
    main()
