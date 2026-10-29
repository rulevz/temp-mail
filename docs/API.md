# API

Base URL: `https://temp-mail.<subdomain>.workers.dev`

Every endpoint except `/health` requires the shared secret:

```
?secret=API_SECRET
```

A wrong or missing secret returns `403 {"error":"forbidden"}`.

---

## `GET /health`

No auth. Returns `{"ok":true}` — useful for uptime checks.

```bash
curl -s "https://temp-mail.<subdomain>.workers.dev/health"
```

## `GET /new`

Create an address. The local part is `label-xxxxx` (lowercase alphanumeric and
dashes, max 20 chars). Nothing is stored — any address at the domain already
works thanks to the catch-all.

| Param | Required | Description |
|---|---|---|
| `secret` | yes | shared secret |
| `label` | no | prefix, default `tmp` |

```bash
curl -s "https://temp-mail.<subdomain>.workers.dev/new?secret=$API_SECRET&label=demo"
# {"address":"demo-a1b2c@rulevz.web.id"}
```

## `GET /messages`

List metadata for an address, newest first. Full bodies are not included.

| Param | Required | Description |
|---|---|---|
| `secret` | yes | shared secret |
| `addr` | yes | full address |

```bash
curl -s "https://temp-mail.<subdomain>.workers.dev/messages?secret=$API_SECRET&addr=demo-a1b2c@rulevz.web.id"
```

```json
{
  "address": "demo-a1b2c@rulevz.web.id",
  "messages": [
    {"id":"9f3a1c2d","to":"demo-a1b2c@rulevz.web.id","from":"noreply@example.com",
     "subject":"Your code","otp":"483920","at":1793300000000}
  ]
}
```

## `GET /message`

Full record, including the text body (max 40 KB, HTML stripped).

| Param | Required | Description |
|---|---|---|
| `secret` | yes | shared secret |
| `addr` | yes | full address |
| `id` | yes | message id from `/messages` |

```bash
curl -s "https://temp-mail.<subdomain>.workers.dev/message?secret=$API_SECRET&addr=demo-a1b2c@rulevz.web.id&id=9f3a1c2d"
```

```json
{
  "id": "9f3a1c2d",
  "to": "demo-a1b2c@rulevz.web.id",
  "from": "noreply@example.com",
  "subject": "Your code",
  "otp": "483920",
  "body": "Your verification code is 483920.",
  "at": 1793300000000
}
```

## Errors

| Status | Body | Cause |
|---|---|---|
| 400 | `{"error":"addr required"}` | missing `addr` |
| 400 | `{"error":"addr and id required"}` | missing `id` |
| 403 | `{"error":"forbidden"}` | bad/missing `secret` |
| 404 | `{"error":"not found"}` | unknown path or message id |

## Retention

Messages live in KV for **24 hours** (`expirationTtl: 86400` in `worker.js`).
Change that value to keep mail longer; KV has no query API beyond prefix listing,
so the 24h window also keeps the namespace small.
