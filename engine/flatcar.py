"""Flatcar Container Linux Stable stream lifecycle, from the project's own feed.

Two authoritative pages make this record, and neither alone would be publishable:

* the project's channel documentation states *when* a Stable major version's
  support ends as an explicit release event — "Any Stable major version remains
  supported until a new major Stable version is released" — but attaches no
  calendar date to any version;
* the public release feed states every release's own publication timestamp, so
  the first Stable release of each major stream is dated to the day.

So the feed's stated date for a stream's first Stable release is published as
``ga``, and ``eol`` is published *derived*: the dated release the documented rule
names, carrying the rule sentence verbatim, the base date it is measured from,
and the triggering release's own id and date in ``milestone_provenance``. The
newest Stable major — the one no newer major has superseded — keeps a null
``eol``, and ``eos``/``eossec`` stay null for every stream: the project publishes
no end of sale and no separate end of security support.

Only Stable majors become releases. The feed's Alpha, Beta, Edge and LTS rows and
its channel-pointer rows are accounted for in the import report as excluded rows:
this record covers the Stable stream, whose lifecycle rule the channel
documentation states. The documentation's LTS rules — an 18 month support cycle
and a roughly yearly cadence — are *not* implemented: the LTS stream's own
release-to-stream history is not published as a structured lifecycle by either
page, and cadence is never a date.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

from . import derived, net, sources, transaction
from .importer import ROOT

# The registry owns the ids and the pages: a record's provenance must name a
# source this checkout installs, and the report must name the pages it read.
SOURCE = sources.source("import-flatcar")
VERIFIER = SOURCE.verifier
FEED_URL, POLICY_URL = (page.url for page in SOURCE.pages)
REPORT = SOURCE.report
RECORD_SCHEMA = "https://zarguell.github.io/eoltracker/v1/schema/product.json"
PRODUCT_ID = "flatcar-container-linux"
PRODUCT_NAME = "Flatcar Container Linux"
UPSTREAM_CATEGORY = "os"

# The rule the derived dates rest on, stored verbatim and required verbatim: a
# reworded or moved policy refuses the import rather than silently re-deriving
# under a new rule. It is the whole dated lifecycle the page publishes for the
# Stable stream, so the offline re-derivation needs no network fetch.
STABLE_RULE = ("Any Stable major version remains supported until a new major Stable "
               "version is released.")
RULE_LABEL = "Stable channel support window"
# What the rule's two dates are, in the source's own terms.
BASE_LABEL = "first Stable release"
TRIGGER_LABEL = "the next major Stable release"
# The page's own statements that are deliberately *not* turned into dates. They
# are recorded with the rule when the page states them verbatim, so a reader can
# see what was read and set aside; an absent one is simply a page that words it
# differently, not a failure, because neither licenses a date for this record.
NOT_DATED = (
    ("Each LTS major release stream has an 18 month support cycle, so there’s a 6 month "
     "overlap between new major releases.",
     "the LTS stream's own release-to-stream history is not published as a structured "
     "lifecycle, so the duration has no verified first-release base to measure from; this "
     "record covers the Stable stream"),
    ("New major releases come out around once per year, marking a new LTS stream, and there "
     "is an overlap where the old stream still gets critical security updates.",
     "cadence, not a date or a duration: a release interval is never converted into a "
     "deadline"),
)

# The feed's own declared columns, kept verbatim per published row, plus the
# version key the row is filed under. A row missing one of them refuses the
# parse; the feed's other columns (architectures, major_software, release_notes)
# are not lifecycle facts and are not stored.
CELLS = ("version", "channel", "release_date")
REQUIRED_ROW_KEYS = ("channel", "release_date")
FEED_TABLE = "releases.json"
# The one channel this record covers. Every other channel is accounted for in
# the report as an excluded row rather than silently skipped.
STABLE = "stable"
CHANNELS = ("alpha", "beta", "stable", "lts", "edge")
# ``4757.2.0``: the feed's own release key shape. A key of any other shape is a
# channel pointer (``current``, ``current-2024``), not a release row.
VERSION = re.compile(r"\d+\.\d+\.\d+\Z")
MAJOR = re.compile(r"\d+\Z")
# ``2026-09-14 12:19:07 +0000``, the only timestamp form the feed states.
TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} \+0000\Z")
TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S %z"
# The vendor's own wording each milestone was read from.
LABELS = {"ga": "release_date"}


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class _Text(HTMLParser):
    """The page's visible text, so a rule is matched against what it states."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.skip = 0
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self.skip:
            self.skip -= 1

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def page_text(html):
    """The page's text with tags and entities resolved and whitespace normalised."""
    parser = _Text()
    parser.feed(html)
    parser.close()
    return " ".join("".join(parser.parts).split())


def policy_rules(html):
    """The project's Stable support rule, verbatim, plus the rows it sets aside.

    The rule sentence is the evidence that licenses every derived ``eol``; a
    page that no longer states it word for word is a review, never a silent
    change to what this record derives. The statements the record refuses to
    date are recorded beside it when the page still carries them.
    """
    text = page_text(html)
    if STABLE_RULE not in text:
        raise ValueError(f"{POLICY_URL} no longer states the Stable support rule verbatim: "
                         f"{STABLE_RULE!r}")
    return {
        "label": RULE_LABEL,
        "quote": STABLE_RULE,
        "not_dated": [{"quote": quote, "reason": reason} for quote, reason in NOT_DATED
                      if quote in text],
    }


def release_day(text, where):
    """One feed timestamp -> the day it names, or a parse failure.

    The feed publishes a full instant, and the day it falls on is the date the
    project states it released the build. The stored cell keeps the timestamp
    verbatim; only its date component becomes a milestone.
    """
    if not isinstance(text, str) or not TIMESTAMP.fullmatch(text):
        raise ValueError(f"{where}: unrecognized release date {text!r}")
    try:
        return datetime.strptime(text, TIMESTAMP_FORMAT).date().isoformat()
    except ValueError as error:
        raise ValueError(f"{where}: release date {text!r} is not a real timestamp") from error


def row_for(key, row):
    """One feed row's declared columns, validated, or a refusal.

    The row's channel and release date are the vendor's own statements, so a row
    that states neither in the expected form refuses the parse instead of being
    reported as an excluded row that was never read.
    """
    where = f"{FEED_TABLE} row {key!r}"
    if not isinstance(row, dict):
        raise ValueError(f"{where}: not an object")
    missing = [name for name in REQUIRED_ROW_KEYS if name not in row]
    if missing:
        raise ValueError(f"{where}: the feed row states no {missing}")
    channel = row["channel"]
    if not isinstance(channel, str) or channel not in CHANNELS:
        raise ValueError(f"{where}: unrecognized release channel {channel!r}")
    return {"version": key, "channel": channel, "release_date": row["release_date"],
            "day": release_day(row["release_date"], where)}


def _key(entry):
    """One row's chronological key: its day, then its own timestamp."""
    return (entry["day"], entry["release_date"])


def parse_feed(payload):
    """Every feed row -> ``(releases, excluded, accounting)``; no row is dropped.

    The Stable rows are grouped into major streams and each stream's first Stable
    release — the earliest dated row of that major — becomes the published
    release, because the documented rule is stated about the *major* version. A
    later Stable build of the same major, a row of any other channel, and a
    channel-pointer row each go into ``excluded`` with its own reason, so the
    identity ``seen == published + excluded`` holds over the whole feed.
    """
    if not isinstance(payload, dict) or not payload:
        raise ValueError(f"{FEED_URL}: the release feed states no rows")
    entries = [(key, row_for(key, row)) for key, row in payload.items()]
    channels, stable = {}, {}
    for key, entry in entries:
        channels[entry["channel"]] = channels.get(entry["channel"], 0) + 1
        if VERSION.fullmatch(key) and entry["channel"] == STABLE:
            stable.setdefault(key.split(".")[0], []).append(entry)
    if not stable:
        raise ValueError(f"{FEED_URL}: the release feed states no Stable release")
    first = {major: min(rows, key=_key) for major, rows in stable.items()}
    dates = [entry["day"] for entry in first.values()]
    if len(set(dates)) != len(dates):
        raise ValueError(f"{FEED_URL}: two Stable major streams state the same release date; "
                         f"the 'new major Stable version' trigger would be ambiguous")
    excluded = []
    for key, entry in entries:
        if not VERSION.fullmatch(key):
            excluded.append({
                "page": FEED_URL, "row": key,
                "reason": "a channel pointer row rather than a release: the channel it points at "
                          "is published from that channel's own release rows"})
            continue
        if entry["channel"] != STABLE:
            excluded.append({
                "page": FEED_URL, "row": key,
                "reason": f"a {entry['channel']} channel release; this record covers the Stable "
                          f"stream, whose support rule the project's channel documentation states"})
            continue
        release = first[key.split(".")[0]]
        if release["version"] != key:
            excluded.append({
                "page": FEED_URL, "row": key,
                "reason": f"a later Stable build of major {release['version'].split('.')[0]}, whose "
                          f"first Stable release {release['version']} ({release['day']}) is the row "
                          f"published as that stream's general availability: a stream is one "
                          f"release, not one per build"})
    releases = [_release(major, entry) for major, entry in first.items()]
    releases.sort(key=lambda release: (release["milestones"]["ga"],
                                       int(release["id"])), reverse=True)
    accounting = {"seen": len(payload), "published": len(releases), "excluded": len(excluded),
                  "channels": dict(sorted(channels.items()))}
    return releases, excluded, accounting


def _release(major, entry):
    """One published Stable major stream, from the feed row that first states it."""
    return {
        "id": major,
        "name": f"{PRODUCT_NAME} {major}",
        "milestones": {"ga": entry["day"], "eos": None, "eossec": None, "eol": None},
        "upstream": {"name": entry["version"],
                     "cells": {name: entry[name] for name in CELLS},
                     "table": FEED_TABLE},
    }


def ordered_releases(releases):
    """Newest Stable major first, by the release date the feed states."""
    return sorted(releases, key=lambda release: (release["milestones"]["ga"],
                                                 int(release["id"])), reverse=True)


def derived_entry(release, trigger, rule):
    """One derived ``eol``'s provenance: the rule, its base and its trigger."""
    return {
        "kind": derived.KIND,
        "method": "release-trigger",
        "source_url": POLICY_URL,
        "quote": rule["quote"],
        "base_date": release["milestones"]["ga"],
        "base_label": BASE_LABEL,
        "trigger": {"release_id": trigger["id"],
                    "date": trigger["milestones"]["ga"],
                    "label": TRIGGER_LABEL},
    }


def derived_for(ordered, index, rule):
    """One stream's transitions, re-derived from the releases that follow it.

    Support ends when the next major Stable version is released, so the stream at
    *index* of the newest-first order derives from the stream at *index-1*. The
    newest stream has no successor and keeps a null ``eol``: the future release
    is not known, and the documented cadence dates nothing. The single function
    both publishing and offline validation call, so the two cannot disagree.
    """
    release = ordered[index]
    milestones = {"ga": release["milestones"]["ga"], "eos": None, "eossec": None, "eol": None}
    provenance = {}
    if index >= 1:
        trigger = ordered[index - 1]
        milestones["eol"] = trigger["milestones"]["ga"]
        provenance["eol"] = derived_entry(release, trigger, rule)
    return milestones, provenance


def with_derived_milestones(releases, rule):
    """Every derivable ``eol``, with the provenance that re-derives it.

    A stored snapshot's derived dates are recomputed, never carried: the trigger
    a stream derives from is whichever major the feed now publishes, so a newly
    published major fills the previous stream's ``eol``, and a stream no newer
    major has superseded keeps the null milestone rather than a stale date.
    """
    ordered = ordered_releases(releases)
    for index, release in enumerate(ordered):
        milestones, provenance = derived_for(ordered, index, rule)
        release["milestones"] = milestones
        if provenance:
            release[derived.DERIVED_KEY] = provenance
        else:
            release.pop(derived.DERIVED_KEY, None)
    return ordered


def _stored_row(release, where):
    """One stored release's feed cells, validated, with its own day and version."""
    upstream = release.get("upstream")
    cells = upstream.get("cells") if isinstance(upstream, dict) else None
    if (not isinstance(cells, dict) or set(cells) != set(CELLS)
            or upstream.get("table") != FEED_TABLE):
        raise ValueError(f"{where}: the release does not store its feed row's cells")
    version = cells["version"]
    if not isinstance(version, str) or not VERSION.fullmatch(version):
        raise ValueError(f"{where}: the stored row states no release version: {version!r}")
    if cells["channel"] != STABLE:
        raise ValueError(f"{where}: the stored row is not a Stable release")
    return version, release_day(cells["release_date"], where)


def validate_record(record):
    """Rebuild every stored stream and derived date from its own cells, offline.

    Offline, the record's own cells are the whole evidence: each stream's ``ga``
    is re-read from the feed row it stores, the stream order is re-sorted from
    those dates, and ``eol`` is re-derived from the triggering major that order
    yields. A milestone, a trigger or a quote that no longer follows its own
    stored cells is never published.
    """
    if (record["id"] != PRODUCT_ID or record["provenance"]["verifier"] != VERIFIER
            or record["provenance"]["source_url"] != FEED_URL):
        raise ValueError("Invalid Flatcar source identity")
    if record["labels"] != LABELS:
        raise ValueError("Invalid Flatcar label evidence")
    releases, seen = [], set()
    for release in record["releases"]:
        where = f"{PRODUCT_NAME} {release.get('id')}"
        if release["id"] in seen or not MAJOR.fullmatch(release["id"]):
            raise ValueError(f"{where}: release does not name its own major stream")
        seen.add(release["id"])
        version, day = _stored_row(release, where)
        if release["upstream"]["name"] != version or version.split(".")[0] != release["id"]:
            raise ValueError(f"{where}: release contradicts the feed row it stores")
        if release["upstream"].get("in_source") not in (None, False):
            raise ValueError(f"{where}: release carries an invalid retention marker")
        if release["milestones"]["ga"] != day:
            raise ValueError(f"{where} contradicts the release date cell it stores")
        releases.append(release)
    if [release["id"] for release in releases] != [release["id"] for release in
                                                   ordered_releases(releases)]:
        raise ValueError("The Flatcar record is not ordered by the feed's release dates")
    rule = {"quote": STABLE_RULE}
    ordered = ordered_releases(releases)
    for index, release in enumerate(ordered):
        where = f"{PRODUCT_ID}: release {release['id']}"
        expected, expected_provenance = derived_for(ordered, index, rule)
        if release["milestones"] != expected:
            raise ValueError(f"{where} contradicts the feed row it stores")
        provenance = release.get(derived.DERIVED_KEY)
        # The shared module owns the entry's shape and re-derives the date beside
        # it; the comparison below pins the rest of the entry — the base, the
        # sentence and the trigger this source's rule yields — so a record can
        # neither drop its rule nor substitute another one.
        derived.validate_milestone_provenance(release["milestones"], provenance, where, seen)
        want = expected_provenance.get("eol")
        got = (provenance or {}).get("eol")
        if want is None:
            if got is not None:
                raise ValueError(f"{where} derives an end of life whose triggering release the "
                                 f"feed does not publish")
            continue
        if got is None:
            raise ValueError(f"{where} publishes a derived end of life with no rule recorded "
                             f"for it")
        if got["base_date"] != want["base_date"] or got["base_label"] != want["base_label"]:
            raise ValueError(f"{where} measures its end of life from the wrong base date")
        if got["source_url"] != want["source_url"] or got["quote"] != want["quote"]:
            raise ValueError(f"{where} does not quote the project rule it applies")
        if got["trigger"]["release_id"] != want["trigger"]["release_id"]:
            raise ValueError(f"{where} names the wrong major as its end-of-life trigger")
        if got["trigger"]["date"] != want["trigger"]["date"]:
            raise ValueError(f"{where} states the wrong date for its end-of-life trigger")
        if got["trigger"]["label"] != want["trigger"]["label"]:
            raise ValueError(f"{where} describes its end-of-life trigger differently")


def record_for(releases, checked):
    """The published ``flatcar-container-linux`` record for one feed snapshot."""
    return {
        "$schema": RECORD_SCHEMA,
        "id": PRODUCT_ID,
        "name": PRODUCT_NAME,
        "category": "software",
        "upstream_category": UPSTREAM_CATEGORY,
        # The project publishes no CPE or other identifier for the release
        # streams, and an invented one would be a claim the source never makes.
        "identifiers": [],
        # The feed's own wording for the one date each stream states.
        "labels": dict(LABELS),
        "links": {"html": FEED_URL, "channel documentation": POLICY_URL},
        "releases": releases,
        "provenance": {"source_url": FEED_URL, "verifier": VERIFIER,
                       "last_checked": checked, "upstream_modified": None},
    }


def retained(release):
    """A committed stream the current feed no longer states, marked as such.

    Republished from its own stored cells, so retention can never introduce a
    date the feed did not publish; the marker says only that this fetch's feed
    lacks the row. Absence from the feed is not an end of life.
    """
    return {**release, "upstream": {**release["upstream"], "in_source": False}}


def combine_releases(fresh, committed):
    """The complete stream snapshot: this fetch's majors plus retained history."""
    if committed is None:
        return list(fresh), []
    ids = {release["id"] for release in fresh}
    kept = [retained(release) for release in committed["releases"] if release["id"] not in ids]
    return list(fresh) + kept, [{"id": release["id"], "name": release["name"],
                                 "reason": "the current Flatcar release feed does not state this "
                                           "major stream; the committed row and its dates are "
                                           "retained"}
                                for release in kept]


def committed_record(root):
    """The committed ``flatcar-container-linux`` record, refusing one this source cannot own."""
    return transaction.committed_product_record(root, PRODUCT_ID, VERIFIER,
                                               validate_record, PRODUCT_NAME)


def report_for(releases, excluded, accounting, rule, kept, checked):
    """The per-row accounting this source publishes beside its record.

    ``seen`` is every feed row this fetch read — the Stable majors it published
    plus every row it accounted for instead, so the identity ``seen == published
    + excluded`` holds and no source row is dropped.
    """
    retained_ids = {entry["id"] for entry in kept}
    fresh = [release for release in releases if release["id"] not in retained_ids]
    return {
        "source_url": FEED_URL,
        "policy_url": POLICY_URL,
        "verifier": VERIFIER,
        "checked_at": checked,
        "record_scope": ("Flatcar Container Linux Stable major streams: one software record with "
                         "one release per Stable major version the project's release feed "
                         "publishes, carrying that stream's first Stable release date as general "
                         "availability and the release date of the next major Stable version, as "
                         "the channel documentation's support rule derives it, as end of life"),
        "rows": {"seen": accounting["seen"], "published": len(fresh), "retained": len(kept),
                 "excluded": accounting["excluded"],
                 "derived_eol": sum(1 for release in releases if release["milestones"]["eol"])},
        "channels": accounting["channels"],
        "excluded": excluded,
        "retained": kept,
        "policy": {
            "url": POLICY_URL,
            "rules": [{"label": rule["label"], "quote": rule["quote"]}],
            "not_dated": rule["not_dated"],
        },
        "total_records": 1,
        "limitations": [
            "eol is derived, not vendor-stated: the channel documentation dates the Stable "
            "stream's support end by release event rather than by calendar, so each derived date "
            "carries the release that triggers it, the rule sentence and the base date in "
            "milestone_provenance and is labelled derived wherever it is published.",
            "The newest Stable major keeps a null end of life: no newer major Stable version has "
            "been released, so the rule names no trigger.",
            "eos and eossec are null for every stream: the project publishes no end of sale and no "
            "separate end of security support.",
            "Only the Stable channel is published. Alpha, Beta, Edge and LTS feed rows are "
            "excluded with their channel named, and channel-pointer rows are excluded as pointers "
            "rather than releases.",
            "The LTS stream is not modelled: the documented 18 month support cycle has no "
            "structured first-release-per-stream history to measure from, and the roughly yearly "
            "LTS cadence is a release interval, never a date.",
            "Only each Stable major's first release is published: a stream is one release "
            "identity, so its later builds are accounted for as excluded rows and a permalink to a "
            "stream keeps resolving.",
            "The millisecond-free publication timestamp the feed states is read at the day "
            "precision its date component carries; the raw cell is kept verbatim beside it.",
            "A major stream the current feed no longer states is retained from the committed "
            "snapshot and marked upstream.in_source false; a dropped row is not an end of life.",
        ],
    }


def import_flatcar(directory=None):
    """Fetch both pages and publish the Flatcar record and report.

    Complete-or-nothing: the fetched snapshot is combined with the streams the
    feed no longer states, staged beside the committed catalog and validated
    there before anything is written. A parse failure, a reworded rule or an
    inconsistent feed leaves every committed file untouched.
    """
    root = Path(directory) if directory is not None else ROOT / "data"
    # The committed ownership check runs before the fetch: a file this source
    # cannot publish aborts the run without a network call at all.
    committed = committed_record(root)
    checked = _now()
    rule = policy_rules(net.get_text(POLICY_URL))
    fresh, excluded, accounting = parse_feed(net.get_json(FEED_URL))
    releases, kept = combine_releases(fresh, committed)
    releases = with_derived_milestones(releases, rule)
    record = record_for(releases, checked)
    validate_record(record)
    report = report_for(releases, excluded, accounting, rule, kept, checked)
    transaction.publish_product_record(record, report, root, REPORT)
    rows = report["rows"]
    return (f"imported {rows['published']} Flatcar Container Linux Stable major streams "
            f"({rows['derived_eol']} derived end of life); excluded {rows['excluded']} feed rows, "
            f"retained {rows['retained']} (data/{REPORT})")
