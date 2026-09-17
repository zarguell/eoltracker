"""Ceph community release branch lifecycle, from the project's own release metadata.

Sources: the published page ``https://docs.ceph.com/en/latest/releases/`` and
the two files that page is built from — the data file
``doc/releases/releases.yml`` and the page source ``doc/releases/index.rst``,
both fetched from the ``ceph/ceph`` repository at ``main``.

The page is a *projection* of the data file: the vendor's own Sphinx extension
(``doc/_ext/ceph_releases.py``) reads ``releases.yml`` and renders one table per
grouping, so reading the file removes the whole class of "the page moved a row"
bugs, exactly as ``engine.vgpu`` prefers the vendor's Markdown mirror. The page
source is read beside it because the branch *inventory* lives there: its toctree
names every branch the project documents, including three retired ones
(Argonaut, Bobtail, Cuttlefish) that ``releases.yml`` carries no lifecycle
record for at all. Without it those three would be an unchecked claim in a
comment instead of an accounted source row.

**Estimated and final end of life are different facts, and the vendor says so.**
The extension heads the column ``"End of life (estimated)"`` for the current
table and ``"End of life"`` for the archived one (``ceph_releases.py:56``), the
current table prints ``target_eol`` (``:109``), and the archived table prints
``actual_eol`` (``:111``) and skips any branch lacking one (``:72``). So
``target_eol`` is an estimate the project may still move, and ``actual_eol`` is
the date the branch actually ended. Only ``actual_eol`` becomes a normalized
milestone; ``target_eol`` is republished verbatim in the vendor's own words and
never reaches ``milestones.eol``. A current branch therefore publishes
``eol: null`` — the honest value — while its estimate stays visible beside it.

No date here is derived from anything but the source's own keys. Ceph's prose
release-cycle document states a stable series lives "approximately 24 months",
and that is deliberately *not* implemented: it is a policy approximation the
same document says "may vary", and rule 2 forbids turning a cadence into a
deadline.

One product (``ceph``), one release per stable branch series (``20.2``), never
per point release: the identity must survive ``20.2.4`` shipping, so a permalink
to a branch keeps resolving. Each release's cells are the vendor's own columns,
kept verbatim under ``upstream.cells``, and ``upstream.table`` names the table
the vendor files the branch under (``Active Releases`` or ``Archived
Releases``) — the source's own statement about whether the branch has ended,
rather than an inference from its dates. Validation re-derives every milestone
and that table from the stored cells offline.
"""
import re
import json
import shutil
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path

import yaml

from . import net, sources
from .importer import ROOT, dump

# The registry owns the id and the pages: a record's provenance must name a
# source this checkout installs, and the report must name the URLs it read.
VERIFIER = sources.source("import-ceph").verifier
SOURCE_URL = sources.CEPH_RELEASES
DATA_URL = sources.CEPH_RELEASES_DATA
# The page source sits beside the data file it names (`.. ceph_releases:: releases.yml`),
# so it is derived from the registered URL rather than restated as a second
# constant that could drift from it — the same way engine.vgpu composes its
# Markdown URL from the registry's page. The registry registers the two URLs a
# reader opens; this is the path the fetcher reads them from.
INDEX_URL = DATA_URL.rsplit("/", 1)[0] + "/index.rst"
REPORT = sources.source("import-ceph").report
RECORD_SCHEMA = "https://zarguell.github.io/eoltracker/v1/schema/product.json"
PRODUCT_ID = "ceph"
PRODUCT_NAME = "Ceph"
UPSTREAM_CATEGORY = "server-app"

# The columns the vendor's own tables declare, in the order they render them.
# The estimate and the final date are separate columns because the source
# distinguishes them; a column the row has no value for carries the vendor's own
# placeholder for an absent value ("--"), so every release states the same
# columns in the same order and a table of rows stays aligned.
NAME = "Name"
INITIAL = "Initial release"
LATEST = "Latest"
ESTIMATED = "End of life (estimated)"
FINAL = "End of life"
CELLS = (NAME, INITIAL, LATEST, ESTIMATED, FINAL)
# The placeholder the vendor's extension prints for a value a row does not
# state (`info.get('actual_eol', '--')`). It is the source's own word for
# "absent", never a date and never normalized into one.
NONE_CELL = "--"
# A four-component version states no series this module could name, and a
# branch is always identified by its stable series (x.2), never by a build.
SERIES_COMPONENTS = 2
# A branch the page's own index names as stable-series `vX.Y.*`.
INDEX_ROW = re.compile(r"^\s+(?P<label>[A-Za-z][A-Za-z ]*?) \(v(?P<series>[\d.]+)\.\*\) <(?P<slug>[a-z]+)>\s*$")


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _value(text, where):
    """One date the source states, as ``YYYY-MM-DD``; anything else fails.

    ``yaml`` already resolves an unquoted ``2027-06-01`` to a ``date``, and a
    quoted one is the same date written differently. Either way the stored value
    is the day the source published, and a value that is neither is a parse
    failure rather than something to guess at.
    """
    if isinstance(text, datetime):
        text = text.date()
    if isinstance(text, date):
        return text.isoformat()
    if isinstance(text, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", text.strip()):
        return date.fromisoformat(text.strip()).isoformat()
    raise ValueError(f"{where}: unrecognized lifecycle date {text!r}")


def series_of(version, where):
    """``20.2.4`` -> ``20.2``: the stable series a branch is identified by.

    A two-component version is already a series (``0.94``), which is how the
    vendor writes a branch whose first stable build it documents that way.
    """
    parts = str(version).strip().split(".")
    if not all(part.isdigit() for part in parts) or len(parts) < SERIES_COMPONENTS:
        raise ValueError(f"{where}: unexpected release version {version!r}")
    if len(parts) == SERIES_COMPONENTS:
        return str(version).strip()
    if len(parts) == SERIES_COMPONENTS + 1:
        return ".".join(parts[:SERIES_COMPONENTS])
    raise ValueError(f"{where}: release version {version!r} names no stable series")


def _series_key(series):
    """Sort key for one series, newest branch first."""
    return tuple(-int(part) for part in series.split("."))


def _payload(text):
    """The parsed release metadata; a document of the wrong shape fails here."""
    try:
        payload = yaml.safe_load(text)
    except yaml.YAMLError as error:
        raise ValueError(f"Ceph release metadata is not valid YAML: {error}") from None
    if not isinstance(payload, dict) or not isinstance(payload.get("releases"), dict):
        raise ValueError("Ceph release metadata declares no `releases` mapping")
    return payload


def _points(branch, info):
    """The branch's point releases, ordered as the vendor orders them.

    The extension sorts on the release date and then the version's numeric
    components to find a branch's first and latest release, so the same rule is
    applied here rather than trusting the file's list order, which the file's
    own header documents as a convention for its Gantt chart.
    """
    if not isinstance(info, dict):
        raise ValueError(f"Ceph branch {branch!r} is not a mapping")
    entries = info.get("releases")
    if not isinstance(entries, list) or not entries:
        raise ValueError(f"Ceph branch {branch!r} states no releases")
    points = []
    for entry in entries:
        if not isinstance(entry, dict) or not entry.get("version"):
            raise ValueError(f"Ceph branch {branch!r} has a release without a version")
        version = str(entry["version"]).strip()
        points.append((version, _value(entry.get("released"), f"Ceph {branch} {version}")))
    return sorted(points, key=lambda point: [point[1]] + [int(part) for part in point[0].split(".")])


def _eol(info, key, branch):
    """One branch-level end-of-life key, or None when the source omits it."""
    stated = info.get(key)
    return None if stated is None else _value(stated, f"Ceph branch {branch!r} {key}")


def _release(branch, info):
    """One published branch, derived from the vendor's own record."""
    points = _points(branch, info)
    oldest, newest = points[0], points[-1]
    series = series_of(newest[0], f"Ceph branch {branch!r}")
    estimated = _eol(info, "target_eol", branch)
    final = _eol(info, "actual_eol", branch)
    cells = {
        NAME: branch.title(),
        INITIAL: oldest[1],
        LATEST: newest[0],
        ESTIMATED: estimated or NONE_CELL,
        FINAL: final or NONE_CELL,
    }
    return {
        "id": series,
        "name": branch.title(),
        # Only a realized end of life is a milestone. `target_eol` is the
        # project's estimate and stays in the cell above, so a branch that has
        # not ended publishes `eol: null` rather than a deadline it may move.
        "milestones": {"ga": oldest[1], "eos": None, "eossec": None, "eol": final},
        "upstream": {"name": newest[0], "cells": cells, "table": table_for(final)},
    }


# The two tables the vendor's own extension renders, headed exactly as it heads
# them. A branch appears in the archived table once it states an actual end of
# life and in the current table otherwise, so the table a row belongs to is the
# source's own statement about the branch, not an inference from its dates.
CURRENT_TABLE = "Active Releases"
ARCHIVED_TABLE = "Archived Releases"


def table_for(final):
    """The vendor's table a branch with this end-of-life statement belongs to."""
    return ARCHIVED_TABLE if final else CURRENT_TABLE


def _documented(text):
    """The branch index the published page renders: slug -> (label, series)."""
    documented = {}
    for line in text.splitlines():
        match = INDEX_ROW.match(line)
        if match:
            documented[match.group("slug")] = (match.group("label").strip(), match.group("series"))
    if not documented:
        raise ValueError(f"Ceph release index states no branch: {INDEX_URL}")
    return documented


def parse_releases(data_text, index_text):
    """Every source row -> ``(releases, excluded)``; no row is ever dropped.

    Two inventories are read, and the accounting covers both. The metadata file
    yields one release per named branch; its ``development`` section yields no
    release, because those are the x.0.z and x.1.z development builds and
    release candidates the project's own release-cycle document separates from
    stable releases, not branches anyone deploys. The page's index yields the
    branches it documents, and a branch named there that the metadata states no
    lifecycle for is reported rather than silently absent — it has no published
    end-of-life date, and an absent date is not a date.
    """
    payload = _payload(data_text)
    releases, excluded, seen = [], [], set()
    for branch, info in payload["releases"].items():
        release = _release(branch, info)
        if release["id"] in seen:
            raise ValueError(f"Ceph branches claim the same series {release['id']!r}: "
                             f"{branch!r} and another")
        seen.add(release["id"])
        releases.append(release)
    if not releases:
        raise ValueError("The Ceph release metadata produced no branches")
    for entry in payload.get("development", {}).get("releases", []) or []:
        version = str(entry.get("version", "")).strip() if isinstance(entry, dict) else ""
        excluded.append({
            "row": version or "development release without a version",
            "reason": "development version (x.0.z / x.1.z) or release candidate, not a stable "
                      "release branch; the project's release-cycle document keeps these separate",
        })
    documented = _documented(index_text)
    known = {branch for branch in payload["releases"]}
    for slug, (label, series) in documented.items():
        if slug in known:
            continue
        excluded.append({
            "row": f"{label} ({series})",
            "reason": f"named in the release page's branch index ({INDEX_URL}) but the release "
                      f"metadata states no lifecycle record for it, so it publishes no date",
        })
    return _ordered(releases), excluded


def _ordered(releases):
    """Newest branch first, the order the vendor's own metadata lists them in."""
    return sorted(releases, key=lambda release: _series_key(release["id"]))


def retained(release):
    """A committed branch the current metadata no longer states, marked as such.

    Republished from its own stored cells, so retention can never introduce a
    date the project did not publish; the marker says only that the current
    metadata lacks the branch. Absence from the file is not an end of life.
    """
    return {**release, "upstream": {**release["upstream"], "in_source": False}}


def combine_releases(fresh, committed):
    """The complete branch snapshot: this fetch's rows plus retained history."""
    if committed is None:
        return _ordered(fresh), []
    ids = {release["id"] for release in fresh}
    kept = [retained(release) for release in committed["releases"] if release["id"] not in ids]
    return (_ordered(fresh + kept),
            [{"id": release["id"], "name": release["name"],
              "reason": "the current Ceph release metadata does not state this branch; the "
                        "committed row and its dates are retained"} for release in kept])


def _cells(release, where):
    """One stored release's cells, refused unless they are the declared columns."""
    cells = release.get("upstream", {}).get("cells")
    if not isinstance(cells, dict) or tuple(cells) != CELLS:
        raise ValueError(f"{where}: release {release['id']} does not carry the vendor's "
                         f"declared columns {CELLS}")
    return cells


def validate_record(record):
    """Rebuild every stored branch from its own published cells, offline.

    A record's cells are the whole evidence, so the identity, the initial
    release and the end of life are re-derived from them: a file whose dates no
    longer follow the row it stores is never published.
    """
    if record["provenance"]["verifier"] != VERIFIER:
        raise ValueError("Invalid Ceph source identity")
    seen = set()
    for release in record["releases"]:
        cells = _cells(release, record["id"])
        where = f"{record['id']}: release {release['id']}"
        if release["id"] in seen:
            raise ValueError(f"Duplicate Ceph branch series: {where}")
        seen.add(release["id"])
        if series_of(cells[LATEST], where) != release["id"]:
            raise ValueError(f"{where} does not name its own series: {cells[LATEST]!r}")
        if release["name"] != cells[NAME]:
            raise ValueError(f"{where} does not name the branch it stores: {cells[NAME]!r}")
        if release["milestones"]["ga"] != cells[INITIAL]:
            raise ValueError(f"{where} ga contradicts its stored initial release")
        # The estimate is not a milestone; the final date is, and a row that
        # states neither publishes no end of life at all.
        expected = None if cells[FINAL] == NONE_CELL else _value(cells[FINAL], where)
        if release["milestones"]["eol"] != expected:
            raise ValueError(f"{where} eol contradicts its stored cells")
        if release["milestones"]["eos"] is not None or release["milestones"]["eossec"] is not None:
            raise ValueError(f"{where} claims a milestone the Ceph source does not publish")
        if release["upstream"].get("name") != cells[LATEST]:
            raise ValueError(f"{where} contradicts the latest release it states")
        if release["upstream"].get("table") != table_for(expected):
            raise ValueError(f"{where} disagrees with the table its own cells put it in")
        if release["upstream"].get("in_source") not in (None, False):
            raise ValueError(f"{where} carries an invalid retention marker")


def record_for(releases, checked):
    """The published ``ceph`` record for one complete branch snapshot."""
    return {
        "$schema": RECORD_SCHEMA,
        "id": PRODUCT_ID,
        "name": PRODUCT_NAME,
        "category": "software",
        "upstream_category": UPSTREAM_CATEGORY,
        # The Ceph project publishes no CPE or other identifier for its release
        # branches, and an invented one would be a claim the source never makes.
        "identifiers": [],
        "labels": {},
        "links": {"html": SOURCE_URL},
        "releases": releases,
        "provenance": {"source_url": SOURCE_URL, "verifier": VERIFIER,
                       "last_checked": checked, "upstream_modified": None},
    }


def estimated_only(releases):
    """The branches whose only end-of-life statement is an estimate.

    Published so a reader can see, without parsing any record, which branches
    carry no normalized deadline and why — and so no one later mistakes the
    absence of ``eol`` for missing data.
    """
    return [{"id": release["id"], "name": release["name"],
             "estimated_eol": release["upstream"]["cells"][ESTIMATED],
             "reason": "the source states this branch's end of life as an estimate only; it is "
                       "retained as the vendor's own cell and is not normalized into "
                       "milestones.eol, and it produces no feed event"}
            for release in releases
            if release["milestones"]["eol"] is None]


def report_for(releases, excluded, kept, checked):
    """The per-row accounting this source publishes beside its record.

    ``rows.seen`` counts every row the two sources of *this fetch* stated, so the
    identity ``seen == (published - retained) + excluded`` holds: a development
    build and a branch the metadata carries no record for are both accounted for,
    not dropped. ``published`` is the complete snapshot, which also carries the
    branches retained from the committed record and counted separately.
    """
    retained_ids = {entry["id"] for entry in kept}
    fresh = [release for release in releases if release["id"] not in retained_ids]
    estimated = estimated_only(releases)
    return {
        "source_url": DATA_URL, "page_url": SOURCE_URL, "index_url": INDEX_URL,
        "verifier": VERIFIER, "checked_at": checked,
        "record_scope": ("Ceph community release branches: one software record with one release "
                         "per stable series (x.2), current and historical, from the Ceph "
                         "project's own release metadata at day precision"),
        "rows": {"seen": len(fresh) + len(excluded), "published": len(releases),
                 "active": sum(1 for release in fresh
                               if release["upstream"].get("table") == CURRENT_TABLE),
                 "archived": sum(1 for release in fresh
                                 if release["upstream"].get("table") == ARCHIVED_TABLE),
                 "retained": len(kept), "excluded": len(excluded)},
        "excluded": excluded,
        "retained": kept,
        "estimated_only": estimated,
        "total_records": 1,
        "limitations": [
            "The source distinguishes an estimated end of life (target_eol, the page's "
            "'End of life (estimated)' column) from a realized one (actual_eol, its "
            "'End of life' column). Only actual_eol is normalized into milestones.eol; an "
            "estimate is republished as the vendor's own cell and is never a deadline, so a "
            "current branch publishes eol: null and produces no feed event.",
            "No date is derived from Ceph's release cadence or from the 'approximately 24 "
            "months' lifetime its release-cycle document states; that document calls the "
            "lifetime an approximation that 'may vary', so it is prose and not modelled.",
            "eos and eossec are always null: Ceph publishes no end-of-sale and no separate "
            "security-support-end date for a branch.",
            "milestones.ga is the branch's initial stable release, the oldest point release "
            "the metadata states, which is the value the vendor's own table shows in its "
            "'Initial release' column.",
            "Point releases are not records: one release per stable series so a permalink "
            "survives the next patch release. The latest point release is carried as a cell.",
            "The three branches the page's index names but the metadata states no lifecycle "
            "for (Argonaut, Bobtail, Cuttlefish) publish no date and are accounted as "
            "exclusions; they each have release notes but no end-of-life statement.",
            "Commercial downstream distributions (Red Hat Ceph Storage, SUSE Enterprise "
            "Storage, Canonical's Ceph offering, IBM Storage Ceph) are separate products with "
            "their own support-contract lifecycles and are deliberately not covered here.",
            "The source is the documentation tree of ceph/ceph at main, not a versioned API; "
            "the project publishes no rate limit for it.",
        ],
    }


def committed_record(root):
    """The committed ``ceph`` record, refusing one this source cannot own.

    A file under this product's name carrying another source's verifier is an
    ownership collision, and a committed record that no longer re-derives from
    its own cells carries a claim the source does not state; both abort before
    anything is written.
    """
    path = root / "products" / (PRODUCT_ID + ".json")
    if not path.exists():
        return None
    record = json.loads(path.read_text(encoding="utf-8"))
    if record["provenance"]["verifier"] != VERIFIER:
        raise ValueError(f"Ceph source ownership collision: {PRODUCT_ID} carries "
                         f"{record['provenance']['verifier']}, not {VERIFIER}")
    validate_record(record)
    return record


def publish_record(record, report, root):
    """Stage the record beside the committed catalog, validate, then replace it.

    Only this source's own file is written. Every committed record is copied
    into the staged catalog and validated there, so a run that would publish an
    inconsistent catalog writes nothing at all, while a record this source does
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
    with tempfile.TemporaryDirectory(prefix="eoltracker-ceph-") as temp:
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


def import_ceph(directory=None):
    """Fetch the Ceph release metadata and publish the ``ceph`` record.

    Complete-or-nothing: the fetched snapshot is combined with the branches the
    source no longer states, staged beside the committed catalog and validated
    there before anything is written. A parse failure or an inconsistent catalog
    leaves every committed file untouched.
    """
    root = Path(directory) if directory is not None else ROOT / "data"
    # The committed ownership check runs before the fetch: a file this source
    # cannot publish aborts the run without a network call at all.
    committed = committed_record(root)
    checked = _now()
    fresh, excluded = parse_releases(net.get_text(DATA_URL), net.get_text(INDEX_URL))
    releases, kept = combine_releases(fresh, committed)
    report = report_for(releases, excluded, kept, checked)
    publish_record(record_for(releases, checked), report, root)
    rows = report["rows"]
    return (f"imported {len(releases)} Ceph release branches "
            f"({rows['active']} active of which {len(report['estimated_only'])} carry an "
            f"estimate only); excluded {rows['excluded']} rows, retained {rows['retained']} "
            f"(data/{REPORT})")
