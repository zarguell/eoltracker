"""PowerDNS Authoritative community lifecycle, at the vendor's stated precision.

Only the captioned lifecycle table is authoritative for dates. Critical-only
updates are not a terminal support milestone; approximate (~) cells are not
firm deadlines. The grouped 4.1-and-older row remains one undated scope.
Commercial agreements can provide support beyond this community lifecycle.
"""
import re
from datetime import date, datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

from . import net, sources, transaction
from .importer import ROOT

SOURCE = sources.source("import-powerdns-authoritative")
PRODUCT_ID = "powerdns-authoritative"
TABLE = "PowerDNS Authoritative Server Release Life Cycle"
HEADERS = ("Version", "Release date", "Critical-Only updates", "End of Life")
MONTHS = {name: index for index, name in enumerate(
    ("January", "February", "March", "April", "May", "June", "July", "August",
     "September", "October", "November", "December"), 1)}
# Cells that state no date at all, reviewed against the vendor's own wording.
# The table writes "EOL" for the scope whose dates PowerDNS never published, and
# a routine edit can leave a blank, a dash or a plain no-date token in any of the
# three columns. Each is the source saying "no date stated": it normalizes to a
# null milestone while the raw cell stays verbatim under ``upstream.cells``.
# Deliberately narrow — a value that only *looks* date-shaped (a bare year, an
# impossible month or day, the vendor's day form with another separator) is not
# in this vocabulary and refuses the refresh instead of passing as unknown.
NO_DATE = frozenset({"", "-", "–", "—", "n/a", "n/a.", "na", "tbd", "tba", "unknown", "eol"})


class _Tables(HTMLParser):
    """Read table cells including nested markup; reject span/layout drift."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables = []
        self.table = None
        self.row = None
        self.cell = None
        self.caption = None

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            if self.table is not None:
                raise ValueError("Nested lifecycle table")
            self.table = {"caption": "", "rows": []}
        elif self.table is not None:
            if tag == "caption":
                self.caption = ""
            elif tag == "tr":
                self.row = []
            elif tag in ("th", "td"):
                if self.row is None or any(dict(attrs).get(key, "1") != "1"
                                           for key in ("rowspan", "colspan")):
                    raise ValueError("Unexpected lifecycle cell layout")
                self.cell = ""
            elif tag == "br" and self.cell is not None:
                self.cell += " "

    def handle_data(self, text):
        if self.cell is not None:
            self.cell += text
        if self.caption is not None:
            self.caption += text

    def handle_endtag(self, tag):
        if self.table is None:
            return
        if tag in ("td", "th") and self.cell is not None:
            self.row.append(" ".join(self.cell.split()))
            self.cell = None
        elif tag == "tr" and self.row is not None:
            self.table["rows"].append(self.row)
            self.row = None
        elif tag == "caption" and self.caption is not None:
            self.table["caption"] = " ".join(self.caption.split()).rstrip("¶").strip()
            self.caption = None
        elif tag == "table":
            self.tables.append(self.table)
            self.table = None


def date_value(text):
    """One dated cell at its stated precision; a no-date cell is ``None``.

    Three cell shapes state a date: ``3rd of June 2026`` and ``June 2026`` at
    the precision the vendor writes, and the ``EOL June 2026`` form, where the
    ``EOL`` token marks the release as past its end of life and the date after
    it is still the vendor's own statement. A ``~ ``-prefixed cell is the
    vendor's approximation and is never a deadline.

    Everything else has to be a date or a reviewed no-date token. The no-date
    vocabulary (:data:`NO_DATE`) covers the raw spellings the table already uses
    for "no date stated", including the bare ``EOL`` the grouped scope carries;
    each normalizes to ``None`` while the cell stays verbatim in the record. A
    date-shaped value outside both — a bare year, an impossible month or day, a
    separator the vendor does not use — is a parse failure, so a genuinely
    malformed cell can never be mistaken for an unknown one.
    """
    text = re.sub(r"\s+", " ", text or "").strip()
    if text.lower() in NO_DATE:
        return None
    approximate = text.startswith("~ ")
    if approximate:
        value = text[2:]
    else:
        value = re.sub(r"^EOL\s+", "", text, flags=re.I)
    match = re.fullmatch(r"(?:(\d{1,2})(st|nd|rd|th) of )?([A-Za-z]+) (\d{4})", value)
    if not match or match[3] not in MONTHS:
        raise ValueError(f"Unrecognized PowerDNS date: {text!r}")
    month, year = MONTHS[match[3]], int(match[4])
    if match[1]:
        day = int(match[1])
        suffix = "th" if 10 <= day % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
        if suffix != match[2]:
            raise ValueError(f"Invalid ordinal: {text!r}")
        try:
            parsed = date(year, month, day).isoformat()
        except ValueError:
            raise ValueError(f"Not a calendar date: {text!r}") from None
    else:
        parsed = f"{year:04d}-{month:02d}"
    if approximate:
        return None
    return parsed


def release_for(cells):
    if set(cells) != set(HEADERS):
        raise ValueError("PowerDNS lifecycle columns changed")
    version = cells["Version"]
    if version != "4.1 and older" and not re.fullmatch(r"\d+\.\d+", version):
        raise ValueError(f"Unexpected PowerDNS version scope: {version!r}")
    # Validate the non-terminal column too, but never map it to support end.
    date_value(cells["Critical-Only updates"])
    return {
        "id": version.replace(" ", "-"), "name": version,
        "milestones": {"ga": date_value(cells["Release date"]), "eos": None,
                       "eossec": None, "eol": date_value(cells["End of Life"])},
        "upstream": {"name": version, "cells": cells, "table": TABLE},
    }


def parse_releases(html):
    parser = _Tables()
    parser.feed(html)
    parser.close()
    tables = [table for table in parser.tables if table["caption"] == TABLE]
    if len(tables) != 1 or not tables[0]["rows"]:
        raise ValueError("Missing or duplicate PowerDNS lifecycle table")
    header, *rows = tables[0]["rows"]
    if tuple(header) != HEADERS or not rows:
        raise ValueError("PowerDNS lifecycle headers changed or table empty")
    releases, seen = [], set()
    for row in rows:
        if len(row) != len(HEADERS):
            raise ValueError("PowerDNS lifecycle row width changed")
        release = release_for(dict(zip(HEADERS, row)))
        if release["id"] in seen:
            raise ValueError("Duplicate PowerDNS release scope")
        seen.add(release["id"])
        releases.append(release)
    return releases


def validate_record(record):
    if (record["id"] != PRODUCT_ID or record["provenance"]["verifier"] != SOURCE.verifier
            or record["provenance"]["source_url"] != SOURCE.url or not record["releases"]):
        raise ValueError("Invalid PowerDNS source identity")
    seen = set()
    for release in record["releases"]:
        upstream = release["upstream"]
        expected = release_for(upstream.get("cells", {}))
        if (release["id"] in seen or upstream.get("table") != TABLE
                or upstream.get("in_source") not in (None, False)
                or any(release[key] != expected[key] for key in ("id", "name", "milestones"))
                or upstream["name"] != expected["upstream"]["name"]):
            raise ValueError("PowerDNS release contradicts its stored source cells")
        seen.add(release["id"])


def import_authoritative(directory=None):
    root = Path(directory) if directory is not None else ROOT / "data"
    old = transaction.committed_product_record(root, PRODUCT_ID, SOURCE.verifier,
                                                validate_record, "PowerDNS Authoritative")
    fresh = parse_releases(net.get_text(SOURCE.url))
    ids = {release["id"] for release in fresh}
    kept = [{**release, "upstream": {**release["upstream"], "in_source": False}}
            for release in (old["releases"] if old else []) if release["id"] not in ids]
    checked = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    record = {
        "$schema": "https://zarguell.github.io/eoltracker/v1/schema/product.json",
        "id": PRODUCT_ID, "name": "PowerDNS Authoritative Server", "category": "software",
        "upstream_category": "server-app", "identifiers": [],
        "labels": {"ga": "Release date", "eol": "End of Life"},
        "links": {"html": SOURCE.url}, "releases": fresh + kept,
        "provenance": {"source_url": SOURCE.url, "verifier": SOURCE.verifier,
                       "last_checked": checked, "upstream_modified": None},
    }
    report = {
        "source_url": SOURCE.url, "verifier": SOURCE.verifier, "checked_at": checked,
        "record_scope": "PowerDNS Authoritative community release trains; 4.1 and older remains one grouped scope",
        "rows": {"seen": len(fresh), "published": len(fresh) + len(kept),
                 "retained": len(kept), "excluded": 0},
        "total_records": 1, "excluded": [],
        "retained": [{"id": release["id"], "reason": "Absent from current table; stored evidence retained"}
                     for release in kept],
        "limitations": [
            "Approximate (~) dates remain vendor cells, never firm milestones or feed events.",
            "Month-only dates retain month precision; no day is inferred.",
            "Critical-Only updates is not terminal support; eos and eossec remain unknown.",
            "Commercial agreements may support releases past community EOL.",
            "The 4.1-and-older group is not expanded into invented individual release records.",
        ],
    }
    transaction.publish_product_record(record, report, root, SOURCE.report)
    return f"imported {len(fresh)} PowerDNS Authoritative scopes; retained {len(kept)}"
