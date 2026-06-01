#!/usr/bin/env python3
"""
Fox Call Server - SIP Call Manager + Telegram Bot
===================================================
FastAPI server that tracks SIP calls and provides a Telegram bot.

The client (fox_caller1.py) makes SIP calls directly from local IP
and reports results here for tracking and bot access.

Endpoints:
  POST /call/start   - Start a new call (legacy - server makes SIP call)
  POST /call/report  - Report a call result from client (NEW)
  GET  /call/{id}    - Check call status (enhanced with details)
  GET  /calls        - List all calls
  DELETE /call/{id}  - Cancel/end a call
  GET  /health       - Health check

Telegram Bot:
  Set BOT_TOKEN env var to enable the bot.
  Commands: /start, /status, /call <id>, /stats, /help
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
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from typing import Optional
from datetime import datetime

# ============================================================================
#                            CONFIGURATION
# ============================================================================

API_URL = "https://api.telicall.com"
SIP_CONNECT_TIMEOUT = 10
RECV_TIMEOUT = 5
RINGING_TIMEOUT = 80
MAX_CALL_DURATION = 600
INSTANT_BYE_CHECKS = 3

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
ADMIN_IDS = os.environ.get("ADMIN_IDS", "")  # comma-separated

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
        pt = 0
        first = (2 << 6) | 0
        header = struct.pack('!BBHII', first, pt, self.rtp_seq, self.rtp_ts, self.ssrc)
        self.rtp_seq = (self.rtp_seq + 1) & 0xFFFF
        self.rtp_ts += 160
        return header + payload

    def send_rtp(self):
        if not self.rtp_ip or not self.rtp_pt or not self.rtp_sk:
            return False
        payload = bytes([0xFF] * 160)
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
    if not device_id:
        device_id = ''.join(random.choices('0123456789abcdef', k=16))
    eg_ip = _rand_eg_ip()
    return {
        "host": "api.telicall.com",
        "x-request-id": str(uuid.uuid4()),
        "user-agent": "Dalvik/2.1.0",
        "x-app-version": "1.2.1",
        "x-client-device-id": device_id,
        "x-lang": "en", "x-os": "android", "x-os-version": "11",
        "x-req-timestamp": str(int(time.time() * 1000)),
        "x-req-signature": "-1",
        "content-type": "application/json",
        "x-token": token or "",
        "x-currency": "EGP",
        "x-real-ip": eg_ip,
    }


def telicall_start_call(phone, call_token, call_device_id):
    if not phone.startswith('+'):
        phone = '+' + phone
    headers = get_headers(token=call_token, device_id=call_device_id)
    try:
        r = requests.post(
            f"{API_URL}/call/outbound/start",
            json={'to': phone, 'source': 'numpad'},
            headers=headers, timeout=10
        )
        if r.status_code == 200 and r.json().get('result'):
            sip = r.json()['result'].get('sip', {})
            from_num = r.json()['result'].get('from', {}).get('msisdn', '')
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
            return {'error': 'call_400'}
        elif r.status_code == 404:
            return {'error': 'call_404'}
        elif r.status_code == 403:
            return {'error': 'call_403'}
        else:
            return {'error': f'call_{r.status_code}'}
    except Exception as e:
        return None


# ============================================================================
#                     CALL EXECUTION (on server - legacy)
# ============================================================================

def execute_sip_call(phone, sip_info):
    call_start = time.time()
    sip_domain = sip_info.get('domain', '?')
    sip_port = sip_info.get('port', 5060)
    sip_user = sip_info.get('user', '?')[:10]
    sip = SIP(sip_info['user'], sip_info['pass'], sip_info['domain'],
              sip_info['port'], sip_info['proto'])
    sip._from_num = str(sip_info.get('from', '')).replace('+', '')
    if not sip.conn():
        return ('sip_conn_fail', 0, '', f'Cannot connect to {sip_domain}:{sip_port}')
    sip.register(auth=False)
    r = sip.recv(RECV_TIMEOUT)
    reg_ok = False
    if r:
        p = sip.parse(r)
        reg_code = p['code'] if p else 0
        if p and reg_code == 401:
            sip._pauth(p['headers'].get('www-authenticate', ''))
            sip.register(auth=True)
            r2 = sip.recv(RECV_TIMEOUT)
            if r2:
                p2 = sip.parse(r2)
                reg2_code = p2['code'] if p2 else 0
                if reg2_code == 200:
                    reg_ok = True
        elif reg_code == 200:
            reg_ok = True
    if not reg_ok:
        sip.close()
        return ('sip_reg_fail', time.time() - call_start, sip._from_num or '', 'SIP registration failed')
    num = phone.replace('+', '')
    sip.invite(num, auth=False)
    r = sip.recv(RECV_TIMEOUT)
    if not r:
        sip.close()
        return ('failed', time.time() - call_start, sip._from_num or '', 'INVITE no response')
    p = sip.parse(r)
    inv_code = p['code'] if p else 0
    if not p or inv_code != 401:
        if inv_code == 200:
            sip.remote_tag = p['to_tag']
            if p['sdp_ip'] and p['sdp_port']:
                sip.ack(num)
                sip.close()
                return ('answered_ok', time.time() - call_start, sip._from_num or '', 'direct 200 OK')
        sip.close()
        return ('failed', time.time() - call_start, sip._from_num or '', f'INVITE unexpected {inv_code}')
    sip._pauth(p['headers'].get('www-authenticate', ''))
    sip.seq -= 1
    sip.invite(num, auth=True)
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
                pass
            elif code in (180, 183):
                ringing_started = True
            elif code == 200:
                call_answered = True
                sip.remote_tag = p['to_tag']
                sdp_ip = p['sdp_ip']
                sdp_port = p['sdp_port']
                if not sdp_ip or not sdp_port:
                    sip.close()
                    return ('failed', time.time() - call_start, sip._from_num or '', 'No SDP in 200 OK')
                sip.ack(num)
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
                    sip.close()
                    return ('declined', time.time() - call_start, sip._from_num or '', 'Instant BYE')
                break
            elif code in (486, 487, 603):
                sip.close()
                return ('declined', time.time() - call_start, sip._from_num or '', f'SIP {code}')
            elif code == 404:
                sip.close()
                return ('not_found', time.time() - call_start, sip._from_num or '', 'SIP 404')
            elif code in (408, 480):
                sip.close()
                return ('no_answer', time.time() - call_start, sip._from_num or '', f'SIP {code}')
            elif code >= 400:
                sip.close()
                return (f'sip_{code}', time.time() - call_start, sip._from_num or '', f'SIP error {code}')
    if not call_answered:
        sip.close()
        if ringing_started:
            return ('no_answer', time.time() - call_start, sip._from_num or '', f'Ring timeout, last code={last_sip_code}')
        return ('failed', time.time() - call_start, sip._from_num or '', f'No ringing, last code={last_sip_code}')
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
    return (result, actual_duration, sip._from_num or '', f'duration={actual_duration:.1f}s')


# ============================================================================
#                         CALL MANAGER
# ============================================================================

active_calls = {}
call_lock = threading.Lock()
completed_calls = {}
MAX_COMPLETED = 2000

# Stats
server_stats = {
    'total_calls': 0,
    'answered': 0,
    'no_answer': 0,
    'failed': 0,
    'busy': 0,
    'not_found': 0,
    'no_balance': 0,
    'started_at': time.time(),
}


def _move_to_completed(call_id: str):
    with call_lock:
        if call_id in active_calls:
            completed_calls[call_id] = active_calls[call_id].copy()
            del active_calls[call_id]
            if len(completed_calls) > MAX_COMPLETED:
                oldest = list(completed_calls.keys())[:len(completed_calls) - MAX_COMPLETED]
                for k in oldest:
                    del completed_calls[k]


def start_call_thread(call_id: str, phone: str, token: str, device_id: str, email: str):
    try:
        _start_call_thread_inner(call_id, phone, token, device_id, email)
    except Exception as e:
        print(f"[CALL] {call_id} CRASHED: {e}")
        with call_lock:
            if call_id in active_calls:
                active_calls[call_id]['status'] = 'ended'
                active_calls[call_id]['result'] = f'error: {str(e)[:100]}'
                active_calls[call_id]['ended_at'] = time.time()
        _move_to_completed(call_id)


def _start_call_thread_inner(call_id: str, phone: str, token: str, device_id: str, email: str):
    t0 = time.time()
    with call_lock:
        active_calls[call_id]['status'] = 'starting'

    sip_info = telicall_start_call(phone, token, device_id)

    if sip_info is None:
        with call_lock:
            active_calls[call_id]['status'] = 'ended'
            active_calls[call_id]['result'] = 'api_timeout'
            active_calls[call_id]['ended_at'] = time.time()
        _move_to_completed(call_id)
        return

    if sip_info == 'no_balance':
        with call_lock:
            active_calls[call_id]['status'] = 'ended'
            active_calls[call_id]['result'] = 'no_balance'
            active_calls[call_id]['ended_at'] = time.time()
        _move_to_completed(call_id)
        return

    if isinstance(sip_info, dict) and 'error' in sip_info:
        err = sip_info['error']
        with call_lock:
            active_calls[call_id]['status'] = 'ended'
            active_calls[call_id]['result'] = err
            active_calls[call_id]['ended_at'] = time.time()
        _move_to_completed(call_id)
        return

    with call_lock:
        active_calls[call_id]['status'] = 'calling'
        active_calls[call_id]['from_number'] = sip_info.get('from', '')

    result, duration, from_num, sip_debug = execute_sip_call(phone, sip_info)

    elapsed = time.time() - t0
    print(f"[CALL] {call_id} END: {result} ({duration:.1f}s) phone={phone}")

    with call_lock:
        if call_id in active_calls:
            active_calls[call_id]['status'] = 'ended'
            active_calls[call_id]['result'] = result
            active_calls[call_id]['duration'] = round(duration, 1)
            active_calls[call_id]['from_number'] = from_num
            active_calls[call_id]['sip_debug'] = sip_debug
            active_calls[call_id]['ended_at'] = time.time()

    # Update server stats
    with call_lock:
        server_stats['total_calls'] += 1
        if result in ('answered_ok', 'answered_short'):
            server_stats['answered'] += 1
        elif result == 'no_answer':
            server_stats['no_answer'] += 1
        elif result in ('declined', 'busy'):
            server_stats['busy'] += 1
        elif result == 'not_found':
            server_stats['not_found'] += 1
        elif result == 'no_balance':
            server_stats['no_balance'] += 1
        else:
            server_stats['failed'] += 1

    _move_to_completed(call_id)


# ============================================================================
#                          FASTAPI APP
# ============================================================================

app = FastAPI(title="Fox Call Server", version="3.0")

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


class CallReportRequest(BaseModel):
    call_id: str
    phone: str
    email: Optional[str] = ""
    result: str
    duration: float = 0
    from_number: Optional[str] = ""
    sip_debug: Optional[str] = ""


@app.post("/call/start")
async def api_start_call(req: CallStartRequest):
    """Start a new call on the server (legacy - may get SIP 403 from non-Egyptian IP)."""
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
            'source': 'server',
        }

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
        'message': 'Call started on server. Use GET /call/{call_id} to check status.'
    }


@app.post("/call/report")
async def api_report_call(req: CallReportRequest):
    """Report a call result from the client (fox_caller1.py makes calls directly)."""
    call_id = req.call_id
    phone = req.phone
    if not phone.startswith('+'):
        phone = '+' + phone

    # Update server stats
    with call_lock:
        server_stats['total_calls'] += 1
        if req.result in ('answered_ok', 'answered_short'):
            server_stats['answered'] += 1
        elif req.result == 'no_answer':
            server_stats['no_answer'] += 1
        elif req.result in ('declined', 'busy'):
            server_stats['busy'] += 1
        elif req.result == 'not_found':
            server_stats['not_found'] += 1
        elif req.result == 'no_balance':
            server_stats['no_balance'] += 1
        else:
            server_stats['failed'] += 1

    # If the call is currently active (e.g. "calling" status), update it
    with call_lock:
        if call_id in active_calls:
            active_calls[call_id]['status'] = 'ended'
            active_calls[call_id]['result'] = req.result
            active_calls[call_id]['duration'] = req.duration
            active_calls[call_id]['from_number'] = req.from_number or ''
            active_calls[call_id]['sip_debug'] = req.sip_debug or ''
            active_calls[call_id]['ended_at'] = time.time()
            active_calls[call_id]['source'] = 'client'
            completed_calls[call_id] = active_calls[call_id].copy()
            del active_calls[call_id]
        else:
            # Create a new completed call entry
            completed_calls[call_id] = {
                'call_id': call_id,
                'phone': phone,
                'email': req.email or '',
                'status': 'ended',
                'result': req.result,
                'duration': req.duration,
                'from_number': req.from_number or '',
                'sip_debug': req.sip_debug or '',
                'started_at': time.time(),
                'ended_at': time.time(),
                'source': 'client',
            }
            # Trim completed calls
            if len(completed_calls) > MAX_COMPLETED:
                oldest = list(completed_calls.keys())[:len(completed_calls) - MAX_COMPLETED]
                for k in oldest:
                    del completed_calls[k]

    return {'status': 'ok', 'call_id': call_id}


@app.get("/call/{call_id}")
async def api_call_status(call_id: str, request: Request):
    """Check the status of a call. Returns JSON or HTML based on Accept header."""
    call_info = None
    is_active = False

    with call_lock:
        if call_id in active_calls:
            call_info = active_calls[call_id].copy()
            is_active = True
        elif call_id in completed_calls:
            call_info = completed_calls[call_id].copy()
            is_active = False

    if not call_info:
        raise HTTPException(status_code=404, detail=f"Call {call_id} not found")

    # Check if client wants HTML
    accept = request.headers.get('accept', '')
    if 'text/html' in accept:
        return HTMLResponse(content=_call_detail_html(call_info, is_active))

    # Return JSON with extra details
    call_info['active'] = is_active
    call_info['elapsed'] = None
    if call_info.get('started_at'):
        if is_active:
            call_info['elapsed'] = round(time.time() - call_info['started_at'], 1)
        elif call_info.get('ended_at'):
            call_info['elapsed'] = round(call_info['ended_at'] - call_info['started_at'], 1)

    return call_info


@app.get("/calls")
async def api_list_calls():
    """List all active and recent completed calls."""
    with call_lock:
        active = list(active_calls.values())
        recent = list(completed_calls.values())[-50:]

    return {
        'active_count': len(active),
        'active': active,
        'recent_completed': recent,
        'total_completed': len(completed_calls),
        'stats': server_stats,
    }


@app.delete("/call/{call_id}")
async def api_cancel_call(call_id: str):
    """Cancel/end a call."""
    with call_lock:
        if call_id not in active_calls:
            if call_id in completed_calls:
                return {'message': f'Call {call_id} already ended', 'status': completed_calls[call_id].get('result')}
            raise HTTPException(status_code=404, detail=f"Call {call_id} not found")
        active_calls[call_id]['cancel'] = True
    return {'message': f'Call {call_id} cancellation requested', 'call_id': call_id}


@app.get("/health")
async def api_health():
    """Health check endpoint."""
    with call_lock:
        active = len(active_calls)
        completed = len(completed_calls)
    uptime = time.time() - server_stats['started_at']
    return {
        'status': 'ok',
        'version': '3.0',
        'active_calls': active,
        'completed_calls': completed,
        'stats': server_stats,
        'uptime_seconds': round(uptime, 0),
        'bot_enabled': bool(BOT_TOKEN),
        'timestamp': time.time()
    }


@app.get("/", response_class=HTMLResponse)
async def api_index():
    """Simple dashboard page."""
    with call_lock:
        active = len(active_calls)
        completed = len(completed_calls)
        st = server_stats.copy()

    uptime = time.time() - st.get('started_at', time.time())
    hours = int(uptime // 3600)
    mins = int((uptime % 3600) // 60)

    html = f"""<!DOCTYPE html>
<html><head><title>Fox Call Server</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; 
       max-width: 800px; margin: 0 auto; padding: 20px; background: #0d1117; color: #c9d1d9; }}
h1 {{ color: #58a6ff; }} h2 {{ color: #8b949e; }}
.card {{ background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 16px; margin: 12px 0; }}
.stat {{ display: inline-block; margin: 8px 16px; text-align: center; }}
.stat .num {{ font-size: 2em; font-weight: bold; }}
.green {{ color: #3fb950; }} .red {{ color: #f85149; }} .yellow {{ color: #d29922; }}
.blue {{ color: #58a6ff; }} .dim {{ color: #8b949e; }}
a {{ color: #58a6ff; }} code {{ background: #1f2937; padding: 2px 6px; border-radius: 4px; }}
input {{ background: #1f2937; border: 1px solid #30363d; color: #c9d1d9; padding: 8px 12px;
         border-radius: 6px; width: 300px; font-size: 14px; }}
button {{ background: #238636; color: white; border: none; padding: 8px 16px;
          border-radius: 6px; cursor: pointer; font-size: 14px; }}
button:hover {{ background: #2ea043; }}
</style></head><body>
<h1>Fox Call Server v3.0</h1>
<div class="card">
<h2>Server Status</h2>
<p>Uptime: {hours}h {mins}m | Active: <span class="blue">{active}</span> | Completed: {completed}</p>
</div>
<div class="card">
<h2>Call Statistics</h2>
<div class="stat"><div class="num green">{st.get('answered',0)}</div><div class="dim">Answered</div></div>
<div class="stat"><div class="num yellow">{st.get('no_answer',0)}</div><div class="dim">No Answer</div></div>
<div class="stat"><div class="num red">{st.get('failed',0)}</div><div class="dim">Failed</div></div>
<div class="stat"><div class="num yellow">{st.get('busy',0)}</div><div class="dim">Busy</div></div>
<div class="stat"><div class="num blue">{st.get('total_calls',0)}</div><div class="dim">Total</div></div>
</div>
<div class="card">
<h2>Check Call Details</h2>
<p>Enter a call ID to see details:</p>
<input id="callId" placeholder="call_xxxxxxxxxxxx" onkeydown="if(event.key==='Enter')checkCall()">
<button onclick="checkCall()">Check</button>
<div id="result" style="margin-top:12px;"></div>
</div>
<div class="card">
<h2>API Endpoints</h2>
<p><code>GET /call/{{id}}</code> - Check call status</p>
<p><code>POST /call/report</code> - Report call result</p>
<p><code>GET /calls</code> - List all calls</p>
<p><code>GET /health</code> - Health check</p>
</div>
<script>
function checkCall() {{
    const id = document.getElementById('callId').value.trim();
    const resultDiv = document.getElementById('result');
    if (!id) return;
    resultDiv.innerHTML = 'Loading...';
    fetch('/call/' + id).then(r => r.json()).then(data => {{
        resultDiv.innerHTML = '<pre style="background:#1f2937;padding:12px;border-radius:6px;overflow-x:auto;">' + 
            JSON.stringify(data, null, 2) + '</pre>';
    }}).catch(e => {{
        resultDiv.innerHTML = '<span style="color:#f85149;">Error: ' + e.message + '</span>';
    }});
}}
</script>
</body></html>"""
    return HTMLResponse(content=html)


def _call_detail_html(call_info, is_active):
    """Generate HTML for a single call detail page."""
    call_id = call_info.get('call_id', '?')
    phone = call_info.get('phone', '?')
    status = call_info.get('status', '?')
    result = call_info.get('result', 'N/A')
    duration = call_info.get('duration', 0)
    from_num = call_info.get('from_number', 'N/A')
    email = call_info.get('email', 'N/A')
    sip_debug = call_info.get('sip_debug', 'N/A')
    source = call_info.get('source', 'server')
    started = call_info.get('started_at')
    ended = call_info.get('ended_at')

    started_str = datetime.fromtimestamp(started).strftime('%Y-%m-%d %H:%M:%S') if started else 'N/A'
    ended_str = datetime.fromtimestamp(ended).strftime('%Y-%m-%d %H:%M:%S') if ended else 'Still active'
    elapsed = round(time.time() - started, 1) if started and is_active else (round(ended - started, 1) if started and ended else 0)

    status_color = '#3fb950' if result in ('answered_ok', 'answered_short') else '#f85149' if 'fail' in str(result) else '#d29922'
    active_text = '<span style="color:#3fb950;">ACTIVE</span>' if is_active else '<span style="color:#8b949e;">ENDED</span>'

    return f"""<!DOCTYPE html>
<html><head><title>Call {call_id}</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
       max-width: 700px; margin: 0 auto; padding: 20px; background: #0d1117; color: #c9d1d9; }}
h1 {{ color: #58a6ff; }} .card {{ background: #161b22; border: 1px solid #30363d;
      border-radius: 8px; padding: 16px; margin: 12px 0; }}
.row {{ display: flex; justify-content: space-between; padding: 8px 0;
        border-bottom: 1px solid #21262d; }}
.row:last-child {{ border-bottom: none; }}
.label {{ color: #8b949e; }} .value {{ color: #c9d1d9; font-weight: 500; }}
a {{ color: #58a6ff; }}
</style></head><body>
<h1>Call Details</h1>
<div class="card">
<div class="row"><span class="label">Call ID</span><span class="value">{call_id}</span></div>
<div class="row"><span class="label">Status</span><span class="value">{active_text}</span></div>
<div class="row"><span class="label">Phone</span><span class="value">{phone}</span></div>
<div class="row"><span class="label">From</span><span class="value">{from_num}</span></div>
<div class="row"><span class="label">Account</span><span class="value">{email}</span></div>
<div class="row"><span class="label">Result</span><span class="value" style="color:{status_color}">{result}</span></div>
<div class="row"><span class="label">Duration</span><span class="value">{duration}s</span></div>
<div class="row"><span class="label">Elapsed</span><span class="value">{elapsed}s</span></div>
<div class="row"><span class="label">Started</span><span class="value">{started_str}</span></div>
<div class="row"><span class="label">Ended</span><span class="value">{ended_str}</span></div>
<div class="row"><span class="label">Source</span><span class="value">{source}</span></div>
<div class="row"><span class="label">SIP Debug</span><span class="value">{sip_debug}</span></div>
</div>
<p><a href="/">Back to Dashboard</a> | <a href="/call/{call_id}?json=1">JSON</a></p>
</body></html>"""


# ============================================================================
#                       TELEGRAM BOT
# ============================================================================

def run_telegram_bot():
    """Run the Telegram bot in a background thread."""
    if not BOT_TOKEN:
        print("[BOT] No BOT_TOKEN set - bot disabled")
        return

    print(f"[BOT] Starting Telegram bot...")
    bot_url = f"https://api.telegram.org/bot{BOT_TOKEN}"

    # Set webhook to empty (use polling)
    try:
        requests.get(f"{bot_url}/deleteWebhook", timeout=5)
    except:
        pass

    last_update_id = 0

    while True:
        try:
            r = requests.get(f"{bot_url}/getUpdates",
                           params={'offset': last_update_id + 1, 'timeout': 30},
                           timeout=35)
            if r.status_code != 200:
                time.sleep(5)
                continue

            data = r.json()
            if not data.get('ok'):
                time.sleep(5)
                continue

            for update in data.get('result', []):
                last_update_id = update.get('update_id', last_update_id)

                if 'message' not in update:
                    continue

                msg = update['message']
                chat_id = msg.get('chat', {}).get('id')
                text = msg.get('text', '').strip()
                user_name = msg.get('from', {}).get('first_name', 'User')

                if not text or not chat_id:
                    continue

                try:
                    reply = _handle_bot_command(text, chat_id, user_name)
                    if reply:
                        requests.post(f"{bot_url}/sendMessage",
                                    json={'chat_id': chat_id, 'text': reply,
                                          'parse_mode': 'HTML'},
                                    timeout=10)
                except Exception as e:
                    print(f"[BOT] Error handling command: {e}")

        except Exception as e:
            print(f"[BOT] Polling error: {e}")
            time.sleep(10)


def _handle_bot_command(text, chat_id, user_name):
    """Handle a bot command and return reply text."""
    text_lower = text.lower()

    if text_lower in ('/start', 'start'):
        return (f"Hey {user_name}! Fox Call Bot is running.\n\n"
                f"Commands:\n"
                f"/status - Server status & stats\n"
                f"/call <id> - Check call details\n"
                f"/calls - Recent calls\n"
                f"/stats - Call statistics\n"
                f"/help - Show this message")

    elif text_lower in ('/status', 'status'):
        with call_lock:
            active = len(active_calls)
            completed = len(completed_calls)
        health = api_health()
        return (f"Server Status\n"
                f"Active calls: {active}\n"
                f"Completed: {completed}\n"
                f"Uptime: {round(health.get('uptime_seconds', 0) / 3600, 1)}h")

    elif text_lower.startswith('/call ') or text_lower.startswith('call '):
        call_id = text.split(' ', 1)[1].strip() if ' ' in text else ''
        if not call_id:
            return "Usage: /call <call_id>\nExample: /call call_162b53090aff"

        with call_lock:
            call_info = None
            is_active = False
            if call_id in active_calls:
                call_info = active_calls[call_id].copy()
                is_active = True
            elif call_id in completed_calls:
                call_info = completed_calls[call_id].copy()
                is_active = False

        if not call_info:
            return f"Call {call_id} not found."

        status_emoji = "🟢" if is_active else "🔴"
        result = call_info.get('result', 'N/A')
        duration = call_info.get('duration', 0)
        phone = call_info.get('phone', '?')
        from_num = call_info.get('from_number', '?')

        return (f"{status_emoji} Call: {call_id}\n"
                f"Phone: {phone}\n"
                f"From: {from_num}\n"
                f"Result: {result}\n"
                f"Duration: {duration}s\n"
                f"Status: {'Active' if is_active else 'Ended'}")

    elif text_lower in ('/calls', 'calls'):
        with call_lock:
            active = list(active_calls.values())[-5:]
            recent = list(completed_calls.values())[-5:]

        lines = ["Recent Calls:"]
        if active:
            lines.append("\nActive:")
            for c in active:
                lines.append(f"  {c.get('call_id','?')} - {c.get('phone','?')} - {c.get('status','?')}")
        if recent:
            lines.append("\nCompleted:")
            for c in recent:
                lines.append(f"  {c.get('call_id','?')} - {c.get('phone','?')} - {c.get('result','?')} ({c.get('duration',0)}s)")
        if not active and not recent:
            lines.append("No calls yet.")
        return '\n'.join(lines)

    elif text_lower in ('/stats', 'stats'):
        with call_lock:
            st = server_stats.copy()
        return (f"Call Statistics\n"
                f"Answered: {st.get('answered', 0)}\n"
                f"No Answer: {st.get('no_answer', 0)}\n"
                f"Failed: {st.get('failed', 0)}\n"
                f"Busy: {st.get('busy', 0)}\n"
                f"Not Found: {st.get('not_found', 0)}\n"
                f"Total: {st.get('total_calls', 0)}")

    elif text_lower in ('/help', 'help'):
        return (f"Fox Call Bot Commands:\n"
                f"/start - Welcome message\n"
                f"/status - Server status\n"
                f"/call <id> - Check call details\n"
                f"/calls - Recent calls\n"
                f"/stats - Statistics\n"
                f"/help - This message")

    return None


# Start bot in background
if BOT_TOKEN:
    bot_thread = threading.Thread(target=run_telegram_bot, daemon=True)
    bot_thread.start()
    print("[BOT] Telegram bot started!")
else:
    print("[BOT] No BOT_TOKEN - bot disabled. Set BOT_TOKEN env var to enable.")


if __name__ == "__main__":
    import uvicorn
    print("Starting Fox Call Server v3.0...")
    uvicorn.run(app, host="0.0.0.0", port=8000)
