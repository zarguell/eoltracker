# EOL Tracker

Static, machine-readable lifecycle catalog for hardware and software: general availability, end-of-sale, end-of-security-support and end-of-life dates, normalized into one schema and published as flat JSON, Atom/RSS/iCalendar feeds and OpenEoX records — entirely from GitHub Pages, with no backend and zero hosting cost.

Live site and API: **https://zarguell.github.io/eoltracker/**

## What it is

EOL Tracker ingests community lifecycle catalogs, normalizes their vendor-specific wording into a single conservative schema, and republishes everything as stable static endpoints:

| What | Where |
|---|---|
| Software catalog (455 products, 7,479 releases) | `/v1/products.json`, `/v1/products/{id}.json`, human pages `/products/{id}/` |
| Hardware catalog (6,910 models, 9 vendors) | `/v1/hardware.json`, `/v1/hardware/{id}.json`, human pages `/hardware/{id}/` |
| Upcoming lifecycle milestones (one event per release × milestone) | `/v1/feed.atom` (RFC 4287), `/v1/feed.rss` (RSS 2.0), `/v1/calendar.ics` (RFC 5545) |
| OpenEoX Core v1.0 CSD01 export | `/v1/openeox/index.json`, `/v1/openeox/{product}/{release}.json` |
| JSON Schemas for every published record | `/v1/schema/product.json`, `/v1/schema/hardware.json` |

Everything is rebuilt and published by a scheduled GitHub Actions workflow; there is no server, no database, no cost. Git history is the audit trail: every milestone revision of every record is attributable and revertible.

PowerDNS Authoritative lifecycle is refreshed with
`python -m engine import-powerdns-authoritative`. Its 11 source scopes include
the grouped “4.1 and older” row. Approximate dates remain raw evidence, definite
months retain month precision, and critical-only updates are not support-end
milestones. This community lifecycle does not describe commercial agreements.

## What differentiates it

- **Hardware and software in one normalized schema.** Community sources are software-shaped or hardware-shaped; this catalog merges both under one milestone model (`ga` / `eos` / `eossec` / `eol`) with provenance on every record (`source_url`, `verifier`, `last_checked`, `upstream_modified`).
- **Conservative, evidence-driven milestone semantics.** Dates are mapped only when the upstream *label* says so ("End of Technical Support" → `eol`, "Security Support" → `eossec`). An absent date is published as absent — never inferred from release cadence, support status or a newer version. Where the normalized view is empty but a raw upstream value exists, the human pages show both side by side, so what was set aside and why is always visible.
- **Official OpenEoX export, not just a lookalike.** Records are exported against the unmodified OASIS OpenEoX Core v1.0 CSD01 JSON Schema (vendored, attributed in `OASIS-NOTICE.txt`). Releases whose required dates are unknown are *excluded* from the export and listed in a machine-readable exclusions index instead of being faked into compliance.
- **Permanent, collision-free event identities.** Every feed entry and calendar event carries a `tag:` URI (RFC 4151) that is minted once and kept for the event's whole life — stable for downstream deduplication and alerting across all three feed formats.
- **Fail-closed publication.** Every deploy validates the full catalog against JSON Schema, checks provenance consistency, runs the unit-test suite and only then builds and publishes. A failing refresh leaves the last good deployment live.

## Goals

1. Grow coverage where demand is proven — planned and tracked publicly in [issues](https://github.com/zarguell/eoltracker/issues), with a persistent coverage tracker issue indexing upstream requests against this catalog.
2. Fill milestone gaps deterministically: vendor-specific parsers for sources whose data is not yet covered, each with cited provenance.
3. Keep operating cost at zero and the entire pipeline reproducible from a fresh clone: `pip install`, four CLI commands, no secrets.

## Architecture

```
endoflife.date API ─┐
                    ├─> engine/importer.py ──> data/products/*.json ─┐
eosl.date HTML ─────┘   engine/hardware.py    data/hardware/*.json   │
                                                data/manifest.json   │
                                                                     ▼
                                        engine/validation.py  (JSON Schema + integrity)
                                                                     │
                                                                     ▼
                                     python -m engine build ──> _site/
                                       site.py     HTML (Jinja2, base-path aware)
                                       openeox.py  OpenEoX Core export
                                       feeds.py    Atom / RSS / iCalendar
                                                                     │
                                     GitHub Actions (daily 05:23 UTC) │
                                     gh-pages branch + Pages artifact ▼
                                                     https://zarguell.github.io/eoltracker/
```

| Module | Responsibility |
|---|---|
| `engine/importer.py` | Software: fetch the complete endoflife.date v1 catalog snapshot, normalize milestone semantics per column label, write one record per product under `data/products/` |
| `engine/hardware.py` | Hardware: crawl eosl.date product-family pages (sitemap-driven, 2 workers, 0.5 s pause, ~240 polite requests), parse heterogeneous vendor tables into one shape, write `data/hardware/` |
| `engine/validation.py` | Schema validation (Draft 2020-12) plus integrity checks: manifest counts match files, release identity/provenance coherence, duplicate and conflict detection |
| `engine/site.py` | Searchable HTML catalog: index, per-product and per-model pages with raw-upstream transparency notes, dark/light UI |
| `engine/openeox.py` | Official OpenEoX Core v1.0 CSD01 export with honest per-record exclusions |
| `engine/feeds.py` | Upcoming-milestone Atom/RSS/iCalendar with permanent `tag:` identities |
| `schema/` | Normalized product/hardware schemas and the vendored OpenEoX schemas |
| `tests/` | Regression tests for mapping semantics, parsing and feeds — the gate CI runs before publishing |

Automation lives in `.github/workflows/`: `publish.yml` builds and publishes on every push to `main`, and once a day refreshes both upstream catalogs (independently — one failing source never loses the other's update), commits changed data back to `main`, then publishes. `ci.yml` runs validation, tests and a build on pull requests.

## Data sources and attribution

- Software records derive from [endoflife.date](https://endoflife.date/) (MIT — see `THIRD-PARTY-NOTICES.txt`).
- Hardware records derive from [eosl.date](https://eosl.date/) by Subash Geetha Krishnan (CC BY 4.0 — see `THIRD-PARTY-NOTICES.txt`).
- OpenEoX Core v1.0 CSD01 schema is vendored unmodified from OASIS (`OASIS-NOTICE.txt`).

## Local development

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m engine import-data     # refresh software catalog from upstream
.venv/bin/python -m engine import-hardware # refresh hardware catalog from upstream
.venv/bin/python -m engine validate        # schema + integrity checks
.venv/bin/python -m engine build           # build site, v1 endpoints, feeds into _site/
.venv/bin/python -m unittest discover      # test suite
```

`_site/` is generated output and gitignored. Serve it locally with `python3 -m http.server 8765 --directory _site`.
