"""openEuler community release lifecycle, from the community's own sources.

Five official, public, unauthenticated sources make this record, and none of
them alone would be publishable:

* the release-catalog API (``www.openeuler.org/api/mirrors/``) enumerates the
  repository identities the community currently ships and marks each one LTS or
  innovation — but states no release or end-of-life date, and omits historical
  releases the community announced in writing;
* the download page states, on the release cards it renders, an explicit
  month-precision ``Planned EOL`` for the service packs it currently serves;
* the lifecycle page states the community's support rules as durations and
  release triggers — six months of community support for an innovation release,
  nine for a minor service pack, twenty-four for a major one — under an explicit
  effective date of August 2025;
* the 24.03 LTS SP4 technical white paper states each release's own general
  availability as an exact calendar day;
* the two release announcements date the two releases whose general
  availability the sources do not agree on.

So the catalog API's identities are published, the white paper's stated days
become ``ga``, the release cards' stated months become ``eol``, and one date is
published *derived*: the six-month innovation window applied to the innovation
release the rule's own effective date covers, carrying the rule sentence
verbatim, the release date it is measured from and the duration in
``milestone_provenance``.

**What is deliberately not published.** ``eos`` and ``eossec`` are null for every
release: the community publishes no end of sale, and its
full-support-to-maintenance-support boundary is a real transition that still
fixes critical and high-severity CVEs, so it is not an end of security support.
The six-year LTS lifetime is read and set aside: its sentence carries an optional
two-year extension and the policy lets an initial LTS release end half a year to
one year early, so no terminal date here is certain. The ``ga`` of ``24.03 LTS``
and of ``24.03 LTS SP4`` stay absent because the sources date them differently —
the paper's day, the lifecycle component's month and an announcement's own
dateline — and the disagreement is pinned with each side's verbatim quote, so a
relocated or reworded one refuses the import rather than letting the surviving
date be published silently.

The white paper is a PDF, so this module carries a bounded extractor for that
document's own construction: FlateDecode content streams, object streams, a page
tree in ``/Kids`` order, and text shown through Identity-H or WinAnsi fonts with
ToUnicode CMaps. It reads text, not layout, and refuses a page or font it cannot
decode rather than returning a shorter release history.
"""
from __future__ import annotations

import json
import multiprocessing
import re
import zlib
from datetime import date, datetime, timezone
from pathlib import Path

try:
    import resource
except ImportError:                                   # pragma: no cover - non-POSIX platform
    resource = None

from . import derived, net, sources, transaction
from .importer import ROOT

# The registry owns the ids and the pages: a record's provenance must name a
# source this checkout installs, and the report must name the pages it read.
SOURCE = sources.source("import-openeuler")
VERIFIER = SOURCE.verifier
DOWNLOAD_URL, API_URL, LIFECYCLE_URL, WHITEPAPER_URL, ANNOUNCEMENT_2403, ANNOUNCEMENT_SP4 = (
    page.url for page in SOURCE.pages)
REPORT = SOURCE.report
RECORD_SCHEMA = "https://zarguell.github.io/eoltracker/v1/schema/product.json"
PRODUCT_ID = "openeuler"
PRODUCT_NAME = "openEuler"
UPSTREAM_CATEGORY = "os"

# The vendor's own wording for each milestone this record publishes, and the
# table each release's own cells were read from.
LABELS = {"ga": "release history", "eol": "Planned EOL"}
API_TABLE = "release catalog API RepoVersion"
HISTORY_TABLE = "technical white paper release history"
CARD_TABLE = "download page release card"
# The release card's own field label, kept verbatim beside the value it states.
CARD_FIELD = "Planned EOL"
# ``2027/03``: the only form a release card states a planned end of life in.
CARD_MONTH = re.compile(r"(\d{4})/(\d{2})\Z")
# ``On May 30, 2024,`` and the paper's one mid-sentence lowercase ``on December
# 30, 2025,``: the only forms the release history dates a release in.
HISTORY_DAY = re.compile(r"(?i)\bon (January|February|March|April|May|June|July|August|"
                         r"September|October|November|December) (\d{1,2}), (\d{4}),")
# The dated statements in the paper's history that are not release statements.
# The community's own establishment is dated in the same paragraph style as its
# releases, so it is named here with the prose around it and set aside; any
# *other* dated statement that names no release still refuses the parse, so a
# rewrite of the history cannot quietly shrink the record.
NON_RELEASE = (
    (re.compile(r"openEuler open source community was officially established", re.I),
     "the community's own establishment, not a release of it"),
)
MONTHS = {name: number for number, name in enumerate(
    ("January", "February", "March", "April", "May", "June", "July", "August",
     "September", "October", "November", "December"), 1)}
# The paper states its release history in the opening section, in consecutive
# pages before the chapters that describe the release's technology rather than
# its dates. The run of pages that carry dated release statements is discovered
# rather than pinned, and a run that is interrupted — a dated statement after a
# page that has none — refuses the import, because a statement this reader
# skipped would silently shrink the history.
HISTORY_GAP = "the release history's pages are not consecutive"

# The community's support rules, stored verbatim and required verbatim: a
# reworded or moved rule refuses the import rather than silently re-deriving
# under a policy the community no longer states. They are read from the
# lifecycle page's own content component, which carries the prose the page
# renders.
INNOVATION_RULE = ("Innovation releases (effective from August 2025): Released in September every "
                   "year with 6 months of community support.")
EFFECTIVE_RULE = ("LTS releases (effective from August 2025): Released every 4 years with 4 years "
                  "of community support.")
FULL_LIFECYCLE_RULE = ("The full lifecycle of an LTS release is 6 years (4 years of full support "
                       "and 2 years of maintenance support).")
EXTENSION_RULE = ("Prior to the end of this lifecycle, a joint maintenance team may be assembled to "
                  "request an optional 2-year extension.")
SP_RULE = ("In principle, the lifecycle for service pack (SP) updates within an LTS release is "
           "9 months for minor SPs (released in June, optional) or 24 months for major SPs "
           "(released in December).")
SP0_RULE = ("By default, the lifecycle of an initial LTS release (SP0) follows that of a major SP, "
            "but could end half a year to 1 year in advance based on a review of its usage in the "
            "community and community rules.")
MAINTENANCE_RULE = ("Maintenance or extended support is limited to fixes for critical or "
                    "high-severity CVEs and bugs.")
# The month the LTS and innovation rules are stated to take effect from. The
# lifecycle component states ``August 2025``; a release before it is not covered
# by these rules and carries no date this record derives from them.
EFFECTIVE = "2025-08-01"
# The label the report files the applied rule under, the base it measures from,
# and the window itself.
INNOVATION_LABEL = "Innovation release support window"
BASE_LABEL = "general availability"
INNOVATION_MONTHS = 6
# The service-pack durations the policy states, in its own calendar units, keyed
# by the kind the policy's own parenthetical pairs with a release month.
SP_MONTHS = {"minor": 9, "major": 24}
SP_KINDS = {"06": "minor", "12": "major"}

# The statements the record reads and sets aside, each with the reason it
# licenses no date here. Recorded beside the rule when the page still carries
# them, so a reader can see what was read and refused; an absent one means the
# page words it differently, not a failure, because none of them licenses a date
# this record could otherwise publish.
NOT_DATED = (
    (FULL_LIFECYCLE_RULE,
     "the six-year LTS lifetime is stated under an effective date of August 2025, and the policy "
     "also lets an initial LTS release end half a year to 1 year before its major SP, so no "
     "release here has a certain terminal date from this sentence"),
    (SP0_RULE,
     "the sentence permits an initial LTS release to end six to twelve months early by review, so "
     "no terminal date for an initial LTS release is certain"),
    (EXTENSION_RULE,
     "the extension is optional and neither its grant nor its terminal date is stated, so it never "
     "shortens or lengthens a published date"),
    (MAINTENANCE_RULE,
     "maintenance support still fixes critical and high-severity CVEs, so this boundary is not an "
     "end of security support and eossec stays null"),
)

# The two general availabilities the sources state differently. Each hold stores
# every side's exact quote; the import verifies each one is still stated where
# the hold names it, so a source that moved or reworded one side refuses the run
# instead of letting the surviving date be published as if the sources agreed.
# Nothing here invents a date: the paper's own day is still stored in the
# release's history cell and only the ``ga`` milestone stays absent.
DISPUTED_GA = {
    "community:24.03:": {
        "reason": "the sources state different general availabilities for openEuler 24.03 LTS: "
                  "the technical white paper dates the release to May 30, 2024, the lifecycle "
                  "component says only that it was released in June 2024, and the community's own "
                  "release announcement carries a June 6, 2024 dateline; the sources define no "
                  "artifact-date versus launch-event-date distinction, so no day is published",
        "evidence": (
            {"source_url": WHITEPAPER_URL,
             "quote": "On May 30, 2024, openEuler 24.03 LTS was released."},
            {"source_url": LIFECYCLE_URL,
             "quote": "The latest openEuler 24.03 LTS was released in June 2024 (kernel 6.6)."},
            {"source_url": ANNOUNCEMENT_2403,
             "quote": "[Beijing, China, June 6, 2024]"},
        ),
    },
    "community:24.03:sp4": {
        "reason": "the sources state different general availabilities for openEuler 24.03 LTS SP4: "
                  "the technical white paper dates the release to June 30, 2026, while the "
                  "community's own release announcement is dated July 1, 2026 and says the release "
                  "is now available; the sources define no artifact-date versus announcement-date "
                  "distinction, so no day is published",
        "evidence": (
            {"source_url": WHITEPAPER_URL,
             "quote": "On June 30, 2026, openEuler 24.03 LTS SP4 was officially released as an "
                      "enhanced and extended update to openEuler 24.03 LTS, built on Linux kernel "
                      "6.6."},
            {"source_url": ANNOUNCEMENT_SP4, "quote": "openEuler 2026-07-01"},
            {"source_url": ANNOUNCEMENT_SP4,
             "quote": "OpenAtom openEuler 24.03 LTS SP4 is now available."},
        ),
    },
}

# The community release line and the separately catalogued embedded line. Each is
# one identity; architectures and scenarios are delivery forms of the same
# release and are never releases of their own.
COMMUNITY = "community"
EMBEDDED = "embedded"
# ``openEuler 24.03 LTS SP4`` and ``openEuler-24.03-LTS-SP4``: the prose and the
# API forms of one identity. The suffix group is greedy, so the longest name at a
# position wins and a reference to ``openEuler 24.03 LTS`` inside a sentence
# about ``openEuler 24.03 LTS SP4`` is not read as that sentence's subject.
COMMUNITY_NAME = re.compile(r"openEuler[-\s](\d{2}\.\d{2})(?:[-\s]LTS)?"
                            r"(?:[-\s](SP\d|64kb))?\b")
# The flavours a community version name may carry after its own version: a
# service pack, or the 64 KB-page kernel build the community ships separately.
SUFFIXES = tuple(f"sp{number}" for number in range(1, 8)) + ("64kb",)
EMBEDDED_NAME = re.compile(r"openEuler[-\s]Embedded[-\s](\d{2}\.\d{2})\b")
# The page's prose is Markdown: emphasis markers are folded away so a stored
# quote is the sentence a reader sees.
MARKDOWN = re.compile(r"\*+|`+")
# A PDF line break inside a hyphenated word, which the rendered page shows as one
# word; prose is joined before a quote is stored.
HYPHEN_BREAK = re.compile(r"(?<=[a-z])-\s+(?=[a-z])")


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _identity(line, version, suffix):
    """One release identity: its line, its version and its flavour suffix."""
    return (line, version, suffix)


def key_string(key):
    """An identity's stable string form, used by the report and its holds."""
    return f"{key[0]}:{key[1]}:{key[2] or ''}"


def parse_key(text):
    """An identity back from its stable string form, or ``None`` for a foreign one.

    The dispute holds are keyed by the string form because they are stored on a
    release's upstream row, so the form has to be readable back: a key that names
    no line, no version or a version the community's own naming never yields is
    not an identity this source can hold a dispute about.
    """
    parts = text.split(":")
    if len(parts) != 3 or parts[0] not in (COMMUNITY, EMBEDDED):
        return None
    if not re.fullmatch(r"\d{2}\.\d{2}", parts[1]):
        return None
    if parts[2] and parts[2] not in SUFFIXES:
        return None
    return _identity(parts[0], parts[1], parts[2] or None)


def release_id(key, lts):
    """One identity's release id, in the catalog's slug vocabulary.

    Only a catalog row's own LTS flag inserts ``lts``: a release the API omits
    keeps the id its name gives, because the sources that state it publish no
    LTS flag and one would be a claim they never make.
    """
    parts = [key[1]]
    if lts:
        parts.append("lts")
    if key[2]:
        parts.append(key[2])
    if key[0] == EMBEDDED:
        parts.insert(0, EMBEDDED)
    return "-".join(parts)


def display_name(key, lts):
    """One identity's published name, as the community's own name text reads."""
    if key[0] == EMBEDDED:
        return f"{PRODUCT_NAME} Embedded {key[1]}"
    parts = [PRODUCT_NAME, key[1]]
    if lts:
        parts.append("LTS")
    if key[2]:
        parts.append(key[2].upper())
    return " ".join(parts)


def identity_of(release):
    """One stored release's identity and LTS flag, re-read from its own cells."""
    row = catalog_row(release["upstream"])
    if row is not None:
        return row["key"], row["lts"]
    history = release["upstream"].get("history")
    if history:
        return history_key(history.get("quote"), release["id"]), None
    raise ValueError(f"{release['id']}: the release names no openEuler identity")


def _identity_of_text(text):
    """The identity a vendor-written name states, or ``None`` when it states none.

    A *whole* name (a catalog version, a release card's ``id``) must match
    completely; a *mention* inside prose is matched from its own start and may be
    followed by more sentence, which is what lets ``scan_names`` find every
    identity a paragraph names.
    """
    for pattern, line in ((EMBEDDED_NAME, EMBEDDED), (COMMUNITY_NAME, COMMUNITY)):
        match = pattern.fullmatch(text)
        if match is not None:
            suffix = match.group(2) if pattern is COMMUNITY_NAME else None
            return _identity(line, match.group(1), suffix.lower() if suffix else None)
    return None


def _mention(text):
    """The identity a run of text opens with, for scanning a longer sentence."""
    match = EMBEDDED_NAME.match(text)
    if match is not None:
        return _identity(EMBEDDED, match.group(1), None), match
    match = COMMUNITY_NAME.match(text)
    if match is None:
        return None, None
    suffix = match.group(2)
    return _identity(COMMUNITY, match.group(1), suffix.lower() if suffix else None), match


def scan_names(text):
    """Every identity a piece of the vendor's own text names, in order.

    Longest match wins at each position, so a name that merely mentions an older
    release is not mistaken for the release the sentence is about. Returns
    ``(position, key, matched text)`` triples.
    """
    found, position = [], 0
    while position < len(text):
        index = text.find("openEuler", position)
        if index < 0:
            break
        key, match = _mention(text[index:])
        if match is None:
            position = index + len("openEuler")
            continue
        found.append((index, key, match.group(0)))
        position = index + match.end()
    return found


# --- the release catalog API ----------------------------------------------


def parse_api(payload):
    """The release catalog's own rows, keyed by identity.

    The API's ``FileInfo.ModTime`` is the zero time, so it is stored and never
    trusted for revision detection; the rows are the identities. A row that
    states no version, no LTS flag or no scenario/architecture list refuses the
    parse instead of being dropped.
    """
    if not isinstance(payload, dict) or not isinstance(payload.get("RepoVersion"), list):
        raise ValueError(f"{API_URL}: the release catalog states no RepoVersion rows")
    rows = payload["RepoVersion"]
    if not rows:
        raise ValueError(f"{API_URL}: the release catalog states no releases")
    catalog = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError(f"{API_URL}: a release catalog row is not an object")
        version = row.get("Version")
        key = _identity_of_text(version) if isinstance(version, str) else None
        if key is None:
            raise ValueError(f"{API_URL}: unrecognized release catalog version {version!r}")
        if key in catalog:
            raise ValueError(f"{API_URL}: the release catalog states {version!r} twice")
        if not isinstance(row.get("LTS"), bool):
            raise ValueError(f"{API_URL}: {version!r} states no LTS flag")
        for column in ("Scenario", "Arch"):
            values = row.get(column)
            if (not isinstance(values, list) or not values
                    or not all(isinstance(value, str) and value for value in values)):
                raise ValueError(f"{API_URL}: {version!r} states no {column} list")
        catalog[key] = {
            "name": version, "lts": row["LTS"],
            "cells": {"Version": version, "LTS": row["LTS"],
                      "Scenario": list(row["Scenario"]), "Arch": list(row["Arch"])},
        }
    return catalog


def catalog_row(upstream):
    """One stored release's catalog cells, re-read offline, or ``None``.

    A release the API does not state stores an empty cell set and no table, so
    the two are read together: a stored catalog row must name one identity and
    one LTS flag, and a release that claims a catalog table must carry its cells.
    """
    if not isinstance(upstream, dict):
        raise ValueError("the release stores no source row")
    cells = upstream.get("cells")
    if not isinstance(cells, dict):
        raise ValueError("the release does not store its source cells")
    if not cells:
        if upstream.get("table") is not None:
            raise ValueError("the release claims a catalog table but stores no cells")
        return None
    if upstream.get("table") != API_TABLE:
        raise ValueError("the release does not store its catalog row's table")
    if set(cells) != {"Version", "LTS", "Scenario", "Arch"}:
        raise ValueError("the release does not store the catalog row's columns")
    version = cells["Version"]
    key = _identity_of_text(version) if isinstance(version, str) else None
    if key is None:
        raise ValueError(f"stored catalog row states no release version: {version!r}")
    if not isinstance(cells["LTS"], bool):
        raise ValueError("stored catalog row states no LTS flag")
    for column in ("Scenario", "Arch"):
        values = cells[column]
        if (not isinstance(values, list) or not values
                or not all(isinstance(value, str) and value for value in values)):
            raise ValueError(f"stored catalog row states no {column} list")
    return {"name": version, "lts": cells["LTS"], "cells": cells, "key": key}


# --- the download page -----------------------------------------------------


def _text_of(html):
    """A page fragment's text, with tags dropped and whitespace folded."""
    return " ".join(re.sub(r"<[^>]+>", " ", html).split())


def card_month(value, where):
    """One release card's ``YYYY/MM`` planned end of life, as an ISO month."""
    if not isinstance(value, str) or not CARD_MONTH.fullmatch(value):
        raise ValueError(f"{where}: unrecognized planned end of life {value!r}")
    year, month = value.split("/")
    try:
        date(int(year), int(month), 1)
    except ValueError as error:
        raise ValueError(f"{where}: {value!r} is not a real calendar month") from error
    return f"{year}-{month}"


def parse_cards(html):
    """The download page's rendered release cards, and its embedded item list.

    Each rendered card is one row: the identity its ``id`` names, the card's own
    subtitle text, and the ``Planned EOL`` value it states verbatim (absent when
    the card states none, as the embedded release's card does). A card that
    states a ``Planned EOL`` in a form this parser does not read refuses the
    parse rather than silently publishing no end of life.
    """
    cards = []
    for chunk in html.split('<div class="download-version-card" id="')[1:]:
        name = chunk.split('"', 1)[0]
        key = _identity_of_text(name)
        if key is None:
            raise ValueError(f"{DOWNLOAD_URL}: release card {name!r} does not name one release")
        if any(card["key"] == key for card in cards):
            raise ValueError(f"{DOWNLOAD_URL}: release card {name!r} is rendered twice")
        subtitle = re.search(r'<p class="subtitle"[^>]*>(.*?)</p>', chunk, re.S)
        text = _text_of(subtitle.group(1)) if subtitle else ""
        stated = re.search(re.escape(CARD_FIELD) + r":\s*(\d{4}/\d{2})(?:\s|\.|$)", text)
        if CARD_FIELD in text and stated is None:
            raise ValueError(f"{DOWNLOAD_URL}: release card {name!r} states an unrecognized "
                             f"{CARD_FIELD}: {text!r}")
        cards.append({"name": name, "key": key, "text": text,
                      "value": stated.group(1) if stated else None})
    if not cards:
        raise ValueError(f"{DOWNLOAD_URL}: the page renders no release cards")
    return cards, item_list(html)


def item_list(html):
    """The download page's embedded JSON-LD release list, as ``{verbatim name: value}``.

    The page embeds an older rendering of its own catalog beside the cards it
    renders. It is *not* read for milestones — the rendered cards lead — but it
    is read so every row it states can be disclosed, and a value it states
    differently from a card refuses the import rather than being passed over.
    An absent list is not a failure: the page may stop embedding one, and no
    milestone depends on it either way.
    """
    for block in re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.S):
        try:
            document = json.loads(block)
        except json.JSONDecodeError:
            continue
        for node in document if isinstance(document, list) else [document]:
            if not isinstance(node, dict) or node.get("@type") != "ItemList":
                continue
            rows = {}
            for item in node.get("itemListElement") or []:
                if not isinstance(item, dict) or not isinstance(item.get("name"), str):
                    continue
                stated = re.search(r"Planned EOL:\s*(\d{4}/\d{2})",
                                   item.get("description") or "")
                rows[item["name"]] = stated.group(1) if stated else None
            if rows:
                return rows
    return {}


def listing_name(name):
    """An embedded item's name with the page's own trailing qualifier removed.

    The list spells a card ``openEuler 24.03 LTS SP3 Long-Term Supported
    Version``: the version is the identity and the rest is the card's own
    classification text, so only the identity survives into the comparison.
    """
    return re.sub(r"\s+Long-Term Supported Versions?\Z", "", name).strip()


def listing_conflicts(cards, listing):
    """Where the page's two renderings of its own catalog disagree, row by row.

    A value the embedded list states differently from the rendered card refuses
    the import: two renderings of one field that no longer agree is a
    disagreement a reader has to be told about, not a value to pick a winner
    from. A row only one of the two renderings carries is disclosed instead,
    because the list is refreshed on a different schedule than the cards.
    """
    rendered = {card["key"]: card for card in cards}
    seen = {}
    for name, value in sorted(listing.items()):
        key = _identity_of_text(listing_name(name))
        if key is None:
            raise ValueError(f"{DOWNLOAD_URL}: the embedded item list names {name!r}, which is not "
                             f"a release")
        if key in seen:
            raise ValueError(f"{DOWNLOAD_URL}: the embedded item list states {name!r} twice")
        seen[key] = value
    conflicts = []
    for key, value in sorted(seen.items(), key=lambda item: key_string(item[0])):
        card = rendered.get(key)
        if card is None:
            conflicts.append({
                "surface": DOWNLOAD_URL, "rendering": "embedded JSON-LD item list",
                "kind": "not_rendered", "identity": key_string(key),
                "reason": "the page's embedded item list states this release but the cards it "
                          "renders do not; the list is an older rendering of the catalog and is "
                          "not read for milestones",
                "stated": value})
        elif card["value"] is not None and value is not None and card["value"] != value:
            raise ValueError(f"{DOWNLOAD_URL}: the rendered card and the embedded item list state "
                             f"different planned end of life values for {card['name']!r}: "
                             f"{card['value']!r} and {value!r}")
    for key, card in sorted(rendered.items(), key=lambda item: key_string(item[0])):
        if card["value"] is not None and seen and key not in seen:
            conflicts.append({
                "surface": DOWNLOAD_URL, "rendering": "rendered release card",
                "kind": "not_listed", "identity": key_string(key),
                "reason": "the rendered card states a planned end of life the page's embedded "
                          "item list does not carry; the card leads and is what this record "
                          "publishes",
                "stated": card["value"]})
    return conflicts


# --- the lifecycle component ----------------------------------------------


def lifecycle_component(html):
    """The lifecycle page's own content component, discovered from its markup.

    The page's prose is not server-rendered: it is supplied by a
    content-hashed script component the page references. The component is
    discovered from the page rather than pinned to today's hash, so a new hash is
    followed instead of a stale copy being read.
    """
    match = re.search(r'href="(/assets/chunks/TheLifecycle[^"]+\.js)"', html)
    if match is None:
        raise ValueError(f"{LIFECYCLE_URL} no longer references its lifecycle component")
    return "https://www.openeuler.org" + match.group(1)


def component_prose(script):
    """The English lifecycle prose the component renders, with Markdown folded.

    The component carries both locales of the same two sections, the English one
    defined first inside ``D={...}``. Each section is taken in document order, and
    ``policy_rules`` then requires the English rule sentence verbatim: a component
    that reorders or translates its sections fails that check loudly instead of
    quietly publishing a rule read from the other locale.
    """
    pieces = {}
    for match in re.finditer(r"\b(overall|lts):`((?:[^`\\]|\\.)*)`", script):
        text = match.group(2).replace("\\n", " ").replace("\\`", "`").replace("\\'", "'")
        pieces.setdefault(match.group(1), []).append(text)
    if not pieces.get("overall") or not pieces.get("lts"):
        raise ValueError(f"{LIFECYCLE_URL}: its lifecycle component states no rule sections")
    prose = " ".join([pieces["overall"][0], pieces["lts"][0]])
    return " ".join(MARKDOWN.sub("", prose).split())


def policy_rules(prose):
    """The community's rules, verbatim, plus the statements they set aside.

    A sentence the page no longer states word for word is a review, never a
    silent change to what this record derives or refuses to derive: the applied
    rule licenses the one derived date, and each set-aside statement is recorded
    beside it while the page still carries it.
    """
    for quote in (INNOVATION_RULE, EFFECTIVE_RULE):
        if quote not in prose:
            raise ValueError(f"{LIFECYCLE_URL} no longer states its rule verbatim: {quote!r}")
    return {
        "url": LIFECYCLE_URL,
        "effective_from": EFFECTIVE,
        "rules": [{"label": INNOVATION_LABEL, "quote": INNOVATION_RULE}],
        "not_dated": [{"quote": quote, "reason": reason} for quote, reason in NOT_DATED
                      if quote in prose],
    }


def innovation_window(ga, key, lts):
    """The one date this source derives, or ``None`` when no rule licenses one.

    The innovation window is stated under an effective date, so it is applied
    only to a release that effective date covers, only to a release the catalog
    marks innovation, and only where the release day it is measured from is
    stated. Everything else keeps a null end of life rather than a date the
    policy does not license.
    """
    if lts is not False or key[0] != COMMUNITY or key[2] is not None or not ga or ga < EFFECTIVE:
        return None
    return derived.add_duration(ga, INNOVATION_MONTHS, "month")


def service_pack_kind(day):
    """The policy's own kind for a service pack released on ``day``.

    The rule pairs the duration with the release month it names — June for a
    minor pack, December for a major one — so the release the history states
    decides which duration the policy applies to it. A pack released in neither
    month has no stated kind and is not cross-checked.
    """
    return SP_KINDS.get((day or "")[5:7])


# --- the technical white paper --------------------------------------------


def parse_history(document):
    """The white paper's release history: one dated statement per release.

    A statement runs from its own dated anchor to the next one, and the release
    it dates is the first identity it names. The paper's one dated non-release
    statement is named in ``NON_RELEASE`` and set aside with its reason; any other
    dated statement that names no release refuses the parse, so a rewrite of the
    history cannot quietly shrink the record. Two statements dating one release
    refuse it too, because which of them is the release's date would be unclear.
    """
    pages = pdf_pages(document)
    dated = [index for index, page in enumerate(pages) if HISTORY_DAY.search(page)]
    if not dated:
        raise ValueError(f"{WHITEPAPER_URL}: the release history states no dated release")
    # The history is a consecutive run of pages at the paper's front. A dated
    # statement separated from it by an undated page would be one this reader
    # silently skipped, so the gap refuses the import.
    if dated != list(range(dated[0], dated[-1] + 1)):
        raise ValueError(f"{WHITEPAPER_URL}: {HISTORY_GAP}")
    # A line break inside a hyphenated word is a wrap, not a hyphen, so each page
    # is joined before its lines are collapsed; pages are then joined the same
    # way, because a statement the paper carries across a page break reads as one
    # sentence.
    text = " ".join(" ".join(HYPHEN_BREAK.sub("-", page).split())
                    for page in pages[dated[0]:dated[-1] + 1])
    anchors = list(HISTORY_DAY.finditer(text))
    statements, set_aside = [], []
    for index, anchor in enumerate(anchors):
        end = anchors[index + 1].start() if index + 1 < len(anchors) else len(text)
        segment = text[anchor.start():end]
        names = scan_names(segment)
        if not names:
            # The community's establishment is dated mid-sentence, so the
            # statement a reader sees carries the clause before the date; only
            # that one check looks at it, and a named release must still be the
            # first identity *after* the anchor.
            lead = text[max(0, anchor.start() - 120):anchor.start()]
            for pattern, reason in NON_RELEASE:
                match = pattern.search(lead)
                if match:
                    set_aside.append({"quote": match.group(0), "reason": reason})
                    break
            else:
                raise ValueError(f"{WHITEPAPER_URL}: the release history dates an unnamed "
                                 f"statement: {segment[:140]!r}")
            continue
        position, key, matched = names[0]
        # The stored quote is the whole statement as the paper states it — its
        # date, its subject and the sentence that carries the subject — so the
        # release's own cells re-read offline without the PDF. The statement ends
        # at the first sentence boundary after the subject, because the paper
        # elaborates on the release in the sentences that follow and those carry
        # no date of their own.
        tail = segment[position + len(matched):]
        stop = re.search(r"\.\s", tail)
        quote = (segment[:position + len(matched) + stop.end()] if stop else segment).strip()
        when = _history_day(anchor, f"{HISTORY_TABLE} statement for {key_string(key)}")
        statements.append({"key": key, "name": matched, "date": when, "quote": quote})
    if not statements:
        raise ValueError(f"{WHITEPAPER_URL}: the release history states no dated release")
    subjects = [key_string(statement["key"]) for statement in statements]
    if len(set(subjects)) != len(subjects):
        raise ValueError(f"{WHITEPAPER_URL}: the release history dates a release twice")
    return ({statement["key"]: statement for statement in statements}, set_aside)


def _history_day(anchor, where):
    """One history statement's own date, as an ISO day."""
    try:
        return date(int(anchor.group(3)), MONTHS[anchor.group(1)],
                    int(anchor.group(2))).isoformat()
    except ValueError as error:
        raise ValueError(f"{where}: {anchor.group(0)!r} is not a real calendar day") from error


def history_key(quote, where):
    """One stored history quote's subject identity, re-read offline.

    The statement's date leads the quote, so the subject is the first identity
    the quote names rather than its first word; the release's own stored name is
    checked against it beside this.
    """
    if not isinstance(quote, str):
        raise ValueError(f"{where}: the release stores no release-history statement")
    names = scan_names(quote)
    if not names:
        raise ValueError(f"{where}: stored release-history statement names no release: {quote!r}")
    return names[0][1]


def history_day(quote, where):
    """One stored history quote's own date, re-read offline."""
    if not isinstance(quote, str):
        raise ValueError(f"{where}: the release stores no release-history statement")
    anchor = HISTORY_DAY.match(quote)
    if anchor is None:
        raise ValueError(f"{where}: stored release-history statement states no release date: "
                         f"{quote!r}")
    return _history_day(anchor, where)


# A bounded PDF reader for the construction this document uses. It reads text,
# not layout: a page whose content stream or fonts it cannot decode is reported
# as undecodable rather than silently contributing fewer sentences.

PDF_OBJECT = re.compile(rb"(?<![0-9])(\d+)\s+(\d+)\s+obj\b")
PDF_STREAM = re.compile(rb"stream\r?\n")
PDF_FONT = re.compile(rb"/Type\s*/Font\b")
PDF_PAGE = re.compile(rb"/Type\s*/Page[^s]")

# Hard bounds on the reader, stated as constants so a crafted or compromised
# document refuses by name instead of consuming the refresh. Every one is far
# above the white paper's own construction (≈5.2 MB, ≈10 600 objects, 95 pages,
# ≈3.2 MB of decoded object/font/page streams) and far below what a
# decompression bomb or an unbounded page-tree walk would need.
MAX_PDF_BYTES = 32 * 1024 * 1024
MAX_PDF_OBJECTS = 200_000
MAX_PDF_PAGES = 20_000
MAX_STREAM_BYTES = 16 * 1024 * 1024
MAX_DECODED_BYTES = 64 * 1024 * 1024
MAX_CMAP_ENTRIES = 100_000
MAX_RANGE_SPAN = 10_000
MAX_TREE_DEPTH = 64
# The isolated parse's own wall-clock and hard resource ceilings. The reader
# itself runs in a child process so a pathological document cannot exhaust the
# refresh's memory or CPU, and so the parent survives whatever the child does.
PDF_TIMEOUT = 60
PDF_CPU_SECONDS = 60
PDF_ADDRESS_SPACE = 768 * 1024 * 1024


class _Budget:
    """The one place the reader's cumulative resource bounds are spent."""

    def __init__(self):
        self.decoded = MAX_DECODED_BYTES

    def spend(self, size, where):
        """Charge ``size`` decoded bytes, refusing a document past the budget."""
        if size > self.decoded:
            raise ValueError(
                f"{WHITEPAPER_URL}: the document's decoded streams exceed the "
                f"{MAX_DECODED_BYTES}-byte budget while reading {where}; a decompression bomb "
                f"is refused rather than expanded")
        self.decoded -= size


def _pdf_objects(data, budget):
    """Every indirect object of the document, with object streams expanded.

    The object count is bounded, and every object stream's expansion is charged
    to the decode budget, so a document that declares a huge object count or
    carries a decompression bomb refuses by name before it is expanded.
    """
    objects = {}
    for match in PDF_OBJECT.finditer(data):
        end = data.find(b"endobj", match.end())
        if end >= 0:
            objects[int(match.group(1))] = data[match.end():end]
            if len(objects) > MAX_PDF_OBJECTS:
                raise ValueError(
                    f"{WHITEPAPER_URL}: the document states more than {MAX_PDF_OBJECTS} indirect "
                    f"objects; a crafted object table is refused rather than expanded")
    for number, body in list(objects.items()):
        if b"/ObjStm" not in body:
            continue
        raw = _deflate(body, budget, f"object stream {number}")
        if raw is None:
            continue
        count = int(re.search(rb"/N\s+(\d+)", body).group(1))
        first = int(re.search(rb"/First\s+(\d+)", body).group(1))
        if count > MAX_PDF_OBJECTS or first > len(raw):
            raise ValueError(
                f"{WHITEPAPER_URL}: object stream {number} declares {count} objects at offset "
                f"{first} past its own {len(raw)} decoded bytes")
        header = raw[:first].split()
        if len(header) < 2 * count:
            raise ValueError(f"{WHITEPAPER_URL}: object stream {number} states {len(header) // 2} "
                             f"of its declared {count} objects")
        pairs = [(int(header[2 * i]), int(header[2 * i + 1])) for i in range(count)]
        for index, (object_number, offset) in enumerate(pairs):
            start = first + offset
            stop = first + pairs[index + 1][1] if index + 1 < len(pairs) else len(raw)
            objects.setdefault(object_number, raw[start:stop])
            if len(objects) > MAX_PDF_OBJECTS:
                raise ValueError(
                    f"{WHITEPAPER_URL}: the document states more than {MAX_PDF_OBJECTS} indirect "
                    f"objects; a crafted object table is refused rather than expanded")
    return objects


def _deflate(body, budget, where):
    """One stream's decoded bytes, bounded, or ``None`` when it is no stream.

    Expansion is bounded by the remaining decode budget: ``decompress`` is given
    a hard ``max_length``, so a stream that would expand past the budget returns
    a bounded prefix and is refused by name rather than being materialized.
    """
    match = PDF_STREAM.search(body)
    if match is None:
        return None
    raw = body[match.end():]
    end = raw.rfind(b"endstream")
    if end >= 0:
        raw = raw[:end]
    if b"FlateDecode" not in body[:match.start()]:
        if len(raw) > MAX_STREAM_BYTES:
            raise ValueError(f"{WHITEPAPER_URL}: the stream at {where} states {len(raw)} bytes, "
                             f"past the {MAX_STREAM_BYTES}-byte stream bound")
        budget.spend(len(raw), where)
        return raw
    decoder = zlib.decompressobj()
    try:
        out = decoder.decompress(raw, budget.decoded + 1)
    except zlib.error:
        return None
    if len(out) > budget.decoded:
        raise ValueError(
            f"{WHITEPAPER_URL}: the stream at {where} expands past the remaining decode budget; a "
            f"decompression bomb is refused rather than expanded")
    budget.spend(len(out), where)
    return out


def _hex_bytes(text):
    return bytes.fromhex(text.decode("ascii").replace(" ", "").replace("\n", ""))


def _cmap(raw):
    """One ToUnicode CMap as ``{source bytes: character}``.

    Both the character pairs and the range spans are bounded: a range that
    claims millions of codes is refused rather than expanded code by code, and
    the table's own entry count is capped, so a crafted CMap cannot turn into an
    algorithmic blow-up.
    """
    table = {}
    for block in re.findall(rb"beginbfchar(.*?)endbfchar", raw, re.S):
        for source, target in re.findall(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", block):
            table[_hex_bytes(source)] = _hex_bytes(target).decode("utf-16-be", "replace")
            if len(table) > MAX_CMAP_ENTRIES:
                raise ValueError(f"{WHITEPAPER_URL}: a ToUnicode CMap states more than "
                                 f"{MAX_CMAP_ENTRIES} entries")
    for block in re.findall(rb"beginbfrange(.*?)endbfrange", raw, re.S):
        for low, high, target in re.findall(
                rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", block):
            first_code, last_code = int(low, 16), int(high, 16)
            if last_code < first_code:
                raise ValueError(f"{WHITEPAPER_URL}: a ToUnicode CMap range ends before it starts")
            if last_code - first_code + 1 > MAX_RANGE_SPAN:
                raise ValueError(
                    f"{WHITEPAPER_URL}: a ToUnicode CMap range spans "
                    f"{last_code - first_code + 1} codes, past the {MAX_RANGE_SPAN}-code bound")
            width = len(_hex_bytes(low))
            base = _hex_bytes(target)
            first = int.from_bytes(base, "big")
            for offset, code in enumerate(range(first_code, last_code + 1)):
                table[code.to_bytes(width, "big")] = (first + offset).to_bytes(
                    len(base), "big").decode("utf-16-be", "replace")
                if len(table) > MAX_CMAP_ENTRIES:
                    raise ValueError(f"{WHITEPAPER_URL}: a ToUnicode CMap states more than "
                                     f"{MAX_CMAP_ENTRIES} entries")
    return table


def _pdf_fonts(objects, budget):
    """Every font's own text map, keyed by font object number."""
    fonts = {}
    for number, body in objects.items():
        if not PDF_FONT.search(body):
            continue
        reference = re.search(rb"/ToUnicode (\d+) 0 R", body)
        if reference is None:
            fonts[number] = None
            continue
        raw = _deflate(objects.get(int(reference.group(1)), b""), budget, f"font {number} CMap")
        if raw is None:
            raise ValueError(f"{WHITEPAPER_URL}: a font states no decodable ToUnicode map")
        fonts[number] = _cmap(raw)
    if not fonts:
        raise ValueError(f"{WHITEPAPER_URL}: the document states no fonts")
    return fonts


def _pdf_page_order(objects):
    """Every page object number, in the document's own page order.

    The walk is iterative, tracks the objects it has visited, and bounds its
    depth and its page count: a cyclic ``/Kids`` chain or a page tree deeper
    than the bound refuses by name instead of recursing until the interpreter
    gives up.
    """
    root = None
    for body in objects.values():
        if re.search(rb"/Type\s*/Catalog", body):
            reference = re.search(rb"/Pages (\d+) 0 R", body)
            root = int(reference.group(1)) if reference else None
            break
    if root is None:
        raise ValueError(f"{WHITEPAPER_URL}: the document states no page tree")
    order, visited = [], set()
    stack = [(root, 0)]
    while stack:
        number, depth = stack.pop()
        if number in visited:
            raise ValueError(f"{WHITEPAPER_URL}: the page tree names object {number} twice; a "
                             f"cyclic page tree is refused")
        if depth > MAX_TREE_DEPTH:
            raise ValueError(f"{WHITEPAPER_URL}: the page tree is deeper than {MAX_TREE_DEPTH} "
                             f"levels; a crafted tree is refused")
        visited.add(number)
        body = objects.get(number, b"")
        if PDF_PAGE.search(body) and not re.search(rb"/Type\s*/Pages", body):
            order.append(number)
            if len(order) > MAX_PDF_PAGES:
                raise ValueError(f"{WHITEPAPER_URL}: the document states more than {MAX_PDF_PAGES} "
                                 f"pages")
            continue
        kids = re.search(rb"/Kids\s*\[(.*?)\]", body, re.S)
        if kids is None:
            raise ValueError(f"{WHITEPAPER_URL}: page tree node {number} states no /Kids array")
        children = [int(kid) for kid in re.findall(rb"(\d+) 0 R", kids.group(1))]
        stack.extend((child, depth + 1) for child in reversed(children))
    if not order:
        raise ValueError(f"{WHITEPAPER_URL}: the document's page tree states no pages")
    return order


def _literal(token):
    """One PDF literal string's bytes, with its escapes resolved."""
    body, out, index = token[1:-1], bytearray(), 0
    while index < len(body):
        char = body[index:index + 1]
        if char == b"\\" and index + 1 < len(body):
            following = body[index + 1:index + 2]
            out += {b"n": b"\n", b"r": b"\r", b"t": b"\t", b"b": b"\b", b"f": b"\f",
                    b"(": b"(", b")": b")", b"\\": b"\\"}.get(following, following)
            index += 2
            continue
        out += char
        index += 1
    return bytes(out)


def _shown(raw, table):
    """One shown string, decoded through its font's map or as single bytes."""
    if not table:
        return raw.decode("latin-1", "replace")
    out, index = [], 0
    while index < len(raw):
        pair = raw[index:index + 2]
        if len(pair) == 2 and pair in table:
            out.append(table[pair])
            index += 2
            continue
        single = raw[index:index + 1]
        if single in table:
            out.append(table[single])
        elif raw[index] >= 32:
            out.append(chr(raw[index]))
        else:
            out.append(" ")
        index += 1
    return "".join(out)


PDF_TOKEN = re.compile(
    rb"/([A-Za-z0-9]+)\s+([\d.]+)\s+(?:Tf|Tfs)|"
    rb"\((?:\\.|[^()\\])*\)|<([0-9A-Fa-f\s]*)>|"
    rb"(-?[\d.]+)\s+(-?[\d.]+)\s+(Tm|Td|TD)|"
    rb"\b(BDC|BMC|EMC|TJ|Tj|T\*|ET)\b", re.S)


def _runs(raw, fonts, names):
    """Every shown string with the position it is shown at.

    A content stream states where each run of text begins, and a PDF's prose is
    one line per run: two runs on one line are joined without a word break, and a
    run that starts a new line begins a new one. Without the positions a line
    that wraps mid-word would read as two words, so the operators that place text
    are read rather than only the ones that show it.
    """
    current, size, x, y = None, 12.0, 0.0, 0.0
    runs, pending = [], []
    for match in PDF_TOKEN.finditer(raw):
        if match.group(1):
            current = fonts.get(int(names.get(match.group(1), b"0")))
            size = float(match.group(2))
            continue
        if match.group(6) is not None:
            # ``Tm`` states the position outright; ``Td``/``TD`` move the text
            # line by an offset, so the two are applied differently.
            if match.group(6) == b"Tm":
                x, y = float(match.group(4)), float(match.group(5))
            else:
                x, y = x + float(match.group(4)), y + float(match.group(5))
            continue
        operator = match.group(7)
        if operator is not None:
            if operator in (b"TJ", b"Tj"):
                runs.append({"text": "".join(pending), "x": x, "y": y, "size": size})
            elif operator == b"T*":
                y -= size
            pending = []
            continue
        token = match.group(0)
        if token.startswith(b"("):
            pending.append(_shown(_literal(token), current))
        elif match.group(3) is not None:
            pending.append(_shown(_hex_bytes(match.group(3)), current))
    return runs


def _page_text(objects, fonts, body, content, budget):
    """One page's text, rebuilt from the positions its runs are shown at.

    Runs are grouped into lines by their vertical coordinate — a whole page's
    lines sit on distinct baselines — and within a line ordered by their
    horizontal coordinate, so a wrapped word is rejoined and two runs of one line
    do not become two lines. Words are separated where the layout puts a gap and
    nowhere else, because the strings a PDF shows carry their own spaces.
    """
    raw = _deflate(objects.get(content, b""), budget, f"page {content} content stream")
    if raw is None:
        raise ValueError(f"{WHITEPAPER_URL}: a page's content stream is not decodable")
    names = dict(re.findall(rb"/(F\d+)\s+(\d+) 0 R", body))
    lines = {}
    for run in _runs(raw, fonts, names):
        lines.setdefault(round(run["y"], 1), []).append(run)
    out = []
    for key in sorted(lines, reverse=True):
        line = sorted(lines[key], key=lambda run: run["x"])
        # A line's own runs are joined as they were drawn: the gap between two
        # runs is a space whether or not the producer wrote one, and a run that
        # continues a word inside the same line is not one.
        out.append(" ".join("".join(run["text"] for run in line).split()))
    return "\n".join(out)


def _pdf_pages(document):
    """Every page's text of the white paper's own PDF, in document order.

    One decode budget covers the whole document, so the object streams, every
    font's CMap and every page's content stream are bounded together and not
    merely one at a time.
    """
    if not isinstance(document, (bytes, bytearray)):
        raise ValueError(f"{WHITEPAPER_URL}: the white paper is not a byte document")
    if len(document) > MAX_PDF_BYTES:
        raise ValueError(f"{WHITEPAPER_URL}: the white paper states {len(document)} bytes, past "
                         f"the {MAX_PDF_BYTES}-byte document bound")
    budget = _Budget()
    objects = _pdf_objects(document, budget)
    order = _pdf_page_order(objects)
    fonts = _pdf_fonts(objects, budget)
    pages = []
    for number in order:
        body = objects.get(number, b"")
        content = re.search(rb"/Contents (\d+) 0 R", body)
        if content is None:
            raise ValueError(f"{WHITEPAPER_URL}: a page states no content stream")
        pages.append(_page_text(objects, fonts, body, int(content.group(1)), budget))
    return pages


def _pdf_worker(document, connection):
    """The child entry point: hard resource ceilings, then the bounded reader.

    The reader runs in its own process so a document that defeats the byte,
    object, page and CMap bounds consumes the child's address space and CPU
    rather than the refresh's, and the parent reports a named failure instead of
    inheriting the cost. ``RLIMIT_AS`` caps the child's memory and ``RLIMIT_CPU``
    its CPU; both are set only in the child.
    """
    try:
        if resource is not None:
            resource.setrlimit(resource.RLIMIT_AS, (PDF_ADDRESS_SPACE, PDF_ADDRESS_SPACE))
            resource.setrlimit(resource.RLIMIT_CPU, (PDF_CPU_SECONDS, PDF_CPU_SECONDS))
    except (ValueError, OSError):
        # A platform without the limit still gets the bounded reader below.
        pass
    try:
        connection.send(("ok", _pdf_pages(document)))
    except BaseException as error:                    # noqa: BLE001 - reported to the parent
        connection.send(("error", f"{type(error).__name__}: {error}"))
    finally:
        connection.close()


class _NoProcess(Exception):
    """The environment forbids creating the isolated reader at all."""


def pdf_pages(document):
    """Every page's text of the white paper's own PDF, in document order.

    The reader itself is bounded, and it is run in an isolated, resource-limited
    child process: a document that got past a bound fails that child by name —
    its memory is capped by ``RLIMIT_AS`` and its CPU by ``RLIMIT_CPU`` — so the
    refresh reports a refusal instead of inheriting the cost. The parent's wait
    is bounded too, so a child that somehow never returns cannot stall the
    refresh.

    A child process is created with a *spawned* context (``forkserver``, else
    ``spawn``), never a bare ``fork``: the collector may run beside threads, and
    no state is inherited that could deadlock. Where the environment forbids
    creating a process at all the bounded in-process reader still runs, so the
    source never depends on process isolation for correctness.
    """
    context = _pdf_context()
    if context is not None:
        try:
            return _isolated_pages(context, document)
        except _NoProcess:
            pass
    return _pdf_pages(document)


def _isolated_pages(context, document):
    """Run ``_pdf_pages`` in a resource-limited child and return its result."""
    parent, child = context.Pipe(duplex=False)
    process = context.Process(target=_pdf_worker, args=(document, child))
    try:
        process.start()
    except (OSError, RuntimeError, ImportError, AttributeError) as error:
        parent.close()
        child.close()
        raise _NoProcess(str(error)) from error
    child.close()
    try:
        # ``poll`` bounds the wait; a child killed by its own CPU ceiling closes
        # the pipe without a result, which is the same refusal.
        if not parent.poll(PDF_TIMEOUT):
            raise ValueError(f"{WHITEPAPER_URL}: parsing the white paper exceeded "
                             f"{PDF_TIMEOUT} seconds; the document is refused")
        try:
            status, payload = parent.recv()
        except EOFError as error:
            raise ValueError(f"{WHITEPAPER_URL}: the isolated PDF reader did not return a result; "
                             f"the document is refused") from error
    finally:
        parent.close()
        process.join(PDF_TIMEOUT)
        if process.is_alive():
            process.terminate()
            process.join()
    if status == "error":
        raise ValueError(f"{WHITEPAPER_URL}: {payload}")
    return payload


def _pdf_context():
    """A *spawning* process context for the isolated reader, or ``None``."""
    for method in ("forkserver", "spawn"):
        try:
            return multiprocessing.get_context(method)
        except ValueError:
            continue
    return None


# --- assembling the record -------------------------------------------------


class Sources:
    """Everything one refresh read, so no builder reaches for the network."""

    def __init__(self, catalog, history, cards, listing, policy, prose, document, announcements,
                 set_aside):
        self.catalog = catalog
        self.history = history
        self.cards = cards
        self.listing = listing
        self.policy = policy
        self.prose = prose
        self.document = document
        self.announcements = announcements
        # The paper's dated statements that are not releases, with the reason
        # each is outside the release history.
        self.set_aside = set_aside
        self.paper = None
        # Every disputed general availability these sources state, verified
        # against the pages it names, keyed by identity.
        self.holds = held_rules(self)

    def text(self):
        """The white paper's own text, extracted once for the holds."""
        if self.paper is None:
            self.paper = " ".join(" ".join(page.split()) for page in pdf_pages(self.document))
        return self.paper

    def stated(self, url):
        """The text of one source the holds need to re-verify a quote against."""
        if url == WHITEPAPER_URL:
            return self.text()
        if url == LIFECYCLE_URL:
            return self.prose
        if url in self.announcements:
            return self.announcements[url]
        raise ValueError(f"No text was read from {url}")


def held_rule(key, sources):
    """One disputed general availability, with every side of it re-verified.

    The hold is a stored refusal, so each side of the disagreement is checked
    against the page it names: a source that moved or reworded one of them
    leaves the refusal unverifiable, and the run fails instead of publishing the
    surviving date as if the sources agreed.
    """
    entry = DISPUTED_GA[key_string(key)]
    for evidence in entry["evidence"]:
        if evidence["quote"] not in sources.stated(evidence["source_url"]):
            raise ValueError(f"{evidence['source_url']} no longer states {evidence['quote']!r}; "
                             f"the disputed general availability of {key_string(key)} needs review")
    return {"reason": entry["reason"],
            "evidence": [dict(evidence) for evidence in entry["evidence"]]}


def held_rules(sources):
    """Every disputed identity, with the hold each one's evidence supports.

    Called as the sources are assembled, so a page that moved or reworded one
    side of a disagreement refuses the parse itself — a run that can no longer
    see both sides must not proceed far enough to publish the surviving date.
    Every hold is checked, not only those of releases this fetch happens to
    state: a disputed identity disappearing from a source is exactly the change
    a reader has to be told about.
    """
    return {key: held_rule(key, sources)
            for key in (parse_key(key_text) for key_text in DISPUTED_GA)
            if key is not None}


def release_for(key, sources):
    """One published release, from the cells the sources state for it."""
    row = sources.catalog.get(key)
    history = sources.history.get(key)
    card = next((card for card in sources.cards if card["key"] == key), None)
    lts = row["lts"] if row else None
    hold = sources.holds.get(key)
    ga = None if hold else (history["date"] if history else None)
    stated_eol = (card_month(card["value"], f"{CARD_TABLE} {card['name']!r}")
                  if card and card["value"] else None)
    provenance = {}
    eol = stated_eol
    if eol is None:
        window = innovation_window(ga, key, lts)
        if window is not None:
            eol = window
            provenance["eol"] = {
                "kind": derived.KIND,
                "method": "release-plus-duration",
                "source_url": LIFECYCLE_URL,
                "quote": INNOVATION_RULE,
                "base_date": ga,
                "base_label": BASE_LABEL,
                "duration": {"value": INNOVATION_MONTHS, "unit": "month"},
            }
    stored = {
        "table": API_TABLE if row else None,
        "cells": dict(row["cells"]) if row else {},
        "history": None,
        "planned_eol": None,
        "in_catalog": bool(row),
        "in_sources": True,
    }
    if history is not None:
        stored["history"] = {"table": HISTORY_TABLE, "quote": history["quote"],
                             "date": history["date"]}
        if hold is not None:
            stored["history"]["hold"] = hold
    if card is not None and card["value"]:
        stored["planned_eol"] = {"table": CARD_TABLE, "label": CARD_FIELD,
                                 "value": card["value"], "card": card["name"]}
    release = {
        "id": release_id(key, lts),
        "name": display_name(key, lts),
        "milestones": {"ga": ga, "eos": None, "eossec": None, "eol": eol},
        "upstream": {
            "name": row["name"] if row else (history["name"] if history else card["name"]),
            **stored,
        },
    }
    if provenance:
        release[derived.DERIVED_KEY] = provenance
    return release


def cross_checks(releases):
    """The policy's stated service-pack windows against the cards' stated months.

    The windows are stated under an effective date, so only a service pack
    released under it is compared, and only against a value the download page
    publishes. The comparison never replaces the published month: a card's stated
    value is what this record publishes, and the policy's own arithmetic is
    recomputed beside it so the two cannot drift apart unobserved.
    """
    checked = []
    for release in releases:
        card = release["upstream"]["planned_eol"]
        history = release["upstream"]["history"]
        key, _lts = identity_of(release)
        kind = service_pack_kind(history["date"]) if history and key[2] else None
        if card is None or kind is None or history["date"] < EFFECTIVE:
            continue
        window = derived.add_duration(history["date"], SP_MONTHS[kind], "month")
        stated = card_month(card["value"], release["id"])
        if window[:7] != stated:
            raise ValueError(f"{card['card']!r}: the lifecycle page's {SP_MONTHS[kind]}-month "
                             f"{kind} service-pack window from the release history's "
                             f"{history['date']} is {window[:7]}, but the card states "
                             f"{card['value']}")
        checked.append({
            "rule": SP_RULE, "release": release["id"], "kind": kind,
            "base": history["date"], "computed": window[:7], "stated": card["value"],
        })
    return checked


def order_key(release):
    """One release's place in the record: its release date, then its own id.

    A release whose general availability is withheld is still ordered by the
    release date its stored history states, so withholding a disputed date never
    moves a release out of the sequence the community released it in.
    """
    history = release["upstream"]["history"]
    return (release["milestones"]["ga"] or (history["date"] if history else ""), release["id"])


def ordered_releases(releases):
    """Newest release first, in the order the sources date them."""
    return sorted(releases, key=order_key, reverse=True)


def combine_releases(fresh, committed):
    """The complete snapshot: this fetch's releases plus the committed history.

    A release no current source states is republished from its own stored cells
    and marked as such: disappearance from a catalog is not an end of life, and
    the white paper's history is the community's own record of what it released.

    Retention is reconciled by the *stable source identity* — the line, version
    and flavour the community's own sources name — never by the generated record
    id. The id embeds the catalog's current LTS flag, so a flag change (an
    innovation release the community later marks LTS) renames the id without
    renaming the release; comparing ids would then retain the old row *and*
    publish the new one, so one release would appear twice with two different
    ids, dates and LTS meanings. Comparing identities collapses them to the
    fresh row and reports the id transition instead.
    """
    if committed is None:
        return list(fresh), [], []
    fresh_keys = {key_string(identity_of(release)[0]): release for release in fresh}
    kept, transitions = [], []
    for release in committed["releases"]:
        key, _lts = identity_of(release)
        current = fresh_keys.get(key_string(key))
        if current is None:
            kept.append({**release, "upstream": {**release["upstream"], "in_sources": False}})
            continue
        if current["id"] != release["id"]:
            transitions.append({
                "identity": key_string(key), "from": release["id"], "to": current["id"],
                "reason": "the sources now state this release identity under a different generated "
                          "id, which embeds the catalog's own LTS flag; the fresh row replaced the "
                          "committed one rather than being published beside it"})
    return list(fresh) + kept, [
        {"id": release["id"], "name": release["name"],
         "reason": "no current openEuler source states this release; the committed row and its "
                   "dates are retained"}
        for release in kept], transitions


def validate_record(record):
    """Rebuild every stored release and derived date from its own cells, offline.

    Offline, the record's own cells are the whole evidence: each release's
    ``ga`` is re-read from the history statement it stores and stayed absent
    where the sources disagree, its ``eol`` is re-read from the release card it
    stores or re-derived from its own history date and the stored duration, the
    policy's service-pack arithmetic is recomputed, and the record's order is
    rebuilt from the dates the releases store. A milestone, a rule or a quote
    that no longer follows its own stored cells is never published.
    """
    if (record["id"] != PRODUCT_ID or record["provenance"]["verifier"] != VERIFIER
            or record["provenance"]["source_url"] != DOWNLOAD_URL):
        raise ValueError("Invalid openEuler source identity")
    if record["labels"] != LABELS:
        raise ValueError("Invalid openEuler label evidence")
    releases, seen, identities = [], set(), set()
    for release in record["releases"]:
        where = f"{PRODUCT_NAME} {release.get('id')}"
        if release["id"] in seen:
            raise ValueError(f"{where}: release id is stated twice")
        seen.add(release["id"])
        upstream = release.get("upstream")
        if not isinstance(upstream, dict):
            raise ValueError(f"{where}: the release stores no source row")
        if upstream.get("in_sources") not in (True, False) or upstream.get("in_catalog") not in (
                True, False):
            raise ValueError(f"{where}: the release carries no valid source marker")
        if not isinstance(upstream.get("name"), str) or not upstream["name"]:
            raise ValueError(f"{where}: the release stores no source name")
        catalog = catalog_row(upstream)
        history, card = upstream.get("history"), upstream.get("planned_eol")
        key = catalog["key"] if catalog else None
        lts = catalog["lts"] if catalog else None
        if history is not None:
            if not isinstance(history, dict) or history.get("table") != HISTORY_TABLE:
                raise ValueError(f"{where}: the release does not store its release-history row")
            quoted, day = history_key(history.get("quote"), where), history_day(
                history.get("quote"), where)
            if key is not None and quoted != key:
                raise ValueError(f"{where} contradicts the release-history statement it stores")
            key = key or quoted
            if history.get("date") != day:
                raise ValueError(f"{where} contradicts the release date it stores")
            hold = history.get("hold")
            if key_string(key) in DISPUTED_GA:
                expected = DISPUTED_GA[key_string(key)]
                if (not isinstance(hold, dict) or hold.get("reason") != expected["reason"]
                        or [dict(evidence) for evidence in hold.get("evidence") or []]
                        != [dict(evidence) for evidence in expected["evidence"]]):
                    raise ValueError(f"{where}: the disputed general availability was rewritten")
                if release["milestones"]["ga"] is not None:
                    raise ValueError(f"{where}: publishes a general availability the sources "
                                     f"disagree about")
            elif hold is not None:
                raise ValueError(f"{where}: stores a dispute hold for an undisputed release")
            elif release["milestones"]["ga"] != day:
                raise ValueError(f"{where} contradicts the release date cell it stores")
        elif release["milestones"]["ga"] is not None:
            raise ValueError(f"{where}: publishes a general availability no source states")
        if key is None:
            raise ValueError(f"{where}: the release names no openEuler identity")
        # The generated id embeds the catalog's LTS flag, so two rows can name
        # one release identity under two ids. One community release is one row:
        # the identity, not the id it happens to mint, is what may appear once.
        if key_string(key) in identities:
            raise ValueError(f"{where}: release identity {key_string(key)} is published twice; one "
                             f"community release may not carry two generated ids")
        identities.add(key_string(key))
        if release["id"] != release_id(key, lts) or release["name"] != display_name(key, lts):
            raise ValueError(f"{where}: release does not name the identity it stores")
        if card is not None:
            if (not isinstance(card, dict) or card.get("table") != CARD_TABLE
                    or card.get("label") != CARD_FIELD):
                raise ValueError(f"{where}: the release does not store its release-card row")
            value = card.get("value")
            if not isinstance(value, str) or not CARD_MONTH.fullmatch(value):
                raise ValueError(f"{where}: the release stores no stated planned end of life")
            if release["milestones"]["eol"] != card_month(value, where):
                raise ValueError(f"{where}: release contradicts the planned end of life it stores")
        releases.append(release)
    if [release["id"] for release in releases] != [release["id"] for release in
                                                   ordered_releases(releases)]:
        raise ValueError("The openEuler record is not ordered by the release dates it stores")
    checks = cross_checks(releases)
    for release in releases:
        where = f"{PRODUCT_ID}: release {release['id']}"
        key, lts = identity_of(release)
        window = innovation_window(release["milestones"]["ga"], key, lts)
        provenance = release.get(derived.DERIVED_KEY)
        derived.validate_milestone_provenance(release["milestones"], provenance, where, seen)
        entry = (provenance or {}).get("eol")
        if window is None:
            if entry is not None:
                raise ValueError(f"{where}: derives an end of life no rule licenses here")
            if (release["milestones"]["eol"] is not None
                    and release["upstream"]["planned_eol"] is None):
                raise ValueError(f"{where}: publishes an end of life no source states")
            continue
        if release["upstream"]["planned_eol"] is not None:
            raise ValueError(f"{where}: derives an end of life a release card already states")
        if entry is None:
            raise ValueError(f"{where}: publishes a derived end of life with no rule recorded "
                             f"for it")
        if entry.get("duration") != {"value": INNOVATION_MONTHS, "unit": "month"}:
            raise ValueError(f"{where} applies the wrong innovation window")
        if entry.get("quote") != INNOVATION_RULE or entry.get("source_url") != LIFECYCLE_URL:
            raise ValueError(f"{where} does not quote the rule it applies")
        if entry.get("base_date") != release["milestones"]["ga"]:
            raise ValueError(f"{where} measures its window from the wrong release date")
    return checks


def record_for(releases, checked):
    """The published ``openeuler`` record for one snapshot of its sources."""
    return {
        "$schema": RECORD_SCHEMA,
        "id": PRODUCT_ID,
        "name": PRODUCT_NAME,
        "category": "software",
        "upstream_category": UPSTREAM_CATEGORY,
        # The community publishes no CPE or other identifier for these releases,
        # and an invented one would be a claim the sources never make.
        "identifiers": [],
        "labels": dict(LABELS),
        "links": {"release downloads": DOWNLOAD_URL, "release catalog": API_URL,
                  "lifecycle policy": LIFECYCLE_URL, "technical white paper": WHITEPAPER_URL},
        "releases": releases,
        "provenance": {"source_url": DOWNLOAD_URL, "verifier": VERIFIER,
                       "last_checked": checked, "upstream_modified": None},
    }


def committed_record(root):
    """The committed ``openeuler`` record, refusing one this source cannot own."""
    return transaction.committed_product_record(root, PRODUCT_ID, VERIFIER,
                                               validate_record, PRODUCT_NAME)


def accounting(sources):
    """Every source row this fetch read, counted per surface and reconciled.

    ``reconciled`` is the number of rows beyond the first that state an identity
    another surface already stated, so ``seen == identities + reconciled``: the
    surface rows that name a release and the releases they name are two counts of
    the same thing, and the report states both so a reader can check the
    arithmetic instead of taking it on faith.
    """
    by_surface = {
        "release catalog API": len(sources.catalog),
        "technical white paper release history": len(sources.history),
        "download page release cards": len(sources.cards),
        "download page embedded item list": len(sources.listing),
    }
    rows = sum(by_surface.values())
    names = [key for key in sources.catalog]
    names += [key for key in sources.history]
    names += [card["key"] for card in sources.cards]
    names += [key for key, _value in _listed(sources.listing)]
    return {"seen": rows, "by_surface": by_surface,
            "identities": len(set(names)), "reconciled": rows - len(set(names))}


def _listed(listing):
    """The embedded item list's rows as ``(identity, value)`` pairs."""
    rows = []
    for name, value in listing.items():
        key = _identity_of_text(listing_name(name))
        rows.append((key, value))
    return rows


def report_for(releases, counts, sources, conflicts, checks, kept, checked, transitions=()):
    """The per-row accounting this source publishes beside its record.

    ``transitions`` names every release identity the sources now state under a
    different generated id — an LTS-flag change renames the id, not the release
    — so a reader can see that the committed row was replaced rather than
    duplicated.
    """
    retained_ids = {entry["id"] for entry in kept}
    fresh = [release for release in releases if release["id"] not in retained_ids]
    stated_eol = [release for release in releases if release["upstream"]["planned_eol"]]
    derived_eol = [release for release in releases if release.get(derived.DERIVED_KEY)]
    held = [release for release in releases
            if (release["upstream"]["history"] or {}).get("hold")]
    return {
        "source_url": DOWNLOAD_URL,
        "verifier": VERIFIER,
        "checked_at": checked,
        "record_scope": ("openEuler community releases: one software record with one release per "
                         "release identity the community's own release catalog and release history "
                         "name, carrying the release day the technical white paper states as "
                         "general availability, the download card's stated planned end of life as "
                         "end of life, and the innovation support window the lifecycle page "
                         "derives where its own effective date covers the release"),
        "rows": {
            "seen": counts["seen"],
            "by_surface": counts["by_surface"],
            "identities": counts["identities"],
            "reconciled": counts["reconciled"],
            "published": len(fresh),
            "retained": len(kept),
            "excluded": 0,
            "catalog_only": sum(1 for release in releases
                                if release["upstream"]["in_catalog"]
                                and not release["upstream"]["history"]),
            "history_only": sum(1 for release in releases
                                if not release["upstream"]["in_catalog"]
                                and release["upstream"]["history"]),
            "ga_stated": sum(1 for release in releases if release["milestones"]["ga"]),
            "ga_withheld": len(held),
            "ga_absent": sum(1 for release in releases
                             if not release["milestones"]["ga"] and release not in held),
            "eol_stated": len(stated_eol),
            "eol_derived": len(derived_eol),
        },
        "conflicts": conflicts,
        "set_aside": [{"table": HISTORY_TABLE, **entry} for entry in sources.set_aside],
        "disputed": [{"release": release["id"],
                      "reason": release["upstream"]["history"]["hold"]["reason"],
                      "evidence": release["upstream"]["history"]["hold"]["evidence"]}
                     for release in held],
        "cross_checks": checks,
        "retained": kept,
        "id_transitions": list(transitions),
        "policy": sources.policy,
        "total_records": 1,
        "limitations": [
            "eos is null for every release: the community publishes no end of sale or orderability "
            "milestone, and a download is not a sale.",
            "eossec is null for every release: the community's full-support-to-maintenance-support "
            "boundary is a real transition, but maintenance support still fixes critical and "
            "high-severity CVEs, so it is not an end of security support.",
            "Most releases carry a null end of life: the download page states a planned end of "
            "life only for the service packs it currently serves, and the lifecycle page's "
            "durations are stated under an effective date of August 2025, so they are applied only "
            "to a release that effective date covers.",
            "The service-pack window is compared, not published: a release card's stated month is "
            "the published end of life, and the policy's own 9/24-month arithmetic is recomputed "
            "beside it and refuses the import when the two disagree.",
            "Two general availabilities are withheld because the sources disagree: each side's "
            "verbatim quote is reported, and neither day is chosen.",
            "The release catalog API states identities, scenarios and architectures only: it "
            "carries no release or end-of-life date, and its FileInfo.ModTime is the zero time, so "
            "it is stored and never used for revision detection.",
            "The catalog is not the release history: the API omits the published innovation "
            "releases 20.09, 21.03, 21.09 and 22.09, which are published from the white paper, and "
            "no catalog disappearance is read as an end of life.",
            "The download page's embedded JSON-LD item list is an older rendering of its own "
            "catalog and is not read for milestones; every row it states differently from the "
            "rendered cards is reported under conflicts.",
            "The lifecycle page's prose is supplied by a content-hashed script component rather "
            "than the server-rendered page; the component is discovered from the page each refresh "
            "and its rule sentence is stored verbatim with the one date derived from it.",
            "The white paper's release history is read from a PDF with a bounded extractor for "
            "that document's own construction; a page or font it cannot decode refuses the import "
            "rather than contributing fewer sentences.",
            "Architectures, scenarios and delivery forms are not releases: one release per "
            "identity the community names, never one per architecture or image.",
            "The embedded line's release is catalogued and published as a release of this "
            "product, as the community's own catalog and download page list it, but neither states "
            "a release date or an end of life for it, so both stay null.",
        ],
    }


def assemble(pages, document):
    """One refresh's sources, from the bytes of every page it reads.

    ``pages`` is ``{url: text}`` for the HTML sources and ``{API_URL: payload}``
    for the catalog, and the lifecycle component's own script body is passed as
    ``script``. Every builder below takes this one object, so the network path
    and an offline fixture exercise the identical code.
    """
    script = pages["script"]
    prose = component_prose(script)
    cards, listing = parse_cards(pages[DOWNLOAD_URL])
    history, set_aside = parse_history(document)
    return Sources(catalog=parse_api(pages[API_URL]), history=history,
                   cards=cards, listing=listing, policy=policy_rules(prose), prose=prose,
                   document=document,
                   announcements={url: _text_of(pages[url])
                                  for url in (ANNOUNCEMENT_2403, ANNOUNCEMENT_SP4)},
                   set_aside=set_aside), listing_conflicts(cards, listing)


def fetch():
    """Read every page and document one refresh needs, from the network.

    The lifecycle component is discovered from the lifecycle page's own markup,
    so the refresh reads the rule the page currently renders rather than a hash a
    site redeploy would leave stale.
    """
    lifecycle = net.get_text(LIFECYCLE_URL)
    pages = {
        "script": net.get_text(lifecycle_component(lifecycle)),
        DOWNLOAD_URL: net.get_text(DOWNLOAD_URL),
        API_URL: net.get_json(API_URL),
        ANNOUNCEMENT_2403: net.get_text(ANNOUNCEMENT_2403),
        ANNOUNCEMENT_SP4: net.get_text(ANNOUNCEMENT_SP4),
    }
    return assemble(pages, net.get(WHITEPAPER_URL).content)


def build(sources, committed):
    """One complete release snapshot: this fetch's releases plus retained history."""
    keys = set(sources.catalog) | set(sources.history)
    keys |= {card["key"] for card in sources.cards}
    keys |= {key for key, _value in _listed(sources.listing)}
    fresh = [release_for(key, sources) for key in sorted(keys, key=key_string)]
    return combine_releases(fresh, committed)


def import_openeuler(directory=None):
    """Fetch every source and publish the openEuler record and its report.

    Complete-or-nothing: the fetched snapshot is combined with the releases no
    current source states, staged beside the committed catalog and validated
    there before anything is written. A parse failure, a reworded rule, a
    disagreeing download-page rendering or an inconsistent release history leaves
    every committed file untouched.
    """
    root = Path(directory) if directory is not None else ROOT / "data"
    # The committed ownership check runs before the fetch: a file this source
    # cannot publish aborts the run without a network call at all.
    committed = committed_record(root)
    checked = _now()
    sources, conflicts = fetch()
    releases, kept, transitions = build(sources, committed)
    releases = ordered_releases(releases)
    record = record_for(releases, checked)
    counts = accounting(sources)
    checks = validate_record(record)
    report = report_for(releases, counts, sources, conflicts, checks, kept, checked,
                        transitions)
    transaction.publish_product_record(record, report, root, REPORT)
    rows = report["rows"]
    return (f"imported {rows['published']} openEuler releases of {rows['identities']} identities "
            f"({rows['ga_stated']} dated, {rows['ga_withheld']} withheld, "
            f"{rows['eol_stated']} stated ends of life, {rows['eol_derived']} derived); "
            f"read {rows['seen']} source rows over {len(rows['by_surface'])} surfaces, retained "
            f"{rows['retained']} (data/{REPORT})")
