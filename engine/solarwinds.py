"""SolarWinds product lifecycle, from SolarWinds' own release-history tables.

Two deterministic sources, one shared reading of the vendor's own vocabulary:

* **Release histories** (``documentation.solarwinds.com``) — one static page per
  product family, discovered from the vendor's own sitemap, each carrying up to
  two lifecycle tables headed ``Version`` / ``EoL announcement`` /
  ``EoE effective date`` / ``EoL effective date`` at day precision. One record
  per family, one release per version row.

**Milestone mapping (issue #116).** Only ``EoL effective date`` becomes a
milestone, and it becomes ``eol``: the vendor's End of Life Policy defines the
EoL date as the day "technical support is no longer available" for the product,
which is the terminal support end and nothing else. The other dated columns are
not milestones, and the reasons are the vendor's:

* ``EoL announcement`` is a notice — customers should start transitioning
  before anything ends. It is neither GA, nor a sale end, nor a support end,
  and it is never mapped to anything.
* ``EoE effective date`` is the end of *engineering*: service releases, bug
  fixes, workarounds and service packs stop. SolarWinds never calls it a
  security-support end, and AGENTS.md forbids a generic support date filling
  ``eossec``, so it is kept verbatim under ``upstream.cells``.
* ``EoS effective date`` is absent from the release histories — the vendor's
  policy says an end-of-sale date "is generally not applicable" to its
  date-based licences — so ``eos`` is null everywhere.

``ga`` is null for every release: a release-history table states no release
date, and the per-version release notes that do state one ("Release date: ...")
are a separate enumeration (issue #119) rather than a guess made here. No date
in this module is derived, so no record carries ``milestone_provenance``.

What the tables do not resolve, and what this module does about it:

* A row whose version cell names *several* releases ("4.1.1, 4.1.2", "12.1
  and earlier", "2020.1 - 2023.1") is one vendor row covering several
  releases. It is excluded and named, never expanded: expanding would attach a
  date to a release the vendor states it individually for none of.
* A cell stating no date at all (``--``, ``N/A``, ``All``) is absent, not
  malformed. A bare year ("2012", the LAN Surveyor row) is a stated date the
  schema has no width for, so it publishes nothing and is reported by name.
* A date cell in the ``EoL effective date`` column that is not a real calendar
  day refuses the page rather than being coerced: that is the one date
  published, so a cell this reader cannot read is never a value it may
  approximate. The announcement and EoE cells are carried verbatim and never
  parsed, so the vendor's own typos in them (SRM's "February, 6, 2024",
  Librato's "APril 1, 2025") can never become a published date.
* One version stated in both of a page's tables with the same values is read
  once and counted as a restatement; a restatement that contradicts the first
  statement refuses the page, because two vendor tables disagreeing about a
  support end is a review, never a silent choice.
* A version the current page no longer states is retained from the committed
  snapshot and marked ``upstream.in_source: false``. A dropped row is not an
  end of life.

Every row either becomes a release or is listed in the source's report with a
truthful reason (AGENTS.md rule 6).
"""
from __future__ import annotations

import re
from datetime import date, datetime, timezone
from pathlib import Path

from . import net, sources, tables, transaction
from .importer import ROOT

# The registry owns the pages, verifiers and report names: this module reads
# them from there rather than restating a URL or an id the site also publishes.
HISTORIES = sources.source("import-solarwinds")

SITEMAP_URL = HISTORIES.pages[0].url
HISTORY_VERIFIER = HISTORIES.verifier
HISTORY_REPORT = HISTORIES.report
RECORD_SCHEMA = "https://zarguell.github.io/eoltracker/v1/schema/product.json"
VENDOR = "SolarWinds"
EOL_LABEL = "EoL effective date"

# A release-history page is a path under the vendor's documentation root with
# ``/content/`` in it. The family key is the product directory before
# ``/content/``, plus the sub-family directory after it when the page is not
# the family's plain ``content/release_notes/release_history.htm`` (the
# Platform's observability sub-family), plus the file stem when the page is not
# named ``release_history`` (SQL Sentry's Plan Explorer page). Keying on the path
# rather than on a hand-kept list means a family SolarWinds adds is published on
# the next refresh instead of silently missing.
ROOT_PATH = "/en/success_center/"
GENERIC_DIRECTORY = "release_notes"
GENERIC_STEM = "release_history"
LOCATION = re.compile(r"<loc>\s*(?P<url>[^<\s]+)\s*</loc>")

# The table class every SolarWinds lifecycle table carries. A table without it
# is other page furniture and is never read as a lifecycle table.
TABLE_CLASS = "TableStyle-SWBrandingTableStyle"

# The declared column roles. ``version``/``product``/``bundle`` identify the
# row, ``announcement``/``eoe``/``eos`` are the vendor's own cells that no
# milestone is read from, and ``eol`` is the one that becomes ``eol``.
VERSION, PRODUCT, BUNDLE = "version", "product", "product bundle"
ANNOUNCEMENT, EOE, EOL, EOS = "announcement", "eoe", "eol", "eos"
# The header label each role may be stated as, folded to lower case. Every
# spelling listed is one the vendor itself prints: the typo'd "EoL annoucement"
# on the Database Mapper and Task Factory pages, and the capitalised plural
# headers on IPAM and Web Help Desk. Anything else refuses the page.
HISTORY_HEADERS = {
    "version": VERSION,
    "eol announcement": ANNOUNCEMENT,
    "eol annoucement": ANNOUNCEMENT,
    "eoe effective date": EOE,
    "eol effective date": EOL,
    # The IPAM page heads its columns in the plural, in capitals.
    "eol announcements": ANNOUNCEMENT,
    "eoe effective dates": EOE,
    "eol effective dates": EOL,
    "eos effective date": EOS,
    "product bundle": BUNDLE,
    "final version": "final version",
}

# A date cell states its day as a leading "Month D, YYYY", optionally followed
# by the vendor's own sentence about the phase ("July 9, 2027: End-of-Life
# (EoL) – SolarWinds will no longer provide technical support for NCM 2024.2").
DAY = re.compile(r"(?P<month>[A-Z][a-z]+) (?P<day>\d{1,2}), (?P<year>\d{4})")
MONTHS = ("January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December")
NO_DATE = frozenset({"", "-", "--", "---", "–", "—", "n/a", "na", "all", "tbd"})
# A stated year with no month: real, published, and not a width this schema
# holds, so it is reported rather than narrowed to a month.
YEAR_ONLY = re.compile(r"\d{4}\Z")
# Footnote markers the vendor appends to a version cell ("2020.2.1[**]").
FOOTNOTE = re.compile(r"\[\**\d*\**\]|\*+")
# A version cell that names exactly one release. Everything else — a comma list,
# a range, "and earlier" — is a grouped row and is never expanded.
GROUPED = re.compile(r",|\sand\s|\s-\s|earlier", re.IGNORECASE)
PAGE_TITLE = re.compile(r"<meta name=\"title\" content=\"(?P<title>[^\"]+)\"")
LONG_LABEL = 64


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _fold(text):
    return tables.fold(text)


def _month(name, where):
    try:
        return MONTHS.index(name) + 1
    except ValueError:
        raise ValueError(f"{where}: {name!r} is not a month name SolarWinds states") from None


def solarwinds_day(text, where):
    """The calendar day one SolarWinds date cell states, or ``None``.

    The cell's own sentence after the day is the vendor's phase prose and is
    not part of the date. A cell that states no date at all is absent; a cell
    whose first token is a date the calendar does not have, or whose wording
    this reader does not know, refuses — it is a published column, so nothing
    here may be approximated.
    """
    value = _fold(text)
    if value.lower() in NO_DATE:
        return None
    match = DAY.search(value)
    if not match or match.start():
        raise ValueError(f"{where}: unrecognized SolarWinds date {value!r}")
    try:
        return date(int(match.group("year")), _month(match.group("month"), where),
                    int(match.group("day"))).isoformat()
    except ValueError:
        raise ValueError(f"{where}: {value!r} is not a real calendar day") from None


def _year_only(text):
    """True for a stated bare year, which the schema has no width for."""
    return bool(YEAR_ONLY.fullmatch(_fold(text)))


def _labels(block, headers, where, heading):
    """The leaf column roles a table's own header declares, in order.

    A header cell states its label and then, in the same cell, the note
    explaining it ("EoL Effective Date — the date SolarWinds stopped providing
    technical support"). The label is the cell's first block; the note stays in
    the row's own cells and is never read as a column name.
    """
    rows, start = tables.header_rows(block, f"{where} {heading}")
    if len(rows) > 1:
        raise ValueError(f"{where}: {heading} header has {len(rows)} rows")
    if any(cell["span"] != (1, 1) for cell in rows[0]):
        raise ValueError(f"{where}: {heading} header carries a span")
    roles = []
    for cell in rows[0]:
        label = _fold(cell["lead"])
        role = headers.get(label.lower())
        if role is None:
            raise ValueError(f"{where}: {heading} declares unrecognized column {label!r}")
        roles.append(role)
    if len(set(roles)) != len(roles):
        raise ValueError(f"{where}: {heading} declares the same column twice")
    return tuple(roles), start


def _version_label(cell):
    """One version cell: the vendor's own label, minus its footnote markers."""
    return FOOTNOTE.sub("", _fold(cell)).strip()


def _grouped(value):
    """True when a version cell names several releases rather than one."""
    return not value or bool(GROUPED.search(value))


def _release(release_id, name, eol, cells, table, extra=None):
    upstream = {"name": release_id, "cells": cells, "table": table}
    if extra:
        upstream.update(extra)
    return {"id": release_id, "name": name,
            "milestones": {"ga": None, "eos": None, "eossec": None, "eol": eol},
            "upstream": upstream}


def _row(cells, roles, table, where):
    """One lifecycle row: the release it states, or why it states none.

    ``EoL effective date`` is the only cell a milestone is read from. The
    announcement, engineering-end and end-of-sale cells are carried verbatim:
    the vendor states them, and nothing this repository normalizes is stated
    by them.
    """
    stated = dict(cells)
    raw = _fold(stated.get(VERSION) or stated.get(PRODUCT) or stated.get(BUNDLE) or "")
    label = _version_label(raw)
    if _grouped(label):
        return None, {"table": table, "row": raw,
                      "reason": "the version cell names more than one release or a range of them; "
                                "one vendor row states the dates of several releases, and "
                                "expanding it would attach a date to a release SolarWinds states "
                                "individually for none"}
    if len(label) > LONG_LABEL:
        return None, {"table": table, "row": label,
                      "reason": "the version cell states no release label this source can publish "
                                "as one release"}
    if _year_only(stated.get(EOL, "")):
        return None, {"table": table, "row": label,
                      "reason": f"the {EOL_LABEL} cell states a year with no month; the schema "
                                f"holds a day or a month, and choosing either would state a date "
                                f"SolarWinds does not give"}
    eol = solarwinds_day(stated.get(EOL, ""), f"{where} {label} {EOL_LABEL}")
    return _release(label, label, eol, stated, table), None


def _stated(release, where):
    """The dated claims a row makes, for comparing two statements of one row.

    A row is compared on the day it publishes and, when both statements of the
    engineering-end cell are dates, on that day too. The two tables of one page
    word the announcement differently — a dated cell in one, the same day inside
    a sentence in the other — so a wording difference is not a contradiction
    of a claim; a different *day* is.
    """
    cells = release["upstream"]["cells"]
    claims = {"version": _fold(cells.get(VERSION, "")),
              "eol": _claim(cells.get(EOL, ""), where)}
    eoe = _claim(cells.get(EOE, ""), where, soft=True)
    if eoe is not None:
        claims["eoe"] = eoe
    return claims


def _claim(text, where, soft=False):
    """The day a cell states, or its own text when it states no single day."""
    value = _fold(text)
    if not value or _year_only(value):
        return None
    match = DAY.search(value)
    if not match:
        if soft:
            return None
        raise ValueError(f"{where}: unrecognized SolarWinds date {value!r}")
    try:
        return date(int(match.group("year")), _month(match.group("month"), where),
                    int(match.group("day"))).isoformat()
    except ValueError:
        if soft:
            return None
        raise ValueError(f"{where}: {value!r} is not a real calendar day") from None


def parse_history(html, url, family):
    """One family release-history page as ``(name, releases, excluded, duplicated)``.

    The page's own tables are read by their declared header, not by their
    position, so a page that states one table (SEM has no supported table at
    all) or a third (the Platform's scalability and SCOM sub-tables, SQL
    Sentry's bundle table) is accounted for either way.
    """
    where = family
    doc = tables.parse_document(html)
    releases, excluded, duplicated, seen = [], [], [], {}
    lifecycle_tables = 0
    for block in doc.blocks:
        if TABLE_CLASS not in (block.get("class") or ""):
            continue
        heading = block["heading"] or "release history"
        roles, start = _labels(block, HISTORY_HEADERS, where, heading)
        body, controls = tables.spanned_rows(block, roles, start)
        if controls:
            raise ValueError(f"{where}: {heading} states unrecognized control row(s) {controls}")
        rows = tables.data_rows(body, where, heading, roles)
        if VERSION not in roles:
            # A table of another kind on the same page (a bundle table keys on
            # Product Bundle): it states lifecycle dates, so it is reported
            # rather than dropped, but a bundle is not a release of the family.
            excluded.append({"table": heading, "rows": len(rows),
                             "reason": f"the table keys on {roles[0]!r} rather than on a release of "
                                       f"this family; its dates are the vendor's, for a scope this "
                                       f"record does not publish"})
            continue
        lifecycle_tables += 1
        for cells in rows:
            release, refusal = _row(cells, roles, heading, where)
            if refusal is not None:
                excluded.append(refusal)
                continue
            first = seen.get(release["id"])
            if first is not None:
                if _stated(first, where) != _stated(release, where):
                    raise ValueError(f"{where}: {release['id']} is stated twice with contradicting "
                                     f"values: {_stated(first, where)} then "
                                     f"{_stated(release, where)}")
                duplicated.append({"table": heading, "row": release["id"],
                                   "reason": "the other table on this page states this release with "
                                             "the same values; it is read once and accounted for "
                                             "here rather than published twice"})
                continue
            seen[release["id"]] = release
            releases.append(release)
    if not lifecycle_tables:
        # A family whose page still names its lifecycle sections but states no
        # table for them (SQL Sentry's Plan Explorer page) publishes no release.
        # A page that names no lifecycle section either is a shape this reader
        # does not know, and refuses rather than publishing an empty record.
        if not any("versions" in heading.lower() for heading in doc.headings):
            raise ValueError(f"{where}: {url} states no SolarWinds lifecycle table")
        excluded.append({"table": "release history", "rows": 0,
                         "reason": "the page names its supported and unsupported version sections "
                                   "but states no table under either, so it publishes no release "
                                   "row"})
    return _title(html, family), releases, excluded, duplicated


def _title(html, where):
    """The product name the page's own metadata states, without its page suffix."""
    match = PAGE_TITLE.search(html)
    title = _fold(match.group("title")) if match else ""
    title = re.sub(r"\s+release history$", "", title, flags=re.IGNORECASE)
    if not title:
        raise ValueError(f"{where}: the page states no product title")
    return title if title.startswith(VENDOR) else f"{VENDOR} {title}"


def family_key(url):
    """The stable product key one release-history URL names."""
    path = url.split("documentation.solarwinds.com", 1)[-1]
    if ROOT_PATH not in path or "/content/" not in path:
        raise ValueError(f"SolarWinds URL does not name a release history: {url}")
    before, _, after = path.partition(ROOT_PATH)[2].partition("/content/")
    parts = [part for part in before.split("/") if part]
    parts += [part for part in after.split("/")[:-1]
              if part and part != GENERIC_DIRECTORY]
    stem = after.rsplit("/", 1)[-1]
    if not stem.endswith(f"{GENERIC_STEM}.htm"):
        raise ValueError(f"SolarWinds URL is not a release history page: {url}")
    stem = stem[:-len(f"{GENERIC_STEM}.htm")].rstrip("_")
    if stem:
        parts.append(stem)
    if not parts:
        raise ValueError(f"SolarWinds URL names no product family: {url}")
    return "-".join(parts)


def discover_families(sitemap):
    """Every product family the vendor's own sitemap publishes a history for."""
    families = {}
    for url in LOCATION.findall(sitemap):
        url = _fold(url)
        if "release_history" not in url:
            continue
        key = family_key(url)
        if key in families:
            raise ValueError(f"The SolarWinds sitemap states {key} twice: {families[key]} and "
                             f"{url}")
        families[key] = url
    if not families:
        raise ValueError("The SolarWinds sitemap states no release history")
    return dict(sorted(families.items()))


def _record(product_id, name, releases, url, verifier, checked, labels):
    return {
        "$schema": RECORD_SCHEMA,
        "id": product_id,
        "name": name,
        "category": "software",
        "upstream_category": "app",
        # SolarWinds publishes no CPE for these products, and an invented one
        # would be a claim the source does not make.
        "identifiers": [],
        "labels": labels,
        "links": {"html": url},
        "releases": releases,
        "provenance": {"source_url": url, "verifier": verifier,
                       "last_checked": checked, "upstream_modified": None},
    }


def _identity(record, product_id, verifier, label):
    """The identity every record of a source states, checked before its rows."""
    if record.get("id") != product_id or record.get("category") != "software":
        raise ValueError(f"Invalid SolarWinds source identity for {product_id}")
    if (record.get("provenance") or {}).get("verifier") != verifier:
        raise ValueError(f"Invalid SolarWinds source identity for {product_id}")
    if record.get("labels") != {"eol": label}:
        raise ValueError(f"{product_id} does not name the column its eol is read from")
    if not record.get("releases"):
        raise ValueError(f"{product_id} states no release")


def _retained(release):
    if release["upstream"].get("in_source") not in (None, False):
        raise ValueError(f"{release['id']} carries an invalid retention marker")


def validate_history(record):
    """Rebuild every family release from its own stored cells, offline."""
    product_id = record.get("id", "")
    if not product_id.startswith("solarwinds-"):
        raise ValueError(f"Unknown SolarWinds record {product_id!r}")
    _identity(record, product_id, HISTORY_VERIFIER, EOL_LABEL)
    for release in record["releases"]:
        _retained(release)
        cells = release["upstream"].get("cells")
        if not isinstance(cells, dict) or not cells:
            raise ValueError(f"{product_id}/{release['id']} carries no source cells")
        table = release["upstream"].get("table")
        rebuilt, refusal = _row(cells, tuple(cells), table, product_id)
        if refusal is not None:
            raise ValueError(f"{product_id}/{release['id']} contradicts its stored cells: "
                             f"{refusal['reason']}")
        if rebuilt != release:
            raise ValueError(f"{product_id}/{release['id']} contradicts its stored cells")


def _combine(fresh, committed, family):
    """This page's rows plus the committed releases it no longer states."""
    if committed is None:
        return fresh, []
    ids = {release["id"] for release in fresh}
    kept = [{**release, "upstream": {**release["upstream"], "in_source": False}}
            for release in committed["releases"] if release["id"] not in ids]
    return fresh + kept, [{"id": release["id"], "name": release["name"],
                           "reason": f"the current SolarWinds {family} page does not state this "
                                     f"release; the committed row and its dates are retained"}
                          for release in kept]


def _rows(published, excluded, duplicated):
    """The report's row arithmetic: every source row counted exactly once."""
    return {"seen": published + len(excluded) + len(duplicated), "published": published,
            "excluded": len(excluded), "duplicated": len(duplicated)}


MAPPING_REASON = (
    "the vendor defines the EoL effective date as the date it stopped providing technical "
    "support, which is the terminal support end; the EoL announcement is a notice to start "
    "transitioning, and the EoE effective date is the end of engineering (service releases, bug "
    "fixes, workarounds and service packs), which SolarWinds never states as a security-support "
    "end, so neither is mapped to any milestone"
)


def import_solarwinds(directory=None):
    """Fetch every family page and publish one record per family.

    Complete-or-nothing: the whole snapshot — every family the vendor's sitemap
    states — is combined with the records this source no longer states, staged
    beside the committed catalog and validated there before anything is
    written. A parse failure, a header change or an inconsistent catalog leaves
    every committed file untouched.
    """
    root = Path(directory) if directory is not None else ROOT / "data"
    # The family set is discovered, so the ownership check runs the other way
    # round: every committed record this source owns is re-derived from its own
    # cells before the sitemap, let alone a family page, is fetched.
    owned = transaction.committed_product_records(
        root, HISTORY_VERIFIER, validate_history, "SolarWinds")
    families = discover_families(net.get_text(SITEMAP_URL))
    committed = {family: owned[f"solarwinds-{family}"]
                 for family in families if f"solarwinds-{family}" in owned}
    checked = _now()
    records, kept, excluded, duplicated, per_family = [], [], [], [], []
    for family, url in families.items():
        name, releases, refusals, restated = parse_history(net.get_text(url), url, family)
        if not releases:
            # The family is published by no record because its page states no
            # release row; the page and the reason are named in the report so
            # the sitemap entry is accounted for rather than silently missing.
            excluded.extend(dict(refusal, family=family) for refusal in refusals)
            excluded.append({"family": family, "url": url, "table": "release history", "rows": 0,
                             "reason": f"the {name} page states no release row this source can "
                                       f"publish, so no record is written for it"})
            per_family.append({"family": family, "url": url, "record": None, "name": name,
                               "rows": _rows(0, refusals, restated), "retained": 0})
            continue
        rows, history = _combine(releases, committed.get(family), family)
        record = _record(f"solarwinds-{family}", name, rows, url, HISTORY_VERIFIER, checked,
                         {"eol": EOL_LABEL})
        validate_history(record)
        records.append(record)
        kept.extend(history)
        excluded.extend(dict(refusal, family=family) for refusal in refusals)
        duplicated.extend(dict(entry, family=family) for entry in restated)
        per_family.append({"family": family, "url": url, "record": record["id"], "name": name,
                           "rows": _rows(len(releases), refusals, restated),
                           "retained": len(history)})
    published = sum(family["rows"]["published"] for family in per_family)
    report = {
        "source_url": SITEMAP_URL, "verifier": HISTORY_VERIFIER, "checked_at": checked,
        "record_scope": (f"SolarWinds product families: {len(families)} software records, one per "
                         f"release-history page the vendor's sitemap states, one release per "
                         f"version row, at the day precision the vendor's own cell states"),
        "rows": {**_rows(published, excluded, duplicated), "retained": len(kept),
                 "families": len(families)},
        "families": per_family,
        "excluded": excluded,
        "duplicated": duplicated,
        "retained": kept,
        "total_records": len(records),
        "milestone_mapping": {"eol": EOL_LABEL, "ga": None, "eos": None, "eossec": None,
                              "announcement": "EoL announcement", "eoe": "EoE effective date",
                              "reason": MAPPING_REASON},
        "limitations": [
            "ga is absent for every release: a release-history table states no release date. The "
            "per-version release notes that do state one are a separate enumeration (issue #119), "
            "not a date this source guesses from the version.",
            "eos is null everywhere: the vendor's End of Life Policy says an end-of-sale date is "
            "'generally not applicable' to its date-based licences, and the one sub-table that "
            "states one (the Platform's Orion SCOM Management Pack) is a scoped table whose rows "
            "are reported as exclusions.",
            "A version cell naming several releases ('4.1.1, 4.1.2', '12.1 and earlier') is "
            "excluded and named; one vendor row states dates for several releases and expanding "
            "it would attach a date to a release stated individually for none.",
            "A stated bare year publishes nothing: the schema holds a day or a month, and "
            "neither would be the date the vendor gives.",
            "The EoL announcement and EoE effective date cells are kept verbatim and never "
            "parsed, so the vendor's own typos in them (SRM's 'February, 6, 2024', Librato's "
            "'APril 1, 2025') can never become a published date.",
            "A release the current page no longer states is retained from the committed snapshot "
            "and marked upstream.in_source false; a dropped row is not an end of life.",
            "Family discovery reads the vendor's own sitemap, so a family SolarWinds adds is "
            "published on the next refresh and a family it removes loses only the records this "
            "source retains.",
        ],
    }
    transaction.publish_product_records(records, report, root, HISTORY_REPORT)
    return (f"imported {published} SolarWinds releases across {len(records)} product families; "
            f"excluded {len(excluded)} rows, duplicated {len(duplicated)}, retained {len(kept)} "
            f"(data/{HISTORY_REPORT})")
