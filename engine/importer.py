"""Import the complete endoflife.date v1 software catalog, never partial snapshots."""
import json
import re
import shutil
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from . import net, sources
from .sources import ENDOFLIFE_DATE_API

ROOT = Path(__file__).resolve().parents[1]
API = ENDOFLIFE_DATE_API
# Declared once, in the registry: a published record's provenance must name a
# source the registry knows, so the collector reads its own id from there.
VERIFIER = sources.source("import-data").verifier
SOFTWARE_CATEGORIES = {"app", "database", "framework", "lang", "os", "server-app", "service", "standard"}
# Cardinality caps for the upstream listing and one product's releases, set
# comfortably above the real catalog (455 upstream products; the largest of the
# committed records carries 150 releases) so a corrupted or adversarial listing
# fails closed before it spends the request budget or the disk.
MAX_PRODUCTS = 5000
MAX_RELEASES = 2000


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def fetch(url):
    """Fetch one upstream JSON document under the shared network policy."""
    return net.get_json(url)


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
    # eoes is the upstream's explicit end of extended support. Absent one, the
    # best known *full* support end falls back to the primary column below; a
    # security-only label is not a full support end and never becomes one.
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
        # Only wording that states full/terminal support — or "end of life",
        # which the mapping above already handles — fills eol from the primary
        # column. "Security support" is deliberately absent: it is security-only,
        # so it stops at eossec instead of republishing fixes-stop as the
        # terminal support end (adonisjs publishes one date under that wording).
        support_label = (labels.get("eol") or "").lower()
        if support_label in {"support", "support status", "supported", "end of life"}:
            result["eol"] = date_value(release.get("eolFrom"))
    return result


def _refuse_foreign_slugs(destination, slugs):
    """Refuse an upstream slug a committed record this source does not own already uses.

    A committed record whose verifier is not this source's belongs to another
    registered pipeline (a vendor collector's shard of the software catalog) or
    to a researched contribution. Re-deriving it from the endoflife.date listing
    would delete that source's history, provenance and report-backed rows, and
    the later collector would then abort on the ownership collision this refresh
    created. The collision is detected before any file is staged, so the
    committed record and every sidecar stay byte-for-byte as they were found.
    """
    products = Path(destination) / "products"
    for slug in slugs:
        path = products / (slug + ".json")
        if not path.exists():
            continue
        verifier = json.loads(path.read_text(encoding="utf-8"))["provenance"]["verifier"]
        if verifier != VERIFIER:
            raise ValueError(f"endoflife.date source ownership collision: {slug} carries "
                             f"{verifier}, not {VERIFIER}")


def normalize(payload, checked):
    product = payload["result"]
    slug = product["name"]
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug):
        raise ValueError(f"Unsafe product slug: {slug!r}")
    if product["category"] not in SOFTWARE_CATEGORIES:
        raise ValueError(f"Unknown software category: {product['category']!r}")
    if len(product["releases"]) > MAX_RELEASES:
        raise ValueError(f"{slug}: upstream product exceeds {MAX_RELEASES} releases")
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
        "provenance": {"source_url": API + slug + "/", "verifier": VERIFIER,
                       "last_checked": checked, "upstream_modified": payload.get("last_modified")},
    }


def import_data(directory=None):
    """Refresh every software product from endoflife.date into ``directory``.

    Complete-or-nothing: the whole upstream catalog is fetched and normalized
    into a staging directory and validated there before any committed file is
    replaced. Returns a one-line summary of what was published.
    """
    from .validation import validate_data
    listing = fetch(API)
    entries = listing["result"]
    if not entries or len(entries) != listing["total"]:
        raise ValueError("Incomplete upstream product listing")
    # Fail before the detail fan-out: a listing that is larger than a real
    # catalog (a hostile or corrupted upstream) must not spend the request
    # budget on one detail fetch per advertised entry.
    if len(entries) > MAX_PRODUCTS:
        raise ValueError(f"Upstream listing exceeds {MAX_PRODUCTS} products: {len(entries)}")
    if len({p["name"] for p in entries}) != len(entries):
        raise ValueError("Duplicate upstream product IDs")
    unknown = {p["category"] for p in entries} - SOFTWARE_CATEGORIES - {"device"}
    if unknown:
        raise ValueError(f"Review new upstream categories before publishing: {unknown}")
    selected = sorted((p for p in entries if p["category"] != "device"), key=lambda p: p["name"])
    destination = Path(directory) if directory is not None else ROOT / "data"
    # The committed ownership check runs before the fan-out: a slug another
    # registered source already owns aborts the refresh without fetching a
    # single detail document, and without staging anything.
    _refuse_foreign_slugs(destination, [p["name"] for p in selected])
    checked = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    # Fetch and normalize everything before touching the committed data directory.
    with ThreadPoolExecutor(max_workers=net.workers(API)) as pool:
        payloads = list(pool.map(lambda p: fetch(API + p["name"] + "/"), selected))
    records = [normalize(p, checked) for p in payloads]
    if [r["id"] for r in records] != [p["name"] for p in selected]:
        raise ValueError("Upstream listing/detail identities disagree")
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
            # The registered source that produced this snapshot, so validation
            # can check the manifest describes a pipeline this checkout installs.
            "source": "import-data",
        })
        # Records this refresh does not own — another registered source's own
        # shard of the software catalog (a vendor collector's branches) and
        # researched contributions (AGENTS.md rule 8 tier b) — are not in the
        # upstream listing, so this refresh cannot re-derive them. Every
        # committed record whose verifier is not this source's is carried into
        # the staged snapshot verbatim: validate_data then checks what is about
        # to be published, keeping the refresh complete-or-nothing, while the
        # bytes and revision time of a record this source does not own survive
        # untouched instead of being dropped or rewritten. A staged record can
        # no longer shadow one of these: `_refuse_foreign_slugs` already
        # aborted if the upstream listing used such a slug, so this loop only
        # ever adds records nothing else would write.
        committed = destination / "products"
        for file in sorted(committed.glob("*.json")) if committed.exists() else ():
            if (staged / "products" / file.name).exists():
                continue
            if json.loads(file.read_text())["provenance"]["verifier"] != VERIFIER:
                shutil.copyfile(file, staged / "products" / file.name)
        # Every registered source's sidecar is staged beside those records. A
        # carried record's own report (AGENTS.md rule 6 accounting) must be
        # present, or validate_data refuses the staged snapshot for a missing
        # sidecar; staging the committed report keeps the internal validation
        # from failing on a sibling source's records this refresh only carries.
        for source in sources.all_sources():
            if source.report and (destination / source.report).is_file():
                shutil.copyfile(destination / source.report, staged / source.report)
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
    return (f"imported {len(records)} software products; excluded {len(entries) - len(records)} "
            f"hardware products")
