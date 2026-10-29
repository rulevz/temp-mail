/**
 * Cloudflare Email Worker — inbox for *@<your-domain>
 * - stores incoming mail in KV (24h TTL)
 * - extracts OTP
 * - pushes notification to Telegram
 * - exposes a small JSON API for the bot: /messages, /message, /new
 *
 * Bindings:
 *   MAIL_KV     KV namespace
 *   TG_TOKEN    Telegram bot token
 *   TG_CHAT     Telegram chat id
 *   API_SECRET  shared secret for the bot API
 */

function json(obj, status = 200) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { "content-type": "application/json; charset=utf-8" },
  });
}

function decodeBody(body, cte) {
  cte = (cte || "").toLowerCase();
  if (cte.includes("base64")) {
    try {
      const bin = atob(body.replace(/\s+/g, ""));
      const bytes = Uint8Array.from(bin, (c) => c.charCodeAt(0));
      return new TextDecoder().decode(bytes);
    } catch {
      return body;
    }
  }
  if (cte.includes("quoted-printable")) {
    return body
      .replace(/=\r?\n/g, "")
      .replace(/=([0-9A-F]{2})/gi, (_, h) => String.fromCharCode(parseInt(h, 16)));
  }
  return body;
}

function stripHtml(s) {
  return s
    .replace(/<style[\s\S]*?<\/style>/gi, " ")
    .replace(/<script[\s\S]*?<\/script>/gi, " ")
    .replace(/<[^>]+>/g, " ")
    .replace(/&nbsp;/gi, " ")
    .replace(/&amp;/gi, "&")
    .replace(/\s+/g, " ");
}

function extractOtp(text) {
  const t = stripHtml(text || "");
  const near = t.match(/(?:code|otp|verification|verify|pin)[^0-9]{0,40}(\d{4,8})/i);
  if (near) return near[1];
  const six = t.match(/\b(\d{6})\b/);
  if (six) return six[1];
  const any = t.match(/\b(\d{4,8})\b/);
  return any ? any[1] : null;
}

function randomId(n = 6) {
  const chars = "abcdefghjkmnpqrstuvwxyz23456789";
  let out = "";
  const buf = crypto.getRandomValues(new Uint8Array(n));
  for (const b of buf) out += chars[b % chars.length];
  return out;
}

async function readRaw(message) {
  try {
    const reader = message.raw.getReader();
    const dec = new TextDecoder();
    let out = "";
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      out += dec.decode(value, { stream: true });
    }
    return out;
  } catch {
    return "";
  }
}

export default {
  async email(message, env, ctx) {
    const to = String(message.to || "").toLowerCase();
    const from = String(message.from || "");
    const subject = message.headers.get("subject") || "";
    const cte = message.headers.get("content-transfer-encoding") || "";

    const raw = await readRaw(message);
    let body = raw;
    const split = raw.indexOf("\r\n\r\n");
    if (split >= 0) body = raw.slice(split + 4);
    body = decodeBody(body, cte).slice(0, 40000);

    const otp = extractOtp(subject + "\n" + body);
    const id = randomId(8);
    const at = Date.now();
    const rec = { id, to, from, subject, otp, body, at };

    if (env.MAIL_KV) {
      await env.MAIL_KV.put(`msg:${to}:${at}:${id}`, JSON.stringify(rec), {
        expirationTtl: 86400,
      });
    }

    if (env.TG_TOKEN && env.TG_CHAT) {
      const text =
        `📧 ${to}\n` +
        `from: ${from}\n` +
        `subject: ${subject}\n` +
        (otp ? `OTP: ${otp}\n` : "") +
        `id: ${id}`;
      ctx.waitUntil(
        fetch(`https://api.telegram.org/bot${env.TG_TOKEN}/sendMessage`, {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ chat_id: env.TG_CHAT, text }),
        }).catch(() => {})
      );
    }
  },

  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname === "/health") return json({ ok: true });
    if (url.searchParams.get("secret") !== env.API_SECRET) {
      return json({ error: "forbidden" }, 403);
    }

    if (url.pathname === "/new") {
      const label = (url.searchParams.get("label") || "tmp")
        .toLowerCase()
        .replace(/[^a-z0-9-]/g, "")
        .slice(0, 20) || "tmp";
      const domain = env.MAIL_DOMAIN || "example.com";
      return json({ address: `${label}-${randomId(5)}@${domain}` });
    }

    if (url.pathname === "/debug") {
      if (!env.TG_TOKEN || !env.TG_CHAT) return json({ error: "tg env missing" }, 500);
      const r = await fetch(`https://api.telegram.org/bot${env.TG_TOKEN}/sendMessage`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          chat_id: env.TG_CHAT,
          text: "🧪 mailbot test push — worker → telegram OK",
        }),
      });
      return json({ telegram: await r.json() });
    }

    if (url.pathname === "/messages") {
      const addr = (url.searchParams.get("addr") || "").toLowerCase();
      if (!addr) return json({ error: "addr required" }, 400);
      const listed = await env.MAIL_KV.list({ prefix: `msg:${addr}:`, limit: 100 });
      const out = [];
      for (const k of listed.keys) {
        const v = await env.MAIL_KV.get(k.name);
        if (v) {
          const { body, ...meta } = JSON.parse(v);
          out.push(meta);
        }
      }
      out.sort((a, b) => b.at - a.at);
      return json({ address: addr, messages: out });
    }

    if (url.pathname === "/message") {
      const addr = (url.searchParams.get("addr") || "").toLowerCase();
      const id = url.searchParams.get("id") || "";
      if (!addr || !id) return json({ error: "addr and id required" }, 400);
      const listed = await env.MAIL_KV.list({ prefix: `msg:${addr}:`, limit: 100 });
      for (const k of listed.keys) {
        const v = await env.MAIL_KV.get(k.name);
        if (v) {
          const rec = JSON.parse(v);
          if (rec.id === id) return json(rec);
        }
      }
      return json({ error: "not found" }, 404);
    }

    return json({ error: "not found" }, 404);
  },
};
