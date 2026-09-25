import unittest
from unittest import mock

import requests

from engine import net


class NetworkSecurityTests(unittest.TestCase):
    def test_private_and_non_http_destinations_are_refused(self):
        for url in (
            "http://127.0.0.1/admin",
            "http://localhost/admin",
            "file:///etc/passwd",
            "https://user:secret@example.com/notice",
        ):
            with self.subTest(url=url):
                with self.assertRaises(net.UnsafeDestination):
                    net._destination(url, trusted=False)

    def test_redirect_to_private_destination_is_refused_before_second_request(self):
        redirect = mock.Mock(status_code=302, headers={"Location": "http://127.0.0.1/admin"})
        redirect.raise_for_status.return_value = None
        with mock.patch.object(net.requests, "get", return_value=redirect) as getter:
            with self.assertRaises(net.UnsafeDestination):
                net.get("https://eosl.date/notice")
        self.assertEqual(getter.call_count, 1)
        self.assertFalse(getter.call_args.kwargs["allow_redirects"])
        self.assertTrue(getter.call_args.kwargs["stream"])

    def test_real_response_is_bounded_after_decompression(self):
        response = requests.Response()
        response.status_code = 200
        response.iter_content = lambda chunk_size: (b"a" * 8, b"b" * 8)
        with self.assertRaises(net.ResponseTooLarge):
            net._materialize(response, 12)

    def test_normal_mocked_response_keeps_existing_text_json_contract(self):
        response = mock.Mock(status_code=200, text="page")
        response.json.return_value = {"ok": True}
        with mock.patch.object(net.requests, "get", return_value=response):
            self.assertEqual(net.get_text("https://eosl.date/"), "page")
            self.assertEqual(net.get_json("https://eosl.date/api"), {"ok": True})


if __name__ == "__main__":
    unittest.main()
