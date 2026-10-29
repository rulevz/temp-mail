#!/usr/bin/env python3
"""Telegram front-end for the Cloudflare mail worker.

Commands:
  /new [label]          create a fresh address on your domain
  /list <addr|last>     list inbox
  /otp <addr|last>      show latest OTP
  /read <addr|last> <id> show full message
"""
import json, os, sys, time
import requests

BASE = os.path.dirname(os.path.abspath(__file__))
CONF = os.path.join(BASE, "config.json")
STATE = os.path.join(BASE, "state.json")

# config.json is optional: env vars take precedence, so the bot can run as a
# systemd/docker service without a file on disk.
conf = {}
if os.path.exists(CONF):
    with open(CONF) as f:
        conf = json.load(f)

TOKEN = os.environ.get("TG_TOKEN") or conf.get("bot_token", "")
CHAT = str(os.environ.get("TG_CHAT") or conf.get("chat_id", ""))
API = (os.environ.get("MAIL_API_BASE") or conf.get("api_base", "")).rstrip("/")
SECRET = os.environ.get("API_SECRET") or conf.get("api_secret", "")
DOMAIN = os.environ.get("MAIL_DOMAIN") or conf.get("domain", "rulevz.web.id")
if not TOKEN or not API or not SECRET:
    raise SystemExit("set TG_TOKEN, MAIL_API_BASE and API_SECRET (env or config.json)")

def load_state():
    try:
        return json.load(open(STATE))
    except Exception:
        return {}

def save_state(s):
    json.dump(s, open(STATE, "w"), indent=1)

state = load_state()

def tg(method, **kw):
    return requests.post(f"https://api.telegram.org/bot{TOKEN}/{method}", json=kw, timeout=70).json()

def send(chat_id, text):
    for chunk in [text[i:i+3800] for i in range(0, len(text), 3800)] or [""]:
        r = tg("sendMessage", chat_id=chat_id, text=chunk, disable_web_page_preview=True)
        if not r.get("ok"):
            print("send failed", r, flush=True)

def resolve(chat_id, arg):
    if arg and arg != "last":
        return arg.lower().strip()
    return state.get(str(chat_id), {}).get("addr")

def cmd_new(chat_id, label):
    r = requests.get(f"{API}/new", params={"secret": SECRET, "label": label or "tmp"}, timeout=30).json()
    addr = r.get("address")
    if not addr:
        return send(chat_id, f"gagal bikin alamat: {r}")
    state.setdefault(str(chat_id), {})["addr"] = addr
    save_state(state)
    send(chat_id, f"alamat baru:\n{addr}\n\npakai /list buat cek inbox")

def cmd_list(chat_id, arg):
    addr = resolve(chat_id, arg)
    if not addr:
        return send(chat_id, "belum ada alamat. /new dulu")
    r = requests.get(f"{API}/messages", params={"secret": SECRET, "addr": addr}, timeout=30).json()
    msgs = r.get("messages", [])
    if not msgs:
        return send(chat_id, f"{addr}\n\n(inbox kosong)")
    lines = [f"{addr}\n"]
    for m in msgs[:15]:
        lines.append(f"• {m.get('subject','(no subject)')[:60]}\n  from: {m.get('from','?')[:40]}\n  id: {m.get('id')}  otp: {m.get('otp') or '-'}")
    send(chat_id, "\n".join(lines))

def cmd_otp(chat_id, arg):
    addr = resolve(chat_id, arg)
    if not addr:
        return send(chat_id, "belum ada alamat. /new dulu")
    r = requests.get(f"{API}/messages", params={"secret": SECRET, "addr": addr}, timeout=30).json()
    for m in r.get("messages", []):
        if m.get("otp"):
            return send(chat_id, f"OTP: {m['otp']}\nfrom: {m.get('from')}\nsubject: {m.get('subject')}")
    send(chat_id, "belum ada OTP masuk")

def cmd_read(chat_id, arg):
    parts = (arg or "").split()
    if not parts:
        return send(chat_id, "format: /read <addr|last> <id>")
    addr = resolve(chat_id, parts[0])
    mid = parts[1] if len(parts) > 1 else ""
    if not addr or not mid:
        return send(chat_id, "format: /read <addr|last> <id>")
    r = requests.get(f"{API}/message", params={"secret": SECRET, "addr": addr, "id": mid}, timeout=30).json()
    if r.get("error"):
        return send(chat_id, f"error: {r['error']}")
    body = (r.get("body") or "")[:3000]
    send(chat_id, f"from: {r.get('from')}\nsubject: {r.get('subject')}\notp: {r.get('otp')}\n\n{body}")

def handle(msg):
    chat_id = msg["chat"]["id"]
    if CHAT and str(chat_id) != CHAT:
        return
    text = (msg.get("text") or "").strip()
    if not text.startswith("/"):
        return
    parts = text.split(maxsplit=1)
    cmd = parts[0].split("@")[0].lower()
    arg = parts[1] if len(parts) > 1 else ""

    if cmd in ("/start", "/help"):
        send(chat_id,
             "mailbot\n\n"
             "/new [label] — alamat baru\n"
             "/list [addr|last] — inbox\n"
             "/otp [addr|last] — kode terakhir\n"
             "/read [addr|last] <id> — isi email\n\n"
             f"domain: {DOMAIN}")
    elif cmd == "/new":
        cmd_new(chat_id, arg)
    elif cmd == "/list":
        cmd_list(chat_id, arg)
    elif cmd == "/otp":
        cmd_otp(chat_id, arg)
    elif cmd == "/read":
        cmd_read(chat_id, arg)
    elif cmd == "/addr":
        a = state.get(str(chat_id), {}).get("addr")
        send(chat_id, a or "belum ada alamat")

def main():
    print("mailbot started", flush=True)
    offset = state.get("_offset")
    fails = 0
    while True:
        try:
            params = {"timeout": 25}
            if offset:
                params["offset"] = offset
            resp = requests.get(
                f"https://api.telegram.org/bot{TOKEN}/getUpdates",
                params=params, timeout=40,
            )
            r = resp.json()
            if not r.get("ok"):
                print("telegram error", r, flush=True)
                time.sleep(5)
                continue
            updates = r.get("result", [])
            if updates:
                print(f"poll: {len(updates)} update(s)", flush=True)
            for upd in updates:
                offset = upd["update_id"] + 1
                state["_offset"] = offset
                save_state(state)
                if "message" in upd:
                    handle(upd["message"])
            fails = 0
        except KeyboardInterrupt:
            break
        except Exception as e:
            fails += 1
            print(f"loop error ({fails}): {e!r}", flush=True)
            time.sleep(min(5 * fails, 30))

if __name__ == "__main__":
    main()
