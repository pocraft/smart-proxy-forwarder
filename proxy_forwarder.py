#!/usr/bin/env python3
"""
Smart Proxy Forwarder — auto-routing CONNECT proxy with China IP detection.

Domestic targets (CN IPs/domains) → direct connection
International targets → forward via remote HTTPS CONNECT proxy

DNS leak-free: routing decisions never trigger local DNS lookups.
"""
import argparse
import dataclasses
import ipaddress
import json
import os
import queue
import random
import signal
import socket
import ssl
import sys
import threading
import time
import urllib.request
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import List, Optional, Tuple

VERSION = "1.2.0"

BUFSIZE = 65536
CHINALIST_CACHE = "/tmp/proxy_china_ip_list.txt"
RELAY_IDLE_TIMEOUT = 300
STATS_FILE = "/tmp/proxy-forwarder-stats.json"
HEALTH_CHECK_INTERVAL = 30
STATS_API_PORT = 10809
POOL_SIZE = 4
POOL_MAX_AGE = 300  # recycle connections after 5 min
UPSTREAM_TYPE = "connect"  # "connect" or "socks5"


@dataclasses.dataclass
class ProxyStats:
    """Thread-safe connection statistics."""
    def __init__(self):
        self.lock = threading.Lock()
        self.total_connections = 0
        self.active_connections = 0
        self.bytes_sent = 0
        self.bytes_recv = 0
        self.start_time = time.time()
        self.health_status = "unknown"
        self.health_last_check = 0.0
        self.active_upstream = ""

    def to_dict(self):
        uptime = time.time() - self.start_time
        with self.lock:
            return {
                "version": VERSION,
                "uptime_seconds": int(uptime),
                "uptime": self._format_uptime(uptime),
                "total_connections": self.total_connections,
                "active_connections": self.active_connections,
                "bytes_sent": self.bytes_sent,
                "bytes_recv": self.bytes_recv,
                "bytes_total": self.bytes_sent + self.bytes_recv,
                "health": self.health_status,
                "health_last_check": self.health_last_check,
                "active_upstream": self.active_upstream,
                "upstream_type": UPSTREAM_TYPE,
                "pool_size": POOL_SIZE,
            }

    @staticmethod
    def _format_uptime(seconds):
        h, r = divmod(int(seconds), 3600)
        m, s = divmod(r, 60)
        return f"{h}h{m:02d}m{s:02d}s"


stats = ProxyStats()


# ── Connection pool ──

@dataclasses.dataclass
class PooledTlsConnection:
    """A cached TLS connection to the upstream proxy."""
    sock: socket.socket
    tls: ssl.SSLSocket
    host: str
    port: int
    created_at: float


class TlsConnectionPool:
    """Simple TLS connection pool for upstream proxy connections."""

    def __init__(self, max_size: int = POOL_SIZE, max_age: int = POOL_MAX_AGE,
                 insecure: bool = False):
        self._pool: queue.Queue = queue.Queue(max_size)
        self._max_age = max_age
        self._insecure = insecure
        self._lock = threading.Lock()
        self._ctx = ssl.create_default_context()
        if insecure:
            self._ctx.check_hostname = False
            self._ctx.verify_mode = ssl.CERT_NONE
        else:
            self._ctx.check_hostname = True
            self._ctx.verify_mode = ssl.CERT_REQUIRED

    def acquire(self, host: str, port: int) -> Optional[ssl.SSLSocket]:
        """Get a pre-warmed TLS connection, or None if pool is empty."""
        now = time.time()
        while True:
            try:
                conn = self._pool.get_nowait()
                if now - conn.created_at < self._max_age:
                    # Quick liveness: just try to getpeername
                    try:
                        conn.sock.getpeername()
                        return conn.tls
                    except OSError:
                        pass
                try:
                    conn.sock.close()
                except OSError:
                    pass
            except queue.Empty:
                return None

    def release(self, conn: PooledTlsConnection):
        """Return a connection to the pool (best-effort)."""
        try:
            self._pool.put_nowait(conn)
        except queue.Full:
            try:
                conn.sock.close()
            except OSError:
                pass

    def new_connection(self, host: str, port: int) -> PooledTlsConnection:
        """Create a fresh TLS connection to the upstream."""
        sock = socket.create_connection((host, port), timeout=15)
        tls = self._ctx.wrap_socket(sock, server_hostname=host)
        return PooledTlsConnection(sock=sock, tls=tls, host=host, port=port,
                                   created_at=time.time())

    def drain(self):
        """Close all connections in the pool."""
        while True:
            try:
                conn = self._pool.get_nowait()
                try:
                    conn.sock.close()
                except OSError:
                    pass
            except queue.Empty:
                break


pool = TlsConnectionPool()


# ── REST API + Dashboard ──

DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="utf-8"><title>代理转发器</title>
<style>
body{font-family:system-ui,sans-serif;max-width:640px;margin:40px auto;padding:0 20px;
     background:#0d1117;color:#c9d1d9;line-height:1.6}
h1{color:#58a6ff}.lang-bar{text-align:right;margin-bottom:16px}
.lang-btn{background:#21262d;color:#c9d1d9;border:1px solid #30363d;padding:4px 12px;cursor:pointer;border-radius:4px;font-size:13px}
.lang-btn.active{background:#1f6feb;border-color:#1f6feb;color:#fff}
pre{background:#161b22;padding:16px;border-radius:8px;overflow-x:auto}
table{width:100%;border-collapse:collapse}td{padding:8px 0;border-bottom:1px solid #21262d}
.val{text-align:right;font-family:monospace;font-weight:bold;color:#7ee787}
.health-alive{color:#3fb950}.health-dead{color:#f85149}.health-unknown{color:#d29922}
</style></head>
<body>
<div class="lang-bar">
<button class="lang-btn active" onclick="setLang('zh')">中文</button>
<button class="lang-btn" onclick="setLang('en')">EN</button>
</div>
<h1 id="title">🔄 代理转发器</h1>
<div id="root">加载中...</div>
<script>
const L={zh:{
title:'🔄 代理转发器',load:'加载中...',status:'状态',alive:'正常',dead:'离线',unknown:'未知',
uptime:'运行时长',conn:'连接数',connFmt:(t,a)=>t+' 总 / '+a+' 活跃',
traffic:'流量',upstream:'上游',type:'类型',pool:'池大小',ver:'版本'
},en:{
title:'🔄 Proxy Forwarder',load:'Loading...',status:'Status',alive:'Alive',dead:'Dead',unknown:'Unknown',
uptime:'Uptime',conn:'Connections',connFmt:(t,a)=>t+' total, '+a+' active',
traffic:'Traffic',upstream:'Upstream',type:'Type',pool:'Pool Size',ver:'Version'
}};
let lang='zh';
function setLang(l){lang=l;
document.querySelectorAll('.lang-btn').forEach(b=>b.className='lang-btn'+(b.textContent===(l==='zh'?'中文':'EN')?' active':''));
document.getElementById('title').textContent=L[l].title;
document.getElementById('root').textContent=L[l].load;load();}
async function load(){const r=await fetch('/stats'),d=await r.json();let h='';const t=L[lang];
h+='<table>';
h+=`<tr><td>${t.status}</td><td class="val health-${d.health}">${t[d.health]||d.health}</td></tr>`;
h+=`<tr><td>${t.uptime}</td><td class="val">${d.uptime}</td></tr>`;
h+=`<tr><td>${t.conn}</td><td class="val">${t.connFmt(d.total_connections,d.active_connections)}</td></tr>`;
h+=`<tr><td>${t.traffic}</td><td class="val">${(d.bytes_total/1024).toFixed(0)} KB</td></tr>`;
h+=`<tr><td>${t.upstream}</td><td class="val">${d.active_upstream||'-'}</td></tr>`;
h+=`<tr><td>${t.type}</td><td class="val">${d.upstream_type||'-'}</td></tr>`;
h+=`<tr><td>${t.pool}</td><td class="val">${d.pool_size||'-'}</td></tr>`;
h+=`<tr><td>${t.ver}</td><td class="val">${d.version}</td></tr></table>`;
document.getElementById('root').innerHTML=h}
load();setInterval(load,5000)
</script>
</body></html>"""


class StatsHandler(BaseHTTPRequestHandler):
    """Serve stats via JSON or HTML dashboard."""
    def do_GET(self):
        if self.path == "/":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(DASHBOARD_HTML.encode())
        elif self.path == "/stats":
            data = json.dumps(stats.to_dict(), indent=2)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(data.encode())
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, fmt, *args):
        pass


def _start_api_server(port: int):
    server = HTTPServer(("127.0.0.1", port), StatsHandler)
    server.serve_forever()


# ── Multi-upstream ──

def parse_upstreams(host_str: str, port: int) -> List[Tuple[str, int]]:
    """Parse comma-separated upstream hosts. Each can be host or host:port."""
    result = []
    for part in host_str.split(","):
        part = part.strip()
        if not part:
            continue
        if ":" in part:
            h, p = part.rsplit(":", 1)
            try:
                result.append((h.strip(), int(p)))
            except ValueError:
                result.append((h.strip(), port))
        else:
            result.append((part, port))
    return result


def pick_upstream(upstreams: List[Tuple[str, int]]) -> Tuple[str, int]:
    """Pick the healthiest upstream. Currently simple random selection."""
    return random.choice(upstreams)


# ── China IP set ──

class ChinaIPSet:
    """China IP address set with CIDR matching."""

    def __init__(self):
        self._networks = []
        for cidr in CHINA_CIDRS:
            self._networks.append(ipaddress.ip_network(cidr, strict=False))

    def load_from_url(self, url: str, cache_path: str):
        new_networks = []
        loaded = False
        if url:
            try:
                print(f"[+] Downloading China IP list: {url}")
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=5) as resp:
                    data = resp.read().decode("utf-8")
                    try:
                        with open(cache_path, "w") as f:
                            f.write(data)
                    except OSError:
                        pass
                    for line in data.splitlines():
                        line = line.strip()
                        if line and not line.startswith("#"):
                            try:
                                new_networks.append(ipaddress.ip_network(line, strict=False))
                            except ValueError:
                                pass
                    if new_networks:
                        self._networks = new_networks
                        loaded = True
                    print(f"[+] Loaded {len(self._networks)} CIDR ranges")
                    return
            except Exception:
                if os.path.exists(cache_path):
                    self._load_file(cache_path)
                    return
        if not loaded and os.path.exists(cache_path):
            self._load_file(cache_path)
            loaded = True
        if not loaded:
            print(f"[+] Using built-in China IP ranges ({len(self._networks)} CIDRs)")

    def _load_file(self, path: str):
        with open(path) as f:
            self._load_lines(f.read().splitlines())

    def _load_lines(self, lines: list):
        for line in lines:
            line = line.strip()
            if line and not line.startswith("#"):
                try:
                    self._networks.append(ipaddress.ip_network(line, strict=False))
                except ValueError:
                    pass

    def contains(self, ip_str: str) -> bool:
        try:
            ip = ipaddress.ip_address(ip_str)
            return any(ip in net for net in self._networks)
        except ValueError:
            return False


# ── Routing helpers ──

def is_direct_domain(host: str, direct_domains: set) -> bool:
    if not host:
        return False
    host_lower = host.lower()
    if host_lower in direct_domains:
        return True
    for pattern in direct_domains:
        if pattern.startswith("*."):
            if host_lower.endswith(pattern[1:]):
                return True
            if host_lower == pattern[2:]:
                return True
    return False


def is_ip_string(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


# ── Traffic relay ──

def socks5_connect(sock, host: str, port: int) -> bool:
    """Perform SOCKS5 handshake over an established TCP connection.
    Returns True on success, False on failure."""
    try:
        # Auth negotiation: version=5, 1 method, method=no-auth(0)
        sock.sendall(bytes([5, 1, 0]))
        resp = sock.recv(2)
        if resp != bytes([5, 0]):
            return False

        # CONNECT: version=5, cmd=connect(1), rsv=0, atyp=domain(3)
        host_b = host.encode()
        msg = bytes([5, 1, 0, 3, len(host_b)]) + host_b + port.to_bytes(2, "big")
        sock.sendall(msg)
        resp = sock.recv(10)
        if len(resp) < 2 or resp[1] != 0:
            return False
        return True
    except OSError:
        return False

def relay_traffic(src, dst, shutdown_event, bytes_counter=None):
    total = 0
    try:
        src.settimeout(RELAY_IDLE_TIMEOUT)
        dst.settimeout(RELAY_IDLE_TIMEOUT)
        while not shutdown_event.is_set():
            src.settimeout(1.0)
            try:
                data = src.recv(BUFSIZE)
                if not data:
                    break
                dst.sendall(data)
                total += len(data)
            except socket.timeout:
                continue
    except socket.timeout:
        pass
    except OSError:
        pass
    except Exception:
        pass
    finally:
        shutdown_event.set()
        for s in (src, dst):
            try:
                s.close()
            except OSError:
                pass
        if bytes_counter:
            bytes_counter(total)
        return total


def _make_byte_counter(attr):
    def _cb(n):
        with stats.lock:
            setattr(stats, attr, getattr(stats, attr) + n)
    return _cb


# ── Connection handler ──

def handle_client(client, china_set, direct_domains, upstreams,
                  insecure=False, log_requests=False, upstream_type="connect"):
    """Handle one CONNECT request with multi-upstream + connection pool support."""
    start_ts = time.time()
    with stats.lock:
        stats.total_connections += 1
        stats.active_connections += 1
    try:
        data = client.recv(BUFSIZE)
        if not data:
            return

        first_line = data.split(b"\r\n")[0].decode("utf-8", errors="replace")
        parts = first_line.split()
        if len(parts) < 2:
            return

        method = parts[0]
        if method != "CONNECT":
            try:
                client.sendall(b"HTTP/1.1 405 Method Not Allowed\r\n\r\n")
            except OSError:
                pass
            return

        target = parts[1]
        dst_host, _, dst_port_str = target.partition(":")
        try:
            dst_port = int(dst_port_str) if dst_port_str else 443
        except ValueError:
            dst_port = 443

        # ── Smart routing ──
        use_proxy = True
        reason = ""

        if is_direct_domain(dst_host, direct_domains):
            use_proxy = False
            reason = "direct-domain"
        elif is_ip_string(dst_host):
            if china_set.contains(dst_host):
                use_proxy = False
                reason = "direct (CN IP)"
            else:
                reason = "proxy (INTL IP)"
        else:
            reason = "proxy (DNS-safe)"

        if use_proxy:
            # Pick an upstream
            remote_host, remote_port = pick_upstream(upstreams)
            with stats.lock:
                stats.active_upstream = f"{remote_host}:{remote_port}"

            if upstream_type == "socks5":
                # ── SOCKS5 upstream: plain TCP + SOCKS5 handshake ──
                remote = socket.create_connection((remote_host, remote_port), timeout=15)
                if not socks5_connect(remote, dst_host, dst_port):
                    client.sendall(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
                    remote.close()
                    return
                client.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                shutdown_event = threading.Event()
                t1 = threading.Thread(target=relay_traffic, args=(
                    client, remote, shutdown_event, _make_byte_counter('bytes_recv')), daemon=True)
                t2 = threading.Thread(target=relay_traffic, args=(
                    remote, client, shutdown_event, _make_byte_counter('bytes_sent')), daemon=True)
                t1.start()
                t2.start()
                t1.join()
                t2.join()
            else:
                # ── HTTPS CONNECT upstream: TLS + CONNECT request ──
                tls_remote = pool.acquire(remote_host, remote_port)
                if tls_remote is None:
                    tls_remote = pool.new_connection(remote_host, remote_port).tls

                try:
                    tls_remote.sendall(
                        f"CONNECT {dst_host}:{dst_port} HTTP/1.1\r\n"
                        f"Host: {dst_host}:{dst_port}\r\n\r\n".encode()
                    )
                    resp = tls_remote.recv(BUFSIZE)
                    if b"200" not in resp:
                        client.sendall(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
                        return
                except OSError:
                    # Connection dead, retry with fresh one
                    try:
                        tls_remote.close()
                    except OSError:
                        pass
                    tls_remote = pool.new_connection(remote_host, remote_port).tls
                    tls_remote.sendall(
                        f"CONNECT {dst_host}:{dst_port} HTTP/1.1\r\n"
                        f"Host: {dst_host}:{dst_port}\r\n\r\n".encode()
                    )
                    resp = tls_remote.recv(BUFSIZE)
                    if b"200" not in resp:
                        client.sendall(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
                        return

                client.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                shutdown_event = threading.Event()
                t1 = threading.Thread(target=relay_traffic, args=(
                    client, tls_remote, shutdown_event, _make_byte_counter('bytes_recv')), daemon=True)
                t2 = threading.Thread(target=relay_traffic, args=(
                    tls_remote, client, shutdown_event, _make_byte_counter('bytes_sent')), daemon=True)
                t1.start()
                t2.start()
                t1.join()
                t2.join()
                # Connection is consumed after tunnel closes — NOT returned to pool.
        else:
            remote = socket.create_connection((dst_host, dst_port), timeout=15)
            client.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            shutdown_event = threading.Event()
            t1 = threading.Thread(target=relay_traffic, args=(client, remote, shutdown_event), daemon=True)
            t2 = threading.Thread(target=relay_traffic, args=(remote, client, shutdown_event), daemon=True)
            t1.start()
            t2.start()
            t1.join()
            t2.join()

        duration = time.time() - start_ts
        if log_requests:
            route = "proxy" if use_proxy else "direct"
            upstream = f" → {remote_host}:{remote_port}" if use_proxy else ""
            print(f"[{time.strftime('%H:%M:%S')}] {dst_host}:{dst_port} → {route}{upstream} ({reason}) {duration:.1f}s")

    except (OSError, socket.timeout, ssl.SSLError, ValueError):
        try:
            client.sendall(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
        except OSError:
            pass
    finally:
        try:
            client.close()
        except OSError:
            pass
        with stats.lock:
            stats.active_connections -= 1


def load_config(config_path: str) -> dict:
    if config_path and os.path.exists(config_path):
        with open(config_path) as f:
            return json.load(f)
    return {}


def main():
    parser = argparse.ArgumentParser(
        description="Smart Proxy Forwarder — auto-routing CONNECT proxy"
    )
    parser.add_argument("--listen-host", default="127.0.0.1")
    parser.add_argument("--listen-port", type=int, default=10808)
    parser.add_argument("--remote-host", default="",
                        help="Remote HTTPS CONNECT proxy host (or comma-separated hosts for failover)")
    parser.add_argument("--remote-port", type=int, default=443)
    parser.add_argument("--config", default="")
    parser.add_argument("--insecure", "-k", action="store_true")
    parser.add_argument("--log-requests", action="store_true")
    parser.add_argument("--api-port", type=int, default=STATS_API_PORT)
    parser.add_argument("--pool-size", type=int, default=POOL_SIZE,
                        help="TLS connection pool size (default: 4)")
    parser.add_argument("--upstream-type", default="connect",
                        choices=["connect", "socks5"],
                        help="Upstream proxy type: connect (HTTPS CONNECT) or socks5 (default: connect)")
    parser.add_argument("--version", action="store_true")
    args = parser.parse_args()

    if args.version:
        print(f"Smart Proxy Forwarder v{VERSION}")
        sys.exit(0)

    cfg = load_config(args.config)
    remote_host = args.remote_host or cfg.get("remote", {}).get("host", "")
    remote_port = args.remote_port or cfg.get("remote", {}).get("port", 443)
    listen_host = args.listen_host or cfg.get("listen", {}).get("host", "127.0.0.1")
    listen_port = args.listen_port or cfg.get("listen", {}).get("port", 10808)
    insecure = args.insecure or cfg.get("insecure", False)
    log_requests = args.log_requests or cfg.get("log_requests", False)
    api_port = args.api_port or cfg.get("api_port", STATS_API_PORT)
    pool_size = args.pool_size or cfg.get("pool_size", POOL_SIZE)
    upstream_type = args.upstream_type or cfg.get("upstream_type", "connect")

    if upstream_type not in ("connect", "socks5"):
        upstream_type = "connect"
    global UPSTREAM_TYPE
    UPSTREAM_TYPE = upstream_type

    if not remote_host:
        print("ERROR: --remote-host is required (or set in config file)", file=sys.stderr)
        sys.exit(1)

    # Parse upstreams (comma-separated)
    upstreams = parse_upstreams(remote_host, remote_port)
    global pool
    pool = TlsConnectionPool(max_size=pool_size, insecure=insecure)

    china = ChinaIPSet()
    china_url = cfg.get("china_ip_list_url", "")
    china.load_from_url(china_url, CHINALIST_CACHE)

    direct_domains = set(DEFAULT_DIRECT_DOMAINS)
    custom_domains = cfg.get("direct_domains", [])
    if custom_domains:
        direct_domains.update(custom_domains)

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((listen_host, listen_port))
    server.listen(100)

    print(f"\n{'='*60}")
    print(f"  Smart Proxy Forwarder v{VERSION}")
    print(f"{'='*60}")
    print(f"  Listen:     {listen_host}:{listen_port}")
    print(f"  Upstream:   {len(upstreams)} server(s)")
    for h, p in upstreams:
        print(f"               {h}:{p} ({upstream_type})")
    print(f"  CN CIDRs:   {len(china._networks)} ranges")
    print(f"  Direct Doms:{len(direct_domains)} rules")
    print(f"  TLS Verify: {'OFF (--insecure)' if insecure else 'ON'}")
    print(f"  Dashboard:  http://127.0.0.1:{api_port}/")
    print(f"  API:        http://127.0.0.1:{api_port}/stats")
    print(f"  Pool:       {pool_size} connections")
    print(f"  Log reqs:   {'ON' if log_requests else 'OFF'}")
    print(f"  Stats:      {STATS_FILE}")
    print(f"  Health:     checking every {HEALTH_CHECK_INTERVAL}s")
    print(f"\n  Set http_proxy=http://{listen_host}:{listen_port}")
    print(f"  Set https_proxy=http://{listen_host}:{listen_port}")
    print(f"\n  CN → Direct | INTL → Proxy (auto, DNS-safe)")
    print(f"{'='*60}\n")

    def shutdown(sig, frame):
        print("\n[-] Shutting down...")
        pool.drain()
        server.close()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    # Stats writer
    def _write_stats():
        while True:
            try:
                with open(STATS_FILE, "w") as f:
                    json.dump(stats.to_dict(), f)
            except OSError:
                pass
            time.sleep(10)
    threading.Thread(target=_write_stats, daemon=True).start()

    # Health check (tests all upstreams)
    def _health_check():
        while True:
            alive_any = False
            for h, p in upstreams:
                try:
                    s = socket.create_connection((h, p), timeout=10)
                    s.close()
                    alive_any = True
                except Exception:
                    pass
            with stats.lock:
                stats.health_status = "alive" if alive_any else "dead"
                stats.health_last_check = time.time()
            time.sleep(HEALTH_CHECK_INTERVAL)
    threading.Thread(target=_health_check, daemon=True).start()

    # REST API + Dashboard
    try:
        t_api = threading.Thread(target=_start_api_server, args=(api_port,), daemon=True)
        t_api.start()
    except Exception as e:
        print(f"  ⚠ REST API failed: {e}")
    print(f"  {'='*60}\n")

    while True:
        try:
            client, addr = server.accept()
            t = threading.Thread(
                target=handle_client,
                args=(client, china, direct_domains, upstreams, insecure, log_requests, upstream_type),
                daemon=True,
            )
            t.start()
        except (OSError, ValueError):
            continue


# ── Domain whitelist ──
DEFAULT_DIRECT_DOMAINS = {
    "*.baidu.com", "*.qq.com", "*.aliyun.com", "*.taobao.com",
    "*.jd.com", "*.weixin.qq.com", "*.wechat.com", "*.163.com",
    "*.sina.com", "*.sohu.com", "*.zhihu.com", "*.bilibili.com",
    "*.douyin.com", "*.bytedance.com", "*.tencent.com", "*.netease.com",
    "*.xiaomi.com", "*.huawei.com", "*.ctrip.com", "*.meituan.com",
    "*.dianping.com", "*.ele.me", "*.58.com", "*.dangdang.com",
    "*.yhd.com", "*.suning.com", "*.gmw.cn",
    "*.aliyuncs.com", "*.alibaba.com", "*.cainiao.com",
    "*.deepseek.com", "api.deepseek.com",
    "*.people.com.cn", "*.xinhuanet.com", "*.cctv.com",
    "*.chinanews.com", "*.thepaper.cn", "*.yicai.com",
    "*.cnstock.com", "*.eastmoney.com", "*.10jqka.com",
    "*.cls.cn", "*.wallstreetcn.com",
    "*.csdn.net", "*.oschina.net", "*.cnblogs.com",
    "*.36kr.com", "*.huxiu.com", "*.geekpark.net",
    "*.ustc.edu.cn", "*.tuna.tsinghua.edu.cn", "*.aliyun.com",
    "*.kernel.org", "*.pypi.org", "*.python.org",
    "*.npmjs.org", "*.rubygems.org",
    "localhost", "127.0.0.1", "::1",
}

CHINA_CIDRS = [
    "1.0.0.0/8", "14.0.0.0/8", "27.0.0.0/8", "36.0.0.0/8",
    "39.0.0.0/8", "42.0.0.0/8", "49.0.0.0/8", "58.0.0.0/8",
    "59.0.0.0/8", "60.0.0.0/8", "61.0.0.0/8", "101.0.0.0/8",
    "103.0.0.0/8", "106.0.0.0/8", "110.0.0.0/8", "111.0.0.0/8",
    "112.0.0.0/8", "113.0.0.0/8", "114.0.0.0/8", "115.0.0.0/8",
    "116.0.0.0/8", "117.0.0.0/8", "118.0.0.0/8", "119.0.0.0/8",
    "120.0.0.0/8", "121.0.0.0/8", "122.0.0.0/8", "123.0.0.0/8",
    "124.0.0.0/8", "125.0.0.0/8", "169.254.0.0/16", "180.0.0.0/8",
    "182.0.0.0/8", "183.0.0.0/8", "202.0.0.0/8", "203.0.0.0/8",
    "210.0.0.0/8", "211.0.0.0/8", "218.0.0.0/8", "219.0.0.0/8",
    "220.0.0.0/8", "221.0.0.0/8", "222.0.0.0/8", "223.0.0.0/8",
]


if __name__ == "__main__":
    main()
