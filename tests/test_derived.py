"""Derived lifecycle dates: recomputable, labelled, and absent from exact surfaces.

A derived date is arithmetic on a base date and a rule the vendor states — an
explicit duration, the release that ends a line, or a parent platform whose
lifecycle a component follows. `engine/derived.py` computes it and re-checks it;
the site labels it and shows the rule; the day-precision surfaces (the upcoming
list, the three feeds and the OpenEoX export) must not carry it, because each of
them publishes days a *source* states.

These tests pin the boundaries where a plausible mistake is silent: a rule that
does not reproduce the stored date (a tampered result or base), provenance keyed
by a milestone that is absent (an orphan), a derived date leaking into an
exact-only document, a month-precision inheritance being carried as a day, and a
contribution losing the property on the way into the catalog.
"""
import copy
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from engine import derived, feeds, openeox, site, site_views
from engine.contribute import (
    build_record, install_file, parse_contribution, research_object, validate_research)

QUOTE = ("TestCity 1 reached general availability on April 1, 2025 and every release is supported "
         "for five years from its general availability date.")
DURATION_QUOTE = "Every release is supported for five years from its general availability date."
SOURCE = "https://vendor.example/lifecycle"


def duration_entry(**overrides):
    entry = {
        "kind": "derived",
        "method": "release-plus-duration",
        "source_url": SOURCE,
        "quote": DURATION_QUOTE,
        "base_date": "2025-04-01",
        "base_label": "general availability",
        "duration": {"value": 5, "unit": "year"},
    }
    entry.update(overrides)
    return entry


def release(milestones=None, provenance=None):
    return {
        "id": "1", "name": "1",
        "milestones": {"ga": "2025-04-01", "eos": None, "eossec": None, "eol": "2030-04-01",
                       **(milestones or {})},
        "upstream": {"name": "1"},
        **(provenance if provenance is not None else
           {"milestone_provenance": {"eol": duration_entry()}}),
    }


def record(slug="testcity", releases=None, verifier="deterministic-sample"):
    return {
        "id": slug, "name": "TestCity", "category": "software", "upstream_category": "server-app",
        "labels": {}, "links": {}, "identifiers": [],
        "releases": releases if releases is not None else [release()],
        "provenance": {"source_url": SOURCE, "verifier": verifier,
                       "last_checked": "2026-09-23T00:00:00Z", "upstream_modified": None},
    }


class CalendarArithmeticTests(unittest.TestCase):
    """The arithmetic is calendar-based, not a fixed day count."""

    def test_years_and_months_land_on_the_stated_day(self):
        self.assertEqual(derived.add_duration("2025-04-01", 5, "year"), "2030-04-01")
        self.assertEqual(derived.add_duration("2025-04-01", 18, "month"), "2026-10-01")
        self.assertEqual(derived.add_duration("2025-04-01", 30, "day"), "2025-05-01")

    def test_a_month_without_the_day_clamps_to_its_last(self):
        # 2025-01-31 + 1 month has no 31st to land on; February's own end is the
        # only date the rule can produce without naming a day that does not exist.
        self.assertEqual(derived.add_duration("2025-01-31", 1, "month"), "2025-02-28")
        self.assertEqual(derived.add_duration("2024-01-31", 1, "month"), "2024-02-29")
        self.assertEqual(derived.add_duration("2024-02-29", 1, "year"), "2025-02-28")

    def test_a_duration_must_be_a_positive_whole_unit(self):
        for value, unit in ((0, "year"), (-1, "month"), ("5", "year"), (5, "week")):
            with self.assertRaises(ValueError):
                derived.add_duration("2025-04-01", value, unit)


class DurationDerivationTests(unittest.TestCase):
    """`validate_milestone_provenance` re-derives the date beside it."""

    def test_a_stated_duration_reproduces_its_milestone(self):
        milestones = {"ga": "2025-04-01", "eos": None, "eossec": None, "eol": "2030-04-01"}
        provenance = {"eol": duration_entry()}
        self.assertIsNone(derived.validate_milestone_provenance(milestones, provenance, "t"))
        self.assertEqual(derived.derive(milestones, provenance), {"eol": "2030-04-01"})

    def test_a_result_its_own_rule_does_not_produce_is_refused(self):
        # The recorded result IS the milestone value, so tampering with either
        # the date or the rule that produced it has to fail.
        milestones = {"ga": "2025-04-01", "eos": None, "eossec": None, "eol": "2031-04-01"}
        with self.assertRaisesRegex(ValueError, "but the stored eol milestone is 2031-04-01"):
            derived.validate_milestone_provenance(milestones, {"eol": duration_entry()}, "t")

    def test_a_tampered_base_no_longer_matches_the_result(self):
        milestones = {"ga": "2025-04-01", "eos": None, "eossec": None, "eol": "2030-04-01"}
        tampered = duration_entry(base_date="2024-04-01")
        with self.assertRaisesRegex(ValueError, "is 2029-04-01"):
            derived.validate_milestone_provenance(milestones, {"eol": tampered}, "t")

    def test_provenance_is_keyed_only_by_a_published_milestone(self):
        milestones = {"ga": "2025-04-01", "eos": None, "eossec": None, "eol": None}
        with self.assertRaisesRegex(ValueError, "the eol milestone is absent"):
            derived.validate_milestone_provenance(milestones, {"eol": duration_entry()}, "t")

    def test_an_unknown_milestone_or_method_is_refused(self):
        milestones = {"ga": "2025-04-01", "eos": None, "eossec": None, "eol": "2030-04-01"}
        with self.assertRaisesRegex(ValueError, "unknown milestone keys"):
            derived.validate_milestone_provenance(milestones, {"supported": duration_entry()}, "t")
        with self.assertRaisesRegex(ValueError, "method must be one of"):
            derived.validate_milestone_provenance(
                milestones, {"eol": duration_entry(method="cadence")}, "t")

    def test_the_branches_are_mutually_exclusive(self):
        milestones = {"ga": "2025-04-01", "eos": None, "eossec": None, "eol": "2030-04-01"}
        both = duration_entry(trigger={"release_id": "2", "date": "2030-04-01", "label": "2"})
        with self.assertRaisesRegex(ValueError, "unknown fields"):
            derived.validate_milestone_provenance(milestones, {"eol": both}, "t")
        missing = duration_entry()
        del missing["duration"]
        with self.assertRaisesRegex(ValueError, "missing fields"):
            derived.validate_milestone_provenance(milestones, {"eol": missing}, "t")

    def test_every_entry_states_it_is_derived(self):
        milestones = {"ga": "2025-04-01", "eos": None, "eossec": None, "eol": "2030-04-01"}
        with self.assertRaisesRegex(ValueError, "kind must be 'derived'"):
            derived.validate_milestone_provenance(
                milestones, {"eol": duration_entry(kind="stated")}, "t")

    def test_an_absent_property_is_valid(self):
        # The property is optional: every record that predates it stays valid.
        self.assertIsNone(derived.validate_milestone_provenance(
            {"ga": None, "eos": None, "eossec": None, "eol": "2030-04-01"}, None, "t"))

    def test_cadence_is_not_representable_as_a_duration(self):
        # A policy of approximate intervals states no duration, so a rule
        # claiming one has to be refused rather than admitted as a number.
        milestones = {"ga": "2025-04-01", "eos": None, "eossec": None, "eol": "2030-04-01"}
        with self.assertRaisesRegex(ValueError, "duration unit must be one of"):
            derived.validate_milestone_provenance(
                milestones, {"eol": duration_entry(duration={"value": 1, "unit": "cadence"})}, "t")
        with self.assertRaisesRegex(ValueError, "duration value must be a positive integer"):
            derived.validate_milestone_provenance(
                milestones, {"eol": duration_entry(duration={"value": 0, "unit": "year"})}, "t")


class TriggerDerivationTests(unittest.TestCase):
    """A trigger date is the derived deadline, and it must be a published release."""

    TRIGGER = {"release_id": "3", "date": "2027-06-17", "label": "3.0.0 release"}
    QUOTE = ("With the release of TestCity 3 we are marking TestCity 1 as end of life; it will no "
             "longer receive support updates.")
    MILESTONES = {"ga": "2025-04-01", "eos": None, "eossec": None, "eol": "2027-06-17"}

    def entry(self, **overrides):
        entry = {
            "kind": "derived", "method": "release-trigger", "source_url": SOURCE, "quote": self.QUOTE,
            "base_date": "2025-04-01", "base_label": "TestCity 1 general availability",
            "trigger": dict(self.TRIGGER),
        }
        entry.update(overrides)
        return entry

    def test_a_stated_release_trigger_reproduces_its_milestone(self):
        self.assertIsNone(derived.validate_milestone_provenance(
            self.MILESTONES, {"eol": self.entry()}, "t", {"1", "3"}))

    def test_the_trigger_date_is_the_deadline_not_a_second_date(self):
        entry = self.entry()
        entry["trigger"]["date"] = "2027-07-01"
        with self.assertRaisesRegex(ValueError, "is not the eol milestone"):
            derived.validate_milestone_provenance(self.MILESTONES, {"eol": entry}, "t", {"1", "3"})

    def test_the_triggering_release_must_exist_in_the_record(self):
        with self.assertRaisesRegex(ValueError, "names no release in this record"):
            derived.validate_milestone_provenance(self.MILESTONES, {"eol": self.entry()}, "t", {"1"})

    def test_a_trigger_cannot_precede_the_release_it_ends(self):
        # The trigger is the later event by definition, so a base after it is
        # the entry contradicting itself.
        entry = self.entry()
        entry["base_date"] = "2028-01-01"
        with self.assertRaisesRegex(ValueError, "cannot come before the release it ends"):
            derived.validate_milestone_provenance(self.MILESTONES, {"eol": entry}, "t", {"1", "3"})


class InheritanceDerivationTests(unittest.TestCase):
    """A component inherits a parent's deadline, stated by the vendor."""

    FIXED_POLICY = ("A component receives the same support as its parent product or platform. "
                    "When a parent product or platform is in Mainstream, or Extended Support, so is "
                    "the component. When a parent product or platform reaches the end of support, so "
                    "does the component.")
    MILESTONES = {"ga": "2021-09-01", "eos": None, "eossec": None, "eol": "2031-10-14"}

    def entry(self, **overrides):
        entry = {
            "kind": "derived", "method": "support-inheritance", "source_url": SOURCE,
            "quote": self.FIXED_POLICY, "base_date": "2021-09-01", "base_label": "parent general availability",
            "parent": {"product_id": "windows-server", "release_id": "2022",
                       "release_name": "Windows Server 2022", "milestone": "eol",
                       "date": "2031-10-14", "source_url": "https://learn.microsoft.com/parent"},
        }
        entry.update(overrides)
        return entry

    def test_a_stated_inheritance_reproduces_the_milestone(self):
        self.assertIsNone(derived.validate_milestone_provenance(self.MILESTONES, {"eol": self.entry()}, "t"))
        self.assertEqual(derived.derive(self.MILESTONES, {"eol": self.entry()}), {"eol": "2031-10-14"})

    def test_the_vendors_own_inheritance_sentence_is_accepted_without_follow(self):
        # Microsoft's Fixed Policy states the rule; it never uses the verb
        # "follow", so a literal "follow" match would refuse the real evidence.
        for wording in (
            self.FIXED_POLICY,
            "Internet Information Services (IIS) is a component of the Windows operating system and "
            "follows the same lifecycle.",
            "Minor releases follow the same lifecycle as the major product release.",
        ):
            self.assertIsNone(derived.validate_milestone_provenance(
                self.MILESTONES, {"eol": self.entry(quote=wording)}, "t"))

    def test_a_quote_stating_the_parents_dates_is_not_an_inheritance_statement(self):
        for wording in ("Windows Server 2022 is supported until October 14, 2031.",
                        "IIS 10.0 is included with Windows Server 2022.",
                        "The parent platform reaches the end of support on October 14, 2031."):
            with self.assertRaisesRegex(ValueError, "does not state that this component's support"):
                derived.validate_milestone_provenance(
                    self.MILESTONES, {"eol": self.entry(quote=wording)}, "t")

    def test_the_inherited_milestone_must_be_an_end_milestone(self):
        entry = self.entry()
        entry["parent"]["milestone"] = "ga"
        with self.assertRaisesRegex(ValueError, "parent.milestone must be one of"):
            derived.validate_milestone_provenance(self.MILESTONES, {"eol": entry}, "t")

    def test_the_parent_date_is_the_deadline(self):
        entry = self.entry()
        entry["parent"]["date"] = "2031-11-01"
        with self.assertRaisesRegex(ValueError, "is not the eol milestone"):
            derived.validate_milestone_provenance(self.MILESTONES, {"eol": entry}, "t")


class SchemaTests(unittest.TestCase):
    """The published schema admits the property and refuses every malformed shape."""

    def schema(self):
        from jsonschema import Draft202012Validator, FormatChecker

        path = Path(site.ROOT) / "schema" / "product.json"
        schema = json.loads(path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        return Draft202012Validator(schema, format_checker=FormatChecker())

    def valid_record(self):
        """A committed endoflife.date-shaped record with one derived milestone."""
        from engine.importer import normalize

        base = {"result": {"name": "sample", "label": "Sample", "category": "lang", "labels": {},
                           "releases": [{"name": "1", "releaseDate": "2025-04-01"}]}}
        record = normalize(base, "2026-09-23T00:00:00Z")
        record["releases"][0].update(release())
        return record

    def test_a_record_without_the_property_is_unchanged(self):
        # Every committed record predates this field; adding it must not alter
        # the shape of a record that does not carry it.
        plain = self.valid_record()
        del plain["releases"][0]["milestone_provenance"]
        self.schema().validate(plain)

    def test_a_well_formed_entry_validates(self):
        self.schema().validate(self.valid_record())

    def test_an_empty_object_is_refused(self):
        # Stating no rule is not the same as stating one; the property is
        # omitted instead, which is what every existing record does.
        from jsonschema.exceptions import ValidationError

        record = self.valid_record()
        record["releases"][0]["milestone_provenance"] = {}
        with self.assertRaises(ValidationError):
            self.schema().validate(record)

    def test_a_second_rule_branch_on_one_entry_is_refused(self):
        from jsonschema.exceptions import ValidationError

        # A duration entry that also carries a trigger leaves two answers to
        # recompute, so the schema refuses it rather than picking one.
        record = self.valid_record()
        record["releases"][0]["milestone_provenance"]["eol"]["trigger"] = {
            "release_id": "2", "date": "2030-04-01", "label": "2"}
        with self.assertRaises(ValidationError):
            self.schema().validate(record)

    def test_an_unknown_method_is_refused(self):
        from jsonschema.exceptions import ValidationError

        record = self.valid_record()
        record["releases"][0]["milestone_provenance"]["eol"]["method"] = "cadence"
        with self.assertRaises(ValidationError):
            self.schema().validate(record)

    def test_a_derived_entry_cannot_smuggle_a_result_field(self):
        from jsonschema.exceptions import ValidationError

        record = self.valid_record()
        record["releases"][0]["milestone_provenance"]["eol"]["result"] = "2030-04-01"
        with self.assertRaises(ValidationError):
            self.schema().validate(record)

    def test_the_property_is_keyed_by_milestone_name_only(self):
        from jsonschema.exceptions import ValidationError

        record = self.valid_record()
        record["releases"][0]["milestone_provenance"]["supported"] = duration_entry()
        with self.assertRaises(ValidationError):
            self.schema().validate(record)


class ContributionRoundTripTests(unittest.TestCase):
    """A contribution that states a rule survives into the catalog with it."""

    def payload(self, **overrides):
        payload = {
            "target": "software", "id": "researched-testcity", "name": "TestCity", "vendor": "Acme",
            "category": "server-app",
            "milestones": {"ga": "2025-04-01", "eol": "2030-04-01"},
            "milestone_provenance": {"eol": duration_entry()},
            "evidence": [{"quote": QUOTE, "source_url": SOURCE, "retrieved_at": "2026-09-23"}],
            "contributor": "zarguell",
        }
        payload.update(overrides)
        return payload

    def build(self, payload):
        contribution = parse_contribution(payload, path="contribution.json")
        research = research_object(contribution, contribution["evidence"], None)
        return build_record(contribution, research, "2026-09-23T00:00:00Z")

    def test_the_property_survives_parsing_and_lands_on_the_release(self):
        record = self.build(self.payload())
        stored = record["releases"][0]["milestone_provenance"]["eol"]
        self.assertEqual(stored, duration_entry())
        # ...and the whole record still passes the researched-record gate.
        validate_research(record, "software")

    def test_a_rule_that_does_not_match_its_stated_date_is_refused_at_admission(self):
        with self.assertRaisesRegex(ValueError, "but the stored eol milestone is"):
            parse_contribution(self.payload(milestones={"ga": "2025-04-01", "eol": "2031-04-01"}))

    def test_a_tampered_record_fails_the_catalog_gate(self):
        record = self.build(self.payload())
        record["releases"][0]["milestones"]["eol"] = "2031-04-01"
        with self.assertRaisesRegex(ValueError, "but the stored eol milestone is"):
            validate_research(record, "software")

    def test_a_derived_milestone_is_exempt_from_the_literal_quote_rule(self):
        # The vendor states a rule, not a day, so no sentence contains the
        # result; the rule's own quote is the evidence for exactly that key.
        # Every stated milestone stays on the literal rule, so moving the GA
        # date away from the sentence fails even though eol still derives.
        record = self.build(self.payload())
        self.assertEqual(record["releases"][0]["milestones"]["eol"], "2030-04-01")
        with self.assertRaisesRegex(ValueError, "no stored quote states the general availability date"):
            parse_contribution(self.payload(
                milestones={"ga": "2025-05-01", "eol": "2030-05-01"},
                milestone_provenance={"eol": duration_entry(base_date="2025-05-01")}))

    def test_a_hardware_contribution_cannot_carry_the_software_only_property(self):
        # Hardware records have no releases and one milestone set, so the
        # release-level property has no shape to attach to there.
        with self.assertRaisesRegex(ValueError, "software-only fields"):
            parse_contribution({
                "target": "hardware", "id": "researched-acme-edge-100", "name": "ACME Edge 100",
                "vendor": "ACME", "milestones": {"ga": "2020-04-01", "eol": "2030-04-01"},
                "milestone_provenance": {"eol": duration_entry(base_date="2020-04-01",
                                                               duration={"value": 10, "unit": "year"})},
                "evidence": [{"quote": QUOTE, "source_url": SOURCE, "retrieved_at": "2026-09-23"}],
                "contributor": "zarguell",
            })

    def test_an_install_round_trips_through_the_committed_catalog(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        (root / "products").mkdir()
        path = root / "contribution.json"
        path.write_text(json.dumps(self.payload()), encoding="utf-8")
        report = install_file(path, root=root, allow_stale=True, now=None)
        committed = json.loads((root / "products" / "researched-testcity.json").read_text())
        self.assertEqual(committed["releases"][0]["milestone_provenance"]["eol"], duration_entry())
        self.assertEqual(report["action"], "install")


class UpcomingSummaryTests(unittest.TestCase):
    """The product page's "next deadline" is a date a source states."""

    def rows(self, milestones, provenance=None):
        return site_views.release_rows(record(releases=[release(milestones, provenance)]))

    def test_a_derived_deadline_is_not_an_upcoming_event(self):
        rows = self.rows({})
        self.assertEqual(site_views.upcoming_events(rows, date(2026, 1, 1)), [])

    def test_the_same_date_is_upcoming_when_the_vendor_states_it(self):
        # The control: identical dates, no provenance, so the same day is listed.
        rows = self.rows({}, provenance={})
        events = site_views.upcoming_events(rows, date(2026, 1, 1))
        self.assertEqual([event["date"] for event in events], ["2030-04-01"])

    def test_the_summary_does_not_advertise_a_derived_deadline(self):
        summary = site_views.summarize(record(releases=[release()]), self.rows({}), date(2026, 1, 1))
        self.assertIsNone(summary["next"])
        self.assertTrue(summary["derived"])

    def test_the_derived_disclosure_reaches_the_release_cell(self):
        row = self.rows({})[0]
        view = row["cells"]["eol"]["derived"]
        self.assertEqual(view["label"], "derived")
        self.assertEqual(view["method"], "release-plus-duration")
        self.assertEqual(view["calculation"], "5 years from general availability (Apr 1, 2025)")
        self.assertEqual(view["quote"], DURATION_QUOTE)
        self.assertEqual(view["source_url"], SOURCE)
        # A milestone the record states carries no disclosure.
        self.assertIsNone(row["cells"]["ga"]["derived"])


class FeedExclusionTests(unittest.TestCase):
    """The day-precision feeds carry days a source states, and say what they drop."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.out = Path(self.temp.name)

    def build(self, products, hardware=None):
        return feeds.build(products, hardware, out_dir=self.out,
                           manifest={"generated_at": "2026-09-17T11:51:01Z"})

    def exclusions(self):
        return json.loads((self.out / feeds.EXCLUSIONS_PATH).read_text())

    def documents(self):
        return {name: (self.out / path).read_text(encoding="utf-8", newline="")
                for name, path in feeds.FEED_PATHS.items()}

    def test_a_derived_event_is_excluded_from_all_three_documents(self):
        result = self.build([record()])
        self.assertEqual((result["events"], result["excluded"]), (0, 1))
        for name, text in self.documents().items():
            self.assertNotIn("2030-04-01", text, name)
        excluded = self.exclusions()
        entry = excluded["excluded"][0]
        self.assertEqual(entry["code"], feeds.DERIVED_EXCLUSION_CODE)
        self.assertEqual(entry["date"], "2030-04-01")
        self.assertEqual(entry["id"], "tag:eoltracker,2026:testcity-1-eol-2030-04-01")
        self.assertEqual(entry["milestone"], "eol")
        # The rule travels with the exclusion, so a consumer can recompute it.
        self.assertEqual(entry["derived"]["method"], "release-plus-duration")
        self.assertEqual(entry["derived"]["base_date"], "2025-04-01")
        self.assertEqual(entry["derived"]["duration"], {"value": 5, "unit": "year"})
        self.assertEqual(entry["derived"]["quote"], DURATION_QUOTE)
        self.assertNotIn("month", entry)

    def test_the_same_date_is_syndicated_when_the_vendor_states_it(self):
        # The control: identical dates with no provenance are published.
        result = self.build([record(releases=[release(provenance={})])])
        self.assertEqual((result["events"], result["excluded"]), (1, 0))
        self.assertIn("2030-04-01", self.documents()["atom"])

    def test_the_accounting_invariant_holds_across_both_exclusion_kinds(self):
        products = [
            record("derived-one"),
            record("stated-one", releases=[release(provenance={})]),
            record("monthly", releases=[
                {"id": "1", "name": "1", "upstream": {"name": "1"},
                 "milestones": {"ga": None, "eos": None, "eossec": None, "eol": "2099-07"}}]),
        ]
        result = self.build(products)
        excluded = self.exclusions()
        counts = excluded["counts"]
        self.assertEqual(counts["upcoming_events"], result["events"] + result["excluded"])
        self.assertEqual(counts["by_code"][feeds.DERIVED_EXCLUSION_CODE], 1)
        self.assertEqual(counts["by_code"][feeds.MONTH_EXCLUSION_CODE], 1)
        self.assertEqual(sum(counts["by_code"].values()), counts["excluded"])
        excluded_ids = {entry["id"] for entry in excluded["excluded"]}
        self.assertEqual({entry["code"] for entry in excluded["excluded"]},
                         {feeds.DERIVED_EXCLUSION_CODE, feeds.MONTH_EXCLUSION_CODE})
        # Disjoint from the feeds and complete with them: every upcoming event
        # is on exactly one side, and the month event keeps its own code and
        # stored month while the derived event carries its rule.
        events = feeds.upcoming_events(products)
        published, split_out = feeds.representable(events)
        published_ids = {event["id"] for event in published}
        self.assertEqual(len(events), counts["upcoming_events"])
        self.assertEqual(published_ids & excluded_ids, set())
        self.assertEqual(published_ids | excluded_ids, {event["id"] for event in events})
        self.assertEqual(split_out, [event for event in events if event["id"] in excluded_ids])
        by_id = {entry["id"]: entry for entry in excluded["excluded"]}
        derived_entry = next(entry for entry in excluded["excluded"]
                             if entry["code"] == feeds.DERIVED_EXCLUSION_CODE)
        self.assertEqual(derived_entry["derived"]["base_date"], "2025-04-01")
        self.assertEqual(by_id[derived_entry["id"]]["milestone"], "eol")

    def test_each_exclusion_names_the_reason_it_is_published_under(self):
        self.build([record()])
        excluded = self.exclusions()
        codes = [reason["code"] for reason in excluded["reasons"]]
        self.assertEqual(codes, list(feeds.EXCLUSION_REASON_BY_CODE))
        for entry in excluded["excluded"]:
            statement = feeds.EXCLUSION_REASON_BY_CODE[entry["code"]]["statement"]
            self.assertEqual(entry["reason"], statement)
            self.assertIn(entry["code"], codes)


class OpenEoxExclusionTests(unittest.TestCase):
    """OpenEoX Core carries the source's own lifecycle dates, not arithmetic."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.out = Path(self.temp.name)

    def build(self, rec):
        return openeox.build([rec], site=self.out)

    def test_a_derived_release_is_excluded_with_its_own_code(self):
        index = self.build(record())
        self.assertEqual(index["counts"]["exported"], 0)
        self.assertEqual(index["counts"]["excluded"], 1)
        exclusion = index["excluded"][0]
        self.assertEqual(exclusion["code"], "end_of_life_derived")
        self.assertEqual(exclusion["release"], "1")
        # The reason names the rule and the base, so the exclusion is auditable.
        self.assertIn("release-plus-duration", exclusion["reason"])
        self.assertIn("2025-04-01", exclusion["reason"])
        self.assertEqual(index["records"], [])

    def test_no_derived_record_is_written_at_all(self):
        self.build(record())
        written = sorted(path.name for path in (self.out / "v1" / "openeox").rglob("*.json"))
        self.assertEqual(written, ["index.json"])

    def test_the_same_dates_are_exported_when_the_vendor_states_them(self):
        # The control: identical dates, no provenance, so a conforming record
        # is written with the day the source states.
        rec = record(releases=[
            release({"eossec": "2030-04-01"}, provenance={})])
        index = self.build(rec)
        self.assertEqual(index["counts"]["exported"], 1)
        self.assertEqual(index["excluded"], [])
        written = json.loads((self.out / index["records"][0]["path"]).read_text())
        self.assertEqual(written["end_of_life"], "2030-04-01T23:59:59Z")
        self.assertEqual(openeox.validate_core(written), [])

    def test_the_index_documents_the_derived_exclusion(self):
        index = self.build(record())
        self.assertIn("derived", index["conventions"])
        self.assertIn("_derived", index["conventions"]["derived"])

    def test_a_derived_optional_field_also_excludes_the_release(self):
        # A derived value anywhere in the release — here the optional
        # general_availability — makes the whole release unexportable, because
        # the record it would be re-expressed from is not all vendor-stated.
        rec = record(releases=[
            release({"ga": "2025-04-01", "eossec": "2030-04-01", "eos": None},
                    {"milestone_provenance": {"ga": duration_entry(
                        base_date="2020-04-01", base_label="first release date")}})])
        index = self.build(rec)
        self.assertEqual(index["counts"]["exported"], 0)
        self.assertEqual(index["excluded"][0]["code"], "general_availability_derived")


class CatalogGateTests(unittest.TestCase):
    """`engine.validation.check_derived` re-checks a committed record's arithmetic."""

    def test_a_derived_record_passes_and_a_tampered_one_fails(self):
        from engine.validation import check_derived

        rec = record(verifier="deterministic-endoflife-date-v1")
        check_derived(rec)
        tampered = copy.deepcopy(rec)
        tampered["releases"][0]["milestones"]["eol"] = "2031-04-01"
        with self.assertRaisesRegex(ValueError, "but the stored eol milestone is"):
            check_derived(tampered)

    def test_a_trigger_must_name_a_release_of_the_same_record(self):
        # The catalog gate passes the record's release ids, so a trigger that
        # points at a release the record does not publish is refused.
        from engine.validation import check_derived

        rec = record(verifier="deterministic-endoflife-date-v1", releases=[
            release({"eol": "2027-06-17"},
                    {"milestone_provenance": {"eol": {
                        "kind": "derived", "method": "release-trigger", "source_url": SOURCE,
                        "quote": TriggerDerivationTests.QUOTE,
                        "base_date": "2025-04-01", "base_label": "general availability",
                        "trigger": {"release_id": "9", "date": "2027-06-17", "label": "9"}}}})])
        with self.assertRaisesRegex(ValueError, "names no release in this record"):
            check_derived(rec)


class NonderivedMilestonesTests(unittest.TestCase):
    """`NonDerivedMilestones` is the stated half of a milestone set."""

    def test_it_is_exactly_the_complement_of_the_derived_keys(self):
        milestones = {"ga": "2025-04-01", "eos": "2026-04-01", "eossec": None, "eol": "2030-04-01"}
        provenance = {"eol": duration_entry()}
        self.assertEqual(derived.NonDerivedMilestones(milestones, provenance),
                         {"ga": "2025-04-01", "eos": "2026-04-01"})
        self.assertEqual(derived.derive(milestones, provenance), {"eol": "2030-04-01"})


if __name__ == "__main__":
    unittest.main()
