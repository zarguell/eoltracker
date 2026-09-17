"""Offline schema and provenance consistency validation."""
import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from .importer import API, ROOT, milestones


def validate_data(directory=None):
    directory = Path(directory) if directory is not None else ROOT / "data"
    schema = json.loads((ROOT / "schema/product.json").read_text())
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    records = []
    for file in sorted((directory / "products").glob("*.json")):
        record = json.loads(file.read_text())
        validator.validate(record)
        if record["id"] != file.stem or record["provenance"]["source_url"] != API + record["id"] + "/":
            raise ValueError(f"Record identity/provenance mismatch: {file}")
        release_ids = set()
        for release in record["releases"]:
            if release["id"] in release_ids or release["id"] != release["upstream"]["name"]:
                raise ValueError(f"Duplicate/mismatched release: {file}: {release['id']}")
            release_ids.add(release["id"])
            if release["milestones"] != milestones(release["upstream"], record["labels"]):
                raise ValueError(f"Milestones contradict source: {file}: {release['id']}")
        records.append(record)
    manifest = json.loads((directory / "manifest.json").read_text())
    Draft202012Validator({
        "type": "object", "additionalProperties": False,
        "required": ["generated_at", "source_url", "product_count", "release_count", "excluded_hardware"],
        "properties": {
            "generated_at": {"type": "string", "format": "date-time"},
            "source_url": {"const": API}, "product_count": {"type": "integer", "minimum": 1},
            "release_count": {"type": "integer", "minimum": 1},
            "excluded_hardware": {"type": "array", "uniqueItems": True, "items": {"type": "string"}},
        },
    }, format_checker=FormatChecker()).validate(manifest)
    if len(records) != manifest["product_count"] or sum(len(r["releases"]) for r in records) != manifest["release_count"]:
        raise ValueError("Manifest counts do not match complete catalog")
    if {r["id"] for r in records} & set(manifest["excluded_hardware"]):
        raise ValueError("Hardware included in software catalog")
    return records
