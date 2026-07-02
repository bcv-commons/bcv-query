# Edge / hosting hardening

The public edge for the hosted services. Caddy already terminates TLS and reverse-proxies
both services; this covers the hardening the app layer can't do (TLS, volumetric/DDoS,
cheap pre-filtering) — see [MCP Guide](mcp.md) and [Client Guide](client-guide.md) for the
app-level auth/rate-limit that complements it.

Current topology (Caddy, `/etc/caddy/Caddyfile`):

```
bcv-query.up.qombi.com  → localhost:8081   (bcv-RAG, incl. /mcp)
shoresh.up.qombi.com    → localhost:8080   (shoresh)
```

## 1. Close shoresh's raw public port (do first — security)

shoresh is reachable **both** via Caddy (TLS) **and** directly on `0.0.0.0:8080` (no TLS,
no edge). Bind its published port to loopback so it's only reachable through Caddy — in the
shoresh stack's `docker-compose.yml`:

```yaml
    ports:
      - "127.0.0.1:8080:8080"   # was "8080:8080" (0.0.0.0) — now loopback only
```

`docker compose up -d` to apply. Caddy (`localhost:8080`) keeps working; the public `:8080`
closes. (bcv-RAG is already correct at `127.0.0.1:8081`.)

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

bcv-query.up.qombi.com {
	import hardened
	reverse_proxy localhost:8081
}

shoresh.up.qombi.com {
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
