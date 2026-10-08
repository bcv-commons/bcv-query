# Edge / hosting hardening

The public edge for the hosted services. Caddy already terminates TLS and reverse-proxies
both services; this covers the hardening the app layer can't do (TLS, volumetric/DDoS,
cheap pre-filtering) — see [MCP Guide](mcp.md) and [Client Guide](client-guide.md) for the
app-level auth/rate-limit that complements it.

Current topology (Caddy, `/etc/caddy/Caddyfile`):

```
bcv-query.qombi.com  → localhost:8081   (bcv-RAG, incl. /mcp)
shoresh.qombi.com    → localhost:8080   (shoresh)
```

## 1. shoresh's `:8080` exposure

shoresh publishes `0.0.0.0:8080`. Two things matter here:

- **External `:8080` is already blocked by the Hetzner cloud firewall** (per the compose
  comment). Verify that firewall rule exists — it's the actual control.
- **Do NOT loopback-bind it** (`127.0.0.1:8080:8080`). Tested and reverted: bcv-RAG reaches
  shoresh via `SHORESH_URL=http://host.docker.internal:8080` (the docker **bridge gateway**,
  not loopback), so a loopback bind cuts the private bcv-RAG→shoresh path.

The clean way to take shoresh off the host port entirely (so the firewall isn't the only
guard) is to put **bcv-RAG and shoresh on a shared docker network** and switch `SHORESH_URL`
to service DNS (`http://shoresh:8080`); then the published `:8080` can be dropped. That's a
compose change across both stacks — worth doing, but out of scope for a quick hardening pass.

## 2. Caddy hardening (request limits + security headers)

Standard Caddy has **no built-in rate limiting** (that needs the `caddy-ratelimit` module via
an `xcaddy` build, or Cloudflare below). What it *can* do without a rebuild — size limits and
headers — is worth adding:

```caddyfile
(hardened) {
	request_body {
		max_size 1MB          # reject oversized bodies before they reach the app
	}
	header {
		-Server
		Strict-Transport-Security "max-age=31536000"
		X-Content-Type-Options "nosniff"
		Referrer-Policy "no-referrer"
	}
}

bcv-query.qombi.com {
	import hardened
	reverse_proxy localhost:8081
}

shoresh.qombi.com {
	import hardened
	reverse_proxy localhost:8080
}
```

`caddy reload` (or `systemctl reload caddy`) to apply.

## 3. Cloudflare (recommended — the volumetric / WAF layer)

App + Caddy still run on your host, so a large flood hits your bandwidth. Cloudflare in front
absorbs it upstream and adds a WAF + edge rate limiting without an `xcaddy` rebuild. Checklist:

1. Add the domain to Cloudflare; point DNS (proxied / orange-cloud) at the host.
2. **SSL/TLS mode: Full (strict)** — Caddy already serves valid certs.
3. **WAF → Managed Rules: on** (OWASP core).
4. **Rate limiting rule** (edge, before it reaches you), e.g.:
   - path `*/api/ask*` or `*/api/search*semantic*` → **20 req / min / IP** → block/challenge.
   - path `*/mcp*` and other `*/api/*` → **120 req / min / IP**.
5. **Cache rule: bypass cache for `/api/*` and `/mcp`** — never cache authenticated API responses.
6. Optionally **Bot Fight Mode** and an **IP allowlist** for known partners.

## Division of responsibility

| Layer | Does | Owner |
|---|---|---|
| App (bcv-RAG) | API-key registration gate + per-key/IP rate limit (`server/gate.py`) | code (shipped) |
| Caddy | TLS, routing, body-size limits, security headers | this doc |
| Cloudflare | DDoS/volumetric, WAF, edge rate limiting, bot filtering | ops (checklist above) |
| Provider caps | OpenAI / Cloudflare **spend ceilings + alerts** — the financial backstop | ops (dashboard) |

> **Hostnames (2026-10-06):** the APIs moved from `*.up.qombi.com` to `bcv-query.qombi.com` and `shoresh.qombi.com`
> (one level up, so a free Cloudflare certificate covers them). The old two-level names redirect with a 308 for a
> transition period; update any client that does not follow redirects.
>
> **Files host (2026-10-08):** `files.qombi.com` is DNS-only (not proxied) and serves the large published data files
> (`GET /files`, `/files/{name}`; Caddy block on the origin, limit `SHORESH_FILES_LIMIT`, default 8/hour per IP). Cloudflare's free plan
> does not carry multi-GB bodies; the trade-off is that this name shows the origin IP. The same path on `shoresh.qombi.com` redirects there.
