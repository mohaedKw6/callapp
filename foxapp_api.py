#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Fox App integration layer for callv2.py.
- Token v2: per-user key + HMAC (matches foxcall/services/foxToken.ts).
- Flask HTTP API exposed for the React Native app.
- /token Telegram command that returns the encoded token to paste in the app.
"""
import os, json, time, hashlib, hmac, secrets, base64, threading, logging
from flask import Flask, request, jsonify

log = logging.getLogger("fox-app")

SHARED_SECRET = "FOXCALL_2026_SHARED_SECRET_v1"
REPLIT_API_URL = "https://3bdef2f4-6a1f-4c7d-af7c-73040d9e35ab-00-2dvjd113zga7x.sisko.replit.dev"

def _resolve_public_url() -> str:
    candidates = []
    env_url = os.environ.get("PUBLIC_URL", "").rstrip("/")
    if env_url:
        candidates.append(env_url)
    if os.environ.get("REPLIT_DEV_DOMAIN"):
        candidates.append(f"https://{os.environ['REPLIT_DEV_DOMAIN']}")
    candidates.append(REPLIT_API_URL)
    for url in candidates:
        try:
            import urllib.request
            req = urllib.request.urlopen(f"{url}/api/health", timeout=4)
            if req.status == 200:
                return url
        except Exception:
            pass
    return candidates[0] if candidates else REPLIT_API_URL

PUBLIC_URL = _resolve_public_url()
PORT = int(os.environ.get("PORT", "5000"))


# ─── Token v2 ─────────────────────────────────────────────────────────────
def _user_key(user_id) -> bytes:
    return hashlib.sha256(f"{SHARED_SECRET}:{user_id}".encode()).digest()

def _xor(data: bytes, key: bytes) -> bytes:
    return bytes(b ^ key[i % len(key)] for i, b in enumerate(data))

def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

def _b64url_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)

def encode_token(user_id, server_url: str) -> str:
    uid = str(user_id)
    nonce = secrets.token_hex(6)
    inner = f"{uid}|{server_url}|{nonce}"
    key = _user_key(uid)
    tag = hmac.new(key, inner.encode("utf-8"), hashlib.sha256).hexdigest()[:16]
    payload = f"{inner}|{tag}".encode("utf-8")
    ct = _xor(payload, key)
    return f"{uid}:{_b64url_encode(ct)}"


# ─── Helpers (lazy import of callv2 to avoid circular load) ───────────────
def _cv():
    import callv2
    return callv2

def _user_record(uid: str) -> dict:
    cv = _cv()
    rec = {}
    try:
        rec.update(cv.load_users_db().get(str(uid), {}) or {})
    except Exception:
        pass
    try:
        bd = cv.load_bot_data()
        bd_user = (bd.get("users", {}) or {}).get(str(uid), {})
        for k, v in bd_user.items():
            rec.setdefault(k, v)
        # legacy balances dict (from earlier bot.py)
        legacy = (bd.get("balances", {}) or {}).get(str(uid))
        if legacy is not None and "balance" not in rec:
            rec["balance"] = legacy
    except Exception:
        pass
    return rec

def _balance(uid: str) -> float:
    return float(_user_record(uid).get("balance", 0.0) or 0.0)

def _call_cost() -> float:
    cv = _cv()
    try:
        d = cv.load_bot_data()
        return float(d.get("settings", {}).get("call_cost", 0.20))
    except Exception:
        return 0.20

def _is_banned(uid: str) -> bool:
    cv = _cv()
    try:
        return cv.is_banned(int(uid))
    except Exception:
        try:
            banned = cv.load_banned_db()
            return str(uid) in banned
        except Exception:
            return False


# ─── Flask app ────────────────────────────────────────────────────────────
app = Flask(__name__)

@app.get("/")
def _root():
    return {"service": "Fox Call Bot", "ok": True, "url": PUBLIC_URL}

@app.get("/api/health")
def _health():
    return {"ok": True, "service": "callapp-bot", "version": "1.0.0"}

@app.get("/api/me")
def api_me():
    uid = request.headers.get("x-user-id", "").strip()
    if not uid.isdigit():
        return jsonify({"error": "missing x-user-id"}), 400
    if _is_banned(uid):
        return jsonify({"error": "banned"}), 403
    rec = _user_record(uid)
    bal = _balance(uid)
    cost = _call_cost()
    possible = int(bal // cost) if cost > 0 else 0
    return jsonify({
        "userId": uid,
        "username": rec.get("username") or "",
        "firstName": rec.get("first_name") or "",
        "fullName": (
            (rec.get("first_name") or "")
            + (" " + rec["last_name"] if rec.get("last_name") else "")
        ).strip() or rec.get("username") or uid,
        "balance": round(bal, 2),
        "cost": round(cost, 2),
        "possibleCalls": possible,
    })

@app.get("/api/balance")
def api_balance():
    uid = request.headers.get("x-user-id", "").strip()
    if not uid.isdigit():
        return jsonify({"error": "missing x-user-id"}), 400
    if _is_banned(uid):
        return jsonify({"error": "banned"}), 403
    return jsonify({"balance": _balance(uid), "cost": _call_cost()})

@app.post("/api/call/start")
def api_call_start():
    uid = request.headers.get("x-user-id", "").strip()
    if not uid.isdigit():
        return jsonify({"error": "missing x-user-id"}), 400
    if _is_banned(uid):
        return jsonify({"error": "banned"}), 403
    body = request.get_json(silent=True) or {}
    to = (body.get("to") or "").strip()
    if not to:
        return jsonify({"error": "missing 'to'"}), 400

    cv = _cv()
    cost = _call_cost()
    bal = _balance(uid)
    if bal < cost - 0.001:
        return jsonify({"error": f"رصيدك مش كافي ({bal:.2f}$). تكلفة المكالمة {cost:.2f}$"}), 402

    try:
        result = cv.start_call(to)
    except Exception as e:
        log.exception("start_call failed")
        return jsonify({"error": str(e)}), 502

    if result is None:
        return jsonify({"error": "لا يوجد حسابات Telicall متاحة أو الحسابات فشلت"}), 502
    if result == "no_balance":
        return jsonify({"error": "الحساب المستخدم لا يحتوي على رصيد"}), 502

    cv.deduct_balance(uid, cost)

    try:
        d = cv.load_bot_data()
        d.setdefault("stats", {})["total_calls"] = d.get("stats", {}).get("total_calls", 0) + 1
        cv.save_bot_data(d)
    except Exception:
        pass

    return jsonify({
        "sip": {
            "username": result.get("user", ""),
            "password": result.get("pass", ""),
            "domain": result.get("domain", ""),
            "port": result.get("port", 5060),
            "protocol": result.get("proto", "tcp"),
            "callLimit": result.get("limit", 60),
        },
        "from": result.get("from", ""),
        "to": result.get("to", to),
        "balance": _balance(uid),
    })

@app.post("/api/call/end")
def api_call_end():
    cv = _cv()
    try:
        d = cv.load_bot_data()
        d.setdefault("stats", {})["success_calls"] = d.get("stats", {}).get("success_calls", 0) + 1
        cv.save_bot_data(d)
    except Exception:
        pass
    return jsonify({"ok": True})


# ─── Telegram /token command + button ─────────────────────────────────────
def install_fox_layer(bot):
    """Wire into the running TeleBot instance: add /token command + Flask thread."""
    @bot.message_handler(commands=["token", "fox", "app"])
    def on_token(m):
        uid = m.from_user.id
        try:
            cv = _cv()
            db = cv.load_users_db()
            urec = db.get(str(uid), {})
            if not urec:
                db[str(uid)] = {
                    "first_seen": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "username": m.from_user.username or "",
                    "first_name": m.from_user.first_name or "",
                    "balance": float(cv.load_bot_data().get("settings", {}).get("default_balance", 0.0)),
                }
                cv.save_users_db(db)
        except Exception:
            pass

        tok = encode_token(uid, PUBLIC_URL)
        bal = _balance(uid)
        cost = _call_cost()
        text = (
            "🔑 *توكن تطبيق Fox Call*\n\n"
            f"`{tok}`\n\n"
            f"💰 رصيدك: *${bal:.2f}*\n"
            f"📞 تكلفة المكالمة: *${cost:.2f}*\n\n"
            "📱 افتح تطبيق Fox Call → الصق التوكن → اعمل اتصال.\n"
            "⚠️ التوكن مرتبط بحسابك. متشركوش مع حد."
        )
        bot.send_message(m.chat.id, text, parse_mode="Markdown")

    log.info("Fox app layer installed (commands: /token /fox /app).")
    _start_flask_once()


_flask_started = False
_flask_lock = threading.Lock()

def _start_flask_once():
    global _flask_started
    with _flask_lock:
        if _flask_started:
            return
        _flask_started = True
    def _run():
        log.info("Fox app Flask listening on 0.0.0.0:%d (PUBLIC_URL=%s)", PORT, PUBLIC_URL)
        try:
            app.run(host="0.0.0.0", port=PORT, threaded=True, use_reloader=False)
        except Exception as e:
            log.exception("Flask crashed: %s", e)
    threading.Thread(target=_run, daemon=True).start()
