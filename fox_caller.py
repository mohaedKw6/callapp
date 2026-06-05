#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Fox Caller SIP v3 - Fast Direct SIP Calling
=============================================
Makes real SIP calls via Telicall. No scanning, fast startup.

Usage:
  python3 fox_caller.py +201118975909
  python3 fox_caller.py +201118975909 +201234567890
  python3 fox_caller.py numbers.txt
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

API_URL = "https://api.telicall.com"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DAN_FILE = os.path.join(BASE_DIR, "Dan.json")
PASSWORD = "@@@GMAQ@@@"

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

def get_sip_credentials(phone, token, device_id):
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
            result = r.json().get('result', {})
            sip = result.get('sip', {})
            return {
                'success': True,
                'sip_user': sip.get('username', ''),
                'sip_pass': sip.get('password', ''),
                'sip_domain': sip.get('domain', ''),
                'call_limit': sip.get('callLimit', 60),
                'voip_register_time': sip.get('voipRegisterTime', 20),
                'from_num': result.get('from', {}).get('msisdn', ''),
                'to_num': result.get('to', {}).get('msisdn', phone),
            }
        elif r.status_code == 400:
            if 'balance' in r.text.lower() or 'insufficient' in r.text.lower():
                return {'success': False, 'error': 'NO_BALANCE'}
            return {'success': False, 'error': f'400: {r.text[:100]}'}
        elif r.status_code == 401:
            return {'success': False, 'error': 'UNAUTHORIZED'}
        return {'success': False, 'error': f'HTTP {r.status_code}'}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def sip_call(phone, sip_user, sip_pass, sip_domain, call_limit=60, voip_reg_time=20):
    """Make a real SIP call. Returns (status, details)."""
    
    # Resolve SIP server
    try:
        sip_ip = socket.gethostbyname(sip_domain)
    except:
        return 'DNS_FAIL', {}
    
    local_port = random.randint(50000, 60000)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(10)
    sock.bind(("0.0.0.0", local_port))
    our_ip = "10.0.0.1"
    
    try:
        # === REGISTER ===
        branch = f"z9hG4bK{uuid.uuid4().hex[:12]}"
        from_tag = uuid.uuid4().hex[:8]
        reg_call_id = f"{uuid.uuid4().hex[:16]}@{sip_domain}"
        
        reg1 = (
            f"REGISTER sip:{sip_domain} SIP/2.0\r\n"
            f"Via: SIP/2.0/UDP {our_ip}:{local_port};branch={branch};rport\r\n"
            f"From: <sip:{sip_user}@{sip_domain}>;tag={from_tag}\r\n"
            f"To: <sip:{sip_user}@{sip_domain}>\r\n"
            f"Call-ID: {reg_call_id}\r\n"
            f"CSeq: 1 REGISTER\r\n"
            f"Contact: <sip:{sip_user}@{our_ip}:{local_port}>\r\n"
            f"Allow: INVITE, ACK, CANCEL, BYE, OPTIONS\r\n"
            f"Expires: {voip_reg_time}\r\n"
            f"Max-Forwards: 70\r\n"
            f"Content-Length: 0\r\n\r\n"
        )
        
        sock.sendto(reg1.encode(), (sip_ip, 5060))
        data, _ = sock.recvfrom(8192)
        resp = data.decode(errors='replace')
        
        if "401" in resp.split('\r\n')[0]:
            realm_m = re.search(r'realm="([^"]+)"', resp)
            nonce_m = re.search(r'nonce="([^"]+)"', resp)
            if not (realm_m and nonce_m):
                return 'AUTH_FAIL', {}
            realm, nonce = realm_m.group(1), nonce_m.group(1)
            
            ha1 = hashlib.md5(f"{sip_user}:{realm}:{sip_pass}".encode()).hexdigest()
            ha2 = hashlib.md5(f"REGISTER:sip:{sip_domain}".encode()).hexdigest()
            resp_hash = hashlib.md5(f"{ha1}:{nonce}:{ha2}".encode()).hexdigest()
            
            reg2 = (
                f"REGISTER sip:{sip_domain} SIP/2.0\r\n"
                f"Via: SIP/2.0/UDP {our_ip}:{local_port};branch=z9hG4bK{uuid.uuid4().hex[:12]};rport\r\n"
                f"From: <sip:{sip_user}@{sip_domain}>;tag={from_tag}\r\n"
                f"To: <sip:{sip_user}@{sip_domain}>\r\n"
                f"Call-ID: {reg_call_id}\r\n"
                f"CSeq: 2 REGISTER\r\n"
                f"Contact: <sip:{sip_user}@{our_ip}:{local_port}>\r\n"
                f"Allow: INVITE, ACK, CANCEL, BYE, OPTIONS\r\n"
                f"Expires: {voip_reg_time}\r\n"
                f"Authorization: Digest username=\"{sip_user}\",realm=\"{realm}\",nonce=\"{nonce}\",uri=\"sip:{sip_domain}\",response=\"{resp_hash}\",algorithm=MD5\r\n"
                f"Max-Forwards: 70\r\n"
                f"Content-Length: 0\r\n\r\n"
            )
            
            sock.sendto(reg2.encode(), (sip_ip, 5060))
            data2, _ = sock.recvfrom(8192)
            resp2 = data2.decode(errors='replace')
            if "200 OK" not in resp2.split('\r\n')[0]:
                return 'REGISTER_FAIL', {}
        elif "200 OK" not in resp.split('\r\n')[0]:
            return 'REGISTER_FAIL', {}
        
        # === INVITE ===
        inv_branch = f"z9hG4bK{uuid.uuid4().hex[:12]}"
        inv_call_id = f"{uuid.uuid4().hex[:16]}@{our_ip}"
        inv_from_tag = uuid.uuid4().hex[:8]
        rtp_port = random.randint(10000, 20000)
        
        sdp = (
            f"v=0\r\no={sip_user} 0 0 IN IP4 {our_ip}\r\ns=-\r\n"
            f"c=IN IP4 {our_ip}\r\nt=0 0\r\n"
            f"m=audio {rtp_port} RTP/AVP 0 8 101\r\n"
            f"a=rtpmap:0 PCMU/8000\r\na=rtpmap:8 PCMA/8000\r\n"
            f"a=rtpmap:101 telephone-event/8000\r\na=sendrecv\r\n"
        )
        
        inv1 = (
            f"INVITE sip:{phone}@{sip_domain} SIP/2.0\r\n"
            f"Via: SIP/2.0/UDP {our_ip}:{local_port};branch={inv_branch};rport\r\n"
            f"From: <sip:{sip_user}@{sip_domain}>;tag={inv_from_tag}\r\n"
            f"To: <sip:{phone}@{sip_domain}>\r\n"
            f"Call-ID: {inv_call_id}\r\n"
            f"CSeq: 1 INVITE\r\n"
            f"Contact: <sip:{sip_user}@{our_ip}:{local_port}>\r\n"
            f"Allow: INVITE, ACK, CANCEL, BYE, OPTIONS\r\n"
            f"Content-Type: application/sdp\r\n"
            f"Content-Length: {len(sdp)}\r\n\r\n{sdp}"
        )
        
        sock.sendto(inv1.encode(), (sip_ip, 5060))
        
        result = 'FAILED'
        to_tag = ""
        ringing = False
        cseq = 1
        
        deadline = time.time() + 45
        
        while time.time() < deadline:
            sock.settimeout(5)
            try:
                data, _ = sock.recvfrom(8192)
                resp = data.decode(errors='replace')
                status = resp.split('\r\n')[0]
                
                to_m = re.search(r'To:.*tag=([a-zA-Z0-9]+)', resp)
                if to_m:
                    to_tag = to_m.group(1)
                
                if "100 Trying" in status:
                    continue
                elif "180 Ringing" in status or "183 Session" in status:
                    print(f"    📞 Ringing...", flush=True)
                    ringing = True
                    result = 'RINGING'
                    continue
                elif "200 OK" in status:
                    print(f"    ✅ ANSWERED!", flush=True)
                    result = 'ANSWERED'
                    
                    # ACK
                    ack = (
                        f"ACK sip:{phone}@{sip_domain} SIP/2.0\r\n"
                        f"Via: SIP/2.0/UDP {our_ip}:{local_port};branch={inv_branch};rport\r\n"
                        f"From: <sip:{sip_user}@{sip_domain}>;tag={inv_from_tag}\r\n"
                        f"To: <sip:{phone}@{sip_domain}>;tag={to_tag}\r\n"
                        f"Call-ID: {inv_call_id}\r\n"
                        f"CSeq: 1 ACK\r\n"
                        f"Content-Length: 0\r\n\r\n"
                    )
                    sock.sendto(ack.encode(), (sip_ip, 5060))
                    
                    # Wait for call duration
                    print(f"    ⏳ Call active ({call_limit}s)...", flush=True)
                    time.sleep(min(call_limit, 60))
                    
                    # BYE
                    bye = (
                        f"BYE sip:{phone}@{sip_domain} SIP/2.0\r\n"
                        f"Via: SIP/2.0/UDP {our_ip}:{local_port};branch=z9hG4bK{uuid.uuid4().hex[:12]};rport\r\n"
                        f"From: <sip:{sip_user}@{sip_domain}>;tag={inv_from_tag}\r\n"
                        f"To: <sip:{phone}@{sip_domain}>;tag={to_tag}\r\n"
                        f"Call-ID: {inv_call_id}\r\n"
                        f"CSeq: 2 BYE\r\n"
                        f"Content-Length: 0\r\n\r\n"
                    )
                    sock.sendto(bye.encode(), (sip_ip, 5060))
                    print(f"    📴 Call ended", flush=True)
                    break
                    
                elif "401" in status or "407" in status:
                    # Auth for INVITE
                    realm_m = re.search(r'realm="([^"]+)"', resp)
                    nonce_m = re.search(r'nonce="([^"]+)"', resp)
                    if realm_m and nonce_m:
                        realm, nonce = realm_m.group(1), nonce_m.group(1)
                        ha1 = hashlib.md5(f"{sip_user}:{realm}:{sip_pass}".encode()).hexdigest()
                        ha2 = hashlib.md5(f"INVITE:sip:{phone}@{sip_domain}".encode()).hexdigest()
                        resp_hash = hashlib.md5(f"{ha1}:{nonce}:{ha2}".encode()).hexdigest()
                        
                        cseq += 1
                        inv2 = (
                            f"INVITE sip:{phone}@{sip_domain} SIP/2.0\r\n"
                            f"Via: SIP/2.0/UDP {our_ip}:{local_port};branch=z9hG4bK{uuid.uuid4().hex[:12]};rport\r\n"
                            f"From: <sip:{sip_user}@{sip_domain}>;tag={inv_from_tag}\r\n"
                            f"To: <sip:{phone}@{sip_domain}>\r\n"
                            f"Call-ID: {inv_call_id}\r\n"
                            f"CSeq: {cseq} INVITE\r\n"
                            f"Contact: <sip:{sip_user}@{our_ip}:{local_port}>\r\n"
                            f"Allow: INVITE, ACK, CANCEL, BYE, OPTIONS\r\n"
                            f"Authorization: Digest username=\"{sip_user}\",realm=\"{realm}\",nonce=\"{nonce}\",uri=\"sip:{phone}@{sip_domain}\",response=\"{resp_hash}\",algorithm=MD5\r\n"
                            f"Content-Type: application/sdp\r\n"
                            f"Content-Length: {len(sdp)}\r\n\r\n{sdp}"
                        )
                        sock.sendto(inv2.encode(), (sip_ip, 5060))
                    continue
                elif "486" in status:
                    result = 'BUSY'
                    print(f"    📵 Busy", flush=True)
                    # Send ACK for error responses
                    ack_err = (
                        f"ACK sip:{phone}@{sip_domain} SIP/2.0\r\n"
                        f"Via: SIP/2.0/UDP {our_ip}:{local_port};branch={inv_branch};rport\r\n"
                        f"From: <sip:{sip_user}@{sip_domain}>;tag={inv_from_tag}\r\n"
                        f"To: <sip:{phone}@{sip_domain}>;tag={to_tag}\r\n"
                        f"Call-ID: {inv_call_id}\r\n"
                        f"CSeq: {cseq} ACK\r\n"
                        f"Content-Length: 0\r\n\r\n"
                    )
                    sock.sendto(ack_err.encode(), (sip_ip, 5060))
                    break
                elif "480" in status:
                    result = 'NO_ANSWER'
                    break
                elif "403" in status:
                    result = 'FORBIDDEN'
                    break
                elif "404" in status:
                    result = 'NOT_FOUND'
                    break
                elif "603" in status or "487" in status:
                    result = 'DECLINED'
                    break
                else:
                    # Unknown response, keep waiting
                    continue
                    
            except socket.timeout:
                if ringing:
                    continue
                break
        
        return result, {}
        
    except Exception as e:
        return f'ERROR: {e}', {}
    finally:
        sock.close()


def main():
    print("╔══════════════════════════════════════════════════╗", flush=True)
    print("║     🦊 Fox Caller v3 - SIP Direct               ║", flush=True)
    print("╚══════════════════════════════════════════════════╝", flush=True)
    
    accounts = load_accounts()
    if not accounts:
        print("❌ No accounts in Dan.json!", flush=True)
        sys.exit(1)
    
    print(f"  Accounts: {len(accounts)} loaded", flush=True)
    
    # Parse arguments
    if len(sys.argv) < 2:
        print("\nUsage: python3 fox_caller.py <phone> [phone2] ...", flush=True)
        print("       python3 fox_caller.py numbers.txt", flush=True)
        sys.exit(1)
    
    # Collect target numbers
    targets = []
    for arg in sys.argv[1:]:
        if os.path.isfile(arg):
            # Read from file
            with open(arg, 'r', encoding='utf-8', errors='ignore') as f:
                for line in f:
                    raw = line.strip().replace(' ', '').replace('-', '').replace('(', '').replace(')', '')
                    raw = raw.replace('\u202a', '').replace('\u202c', '')
                    digits = raw.lstrip('+')
                    if digits.isdigit() and len(digits) >= 8:
                        if not raw.startswith('+'):
                            raw = '+' + digits
                        targets.append(raw)
        else:
            # Single number
            raw = arg.replace(' ', '').replace('-', '')
            digits = raw.lstrip('+')
            if digits.isdigit() and len(digits) >= 8:
                if not raw.startswith('+'):
                    raw = '+' + digits
                targets.append(raw)
    
    if not targets:
        print("❌ No valid phone numbers!", flush=True)
        sys.exit(1)
    
    # Deduplicate
    seen = set()
    numbers = []
    for n in targets:
        if n not in seen:
            seen.add(n)
            numbers.append(n)
    
    print(f"  Numbers: {len(numbers)}", flush=True)
    for i, n in enumerate(numbers[:10]):
        print(f"    [{i+1}] {n}", flush=True)
    
    # Make calls - rotate through accounts
    results = []
    acc_idx = 0
    
    for i, phone in enumerate(numbers):
        # Find an account with balance
        found = False
        for attempt in range(len(accounts)):
            acc = accounts[acc_idx % len(accounts)]
            token = acc.get('x-token', '')
            device = acc.get('x-client-device-id', '')
            email = acc.get('email', '?')
            acc_idx += 1
            
            print(f"\n[{i+1}/{len(numbers)}] 📱 {phone}", flush=True)
            print(f"  Account: {email}", flush=True)
            
            # Get SIP credentials
            creds = get_sip_credentials(phone, token, device)
            
            if not creds.get('success'):
                err = creds.get('error', '?')
                if 'NO_BALANCE' in err:
                    print(f"  💸 No balance, trying next account...", flush=True)
                    continue
                elif 'UNAUTHORIZED' in err:
                    print(f"  🔒 Token expired, trying next...", flush=True)
                    continue
                else:
                    print(f"  ❌ Error: {err}", flush=True)
                    continue
            
            from_num = creds.get('from_num', '?')
            print(f"  From: {from_num}", flush=True)
            print(f"  SIP: {creds['sip_user'][:20]}...@{creds['sip_domain']}", flush=True)
            
            # Make the SIP call
            status, _ = sip_call(
                phone,
                creds['sip_user'],
                creds['sip_pass'],
                creds['sip_domain'],
                call_limit=creds.get('call_limit', 60),
                voip_reg_time=creds.get('voip_register_time', 20)
            )
            
            results.append({
                'phone': phone,
                'account': email,
                'from': from_num,
                'status': status,
            })
            
            found = True
            
            if status in ('ANSWERED', 'RINGING'):
                # Account used, move to next
                break
            elif status == 'BUSY':
                print(f"  Phone busy, will retry with different account...", flush=True)
                # Try another account
                continue
            else:
                break
        
        if not found:
            results.append({
                'phone': phone,
                'account': '?',
                'from': '?',
                'status': 'ALL_ACCOUNTS_FAILED',
            })
        
        # Small delay between calls
        if i < len(numbers) - 1:
            time.sleep(2)
    
    # Summary
    print(f"\n{'='*55}", flush=True)
    print(f"  Fox Caller - Summary", flush=True)
    print(f"{'='*55}", flush=True)
    
    answered = sum(1 for r in results if r['status'] == 'ANSWERED')
    ringing = sum(1 for r in results if r['status'] == 'RINGING')
    busy = sum(1 for r in results if r['status'] == 'BUSY')
    failed = sum(1 for r in results if r['status'] not in ('ANSWERED', 'RINGING'))
    
    print(f"  Total:    {len(results)}", flush=True)
    print(f"  Answered: {answered}", flush=True)
    print(f"  Ringing:  {ringing}", flush=True)
    print(f"  Busy:     {busy}", flush=True)
    print(f"  Failed:   {failed}", flush=True)
    
    for r in results:
        if r['status'] == 'ANSWERED':
            icon = '✅'
        elif r['status'] == 'RINGING':
            icon = '📞'
        elif r['status'] == 'BUSY':
            icon = '📵'
        else:
            icon = '❌'
        print(f"  {icon} {r['phone']} ← {r['from']} ({r['status']})", flush=True)


if __name__ == '__main__':
    main()
