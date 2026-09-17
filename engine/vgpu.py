"""NVIDIA vGPU software branch lifecycle, from the vendor's own branch tables.

Source: ``https://docs.nvidia.com/vgpu/index.html``, fetched as its Markdown
mirror (``.../index.html.md``), which renders the same tables as pipe rows. The
page's "Active vGPU Software Releases" and "Older vGPU Software Releases"
tables carry one row per driver branch: the vGPU release, the branch (R580...),
the branch type the vendor's lifecycle policy defines (Long-Term Support,
Production, or the EOL variants), the latest release in the branch, and the
month-precision release and EOL dates.

The vendor publishes no day anywhere, so per AGENTS.md rule 4 every milestone
is stored as ``YYYY-MM`` — the shape the schema admits beside full ISO days and
that is never padded with a fabricated ``-01``. A table's "Release Date" belongs
to the *latest release in the branch*, not to the branch's first release, so it
is kept as the row's own cell and never mapped onto ``ga``. Nothing is derived
from the published branch policy either; every stored milestone is a value the
vendor's row states.

One product (``nvidia-vgpu``), one release per driver branch major (``19``).
The identity is the branch, never the latest release in it (``19.1``), which
changes whenever the vendor ships a patch, so a permalink survives that. Each
row's cells are kept verbatim under the release's ``upstream``, so the human
pages show exactly what the vendor published and validation re-derives every
milestone from them offline.
"""
import json
import re
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from . import net, sources
from .importer import ROOT, dump

# The registry owns the id and the page: a record's provenance must name a
# source this checkout installs, and the site links the page a reader opens.
VERIFIER = sources.source("import-vgpu").verifier
SOURCE_URL = sources.NVIDIA_VGPU_DOCS
# The same page, rendered as the Markdown whose tables the refresh parses.
MARKDOWN_URL = SOURCE_URL + ".md"
REPORT = sources.source("import-vgpu").report
RECORD_SCHEMA = "https://zarguell.github.io/eoltracker/v1/schema/product.json"
PRODUCT_ID = "nvidia-vgpu"
PRODUCT_NAME = "NVIDIA vGPU"
UPSTREAM_CATEGORY = "server-app"

# The two branch tables, exactly as the vendor heads them.
ACTIVE = "Active vGPU Software Releases"
OLDER = "Older vGPU Software Releases"
BRANCH_TABLES = (ACTIVE, OLDER)
# The columns both tables declare. A reshaped header set refuses the parse
# rather than letting a column be read under the wrong name.
HEADERS = ("vGPU Software Release", "Driver Branch", "vGPU Branch Type",
           "Latest Release in Branch", "Release Date", "EOL Date")
# The branch types the vendor's lifecycle policy defines. A type outside this
# set is a policy change to review before publishing, never something to guess.
BRANCH_TYPES = frozenset({"long-term support", "production", "eol production",
                          "eol long-term support", "eol"})
MONTH_NAMES = (("january", "jan"), ("february", "feb"), ("march", "mar"), ("april", "apr"),
               ("may", "may"), ("june", "jun"), ("july", "jul"), ("august", "aug"),
               ("september", "sep", "sept"), ("october", "oct"), ("november", "nov"),
               ("december", "dec"))
MONTHS = {name: number for number, names in enumerate(MONTH_NAMES, start=1) for name in names}
# A cell that states no date. None of these is a date, and none becomes one.
NO_DATE = {"", "-", "—", "n/a", "na", "tbd", "tba", "unknown"}


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _normalized(text):
    """Fold a header or value for comparison: case and punctuation removed."""
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def month_value(text, where):
    """``July 2028`` -> ``2028-07``; anything else is a parse failure, not a guess.

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


def _cells(line):
    """One Markdown table row -> cell texts, with links reduced to their text.

    A cell may carry a link, including one redirected through a mail scanner:
    the text is what the vendor states, so the href is never read. A footnote
    marker is a link whose text is its own number; it qualifies the row, so it
    is dropped rather than left glued to the value it annotates
    (``EOL[1](...)`` is the branch type EOL).
    """
    cells = re.sub(r"\[\d+\]\([^)]*\)", "", line.strip().strip("|"))
    return [re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", cell).strip() for cell in cells.split("|")]


def _separator(cells):
    """True for a Markdown table's alignment row."""
    return bool(cells) and all(re.fullmatch(r":?-{1,}:?", cell) for cell in cells)


def _cell(cells, header):
    """One column of a parsed row, matched by normalized header text."""
    wanted = _normalized(header)
    for key, value in cells.items():
        if _normalized(key) == wanted:
            return value
    raise ValueError(f"vGPU row without the {header!r} column")


def _tables(markdown):
    """The two branch tables, header-matched; a missing or reshaped table fails."""
    lines = markdown.splitlines()
    tables = {}
    for index, line in enumerate(lines):
        if not line.startswith("#### "):
            continue
        heading = line[5:].strip()
        if heading not in BRANCH_TABLES:
            continue
        if heading in tables:
            raise ValueError(f"Duplicate vGPU branch table: {heading}")
        header, rows = None, []
        for row in lines[index + 1:]:
            if not row.strip():
                continue
            if not row.strip().startswith("|"):
                break
            cells = _cells(row)
            if _separator(cells):
                continue
            if header is None:
                if tuple(_normalized(cell) for cell in cells) != tuple(map(_normalized, HEADERS)):
                    raise ValueError(f"Unexpected vGPU table headers in {heading!r}: {cells}")
                header = cells
                continue
            if len(cells) != len(header):
                raise ValueError(f"{heading} row has {len(cells)} cells for {len(header)} "
                                 f"columns: {cells[0]!r}")
            rows.append(dict(zip(header, cells)))
        tables[heading] = rows
    for heading in BRANCH_TABLES:
        if heading not in tables:
            raise ValueError(f"Missing vGPU branch table: {heading}")
    return tables


def _branch_type(cell, where):
    """The vendor's branch type, checked against the policy's vocabulary."""
    text = re.sub(r"\s+", " ", cell).strip().lower()
    if text not in BRANCH_TYPES:
        raise ValueError(f"{where}: unknown vGPU branch type {cell!r}")
    return text


def _release(release_id, row, heading):
    """One published release, derived from the vendor's own cells."""
    cells = {header: _cell(row, header) for header in HEADERS}
    where = f"vGPU {cells['vGPU Software Release']!r}"
    _branch_type(cells["vGPU Branch Type"], where)
    return {
        "id": release_id,
        "name": cells["vGPU Software Release"],
        "milestones": {"ga": None, "eos": None, "eossec": None,
                       "eol": month_value(cells["EOL Date"], where)},
        "upstream": {"name": cells["Latest Release in Branch"], "cells": cells, "table": heading},
    }


def parse_branches(markdown):
    """Every branch row -> ``(releases, exclusions)``; no row is ever dropped.

    A row that identifies its branch becomes a release. A row the parser cannot
    place — no branch number at all, or a second row claiming a branch already
    seen — is reported with the reason instead, so the accounting adds up. A row
    that states no EOL is still published, with a null milestone: an unannounced
    deadline stays absent.
    """
    releases, excluded, seen = [], [], set()
    for heading, rows in _tables(markdown).items():
        for row in rows:
            name = _cell(row, "vGPU Software Release")
            number = re.search(r"(\d+)$", name)
            if number is None:
                excluded.append({"table": heading, "row": name,
                                 "reason": "no branch number in the release name"})
                continue
            release_id = number.group(1)
            if release_id in seen:
                excluded.append({"table": heading, "row": name,
                                 "reason": f"duplicate branch row for release {release_id!r}"})
                continue
            seen.add(release_id)
            releases.append(_release(release_id, row, heading))
    if not releases:
        raise ValueError("The vGPU branch tables produced no releases")
    return _ordered(releases), excluded


def _ordered(releases):
    """Newest branch first, as the vendor's own tables list them."""
    return sorted(releases, key=lambda release: -int(release["id"]))


def retained(release):
    """A committed release the current tables no longer state, marked as such.

    The row is republished from its own stored cells, so retention can never
    introduce a date the vendor did not publish; the marker says only that the
    current table lacks the row. Absence from a table is not an end of life.
    """
    return {**release, "upstream": {**release["upstream"], "in_source": False}}


def combine_releases(fresh, committed):
    """The complete branch snapshot: this fetch's rows plus retained history.

    A published branch the vendor's current tables no longer state keeps its
    record rather than disappearing from the catalog, exactly as a source row
    dropped from a table is not thereby an end of life.
    """
    if committed is None:
        return _ordered(fresh), []
    ids = {release["id"] for release in fresh}
    kept = [retained(release) for release in committed["releases"] if release["id"] not in ids]
    return (_ordered(fresh + kept),
            [{"id": release["id"], "name": release["name"],
              "reason": "the current vGPU branch tables do not state this branch; "
                        "the committed row and its dates are retained"} for release in kept])


def validate_record(record):
    """Rebuild every stored release from its own published cells, offline.

    Offline, a record's cells are the whole evidence: the milestone, the branch
    type and the identity are re-derived from them, so a file whose dates or
    branch no longer follow the row it stores is never published.
    """
    if record["provenance"]["verifier"] != VERIFIER:
        raise ValueError("Invalid NVIDIA vGPU source identity")
    seen = set()
    for release in record["releases"]:
        cells = release.get("upstream", {}).get("cells")
        if not isinstance(cells, dict) or not cells:
            raise ValueError(f"NVIDIA vGPU release without source cells: {release['id']}")
        name = _cell(cells, "vGPU Software Release")
        number = re.search(r"(\d+)$", name)
        if release["id"] in seen or number is None or number.group(1) != release["id"]:
            raise ValueError(f"{record['id']}: release {release['id']} does not name its own "
                             f"branch: {name!r}")
        seen.add(release["id"])
        expected = _release(release["id"], cells, release["upstream"].get("table", ""))
        if release["name"] != expected["name"] or release["milestones"] != expected["milestones"]:
            raise ValueError(f"{record['id']}: release {release['id']} contradicts its stored cells")
        if release["upstream"].get("name") != expected["upstream"]["name"]:
            raise ValueError(f"{record['id']}: release {release['id']} contradicts the published "
                             f"latest release in its branch")
        if release["upstream"].get("in_source") not in (None, False):
            raise ValueError(f"{record['id']}: release {release['id']} carries an invalid "
                             f"retention marker")


def record_for(releases, checked):
    """The published ``nvidia-vgpu`` record for one complete branch snapshot."""
    return {
        "$schema": RECORD_SCHEMA,
        "id": PRODUCT_ID,
        "name": PRODUCT_NAME,
        "category": "software",
        "upstream_category": UPSTREAM_CATEGORY,
        # No identifier is published: the vendor documents branches and driver
        # builds, never a CPE for this product, and an invented one would be a
        # claim the source does not make.
        "identifiers": [],
        "labels": {},
        "links": {"html": SOURCE_URL},
        "releases": releases,
        "provenance": {"source_url": SOURCE_URL, "verifier": VERIFIER,
                       "last_checked": checked, "upstream_modified": None},
    }


def report_for(releases, excluded, kept, checked):
    """The per-row accounting this source publishes beside its record.

    ``rows`` counts what this fetch saw: the table totals cover the rows the
    current page stated, and the retained snapshot rows are accounted
    separately, so the numbers read as one observation of one source.
    """
    retained = {entry["id"] for entry in kept}
    fresh = [release for release in releases if release["id"] not in retained]
    tables = {heading: sum(1 for release in fresh if release["upstream"].get("table") == heading)
              for heading in BRANCH_TABLES}
    return {
        "source_url": SOURCE_URL, "markdown_url": MARKDOWN_URL, "verifier": VERIFIER,
        "checked_at": checked,
        "record_scope": ("NVIDIA vGPU software driver branches: one software record with one "
                         "release per branch major, from the vendor's active and older branch "
                         "tables, at the month precision those tables state"),
        "rows": {"seen": len(fresh) + len(excluded), "published": len(releases),
                 "active": tables[ACTIVE], "older": tables[OLDER],
                 "retained": len(kept), "excluded": len(excluded)},
        "excluded": excluded,
        "retained": kept,
        "total_records": 1,
        "limitations": [
            "Month precision only: the vendor's tables state months, so every milestone is "
            "stored as YYYY-MM and no day is ever invented.",
            "ga is absent: a table's Release Date belongs to the latest release in the branch, "
            "not to the branch's first release, so it is kept as a cell and never mapped to GA.",
            "No date is derived from the published branch policy (Production 1 year, LTS 3 "
            "years); stored milestones are the vendor's own row values.",
            "A branch the current tables no longer state is retained from the committed "
            "snapshot and marked upstream.in_source false; a dropped row is not an end of life.",
            "Branch type and the latest release in branch are carried as the vendor's cells; "
            "neither is a support claim of its own.",
        ],
    }


def committed_record(root):
    """The committed ``nvidia-vgpu`` record, refusing one this source cannot own.

    A file under this product's name carrying another source's verifier is an
    ownership collision: republishing it would overwrite a record this pipeline
    did not produce. A committed record that no longer re-derives from its own
    stored cells is equally unpublishable — merging it would carry a claim the
    vendor's table does not state — so both abort before anything is written.
    """
    path = root / "products" / (PRODUCT_ID + ".json")
    if not path.exists():
        return None
    record = json.loads(path.read_text(encoding="utf-8"))
    if record["provenance"]["verifier"] != VERIFIER:
        raise ValueError(f"NVIDIA vGPU source ownership collision: {PRODUCT_ID} carries "
                         f"{record['provenance']['verifier']}, not {VERIFIER}")
    validate_record(record)
    return record


def publish_record(record, report, root):
    """Stage the record beside the committed catalog, validate, then replace it.

    Only this source's own file is written. Every committed record is copied
    into the staged catalog and validated there, so a run that would publish an
    inconsistent catalog writes nothing at all — while a record this source does
    not own is left byte-for-byte as it was found. A record whose content is
    unchanged keeps its previous revision time, so a quiet source republishes
    byte-identical files.
    """
    from .validation import validate_data

    products = root / "products"
    if not (root / "manifest.json").exists() or not products.is_dir():
        raise ValueError(f"Not a catalog directory: {root}")
    manifest = (root / "manifest.json").read_text(encoding="utf-8")
    target = products / (record["id"] + ".json")
    if target.exists():
        old = json.loads(target.read_text(encoding="utf-8"))
        unchanged = {**record, "provenance": {**record["provenance"],
                                             "last_checked": old["provenance"]["last_checked"]}}
        if old == unchanged:
            record = unchanged
    with tempfile.TemporaryDirectory(prefix="eoltracker-vgpu-") as temp:
        staged = Path(temp)
        shutil.copytree(products, staged / "products")
        dump(staged / "products" / (record["id"] + ".json"), record)
        (staged / "manifest.json").write_text(manifest, encoding="utf-8")
        if "hardware_count" in json.loads(manifest):
            # The manifest counts the hardware catalog too, so the staged
            # catalog carries it rather than claiming an empty one validates.
            shutil.copytree(root / "hardware", staged / "hardware")
        dump(staged / REPORT, report)
        validate_data(staged)
        dump(target, record)
        dump(root / REPORT, report)
    return record


def import_vgpu(directory=None):
    """Fetch the branch tables and publish the ``nvidia-vgpu`` record.

    Complete-or-nothing: the fetched snapshot is combined with the branches the
    source no longer states, staged beside the committed catalog and validated
    there before anything is written. A parse failure, a header change or an
    inconsistent catalog leaves every committed file untouched.
    """
    root = Path(directory) if directory is not None else ROOT / "data"
    # The committed ownership check runs before the fetch: a file this source
    # cannot publish aborts the run without a network call at all.
    committed = committed_record(root)
    checked = _now()
    fresh, excluded = parse_branches(net.get_text(MARKDOWN_URL))
    releases, kept = combine_releases(fresh, committed)
    report = report_for(releases, excluded, kept, checked)
    publish_record(record_for(releases, checked), report, root)
    rows = report["rows"]
    return (f"imported {len(releases)} NVIDIA vGPU branch releases "
            f"({rows['active']} active from the current tables); excluded {rows['excluded']} rows, "
            f"retained {rows['retained']} (data/{REPORT})")
