"""Microsoft Visio desktop and LTSC lifecycle, from Microsoft's own pages.

Source: the Microsoft Lifecycle product pages for Visio, content-negotiated to
Markdown with ``?accept=text/markdown`` so the tables are read as published
rather than through HTML layout noise. One product (``visio``) with one release
per published lifecycle line — the ten versioned desktop/LTSC lines, Visio
Plan 2, and every service-pack row Microsoft states.

**Start Date is not general availability.** Microsoft's own export guidance
defines it as "Date support started for product", so it is retained verbatim
in ``upstream.cells`` and never mapped to ``ga``: every release publishes
``ga: null``. There are no sale or orderability dates, so ``eos`` is null, and
no column is labelled as a security-support end, so ``eossec`` is null. The
only normalized milestone is the terminal one, and it comes from the column
Microsoft labels as the end of support:

* Modern policy pages state ``Retirement Date`` -> ``eol``.
* Fixed policy pages state ``Extended End Date`` -> ``eol`` where the column
  exists; ``Visio LTSC 2021`` and ``Visio LTSC 2024`` publish only
  ``Mainstream End Date``, which is the terminal date for their lifecycle.
* A service-pack row of the ``Releases`` table states ``End Date`` ->
  ``eol`` for that service-pack release.
* A cell that states no date (Visio Plan 2's ``In Support``) leaves the
  milestone absent. An announced extension is never collapsed into an earlier
  published deadline, and an absent deadline is never inferred from cadence.

**End instants are normalized to the last fully supported day.** Microsoft
prints end cells as Pacific-time instants one second before 7:00 AM, and the
day that instant falls on is the first moment support no longer applies. The
last fully supported calendar day is therefore the printed day minus one, and
that is the day Microsoft's own aggregate pages state: the ``Ending Support in
2029`` index lists Visio 2024 and Visio LTSC 2024 as ``October 9, 2029`` while
their product pages print ``10/10/2029 6:59:59 AM``. The same one-day offset
holds for every Visio entry on every aggregate index (see
``tests/test_visio.py``), and it is the convention the committed catalog
already uses for Microsoft products (``data/products/office.json`` stores
``2029-10-09``). The printed instant is kept verbatim in ``upstream.cells``,
and an end cell whose printed time is not ``6:59:59 AM`` refuses the parse
rather than being shifted silently.

Microsoft's official export workbook is *not* read here and *not* assumed
complete: this record comes from the product pages, so a lagging or partial
export can never drop or invent a line. The workbook was checked while
implementing this collector, and the expectation that it omits the current
2021/2024 Visio rows turned out to be wrong about the artifact: its Export
sheet carries all 43 Visio rows, and every stored end date is the day *before*
the printed ``6:59:59 AM`` instant — exactly the normalization below. The
earlier 35-row reading was a truncated text conversion of the sheet (2,264 of
its 2,943 data rows survived), not the workbook. The report's ``disclosures``
records that reading and the correction; the refresh itself never depends on
any of it.

Out of scope, with reasons: Visio Services in SharePoint (Microsoft's own web
service with its own Modern-policy page), Visio Plan 1 (Microsoft states it
"does not include the Visio desktop app", and no lifecycle page exists for it),
and the Visio web offering in Microsoft 365 (Microsoft publishes no lifecycle
page for it; the deployment guide lists it beside, not instead of, the desktop
lines). None of them is a desktop or LTSC lifecycle line, and none is folded
into one.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from . import derived, net, sources, transaction
from .importer import ROOT

# The registry owns the id, the verifier and every page URL: this module reads
# them from there rather than restating a source the checkout might not install.
SOURCE = sources.source("import-visio")
VERIFIER = SOURCE.verifier
SOURCE_URL = SOURCE.url
REPORT = SOURCE.report
RECORD_SCHEMA = "https://zarguell.github.io/eoltracker/v1/schema/product.json"
PRODUCT_ID = "visio"
PRODUCT_NAME = "Microsoft Visio"
UPSTREAM_CATEGORY = "app"

# The Markdown rendering of a page: the same page, in the form whose tables are
# the vendor's own data rather than an HTML rendering of it.
ACCEPT = "?accept=text/markdown"

# The listing name each registered page must carry, keyed by its URL slug. A
# page whose title disagrees is a reshaped or redirected source, not a release
# line to publish under the wrong name.
PAGE_NAMES = {
    "visio-2024": "Visio 2024",
    "visio-ltsc-2024": "Visio LTSC 2024",
    "visio-2021": "Visio 2021",
    "visio-ltsc-2021": "Visio LTSC 2021",
    "visio-plan-2": "Visio Plan 2",
    "visio-2019": "Visio 2019",
    "visio-2016": "Visio 2016",
    "visio-2013": "Visio 2013",
    "visio-2010": "Visio 2010",
    "visio-2007": "Visio 2007",
    "visio-2003": "Visio 2003",
}

# The page sections this collector reads, as the vendor heads them.
SUPPORT_SECTION = "Support Dates"
RELEASES_SECTION = "Releases"
EDITIONS_SECTION = "Editions"
# The three shapes the vendor's support table takes. The columns are the whole
# layout contract: a table declaring anything else refuses the parse.
SUPPORT_HEADERS = {
    "modern": ("Listing", "Start Date", "Retirement Date"),
    "mainstream": ("Listing", "Start Date", "Mainstream End Date"),
    "fixed": ("Listing", "Start Date", "Mainstream End Date", "Extended End Date"),
}
# The service-pack table's columns.
RELEASE_HEADERS = ("Version", "Start Date", "End Date")
# Which policy sentence goes with which table shape; a page that states one and
# publishes the other is a source change to review, never a silent preference.
POLICY_TABLES = {"Modern": "modern", "Fixed": ("mainstream", "fixed")}
# The policy wording the page must carry, and the policy name stored beside a row.
POLICY = re.compile(r"follows the \[(Modern|Fixed)\]\([^)]*\) Lifecycle Policy")
EDITIONS = re.compile(r"This applies to the following editions: ([^\n]+)")
# ``10/10/2029 6:59:59 AM`` — every support date these pages state.
INSTANT = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4}) (\d{1,2}):(\d{2}):(\d{2}) (AM|PM)")
# The instant Microsoft prints for an end cell: one second before 7:00 AM
# Pacific. Any other time on an end cell is a changed convention.
END_TIME = (6, 59, 59, "AM")
# A service-pack row's version cell: "Service Pack 3" or "Original Release".
VERSION = re.compile(r"Service Pack \d+|Original Release")
# A cell that states no date. It is not a date, and it never becomes one.
NO_DATE = {"", "-", "—", "n/a", "na", "tbd", "tba", "unknown", "in support"}
# The H1 of a page: the vendor's own listing name.
TITLE = re.compile(r"^# (.+)$", re.MULTILINE)
# Front-matter facts kept as page evidence, not as milestones.
UPDATED = re.compile(r"^updated_at: (.+)$", re.MULTILINE)

# The official export workbook. It is *not* a refresh input — the product pages
# are the source — but it is the artifact the implementation brief warned might
# omit the current lines, so what it holds at the revision this collector was
# built against is measured once and disclosed rather than asserted, and the
# tests re-measure it from the saved workbook.
WORKBOOK_URL = ("https://download.microsoft.com/download/"
                "a0c60d25-38e1-4d44-91e3-76c6d4c71275/product-lifecycle-data-new.xlsx")
# Visio rows in the Export sheet, counted from the workbook itself, and the
# current lines among them.
WORKBOOK_VISIO_ROWS = 43
WORKBOOK_CURRENT_LINES = ("Visio 2021", "Visio LTSC 2021", "Visio 2024", "Visio LTSC 2024")
# The corroboration for the one-day boundary, measured from Microsoft's own
# aggregate "Ending Support in <year>" index pages by ``tests/test_visio.py``,
# which re-counts both numbers from the saved pages on every run: 21 published
# Visio entries (22 including the excluded Visio Services line) across 13 index
# pages, every one of them stating the day before a product page's printed
# instant. The index pages are evidence, never a fetch input.
BOUNDARY_INDEX_ENTRIES = 21
BOUNDARY_INDEX_PAGES = 13

# The offerings Microsoft publishes under the Visio name that this record is
# deliberately not: each is excluded for its own stated reason, and none of
# them is a desktop or LTSC lifecycle line.
EXCLUDED_OFFERINGS = (
    ("https://learn.microsoft.com/en-us/lifecycle/products/"
     "visio-services-in-sharepoint-in-microsoft-365",
     "Visio Services in SharePoint (in Microsoft 365) is a web service with its own "
     "Modern Lifecycle page (Retirement Date 2/11/2023 6:59:59 AM). It is not a "
     "desktop or LTSC lifecycle line and is not folded into one."),
    ("https://www.microsoft.com/en-us/microsoft-365/visio/visio-plan-1",
     "Visio Plan 1 is excluded: Microsoft states \"Visio Plan 1 does not include the "
     "Visio desktop app\", and Microsoft Lifecycle publishes no lifecycle page for it "
     "(the products index returns 404)."),
    ("https://learn.microsoft.com/en-us/microsoft-365-apps/deploy/deployment-guide-for-visio",
     "The Visio web offering in Microsoft 365 is excluded: it is a browsing and "
     "basic-editing offering listed beside the desktop lines, and Microsoft Lifecycle "
     "publishes no lifecycle page naming it."),
)
# Visio Services actually has a live page; it is fetched only to be reported, not
# to publish a release from it.
SERVICES_URL = EXCLUDED_OFFERINGS[0][0]


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _cells(line):
    """One Markdown table row -> cell texts, with links reduced to their text."""
    cells = line.strip().strip("|").split("|")
    return [re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", cell).strip() for cell in cells]


def _separator(cells):
    """True for a Markdown table's alignment row."""
    return bool(cells) and all(re.fullmatch(r":?-{1,}:?", cell) for cell in cells)


def _table(lines, index):
    """The Markdown table starting at ``lines[index]``: its header and raw rows."""
    header, rows = None, []
    for row in lines[index:]:
        if not row.strip():
            continue
        if not row.strip().startswith("|"):
            break
        cells = _cells(row)
        if _separator(cells):
            continue
        if header is None:
            header = cells
            continue
        rows.append(cells)
    return header or [], rows


def _tables(markdown):
    """Every pipe table on the page as ``(section, header, rows)``, in page order."""
    lines = markdown.splitlines()
    tables, section, index = [], "", 0
    while index < len(lines):
        line = lines[index]
        if line.startswith("#"):
            section = line.lstrip("#").strip()
        elif line.strip().startswith("|"):
            header, rows = _table(lines, index)
            tables.append((section, header, rows))
            while index < len(lines) and lines[index].strip().startswith("|"):
                index += 1
            continue
        index += 1
    return tables


def _one_table(markdown, section, headers, where):
    """The single table of ``section`` declaring ``headers``; ambiguity refuses.

    A missing table means the page no longer states the lifecycle line it used
    to; a second one means the layout changed enough that reading either would
    be a guess. Both are source changes to review.
    """
    found = [(header, rows) for name, header, rows in _tables(markdown)
             if name == section and tuple(header) == tuple(headers)]
    if not found:
        raise ValueError(f"{where}: no {section} table declaring {list(headers)}")
    if len(found) > 1:
        raise ValueError(f"{where}: {len(found)} {section} tables declare {list(headers)}")
    header, rows = found[0]
    for row in rows:
        if len(row) != len(header):
            raise ValueError(f"{where}: {section} row has {len(row)} cells for "
                             f"{len(header)} columns: {row[0]!r}")
    return header, rows


def _listing(cells, header):
    """One column of a parsed row, matched by the table's own header text."""
    for column, value in zip(header, cells):
        if column == "Listing":
            return value
    raise ValueError(f"Visio row without the 'Listing' column: {cells!r}")


def day(text, where, end=False):
    """One support-date cell -> the ISO day this catalog stores, or ``None``.

    A start cell prints the day support began, so it keeps its printed day. An
    end cell prints the instant support stops, one second before 7:00 AM
    Pacific on the day after the last fully supported day, so it normalizes to
    the previous calendar day — the day Microsoft's own aggregate indexes
    state. An end cell whose time is not that instant is a changed convention
    and refuses, rather than being shifted on an assumption.
    """
    value = text.strip()
    if value.lower() in NO_DATE:
        return None
    match = INSTANT.fullmatch(value)
    if match is None:
        raise ValueError(f"{where}: unrecognized Microsoft lifecycle date {text!r}")
    month, day_of_month, year, hour, minute, second, meridiem = match.groups()
    try:
        printed = date(int(year), int(month), int(day_of_month))
    except ValueError as error:
        raise ValueError(f"{where}: not a real calendar day: {text!r}") from error
    if not end:
        return printed.isoformat()
    if (int(hour), int(minute), int(second), meridiem) != END_TIME:
        raise ValueError(f"{where}: end cell is not the published 6:59:59 AM instant: "
                         f"{text!r}; a changed end convention is a source change to review")
    return (printed - timedelta(days=1)).isoformat()


def _policy(markdown, where):
    """The lifecycle policy the page's own sentence states."""
    found = POLICY.search(markdown)
    if found is None:
        raise ValueError(f"{where}: page states no Lifecycle Policy sentence")
    return found.group(1)


def _editions(markdown, section_cells, where):
    """The editions the page's own sentence states, cross-checked against its list."""
    found = EDITIONS.search(markdown)
    listed = [value for value in section_cells if value]
    if found is None:
        if listed:
            raise ValueError(f"{where}: page lists editions but states no editions sentence")
        return []
    stated = [value.strip() for value in found.group(1).split(",") if value.strip()]
    if sorted(stated) != sorted(listed):
        raise ValueError(f"{where}: editions sentence {stated} contradicts the page's "
                         f"edition list {listed}")
    return stated


def _section_cells(markdown, section):
    """The bullet list under one ``##`` section, as its cell values."""
    lines = markdown.splitlines()
    cells, inside = [], False
    for line in lines:
        if line.startswith("## "):
            inside = line[3:].strip() == section
            continue
        if inside and line.strip().startswith("- "):
            cells.append(line.strip()[2:].strip())
    return cells


def _support_row(header, rows, name, where):
    """The one Support Dates row of a page, refusing a multi-row reshape."""
    if len(rows) != 1:
        raise ValueError(f"{where}: {SUPPORT_SECTION} states {len(rows)} rows; this source "
                         f"publishes one lifecycle line per page")
    row = dict(zip(header, rows[0]))
    listing = row["Listing"]
    if listing != name:
        raise ValueError(f"{where}: {SUPPORT_SECTION} row names {listing!r}, not the "
                         f"page's own listing {name!r}")
    return row


def parse_page(markdown, url):
    """One product page -> its published release row(s), or a parse failure.

    The page's own title, policy sentence, editions and support table are
    checked against each other, and every date cell it states is read here, so
    a page that has been re-titled, re-policied, re-columned or re-dated
    refuses instead of publishing a line under the wrong lifecycle.
    """
    slug = url.rstrip("/").rsplit("/", 1)[-1]
    expected = PAGE_NAMES.get(slug)
    if expected is None:
        raise ValueError(f"No Visio listing is registered for {url!r}")
    where = f"Visio page {expected!r}"
    title = TITLE.search(markdown)
    if title is None or title.group(1).strip() != expected:
        raise ValueError(f"{where}: page title is "
                         f"{title.group(1).strip() if title else 'absent'!r}")
    policy = _policy(markdown, where)
    shape = POLICY_TABLES[policy]
    shapes = (shape,) if isinstance(shape, str) else shape
    headers = next((SUPPORT_HEADERS[candidate] for candidate in shapes
                    if any(tuple(header) == SUPPORT_HEADERS[candidate]
                           for name, header, _ in _tables(markdown)
                           if name == SUPPORT_SECTION)), None)
    if headers is None:
        declared = [tuple(header) for name, header, _ in _tables(markdown)
                    if name == SUPPORT_SECTION]
        raise ValueError(f"{where}: a {policy} policy page has no {SUPPORT_SECTION} table "
                         f"declaring {list(SUPPORT_HEADERS[shapes[0]])}; it declares {declared}")
    header, rows = _one_table(markdown, SUPPORT_SECTION, headers, where)
    editions = _editions(markdown, _section_cells(markdown, EDITIONS_SECTION), where)
    support = _support_row(header, rows, expected, where)
    starts = day(support["Start Date"], f"{where}: Start Date")
    eol = day(support[headers[-1]], f"{where}: {headers[-1]}", end=True)
    releases = _release_rows(markdown, where)
    updated = UPDATED.search(markdown)
    return {
        "url": url, "slug": slug, "name": expected, "policy": policy,
        "editions": editions, "table": SUPPORT_SECTION, "header": header,
        "support": support, "start": starts, "eol": eol,
        "end_column": headers[-1], "updated": updated.group(1).strip() if updated else None,
        "releases": releases,
    }


def _release_rows(markdown, where):
    """Every service-pack row of a page's ``Releases`` table, read and dated.

    Each row comes back as its declared cells plus the terminal date read from
    its own ``End Date`` cell, so the page's dates are parsed once.
    """
    declared = [(name, header) for name, header, _ in _tables(markdown)
                if name == RELEASES_SECTION]
    if not declared:
        return []
    if len(declared) != 1:
        raise ValueError(f"{where}: {len(declared)} {RELEASES_SECTION} tables")
    header, rows = _one_table(markdown, RELEASES_SECTION, RELEASE_HEADERS, where)
    read, seen = [], set()
    for row in rows:
        if not VERSION.fullmatch(row[0]):
            raise ValueError(f"{where}: unrecognized release row {row[0]!r}")
        cells = dict(zip(header, row))
        if cells["Version"] in seen:
            raise ValueError(f"{where}: {cells['Version']!r} is stated twice in {RELEASES_SECTION}")
        seen.add(cells["Version"])
        at = f"{where} {cells['Version']}"
        day(cells["Start Date"], f"{at}: Start Date")
        read.append((cells, day(cells["End Date"], f"{at}: End Date", end=True)))
    return read


def release_id(line, version=None):
    """One published row's stable id: the version line, plus its release scope.

    The version is the vendor's own text, so the id survives a service-pack row
    being added or retired around it: ``visio-2024``, ``visio-ltsc-2024``,
    ``visio-2013-sp1``, ``visio-2003-original``.
    """
    text = f"{line} {version}" if version else line
    return re.sub(r"[^a-z0-9]+", "-", text.replace("Visio ", "visio-").lower()).strip("-")


def scope_of(version):
    """The id suffix a service-pack row contributes: ``sp3`` / ``original``."""
    found = re.search(r"Service Pack (\d+)", version)
    return f"sp{found.group(1)}" if found else "original"


def _release(line, cells, table, eol):
    """One published release, derived from the row's own cells.

    ``eol`` is the terminal date already read from the named end column of this
    row, so a page's cells are parsed once and the release carries exactly the
    dates the page states.
    """
    raw = dict(cells)
    scope = None if table == SUPPORT_SECTION else scope_of(raw["Version"])
    return {
        "id": release_id(line, scope),
        "name": line if scope is None else f"{line} {raw['Version']}",
        "milestones": {"ga": None, "eos": None, "eossec": None, "eol": eol},
        "upstream": {"name": line, "cells": raw, "table": table},
    }


def parse_pages(pages):
    """Every product page -> ``(releases, page_detail)``; no row is dropped.

    Rows are read from the vendor's own two tables: one lifecycle line per page
    from ``Support Dates``, and every row of ``Releases`` where the page states
    one. Every row read becomes a release, so the counts add up; a row this
    parser cannot place refuses the whole parse rather than being skipped. A
    page listed twice is a duplicate statement of every row it carries and
    equally refuses.
    """
    releases, detail, seen, read = [], [], {}, {}
    for url, markdown in pages:
        if url in read:
            raise ValueError(f"{url} is listed twice; its rows would be published twice")
        read[url] = markdown
        page = parse_page(markdown, url)
        line, policy = page["name"], page["policy"]
        rows = [(SUPPORT_SECTION, page["support"], page["eol"])]
        rows += [(RELEASES_SECTION, cells, eol) for cells, eol in page["releases"]]
        published = []
        for table, cells, eol in rows:
            where = f"{line} {cells.get('Version', '')}".strip()
            release = _release(line, cells, table, eol)
            if release["id"] in seen:
                raise ValueError(f"{where}: release {release['id']!r} is stated twice "
                                 f"({seen[release['id']]} and {url})")
            seen[release["id"]] = url
            release["upstream"].update(policy=policy, editions=page["editions"],
                                       source_url=url)
            published.append(release)
        releases.extend(published)
        detail.append({
            "url": url, "listing": line, "policy": policy,
            "editions": page["editions"], "table": page["table"],
            "columns": list(page["header"]), "end_column": page["end_column"],
            "support_rows": 1, "release_rows": len(page["releases"]),
            "rows": 1 + len(page["releases"]),
            "published": len(published), "excluded": 0,
            "updated_at": page["updated"],
        })
    if not releases:
        raise ValueError("No Visio lifecycle line was published")
    return releases, detail


def retained(release):
    """A committed release the current pages no longer state, marked as such.

    The row is republished from its own stored cells, so retention can never
    introduce a date Microsoft did not publish; the marker says only that this
    fetch did not state the line. A page dropping a line is not an end of life.
    """
    return {**release, "upstream": {**release["upstream"], "in_source": False}}


def combine_releases(fresh, committed):
    """The complete Visio snapshot: this fetch's rows plus retained history."""
    if committed is None:
        return list(fresh), []
    ids = {release["id"] for release in fresh}
    kept = [retained(release) for release in committed["releases"] if release["id"] not in ids]
    return (fresh + kept,
            [{"id": release["id"], "name": release["name"],
              "reason": "the current Microsoft Visio lifecycle pages do not state this "
                        "line; the committed row and its dates are retained"} for release in kept])


def validate_record(record):
    """Rebuild every stored release from its own published cells, offline.

    Offline, a record's cells are the whole evidence: the identity, the policy,
    the editions and the one normalized date are re-derived from them, so a
    file whose dates no longer follow the row it stores is never published.
    Each release's derived-milestone provenance is re-checked too, so a
    hand-edited derivation fails here as well as at the catalog gate.
    """
    if record["provenance"]["verifier"] != VERIFIER:
        raise ValueError("Invalid Microsoft Visio source identity")
    seen, ids = set(), {release["id"] for release in record["releases"]}
    for release in record["releases"]:
        upstream = release.get("upstream")
        cells = upstream.get("cells") if isinstance(upstream, dict) else None
        if not isinstance(cells, dict) or not cells:
            raise ValueError(f"Visio release without source cells: {release['id']}")
        where = f"{record['id']}/{release['id']}"
        table = upstream.get("table")
        line = upstream.get("name")
        if table == SUPPORT_SECTION:
            headers = SUPPORT_HEADERS["modern"] if "Retirement Date" in cells else (
                SUPPORT_HEADERS["fixed"] if "Extended End Date" in cells
                else SUPPORT_HEADERS["mainstream"])
            end_column = headers[-1]
            if tuple(cells) != tuple(headers):
                raise ValueError(f"{where} does not carry its table's columns {list(headers)}")
            if cells["Listing"] != line:
                raise ValueError(f"{where} does not name the listing it stores")
            expected_id = release_id(line)
            expected_name = line
        elif table == RELEASES_SECTION:
            if tuple(cells) != RELEASE_HEADERS:
                raise ValueError(f"{where} does not carry the vendor's declared columns "
                                 f"{list(RELEASE_HEADERS)}")
            if not VERSION.fullmatch(cells["Version"]):
                raise ValueError(f"{where} states no service-pack version")
            end_column = "End Date"
            expected_id = release_id(line, scope_of(cells["Version"]))
            expected_name = f"{line} {cells['Version']}"
        else:
            raise ValueError(f"{where} names no readable Visio table: {table!r}")
        if release["id"] in seen or release["id"] != expected_id:
            raise ValueError(f"{where} does not name its own release line")
        seen.add(release["id"])
        if release["name"] != expected_name:
            raise ValueError(f"{where} does not name the release it stores")
        expected = {"ga": None, "eos": None, "eossec": None,
                    "eol": day(cells[end_column], f"{where} {end_column}", end=True)}
        # Every milestone this source publishes is a date Microsoft states, so
        # the row's own cell is the whole authority: a milestone that no longer
        # follows its cell is refused even when a derivation is attached, since
        # a derivation beside a vendor statement could only override it.
        if release["milestones"] != expected:
            raise ValueError(f"{where} contradicts its stored cells")
        policy, editions = upstream.get("policy"), upstream.get("editions")
        if policy not in ("Modern", "Fixed"):
            raise ValueError(f"{where} states no lifecycle policy")
        if not isinstance(editions, list) or any(not isinstance(value, str) or not value
                                                for value in editions):
            raise ValueError(f"{where} carries an invalid editions list")
        if upstream.get("source_url") not in [url for url in _page_urls()]:
            raise ValueError(f"{where} names no registered Visio page")
        if upstream.get("in_source") not in (None, False):
            raise ValueError(f"{where} carries an invalid retention marker")
        derived.validate_milestone_provenance(release["milestones"],
                                              release.get(derived.DERIVED_KEY),
                                              where, ids)


def _page_urls():
    """Every page URL the registered source reads."""
    return [page.url for page in SOURCE.pages]


def record_for(releases, checked):
    """The published ``visio`` record for one complete page snapshot."""
    return {
        "$schema": RECORD_SCHEMA,
        "id": PRODUCT_ID,
        "name": PRODUCT_NAME,
        "category": "software",
        "upstream_category": UPSTREAM_CATEGORY,
        # Microsoft publishes no CPE for a Visio lifecycle line, and an invented
        # identifier would be a claim the source does not make.
        "identifiers": [],
        # Every release's own row carries the column wording its date was read
        # from, and the wording differs by policy and table, so no single
        # mapping is published here.
        "labels": {},
        "links": {"html": SOURCE_URL},
        "releases": releases,
        "provenance": {"source_url": SOURCE_URL, "verifier": VERIFIER,
                       "last_checked": checked, "upstream_modified": None},
    }


def report_for(releases, detail, kept, excluded, checked):
    """The per-page, per-row accounting this source publishes beside its record."""
    fresh = [release for release in releases
             if release["id"] not in {entry["id"] for entry in kept}]
    support_rows = sum(entry["support_rows"] for entry in detail)
    release_rows = sum(entry["release_rows"] for entry in detail)
    return {
        "source_url": SOURCE_URL, "accept": ACCEPT, "verifier": VERIFIER,
        "checked_at": checked,
        "record_scope": ("Microsoft Visio desktop and LTSC lifecycle lines: one software "
                         "record with one release per published line — the ten versioned "
                         "desktop/LTSC lines, Visio Plan 2, and every service-pack row "
                         "Microsoft states"),
        "pages": {
            "read": len(detail),
            "listed": len(PAGE_NAMES),
            "with_release_rows": sum(1 for entry in detail if entry["release_rows"]),
        },
        "rows": {
            "seen": support_rows + release_rows,
            "published": len(fresh) + len(kept),
            "fresh": len(fresh),
            "retained": len(kept),
            "excluded": 0,
            "support_dates": support_rows,
            "releases": release_rows,
        },
        "offerings": {
            "excluded": len(excluded),
            "published": len(PAGE_NAMES),
        },
        "milestones": {key: sum(1 for release in releases if release["milestones"][key])
                       for key in ("ga", "eos", "eossec", "eol")},
        "page_detail": detail,
        "excluded": excluded,
        "retained": kept,
        "disclosures": [
            "Start Date is not general availability: Microsoft's export guidance defines "
            "it as \"Date support started for product\", so every release publishes "
            "ga: null and the raw cell stays verbatim in upstream.cells.",
            "End cells are published as Pacific-time instants ('10/10/2029 6:59:59 AM') "
            "and are normalized to the last fully supported calendar day (2029-10-09) — "
            "the printed day minus one. Microsoft's own aggregate 'Ending Support in "
            "<year>' indexes state exactly that day for every Visio entry they carry "
            f"({BOUNDARY_INDEX_ENTRIES} entries across {BOUNDARY_INDEX_PAGES} index "
            "pages, all one calendar day before the product page's printed instant), and "
            "the printed instant is retained verbatim. An end cell printed at any other "
            "time refuses the parse rather than being shifted on an assumption.",
            "The official export workbook (" + WORKBOOK_URL + ") was checked while "
            f"implementing this collector. It carries all {WORKBOOK_VISIO_ROWS} Visio rows, "
            "including the current " + ", ".join(WORKBOOK_CURRENT_LINES) + " lines, and "
            "every stored end date is the day before the printed 6:59:59 AM cell — the "
            "same normalization this collector applies, seen in Microsoft's own export. "
            "The expectation that it omits the current 2021 and 2024 lines is not what "
            "the artifact contains: an earlier reading that reported 35 Visio rows was a "
            "truncated text conversion of the sheet (2,264 of its 2,943 data rows "
            "survived), not the workbook. Either way this record does not depend on that "
            "artifact: the product pages are the source, so a workbook that lagged, "
            "disagreed or omitted lines could not drop or invent one here.",
            "eos and eossec are published as null on every release: Microsoft states no "
            "sale or orderability date, and none of these columns is labelled as a "
            "security-support end. Mainstream End Date is kept as the vendor's own cell "
            "and never mapped.",
        ],
        "limitations": [
            "Visio Services in SharePoint (in Microsoft 365) is a web service with its "
            "own Modern Lifecycle page and is not a desktop or LTSC line; Visio Plan 1 "
            "and the Visio web offering in Microsoft 365 are excluded as separate "
            "offerings (Plan 1 by Microsoft's own \"does not include the Visio desktop "
            "app\" statement). All three are listed under 'excluded' with their reasons.",
            "Edition-scoped rows are merged into the release line that states the same "
            "dates; no edition is split into its own release and none is dropped.",
            "A line the current pages no longer state is retained from the committed "
            "snapshot, marked upstream.in_source false; a dropped page is not an end of "
            "life and introduces no date.",
            "The pages' 'updated_at' stamps are recorded as page evidence and are never "
            "mapped to a milestone.",
        ],
        "total_records": 1,
    }


def committed_record(root):
    """The committed ``visio`` record, refusing one this source cannot own."""
    return transaction.committed_product_record(root, PRODUCT_ID, VERIFIER,
                                                validate_record, "Microsoft Visio")


def publish_record(record, report, root):
    """Stage the record beside the committed catalog, validate, then replace it."""
    return transaction.publish_product_record(record, report, root, REPORT)


def snapshot(pages):
    """Fetch every registered Visio page as Markdown, in registry order."""
    return [(url, net.get_text(url + ACCEPT)) for url in pages]


def import_visio(directory=None):
    """Fetch the Visio lifecycle pages and publish the ``visio`` record.

    Complete-or-nothing: every page is fetched and parsed, the fetched rows are
    combined with the lines this source no longer states, the whole snapshot is
    staged beside the committed catalog and validated there, and only then is
    anything written.
    """
    root = Path(directory) if directory is not None else ROOT / "data"
    committed = committed_record(root)
    checked = _now()
    releases, detail = parse_pages(snapshot(_page_urls()))
    combined, kept = combine_releases(releases, committed)
    excluded = [{"url": url, "reason": reason} for url, reason in EXCLUDED_OFFERINGS]
    report = report_for(combined, detail, kept, excluded, checked)
    publish_record(record_for(combined, checked), report, root)
    rows = report["rows"]
    return (f"imported {rows['published']} Microsoft Visio lifecycle lines "
            f"({rows['support_dates']} support-date rows + {rows['releases']} release rows); "
            f"excluded {rows['excluded']} offerings, retained {rows['retained']} "
            f"(data/{REPORT})")
