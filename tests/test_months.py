"""Boundary tests for month-precision dates across every consumer (AGENTS.md rule 4).

A source that publishes "July 2028" publishes no day. The schema admits that
shape (``YYYY-MM``) beside full ISO days, and everything that reads a milestone
has to keep the two widths apart: display may not pad ``-01``, the feeds and
iCalendar carry days only and must publish what they drop, the OpenEoX export
must exclude a month release rather than invent a day for it, and a day-only
consumer must never be handed a month by accident.

These are the boundaries where a plausible mistake is silent: an off-by-one in
the "has this month passed?" window, a day count computed from the 1st of the
month instead of its end, a month leaking into an RFC 822 date-time, or a
month-precision exclusion being counted as a day-precision publication.
"""
import json
import re
import tempfile
import unittest
from datetime import date
from pathlib import Path

from engine import feeds, openeox, site_config, site_views

MONTH = "2099-07"
DAY = "2099-07-15"


def product(record_id="vgpu", name="Sample", ga=None, eos=None, eol=None, eossec=None):
    return {"id": record_id, "name": name, "releases": [
        {"id": "1", "name": "1", "milestones": {"ga": ga, "eos": eos, "eossec": eossec, "eol": eol}},
    ]}


def rows(**milestones):
    """Release rows as the pages consume them, through the real presenter."""
    record = {"id": "sample", "name": "Sample", "labels": {},
              "provenance": {"source_url": "https://example.test/", "verifier": "researched-sample",
                             "last_checked": "2026-09-17T00:00:00Z", "upstream_modified": None},
              "releases": [{"id": "1", "name": "1",
                            "milestones": {"ga": None, "eos": None, "eossec": None, "eol": None, **milestones},
                            "upstream": {"name": "1"}}]}
    return site_views.release_rows(record)


class MonthValueTests(unittest.TestCase):
    """`site_config.month_value`/`is_month` decide every other question here."""

    def test_only_a_real_month_is_a_month(self):
        for value in ("2099-07", "2099-01", "2099-12"):
            self.assertTrue(site_config.is_month(value), value)
        # 00 and 13 are not months; a day, a bare year and junk are not months.
        for value in ("2099-00", "2099-13", "2099-7", "2099", "2099-07-15", "July 2099", "", None):
            self.assertFalse(site_config.is_month(value), value)

    def test_month_end_uses_each_months_own_width(self):
        self.assertEqual(site_config.month_end("2099-07"), date(2099, 7, 31))
        self.assertEqual(site_config.month_end("2099-02"), date(2099, 2, 28))
        self.assertEqual(site_config.month_end("2098-02"), date(2098, 2, 28))
        # A leap year's February, and a day value that is not a month at all.
        self.assertEqual(site_config.month_end("2100-02"), date(2100, 2, 28))
        self.assertEqual(site_config.month_end("2096-02"), date(2096, 2, 29))
        self.assertIsNone(site_config.month_end("2099-07-15"))


class HumanDateTests(unittest.TestCase):
    """Display states the width it has; it never pads a month into a day."""

    def test_a_month_prints_as_a_month_and_a_day_as_a_day(self):
        self.assertEqual(site_config.human_date(MONTH), "July 2099")
        self.assertEqual(site_config.human_date("2099-01"), "January 2099")
        self.assertEqual(site_config.human_date("2099-12"), "December 2099")
        self.assertEqual(site_config.human_date(DAY), "Jul 15, 2099")
        self.assertIsNone(site_config.human_date(None))

    def test_a_month_never_renders_as_a_padded_day(self):
        text = site_config.human_date(MONTH)
        self.assertNotRegex(text, r"\b0?1\b")
        self.assertNotRegex(text, r"\d{2}, \d{4}")


class CountdownTests(unittest.TestCase):
    """`site_views.upcoming_events`: the window and the count use the month's end."""

    def events(self, today, **milestones):
        return site_views.upcoming_events(rows(**milestones), today)

    def test_a_month_is_upcoming_through_its_last_day(self):
        month = self.events(date(2099, 7, 1), eol=MONTH)
        self.assertEqual([event["date"] for event in month], [MONTH])
        # The last day of the month still counts, and the day after does not.
        self.assertEqual(len(self.events(date(2099, 7, 31), eol=MONTH)), 1)
        self.assertEqual(self.events(date(2099, 8, 1), eol=MONTH), [])

    def test_day_count_runs_to_the_months_end_not_its_first(self):
        event = self.events(date(2099, 7, 1), eol=MONTH)[0]
        # July has 31 days: from the 1st, the deadline is the 31st, so 30 days out.
        self.assertEqual(event["days"], 30)
        self.assertEqual(self.events(date(2099, 7, 31), eol=MONTH)[0]["days"], 0)
        self.assertEqual(self.events(date(2099, 7, 30), eol=MONTH)[0]["days"], 1)

    def test_a_month_is_flagged_so_callers_can_tell_the_width(self):
        event = self.events(date(2099, 7, 1), eol=MONTH)[0]
        self.assertTrue(event["month"])
        self.assertEqual(event["human"], "July 2099")
        self.assertFalse(self.events(date(2099, 7, 1), eol=DAY)[0]["month"])

    def test_day_precision_windows_are_unchanged(self):
        events = self.events(date(2099, 7, 15), eol=DAY)
        self.assertEqual([event["date"] for event in events], [DAY])
        self.assertEqual(events[0]["days"], 0)
        self.assertEqual(self.events(date(2099, 7, 16), eol=DAY), [])
        self.assertEqual(self.events(date(2099, 7, 14), eol=DAY)[0]["days"], 1)


class FeedExclusionTests(unittest.TestCase):
    """The day-only feeds publish exactly what they cannot carry."""

    def build(self, products, hardware=None):
        self.out = Path(self.temp.name)
        return feeds.build(products, hardware, out_dir=self.out,
                           manifest={"generated_at": "2026-09-17T11:51:01Z"})

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    def documents(self):
        return {name: (self.out / path).read_text(encoding="utf-8", newline="")
                for name, path in feeds.FEED_PATHS.items()}

    def test_a_month_event_is_excluded_and_accounted_not_padded(self):
        result = self.build([product(eol=MONTH)])
        self.assertEqual(result["events"], 0)
        self.assertEqual(result["excluded"], 1)
        documents = self.documents()
        for name, text in documents.items():
            self.assertNotIn(MONTH, text, name)
        excluded = json.loads((self.out / feeds.EXCLUSIONS_PATH).read_text())
        self.assertEqual({key: excluded["counts"][key] for key in ("upcoming_events", "feeds", "excluded")},
                         {"upcoming_events": 1, "feeds": 0, "excluded": 1})
        codes = [reason["code"] for reason in excluded["reasons"]]
        self.assertEqual(codes, [feeds.MONTH_EXCLUSION_CODE, feeds.DERIVED_EXCLUSION_CODE])
        entry = excluded["excluded"][0]
        self.assertEqual(entry["month"], MONTH)
        self.assertEqual(entry["human"], "July 2099")
        self.assertEqual(entry["id"], "tag:eoltracker,2026:software:vgpu:1:eol")
        self.assertEqual(entry["milestone"], "eol")
        self.assertIn("month", entry["reason"].lower())

    def test_a_day_event_is_published_and_the_two_sets_are_disjoint(self):
        result = self.build([product(eol=DAY)])
        self.assertEqual((result["events"], result["excluded"]), (1, 0))
        excluded = json.loads((self.out / feeds.EXCLUSIONS_PATH).read_text())
        self.assertEqual(excluded["excluded"], [])
        # The day event's permanent identity is in the feed, and the account
        # counts it on the feeds' side of the split rather than as an exclusion.
        self.assertIn("tag:eoltracker,2026:software:vgpu:1:eol", self.documents()["atom"])
        self.assertEqual([excluded["counts"][key] for key in ("upcoming_events", "feeds", "excluded")], [1, 1, 0])

    def test_every_upcoming_event_lands_in_exactly_one_side(self):
        products = [product("a", eol=MONTH), product("b", eol=DAY)]
        result = self.build(products)
        excluded = json.loads((self.out / feeds.EXCLUSIONS_PATH).read_text())
        self.assertEqual(result["events"], 1)
        self.assertEqual(result["excluded"], 1)
        self.assertEqual(excluded["counts"]["upcoming_events"], result["events"] + result["excluded"])
        ids = [entry["id"] for entry in excluded["excluded"]]
        self.assertEqual(len(ids), len(set(ids)))
        # The month event's identity is permanent and carries no date; the month
        # it states lives in the entry's own date field, and the event is in the
        # account rather than in the feeds.
        self.assertEqual(excluded["excluded"][0]["date"], MONTH)
        self.assertNotIn(ids[0], self.documents()["atom"])

    def test_a_month_event_still_competes_for_identifier_uniqueness(self):
        # Month events share the identifier space with day events even though
        # only the exclusion document publishes them, so two records minting one
        # id is refused rather than published as one merged deadline.
        with self.assertRaisesRegex(ValueError, "Duplicate event identifier"):
            self.build([product("a", eol=MONTH), product("a", eol=MONTH)])

    def test_a_month_past_its_end_is_not_upcoming_and_not_excluded(self):
        products = [{"id": "a", "name": "Sample", "releases": [
            {"id": "1", "name": "1", "milestones": {"ga": None, "eos": None, "eossec": None, "eol": "2000-01"}}]}]
        self.build(products)
        self.assertEqual(json.loads((self.out / feeds.EXCLUSIONS_PATH).read_text())["counts"]["upcoming_events"], 0)

    def test_a_month_is_never_handed_to_a_day_only_formatter(self):
        # `_ics_date`/`_rfc822` are the two places a day is required; a month
        # must fail loudly rather than be padded or raise from `fromisoformat`.
        for formatter in (feeds._ics_date, feeds._rfc822):
            with self.assertRaisesRegex(ValueError, "month precision"):
                formatter(MONTH)

    def test_the_documented_path_is_the_one_written(self):
        result = self.build([product(eol=MONTH)])
        self.assertIn(str(self.out / feeds.EXCLUSIONS_PATH), result["files"])
        self.assertEqual(feeds.EXCLUSIONS_PATH.as_posix(), "v1/feed-exclusions.json")


class OpenEoxMonthTests(unittest.TestCase):
    """OpenEoX Core carries days only: a month release is excluded, never padded."""

    def release(self, **milestones):
        return {"id": "sample", "releases": [
            {"id": "1", "name": "1", "milestones": {"ga": None, "eos": None, "eossec": None, "eol": None,
                                                    **milestones}}],
            "provenance": {"source_url": "https://example.test/", "verifier": "deterministic-sample",
                           "last_checked": "2026-09-17T00:00:00Z", "upstream_modified": None}}

    def build(self, record):
        self.out = Path(self.temp.name)
        return openeox.build([record], site=self.out)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    def test_a_month_release_is_excluded_with_its_own_code(self):
        index = self.build(self.release(eossec=MONTH, eol=MONTH))
        self.assertEqual(index["counts"]["exported"], 0)
        self.assertEqual(len(index["excluded"]), 1)
        exclusion = index["excluded"][0]
        self.assertEqual(exclusion["code"], "end_of_security_support_month_precision")
        self.assertEqual(exclusion["release"], "1")
        self.assertIn(MONTH, exclusion["reason"])
        # No record at all is written for it, so no day can be invented.
        self.assertEqual(index["records"], [])

    def test_the_excluded_month_never_becomes_a_day_document(self):
        self.build(self.release(eossec=MONTH, eol=MONTH))
        written = list((self.out / "v1" / "openeox").rglob("*.json"))
        self.assertEqual([path.name for path in written], ["index.json"])

    def test_a_day_release_is_still_exported_unchanged(self):
        index = self.build(self.release(eossec=DAY, eol=DAY))
        self.assertEqual(index["counts"]["exported"], 1)
        self.assertEqual(index["excluded"], [])
        record = json.loads((self.out / index["records"][0]["path"]).read_text())
        self.assertEqual(record["end_of_life"], f"{DAY}T23:59:59Z")
        self.assertEqual(openeox.validate_core(record), [])

    def test_a_month_on_an_optional_field_also_excludes_the_release(self):
        # A month anywhere is not a day, so the release cannot be re-expressed;
        # it is excluded rather than published with a gap the month did not state.
        index = self.build(self.release(ga=MONTH, eossec=DAY, eol=DAY))
        self.assertEqual(index["counts"]["exported"], 0)
        self.assertEqual(index["excluded"][0]["code"], "general_availability_month_precision")

    def test_the_conventions_document_the_month_exclusion(self):
        index = self.build(self.release(eossec=MONTH, eol=MONTH))
        self.assertIn("month_precision", index["conventions"])


class VendorRecordPresentationTests(unittest.TestCase):
    """A vendor collector's cells are shown as their own evidence, not a mapping."""

    def record(self):
        return {
            "id": "nvidia-vgpu", "name": "NVIDIA vGPU", "labels": {},
            "provenance": {"source_url": "https://docs.nvidia.com/vgpu/index.html",
                           "verifier": "deterministic-nvidia-vgpu",
                           "last_checked": "2026-09-17T00:00:00Z", "upstream_modified": None},
            "releases": [{"id": "19", "name": "NVIDIA vGPU 19",
                          "milestones": {"ga": None, "eos": None, "eossec": None, "eol": MONTH},
                          "upstream": {"name": "19.1", "table": "Active vGPU Software Releases",
                                       "cells": {"Driver Branch": "R580", "EOL Date": "July 2028"}}}],
        }

    def test_stored_cells_are_surfaced_as_evidence(self):
        row = site_views.release_rows(self.record())[0]
        self.assertEqual([cell["column"] for cell in row["evidence"]], ["Driver Branch", "EOL Date"])
        self.assertEqual(row["evidence"][1]["value"], "July 2028")
        # The verbatim panel shows the cells, not an empty endoflife.date field list.
        self.assertEqual(row["verbatim"]["cells"]["Driver Branch"], "R580")
        self.assertEqual(row["raw"], [])

    def test_a_day_precision_endoflife_record_has_no_vendor_evidence(self):
        record = {"id": "python", "name": "Python", "labels": {},
                  "provenance": {"source_url": "https://endoflife.date/api/v1/products/python/",
                                 "verifier": "deterministic-endoflife-date-v1",
                                 "last_checked": "2026-09-17T00:00:00Z", "upstream_modified": None},
                  "releases": [{"id": "3.14", "name": "3.14", "upstream": {"name": "3.14",
                                "releaseDate": "2025-10-07"},
                                "milestones": {"ga": "2025-10-07", "eos": None, "eossec": None, "eol": None}}]}
        row = site_views.release_rows(record)[0]
        self.assertEqual(row["evidence"], [])
        self.assertEqual(row["raw"][0]["field"], "releaseDate")
        self.assertFalse(row["cells"]["ga"]["month"])

    def test_registry_attribution_is_reused_for_a_vendor_record(self):
        from engine import sources

        verifier = "deterministic-nvidia-vgpu"
        self.assertEqual(site_config.source_name_for(verifier), sources.source_for(verifier).name)
        self.assertEqual(site_config.source_attribution_for(verifier), sources.source_for(verifier).attribution)
        # A researched verifier names a contributor, not a pipeline.
        self.assertIsNone(site_config.source_name_for("researched-zarguell"))
        self.assertEqual(site_config.source_attribution_for("researched-zarguell"), "")

    def test_only_the_endoflife_pipeline_owns_its_label_mapping(self):
        self.assertTrue(site_config.endoflife_date_record("deterministic-endoflife-date-v1"))
        self.assertFalse(site_config.endoflife_date_record("deterministic-nvidia-vgpu"))
        self.assertFalse(site_config.endoflife_date_record("researched-zarguell"))


if __name__ == "__main__":
    unittest.main()
