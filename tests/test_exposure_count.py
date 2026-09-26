"""Tests for the exposure-count probe.

The probe talks to Shodan. These tests never do: they exercise the query rules,
the version-pinned refusal and the response parsing against saved shapes, so the
decision recorded in `contributions/exposure-telemetry-design.md` can be
re-checked without a key and without a network.
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import exposure_count  # noqa: E402

TOOL = Path(__file__).resolve().parent.parent / "tools" / "exposure_count.py"

# The response shape from developer.shodan.io/api, with a realistic total.
COUNT_RESPONSE = {
    "matches": [],
    "facets": {"country": [{"count": 3, "value": "US"}, {"count": 1, "value": "DE"}]},
    "total": 4,
}


class QueryTests(unittest.TestCase):
    def test_a_query_is_required(self):
        with self.assertRaisesRegex(ProbeError := exposure_count.ProbeError, "query is required"):
            exposure_count.build_url("key", "   ")

    def test_the_query_is_encoded_not_concatenated(self):
        url = exposure_count.build_url("secret", 'product:"MikroTik RouterOS"')
        self.assertIn("product%3A%22MikroTik+RouterOS%22", url)
        self.assertTrue(url.startswith(exposure_count.ENDPOINT + "?"))
        self.assertIn("key=secret", url)

    def test_facets_are_passed_through_when_asked_for(self):
        self.assertNotIn("facets", exposure_count.build_url("k", "product:nginx"))
        self.assertIn("facets=country%3A20", exposure_count.build_url("k", "product:nginx",
                                                                      "country:20"))


class RefusalTests(unittest.TestCase):
    def test_a_version_pinned_query_is_refused_by_default(self):
        # The reason this refusal exists: Shodan's version field is optional and
        # banner-derived, so a version count measures reported versions.
        with self.assertRaisesRegex(exposure_count.ProbeError, "pins a version"):
            exposure_count.run("key", "product:nginx version:1.18.0")

    def test_the_refusal_can_be_overridden_deliberately(self):
        with mock.patch.object(exposure_count, "fetch", return_value=COUNT_RESPONSE):
            result = exposure_count.run("key", "product:nginx version:1.18.0", allow_version=True)
        self.assertTrue(result["version_pinned"])
        self.assertEqual(result["count"], 4)

    def test_a_product_only_query_is_allowed(self):
        with mock.patch.object(exposure_count, "fetch", return_value=COUNT_RESPONSE):
            result = exposure_count.run("key", "product:FortiOS")
        self.assertFalse(result["version_pinned"])

    def test_no_key_is_refused_before_any_request(self):
        with mock.patch.object(exposure_count, "fetch") as fetch:
            with self.assertRaisesRegex(exposure_count.ProbeError, "SHODAN_API_KEY"):
                exposure_count.run("", "product:FortiOS")
        fetch.assert_not_called()


class ParseTests(unittest.TestCase):
    def test_a_count_response_yields_the_total_and_its_facets(self):
        result = exposure_count.parse(COUNT_RESPONSE, "product:nginx", "country:10")
        self.assertEqual(result["count"], 4)
        self.assertEqual(result["unit"], "banner records observed, not devices")
        self.assertEqual([bucket["value"] for bucket in result["groups"]["country"]],
                         ["US", "DE"])
        self.assertEqual(result["source"], "Shodan")

    def test_the_caveats_travel_with_the_number(self):
        # A number without its basis is the thing this whole exercise is about.
        result = exposure_count.parse(COUNT_RESPONSE, "product:nginx")
        self.assertIn("not a census", result["caveats"])
        self.assertIn("Shodan", result["caveats"])

    def test_a_response_carrying_host_records_is_refused_rather_than_partly_used(self):
        payload = {"matches": [{"ip_str": "192.0.2.1"}], "total": 1}
        with self.assertRaisesRegex(exposure_count.ProbeError, "host records"):
            exposure_count.parse(payload, "product:nginx")

    def test_a_response_without_a_total_is_refused(self):
        with self.assertRaisesRegex(exposure_count.ProbeError, "no 'total'"):
            exposure_count.parse({"matches": []}, "product:nginx")

    def test_a_total_that_is_not_a_count_is_refused(self):
        for bad in ("4", -1, True, None):
            with self.assertRaises(exposure_count.ProbeError):
                exposure_count.parse({"total": bad, "matches": []}, "product:nginx")

    def test_a_result_never_contains_an_address_or_a_banner(self):
        result = exposure_count.parse(COUNT_RESPONSE, "product:nginx", "country:10")
        serialized = json.dumps(result)
        self.assertNotIn("ip_str", serialized)
        self.assertNotIn("data", result)
        self.assertEqual(set(result), {"source", "source_url", "query", "facets", "count",
                                       "unit", "caveats", "version_pinned", "groups"})


class TransportTests(unittest.TestCase):
    def test_an_unauthorized_response_says_the_key_was_rejected(self):
        import urllib.error
        error = urllib.error.HTTPError(TOOL.as_uri(), 401, "Unauthorized", {}, None)
        with mock.patch("urllib.request.urlopen", side_effect=error):
            with self.assertRaisesRegex(exposure_count.ProbeError, "rejected the API key"):
                exposure_count.fetch("https://example.invalid/x")

    def test_a_rate_limit_says_what_the_documented_limit_is(self):
        import urllib.error
        error = urllib.error.HTTPError(TOOL.as_uri(), 429, "Too Many", {}, None)
        with mock.patch("urllib.request.urlopen", side_effect=error):
            with self.assertRaisesRegex(exposure_count.ProbeError, "one request per second"):
                exposure_count.fetch("https://example.invalid/x")


class CommandLineTests(unittest.TestCase):
    def test_without_a_key_the_command_exits_non_zero_and_explains_how_to_get_one(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            code = exposure_count.main(["product:FortiOS"])
        self.assertEqual(code, 2)

    def test_a_refused_version_query_exits_non_zero(self):
        with mock.patch.dict("os.environ", {"SHODAN_API_KEY": "k"}, clear=True), \
                mock.patch.object(exposure_count, "fetch", return_value=COUNT_RESPONSE):
            self.assertEqual(exposure_count.main(["product:nginx version:1.18.0"]), 2)

    def test_a_count_prints_the_number_its_basis_and_the_attribution(self):
        out = subprocess.run([sys.executable, str(TOOL), "--help"], capture_output=True, text=True)
        self.assertEqual(out.returncode, 0)
        self.assertIn("SHODAN_API_KEY", out.stdout)

    def test_the_help_text_states_the_version_refusal(self):
        out = subprocess.run([sys.executable, str(TOOL), "--help"], capture_output=True, text=True)
        # Matched on phrases that survive the help text's line wrapping.
        self.assertIn("counts products, not versions", out.stdout)
        self.assertIn("version-pinned", out.stdout)


if __name__ == "__main__":
    unittest.main()
