#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GitHub-based Daily Backup for Fox Call Bot (v5.5.0).

🐘 PostgreSQL is now the PRIMARY data store (persistent).
☁️ GitHub is the BACKUP only — syncs once per day.

Flow:
  1. On startup: if PostgreSQL is empty → pull from GitHub → import to DB
  2. Every 24 hours: export from PostgreSQL → push to GitHub (daily backup)
  3. On manual data upload: immediate push to GitHub
  4. On critical changes (group auth, subs, sub-bots): immediate push

🔒 Data Protection:
  Before pushing, compare PostgreSQL Dan.json account count vs GitHub.
  - If DB >= GitHub → push (data is safe)
  - If DB < GitHub → pull from GitHub instead (data was lost)

Environment variables:
  GH_TOKEN   — GitHub personal access token (required)
  GH_REPO    — GitHub repo in "owner/repo" format (default: mohaedKw6/callapp)
  GH_BRANCH  — Branch to sync with (default: main)
  GH_DATA_DIR— Directory in the repo (default: data)
  DATA_DIR   — Local data directory (default: ./data)
  SYNC_INTERVAL— Seconds between auto-syncs (default: 86400 = 24 hours)
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
GH_REPO     = os.environ.get("GH_REPO", "mohaedKw6/callapp").strip('"').strip("'").strip()
GH_BRANCH   = os.environ.get("GH_BRANCH", "main").strip('"').strip("'").strip()
GH_DATA_DIR = os.environ.get("GH_DATA_DIR", "data").strip('"').strip("'").strip()
DATA_DIR    = os.environ.get("DATA_DIR", os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data"
))
# 🐘🔄 نسخ احتياطي يومي — كل 24 ساعة (86400 ثانية) بدل كل 10 ثواني
SYNC_INTERVAL = int(os.environ.get("SYNC_INTERVAL", "86400"))

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

# 🔒 ملفات مشفرة — يتخطى التحقق من JSON لأنها مش JSON عادي
ENCRYPTED_FILES = {"telicall_accounts.json"}

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
_last_backup_date = ""  # تاريخ آخر نسخة احتياطية (YYYY-MM-DD)


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


def _file_local_content(filepath: str, is_encrypted: bool = False) -> str | None:
    """Read local file content as string. Returns None if missing.
    For encrypted files, read as binary and decode as latin-1 to preserve bytes."""
    if not os.path.exists(filepath):
        return None
    try:
        if is_encrypted:
            with open(filepath, "rb") as f:
                raw = f.read()
            return raw.decode("latin-1")  # يحافظ على كل البايتات
        else:
            with open(filepath, "r", encoding="utf-8") as f:
                return f.read()
    except Exception:
        return None


# ═══════════════════════════════════════════════════════════════════════════════
#  🔒 Dan.json Account Count — حماية البيانات (من PostgreSQL)
# ═══════════════════════════════════════════════════════════════════════════════

def _get_local_dan_count() -> int:
    """عدد حسابات Dan.json (من PostgreSQL الأول، ثم JSON)"""
    # 🐘 PostgreSQL — المصدر الأساسي
    try:
        from db_manager import dan_count_total
        count = dan_count_total()
        if count > 0:
            return count
    except: pass
    # 📄 Fallback — bot_data.json
    bot_data_path = os.path.join(DATA_DIR, "bot_data.json")
    if not os.path.exists(bot_data_path):
        return 0
    try:
        with open(bot_data_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return len(data.get("registered_accounts", []))
    except Exception:
        return 0


def _get_github_dan_count() -> int:
    """عدد حسابات Dan.json على GitHub (registered_accounts في bot_data.json)"""
    if not GH_TOKEN:
        return 0
    try:
        import requests as req
        gh_path = f"{GH_DATA_DIR}/bot_data.json"
        url = _gh_api_url(gh_path)
        r = req.get(url, headers=_gh_headers(), timeout=30)
        if r.status_code == 200:
            resp = r.json()
            content_b64 = resp.get("content", "").replace("\n", "")
            content_bytes = base64.b64decode(content_b64)
            content_str = content_bytes.decode("utf-8")
            data = json.loads(content_str)
            count = len(data.get("registered_accounts", []))
            log.info("[gh-sync] GitHub Dan.json count: %d", count)
            return count
        else:
            log.warning("[gh-sync] Could not fetch bot_data.json from GitHub: HTTP %d", r.status_code)
            return 0
    except Exception as e:
        log.error("[gh-sync] Error fetching GitHub Dan.json count: %s", e)
        return 0


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
        is_encrypted = fname in ENCRYPTED_FILES

        try:
            r = req.get(url, headers=_gh_headers(), timeout=30)
            if r.status_code == 200:
                data = r.json()
                content_b64 = data.get("content", "")
                sha = data.get("sha", "")

                # Decode base64 content
                content_b64_clean = content_b64.replace("\n", "")
                content_bytes = base64.b64decode(content_b64_clean)

                if is_encrypted:
                    # 🔒 ملف مشفر — نحفظه كـ binary بدون التحقق من JSON
                    with open(local_path, "wb") as f:
                        f.write(content_bytes)
                    _file_shas[fname] = sha
                    _local_hashes[fname] = _file_local_hash(local_path)
                    result["pulled"] += 1
                    result["details"].append(f"{fname}: pulled OK (encrypted)")
                    log.info("[gh-sync] Pulled %s (encrypted)", fname)
                else:
                    # ملف JSON عادي — نتحقق إنه JSON صحيح
                    content_str = content_bytes.decode("utf-8")
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
    is_encrypted = fname in ENCRYPTED_FILES
    content = _file_local_content(local_path, is_encrypted=is_encrypted)
    if content is None:
        return {"status": "skipped", "detail": f"{fname}: read error"}

    gh_path = f"{GH_DATA_DIR}/{fname}"
    url = _gh_api_url(gh_path)

    # Build commit message
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    commit_msg = f"daily-backup: update {fname} [{ts}]"

    # Encode content as base64
    if is_encrypted:
        content_b64 = base64.b64encode(content.encode("latin-1")).decode("ascii")
    else:
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
                            continue
                except Exception:
                    pass

            error_msg = ""
            try:
                error_msg = r.json().get("message", r.text[:200])
            except Exception:
                error_msg = r.text[:200]

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


def push_to_github(force: bool = False) -> dict:
    """Upload changed data files to GitHub repo (daily backup).
    Only uploads files that have actually changed (hash comparison).

    🔒 Data Protection: Based on Dan.json account count
    Before pushing, compare DB registered_accounts count vs GitHub's.
    - If DB >= GitHub → push (data is safe, no accounts lost)
    - If DB < GitHub → pull from GitHub instead (data was lost)

    Args:
        force: Force push even if hashes match

    Returns {pushed: int, skipped: int, errors: int, details: []}
    """
    global _sync_cycle_count, _last_push_time, _last_backup_date

    if not GH_TOKEN:
        log.warning("[gh-sync] No GH_TOKEN set — skipping push")
        return {"pushed": 0, "skipped": 0, "errors": 0, "details": ["No GH_TOKEN"]}

    # 🐘 قبل الرفع — نحدث ملفات JSON من PostgreSQL
    try:
        from db_manager import export_to_json
        export_result = export_to_json(DATA_DIR)
        log.info("[gh-sync] 🐘 Exported from DB to JSON: %d files", export_result.get("exported", 0))
    except Exception as e:
        log.warning("[gh-sync] ⚠️ DB export failed, using local JSON: %s", e)

    # ═══ 🔒 حماية بناءً على عدد حسابات Dan.json ═══
    if not force:
        local_count = _get_local_dan_count()
        github_count = _get_github_dan_count()

        log.info("[gh-sync] 🔒 Dan.json protection: local=%d, github=%d", local_count, github_count)

        if github_count > 0 and local_count < github_count:
            log.warning(
                "[gh-sync] 🚨 DATA PROTECTION: Local Dan.json accounts (%d) < GitHub (%d) — pulling from GitHub instead!",
                local_count, github_count
            )
            try:
                pull_result = pull_from_github()
                # 🐘 بعد السحب — استيراد لـ PostgreSQL
                try:
                    from db_manager import import_from_json
                    import_from_json(DATA_DIR)
                except: pass
                return {
                    "pushed": 0, "skipped": 0, "errors": 0,
                    "details": [
                        f"🔒 حماية البيانات: حسابات Dan.json المحلية ({local_count}) أقل من GitHub ({github_count})\n"
                        f"✅ تم سحب البيانات من GitHub بدلاً من رفع بيانات ناقصة\n"
                        f"📥 سحب: {pull_result['pulled']} | تخطي: {pull_result['skipped']} | أخطاء: {pull_result['errors']}"
                    ]
                }
            except Exception as e:
                log.error("[gh-sync] Recovery pull failed: %s", e)
                return {"pushed": 0, "skipped": 0, "errors": 1,
                        "details": [f"🔒 DATA PROTECTION: Local ({local_count}) < GitHub ({github_count}), pull also failed: {e}"]}
        elif local_count >= github_count and github_count > 0:
            log.info("[gh-sync] ✅ Dan.json protection: local (%d) >= github (%d) — safe to push", local_count, github_count)
        elif github_count == 0 and local_count == 0:
            log.info("[gh-sync] ⚠️ Both local and GitHub have 0 Dan.json accounts — first time or no data yet")
        elif local_count > 0 and github_count == 0:
            log.info("[gh-sync] ✅ Local has %d accounts, GitHub has 0 — pushing new data", local_count)

    import requests as req

    result = {"pushed": 0, "skipped": 0, "errors": 0, "details": []}
    _sync_cycle_count += 1

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
    _last_backup_date = datetime.now().strftime("%Y-%m-%d")

    if result["pushed"] > 0 or result["errors"] > 0:
        log.info("[gh-sync] Backup #%d complete: %d pushed, %d skipped, %d errors",
                 _sync_cycle_count, result["pushed"], result["skipped"], result["errors"])
    return result


# ═══════════════════════════════════════════════════════════════════════════════
#  Auto-sync background thread — نسخ احتياطي يومي (كل 24 ساعة)
# ═══════════════════════════════════════════════════════════════════════════════

def _sync_loop():
    """Background thread that pushes data to GitHub once per day."""
    log.info("[gh-sync] Daily backup started (interval: %ds = %d hours)", SYNC_INTERVAL, SYNC_INTERVAL // 3600)

    while not _stop_event.is_set():
        # Wait for the interval, but check stop_event frequently
        waited = 0
        while waited < SYNC_INTERVAL and not _stop_event.is_set():
            time.sleep(min(30, SYNC_INTERVAL - waited))
            waited += 30

        if _stop_event.is_set():
            break

        try:
            with _sync_lock:
                push_to_github()
        except Exception as e:
            log.error("[gh-sync] Daily backup error: %s", e)

    log.info("[gh-sync] Daily backup stopped")


def start_auto_sync():
    """Start the background daily backup thread."""
    global _sync_thread
    if _sync_thread is not None and _sync_thread.is_alive():
        return  # Already running

    _stop_event.clear()
    _sync_thread = threading.Thread(target=_sync_loop, daemon=True, name="gh-sync")
    _sync_thread.start()
    log.info("[gh-sync] Daily backup thread launched (every %d hours)", SYNC_INTERVAL // 3600)


def stop_auto_sync():
    """Stop the background daily backup thread and do a final push."""
    _stop_event.set()
    # Final push before shutdown
    try:
        with _sync_lock:
            push_to_github(force=True)
    except Exception as e:
        log.error("[gh-sync] Final push error: %s", e)


def push_now():
    """Immediate push to GitHub — call this after critical data changes
    (group authorization, subscription, sub-bot registration, manual upload, etc.)
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
    """Full initialization: pull from GitHub if PostgreSQL is empty, then start daily backup.
    Call this AFTER _init_data_dir() so defaults exist locally.
    This ensures all .json data is loaded BEFORE the bot starts processing messages.
    """
    if not GH_TOKEN:
        log.warning("[gh-sync] No GH_TOKEN — GitHub backup disabled")
        log.warning("[gh-sync] Set GH_TOKEN env var to enable daily backup")
        return

    log.info("[gh-sync] Initializing GitHub backup (repo: %s, branch: %s)", GH_REPO, GH_BRANCH)

    # Step 1: Check if PostgreSQL has data
    try:
        from db_manager import db_is_empty
        if db_is_empty():
            # PostgreSQL empty → pull from GitHub
            log.info("[gh-sync] 📥 PostgreSQL is empty — pulling from GitHub...")
            result = pull_from_github()
            log.info("[gh-sync] Pull result: %d pulled, %d skipped, %d errors",
                     result["pulled"], result["skipped"], result["errors"])
            # Import pulled data into PostgreSQL
            try:
                from db_manager import import_from_json
                import_result = import_from_json(DATA_DIR)
                log.info("[gh-sync] 🐘 Imported to PostgreSQL: %d files", import_result.get("imported", 0))
            except Exception as e:
                log.error("[gh-sync] Import to PostgreSQL failed: %s", e)
        else:
            log.info("[gh-sync] ✅ PostgreSQL has data — skipping GitHub pull")
    except Exception as e:
        log.warning("[gh-sync] Cannot check PostgreSQL, pulling from GitHub: %s", e)
        result = pull_from_github()
        log.info("[gh-sync] Pull result: %d pulled, %d skipped, %d errors",
                 result["pulled"], result["skipped"], result["errors"])

    # Step 2: Start daily backup thread
    start_auto_sync()

    log.info("[gh-sync] Ready — daily backup every %d hours", SYNC_INTERVAL // 3600)
