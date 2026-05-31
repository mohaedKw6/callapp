#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GitHub-based Data Persistence for Fox Call Bot.

Uses the GitHub Contents API to store/retrieve JSON data files
in the repo's data/ directory. This ensures data survives
Railway container restarts without needing a paid Volume.

Flow:
  1. On startup:  pull latest data from GitHub → overwrite local files
  2. Every N minutes: push local data to GitHub (only if changed)
  3. On shutdown: final push to GitHub

Environment variables:
  GH_TOKEN   — GitHub personal access token (required)
  GH_REPO    — GitHub repo in "owner/repo" format (default: MohamedQM/callapp)
  GH_BRANCH  — Branch to sync with (default: main)
  GH_DATA_DIR— Directory in the repo (default: data)
  DATA_DIR   — Local data directory (default: ./data)
  SYNC_INTERVAL— Seconds between auto-syncs (default: 600 = 10 min)
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
    GH_TOKEN = "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"  # fallback — same as deployment token
    log.warning("[gh-sync] ⚠️ GH_TOKEN not in env vars, using hardcoded fallback")
else:
    log.info("[gh-sync] ✅ GH_TOKEN loaded from env (%s...)", GH_TOKEN[:8])
GH_REPO     = os.environ.get("GH_REPO", "mohaedkw6/callapp").strip('"').strip("'").strip()
GH_BRANCH   = os.environ.get("GH_BRANCH", "main").strip('"').strip("'").strip()
GH_DATA_DIR = os.environ.get("GH_DATA_DIR", "data").strip('"').strip("'").strip()
DATA_DIR    = os.environ.get("DATA_DIR", os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data"
))
SYNC_INTERVAL = int(os.environ.get("SYNC_INTERVAL", "600"))  # 10 minutes

# Files to sync — match the list in callv2._init_data_dir()
# Files that are encrypted (base64 XOR) — don't validate as JSON
_ENCRYPTED_FILES = {"telicall_accounts.json"}

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
]

# Track SHA for each file (needed for GitHub update API)
_file_shas: dict = {}
# Track local file hashes to detect changes
_local_hashes: dict = {}
_sync_lock = threading.Lock()
_sync_thread = None
_stop_event = threading.Event()


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

                # Validate it's valid JSON (unless encrypted file)
                if fname not in _ENCRYPTED_FILES:
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
#  Push (upload) to GitHub
# ═══════════════════════════════════════════════════════════════════════════════

def push_to_github(force: bool = False) -> dict:
    """Upload changed data files to GitHub repo.
    Only uploads files that have actually changed (hash comparison).
    Returns {pushed: int, skipped: int, errors: int, details: []}
    """
    if not GH_TOKEN:
        log.warning("[gh-sync] No GH_TOKEN set — skipping push")
        return {"pushed": 0, "skipped": 0, "errors": 0, "details": ["No GH_TOKEN"]}

    import requests as req

    result = {"pushed": 0, "skipped": 0, "errors": 0, "details": []}

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
            result["details"].append(f"{fname}: no changes")
            continue

        content = _file_local_content(local_path)
        if content is None:
            result["skipped"] += 1
            result["details"].append(f"{fname}: read error")
            continue

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

        try:
            r = req.put(url, headers=_gh_headers(), json=body, timeout=30)
            if r.status_code in (200, 201):
                data = r.json()
                new_sha = data.get("content", {}).get("sha", "") or data.get("commit", {}).get("sha", "")
                if new_sha and "content" in data:
                    _file_shas[fname] = data["content"].get("sha", new_sha)
                _local_hashes[fname] = current_hash
                result["pushed"] += 1
                result["details"].append(f"{fname}: pushed OK")
                log.info("[gh-sync] Pushed %s", fname)
            else:
                error_msg = ""
                try:
                    error_msg = r.json().get("message", r.text[:200])
                except Exception:
                    error_msg = r.text[:200]
                result["errors"] += 1
                result["details"].append(f"{fname}: HTTP {r.status_code} - {error_msg}")
                log.warning("[gh-sync] Failed to push %s: HTTP %d - %s",
                            fname, r.status_code, error_msg)

        except Exception as e:
            result["errors"] += 1
            result["details"].append(f"{fname}: {e}")
            log.error("[gh-sync] Error pushing %s: %s", fname, e)

    log.info("[gh-sync] Push complete: %d pushed, %d skipped, %d errors",
             result["pushed"], result["skipped"], result["errors"])
    return result


# ═══════════════════════════════════════════════════════════════════════════════
#  Auto-sync background thread
# ═══════════════════════════════════════════════════════════════════════════════

def _sync_loop():
    """Background thread that periodically pushes data to GitHub."""
    log.info("[gh-sync] Auto-sync started (interval: %ds)", SYNC_INTERVAL)

    while not _stop_event.is_set():
        # Wait for the interval, but check stop_event every 10 seconds
        waited = 0
        while waited < SYNC_INTERVAL and not _stop_event.is_set():
            time.sleep(min(10, SYNC_INTERVAL - waited))
            waited += 10

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


# ═══════════════════════════════════════════════════════════════════════════════
#  Startup initialization
# ═══════════════════════════════════════════════════════════════════════════════

def init_github_sync():
    """Full initialization: pull from GitHub, then start auto-sync.
    Call this AFTER _init_data_dir() so defaults exist locally.
    """
    if not GH_TOKEN:
        log.warning("[gh-sync] No GH_TOKEN — GitHub sync disabled")
        log.warning("[gh-sync] Set GH_TOKEN env var to enable persistent storage")
        return

    log.info("[gh-sync] Initializing GitHub sync (repo: %s, branch: %s)", GH_REPO, GH_BRANCH)

    # Step 1: Pull latest data from GitHub
    log.info("[gh-sync] Pulling latest data from GitHub...")
    result = pull_from_github()
    log.info("[gh-sync] Pull result: %d pulled, %d skipped, %d errors",
             result["pulled"], result["skipped"], result["errors"])

    # Step 2: Start auto-sync thread
    start_auto_sync()

    log.info("[gh-sync] Ready — data will auto-sync every %d seconds", SYNC_INTERVAL)
