"""Admit one-time researched lifecycle records (AGENTS.md rule 8, tier b).

Some products have no deterministic source: no API, no lifecycle table, only a
vendor notice that states a date in prose. Rule 8 allows those products into the
catalog as *researched* records, but only when the exact vendor sentence is
stored verbatim beside the date it proves. This module is that admission path.

A contribution is one JSON file in ``contributions/``::

    {
      "target": "software" | "hardware",
      "id": "researched-<slug>",              # optional; derived from name
      "name": "Synology DSM 6.2",             # new-product fields
      "vendor": "Synology",
      "category": "os",                       # software only: upstream_category
      "product_line": "Synology",             # hardware only; defaults to vendor
      "summary": "...",                       # optional display context
      "release": "6.2",                       # software only; defaults to the id minus its prefix
      "identifiers": [{"type": "purl", "id": "..."}],
      "links": {"about": "https://..."},
      "milestones": {"eol": "2024-10-01"},    # a non-empty subset of the four keys
      "evidence": [{"quote": "...", "source_url": "...", "retrieved_at": "2026-09-17",
                    "milestones": ["eol"]}],
      "contributor": "zarguell",
      "method": "manual" | "agent",           # optional, defaults to manual
      "stale_after": "2027-01-01",            # optional explicit review deadline
      "notes": "..."                          # optional review context
    }

Every stored milestone date must appear, in a recognized day-precision form, in
the verbatim quote stored beside it, and every quote must appear in the text
fetched from its ``source_url`` at admission time. Day precision is required on
both sides: ``October 2024`` never proves ``2024-10-01`` and ``2024-10-01`` never
proves ``October 2024`` (AGENTS.md rule 4). ``--allow-stale-evidence`` is the
offline path: it accepts the stored evidence without refetching and leaves
``provenance.research.verified_at`` null so the difference stays visible.

An evidence entry is *scoped*: it may back only the release lines its quote
belongs to. A quote that names a line (or the product) backs what it names; a
quote that names nothing is accepted only when exactly one line states the dates
it carries. A quote whose dates match several unnamed lines is ambiguous — a
date that could belong to any of them backs none of them — and is refused, so a
real vendor date for one branch can never be published as another branch's
deadline (issue #92). The scope is stored on the entry when the contribution
states it, and re-derived from the record when it is absent, so a committed
record that predates the property is still checked under the same rule.

A derived rule is evidence of its own (issue #79). Every ``milestone_provenance``
entry's cited quote is fetched and confirmed at admission beside the ordinary
evidence, and its ``source_url`` must be a public https citation. A derived date
is exempt from the literal date-in-quote rule — the vendor states a rule, not the
resulting day — but the rule itself is never exempt from being read from the page
it cites. A source that cannot be refetched leaves ``verified_at`` null; it never
turns an unread rule into a verified derivation.

A citation URL is a public page, not an authenticated endpoint (issue #102):
``source_url`` and each derived rule's ``source_url`` must be an ``https`` URL on
a public host with no fragment and no credential-shaped query parameter, and a
refusal prints the redacted URL so a rejected secret never reaches a log. A
contribution's display ``links`` stay permissive (a vendor deep link with a
fragment is a real citation) but still refuse userinfo and control characters.

A researched record is rejected when its normalized identifiers, slug or name
collide with a deterministic record's (issue #91): admission is by identity, not
by destination path, so a researched copy can never shadow, duplicate or outlive
the pipeline record for the same product.

A researched record may only ever be written by this command, only into the
``researched-`` id namespace, and only into a file owned by its own verifier
(``researched-<contributor-slug>``). A deterministic record is never replaced,
shadowed or extended: if the target file carries any other verifier, admission
refuses. Reinstalling a record whose content is unchanged is a no-op, so a second
run is byte-identical; a content change is an update and appends to
``data/contributions-log.json``.

The research provenance the records carry::

    "provenance": {
      "source_url": "<first evidence source_url>",      # software
      "source_urls": ["<first>", ...],                  # hardware
      "verifier": "researched-<contributor-slug>",
      "last_checked": "2026-09-17T12:00:00Z",
      "upstream_modified": null,
      "research": {
        "quote": "<evidence quotes, normalized whitespace, joined by a blank line>",
        "source_url": "<first evidence source_url>",
        "retrieved_at": "<most recent evidence retrieved_at>",
        "contributor": "zarguell",
        "method": "manual",
        "verified_at": "2026-09-17T12:00:00Z",   # null when admitted unverified
        "stale_after": null,
        "evidence": [{"quote", "source_url", "retrieved_at", "milestones"?}],
        "vendor"?, "summary"?, "notes"?          # contribution context, kept
      }
    }

Both records also carry the contribution verbatim for display:
``upstream.Contribution`` is a cell ``{"text": <quote>, "value": null,
"datetime": null, "role": null, "links": [<source urls>]}``; software keeps it on
the release it describes, hardware on the record.
"""
from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from datetime import date, datetime, timezone
from html import unescape
from pathlib import Path
from urllib.parse import urlsplit

import requests
from jsonschema import Draft202012Validator, FormatChecker

from . import derived, net, sources, urls
from .importer import ROOT, dump

CONTRIBUTIONS = "contributions"
DATA = "data"
LOG = "contributions-log.json"
PRODUCTS = "products"
HARDWARE = "hardware"

RESEARCHED_VERIFIER_PREFIX = sources.RESEARCHED_PREFIX
# A researched record is re-reviewed when its evidence has not been refetched
# for six months; presentation surfaces warn past this age.
STALE_DAYS = 180
# How close a published end date has to be before a researched hardware record
# reads as `expiring` rather than `supported`. It is a display horizon, not a
# claim about the vendor's notice.
EXPIRING_DAYS = 180
TARGETS = ("software", "hardware")
MILESTONE_KEYS = ("ga", "eos", "eossec", "eol")
MILESTONE_LABELS = {"ga": "general availability", "eos": "end of sale",
                    "eossec": "end of security support", "eol": "end of life"}
METHODS = ("manual", "agent")
UPSTREAM_CATEGORIES = ("app", "database", "framework", "lang", "os", "server-app", "service", "standard")
MIN_QUOTE = 20
SCHEMAS = {"software": "product.json", "hardware": "hardware.json"}
CONTRIBUTION_KEYS = frozenset({
    "target", "id", "name", "vendor", "category", "product_line", "summary", "release",
    "releases", "identifiers", "links", "milestones", "milestone_provenance", "evidence",
    "contributor", "method", "stale_after", "notes",
})
EVIDENCE_KEYS = frozenset({"quote", "source_url", "retrieved_at", "milestones", "scope"})
# One evidence entry's declared scope (issue #92). `product` names the product the
# quote is about -- it is how a notice that opens with the product's own name
# scopes a sentence that then states only a date -- and `releases` lists the
# release-line ids the quote belongs to. The property is optional and deliberate:
# an entry that states neither still scopes itself from what the quote names and
# from the single line whose dates it carries, so every record that predates it
# keeps validating while the check itself is never skipped.
SCOPE_KEYS = frozenset({"product", "releases"})
# One release line inside a contribution that covers several. `milestones` states
# the branch's own dates, so a product whose notice dates more than one line --
# or dates the current line and leaves an undated one that must not disappear --
# is one contribution with one release per branch. `milestone_provenance` is the
# line's optional derived-date disclosure, keyed by the milestones the notice
# states a *rule* for rather than a date (see engine/derived.py).
RELEASE_KEYS = frozenset({"id", "name", "milestones", "milestone_provenance"})
# Contribution fields copied into the research object as kept context. A
# hardware record already states its own vendor and product line, so only the
# software target keeps `vendor` there.
SOFTWARE_CONTEXT = ("vendor", "summary", "notes")
HARDWARE_CONTEXT = ("summary", "notes")
SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
DAY = re.compile(r"\d{4}-\d{2}-\d{2}\Z")
MONTH = re.compile(r"\d{4}-\d{2}\Z")
HTML_SKIP = re.compile(r"(?is)<(script|style)[^>]*>.*?</\1>")
HTML_TAG = re.compile(r"(?s)<[^>]+>")

_DATE_PATTERNS: dict[str, re.Pattern] = {}


def normalize_space(value):
    """Fold every run of whitespace to one space, as source text is folded."""
    return " ".join(str(value).split())


def slugify(value):
    """A lower-case hyphen slug, or an empty string when nothing survives."""
    return re.sub(r"[^a-z0-9]+", "-", str(value).lower()).strip("-")


def verifier_for(contributor):
    """The verifier id one contributor's researched records carry."""
    slug = slugify(contributor)
    if not SLUG.fullmatch(slug):
        raise ValueError(f"Contributor {contributor!r} has no usable slug")
    return RESEARCHED_VERIFIER_PREFIX + slug


def is_researched(record):
    """True when a catalog record carries researched provenance."""
    return bool(record.get("provenance", {}).get("research"))


def deterministic_records(records):
    """The records a deterministic pipeline owns, in the input order.

    The manifest counts (``product_count``, ``release_count``) describe that
    slice only: an importer rewrites them from its upstream listing, which never
    contains a researched record.
    """
    return [record for record in records if not is_researched(record)]


def identifier_keys(identifier):
    """The identity keys one ``{type, id}`` pair occupies, normalized.

    A purl and a CPE name the same product in more than one spelling: a purl's
    version qualifier (``@6.2``) is not part of the package identity, and a CPE
    2.3 name's trailing target fields (``:windows`` onward) are not part of the
    vendor/product pair that identifies a product. Both reduced forms are keys,
    so a researched copy of ``pkg:pypi/qiskit`` or ``cpe:2.3:a:adobe:acrobat``
    is caught however the copy spelled the version it covers -- which is exactly
    the shadow a destination-path check cannot see (issue #91).

    Keys are namespaced by kind (``purl:``/``cpe:``/the declared type) so a purl
    and a CPE that happen to share a string never collide by accident, and the
    bare normalized value is included so two records spelling the same scheme
    differently still collide.
    """
    if not isinstance(identifier, dict):
        return set()
    kind = slugify(identifier.get("type") or "")
    value = normalize_space(str(identifier.get("id") or "")).casefold()
    if not value:
        return set()
    keys = {f"{kind or 'id'}:{value}", value}
    if value.startswith("pkg:"):
        body = value[4:].split("?", 1)[0].split("#", 1)[0]
        keys.add(f"purl:{body.split('@', 1)[0]}")
    elif value.startswith("cpe:"):
        fields = value.split(":")
        if len(fields) >= 5:
            keys.add(f"cpe:{':'.join(fields[:5])}")
    return keys


def record_identities(record):
    """The identity keys a record occupies: its id, name, and each identifier."""
    keys = set()
    for value in (record.get("id"), record.get("name")):
        text = normalize_space(str(value or "")).casefold()
        if text:
            keys.add(f"name:{text}")
    for identifier in record.get("identifiers") or []:
        keys |= identifier_keys(identifier)
    return keys


def _identifier_identity(record):
    keys = set()
    for identifier in record.get("identifiers") or []:
        keys |= identifier_keys(identifier)
    return keys


def _same_product(left, right):
    left_ids, right_ids = _identifier_identity(left), _identifier_identity(right)
    if left_ids and right_ids:
        return bool(left_ids & right_ids)
    return normalize_space(str(left.get("name") or "")).casefold() == normalize_space(
        str(right.get("name") or "")).casefold()


def check_identity_collision(root, record, target):
    """Refuse a researched copy of a deterministic product's identity."""
    directory = Path(root) / (PRODUCTS if target == "software" else HARDWARE)
    if not directory.is_dir():
        return
    destination = record["id"]
    for path in directory.glob("*.json"):
        if path.stem == destination:
            continue
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError(f"cannot inspect catalog identity {path.name}: {error}") from error
        if is_researched(existing):
            continue
        if _same_product(existing, record):
            raise ValueError(f"researched record {record['id']!r} shadows deterministic product "
                             f"{existing['id']!r} by product identity")


def derived_evidence(contribution):
    """The rule quotes that must be fetched alongside ordinary evidence."""
    entries = []
    for line in contribution.get("releases") or ():
        for entry in (line.get(derived.DERIVED_KEY) or {}).values():
            entries.append({"source_url": urls.safe_citation_url(entry["source_url"],
                                                                  "derived.source_url"),
                            "quote": entry["quote"]})
    return entries


def _stamp(now=None):
    moment = now or datetime.now(timezone.utc)
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _today(now=None):
    moment = now or datetime.now(timezone.utc)
    return moment.astimezone(timezone.utc).date()


def _truncate(quote, limit=90):
    text = normalize_space(quote)
    return text if len(text) <= limit else text[:limit] + "..."


def _ordinal(day):
    """``1st``/``2nd``/``3rd``/``4th``: the suffix a vendor sentence spells.

    The teens are the exception the naive ``day % 10`` mapping gets wrong, and
    vendors really write them: Helm spells its end-of-life days this way
    ("February 10th, 2027", "August 13th, 2020").
    """
    if 10 <= day % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
    return f"{day}{suffix}"


def _date_pattern(day):
    """Match any day-precision spelling of an ISO day, and nothing coarser.

    Ordinal spellings are day precision too -- "February 10th, 2027" states the
    day exactly as "February 10, 2027" does -- so they are matched here or a
    vendor sentence quoted verbatim could not back the date it states. Nothing
    coarser matches: a month-only "February 2027" is never evidence for a day.
    """
    pattern = _DATE_PATTERNS.get(day)
    if pattern is None:
        parsed = date.fromisoformat(day)
        month, short = parsed.strftime("%B"), parsed.strftime("%b")
        ordinal = _ordinal(parsed.day)
        spelled = "|".join(re.escape(text) for text in (
            f"{month} {parsed.day}, {parsed.year}", f"{month} {parsed.day:02d}, {parsed.year}",
            f"{month} {ordinal}, {parsed.year}",
            f"{short} {parsed.day}, {parsed.year}", f"{short}. {parsed.day}, {parsed.year}",
            f"{short} {parsed.day:02d}, {parsed.year}", f"{short}. {parsed.day:02d}, {parsed.year}",
            f"{short} {ordinal}, {parsed.year}", f"{short}. {ordinal}, {parsed.year}",
            f"{parsed.day} {month} {parsed.year}", f"{parsed.day:02d} {month} {parsed.year}",
            f"{parsed.day} {short} {parsed.year}", f"{parsed.day:02d} {short} {parsed.year}",
            f"{ordinal} {month} {parsed.year}", f"{ordinal} {short} {parsed.year}",
            # US numeric spellings, the matrix convention ("All dates in
            # mm/dd/yyyy format"): leading zeros optional on both fields, and
            # always both a month and a day -- "06/2020" states no day.
            f"{parsed.month}/{parsed.day}/{parsed.year}", f"{parsed.month:02d}/{parsed.day:02d}/{parsed.year}",
            f"{parsed.month}/{parsed.day}/{parsed.year}", f"{parsed.month:02d}/{parsed.day:02d}/{parsed.year}",
            f"{parsed.month}/{parsed.day:02d}/{parsed.year}", f"{parsed.month:02d}/{parsed.day}/{parsed.year}",
            # DD-Mon-YYYY vendor format, e.g. "25-Aug-2028" or "9-Aug-2022":
            # day is written without a leading zero, so match both widths.
            f"{parsed.day}-{short}-{parsed.year}", f"{parsed.day:02d}-{short}-{parsed.year}",
        ))
        pattern = re.compile(
            rf"(?<![0-9A-Za-z]){re.escape(day)}(?![0-9])"
            rf"|(?<![0-9A-Za-z])(?:{spelled})(?![0-9])", re.IGNORECASE)
        _DATE_PATTERNS[day] = pattern
    return pattern


def date_in_quote(day, quote):
    """True when the exact ISO day appears in ``quote`` at day precision."""
    return bool(_date_pattern(day).search(quote))


def _month_pattern(month):
    """Match the spelled/spoken forms of an ISO month `YYYY-MM`, and its ISO form.

       A month-precision source like Ghost's "Jan 2019" is evidence for a month
       and nothing finer; the match admits the ISO form and the short/long
       month spellings the vendor wrote, at the precision the source states.
    """
    pattern = _DATE_PATTERNS.get(month)
    if pattern is None:
        parsed = date.fromisoformat(month + "-01")
        long_name, short = parsed.strftime("%B"), parsed.strftime("%b")
        spelled = "|".join(re.escape(text) for text in (
            f"{long_name} {parsed.year}", f"{short} {parsed.year}",
            f"{short}. {parsed.year}", f"{parsed.year} {long_name}", f"{parsed.year} {short}",
        ))
        pattern = re.compile(
            rf"(?<![0-9A-Za-z]){re.escape(month)}(?![0-9])"
            rf"|(?<![0-9A-Za-z])(?:{spelled})(?![0-9A-Za-z])", re.IGNORECASE)
        _DATE_PATTERNS[month] = pattern
    return pattern


def date_in_quote(value, quote):
    """True when the stored milestone date appears in ``quote`` at its precision.

    A day-precision value matches day spellings; a month-precision value matches
    month spellings only, so a coarser source cannot back a finer stored date.
    """
    if DAY.fullmatch(value):
        return bool(_date_pattern(value).search(quote))
    if MONTH.fullmatch(value):
        return bool(_month_pattern(value).search(quote))
    return False


def missing_backing(milestones, evidence, provenance=None, release_id=None, product_name=None):
    """Return milestone keys whose in-scope stored quote does not state the date."""
    derived = provenance or {}
    quoted = {key: [] for key in MILESTONE_KEYS}
    for entry in evidence:
        scope = entry.get("scope") or {}
        if scope.get("releases") and (release_id is None or release_id not in scope["releases"]):
            continue
        if (scope.get("product") and product_name is not None
                and normalize_space(scope["product"]).casefold()
                != normalize_space(str(product_name)).casefold()):
            continue
        for key in entry.get("milestones") or MILESTONE_KEYS:
            quoted[key].append(entry["quote"])
    return [key for key in MILESTONE_KEYS
            if milestones.get(key) and key not in derived
            and not any(date_in_quote(milestones[key], quote) for quote in quoted[key])]


def quote_of(evidence):
    """The display quote: every evidence quote, whitespace-normalized.

    Joined with a single space: validation requires the stored quote to equal
    its own whitespace-normalized form, and a join that introduced any other
    separator would not survive that folding. A contribution may cite several
    sentences, so the join is one folded space and nothing here can reopen a
    line break.
    """
    return normalize_space(" ".join(entry["quote"] for entry in evidence))


def fetch_text(url):
    """GET one source page as text, politely identified."""
    return net.get_text(url)


def page_text(html):
    """Visible page text with tags dropped, entities decoded, whitespace folded."""
    text = HTML_SKIP.sub(" ", html)
    text = HTML_TAG.sub(" ", text)
    return normalize_space(unescape(text))


def _text(value, where, field):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{where}: {field} must be a non-empty string")
    return value.strip()


def _day(value, where):
    if not isinstance(value, str) or not DAY.fullmatch(value):
        raise ValueError(f"{where}: {value!r} is not an ISO day (YYYY-MM-DD); month-only "
                         "or inferred dates are never accepted")
    try:
        date.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"{where}: {value!r} is not a real calendar day") from error
    return value


def _milestone(value, where):
    """A milestone date the source publishes as a day or a month.

    The published product schema admits both `YYYY-MM` and `YYYY-MM-DD`; a
    contribution states whatever the source states, at the precision the source
    actually gives. A month is never padded to a day here, so a vendor table
    that names only "Jan 2019" records a month precision that stays a month on
    the live catalog and is excluded from the day-precision OpenEoX export.
    """
    if not isinstance(value, str):
        raise ValueError(f"{where}: {value!r} is not an ISO date string")
    if DAY.fullmatch(value):
        try:
            date.fromisoformat(value)
        except ValueError as error:
            raise ValueError(f"{where}: {value!r} is not a real calendar day") from error
        return value
    if MONTH.fullmatch(value):
        try:
            date.fromisoformat(value + "-01")
        except ValueError as error:
            raise ValueError(f"{where}: {value!r} is not a real calendar month") from error
        return value
    raise ValueError(f"{where}: {value!r} is not an ISO day (YYYY-MM-DD) or month "
                     "(YYYY-MM); finer precision is never inferred from a coarser source")
    return value


def _url(value, where):
    text = _text(value, where, "source_url")
    parsed = urlsplit(text)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError(f"{where}: source_url must be an absolute http(s) URL: {text!r}")
    return text


def _parse_milestones(value, where, allow_empty=False):
    """One milestone set. ``allow_empty`` admits an explicit "no dates" set.

    A release line may legitimately state no dates: a branch the notice covers
    while it announces nothing about its end. That is a different thing from a
    contribution that states nothing at all, which the product-level set still
    refuses, so only release lines pass ``allow_empty``.
    """
    if not isinstance(value, dict) or (not value and not allow_empty):
        raise ValueError(f"{where}: milestones must be a non-empty object")
    unknown = sorted(set(value) - set(MILESTONE_KEYS))
    if unknown:
        raise ValueError(f"{where}: unknown milestone keys {unknown}; allowed {list(MILESTONE_KEYS)}")
    milestones = dict.fromkeys(MILESTONE_KEYS)
    for key, day in value.items():
        # An explicit null states the same thing the missing key does -- no
        # announced date -- and is how a release line that the notice leaves
        # undated says so out loud. Only lines admit it; the product-level set
        # still refuses an empty object because that contribution states nothing.
        if day is None and allow_empty:
            continue
        milestones[key] = _milestone(day, f"{where}: milestones.{key}")
    return milestones


def validate_derived(milestones, provenance, where, release_ids=None):
    """Check one release line's derived-date disclosure against its own rule.

    A contribution may state a milestone the vendor dates only as a *rule* --
    an explicit duration, the release that ends this line, or the parent platform
    whose lifecycle it follows. The stored provenance is checked here against the
    dates beside it: a rule that does not produce the stored date is refused
    rather than published as a vendor fact. The check is ``engine.derived``'s --
    the same one the catalog gate runs -- so a contribution and the committed
    record cannot disagree about what a rule produces. Returns the entry as it
    was written, or ``None`` when the line states only vendor dates.
    """
    if provenance is None:
        return None
    derived.validate_milestone_provenance(milestones, provenance, where, release_ids)
    for entry in provenance.values():
        urls.safe_citation_url(entry["source_url"], f"{where}.derived.source_url")
    return copy.deepcopy(provenance)


def _parse_releases(value, where):
    """The release lines of a contribution that covers more than one branch.

    The text is just the quotes: whatever a branch states is quoted verbatim in
    the document quoted in `quote`, so a verbatim dump per branch would only
    restate it. The important part is that every branch the notice covers is
    named, dated branches and undated ones alike -- an undated line is a branch
    with no announced end, never a line that vanished from its own notice.
    """
    if not isinstance(value, list) or not value:
        raise ValueError(f"{where}: releases must be a non-empty array of release lines")
    lines, seen = [], set()
    for index, raw in enumerate(value):
        at = f"{where}: releases[{index}]"
        if not isinstance(raw, dict):
            raise ValueError(f"{at}: release must be an object")
        unknown = sorted(set(raw) - RELEASE_KEYS)
        if unknown:
            raise ValueError(f"{at}: unknown fields {unknown}; allowed {sorted(RELEASE_KEYS)}")
        release = {"id": _text(raw.get("id"), at, "id")}
        release["name"] = _text(raw.get("name", release["id"]), at, "name")
        release["milestones"] = _parse_milestones(raw.get("milestones"), at, allow_empty=True)
        release["milestone_provenance"] = validate_derived(
            release["milestones"], raw.get("milestone_provenance"), at,
            {line["id"] for line in value if isinstance(line, dict) and isinstance(line.get("id"), str)})
        if release["id"] in seen:
            raise ValueError(f"{at}: duplicate release id {release['id']!r}")
        seen.add(release["id"])
        lines.append(release)
    return lines


def _parse_evidence(value, where, releases):
    """Validate stored quotes and their product/release scope."""
    if not isinstance(value, list) or not value:
        raise ValueError(f"{where}: evidence must be a non-empty array of stored quotes")
    release_ids = {release["id"] for release in releases}
    entries = []
    for index, raw in enumerate(value):
        at = f"{where}: evidence[{index}]"
        if not isinstance(raw, dict):
            raise ValueError(f"{at}: evidence entry must be an object")
        unknown = sorted(set(raw) - EVIDENCE_KEYS)
        if unknown:
            raise ValueError(f"{at}: unknown fields {unknown}; allowed {sorted(EVIDENCE_KEYS)}")
        quote = normalize_space(_text(raw.get("quote"), at, "quote"))
        if len(quote) < MIN_QUOTE:
            raise ValueError(f"{at}: quote must store at least {MIN_QUOTE} characters of the source "
                             "sentence verbatim; that sentence is the evidence")
        entry = {"quote": quote,
                 "source_url": urls.safe_citation_url(raw.get("source_url"), f"{at}.source_url"),
                 "retrieved_at": _day(raw.get("retrieved_at"), f"{at}.retrieved_at")}
        scope = raw.get("scope")
        if scope is not None:
            if not isinstance(scope, dict):
                raise ValueError(f"{at}.scope must be an object")
            unknown_scope = sorted(set(scope) - SCOPE_KEYS)
            if unknown_scope:
                raise ValueError(f"{at}.scope has unknown fields {unknown_scope}")
            parsed_scope = {}
            if "product" in scope:
                parsed_scope["product"] = _text(scope["product"], f"{at}.scope", "product")
            if "releases" in scope:
                values = scope["releases"]
                if not isinstance(values, list) or not values:
                    raise ValueError(f"{at}.scope.releases must be a non-empty array")
                parsed_scope["releases"] = [_text(value, f"{at}.scope.releases", "release")
                                             for value in values]
                unknown_releases = sorted(set(parsed_scope["releases"]) - release_ids)
                if unknown_releases:
                    raise ValueError(f"{at}.scope names releases not in the contribution: {unknown_releases}")
            if not parsed_scope:
                raise ValueError(f"{at}.scope must state product or releases")
            entry["scope"] = parsed_scope
        keys = raw.get("milestones")
        if keys is not None:
            if not isinstance(keys, list) or not keys:
                raise ValueError(f"{at}: milestones must be a non-empty array of milestone keys")
            unknown_keys = sorted(set(keys) - set(MILESTONE_KEYS))
            if unknown_keys:
                raise ValueError(f"{at}: unknown milestone keys {unknown_keys}")
            for key in keys:
                if not any(release["milestones"][key] for release in releases):
                    raise ValueError(f"{at}: evidence claims {MILESTONE_LABELS[key]} but the "
                                     "contribution states no such date")
            entry["milestones"] = list(dict.fromkeys(keys))
        entries.append(entry)
    return entries


def _parse_links(value, where):
    if value is None:
        return {}
    if isinstance(value, dict):
        links = {}
        for key, href in value.items():
            if href is None:
                links[str(key)] = None
            else:
                links[str(key)] = _url(href, f"{where}: links.{key}")
        return links
    if isinstance(value, list):
        links = {}
        for index, item in enumerate(value):
            at = f"{where}: links[{index}]"
            if not isinstance(item, dict) or set(item) != {"rel", "href"}:
                raise ValueError(f"{at}: link must be {{\"rel\": ..., \"href\": ...}}")
            links[_text(item["rel"], at, "rel")] = _url(item["href"], at)
        return links
    raise ValueError(f"{where}: links must be an object or a list of {{rel, href}} pairs")


def _parse_identifiers(value, where):
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{where}: identifiers must be an array")
    identifiers = []
    for index, item in enumerate(value):
        at = f"{where}: identifiers[{index}]"
        if not isinstance(item, dict) or not {"type", "id"} <= set(item):
            raise ValueError(f"{at}: identifier must be an object with type and id")
        identifiers.append({"type": _text(item["type"], at, "type"), "id": _text(item["id"], at, "id")})
    return identifiers


def parse_contribution(raw, path="<contribution>"):
    """Validate one contribution file into its normalized form, or raise."""
    where = str(path)
    if not isinstance(raw, dict):
        raise ValueError(f"{where}: contribution must be a JSON object")
    unknown = sorted(set(raw) - CONTRIBUTION_KEYS)
    if unknown:
        raise ValueError(f"{where}: unknown fields {unknown}; allowed {sorted(CONTRIBUTION_KEYS)}")
    target = raw.get("target")
    if target not in TARGETS:
        raise ValueError(f"{where}: target must be one of {list(TARGETS)}")
    if target == "hardware" and "releases" in raw:
        raise ValueError(f"{where}: releases are software-only; a hardware record states one "
                         "milestone set for the model the notice describes")
    # A contribution states its dates either for the product as a whole
    # (`milestones`) or per release line (`releases`), never both: a product
    # whose branches differ in lifecycle has no single truthful milestone set.
    if "milestones" in raw and "releases" in raw:
        raise ValueError(f"{where}: state milestones once -- either the product's own `milestones` "
                         "or one entry per branch under `releases`, not both")
    name = _text(raw.get("name"), where, "name")
    if "id" in raw:
        record_id = _text(raw["id"], where, "id")
    else:
        record_id = RESEARCHED_VERIFIER_PREFIX + slugify(name)
    if not SLUG.fullmatch(record_id):
        raise ValueError(f"{where}: id {record_id!r} is not a lower-case hyphen slug")
    if not record_id.startswith(RESEARCHED_VERIFIER_PREFIX):
        raise ValueError(f"{where}: researched records live in the {RESEARCHED_VERIFIER_PREFIX}<slug> "
                         f"id namespace; {record_id!r} is not one of them")
    # The release labels the thing the notice describes. Defaulting to the id's
    # own slug keeps every release id URL-safe and stable, which the OpenEoX
    # export and the feed identities both depend on.
    if "releases" in raw:
        lines = _parse_releases(raw["releases"], where)
    else:
        default_release = record_id[len(RESEARCHED_VERIFIER_PREFIX):]
        label = _text(raw.get("release", default_release), where, "release")
        milestones = _parse_milestones(raw.get("milestones"), where)
        lines = [{"id": label, "name": label, "milestones": milestones,
                  "milestone_provenance": validate_derived(
                      milestones, raw.get("milestone_provenance") if target == "software" else None,
                      where, {label})}]
    contribution = {
        "target": target,
        "contributor": _text(raw.get("contributor"), where, "contributor"),
        # The whole-catalog view of the record's first line, kept where callers
        # that predate multi-release contributions already look for it.
        "milestones": lines[0]["milestones"],
        "releases": lines,
    }
    method = raw.get("method", "manual")
    if method not in METHODS:
        raise ValueError(f"{where}: method must be one of {list(METHODS)}")
    contribution["method"] = method
    contribution["evidence"] = _parse_evidence(raw.get("evidence"), where, lines)
    contribution["name"] = name
    contribution["id"] = record_id
    if target == "software":
        category = raw.get("category")
        if category not in UPSTREAM_CATEGORIES:
            raise ValueError(f"{where}: category must be one of {list(UPSTREAM_CATEGORIES)}")
        contribution["category"] = category
        contribution["release"] = lines[0]["id"]
        contribution["identifiers"] = _parse_identifiers(raw.get("identifiers"), where)
        contribution["links"] = _parse_links(raw.get("links"), where)
    else:
        software_only = sorted({"identifiers", "links", "release", "category", "milestone_provenance"} & set(raw))
        if software_only:
            raise ValueError(f"{where}: {software_only} are software-only fields")
        contribution["vendor"] = _text(raw.get("vendor"), where, "vendor")
        contribution["product_line"] = _text(raw.get("product_line", contribution["vendor"]),
                                             where, "product_line")
    if "stale_after" in raw and raw["stale_after"] is not None:
        contribution["stale_after"] = _day(raw["stale_after"], f"{where}: stale_after")
    else:
        contribution["stale_after"] = None
    # Context the record itself has no field for: a researched software record
    # states its vendor nowhere else, so it is kept in the research object.
    context = SOFTWARE_CONTEXT if target == "software" else HARDWARE_CONTEXT
    for key in context:
        if raw.get(key) is not None:
            contribution[key] = _text(raw[key], where, key)
    unbacked = [key for line in lines
                for key in missing_backing(line["milestones"], contribution["evidence"],
                                           line.get("milestone_provenance"),
                                           line["id"], contribution["name"])]
    if unbacked:
        labels = ", ".join(dict.fromkeys(MILESTONE_LABELS[key] for key in unbacked))
        raise ValueError(f"{where}: no stored quote states the {labels} date; every milestone must be "
                         "quoted verbatim from the source")
    return contribution


def verify_evidence(evidence, fetch=None, allow_stale=False):
    """Confirm every stored quote appears in freshly fetched source text.

    ``allow_stale`` is the offline mode: the stored evidence is accepted as-is
    and the caller records that it was not refetched. Returns True when the
    evidence was verified against the live sources.
    """
    if allow_stale:
        return False
    fetcher = fetch or fetch_text
    pages = {}
    for entry in evidence:
        url = entry["source_url"]
        if url not in pages:
            try:
                pages[url] = page_text(fetcher(url))
            except (requests.RequestException, OSError) as error:
                raise ValueError(f"Cannot verify evidence from {urls.redact_url(url)}: {error}; rerun with "
                                 "--allow-stale-evidence to admit the stored evidence unverified") from error
        if entry["quote"] not in pages[url]:
            raise ValueError(f"Quote not found in {urls.redact_url(url)}: {_truncate(entry['quote'])}")
    return True


def verify_derived_evidence(contribution, fetch=None, allow_stale=False):
    """Verify every derived rule quote in addition to ordinary evidence."""
    return verify_evidence(derived_evidence(contribution), fetch=fetch, allow_stale=allow_stale)


def research_object(contribution, evidence, verified_at):
    """The provenance.research object of one researched record."""
    research = {
        "quote": quote_of(evidence),
        "source_url": evidence[0]["source_url"],
        "retrieved_at": max(entry["retrieved_at"] for entry in evidence),
        "contributor": contribution["contributor"],
        "method": contribution["method"],
        "verified_at": verified_at,
        "stale_after": contribution["stale_after"],
        "evidence": copy.deepcopy(evidence),
    }
    context = SOFTWARE_CONTEXT if contribution["target"] == "software" else HARDWARE_CONTEXT
    for key in context:
        if key in contribution:
            research[key] = contribution[key]
    return research


def contribution_cell(research):
    """The verbatim contribution as a cell, for ``upstream.Contribution``."""
    return {"text": research["quote"], "value": None, "datetime": None, "role": None,
            "links": list(dict.fromkeys(entry["source_url"] for entry in research["evidence"]))}


def hardware_status(milestones, today):
    """Status derived from the stored dates, never from an absent one.

    ``eol`` once the terminal date has passed; ``expiring`` when a published end
    date falls inside the review horizon or has already passed while the record
    still carries a later one; ``supported`` when every published end date is
    further out; ``unknown`` when no end date is published at all.
    """
    ends = [milestones[key] for key in ("eos", "eossec", "eol") if milestones[key]]
    if not ends:
        return "unknown"
    terminal = milestones["eol"]
    if terminal and date.fromisoformat(terminal) <= today:
        return "eol"
    nearest = min(date.fromisoformat(day) for day in ends)
    if nearest <= today or (nearest - today).days <= EXPIRING_DAYS:
        return "expiring"
    return "supported"


def build_record(contribution, research, checked, now=None):
    """The published record for one validated, verified contribution."""
    cell = contribution_cell(research)
    verifier = verifier_for(contribution["contributor"])
    provenance = {"verifier": verifier, "last_checked": checked, "research": research}
    if contribution["target"] == "software":
        provenance.update({"source_url": research["source_url"], "upstream_modified": None})
        return {
            "$schema": "https://zarguell.github.io/eoltracker/v1/schema/product.json",
            "id": contribution["id"], "name": contribution["name"], "category": "software",
            "upstream_category": contribution["category"], "identifiers": contribution["identifiers"],
            "labels": {}, "links": contribution["links"],
            "releases": [{"id": line["id"], "name": line["name"], "milestones": dict(line["milestones"]),
                          "upstream": {"name": line["name"], "Contribution": cell},
                          **({derived.DERIVED_KEY: copy.deepcopy(line[derived.DERIVED_KEY])}
                             if line.get(derived.DERIVED_KEY) else {})}
                         for line in contribution["releases"]],
            "provenance": provenance,
        }
    provenance["source_urls"] = list(dict.fromkeys(entry["source_url"] for entry in research["evidence"]))
    return {
        "$schema": "https://zarguell.github.io/eoltracker/v1/schema/hardware.json",
        "id": contribution["id"], "name": contribution["name"], "category": "hardware",
        "vendor": contribution["vendor"], "product_line": contribution["product_line"],
        "milestones": dict(contribution["milestones"]),
        "status": hardware_status(contribution["milestones"], _today(now)),
        "upstream": {"Contribution": cell},
        "provenance": provenance,
    }


def _schema(target):
    path = ROOT / "schema" / SCHEMAS[target]
    schema = json.loads(path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def check_schema(record, target):
    """Validate one record against its published JSON Schema.

    A schema failure is reported as a ``ValueError`` like every other admission
    error, so the CLI exits with a message instead of a traceback.
    """
    from jsonschema.exceptions import ValidationError

    try:
        _schema(target).validate(record)
    except ValidationError as error:
        raise ValueError(f"{record.get('id', '<record>')}: {error.json_path}: {error.message}") from error


def validate_research(record, target):
    """Coherence of a researched record's provenance, independent of any fetch.

    Every rule here re-derives from the stored evidence, so a hand-edited record
    that no longer matches its own quotes fails the catalog gate.
    """
    where = str(record.get("id"))
    record_id = record.get("id")
    if not isinstance(record_id, str) or not SLUG.fullmatch(record_id):
        raise ValueError(f"{where}: researched record id must be a lower-case hyphen slug")
    if not record_id.startswith(RESEARCHED_VERIFIER_PREFIX):
        raise ValueError(f"{where}: researched records live in the {RESEARCHED_VERIFIER_PREFIX}<slug> id "
                         "namespace, so they can never collide with a product a collector may claim")
    provenance = record["provenance"]
    verifier = provenance["verifier"]
    if not verifier.startswith(RESEARCHED_VERIFIER_PREFIX):
        raise ValueError(f"{where}: research provenance requires a "
                         f"{RESEARCHED_VERIFIER_PREFIX}<contributor> verifier, not {verifier!r}")
    research = provenance["research"]
    contributor = research["contributor"]
    if verifier != verifier_for(contributor):
        raise ValueError(f"{where}: verifier {verifier!r} does not match contributor {contributor!r}")
    if research["quote"] != normalize_space(research["quote"]):
        raise ValueError(f"{where}: research.quote must store normalized whitespace")
    if len(research["quote"]) < MIN_QUOTE:
        raise ValueError(f"{where}: research.quote is shorter than {MIN_QUOTE} characters")
    if research["method"] not in METHODS:
        raise ValueError(f"{where}: research.method must be one of {list(METHODS)}")
    _day(research["retrieved_at"], f"{where}: research.retrieved_at")
    if research["stale_after"] is not None:
        _day(research["stale_after"], f"{where}: research.stale_after")
    if research["verified_at"] is not None:
        try:
            datetime.fromisoformat(str(research["verified_at"]).replace("Z", "+00:00"))
        except ValueError as error:
            raise ValueError(f"{where}: research.verified_at is not a timestamp: "
                             f"{research['verified_at']!r}") from error
    evidence = research["evidence"]
    if not isinstance(evidence, list) or not evidence:
        raise ValueError(f"{where}: research.evidence must be a non-empty array")
    for index, entry in enumerate(evidence):
        at = f"{where}: research.evidence[{index}]"
        unknown = sorted(set(entry) - EVIDENCE_KEYS)
        if unknown:
            raise ValueError(f"{at}: unknown fields {unknown}")
        if normalize_space(_text(entry.get("quote"), at, "quote")) != entry["quote"]:
            raise ValueError(f"{at}: quote must store normalized whitespace")
        if len(entry["quote"]) < MIN_QUOTE:
            raise ValueError(f"{at}: quote is shorter than {MIN_QUOTE} characters")
        urls.safe_citation_url(entry["source_url"], f"{at}.source_url")
        _day(entry["retrieved_at"], f"{at}.retrieved_at")
        scope = entry.get("scope")
        if scope is not None:
            if not isinstance(scope, dict) or set(scope) - SCOPE_KEYS:
                raise ValueError(f"{at}.scope must contain only product/releases")
            if "product" in scope:
                _text(scope["product"], f"{at}.scope", "product")
            if "releases" in scope:
                if not isinstance(scope["releases"], list) or not scope["releases"]:
                    raise ValueError(f"{at}.scope.releases must be a non-empty array")
                for release_id in scope["releases"]:
                    _text(release_id, f"{at}.scope.releases", "release")
            if not scope:
                raise ValueError(f"{at}.scope must state product or releases")
    if research["quote"] != quote_of(evidence):
        raise ValueError(f"{where}: research.quote is not the evidence quotes joined verbatim")
    if research["source_url"] != evidence[0]["source_url"]:
        raise ValueError(f"{where}: research.source_url must be the first evidence source")
    if research["retrieved_at"] not in {entry["retrieved_at"] for entry in evidence}:
        raise ValueError(f"{where}: research.retrieved_at is not one of the evidence retrieval dates")
    if target == "software":
        if provenance["source_url"] != research["source_url"]:
            raise ValueError(f"{where}: provenance.source_url must be the researched source")
        releases = record["releases"]
        if not releases:
            raise ValueError(f"{where}: a researched software record states at least one release")
        ids = [release["id"] for release in releases]
        if len(set(ids)) != len(ids):
            raise ValueError(f"{where}: duplicate release ids {ids}")
        for release in releases:
            cell = release.get("upstream", {}).get("Contribution")
            if not isinstance(cell, dict) or cell.get("text") != research["quote"]:
                raise ValueError(f"{where}: release {release['id']!r} must carry the researched quote "
                                 "verbatim under upstream.Contribution")
        # A derived date is checked against its own rule here, not only against
        # the schema: a hand-edited milestone or base that no longer follows the
        # stored rule fails the catalog gate instead of being published.
        derived_ids = {release["id"] for release in releases}
        for release in releases:
            validate_derived(release["milestones"], release.get(derived.DERIVED_KEY),
                             f"{where}/{release['id']}", derived_ids)
        milestone_sets = [release["milestones"] for release in releases]
        published = [{"id": release["id"], "name": release["name"],
                      "milestones": release["milestones"],
                      derived.DERIVED_KEY: release.get(derived.DERIVED_KEY)} for release in releases]
    else:
        source_urls = provenance["source_urls"]
        if source_urls[0] != research["source_url"] or set(source_urls) != {e["source_url"] for e in evidence}:
            raise ValueError(f"{where}: provenance.source_urls must be the evidence sources, "
                             "primary first")
        cell = record["upstream"].get("Contribution")
        if not isinstance(cell, dict) or cell.get("text") != research["quote"]:
            raise ValueError(f"{where}: the record must carry the researched quote verbatim "
                             "under upstream.Contribution")
        milestone_sets = [record["milestones"]]
        published = [record]
    # An entry's `milestones` says which dates its quote backs; the record may
    # publish those dates on more than one release line (a notice that dates a
    # branch is quoted once for it), so the claim is checked against every set
    # the record carries rather than any one of them.
    stated = {key for milestones in milestone_sets for key, day in milestones.items() if day}
    for index, entry in enumerate(evidence):
        for key in entry.get("milestones") or ():
            if key not in stated:
                raise ValueError(f"{where}: research.evidence[{index}] claims "
                                 f"{MILESTONE_LABELS[key]} but the record states no such date")
    for line in published:
        unbacked = missing_backing(line["milestones"], evidence, line.get(derived.DERIVED_KEY),
                                   line.get("id"), line.get("name"))
        if unbacked:
            labels = ", ".join(dict.fromkeys(MILESTONE_LABELS[key] for key in unbacked))
            raise ValueError(f"{where}: no stored quote states the {labels} date")


def research_view(record, today=None):
    """Template-ready provenance view of a researched record, else None."""
    research = record.get("provenance", {}).get("research")
    if not research:
        return None
    reference = today or _today()
    last_checked = record["provenance"].get("last_checked")
    age_days = None
    stale_reasons = []
    if last_checked:
        try:
            moment = datetime.fromisoformat(str(last_checked).replace("Z", "+00:00")).date()
        except ValueError:
            moment = None
        if moment is not None:
            age_days = (reference - moment).days
            if age_days > STALE_DAYS:
                stale_reasons.append("age")
    stale_after = research.get("stale_after")
    if stale_after and reference > date.fromisoformat(stale_after):
        stale_reasons.append("stale_after")
    return {
        "contributor": research["contributor"], "method": research["method"],
        "retrieved_at": research["retrieved_at"], "verified_at": research.get("verified_at"),
        "verified": bool(research.get("verified_at")), "stale_after": stale_after,
        "quote": research["quote"], "source_url": research["source_url"],
        "sources": [{"source_url": entry["source_url"], "retrieved_at": entry["retrieved_at"],
                     "quote": entry["quote"]} for entry in research["evidence"]],
        "last_checked": last_checked, "age_days": age_days,
        "stale": bool(stale_reasons), "stale_reasons": stale_reasons,
        "vendor": research.get("vendor"), "summary": research.get("summary"),
    }


def record_path(root, target, record_id):
    return Path(root) / (PRODUCTS if target == "software" else HARDWARE) / (record_id + ".json")


def read_existing(destination, verifier):
    """The record already at ``destination``, once its verifier is compatible.

    Research never replaces, shadows or extends a record another pipeline owns:
    any other verifier — deterministic or another contributor's — refuses here.
    """
    if not destination.exists():
        return None
    old = json.loads(destination.read_text(encoding="utf-8"))
    if not isinstance(old, dict) or not isinstance(old.get("provenance"), dict):
        raise ValueError(f"{destination.name} is not a catalog record; refusing to overwrite it")
    old_verifier = old["provenance"].get("verifier")
    if old_verifier != verifier:
        raise ValueError(f"{destination.name} already exists with verifier {old_verifier!r}; a researched "
                         f"record may only be written by its own {verifier!r} verifier")
    return old


def _stable(record):
    """A record's content apart from the times a reinstall legitimately moves.

    ``verified_at`` keeps only whether the evidence has ever been refetched, so
    admitting stored evidence and later verifying it is a real change while a
    re-verification on another day is not.
    """
    stable = copy.deepcopy(record)
    stable["provenance"]["last_checked"] = None
    stable["provenance"]["research"]["verified_at"] = bool(stable["provenance"]["research"]["verified_at"])
    return stable


def append_log(root, entry):
    """Append one ``{id, action, at}`` line to the committed contribution log."""
    path = Path(root) / LOG
    entries = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    if not isinstance(entries, list):
        raise ValueError(f"{path} must hold a JSON array of log entries")
    entries.append(entry)
    dump(path, entries)
    return path


def _validate_catalog(root, target):
    from .validation import validate_data, validate_hardware

    if target == "software":
        if (Path(root) / "manifest.json").exists():
            validate_data(root)
    else:
        validate_hardware(root)


def _prepare(path, root, fetch, allow_stale, now):
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as error:
        raise ValueError(f"cannot read contribution: {error}") from error
    except json.JSONDecodeError as error:
        raise ValueError(f"not valid JSON: {error}") from error
    contribution = parse_contribution(raw, path=str(path))
    verified = verify_evidence(contribution["evidence"], fetch=fetch, allow_stale=allow_stale)
    if verified:
        verified = verify_derived_evidence(contribution, fetch=fetch, allow_stale=allow_stale)
    checked = _stamp(now)
    research = research_object(contribution, contribution["evidence"],
                               checked if verified else None)
    record = build_record(contribution, research, checked, now=now)
    check_schema(record, contribution["target"])
    validate_research(record, contribution["target"])
    check_identity_collision(root, record, contribution["target"])
    destination = record_path(root, contribution["target"], record["id"])
    existing = read_existing(destination, record["provenance"]["verifier"])
    return contribution, record, verified, destination, existing


def _report(path, contribution, record, verified, destination, existing, action, written):
    """The one-line report of what one contribution states and where it went.

    Every release line is named, undated ones included: a branch the notice
    covers with no announced end must read as "no dates" here rather than be
    absent from the report, which is the same honesty the record itself
    publishes.
    """
    lines = (record["releases"] if contribution["target"] == "software"
             else [{"id": record["id"], "milestones": record["milestones"]}])
    stated = "; ".join(
        f"{line['id']}: " + ", ".join(f"{key}={line['milestones'][key]}" for key in MILESTONE_KEYS
                                      if line["milestones"][key])
        if any(line["milestones"][key] for key in MILESTONE_KEYS) else f"{line['id']}: no dates"
        for line in lines)
    return {"path": str(path), "target": contribution["target"], "id": record["id"],
            "verifier": record["provenance"]["verifier"], "milestones": lines[0]["milestones"],
            "releases": [{"id": line["id"], "milestones": dict(line["milestones"])} for line in lines],
            "stated": stated,
            "sources": [entry["source_url"] for entry in record["provenance"]["research"]["evidence"]],
            "verified": verified, "existing": existing is not None,
            "destination": str(destination), "action": action, "written": written}


def data_root(root=None):
    """The catalog directory a contribution is admitted into."""
    return Path(root) if root is not None else ROOT / DATA


def check_file(path, root=None, fetch=None, allow_stale=False, now=None):
    """Validate one contribution exactly as ``install_file`` would, writing nothing."""
    root = data_root(root)
    contribution, record, verified, destination, existing = _prepare(path, root, fetch, allow_stale, now)
    return _report(path, contribution, record, verified, destination, existing, "check", False)


def install_file(path, root=None, fetch=None, allow_stale=False, now=None):
    """Install one validated contribution into the catalog.

    Reinstalling unchanged content is a no-op so a second run is byte-identical
    (AGENTS.md import convention); changed content is an update and is logged.
    """
    root = data_root(root)
    contribution, record, verified, destination, existing = _prepare(path, root, fetch, allow_stale, now)
    action = "install" if existing is None else "update"
    if existing is not None and _stable(existing) == _stable(record):
        return _report(path, contribution, record, verified, destination, existing, "unchanged", False)
    previous = destination.read_bytes() if destination.exists() else None
    dump(destination, record)
    try:
        _validate_catalog(root, contribution["target"])
    except Exception:
        if previous is None:
            destination.unlink()
        else:
            destination.write_bytes(previous)
        raise
    append_log(root, {"id": record["id"], "action": action, "at": record["provenance"]["last_checked"]})
    return _report(path, contribution, record, verified, destination, existing, action, True)


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="python -m engine contribute",
        description="Validate or install one-time researched lifecycle contributions.")
    parser.add_argument("files", nargs="*", metavar="contribution.json",
                        help="contribution files to process; default contributions/*.json")
    parser.add_argument("--check", action="store_true", help="validate only (the default)")
    parser.add_argument("--install", action="store_true",
                        help="write validated records into data/ and append data/contributions-log.json")
    parser.add_argument("--allow-stale-evidence", action="store_true",
                        help="do not refetch source_url; admit the stored evidence unverified")
    args = parser.parse_args(argv)
    if args.check and args.install:
        parser.error("--check and --install are mutually exclusive")
    paths = [Path(name) for name in args.files] or sorted((ROOT / CONTRIBUTIONS).glob("*.json"))
    if not paths:
        parser.error(f"no contribution files in {ROOT / CONTRIBUTIONS}")
    failures = 0
    for path in paths:
        try:
            if args.install:
                report = install_file(path, allow_stale=args.allow_stale_evidence)
            else:
                report = check_file(path, allow_stale=args.allow_stale_evidence)
        except ValueError as error:
            print(f"ERROR {path}: {error}", file=sys.stderr)
            failures += 1
            continue
        evidence = "evidence verified" if report["verified"] else "evidence not refetched"
        print(f"{report['path']}: {report['target']} {report['id']} -> {report['action']} "
              f"[{report['verifier']}] ({report['stated'] or 'no dates'}; {len(report['sources'])} source(s); "
              f"{evidence})")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
