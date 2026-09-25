"""Check Point Security Gateway & Management release-train lifecycle, from the vendor's own policy page.

Source: ``https://www.checkpoint.com/support-services/support-life-cycle-policy/``.
The page's "Security Gateway & Management" table (under the "Software Support"
section, ``id="gateway-management"``) carries one row per release train — the
Gaia-based Security Gateway and Security Management trains: the train name, its
general-availability month, the sub-releases it covers, and the month its
support ends.

The vendor publishes no day anywhere on this table, so per AGENTS.md rule 4
every milestone is stored as ``YYYY-MM`` — the shape the schema admits beside
full ISO days and that is never padded with a fabricated ``-01``. Only the two
columns that are dates become milestones: ``General Availability`` -> ``ga`` and
``Support Until`` -> ``eol``. ``Support Until`` is the terminal support end for
the train (the vendor states no separate security-only end here), and the page's
policy prose — "support for all software products for a minimum of four years,
starting from the general availability date" — is a *rule*, not a date, so
nothing is derived from it arithmetically.

Both current and historical trains are published: the table keeps them together
(R82.20 down to R75), so the record is the vendor's complete train inventory, and
``Affected Versions`` grouping is preserved verbatim in the row's cells rather
than expanded into invented sub-release records.

One product (``checkpoint-security-gateway``), one release per release train.
The identity is the train (``r81-20``), not a build or a take, so a permalink
survives every jumbo hotfix. The page also carries the Appliances Support
timeline, the service tables and the Unsupported Products table; those rows are
outside this source's software scope and are accounted for in the report rather
than silently ignored.

Access: the host is fronted by an AWS WAF that answers a burst of requests with
a JavaScript challenge (``202`` + ``x-amzn-waf-action: challenge``) and serves
the real page to a politely spaced request. The collector performs exactly one
fetch per run; a challenged or reshaped response refuses the parse, so a
rate-limited run writes nothing and the next scheduled refresh picks it up.
"""
import re
from datetime import datetime, timezone
from pathlib import Path

from . import net, sources
from .importer import ROOT

# The registry owns the id and the page: a record's provenance must name a
# source this checkout installs, and the site links the page a reader opens.
VERIFIER = sources.source("import-checkpoint").verifier
SOURCE_URL = sources.CHECKPOINT_LIFECYCLE
REPORT = sources.source("import-checkpoint").report
RECORD_SCHEMA = "https://zarguell.github.io/eoltracker/v1/schema/product.json"
PRODUCT_ID = "checkpoint-security-gateway"
PRODUCT_NAME = "Check Point Security Gateway & Management"
UPSTREAM_CATEGORY = "server-app"

# The section heading whose table is this source's scope, exactly as the vendor
# states it, and the columns that table declares. A reshaped header set refuses
# the parse rather than letting a column be read under the wrong name.
TABLE_NAME = "Security Gateway & Management"
HEADERS = ("Major Version", "General Availability", "Affected Versions", "Support Until")
# The two columns that state a date, and the milestone each carries.
GA_COLUMN = "General Availability"
EOL_COLUMN = "Support Until"
# The policy page's <h2> sections. Only the Software Support section's tables are
# in scope; the Appliances Support timeline is a different catalog's scope.
SOFTWARE_SECTION = "Software Support"
MONTH_NAMES = (("january", "jan"), ("february", "feb"), ("march", "mar"), ("april", "apr"),
               ("may", "may"), ("june", "jun"), ("july", "jul"), ("august", "aug"),
               ("september", "sept", "sep"), ("october", "oct"), ("november", "nov"),
               ("december", "dec"))
MONTHS = {name: number for number, names in enumerate(MONTH_NAMES, start=1) for name in names}
# A cell that states no date. None of these is a date, and none becomes one.
NO_DATE = {"", "-", "–", "—", "n/a", "na", "tbd", "tba", "unknown"}
ROW = re.compile(r"<tr\b.*?</tr>", re.S | re.I)
CELL = re.compile(r"<(t[hd])\b[^>]*>(.*?)</\1>", re.S | re.I)
TABLE = re.compile(r"<table\b.*?</table>", re.S | re.I)
HEADING = re.compile(r"<h([1-6])\b[^>]*>(.*?)</h\1>", re.S | re.I)
TAG = re.compile(r"<[^>]+>")


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _text(value):
    """One cell's visible text: tags dropped, entities decoded, whitespace folded."""
    from html import unescape
    return re.sub(r"\s+", " ", unescape(TAG.sub(" ", value or ""))).replace("\xa0", " ").strip()


def _normalized(text):
    """Fold a header or value for comparison: case and punctuation removed."""
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def month_value(text, where):
    """``September 2030`` -> ``2030-09``; anything else is a parse failure, not a guess.

    The result is a month, and it stays a month: no day is ever appended.
    """
    text = re.sub(r"\s+", " ", text or "").strip()
    if text.lower() in NO_DATE:
        return None
    match = re.fullmatch(r"([A-Za-z]+)\.?\s+(\d{4})", text)
    number = MONTHS.get(match.group(1).lower()) if match else None
    if number is None:
        raise ValueError(f"{where}: unrecognized month-precision date {text!r}")
    return f"{match.group(2)}-{number:02d}"


def train_id(name):
    """The stable id of one release train: its own name, URL-safe.

    ``Check Point R81.20`` -> ``r81-20``; ``Check Point R75.40VS`` -> ``r75-40vs``;
    ``Check Point R80*`` -> ``r80``; ``NGSE`` -> ``ngse``. The vendor's own name is
    the identity, minus the product prefix and footnote markers, so a build or a
    take never changes it and a distinct train (R75.40VS) stays distinct from the
    train it is named beside (R75.40).
    """
    text = re.sub(r"\^\*+|\*+$", "", name.strip()).strip()
    text = re.sub(r"^Check\s+Point\s+", "", text, flags=re.I).strip()
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _tables(page):
    """Every table on the page as ``(section, heading, headers, rows)``.

    The page groups its tables under ``<h2>`` sections and ``<h3>`` headings, so
    a table is read with the heading that names it and the section it sits in.
    Rows are kept as cell lists and only ever read against their own table's
    header, so the appliance grid is never made to fit a software table.
    """
    structure = sorted((m.start(), m.group(1), _text(m.group(2)))
                       for m in HEADING.finditer(page))
    tables = []
    for match in TABLE.finditer(page):
        start = match.start()
        section = heading = ""
        for position, level, text in structure:
            if position > start:
                break
            if level == "2":
                section, heading = text, ""
            else:
                heading = text
        rows, headers = [], []
        for row in ROW.findall(match.group(0)):
            cells = [(kind.lower(), _text(body)) for kind, body in CELL.findall(row)]
            if not cells:
                continue
            if all(kind == "th" for kind, _ in cells):
                if not headers:
                    headers = [text for _, text in cells]
                continue
            rows.append([text for _, text in cells])
        tables.append({"section": section, "heading": heading, "headers": headers, "rows": rows})
    if not tables:
        raise ValueError(f"The Check Point policy page states no tables: {SOURCE_URL}")
    return tables


def _row(cells, header, heading):
    """One raw row paired with its table's header, refusing a ragged row."""
    if len(cells) != len(header):
        raise ValueError(f"{heading} row has {len(cells)} cells for {len(header)} columns: "
                         f"{cells[0]!r}")
    return dict(zip(header, cells))


def _cell(cells, header):
    """One column of a parsed row, matched by normalized header text."""
    wanted = _normalized(header)
    for key, value in cells.items():
        if _normalized(key) == wanted:
            return value
    raise ValueError(f"Check Point row without the {header!r} column")


def _release(name, cells, heading):
    """One published release train, derived from the vendor's own cells."""
    release_id = train_id(name)
    where = f"Check Point {name!r}"
    return {
        "id": release_id,
        "name": name,
        "milestones": {"ga": month_value(_cell(cells, GA_COLUMN), where),
                       "eos": None, "eossec": None,
                       "eol": month_value(_cell(cells, EOL_COLUMN), where)},
        "upstream": {"name": name, "cells": cells, "table": heading},
    }


def _stated(cells):
    """Every lifecycle-bearing cell of a train row, for comparing two of them.

    The major version is the row's identity, so it is normalized rather than
    compared; the general-availability month, the affected-versions grouping and
    the support-until month are the vendor's claims about the train. Two rows
    naming one train while disagreeing about any of them are the vendor
    contradicting itself, never a duplicate to deduplicate silently.
    """
    return {column: re.sub(r"\s+", " ", _cell(cells, column)).strip()
            for column in HEADERS if column != "Major Version"}


def parse_trains(page):
    """Every in-scope table row -> ``(releases, excluded)``; no row is dropped.

    The Security Gateway & Management table's rows become the release inventory.
    Every other row the page states — the appliance timeline, the service tables,
    the Unsupported Products table, and the Latest Announcements summary — is
    reported with the section and heading it came from, so the accounting covers
    the whole page. A row that identifies no train is reported with its reason
    instead of being published.

    A second row for a train already seen is accounted as a duplicate only when
    it restates the first with the same lifecycle cells; a row that contradicts
    the first refuses the parse rather than publishing whichever came first.
    """
    tables = _tables(page)
    if not any(_normalized(table["heading"]) == _normalized(TABLE_NAME) for table in tables):
        raise ValueError(f"Missing Check Point table: {TABLE_NAME}")
    releases, excluded, seen = [], [], {}
    for table in tables:
        heading = table["heading"]
        if (_normalized(heading) != _normalized(TABLE_NAME)
                or _normalized(table["section"]) != _normalized(SOFTWARE_SECTION)):
            excluded.extend(
                {"section": table["section"], "table": heading, "row": " | ".join(cells),
                 "reason": f"not the {TABLE_NAME} software table: this row states no "
                           f"Security Gateway & Management release-train lifecycle"}
                for cells in table["rows"])
            continue
        if tuple(map(_normalized, table["headers"])) != tuple(map(_normalized, HEADERS)):
            raise ValueError(f"Unexpected Check Point table headers in {heading!r}: "
                             f"{table['headers']}")
        for cells in table["rows"]:
            row = _row(cells, table["headers"], heading)
            name = _cell(row, "Major Version").strip()
            if not name:
                excluded.append({"section": table["section"], "table": heading, "row": name,
                                 "reason": "the row states no release train"})
                continue
            release_id = train_id(name)
            if not release_id:
                excluded.append({"section": table["section"], "table": heading, "row": name,
                                 "reason": "no release-train identity in the row"})
                continue
            if release_id in seen:
                if seen[release_id] != _stated(row):
                    raise ValueError(f"Check Point {name!r} is stated twice with contradicting "
                                     f"values: {seen[release_id]} then {_stated(row)}")
                excluded.append({"section": table["section"], "table": heading, "row": name,
                                 "reason": f"duplicate train row for release {release_id!r}"})
                continue
            seen[release_id] = _stated(row)
            releases.append(_release(name, row, heading))
    if not releases:
        raise ValueError("The Check Point Security Gateway & Management table produced no releases")
    return releases, excluded


def retained(release):
    """A committed train the current table no longer states, marked as such.

    The row is republished from its own stored cells, so retention can never
    introduce a date the vendor did not publish; the marker says only that the
    current table lacks the row. Absence from a table is not an end of life.
    """
    return {**release, "upstream": {**release["upstream"], "in_source": False}}


def combine_releases(fresh, committed):
    """The complete train snapshot: this fetch's rows plus retained history.

    A published train the vendor's current table no longer states keeps its
    record rather than disappearing from the catalog, exactly as a source row
    dropped from a table is not thereby an end of life.
    """
    if committed is None:
        return list(fresh), []
    ids = {release["id"] for release in fresh}
    kept = [retained(release) for release in committed["releases"] if release["id"] not in ids]
    return (fresh + kept,
            [{"id": release["id"], "name": release["name"],
              "reason": "the current Check Point table does not state this release train; "
                        "the committed row and its dates are retained"} for release in kept])


def validate_record(record):
    """Rebuild every stored train from its own published cells, offline.

    Offline, a record's cells are the whole evidence: the train identity and
    both milestones are re-derived from them, so a file whose dates or train no
    longer follow the row it stores is never published.
    """
    if record["provenance"]["verifier"] != VERIFIER:
        raise ValueError("Invalid Check Point source identity")
    seen = set()
    for release in record["releases"]:
        cells = release.get("upstream", {}).get("cells")
        if not isinstance(cells, dict) or not cells:
            raise ValueError(f"Check Point release without source cells: {release['id']}")
        for column in HEADERS:
            _cell(cells, column)
        name = _cell(cells, "Major Version").strip()
        if release["id"] in seen or train_id(name) != release["id"]:
            raise ValueError(f"{record['id']}: release {release['id']} does not name its own "
                             f"train: {name!r}")
        seen.add(release["id"])
        expected = _release(name, cells, release["upstream"].get("table", ""))
        if release["name"] != expected["name"] or release["milestones"] != expected["milestones"]:
            raise ValueError(f"{record['id']}: release {release['id']} contradicts its stored cells")
        if release["upstream"].get("name") != expected["upstream"]["name"]:
            raise ValueError(f"{record['id']}: release {release['id']} contradicts the published "
                             f"train name")
        if release["upstream"].get("in_source") not in (None, False):
            raise ValueError(f"{record['id']}: release {release['id']} carries an invalid "
                             f"retention marker")


def record_for(releases, checked):
    """The published ``checkpoint-security-gateway`` record for one train snapshot."""
    return {
        "$schema": RECORD_SCHEMA,
        "id": PRODUCT_ID,
        "name": PRODUCT_NAME,
        "category": "software",
        "upstream_category": UPSTREAM_CATEGORY,
        # No identifier is published: Check Point documents release trains,
        # never a CPE for this product, and an invented one would be a claim the
        # source does not make.
        "identifiers": [],
        # The vendor column wording each milestone was read from.
        "labels": {"ga": GA_COLUMN, "eol": EOL_COLUMN},
        "links": {"html": SOURCE_URL},
        "releases": releases,
        "provenance": {"source_url": SOURCE_URL, "verifier": VERIFIER,
                       "last_checked": checked, "upstream_modified": None},
    }


def report_for(releases, excluded, kept, checked):
    """The per-row accounting this source publishes beside its record.

    ``seen`` is every table row the page stated that is in scope of this
    source's table plus the rows this source reports as out of scope, so the
    page's rows are all accounted for; the retained snapshot rows are counted
    separately, so the numbers read as one observation of one source.
    """
    retained = {entry["id"] for entry in kept}
    fresh = [release for release in releases if release["id"] not in retained]
    undated = sum(1 for release in fresh if release["milestones"]["ga"] is None
                  or release["milestones"]["eol"] is None)
    return {
        "source_url": SOURCE_URL, "verifier": VERIFIER,
        "checked_at": checked,
        "record_scope": ("Check Point Security Gateway & Management release trains: one software "
                         "record with one release per train, from the vendor's own Support Life "
                         "Cycle Policy table, at the month precision that table states"),
        "rows": {"seen": len(fresh) + len(excluded), "published": len(releases),
                 "trains": len(fresh), "undated": undated,
                 "retained": len(kept), "excluded": len(excluded)},
        "excluded": excluded,
        "retained": kept,
        "total_records": 1,
        "limitations": [
            "Month precision only: the vendor's table states months, so every milestone is "
            "stored as YYYY-MM and no day is ever invented.",
            "eos and eossec are absent: the Security Gateway & Management table publishes no "
            "end-of-sale column and no separate security-only end.",
            "No date is derived from the published support policy (a minimum of four years from "
            "general availability); stored milestones are the vendor's own row values.",
            "Affected Versions grouping is preserved verbatim as the row's own cell; a grouped "
            "scope (R80.20, R80.30***) is never expanded into invented sub-release records.",
            "Footnote variants (the R80.30 FIPS mode statement and the day-precision cloud "
            "firewall end-of-support list) are sub-scopes of, not replacements for, the table "
            "rows; they are not read as milestones.",
            "Out of scope and reported as excluded rows: the Appliances Support timeline, the "
            "service tables (GenAI Protect, Cloudguard CNAPP, NDR, Workspace Security Connect "
            "and App Protect, Edge, IoT Protect Firmware, Capsule Workspace), the Unsupported "
            "Products table and the Latest Announcements summary. Appliance lifecycle is the "
            "hardware catalog's scope, and software coverage here does not imply it.",
            "A train the current table no longer states is retained from the committed snapshot "
            "and marked upstream.in_source false; a dropped row is not an end of life.",
            "The host answers a request burst with an AWS WAF JavaScript challenge; this "
            "collector makes one fetch per run, and a challenged response refuses the parse "
            "rather than publishing a partial snapshot.",
        ],
    }


def committed_record(root):
    """The committed ``checkpoint-security-gateway`` record, refusing a foreign one."""
    from . import transaction

    return transaction.committed_product_record(root, PRODUCT_ID, VERIFIER,
                                                validate_record, "Check Point")


def publish_record(record, report, root):
    """Stage the record beside the committed catalog, validate, then replace it."""
    from . import transaction

    return transaction.publish_product_record(record, report, root, REPORT)


def import_checkpoint(directory=None):
    """Fetch the policy page and publish the ``checkpoint-security-gateway`` record.

    Complete-or-nothing: the fetched snapshot is combined with the trains the
    source no longer states, staged beside the committed catalog and validated
    there before anything is written. A parse failure, a header change, a
    challenged response or an inconsistent catalog leaves every committed file
    untouched.
    """
    root = Path(directory) if directory is not None else ROOT / "data"
    # The committed ownership check runs before the fetch: a file this source
    # cannot publish aborts the run without a network call at all.
    committed = committed_record(root)
    checked = _now()
    # One fetch per run: this host challenges bursts, so the page is read once.
    page = net.get_text(SOURCE_URL, encoding="utf-8")
    # A challenged response is either the JavaScript challenge bootstrap or an
    # empty body; neither is the lifecycle table, and neither becomes a snapshot.
    if (not page.strip() or "awsWafCookieDomainList" in page or "challenge-container" in page
            or "<table" not in page):
        raise ValueError(f"The Check Point policy page did not serve the lifecycle table "
                         f"(empty or WAF-challenged response): {SOURCE_URL}; retry the refresh "
                         f"later")
    fresh, excluded = parse_trains(page)
    releases, kept = combine_releases(fresh, committed)
    report = report_for(releases, excluded, kept, checked)
    publish_record(record_for(releases, checked), report, root)
    rows = report["rows"]
    return (f"imported {len(releases)} Check Point release trains "
            f"({rows['trains']} from the current table); excluded {rows['excluded']} rows, "
            f"retained {rows['retained']} (data/{REPORT})")
