"""GitHub Enterprise Server branch lifecycle, from GitHub's own release table.

Source: ``https://docs.github.com/en/enterprise-server@latest/admin/all-releases``,
fetched as its Markdown rendering (the same URL with ``.md`` appended), which
renders the page's tables as pipe rows. The page's "Releases of GitHub
Enterprise Server" table carries one row per release line: the version, the
release candidate date, the release date, the closing down date, whether the
version is still supported, and links to that version's release notes and docs.

GitHub states the semantics of its own columns on that page in prose: "GitHub
supports at least the four most recent feature releases." In the vendor's
upgrade-troubleshooting article the same column is described as the support
window's end — "We have extended the support window for versions 3.14, 3.15,
3.16, and 3.17. ... The closing down date for each of 3.14, 3.15, 3.16, and
3.17 has been updated." and "We will continue to release patches for 3.14,
3.15, 3.16, and 3.17 throughout this extended support window." So a closing down
date is the end of the window in which GitHub still ships patches for that
feature release: the terminal support date, mapped to ``eol``.

Only the two dates the table states become milestones, at the day precision the
table states: ``Release`` -> ``ga`` and ``Closing down date`` -> ``eol``. Nothing
is derived from the four-release policy, from a fixed support duration, or from
a version's absence from the table, because the published column is the only
support claim GitHub makes — and it does not follow a fixed duration (3.17 runs
2025-06-03 to 2026-09-22, while 3.14 and 3.15 both close 2026-04-23). ``eos`` and
``eossec`` stay null: the source publishes no sale end and no separate
security-only end.

One product (``github-enterprise-server``), one release per feature release line
(``3.22``). A patch (``3.22.1``) is a release inside its line, so the identity is
the line and a permalink does not churn on every patch. Every row's declared
cells are kept verbatim under the release's ``upstream``, including the vendor's
own supported/not-supported wording read from the table's icon label, so the
human pages show what GitHub published and validation re-derives every milestone
from those cells offline.

Out of scope, and never read as a GHES end of life: the REST API version
calendar on the same site (an API version retiring is not the appliance's
lifecycle), GitHub Enterprise Cloud, hosted runners, and the page's tool-version
tables (CodeQL CLI, Actions Runner), whose rows state no lifecycle date.
"""
import re
from datetime import date, datetime, timezone
from pathlib import Path

from . import net, sources, transaction
from .importer import ROOT

# The registry owns the id and the page: a record's provenance must name a
# source this checkout installs, and the site links the page a reader opens.
VERIFIER = sources.source("import-ghes").verifier
SOURCE_URL = sources.GITHUB_GHES_RELEASES
# The same page, rendered as the Markdown whose tables the refresh parses.
MARKDOWN_URL = SOURCE_URL + ".md"
REPORT = sources.source("import-ghes").report
RECORD_SCHEMA = "https://zarguell.github.io/eoltracker/v1/schema/product.json"
PRODUCT_ID = "github-enterprise-server"
PRODUCT_NAME = "GitHub Enterprise Server"
UPSTREAM_CATEGORY = "server-app"

# The columns the lifecycle table declares, exactly as the vendor heads them. A
# reshaped header set refuses the parse rather than letting a column be read
# under the wrong name.
LIFECYCLE_COLUMNS = ("Version", "Candidate", "Release", "Closing down date")
# The section whose first table is the lifecycle table.
RELEASES_SECTION = "Releases of GitHub Enterprise Server"
# The vendor's own wording for the Supported column. In the Markdown rendering
# the cell is the octicon whose aria-label carries that wording; a plain-text
# cell states the same two phrases. Anything else is a reshaped page.
SUPPORTED_LABELS = {"supported": "Supported", "not supported": "Not supported"}
# The milestone each stated column carries. Only these two columns are dates.
GA_COLUMN = "Release"
EOL_COLUMN = "Closing down date"
# A version line: two or more dot-separated numbers (3.22, 11.10.340).
VERSION = re.compile(r"\d+(?:\.\d+)+")
DAY = re.compile(r"\d{4}-\d{2}-\d{2}")
# A cell that states no date. None of these is a date, and none becomes one.
NO_DATE = {"", "-", "—", "n/a", "na", "tbd", "tba", "unknown"}


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _normalized(text):
    """Fold a header or value for comparison: case and punctuation removed."""
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def day_value(text, where):
    """``2027-09-08`` -> itself; anything else is a parse failure, not a guess.

    The table publishes full days, so a day is what is stored: a value of
    another shape (or a date that is not on the calendar) refuses the parse
    rather than being coerced.
    """
    text = re.sub(r"\s+", " ", text or "").strip()
    if text.lower() in NO_DATE:
        return None
    if not DAY.fullmatch(text):
        raise ValueError(f"{where}: unrecognized day-precision date {text!r}")
    try:
        date.fromisoformat(text)
    except ValueError:
        raise ValueError(f"{where}: unrecognized day-precision date {text!r}") from None
    return text


def _cells(line):
    """One Markdown table row -> cell texts, with links reduced to their text.

    A cell may carry a link: the text is what the vendor states, so the href is
    never read. The supported column's icon is markup, not text, and is kept
    intact here so :func:`_supported` can read the vendor's own label from it.
    """
    cells = line.strip().strip("|")
    return [re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", cell).strip() for cell in cells.split("|")]


def _separator(cells):
    """True for a Markdown table's alignment row."""
    return bool(cells) and all(re.fullmatch(r":?-{1,}:?", cell) for cell in cells)


def _supported(cell, where):
    """The vendor's support wording, read from the cell's own label or text."""
    match = re.search(r'aria-label="([^"]*)"', cell)
    text = re.sub(r"\s+", " ", match.group(1) if match else cell).strip()
    wording = SUPPORTED_LABELS.get(text.lower())
    if wording is None:
        raise ValueError(f"{where}: unrecognized Supported cell {text!r}")
    return wording


def _cell(cells, header):
    """One column of a parsed row, matched by normalized header text."""
    wanted = _normalized(header)
    for key, value in cells.items():
        if _normalized(key) == wanted:
            return value
    raise ValueError(f"GHES row without the {header!r} column")


def _optional_cell(cells, header):
    """One column that only some lifecycle tables declare; empty when absent."""
    wanted = _normalized(header)
    for key, value in cells.items():
        if _normalized(key) == wanted:
            return value
    return ""


def _table(lines, index):
    """The Markdown table starting at ``lines[index]``: its header and raw rows.

    Rows are kept as cell lists rather than dictionaries, because the page's
    other tables declare their own headers: a row is only ever read against the
    header of the table it came from, and a tool-version table is never made to
    fit the lifecycle table's columns.
    """
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
    """Every pipe table on the page, as ``(heading, header, rows)``.

    The page carries the lifecycle table plus the vendor's tool-version and
    developer-docs tables. Only the lifecycle table is read for releases; the
    others are still collected, so the report accounts for every row the page
    states instead of silently ignoring it.
    """
    lines = markdown.splitlines()
    tables = []
    heading = ""
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.startswith("#"):
            heading = line.lstrip("#").strip()
        elif line.strip().startswith("|"):
            header, rows = _table(lines, index)
            tables.append((heading, header, rows))
            while index < len(lines) and lines[index].strip().startswith("|"):
                index += 1
            continue
        index += 1
    if not tables:
        raise ValueError("The GitHub Enterprise Server page states no tables")
    return tables


def _release(cells, heading):
    """One published release line, derived from the vendor's own cells.

    The row's own columns are kept verbatim. ``Supported`` is stored as the
    wording its icon carries, which is the vendor's support state rather than a
    date; a table that declares no support column contributes no such cell.
    """
    version = re.sub(r"\s+", " ", _cell(cells, "Version")).strip()
    where = f"GitHub Enterprise Server {version}"
    stated = dict(cells)
    supported = _optional_cell(cells, "Supported")
    if supported:
        stated["Supported"] = _supported(supported, where)
    return {
        "id": version,
        "name": f"GitHub Enterprise Server {version}",
        "milestones": {"ga": day_value(_cell(cells, GA_COLUMN), where), "eos": None, "eossec": None,
                       "eol": day_value(_cell(cells, EOL_COLUMN), where)},
        "upstream": {"name": version, "cells": stated, "table": heading},
    }


def _is_lifecycle(header):
    """True for a table declaring the vendor's four lifecycle columns.

    The releases table also declares the support state and two documentation
    links; the older developer-documentation table declares the same four date
    columns and one link column instead. Both carry release lines, so a table is
    recognized by those leading columns rather than by a fixed width or heading.
    """
    return (tuple(_normalized(cell) for cell in header[:len(LIFECYCLE_COLUMNS)])
            == tuple(map(_normalized, LIFECYCLE_COLUMNS)))


def _lifecycle_row(header, row, heading):
    """One raw row paired with its table's header, refusing a ragged row."""
    if len(row) != len(header):
        raise ValueError(f"{heading} row has {len(row)} cells for {len(header)} columns: "
                         f"{row[0]!r}")
    return dict(zip(header, row))


def _stated(cells):
    """Every lifecycle-bearing statement a row makes, for comparing two of them.

    The four declared lifecycle columns are always included. The vendor's
    support wording is included whenever the row states it: it is not a date, but
    it is the vendor's own lifecycle claim about the line, so two tables
    disagreeing about it — one saying ``Supported`` while the other says ``Not
    supported`` — are contradicting each other and must refuse the parse rather
    than let the first row chosen decide. A table that declares no support column
    (the developer-documentation table) makes no such claim, so its rows compare
    on the columns they do state.
    """
    stated = {column: re.sub(r"\s+", " ", cells[column]).strip() for column in LIFECYCLE_COLUMNS}
    supported = _optional_cell(cells, "Supported")
    if supported:
        stated["Supported"] = _supported(supported, f"GitHub Enterprise Server {stated['Version']}")
    return stated


def _disagreements(first, second):
    """The columns two statements of one release line state differently.

    A column only one of the two rows declares is not a disagreement: a table
    that states no support column makes no support claim, so its row is compared
    on the columns it does state. Only a column both rows state — with different
    values — is the vendor contradicting itself.
    """
    return sorted(column for column in set(first) & set(second)
                  if first[column] != second[column])


def parse_releases(markdown):
    """Every page row -> ``(releases, excluded, duplicated)``; no row is dropped.

    Every lifecycle row states a release line, so every one of them is in the
    inventory — including the legacy line that declares no dates at all, which is
    published with null milestones rather than discarded: an unannounced deadline
    stays absent (AGENTS.md rule 2). A row the parser cannot place at all — one
    that states no version line — is reported with its reason instead.

    The developer-documentation table restates release lines the releases table
    already carries, at the same dates; a restatement is accounted in
    ``duplicated`` so the rows add up, and a restatement whose values contradict
    the first statement refuses the parse: two vendor tables disagreeing about a
    support date is a review, never a silent choice between them. A row of any
    other table — the CodeQL CLI and Actions Runner version tables, which state
    no lifecycle date — is reported as excluded.

    ``releases`` (minus retained history) + ``excluded`` + ``duplicated`` is
    every lifecycle row the page states.
    """
    releases, excluded, duplicated, seen = [], [], [], {}
    tables = _tables(markdown)
    authoritative = [rows for heading, header, rows in tables
                     if heading == RELEASES_SECTION and _is_lifecycle(header)]
    if not authoritative:
        raise ValueError(f"Missing GitHub Enterprise Server table: {RELEASES_SECTION}")
    if not any(authoritative):
        # A header-only releases table is a partial snapshot, not an empty
        # catalog: the developer-documentation table's rows would publish as the
        # whole inventory, and a first-run refresh would report success for it.
        # Refuse the parse so the refresh writes nothing.
        raise ValueError(f"The GitHub Enterprise Server table {RELEASES_SECTION!r} states no "
                         f"release lines")
    for heading, header, rows in tables:
        for row in rows:
            if not _is_lifecycle(header):
                excluded.append({"table": heading, "row": " | ".join(row),
                                 "reason": "not a GitHub Enterprise Server lifecycle table: it "
                                           "declares no Closing down date column, so its rows "
                                           "state no branch support date"})
                continue
            cells = _lifecycle_row(header, row, heading)
            version = re.sub(r"\s+", " ", cells["Version"]).strip()
            if not VERSION.fullmatch(version):
                excluded.append({"table": heading, "row": version,
                                 "reason": "no version line in the row"})
                continue
            first = seen.get(version)
            if first is not None:
                second = _stated(cells)
                contradicting = _disagreements(first, second)
                if contradicting:
                    raise ValueError(f"GitHub Enterprise Server {version} is stated twice with "
                                     f"contradicting values ({', '.join(contradicting)}): "
                                     f"{first} then {second}")
                duplicated.append({"table": heading, "row": version,
                                   "reason": "another table on the page states this release line "
                                             "with the same values; the line is read once, and "
                                             "this row is accounted here rather than dropped"})
                continue
            seen[version] = _stated(cells)
            releases.append(_release(cells, heading))
    if not releases:
        raise ValueError("The GitHub Enterprise Server table produced no releases")
    return _ordered(releases), excluded, duplicated


def _ordered(releases):
    """Newest release line first, as the vendor's own table lists them.

    The page lists its rows by release date, newest first, so the published
    ``ga`` is the ordering key rather than the version number: the legacy
    ``11.10.340`` line is numerically larger than ``3.22`` but shipped in 2015,
    and a row that states no release date sorts after every dated one.
    """
    return sorted(releases,
                  key=lambda release: (release["milestones"]["ga"] or "",
                                       tuple(int(part) for part in release["id"].split("."))),
                  reverse=True)


def retained(release):
    """A committed release the current table no longer states, marked as such.

    The row is republished from its own stored cells, so retention can never
    introduce a date GitHub did not publish; the marker says only that the
    current table lacks the row. Absence from the table is not an end of life.
    """
    return {**release, "upstream": {**release["upstream"], "in_source": False}}


def combine_releases(fresh, committed):
    """The complete release-line snapshot: this fetch's rows plus retained history.

    A published line the current table no longer states keeps its record rather
    than disappearing from the catalog, exactly as a source row dropped from a
    table is not thereby an end of life.
    """
    if committed is None:
        return _ordered(fresh), []
    ids = {release["id"] for release in fresh}
    kept = [retained(release) for release in committed["releases"] if release["id"] not in ids]
    return (_ordered(fresh + kept),
            [{"id": release["id"], "name": release["name"],
              "reason": "the current GitHub Enterprise Server table does not state this release "
                        "line; the committed row and its dates are retained"} for release in kept])


def validate_record(record):
    """Rebuild every stored release from its own published cells, offline.

    Offline, a record's cells are the whole evidence: the release date, the
    closing down date and the support wording are re-derived from them, so a
    file whose dates no longer follow the row it stores is never published. The
    legacy line whose row states no dates keeps null milestones, which is what
    its own cells re-derive.
    """
    if record["provenance"]["verifier"] != VERIFIER:
        raise ValueError("Invalid GitHub Enterprise Server source identity")
    seen = set()
    for release in record["releases"]:
        cells = release.get("upstream", {}).get("cells")
        if not isinstance(cells, dict) or not cells:
            raise ValueError(f"GitHub Enterprise Server release without source cells: "
                             f"{release['id']}")
        for column in LIFECYCLE_COLUMNS:
            _cell(cells, column)
        version = re.sub(r"\s+", " ", _cell(cells, "Version")).strip()
        if release["id"] in seen or version != release["id"]:
            raise ValueError(f"{record['id']}: release {release['id']} does not name its own "
                             f"version line: {version!r}")
        if not VERSION.fullmatch(version):
            raise ValueError(f"{record['id']}: release {release['id']} is not a version line")
        where = f"GitHub Enterprise Server {version}"
        milestones = {"ga": day_value(_cell(cells, GA_COLUMN), where), "eos": None, "eossec": None,
                      "eol": day_value(_cell(cells, EOL_COLUMN), where)}
        if release["milestones"] != milestones:
            raise ValueError(f"{record['id']}: release {release['id']} contradicts its stored cells")
        if release.get("upstream", {}).get("name") != version:
            raise ValueError(f"{record['id']}: release {release['id']} contradicts the published "
                             f"version line")
        supported = _optional_cell(cells, "Supported")
        if supported and _supported(supported, where) != supported:
            raise ValueError(f"{record['id']}: release {release['id']} contradicts the published "
                             f"support state")
        if release["upstream"].get("in_source") not in (None, False):
            raise ValueError(f"{record['id']}: release {release['id']} carries an invalid "
                             f"retention marker")


def record_for(releases, checked):
    """The published ``github-enterprise-server`` record for one complete snapshot."""
    return {
        "$schema": RECORD_SCHEMA,
        "id": PRODUCT_ID,
        "name": PRODUCT_NAME,
        "category": "software",
        "upstream_category": UPSTREAM_CATEGORY,
        # No identifier is published: GitHub documents release lines and the
        # appliance images, never a CPE for this product, and an invented one
        # would be a claim the source does not make.
        "identifiers": [],
        # The vendor column wording each milestone was read from.
        "labels": {"ga": GA_COLUMN, "eol": EOL_COLUMN},
        "links": {"html": SOURCE_URL},
        "releases": releases,
        "provenance": {"source_url": SOURCE_URL, "verifier": VERIFIER,
                       "last_checked": checked, "upstream_modified": None},
    }


def report_for(releases, excluded, duplicated, kept, checked):
    """The per-row accounting this source publishes beside its record.

    ``seen`` is every lifecycle row the page stated; ``published`` is the
    inventory it produced (the legacy line without dates included, with null
    milestones); ``duplicated`` is a row another table restated with the same
    values; ``excluded`` is a row of a table that states no lifecycle date. The
    three add up to ``seen``, so no source row is unaccounted for.
    """
    retained_ids = {entry["id"] for entry in kept}
    fresh = [release for release in releases if release["id"] not in retained_ids]
    # Every lifecycle row read is either published, or a restatement of a line
    # already published; the rest of the page's rows are excluded with a reason.
    lifecycle = len(fresh) + len(duplicated)
    undated = sum(1 for release in fresh
                  if release["milestones"]["ga"] is None or release["milestones"]["eol"] is None)
    return {
        "source_url": SOURCE_URL, "markdown_url": MARKDOWN_URL, "verifier": VERIFIER,
        "checked_at": checked,
        "record_scope": ("GitHub Enterprise Server release lines: one software record with one "
                         "release per feature release line, from the vendor's own releases table, "
                         "carrying the release date and the closing down date that table states"),
        "rows": {"seen": lifecycle + len(excluded), "published": len(releases),
                 "lifecycle": lifecycle, "undated": undated, "retained": len(kept),
                 "duplicated": len(duplicated), "excluded": len(excluded)},
        "excluded": excluded,
        "duplicated": duplicated,
        "retained": kept,
        "total_records": 1,
        "limitations": [
            "eol is the vendor's 'Closing down date': the end of the window in which GitHub still "
            "releases patches for that feature release. It is not a deprecation start.",
            "eos and eossec are absent: the source publishes no sale end and no separate "
            "security-only support end.",
            "No date is derived from the four-release support policy, from a fixed support "
            "duration, or from the release cadence; the stored dates are the table's own values.",
            "A release line whose row states no dates is published with null milestones, not "
            "dropped. The 11.10.340 line is the page's only such row.",
            "The older developer documentation table restates the release lines it documents; "
            "those rows are listed under 'duplicated' and counted once, and a restatement that "
            "disagreed with the releases table would refuse the parse instead of being chosen.",
            "A release line the current table no longer states is retained from the committed "
            "snapshot and marked upstream.in_source false; a dropped row is not an end of life.",
            "The page's Supported column is carried as the vendor's own wording and is never "
            "mapped to a milestone.",
            "Out of scope: REST API version retirement (a different calendar on the same site), "
            "GitHub Enterprise Cloud, hosted runners, and the page's CodeQL CLI and Actions "
            "Runner version tables, whose rows state no lifecycle date and are reported as "
            "excluded rows.",
        ],
    }


def committed_record(root):
    """The committed ``github-enterprise-server`` record, refusing a foreign one."""
    return transaction.committed_product_record(root, PRODUCT_ID, VERIFIER,
                                                validate_record, "GitHub Enterprise Server")


def publish_record(record, report, root):
    """Stage the record beside the committed catalog, validate, then replace it."""
    return transaction.publish_product_record(record, report, root, REPORT)


def import_ghes(directory=None):
    """Fetch the releases table and publish the ``github-enterprise-server`` record.

    Complete-or-nothing: the fetched snapshot is combined with the release lines
    the source no longer states, staged beside the committed catalog and
    validated there before anything is written. A parse failure, a header change
    or an inconsistent catalog leaves every committed file untouched.
    """
    root = Path(directory) if directory is not None else ROOT / "data"
    # The committed ownership check runs before the fetch: a file this source
    # cannot publish aborts the run without a network call at all.
    committed = committed_record(root)
    checked = _now()
    fresh, excluded, duplicated = parse_releases(net.get_text(MARKDOWN_URL))
    releases, kept = combine_releases(fresh, committed)
    report = report_for(releases, excluded, duplicated, kept, checked)
    publish_record(record_for(releases, checked), report, root)
    rows = report["rows"]
    return (f"imported {len(releases)} GitHub Enterprise Server release lines "
            f"({rows['lifecycle']} lifecycle rows, {rows['undated']} without dates); "
            f"excluded {rows['excluded']} rows, duplicated {rows['duplicated']}, "
            f"retained {rows['retained']} (data/{REPORT})")
