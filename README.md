# EOL Tracker

Static, machine-readable lifecycle catalog for hardware and software: general availability, end-of-sale, end-of-security-support and end-of-life dates, normalized into one schema and published as flat JSON, Atom/RSS/iCalendar feeds and OpenEoX records — entirely from GitHub Pages, with no backend and zero hosting cost.

Live site and API: **https://zarguell.github.io/eoltracker/**

## What it is

EOL Tracker ingests community lifecycle catalogs, normalizes their vendor-specific wording into a single conservative schema, and republishes everything as stable static endpoints:

| What | Where |
|---|---|
| Software catalog (488 products, 7,988 releases) | `/v1/products.json`, `/v1/products/{id}.json`, human pages `/products/{id}/` |
| Hardware catalog (6,999 models, 9 vendors) | `/v1/hardware.json`, `/v1/hardware/{id}.json`, human pages `/hardware/{id}/` |
| Upcoming lifecycle milestones (one exact vendor-stated event per release × milestone) | `/v1/feed.atom` (RFC 4287), `/v1/feed.rss` (RSS 2.0), `/v1/calendar.ics` (RFC 5545), exclusions `/v1/feed-exclusions.json` |
| OpenEoX Core v1.0 CSD01 export | `/v1/openeox/index.json`, `/v1/openeox/{product}/{release}.json` |
| JSON Schemas for every published record | `/v1/schema/product.json`, `/v1/schema/hardware.json` |

Everything is rebuilt and published by a scheduled GitHub Actions workflow; there is no server, no database, no cost. Git history is the audit trail: every milestone revision of every record is attributable and revertible.

PowerDNS Authoritative lifecycle is refreshed with
`python -m engine import-powerdns-authoritative`. Its 11 source scopes include
the grouped “4.1 and older” row. Approximate dates remain raw evidence, definite
months retain month precision, and critical-only updates are not support-end
milestones. This community lifecycle does not describe commercial agreements.

Odoo's release and standard-support calendar is refreshed with
`python -m engine import-odoo`. All 14 source rows are retained, including
SaaS versions and the grouped older versions. Release months stay months;
planned dates and “Before” bounds stay raw. Standard-support expiry is not a
terminal or security-support deadline: extended support continues and security
terms differ by hosting platform. Consequently this calendar adds no retirement
feed events and does not establish dated Odoo EOL coverage.

## What differentiates it

- **Hardware and software in one normalized schema.** Community sources are software-shaped or hardware-shaped; this catalog merges both under one milestone model (`ga` / `eos` / `eossec` / `eol`) with provenance on every record (`source_url`, `verifier`, `last_checked`, `upstream_modified`).
- **Conservative, evidence-driven milestone semantics.** Dates are mapped only when the upstream *label* says so ("End of Technical Support" → `eol`, "Security Support" → `eossec`). An absent date is published as absent — never inferred from release cadence, support status or a newer version. A vendor-stated duration, release trigger, or component-support inheritance rule may produce a **derived** date when the base, exact rule, source URL, and quote are retained in `milestone_provenance`; the UI labels it derived. Derived dates are excluded from exact-day feeds and OpenEoX, with machine-readable reasons.
- **Official OpenEoX export, not just a lookalike.** Records are exported against the unmodified OASIS OpenEoX Core v1.0 CSD01 JSON Schema (vendored, attributed in `OASIS-NOTICE.txt`). Releases whose required dates are unknown or derived are *excluded* from the export and listed in a machine-readable exclusions index instead of being faked into compliance.
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

- The baseline software catalog derives from [endoflife.date](https://endoflife.date/) (MIT — see `THIRD-PARTY-NOTICES.txt`). Vendor-primary collectors and researched contributions add products that source does not cover; every record names its exact vendor pages, verifier, and stated/derived date basis.
- Hardware records derive from [eosl.date](https://eosl.date/) by Subash Geetha Krishnan (CC BY 4.0 — see `THIRD-PARTY-NOTICES.txt`).
- OpenEoX Core v1.0 CSD01 schema is vendored unmodified from OASIS (`OASIS-NOTICE.txt`).

XenServer hypervisor lifecycle is refreshed with
`.venv/bin/python -m engine import-xenserver`. It reads three public vendor
pages: the current `xenserver.com/support` product matrix (XenServer 9 and 8.4),
Citrix's legacy product matrix (Citrix Hypervisor 8.2/8.1/8.0, XenServer 7.6
down to 5, and the XenSource 4.x/3.x rows), and the public support article
CTX692513, which states the Citrix Hypervisor 8.2 Cumulative Update 1 end of
life. XenServer 8 and 8.4 are one line (the vendor states 8 is 8.4 under the
hood), only each table's own `EOL` and `EOS` columns become milestones, and
`NSC`, `EOM` and `EOES` stay the vendor's own cells — `NSC` is never general
availability and `EOM`/`EOES` never become a security-support end. Citrix
Hypervisor 8.0/8.1 keep only the dates their tab states. The `8.2` terminal date
is stated by both the legacy matrix and the article, and the refresh refuses if
the two disagree.

Flatcar Container Linux Stable streams are refreshed with
`.venv/bin/python -m engine import-flatcar`. It reads the project's public
release feed (`flatcar.org/releases-json/releases.json`) — which dates every
release to the day — and its channel documentation, which states the Stable
support rule: *"Any Stable major version remains supported until a new major
Stable version is released."* One release is published per Stable major, dated
from that stream's first Stable release as `ga`, with `eol` **derived** from the
dated next-major release and carrying the rule, base and trigger in
`milestone_provenance`; the newest stream keeps a null `eol`, and `eos`/`eossec`
stay null. Alpha, Beta, Edge and LTS rows and the feed's channel-pointer rows
are accounted for with their reasons in `data/flatcar-import.json`. The LTS
stream's 18-month rule is deliberately not modelled: no structured first-release
history per LTS stream exists to measure from, and its yearly cadence is a
release interval, never a date.

openEuler community releases are refreshed with
`.venv/bin/python -m engine import-openeuler`. It reads five official, public
sources: the release-catalog API (`openeuler.org/api/mirrors/`) for release
identities and LTS flags, the download page for the month-precision `Planned
EOL` of the service packs it currently serves, the lifecycle page's own content
component for the community's support rules, the 24.03 LTS SP4 technical white
paper for each release's day-precision release date, and the two release
announcements that date the two releases the sources disagree about. The
catalog API's identities become releases; a white-paper release day becomes
`ga`; a card's `Planned EOL` becomes a month-precision `eol`; and the six-month
innovation window becomes one **derived** `eol`, labelled and carrying its rule,
base and duration in `milestone_provenance`. `eos` and `eossec` stay null — the
full-support-to-maintenance-support boundary still fixes critical CVEs, so it is
not a security-support end. Two `ga` dates stay absent because the sources
disagree (the paper's day, the lifecycle component's month, an announcement's
own dateline); every side is stored verbatim, and a moved or reworded one
refuses the import. The six-year LTS lifetime, the early-SP0 sentence and the
optional two-year extension are read and set aside with reasons, and the
policy's 9/24-month service-pack arithmetic is recomputed beside the cards'
stated months rather than published. The API omits the published innovation
releases 20.09, 21.03, 21.09 and 22.09, which are published from the white
paper's history; a catalog omission is never read as an end of life. Every
source row is accounted for per surface, and the disclosures live in
`data/openeuler-import.json`.

## Local development

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m engine import-data     # refresh software catalog from upstream
.venv/bin/python -m engine import-hardware # refresh hardware catalog from upstream
.venv/bin/python -m engine validate        # schema + integrity checks
.venv/bin/python -m engine build           # build EVERY publication stage into _site/ (atomic)
.venv/bin/python -m unittest discover      # test suite
```

CI and publication install from `requirements.lock` with
`pip install --require-hashes`: `requirements.txt` names the direct dependencies
and the lock pins every transitive distribution by version and SHA-256, so a
compromised index cannot substitute a distribution in a job that holds a write
token. Regenerate the lock after changing `requirements.txt` (see the header of
the lock file).

`python -m engine build` writes the whole publication — pages, v1 endpoints,
OpenEoX, the three syndication feeds with their exclusion account, and the
change ledger — into a sibling staging tree and replaces `_site/` only after
every stage succeeds, so a failed stage leaves the previously published tree
intact rather than a partial one.

`_site/` is generated output and gitignored. Serve it locally with `python3 -m http.server 8765 --directory _site`.
