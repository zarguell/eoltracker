"""Shared publication for single-product software collectors.

Stage the record beside the committed catalog and validate before writing.
Parse and validation failures leave committed files untouched. The two final
writes are not an atomic filesystem transaction; refresh_source supplies
snapshot rollback for write failures during orchestrated refreshes.
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
