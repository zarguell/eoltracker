"""Shared publication for software collectors that own one or more records.

Stage the record beside the committed catalog and validate before writing.
Parse and validation failures leave committed files untouched. The two final
writes are not an atomic filesystem transaction by themselves, so every entry
point wraps this module in `engine.refresh`'s snapshot rollback: the registered
`refresh` command and each direct `python -m engine import-<source>` command
both run through `refresh.refresh_source`, which restores the data directory
byte-for-byte if any write fails (AGENTS.md; issue #94).
Call committed_product_record before fetching to enforce source ownership.
Quiet product and report content independently preserve revision timestamps.
"""
import json
import shutil
import tempfile
from pathlib import Path

from .importer import dump
from . import sources


def committed_product_record(root, product_id, verifier, validate_record, name):
    """The committed record for ``product_id``, refusing one this source cannot own.

    A file under this product's name carrying another source's verifier is an
    ownership collision: republishing it would overwrite a record this pipeline
    did not produce. A committed record that no longer re-derives from its own
    stored cells is equally unpublishable — merging it would carry a claim the
    vendor's page does not state. Both abort before anything is written.
    """
    path = root / "products" / (product_id + ".json")
    if not path.exists():
        return None
    record = json.loads(path.read_text(encoding="utf-8"))
    if record["provenance"]["verifier"] != verifier:
        raise ValueError(f"{name} source ownership collision: {product_id} carries "
                         f"{record['provenance']['verifier']}, not {verifier}")
    validate_record(record)
    return record


def committed_product_records(root, verifier, validate_record, name):
    """Every committed record this source owns, keyed by product id.

    A source whose records are discovered rather than declared cannot name the
    products it owns in advance, so it needs the other direction of the same
    check: which committed files already carry its verifier, each one
    re-derived from its own cells before the run is allowed to fetch anything.
    A record this verifier owns that no longer follows its own cells aborts the
    refresh rather than being merged or silently rewritten.
    """
    products = root / "products"
    if not products.is_dir():
        raise ValueError(f"Not a catalog directory: {root}")
    owned = {}
    for path in sorted(products.glob("*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        if record.get("provenance", {}).get("verifier") != verifier:
            continue
        if path.stem != record.get("id"):
            raise ValueError(f"{name} record {path.name} does not name its own product")
        validate_record(record)
        owned[record["id"]] = record
    return owned


def publish_product_record(record, report, root, report_name):
    """Stage the record beside the committed catalog, validate, then replace it.

    Only this source's own file is written. Every committed record is copied
    into the staged catalog and validated there, so a run that would publish an
    inconsistent catalog writes nothing at all — while a record this source
    does not own is left byte-for-byte as it was found. A record whose content
    is unchanged keeps its previous revision time, and a report whose content
    is unchanged keeps its previous ``checked_at``, so a quiet source
    republishes byte-identical files.
    """
    from .validation import validate_data

    products = root / "products"
    if not (root / "manifest.json").exists() or not products.is_dir():
        raise ValueError(f"Not a catalog directory: {root}")
    manifest = (root / "manifest.json").read_text(encoding="utf-8")
    target = products / (record["id"] + ".json")
    if target.exists():
        old = json.loads(target.read_text(encoding="utf-8"))
        unchanged = {**record, "provenance": {**record["provenance"],
                                              "last_checked": old["provenance"]["last_checked"]}}
        if old == unchanged:
            record = unchanged
    report_target = root / report_name
    if report_target.exists():
        old_report = json.loads(report_target.read_text(encoding="utf-8"))
        unchanged_report = {**report, "checked_at": old_report.get("checked_at")}
        if old_report == unchanged_report:
            report = unchanged_report
    with tempfile.TemporaryDirectory(prefix="eoltracker-publish-") as temp:
        staged = Path(temp)
        shutil.copytree(products, staged / "products")
        dump(staged / "products" / (record["id"] + ".json"), record)
        (staged / "manifest.json").write_text(manifest, encoding="utf-8")
        if "hardware_count" in json.loads(manifest):
            # The manifest counts the hardware catalog too, so the staged
            # catalog carries it rather than claiming an empty one validates.
            shutil.copytree(root / "hardware", staged / "hardware")
        for source in sources.all_sources():
            if source.report and (root / source.report).is_file():
                shutil.copy2(root / source.report, staged / source.report)
        dump(staged / report_name, report)
        validate_data(staged)
        dump(target, record)
        dump(report_target, report)
    return record


def publish_product_records(records, report, root, report_name):
    """Stage every record this source owns, validate, then replace them together.

    A vendor whose pages carry several products — SolarWinds publishes one
    record per product family, OpenEdge one per product line — owns them with
    one source, one report and one ``total_records`` count, so they are
    published as a set: the staged catalog holds the whole snapshot and
    validation sees it complete, which a per-record call could never assert
    once the report claims more than one record.

    The guarantees of :func:`publish_product_record` are unchanged, only
    widened: unchanged records keep their own revision time, an unchanged
    report keeps its ``checked_at``, and a parse or validation failure leaves
    every committed file — published or not — byte-for-byte as it was found.
    """
    from .validation import validate_data

    if not records:
        raise ValueError("A source that owns no record has nothing to publish")
    products = root / "products"
    if not (root / "manifest.json").exists() or not products.is_dir():
        raise ValueError(f"Not a catalog directory: {root}")
    ids = [record["id"] for record in records]
    if len(set(ids)) != len(ids):
        raise ValueError(f"A source cannot publish one product twice: {ids}")
    manifest = (root / "manifest.json").read_text(encoding="utf-8")
    settled = []
    for record in records:
        target = products / (record["id"] + ".json")
        if target.exists():
            old = json.loads(target.read_text(encoding="utf-8"))
            unchanged = {**record, "provenance": {**record["provenance"],
                                                  "last_checked": old["provenance"]["last_checked"]}}
            if old == unchanged:
                record = unchanged
        settled.append((target, record))
    report_target = root / report_name
    if report_target.exists():
        old_report = json.loads(report_target.read_text(encoding="utf-8"))
        unchanged_report = {**report, "checked_at": old_report.get("checked_at")}
        if old_report == unchanged_report:
            report = unchanged_report
    with tempfile.TemporaryDirectory(prefix="eoltracker-publish-") as temp:
        staged = Path(temp)
        shutil.copytree(products, staged / "products")
        for target, record in settled:
            dump(staged / "products" / (record["id"] + ".json"), record)
        (staged / "manifest.json").write_text(manifest, encoding="utf-8")
        if "hardware_count" in json.loads(manifest):
            # The manifest counts the hardware catalog too, so the staged
            # catalog carries it rather than claiming an empty one validates.
            shutil.copytree(root / "hardware", staged / "hardware")
        for source in sources.all_sources():
            if source.report and (root / source.report).is_file():
                shutil.copy2(root / source.report, staged / source.report)
        dump(staged / report_name, report)
        validate_data(staged)
        for target, record in settled:
            dump(target, record)
        dump(report_target, report)
    return [record for _, record in settled]
