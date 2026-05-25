#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GitHub-based Data Persistence for Fox Call Bot.

Uses the GitHub Contents API to store/retrieve JSON data files
in the repo's data/ directory. This ensures data survives
Railway container restarts without needing a paid Volume.

Flow:
  1. On startup:  pull latest data from GitHub → overwrite local files
  2. Every 10 seconds: push local data to GitHub (only if changed)
  3. On shutdown: final push to GitHub
  4. On critical changes (group auth, subs, sub-bots): immediate push

Environment variables:
  GH_TOKEN   — GitHub personal access token (required)
  GH_REPO    — GitHub repo in "owner/repo" format (default: MohamedQM/callapp)
  GH_BRANCH  — Branch to sync with (default: main)
  GH_DATA_DIR— Directory in the repo (default: data)
  DATA_DIR   — Local data directory (default: ./data)
  SYNC_INTERVAL— Seconds between auto-syncs (default: 10)
"""

import os
import json
import time
import hashlib
import base64
import threading
import logging
from datetime import datetime

log = logging.getLogger("gh-sync")

# ═══════════════════════════════════════════════════════════════════════════════
#  Configuration
# ═══════════════════════════════════════════════════════════════════════════════

GH_TOKEN    = os.environ.get("GH_TOKEN", "").strip('"').strip("'").strip()
if not GH_TOKEN:
    GH_TOKEN = "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"  # fallback
    log.warning("[gh-sync] ⚠️ GH_TOKEN not in env vars, using hardcoded fallback")
else:
    log.info("[gh-sync] ✅ GH_TOKEN loaded from env (%s...)", GH_TOKEN[:8])
GH_REPO     = os.environ.get("GH_REPO", "MohamedQM/callapp").strip('"').strip("'").strip()
GH_BRANCH   = os.environ.get("GH_BRANCH", "main").strip('"').strip("'").strip()
GH_DATA_DIR = os.environ.get("GH_DATA_DIR", "data").strip('"').strip("'").strip()
DATA_DIR    = os.environ.get("DATA_DIR", os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data"
))
# 🔁 تزامن كل 10 ثواني — عشان الداتا ما تضيعش أبداً
SYNC_INTERVAL = int(os.environ.get("SYNC_INTERVAL", "10"))

# Files to sync — match the list in callv2._init_data_dir()
SYNC_FILES = [
    "bot_data.json",
    "telicall_accounts.json",
    "users_db.json",
    "premium_db.json",
    "banned_db.json",
    "tokens_cache.json",
    "call_logs.json",
    "security_strikes.json",
    "monthly_subs.json",
    "dtmf_settings.json",
    "sub_bots.json",
    "failed_accounts.json",
    "double_call_map.json",
    "authorized_groups.json",
    "contacts_db.json",
    "owner_earnings.json",
]

# Track SHA for each file (needed for GitHub update API)
_file_shas: dict = {}
# Track local file hashes to detect changes
_local_hashes: dict = {}
_sync_lock = threading.Lock()
_sync_thread = None
_stop_event = threading.Event()
# Counter for sync cycles
_sync_cycle_count = 0
_last_push_time = 0.0
# Track remote file sizes for data protection
_remote_sizes: dict = {}
# Pending sync decision from admin (data size warning)
_sync_decision_pending = False


# ═══════════════════════════════════════════════════════════════════════════════
#  GitHub API helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _gh_api_url(path: str) -> str:
    """Build GitHub Contents API URL."""
    return f"https://api.github.com/repos/{GH_REPO}/contents/{path}"


def _gh_headers() -> dict:
    """Headers for GitHub API requests."""
    return {
        "Authorization": f"token {GH_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "FoxCall-Bot-Sync",
    }


def _file_local_hash(filepath: str) -> str:
    """Compute SHA-256 hash of a local file. Returns empty string if file missing."""
    if not os.path.exists(filepath):
        return ""
    try:
        with open(filepath, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except Exception:
        return ""


def _file_local_content(filepath: str) -> str | None:
    """Read local file content as string. Returns None if missing."""
    if not os.path.exists(filepath):
        return None
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None


def _get_total_local_data_size() -> int:
    """Get total size in bytes of all local data files."""
    total = 0
    for fname in SYNC_FILES:
        fpath = os.path.join(DATA_DIR, fname)
        if os.path.exists(fpath):
            try:
                total += os.path.getsize(fpath)
            except Exception:
                pass
    return total


def _get_remote_data_size() -> int:
    """Get total size in bytes of all data files on GitHub.
    Also updates _remote_sizes dict for individual file tracking.
    """
    import requests as req
    total = 0
    for fname in SYNC_FILES:
        gh_path = f"{GH_DATA_DIR}/{fname}"
        url = _gh_api_url(gh_path)
        try:
            r = req.get(url, headers=_gh_headers(), timeout=15)
            if r.status_code == 200:
                data = r.json()
                size = data.get("size", 0)
                _remote_sizes[fname] = size
                total += size
            elif r.status_code == 404:
                _remote_sizes[fname] = 0
        except Exception:
            pass
    return total


# ═══════════════════════════════════════════════════════════════════════════════
#  Pull (download) from GitHub
# ═══════════════════════════════════════════════════════════════════════════════

def pull_from_github() -> dict:
    """Download all data files from GitHub repo.
    Returns {pulled: int, skipped: int, errors: int, details: []}
    """
    if not GH_TOKEN:
        log.warning("[gh-sync] No GH_TOKEN set — skipping pull")
        return {"pulled": 0, "skipped": 0, "errors": 0, "details": ["No GH_TOKEN"]}

    import requests as req

    result = {"pulled": 0, "skipped": 0, "errors": 0, "details": []}
    os.makedirs(DATA_DIR, exist_ok=True)

    for fname in SYNC_FILES:
        local_path = os.path.join(DATA_DIR, fname)
        gh_path = f"{GH_DATA_DIR}/{fname}"
        url = _gh_api_url(gh_path)

        try:
            r = req.get(url, headers=_gh_headers(), timeout=30)
            if r.status_code == 200:
                data = r.json()
                content_b64 = data.get("content", "")
                sha = data.get("sha", "")

                # Decode base64 content
                # GitHub returns base64 with newlines — strip them
                content_b64_clean = content_b64.replace("\n", "")
                content_bytes = base64.b64decode(content_b64_clean)
                content_str = content_bytes.decode("utf-8")

                # Validate it's valid JSON
                try:
                    json.loads(content_str)
                except json.JSONDecodeError:
                    result["errors"] += 1
                    result["details"].append(f"{fname}: invalid JSON from GitHub")
                    continue

                # Save locally (overwrite)
                with open(local_path, "w", encoding="utf-8") as f:
                    f.write(content_str)

                # Track SHA for future updates
                _file_shas[fname] = sha
                _local_hashes[fname] = _file_local_hash(local_path)

                result["pulled"] += 1
                result["details"].append(f"{fname}: pulled OK")
                log.info("[gh-sync] Pulled %s", fname)

            elif r.status_code == 404:
                # File doesn't exist on GitHub yet — that's fine
                result["skipped"] += 1
                result["details"].append(f"{fname}: not on GitHub yet")
            else:
                result["errors"] += 1
                result["details"].append(f"{fname}: HTTP {r.status_code}")
                log.warning("[gh-sync] Failed to pull %s: HTTP %d", fname, r.status_code)

        except Exception as e:
            result["errors"] += 1
            result["details"].append(f"{fname}: {e}")
            log.error("[gh-sync] Error pulling %s: %s", fname, e)

    log.info("[gh-sync] Pull complete: %d pulled, %d skipped, %d errors",
             result["pulled"], result["skipped"], result["errors"])
    return result


# ═══════════════════════════════════════════════════════════════════════════════
#  Push (upload) to GitHub — مع إعادة المحاولة عند الفشل
# ═══════════════════════════════════════════════════════════════════════════════

def _push_single_file(req, fname: str, local_path: str, current_hash: str) -> dict:
    """Push a single file to GitHub with retry logic.
    Returns {"status": "ok"|"skipped"|"error", "detail": str}
    """
    content = _file_local_content(local_path)
    if content is None:
        return {"status": "skipped", "detail": f"{fname}: read error"}

    gh_path = f"{GH_DATA_DIR}/{fname}"
    url = _gh_api_url(gh_path)

    # Build commit message
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    commit_msg = f"auto-sync: update {fname} [{ts}]"

    # Encode content as base64
    content_b64 = base64.b64encode(content.encode("utf-8")).decode("ascii")

    # Build request body
    body = {
        "message": commit_msg,
        "content": content_b64,
        "branch": GH_BRANCH,
    }

    # If we have the SHA, include it (required for updates)
    sha = _file_shas.get(fname)
    if sha:
        body["sha"] = sha
    else:
        # Try to get SHA from GitHub first
        try:
            r = req.get(url, headers=_gh_headers(), timeout=15)
            if r.status_code == 200:
                existing_sha = r.json().get("sha", "")
                if existing_sha:
                    body["sha"] = existing_sha
                    _file_shas[fname] = existing_sha
        except Exception:
            pass

    # محاولة الدفع مع إعادة المحاولة (3 مرات)
    for attempt in range(3):
        try:
            r = req.put(url, headers=_gh_headers(), json=body, timeout=30)
            if r.status_code in (200, 201):
                data = r.json()
                new_sha = data.get("content", {}).get("sha", "") or data.get("commit", {}).get("sha", "")
                if new_sha and "content" in data:
                    _file_shas[fname] = data["content"].get("sha", new_sha)
                _local_hashes[fname] = current_hash
                return {"status": "ok", "detail": f"{fname}: pushed OK"}
            
            # لو فيه تعارض (409 Conflict) — نحدث الـ SHA ونعيد المحاولة
            if r.status_code == 409:
                log.warning("[gh-sync] Conflict on %s, refreshing SHA (attempt %d)", fname, attempt + 1)
                try:
                    r2 = req.get(url, headers=_gh_headers(), timeout=15)
                    if r2.status_code == 200:
                        new_sha = r2.json().get("sha", "")
                        if new_sha:
                            body["sha"] = new_sha
                            _file_shas[fname] = new_sha
                            continue  # إعادة المحاولة بالـ SHA الجديد
                except Exception:
                    pass
            
            error_msg = ""
            try:
                error_msg = r.json().get("message", r.text[:200])
            except Exception:
                error_msg = r.text[:200]
            
            # لو مش التعارض، نحاول تاني بعد انتظار
            if attempt < 2:
                time.sleep(1 * (attempt + 1))
                continue
            
            return {"status": "error", "detail": f"{fname}: HTTP {r.status_code} - {error_msg}"}

        except Exception as e:
            if attempt < 2:
                time.sleep(1 * (attempt + 1))
                continue
            return {"status": "error", "detail": f"{fname}: {e}"}

    return {"status": "error", "detail": f"{fname}: failed after 3 attempts"}


def push_to_github(force: bool = False, skip_size_check: bool = False) -> dict:
    """Upload changed data files to GitHub repo.
    Only uploads files that have actually changed (hash comparison).
    
    🔒 Data protection: If local data size is smaller than remote GitHub data,
    the push is BLOCKED and admins are notified with Yes/No buttons.
    
    Args:
        force: Force push even if hashes match
        skip_size_check: Skip the size protection check (used when admin approves)
    
    Returns {pushed: int, skipped: int, errors: int, details: [], size_blocked: bool}
    """
    global _sync_cycle_count, _last_push_time, _sync_decision_pending

    if not GH_TOKEN:
        log.warning("[gh-sync] No GH_TOKEN set — skipping push")
        return {"pushed": 0, "skipped": 0, "errors": 0, "details": ["No GH_TOKEN"], "size_blocked": False}

    # ═══ 🔒 حماية الداتا: تحقق الحجم ═══
    if not skip_size_check and not force:
        try:
            local_size = _get_total_local_data_size()
            remote_size = _get_remote_data_size()
            
            if remote_size > 0 and local_size < remote_size:
                # الحجم المحلي أقل من الحجم المرفوع — خطر فقدان بيانات!
                local_mb = local_size / (1024 * 1024)
                remote_mb = remote_size / (1024 * 1024)
                diff_mb = remote_mb - local_mb
                
                log.warning(
                    "[gh-sync] 🚨 SIZE PROTECTION: Local %.2f MB < Remote %.2f MB (diff: %.2f MB) — blocking push!",
                    local_mb, remote_mb, diff_mb
                )
                
                # أبلغ الأدمنز وانتظر قرارهم
                _notify_admins_size_warning(local_mb, remote_mb, diff_mb)
                _sync_decision_pending = True
                
                return {
                    "pushed": 0, "skipped": 0, "errors": 0,
                    "details": [f"SIZE BLOCKED: Local {local_mb:.2f} MB < Remote {remote_mb:.2f} MB"],
                    "size_blocked": True,
                    "local_size_mb": local_mb,
                    "remote_size_mb": remote_mb
                }
        except Exception as e:
            log.error("[gh-sync] Size check error (proceeding anyway): %s", e)

    import requests as req

    result = {"pushed": 0, "skipped": 0, "errors": 0, "details": [], "size_blocked": False}
    _sync_cycle_count += 1
    _sync_decision_pending = False

    for fname in SYNC_FILES:
        local_path = os.path.join(DATA_DIR, fname)

        if not os.path.exists(local_path):
            result["skipped"] += 1
            result["details"].append(f"{fname}: local file missing")
            continue

        # Check if file has changed since last sync
        current_hash = _file_local_hash(local_path)
        if not force and current_hash == _local_hashes.get(fname, ""):
            result["skipped"] += 1
            continue

        push_result = _push_single_file(req, fname, local_path, current_hash)
        
        if push_result["status"] == "ok":
            result["pushed"] += 1
            result["details"].append(push_result["detail"])
            log.info("[gh-sync] Pushed %s", fname)
        elif push_result["status"] == "skipped":
            result["skipped"] += 1
            result["details"].append(push_result["detail"])
        else:
            result["errors"] += 1
            result["details"].append(push_result["detail"])
            log.warning("[gh-sync] Failed to push %s: %s", fname, push_result["detail"])

    _last_push_time = time.time()

    if result["pushed"] > 0 or result["errors"] > 0:
        log.info("[gh-sync] Push #%d complete: %d pushed, %d skipped, %d errors",
                 _sync_cycle_count, result["pushed"], result["skipped"], result["errors"])
    return result


def _notify_admins_size_warning(local_mb: float, remote_mb: float, diff_mb: float):
    """أبلغ الأدمنز إن حجم الداتا المحلية أقل من المرفوع على GitHub"""
    try:
        import telebot
        from callv2 import BOT_TOKEN, ADMIN_IDS
        
        _bot = telebot.TeleBot(BOT_TOKEN)
        
        for admin_id in ADMIN_IDS:
            try:
                from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
                kb = InlineKeyboardMarkup()
                kb.row(
                    InlineKeyboardButton("✅ نعم — اكمل الرفع", callback_data="sync_force_yes"),
                    InlineKeyboardButton("❌ لا — نزل من GitHub", callback_data="sync_force_no"),
                )
                _bot.send_message(
                    admin_id,
                    f"🚨 *تحذير حماية الداتا!*\n\n"
                    f"📊 الحجم المحلي: `{local_mb:.2f} MB`\n"
                    f"☁️ حجم GitHub: `{remote_mb:.2f} MB`\n"
                    f"📉 الفرق: `{diff_mb:.2f} MB` أقل\n\n"
                    f"الحجم المحلي **أقل** من المرفوع على GitHub.\n"
                    f"هل تريدني أكمل الرفع واستبدال الداتا على GitHub؟\n\n"
                    f"✅ *نعم* = ارفع الداتا المحلية واستبدل\n"
                    f"❌ *لا* = نزل الداتا من GitHub واستعملها محلياً",
                    parse_mode='Markdown',
                    reply_markup=kb
                )
            except Exception as e:
                log.error("[gh-sync] Failed to notify admin %s: %s", admin_id, e)
    except Exception as e:
        log.error("[gh-sync] Failed to notify admins: %s", e)


# ═══════════════════════════════════════════════════════════════════════════════
#  Auto-sync background thread — كل 10 ثواني
# ═══════════════════════════════════════════════════════════════════════════════

def _sync_loop():
    """Background thread that periodically pushes data to GitHub."""
    log.info("[gh-sync] Auto-sync started (interval: %ds)", SYNC_INTERVAL)

    while not _stop_event.is_set():
        # Wait for the interval, but check stop_event frequently
        waited = 0
        while waited < SYNC_INTERVAL and not _stop_event.is_set():
            time.sleep(min(2, SYNC_INTERVAL - waited))
            waited += 2

        if _stop_event.is_set():
            break

        try:
            with _sync_lock:
                push_to_github()
        except Exception as e:
            log.error("[gh-sync] Auto-sync error: %s", e)

    log.info("[gh-sync] Auto-sync stopped")


def start_auto_sync():
    """Start the background auto-sync thread."""
    global _sync_thread
    if _sync_thread is not None and _sync_thread.is_alive():
        return  # Already running

    _stop_event.clear()
    _sync_thread = threading.Thread(target=_sync_loop, daemon=True, name="gh-sync")
    _sync_thread.start()
    log.info("[gh-sync] Auto-sync thread launched")


def stop_auto_sync():
    """Stop the background auto-sync thread and do a final push."""
    _stop_event.set()
    # Final push before shutdown
    try:
        with _sync_lock:
            push_to_github(force=True)
    except Exception as e:
        log.error("[gh-sync] Final push error: %s", e)


def push_now():
    """Immediate push to GitHub — call this after critical data changes
    (group authorization, subscription, sub-bot registration, etc.)
    Runs in a background thread to avoid blocking the caller.
    """
    def _do_push():
        try:
            with _sync_lock:
                push_to_github()
        except Exception as e:
            log.error("[gh-sync] push_now error: %s", e)
    t = threading.Thread(target=_do_push, daemon=True, name="gh-push-now")
    t.start()


# ═══════════════════════════════════════════════════════════════════════════════
#  Startup initialization
# ═══════════════════════════════════════════════════════════════════════════════

def init_github_sync():
    """Full initialization: pull from GitHub, then start auto-sync.
    Call this AFTER _init_data_dir() so defaults exist locally.
    This ensures all .json data is loaded BEFORE the bot starts processing messages.
    """
    if not GH_TOKEN:
        log.warning("[gh-sync] No GH_TOKEN — GitHub sync disabled")
        log.warning("[gh-sync] Set GH_TOKEN env var to enable persistent storage")
        return

    log.info("[gh-sync] Initializing GitHub sync (repo: %s, branch: %s)", GH_REPO, GH_BRANCH)

    # Step 1: Pull latest data from GitHub (BLOCKING — must complete before bot starts)
    log.info("[gh-sync] Pulling latest data from GitHub...")
    result = pull_from_github()
    log.info("[gh-sync] Pull result: %d pulled, %d skipped, %d errors",
             result["pulled"], result["skipped"], result["errors"])

    # Step 2: Start auto-sync thread (every 10 seconds)
    start_auto_sync()

    log.info("[gh-sync] Ready — data will auto-sync every %d seconds", SYNC_INTERVAL)
