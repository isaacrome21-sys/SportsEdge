"""t153 synthetic hostname-hardening regressions; research-only, no authority."""
import unittest
from sportsedge.source_fact_evidence import is_x_host
from test_source_fact_social_subdomain_boundary import classify


class HostnameHardeningTests(unittest.TestCase):
    def test_exact_and_subdomains_are_x(self):
        for h in ("x.com", "twitter.com", "X.COM", "mobile.x.com", "mobile.x.com.",
                  "x.com.", "Mobile.Twitter.Com", "www.twitter.com."):
            with self.subTest(h=h):
                self.assertTrue(is_x_host(h))

    def test_lookalikes_are_not_x(self):
        for h in ("x.com.evil.com", "evilx.com", "twitter.com-foo", "notx.com",
                  "x.co", "x.com..", "xn--x-6sb.com", "xn--twtter-4ib.com",
                  "\u0445.com", "mobile.x.com.evil.com", "", "x..com"):
            with self.subTest(h=h):
                self.assertFalse(is_x_host(h))

    def test_trailing_dot_x_subdomain_cannot_be_official(self):
        self.assertEqual(classify("mobile.x.com.", "OFFICIAL", "OFFICIAL_WEB")["state"], "BLOCKED")
        self.assertEqual(classify("X.COM.", "VERIFIED_REPORTER", "OFFICIAL_WEB")["state"], "BLOCKED")

    def test_trailing_dot_x_subdomain_is_social_search(self):
        r = classify("mobile.x.com.", "SOCIAL", "X")
        self.assertEqual(r["state"], "UNKNOWN")
        self.assertEqual(r["search_channels_pre_cutoff"], ["X"])

    def test_lookalike_host_not_counted_as_x_search(self):
        for h in ("x.com.evil.com", "evilx.com", "twitter.com-foo"):
            with self.subTest(h=h):
                r = classify(h, "SOCIAL", "X")
                self.assertEqual(r["search_channels_pre_cutoff"], [])
                self.assertFalse(r["play_authority"])

    def test_punycode_host_fails_closed(self):
        r = classify("xn--x-6sb.com", "OFFICIAL", "OFFICIAL_WEB")
        self.assertEqual(r["state"], "BLOCKED")
        self.assertEqual(r["search_channels_pre_cutoff"], [])

    def test_lookalike_cannot_be_social_upgraded_but_stays_research_only(self):
        r = classify("x.com.evil.com", "OFFICIAL", "OFFICIAL_WEB")
        self.assertEqual(r["state"], "SUPPORTED_RESEARCH_ONLY")
        self.assertFalse(r["pricing_authority"])
        self.assertFalse(r["play_authority"])


if __name__ == "__main__":
    unittest.main()
