#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Fox Caller Diagnostic - Step by step test of the full Telicall flow
to understand why calls report success but don't actually connect.
"""

import requests
import json
import uuid
import time
import random
import base64
import hashlib
import re
import os
import sys

# Config
API_URL = "https://api.telicall.com"
DAN_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Dan.json")
PASSWORD = "@@@GMAQ@@@"

# Instant Mail API
INSTANTMAIL_API_BASE = "https://mail-server-2.1timetech.com"
INSTANTMAIL_APP_KEY = "b9db03078622"

# Egyptian IP ranges
_EG_RANGES = [
    (41, 32), (41, 33), (41, 34), (41, 35), (41, 36),
    (41, 37), (41, 38), (41, 39), (41, 40), (41, 41),
    (156, 192), (156, 193), (156, 194), (156, 195),
    (197, 32), (197, 33), (197, 34), (197, 35),
    (102, 156), (102, 157), (102, 158), (102, 159),
    (154, 128), (154, 129), (154, 130), (154, 131),
]

def rand_eg_ip():
    a, b = random.choice(_EG_RANGES)
    return f"{a}.{b}.{random.randint(1,254)}.{random.randint(1,254)}"

def decrypt_file(path, password):
    with open(path, 'rb') as f:
        raw = base64.b64decode(f.read())
    key = hashlib.sha256(password.encode()).digest()
    return bytes([raw[i] ^ key[i % len(key)] for i in range(len(raw))]).decode('utf-8')

def load_accounts():
    try:
        return json.loads(decrypt_file(DAN_FILE, PASSWORD))
    except:
        try:
            with open(DAN_FILE, 'r') as f:
                return json.loads(f.read())
        except:
            return []

# ═══════════════════════════════════════════════════════
# Instant Mail API (with encryption)
# ═══════════════════════════════════════════════════════
BASE64_ALPHA = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/'
_CIPHER_SWAPS = [
    (1, 51), (27, 57), (26, 40), (62, 49),
    (42, 44), (56, 63),
]
def _build_custom_alphabet():
    alpha = list(BASE64_ALPHA)
    for i, j in _CIPHER_SWAPS:
        alpha[i], alpha[j] = alpha[j], alpha[i]
    return ''.join(alpha)
_CUSTOM_ALPHA = _build_custom_alphabet()
_DECODE_TRANS = str.maketrans(_CUSTOM_ALPHA, BASE64_ALPHA)

def instantmail_decode(encrypted_data):
    try:
        reversed_str = encrypted_data[::-1]
        processed = reversed_str.replace('*', '/').replace('=', '+')
        if processed.endswith('xx'):
            processed = processed[:-2] + '=='
        elif processed.endswith('x'):
            processed = processed[:-1] + '='
        standard = processed.translate(_DECODE_TRANS)
        pad_needed = 4 - len(standard) % 4
        if pad_needed < 4:
            standard += '=' * pad_needed
        decoded_bytes = base64.b64decode(standard)
        text = decoded_bytes.decode('utf-8', errors='replace')
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            for pattern in [r'\{.*\}', r'\[.*\]']:
                m = re.search(pattern, text)
                if m:
                    try:
                        return json.loads(m.group())
                    except:
                        continue
            return None
    except Exception as e:
        print(f"  [DECODE ERROR] {e}")
        return None

def instantmail_create_inbox():
    headers = {
        'accept': 'application/json',
        'x-app-key': INSTANTMAIL_APP_KEY,
        'Content-Type': 'application/json',
        'User-Agent': 'okhttp/4.9.2'
    }
    try:
        r = requests.post(
            f"{INSTANTMAIL_API_BASE}/api/g-mail?params=x03e",
            headers=headers, json={}, timeout=20
        )
        print(f"  InstantMail: HTTP {r.status_code}")
        if r.status_code == 200:
            resp = r.json()
            encrypted_data = resp.get('data', '')
            if encrypted_data:
                decoded = instantmail_decode(encrypted_data)
                if decoded and decoded.get('success'):
                    email = decoded.get('email', '')
                    inbox_id = decoded.get('id', '')
                    print(f"  Created: {email} (id: {inbox_id})")
                    return email, inbox_id
                else:
                    print(f"  Decode result: {decoded}")
            else:
                print(f"  No data in response: {json.dumps(resp)[:200]}")
        else:
            print(f"  Response: {r.text[:200]}")
    except Exception as e:
        print(f"  Error: {e}")
    return None, None

def instantmail_get_messages(inbox_id):
    headers = {
        'accept': 'application/json',
        'x-app-key': INSTANTMAIL_APP_KEY,
        'User-Agent': 'okhttp/4.9.2'
    }
    try:
        r = requests.get(
            f"{INSTANTMAIL_API_BASE}/api/email/{inbox_id}/messages",
            headers=headers, timeout=20
        )
        if r.status_code == 200:
            resp = r.json()
            encrypted_data = resp.get('data', '')
            if encrypted_data:
                decoded = instantmail_decode(encrypted_data)
                if isinstance(decoded, list):
                    return decoded
                elif isinstance(decoded, dict):
                    return decoded.get('messages', decoded.get('data', []))
            return []
    except Exception as e:
        print(f"  Message read error: {e}")
    return []


# ═══════════════════════════════════════════════════════
# Telicall API
# ═══════════════════════════════════════════════════════
def telicall_init():
    """Step 1: Initialize a new session"""
    device = ''.join(random.choices('0123456789abcdef', k=16))
    ip = rand_eg_ip()
    h = {
        "host": "api.telicall.com",
        "x-request-id": str(uuid.uuid4()),
        "user-agent": "Dalvik/2.1.0",
        "x-app-version": "1.2.1",
        "x-client-device-id": device,
        "x-lang": "en", "x-os": "android", "x-os-version": "11",
        "x-req-timestamp": str(int(time.time() * 1000)),
        "x-req-signature": "-1",
        "content-type": "application/json",
        "x-token": "",
        "x-currency": "EGP",
        "x-real-ip": ip,
    }
    body = {
        "countryCode": "eg", "deviceName": "Infinix X698",
        "notificationToken": "", "oldToken": "",
        "peerKey": str(random.randint(100, 999)),
        "timeZone": "Africa/Cairo", "localizationKey": ""
    }
    try:
        r = requests.post(f"{API_URL}/init", json=body, headers=h, timeout=15)
        print(f"  /init: HTTP {r.status_code}")
        resp = r.json()
        # Print full response for debugging
        print(f"  /init response: {json.dumps(resp, indent=2)[:500]}")
        if r.status_code == 200:
            token = resp.get('result', {}).get('token')
            if token:
                return token, device, h
    except Exception as e:
        print(f"  /init error: {e}")
    return None, None, None

def telicall_send_email(email, headers):
    """Step 2: Send verification email"""
    headers = dict(headers)
    headers["x-request-id"] = str(uuid.uuid4())
    headers["x-req-timestamp"] = str(int(time.time() * 1000))
    try:
        r = requests.post(f"{API_URL}/auth/send-email", json={'email': email},
                          headers=headers, timeout=15)
        print(f"  /auth/send-email: HTTP {r.status_code}")
        resp = r.json()
        print(f"  Response: {json.dumps(resp, indent=2)[:500]}")
        if r.status_code == 200:
            ref = resp.get('result', {}).get('reference')
            return ref, None
        else:
            err = resp.get('meta', {}).get('errorMessage', str(resp)[:100])
            return None, err
    except Exception as e:
        print(f"  Error: {e}")
        return None, str(e)

def telicall_verify_otp(ref, code, headers):
    """Step 3: Verify OTP"""
    headers = dict(headers)
    headers["x-request-id"] = str(uuid.uuid4())
    headers["x-req-timestamp"] = str(int(time.time() * 1000))
    try:
        r = requests.post(f"{API_URL}/auth/verify-identity",
                          json={'reference': ref, 'code': str(code)},
                          headers=headers, timeout=15)
        print(f"  /auth/verify-identity: HTTP {r.status_code}")
        resp = r.json()
        print(f"  Response: {json.dumps(resp, indent=2)[:800]}")
        if r.status_code == 200:
            user = resp.get('result', {}).get('user')
            new_token = resp.get('result', {}).get('token')
            return user, new_token, None
        else:
            err = resp.get('meta', {}).get('errorMessage', str(resp)[:100])
            return None, None, err
    except Exception as e:
        print(f"  Error: {e}")
        return None, None, str(e)

def telicall_make_call(phone, token, device_id):
    """Step 4: Make a call"""
    ip = rand_eg_ip()
    h = {
        "host": "api.telicall.com",
        "x-request-id": str(uuid.uuid4()),
        "user-agent": "Dalvik/2.1.0",
        "x-app-version": "1.2.1",
        "x-client-device-id": device_id,
        "x-lang": "en", "x-os": "android", "x-os-version": "11",
        "x-req-timestamp": str(int(time.time() * 1000)),
        "x-req-signature": "-1",
        "content-type": "application/json",
        "x-token": token,
        "x-currency": "EGP",
        "x-real-ip": ip,
    }
    try:
        r = requests.post(f"{API_URL}/call/outbound/start",
                          json={'to': phone, 'source': 'numpad'},
                          headers=h, timeout=15)
        print(f"  /call/outbound/start: HTTP {r.status_code}")
        resp = r.json()
        print(f"  FULL Response: {json.dumps(resp, indent=2)[:1000]}")
        return resp
    except Exception as e:
        print(f"  Error: {e}")
        return None

def telicall_get_balance(token, device_id):
    """Check account balance"""
    h = {
        "host": "api.telicall.com",
        "x-request-id": str(uuid.uuid4()),
        "user-agent": "Dalvik/2.1.0",
        "x-app-version": "1.2.1",
        "x-client-device-id": device_id,
        "x-lang": "en", "x-os": "android", "x-os-version": "11",
        "x-req-timestamp": str(int(time.time() * 1000)),
        "x-req-signature": "-1",
        "content-type": "application/json",
        "x-token": token,
    }
    try:
        r = requests.get(f"{API_URL}/user/profile", headers=h, timeout=15)
        print(f"  /user/profile: HTTP {r.status_code}")
        resp = r.json()
        print(f"  Response: {json.dumps(resp, indent=2)[:800]}")
        return resp
    except Exception as e:
        print(f"  Error: {e}")
        return None


# ═══════════════════════════════════════════════════════
# Diagnostic Tests
# ═══════════════════════════════════════════════════════

def test_old_accounts():
    """Test 1: Check if old Dan.json tokens still work"""
    print("\n" + "="*60)
    print("TEST 1: Old Dan.json Account Tokens")
    print("="*60)
    
    accounts = load_accounts()
    if not accounts:
        print("  No accounts found in Dan.json!")
        return
    
    print(f"  Found {len(accounts)} accounts")
    
    # Test first 3 accounts
    for i, acc in enumerate(accounts[:3]):
        email = acc.get('email', '?')
        token = acc.get('x-token', '')
        device = acc.get('x-client-device-id', '')
        
        print(f"\n  --- Account {i+1}: {email} ---")
        print(f"  Token: {token[:30]}...")
        print(f"  Device: {device}")
        
        # Test: Check profile with old token
        print(f"\n  [Checking profile with old token]")
        profile = telicall_get_balance(token, device)
        
        # Test: Try making a call with old token
        print(f"\n  [Trying call with old token to +201118975909]")
        call_resp = telicall_make_call("+201118975909", token, device)
        
        print()

def test_fresh_session():
    """Test 2: Create fresh session and try call without verification"""
    print("\n" + "="*60)
    print("TEST 2: Fresh Session (Unverified) - Make Call")
    print("="*60)
    
    # Init
    print("\n  [Step 1: Initialize session]")
    token, device, headers = telicall_init()
    
    if not token:
        print("  FAILED to init session!")
        return
    
    print(f"  Fresh token: {token[:30]}...")
    
    # Try call WITHOUT verification
    print(f"\n  [Step 2: Try call WITHOUT email verification]")
    call_resp = telicall_make_call("+201118975909", token, device)
    
    # Check profile
    print(f"\n  [Step 3: Check profile]")
    profile = telicall_get_balance(token, device)

def test_full_flow():
    """Test 3: Full flow - init → create email → verify → call"""
    print("\n" + "="*60)
    print("TEST 3: Full Flow (Init → Email → Verify → Call)")
    print("="*60)
    
    # Step 1: Init session
    print("\n  [Step 1: Initialize session]")
    token, device, headers = telicall_init()
    
    if not token:
        print("  FAILED to init session!")
        return
    
    headers["x-token"] = token
    print(f"  Fresh token: {token[:30]}...")
    
    # Step 2: Create email via Instant Mail
    print("\n  [Step 2: Create temp email via Instant Mail]")
    email, inbox_id = instantmail_create_inbox()
    
    if not email:
        print("  FAILED to create email!")
        return
    
    # Step 3: Send verification email
    print(f"\n  [Step 3: Send verification email to {email}]")
    ref, err = telicall_send_email(email, headers)
    
    if not ref:
        print(f"  FAILED to send verification: {err}")
        return
    
    print(f"  Reference: {ref}")
    
    # Step 4: Read OTP from email
    print(f"\n  [Step 4: Reading OTP from email (polling for 90s)]")
    deadline = time.time() + 90
    
    while time.time() < deadline:
        messages = instantmail_get_messages(inbox_id)
        if messages:
            print(f"  Got {len(messages)} messages!")
            for msg in messages:
                print(f"  Message: {json.dumps(msg, indent=2)[:500]}")
                
                # Try to extract OTP
                text_parts = []
                if isinstance(msg, dict):
                    for field in ['body', 'text', 'content', 'html', 'message', 'subject', 'snippet']:
                        val = msg.get(field, '')
                        if val:
                            text_parts.append(str(val))
                    if not text_parts:
                        for key, val in msg.items():
                            if isinstance(val, str) and len(val) > 5:
                                text_parts.append(val)
                
                combined = ' '.join(text_parts)
                # Clean HTML
                clean = re.sub(r'<[^>]+>', ' ', combined)
                m = re.search(r'\b(\d{6})\b', clean)
                if m:
                    otp = m.group(1)
                    print(f"\n  OTP FOUND: {otp}")
                    
                    # Step 5: Verify OTP
                    print(f"\n  [Step 5: Verify OTP]")
                    user, new_token, verify_err = telicall_verify_otp(ref, otp, headers)
                    
                    if user:
                        print(f"  ACCOUNT VERIFIED!")
                        print(f"  User: {json.dumps(user, indent=2)[:500]}")
                        
                        # Use new token if returned
                        call_token = new_token or token
                        
                        # Step 6: Make call
                        print(f"\n  [Step 6: Make call to +201118975909]")
                        call_resp = telicall_make_call("+201118975909", call_token, device)
                        
                        # Step 7: Check profile after verification
                        print(f"\n  [Step 7: Check profile after verification]")
                        profile = telicall_get_balance(call_token, device)
                        
                        return
                    else:
                        print(f"  Verification FAILED: {verify_err}")
                        return
        else:
            elapsed = int(time.time() - (deadline - 90))
            print(f"  No messages yet... ({elapsed}s)")
        
        time.sleep(3)
    
    print("\n  OTP TIMEOUT - no email received!")

def test_api_url():
    """Test which API URL works"""
    print("\n" + "="*60)
    print("TEST 0: API URL Check")
    print("="*60)
    
    for url in ["https://api.telicall.com", "https://api.telicall.io"]:
        try:
            r = requests.get(url, timeout=10)
            print(f"  {url}: HTTP {r.status_code} ({r.text[:100]})")
        except Exception as e:
            print(f"  {url}: {type(e).__name__}: {e}")


if __name__ == '__main__':
    print("╔══════════════════════════════════════════════════╗")
    print("║     🦊 Fox Caller Diagnostic Tool               ║")
    print("╚══════════════════════════════════════════════════╝")
    
    # Test 0: API URL
    test_api_url()
    
    # Test 1: Old accounts
    test_old_accounts()
    
    # Test 2: Fresh unverified session
    test_fresh_session()
    
    # Test 3: Full flow with email verification
    test_full_flow()
    
    print("\n\n" + "="*60)
    print("DIAGNOSTIC COMPLETE")
    print("="*60)
