"""Derived lifecycle dates: a published date whose rule the vendor states.

A derived date is not a vendor-stated date, and this module is the one place
that says so. It exists because some vendors publish the *rule* that ends a
release's support — an explicit duration ("five years from general
availability"), an explicit trigger (a named release that supersedes this one),
or an explicit inheritance ("this component follows the same lifecycle as its
parent platform") — while the resulting calendar day is arithmetic on a base
date the vendor does state.

AGENTS.md rule 2 forbids inventing a date. It does not forbid stating a date
whose every input is published: the base date, the rule and the arithmetic are
all checkable, so the result is *recomputable* rather than inferred. What the
rule does forbid, and what this module refuses, is derivation from cadence
alone — "a new major every year, so this one ends next March" has no stated
rule, no stated duration and no stated trigger, and no such entry can be built
here.

Every derived value is published on the record as a sibling object::

    "milestones": {"ga": "2025-04-01", "eol": "2030-04-01", ...},
    "milestone_provenance": {
        "eol": {
            "kind": "derived",
            "method": "release-plus-duration",
            "source_url": "https://vendor.example/lifecycle",
            "quote": "Each release is supported for five years from its general availability date.",
            "base_date": "2025-04-01",
            "base_label": "general availability",
            "duration": {"value": 5, "unit": "year"},
        }
    }

The entry is keyed by the milestone it explains, carries the base the
arithmetic starts from, the rule as the vendor stated it and the page it was
read from — and never a ``result`` field, because the result *is* the milestone
value beside it. That is what makes tampering detectable: this module
re-derives every result from the stored base and rule and refuses a record
whose milestone disagrees (``validate_milestone_provenance``), so a derived
date can never be edited into a number its own rule does not produce.

The disclosure travels with the date everywhere it is consumed:

* the product page and the API documentation mark the cell ``derived`` and
  print the method, the base, the duration/trigger/parent and the quote;
* the record's own ``milestone_provenance`` is published verbatim in the JSON;
* the day-precision feeds (Atom, RSS, iCalendar) and the OpenEoX export carry
  vendor-stated days only, so a derived milestone is excluded there and the
  exclusion is enumerated with its reason — never silently carried as if the
  vendor had stated the day.

Nothing here is presentation logic; the site reads these helpers the same way a
collector does.
"""
from __future__ import annotations

import re
from calendar import monthrange
from datetime import date, timedelta
from urllib.parse import urlsplit

# The record field this module owns. It is a release-level sibling of
# `milestones` (a hardware record is one model with one milestone set and
# carries no releases, so the property is software-only by construction).
DERIVED_KEY = "milestone_provenance"
KIND = "derived"
MILESTONE_KEYS = ("ga", "eos", "eossec", "eol")
# A derived claim always ends a release's support, so an inheritance refers to a
# parent's end milestone; `ga` is a beginning, not a deadline.
END_MILESTONES = ("eos", "eossec", "eol")
METHODS = ("release-plus-duration", "release-trigger", "support-inheritance")
# Which branch key each method carries. The three are mutually exclusive: a
# duration and a trigger on one entry would leave two answers to recompute.
BRANCH = {
    "release-plus-duration": "duration",
    "release-trigger": "trigger",
    "support-inheritance": "parent",
}
UNITS = ("day", "month", "year")
COMMON_KEYS = ("kind", "method", "source_url", "quote", "base_date", "base_label")
DURATION_KEYS = ("value", "unit")
TRIGGER_KEYS = ("release_id", "date", "label")
PARENT_KEYS = ("product_id", "release_id", "release_name", "milestone", "date", "source_url")
# The same floor the researched-evidence quotes use: the quote is the rule's
# evidence, so a fragment cannot stand in for a vendor sentence.
MIN_QUOTE = 20
DAY = re.compile(r"\d{4}-\d{2}-\d{2}\Z")

# A support-inheritance quote states that the component's support follows its
# parent: it has to state the *relationship*, not merely mention a parent, and
# name a lifecycle, support or policy — because either half alone states the
# parent's own dates rather than the inheritance rule. Vendors word the
# relationship several ways and the real sentences must all pass:
# Microsoft's Fixed Policy says "A component receives the same support as its
# parent product or platform ... When a parent product or platform reaches the
# end of support, so does the component", which never uses the verb "follow".
_INHERITS = re.compile(
    r"\b(?:follow\w*|"
    r"same (?:support|lifecycle|life cycle) as|"
    r"receives? the same|"
    r"so (?:is|does) the component|"
    r"component (?:receives|follows|of))\b",
    re.IGNORECASE)
_COMPONENT = re.compile(r"\b(?:component|lifecycle|life cycle|support|policy)\b", re.IGNORECASE)


def _text(value, where, field):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{where}: {field} must be a non-empty string")
    return value.strip()


def _day(value, where, field):
    if not isinstance(value, str) or not DAY.fullmatch(value):
        raise ValueError(f"{where}: {field} must be an ISO day (YYYY-MM-DD): {value!r}")
    try:
        date.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"{where}: {field} is not a real calendar day: {value!r}") from error
    return value


def _url(value, where, field):
    text = _text(value, where, field)
    parsed = urlsplit(text)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError(f"{where}: {field} must be an absolute http(s) URL: {text!r}")
    return text


def _object(value, where, field, keys):
    """One branch object with exactly ``keys``, each present and non-empty."""
    if not isinstance(value, dict):
        raise ValueError(f"{where}: {field} must be an object")
    unknown = sorted(set(value) - set(keys))
    if unknown:
        raise ValueError(f"{where}: {field} has unknown fields {unknown}; allowed {sorted(keys)}")
    missing = sorted(set(keys) - set(value))
    if missing:
        raise ValueError(f"{where}: {field} is missing {missing}")
    return value


def add_duration(day, value, unit):
    """``day`` plus ``value`` whole ``unit``s of calendar time, as an ISO day.

    The addition is calendar arithmetic on the day the source states, not a
    fixed number of days: a year is the same date one year later, a month is
    the same day of a later month. Months have no 31st and February has no 29th
    in a common year, so a result that would land past the end of its month is
    clamped to that month's last day — the only date the rule can produce
    without naming a day the calendar does not have.
    """
    where = f"derived duration {value!r} {unit!r}"
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{where}: duration value must be a positive integer")
    if unit not in UNITS:
        raise ValueError(f"{where}: duration unit must be one of {list(UNITS)}")
    start = date.fromisoformat(_day(day, where, "base_date"))
    if unit == "day":
        return (start + timedelta(days=value)).isoformat()
    months = value if unit == "month" else value * 12
    index = start.year * 12 + (start.month - 1) + months
    year, month = divmod(index, 12)
    month += 1
    return date(year, month, min(start.day, monthrange(year, month)[1])).isoformat()


def NonDerivedMilestones(milestones, provenance):
    """The milestones the vendor itself states — every key that is not derived.

    A derived milestone is a published date but not a *stated* one, so a
    consumer that carries stated days only (the syndication feeds, the OpenEoX
    export, an exact-day comparison) reads this instead of the raw milestone
    set. Complements ``derive()``: the two are disjoint and together cover the
    non-null milestones.
    """
    derived_keys = set(provenance or {})
    return {key: value for key, value in (milestones or {}).items()
            if value and key not in derived_keys}


def _entry(milestones, key, entry, where, release_ids):
    """Validate one derived entry against the milestone it explains."""
    at = f"{where}: {DERIVED_KEY}.{key}"
    value = milestones.get(key)
    if not value:
        raise ValueError(f"{at}: states a derived date, but the {key} milestone is absent. "
                         "Provenance is keyed only by published milestones; an absent date stays absent")
    _day(value, at, "milestone")
    if not isinstance(entry, dict):
        raise ValueError(f"{at}: must be an object")
    method = entry.get("method")
    if method not in METHODS:
        raise ValueError(f"{at}: method must be one of {list(METHODS)}: {method!r}")
    branch = BRANCH[method]
    expected = set(COMMON_KEYS) | {branch}
    unknown = sorted(set(entry) - expected)
    if unknown:
        raise ValueError(f"{at}: unknown fields {unknown}; a {method} entry carries {sorted(expected)}. "
                         "The three derivation branches are mutually exclusive")
    missing = sorted(expected - set(entry))
    if missing:
        raise ValueError(f"{at}: missing fields {missing} for method {method}")
    if entry.get("kind") != KIND:
        raise ValueError(f"{at}: kind must be {KIND!r}; a derived date is never presented as vendor-stated")
    quote = _text(entry["quote"], at, "quote")
    if len(quote) < MIN_QUOTE:
        raise ValueError(f"{at}: quote must store at least {MIN_QUOTE} characters of the vendor's rule "
                         "verbatim; that sentence is what licenses the derivation")
    _url(entry["source_url"], at, "source_url")
    base = _day(entry["base_date"], at, "base_date")
    _text(entry["base_label"], at, "base_label")
    if method == "release-plus-duration":
        return _duration(at, key, value, base, entry[branch])
    if method == "release-trigger":
        return _trigger(at, key, value, base, entry[branch], release_ids)
    return _parent(at, key, value, base, entry[branch], quote)


def _duration(at, key, value, base, duration):
    _object(duration, at, "duration", DURATION_KEYS)
    recomputed = add_duration(base, duration["value"], duration["unit"])
    if recomputed != value:
        raise ValueError(f"{at}: {duration['value']} {duration['unit']}(s) from {base} is {recomputed}, "
                         f"but the stored {key} milestone is {value}")
    return recomputed


def _trigger(at, key, value, base, trigger, release_ids):
    _object(trigger, at, "trigger", TRIGGER_KEYS)
    release_id = _text(trigger["release_id"], at, "trigger.release_id")
    stated = _day(trigger["date"], at, "trigger.date")
    _text(trigger["label"], at, "trigger.label")
    if stated != value:
        raise ValueError(f"{at}: trigger.date {stated} is not the {key} milestone {value}; the trigger "
                         "release's own date is the derived deadline, or the entry states a different rule")
    if stated < base:
        raise ValueError(f"{at}: trigger.date {stated} precedes base_date {base}; the triggering event "
                         "cannot come before the release it ends")
    if release_ids is not None and release_id not in release_ids:
        raise ValueError(f"{at}: trigger.release_id {release_id!r} names no release in this record; "
                         f"the triggering release must be published here too (have {sorted(release_ids)})")
    return stated


def _parent(at, key, value, base, parent, quote):
    _object(parent, at, "parent", PARENT_KEYS)
    _text(parent["product_id"], at, "parent.product_id")
    _text(parent["release_id"], at, "parent.release_id")
    _text(parent["release_name"], at, "parent.release_name")
    milestone = parent["milestone"]
    if milestone not in END_MILESTONES:
        raise ValueError(f"{at}: parent.milestone must be one of {list(END_MILESTONES)}; support is "
                         "inherited from a parent's deadline, never from its general availability")
    stated = _day(parent["date"], at, "parent.date")
    _url(parent["source_url"], at, "parent.source_url")
    if stated != value:
        raise ValueError(f"{at}: parent.date {stated} is not the {key} milestone {value}; the inherited "
                         "deadline is the parent's own deadline, or the entry claims a different one")
    if stated < base:
        raise ValueError(f"{at}: parent.date {stated} precedes base_date {base}")
    if not (_INHERITS.search(quote) and _COMPONENT.search(quote)):
        raise ValueError(f"{at}: the quote does not state that this component's support follows its "
                         "parent; store the vendor's own sentence for that rule")
    return stated


def validate_milestone_provenance(milestones, provenance, where="<record>", release_ids=None):
    """Refuse a derived entry that does not re-derive to the date beside it.

    ``milestones`` is the release's own milestone set and ``provenance`` its
    ``milestone_provenance``. ``release_ids`` is the set of release ids the
    containing record publishes; when it is supplied, a ``release-trigger``
    entry must name one of them, so a trigger cannot point at a release that
    does not exist in the catalog it is published in.

    Returns ``None`` for an absent property (the property is optional and every
    record that predates it stays valid) and for a consistent one; raises
    ``ValueError`` for anything else, including a stored milestone that no
    rule in its own entry produces.
    """
    if provenance is None:
        return None
    if not isinstance(provenance, dict):
        raise ValueError(f"{where}: {DERIVED_KEY} must be an object keyed by milestone name")
    if not provenance:
        raise ValueError(f"{where}: {DERIVED_KEY} is empty; omit the property instead of stating no rule")
    unknown = sorted(set(provenance) - set(MILESTONE_KEYS))
    if unknown:
        raise ValueError(f"{where}: {DERIVED_KEY} has unknown milestone keys {unknown}; "
                         f"allowed {list(MILESTONE_KEYS)}")
    for key in sorted(provenance):
        _entry(milestones or {}, key, provenance[key], where, release_ids)
    return None


def derive(milestones, provenance, where="<record>", release_ids=None):
    """Re-derive every entry of one provenance object: ``{milestone_key: day}``.

    The recomputation is the validation: this returns the dates the stored base
    and rule produce, and raises the same errors ``validate_milestone_provenance``
    does, so a caller can neither read a tampered result out of a record nor
    treat this as a second, laxer opinion about one.
    """
    validate_milestone_provenance(milestones, provenance, where, release_ids)
    results = {}
    for key, entry in (provenance or {}).items():
        method = entry["method"]
        if method == "release-plus-duration":
            results[key] = add_duration(entry["base_date"], entry["duration"]["value"],
                                        entry["duration"]["unit"])
        elif method == "release-trigger":
            results[key] = entry["trigger"]["date"]
        else:
            results[key] = entry["parent"]["date"]
    return results
