"""Import the complete endoflife.date v1 software catalog, never partial snapshots."""
import json
import re
import shutil
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
API = "https://endoflife.date/api/v1/products/"
SOFTWARE_CATEGORIES = {"app", "database", "framework", "lang", "os", "server-app", "service", "standard"}


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def fetch(url):
    response = requests.get(url, timeout=(15, 90), headers={"User-Agent": "eoltracker/1.0 (+https://github.com/zarguell/eoltracker)"})
    response.raise_for_status()
    return response.json()


def date_value(value):
    # A boolean status is not a date, and must never become an invented deadline.
    if value is None or isinstance(value, bool):
        return None
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError(f"Unexpected lifecycle date: {value!r}")
    from datetime import date
    date.fromisoformat(value)
    return value


def milestones(release, labels):
    """Map only semantically explicit labels; retain all other dates upstream."""
    result = {"ga": date_value(release.get("releaseDate")), "eos": None, "eossec": None, "eol": None}
    # Labels are vendor wording, compared in normalized form (case, hyphen and
    # punctuation folded) so "End-of-life Date" and "End Of Life" match.
    mapping = {
        "security support": "eossec",
        "end of security support": "eossec",
        "end of sales": "eos",
        "end of sale": "eos",
        "end of life": "eol",
        "end of life date": "eol",
        "end of technical support": "eol",
        "end of general support": "eol",
        "end of support life": "eol",
        "security and technical support": "eol",
    }
    for field in ("eoas", "discontinued", "eol", "eoes"):
        label = re.sub(r"[^a-z0-9]+", " ", (labels.get(field) or "").strip().lower()).strip()
        target = mapping.get(label)
        if target:
            result[target] = date_value(release.get(field + "From"))
    # eoes is the upstream's explicit end of extended support. If there is no
    # extended support, security support's end is the best known support end,
    # not a claim that an undisclosed commercial contract cannot exist.
    extended = date_value(release.get("eoesFrom"))
    # Extended security updates are security support too. Generic support dates
    # remain separate from security dates; an announced extension with unknown
    # end must not be collapsed into the earlier standard support deadline.
    extended_label = (labels.get("eoes") or "").lower()
    if "security" in extended_label:
        result["eossec"] = extended
    if extended:
        result["eol"] = extended
    elif not extended_label:
        support_label = (labels.get("eol") or "").lower()
        if support_label in {"security support", "support", "support status", "supported", "end of life"}:
            result["eol"] = date_value(release.get("eolFrom"))
    return result


def normalize(payload, checked):
    product = payload["result"]
    slug = product["name"]
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug):
        raise ValueError(f"Unsafe product slug: {slug!r}")
    if product["category"] not in SOFTWARE_CATEGORIES:
        raise ValueError(f"Unknown software category: {product['category']!r}")
    labels = product.get("labels", {})
    releases = []
    for release in product["releases"]:
        releases.append({"id": release["name"], "name": release.get("label") or release["name"],
                         "milestones": milestones(release, labels), "upstream": release})
    return {
        "$schema": "https://zarguell.github.io/eoltracker/v1/schema/product.json",
        "id": slug, "name": product["label"], "category": "software",
        "upstream_category": product["category"], "identifiers": product.get("identifiers", []),
        "labels": labels, "links": product.get("links", {}), "releases": releases,
        "provenance": {"source_url": API + slug + "/", "verifier": "deterministic-endoflife-date-v1",
                       "last_checked": checked, "upstream_modified": payload.get("last_modified")},
    }


def import_data():
    from .validation import validate_data
    listing = fetch(API)
    entries = listing["result"]
    if not entries or len(entries) != listing["total"]:
        raise ValueError("Incomplete upstream product listing")
    if len({p["name"] for p in entries}) != len(entries):
        raise ValueError("Duplicate upstream product IDs")
    unknown = {p["category"] for p in entries} - SOFTWARE_CATEGORIES - {"device"}
    if unknown:
        raise ValueError(f"Review new upstream categories before publishing: {unknown}")
    selected = sorted((p for p in entries if p["category"] != "device"), key=lambda p: p["name"])
    checked = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    # Fetch and normalize everything before touching the committed data directory.
    with ThreadPoolExecutor(max_workers=8) as pool:
        payloads = list(pool.map(lambda p: fetch(API + p["name"] + "/"), selected))
    records = [normalize(p, checked) for p in payloads]
    if [r["id"] for r in records] != [p["name"] for p in selected]:
        raise ValueError("Upstream listing/detail identities disagree")
    destination = ROOT / "data"
    with tempfile.TemporaryDirectory(prefix="eoltracker-") as temp:
        staged = Path(temp)
        for record in records:
            previous = destination / "products" / (record["id"] + ".json")
            if previous.exists():
                old = json.loads(previous.read_text())
                # Preserve per-record revision time if all content is unchanged;
                # manifest.generated_at records every successful complete refresh.
                record["provenance"]["last_checked"] = old["provenance"]["last_checked"]
                if old != record:
                    record["provenance"]["last_checked"] = checked
            dump(staged / "products" / (record["id"] + ".json"), record)
        dump(staged / "manifest.json", {
            "generated_at": checked, "source_url": API, "product_count": len(records),
            "release_count": sum(len(r["releases"]) for r in records),
            "excluded_hardware": sorted(p["name"] for p in entries if p["category"] == "device"),
        })
        validate_data(staged)
        destination.mkdir(exist_ok=True)
        products = destination / "products"
        products.mkdir(exist_ok=True)
        for file in (staged / "products").glob("*.json"):
            shutil.copyfile(file, products / file.name)
        for file in products.glob("*.json"):
            if not (staged / "products" / file.name).exists():
                file.unlink()
        shutil.copyfile(staged / "manifest.json", destination / "manifest.json")
    print(f"Imported {len(records)} software products; excluded {len(entries) - len(records)} hardware products")
