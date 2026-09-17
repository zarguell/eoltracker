"""Samba release-series lifecycle, from the project's own planning table.

Source: the Samba wiki page ``Samba_Release_Planning`` ("Samba Release
Planning and Supported Release Lifetime"), fetched rendered. The wikitext
source is a MediaWiki template shell that pulls the next version from a
release JSON at parse time; the rendered page is the statement a reader sees
and the stable thing to parse.

**Forecast dates are not dates.** The vendor footnotes its own table: "Dates
in the future are marked ~ for approximate and are simple forecasts based on
the historical release pattern described above. The specific details of the
release cycle are at the discretion of the release manager". A ``~`` cell is
policy arithmetic (rule 2): it stays verbatim in ``upstream.cells`` and never
becomes a milestone. Only a cell stating a plain ``YYYY-MM-DD`` is a fact;
every column is validated, so a reshaped cell fails the parse instead of
being guessed at.

**Mode columns are mode entries, not ends.** The columns ``maintenance`` and
``security`` date when a series *enters* maintenance / security-fixes-only
mode; security fixes continue until the series is discontinued. So the
``security`` column never fills ``eossec``, and the terminal date is the
realized ``discontinued (EOL)`` cell. Mapping: ``started`` -> ``ga``,
realized ``discontinued (EOL)`` -> ``eol``; ``eos``/``eossec`` stay null —
Samba publishes no end of sale, and its own mode definitions put security
fixes at the end of the series, not before it.

One product (``samba``), one release per series (``4.23``), so a permalink
survives point releases. Every row the table states is published, including
the upcoming series whose dates are all forecasts and the grouped historical
rows. The third-party Samba-AD packaging matrix (tranquil.it) is a different
product and stays out of scope.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from html.parser import HTMLParser

from . import net, sources, transaction
from .contribute import page_text
from .importer import ROOT

# The registry owns the id and the page: a record's provenance must name a
# source this checkout installs, and the report must name the page it read.
VERIFIER = sources.source("import-samba").verifier
SOURCE_URL = sources.SAMBA_RELEASE_PLANNING
REPORT = sources.source("import-samba").report
RECORD_SCHEMA = "https://zarguell.github.io/eoltracker/v1/schema/product.json"
PRODUCT_ID = "samba"
PRODUCT_NAME = "Samba"
UPSTREAM_CATEGORY = "server-app"

# The page's own heading and column labels, in the order the table states them.
TABLE = "Samba Release Planning and Supported Release Lifetime"
HEADERS = ("series", "git branch", "status", "started", "maintenance",
           "security", "discontinued (EOL)")
STARTED = "started"
DISCONTINUED = "discontinued (EOL)"

# A date the source states plainly, as a realized fact; anything else — a
# ``~`` forecast, prose, an empty cell — states no date.
DAY = re.compile(r"\d{4}-\d{2}-\d{2}")
SERIES = re.compile(r"\d+\.\d+")


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class _Tables(HTMLParser):
    """Read table cells including nested markup; reject span/layout drift."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables = []
        self.table = None
        self.row = None
        self.cell = None

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            if self.table is not None:
                raise ValueError("Nested Samba table")
            self.table = []
        elif tag == "tr" and self.table is not None:
            self.row = []
        elif tag in ("td", "th") and self.row is not None:
            self.cell = []
        elif self.cell is not None and tag == "br":
            self.cell.append(" ")

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self.cell is not None:
            self.row.append(" ".join("".join(self.cell).split()))
            self.cell = None
        elif tag == "tr" and self.row is not None:
            self.table.append(self.row)
            self.row = None
        elif tag == "table" and self.table is not None:
            self.tables.append(self.table)
            self.table = None

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)


def day_value(text, where):
    """One realized ``YYYY-MM-DD`` cell; a forecast or bound cell is none.

    Only the vendor's plain day form is a date. A ``~``-prefixed cell is the
    vendor's own forecast ("simple forecasts based on the historical release
    pattern"), an empty cell states nothing: both stay raw. Anything else is
    a reshaped table and fails the parse rather than being read as a date it
    does not state.
    """
    value = text.strip()
    if value.startswith("~"):
        return None
    if DAY.fullmatch(value):
        return value
    if value == "":
        return None
    raise ValueError(f"{where}: unrecognized Samba lifecycle date {text!r}")


def series_id(name):
    """The stable identity of one row series, exactly as the vendor writes it."""
    match = SERIES.fullmatch(name)
    if match is None:
        raise ValueError(f"Unexpected Samba release series: {name!r}")
    return f"samba-{name}"


def release_for(cells):
    """One published release row, derived from the vendor's own cells."""
    if set(cells) != set(HEADERS):
        raise ValueError("Samba planning columns changed")
    name = cells["series"]
    # Drop the " ([[Release Planning for Samba 4.23|details]])" suffix the
    # rendered page puts after the series number in its first column.
    name = name.split("(", 1)[0].strip()
    if not SERIES.fullmatch(name):
        raise ValueError(f"Unexpected Samba release series: {name!r}")
    ga = day_value(cells[STARTED], f"{name} {STARTED}")
    eol = day_value(cells[DISCONTINUED], f"{name} {DISCONTINUED}")
    return {
        "id": series_id(name), "name": f"Samba {name}",
        "milestones": {"ga": ga, "eos": None, "eossec": None, "eol": eol},
        "upstream": {"name": name, "cells": cells, "table": TABLE},
    }


def parse_releases(html):
    """Every row of the vendor's planning table, in the order the page states."""
    folded = page_text(html)
    if TABLE not in folded:
        raise ValueError("Samba release-planning heading missing")
    parser = _Tables()
    parser.feed(html)
    parser.close()
    # The table is identified by the columns it declares, not by being the
    # only table on the page; two candidates are an ambiguity to refuse. The
    # vendor renders its header verbatim, so the comparison normalizes the
    # same case-fold on both sides.
    expected = [header.lower() for header in HEADERS]
    tables = [table for table in parser.tables
              if table and [cell.lower() for cell in table[0]] == expected]
    if len(tables) != 1:
        raise ValueError("Missing or duplicate Samba planning table")
    rows = [row for row in tables[0][1:] if any(row)]
    if not rows:
        raise ValueError("Samba planning table is empty")
    releases, seen = [], set()
    for row in rows:
        if len(row) != len(HEADERS):
            raise ValueError("Samba planning row width changed")
        release = release_for(dict(zip(HEADERS, row)))
        if release["id"] in seen:
            raise ValueError("Duplicate Samba release series")
        seen.add(release["id"])
        releases.append(release)
    return releases


def validate_record(record):
    """Rebuild every stored series from its own published cells, offline."""
    if record["provenance"]["verifier"] != VERIFIER:
        raise ValueError("Invalid Samba source identity")
    seen = set()
    for release in record["releases"]:
        cells = release.get("upstream", {}).get("cells")
        if not isinstance(cells, dict) or tuple(cells) != HEADERS:
            raise ValueError(f"{record['id']}: release {release['id']} does not carry "
                             f"the vendor's declared columns {HEADERS}")
        where = f"{record['id']}: release {release['id']}"
        if release["id"] in seen:
            raise ValueError(f"Duplicate Samba series: {where}")
        seen.add(release["id"])
        name = cells["series"].split("(", 1)[0].strip()
        if series_id(name) != release["id"]:
            raise ValueError(f"{where} does not name its own series")
        if release["name"] != f"Samba {name}":
            raise ValueError(f"{where} does not name the series it stores")
        expected = {"ga": day_value(cells[STARTED], where),
                    "eos": None, "eossec": None,
                    "eol": day_value(cells[DISCONTINUED], where)}
        if release["milestones"] != expected:
            raise ValueError(f"{where} milestones contradict its stored cells")


def record_for(releases, checked):
    """The published ``samba`` record for one complete planning snapshot."""
    return {
        "$schema": RECORD_SCHEMA,
        "id": PRODUCT_ID,
        "name": PRODUCT_NAME,
        "category": "software",
        "upstream_category": UPSTREAM_CATEGORY,
        # The Samba project publishes no CPE or other identifier for its
        # release series, and an invented one would be a claim the source
        # never makes.
        "identifiers": [],
        "labels": {},
        "links": {"html": SOURCE_URL},
        "releases": releases,
        "provenance": {"source_url": SOURCE_URL, "verifier": VERIFIER,
                       "last_checked": checked, "upstream_modified": None},
    }


def forecast_rows(releases, column):
    """The rows whose cell for *column* is the vendor's forecast, not a date.

    Published so a reader can see, without parsing any record, which series
    carry no normalized deadline and why — and so no one later mistakes the
    absence of the milestone for missing data.
    """
    key = STARTED if column == STARTED else DISCONTINUED
    return [{"id": release["id"], "name": release["name"],
             "cell": release["upstream"]["cells"][key]}
            for release in releases
            if release["upstream"]["cells"][key].startswith("~")]


def report_for(releases, checked):
    """The per-row accounting this source publishes beside its record."""
    started = forecast_rows(releases, STARTED)
    discontinued = forecast_rows(releases, DISCONTINUED)
    return {
        "verifier": VERIFIER,
        "rows": {"seen": len(releases), "published": len(releases),
                 "retained": 0, "excluded": 0},
        "milestones": {
            "ga_stated": len(releases) - len(started),
            "ga_forecast": len(started),
            "eol_stated": sum(1 for release in releases
                              if release["milestones"]["eol"] is not None),
            "eol_forecast": len(discontinued),
        },
        "forecast_ga": started,
        "forecast_eol": discontinued,
        "limitations": [
            "The vendor marks future dates '~': simple forecasts based on the "
            "historical release pattern. Forecasts are retained verbatim in "
            "upstream.cells and never become milestones.",
            "The 'security' column dates entry into security-fixes-only mode; "
            "security fixes continue until the realized 'discontinued (EOL)' "
            "date, so no eossec is published.",
            "Third-party Samba-AD packaging matrices are out of scope.",
        ],
        "total_records": 1,
        "checked_at": checked,
        "source_url": SOURCE_URL,
    }


def committed_record(root):
    """The committed ``samba`` record, refusing one this source cannot own."""
    return transaction.committed_product_record(root, PRODUCT_ID, VERIFIER,
                                                validate_record, "Samba")


def import_samba(directory=None):
    """Fetch the planning table and publish the ``samba`` record and report."""
    root = Path(directory) if directory is not None else ROOT / "data"
    committed = committed_record(root)
    html = net.get_text(SOURCE_URL)
    releases = parse_releases(html)
    checked = _now()
    record = record_for(releases, checked)
    validate_record(record)
    report = report_for(releases, checked)
    transaction.publish_product_record(record, report, root,
                                       report_name=REPORT)
    print(f"imported {len(releases)} Samba release series; "
          f"retained {report['rows']['retained']} (data/{REPORT})")
    return f"imported {len(releases)} Samba release series"
