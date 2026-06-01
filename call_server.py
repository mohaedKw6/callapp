#!/usr/bin/env python3
"""
Fox Call Server - SIP Call Manager
===================================
FastAPI server that manages SIP calls via Telicall API.
Receives account+number from clients, makes the SIP call on the server,
and tracks call status so clients can check if a call is still active.

Endpoints:
  POST /call/start   - Start a new call (returns call_id)
  GET  /call/{id}    - Check call status
  GET  /calls        - List all calls
  DELETE /call/{id}  - Cancel/end a call
"""

import os
import re
import sys
import uuid
import time
import socket
import struct
import hashlib
import random
import threading
import warnings
warnings.filterwarnings('ignore', category=DeprecationWarning)

import audioop
import requests
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
from datetime import datetime

# ============================================================================
#                            CONFIGURATION
# ============================================================================

API_URL = "https://api.telicall.com"
SIP_CONNECT_TIMEOUT = 10
RECV_TIMEOUT = 5
RINGING_TIMEOUT = 80          # SIP loop iterations (80 * 0.5s = 40s ringing max)
MAX_CALL_DURATION = 600       # 10 min max call duration (safety limit)
INSTANT_BYE_CHECKS = 3

# Egyptian IP ranges for x-real-ip header
_EG_RANGES = [
    (41, 32), (41, 33), (41, 34), (41, 35), (41, 36),
    (41, 37), (41, 38), (41, 39), (41, 40), (41, 41),
    (41, 42), (41, 43), (41, 44), (41, 45), (41, 46),
    (41, 47), (41, 48), (41, 49), (41, 50), (41, 51),
    (41, 52), (41, 53), (41, 54), (41, 55), (41, 56),
    (41, 57), (41, 58), (41, 59), (41, 60), (41, 61),
    (156, 192), (156, 193), (156, 194), (156, 195),
    (156, 196), (156, 197), (156, 198), (156, 199),
    (156, 200), (156, 201), (156, 202), (156, 203),
    (197, 32), (197, 33), (197, 34), (197, 35),
    (197, 36), (197, 37), (197, 38), (197, 39),
    (197, 40), (197, 41), (197, 42), (197, 43),
]

def _rand_eg_ip():
    """Generate a random Egyptian IP for x-real-ip header."""
    a, b = random.choice(_EG_RANGES)
    c = random.randint(1, 254)
    d = random.randint(1, 254)
    return f"{a}.{b}.{c}.{d}"


# ============================================================================
#                              SIP CLASS
# ============================================================================

class SIP:
    """SIP client for making VoIP calls via Telicall."""

    def __init__(self, u, p, d, pt, pr='tcp'):
        self.u, self.p, self.d, self.pt, self.pr = u, p, d, pt, pr
        self.lp = random.randint(50000, 60000)
        self.rtp_port = self.lp + 2
        self.tag = uuid.uuid4().hex[:8]
        self.seq = 1
        self.sk = None
        self.rs = self.rn = self.ro = self.rq = None
        self.br = self.cid = None
        self.rtp_sk = None
        self.rtp_run = False
        self.audio = []
        self.rtp_ip = None
        self.rtp_pt = None
        self.ssrc = random.randint(1000000, 9999999)
        self.rtp_seq = 0
        self.rtp_ts = 0
        self.remote_tag = None
        self._from_num = ''

    def conn(self):
        try:
            self.sk = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sk.settimeout(SIP_CONNECT_TIMEOUT)
            if self.pr == 'tls':
                import ssl
                context = ssl.create_default_context()
                context.check_hostname = False
                context.verify_mode = ssl.CERT_NONE
                self.sk = context.wrap_socket(self.sk, server_hostname=self.d)
            self.sk.connect((self.d, self.pt))
            return True
        except Exception as e:
            print(f"  [SIP] conn() FAILED: {e}")
            return False

    def _pauth(self, h):
        for k, p in [('rs', r'realm="([^"]+)"'), ('rn', r'nonce="([^"]+)"'),
                     ('ro', r'opaque="([^"]+)"'), ('rq', r'qop="([^"]+)"')]:
            m = re.search(p, h)
            if m:
                setattr(self, k, m.group(1))

    def _auth(self, method, uri):
        if not self.rs or not self.rn:
            return None
        h1 = hashlib.md5(f"{self.u}:{self.rs}:{self.p}".encode()).hexdigest()
        h2 = hashlib.md5(f"{method}:{uri}".encode()).hexdigest()
        if self.rq:
            nc, cn = "00000001", uuid.uuid4().hex[:8]
            rp = hashlib.md5(f"{h1}:{self.rn}:{nc}:{cn}:{self.rq}:{h2}".encode()).hexdigest()
            return (f'Digest username="{self.u}",realm="{self.rs}",nonce="{self.rn}",'
                    f'uri="{uri}",response="{rp}",opaque="{self.ro}",'
                    f'qop={self.rq},nc={nc},cnonce="{cn}",algorithm=MD5')
        rp = hashlib.md5(f"{h1}:{self.rn}:{h2}".encode()).hexdigest()
        return (f'Digest username="{self.u}",realm="{self.rs}",nonce="{self.rn}",'
                f'uri="{uri}",response="{rp}",opaque="{self.ro}",algorithm=MD5')

    def send(self, msg):
        try:
            if isinstance(msg, str):
                msg = msg.encode()
            self.sk.send(msg)
            return True
        except:
            return False

    def recv(self, timeout=RECV_TIMEOUT):
        try:
            self.sk.settimeout(timeout)
            data = b''
            while True:
                chunk = self.sk.recv(4096)
                if not chunk:
                    break
                data += chunk
                if b'\r\n\r\n' in data:
                    try:
                        header = data.split(b'\r\n\r\n')[0].decode('utf-8', errors='ignore')
                        cl = re.search(r'Content-Length:\s*(\d+)', header, re.IGNORECASE)
                        if cl:
                            body_start = data.find(b'\r\n\r\n') + 4
                            if len(data) >= body_start + int(cl.group(1)):
                                break
                        else:
                            break
                    except:
                        break
            return data.decode('utf-8', errors='ignore')
        except:
            return None

    def parse(self, resp):
        if not resp:
            return None
        lines = resp.split('\r\n')
        parts = lines[0].split(' ', 2)
        code = int(parts[1]) if len(parts) > 1 else 0
        headers = {}
        for line in lines[1:]:
            if ':' in line:
                k, v = line.split(':', 1)
                headers[k.strip().lower()] = v.strip()
        to_tag = None
        m = re.search(r';tag=([^;>\s]+)', headers.get('to', ''))
        if m:
            to_tag = m.group(1)
        sdp_ip, sdp_port = None, None
        if '\r\n\r\n' in resp:
            sdp = resp.split('\r\n\r\n', 1)[1]
            m = re.search(r'c=IN IP4 ([\d.]+)', sdp)
            if m:
                sdp_ip = m.group(1)
            m = re.search(r'm=audio (\d+)', sdp)
            if m:
                sdp_port = int(m.group(1))
        return {'code': code, 'headers': headers, 'to_tag': to_tag,
                'sdp_ip': sdp_ip, 'sdp_port': sdp_port}

    def register(self, auth=False):
        uri = f"sip:{self.d}"
        branch = f"z9hG4bK-{uuid.uuid4().hex[:16]}"
        call_id = f"{uuid.uuid4().hex[:16]}@{self.d}"
        msg = f"REGISTER {uri} SIP/2.0\r\n"
        msg += f"Via: SIP/2.0/{self.pr.upper()} {self.d}:{self.pt};branch={branch};rport\r\n"
        msg += f"From: <sip:{self.u}@{self.d}>;tag={self.tag}\r\n"
        msg += f"To: <sip:{self.u}@{self.d}>\r\n"
        msg += f"Call-ID: {call_id}\r\n"
        msg += f"CSeq: {self.seq} REGISTER\r\n"
        msg += f"Contact: <sip:{self.u}@{self.d}:{self.lp}>\r\n"
        msg += "Max-Forwards: 70\r\n"
        msg += "User-Agent: TelliCall/1.2.1\r\n"
        msg += "Allow: INVITE, ACK, CANCEL, BYE, OPTIONS\r\n"
        if auth and self.rn:
            a = self._auth("REGISTER", uri)
            if a:
                msg += f"Authorization: {a}\r\n"
        msg += "Content-Length: 0\r\n\r\n"
        self.seq += 1
        return self.send(msg)

    def _get_local_ip(self):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect((self.d, 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except:
            return '0.0.0.0'

    def invite(self, number, auth=False):
        uri = f"sip:+{number}@{self.d}"
        self.br = f"z9hG4bK-{uuid.uuid4().hex[:16]}"
        self.cid = f"{uuid.uuid4().hex[:16]}@{self.d}"
        local_ip = self._get_local_ip()
        sdp = f"v=0\r\n"
        sdp += f"o=- {int(time.time())} {int(time.time())} IN IP4 {local_ip}\r\n"
        sdp += "s=TelliCall\r\n"
        sdp += f"c=IN IP4 {local_ip}\r\n"
        sdp += "t=0 0\r\n"
        sdp += f"m=audio {self.rtp_port} RTP/AVP 0 8 101\r\n"
        sdp += "a=rtpmap:0 PCMU/8000\r\n"
        sdp += "a=rtpmap:8 PCMA/8000\r\n"
        sdp += "a=rtpmap:101 telephone-event/8000\r\n"
        sdp += "a=sendrecv\r\n"
        sdp += "a=ptime:20\r\n"
        sdp_b = sdp.encode()
        msg = f"INVITE {uri} SIP/2.0\r\n"
        msg += f"Via: SIP/2.0/{self.pr.upper()} {self.d}:{self.pt};branch={self.br};rport\r\n"
        msg += f"From: <sip:{self.u}@{self.d}>;tag={self.tag}\r\n"
        msg += f"To: <sip:+{number}@{self.d}>\r\n"
        msg += f"Call-ID: {self.cid}\r\n"
        msg += f"CSeq: {self.seq} INVITE\r\n"
        msg += f"Contact: <sip:{self.u}@{self.d}:{self.lp}>\r\n"
        msg += "Max-Forwards: 70\r\n"
        msg += "User-Agent: TelliCall/1.2.1\r\n"
        msg += "Allow: INVITE, ACK, CANCEL, BYE, OPTIONS\r\n"
        msg += "Content-Type: application/sdp\r\n"
        if auth and self.rn:
            a = self._auth("INVITE", uri)
            if a:
                msg += f"Authorization: {a}\r\n"
        msg += f"Content-Length: {len(sdp_b)}\r\n\r\n"
        msg += sdp
        self.seq += 1
        return self.send(msg)

    def ack(self, number):
        msg = f"ACK sip:+{number}@{self.d} SIP/2.0\r\n"
        msg += f"Via: SIP/2.0/{self.pr.upper()} {self.d}:{self.pt};branch={self.br};rport\r\n"
        msg += f"From: <sip:{self.u}@{self.d}>;tag={self.tag}\r\n"
        msg += f"To: <sip:+{number}@{self.d}>;tag={self.remote_tag}\r\n"
        msg += f"Call-ID: {self.cid}\r\n"
        msg += f"CSeq: {self.seq} ACK\r\n"
        msg += "Max-Forwards: 70\r\n"
        msg += "Content-Length: 0\r\n\r\n"
        return self.send(msg)

    def bye(self, number):
        self.seq += 1
        branch = f"z9hG4bK-{uuid.uuid4().hex[:16]}"
        msg = f"BYE sip:+{number}@{self.d} SIP/2.0\r\n"
        msg += f"Via: SIP/2.0/{self.pr.upper()} {self.d}:{self.pt};branch={branch};rport\r\n"
        msg += f"From: <sip:{self.u}@{self.d}>;tag={self.tag}\r\n"
        msg += f"To: <sip:+{number}@{self.d}>;tag={self.remote_tag}\r\n"
        msg += f"Call-ID: {self.cid}\r\n"
        msg += f"CSeq: {self.seq} BYE\r\n"
        msg += "Max-Forwards: 70\r\n"
        msg += "Content-Length: 0\r\n\r\n"
        return self.send(msg)

    def ok(self, req):
        lines = req.split('\r\n')
        headers = {}
        for line in lines[1:]:
            if ':' in line:
                k, v = line.split(':', 1)
                headers[k.strip().lower()] = v.strip()
        msg = "SIP/2.0 200 OK\r\n"
        msg += f"Via: {headers.get('via', '')}\r\n"
        msg += f"From: {headers.get('from', '')}\r\n"
        msg += f"To: {headers.get('to', '')}\r\n"
        msg += f"Call-ID: {headers.get('call-id', '')}\r\n"
        msg += f"CSeq: {headers.get('cseq', '')}\r\n"
        msg += "Content-Length: 0\r\n\r\n"
        return self.send(msg)

    def start_rtp(self):
        try:
            self.rtp_sk = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.rtp_sk.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                self.rtp_sk.bind(('0.0.0.0', self.rtp_port))
            except OSError:
                self.rtp_sk.bind(('0.0.0.0', 0))
                self.rtp_port = self.rtp_sk.getsockname()[1]
            self.rtp_sk.settimeout(0.05)
            self.rtp_run = True
            return True
        except:
            return False

    def build_rtp(self, payload):
        pt = 0  # PCMU silence
        first = (2 << 6) | 0
        header = struct.pack('!BBHII', first, pt, self.rtp_seq, self.rtp_ts, self.ssrc)
        self.rtp_seq = (self.rtp_seq + 1) & 0xFFFF
        self.rtp_ts += 160
        return header + payload

    def send_rtp(self):
        if not self.rtp_ip or not self.rtp_pt or not self.rtp_sk:
            return False
        payload = bytes([0xFF] * 160)  # silence
        pkt = self.build_rtp(payload)
        try:
            self.rtp_sk.sendto(pkt, (self.rtp_ip, self.rtp_pt))
            return True
        except:
            return False

    def rtp_loop(self, stop_evt, dur):
        start = time.perf_counter()

        def _recv_worker():
            sock = self.rtp_sk
            try:
                sock.settimeout(1.0)
            except:
                pass
            while self.rtp_run and not stop_evt.is_set():
                try:
                    data, addr = sock.recvfrom(4096)
                    if len(data) < 12:
                        continue
                    pt = data[1] & 0x7F
                    raw = data[12:]
                    if pt == 8:
                        pcm = audioop.alaw2lin(raw, 2)
                    else:
                        pcm = audioop.ulaw2lin(raw, 2)
                    self.audio.append(pcm)
                except socket.timeout:
                    continue
                except OSError:
                    break
                except:
                    pass

        recv_thread = threading.Thread(target=_recv_worker, daemon=True)
        recv_thread.start()

        sent = 0
        next_send = start
        PTIME = 0.020

        while self.rtp_run and not stop_evt.is_set():
            now = time.perf_counter()
            if now - start >= dur:
                break
            if now >= next_send:
                self.send_rtp()
                sent += 1
                next_send = start + sent * PTIME
            remaining = next_send - time.perf_counter()
            if remaining > 0.003:
                time.sleep(remaining - 0.002)
            while time.perf_counter() < next_send:
                pass

        stop_evt.set()
        recv_thread.join(timeout=2.0)

    def stop_rtp(self):
        self.rtp_run = False
        if self.rtp_sk:
            try:
                self.rtp_sk.close()
            except:
                pass

    def close(self):
        self.stop_rtp()
        if self.sk:
            try:
                self.sk.close()
            except:
                pass


# ============================================================================
#                          TELICALL API
# ============================================================================

def get_headers(token=None, device_id=None):
    """Get Telicall API headers with Egyptian IP spoofing."""
    if not device_id:
        device_id = ''.join(random.choices('0123456789abcdef', k=16))
    eg_ip = _rand_eg_ip()
    return {
        "host": "api.telicall.com",
        "x-request-id": str(uuid.uuid4()),
        "user-agent": "Dalvik/2.1.0",
        "x-app-version": "1.2.1",
        "x-client-device-id": device_id,
        "x-lang": "en",
        "x-os": "android",
        "x-os-version": "11",
        "x-req-timestamp": str(int(time.time() * 1000)),
        "x-req-signature": "-1",
        "content-type": "application/json",
        "x-token": token or "",
        "x-currency": "EGP",
        "x-real-ip": eg_ip,
    }


def telicall_start_call(phone, call_token, call_device_id):
    """Start a call via Telicall API and return SIP credentials."""
    if not phone.startswith('+'):
        phone = '+' + phone
    headers = get_headers(token=call_token, device_id=call_device_id)
    try:
        r = requests.post(
            f"{API_URL}/call/outbound/start",
            json={'to': phone, 'source': 'numpad'},
            headers=headers,
            timeout=10
        )
        print(f"  [API] Telicall response: HTTP {r.status_code}")
        if r.status_code == 200 and r.json().get('result'):
            sip = r.json()['result'].get('sip', {})
            from_num = r.json()['result'].get('from', {}).get('msisdn', '')
            print(f"  [API] SIP creds: domain={sip.get('domain')} port={sip.get('port')} proto={sip.get('protocol')} from={from_num}")
            return {
                'user': sip.get('username'),
                'pass': sip.get('password'),
                'domain': sip.get('domain'),
                'port': sip.get('port', 5060),
                'proto': sip.get('protocol', 'tcp'),
                'from': from_num,
                'to': r.json()['result'].get('to', {}).get('msisdn'),
                'limit': sip.get('callLimit', 60),
                'balance': sip.get('balanceLimit', 60),
            }
        elif r.status_code == 400:
            err_text = r.text.lower()
            if 'balance' in err_text:
                return 'no_balance'
            print(f"  [API] 400 error: {r.text[:200]}")
            return {'error': 'call_400'}
        elif r.status_code == 404:
            return {'error': 'call_404'}
        elif r.status_code == 403:
            return {'error': 'call_403'}
        else:
            print(f"  [API] Unexpected HTTP {r.status_code}: {r.text[:200]}")
            return {'error': f'call_{r.status_code}'}
    except Exception as e:
        print(f"  [API] Exception: {e}")
        return None


# ============================================================================
#                     CALL EXECUTION (on server)
# ============================================================================

def execute_sip_call(phone, sip_info):
    """
    Execute a SIP call and return the result.
    The call stays alive until it naturally ends (BYE from other side)
    or until MAX_CALL_DURATION is reached.
    Returns: (result_str, duration_seconds, from_number, sip_debug)
    """
    call_start = time.time()
    sip_domain = sip_info.get('domain', '?')
    sip_port = sip_info.get('port', 5060)
    sip_user = sip_info.get('user', '?')[:10]
    print(f"  [SIP] Connecting to {sip_domain}:{sip_port} as {sip_user}...")

    sip = SIP(sip_info['user'], sip_info['pass'], sip_info['domain'],
              sip_info['port'], sip_info['proto'])
    sip._from_num = str(sip_info.get('from', '')).replace('+', '')

    # Connect
    if not sip.conn():
        print(f"  [SIP] FAILED to connect to {sip_domain}:{sip_port}")
        return ('sip_conn_fail', 0, '', f'Cannot connect to {sip_domain}:{sip_port}')

    local_ip = sip._get_local_ip()
    print(f"  [SIP] Connected! Local IP: {local_ip}")

    # REGISTER (without auth first)
    sip.register(auth=False)
    r = sip.recv(RECV_TIMEOUT)
    reg_ok = False
    if r:
        p = sip.parse(r)
        reg_code = p['code'] if p else 0
        print(f"  [SIP] REGISTER response: {reg_code}")
        if p and reg_code == 401:
            # Need auth - send REGISTER with credentials
            sip._pauth(p['headers'].get('www-authenticate', ''))
            sip.register(auth=True)
            r2 = sip.recv(RECV_TIMEOUT)
            if r2:
                p2 = sip.parse(r2)
                reg2_code = p2['code'] if p2 else 0
                print(f"  [SIP] REGISTER+auth response: {reg2_code}")
                if reg2_code == 200:
                    reg_ok = True
                else:
                    print(f"  [SIP] REGISTER FAILED with code {reg2_code}")
            else:
                print(f"  [SIP] REGISTER+auth: no response")
        elif reg_code == 200:
            reg_ok = True
        else:
            print(f"  [SIP] REGISTER unexpected code: {reg_code}")
    else:
        print(f"  [SIP] REGISTER: no response at all")

    if not reg_ok:
        print(f"  [SIP] Registration failed - cannot proceed with INVITE")
        sip.close()
        return ('sip_reg_fail', time.time() - call_start, sip._from_num or '',
                'SIP registration failed')

    print(f"  [SIP] Registration OK - sending INVITE to {phone}")

    # INVITE (without auth first - SIP servers usually challenge)
    num = phone.replace('+', '')
    sip.invite(num, auth=False)
    r = sip.recv(RECV_TIMEOUT)

    if not r:
        print(f"  [SIP] INVITE: no response")
        sip.close()
        return ('failed', time.time() - call_start, sip._from_num or '', 'INVITE no response')

    p = sip.parse(r)
    inv_code = p['code'] if p else 0
    print(f"  [SIP] INVITE response: {inv_code}")

    if not p or inv_code != 401:
        if inv_code == 200:
            sip.remote_tag = p['to_tag']
            sdp_ip = p['sdp_ip']
            sdp_port = p['sdp_port']
            if sdp_ip and sdp_port:
                sip.ack(num)
                sip.close()
                return ('answered_ok', time.time() - call_start, sip._from_num or '', 'direct 200 OK')
        # Any non-401 response to first INVITE is unusual
        print(f"  [SIP] INVITE got unexpected code {inv_code} (expected 401 challenge)")
        sip.close()
        return ('failed', time.time() - call_start, sip._from_num or '',
                f'INVITE unexpected {inv_code}')

    # INVITE with auth
    print(f"  [SIP] Got 401 challenge - re-sending INVITE with auth")
    sip._pauth(p['headers'].get('www-authenticate', ''))
    sip.seq -= 1
    sip.invite(num, auth=True)

    # Wait for ringing / answer
    ringing_started = False
    call_answered = False
    sdp_ip = sdp_port = None
    last_sip_code = 0

    for i in range(RINGING_TIMEOUT):
        r = sip.recv(0.5)
        if r:
            p = sip.parse(r)
            code = p['code'] if p else 0
            last_sip_code = code

            if code == 100:
                pass  # Trying
            elif code == 180 or code == 183:
                if not ringing_started:
                    print(f"  [SIP] RINGING (code {code})")
                ringing_started = True
            elif code == 200:
                call_answered = True
                sip.remote_tag = p['to_tag']
                sdp_ip = p['sdp_ip']
                sdp_port = p['sdp_port']
                print(f"  [SIP] ANSWERED! SDP: {sdp_ip}:{sdp_port}")

                if not sdp_ip or not sdp_port:
                    sip.close()
                    return ('failed', time.time() - call_start, sip._from_num or '', 'No SDP in 200 OK')

                sip.ack(num)

                # Check for instant BYE
                sip.sk.settimeout(0.2)
                instant_bye = False
                for _check in range(INSTANT_BYE_CHECKS):
                    try:
                        chk = sip.sk.recv(4096)
                        if chk:
                            chk_str = chk.decode('utf-8', errors='ignore')
                            if 'BYE ' in chk_str:
                                instant_bye = True
                                sip.ok(chk_str)
                                break
                    except:
                        pass

                if instant_bye:
                    print(f"  [SIP] Instant BYE after answer - declined")
                    sip.close()
                    return ('declined', time.time() - call_start, sip._from_num or '', 'Instant BYE')

                break

            elif code in (486, 487, 603):
                print(f"  [SIP] DECLINED (code {code})")
                sip.close()
                return ('declined', time.time() - call_start, sip._from_num or '', f'SIP {code}')
            elif code == 404:
                print(f"  [SIP] NOT FOUND (code 404)")
                sip.close()
                return ('not_found', time.time() - call_start, sip._from_num or '', 'SIP 404')
            elif code in (408, 480):
                print(f"  [SIP] NO ANSWER (code {code})")
                sip.close()
                return ('no_answer', time.time() - call_start, sip._from_num or '', f'SIP {code}')
            elif code >= 400:
                print(f"  [SIP] ERROR code {code}")
                sip.close()
                return (f'sip_{code}', time.time() - call_start, sip._from_num or '',
                        f'SIP error {code}')

    if not call_answered:
        sip.close()
        if ringing_started:
            print(f"  [SIP] Rang but no answer (timeout)")
            return ('no_answer', time.time() - call_start, sip._from_num or '',
                    f'Ring timeout, last code={last_sip_code}')
        else:
            print(f"  [SIP] Failed - no ringing (last SIP code={last_sip_code})")
            return ('failed', time.time() - call_start, sip._from_num or '',
                    f'No ringing, last code={last_sip_code}')

    # ===== Call was answered - STAY IN CALL until natural disconnect =====
    sip.rtp_ip = sdp_ip if sdp_ip else sip.d
    sip.rtp_pt = sdp_port if sdp_port else 5004

    stop_evt = threading.Event()
    if sip.start_rtp():
        rt = threading.Thread(target=sip.rtp_loop, args=(stop_evt, MAX_CALL_DURATION), daemon=True)
        rt.start()

    time.sleep(0.3)
    start_time = time.time()
    deadline = start_time + MAX_CALL_DURATION
    call_ended = False

    print(f"  [SIP] Call connected - waiting for BYE or timeout ({MAX_CALL_DURATION}s)")
    sip.sk.settimeout(0.5)
    while time.time() < deadline:
        try:
            chk = sip.sk.recv(4096)
            if chk:
                chk_str = chk.decode('utf-8', errors='ignore')
                if 'BYE ' in chk_str:
                    first = chk_str.strip().split('\r\n')[0] if '\r\n' in chk_str else chk_str.strip().split('\n')[0]
                    if first.startswith('BYE ') or '\r\nBYE ' in chk_str or '\nBYE ' in chk_str:
                        sip.ok(chk_str)
                        call_ended = True
                        break
        except:
            pass

    actual_duration = time.time() - start_time
    stop_evt.set()
    sip.stop_rtp()

    if not call_ended:
        sip.bye(num)

    sip.close()

    result = 'answered_ok' if actual_duration >= 1 else 'answered_short'
    print(f"  [SIP] Call ended: {result} duration={actual_duration:.1f}s")
    return (result, actual_duration, sip._from_num or '', f'duration={actual_duration:.1f}s')


# ============================================================================
#                         CALL MANAGER
# ============================================================================

# Active calls: call_id -> call info dict
active_calls = {}
call_lock = threading.Lock()

# Completed calls (keep last 1000 for history)
completed_calls = {}
MAX_COMPLETED = 1000


def start_call_thread(call_id: str, phone: str, token: str, device_id: str, email: str):
    """Run the SIP call in a background thread and update status."""
    try:
        _start_call_thread_inner(call_id, phone, token, device_id, email)
    except Exception as e:
        # Catch any unhandled exception so the thread doesn't crash silently
        print(f"[CALL] {call_id} CRASHED: {e}")
        with call_lock:
            if call_id in active_calls:
                active_calls[call_id]['status'] = 'ended'
                active_calls[call_id]['result'] = f'error: {str(e)[:100]}'
                active_calls[call_id]['ended_at'] = time.time()
        _move_to_completed(call_id)


def _start_call_thread_inner(call_id: str, phone: str, token: str, device_id: str, email: str):
    """Internal: Run the SIP call in a background thread."""
    t0 = time.time()
    print(f"[CALL] {call_id} START phone={phone} email={email[:20]}")

    with call_lock:
        active_calls[call_id]['status'] = 'starting'

    # Step 1: Get SIP credentials from Telicall API
    sip_info = telicall_start_call(phone, token, device_id)

    if sip_info is None:
        print(f"[CALL] {call_id} API_TIMEOUT after {time.time()-t0:.1f}s")
        with call_lock:
            active_calls[call_id]['status'] = 'ended'
            active_calls[call_id]['result'] = 'api_timeout'
            active_calls[call_id]['ended_at'] = time.time()
        _move_to_completed(call_id)
        return

    if sip_info == 'no_balance':
        print(f"[CALL] {call_id} NO_BALANCE")
        with call_lock:
            active_calls[call_id]['status'] = 'ended'
            active_calls[call_id]['result'] = 'no_balance'
            active_calls[call_id]['ended_at'] = time.time()
        _move_to_completed(call_id)
        return

    if isinstance(sip_info, dict) and 'error' in sip_info:
        err = sip_info['error']
        print(f"[CALL] {call_id} API_ERROR: {err}")
        with call_lock:
            active_calls[call_id]['status'] = 'ended'
            active_calls[call_id]['result'] = err
            active_calls[call_id]['ended_at'] = time.time()
        _move_to_completed(call_id)
        return

    # Step 2: Execute SIP call
    with call_lock:
        active_calls[call_id]['status'] = 'calling'
        active_calls[call_id]['from_number'] = sip_info.get('from', '')

    result, duration, from_num, sip_debug = execute_sip_call(phone, sip_info)

    elapsed = time.time() - t0
    print(f"[CALL] {call_id} END: {result} ({duration:.1f}s, total {elapsed:.1f}s) phone={phone} debug={sip_debug}")

    with call_lock:
        if call_id in active_calls:
            active_calls[call_id]['status'] = 'ended'
            active_calls[call_id]['result'] = result
            active_calls[call_id]['duration'] = round(duration, 1)
            active_calls[call_id]['from_number'] = from_num
            active_calls[call_id]['sip_debug'] = sip_debug
            active_calls[call_id]['ended_at'] = time.time()

    _move_to_completed(call_id)


def _move_to_completed(call_id: str):
    """Move a call from active to completed."""
    with call_lock:
        if call_id in active_calls:
            completed_calls[call_id] = active_calls[call_id].copy()
            del active_calls[call_id]
            # Trim completed calls
            if len(completed_calls) > MAX_COMPLETED:
                oldest = list(completed_calls.keys())[:len(completed_calls) - MAX_COMPLETED]
                for k in oldest:
                    del completed_calls[k]


# ============================================================================
#                          FASTAPI APP
# ============================================================================

app = FastAPI(title="Fox Call Server", version="2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class CallStartRequest(BaseModel):
    phone: str
    token: str
    device_id: str
    email: Optional[str] = ""


@app.post("/call/start")
async def api_start_call(req: CallStartRequest):
    """
    Start a new call. Returns call_id immediately.
    The call runs in background on the server.
    """
    call_id = f"call_{uuid.uuid4().hex[:12]}"

    phone = req.phone
    if not phone.startswith('+'):
        phone = '+' + phone

    with call_lock:
        active_calls[call_id] = {
            'call_id': call_id,
            'phone': phone,
            'email': req.email,
            'status': 'queued',
            'result': None,
            'duration': 0,
            'from_number': '',
            'sip_debug': '',
            'started_at': time.time(),
            'ended_at': None,
        }

    # Start call in background thread
    t = threading.Thread(
        target=start_call_thread,
        args=(call_id, phone, req.token, req.device_id, req.email or ''),
        daemon=True
    )
    t.start()

    return {
        'call_id': call_id,
        'phone': phone,
        'status': 'queued',
        'message': 'Call started. Use GET /call/{call_id} to check status.'
    }


@app.get("/call/{call_id}")
async def api_call_status(call_id: str):
    """Check the status of a call."""
    with call_lock:
        if call_id in active_calls:
            info = active_calls[call_id].copy()
            info['active'] = True
            return info
        elif call_id in completed_calls:
            info = completed_calls[call_id].copy()
            info['active'] = False
            return info

    raise HTTPException(status_code=404, detail=f"Call {call_id} not found")


@app.get("/calls")
async def api_list_calls():
    """List all active and recent completed calls."""
    with call_lock:
        active = list(active_calls.values())
        recent = list(completed_calls.values())[-20:]  # Last 20 completed

    return {
        'active_count': len(active),
        'active': active,
        'recent_completed': recent,
        'total_completed': len(completed_calls)
    }


@app.delete("/call/{call_id}")
async def api_cancel_call(call_id: str):
    """Cancel/end a call (sends BYE if still active)."""
    with call_lock:
        if call_id not in active_calls:
            if call_id in completed_calls:
                return {'message': f'Call {call_id} already ended', 'status': completed_calls[call_id].get('result')}
            raise HTTPException(status_code=404, detail=f"Call {call_id} not found")

        # Mark for cancellation - the SIP loop will pick it up
        active_calls[call_id]['cancel'] = True

    return {'message': f'Call {call_id} cancellation requested', 'call_id': call_id}


@app.get("/health")
async def api_health():
    """Health check endpoint."""
    with call_lock:
        active = len(active_calls)
        completed = len(completed_calls)
    return {
        'status': 'ok',
        'active_calls': active,
        'completed_calls': completed,
        'timestamp': time.time()
    }


if __name__ == "__main__":
    import uvicorn
    print("Starting Fox Call Server v2.0...")
    uvicorn.run(app, host="0.0.0.0", port=8000)
