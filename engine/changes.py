"""Observed Opengear catalog and lifecycle changes as a ledger and an Atom feed.

Two things change under a vendor lifecycle integration, and they are never the
same claim:

* the vendor **catalog** — the exact model strings the configurator sells
  (`record.catalog.listed`), and
* the vendor **lifecycle notices** — the end-of-sale and end-of-support rows
  that publish real dates (`record.lifecycle.listed` plus the matched lifecycle
  record ids, and the lifecycle rows themselves).

`update_history()` diffs two snapshots of one source's hardware records and
appends only what it observed:

* `catalog_added` / `catalog_removed` when `record.catalog.listed` becomes true
  or stops being true — whether the record is still published with
  `listed: false` or is no longer in the snapshot at all, because a catalog
  record is retained after the configurator drops it;
* `announcement` when a notice now matches an exact catalog model
  (`record.lifecycle.listed` false -> true), or when a lifecycle row the
  previous snapshot did not carry appears;
* `notice_change` when a published notice is withdrawn
  (`record.lifecycle.listed` true -> false) or resolves to a different set of
  lifecycle records — what is published changed, so the dates that notice
  carried go with it;
* `date_change` when a published milestone date is different in the new
  snapshot: a correction, or a date the source *cleared* (after `null`).

One event states one thing: the listing, what is published about a record, or
the dates it publishes. A notice arriving or leaving owns the dates it brought,
so withdrawing one notice is a single event rather than a withdrawal plus four
cleared dates, and a record missing from a snapshot is reported as missing
rather than as every one of its dates being cleared.

A missing value is `null` (not captured / not published), never a date, so a
date is only ever reported when the record itself carries it. The ledger keeps
its events in append order and never edits one; a transition that reverses
later (unlisted -> listed again, or a corrected date put back) mints a new
event with its own identifier instead of rewriting the old one.

Ledger contract (`data/opengear-changes.json`), the return value of
`update_history()`:

    {
      "version": 1,
      "checked_at": "2026-09-17T11:00:00Z",   # this observation
      "baseline_at": "2026-09-17T11:00:00Z",  # when the comparison baseline was seeded
      "events": [
        {
          "id": "tag:eoltracker,2026:changes-<record>-<kind>-<sha256:16>",
          "record_id": "opengear-om2200-0123456789ab",
          "name": "OM2200",
          "observed_at": "2026-09-17T11:00:00Z",
          "kind": "announcement" | "notice_change" | "date_change" | "catalog_added" | "catalog_removed",
          "changes": {"<field>": {"before": <json>, "after": <json>}},
          "source_urls": ["https://opengear.com/..."]
        }
      ]
    }

Field names are `record.present`, `catalog.listed`, `lifecycle.listed`,
`lifecycle.matches` and `milestones.<ga|eos|eossec|eol>`. `observed_at` is when
the change was observed — the caller's `checked` snapshot time — and never a
milestone date. Event ids are a stable SHA-256 over the record, the kind, the
change values and the observation time, so re-running an unchanged import
appends nothing and a reversal is a distinct event.

The first run of all (`history is None`, or a ledger with no `baseline_at`)
seeds the baseline and appends no event: the notices that were already
published when the ledger started are not news. Every later run is a real
comparison — an empty previous snapshot then reports the records that appeared,
because that snapshot was observed and it was empty. Callers pass the records
of one source, in the order the vendor's own tables present them;
`hardware.publish_records()` returns exactly the records one verifier owns:

    previous = hardware.get_records()                 # before publishing
    ledger = changes.load_history()                   # None on the first run
    ledger = changes.update_history(previous, records, checked, ledger)
    hardware.publish_records(records, "deterministic-opengear")
    dump(changes.HISTORY_PATH, ledger)                 # after a successful publish

`build()` writes two observational documents below `_site` (or `out_dir`):

* `v1/changes.json`  the ledger as a feed document, newest event first;
* `v1/changes.atom`  RFC 4287, one `entry` per observation.

There is no iCalendar document: these are observations, not deadlines, and a
calendar entry dated by the day a vendor edited a page would be a fabricated
timeline. The Atom feed has its own permanent identity
(`tag:eoltracker,2026:opengear-lifecycle-changes`) and each entry links to the
hardware record page it is about rather than to a date.
"""
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

from .feeds import TAG_PREFIX, generated_at
from .importer import ROOT
from .site_config import HARDWARE_MILESTONES, SITE_URL, human_date, site_url

DEFAULT_OUT = ROOT / "_site"
HISTORY_PATH = ROOT / "data" / "opengear-changes.json"

# The ledger's own format version, not the catalog's.
LEDGER_VERSION = 1
# RFC 3339, seconds, UTC: the only shape an observation timestamp is stored in.
OBSERVED_AT = "%Y-%m-%dT%H:%M:%SZ"

# A separate, permanent feed identity (RFC 4151): this document syndicates
# observations, not deadlines, so it must never share the id of the upcoming
# milestone feed, and no entry may share an id with a milestone event.
CHANGES_FEED_ID = TAG_PREFIX + "opengear-lifecycle-changes"
CHANGES_FEED_TITLE = "EOL Tracker — Opengear catalog and lifecycle changes"
CHANGES_FEED_SUBTITLE = ("Observed changes to the exact models the Opengear product configurator lists and to the "
                         "end-of-sale and end-of-support records published for them. A catalog listing is not a "
                         "support entitlement and catalog disappearance is not an end of life.")
AUTHOR = "EOL Tracker"
GENERATOR = "EOL Tracker"

FEED_PATHS = {
    "json": Path("v1/changes.json"),
    "atom": Path("v1/changes.atom"),
}

# The five statements a change can make. `notice_change` covers a notice
# withdrawn or resolving elsewhere, and `date_change` only a published date that
# is different: neither ever implies an end of sale.
KIND_LABELS = {
    "announcement": "announcement observed",
    "notice_change": "published notices changed",
    "date_change": "published dates changed",
    "catalog_added": "added to the vendor catalog",
    "catalog_removed": "removed from the vendor catalog",
}

RECORD_PRESENT = "record.present"
CATALOG_LISTED = "catalog.listed"
LIFECYCLE_LISTED = "lifecycle.listed"
LIFECYCLE_MATCHES = "lifecycle.matches"

MILESTONE_KEYS = tuple(milestone["key"] for milestone in HARDWARE_MILESTONES)
MILESTONE_LABELS = {milestone["key"]: milestone["label"] for milestone in HARDWARE_MILESTONES}
FIELD_LABELS = {
    RECORD_PRESENT: "Record in the source table",
    CATALOG_LISTED: "Vendor catalog listing",
    LIFECYCLE_LISTED: "Publication matching this exact model",
    LIFECYCLE_MATCHES: "Matched lifecycle records",
    **{f"milestones.{key}": MILESTONE_LABELS[key] for key in MILESTONE_KEYS},
}
# One wording per field family, so a summary reads as a sentence and never
# prints a bare Python value.
PRESENCE_VALUES = {True: "present", False: "absent", None: "not captured"}
LISTING_VALUES = {True: "listed", False: "not listed", None: "not captured"}
NOTICE_VALUES = {True: "published", False: "not published", None: "not captured"}


def _clean(value):
    """One line of printable text: no control characters, single spaces."""
    return re.sub(r"\s+", " ", re.sub(r"[\x00-\x1f\x7f]", " ", str(value))).strip()


def _moment(value):
    """One observation timestamp as an aware UTC datetime.

    Accepts an RFC 3339 string (what the collector writes) or an aware
    datetime. An absent timestamp raises: an observed change with no
    observation time would have to be dated from the vendor data instead, and
    those dates are not observations.
    """
    if isinstance(value, datetime):
        moment = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return moment.astimezone(timezone.utc).replace(microsecond=0)
    text = str(value or "").strip()
    if not text:
        raise ValueError("An observation timestamp is required (RFC 3339 date-time)")
    moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).replace(microsecond=0)


def _stamp(value):
    """One observation timestamp in the stored shape."""
    return _moment(value).strftime(OBSERVED_AT)


def _index(records):
    """The snapshot keyed by record id, rejecting an ambiguous snapshot."""
    index = {}
    for record in records or ():
        record_id = record["id"]
        if record_id in index:
            raise ValueError(f"Duplicate hardware record id {record_id!r} in one snapshot")
        index[record_id] = record
    return index


def _verifiers(records):
    """The source verifiers a snapshot publishes, in any accepted shape."""
    values = records.values() if isinstance(records, dict) else (records or ())
    return {record["provenance"]["verifier"] for record in values if (record.get("provenance") or {}).get("verifier")}


def _scoped(before, after):
    """The comparison baseline: the previous records of the snapshot's sources.

    One `data/hardware/` tree publishes several sources side by side (`eosl.date`
    and Opengear are separate verifiers), and a refresh only replaces the records
    of its own verifier. So the baseline keeps the previous records the current
    snapshot's sources own: a foreign record's absence is not a change this
    ledger observed. A snapshot that publishes no source at all states nothing
    about ownership, so it is compared whole rather than filtered to nothing.
    """
    scopes = _verifiers(after)
    if not scopes:
        return before
    return {record_id: record for record_id, record in before.items()
            if record_id in after or (record.get("provenance") or {}).get("verifier") in scopes}


def _catalog(record):
    catalog = (record or {}).get("catalog")
    return catalog if isinstance(catalog, dict) else None


def _listed(record):
    """`catalog.listed`, or None when this snapshot states no listing at all."""
    catalog = _catalog(record)
    if catalog is None or "listed" not in catalog:
        return None
    return bool(catalog["listed"])


def _noticed(record):
    """`lifecycle.listed`, or None when this snapshot states no notice state."""
    lifecycle = (record or {}).get("lifecycle")
    if not isinstance(lifecycle, dict) or "listed" not in lifecycle:
        return None
    return bool(lifecycle["listed"])


def _matches(record):
    """The matched lifecycle record ids, deduplicated and ordered.

    Sorted because the order a collector resolved matches in is not a claim the
    vendor makes; without that, a reordered list would read as a change.
    """
    lifecycle = (record or {}).get("lifecycle")
    values = lifecycle.get("matches") if isinstance(lifecycle, dict) else None
    if not isinstance(values, (list, tuple)):
        return []
    return sorted({str(value) for value in values})


def _milestones(record):
    milestones = (record or {}).get("milestones") or {}
    return {key: milestones.get(key) for key in MILESTONE_KEYS}


def _change(before, after):
    return {"before": before, "after": after}


def _notice_changes(noticed_before, noticed_after, matches_before, matches_after):
    changes = {LIFECYCLE_LISTED: _change(noticed_before, noticed_after)}
    if matches_before != matches_after:
        changes[LIFECYCLE_MATCHES] = _change(matches_before, matches_after)
    return changes


def _milestone_changes(prior, present):
    before_milestones, after_milestones = _milestones(prior), _milestones(present)
    return {f"milestones.{key}": _change(before_milestones[key], after_milestones[key])
            for key in MILESTONE_KEYS if before_milestones[key] != after_milestones[key]}


def _events_for(prior, present):
    """Every change one record id produced, as `(kind, changes)` pairs.

    `prior` and `present` are the record as the previous and current snapshots
    published it, or None when that snapshot did not carry it. A record is named
    by an identity that never depends on the vendor's dates, so a correction
    reads as a change to one record rather than the death of one record and the
    birth of another.

    One event states one thing: the catalog listing, what is published about it,
    or the dates it publishes — and a notice arriving or leaving owns the dates
    it brought with it, so withdrawing a notice is one event rather than a
    withdrawal plus four cleared dates. `published` holds those deltas when both
    snapshots carried the record; a record missing from a snapshot is reported
    as missing instead of as all of its dates being cleared.
    """
    events = []
    listed_before, listed_after = _listed(prior), _listed(present)
    noticed_before, noticed_after = _noticed(prior), _noticed(present)
    matches_before, matches_after = _matches(prior), _matches(present)
    published = _milestone_changes(prior, present) if prior is not None and present is not None else {}
    catalog_record = _catalog(prior) is not None or _catalog(present) is not None

    # A catalog listing is a listing, in both directions. None here means the
    # snapshot stated nothing, so a record that was never listed is not an
    # addition and a record that gained an unlisted state is not a removal: only
    # a statement can change. A listed record the current snapshot dropped
    # entirely is a removal too — the collector retains the record, so a listing
    # that is gone from the data is gone from the catalog.
    if listed_after is True and listed_before is not True:
        events.append(("catalog_added", {CATALOG_LISTED: _change(listed_before, listed_after)}))
    elif listed_before is True and listed_after is not True:
        events.append(("catalog_removed", {CATALOG_LISTED: _change(listed_before, listed_after)}))

    # An exact notice for an exact model appearing is the announcement; a notice
    # withdrawn, or resolving to different records, is a change to what is
    # published. Neither is an end of sale, and neither is reported as a date
    # change: the dates belong to the notice that stated them.
    if noticed_after is True and noticed_before is not True:
        changes = _notice_changes(noticed_before, noticed_after, matches_before, matches_after)
        changes.update(published)
        events.append(("announcement", changes))
    elif noticed_before is True and noticed_after is not True:
        changes = _notice_changes(noticed_before, noticed_after, matches_before, matches_after)
        changes.update(published)
        events.append(("notice_change", changes))
    elif matches_before != matches_after:
        changes = {LIFECYCLE_MATCHES: _change(matches_before, matches_after)}
        changes.update(published)
        events.append(("notice_change", changes))
    # A lifecycle row appears and disappears; a catalog record never does,
    # because the collector retains it and reports its listing above instead.
    elif not catalog_record and prior is None:
        events.append(("announcement", {RECORD_PRESENT: _change(False, True)}))
    elif not catalog_record and present is None:
        events.append(("notice_change", {RECORD_PRESENT: _change(True, False)}))
    # A published date that is different — corrected, or cleared to null — is a
    # change only where the record was already published and is still there. An
    # absent date is never filled in from anywhere.
    elif published:
        events.append(("date_change", published))
    return events


def _sources(*records):
    """The source URLs the change can be checked against, first seen first."""
    urls = []
    for record in records:
        if not record:
            continue
        candidates = [(_catalog(record) or {}).get("source_url")]
        candidates.extend((record.get("provenance") or {}).get("source_urls") or ())
        for url in candidates:
            if isinstance(url, str) and url and url not in urls:
                urls.append(url)
    return urls


def _event_id(record_id, kind, changes, observed_at):
    """A stable, permanent identifier for one observed change (RFC 4151).

    The digest covers the record, the kind, the exact before/after values and
    the observation time, so it identifies *this* observation: the same change
    observed again on the same run is the same event, and a reversal (or the
    same correction made on a later day) is a different one.
    """
    payload = json.dumps({"record_id": record_id, "kind": kind, "changes": changes, "observed_at": observed_at},
                         ensure_ascii=False, sort_keys=True)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
    return f"{TAG_PREFIX}changes-{record_id}-{kind}-{digest}"


def _event(record_id, kind, changes, observed_at, name, source_urls):
    return {
        "id": _event_id(record_id, kind, changes, observed_at),
        "record_id": record_id,
        "name": name,
        "observed_at": observed_at,
        "kind": kind,
        "changes": changes,
        "source_urls": source_urls,
    }


def update_history(previous, current, checked, history=None):
    """Append the changes observed between two snapshots of one source.

    `previous` and `current` are that source's hardware records before and after
    a refresh (lists of the published record dicts), `checked` is the RFC 3339
    observation time of the refresh, and `history` is the ledger this function
    returned last time (or None when no run has been recorded yet). The returned
    ledger is a new object: the events already in `history` are carried over
    untouched and the new ones are appended, deduplicated by identifier.

    The first run seeds the baseline (`baseline_at`) and appends no event:
    historical notices are not re-announced, and on a source whose first
    snapshot is the whole vendor catalog every record would otherwise look like
    it was announced that day. Every later run is a real comparison, including
    one whose previous snapshot was empty, which reports the records that
    appeared. Raises `ValueError` if a snapshot carries one record id twice or
    if `checked` is not a timestamp.
    """
    observed_at = _stamp(checked)
    before, after = _index(previous), _index(current)
    before = _scoped(before, after)
    ledger = history if isinstance(history, dict) else {}
    events = [event for event in (ledger.get("events") or ()) if isinstance(event, dict) and event.get("id")]
    known = {event["id"] for event in events}
    appended = []
    if ledger.get("baseline_at"):
        for record_id in sorted(set(before) | set(after)):
            prior, present = before.get(record_id), after.get(record_id)
            name = _clean((present or prior).get("name") or record_id)
            sources = _sources(present, prior)
            for kind, changes in _events_for(prior, present):
                event = _event(record_id, kind, changes, observed_at, name, sources)
                if event["id"] in known:
                    continue
                known.add(event["id"])
                appended.append(event)
    return {
        "version": LEDGER_VERSION,
        "checked_at": observed_at,
        "baseline_at": ledger.get("baseline_at") or observed_at,
        "events": events + appended,
    }


def load_history(path=None):
    """The persisted ledger, or None when no run has been recorded yet."""
    target = Path(path) if path is not None else HISTORY_PATH
    if not target.exists():
        return None
    return json.loads(target.read_text(encoding="utf-8"))


def _render(field, value):
    """One side of a change as the feed prints it, never as a raw value."""
    if field == RECORD_PRESENT:
        return PRESENCE_VALUES.get(value, str(value))
    if field == CATALOG_LISTED:
        return LISTING_VALUES.get(value, str(value))
    if field == LIFECYCLE_LISTED:
        return NOTICE_VALUES.get(value, str(value))
    if field == LIFECYCLE_MATCHES:
        if value is None:
            return "not captured"
        return ", ".join(value) if value else "none"
    if field.startswith("milestones."):
        return "not published" if value is None else f"{human_date(value)} ({value})"
    return str(value)


def _phrase(field, change):
    before, after = _render(field, change.get("before")), _render(field, change.get("after"))
    return f"{FIELD_LABELS.get(field, field)} {before} → {after}"


def _entry(event):
    """One observation as the Atom entry and JSON record it is published as."""
    name = event.get("name") or event.get("record_id")
    kind = str(event.get("kind") or "")
    phrases = [_phrase(field, change) for field, change in (event.get("changes") or {}).items()]
    summary = f"{name} — {'; '.join(phrases)}." if phrases else f"{name}."
    summary += f" Observed {event.get('observed_at')} UTC."
    sources = [url for url in (event.get("source_urls") or ()) if url]
    if sources:
        summary += " Sources: " + " ".join(sources)
    return {
        "id": event["id"],
        "record_id": event.get("record_id"),
        "kind": kind,
        "title": f"{name} — {KIND_LABELS.get(kind, kind)}",
        "updated": event.get("observed_at"),
        # Canonical link: every change is about one hardware record's page.
        "url": site_url(f"hardware/{event.get('record_id')}/"),
        "summary": summary,
    }


def _order(event):
    return (str(event.get("observed_at") or ""), str(event.get("record_id") or ""),
            str(event.get("kind") or ""), str(event.get("id") or ""))


def _maybe_stamp(value):
    """One observation timestamp, or None when the ledger carries no usable one."""
    try:
        return _stamp(value)
    except (ValueError, TypeError):
        return None


def _updated(ledger, events):
    """The feed's update instant: the latest observation, never a deadline.

    Every candidate is an observation time the ledger recorded — an event's, or
    the run's own — so the feed is never dated by the snapshot and never by a
    milestone date. A ledger with neither still gets a timestamp: the current
    feed snapshot time, which is the moment this document was built.
    """
    stamps = [stamp for stamp in (_maybe_stamp(event.get("observed_at")) for event in events) if stamp]
    stamps += [stamp for stamp in (_maybe_stamp(ledger.get(key)) for key in ("checked_at", "baseline_at")) if stamp]
    return max(stamps) if stamps else _stamp(generated_at())


def changes_document(ledger, events, updated):
    """The published JSON document: the ledger contract, newest event first.

    The document is a superset of the stored ledger — same `version`,
    `checked_at`, `baseline_at` and `events` — plus the feed identity and its
    update instant, so a reader of the HTTP endpoint and a reader of the file
    are reading the same shape.
    """
    document = {key: value for key, value in ledger.items() if key != "events"}
    document.update({
        "version": LEDGER_VERSION,
        "id": CHANGES_FEED_ID,
        "title": CHANGES_FEED_TITLE,
        "subtitle": CHANGES_FEED_SUBTITLE,
        "home": SITE_URL,
        "updated": updated,
        "count": len(events),
        "events": [dict(event) for event in events],
    })
    return document


def atom_feed(events, updated):
    """RFC 4287 document: one entry per observed change, newest first."""
    lines = [
        '<?xml version="1.0" encoding="utf-8"?>',
        '<feed xmlns="http://www.w3.org/2005/Atom" xml:lang="en">',
        f"  <id>{escape(CHANGES_FEED_ID)}</id>",
        f"  <title>{escape(CHANGES_FEED_TITLE)}</title>",
        f"  <subtitle>{escape(CHANGES_FEED_SUBTITLE)}</subtitle>",
        f"  <updated>{escape(updated)}</updated>",
        f'  <link rel="self" type="application/atom+xml" href={quoteattr(site_url("v1/changes.atom"))}/>',
        f'  <link rel="alternate" type="text/html" href={quoteattr(SITE_URL)}/>',
        f"  <author><name>{escape(AUTHOR)}</name></author>",
        f'  <generator uri={quoteattr(SITE_URL)}>{escape(GENERATOR)}</generator>',
    ]
    for event in events:
        entry = _entry(event)
        lines.extend([
            "  <entry>",
            f"    <id>{escape(entry['id'])}</id>",
            f"    <title>{escape(entry['title'])}</title>",
            f"    <updated>{escape(entry['updated'])}</updated>",
            f'    <link rel="alternate" type="text/html" href={quoteattr(entry["url"])}/>',
            f'    <category term={quoteattr(entry["kind"])} '
            f'label={quoteattr(KIND_LABELS.get(entry["kind"], entry["kind"]))}/>',
            f'    <summary type="text">{escape(entry["summary"])}</summary>',
            "  </entry>",
        ])
    lines.append("</feed>")
    return "\n".join(lines) + "\n"


def validate_ledger(ledger):
    """Refuse a ledger that would publish duplicate or malformed entries (#114).

    The published document is what consumers key on, so two events with one
    identifier would be one event to every reader — a duplicate Atom `id`, a
    duplicate JSON entry — and a missing or non-tag identifier would publish an
    entry nothing can address. The ledger is validated before anything is
    written, so a bad ledger fails the build instead of reaching `_site/`.

    Returns the usable events in the ledger's stored order.
    """
    if ledger is None:
        return []
    if not isinstance(ledger, dict):
        raise ValueError(f"Change ledger is not an object: {type(ledger).__name__}")
    if "version" in ledger and ledger["version"] != LEDGER_VERSION:
        raise ValueError(f"Change ledger version {ledger['version']!r} is not {LEDGER_VERSION}")
    events = []
    seen = {}
    for index, event in enumerate(ledger.get("events") or ()):
        if not isinstance(event, dict) or not event.get("id"):
            raise ValueError(f"Change ledger event {index} has no id")
        event_id = event["id"]
        if not isinstance(event_id, str) or not event_id.startswith(TAG_PREFIX):
            raise ValueError(f"Change ledger event {index} id is not a permanent tag URI: {event_id!r}")
        if event_id in seen:
            raise ValueError(f"Duplicate change ledger event id {event_id!r} at index {index} "
                             f"(first at {seen[event_id]})")
        seen[event_id] = index
        events.append(event)
    return events


def _write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def build(history, out_dir=None):
    """Write `v1/changes.json` and `v1/changes.atom` below `_site` (or `out_dir`).

    `history` is the ledger `update_history()` returned (the persisted
    `data/opengear-changes.json`), or an empty mapping when no run has been
    recorded. The ledger is validated — version, identifier shape and
    uniqueness — before either document is written, so a duplicate identifier
    is refused rather than published as a duplicate Atom entry. Events are
    published newest first, with observation timestamps; no snapshot time is
    invented when the ledger carries one. Returns the event count, the update
    timestamp and the written paths.
    """
    ledger = history if isinstance(history, dict) else {}
    events = validate_ledger(ledger)
    events.sort(key=_order, reverse=True)
    updated = _updated(ledger, events)
    documents = {
        "json": json.dumps(changes_document(ledger, events, updated), ensure_ascii=False, indent=2) + "\n",
        "atom": atom_feed(events, updated),
    }
    out = Path(out_dir) if out_dir is not None else DEFAULT_OUT
    written = []
    for name, document in documents.items():
        path = out / FEED_PATHS[name]
        _write(path, document)
        written.append(str(path))
    return {"events": len(events), "updated": updated, "files": written}
