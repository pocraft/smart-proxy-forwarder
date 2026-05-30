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
import signal
import socket
import ssl
import sys
import threading
import time
import urllib.request
from http.server import HTTPServer, BaseHTTPRequestHandler

VERSION = "1.0.0"

BUFSIZE = 65536
CHINALIST_CACHE = "/tmp/proxy_china_ip_list.txt"
RELAY_IDLE_TIMEOUT = 300
STATS_FILE = "/tmp/proxy-forwarder-stats.json"
HEALTH_CHECK_INTERVAL = 30
STATS_API_PORT = 10809


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
            }

    @staticmethod
    def _format_uptime(seconds):
        h, r = divmod(int(seconds), 3600)
        m, s = divmod(r, 60)
        return f"{h}h{m:02d}m{s:02d}s"


stats = ProxyStats()


# ── REST API handler ──

class StatsHandler(BaseHTTPRequestHandler):
    """Serve stats JSON via HTTP GET."""
    def do_GET(self):
        if self.path in ("/", "/stats"):
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
        pass  # suppress HTTP server log output


def _start_api_server(port: int):
    """Start REST API server in a background thread."""
    server = HTTPServer(("127.0.0.1", port), StatsHandler)
    server.serve_forever()


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
                    lines = data.splitlines()
                    for line in lines:
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

def relay_traffic(src, dst, shutdown_event, bytes_counter=None):
    """Bidirectional traffic relay with idle timeout.

    Uses shutdown_event to signal the paired relay to stop when one direction closes.
    Polls for shutdown_event every second while waiting for data.
    """
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
    """Create a bytes counter callback for a given stats attribute."""
    def _cb(n):
        with stats.lock:
            setattr(stats, attr, getattr(stats, attr) + n)
    return _cb


# ── Connection handler ──

def handle_client(client, china_set, direct_domains, remote_host, remote_port,
                  insecure=False, log_requests=False):
    """Handle one CONNECT request — route domestic direct, international via proxy."""
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

        # ── Smart routing (DNS leak-free) ──
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
            ctx = ssl.create_default_context()
            if insecure:
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
            else:
                ctx.check_hostname = True
                ctx.verify_mode = ssl.CERT_REQUIRED

            remote = socket.create_connection((remote_host, remote_port), timeout=15)
            tls_remote = ctx.wrap_socket(remote, server_hostname=remote_host)

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
            print(f"[{time.strftime('%H:%M:%S')}] {dst_host}:{dst_port} → {route} ({reason}) {duration:.1f}s")

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
    parser.add_argument("--listen-host", default="127.0.0.1",
                        help="Local listen address (default: 127.0.0.1)")
    parser.add_argument("--listen-port", type=int, default=10808,
                        help="Local listen port (default: 10808)")
    parser.add_argument("--remote-host", default="",
                        help="Remote HTTPS CONNECT proxy host (required)")
    parser.add_argument("--remote-port", type=int, default=443,
                        help="Remote HTTPS CONNECT proxy port (default: 443)")
    parser.add_argument("--config", default="",
                        help="Path to config JSON file")
    parser.add_argument("--insecure", "-k", action="store_true",
                        help="Skip TLS certificate verification for remote proxy (default: verify)")
    parser.add_argument("--log-requests", action="store_true",
                        help="Log each CONNECT request with target, route and timing")
    parser.add_argument("--api-port", type=int, default=STATS_API_PORT,
                        help=f"REST API port for stats (default: {STATS_API_PORT})")
    parser.add_argument("--version", action="store_true",
                        help="Show version and exit")
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

    if not remote_host:
        print("ERROR: --remote-host is required (or set in config file)", file=sys.stderr)
        print("  Example: --remote-host your-proxy.example.com --remote-port 443", file=sys.stderr)
        sys.exit(1)

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
    print(f"  Remote:     {remote_host}:{remote_port}")
    print(f"  CN CIDRs:   {len(china._networks)} ranges")
    print(f"  Direct Doms:{len(direct_domains)} rules")
    print(f"  TLS Verify: {'OFF (--insecure)' if insecure else 'ON'}")
    print(f"  API:        http://127.0.0.1:{api_port}/stats")
    print(f"  Log reqs:   {'ON' if log_requests else 'OFF'}")
    print(f"  Stats:      {STATS_FILE}")
    print(f"  Health:     checking every {HEALTH_CHECK_INTERVAL}s")
    print(f"\n  Set http_proxy=http://{listen_host}:{listen_port}")
    print(f"  Set https_proxy=http://{listen_host}:{listen_port}")
    print(f"\n  CN → Direct | INTL → Proxy (auto, DNS-safe)")
    print(f"{'='*60}\n")

    def shutdown(sig, frame):
        print("\n[-] Shutting down...")
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

    # Health check
    def _health_check():
        while True:
            try:
                s = socket.create_connection((remote_host, remote_port), timeout=10)
                s.close()
                with stats.lock:
                    stats.health_status = "alive"
                    stats.health_last_check = time.time()
            except Exception:
                with stats.lock:
                    stats.health_status = "dead"
                    stats.health_last_check = time.time()
            time.sleep(HEALTH_CHECK_INTERVAL)
    threading.Thread(target=_health_check, daemon=True).start()

    # REST API
    try:
        t_api = threading.Thread(target=_start_api_server, args=(api_port,), daemon=True)
        t_api.start()
        print(f"  ✓ REST API running on http://127.0.0.1:{api_port}/stats")
    except Exception as e:
        print(f"  ⚠ REST API failed to start: {e}")
    print(f"  {'='*60}\n")

    while True:
        try:
            client, addr = server.accept()
            t = threading.Thread(
                target=handle_client,
                args=(client, china, direct_domains, remote_host, remote_port, insecure, log_requests),
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
