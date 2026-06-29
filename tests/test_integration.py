"""Integration tests for proxy_forwarder (requires network)."""
import json
import socket as sock
import threading
import time
import unittest
import sys
import os
from unittest.mock import patch, MagicMock
from io import StringIO

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import proxy_forwarder as pf


class TestStats(unittest.TestCase):
    """Test ProxyStats class."""

    def setUp(self):
        self.s = pf.ProxyStats()

    def test_initial_values(self):
        d = self.s.to_dict()
        self.assertEqual(d["total_connections"], 0)
        self.assertEqual(d["active_connections"], 0)
        self.assertEqual(d["bytes_total"], 0)
        self.assertEqual(d["health"], "unknown")
        self.assertGreaterEqual(d["uptime_seconds"], 0)

    def test_connections_tracking(self):
        with self.s.lock:
            self.s.total_connections = 5
            self.s.active_connections = 2
        d = self.s.to_dict()
        self.assertEqual(d["total_connections"], 5)
        self.assertEqual(d["active_connections"], 2)

    def test_bytes_tracking(self):
        with self.s.lock:
            self.s.bytes_sent = 1000
            self.s.bytes_recv = 500
        d = self.s.to_dict()
        self.assertEqual(d["bytes_sent"], 1000)
        self.assertEqual(d["bytes_recv"], 500)
        self.assertEqual(d["bytes_total"], 1500)

    def test_health_alive(self):
        with self.s.lock:
            self.s.health_status = "alive"
        self.assertEqual(self.s.to_dict()["health"], "alive")

    def test_health_dead(self):
        with self.s.lock:
            self.s.health_status = "dead"
        self.assertEqual(self.s.to_dict()["health"], "dead")

    def test_uptime_format(self):
        self.assertEqual(pf.ProxyStats._format_uptime(3661), "1h01m01s")
        self.assertEqual(pf.ProxyStats._format_uptime(0), "0h00m00s")
        self.assertEqual(pf.ProxyStats._format_uptime(7200), "2h00m00s")


class TestByteCounter(unittest.TestCase):
    """Test _make_byte_counter callback (uses global stats)."""

    def setUp(self):
        with pf.stats.lock:
            pf.stats.bytes_recv = 0
            pf.stats.bytes_sent = 0

    def test_counter_increments_bytes_recv(self):
        cb = pf._make_byte_counter("bytes_recv")
        cb(100)
        with pf.stats.lock:
            self.assertEqual(pf.stats.bytes_recv, 100)

    def test_counter_increments_bytes_sent(self):
        cb = pf._make_byte_counter("bytes_sent")
        cb(50)
        cb(30)
        with pf.stats.lock:
            self.assertEqual(pf.stats.bytes_sent, 80)

    def test_counter_thread_safe(self):
        cb = pf._make_byte_counter("bytes_recv")
        threads = []
        for _ in range(10):
            t = threading.Thread(target=lambda: [cb(10) for _ in range(100)], daemon=True)
            threads.append(t)
            t.start()
        for t in threads:
            t.join(timeout=5)
        with pf.stats.lock:
            self.assertEqual(pf.stats.bytes_recv, 10 * 100 * 10)


class TestStatsHandler(unittest.TestCase):
    """Test REST API StatsHandler without starting HTTP server."""

    def setUp(self):
        self.handler = pf.StatsHandler
        # Reset stats
        with pf.stats.lock:
            pf.stats.total_connections = 42
            pf.stats.health_status = "alive"

    def test_handler_returns_stats_json(self):
        """Simulate a GET /stats request."""
        # Create a mock request
        mock_wfile = MagicMock()
        handler = self.handler
        handler.path = "/stats"
        handler.send_response = MagicMock()
        handler.send_header = MagicMock()
        handler.end_headers = MagicMock()
        handler.wfile = mock_wfile

        # Call do_GET
        instance = handler.__new__(handler)
        instance.path = "/stats"
        instance.send_response = MagicMock()
        instance.send_header = MagicMock()
        instance.end_headers = MagicMock()
        instance.wfile = MagicMock()

        # Inject stats and call
        from proxy_forwarder import stats as s
        with s.lock:
            s.total_connections = 42
        instance.do_GET()

        # Verify response
        instance.send_response.assert_called_with(200)
        written = instance.wfile.write.call_args[0][0]
        data = json.loads(written)
        self.assertEqual(data["total_connections"], 42)

    def test_handler_root_also_works(self):
        instance = self.handler.__new__(self.handler)
        instance.path = "/"
        instance.send_response = MagicMock()
        instance.send_header = MagicMock()
        instance.end_headers = MagicMock()
        instance.wfile = MagicMock()
        instance.do_GET()
        instance.send_response.assert_called_with(200)

    def test_handler_404_on_unknown_path(self):
        instance = self.handler.__new__(self.handler)
        instance.path = "/unknown"
        instance.send_response = MagicMock()
        instance.send_header = MagicMock()
        instance.end_headers = MagicMock()
        instance.wfile = MagicMock()
        instance.do_GET()
        instance.send_response.assert_called_with(404)

    def test_handler_log_message_suppressed(self):
        """log_message should not write to stderr."""
        instance = self.handler.__new__(self.handler)
        stderr = StringIO()
        old_stderr = sys.stderr
        sys.stderr = stderr
        try:
            instance.log_message("test %s", "message")
            self.assertEqual(stderr.getvalue(), "")
        finally:
            sys.stderr = old_stderr


class TestAPIServerStart(unittest.TestCase):
    """Test that API server can start on a random port."""

    def test_api_server_starts_and_serves(self):
        import socket

        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]

        from http.server import HTTPServer
        server = HTTPServer(("127.0.0.1", port), pf.StatsHandler)
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        time.sleep(0.2)

        import urllib.request
        resp = urllib.request.urlopen(f"http://127.0.0.1:{port}/stats")
        data = json.loads(resp.read().decode())
        self.assertIn("version", data)
        self.assertIn("uptime", data)
        self.assertIn("health", data)
        self.assertEqual(data["version"], pf.VERSION)
        server.shutdown()
        server.server_close()


class TestVersion(unittest.TestCase):
    """Test VERSION constant."""

    def test_version_matches(self):
        self.assertEqual(pf.VERSION, "1.3.0")

    def test_version_format(self):
        parts = pf.VERSION.split(".")
        self.assertEqual(len(parts), 3)
        for p in parts:
            self.assertTrue(p.isdigit())


class TestChinaIPSetIntegration(unittest.TestCase):
    """Integration tests for ChinaIPSet with real IP data."""

    def test_common_china_ips(self):
        c = pf.ChinaIPSet()
        cases = [
            ("223.5.5.5", True),
            ("114.114.114.114", True),
            ("119.125.217.23", True),
            ("8.8.8.8", False),
            ("208.67.222.222", False),
            ("1.1.1.1", True),
        ]
        for ip, expected in cases:
            self.assertEqual(c.contains(ip), expected, f"Mismatch for {ip}")

    def test_builtin_ranges_loaded(self):
        c = pf.ChinaIPSet()
        self.assertGreater(len(c._networks), 40)


class TestCONNECTProtocol(unittest.TestCase):

    def test_parse_valid_connect(self):
        data = b"CONNECT www.google.com:443 HTTP/1.1\r\nHost: www.google.com:443\r\n\r\n"
        first_line = data.split(b"\r\n")[0].decode("utf-8", errors="replace")
        parts = first_line.split()
        self.assertEqual(len(parts), 3)
        self.assertEqual(parts[0], "CONNECT")
        target = parts[1]
        dst_host, _, dst_port_str = target.partition(":")
        self.assertEqual(dst_host, "www.google.com")
        self.assertEqual(dst_port_str, "443")

    def test_parse_connect_without_port(self):
        data = b"CONNECT 1.2.3.4 HTTP/1.1\r\n\r\n"
        first_line = data.split(b"\r\n")[0].decode("utf-8", errors="replace")
        parts = first_line.split()
        target = parts[1]
        dst_host, _, dst_port_str = target.partition(":")
        self.assertEqual(dst_host, "1.2.3.4")
        self.assertEqual(dst_port_str, "")

    def test_relay_traffic_shutdown(self):
        a, b = sock.socketpair()
        evt = threading.Event()
        t = threading.Thread(target=pf.relay_traffic, args=(a, b, evt), daemon=True)
        t.start()
        time.sleep(0.1)
        evt.set()
        t.join(timeout=2)
        self.assertFalse(t.is_alive())
        a.close()
        b.close()

    def test_relay_traffic_with_byte_counter(self):
        a, b = sock.socketpair()
        evt = threading.Event()
        results = []
        cb = lambda n: results.append(n)
        t = threading.Thread(target=pf.relay_traffic, args=(a, b, evt, cb), daemon=True)
        t.start()
        b.sendall(b"hello")
        time.sleep(0.2)
        evt.set()
        t.join(timeout=2)
        a.close()
        b.close()


class TestRoutingLogic(unittest.TestCase):

    def setUp(self):
        self.china = pf.ChinaIPSet()
        self.domains = pf.DEFAULT_DIRECT_DOMAINS

    def test_routing_google(self):
        self.assertFalse(pf.is_direct_domain("www.google.com", self.domains))
        self.assertFalse(pf.is_ip_string("www.google.com"))

    def test_routing_baidu(self):
        self.assertTrue(pf.is_direct_domain("www.baidu.com", self.domains))

    def test_routing_china_ip(self):
        self.assertTrue(pf.is_ip_string("119.125.217.23"))
        self.assertTrue(self.china.contains("119.125.217.23"))

    def test_routing_foreign_ip(self):
        self.assertTrue(pf.is_ip_string("8.8.8.8"))
        self.assertFalse(self.china.contains("8.8.8.8"))


if __name__ == "__main__":
    unittest.main()
