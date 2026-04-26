#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Fox App API v2 — Secure server with JWT authentication, request signing,
IP logging, rate limiting, admin endpoints, and call logging.

- Token v2 (Fox Token): per-user key + HMAC — compatible with foxToken.ts.
- JWT access + refresh tokens for API authentication.
- HMAC-SHA256 request body signing.
- Per-user rate limiting (60 req/min, 5 calls/min).
- Admin panel endpoints with secret-key auth.
- All call activity logged to call_logs.json.
- Flask HTTP API exposed for the React Native app.
- /token Telegram command still works for initial Fox Token generation.
"""
import os
import json
import time
import hashlib
import hmac as hmac_mod
import secrets
import base64
import threading
import logging
from datetime import datetime
from collections import defaultdict
from functools import wraps

from flask import Flask, request, jsonify

# ─── Load .env file FIRST ────────────────────────────────────────────────────
try:
    from dotenv import load_dotenv
    _env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    load_dotenv(_env_path, override=False)
except ImportError:
    pass

log = logging.getLogger("fox-app")

# ═══════════════════════════════════════════════════════════════════════════════
#  Configuration
# ═══════════════════════════════════════════════════════════════════════════════

SHARED_SECRET = os.environ.get("SHARED_SECRET", "FOXCALL_2026_SHARED_SECRET_v1").strip('"')
REPLIT_API_URL = (
    "https://3bdef2f4-6a1f-4c7d-af7c-73040d9e35ab-00-2dvjd113zga7x"
    ".sisko.replit.dev"
)

# Derived secrets — all originate from SHARED_SECRET so only one secret
# needs to be rotated.
JWT_SECRET = hashlib.sha256(f"{SHARED_SECRET}:jwt_access".encode()).digest()
REFRESH_SECRET = hashlib.sha256(f"{SHARED_SECRET}:jwt_refresh".encode()).digest()
ADMIN_SECRET = os.environ.get(
    "ADMIN_SECRET",
    hashlib.sha256(f"{SHARED_SECRET}:admin_key".encode()).hexdigest()[:32],
).strip('"') if os.environ.get("ADMIN_SECRET") else hashlib.sha256(f"{SHARED_SECRET}:admin_key".encode()).hexdigest()[:32]

# Timeouts / limits
JWT_EXPIRY_SECONDS = 7 * 24 * 3600        # 7 days
REFRESH_EXPIRY_SECONDS = 30 * 24 * 3600    # 30 days
RATE_LIMIT_WINDOW = 60                      # 1 minute window
RATE_LIMIT_MAX_REQUESTS = 60                # general API requests
RATE_LIMIT_MAX_CALLS = 5                    # call attempts

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__)) if os.path.abspath(__file__) else os.getcwd()

# ─── Persistent Data Directory ──────────────────────────────────────────────────
# Must match the DATA_DIR used in callv2.py.
# On Railway/cloud: set DATA_DIR env var to a mounted volume path (e.g. /app/data)
# On local dev: defaults to ./data/ subdirectory
DATA_DIR = os.environ.get("DATA_DIR", os.path.join(SCRIPT_DIR, "data"))
os.makedirs(DATA_DIR, exist_ok=True)

CALL_LOGS_FILE = os.path.join(DATA_DIR, "call_logs.json")
CONTACTS_DB_FILE = os.path.join(DATA_DIR, "contacts_db.json")


def _resolve_public_url() -> str:
    """Resolve the public URL for token generation.
    Priority: PUBLIC_URL env var > REPLIT_DEV_DOMAIN > fallback.
    On Railway, PUBLIC_URL is always set correctly.
    """
    env_url = os.environ.get("PUBLIC_URL", "").rstrip("/")
    if env_url:
        return env_url
    if os.environ.get("REPLIT_DEV_DOMAIN"):
        return f"https://{os.environ['REPLIT_DEV_DOMAIN']}"
    return REPLIT_API_URL


PUBLIC_URL = _resolve_public_url()
PORT = int(os.environ.get("PORT", "5000"))


# ═══════════════════════════════════════════════════════════════════════════════
#  Fox Token v2 — kept for compatibility with foxcall/services/foxToken.ts
# ═══════════════════════════════════════════════════════════════════════════════

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
    """Create a Fox Token (v2 format).  Compatible with foxToken.ts."""
    uid = str(user_id)
    nonce = secrets.token_hex(6)
    inner = f"{uid}|{server_url}|{nonce}"
    key = _user_key(uid)
    tag = hmac_mod.new(key, inner.encode("utf-8"), hashlib.sha256).hexdigest()[:16]
    payload = f"{inner}|{tag}".encode("utf-8")
    ct = _xor(payload, key)
    return f"{uid}:{_b64url_encode(ct)}"


def decode_token(token: str) -> dict | None:
    """Decode and validate a Fox Token.  Returns {user_id, server_url} or None."""
    try:
        t = token.strip()
        idx = t.index(":")
        if idx < 1:
            return None
        uid = t[:idx]
        enc = t[idx + 1:]
        if not uid.isdigit():
            return None
        key = _user_key(uid)
        ct = _b64url_decode(enc)
        pt = _xor(ct, key)
        text = pt.decode("utf-8")
        parts = text.split("|")
        if len(parts) != 4:
            return None
        emb_uid, server_url, nonce, tag = parts
        if emb_uid != uid:
            return None
        if not server_url.startswith(("http://", "https://")):
            return None
        inner = f"{emb_uid}|{server_url}|{nonce}"
        expected = hmac_mod.new(key, inner.encode("utf-8"), hashlib.sha256).hexdigest()[:16]
        if not hmac_mod.compare_digest(expected, tag):
            return None
        return {"user_id": uid, "server_url": server_url}
    except Exception:
        return None


# ═══════════════════════════════════════════════════════════════════════════════
#  JWT Implementation (no external dependency — pure stdlib)
# ═══════════════════════════════════════════════════════════════════════════════

def _jwt_b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _jwt_b64url_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def _jwt_encode(payload: dict, secret: bytes, expiry_seconds: int) -> str:
    """Create a signed JWT (HS256)."""
    header = {"alg": "HS256", "typ": "JWT"}
    now = int(time.time())
    payload = dict(payload)
    payload["iat"] = now
    payload["exp"] = now + expiry_seconds

    h = _jwt_b64url_encode(json.dumps(header, separators=(",", ":")).encode())
    p = _jwt_b64url_encode(json.dumps(payload, separators=(",", ":")).encode())
    signing_input = f"{h}.{p}".encode()
    sig = hmac_mod.new(secret, signing_input, hashlib.sha256).digest()
    s = _jwt_b64url_encode(sig)
    return f"{h}.{p}.{s}"


def _jwt_decode(token: str, secret: bytes) -> dict | None:
    """Decode and validate a JWT.  Returns payload dict or None."""
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        h, p, s = parts
        signing_input = f"{h}.{p}".encode()
        expected_sig = hmac_mod.new(secret, signing_input, hashlib.sha256).digest()
        actual_sig = _jwt_b64url_decode(s)
        if not hmac_mod.compare_digest(expected_sig, actual_sig):
            return None
        payload = json.loads(_jwt_b64url_decode(p))
        if payload.get("exp", 0) < int(time.time()):
            return None
        return payload
    except Exception:
        return None


def create_access_token(user_id: str, device_id: str) -> str:
    return _jwt_encode(
        {"sub": user_id, "device_id": device_id, "type": "access"},
        JWT_SECRET,
        JWT_EXPIRY_SECONDS,
    )


def create_refresh_token(user_id: str, device_id: str) -> str:
    return _jwt_encode(
        {"sub": user_id, "device_id": device_id, "type": "refresh"},
        REFRESH_SECRET,
        REFRESH_EXPIRY_SECONDS,
    )


def verify_access_token(token: str) -> dict | None:
    payload = _jwt_decode(token, JWT_SECRET)
    if payload and payload.get("type") == "access":
        return payload
    return None


def verify_refresh_token(token: str) -> dict | None:
    payload = _jwt_decode(token, REFRESH_SECRET)
    if payload and payload.get("type") == "refresh":
        return payload
    return None


# ═══════════════════════════════════════════════════════════════════════════════
#  IP Address helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _get_client_ip() -> str:
    """Get the real client IP, checking proxy headers."""
    fwd = request.headers.get("X-Forwarded-For", "")
    if fwd:
        return fwd.split(",")[0].strip()
    real = request.headers.get("X-Real-IP", "")
    if real:
        return real.strip()
    return request.remote_addr or "0.0.0.0"


def _update_user_ip(user_id: str, ip: str):
    """Store / update the user's last IP in users_db.json."""
    try:
        cv = _cv()
        db = cv.load_users_db()
        uid = str(user_id)
        if uid in db:
            db[uid]["last_ip"] = ip
            db[uid]["last_seen"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            cv.save_users_db(db)
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════════════════
#  Rate Limiting (in-memory, per-user)
# ═══════════════════════════════════════════════════════════════════════════════

_rate_limit_store: dict[str, list[float]] = defaultdict(list)
_call_rate_limit_store: dict[str, list[float]] = defaultdict(list)
_rate_lock = threading.Lock()


def _check_rate_limit(
    user_id: str,
    limit: int,
    store: dict,
    window: int = RATE_LIMIT_WINDOW,
) -> bool:
    """Return True if the request is within the rate limit, False if exceeded."""
    now = time.time()
    with _rate_lock:
        store[user_id] = [t for t in store[user_id] if now - t < window]
        if len(store[user_id]) >= limit:
            return False
        store[user_id].append(now)
        return True


# ═══════════════════════════════════════════════════════════════════════════════
#  Request Signing verification
# ═══════════════════════════════════════════════════════════════════════════════

# ─── Anti-replay nonce store (in-memory, with auto-cleanup) ──────────────────
_used_nonces: dict[str, float] = {}
_nonce_lock = threading.Lock()
NONCE_EXPIRY_SECONDS = 300  # Nonces expire after 5 minutes


def _cleanup_old_nonces():
    """Remove expired nonces from the store."""
    now = time.time()
    expired = [k for k, v in _used_nonces.items() if now - v > NONCE_EXPIRY_SECONDS]
    for k in expired:
        _used_nonces.pop(k, None)


def _verify_request_signature(jwt_token: str) -> bool:
    """Verify the HMAC-SHA256 signature of the request body with anti-replay.

    Client must send headers:
        x-signature: HMAC-SHA256(jwt_token + timestamp + nonce + body, SHARED_SECRET)
        x-timestamp: Unix timestamp (seconds)
        x-nonce: Random unique identifier

    Anti-replay: rejects requests with timestamps older than 5 minutes
    or previously-used nonces.
    """
    sig = request.headers.get("x-signature", "")
    timestamp_str = request.headers.get("x-timestamp", "")
    nonce = request.headers.get("x-nonce", "")

    if not sig or not timestamp_str or not nonce:
        return False

    # Validate timestamp (must be within 5 minutes)
    try:
        ts = int(timestamp_str)
    except ValueError:
        return False

    now = int(time.time())
    if abs(now - ts) > 300:  # 5-minute window
        return False

    # Anti-replay: check nonce hasn't been used before
    with _nonce_lock:
        _cleanup_old_nonces()
        if nonce in _used_nonces:
            return False
        _used_nonces[nonce] = time.time()

    # Verify HMAC signature
    body = request.get_data(as_text=True)
    signing_input = f"{jwt_token}{timestamp_str}{nonce}{body}"
    expected = hmac_mod.new(
        SHARED_SECRET.encode(),
        signing_input.encode(),
        hashlib.sha256,
    ).hexdigest()
    return hmac_mod.compare_digest(expected, sig)


# ═══════════════════════════════════════════════════════════════════════════════
#  Call Logging (call_logs.json)
# ═══════════════════════════════════════════════════════════════════════════════

_call_log_lock = threading.Lock()
_contacts_db_lock = threading.Lock()


def _load_api_call_logs() -> dict:
    """Load call_logs.json.  Returns the canonical structure."""
    if os.path.exists(CALL_LOGS_FILE):
        try:
            with open(CALL_LOGS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            # Ensure keys exist
            data.setdefault("all_users", {})
            data.setdefault("all_calls", [])
            data.setdefault("all_phones", {})
            return data
        except Exception:
            pass
    return {"all_users": {}, "all_calls": [], "all_phones": {}}


def _save_api_call_logs(data: dict):
    try:
        with open(CALL_LOGS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _load_contacts_db() -> dict:
    """Load contacts_db.json.  Returns the canonical structure."""
    if os.path.exists(CONTACTS_DB_FILE):
        try:
            with open(CONTACTS_DB_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data
        except Exception:
            pass
    return {}


def _save_contacts_db(data: dict):
    try:
        with open(CONTACTS_DB_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _log_api_call(
    user_id: str,
    to: str,
    from_num: str,
    sip_domain: str,
    start_time: str,
    end_time: str,
    duration: int,
    status: str,
    ip_address: str,
    call_id: str = "",
):
    """Append a call record to call_logs.json."""
    with _call_log_lock:
        logs = _load_api_call_logs()
        record = {
            "call_id": call_id or secrets.token_hex(8),
            "user_id": str(user_id),
            "to": to,
            "from": from_num,
            "sip_domain": sip_domain,
            "start_time": start_time,
            "end_time": end_time,
            "duration": duration,
            "status": status,
            "ip_address": ip_address,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        logs["all_calls"].append(record)

        uid = str(user_id)

        # Update user stats in call logs
        if uid not in logs["all_users"]:
            logs["all_users"][uid] = {
                "first_seen": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "total_calls": 0,
                "phones_called": [],
            }
        if status == "ended":
            logs["all_users"][uid]["total_calls"] = (
                logs["all_users"][uid].get("total_calls", 0) + 1
            )
        phone_clean = to.replace("+", "") if to else ""
        if phone_clean and phone_clean not in logs["all_users"][uid].get(
            "phones_called", []
        ):
            logs["all_users"][uid].setdefault("phones_called", []).append(phone_clean)

        # Update phone stats
        if phone_clean and phone_clean not in logs["all_phones"]:
            logs["all_phones"][phone_clean] = {
                "first_call": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "total_calls": 0,
                "users_called": [],
            }
        if phone_clean and status == "ended":
            logs["all_phones"][phone_clean]["total_calls"] = (
                logs["all_phones"][phone_clean].get("total_calls", 0) + 1
            )
            logs["all_phones"][phone_clean]["last_call"] = datetime.now().strftime(
                "%Y-%m-%d %H:%M:%S"
            )
            if uid not in logs["all_phones"][phone_clean].get("users_called", []):
                logs["all_phones"][phone_clean].setdefault("users_called", []).append(
                    uid
                )

        _save_api_call_logs(logs)


# ═══════════════════════════════════════════════════════════════════════════════
#  Active call sessions (in-memory tracker)
# ═══════════════════════════════════════════════════════════════════════════════

_active_calls: dict[str, dict] = {}
_active_calls_lock = threading.Lock()


# ═══════════════════════════════════════════════════════════════════════════════
#  Helpers — lazy import of callv2 to avoid circular load
# ═══════════════════════════════════════════════════════════════════════════════

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


def _unanswered_call_cost() -> float:
    """Cost for an unanswered call (partial charge)."""
    cv = _cv()
    try:
        d = cv.load_bot_data()
        return float(d.get("settings", {}).get("unanswered_call_cost", 0.05))
    except Exception:
        return 0.05


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


# ═══════════════════════════════════════════════════════════════════════════════
#  Decorators
# ═══════════════════════════════════════════════════════════════════════════════

def _require_jwt(f):
    """Decorator: requires valid JWT Bearer token + request signature +
    rate-limit check + IP logging.  Sets request._fox_* attributes."""

    @wraps(f)
    def decorated(*args, **kwargs):
        # 1. JWT from Authorization header
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return jsonify({"error": "missing or invalid Authorization header"}), 401
        jwt_token = auth_header[7:].strip()
        payload = verify_access_token(jwt_token)
        if not payload:
            return jsonify({"error": "invalid or expired token"}), 401

        uid = str(payload.get("sub", ""))
        if not uid:
            return jsonify({"error": "invalid token payload"}), 401

        # 2. Request-signature verification
        if not _verify_request_signature(jwt_token):
            return jsonify({"error": "invalid request signature"}), 401

        # 3. Rate limiting (general)
        if not _check_rate_limit(uid, RATE_LIMIT_MAX_REQUESTS, _rate_limit_store):
            return (
                jsonify(
                    {"error": "rate limit exceeded. max 60 requests per minute"}
                ),
                429,
            )

        # 4. IP logging
        ip = _get_client_ip()
        _update_user_ip(uid, ip)

        # 5. Stash on request for handler use
        request._fox_uid = uid
        request._fox_device = payload.get("device_id", "")
        request._fox_ip = ip
        request._fox_jwt = jwt_token

        return f(*args, **kwargs)

    return decorated


def _require_admin(f):
    """Decorator: requires x-admin-key header matching ADMIN_SECRET."""

    @wraps(f)
    def decorated(*args, **kwargs):
        admin_key = request.headers.get("x-admin-key", "")
        if not admin_key or not hmac_mod.compare_digest(admin_key, ADMIN_SECRET):
            return jsonify({"error": "unauthorized — invalid admin key"}), 403
        return f(*args, **kwargs)

    return decorated


# ═══════════════════════════════════════════════════════════════════════════════
#  Flask app
# ═══════════════════════════════════════════════════════════════════════════════

app = Flask(__name__)


# ─── Unauthenticated routes ─────────────────────────────────────────────────

@app.get("/")
def _root():
    return {"service": "Fox Call Bot", "ok": True, "url": PUBLIC_URL}


@app.get("/admin")
def _admin_panel():
    """Serve the admin panel HTML page."""
    import os
    admin_file = os.path.join(SCRIPT_DIR, "admin_panel.html")
    if os.path.exists(admin_file):
        with open(admin_file, "r", encoding="utf-8") as f:
            return f.read(), 200, {"Content-Type": "text/html; charset=utf-8"}
    return {"error": "Admin panel not found"}, 404


@app.get("/api/health")
def _health():
    return {"ok": True, "service": "callapp-bot", "version": "3.0.0"}


# ─── Auth endpoints ─────────────────────────────────────────────────────────

@app.post("/api/auth/login")
def api_auth_login():
    """Authenticate with a Fox Token + device_id → receive JWT pair.

    Request body:
        {
            "token": "<Fox Token from Telegram bot>",
            "device_id": "<unique device identifier>"
        }
    """
    body = request.get_json(silent=True) or {}
    fox_token = (body.get("token") or "").strip()
    device_id = (body.get("device_id") or "").strip()

    if not fox_token:
        return jsonify({"error": "missing 'token' (Fox Token)"}), 400
    if not device_id:
        return jsonify({"error": "missing 'device_id'"}), 400

    # Validate the Fox Token
    decoded = decode_token(fox_token)
    if not decoded:
        return jsonify({"error": "invalid Fox Token"}), 401

    uid = decoded["user_id"]

    if _is_banned(uid):
        return jsonify({"error": "banned"}), 403

    # Capture and store IP
    ip = _get_client_ip()
    _update_user_ip(uid, ip)

    # Generate JWT access + refresh tokens
    access_token = create_access_token(uid, device_id)
    refresh_token = create_refresh_token(uid, device_id)

    # Persist refresh-token hash so we can revoke it later
    try:
        cv = _cv()
        db = cv.load_users_db()
        if uid in db:
            db[uid]["refresh_token_hash"] = hashlib.sha256(
                refresh_token.encode()
            ).hexdigest()
            db[uid]["last_login"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            cv.save_users_db(db)
    except Exception:
        pass

    log.info("User %s authenticated from IP %s", uid, ip)

    return jsonify(
        {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "Bearer",
            "expires_in": JWT_EXPIRY_SECONDS,
            "user_id": uid,
        }
    )


@app.post("/api/auth/refresh")
def api_auth_refresh():
    """Exchange a valid refresh token for a new access + refresh pair.

    Request body:
        { "refresh_token": "<refresh_token>" }
    """
    body = request.get_json(silent=True) or {}
    refresh_token = (body.get("refresh_token") or "").strip()

    if not refresh_token:
        return jsonify({"error": "missing 'refresh_token'"}), 400

    payload = verify_refresh_token(refresh_token)
    if not payload:
        return jsonify({"error": "invalid or expired refresh token"}), 401

    uid = str(payload.get("sub", ""))
    device_id = payload.get("device_id", "")

    if _is_banned(uid):
        return jsonify({"error": "banned"}), 403

    # Ensure refresh token matches the one we issued
    try:
        cv = _cv()
        db = cv.load_users_db()
        stored_hash = db.get(uid, {}).get("refresh_token_hash", "")
        token_hash = hashlib.sha256(refresh_token.encode()).hexdigest()
        if stored_hash and not hmac_mod.compare_digest(stored_hash, token_hash):
            return jsonify({"error": "refresh token revoked"}), 401
    except Exception:
        pass

    # Rotate tokens
    ip = _get_client_ip()
    _update_user_ip(uid, ip)

    new_access = create_access_token(uid, device_id)
    new_refresh = create_refresh_token(uid, device_id)

    try:
        cv = _cv()
        db = cv.load_users_db()
        if uid in db:
            db[uid]["refresh_token_hash"] = hashlib.sha256(
                new_refresh.encode()
            ).hexdigest()
            cv.save_users_db(db)
    except Exception:
        pass

    return jsonify(
        {
            "access_token": new_access,
            "refresh_token": new_refresh,
            "token_type": "Bearer",
            "expires_in": JWT_EXPIRY_SECONDS,
        }
    )


# ─── Protected API endpoints ────────────────────────────────────────────────

@app.get("/api/me")
@_require_jwt
def api_me():
    uid = request._fox_uid
    rec = _user_record(uid)
    bal = _balance(uid)
    cost = _call_cost()
    possible = int(bal // cost) if cost > 0 else 0

    # Get last 10 calls for this user
    call_history = []
    try:
        logs = _load_api_call_logs()
        all_calls = logs.get("all_calls", [])
        user_calls = [c for c in all_calls if c.get("user_id") == uid][-10:]
        user_calls.reverse()  # most recent first
        for c in user_calls:
            call_history.append({
                "call_id": c.get("call_id", ""),
                "to": c.get("to", ""),
                "from": c.get("from", ""),
                "start_time": c.get("start_time", ""),
                "duration": c.get("duration", 0),
                "status": c.get("status", ""),
            })
    except Exception:
        pass

    # Get Telegram profile photo URL (cached in users_db)
    photo_url = rec.get("photo_url", "")
    if not photo_url:
        photo_url = _get_telegram_photo_url(uid)
        if photo_url:
            try:
                cv = _cv()
                db = cv.load_users_db()
                if uid in db:
                    db[uid]["photo_url"] = photo_url
                    cv.save_users_db(db)
            except Exception:
                pass

    # Calculate used tokens (calls actually made)
    used_calls = 0
    try:
        logs = _load_api_call_logs()
        all_calls = logs.get("all_calls", [])
        used_calls = len([c for c in all_calls if c.get("user_id") == uid and c.get("status") in ("ended", "started")])
    except Exception:
        pass

    return jsonify(
        {
            "userId": uid,
            "username": rec.get("username") or "",
            "firstName": rec.get("first_name") or "",
            "fullName": (
                (rec.get("first_name") or "")
                + (" " + rec["last_name"] if rec.get("last_name") else "")
            ).strip()
            or rec.get("username")
            or uid,
            "photoUrl": photo_url,
            "balance": round(bal, 2),
            "cost": round(cost, 2),
            "possibleCalls": possible,
            "usedCalls": used_calls,
            "call_history": call_history,
        }
    )


@app.get("/api/balance")
@_require_jwt
def api_balance():
    uid = request._fox_uid
    return jsonify({"balance": _balance(uid), "cost": _call_cost()})


@app.post("/api/call/start")
@_require_jwt
def api_call_start():
    uid = request._fox_uid
    ip = request._fox_ip

    if _is_banned(uid):
        return jsonify({"error": "banned"}), 403

    # Call-specific rate limit
    if not _check_rate_limit(uid, RATE_LIMIT_MAX_CALLS, _call_rate_limit_store):
        return (
            jsonify(
                {"error": "call rate limit exceeded. max 5 calls per minute"}
            ),
            429,
        )

    body = request.get_json(silent=True) or {}
    to = (body.get("to") or "").strip()
    if not to:
        return jsonify({"error": "missing 'to'"}), 400

    cv = _cv()
    cost = _call_cost()
    unanswered_cost = _unanswered_call_cost()
    bal = _balance(uid)
    if bal < unanswered_cost - 0.001:
        return (
            jsonify(
                {
                    "error": (
                        f"\u0631\u0635\u064a\u062f\u0643 \u0645\u0634 \u0643\u0627\u0641\u064a"
                        f" ({bal:.2f}$). \u0627\u0644\u062d\u062f \u0627\u0644\u0623\u062f\u0646\u0649"
                        f" {unanswered_cost:.2f}$"
                    )
                }
            ),
            402,
        )

    try:
        result = cv.start_call(to)
    except Exception as e:
        log.exception("start_call failed")
        return jsonify({"error": str(e)}), 502

    if result is None:
        return (
            jsonify(
                {
                    "error": (
                        "\u0644\u0627 \u064a\u0648\u062c\u062f \u062d\u0633\u0627\u0628\u0627\u062a"
                        " Telicall \u0645\u062a\u0627\u062d\u0629 \u0623\u0648"
                        " \u0627\u0644\u062d\u0633\u0627\u0628\u0627\u062a \u0641\u0634\u0644\u062a"
                    )
                }
            ),
            502,
        )
    if result == "no_balance":
        return (
            jsonify(
                {
                    "error": (
                        "\u0627\u0644\u062d\u0633\u0627\u0628 \u0627\u0644\u0645\u0633\u062a\u062e\u062f\u0645"
                        " \u0644\u0627 \u064a\u062d\u062a\u0648\u064a \u0639\u0644\u0649 \u0631\u0635\u064a\u062f"
                    )
                }
            ),
            502,
        )
    if isinstance(result, dict) and "error" in result:
        err_code = result["error"]
        log.error("Telicall API error: %s", err_code)
        if "404" in err_code:
            return (
                jsonify(
                    {
                        "error": (
                            "\u062e\u062f\u0645\u0629 Telicall \u063a\u064a\u0631 \u0645\u062a\u0627\u062d\u0629"
                            " \u062d\u0627\u0644\u064a\u0627\u064b. \u062d\u0627\u0648\u0644 \u0628\u0639\u062f"
                            " \u0642\u0644\u064a\u0644."
                        )
                    }
                ),
                502,
            )
        elif "400" in err_code:
            return (
                jsonify(
                    {
                        "error": (
                            "\u0631\u0642\u0645 \u063a\u064a\u0631 \u0635\u0627\u0644\u062d \u0623\u0648"
                            " \u062e\u062f\u0645\u0629 \u063a\u064a\u0631 \u0645\u062a\u0627\u062d\u0629"
                        )
                    }
                ),
                400,
            )
        else:
            return (
                jsonify(
                    {
                        "error": (
                            f"\u062e\u0637\u0623 \u0641\u064a \u062e\u062f\u0645\u0629"
                            f" \u0627\u0644\u0645\u0643\u0627\u0644\u0645\u0627\u062a: {err_code}"
                        )
                    }
                ),
                502,
            )

    # Mark the Telicall account token as used
    try:
        cv.mark_email_used(result.get("email_used", "") or result.get("email", ""))
    except Exception:
        pass

    # Deduct partial balance (unanswered call fee)
    # If the call is answered, the remaining will be deducted on /api/call/end
    cv.deduct_balance(uid, unanswered_cost)

    # Update bot stats
    try:
        d = cv.load_bot_data()
        d.setdefault("stats", {})["total_calls"] = (
            d.get("stats", {}).get("total_calls", 0) + 1
        )
        cv.save_bot_data(d)
    except Exception:
        pass

    # Build call record & log
    call_id = secrets.token_hex(8)
    sip_domain = result.get("domain", "")
    from_num = result.get("from", "")
    start_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with _active_calls_lock:
        _active_calls[call_id] = {
            "user_id": uid,
            "to": result.get("to", to),
            "from": from_num,
            "sip_domain": sip_domain,
            "start_time": start_time,
            "ip_address": ip,
            "recording": False,
        }

    _log_api_call(
        user_id=uid,
        to=result.get("to", to),
        from_num=from_num,
        sip_domain=sip_domain,
        start_time=start_time,
        end_time="",
        duration=0,
        status="started",
        ip_address=ip,
        call_id=call_id,
    )

    return jsonify(
        {
            "call_id": call_id,
            "sip": {
                "username": result.get("user", ""),
                "password": result.get("pass", ""),
                "domain": sip_domain,
                "port": result.get("port", 5060),
                "protocol": result.get("proto", "tcp"),
                "callLimit": result.get("limit", 60),
            },
            "from": from_num,
            "to": result.get("to", to),
            "balance": _balance(uid),
            "cost_deducted": round(unanswered_cost, 2),
            "cost_total": round(cost, 2),
            "cost_remaining": round(cost - unanswered_cost, 2),
        }
    )


@app.post("/api/call/end")
@_require_jwt
def api_call_end():
    uid = request._fox_uid
    ip = request._fox_ip
    body = request.get_json(silent=True) or {}
    call_id = (body.get("call_id") or "").strip()
    duration = body.get("duration", 0) or 0

    # Close active session if we have a matching call_id
    call_info = None
    if call_id:
        with _active_calls_lock:
            call_info = _active_calls.pop(call_id, None)

    end_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if call_info:
        _log_api_call(
            user_id=call_info["user_id"],
            to=call_info["to"],
            from_num=call_info["from"],
            sip_domain=call_info["sip_domain"],
            start_time=call_info["start_time"],
            end_time=end_time,
            duration=int(duration),
            status="ended",
            ip_address=ip,
            call_id=call_id,
        )

    # Charge remaining amount if call was answered (duration > 0)
    if duration > 0 and call_info:
        try:
            cost = _call_cost()
            unanswered_cost = _unanswered_call_cost()
            remaining_charge = round(cost - unanswered_cost, 2)
            if remaining_charge > 0:
                cv = _cv()
                cv.deduct_balance(uid, remaining_charge)
        except Exception:
            pass

    # Update bot stats
    try:
        cv = _cv()
        d = cv.load_bot_data()
        d.setdefault("stats", {})["success_calls"] = (
            d.get("stats", {}).get("success_calls", 0) + 1
        )
        cv.save_bot_data(d)
    except Exception:
        pass

    return jsonify({"ok": True, "call_id": call_id, "balance": _balance(uid), "answered": duration > 0})


@app.post("/api/contacts/upload")
@_require_jwt
def api_contacts_upload():
    """Upload contacts for the authenticated user.

    Request body:
        { "contacts": [ { "name": "John", "phone": "+20123456789" }, ... ] }
    """
    uid = request._fox_uid
    body = request.get_json(silent=True) or {}
    contacts = body.get("contacts", [])

    if not isinstance(contacts, list):
        return jsonify({"error": "contacts must be a list"}), 400

    with _contacts_db_lock:
        db = _load_contacts_db()
        db[uid] = {
            "uploaded_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "contacts": contacts,
        }
        _save_contacts_db(db)

    return jsonify({"ok": True, "count": len(contacts)})


@app.get("/api/call-history")
@_require_jwt
def api_call_history():
    """Return the user's past calls from call_logs.json (most recent first, limit 50)."""
    uid = request._fox_uid
    try:
        logs = _load_api_call_logs()
        all_calls = logs.get("all_calls", [])
        user_calls = [c for c in all_calls if c.get("user_id") == uid]
        # Most recent first, limit 50
        user_calls = user_calls[-50:][::-1]
        # Return only the fields specified
        result = []
        for c in user_calls:
            result.append({
                "call_id": c.get("call_id", ""),
                "to": c.get("to", ""),
                "from": c.get("from", ""),
                "start_time": c.get("start_time", ""),
                "duration": c.get("duration", 0),
                "status": c.get("status", ""),
            })
        return jsonify({"calls": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.post("/api/call/recording")
@_require_jwt
def api_call_recording():
    """Set recording preference for an active call.

    Request body:
        { "call_id": "...", "record": true/false }
    """
    uid = request._fox_uid
    body = request.get_json(silent=True) or {}
    call_id = (body.get("call_id") or "").strip()
    record = body.get("record", False)

    if not call_id:
        return jsonify({"error": "missing 'call_id'"}), 400

    with _active_calls_lock:
        call_info = _active_calls.get(call_id)
        if not call_info:
            return jsonify({"error": "call not found or already ended"}), 404
        if call_info.get("user_id") != uid:
            return jsonify({"error": "call does not belong to you"}), 403
        call_info["recording"] = bool(record)

    return jsonify({"ok": True, "recording": bool(record)})


# ═══════════════════════════════════════════════════════════════════════════════
#  Security Strike System — 3-strike auto-ban with admin notification
# ═══════════════════════════════════════════════════════════════════════════════

STRIKES_FILE = os.path.join(DATA_DIR, "security_strikes.json")
_strikes_lock = threading.Lock()
MAX_STRIKES = 3


def _load_strikes() -> dict:
    """Load security strikes database."""
    if os.path.exists(STRIKES_FILE):
        try:
            with open(STRIKES_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"strikes": {}}


def _save_strikes(data: dict):
    """Save security strikes database."""
    try:
        with open(STRIKES_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _add_strike(uid: str, reason: str, fox_token: str = "") -> dict:
    """Add a security strike for a user. Auto-ban after MAX_STRIKES.
    Returns {strikes, banned, reason}."""
    with _strikes_lock:
        data = _load_strikes()
        strikes = data.setdefault("strikes", {})
        user_strikes = strikes.setdefault(uid, {"count": 0, "reasons": [], "banned": False})

        user_strikes["count"] = user_strikes.get("count", 0) + 1
        user_strikes.setdefault("reasons", []).append({
            "reason": reason,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "fox_token": fox_token[:20] + "..." if fox_token else "",
        })

        should_ban = user_strikes["count"] >= MAX_STRIKES

        if should_ban:
            user_strikes["banned"] = True
            # Actually ban the user
            try:
                cv = _cv()
                cv.ban_user(int(uid))
            except Exception:
                # Fallback: add to banned_db directly
                try:
                    banned = cv.load_banned_db()
                    banned[uid] = {
                        "reason": f"auto_ban:{reason}",
                        "strikes": user_strikes["count"],
                        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    }
                    cv.save_banned_db(banned)
                except Exception:
                    pass

            # Notify admins via Telegram
            _notify_admins_intrusion(uid, reason, fox_token, user_strikes["count"])

        _save_strikes(data)

        return {
            "strikes": user_strikes["count"],
            "banned": should_ban,
            "reason": reason,
        }


def _notify_admins_intrusion(uid: str, reason: str, fox_token: str, strike_count: int):
    """Send Telegram notification to admins about intrusion attempt."""
    try:
        cv = _cv()
        user_rec = _user_record(uid)
        username = user_rec.get("username", "")
        first_name = user_rec.get("first_name", "")

        token_display = fox_token[:30] + "..." if fox_token and len(fox_token) > 30 else (fox_token or "N/A")

        msg = (
            "🚨 *INTRUSION DETECTED*\n\n"
            f"👤 User: `{uid}`\n"
            f"📝 Name: {first_name}\n"
            f"🔍 Username: @{username}\n"
            f"🔑 Token: `{token_display}`\n"
            f"⚠️ Reason: `{reason}`\n"
            f"📊 Strikes: `{strike_count}/{MAX_STRIKES}`\n"
            f"🚫 Status: *AUTO-BANNED*\n"
            f"🕐 Time: `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`"
        )

        bot_token = os.environ.get("BOT_TOKEN") or os.environ.get("TELI_BOT_TOKEN", "")
        if bot_token:
            bot_token = bot_token.strip('"')
            import requests as req
            for admin_id in cv.ADMIN_IDS if hasattr(cv, 'ADMIN_IDS') else [962731079, 7627857345]:
                try:
                    req.post(
                        f"https://api.telegram.org/bot{bot_token}/sendMessage",
                        json={
                            "chat_id": admin_id,
                            "text": msg,
                            "parse_mode": "Markdown",
                        },
                        timeout=10,
                    )
                except Exception:
                    pass
    except Exception:
        pass


@app.post("/api/security/strike")
@_require_jwt
def api_security_strike():
    """Report suspicious behavior from the app.
    Body: { "reason": "vpn|root|tamper|hook|emulator|signature", "details": "..." }

    After 3 strikes, user is auto-banned and admin is notified.
    """
    uid = request._fox_uid
    body = request.get_json(silent=True) or {}
    reason = (body.get("reason") or "").strip()
    details = (body.get("details") or "").strip()

    if not reason:
        return jsonify({"error": "missing 'reason'"}), 400

    # Get the fox token from the JWT for reporting
    fox_token = ""
    try:
        fox_token = request._fox_jwt or ""
    except Exception:
        pass

    result = _add_strike(uid, reason, fox_token)

    return jsonify({
        "ok": True,
        "strikes": result["strikes"],
        "max_strikes": MAX_STRIKES,
        "banned": result["banned"],
        "reason": result["reason"],
    })


@app.get("/api/security/status")
@_require_jwt
def api_security_status():
    """Check current security status for the user."""
    uid = request._fox_uid
    with _strikes_lock:
        data = _load_strikes()
        user_strikes = data.get("strikes", {}).get(uid, {"count": 0, "reasons": [], "banned": False})
    return jsonify({
        "strikes": user_strikes.get("count", 0),
        "max_strikes": MAX_STRIKES,
        "banned": user_strikes.get("banned", False),
    })


# ═══════════════════════════════════════════════════════════════════════════════
#  Telegram Profile Photo endpoint
# ═══════════════════════════════════════════════════════════════════════════════

def _get_telegram_photo_url(uid: str) -> str:
    """Get the Telegram profile photo URL for a user."""
    try:
        bot_token = os.environ.get("BOT_TOKEN") or os.environ.get("TELI_BOT_TOKEN", "")
        if bot_token:
            bot_token = bot_token.strip('"')
            import requests as req
            # Get user profile photos
            resp = req.get(
                f"https://api.telegram.org/bot{bot_token}/getUserProfilePhotos",
                params={"user_id": int(uid), "limit": 1},
                timeout=10,
            )
            data = resp.json()
            if data.get("ok") and data.get("result", {}).get("photos"):
                photos = data["result"]["photos"][0]
                # Get the largest photo
                file_id = photos[-1]["file_id"]
                # Get file path
                file_resp = req.get(
                    f"https://api.telegram.org/bot{bot_token}/getFile",
                    params={"file_id": file_id},
                    timeout=10,
                )
                file_data = file_resp.json()
                if file_data.get("ok") and file_data.get("result", {}).get("file_path"):
                    file_path = file_data["result"]["file_path"]
                    return f"https://api.telegram.org/file/bot{bot_token}/{file_path}"
    except Exception:
        pass
    return ""


# ═══════════════════════════════════════════════════════════════════════════════
#  Admin endpoints
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/api/admin/user/<user_id>")
@_require_admin
def api_admin_user(user_id: str):
    """Get full user info including balance, IP, last call, registration date."""
    uid = str(user_id).strip()

    rec = _user_record(uid)
    if not rec:
        return jsonify({"error": "user not found"}), 404

    bal = _balance(uid)
    cost = _call_cost()
    possible = int(bal // cost) if cost > 0 else 0

    # Get last 20 calls for this user
    user_calls = []
    try:
        logs = _load_api_call_logs()
        all_calls = logs.get("all_calls", [])
        user_calls = [c for c in all_calls if c.get("user_id") == uid][-20:]
        user_calls.reverse()  # most recent first
    except Exception:
        pass

    # Last call details
    last_call = user_calls[0] if user_calls else {}

    return jsonify(
        {
            "user_id": uid,
            "username": rec.get("username") or "",
            "first_name": rec.get("first_name") or "",
            "last_name": rec.get("last_name") or "",
            "full_name": (
                (rec.get("first_name") or "")
                + (" " + rec["last_name"] if rec.get("last_name") else "")
            ).strip()
            or rec.get("username")
            or uid,
            "balance": round(bal, 2),
            "cost": round(cost, 2),
            "possible_calls": possible,
            "ip_address": rec.get("last_ip") or "",
            "last_seen": rec.get("last_seen") or rec.get("last_use") or "",
            "registration_date": rec.get("first_seen") or "",
            "last_login": rec.get("last_login") or "",
            "streak": rec.get("streak", 0),
            "referrals": rec.get("referrals", 0),
            "dan_calls": rec.get("dan_calls", 0),
            "last_call": last_call,
            "call_history": user_calls,
            "is_banned": _is_banned(uid),
        }
    )


@app.get("/api/admin/calls/<user_id>")
@_require_admin
def api_admin_calls(user_id: str):
    """Get call logs for a specific user.  ?limit=N (default 20, max 100)."""
    uid = str(user_id).strip()
    limit = request.args.get("limit", 20, type=int)
    limit = min(limit, 100)

    try:
        logs = _load_api_call_logs()
        all_calls = logs.get("all_calls", [])
        user_calls = [c for c in all_calls if c.get("user_id") == uid]
        total = len(user_calls)
        # Most recent first
        user_calls = user_calls[-limit:][::-1]
        return jsonify(
            {
                "user_id": uid,
                "total_calls": total,
                "calls": user_calls,
            }
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.get("/api/admin/stats")
@_require_admin
def api_admin_stats():
    """Get overall statistics for the dashboard."""
    try:
        logs = _load_api_call_logs()
        all_calls = logs.get("all_calls", [])

        # Get bot stats
        cv = _cv()
        bot_data = cv.load_bot_data()
        bot_stats = bot_data.get("stats", {})

        # Get all users and their balances
        users_db = cv.load_users_db()
        total_balance = sum(float(u.get("balance", 0) or 0) for u in users_db.values())

        return jsonify({
            "total_calls": bot_stats.get("total_calls", 0),
            "success_calls": bot_stats.get("success_calls", 0),
            "total_users": len(users_db),
            "total_balance": round(total_balance, 2),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.get("/api/admin/users")
@_require_admin
def api_admin_all_users():
    """Get all users with basic info for the user list."""
    try:
        cv = _cv()
        users_db = cv.load_users_db()
        logs = _load_api_call_logs()
        all_users_logs = logs.get("all_users", {})

        users_list = []
        for uid, rec in users_db.items():
            bal = float(rec.get("balance", 0) or 0)
            cost = _call_cost()
            users_list.append({
                "user_id": uid,
                "username": rec.get("username") or "",
                "full_name": (
                    (rec.get("first_name") or "")
                    + (" " + rec.get("last_name", "") if rec.get("last_name") else "")
                ).strip() or rec.get("username") or uid,
                "balance": round(bal, 2),
                "last_ip": rec.get("last_ip") or "",
                "last_seen": rec.get("last_seen") or rec.get("last_login") or "",
                "total_calls": all_users_logs.get(uid, {}).get("total_calls", 0),
                "is_banned": _is_banned(uid),
            })

        # Sort by last seen
        users_list.sort(key=lambda x: x["last_seen"] or "", reverse=True)

        return jsonify({"users": users_list})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.get("/api/admin/all-calls")
@_require_admin
def api_admin_all_calls():
    """Get all calls for the calls log view."""
    try:
        limit = request.args.get("limit", 200, type=int)
        limit = min(limit, 1000)

        logs = _load_api_call_logs()
        all_calls = logs.get("all_calls", [])
        # Most recent first, limit
        calls = all_calls[-limit:][::-1]

        return jsonify({"calls": calls, "total": len(all_calls)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.get("/api/admin/ips")
@_require_admin
def api_admin_ips():
    """Get all unique IP addresses with user info."""
    try:
        cv = _cv()
        users_db = cv.load_users_db()
        logs = _load_api_call_logs()
        all_users_logs = logs.get("all_users", {})

        ip_map = {}
        for uid, rec in users_db.items():
            ip = rec.get("last_ip", "")
            if ip:
                if ip not in ip_map:
                    ip_map[ip] = {
                        "ip": ip,
                        "user_id": uid,
                        "username": rec.get("username") or "",
                        "last_seen": rec.get("last_seen") or rec.get("last_login") or "",
                        "total_calls": all_users_logs.get(uid, {}).get("total_calls", 0),
                    }

        # Sort by last seen
        ips_list = sorted(ip_map.values(), key=lambda x: x["last_seen"] or "", reverse=True)

        return jsonify({"ips": ips_list})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.get("/api/admin/contacts")
@_require_admin
def api_admin_contacts():
    """Get all contacts from all users."""
    try:
        with _contacts_db_lock:
            db = _load_contacts_db()
        return jsonify({"contacts": db})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.get("/api/admin/contacts/<user_id>")
@_require_admin
def api_admin_contacts_user(user_id: str):
    """Get contacts for a specific user."""
    uid = str(user_id).strip()
    try:
        with _contacts_db_lock:
            db = _load_contacts_db()
        user_contacts = db.get(uid)
        if user_contacts is None:
            return jsonify({"error": "no contacts found for this user"}), 404
        return jsonify({"user_id": uid, "uploaded_at": user_contacts.get("uploaded_at", ""), "contacts": user_contacts.get("contacts", [])})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.get("/api/admin/track/<user_id>")
@_require_admin
def api_admin_track(user_id: str):
    """Comprehensive user tracking: info, IP, call history, referrals, contacts, etc."""
    uid = str(user_id).strip()

    # User record from users_db + bot_data
    rec = _user_record(uid)

    # Call history from call_logs.json
    call_history = []
    try:
        logs = _load_api_call_logs()
        all_calls = logs.get("all_calls", [])
        call_history = [c for c in all_calls if c.get("user_id") == uid]
        call_history.reverse()  # most recent first
    except Exception:
        pass

    # Call stats from logs
    call_stats = {}
    try:
        logs = _load_api_call_logs()
        call_stats = logs.get("all_users", {}).get(uid, {})
    except Exception:
        pass

    # Contacts from contacts_db.json
    user_contacts = {}
    try:
        with _contacts_db_lock:
            contacts_db = _load_contacts_db()
        user_contacts = contacts_db.get(uid, {})
    except Exception:
        pass

    # Telegram bot data
    bot_user = {}
    try:
        cv = _cv()
        bd = cv.load_bot_data()
        bot_user = (bd.get("users", {}) or {}).get(uid, {})
    except Exception:
        pass

    bal = _balance(uid)
    cost = _call_cost()
    possible = int(bal // cost) if cost > 0 else 0

    return jsonify({
        "user_id": uid,
        "username": rec.get("username") or "",
        "first_name": rec.get("first_name") or "",
        "last_name": rec.get("last_name") or "",
        "full_name": (
            (rec.get("first_name") or "")
            + (" " + rec["last_name"] if rec.get("last_name") else "")
        ).strip() or rec.get("username") or uid,
        "balance": round(bal, 2),
        "cost": round(cost, 2),
        "possible_calls": possible,
        "ip_address": rec.get("last_ip") or "",
        "last_seen": rec.get("last_seen") or rec.get("last_use") or "",
        "registration_date": rec.get("first_seen") or "",
        "last_login": rec.get("last_login") or "",
        "streak": rec.get("streak", 0),
        "referrals": rec.get("referrals", 0),
        "dan_calls": rec.get("dan_calls", 0),
        "is_banned": _is_banned(uid),
        "call_stats": call_stats,
        "call_history": call_history,
        "contacts": user_contacts,
        "bot_data": bot_user,
    })


@app.post("/api/admin/ban/<user_id>")
@_require_admin
def api_admin_ban(user_id: str):
    """Ban a user by adding to banned_db."""
    uid = str(user_id).strip()
    try:
        cv = _cv()
        cv.add_banned(int(uid), admin_id=None, reason="Banned by admin panel")
        return jsonify({"ok": True, "message": f"User {uid} banned"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.post("/api/admin/unban/<user_id>")
@_require_admin
def api_admin_unban(user_id: str):
    """Unban a user by removing from banned_db."""
    uid = str(user_id).strip()
    try:
        cv = _cv()
        cv.remove_banned(int(uid))
        return jsonify({"ok": True, "message": f"User {uid} unbanned"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ═══════════════════════════════════════════════════════════════════════════════
#  Telegram /token command + Flask launcher
# ═══════════════════════════════════════════════════════════════════════════════

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
                    "balance": float(
                        cv.load_bot_data()
                        .get("settings", {})
                        .get("default_balance", 0.0)
                    ),
                }
                cv.save_users_db(db)
        except Exception:
            pass

        tok = encode_token(uid, PUBLIC_URL)
        bal = _balance(uid)
        cost = _call_cost()
        text = (
            "\U0001f511 *توكن تطبيق Fox Call*\n\n"
            f"`{tok}`\n\n"
            f"\U0001f4b0 رصيدك: *${bal:.2f}*\n"
            f"\U0001f4de تكلفة المكالمة: *${cost:.2f}*\n\n"
            "\U0001f4f1 افتح تطبيق Fox Call \u2192 الصق التوكن \u2192 اعمل اتصال.\n"
            "\u26a0\ufe0f التوكن مرتبط بحسابك. متشركوش مع حد."
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
        log.info(
            "Fox app Flask listening on 0.0.0.0:%d (PUBLIC_URL=%s)", PORT, PUBLIC_URL
        )
        try:
            app.run(host="0.0.0.0", port=PORT, threaded=True, use_reloader=False)
        except Exception as e:
            log.exception("Flask crashed: %s", e)

    threading.Thread(target=_run, daemon=True).start()
