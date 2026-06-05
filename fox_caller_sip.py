#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Fox Caller SIP v2 - Full Auto SIP Calling via Telicall
========================================================
Makes ACTUAL phone calls using Telicall's SIP infrastructure.

How it works:
  1. Get SIP credentials from Telicall API (/call/outbound/start)
  2. REGISTER with SIP server (authentication)
  3. Send INVITE to target phone number
  4. Call connects, wait for duration
  5. Send BYE to end call

Uses raw SIP protocol over UDP (no extra dependencies needed!)

Usage:
  python3 fox_caller_sip.py +201118975909
  python3 fox_caller_sip.py +201118975909 --duration 30
  python3 fox_caller_sip.py numbers.txt
  python3 fox_caller_sip.py numbers.xlsx
"""

import requests
import json
import uuid
import time
import random
import base64
import hashlib
import os
import sys
import socket
import re
import threading

# ═══════════════════════════════════════════════════════
# Config
# ═══════════════════════════════════════════════════════
API_URL = "https://api.telicall.com"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DAN_FILE = os.path.join(BASE_DIR, "Dan.json")
PASSWORD = "@@@GMAQ@@@"

# Egyptian IP ranges (for x-real-ip header)
_EG_RANGES = [
    (41, 32), (41, 33), (41, 34), (41, 35), (41, 36),
    (41, 37), (41, 38), (41, 39), (41, 40), (41, 41),
    (41, 42), (41, 43), (41, 44), (41, 45), (41, 46),
    (41, 47), (41, 48), (41, 49), (41, 50), (41, 51),
    (156, 192), (156, 193), (156, 194), (156, 195),
    (156, 196), (156, 197), (156, 198), (156, 199),
    (197, 32), (197, 33), (197, 34), (197, 35),
    (102, 156), (102, 157), (102, 158), (102, 159),
    (154, 128), (154, 129), (154, 130), (154, 131),
]

_stats_lock = threading.Lock()
_stats = {"calls_made": 0, "calls_ringing": 0, "calls_answered": 0,
          "calls_busy": 0, "calls_failed": 0, "no_balance": 0,
          "register_fail": 0, "total_attempted": 0}


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
# Telicall API - Get SIP Credentials
# ═══════════════════════════════════════════════════════
def get_sip_credentials(phone, token, device_id):
    """Get SIP credentials from Telicall API"""
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
        if r.status_code == 200:
            data = r.json()
            result = data.get('result', {})
            sip = result.get('sip', {})
            return {
                'success': True,
                'sip_user': sip.get('username', ''),
                'sip_pass': sip.get('password', ''),
                'sip_domain': sip.get('domain', ''),
                'sip_port': sip.get('port', 5061),
                'sip_protocol': sip.get('protocol', 'tls'),
                'call_limit': sip.get('callLimit', 60),
                'balance_limit': sip.get('balanceLimit', 60),
                'timeout': sip.get('timeout', 28),
                'ch_delay': sip.get('chDelay', 2500),
                'voip_register_time': sip.get('voipRegisterTime', 20),
                'call_id': result.get('callId', ''),
                'from_num': result.get('from', {}).get('msisdn', ''),
                'to_num': result.get('to', {}).get('msisdn', phone),
            }
        elif r.status_code == 400:
            err = r.text.lower()
            if 'balance' in err or 'insufficient' in err:
                return {'success': False, 'error': 'NO_BALANCE'}
            return {'success': False, 'error': f'400: {r.text[:200]}'}
        elif r.status_code == 401:
            return {'success': False, 'error': 'UNAUTHORIZED'}
        else:
            return {'success': False, 'error': f'HTTP {r.status_code}'}
    except Exception as e:
        return {'success': False, 'error': str(e)}


# ═══════════════════════════════════════════════════════
# SIP Client - Raw UDP SIP
# ═══════════════════════════════════════════════════════
class SIPCallResult:
    RINGING = "ringing"
    ANSWERED = "answered"
    BUSY = "busy"
    NO_ANSWER = "no_answer"
    FAILED = "failed"
    UNAVAILABLE = "unavailable"
    DECLINED = "declined"


def sip_register(sock, sip_ip, sip_port, sip_user, sip_pass, sip_domain, local_port, our_ip, voip_register_time=20):
    """Register with SIP server. Returns True on success."""
    branch_tag = f"z9hG4bK{uuid.uuid4().hex[:12]}"
    from_tag = uuid.uuid4().hex[:8]
    call_id = f"{uuid.uuid4().hex[:16]}@{sip_domain}"
    
    register_msg = (
        f"REGISTER sip:{sip_domain} SIP/2.0\r\n"
        f"Via: SIP/2.0/UDP {our_ip}:{local_port};branch={branch_tag};rport\r\n"
        f"From: <sip:{sip_user}@{sip_domain}>;tag={from_tag}\r\n"
        f"To: <sip:{sip_user}@{sip_domain}>\r\n"
        f"Call-ID: {call_id}\r\n"
        f"CSeq: 1 REGISTER\r\n"
        f"Contact: <sip:{sip_user}@{our_ip}:{local_port}>\r\n"
        f"Allow: INVITE, ACK, CANCEL, BYE, OPTIONS\r\n"
        f"Expires: {voip_register_time}\r\n"
        f"Max-Forwards: 70\r\n"
        f"Content-Length: 0\r\n"
        f"\r\n"
    )
    
    sock.sendto(register_msg.encode(), (sip_ip, sip_port))
    
    try:
        data, addr = sock.recvfrom(8192)
        response = data.decode(errors='replace')
        status_line = response.split('\r\n')[0] if '\r\n' in response else response.split('\n')[0]
        
        if "401" in status_line or "407" in status_line:
            # Need authentication
            realm_match = re.search(r'realm="([^"]+)"', response)
            nonce_match = re.search(r'nonce="([^"]+)"', response)
            algorithm_match = re.search(r'algorithm=([A-Za-z0-9-]+)', response)
            algorithm = algorithm_match.group(1) if algorithm_match else "MD5"
            
            if realm_match and nonce_match:
                realm = realm_match.group(1)
                nonce = nonce_match.group(1)
                
                if algorithm.upper() == "MD5" or algorithm.upper() == "AKAv1-MD5":
                    # For AKAv1-MD5, we still use MD5 digest (SIP digest auth)
                    ha1 = hashlib.md5(f"{sip_user}:{realm}:{sip_pass}".encode()).hexdigest()
                    ha2 = hashlib.md5(f"REGISTER:sip:{sip_domain}".encode()).hexdigest()
                    response_hash = hashlib.md5(f"{ha1}:{nonce}:{ha2}".encode()).hexdigest()
                else:
                    ha1 = hashlib.md5(f"{sip_user}:{realm}:{sip_pass}".encode()).hexdigest()
                    ha2 = hashlib.md5(f"REGISTER:sip:{sip_domain}".encode()).hexdigest()
                    response_hash = hashlib.md5(f"{ha1}:{nonce}:{ha2}".encode()).hexdigest()
                
                new_branch = f"z9hG4bK{uuid.uuid4().hex[:12]}"
                
                register_auth = (
                    f"REGISTER sip:{sip_domain} SIP/2.0\r\n"
                    f"Via: SIP/2.0/UDP {our_ip}:{local_port};branch={new_branch};rport\r\n"
                    f"From: <sip:{sip_user}@{sip_domain}>;tag={from_tag}\r\n"
                    f"To: <sip:{sip_user}@{sip_domain}>\r\n"
                    f"Call-ID: {call_id}\r\n"
                    f"CSeq: 2 REGISTER\r\n"
                    f"Contact: <sip:{sip_user}@{our_ip}:{local_port}>\r\n"
                    f"Allow: INVITE, ACK, CANCEL, BYE, OPTIONS\r\n"
                    f"Expires: {voip_register_time}\r\n"
                    f"Max-Forwards: 70\r\n"
                    f"Authorization: Digest username=\"{sip_user}\",realm=\"{realm}\",nonce=\"{nonce}\",uri=\"sip:{sip_domain}\",response=\"{response_hash}\",algorithm=MD5\r\n"
                    f"Content-Length: 0\r\n"
                    f"\r\n"
                )
                
                sock.sendto(register_auth.encode(), (sip_ip, sip_port))
                
                try:
                    data2, addr2 = sock.recvfrom(8192)
                    response2 = data2.decode(errors='replace')
                    status2 = response2.split('\r\n')[0] if '\r\n' in response2 else response2.split('\n')[0]
                    return "200 OK" in status2
                except socket.timeout:
                    return False
            return False
        elif "200 OK" in status_line:
            return True
        return False
    except socket.timeout:
        return False


def sip_invite(sock, sip_ip, sip_port, sip_user, sip_pass, sip_domain, target_phone, 
               local_port, our_ip, call_limit=60):
    """Send INVITE and handle the call. Returns SIPCallResult."""
    
    invite_branch = f"z9hG4bK{uuid.uuid4().hex[:12]}"
    invite_call_id = f"{uuid.uuid4().hex[:16]}@{our_ip}"
    invite_from_tag = uuid.uuid4().hex[:8]
    
    # SDP body for audio call
    rtp_port = random.randint(10000, 20000)
    sdp_body = (
        f"v=0\r\n"
        f"o={sip_user} 0 0 IN IP4 {our_ip}\r\n"
        f"s=-\r\n"
        f"c=IN IP4 {our_ip}\r\n"
        f"t=0 0\r\n"
        f"m=audio {rtp_port} RTP/AVP 0 8 101\r\n"
        f"a=rtpmap:0 PCMU/8000\r\n"
        f"a=rtpmap:8 PCMA/8000\r\n"
        f"a=rtpmap:101 telephone-event/8000\r\n"
        f"a=sendrecv\r\n"
    )
    
    invite_msg = (
        f"INVITE sip:{target_phone}@{sip_domain} SIP/2.0\r\n"
        f"Via: SIP/2.0/UDP {our_ip}:{local_port};branch={invite_branch};rport\r\n"
        f"From: <sip:{sip_user}@{sip_domain}>;tag={invite_from_tag}\r\n"
        f"To: <sip:{target_phone}@{sip_domain}>\r\n"
        f"Call-ID: {invite_call_id}\r\n"
        f"CSeq: 1 INVITE\r\n"
        f"Contact: <sip:{sip_user}@{our_ip}:{local_port}>\r\n"
        f"Allow: INVITE, ACK, CANCEL, BYE, OPTIONS\r\n"
        f"Supported: replaces, outbound\r\n"
        f"Content-Type: application/sdp\r\n"
        f"Content-Length: {len(sdp_body)}\r\n"
        f"\r\n"
        f"{sdp_body}"
    )
    
    sock.sendto(invite_msg.encode(), (sip_ip, sip_port))
    
    result = SIPCallResult.FAILED
    to_tag = ""
    invite_cseq = 1
    answered = False
    
    deadline = time.time() + 45  # Wait up to 45s for answer
    
    while time.time() < deadline:
        sock.settimeout(5)
        try:
            data, addr = sock.recvfrom(8192)
            response = data.decode(errors='replace')
            status_line = response.split('\r\n')[0] if '\r\n' in response else response.split('\n')[0]
            
            # Extract To tag if present
            to_tag_match = re.search(r'To:.*tag=([a-zA-Z0-9]+)', response)
            if to_tag_match:
                to_tag = to_tag_match.group(1)
            
            if "100 Trying" in status_line:
                continue
            elif "180 Ringing" in status_line:
                print(f"    📞 RINGING!", flush=True)
                with _stats_lock:
                    _stats["calls_ringing"] += 1
                result = SIPCallResult.RINGING
                continue
            elif "183 Session Progress" in status_line:
                print(f"    📞 Ringing...", flush=True)
                with _stats_lock:
                    _stats["calls_ringing"] += 1
                result = SIPCallResult.RINGING
                continue
            elif "200 OK" in status_line:
                print(f"    ✅ ANSWERED!", flush=True)
                with _stats_lock:
                    _stats["calls_answered"] += 1
                result = SIPCallResult.ANSWERED
                answered = True
                
                # Send ACK
                ack_msg = (
                    f"ACK sip:{target_phone}@{sip_domain} SIP/2.0\r\n"
                    f"Via: SIP/2.0/UDP {our_ip}:{local_port};branch={invite_branch};rport\r\n"
                    f"From: <sip:{sip_user}@{sip_domain}>;tag={invite_from_tag}\r\n"
                    f"To: <sip:{target_phone}@{sip_domain}>;tag={to_tag}\r\n"
                    f"Call-ID: {invite_call_id}\r\n"
                    f"CSeq: 1 ACK\r\n"
                    f"Content-Length: 0\r\n"
                    f"\r\n"
                )
                sock.sendto(ack_msg.encode(), (sip_ip, sip_port))
                
                # Wait for call duration
                print(f"    ⏳ Call active ({call_limit}s)...", flush=True)
                time.sleep(min(call_limit, 60))
                
                # Send BYE
                bye_msg = (
                    f"BYE sip:{target_phone}@{sip_domain} SIP/2.0\r\n"
                    f"Via: SIP/2.0/UDP {our_ip}:{local_port};branch=z9hG4bK{uuid.uuid4().hex[:12]};rport\r\n"
                    f"From: <sip:{sip_user}@{sip_domain}>;tag={invite_from_tag}\r\n"
                    f"To: <sip:{target_phone}@{sip_domain}>;tag={to_tag}\r\n"
                    f"Call-ID: {invite_call_id}\r\n"
                    f"CSeq: 2 BYE\r\n"
                    f"Content-Length: 0\r\n"
                    f"\r\n"
                )
                sock.sendto(bye_msg.encode(), (sip_ip, sip_port))
                print(f"    📴 Call ended", flush=True)
                break
                
            elif "401" in status_line or "407" in status_line:
                # Need auth for INVITE
                realm_match = re.search(r'realm="([^"]+)"', response)
                nonce_match = re.search(r'nonce="([^"]+)"', response)
                
                if realm_match and nonce_match:
                    realm = realm_match.group(1)
                    nonce = nonce_match.group(1)
                    
                    ha1 = hashlib.md5(f"{sip_user}:{realm}:{sip_pass}".encode()).hexdigest()
                    ha2 = hashlib.md5(f"INVITE:sip:{target_phone}@{sip_domain}".encode()).hexdigest()
                    response_hash = hashlib.md5(f"{ha1}:{nonce}:{ha2}".encode()).hexdigest()
                    
                    invite_cseq += 1
                    new_invite_branch = f"z9hG4bK{uuid.uuid4().hex[:12]}"
                    
                    invite_auth = (
                        f"INVITE sip:{target_phone}@{sip_domain} SIP/2.0\r\n"
                        f"Via: SIP/2.0/UDP {our_ip}:{local_port};branch={new_invite_branch};rport\r\n"
                        f"From: <sip:{sip_user}@{sip_domain}>;tag={invite_from_tag}\r\n"
                        f"To: <sip:{target_phone}@{sip_domain}>\r\n"
                        f"Call-ID: {invite_call_id}\r\n"
                        f"CSeq: {invite_cseq} INVITE\r\n"
                        f"Contact: <sip:{sip_user}@{our_ip}:{local_port}>\r\n"
                        f"Allow: INVITE, ACK, CANCEL, BYE, OPTIONS\r\n"
                        f"Authorization: Digest username=\"{sip_user}\",realm=\"{realm}\",nonce=\"{nonce}\",uri=\"sip:{target_phone}@{sip_domain}\",response=\"{response_hash}\",algorithm=MD5\r\n"
                        f"Content-Type: application/sdp\r\n"
                        f"Content-Length: {len(sdp_body)}\r\n"
                        f"\r\n"
                        f"{sdp_body}"
                    )
                    
                    sock.sendto(invite_auth.encode(), (sip_ip, sip_port))
                continue
                
            elif "403" in status_line:
                result = SIPCallResult.DECLINED
                break
            elif "404" in status_line:
                result = SIPCallResult.UNAVAILABLE
                break
            elif "480" in status_line:
                result = SIPCallResult.NO_ANSWER
                break
            elif "486" in status_line:
                print(f"    📵 Busy", flush=True)
                result = SIPCallResult.BUSY
                with _stats_lock:
                    _stats["calls_busy"] += 1
                break
            elif "487" in status_line:
                result = SIPCallResult.NO_ANSWER
                break
            elif "600" in status_line:
                result = SIPCallResult.BUSY
                break
            elif "603" in status_line:
                result = SIPCallResult.DECLINED
                break
            elif status_line.startswith("SIP/2.0 5") or status_line.startswith("SIP/2.0 6"):
                result = SIPCallResult.FAILED
                break
                
        except socket.timeout:
            if result == SIPCallResult.RINGING:
                # Still ringing, keep waiting
                continue
            elif answered:
                break
            continue
        except Exception as e:
            print(f"    Error: {e}", flush=True)
            break
    
    return result


def make_call(phone, token, device_id, duration=60):
    """
    Make a complete SIP call to a phone number.
    Returns SIPCallResult.
    """
    # Step 1: Get SIP credentials
    creds = get_sip_credentials(phone, token, device_id)
    
    if not creds.get('success'):
        err = creds.get('error', 'unknown')
        if 'NO_BALANCE' in err:
            return 'NO_BALANCE', creds
        return err, creds
    
    sip_user = creds['sip_user']
    sip_pass = creds['sip_pass']
    sip_domain = creds['sip_domain']
    call_limit = min(creds.get('call_limit', duration), duration)
    voip_reg_time = creds.get('voip_register_time', 20)
    from_num = creds.get('from_num', '')
    
    # Resolve SIP server
    try:
        sip_ip = socket.gethostbyname(sip_domain)
    except:
        return 'DNS_FAIL', creds
    
    # Create UDP socket
    local_port = random.randint(50000, 60000)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(10)
    try:
        sock.bind(("0.0.0.0", local_port))
    except:
        local_port = random.randint(40000, 50000)
        sock.bind(("0.0.0.0", local_port))
    
    our_ip = "10.0.0.1"
    sip_port = 5060  # Use UDP 5060
    
    try:
        # Step 2: REGISTER
        reg_ok = sip_register(sock, sip_ip, sip_port, sip_user, sip_pass, 
                              sip_domain, local_port, our_ip, voip_reg_time)
        
        if not reg_ok:
            with _stats_lock:
                _stats["register_fail"] += 1
            return 'REGISTER_FAIL', creds
        
        # Step 3: INVITE (make the call)
        result = sip_invite(sock, sip_ip, sip_port, sip_user, sip_pass, sip_domain,
                           phone, local_port, our_ip, call_limit)
        
        with _stats_lock:
            _stats["calls_made"] += 1
        
        return result, creds
        
    finally:
        sock.close()


def read_numbers(filepath):
    """Read phone numbers from xlsx or txt file"""
    numbers = []
    
    if filepath.endswith(('.xlsx', '.xls')):
        try:
            import openpyxl
            wb = openpyxl.load_workbook(filepath, read_only=True)
            ws = wb.active
            for row in ws.iter_rows(values_only=True):
                for cell in row:
                    if cell is not None:
                        raw = str(cell).strip()
                        raw = raw.replace(' ', '').replace('-', '').replace('(', '').replace(')', '')
                        raw = raw.replace('\u202a', '').replace('\u202c', '')
                        digits = raw.lstrip('+')
                        if digits.isdigit() and len(digits) >= 8:
                            if not raw.startswith('+'):
                                raw = '+' + digits
                            numbers.append(raw)
            wb.close()
        except Exception as e:
            print(f"Error reading xlsx: {e}", flush=True)
    else:
        try:
            with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                for line in f:
                    raw = line.strip()
                    if not raw:
                        continue
                    raw = raw.replace(' ', '').replace('-', '').replace('(', '').replace(')', '')
                    digits = raw.lstrip('+')
                    if digits.isdigit() and len(digits) >= 8:
                        if not raw.startswith('+'):
                            raw = '+' + digits
                        numbers.append(raw)
        except Exception as e:
            print(f"Error reading file: {e}", flush=True)
    
    # Deduplicate
    seen = set()
    unique = []
    for n in numbers:
        if n not in seen:
            seen.add(n)
            unique.append(n)
    return unique


def main():
    print("╔══════════════════════════════════════════════════╗", flush=True)
    print("║     🦊 Fox Caller SIP v2 - Real Calls           ║", flush=True)
    print("╚══════════════════════════════════════════════════╝", flush=True)
    
    # Load accounts
    accounts = load_accounts()
    if not accounts:
        print("❌ No accounts found in Dan.json!", flush=True)
        sys.exit(1)
    
    # Filter accounts with balance
    print(f"\n  Scanning {len(accounts)} accounts for balance...", flush=True)
    working_accounts = []
    for acc in accounts:
        token = acc.get('x-token', '')
        device = acc.get('x-client-device-id', '')
        email = acc.get('email', '?')
        
        # Quick balance check - try to get SIP credentials
        creds = get_sip_credentials("+201000000000", token, device)
        if creds.get('success'):
            working_accounts.append(acc)
            print(f"  ✅ {email} - Has balance (from: {creds.get('from_num', '?')})", flush=True)
        elif 'NO_BALANCE' in creds.get('error', ''):
            print(f"  💸 {email} - No balance", flush=True)
        else:
            err = creds.get('error', '?')
            print(f"  ❌ {email} - {err[:40]}", flush=True)
        
        time.sleep(0.5)
    
    print(f"\n  Working accounts: {len(working_accounts)}/{len(accounts)}", flush=True)
    
    if not working_accounts:
        print("❌ No accounts with balance found!", flush=True)
        sys.exit(1)
    
    # Get target phone number(s)
    if len(sys.argv) < 2:
        print("\nUsage: python3 fox_caller_sip.py <phone_number|file>", flush=True)
        print("  python3 fox_caller_sip.py +201118975909", flush=True)
        print("  python3 fox_caller_sip.py numbers.txt", flush=True)
        print("  python3 fox_caller_sip.py numbers.xlsx", flush=True)
        sys.exit(1)
    
    target = sys.argv[1]
    
    # Check if it's a file or a number
    if os.path.isfile(target):
        numbers = read_numbers(target)
        print(f"  Loaded {len(numbers)} numbers from {target}", flush=True)
    else:
        # Normalize phone number
        digits = target.lstrip('+').replace(' ', '').replace('-', '')
        if not target.startswith('+'):
            target = '+' + digits
        numbers = [target]
    
    for i, num in enumerate(numbers[:5]):
        print(f"    [{i+1}] {num}", flush=True)
    if len(numbers) > 5:
        print(f"    ... and {len(numbers)-5} more", flush=True)
    
    # Make calls
    print(f"\n{'='*55}", flush=True)
    print(f"  Starting calls...", flush=True)
    print(f"{'='*55}", flush=True)
    
    call_results = []
    
    for i, phone in enumerate(numbers):
        acc = working_accounts[i % len(working_accounts)]
        token = acc.get('x-token', '')
        device = acc.get('x-client-device-id', '')
        email = acc.get('email', '?')
        
        with _stats_lock:
            _stats["total_attempted"] += 1
        
        print(f"\n[{i+1}/{len(numbers)}] 📱 {phone} via {email}", flush=True)
        
        result, creds = make_call(phone, token, device)
        
        from_num = creds.get('from_num', '?') if isinstance(creds, dict) else '?'
        
        if result == SIPCallResult.ANSWERED:
            print(f"  ✅ ANSWERED ← {from_num}", flush=True)
        elif result == SIPCallResult.RINGING:
            print(f"  📞 RANG (no answer) ← {from_num}", flush=True)
        elif result == SIPCallResult.BUSY:
            print(f"  📵 BUSY ← {from_num}", flush=True)
        elif result == 'NO_BALANCE':
            print(f"  💸 No balance", flush=True)
            with _stats_lock:
                _stats["no_balance"] += 1
        elif result == SIPCallResult.NO_ANSWER:
            print(f"  ⏰ No answer ← {from_num}", flush=True)
        elif result == 'REGISTER_FAIL':
            print(f"  ❌ SIP Register failed", flush=True)
        else:
            print(f"  ❌ {result} ← {from_num}", flush=True)
        
        call_results.append({
            'phone': phone,
            'account': email,
            'from': from_num,
            'result': result,
        })
        
        # Delay between calls
        if i < len(numbers) - 1:
            time.sleep(2)
    
    # Final report
    with _stats_lock:
        s = dict(_stats)
    
    print(f"\n{'='*55}", flush=True)
    print(f"  Fox Caller SIP - Final Report", flush=True)
    print(f"{'='*55}", flush=True)
    print(f"  Total Attempted: {s['total_attempted']}", flush=True)
    print(f"  SIP Calls Made:  {s['calls_made']}", flush=True)
    print(f"  Ringing:         {s['calls_ringing']}", flush=True)
    print(f"  Answered:        {s['calls_answered']}", flush=True)
    print(f"  Busy:            {s['calls_busy']}", flush=True)
    print(f"  No Balance:      {s['no_balance']}", flush=True)
    print(f"  Register Failed: {s['register_fail']}", flush=True)
    print(f"  Other Failed:    {s['calls_failed']}", flush=True)
    
    print(f"\n  Call Details:", flush=True)
    for cr in call_results:
        if cr['result'] == SIPCallResult.ANSWERED:
            icon = "✅"
        elif cr['result'] == SIPCallResult.RINGING:
            icon = "📞"
        elif cr['result'] == SIPCallResult.BUSY:
            icon = "📵"
        else:
            icon = "❌"
        print(f"    {icon} {cr['phone']} ← {cr['from']} ({cr['result']})", flush=True)


if __name__ == '__main__':
    main()
