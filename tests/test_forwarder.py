"""Basic unit tests for proxy_forwarder."""
import sys
import os
import unittest
from unittest.mock import patch, MagicMock

# Add parent dir so we can import the module
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Rename module to avoid py_compile issues with hyphen
import proxy_forwarder as pf


class TestIsIPString(unittest.TestCase):
    """Test is_ip_string function."""

    def test_ipv4(self):
        self.assertTrue(pf.is_ip_string("1.2.3.4"))
        self.assertTrue(pf.is_ip_string("192.168.1.1"))
        self.assertTrue(pf.is_ip_string("0.0.0.0"))
        self.assertTrue(pf.is_ip_string("255.255.255.255"))

    def test_ipv6(self):
        self.assertTrue(pf.is_ip_string("::1"))
        self.assertTrue(pf.is_ip_string("2001:db8::1"))
        self.assertTrue(pf.is_ip_string("fe80::1"))

    def test_hostnames(self):
        self.assertFalse(pf.is_ip_string("google.com"))
        self.assertFalse(pf.is_ip_string("www.baidu.com"))
        self.assertFalse(pf.is_ip_string("localhost"))
        self.assertFalse(pf.is_ip_string(""))
        self.assertFalse(pf.is_ip_string("abc.def"))


class TestIsDirectDomain(unittest.TestCase):
    """Test is_direct_domain function."""

    def setUp(self):
        self.domains = {"*.baidu.com", "*.deepseek.com", "api.deepseek.com",
                        "localhost", "127.0.0.1"}

    def test_exact_match(self):
        self.assertTrue(pf.is_direct_domain("api.deepseek.com", self.domains))
        self.assertTrue(pf.is_direct_domain("localhost", self.domains))
        self.assertTrue(pf.is_direct_domain("127.0.0.1", self.domains))

    def test_wildcard_match(self):
        self.assertTrue(pf.is_direct_domain("www.baidu.com", self.domains))
        self.assertTrue(pf.is_direct_domain("chat.deepseek.com", self.domains))
        self.assertTrue(pf.is_direct_domain("baidu.com", self.domains))

    def test_no_match(self):
        self.assertFalse(pf.is_direct_domain("google.com", self.domains))
        self.assertFalse(pf.is_direct_domain("github.com", self.domains))
        self.assertFalse(pf.is_direct_domain("", self.domains))

    def test_case_insensitive(self):
        self.assertTrue(pf.is_direct_domain("API.DEEPSEEK.COM", self.domains))
        self.assertTrue(pf.is_direct_domain("WWW.BAIDU.COM", self.domains))


class TestChinaIPSet(unittest.TestCase):
    """Test ChinaIPSet class."""

    def setUp(self):
        self.c = pf.ChinaIPSet()

    def test_contains_china_ip(self):
        # 114.114.114.114 (China DNS) should be in China range
        self.assertTrue(self.c.contains("114.114.114.114"))
        # 223.5.5.5 (Ali DNS) should be in China range
        self.assertTrue(self.c.contains("223.5.5.5"))
        # 119.125.217.23 (Guangdong Telecom) should be in China range
        self.assertTrue(self.c.contains("119.125.217.23"))

    def test_not_contains_foreign_ip(self):
        # 8.8.8.8 (Google DNS) is not in China range
        self.assertFalse(self.c.contains("8.8.8.8"))
        # 208.67.222.222 (OpenDNS) is not in China range
        self.assertFalse(self.c.contains("208.67.222.222"))

    def test_invalid_ip(self):
        self.assertFalse(self.c.contains("not-an-ip"))
        self.assertFalse(self.c.contains(""))


class TestLoadConfig(unittest.TestCase):
    """Test load_config function."""

    def test_empty_path(self):
        self.assertEqual(pf.load_config(""), {})

    def test_nonexistent_path(self):
        self.assertEqual(pf.load_config("/nonexistent/config.json"), {})

    @patch("os.path.exists")
    @patch("builtins.open")
    def test_valid_config(self, mock_open, mock_exists):
        mock_exists.return_value = True
        mock_file = MagicMock()
        mock_file.read.return_value = '{"remote": {"host": "test.com"}}'
        mock_open.return_value.__enter__.return_value = mock_file
        result = pf.load_config("/fake/config.json")
        self.assertEqual(result, {"remote": {"host": "test.com"}})


class TestDefaultDomains(unittest.TestCase):
    """Verify DEFAULT_DIRECT_DOMAINS is properly formatted."""

    def test_all_entries_valid(self):
        """All entries should start with *. or be a simple hostname."""
        for d in pf.DEFAULT_DIRECT_DOMAINS:
            self.assertTrue(
                d.startswith("*.") or "." in d or d in ("localhost", "::1"),
                f"Bad domain entry: {d}"
            )

    def test_common_services_present(self):
        """Verify critical Chinese services are in the list."""
        combined = " ".join(pf.DEFAULT_DIRECT_DOMAINS)
        self.assertIn("baidu.com", combined)
        self.assertIn("deepseek.com", combined)
        self.assertIn("weixin.qq.com", combined)
        self.assertIn("aliyun.com", combined)


class TestSocks5AcceptHandshake(unittest.TestCase):
    """Test socks5_accept_handshake function."""

    def _make_sock(self, req_bytes):
        """Helper: create a MagicMock socket that returns req_bytes on recv()."""
        sock = MagicMock()
        sock.recv.return_value = req_bytes
        return sock

    def _make_request(self, atyp, addr_bytes, port=443):
        """Build a SOCKS5 CONNECT request frame."""
        return bytes([5, 1, 0, atyp]) + addr_bytes + port.to_bytes(2, "big")

    def test_ipv4(self):
        """IPv4 address (atyp=1) should parse correctly."""
        greeting = bytes([5, 1, 0])
        req = self._make_request(1, bytes([192, 168, 1, 1]), 8080)
        sock = MagicMock()
        sock.recv.return_value = req
        result = pf.socks5_accept_handshake(sock, greeting)
        self.assertEqual(result, ("192.168.1.1", 8080))
        # Check greeting response was sent
        sock.sendall.assert_any_call(bytes([5, 0]))

    def test_ipv4_default_port(self):
        """IPv4 with default port 443."""
        greeting = bytes([5, 1, 0])
        req = self._make_request(1, bytes([8, 8, 8, 8]))
        sock = MagicMock()
        sock.recv.return_value = req
        result = pf.socks5_accept_handshake(sock, greeting)
        self.assertEqual(result, ("8.8.8.8", 443))

    def test_domain_name(self):
        """Domain name (atyp=3) should parse correctly."""
        greeting = bytes([5, 1, 0])
        host = b"www.google.com"
        req = self._make_request(3, bytes([len(host)]) + host, 443)
        sock = MagicMock()
        sock.recv.return_value = req
        result = pf.socks5_accept_handshake(sock, greeting)
        self.assertEqual(result, ("www.google.com", 443))

    def test_ipv6(self):
        """IPv6 address (atyp=4) should parse correctly."""
        greeting = bytes([5, 1, 0])
        ipv6_bytes = bytes([0x20, 0x01, 0x48, 0x60, 0x48, 0x60, 0, 0,
                            0, 0, 0, 0, 0, 0, 0x88, 0x88])
        req = self._make_request(4, ipv6_bytes, 993)
        sock = MagicMock()
        sock.recv.return_value = req
        result = pf.socks5_accept_handshake(sock, greeting)
        self.assertEqual(result, ("2001:4860:4860::8888", 993))

    def test_invalid_greeting_not_socks5(self):
        """First byte not 0x05 should return None."""
        sock = MagicMock()
        result = pf.socks5_accept_handshake(sock, b"GET / HTTP/1.1\r\n")
        self.assertIsNone(result)
        sock.sendall.assert_not_called()

    def test_invalid_greeting_too_short(self):
        """Greeting shorter than 2 bytes should return None."""
        sock = MagicMock()
        result = pf.socks5_accept_handshake(sock, bytes([5]))
        self.assertIsNone(result)

    def test_request_not_connect(self):
        """Request cmd != 1 (not CONNECT) should return None."""
        greeting = bytes([5, 1, 0])
        # cmd=2 (BIND) instead of 1 (CONNECT)
        req = bytes([5, 2, 0, 1, 192, 168, 1, 1, 0, 80])
        sock = MagicMock()
        sock.recv.side_effect = [greeting, req]
        result = pf.socks5_accept_handshake(sock, greeting)
        self.assertIsNone(result)

    def test_unsupported_atyp(self):
        """Unsupported address type should return None."""
        greeting = bytes([5, 1, 0])
        # atyp=0 (invalid)
        req = bytes([5, 1, 0, 0, 0, 0, 0, 0, 0, 0])
        sock = MagicMock()
        sock.recv.side_effect = [greeting, req]
        result = pf.socks5_accept_handshake(sock, greeting)
        self.assertIsNone(result)

    def test_request_too_short(self):
        """Request shorter than 7 bytes should return None."""
        greeting = bytes([5, 1, 0])
        sock = MagicMock()
        sock.recv.side_effect = [greeting, bytes([5, 1, 0, 1, 0])]
        result = pf.socks5_accept_handshake(sock, greeting)
        self.assertIsNone(result)

    def test_oserror_handled(self):
        """OSError during handshake should return None."""
        sock = MagicMock()
        sock.recv.side_effect = OSError("Connection reset")
        result = pf.socks5_accept_handshake(sock, bytes([5, 1, 0]))
        self.assertIsNone(result)


class TestVersion(unittest.TestCase):
    """Test VERSION constant."""

    def test_version_format(self):
        parts = pf.VERSION.split(".")
        self.assertEqual(len(parts), 3)
        for p in parts:
            self.assertTrue(p.isdigit())


if __name__ == "__main__":
    unittest.main()
