import json
import re
import tempfile
import unittest
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

from engine import feeds
from engine.importer import ROOT

ATOM = "{http://www.w3.org/2005/Atom}"
MANIFEST = {"generated_at": "2026-09-17T11:51:01Z"}
TODAY = datetime.now(timezone.utc).date()


def software():
    """A catalog whose only upcoming milestones are in 2099, plus past ones."""
    return [
        {"id": "python", "name": "Python", "releases": [
            {"id": "2.7", "name": "2.7", "milestones": {"ga": "2010-07-03", "eos": None, "eossec": None, "eol": "2020-01-01"}},
            {"id": "3.14", "name": "3.14", "milestones": {"ga": "2025-10-07", "eos": None, "eossec": "2099-10-31", "eol": "2099-10-31"}},
        ]},
        {"id": "routeros", "name": "RouterOS", "releases": [
            {"id": "7", "name": "7", "milestones": {"ga": "2024-01-01", "eos": "2099-01-31", "eossec": None, "eol": None}},
        ]},
    ]


def hardware():
    return [{
        "id": "cisco-c9300", "name": "Catalyst 9300", "vendor": "Cisco", "product_line": "Catalyst",
        "model_number": "C9300-48P", "status": "expiring",
        "milestones": {"ga": "2019-06-01", "eos": "2099-10-15", "eossec": None, "eol": "2099-03-15"},
        "provenance": {"source_urls": ["https://www.cisco.com/eos-eol-notice.html"],
                       "verifier": "deterministic-eosl-date", "last_checked": "2026-09-17T00:00:00Z",
                       "upstream_modified": None},
    }]


def atom_entries(text):
    return ET.fromstring(text).findall(f"{ATOM}entry")


def rss_items(text):
    return ET.fromstring(text).find("channel").findall("item")


def entry_ids(atom):
    return [entry.find(f"{ATOM}id").text for entry in atom_entries(atom)]


def id_date(entry_id):
    """The milestone date every event id ends with."""
    return entry_id[-10:]


def unfold(text):
    """Undo RFC 5545 folding, keeping the CRLF line structure."""
    return re.sub(r"\r\n[ \t]", "", text)


def ics_values(text, name):
    return [line.split(":", 1)[1] for line in unfold(text).split("\r\n") if line.startswith(f"{name}:")]


def rss_guids(rss):
    return [item.find("guid").text for item in rss_items(rss)]


class FeedTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.out = Path(self.temp.name)

    def build(self, products=None, hardware=None, manifest=MANIFEST):
        self.result = feeds.build(
            software() if products is None else products, hardware, out_dir=self.out, manifest=manifest)
        # newline="" keeps the iCalendar CRLF byte-for-byte readable.
        return {name: (self.out / path).read_text(encoding="utf-8", newline="")
                for name, path in feeds.FEED_PATHS.items()}

    def test_build_writes_the_three_documents(self):
        documents = self.build(hardware=hardware())
        for name, path in feeds.FEED_PATHS.items():
            self.assertTrue((self.out / path).is_file(), path)
            self.assertIn(str(self.out / path), self.result["files"])
        # python 3.14 eossec + eol, routeros 7 eos, hardware eos + eol.
        self.assertEqual(self.result["events"], 5)
        self.assertEqual(self.result["updated"], MANIFEST["generated_at"])
        self.assertEqual(len(atom_entries(documents["atom"])), 5)
        self.assertEqual(len(rss_items(documents["rss"])), 5)
        self.assertEqual(documents["ics"].count("BEGIN:VEVENT"), 5)

    def test_atom_is_rfc4287_shaped(self):
        document = self.build(hardware=hardware())["atom"]
        feed = ET.fromstring(document)
        self.assertEqual(feed.tag, f"{ATOM}feed")
        for required in ("id", "title", "updated"):
            self.assertTrue(feed.find(f"{ATOM}{required}").text, required)
        self.assertEqual(feed.find(f"{ATOM}author/{ATOM}name").text, "EOL Tracker")
        links = {link.get("rel"): link.get("href") for link in feed.findall(f"{ATOM}link")}
        self.assertEqual(links["self"], feeds.site_url("v1/feed.atom"))
        self.assertTrue(links["alternate"].startswith("https://"))
        for entry in atom_entries(document):
            for required in ("id", "title", "updated", "summary", "category"):
                self.assertIsNotNone(entry.find(f"{ATOM}{required}"), required)
            self.assertTrue(entry.find(f"{ATOM}id").text.startswith("tag:eoltracker,"))
            self.assertEqual(entry.find(f"{ATOM}link").get("rel"), "alternate")
            self.assertEqual(entry.find(f"{ATOM}updated").text, MANIFEST["generated_at"])
        # Sorted by date, which every event id ends with.
        days = [id_date(entry.find(f"{ATOM}id").text) for entry in atom_entries(document)]
        self.assertEqual(days, sorted(days))

    def test_only_upcoming_milestones_are_published(self):
        documents = self.build()
        ids = entry_ids(documents["atom"])
        self.assertTrue(ids)
        self.assertEqual(ids, ics_values(documents["ics"], "UID"))
        self.assertEqual(ids, rss_guids(documents["rss"]))
        self.assertEqual(ids, [
            "tag:eoltracker,2026:routeros-7-eos-2099-01-31",
            "tag:eoltracker,2026:python-3.14-eol-2099-10-31",
            "tag:eoltracker,2026:python-3.14-eossec-2099-10-31",
        ])

    def test_event_ids_are_valid_permanent_tag_uris(self):
        products = [{"id": "python", "name": "Python", "releases": [
            {"id": "3.14", "name": "3.14", "milestones": {"ga": None, "eos": None, "eossec": None, "eol": "2099-10-31"}},
            {"id": "1 (LTS) 'name'", "name": "1 (LTS) 'name'", "milestones": {
                "ga": None, "eos": None, "eossec": None, "eol": "2099-11-30"}},
        ]}]
        ids = entry_ids(self.build(products=products)["atom"])
        for value in ids:
            # RFC 4151 syntax, and the tagging date must not be in the future.
            match = re.fullmatch(r"tag:eoltracker,(\d{4}):([^\s#?]*)", value)
            self.assertIsNotNone(match, value)
            self.assertLessEqual(date.fromisoformat(match.group(1) + "-01-01"), TODAY)
            self.assertNotIn(" ", match.group(2))
            self.assertIsNone(re.search(r"%(?![0-9A-F]{2})", match.group(2)))
        # Product, release, milestone and date, hyphen joined and encoded.
        self.assertEqual(ids, [
            "tag:eoltracker,2026:python-3.14-eol-2099-10-31",
            "tag:eoltracker,2026:python-1%20%28LTS%29%20%27name%27-eol-2099-11-30",
        ])

    def test_two_events_never_mint_one_identifier(self):
        # Same product id, release id, milestone and date in both catalogs: the
        # software and hardware namespaces are separate, so this is possible.
        products = [{"id": "edge", "name": "Edge", "releases": [
            {"id": "1", "name": "1", "milestones": {"ga": None, "eos": None, "eossec": None, "eol": "2099-10-31"}},
        ]}]
        hardware = [{"id": "edge", "name": "Edge", "model_number": "1", "status": "expiring",
                     "milestones": {"ga": None, "eos": None, "eossec": None, "eol": "2099-10-31"},
                     "provenance": {"source_urls": []}}]
        # A duplicate UID would silently merge two deadlines in a calendar, so
        # the collision is reported instead of being published.
        with self.assertRaisesRegex(ValueError, "Duplicate event identifier"):
            self.build(products=products, hardware=hardware)

    def test_events_are_ordered_by_date_then_title(self):
        products = [{"id": "b", "name": "Beta", "releases": [
            {"id": "1", "name": "1", "milestones": {"ga": None, "eos": None, "eossec": None, "eol": "2099-02-01"}},
        ]}, {"id": "a", "name": "Alpha", "releases": [
            {"id": "1", "name": "1", "milestones": {"ga": None, "eos": None, "eossec": None, "eol": "2099-01-01"}},
            {"id": "2", "name": "2", "milestones": {"ga": None, "eos": None, "eossec": None, "eol": "2099-01-01"}},
        ]}]
        titles = [entry.find(f"{ATOM}title").text for entry in atom_entries(self.build(products=products)["atom"])]
        self.assertEqual(titles, ["Alpha 1 End of life", "Alpha 2 End of life", "Beta 1 End of life"])

    def test_today_is_upcoming_and_yesterday_is_not(self):
        products = [{"id": "sample", "name": "Sample", "releases": [
            {"id": "1", "name": "1", "milestones": {
                "ga": None, "eos": (TODAY - timedelta(days=1)).isoformat(),
                "eossec": TODAY.isoformat(), "eol": (TODAY + timedelta(days=1)).isoformat()}},
        ]}]
        upcoming = lambda today: [event["date"] for event in feeds.upcoming_events(products, today=today)]
        self.assertEqual(upcoming(TODAY), [TODAY.isoformat(), (TODAY + timedelta(days=1)).isoformat()])
        self.assertEqual(upcoming(TODAY + timedelta(days=1)), [(TODAY + timedelta(days=1)).isoformat()])
        self.assertEqual(upcoming(TODAY - timedelta(days=1)),
                         [(TODAY - timedelta(days=1)).isoformat(), TODAY.isoformat(), (TODAY + timedelta(days=1)).isoformat()])
        # `build` uses the same inclusive UTC window, so today's own event is present.
        ids = entry_ids(self.build(products=products)["atom"])
        self.assertNotIn((TODAY - timedelta(days=1)).isoformat(), "".join(ids))
        self.assertIn(TODAY.isoformat(), "".join(ids))

    def test_event_identifiers_are_stable_across_runs(self):
        first = self.build(hardware=hardware())
        # A different snapshot: input order reversed, timestamps moved.
        second = self.build(products=list(reversed(software())), hardware=hardware(),
                            manifest={"generated_at": "2027-01-01T00:00:00Z"})
        self.assertEqual(entry_ids(first["atom"]), entry_ids(second["atom"]))
        self.assertEqual(ics_values(first["ics"], "UID"), ics_values(second["ics"], "UID"))
        self.assertEqual(rss_guids(first["rss"]), entry_ids(first["atom"]))
        # Only the snapshot timestamps differ between the two runs.
        self.assertNotEqual(first["atom"], second["atom"])

    def test_hardware_events_link_to_the_verified_source(self):
        entries = atom_entries(self.build(hardware=hardware())["atom"])
        model = [entry for entry in entries if "C9300-48P" in entry.find(f"{ATOM}title").text]
        self.assertEqual([entry.find(f"{ATOM}link").get("href") for entry in model],
                         ["https://www.cisco.com/eos-eol-notice.html"] * 2)
        self.assertEqual([entry.find(f"{ATOM}title").text for entry in model],
                         ["Catalyst 9300 C9300-48P End of life", "Catalyst 9300 C9300-48P End of sale"])
        self.assertEqual([entry.find(f"{ATOM}category").get("term") for entry in model], ["eol", "eos"])
        self.assertEqual([id_date(entry.find(f"{ATOM}id").text) for entry in model],
                         ["2099-03-15", "2099-10-15"])

    def test_xml_text_and_attributes_are_escaped(self):
        products = [{"id": "amp", "name": "A & B <c>\x07", "releases": [
            {"id": '1"2', "name": '1"2\n', "milestones": {"ga": None, "eos": None, "eossec": None, "eol": "2099-03-04"}},
        ]}]
        documents = self.build(products=products)
        self.assertIn("A &amp; B &lt;c&gt;", documents["atom"])
        entry = atom_entries(documents["atom"])[0]
        self.assertEqual(entry.find(f"{ATOM}title").text, 'A & B <c> 1"2 End of life')
        self.assertEqual(entry.find(f"{ATOM}summary").text,
                         'A & B <c> 1"2 End of life on Mar 4, 2099 (2099-03-04). '
                         'Full lifecycle: https://zarguell.github.io/eoltracker/products/amp/')
        self.assertEqual(len(rss_items(documents["rss"])), 1)
        self.assertEqual(rss_items(documents["rss"])[0].find("title").text, entry.find(f"{ATOM}title").text)
        self.assertIn('href="https://zarguell.github.io/eoltracker/products/amp/"', documents["atom"])
        self.assertIn("<link>https://zarguell.github.io/eoltracker/products/amp/</link>", documents["rss"])
        # XML 1.0 forbids control characters even escaped, so they never reach the output.
        for document in (documents["atom"], documents["rss"]):
            ET.fromstring(document)
            self.assertNotIn("\x07", document)

    def test_ics_lines_are_folded_and_crlf_terminated(self):
        name = "Very Long Product Name " * 8
        products = [{"id": "long", "name": name, "releases": [
            {"id": "1.0", "name": "1.0", "milestones": {"ga": None, "eos": None, "eossec": None, "eol": "2099-12-31"}},
        ]}]
        ics = self.build(products=products)["ics"]
        self.assertTrue(ics.endswith("END:VCALENDAR\r\n"))
        self.assertNotIn("\n", ics.replace("\r\n", ""))
        physical = ics.split("\r\n")[:-1]
        self.assertTrue(all(len(line.encode("utf-8")) <= 75 for line in physical), max(physical, key=len))
        self.assertEqual(ics_values(ics, "SUMMARY"), [name.rstrip() + " 1.0 End of life"])
        # The summary alone exceeds one line, so it must continue on a folded line.
        start = next(index for index, line in enumerate(physical) if line.startswith("SUMMARY:"))
        self.assertTrue(physical[start + 1].startswith(" "), physical[start:start + 2])

    def test_ics_folding_keeps_multibyte_characters_whole(self):
        name = "é" * 40
        products = [{"id": "accent", "name": name, "releases": [
            {"id": "1", "name": "1", "milestones": {"ga": None, "eos": None, "eossec": None, "eol": "2099-12-31"}},
        ]}]
        ics = self.build(products=products)["ics"]
        physical = ics.split("\r\n")[:-1]
        self.assertTrue(all(len(line.encode("utf-8")) <= 75 for line in physical))
        self.assertTrue(any(line.startswith(" ") for line in physical))
        # An unfolded value round-trips, which it cannot if a fold split a character.
        self.assertEqual(ics_values(ics, "SUMMARY"), [name + " 1 End of life"])

    def test_ics_escapes_text_values(self):
        products = [{"id": "esc", "name": "Esc\\aped, semi;colon\x07", "releases": [
            {"id": "1", "name": "1", "milestones": {"ga": None, "eos": None, "eossec": None, "eol": "2099-06-07"}},
        ]}]
        ics = self.build(products=products)["ics"]
        self.assertEqual(ics_values(ics, "SUMMARY"), ["Esc\\\\aped\\, semi\\;colon 1 End of life"])
        self.assertEqual(ics_values(ics, "DTSTART;VALUE=DATE"), ["20990607"])
        self.assertEqual(ics_values(ics, "CATEGORIES"), ["End of life"])
        self.assertNotIn("\x07", unfold(ics))

    def test_ics_calendar_structure(self):
        ics = self.build(hardware=hardware())["ics"]
        self.assertTrue(ics.startswith("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//EOL Tracker//"))
        self.assertIn("\r\nCALSCALE:GREGORIAN\r\n", ics)
        self.assertIn("\r\nMETHOD:PUBLISH\r\n", ics)
        self.assertEqual(ics.count("BEGIN:VEVENT"), ics.count("END:VEVENT"))

    def test_rss_channel_and_item_fields(self):
        documents = self.build(hardware=hardware())
        ids = entry_ids(documents["atom"])
        root = ET.fromstring(documents["rss"])
        self.assertEqual(root.get("version"), "2.0")
        channel = root.find("channel")
        self.assertEqual(channel.find("link").text, feeds.SITE_URL)
        self.assertTrue(channel.find("description").text.startswith("General availability"))
        self.assertEqual(channel.find("language").text, "en")
        self.assertEqual(channel.find("lastBuildDate").text, "Thu, 17 Sep 2026 11:51:01 GMT")
        self.assertEqual(channel.find("pubDate").text, channel.find("lastBuildDate").text)
        self.assertEqual(channel.find("{http://www.w3.org/2005/Atom}link").get("href"),
                         feeds.site_url("v1/feed.rss"))
        items = rss_items(documents["rss"])
        self.assertEqual([item.find("guid").text for item in items], ids)
        for item in items:
            self.assertTrue(item.find("title").text)
            self.assertTrue(item.find("link").text.startswith("https://"))
            self.assertEqual(item.find("guid").get("isPermaLink"), "false")
            self.assertIn(item.find("category").text, feeds.MILESTONE_LABELS.values())
            self.assertEqual(parsedate_to_datetime(item.find("pubDate").text).tzinfo, timezone.utc)

    def test_timestamps_come_from_the_snapshot_manifest(self):
        documents = self.build(manifest={"generated_at": "2031-02-03T04:05:06Z"})
        feed = ET.fromstring(documents["atom"])
        self.assertEqual(feed.find(f"{ATOM}updated").text, "2031-02-03T04:05:06Z")
        self.assertEqual(feed.find(f"{ATOM}entry/{ATOM}updated").text, "2031-02-03T04:05:06Z")
        self.assertIn("<lastBuildDate>Mon, 03 Feb 2031 04:05:06 GMT</lastBuildDate>", documents["rss"])
        self.assertEqual(set(ics_values(documents["ics"], "DTSTAMP")), {"20310203T040506Z"})

    def test_manifest_defaults_to_the_committed_catalog(self):
        committed = json.loads((ROOT / "data/manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(feeds.generated_at(), feeds.generated_at(committed))
        self.assertEqual(feeds.generated_at({"generated_at": "2031-02-03T04:05:06.000Z"}).isoformat(),
                         "2031-02-03T04:05:06+00:00")
        self.assertIsNotNone(feeds.generated_at({}))

    def test_empty_catalog_writes_valid_empty_documents(self):
        documents = self.build(products=[], hardware=None)
        self.assertEqual(self.result["events"], 0)
        self.assertEqual(atom_entries(documents["atom"]), [])
        self.assertEqual(rss_items(documents["rss"]), [])
        self.assertNotIn("BEGIN:VEVENT", documents["ics"])
        self.assertTrue(documents["ics"].endswith("END:VCALENDAR\r\n"))


if __name__ == "__main__":
    unittest.main()
