"""Offline schema and provenance consistency validation.

The JSON Schemas prove shape; the checks here prove coherence — a record's
milestones still follow the pipeline that owns it, its researched quotes still
back its dates, a derived milestone still recomputes from its own stored rule
(``engine.derived``), a release's stated end does not precede its own general
availability, and every registered source that owns committed records has
published its accounting sidecar. Every check re-derives from the record itself,
so a hand-edited catalog fails the gate instead of being published.
"""
import json
import re
from datetime import date
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from . import sources
from .importer import API, ROOT, milestones


class CatalogError(ValueError):
    """A committed catalog violates a coherence rule the JSON Schema cannot state.

    The schemas prove a record's shape; this is the failure for what they cannot
    express — a date that no longer follows its own evidence, a snapshot whose
    counts or sidecars disagree with the records beside them, a milestone that
    cannot be true of its own release. It stays a ``ValueError`` so every caller
    that already treats a broken catalog as a value error is unaffected, and it
    gives a regression test a precise failure to assert instead of the wording
    of a Python message.
    """


class ReportError(CatalogError):
    """A registered source's accounting sidecar is missing or disagrees with its records."""


class ChronologyError(CatalogError):
    """A record states an end milestone provably earlier than its own general availability."""


class MilestoneError(CatalogError):
    """A release's stated milestones do not re-derive from the source they cite."""


class ManifestError(CatalogError):
    """The manifest's counts or named source do not describe the committed catalog."""


HARDWARE_DIR = "hardware"
MANIFEST_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["generated_at", "source_url", "product_count", "release_count", "excluded_hardware"],
    "properties": {
        "generated_at": {"type": "string", "format": "date-time"},
        "source_url": {"const": API}, "product_count": {"type": "integer", "minimum": 1},
        "release_count": {"type": "integer", "minimum": 1},
        "excluded_hardware": {"type": "array", "uniqueItems": True, "items": {"type": "string"}},
        "hardware_count": {"type": "integer", "minimum": 0},
        # Added by the refresh so the snapshot names the registered source that
        # produced it. Optional here so a manifest committed before the registry
        # still validates; checked against the registry whenever it is present.
        "source": {"type": "string"},
    },
}


def check_source(record, category):
    """The registered source owning a deterministic record's verifier.

    Delegates to the registry so the "which verifiers are real, and which
    catalog does each own" rule lives in exactly one place; this only supplies
    the record-shaped error message a catalog failure should carry.
    """
    verifier = (record.get("provenance") or {}).get("verifier")
    try:
        return sources.validate_verifier(verifier, category)
    except sources.RegistryError as error:
        raise type(error)(f"{record.get('id')}: {error}") from None


# A month-precision value is ``YYYY-MM`` and nothing else; the width is a
# published shape of its own and is never padded into a day (AGENTS.md rule 4).
MONTH_PRECISION = re.compile(r"\d{4}-\d{2}\Z")
# The milestones that end a release's support. ``ga`` is ordered against each of
# them; no ordering between two end milestones is asserted, because a real vendor
# exception exists in the committed catalog (see :func:`check_chronology`).
END_MILESTONES = ("eos", "eossec", "eol")


def covered_start(value):
    """The earliest calendar day a stated milestone can cover.

    A milestone is a day or a month, and the comparison has to respect the width
    the source published without inventing the other: a ``YYYY-MM`` value covers
    its whole month, so the earliest day it can cover is the first of that month.
    Comparing the first day each value covers is how a month-precision date is
    ordered without being padded into a day. This is the same conservative
    direction ``engine.derived`` documents for its base dates: a month that
    *could* begin before the value it is compared against is refused rather than
    assumed to fall later.
    """
    if MONTH_PRECISION.fullmatch(value):
        return date.fromisoformat(value + "-01")
    return date.fromisoformat(value)


def check_chronology(record):
    """A release's stated end cannot precede its own general availability.

    The schema proves each milestone is a day or a month; this proves the window
    they describe can exist at all. A record whose ``ga`` is absent, or whose end
    milestone is absent, states no interval to contradict, so it is left alone —
    an absent date stays absent. Only ``ga`` is ordered against: the milestones
    are compared by the earliest day each covers, so a month is never padded into
    a day, and equal boundaries (the same date, or the same month) pass.

    No ordering is asserted *between* end milestones. A vendor can state them out
    of order for reasons of its own — the committed XenServer record publishes
    ``eos 2013-09-23`` after ``eol 2013-09-15`` from Citrix's own tables — so a
    rule there would refuse a real vendor statement, which is exactly the kind of
    invented rule AGENTS.md forbids.
    """
    for release in record["releases"]:
        milestones = release["milestones"]
        ga = milestones.get("ga")
        if not ga:
            continue
        for key in END_MILESTONES:
            end = milestones.get(key)
            if end and covered_start(end) < covered_start(ga):
                raise ChronologyError(f"{record['id']}/{release['id']}: {key} {end} precedes "
                                      f"the release's own ga {ga}")


def check_derived(record):
    """Re-derive every `milestone_provenance` entry of one software record.

    The schema proves the entry's shape; this proves its arithmetic. A derived
    milestone is a published date, so it is held to the same bar as a stated one
    — the record's own rule has to produce the value beside it — and it runs the
    shared module's check, so the catalog gate and a collector cannot drift apart.
    """
    from . import derived

    release_ids = {release["id"] for release in record["releases"]}
    for release in record["releases"]:
        derived.validate_milestone_provenance(
            release["milestones"], release.get(derived.DERIVED_KEY),
            f"{record['id']}/{release['id']}", release_ids)


def validate_hardware(directory=None):
    """Validate committed hardware records; returns records in slug order."""
    from .contribute import is_researched, validate_research
    directory = Path(directory) if directory is not None else ROOT / "data"
    schema = json.loads((ROOT / "schema/hardware.json").read_text())
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    records = []
    seen = set()
    owned = {}
    for file in sorted((directory / HARDWARE_DIR).glob("*.json")):
        record = json.loads(file.read_text())
        validator.validate(record)
        if record["id"] != file.stem:
            raise CatalogError(f"Hardware record identity mismatch: {file}")
        if is_researched(record):
            # A researched record states no upstream row and re-derives nothing
            # from a collector's published cells; its evidence is checked instead.
            validate_research(record, "hardware")
        else:
            # The source that owns this verifier decides how the record is
            # re-checked, so a new collector adds its own validator to the
            # registry instead of a branch here.
            found = check_source(record, "hardware")
            check = sources.record_validator(found)
            if check is not None:
                check(record)
        if record["id"] in seen:
            raise CatalogError(f"Duplicate hardware record: {file}")
        seen.add(record["id"])
        owned.setdefault(record["provenance"]["verifier"], set()).add(record["id"])
        # Only the terminal support end is ordered against ga. eos is not: the
        # committed eosl.date record dell-emc-isilon-iq-6000i states an end of
        # sale of 2008-05-30 beside a release date of 2010-03-15, the vendor's
        # own cells, so ordering eos here would refuse a real source row.
        ga, eol = record["milestones"]["ga"], record["milestones"]["eol"]
        if ga and eol and covered_start(eol) < covered_start(ga):
            raise ChronologyError(f"Hardware chronology violation: {file}: eol {eol} < ga {ga}")
        records.append(record)
    check_source_reports(directory, owned, "hardware")
    return records


def check_source_reports(directory, owned, category):
    """Every source's sidecar must exist and account for the records it owns.

    A source that publishes a per-row accounting sidecar states how many
    records its refresh wrote (``total_records``); that number is the one thing
    a reader of the report can check against the catalog it describes. AGENTS.md
    rule 6 treats an exclusion as published data, so the sidecar is not optional:
    a source that owns committed records with no sidecar has silently dropped the
    accounting for them, and a documented report URL would 404. The sidecar is
    therefore required whenever its source owns records, must be the JSON object
    the format promises, and must name its own source and count. Only the sources
    of ``category`` are checked: each catalog directory holds both catalogs'
    records at once, and neither validation pass owns the other's sidecars.
    """
    for source in sources.all_sources():
        if source.category != category or not source.report:
            continue
        report_path = directory / source.report
        if source.verifier not in owned:
            # A sidecar with no committed record behind it claims coverage the
            # catalog cannot show, which is the same lie in the other direction.
            if report_path.exists():
                raise ReportError(f"{source.report} exists but no committed record carries "
                                  f"{source.verifier}")
            # A source owning nothing in this directory has nothing to account
            # for, so a catalog that never held its records is not a failure.
            continue
        count = len(owned[source.verifier])
        if not report_path.exists():
            raise ReportError(f"{source.report} is missing although {count} committed records carry "
                              f"{source.verifier}")
        try:
            report = json.loads(report_path.read_text())
        except json.JSONDecodeError as error:
            raise ReportError(f"{source.report} is not valid JSON: {error}") from error
        if not isinstance(report, dict):
            raise ReportError(f"{source.report} is not a JSON object")
        if report.get("verifier") != source.verifier:
            raise ReportError(f"{source.report} does not name the source that published it")
        if report.get("total_records") != count:
            raise ReportError(f"{source.report} reports {report.get('total_records')} records but "
                              f"{count} carry {source.verifier}")


def validate_data(directory=None):
    from .contribute import is_researched, validate_research
    directory = Path(directory) if directory is not None else ROOT / "data"
    schema = json.loads((ROOT / "schema/product.json").read_text())
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    records = []
    owned = {}
    for file in sorted((directory / "products").glob("*.json")):
        record = json.loads(file.read_text())
        validator.validate(record)
        if record["id"] != file.stem:
            raise CatalogError(f"Record identity mismatch: {file}")
        check_derived(record)
        # A release whose stated end precedes its own general availability is an
        # impossible window whatever produced it, so both deterministic and
        # researched records are ordered here — the researched admission rules
        # check a quoted date against the evidence, never against a sibling.
        check_chronology(record)
        if is_researched(record):
            # Researched records have no upstream release object to contradict;
            # their stored quotes are the evidence and are checked against them.
            validate_research(record, "software")
            records.append(record)
            continue
        # A software record must name the registered software source: a
        # hardware collector's verifier here would publish an unbuildable claim.
        found = check_source(record, "software")
        owned.setdefault(record["provenance"]["verifier"], set()).add(record["id"])
        if found.id != "import-data":
            # The source that owns this verifier decides how its records are
            # re-checked, so a new collector adds its own validator to the
            # registry instead of a branch here. A software source that
            # re-derives nothing offline cannot be published: no installed
            # pipeline could reproduce what it wrote.
            check = sources.record_validator(found)
            if check is None:
                raise CatalogError(f"{file}: source {found.id!r} re-derives no record offline")
            check(record)
        else:
            if record["provenance"]["source_url"] != API + record["id"] + "/":
                raise CatalogError(f"Record identity/provenance mismatch: {file}")
            release_ids = set()
            for release in record["releases"]:
                if release["id"] in release_ids or release["id"] != release["upstream"]["name"]:
                    raise CatalogError(f"Duplicate/mismatched release: {file}: {release['id']}")
                release_ids.add(release["id"])
                if release["milestones"] != milestones(release["upstream"], record["labels"]):
                    raise MilestoneError(f"Milestones contradict source: {file}: {release['id']}")
        records.append(record)
    # The manifest describes the endoflife.date snapshot the importer maintains:
    # a software record another registered source owns is a separate shard of
    # the catalog, carried additively, so its records and releases are reported
    # on their own sidecar and are never counted into this source's totals.
    deterministic = [record for record in records if not is_researched(record)]
    manifest = json.loads((directory / "manifest.json").read_text())
    Draft202012Validator(MANIFEST_SCHEMA, format_checker=FormatChecker()).validate(manifest)
    counted = [record for record in deterministic
               if record["provenance"]["verifier"] == sources.source("import-data").verifier]
    if (len(counted) != manifest["product_count"]
            or sum(len(r["releases"]) for r in counted) != manifest["release_count"]):
        raise ManifestError("Manifest counts do not match complete catalog")
    if {r["id"] for r in records} & set(manifest["excluded_hardware"]):
        raise ManifestError("Hardware included in software catalog")
    check_source_reports(directory, owned, "software")
    check_manifest_source(manifest, counted)
    if "hardware_count" in manifest and len(validate_hardware(directory)) != manifest["hardware_count"]:
        raise ManifestError("Manifest hardware_count does not match committed hardware records")
    return records


def check_manifest_source(manifest, records):
    """The manifest's named source must be the pipeline that owns its records.

    A manifest states which registered source produced the software snapshot it
    describes; naming a source whose verifier no committed record carries (or a
    different source's verifier) means the counts describe a snapshot no
    installed pipeline can reproduce.
    """
    verifiers = {record["provenance"]["verifier"] for record in records}
    named = manifest.get("source")
    if named is None:
        # Older snapshots predate the field; the records' own verifiers are
        # still required to name a registered software source above.
        return
    found = sources.source(named)
    if found.category != "software":
        raise ManifestError(f"Manifest source {named!r} does not own the software catalog")
    if verifiers and verifiers != {found.verifier}:
        raise ManifestError(f"Manifest source {named!r} does not match record verifiers "
                            f"{sorted(verifiers)}")
    if API not in found.urls:
        raise ManifestError(f"Manifest source_url is not a page read by {named!r}")
