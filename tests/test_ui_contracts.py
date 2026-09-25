"""DOM contracts for the homepage catalog cards (audit issue #96).

The homepage card's ``data-next-date`` is the sort key the filter script reads,
and for a month-precision milestone it is a ``YYYY-MM`` value. The card has to
say the same thing to a reader as it does to the sort: a month is not a day, so
the visible date carries a month-precision marker and a machine-readable
``<time datetime="YYYY-MM">`` whose value is exactly the stored month (AGENTS.md
rule 4 — a month is never padded into a day). Before this contract the card
printed only the human text, so a month window and an exact day looked identical.

Cards render through the real template and the real presenter
(``site_views.release_rows``/``summarize``), so a regression in either — the
template dropping the marker, or the presenter dropping ``next.month`` — fails
here rather than only in a browser.
"""
import json
import re
import unittest
from datetime import date
from html.parser import HTMLParser

from engine import site_config, site_views
from engine.importer import ROOT
from engine.site_config import (CATALOG_STATES, HARDWARE_MILESTONES, HARDWARE_STATUS_ORDER,
                                HARDWARE_STATUSES, MILESTONES)

# A fixed "today" keeps the sweep deterministic; the assertions below are
# invariants over whatever cards remain, not a pinned card count.
TODAY = date(2026, 9, 25)
MONTH = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class CardReader(HTMLParser):
    """The product cards' next-deadline markup, as a consumer of the page sees it.

    Cards contain nested lists, so the card's own ``</li>`` is found by depth
    rather than by the first closing list item.
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.cards = []
        self._card = None
        self._depth = 0
        self._in_next = False
        self._text = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        classes = (attributes.get("class") or "").split()
        if tag == "li":
            if self._card is None and "product-card" in classes:
                self._card = {"next_date": attributes.get("data-next-date"), "times": [], "text": ""}
                self._depth = 1
            elif self._card is not None:
                self._depth += 1
        elif tag == "p" and "product-next" in classes and self._card is not None:
            self._in_next = True
            self._text = []
        elif tag == "time" and self._in_next:
            self._card["times"].append(attributes.get("datetime"))

    def handle_data(self, data):
        if self._in_next:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag == "p" and self._in_next:
            self._in_next = False
            self._card["text"] = " ".join("".join(self._text).split())
        elif tag == "li" and self._card is not None:
            self._depth -= 1
            if self._depth == 0:
                self.cards.append(self._card)
                self._card = None


def release_record(**milestones):
    """One synthetic product whose release publishes exactly the given milestones."""
    return {
        "id": "sample", "name": "Sample", "labels": {},
        "provenance": {"source_url": "https://example.test/", "verifier": "researched-sample",
                       "last_checked": "2026-09-17T00:00:00Z", "upstream_modified": None},
        "releases": [{"id": "1", "name": "1", "upstream": {"name": "1"},
                      "milestones": {"ga": None, "eos": None, "eossec": None, "eol": None, **milestones}}],
    }


def summarize(record, name, today=TODAY):
    """A card summary through the real presenter, the way `site.build` makes one."""
    record = {**record, "name": name, "upstream_category": "Sample"}
    return site_views.summarize(record, site_views.release_rows(record), today)


def index_context(products):
    """The minimum `index.html` context; the catalog chrome stays empty."""
    state_counts = {state["key"]: 0 for state in CATALOG_STATES}
    state_order = {state["key"]: index for index, state in enumerate(CATALOG_STATES)}
    state_order["lifecycle-row"] = len(state_order)
    state_counts["lifecycle-row"] = 0
    return {
        "active": "index",
        "canonical": site_config.site_url(),
        "title": "EOL Tracker — software and hardware lifecycle dates",
        "description": "Homepage card contract render.",
        "notices": {},
        "manifest": {},
        "schema_version": 1,
        "schema_files": [],
        "refresh": {"iso": "2026-09-25T00:00:00Z", "human": "Sep 25, 2026"},
        "product_count": len(products),
        "release_count": sum(product["releases"] for product in products),
        "excluded_count": 0,
        "researched_count": 0,
        "researched_hardware_count": 0,
        "hardware_count": 0,
        "products": products,
        "coverage": site_views.milestone_coverage([]),
        "categories": [],
        "hardware": [],
        "hardware_coverage": site_views.milestone_coverage([]),
        "hardware_vendors": [],
        "hardware_statuses": [],
        "catalog_states": CATALOG_STATES,
        "catalog_state_counts": state_counts,
        "catalog_state_order": state_order,
        "catalog_stats": {},
        "import_report": None,
        "report_families": [],
        "research_stale_days": 30,
        "changes_available": False,
        "changes_json_url": site_config.url_for("v1/changes.json"),
        "changes_atom_url": site_config.url_for("v1/changes.atom"),
        "feed_url": site_config.url_for("v1/feed.json"),
        "products_url": site_config.url_for("v1/products.json"),
        "hardware_url": site_config.url_for("v1/hardware.json"),
        "milestone_meta": MILESTONES,
        "hardware_milestone_meta": HARDWARE_MILESTONES,
        "hardware_status_meta": HARDWARE_STATUSES,
        "hardware_status_order": HARDWARE_STATUS_ORDER,
        "catalog_source_name": "Opengear product configurator",
        "catalog_source_site": "https://opengear.com/configure/",
    }


def render_cards(products):
    """Render the real homepage template and read its cards back."""
    html = site_config.env.get_template("index.html").render(**index_context(products))
    reader = CardReader()
    reader.feed(html)
    return reader.cards


def committed_products():
    """Committed product records, loaded without validating the live catalog."""
    directory = ROOT / "data" / "products"
    return [json.loads(path.read_text(encoding="utf-8")) for path in sorted(directory.glob("*.json"))]


class NextDeadlineCardTests(unittest.TestCase):
    """Every card's visible next deadline matches its machine-readable value."""

    def assert_card_contract(self, card):
        value = card["next_date"]
        if not value:
            self.assertEqual(card["times"], [], "a card with no next deadline renders no date")
            self.assertNotIn("month precision", card["text"])
            return
        self.assertEqual(len(card["times"]), 1, f"one machine-readable date per card: {card}")
        self.assertEqual(card["times"][0], value)
        if MONTH.match(value):
            self.assertIn("month precision", card["text"])
        else:
            self.assertTrue(DAY.match(value), value)
            self.assertNotIn("month precision", card["text"])

    def test_a_month_card_states_the_month_and_never_a_padded_day(self):
        record = release_record(eol="2099-07")
        cards = render_cards([summarize(record, "Month Sample")])
        self.assertEqual(len(cards), 1)
        card = cards[0]
        self.assertEqual(card["next_date"], "2099-07")
        self.assertEqual(card["times"], ["2099-07"])
        self.assertIn("month precision", card["text"])
        self.assertIn("July 2099", card["text"])
        # The human text must not have grown a day the source never stated.
        self.assertNotRegex(card["text"], r"Jul 1, 2099")

    def test_a_day_card_carries_no_month_marker(self):
        card = render_cards([summarize(release_record(eol="2099-07-15"), "Day Sample")])[0]
        self.assertEqual(card["next_date"], "2099-07-15")
        self.assertEqual(card["times"], ["2099-07-15"])
        self.assertNotIn("month precision", card["text"])
        self.assertIn("Jul 15, 2099", card["text"])

    def test_a_card_without_a_deadline_renders_no_next_line(self):
        self.assert_card_contract(render_cards([summarize(release_record(), "None Sample")])[0])

    def test_every_card_obeys_the_contract(self):
        cards = render_cards([summary for summary in (
            summarize(release_record(eol="2099-07"), "Month Sample"),
            summarize(release_record(eol="2099-07-15"), "Day Sample"),
            summarize(release_record(), "None Sample"),
        )])
        self.assertEqual(len(cards), 3)
        for card in cards:
            self.assert_card_contract(card)
        self.assertEqual(sum(1 for card in cards if MONTH.match(card["next_date"] or "")), 1)

    def test_the_whole_committed_catalog_obeys_the_contract(self):
        # The audit found month-precision cards being flattened on the live
        # homepage; this sweeps all of them, not only the ones data happens to
        # publish today.
        products = committed_products()
        summaries = [summarize(record, record["name"]) for record in products]
        cards = render_cards(summaries)
        self.assertEqual(len(cards), len(products))
        for card in cards:
            self.assert_card_contract(card)
        # The presenter must keep flagging the width, or the sweep above would
        # pass vacuously on a catalog that lost the flag.
        self.assertTrue(all(card["times"] == [card["next_date"]]
                            for card in cards if card["next_date"]))


if __name__ == "__main__":
    unittest.main()
