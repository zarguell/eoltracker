"""Offline schema and provenance consistency validation.

The JSON Schemas prove shape; the checks here prove coherence — a record's
milestones still follow the pipeline that owns it, its researched quotes still
back its dates, and a derived milestone still recomputes from its own stored
rule (``engine.derived``). Every check re-derives from the record itself, so a
hand-edited catalog fails the gate instead of being published.
"""
import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from . import sources
from .importer import API, ROOT, milestones

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
            raise ValueError(f"Hardware record identity mismatch: {file}")
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
            raise ValueError(f"Duplicate hardware record: {file}")
        seen.add(record["id"])
        owned.setdefault(record["provenance"]["verifier"], set()).add(record["id"])
        ga, eol = record["milestones"]["ga"], record["milestones"]["eol"]
        if ga and eol and eol < ga:
            raise ValueError(f"Hardware chronology violation: {file}: eol {eol} < ga {ga}")
        records.append(record)
    check_source_reports(directory, owned, "hardware")
    return records


def check_source_reports(directory, owned, category):
    """Every source's sidecar must account for the records it owns.

    A source that publishes a per-row accounting sidecar states how many
    records its refresh wrote (``total_records``); that number is the one thing
    a reader of the report can check against the catalog it describes, so a
    sidecar that disagrees with the committed records fails validation instead
    of claiming coverage the catalog does not show. Only the sources of
    ``category`` are checked: each catalog directory holds both catalogs'
    records at once, and neither validation pass owns the other's sidecars.
    """
    for source in sources.all_sources():
        if source.category != category:
            continue
        if not source.report or not (directory / source.report).exists():
            continue
        if source.verifier not in owned:
            raise ValueError(f"{source.report} exists but no committed record carries "
                             f"{source.verifier}")
        report = json.loads((directory / source.report).read_text())
        if report.get("verifier") != source.verifier:
            raise ValueError(f"{source.report} does not name the source that published it")
        if report.get("total_records") != len(owned[source.verifier]):
            raise ValueError(f"{source.report} reports {report.get('total_records')} records but "
                             f"{len(owned[source.verifier])} carry {source.verifier}")


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
            raise ValueError(f"Record identity mismatch: {file}")
        check_derived(record)
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
                raise ValueError(f"{file}: source {found.id!r} re-derives no record offline")
            check(record)
        else:
            if record["provenance"]["source_url"] != API + record["id"] + "/":
                raise ValueError(f"Record identity/provenance mismatch: {file}")
            release_ids = set()
            for release in record["releases"]:
                if release["id"] in release_ids or release["id"] != release["upstream"]["name"]:
                    raise ValueError(f"Duplicate/mismatched release: {file}: {release['id']}")
                release_ids.add(release["id"])
                if release["milestones"] != milestones(release["upstream"], record["labels"]):
                    raise ValueError(f"Milestones contradict source: {file}: {release['id']}")
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
        raise ValueError("Manifest counts do not match complete catalog")
    if {r["id"] for r in records} & set(manifest["excluded_hardware"]):
        raise ValueError("Hardware included in software catalog")
    check_source_reports(directory, owned, "software")
    check_manifest_source(manifest, counted)
    if "hardware_count" in manifest and len(validate_hardware(directory)) != manifest["hardware_count"]:
        raise ValueError("Manifest hardware_count does not match committed hardware records")
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
        raise ValueError(f"Manifest source {named!r} does not own the software catalog")
    if verifiers and verifiers != {found.verifier}:
        raise ValueError(f"Manifest source {named!r} does not match record verifiers {sorted(verifiers)}")
    if API not in found.urls:
        raise ValueError(f"Manifest source_url is not a page read by {named!r}")
