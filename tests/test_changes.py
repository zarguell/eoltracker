import copy
import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from engine import changes, feeds
from engine.opengear import identity
from engine.site_config import site_url

ATOM = "{http://www.w3.org/2005/Atom}"
CONFIGURE = "https://opengear.com/configure/"
NOTICE = "https://opengear.com/end-life-products"
CHECKED = "2026-09-17T11:00:00Z"
LATER = "2026-09-18T11:00:00Z"


def catalog_record(sku, listed=True, notice=False, matches=(), name=None, source_url=CONFIGURE):
    """One exact configurator model, in the collector's published shape."""
    return {
        "$schema": "https://zarguell.github.io/eoltracker/v1/schema/hardware.json",
        "id": identity("catalog", sku, sku),
        "name": name or sku,
        "category": "hardware",
        "vendor": "Opengear",
        "product_line": "Opengear",
        "family": "catalog",
        "model_number": sku,
        "milestones": {"ga": None, "eos": None, "eossec": None, "eol": None},
        "status": "unknown",
        "upstream": {"SKU": {"text": sku, "value": None, "datetime": None, "role": None, "links": []}},
        "provenance": {"source_urls": [source_url], "verifier": "deterministic-opengear",
                       "last_checked": "2026-09-17T00:00:00Z"},
        "catalog": {"listed": listed, "source_url": source_url},
        "lifecycle": {"listed": notice, "matches": list(matches)},
    }


def lifecycle_record(product="OM2200", parts="OM2216", eos=None, eol="2031-06-30"):
    """One Opengear lifecycle row, named by part grouping rather than dates."""
    record_id = identity("hardware", product, parts)
    return {
        "$schema": "https://zarguell.github.io/eoltracker/v1/schema/hardware.json",
        "id": record_id,
        "name": product,
        "category": "hardware",
        "vendor": "Opengear",
        "product_line": "Opengear",
        "family": "hardware",
        "model_number": parts,
        "milestones": {"ga": None, "eos": eos, "eossec": None, "eol": eol},
        "status": "expiring",
        "upstream": {"Product": {"text": product, "value": None, "datetime": None, "role": None, "links": []}},
        "provenance": {"source_urls": [NOTICE], "verifier": "deterministic-opengear",
                       "last_checked": "2026-09-17T00:00:00Z"},
    }


def kinds(ledger):
    return [event["kind"] for event in ledger["events"]]


def by_kind(ledger, kind):
    return [event for event in ledger["events"] if event["kind"] == kind]


class UpdateHistoryTests(unittest.TestCase):
    def test_first_run_seeds_baseline_without_backfill(self):
        records = [catalog_record("OM2200", listed=True, notice=True, matches=["opengear-x"]),
                   lifecycle_record()]
        seeded = changes.update_history([], records, CHECKED, None)
        self.assertEqual(seeded["version"], changes.LEDGER_VERSION)
        self.assertEqual(seeded["events"], [])
        self.assertEqual(seeded["baseline_at"], CHECKED)
        self.assertEqual(seeded["checked_at"], CHECKED)
        # An empty comparison is the same statement whether or not a ledger exists.
        seeded = changes.update_history([], records, CHECKED, {"version": 1, "events": []})
        self.assertEqual(seeded["events"], [])

    def test_announcement_then_repeat_import_is_idempotent(self):
        sku = catalog_record("OM2200", listed=True, notice=False)
        row = lifecycle_record()
        first = changes.update_history([sku], [sku], CHECKED, None)
        self.assertEqual(first["events"], [])

        announced = catalog_record("OM2200", listed=True, notice=True, matches=[row["id"]])
        second = changes.update_history([sku], [announced], LATER, first)
        self.assertEqual(kinds(second), ["announcement"])
        event = second["events"][0]
        self.assertEqual(event["record_id"], sku["id"])
        self.assertEqual(event["observed_at"], LATER)
        self.assertEqual(event["changes"]["lifecycle.listed"], {"before": False, "after": True})
        self.assertEqual(event["changes"]["lifecycle.matches"], {"before": [], "after": [row["id"]]})
        self.assertEqual(event["source_urls"], [CONFIGURE])
        self.assertNotIn("milestones.eol", event["changes"])
        # The history handed back is extended, not rebuilt: earlier events survive.
        self.assertEqual(second["baseline_at"], CHECKED)

        third = changes.update_history([announced], [announced], "2026-09-19T11:00:00Z", second)
        self.assertEqual(third["events"], second["events"])
        self.assertEqual(changes.update_history([announced], [announced], LATER, third)["events"], second["events"])

    def test_lifecycle_row_appearance_date_correction_and_cleared_date(self):
        row = lifecycle_record()
        baseline = changes.update_history([], [row], CHECKED, None)
        # A row the previous snapshot did not carry is an announcement, and it
        # arrives with the dates it publishes rather than as a date delta.
        appeared = changes.update_history([], [row], LATER, baseline)
        self.assertEqual(kinds(appeared), ["announcement"])
        self.assertEqual(appeared["events"][0]["changes"],
                         {"record.present": {"before": False, "after": True}})
        self.assertEqual(appeared["events"][0]["record_id"], row["id"])

        # A corrected deadline is a date change, in the direction the source published.
        corrected = lifecycle_record(eol="2032-06-30")
        ledger = changes.update_history([row], [corrected], "2026-09-19T11:00:00Z", appeared)
        self.assertEqual(kinds(ledger)[-1], "date_change")
        self.assertEqual(ledger["events"][-1]["changes"],
                         {"milestones.eol": {"before": "2031-06-30", "after": "2032-06-30"}})

        # Clearing a date is published as null, never as the old date or a guess.
        cleared = lifecycle_record(eol=None, eos="2026-06-30")
        ledger = changes.update_history([corrected], [cleared], "2026-09-20T11:00:00Z", ledger)
        self.assertEqual(ledger["events"][-1]["changes"],
                         {"milestones.eos": {"before": None, "after": "2026-06-30"},
                          "milestones.eol": {"before": "2032-06-30", "after": None}})
        self.assertEqual(ledger["events"][-1]["record_id"], row["id"])

    def test_identity_survives_a_date_correction(self):
        row = lifecycle_record(eos="2026-06-30")
        corrected = lifecycle_record(eos="2026-07-31")
        self.assertEqual(row["id"], corrected["id"])
        baseline = changes.update_history([], [row], CHECKED, None)
        ledger = changes.update_history([row], [corrected], LATER, baseline)
        self.assertEqual(ledger["events"][0]["record_id"], row["id"])

    def test_catalog_removal_flip_and_missing_record(self):
        sku = catalog_record("OM2200", listed=True)
        other = catalog_record("CM8100", listed=True)
        baseline = changes.update_history([], [sku, other], CHECKED, None)
        ledger = changes.update_history(
            [sku, other], [catalog_record("OM2200", listed=False)], LATER, baseline)
        removed = by_kind(ledger, "catalog_removed")
        self.assertEqual(len(removed), 2)
        by_record = {event["record_id"]: event for event in removed}
        # Unlisted but retained: the configurator stopped listing it.
        self.assertEqual(by_record[sku["id"]]["changes"],
                         {"catalog.listed": {"before": True, "after": False}})
        # Absent from the snapshot: the listing is gone either way.
        self.assertEqual(by_record[other["id"]]["changes"],
                         {"catalog.listed": {"before": True, "after": None}})
        # Absence is not a support claim, and no date is invented for it.
        self.assertEqual([key for event in removed for key in event["changes"]], ["catalog.listed"] * 2)

    def test_catalog_added_and_unlisted_records_are_not_news(self):
        never_listed = catalog_record("OM2216", listed=False)
        baseline = changes.update_history([], [never_listed], CHECKED, None)
        # Recording an already-unlisted SKU is not an addition or a removal.
        ledger = changes.update_history([never_listed], [never_listed], LATER, baseline)
        self.assertEqual(ledger["events"], [])
        listed = catalog_record("OM2216", listed=True)
        ledger = changes.update_history([never_listed], [listed], LATER, baseline)
        self.assertEqual(kinds(ledger), ["catalog_added"])
        self.assertEqual(ledger["events"][0]["changes"],
                         {"catalog.listed": {"before": False, "after": True}})
        # A record whose snapshot stated no listing reports the unknown honestly.
        unknown = copy.deepcopy(never_listed)
        unknown["catalog"] = {"source_url": CONFIGURE}
        ledger = changes.update_history([unknown], [listed], LATER, baseline)
        self.assertEqual(ledger["events"][0]["changes"],
                         {"catalog.listed": {"before": None, "after": True}})

    def test_withdrawn_notice_and_match_scope_are_notice_changes(self):
        row, sibling = lifecycle_record(), lifecycle_record("OM2200", "OM2232")
        announced = catalog_record("OM2200", notice=True, matches=[row["id"]])
        announced["milestones"]["eol"] = row["milestones"]["eol"]
        baseline = changes.update_history([], [announced], CHECKED, None)
        withdrawn = catalog_record("OM2200", notice=False)
        ledger = changes.update_history([announced], [withdrawn], LATER, baseline)
        # One event: the notice left, and the deadline it published left with it.
        self.assertEqual(kinds(ledger), ["notice_change"])
        self.assertEqual(ledger["events"][0]["changes"],
                         {"lifecycle.listed": {"before": True, "after": False},
                          "lifecycle.matches": {"before": [row["id"]], "after": []},
                          "milestones.eol": {"before": "2031-06-30", "after": None}})
        # Revoked notice state that is recorded again is an announcement.
        ledger = changes.update_history([withdrawn], [announced], "2026-09-19T11:00:00Z", ledger)
        self.assertEqual(kinds(ledger)[-1], "announcement")
        self.assertEqual(ledger["events"][-1]["changes"]["milestones.eol"],
                         {"before": None, "after": "2031-06-30"})

        # A widened match is reported as the exact id sets, with no date picked.
        widened = catalog_record("OM2200", notice=True, matches=[row["id"], sibling["id"]])
        widened["milestones"]["eol"] = row["milestones"]["eol"]
        ledger = changes.update_history([announced], [widened], "2026-09-19T11:00:00Z", ledger)
        event = ledger["events"][-1]
        self.assertEqual(event["kind"], "notice_change")
        self.assertEqual(list(event["changes"]), ["lifecycle.matches"])
        self.assertEqual(event["changes"]["lifecycle.matches"],
                         {"before": [row["id"]], "after": sorted([row["id"], sibling["id"]])})

    def test_lifecycle_rows_removed_and_unmatched_catalog_rows_have_no_dates(self):
        row = lifecycle_record()
        baseline = changes.update_history([], [row], CHECKED, None)
        gone = changes.update_history([row], [], LATER, baseline)
        self.assertEqual(kinds(gone), ["notice_change"])
        self.assertEqual(gone["events"][0]["changes"],
                         {"record.present": {"before": True, "after": False}})

        # An unmatched catalog record publishes no date at all: the collector
        # stores its own raw configurator cells with null milestones, so editing
        # one is not a change to anything the vendor published.
        sku = catalog_record("OM2200", listed=True)
        self.assertEqual(sku["milestones"], {"ga": None, "eos": None, "eossec": None, "eol": None})
        baseline = changes.update_history([], [sku], CHECKED, None)
        self.assertEqual(changes.update_history([sku], [sku], LATER, baseline)["events"], [])

    def test_notice_dates_are_reported_for_the_record_that_publishes_them(self):
        row = lifecycle_record(eol="2031-06-30")
        matched = catalog_record("OM2200", notice=True, matches=[row["id"]])
        matched["milestones"] = {"ga": None, "eos": None, "eossec": None, "eol": "2031-06-30"}
        baseline = changes.update_history([], [matched], CHECKED, None)

        # The announcement reports the dates the notice brought with it.
        unmatched = catalog_record("OM2200", notice=False)
        ledger = changes.update_history([unmatched], [matched], LATER, baseline)
        event = ledger["events"][0]
        self.assertEqual(event["kind"], "announcement")
        self.assertEqual(event["changes"]["milestones.eol"], {"before": None, "after": "2031-06-30"})

        # A later correction to that notice's date is a date change on the record.
        corrected = copy.deepcopy(matched)
        corrected["milestones"]["eol"] = "2032-06-30"
        ledger = changes.update_history([matched], [corrected], "2026-09-19T11:00:00Z", ledger)
        event = ledger["events"][-1]
        self.assertEqual(event["kind"], "date_change")
        self.assertEqual(event["changes"], {"milestones.eol": {"before": "2031-06-30", "after": "2032-06-30"}})

    def test_reversal_mints_a_new_event_and_keeps_the_first(self):
        sku = catalog_record("OM2200", listed=True)
        baseline = changes.update_history([], [sku], CHECKED, None)
        removed = changes.update_history([sku], [catalog_record("OM2200", listed=False)], LATER, baseline)
        restored = changes.update_history(
            [catalog_record("OM2200", listed=False)], [sku], "2026-09-19T11:00:00Z", removed)
        self.assertEqual(kinds(restored), ["catalog_removed", "catalog_added"])
        ids = [event["id"] for event in restored["events"]]
        self.assertEqual(len(set(ids)), 2)
        # Reversing back to the earlier state does not rewrite the earlier event.
        self.assertEqual(restored["events"][0], removed["events"][0])
        again = changes.update_history([sku], [catalog_record("OM2200", listed=False)],
                                       "2026-09-20T11:00:00Z", restored)
        self.assertEqual(kinds(again)[-1], "catalog_removed")
        self.assertNotIn(again["events"][-1]["id"], ids)

    def test_history_input_is_never_mutated(self):
        sku = catalog_record("OM2200", listed=True)
        baseline = changes.update_history([], [sku], CHECKED, None)
        before = copy.deepcopy(baseline)
        changes.update_history([sku], [catalog_record("OM2200", listed=False)], LATER, baseline)
        self.assertEqual(baseline, before)

    def test_other_sources_records_are_not_this_ledger_s_changes(self):
        sku = catalog_record("OM2200", listed=True)
        foreign = lifecycle_record("IM7200", "IM7200 Rev 06")
        foreign["provenance"]["verifier"] = "deterministic-eosl-date"
        baseline = changes.update_history([], [sku, foreign], CHECKED, None)
        # A refresh of the Opengear source replaces only Opengear records, so the
        # eosl.date record's absence is not an observation about Opengear.
        ledger = changes.update_history([sku, foreign], [sku], LATER, baseline)
        self.assertEqual(ledger["events"], [])
        # A record whose source this snapshot does publish is still compared.
        ledger = changes.update_history([sku, foreign], [sku, lifecycle_record()], LATER, baseline)
        self.assertEqual(kinds(ledger), ["announcement"])

    def test_duplicate_ids_and_missing_timestamp_are_rejected(self):
        sku = catalog_record("OM2200", listed=True)
        for snapshot in ([sku, copy.deepcopy(sku)],):
            with self.assertRaisesRegex(ValueError, "Duplicate hardware record id"):
                changes.update_history([], snapshot, CHECKED, None)
        for value in (None, "", "  ", "17 September 2026"):
            with self.assertRaises(ValueError):
                changes.update_history([], [sku], value, None)


class BuildTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.out = Path(self.temp.name)

    def ledger(self):
        row = lifecycle_record()
        announced = catalog_record("OM2200 & <rev>", notice=True, matches=[row["id"]],
                                   source_url=CONFIGURE + "?sku=OM2200&rev=2")
        baseline = changes.update_history([], [announced, row], CHECKED, None)
        first = changes.update_history([], [announced, row], LATER, baseline)
        corrected = lifecycle_record(eol="2032-06-30")
        return changes.update_history(
            [row], [corrected], "2026-09-19T11:00:00Z", first)

    def test_build_writes_json_and_atom_without_a_calendar(self):
        result = changes.build(self.ledger(), out_dir=self.out)
        json_path, atom_path = self.out / "v1/changes.json", self.out / "v1/changes.atom"
        self.assertEqual(result["files"], [str(json_path), str(atom_path)])
        self.assertEqual(result["updated"], "2026-09-19T11:00:00Z")
        document = json.loads(json_path.read_text(encoding="utf-8"))
        self.assertEqual(document["count"], result["events"])
        self.assertEqual(document["updated"], result["updated"])
        self.assertEqual(document["id"], changes.CHANGES_FEED_ID)
        self.assertNotEqual(changes.CHANGES_FEED_ID, feeds.FEED_ID)
        # The published document is the ledger contract plus the feed's identity,
        # so a reader of the endpoint and of the stored file read one shape.
        ledger = self.ledger()
        self.assertEqual(sorted(event["id"] for event in document["events"]),
                         sorted(event["id"] for event in ledger["events"]))
        self.assertEqual({key: document[key] for key in ("version", "checked_at", "baseline_at")},
                         {key: ledger[key] for key in ("version", "checked_at", "baseline_at")})
        # Newest observation first, and no milestone feed is touched.
        observed = [event["observed_at"] for event in document["events"]]
        self.assertEqual(observed, sorted(observed, reverse=True))
        self.assertEqual(sorted(p.name for p in (self.out / "v1").iterdir()),
                         ["changes.atom", "changes.json"])

    def test_atom_is_valid_and_escaped_with_before_after_and_sources(self):
        changes.build(self.ledger(), out_dir=self.out)
        text = (self.out / "v1/changes.atom").read_text(encoding="utf-8")
        feed = ET.fromstring(text)
        self.assertEqual(feed.find(f"{ATOM}id").text, changes.CHANGES_FEED_ID)
        entries = feed.findall(f"{ATOM}entry")
        self.assertEqual(len(entries), 4)
        for entry in entries:
            self.assertTrue(entry.find(f"{ATOM}id").text.startswith(feeds.TAG_PREFIX))
            self.assertTrue(entry.find(f"{ATOM}link").get("href").startswith(site_url("hardware/")))
        titles = [entry.find(f"{ATOM}title").text for entry in entries]
        # A SKU is an exact vendor model string, escapes intact in the XML.
        self.assertIn("OM2200 & <rev> — added to the vendor catalog", titles)
        self.assertIn("OM2200 — announcement observed", titles)
        by_title = dict(zip(titles, entries))
        correction = by_title["OM2200 — published dates changed"]
        summary = correction.find(f"{ATOM}summary").text
        self.assertIn("End of support Jun 30, 2031 (2031-06-30) → Jun 30, 2032 (2032-06-30)", summary)
        self.assertIn("Observed 2026-09-19T11:00:00Z UTC.", summary)
        self.assertIn(NOTICE, summary)
        added = by_title["OM2200 & <rev> — added to the vendor catalog"]
        self.assertIn("Vendor catalog listing not captured → listed", added.find(f"{ATOM}summary").text)
        self.assertIn(CONFIGURE + "?sku=OM2200&rev=2", added.find(f"{ATOM}summary").text)
        announcement = by_title["OM2200 — announcement observed"]
        self.assertIn("Record in the source table absent → present",
                      announcement.find(f"{ATOM}summary").text)
        self.assertEqual(announcement.find(f"{ATOM}updated").text, LATER)

    def test_cleared_date_renders_as_not_published_and_empty_ledger_builds(self):
        row = lifecycle_record()
        baseline = changes.update_history([], [row], CHECKED, None)
        ledger = changes.update_history([row], [lifecycle_record(eol=None)], LATER, baseline)
        changes.build(ledger, out_dir=self.out)
        entry = ET.fromstring((self.out / "v1/changes.atom").read_text(encoding="utf-8")).find(f"{ATOM}entry")
        self.assertIn("End of support Jun 30, 2031 (2031-06-30) → not published",
                      entry.find(f"{ATOM}summary").text)

        empty = changes.build({"version": 1, "baseline_at": CHECKED, "checked_at": CHECKED, "events": []},
                              out_dir=self.out)
        self.assertEqual(empty["events"], 0)
        self.assertEqual(empty["updated"], CHECKED)
        feed = ET.fromstring((self.out / "v1" / "changes.atom").read_text(encoding="utf-8"))
        self.assertEqual(feed.findall(f"{ATOM}entry"), [])
        self.assertEqual(json.loads((self.out / "v1" / "changes.json").read_text(encoding="utf-8"))["events"], [])


class LedgerValidationTests(unittest.TestCase):
    """A ledger that would publish duplicate or unaddressable entries is refused (#114)."""

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.out = Path(temp.name)

    def ledger(self):
        row = lifecycle_record()
        baseline = changes.update_history([], [row], CHECKED, None)
        return changes.update_history([], [row], LATER, baseline)

    def test_a_duplicate_event_id_is_refused_before_anything_is_written(self):
        ledger = self.ledger()
        duplicate = copy.deepcopy(ledger["events"][0])
        ledger = {**ledger, "events": ledger["events"] + [duplicate]}
        with self.assertRaisesRegex(ValueError, "Duplicate change ledger event id"):
            changes.build(ledger, out_dir=self.out)
        # Nothing was published: no duplicate Atom entry survives a failed build.
        self.assertFalse((self.out / "v1" / "changes.atom").exists())
        self.assertFalse((self.out / "v1" / "changes.json").exists())

    def test_an_event_without_a_permanent_id_is_refused(self):
        ledger = self.ledger()
        ledger = {**ledger, "events": [{**ledger["events"][0], "id": "not-a-tag"}]}
        with self.assertRaisesRegex(ValueError, "not a permanent tag URI"):
            changes.build(ledger, out_dir=self.out)

    def test_an_event_with_no_id_at_all_is_refused(self):
        ledger = self.ledger()
        event = {key: value for key, value in ledger["events"][0].items() if key != "id"}
        with self.assertRaisesRegex(ValueError, "has no id"):
            changes.build({**ledger, "events": [event]}, out_dir=self.out)

    def test_a_wrong_ledger_version_is_refused(self):
        ledger = {**self.ledger(), "version": changes.LEDGER_VERSION + 1}
        with self.assertRaisesRegex(ValueError, "version"):
            changes.build(ledger, out_dir=self.out)

    def test_a_valid_ledger_still_publishes_distinct_entries(self):
        result = changes.build(self.ledger(), out_dir=self.out)
        document = json.loads((self.out / "v1" / "changes.json").read_text(encoding="utf-8"))
        ids = [event["id"] for event in document["events"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len(ids), result["events"])
        # The published Atom feed carries one entry per distinct id.
        entries = ET.fromstring((self.out / "v1" / "changes.atom").read_text(encoding="utf-8")) \
            .findall(f"{ATOM}entry")
        self.assertEqual(sorted(entry.find(f"{ATOM}id").text for entry in entries), sorted(ids))


if __name__ == "__main__":
    unittest.main()
