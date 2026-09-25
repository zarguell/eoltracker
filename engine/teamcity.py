"""TeamCity On-Premises lifecycle, from JetBrains' own release cycle and catalog.

Two authoritative pages make this record, and neither alone would be publishable:

* the release-cycle policy states *when* a major line's support stages end as
  explicit release events — end of sale "with the release of the next major
  version", end of support "with the release of two newer major versions" — but
  attaches no calendar date to any version;
* the previous-releases catalog states every major line's own day-precision
  release date, from 3.1 through the current release.

So the catalog's stated dates are published as ``ga``, and ``eos``/``eol`` are
published *derived*: the dated release the policy names, carrying the policy
sentence verbatim, the base date it is measured from, and the trigger release's
own id and date in ``milestone_provenance``. A major line whose triggering
release has not been published yet keeps a null milestone, and ``eossec`` stays
null for every line — JetBrains publishes no separate security-support end. The
policy's "usually released every four months" is cadence, never a date.

Only major lines become releases. The catalog's bugfix (minor) lines are
accounted for in the import report as excluded rows: JetBrains states lifecycle
at major-version level, so a patch line has none of its own.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

from . import derived, net, sources, transaction
from .importer import ROOT

# The registry owns the ids and the pages: a record's provenance must name a
# source this checkout installs, and the report must name the pages it read.
SOURCE = sources.source("import-teamcity")
VERIFIER = SOURCE.verifier
POLICY_URL, CATALOG_URL = (page.url for page in SOURCE.pages)
REPORT = SOURCE.report
RECORD_SCHEMA = "https://zarguell.github.io/eoltracker/v1/schema/product.json"
PRODUCT_ID = "teamcity"
PRODUCT_NAME = "TeamCity On-Premises"
UPSTREAM_CATEGORY = "server-app"

# The page's own name for the release list, and the two facts each of its
# chapters states. A renamed list or a renamed cell label refuses the parse.
CATALOG_TABLE = "Previous Releases Downloads"
HEADING = "Heading"
RELEASE_DATE = "Release date"
# The release-stage table's columns and the two rows that state a rule.
RULE_COLUMNS = ("Release Stage", "Description")
# The vendor's rule sentences, stored verbatim and required verbatim: a reworded
# policy refuses the import rather than silently re-deriving under a new rule.
# These two rows are the whole dated lifecycle the policy publishes, so the
# offline re-derivation re-derives from them without a network fetch.
EOS_LABEL = "TeamCity On-Premises End of Sale"
EOL_LABEL = "TeamCity On-Premises End of Support"
# Every release-stage row the policy page is reviewed to state, and what each
# one is: the two rules this record applies, and the two rows that state no
# dated milestone. The set is complete on purpose — an unreviewed label refuses
# the parse — because a newly added stage can change support semantics while the
# record would otherwise keep deriving under stale ones and still claim complete
# row coverage.
NOT_DATED = (
    ("TeamCity Cloud Major Release",
     "TeamCity Cloud is a different product with its own subscription licensing; this record "
     "covers On-Premises only"),
    ("TeamCity On-Premises Major Release",
     "a release-stage description, not a milestone: its 'usually released every four months' "
     "is cadence, and a cadence is never converted into a date"),
)
POLICY_LABELS = (EOS_LABEL, EOL_LABEL) + tuple(label for label, _reason in NOT_DATED)
EOS_QUOTE = "Occurs for the previous major version with the release of the next major version."
EOL_QUOTE = "Occurs with the release of two newer major versions."
RULES = {"eos": {"label": EOS_LABEL, "quote": EOS_QUOTE},
         "eol": {"label": EOL_LABEL, "quote": EOL_QUOTE}}
# What each trigger release is, in the policy's own terms.
EOS_TRIGGER = "the next major version"
EOL_TRIGGER = "the second newer major version"
BASE_LABEL = "general availability"

# ``TeamCity 2026.1`` and the catalog's bolded current line. The version's
# component count decides whether the chapter is a major line or a patch line.
CHAPTER = re.compile(r"(?:(?:Current version:) )?TeamCity (?P<version>\d+(?:\.\d+)*)\Z")
MAJOR = re.compile(r"\d+\.\d+\Z")
# ``2 September 2026``, the only date form the catalog states.
DATE_TEXT = re.compile(r"(?P<day>\d{1,2}) (?P<month>[A-Z][a-z]+) (?P<year>\d{4})\Z")
MONTHS = {name: index for index, name in enumerate(
    ("January", "February", "March", "April", "May", "June", "July", "August",
     "September", "October", "November", "December"), 1)}
# The appendix of a chapter's paragraphs that states the release date; the
# archived pages render it as Markdown in some sections.
MARKDOWN = re.compile(r"^[^\w]*")


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
                raise ValueError("Nested TeamCity tables")
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


class _Chapters(HTMLParser):
    """Each ``<section class="chapter">`` as its heading and paragraph text.

    A release chapter is a heading plus the paragraphs beneath it, not a table
    row, so the catalog is read as the blocks the page renders. Tags are
    dropped, whitespace folded within a line, and a ``<br>`` kept as the line
    break the page shows — the release date and the build number are two lines
    of one paragraph and only the first is a date.
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.chapters = []
        self.depth = 0
        self.blocks = []
        self.tag = None
        self.buf = []

    def handle_starttag(self, tag, attrs):
        if tag == "section":
            classes = (dict(attrs).get("class") or "").split()
            if self.depth == 0 and "chapter" not in classes:
                return
            self.depth += 1
            return
        if self.depth == 0:
            return
        if tag == "br":
            if self.tag is not None:
                self.buf.append("\n")
            return
        if tag in ("h2", "p"):
            self._flush()
            self.tag, self.buf = tag, []

    def _flush(self):
        if self.tag is None:
            return
        text = re.sub(r"[ \t]+", " ", "".join(self.buf))
        self.blocks.append((self.tag, re.sub(r"\s*\n\s*", "\n", text).strip()))
        self.tag, self.buf = None, []

    def handle_endtag(self, tag):
        if self.depth == 0:
            return
        if tag in ("h2", "p"):
            self._flush()
        elif tag == "section":
            self.depth -= 1
            if self.depth == 0:
                self.chapters.append(self.blocks)
                self.blocks = []

    def handle_data(self, data):
        if self.depth and self.tag is not None:
            self.buf.append(data)


def _chapters(html):
    parser = _Chapters()
    parser.feed(html)
    parser.close()
    return parser.chapters


def policy_rules(html):
    """The vendor's two trigger rules, verbatim, plus the accounting of every row.

    The rules are prose in a release-stage table, so the table is identified by
    the columns it declares and each rule row by its own label. The stored quote
    is the rule sentence itself, and it must appear in the page word for word:
    a reworded or renamed policy refuses instead of deriving under a rule the
    vendor no longer states.

    The table's labels are required to be *exactly* the reviewed set: every row
    the policy is reviewed to state must be present, and any row it states that
    this record has not reviewed refuses the parse. A newly added release stage
    governs support as surely as the two rows this record applies, so silently
    dropping it would let the record keep deriving under stale semantics while
    still reporting complete row coverage. The rows that state no dated milestone
    are returned, with the reason each licenses no date, as the accounting a
    reader can check the two rules against.
    """
    parser = _Tables()
    parser.feed(html)
    parser.close()
    tables = [table for table in parser.tables
              if table and list(table[0]) == list(RULE_COLUMNS)]
    if len(tables) != 1:
        raise ValueError("Missing or duplicate TeamCity release-stage table")
    rows = [row for row in tables[0][1:] if any(row)]
    for row in rows:
        if len(row) != len(RULE_COLUMNS):
            raise ValueError("TeamCity release-stage row width changed")
    stated = {}
    for row in rows:
        stated.setdefault(row[0], []).append(row[1])
    missing = [label for label in POLICY_LABELS if label not in stated]
    if missing:
        raise ValueError(f"The TeamCity release cycle no longer states the reviewed release-stage "
                         f"rows: {missing}")
    unknown = [label for label in stated if label not in POLICY_LABELS]
    if unknown:
        raise ValueError(f"The TeamCity release cycle states release-stage rows this record has "
                         f"not reviewed: {unknown}")
    rules = {}
    for key, label, quote in (("eos", EOS_LABEL, EOS_QUOTE), ("eol", EOL_LABEL, EOL_QUOTE)):
        if len(stated.get(label, [])) != 1:
            raise ValueError(f"The TeamCity release cycle no longer states {label!r} exactly once")
        text = stated[label][0]
        if quote not in text:
            raise ValueError(f"The TeamCity release cycle reworded {label!r}: {text!r}")
        rules[key] = {"label": label, "quote": quote, "text": text}
    # Every row of the table that states no rule this record applies, with the
    # reason it does not: the two rules are the whole dated lifecycle the policy
    # publishes, and the rest of the page is either cadence prose or Cloud.
    others = [{"row": label, "reason": reason} for label, reason in NOT_DATED
              if label in stated]
    # The report's row count is the *parsed* table row count, taken here where
    # the table was read, not recomputed from the rules and rows this function
    # happens to return: a filter that dropped a row could otherwise still sum
    # to a complete-looking total.
    return rules, others, len(rows)


def release_date(text, where):
    """One catalog chapter's ``Release date: 2 September 2026`` line.

    The paragraph's first line is the date and the following lines are the build
    number. Month names and day counts the calendar does not have refuse.
    """
    first = MARKDOWN.sub("", text.split("\n", 1)[0]).strip()
    prefix = RELEASE_DATE + ":"
    if not first.startswith(prefix):
        raise ValueError(f"{where}: unexpected catalog paragraph {text!r}")
    value = first[len(prefix):].strip()
    match = DATE_TEXT.fullmatch(value)
    if match is None:
        raise ValueError(f"{where}: unrecognized release date {value!r}")
    try:
        return date(int(match.group("year")), MONTHS[match.group("month")],
                    int(match.group("day"))).isoformat()
    except (KeyError, ValueError) as error:
        raise ValueError(f"{where}: {value!r} is not a real calendar day") from error


def release_for(cells):
    """One published release, from the chapter cells that state it."""
    version = cells[HEADING]
    match = CHAPTER.fullmatch(version)
    if match is None:
        raise ValueError(f"Unexpected TeamCity release heading: {version!r}")
    name = match.group("version")
    return {
        "id": name,
        "name": f"{PRODUCT_NAME} {name}",
        "milestones": {"ga": release_date(cells[RELEASE_DATE], f"TeamCity {name}"),
                       "eos": None, "eossec": None, "eol": None},
        "upstream": {"name": name, "cells": cells, "table": CATALOG_TABLE},
    }


def parse_catalog(html):
    """Every catalog chapter -> ``(releases, excluded)``; no row is dropped.

    A chapter whose version has two components is a major line; one with a third
    component is a bugfix line, published as no release of its own because the
    vendor's policy states lifecycle at major-version level. Every major line
    must state its release date — the catalog dates are the whole basis of the
    record, so a major line without one refuses the parse.
    """
    releases, excluded, seen = [], [], set()
    for blocks in _chapters(html):
        heading = next((text for tag, text in blocks if tag == "h2"), None)
        if heading is None:
            raise ValueError("A TeamCity catalog chapter states no release heading")
        version = CHAPTER.fullmatch(heading)
        if version is None:
            raise ValueError(f"Unrecognized TeamCity catalog heading {heading!r}")
        version = version.group("version")
        if version in seen:
            raise ValueError(f"The TeamCity catalog states {version!r} twice")
        seen.add(version)
        dated = next((text for tag, text in blocks
                      if tag == "p" and MARKDOWN.sub("", text).startswith(RELEASE_DATE + ":")), None)
        if not MAJOR.fullmatch(version):
            excluded.append({
                "page": CATALOG_URL, "row": heading,
                "reason": "a bugfix (minor) release line: JetBrains states the lifecycle at "
                          "major-version level, so this line carries no lifecycle of its own and "
                          "its parent major line is published instead"})
            continue
        if dated is None:
            raise ValueError(f"TeamCity {version}: the catalog states no release date "
                             f"for this major line")
        releases.append(release_for({HEADING: heading, RELEASE_DATE: dated}))
    if not releases:
        raise ValueError("The TeamCity catalog produced no major lines")
    parents = {release["id"] for release in releases}
    orphans = [entry["row"] for entry in excluded
               if entry["row"].rsplit(".", 1)[0].replace("TeamCity ", "") not in parents]
    if orphans:
        raise ValueError(f"TeamCity bugfix rows without a published major line: {orphans}")
    dates = [release["milestones"]["ga"] for release in releases]
    if len(set(dates)) != len(dates):
        raise ValueError("Two TeamCity major lines state the same release date; the policy's "
                         "'next major version' trigger would be ambiguous")
    return releases, excluded


def _version_key(version):
    """One version's numeric order, so ``2026.1`` sorts above ``10.0``."""
    return tuple(int(part) for part in version.split("."))


def ordered_releases(releases):
    """Newest major line first, by the version identity the catalog states.

    The policy defines a transition by *the next* and *the second newer* major
    version, so the order is the versions' own numeric identity. ``_check_order``
    then requires that identity order and the release-date order to agree: a
    catalog that dated a newer major before an older one would otherwise pick the
    wrong trigger release while still re-deriving consistently.
    """
    return sorted(releases, key=lambda release: _version_key(release["id"]), reverse=True)


def _check_order(ordered, where):
    """Require the major versions' order and the release dates to agree."""
    for index in range(len(ordered) - 1):
        newer, older = ordered[index], ordered[index + 1]
        newer_date = newer["milestones"]["ga"]
        older_date = older["milestones"]["ga"]
        if newer_date is None or older_date is None:
            raise ValueError(f"{where}: a major line states no release date")
        if newer_date <= older_date:
            raise ValueError(
                f"{where}: major {newer['id']} is newer than major {older['id']} but the catalog "
                f"dates it {newer_date}, not after {older_date}; the policy's trigger would point "
                f"at the wrong release")


def derived_entry(key, release, trigger, rule):
    """One derived milestone's provenance: the rule, its base and its trigger."""
    return {
        "kind": derived.KIND,
        "method": "release-trigger",
        "source_url": POLICY_URL,
        "quote": rule["quote"],
        "base_date": release["milestones"]["ga"],
        "base_label": BASE_LABEL,
        "trigger": {"release_id": trigger["id"],
                    "date": trigger["milestones"]["ga"],
                    "label": EOS_TRIGGER if key == "eos" else EOL_TRIGGER},
    }


def derived_for(ordered, index, rules):
    """One line's transitions, re-derived from the releases that follow it.

    End of sale happens with the next major release and end of support with the
    second newer one, so the line at *index* of the newest-first order derives
    from the lines at *index-1* and *index-2*. A trigger the catalog does not
    publish yet yields ``None``: the future transition is not known, and neither
    the policy nor the roadmap's rough estimate dates it. The single function
    both publishing and offline validation call, so the two cannot disagree.
    """
    release = ordered[index]
    milestones = {"ga": release["milestones"]["ga"], "eos": None, "eossec": None, "eol": None}
    provenance = {}
    for key, offset in (("eos", 1), ("eol", 2)):
        trigger = ordered[index - offset] if index >= offset else None
        if trigger is None:
            continue
        milestones[key] = trigger["milestones"]["ga"]
        provenance[key] = derived_entry(key, release, trigger, rules[key])
    return milestones, provenance


def with_derived_milestones(releases, rules):
    """Every derivable ``eos``/``eol``, with the provenance that re-derives it.

    A stored snapshot's derived dates are recomputed, never carried: the
    trigger a line derives from is whichever release the catalog now states, so
    a newly published major fills two older lines, and a rule that no longer
    applies leaves the milestone null rather than stale. Each derived date is
    labelled, and its provenance carries the base, the rule sentence and the
    trigger release. The version order must agree with the release dates.
    """
    ordered = ordered_releases(releases)
    _check_order(ordered, CATALOG_URL)
    for index, release in enumerate(ordered):
        milestones, provenance = derived_for(ordered, index, rules)
        release["milestones"] = milestones
        if provenance:
            release[derived.DERIVED_KEY] = provenance
        else:
            release.pop(derived.DERIVED_KEY, None)
    return ordered


def validate_record(record):
    """Rebuild every stored release and derived date from its own cells, offline.

    Offline, the record's own cells are the whole evidence: each release's
    ``ga`` is re-read from the chapter it stores, the release order is re-sorted
    from those dates, and ``eos``/``eol`` are re-derived from the triggering
    releases that order yields. A milestone, a trigger or a quote that no longer
    follows its own stored cells is never published.
    """
    if (record["id"] != PRODUCT_ID or record["provenance"]["verifier"] != VERIFIER
            or record["provenance"]["source_url"] != CATALOG_URL):
        raise ValueError("Invalid TeamCity source identity")
    if record["labels"] != {"ga": RELEASE_DATE, "eos": EOS_LABEL, "eol": EOL_LABEL}:
        raise ValueError("Invalid TeamCity label evidence")
    releases, seen = [], set()
    for release in record["releases"]:
        cells = release.get("upstream", {}).get("cells")
        if (not isinstance(cells, dict) or set(cells) != {HEADING, RELEASE_DATE}
                or release["upstream"].get("table") != CATALOG_TABLE):
            raise ValueError(f"TeamCity release without source cells: {release['id']}")
        where = f"TeamCity {release['id']}"
        expected = release_for(cells)
        if release["id"] in seen or release["id"] != expected["id"] or not MAJOR.fullmatch(release["id"]):
            raise ValueError(f"{where}: release does not name its own catalog chapter")
        seen.add(release["id"])
        if release["name"] != expected["name"] or release["upstream"]["name"] != expected["id"]:
            raise ValueError(f"{where}: release contradicts the chapter it stores")
        if release["upstream"].get("in_source") not in (None, False):
            raise ValueError(f"{where}: release carries an invalid retention marker")
        releases.append(release)
    if [release["id"] for release in releases] != [release["id"] for release in ordered_releases(releases)]:
        raise ValueError("The TeamCity record is not ordered by the catalog's release versions")
    ordered = ordered_releases(releases)
    _check_order(ordered, record["id"])
    for index, release in enumerate(ordered):
        where = f"{record['id']}: release {release['id']}"
        # The chapter is the base of everything else: its own heading and date
        # cell re-produce the id and the `ga` stored beside them, so a record
        # whose date no longer follows the row it carries is refused.
        stored = release_for(release["upstream"]["cells"])
        if release["milestones"]["ga"] != stored["milestones"]["ga"]:
            raise ValueError(f"{where} contradicts the release date cell it stores")
        expected, expected_provenance = derived_for(ordered, index, RULES)
        if release["milestones"] != expected:
            raise ValueError(f"{where} contradicts the catalog chapter it stores")
        provenance = release.get(derived.DERIVED_KEY)
        # The shared module owns the entry's shape and re-derives the date
        # beside it; the comparison below pins the rest of the entry — the
        # base, the sentence and the trigger this source's policy yields — so a
        # record can neither drop its rule nor substitute another one.
        derived.validate_milestone_provenance(release["milestones"], provenance, where, seen)
        for key in ("eos", "eol"):
            want = expected_provenance.get(key)
            got = (provenance or {}).get(key)
            if want is None:
                if got is not None:
                    raise ValueError(f"{where} derives a {key} whose trigger the catalog "
                                     f"does not publish")
                continue
            if got is None:
                raise ValueError(f"{where} publishes a derived {key} with no rule recorded for it")
            if got["base_date"] != want["base_date"] or got["base_label"] != want["base_label"]:
                raise ValueError(f"{where} measures its {key} from the wrong base date")
            if got["source_url"] != want["source_url"] or got["quote"] != want["quote"]:
                raise ValueError(f"{where} does not quote the vendor rule it applies")
            if got["trigger"]["release_id"] != want["trigger"]["release_id"]:
                raise ValueError(f"{where} names the wrong release as its {key} trigger")
            if got["trigger"]["date"] != want["trigger"]["date"]:
                raise ValueError(f"{where} states the wrong date for its {key} trigger")
            if got["trigger"]["label"] != want["trigger"]["label"]:
                raise ValueError(f"{where} describes its {key} trigger differently")


def record_for(releases, checked):
    """The published ``teamcity`` record for one complete catalog snapshot."""
    return {
        "$schema": RECORD_SCHEMA,
        "id": PRODUCT_ID,
        "name": PRODUCT_NAME,
        "category": "software",
        "upstream_category": UPSTREAM_CATEGORY,
        # JetBrains publishes no CPE or other identifier for the release lines,
        # and an invented one would be a claim the source never makes.
        "identifiers": [],
        # The vendor's own wording each milestone was read from.
        "labels": {"ga": RELEASE_DATE, "eos": EOS_LABEL, "eol": EOL_LABEL},
        "links": {"html": CATALOG_URL, "release cycle policy": POLICY_URL},
        "releases": releases,
        "provenance": {"source_url": CATALOG_URL, "verifier": VERIFIER,
                       "last_checked": checked, "upstream_modified": None},
    }


def retained(release):
    """A committed major line the current catalog no longer states.

    Republished from its own stored cells, so retention can never introduce a
    date JetBrains did not publish; the marker says only that this fetch's
    catalog lacks the chapter. Absence from the catalog is not an end of life.
    """
    return {**release, "upstream": {**release["upstream"], "in_source": False}}


def combine_releases(fresh, committed):
    """The complete major-line snapshot: this fetch's chapters plus retained history."""
    if committed is None:
        return list(fresh), []
    ids = {release["id"] for release in fresh}
    kept = [retained(release) for release in committed["releases"] if release["id"] not in ids]
    return list(fresh) + kept, [{"id": release["id"], "name": release["name"],
                                 "reason": "the current TeamCity catalog does not state this major "
                                           "line; the committed row and its dates are retained"}
                                for release in kept]


def committed_record(root):
    """The committed ``teamcity`` record, refusing one this source cannot own."""
    return transaction.committed_product_record(root, PRODUCT_ID, VERIFIER,
                                                validate_record, "TeamCity")


def report_for(releases, excluded, policy, kept, checked):
    """The per-row accounting this source publishes beside its record.

    ``seen`` is every catalog chapter this fetch read — the major lines it
    published plus the bugfix lines it accounted for instead, so the identity
    ``seen == published + excluded`` holds and no source row is dropped. The
    policy page is accounted the same way: ``policy_rows`` is the release-stage
    table's own parsed row count, so a row this record had not reviewed could
    never be missing from the total.
    """
    rules, others, policy_rows = policy
    retained_ids = {entry["id"] for entry in kept}
    fresh = [release for release in releases if release["id"] not in retained_ids]
    return {
        "source_url": CATALOG_URL,
        "policy_url": POLICY_URL,
        "verifier": VERIFIER,
        "checked_at": checked,
        "record_scope": ("TeamCity On-Premises major lines: one software record with one release "
                         "per major line the vendor's release catalog states, carrying the release "
                         "date it states as general availability and the two support-stage dates "
                         "the vendor's release-cycle policy derives from later releases"),
        "rows": {"seen": len(fresh) + len(excluded), "published": len(fresh),
                 "retained": len(kept), "excluded": len(excluded),
                 "derived_eos": sum(1 for release in releases if release["milestones"]["eos"]),
                 "derived_eol": sum(1 for release in releases if release["milestones"]["eol"])},
        "excluded": excluded,
        "retained": kept,
        "policy": {
            "url": POLICY_URL,
            "rules": [{"label": rules[key]["label"], "quote": rules[key]["quote"],
                       "text": rules[key]["text"]} for key in ("eos", "eol")],
            "labels": list(POLICY_LABELS),
            "rows": {"seen": policy_rows, "used": len(rules),
                     "not_dated": others},
        },
        "total_records": 1,
        "limitations": [
            "eos and eol are derived, not vendor-stated: the policy dates them by release event "
            "rather than by calendar, so each derived date carries the release that triggers it, "
            "the policy sentence and the base date in milestone_provenance, and is labelled "
            "derived wherever it is published.",
            "A major line whose triggering release has not been published yet keeps a null "
            "milestone: 2026.2 has neither, and 2026.1 has an end of sale but no end of support.",
            "eossec is absent for every line: JetBrains publishes no separate end of security "
            "support, and critical-issue patches before an end of sale are not one.",
            "The policy's 'usually released every four months' is cadence, and the roadmap's "
            "approximate 'end of 2026' for 2026.3 is a rough estimate; neither is a date, so no "
            "2026.3 release or transition is published from them.",
            "Bugfix (minor) release lines are accounted for as excluded rows: the vendor states "
            "lifecycle at major-version level, so a patch line carries none of its own.",
            "The catalog's older chapters state no release date for their first patch lines "
            "(3.1.1, 4.0.1 and later); those lines are excluded on the same grounds and no date "
            "is invented for them.",
            "A major line the current catalog no longer states is retained from the committed "
            "snapshot and marked upstream.in_source false; a dropped chapter is not an end of life.",
            "The official documentation index lists 2023.07 and 2023.09 documentation versions "
            "that the On-Premises release catalog does not state as release lines; they are not "
            "published here.",
        ],
    }


def import_teamcity(directory=None):
    """Fetch both pages and publish the ``teamcity`` record and report.

    Complete-or-nothing: the fetched snapshot is combined with the major lines
    the catalog no longer states, staged beside the committed catalog and
    validated there before anything is written. A parse failure, a reworded
    policy or an inconsistent catalog leaves every committed file untouched.
    """
    root = Path(directory) if directory is not None else ROOT / "data"
    # The committed ownership check runs before the fetch: a file this source
    # cannot publish aborts the run without a network call at all.
    committed = committed_record(root)
    checked = _now()
    policy = policy_rules(net.get_text(POLICY_URL))
    fresh, excluded = parse_catalog(net.get_text(CATALOG_URL))
    releases, kept = combine_releases(fresh, committed)
    releases = with_derived_milestones(releases, policy[0])
    record = record_for(releases, checked)
    validate_record(record)
    report = report_for(releases, excluded, policy, kept, checked)
    transaction.publish_product_record(record, report, root, REPORT)
    rows = report["rows"]
    return (f"imported {len(releases)} TeamCity On-Premises major lines "
            f"({rows['derived_eos']} derived end of sale, {rows['derived_eol']} derived end of "
            f"support); excluded {rows['excluded']} bugfix rows, retained {rows['retained']} "
            f"(data/{REPORT})")
