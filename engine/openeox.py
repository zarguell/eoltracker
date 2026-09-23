"""Publish the normalized catalog as OpenEoX Core v1.0 CSD01 records.

A record is written only where the upstream source states the milestones OpenEoX
Core requires (``end_of_security_support`` and ``end_of_life``) and the
chronological mandatory tests 7.1.1 and 7.1.3 of the specification hold. Every
other release is listed in the index with a machine-readable reason, so nothing
is guessed, invented as ``tba``, or dropped silently.

Month precision is one of those reasons. OpenEoX Core properties are RFC 3339
date-times of a stated day, so a release whose source states only a month
(``YYYY-MM``) has no day to publish; it is excluded under
``<property>_month_precision`` rather than padded, and the unknown month is
never widened into a deadline. That is a different claim from an absent date:
the source *did* announce a deadline, at a width this format cannot carry.

A *derived* milestone is the other reason of the same kind, and the sharper one.
``milestone_provenance`` publishes a date whose rule and base the vendor states
(see `engine/derived.py`), so the date is real, published and recomputable — but
it is not a day the vendor states. These properties are the source's own
lifecycle dates, so exporting a derived value as one would present arithmetic as
a vendor statement; the release is excluded under ``<property>_derived`` with
the rule, base and quote named in the reason, and the derived date stays
published in the catalog record where its rule travels with it.

The records carry no product identity: OpenEoX Core deliberately has no product,
vendor or version properties, so the product and release are bound through the
record's URL and through ``index.json`` next to it.

The vendored schema in ``schema/openeox-core.json`` is the unmodified OASIS
CSD01 snapshot; attribution and the required license and notices section are in
``OASIS-NOTICE.txt``. Validation asserts the schema's format vocabulary and the
date-time lexical rules of specification section 4.1.6; it does not imply OASIS
certification or endorsement.
"""
from __future__ import annotations

import functools
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from .site_config import is_month
from . import derived

ROOT = Path(__file__).resolve().parents[1]
SITE_BASE = "https://zarguell.github.io/eoltracker"
UPSTREAM = "https://endoflife.date/api/v1/products/"
# The specification fixes this exact string as the value of every record's
# $schema, so it is also what the records identifier below has to say.
SCHEMA_URL = "https://docs.oasis-open.org/openeox/eox-core/v1.0/schema/core.json"
SCHEMA_SNAPSHOT_URL = "https://docs.oasis-open.org/openeox/eox-core/v1.0/csd01/schema/core.json"
META_SCHEMA_URL = "https://docs.oasis-open.org/openeox/eox-core/v1.0/schema/meta.json"
CORE_SCHEMA_PATH = ROOT / "schema" / "openeox-core.json"
INDEX_NAME = "index.json"
SITE_PATH = ("v1", "openeox")

PRODUCT_ID = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
# RFC 3339 section 5.6 ABNF with the deviations of specification section 4.1.6:
# upper case T and Z only, and no leap seconds.
TIMESTAMP = re.compile(
    r"\d{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])"
    r"T(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d(?:\.\d+)?"
    r"(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)"
)
DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
# OpenEoX Core property names; general_availability and end_of_sales are
# optional, end_of_security_support and end_of_life are required.
FIELDS = ("general_availability", "end_of_sales", "end_of_security_support", "end_of_life")
REQUIRED = ("end_of_security_support", "end_of_life")
# Catalog milestone keys are site shorthand, not OpenEoX property names.
MILESTONE_KEYS = {
    "ga": "general_availability",
    "eos": "end_of_sales",
    "eossec": "end_of_security_support",
    "eol": "end_of_life",
}
TITLES = {
    "general_availability": "general availability",
    "end_of_sales": "end of sales",
    "end_of_security_support": "end of security support",
    "end_of_life": "end of life",
}
# End milestones are inclusive last days, general availability is a first day.
MIDNIGHT_FIELD = "general_availability"
LAST_SECOND = "23:59:59"
FIRST_SECOND = "00:00:00"


@functools.cache
def _validator():
    schema = json.loads(CORE_SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def _instant(value):
    """Return the aware UTC moment of a valid CSD01 date-time, else None."""
    if not isinstance(value, str) or value == "tba" or not TIMESTAMP.fullmatch(value):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        # Syntactically shaped but not a real instant, e.g. 2025-02-30.
        return None


def _utc_text(moment):
    text = moment.strftime("%Y-%m-%dT%H:%M:%S")
    if moment.microsecond:
        text += "." + f"{moment.microsecond:06d}".rstrip("0")
    return text + "Z"


def validate_core(record):
    """Return the OpenEoX Core conformance errors of one record.

    An empty list means the record is valid. The checks are the pinned CSD01
    core.json under JSON Schema Draft 2020-12 with the format vocabulary
    asserted (which also rejects unknown properties), the date-time lexical
    rules of specification section 4.1.6 - mandatory test 7.1.2, stricter than
    the JSON Schema format assertion, which accepts lower case ``t`` and ``z`` -
    and the chronological mandatory tests 7.1.1 and 7.1.3, compared as
    timezone aware instants with ``tba`` handled as the specification requires.
    """
    if not isinstance(record, dict):
        return ["record: not a JSON object"]
    errors = [
        f"{error.json_path}: {error.message}"
        for error in sorted(_validator().iter_errors(record), key=lambda error: (error.json_path, error.message))
    ]
    for field in (*FIELDS, "last_updated"):
        value = record.get(field)
        if not isinstance(value, str) or value == "tba":
            continue
        if _instant(value) is None:
            errors.append(
                f"$.{field}: {value!r} is not a date-time as restricted by specification section 4.1.6 "
                "(upper case T and Z, no leap seconds, valid calendar date)"
            )
    errors += _chronology_errors(record)
    return errors


def _chronology_errors(record):
    """Mandatory tests 7.1.1 and 7.1.3; tba means later than any date."""
    errors = []
    end_of_life = record.get("end_of_life")
    life = _instant(end_of_life)
    if life is not None:
        for field in FIELDS:
            if field == "end_of_life":
                continue
            moment = _instant(record.get(field))
            if moment is not None and moment > life:
                errors.append(
                    f"$.end_of_life: end_of_life {end_of_life} is earlier than {field} "
                    f"{record[field]} (mandatory test 7.1.1)"
                )
    availability = _instant(record.get("general_availability"))
    if availability is not None:
        for field in FIELDS:
            if field == "general_availability":
                continue
            moment = _instant(record.get(field))
            if moment is not None and moment < availability:
                errors.append(
                    f"$.general_availability: general_availability {record['general_availability']} is later "
                    f"than {field} {record[field]} (mandatory test 7.1.3)"
                )
    return errors


def _milestones(product_id, release_id, milestones, provenance=None):
    """Map catalog milestones to catalog dates, or report why they are unusable.

    Returns ``(days, exclusion)``. ``days`` maps OpenEoX property names to
    calendar days; ``exclusion`` is the machine-readable reason the release has
    no usable milestone set at all, or None. Two kinds of milestone are not a
    stated day:

    * a *month-precision* milestone (``YYYY-MM``) states a month, so publishing
      "July 2028" as an OpenEoX date-time would mean inventing the day AGENTS.md
      rule 4 forbids; and
    * a *derived* milestone (``milestone_provenance``; see `engine/derived.py`)
      is arithmetic on a rule and a base the vendor publishes, which is a real
      published date but not a *vendor-stated day* — and the OpenEoX Core
      properties are exactly the vendor's stated lifecycle dates. Its rule and
      base live in the catalog record, not in an OpenEoX document.

    A release carrying either is excluded with its own code — never padded,
    never silently dropped, and never given the ``tba`` value.
    """
    if not isinstance(milestones, dict):
        raise ValueError(f"Release {product_id}/{release_id} has no milestones object")
    days = dict.fromkeys(FIELDS)
    for key, field in MILESTONE_KEYS.items():
        value = milestones.get(key)
        if value is None:
            continue
        if not isinstance(value, str):
            raise ValueError(f"Release {product_id}/{release_id} milestone {key} is not a date: {value!r}")
        if is_month(value):
            return None, {
                "product": product_id,
                "release": release_id,
                "code": f"{field}_month_precision",
                "reason": f"The source states {field} as the month {value}, not a day. OpenEoX Core "
                "requires a date-time of a stated day, so this release is not exported rather than "
                "having a day invented for it.",
            }
        if (provenance or {}).get(key):
            return None, {
                "product": product_id,
                "release": release_id,
                "code": f"{field}_derived",
                "reason": f"{field} is a derived date: the record's milestone_provenance states the "
                f"method {provenance[key]['method']!r} with base date {provenance[key]['base_date']} "
                f"({provenance[key]['base_label']}) and the quote it comes from. The value is derived "
                "from that explicit rule rather than stated as a day by the source. OpenEoX Core "
                "properties are the source's own lifecycle dates, so this release is not exported; "
                "the derived date stays published in the catalog record with its rule.",
            }
        if not DATE.fullmatch(value):
            raise ValueError(f"Release {product_id}/{release_id} milestone {key} is not a date: {value!r}")
        datetime.strptime(value, "%Y-%m-%d")
        days[field] = value
    return days, None


def _last_updated(product_id, provenance):
    """The catalog timestamp to report, normalized to UTC; never invented."""
    if not isinstance(provenance, dict):
        raise ValueError(f"Product {product_id} has no provenance object")
    for key in ("upstream_modified", "last_checked"):
        value = provenance.get(key)
        if value is None:
            continue
        moment = _instant(value)
        if moment is None:
            try:
                parsed = datetime.fromisoformat(value)
            except (TypeError, ValueError) as error:
                raise ValueError(f"Product {product_id} provenance.{key} is not a timestamp: {value!r}") from error
            if parsed.tzinfo is None:
                raise ValueError(f"Product {product_id} provenance.{key} has no timezone offset: {value!r}")
            moment = parsed.astimezone(timezone.utc)
        return _utc_text(moment)
    raise ValueError(f"Product {product_id} has no provenance timestamp for last_updated")


def _record(product_id, release, last_updated):
    """Return (record, None) for a publishable release or (None, exclusion)."""
    release_id = release["id"]
    days, exclusion = _milestones(product_id, release_id, release.get("milestones"),
                                  release.get(derived.DERIVED_KEY))
    if exclusion:
        # The exclusion is built before the release's name so the index entry
        # carries the same identity fields as every other exclusion row.
        return None, {"product": product_id, "release": release_id,
                      "release_name": release.get("name") or release_id, **exclusion}
    unknown = [field for field in REQUIRED if days[field] is None]
    if unknown:
        field = unknown[0]
        return None, {
            "product": product_id,
            "release": release_id,
            "release_name": release.get("name") or release_id,
            "code": f"{field}_unknown",
            "reason": f"The source catalog states no {TITLES[field]} date. OpenEoX Core requires {field}, "
            "so this export neither guesses a date nor substitutes the 'tba' value.",
        }
    # Report every violated pair exactly once. Test 7.1.3 covers general
    # availability as the later date, test 7.1.1 covers end_of_life as the
    # earlier one; the pair of the two would otherwise only repeat itself.
    violations = []
    availability = days["general_availability"]
    if availability:
        for field in ("end_of_sales", "end_of_security_support", "end_of_life"):
            if days[field] and days[field] < availability:
                violations.append((availability, "general_availability", days[field], field, "7.1.3"))
    life = days["end_of_life"]
    for field in ("end_of_sales", "end_of_security_support"):
        if days[field] and days[field] > life:
            violations.append((days[field], field, life, "end_of_life", "7.1.1"))
    if violations:
        later_field, earlier_field = violations[0][1], violations[0][3]
        failed = "; ".join(
            f"{a_field} {a} is later than {b_field} {b} (mandatory test {test_id})"
            for a, a_field, b, b_field, test_id in violations
        )
        return None, {
            "product": product_id,
            "release": release_id,
            "release_name": release.get("name") or release_id,
            "code": f"{later_field}_after_{earlier_field}",
            "reason": f"The source catalog dates fail the chronological requirements of the specification: "
            f"{failed}. This release is not exported rather than rewritten to fit.",
        }
    record = {"$schema": SCHEMA_URL}
    for field in FIELDS:
        if days[field]:
            second = FIRST_SECOND if field == MIDNIGHT_FIELD else LAST_SECOND
            record[field] = f"{days[field]}T{second}Z"
    record["last_updated"] = last_updated
    return record, None


def _export_product(product):
    """Return the (path, index row, record) entries and exclusions of a product."""
    product_id = product.get("id")
    if not isinstance(product_id, str) or not PRODUCT_ID.fullmatch(product_id):
        raise ValueError(f"Unsafe product id: {product_id!r}")
    last_updated = _last_updated(product_id, product.get("provenance"))
    releases = product.get("releases")
    if not isinstance(releases, list):
        raise ValueError(f"Product {product_id} has no releases list")
    entries, exclusions, seen = [], [], set()
    for release in releases:
        if not isinstance(release, dict):
            raise ValueError(f"Product {product_id} has a release that is not an object")
        release_id = release.get("id")
        if not isinstance(release_id, str) or not release_id:
            raise ValueError(f"Unsafe release id in product {product_id}: {release_id!r}")
        name = release_id.encode("utf-8").hex()
        # Identical release ids would silently overwrite one record with another.
        if name in seen:
            raise ValueError(f"Duplicate release id {release_id!r} in product {product_id}")
        seen.add(name)
        record, exclusion = _record(product_id, release, last_updated)
        if record is None:
            exclusions.append(exclusion)
            continue
        path = f"{SITE_PATH[0]}/{SITE_PATH[1]}/{product_id}/{name}.json"
        entries.append({
            "file": (product_id, name + ".json"),
            "record": record,
            "row": {"product": product_id, "release": release_id, "release_name": release.get("name") or release_id,
                    "id": name, "path": path, "url": f"{SITE_BASE}/{path}"},
        })
    return entries, exclusions


def _index(entries, exclusions, counts):
    return {
        "title": "OpenEoX Core records for the eoltracker software catalog",
        "source": {"catalog": SITE_BASE + "/", "upstream": UPSTREAM},
        "schema": {
            "name": "OpenEoX Core Schema Version 1.0",
            "draft_status": "OASIS Committee Specification Draft 01 (CSD01), dated 13 July 2026. A public-review "
            "draft: not a Committee Specification and not an OASIS Standard.",
            "citation": "OpenEoX Core Schema Version 1.0. Edited by Jautau White, Stefan Hagen, and Thomas Schmidt. "
            "13 July 2026. OASIS Committee Specification Draft 01.",
            "url": SCHEMA_URL,
            "snapshot_url": SCHEMA_SNAPSHOT_URL,
            "meta_schema_url": META_SCHEMA_URL,
            "vendored_core_url": f"{SITE_BASE}/{SITE_PATH[0]}/schema/openeox-core.json",
            "vendored_meta_url": f"{SITE_BASE}/{SITE_PATH[0]}/schema/openeox-meta.json",
            "license": "Copyright (c) OASIS Open 2026. All Rights Reserved. IPR mode: Non-Assertion. "
            "The specification's license and notices section is reproduced verbatim in OASIS-NOTICE.txt in this "
            "repository, alongside the vendored schema files.",
        },
        "validation": {
            "statement": "Every record below was validated against the pinned CSD01 core.json under JSON Schema "
            "Draft 2020-12 with format assertion, and against the specification's mandatory tests 7.1.1, 7.1.2 and "
            "7.1.3, before publication. This states what was checked about these files only: it is not OASIS "
            "certification, approval, or endorsement of this site or of its data.",
            "schema_url": SCHEMA_URL,
        },
        "conventions": {
            "record_id": "The file name is the lower case hex of the UTF-8 bytes of the release identifier: "
            "deterministic, collision free, and safe on case insensitive file systems.",
            "dates": "The source catalog carries calendar days only. general_availability is normalized to "
            "00:00:00Z of the stated day and end_of_sales, end_of_security_support and end_of_life to 23:59:59Z of "
            "the stated day. Those times are a rendering convention of this site, not a time of day reported by the "
            "source.",
            "unknown_values": "The value 'tba' is never emitted. A milestone the source does not state is omitted "
            "when OpenEoX makes it optional, and the release is excluded with its reason when OpenEoX requires it "
            "(end_of_security_support, end_of_life).",
            "month_precision": "OpenEoX Core properties are date-times of a stated calendar day. A release whose "
            "source states a milestone as a month (YYYY-MM) is excluded under the code "
            "'<property>_month_precision' rather than having a day invented for it, so no record here carries a "
            "day the source never published.",
            "derived": "A release whose milestone_provenance derives a milestone from a stated rule (an explicit "
            "duration, a release trigger, or a parent platform's lifecycle) is excluded under the code "
            "'<property>_derived'. The date is a published, recomputable fact — the rule, base and quote are in "
            "the catalog record — but it is not a day the source states, and OpenEoX Core properties are the "
            "source's own lifecycle dates. No derived date is exported as if the vendor had stated the day.",
            "last_updated": "Taken from the upstream revision timestamp of the source record, falling back to its "
            "last checked time; unchanged source content keeps the same value across builds.",
            "excluded": "Releases without a record are listed under 'excluded' with a machine-readable code and a "
            "reason. None of them are guessed, and none of them are silently dropped.",
            "product_identity": "OpenEoX Core has no product or version property. The product and release of a "
            "record are its path and the 'product' and 'release' fields of the entry pointing at it.",
        },
        "counts": counts,
        "records": [entry["row"] for entry in entries],
        "excluded": exclusions,
    }


def _dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build(products, site=None):
    """Write the OpenEoX Core records and index below ``_site`` and return the index.

    ``products`` are normalized software records. Every record is validated
    before anything is written, so a failure leaves the published tree as it
    was; entries whose record would not validate raise, because the export
    itself must not be the thing that makes an invalid record.
    """
    root = Path(site) if site is not None else ROOT / "_site"
    out_dir = root.joinpath(*SITE_PATH)
    entries, exclusions, releases = [], [], 0
    for product in products:
        product_entries, product_exclusions = _export_product(product)
        entries += product_entries
        exclusions += product_exclusions
        releases += len(product_entries) + len(product_exclusions)
    entries.sort(key=lambda entry: (entry["row"]["product"], entry["row"]["release"]))
    exclusions.sort(key=lambda exclusion: (exclusion["product"], exclusion["release"]))
    for entry in entries:
        errors = validate_core(entry["record"])
        if errors:
            raise RuntimeError(f"Refusing to publish invalid OpenEoX record {entry['row']['path']}: {errors}")
    counts = {"products": len(products), "releases": releases, "exported": len(entries), "excluded": len(exclusions)}
    index = _index(entries, exclusions, counts)
    out_dir.mkdir(parents=True, exist_ok=True)
    published = {}
    for entry in entries:
        path = out_dir.joinpath(*entry["file"])
        path.parent.mkdir(parents=True, exist_ok=True)
        _dump(path, entry["record"])
        published.setdefault(entry["file"][0], set()).add(entry["file"][1])
    _dump(out_dir / INDEX_NAME, index)
    # What is published has to be what the index describes: drop records of an
    # earlier build, for a release that has since been removed or is now
    # excluded, so no file outlives its entry.
    for child in sorted(out_dir.iterdir()):
        if not child.is_dir():
            continue
        keep = published.get(child.name, set())
        for stale in child.glob("*.json"):
            if stale.name not in keep:
                stale.unlink()
        if not keep:
            shutil.rmtree(child)
    return index
