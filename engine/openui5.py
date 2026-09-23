"""OpenUI5 numbered-branch lifecycle, from the project's own release documents.

Five official documents make this record, and each states a fact no other one
does:

* ``versionoverview.json`` (``https://sdk.openui5.org/versionoverview.json``)
  states every published numbered branch (``1.152.*`` down to ``1.22.*``), its
  maintenance status, its LTS flag and the project's own ``eom``/``eomm``/
  ``eocp`` cells — plus the exhaustive ``patches`` array, one row per published
  patch version with its EOCP cell and removal flag;
* ``version.json`` states the currently maintained branches and the latest
  patch version in each;
* the release feed the releases page renders (``OpenUI5ReleasesInfo``) states
  the release date of each currently maintained branch's latest patch;
* the releases page declares the column that date is published under, which is
  the one label this record maps;
* the maintenance policy states what EOM, EOL and EOCP mean and the support
  period of each release type.

What is published, and what is deliberately not, is the substance of this
module. Every numbered branch that the project published becomes one release,
identified by the branch (``1.152``) rather than by its newest patch, because
lifecycle is stated per branch and the patch identity changes with every patch.
``ga`` is published only where a source states it: the feed row for a branch
whose latest patch is the branch's own ``.0`` release dates that release, and so
the branch. For every other branch the feed's date belongs to a *patch* — it is
kept verbatim under ``upstream.current`` and is never promoted to the branch's
general availability.

The project's end-of-life vocabulary is not mapped onto this catalog's
milestones, because none of its three end columns is one:

* ``eom`` — end of *maintenance*: the policy says mid-term and long-term
  releases receive bug fixes until then, and that after it "only critical
  security patches are offered for a year, after which these versions reach
  their EOL date". It is neither the end of security support nor the terminal
  end of life, so it fills neither ``eossec`` nor ``eol``.
* ``eomm`` — the project's own maintenance marker, which the live rows often
  duplicate in ``eom`` and which carries no normalized meaning of its own.
* ``eocp`` — end of *cloud provisioning*: removal from the Akamai CDN a year
  after a patch is superseded, not a support deadline at all.

Every one of those cells is retained verbatim in the branch's ``upstream.cells``,
and every one of the 1038 patch rows is retained verbatim under its branch's
``upstream.patches``. No ``eos``, ``eossec`` or ``eol`` is published for any
branch: they stay ``null``, and ``validate_record`` refuses an offline record
that fills one, so a quarter can never be quietly turned into a deadline.

Quarters also stay quarters. The vendor publishes ``Q3/2026``, never a day or a
month, and the normalized schema carries a day or a month — so a quarter is
retained as the source's own text rather than converted, and no normalized
value is invented from it. The schema extension that would let quarter-precision
lifecycle be published is a deliberate, reviewed change this module leaves to
its reviewers.

The policy's support durations (Standard 6 weeks, MTS 9 months, LTS 15 months)
are stored verbatim in the import report and are not derived from either: the
project's rows carry explicit extensions the generic duration contradicts
(1.71 and 1.108 run to ``Q4/2030``), the branch catalog does not label which
non-LTS branch is MTS and which is Standard, and the one-step derivation the
schema expresses cannot carry the policy's two-step "EOM then one more year"
rule.

One product (``openui5``), one release per published numbered branch. Nothing
is read behind a login and nothing is inferred from release cadence.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

from . import net, sources, transaction
from .importer import ROOT

# The registry owns the id and the pages: a record's provenance must name a
# source this checkout installs, and the report must name the pages it read.
SOURCE = sources.source("import-openui5")
VERIFIER = SOURCE.verifier
RELEASE_PAGE, FEED_URL, VERSION_OVERVIEW_URL, VERSION_URL, POLICY_URL = (
    page.url for page in SOURCE.pages)
REPORT = SOURCE.report
RECORD_SCHEMA = "https://zarguell.github.io/eoltracker/v1/schema/product.json"
PRODUCT_ID = "openui5"
PRODUCT_NAME = "OpenUI5"
UPSTREAM_CATEGORY = "framework"

# The documents' own array and table names, so a stored revision names where it
# was read from rather than restating a URL a reader would have to guess at.
VERSIONS_TABLE = "versionoverview.json versions"
PATCHES_TABLE = "versionoverview.json patches"
CURRENT_TABLE = "version.json and OpenUI5ReleasesInfo"

# The declared shape of each source row. A row that gains, loses or renames a
# field is a source reshape to review before publishing, so it refuses here
# instead of having a column silently read under the wrong name.
VERSION_ROW_KEYS = ("version", "support", "lts", "eom", "eomm", "eocp")
# The rows that state no EOCP cell at all: the two the project marks Skipped,
# and the loader's wildcard default row.
NO_EOCP_ROW_KEYS = ("version", "support", "lts", "eom", "eomm")
PATCH_ROW_KEYS = ("version", "eocp", "removed", "hidden", "extended_eocp")
PATCH_ROW_REQUIRED = ("version", "eocp")
CURRENT_ROW_KEYS = ("version", "support", "lts")
FEED_ROW_KEYS = ("version", "release_date", "eom", "url_download_runtime",
                 "url_download_sdk", "url_download_mobile", "url_demokit",
                 "url_releasenotes")

# A branch row's identity: ``1.152.*`` names the branch ``1.152``. The
# wildcard row is the overview page's default maintenance metadata for the
# loader, not a release branch, and is excluded as such.
BRANCH_ROW = re.compile(r"(?P<branch>\d+\.\d+)\.\*\Z")
WILDCARD_ROW = "*"
PATCH_VERSION = re.compile(r"\d+\.\d+\.\d+(?:-legacy-free)?\Z")
# The maintenance statuses the project publishes. Case and internal spacing are
# the only variation the live rows show (``Out of Maintenance`` and
# ``Out of maintenance`` both appear), so status is compared folded and stored
# as the row wrote it; a new status refuses rather than being guessed at.
SUPPORT = frozenset({"maintenance", "out of maintenance", "skipped"})
SKIPPED = "skipped"
# A lifecycle cell's only forms: an empty cell states nothing, the project's
# own "To Be Determined" placeholder states that it has not decided, and
# everything else is a quarter, optionally prefixed with the maintenance type
# the row marks (``Long-term Maintenance, Q4/2030``). All are kept verbatim.
QUARTER = re.compile(r"(?:Long-[Tt]erm Maintenance, )?Q[1-4]/\d{4}\Z")
UNDETERMINED = "To Be Determined"
# The feed states its release dates as ``31.08.2026``. That is the only form it
# uses, and an ISO day arriving here would be a different document shape.
FEED_DATE = re.compile(r"(?P<day>\d{2})\.(?P<month>\d{2})\.(?P<year>\d{4})\Z")

# The maintenance policy's sentences this record's withholding of ``eol`` rests
# on, stored verbatim with the page. They are required word for word: a
# reworded policy refuses the import rather than letting a reader assume the
# project still states the same EOM/EOL/EOCP relationship. The policy renders
# markup-escaped parentheses (``\\(EOL\\)``), which the comparison folds away;
# the quote itself is the sentence as the page renders it.
SECURITY_QUOTE = ("All OpenUI5 versions receive critical security fixes until the "
                  "version\u2019s end of life (EOL) date.")
EOM_QUOTE = ("Mid-term and long-term maintenance releases also receive bug fixes until their "
             "end of maintenance (EOM) date (for standard releases, bug fixes are included in "
             "the next OpenUI5 version).")
EOL_RULE_QUOTE = ("After the EOM date, only critical security patches are offered for a year, "
                  "after which these versions reach their EOL date.")
EOCP_QUOTE = ("OpenUI5 versions reach End of Cloud Provisioning (EOCP) and are removed from the "
              "Akamai content delivery network approximately one year after becoming outdated.")
QUOTES = {"security": SECURITY_QUOTE, "eom": EOM_QUOTE, "eol_rule": EOL_RULE_QUOTE,
          "eocp": EOCP_QUOTE}
# The support-period table, matched by the columns the page declares.
POLICY_COLUMNS = ("Release Type", "Support Period", "Typical Release Cycle")
POLICY_TYPES = ("Standard", "Mid-Term Support (MTS)", "Long-Term Support (LTS)")
# The columns the releases page declares; its last one is the header the feed's
# stated day is read under, which is the only label this record maps.
RELEASE_COLUMNS = ("Version", "Download", "Documentation", "Release Date")
# The record's links: the pages a reader opens to check the record against its
# sources, keyed by what the site credits each with.
LINKS = {"html": RELEASE_PAGE, "release feed": FEED_URL,
         "version overview": VERSION_OVERVIEW_URL, "current versions": VERSION_URL,
         "maintenance policy": POLICY_URL}
# The column label the releases page prints for the date the feed publishes.
GA_LABEL = "Release Date"


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _folded(text):
    """Compare source text as the page means it: escapes and whitespace folded.

    The policy is rendered from escaped Markdown, so ``\\(``/``\\)`` and a
    typographic apostrophe appear around otherwise plain sentences. Folding
    those away is what lets the stored quote be the rendered sentence and the
    comparison still find it in the page.
    """
    text = text.replace("\u2019", "'")
    text = re.sub(r"\\([^A-Za-z0-9])", r"\1", text)
    return re.sub(r"\s+", " ", text).strip()


def _payload(text, where):
    """One document parsed as JSON; a body of the wrong shape fails here."""
    try:
        return json.loads(text)
    except ValueError as error:
        raise ValueError(f"{where}: response is not JSON: {error}") from None


def _row_keys(row, where, required, allowed):
    """One source row's declared fields, refused if the shape changed."""
    if not isinstance(row, dict):
        raise ValueError(f"{where}: source row is not an object: {row!r}")
    unknown = sorted(set(row) - set(allowed))
    if unknown:
        raise ValueError(f"{where}: unrecognized source fields {unknown}; the row states "
                         f"{sorted(allowed)} and a new field needs review before it is published")
    missing = sorted(set(required) - set(row))
    if missing:
        raise ValueError(f"{where}: source row is missing {missing}")
    return row


def support_value(value, where):
    """One branch row's maintenance status, folded for comparison and kept as written."""
    status = re.sub(r"\s+", " ", str(value or "")).strip().lower()
    if status not in SUPPORT:
        raise ValueError(f"{where}: unrecognized maintenance status {value!r}; the project "
                         f"publishes {sorted(SUPPORT)}")
    return status


def lifecycle_value(text, where):
    """One ``eom``/``eomm``/``eocp`` cell, kept exactly as the source states it.

    Empty, the project's own undetermined placeholder, and quarters are the
    forms it publishes. The value is returned verbatim — a quarter is never
    converted to a month or a day, and no cell is ever read as a milestone.
    """
    if not isinstance(text, str):
        raise ValueError(f"{where}: lifecycle cell must be text: {text!r}")
    value = text.strip()
    if value in ("", UNDETERMINED) or QUARTER.fullmatch(value):
        return value
    raise ValueError(f"{where}: unrecognized lifecycle cell {text!r}; the project publishes "
                     f"quarters, {UNDETERMINED!r} or an empty cell, and a quarter is retained "
                     f"verbatim rather than converted")


def feed_day(text, where):
    """One feed release date, ``31.08.2026`` -> ``2026-08-31``.

    The feed states a day, so the day is kept; a month or an ISO date here
    would be a reshaped document and refuses.
    """
    match = FEED_DATE.fullmatch((text or "").strip())
    if match is None:
        raise ValueError(f"{where}: unrecognized release date {text!r}")
    try:
        return date(int(match.group("year")), int(match.group("month")),
                    int(match.group("day"))).isoformat()
    except ValueError as error:
        raise ValueError(f"{where}: {text!r} is not a real calendar day") from error


def parse_version_overview(text):
    """Every branch row and patch row -> ``(branches, patches, excluded)``.

    No version row is dropped: a numbered branch becomes a published release, a
    row the project marks Skipped or the loader's wildcard default row is
    returned as an exclusion with the reason, and every patch row is attributed
    to the branch it names. Duplicate branch ids and duplicate patch versions
    refuse — either would publish two rows claiming the same identity.
    """
    payload = _payload(text, VERSION_OVERVIEW_URL)
    if not isinstance(payload, dict) or set(payload) != {"versions", "patches"}:
        raise ValueError(f"{VERSION_OVERVIEW_URL}: unexpected document shape "
                         f"{sorted(payload) if isinstance(payload, dict) else type(payload).__name__}")
    if not isinstance(payload["versions"], list) or not payload["versions"]:
        raise ValueError(f"{VERSION_OVERVIEW_URL}: versions must be a non-empty array")
    if not isinstance(payload["patches"], list):
        raise ValueError(f"{VERSION_OVERVIEW_URL}: patches must be an array")
    branches, excluded, seen = [], [], set()
    for index, row in enumerate(payload["versions"]):
        where = f"{VERSION_OVERVIEW_URL} versions row {index}"
        if not isinstance(row, dict):
            raise ValueError(f"{where}: source row is not an object: {row!r}")
        status = support_value(row.get("support"), where)
        label = row.get("version")
        required = VERSION_ROW_KEYS if "eocp" in row else NO_EOCP_ROW_KEYS
        _row_keys(row, where, required, VERSION_ROW_KEYS)
        if label == WILDCARD_ROW:
            excluded.append({
                "page": VERSION_OVERVIEW_URL, "row": label,
                "reason": "the version overview's wildcard default row: it carries the loader's "
                          "fallback maintenance metadata rather than a published release branch"})
            continue
        match = BRANCH_ROW.fullmatch(label)
        if match is None:
            raise ValueError(f"{where}: unrecognized version row {label!r}")
        branch = match.group("branch")
        if branch in seen:
            raise ValueError(f"{VERSION_OVERVIEW_URL}: branch {branch!r} is stated twice")
        seen.add(branch)
        if not isinstance(row["lts"], bool):
            raise ValueError(f"{where}: the lts flag must be a boolean: {row['lts']!r}")
        cells = {key: row[key] for key in VERSION_ROW_KEYS if key in row}
        for key in ("eom", "eomm", "eocp"):
            if key in cells:
                lifecycle_value(cells[key], f"{where} {key}")
        if status == SKIPPED:
            excluded.append({
                "page": VERSION_OVERVIEW_URL, "row": label,
                "reason": "the project marks this branch Skipped: no release was published for "
                          "it, so it carries neither a patch nor a lifecycle of its own"})
            continue
        branches.append({"id": branch, "label": label, "support": status, "cells": cells})
    patches, versions = {}, set()
    for index, row in enumerate(payload["patches"]):
        where = f"{VERSION_OVERVIEW_URL} patches row {index}"
        _row_keys(row, where, PATCH_ROW_REQUIRED, PATCH_ROW_KEYS)
        label = row["version"]
        if not isinstance(label, str) or not PATCH_VERSION.fullmatch(label):
            raise ValueError(f"{where}: unrecognized patch version {label!r}")
        for key in ("removed", "hidden"):
            if key in row and not isinstance(row[key], bool):
                raise ValueError(f"{where}: the {key} flag must be a boolean: {row[key]!r}")
        for key in ("eocp", "extended_eocp"):
            if key in row:
                lifecycle_value(row[key], f"{where} {key}")
        if label in versions:
            raise ValueError(f"{VERSION_OVERVIEW_URL}: patch {label!r} is stated twice")
        versions.add(label)
        branch = ".".join(label.split("-")[0].split(".")[:2])
        if branch not in seen:
            raise ValueError(f"{where}: patch {label!r} names branch {branch!r}, which the "
                             f"versions array does not state")
        patches.setdefault(branch, []).append({key: row[key] for key in PATCH_ROW_KEYS
                                               if key in row})
    published = {entry["id"] for entry in branches}
    orphans = sorted(branch for branch in patches if branch not in published)
    if orphans:
        raise ValueError(f"{VERSION_OVERVIEW_URL}: patches for branches that are not published "
                         f"releases: {orphans}")
    return branches, patches, excluded


def parse_current(text, branches):
    """The currently maintained branches -> ``(rows, excluded)``.

    ``latest`` and ``active`` are pointers to the newest branch rather than
    branch rows of their own, so they are excluded with that reason and every
    branch key becomes one current row. A row must name a branch the overview
    states, must not contradict that branch's status or LTS flag, and must name
    a patch version belonging to it; the two documents disagreeing refuses.
    """
    payload = _payload(text, VERSION_URL)
    if not isinstance(payload, dict) or not payload:
        raise ValueError(f"{VERSION_URL}: unexpected document shape")
    statuses = {entry["id"]: entry for entry in branches}
    rows, excluded, seen = {}, [], set()
    for key, row in payload.items():
        where = f"{VERSION_URL} row {key!r}"
        _row_keys(row, where, CURRENT_ROW_KEYS, CURRENT_ROW_KEYS)
        if key in ("latest", "active"):
            excluded.append({
                "page": VERSION_URL, "row": key,
                "reason": "a pointer to the newest maintained branch rather than a branch row of "
                          "its own; the branch it names is published from that branch's own row"})
            continue
        if key not in statuses:
            raise ValueError(f"{where}: names branch {key!r}, which the version overview does "
                             f"not publish")
        if key in seen:
            raise ValueError(f"{VERSION_URL}: branch {key!r} is stated twice")
        seen.add(key)
        expected = statuses[key]
        status = support_value(row["support"], where)
        if status != expected["support"] or row["lts"] is not expected["cells"]["lts"]:
            raise ValueError(f"{where}: {status!r}/lts {row['lts']!r} contradicts the version "
                             f"overview's {expected['support']!r}/"
                             f"{expected['cells']['lts']!r} for branch {key!r}")
        if not isinstance(row["version"], str) or not (
                PATCH_VERSION.fullmatch(row["version"])
                and row["version"].startswith(key + ".")):
            raise ValueError(f"{where}: version {row['version']!r} is not a patch of branch {key!r}")
        rows[key] = {name: row[name] for name in CURRENT_ROW_KEYS}
    if not rows:
        raise ValueError(f"{VERSION_URL}: states no maintained branch")
    return rows, excluded


def parse_feed(text):
    """The release feed's rows -> ``(rows, excluded)``.

    One row per currently maintained branch, stating the release date of that
    branch's latest patch. Two rows claiming one branch refuse, as does a row
    whose declared fields changed.
    """
    payload = _payload(text, FEED_URL)
    if not isinstance(payload, list) or not payload:
        raise ValueError(f"{FEED_URL}: the release feed must be a non-empty array")
    rows, excluded, seen = {}, [], set()
    for index, row in enumerate(payload):
        where = f"{FEED_URL} row {index}"
        _row_keys(row, where, FEED_ROW_KEYS, FEED_ROW_KEYS)
        label = row["version"]
        if not isinstance(label, str) or not PATCH_VERSION.fullmatch(label):
            raise ValueError(f"{where}: unrecognized release version {label!r}")
        feed_day(row["release_date"], where)
        lifecycle_value(row["eom"], f"{where} eom")
        branch = ".".join(label.split(".")[:2])
        if branch in seen:
            raise ValueError(f"{FEED_URL}: branch {branch!r} is stated twice")
        seen.add(branch)
        rows[branch] = {key: row[key] for key in FEED_ROW_KEYS}
    return rows, excluded


def _patch_key(version):
    """One patch version's numeric order, so ``1.148.9`` sorts above ``1.148.0``.

    A ``-legacy-free`` row shares its numeric version with the plain row, and
    the plain one is the branch's release: the suffix is ordered below it so a
    latest-patch identity is never the legacy-free build.
    """
    core, _, suffix = version.partition("-")
    return tuple(int(part) for part in core.split(".")) + (0 if suffix else 1,)


def max_patch(patches, where):
    """The newest patch version a branch states; a branch with no patch refuses."""
    if not patches:
        raise ValueError(f"{where}: the branch states no patch version to publish")
    return max((row["version"] for row in patches), key=_patch_key)


def branch_key(branch):
    """Newest branch first, on the numbers the project itself uses."""
    return tuple(int(part) for part in branch.split("."))


def _release(branch_id, row, patches, current, feed):
    """One published branch release, from the source rows that state it.

    The branch's cells, its patch rows and its current row are all kept
    verbatim. ``ga`` is the feed's stated date only when the feed's own version
    is this branch's ``.0`` release — that is the one case where the date it
    publishes is the branch's rather than a patch's.
    """
    cells = {key: row[key] for key in VERSION_ROW_KEYS if key in row}
    ga = None
    upstream = {"name": row["version"], "cells": cells, "table": VERSIONS_TABLE,
                "patches": [dict(patch) for patch in patches]}
    if current is not None and feed is not None:
        ga = feed_day(feed["release_date"], f"OpenUI5 {branch_id} current release") \
            if feed["version"] == branch_id + ".0" else None
        upstream["current"] = {"version": {key: current[key] for key in CURRENT_ROW_KEYS},
                               "release": {key: feed[key] for key in FEED_ROW_KEYS},
                               "table": CURRENT_TABLE}
    return {
        "id": branch_id,
        "name": f"{PRODUCT_NAME} {branch_id}",
        "milestones": {"ga": ga, "eos": None, "eossec": None, "eol": None},
        "upstream": upstream,
    }


def parse_releases(overview_text, current_text, feed_text):
    """Every source row -> ``(releases, accounting)``; no row is ever dropped.

    Complete-or-nothing across the three documents: the current rows are read
    against the branches the overview states, the feed rows against the current
    rows and the patch versions, and the result is the numbered branches the
    project published, newest first.
    """
    branches, patches, excluded = parse_version_overview(overview_text)
    current, current_excluded = parse_current(current_text, branches)
    feed, feed_excluded = parse_feed(feed_text)
    for branch in feed:
        if branch not in current:
            raise ValueError(f"{FEED_URL}: states a release for branch {branch!r}, which "
                             f"{VERSION_URL} does not list as maintained")
    for branch, row in current.items():
        stated = max_patch(patches.get(branch, []), f"OpenUI5 {branch}")
        if row["version"] != stated:
            raise ValueError(f"{VERSION_URL}: branch {branch!r} states latest patch "
                             f"{row['version']!r}, but the version overview's newest patch is "
                             f"{stated!r}")
        if branch not in feed:
            raise ValueError(f"{FEED_URL}: states no release for maintained branch {branch!r}")
        if feed[branch]["version"] != row["version"]:
            raise ValueError(f"{FEED_URL}: branch {branch!r} states release "
                             f"{feed[branch]['version']!r}, but {VERSION_URL} states "
                             f"{row['version']!r}")
    releases = [_release(branch["id"], branch["cells"], patches.get(branch["id"], []),
                         current.get(branch["id"]), feed.get(branch["id"]))
                for branch in branches]
    releases.sort(key=lambda release: branch_key(release["id"]), reverse=True)
    with_patches = sum(1 for release in releases if release["upstream"]["patches"])
    accounting = {
        "branches": {"seen": len(branches) + len(excluded), "published": len(branches),
                     "excluded": len(excluded)},
        "patches": {"seen": sum(len(rows) for rows in patches.values()),
                    "published": sum(len(release["upstream"]["patches"]) for release in releases),
                    "branches": with_patches,
                    "branches_without": len(releases) - with_patches},
        "current": {"seen": len(current) + len(current_excluded), "used": len(current),
                    "excluded": len(current_excluded)},
        "feed": {"seen": len(feed), "used": len(current),
                 "excluded": len(feed_excluded)},
        "excluded": excluded,
        "current_excluded": current_excluded + feed_excluded,
    }
    return releases, accounting


def policy_rules(text):
    """The policy's meaning statements and its support-period rows, verbatim.

    The sentences that separate EOM, EOL and EOCP are required word for word:
    they are the evidence that this record's ``eol`` staying null is the
    project's own semantics rather than an omission. The support-period table
    is read by its declared columns and returned row by row, so the durations
    are covered rather than only cited.
    """
    page = _folded(text)
    rules = {}
    for key, quote in QUOTES.items():
        if _folded(quote) not in page:
            raise ValueError(f"{POLICY_URL}: the maintenance policy no longer states the "
                             f"{key!r} sentence verbatim; a reworded policy is reviewed before "
                             f"this record is published")
        rules[key] = quote
    parser = _Tables()
    parser.feed(text)
    parser.close()
    tables = [table for table in parser.tables
              if table and tuple(map(_folded, table[0])) == POLICY_COLUMNS]
    if len(tables) != 1:
        raise ValueError(f"{POLICY_URL}: missing or duplicate support-period table")
    rows = [row for row in tables[0][1:] if any(row)]
    for row in rows:
        if len(row) != len(POLICY_COLUMNS):
            raise ValueError(f"{POLICY_URL}: support-period row width changed")
    # The page renders escaped Markdown (``Mid-Term Support \(MTS\)``), so the
    # declared type is compared folded and the row is returned as rendered.
    stated = {_folded(row[0]): row for row in rows}
    for name in POLICY_TYPES:
        if name not in stated:
            raise ValueError(f"{POLICY_URL}: the support-period table no longer states {name!r}")
    return {"rules": rules,
            "periods": [{"release_type": row[0], "support_period": row[1],
                         "cycle": row[2]} for row in rows]}


def release_columns(text):
    """The columns the releases page declares, which is where ``ga`` is labelled.

    The page renders its rows from the same feed this module reads, so its own
    declared header row is the evidence for the label ``ga`` is mapped from:
    the page names the column and the feed supplies the day. A reshaped header
    refuses, and so does a page rendering no release table at all — the reader
    that would check a published date against the site has to exist.
    """
    parser = _Tables()
    parser.feed(text)
    parser.close()
    # The page declares its columns in a header row and renders its body
    # client-side from the same feed, so the header is the evidence; a body
    # placeholder row is not a data row and is not required to span the columns.
    tables = [table for table in parser.tables
              if table and list(table[0]) == list(RELEASE_COLUMNS)]
    if len(tables) != 1:
        raise ValueError(f"{RELEASE_PAGE}: missing or duplicate release table")
    declared = list(tables[0][0])
    if declared != list(RELEASE_COLUMNS):
        raise ValueError(f"{RELEASE_PAGE}: release table columns changed: {declared}")
    return {"columns": declared, "rows": len(tables[0]) - 1}


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
                raise ValueError("Nested OpenUI5 policy tables")
            self.table = []
        elif tag == "tr" and self.table is not None:
            self.row = []
        elif tag in ("td", "th") and self.row is not None:
            self.cell = []
        elif tag == "br" and self.cell is not None:
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


def retained(release):
    """A committed branch the current documents no longer state, marked as such.

    Republished from its own stored rows, so retention can never introduce a
    date the project did not publish; the marker says only that this fetch's
    documents lack the branch. Absence from the overview is not an end of life.
    """
    return {**release, "upstream": {**release["upstream"], "in_source": False}}


def combine_releases(fresh, committed):
    """The complete branch snapshot: this fetch's branches plus retained history.

    The union is re-sorted newest branch first, because a retained branch sits
    wherever its own number puts it rather than after the freshly fetched ones.
    """
    if committed is None:
        return list(fresh), []
    ids = {release["id"] for release in fresh}
    kept = [retained(release) for release in committed["releases"] if release["id"] not in ids]
    releases = list(fresh) + kept
    releases.sort(key=lambda release: branch_key(release["id"]), reverse=True)
    return releases, [{"id": release["id"], "name": release["name"],
                       "reason": "the current OpenUI5 version overview does not state "
                                 "this branch; the committed row, its cells, its "
                                 "patches and its dates are retained"}
                      for release in kept]


def _cells_of(release, where):
    """One stored release's branch cells, refused unless they are the declared columns."""
    cells = release.get("upstream", {}).get("cells")
    if (not isinstance(cells, dict) or set(cells) != set(VERSION_ROW_KEYS)
            or release["upstream"].get("table") != VERSIONS_TABLE):
        raise ValueError(f"{where}: the release does not store its branch row's cells")
    return cells


def _patches_of(release, where):
    """One stored release's patch rows, refused unless they are the declared shape."""
    rows = release["upstream"].get("patches")
    if not isinstance(rows, list):
        raise ValueError(f"{where}: the release does not store its branch's patch rows")
    seen = set()
    for index, row in enumerate(rows):
        at = f"{where} patch row {index}"
        _row_keys(row, at, PATCH_ROW_REQUIRED, PATCH_ROW_KEYS)
        label = row["version"]
        if not isinstance(label, str) or not PATCH_VERSION.fullmatch(label):
            raise ValueError(f"{at}: unrecognized patch version {label!r}")
        for key in ("removed", "hidden"):
            if key in row and not isinstance(row[key], bool):
                raise ValueError(f"{at}: the {key} flag must be a boolean: {row[key]!r}")
        for key in ("eocp", "extended_eocp"):
            if key in row:
                lifecycle_value(row[key], f"{at} {key}")
        if label in seen:
            raise ValueError(f"{where}: patch {label!r} is stored twice")
        seen.add(label)
    return rows


def validate_record(record):
    """Rebuild every stored branch from its own published rows, offline.

    Offline, the record's own rows are the whole evidence: the branch identity
    and the maintenance status are re-read from the stored cells, the patch
    rows are re-checked for shape and identity, and ``ga`` is re-derived from
    the stored current row — so a record whose ``ga`` no longer follows the
    release the project dates, or which publishes an ``eos``/``eossec``/``eol``
    the project never states, is refused rather than published.
    """
    if (record["id"] != PRODUCT_ID or record["provenance"]["verifier"] != VERIFIER
            or record["provenance"]["source_url"] != VERSION_OVERVIEW_URL):
        raise ValueError("Invalid OpenUI5 source identity")
    if record["labels"] != {"ga": GA_LABEL}:
        raise ValueError("Invalid OpenUI5 label evidence")
    if record["links"] != LINKS:
        raise ValueError("Invalid OpenUI5 source links")
    releases, seen = [], set()
    for release in record["releases"]:
        branch = release["id"]
        where = f"OpenUI5 {branch}"
        if not isinstance(branch, str) or not BRANCH_ROW.fullmatch(branch + ".*"):
            raise ValueError(f"{where}: release id does not name a numbered branch")
        if branch in seen:
            raise ValueError(f"{where}: branch is published twice")
        seen.add(branch)
        cells = _cells_of(release, where)
        if cells["version"] != branch + ".*":
            raise ValueError(f"{where}: the stored cells name a different branch: "
                             f"{cells['version']!r}")
        support_value(cells["support"], where)
        if not isinstance(cells["lts"], bool):
            raise ValueError(f"{where}: the lts flag must be a boolean: {cells['lts']!r}")
        for key in ("eom", "eomm", "eocp"):
            lifecycle_value(cells[key], f"{where} {key}")
        if release["name"] != f"{PRODUCT_NAME} {branch}" or release["upstream"]["name"] != cells["version"]:
            raise ValueError(f"{where}: release does not name the branch row it stores")
        rows = _patches_of(release, where)
        for row in rows:
            if not row["version"].startswith(branch + "."):
                raise ValueError(f"{where}: patch {row['version']!r} belongs to another branch")
        current = release["upstream"].get("current")
        if current is None:
            if release["milestones"]["ga"] is not None:
                raise ValueError(f"{where}: publishes a ga with no current release row to support it")
        else:
            if set(current) != {"version", "release", "table"} or current["table"] != CURRENT_TABLE:
                raise ValueError(f"{where}: current row is not the stored source rows")
            stored, stated = current["version"], current["release"]
            _row_keys(stored, f"{where} current", CURRENT_ROW_KEYS, CURRENT_ROW_KEYS)
            _row_keys(stated, f"{where} current release", FEED_ROW_KEYS, FEED_ROW_KEYS)
            if stated["version"] != stored["version"] or not stated["version"].startswith(branch + "."):
                raise ValueError(f"{where}: the stored current rows name different versions")
            if stored["version"] != max_patch(rows, where):
                raise ValueError(f"{where}: the current row is not the branch's newest patch")
            if support_value(stored["support"], f"{where} current") != support_value(
                    cells["support"], where) or stored["lts"] is not cells["lts"]:
                raise ValueError(f"{where}: the current row contradicts the branch row it stores")
            lifecycle_value(stated["eom"], f"{where} current eom")
            expected = feed_day(stated["release_date"], where) \
                if stated["version"] == branch + ".0" else None
            if release["milestones"]["ga"] != expected:
                raise ValueError(f"{where}: ga contradicts the release date the current row states")
        if release["milestones"]["eos"] is not None or release["milestones"]["eossec"] is not None \
                or release["milestones"]["eol"] is not None:
            raise ValueError(f"{where}: publishes an end milestone, but the project's eom/eomm/eocp "
                             f"cells are neither the end of security support nor the end of life")
        if release["upstream"].get("in_source") not in (None, False):
            raise ValueError(f"{where}: release carries an invalid retention marker")
        releases.append(release)
    expected = sorted((release["id"] for release in releases), key=branch_key, reverse=True)
    if [release["id"] for release in releases] != expected:
        raise ValueError("The OpenUI5 record is not ordered newest branch first")


def record_for(releases, checked):
    """The published ``openui5`` record for one complete branch snapshot."""
    return {
        "$schema": RECORD_SCHEMA,
        "id": PRODUCT_ID,
        "name": PRODUCT_NAME,
        "category": "software",
        "upstream_category": UPSTREAM_CATEGORY,
        # The project publishes numbered branches and patches, never a CPE or
        # other identifier for them, so none is invented here.
        "identifiers": [],
        # The only label this record maps: the feed's stated day becomes the
        # branch's general availability when it dates the branch's own ``.0``
        # release. The eom/eomm/eocp cells map to nothing.
        "labels": {"ga": GA_LABEL},
        "links": dict(LINKS),
        "releases": releases,
        "provenance": {"source_url": VERSION_OVERVIEW_URL, "verifier": VERIFIER,
                       "last_checked": checked, "upstream_modified": None},
    }


def committed_record(root):
    """The committed ``openui5`` record, refusing one this source cannot own."""
    return transaction.committed_product_record(root, PRODUCT_ID, VERIFIER,
                                                validate_record, "OpenUI5")


def publish_record(record, report, root):
    """Stage the record beside the committed catalog, validate, then replace it."""
    return transaction.publish_product_record(record, report, root, REPORT)


def report_for(releases, accounting, policy, kept, checked):
    """The per-row accounting this source publishes beside its record.

    Every version row, patch row, current row and feed row this fetch read is
    accounted for: the identities ``branches.seen == published + excluded`` and
    ``patches.seen == published`` hold, the current and feed rows are counted
    with the pointers and any disagreement that excluded them, and the retained
    snapshot rows are counted separately so the numbers read as one observation
    of one source.
    """
    retained_ids = {entry["id"] for entry in kept}
    fresh = [release for release in releases if release["id"] not in retained_ids]
    stated = {key: sum(1 for release in fresh if release["milestones"][key])
              for key in ("ga", "eos", "eossec", "eol")}
    # How many branches this fetch read state each vendor lifecycle cell, and
    # how many patch rows they carried: the quarter-precision surface the record
    # retains as cell text, counted without converting any of it.
    cells = {key: sum(1 for release in fresh
                      if release["upstream"]["cells"].get(key)) for key in ("eom", "eomm", "eocp")}
    cells["patches"] = sum(len(release["upstream"]["patches"]) for release in fresh)
    return {
        "source_url": VERSION_OVERVIEW_URL,
        "verifier": VERIFIER,
        "checked_at": checked,
        "record_scope": ("OpenUI5 numbered release branches: one software record with one "
                         "release per published numbered branch, carrying the project's own "
                         "eom/eomm/eocp cells and every patch row verbatim, general availability "
                         "only where a stated release date dates the branch's own .0 release, "
                         "and no normalized end milestone"),
        "rows": {**accounting, "retained": len(kept)},
        "total_records": 1,
        "milestones_published": stated,
        # The lifecycle cells this fetch retained rather than normalized, per
        # cell, so the sidecar records the quarter-precision surface its record
        # carries without converting any of it.
        "lifecycle_cells_retained": cells,
        "policy": {"url": POLICY_URL,
                   "rules": [{"key": key, "quote": quote}
                             for key, quote in policy["rules"].items()],
                   "periods": policy["periods"],
                   "rows": {"seen": len(policy["periods"]), "dated": 0,
                            "not_dated": [
                                {"row": row["release_type"],
                                 "reason": "a support-period duration, not a date: the branch "
                                           "catalog does not label which non-LTS branch is MTS or "
                                           "Standard, the project's own rows carry explicit "
                                           "extensions a generic duration contradicts, and the "
                                           "policy's EOL rule runs through EOM, which the "
                                           "normalized schema does not carry"}
                                for row in policy["periods"]]}},
        "limitations": [
            "No end milestone is published: the project's eom, eomm and eocp cells are retained "
            "verbatim in every branch's upstream.cells and none of them is this catalog's eos, "
            "eossec or eol. The policy states that bug fixes run to EOM, that critical security "
            "patches then run for one more year, and that EOCP is removal from the CDN.",
            "Quarter precision is not normalized: every eom/eomm/eocp value the project states is "
            "a quarter (Q3/2026), and the normalized milestones carry a day or a month only, so "
            "no quarter is converted to either and every quarter stays the project's own text.",
            "General availability is published for 2 branches only, where the release feed's "
            "stated date dates the branch's own .0 release (1.152 and 1.150). Every other feed "
            "row dates a patch, and is preserved under that branch's upstream.current rather "
            "than promoted to the branch.",
            "Patch metadata is retained, not normalized: 1038 patch rows are stored verbatim "
            "under the branch they belong to, including their eocp quarters, their removed and "
            "hidden flags and 1.48.6's extended_eocp cell. No patch row becomes a release.",
            "The two sources disagree for 1.142 in the live snapshot: versionoverview.json states "
            "eom 'Q3/2026' while the release feed states an empty eom for that branch. Both cells "
            "are kept verbatim as the rows that state them, and branch lifecycle is read from "
            "versionoverview.json rather than reconciled from either.",
            "No duration is derived from the policy's support periods (Standard 6 weeks, MTS 9 "
            "months, LTS 15 months): a stated quarter such as 1.71's and 1.108's Q4/2030 "
            "contradicts a generic LTS duration, the branch catalog does not label which "
            "non-LTS branch is MTS and which is Standard, and the policy's two-step EOM then one "
            "year rule cannot be expressed as one calculation from a stated day.",
            "Branch maintenance status (Maintenance/Out of Maintenance) and the LTS flag are the "
            "project's current state, not deadlines, so neither becomes a milestone.",
            "1.137 and 1.83 are excluded: the project marks both Skipped and published no release "
            "for them. The wildcard default row is excluded as the loader's fallback metadata "
            "rather than a release branch. Odd-numbered legacy branches the overview does not "
            "state are not synthesized.",
            "Branches 1.24 and 1.22 are published from their branch rows and state no patch row "
            "at all; a branch with no published patch keeps a null ga and an empty patch list.",
        ],
    }


def import_openui5(directory=None):
    """Fetch the five documents and publish the ``openui5`` record and report.

    Complete-or-nothing: the fetched snapshot is combined with the branches the
    documents no longer state, staged beside the committed catalog and validated
    there before anything is written. A reshaped document, a reworded policy, a
    release page that no longer declares the ``ga`` column, or an inconsistent
    catalog leaves every committed file untouched.
    """
    root = Path(directory) if directory is not None else ROOT / "data"
    # The committed ownership check runs before the fetch: a file this source
    # cannot publish aborts the run without a network call at all.
    committed = committed_record(root)
    checked = _now()
    policy = policy_rules(net.get_text(POLICY_URL))
    page = release_columns(net.get_text(RELEASE_PAGE))
    # The label ``ga`` is mapped from is the page's own column header, so the
    # page and the record have to name the same one: a renamed column refuses
    # rather than leaving a stored label no page states.
    if page["columns"][-1] != GA_LABEL:
        raise ValueError(f"{RELEASE_PAGE}: the release date column is no longer {GA_LABEL!r}")
    overview = net.get_text(VERSION_OVERVIEW_URL)
    current = net.get_text(VERSION_URL)
    feed = net.get_text(FEED_URL)
    fresh, accounting = parse_releases(overview, current, feed)
    releases, kept = combine_releases(fresh, committed)
    record = record_for(releases, checked)
    validate_record(record)
    report = report_for(releases, accounting, policy, kept, checked)
    report["release_page"] = {"url": RELEASE_PAGE, "columns": page["columns"],
                              "rows": page["rows"], "label_mapped": GA_LABEL}
    transaction.publish_product_record(record, report, root, REPORT)
    rows = report["rows"]
    return (f"imported {len(releases)} OpenUI5 branches "
            f"({report['milestones_published']['ga']} with a stated general availability, "
            f"{rows['patches']['published']} patch rows retained); excluded "
            f"{rows['branches']['excluded']} version rows, retained {rows['retained']} "
            f"(data/{REPORT})")
