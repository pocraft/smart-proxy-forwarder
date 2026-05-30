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


class TestVersion(unittest.TestCase):
    """Test VERSION constant."""

    def test_version_format(self):
        parts = pf.VERSION.split(".")
        self.assertEqual(len(parts), 3)
        for p in parts:
            self.assertTrue(p.isdigit())


if __name__ == "__main__":
    unittest.main()
