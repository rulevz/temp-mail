# temp-mail — catch-all inbox for `rulevz.web.id`

Self-hosted disposable email on **Cloudflare Email Routing + Workers + KV**, with
OTP extraction, a small JSON API and a Telegram bot front-end.

No VPS required for mail: Cloudflare receives the mail, a Worker parses it and
stores it in KV for 24 hours. The Telegram bot is optional and can run anywhere.

```
mail to anything@rulevz.web.id
   → Cloudflare Email Routing (catch-all)
   → Worker (worker.js)
       ├─ KV:  msg:<addr>:<ts>:<id>   (24h TTL)
       └─ Telegram push (from + subject + OTP)
Telegram bot (bot.py)
   /new /list /otp /read  →  worker JSON API
```

## Features

- **Unlimited addresses** — any local part at `rulevz.web.id` works, no signup.
- **OTP extraction** — 4–8 digit codes, with context-aware matching.
- **Telegram push** — every incoming mail is forwarded with sender, subject and OTP.
- **JSON API** — `/new`, `/messages`, `/message`, protected by a shared secret.
- **Zero infrastructure** — Email Routing + Worker + KV; the bot is optional.
- **24h retention** — KV TTL, easy to change.

## Deploy

### 1. KV namespace

Cloudflare dashboard → **Storage & Databases → KV → Create namespace**, name it
`mailbot`, copy the namespace ID.

### 2. Worker

Workers & Pages → **Create → Worker**, paste `worker.js`, deploy.

Bindings (Worker → Settings → Variables and Secrets):

| Name | Type | Value |
|---|---|---|
| `MAIL_KV` | KV binding | `mailbot` |
| `MAIL_DOMAIN` | Variable | `rulevz.web.id` |
| `API_SECRET` | Secret | long random string |
| `TG_TOKEN` | Secret | Telegram bot token (optional) |
| `TG_CHAT` | Secret | numeric chat id (optional) |

Note the worker URL: `https://temp-mail.<subdomain>.workers.dev`.

### 3. Email Routing

`rulevz.web.id` → **Email → Email Routing → Routes → Catch-all** →
Action **Send to a Worker** → pick this worker → Save.

Make sure the domain's MX records point to Cloudflare Email Routing.

### 4. Test

```bash
curl "https://temp-mail.<subdomain>.workers.dev/health"
curl "https://temp-mail.<subdomain>.workers.dev/new?secret=$API_SECRET&label=demo"
curl "https://temp-mail.<subdomain>.workers.dev/messages?secret=$API_SECRET&addr=demo-xxxxx@rulevz.web.id"
```

Send an email to the generated address; it should appear in KV (and Telegram if
configured) within seconds.

### 5. Telegram bot (optional)

```bash
cd bot
python3 -m pip install -r requirements.txt

export TG_TOKEN="123456:ABC..."
export TG_CHAT="123456789"
export MAIL_API_BASE="https://temp-mail.<subdomain>.workers.dev"
export API_SECRET="same-secret-as-worker"
export MAIL_DOMAIN="rulevz.web.id"

python3 bot.py
```

Commands:

```
/new [label]          create a fresh address
/list [addr|last]     list inbox
/otp [addr|last]      latest OTP
/read [addr|last] <id> show full message
```

## API

All endpoints except `/health` require `?secret=API_SECRET`.

| Method | Path | Params | Returns |
|---|---|---|---|
| GET | `/health` | — | `{"ok":true}` |
| GET | `/new` | `label` | `{"address":"label-xxxxx@rulevz.web.id"}` |
| GET | `/messages` | `addr` | `{"address":...,"messages":[{id,from,subject,otp,at}]}` |
| GET | `/message` | `addr`,`id` | full record incl. `body` |

Details and curl examples: [`docs/API.md`](docs/API.md).

## Security notes

- `API_SECRET` is the only gate on the worker API — generate 32+ random bytes
  and keep it out of URLs that end up in logs/browsers.
- The worker stores raw text bodies (HTML stripped) up to 40 KB; attachments are
  not stored.
- KV entries expire after 24h (`expirationTtl` in `worker.js`).
- Rotate `API_SECRET` and `TG_TOKEN` if they ever leak; update the bot env.

## Limitations

- Text/plain bodies only; HTML is stripped for OTP extraction.
- One domain per deployment (`MAIL_DOMAIN`).
- No web UI — the API and Telegram bot are the interface.
- Cloudflare Workers free plan limits apply (requests/KV ops per day).

## License

MIT — see [LICENSE](LICENSE).
