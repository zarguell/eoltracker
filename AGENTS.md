# AGENTS.md — eoltracker

Instructions for coding agents working in this repository. This is the
authoritative technical brief; the [README](README.md) is the public overview.

## Non-negotiable rules

1. **Never link to `endoflife-date/endoflife.date` issues in any issue, PR,
   commit message, comment or file created in this repository.** We do not
   backlink our planning to upstream's tracker. Upstream *sources* (the API,
   docs, schemas) may be referenced; upstream issue/PR URLs may not.
2. **No fabricated dates, ever.** A milestone is published only when the
   upstream data or label explicitly carries it. Never infer EOL from release
   cadence, support status, a newer release, or "the product is old". Absent
   stays absent.
3. **Conservative label mapping.** Milestones in `engine/importer.py` /
   `engine/hardware.py` are assigned by matching the upstream column *label*
   (normalized: case, hyphens, punctuation folded). Extending the mapping
   requires evidence from a real upstream record, plus a regression test
   pinning the vendor wording.
4. **Month-precision dates must not become day-precision.** If a source
   publishes "July 2028", do not invent `-28`. Store the precision the source
   gives or extend the schema deliberately in a reviewed change.
5. **Tests and validation gate every push.** `python -m unittest discover`
   and `python -m engine validate` must pass before committing. CI runs the
   same gate before publication.

## Repository layout

```
engine/
  importer.py     software catalog: endoflife.date API -> data/products/*.json
  hardware.py     hardware catalog: eosl.date HTML -> data/hardware/*.json
  validation.py   JSON Schema + catalog integrity checks (manifest counts,
                  provenance coherence, duplicate/conflict detection)
  site.py         Jinja2 HTML site (index, per-product, per-hardware pages)
  openeox.py      OpenEoX Core v1.0 CSD01 export with honest exclusions
  feeds.py        upcoming-milestone Atom (RFC 4287) / RSS 2.0 / iCal (RFC 5545)
  templates/      all markup (Jinja2); no HTML in the python modules
  __main__.py     CLI: import-data | import-hardware | validate | build
data/
  products/<id>.json    one normalized record per software product
  hardware/<id>.json    one normalized record per hardware model
  manifest.json         snapshot metadata (counts, generated_at, exclusions)
schema/                 normalized + vendored OpenEoX JSON Schemas
tests/                  unittest suite (the CI gate)
.github/workflows/      publish.yml (build+publish, daily refresh), ci.yml (PR gate)
OASIS-NOTICE.txt, THIRD-PARTY-NOTICES.txt   required attributions; keep in sync
```

`_site/` is generated output, gitignored, never committed. `data/` is the
committed source of truth for the catalog; the built site is derived.

## Commands

```bash
.venv/bin/python -m engine import-data      # refresh software from upstream API
.venv/bin/python -m engine import-hardware  # refresh hardware (~240 polite requests, 2 workers, 0.5s pause)
.venv/bin/python -m engine validate         # schema + integrity; nonzero exit on any violation
.venv/bin/python -m engine build            # rebuild _site/ (site, v1 endpoints, OpenEoX, feeds)
.venv/bin/python -m unittest discover       # 60+ tests; run before every commit
```

Full build takes ~5 minutes (hardware crawl dominates). Committing data
changes alone does not publish anything — publication happens only through
`.github/workflows/publish.yml` on `main`.

## Data model (what agents must not break)

Software record (`data/products/<slug>.json`):

- `id` — URL-safe slug, also the filename. Renaming an id breaks every
  permalink and feed identity; treat id changes as destructive migrations.
- `releases[]` — each has `id`, `milestones` (`ga`/`eos`/`eossec`/`eol`, ISO
  dates or `null`), `upstream` (the raw upstream release object, kept verbatim
  for transparency), `provenance` (`source_url`, `verifier`,
  `last_checked`, `upstream_modified`).
- `labels` — upstream column-label wording, the evidence the mapper matched.

Hardware record (`data/hardware/<id>.json`): `id`, `name`, `vendor`,
`product_line`, `milestones`, `status`, `upstream` (raw per-row cells),
`provenance`. Hardware uses eosl.date's own vocabulary; its `eol` is the
terminal support end (their "End of Support Date"), not a software-style
support-contract end. Do not blur the two vocabularies.

Milestone semantics (shared contract):

- `ga` — general availability (release).
- `eos` — end of sale / orderability.
- `eossec` — end of *security* support only (fixes stop).
- `eol` — end of life / full support end (terminal date).
- Rule: a generic "support" date never fills `eossec`; an announced extension
  with unknown end date must not collapse into an earlier known deadline;
  extended-security dates fill both `eossec` and `eol` only per the mapping
  evidence rules in the importers.

Published endpoints (all under `https://zarguell.github.io/eoltracker/`):
`/v1/products.json`, `/v1/products/{id}.json`, `/v1/hardware.json`,
`/v1/hardware/{id}.json`, `/v1/feed.{atom,rss}`, `/v1/calendar.ics`,
`/v1/openeox/index.json` + `/v1/openeox/{product}/{release}.json`,
`/v1/schema/*.json`. Feed events carry permanent `tag:eoltracker,2026:...`
identities (RFC 4151) — never re-mint or reformat them.

## Workflows

### Changing code or schemas

1. Reproduce first (bug) or write the failing test first (behavior change).
   Add regression tests next to the affected module in `tests/`.
2. Make the change; keep markup in `engine/templates/`, logic in `engine/`.
3. Run: `python -m unittest discover` and `python -m engine validate`.
4. For schema changes: schemas live in `schema/` and are copied to
   `_site/v1/schema/` at build time; keep both in sync via the build, never
   hand-edit `_site`.
5. For label-mapping changes: cite the upstream product page in the test
   comment and cover the negative case (what must NOT map).
6. Commit with a specific message; push to `main` publishes automatically.

### Adding a data source or product family

This is how gap-analysis items are implemented (tracked in the repo's issues;
see the master coverage tracker issue for the current queue):

1. **Investigate first** — verify the primary source: exact URL, table shape,
   date semantics (sale vs security vs terminal support), update cadence,
   access constraints. Record findings in the issue, including blockers.
2. **Get a go/no-go decision recorded on the issue** before writing a parser.
   If no-go, document why (no public dates, login-gated, licensing) and close.
3. **Implement as a deterministic module** (see `hardware.py` for the pattern:
   sitemap discovery, polite fetching, heterogeneous-table parsing, raw-cell
   preservation). Never scrape behind logins; respect robots/ToS.
4. **Extend the schema deliberately** if the source has semantics the current
   schema cannot represent honestly (e.g. month precision, per-firmware
   milestones). Schema changes are reviewed changes with tests.
5. **Import → validate → build → verify live output** — check generated JSON
   against the source values for a sample before committing.
6. **Update the tracking issue** with what was done; close only after the
   change is on `main` and the live site shows the new data.

### Refreshing the catalog locally

Run `import-data` / `import-hardware`, then `validate`, then review `git
status data/` before committing. The daily Actions run does exactly this on a
schedule (05:23 UTC) and commits changes back to `main` as
`github-actions[bot]`. Never hand-edit files under `data/` — they are
generated from upstream and will be overwritten; corrections belong in the
importer or in upstream.

### Issue conventions

- Work items live as GitHub issues; the persistent master tracker issue stays
  open and indexes coverage gaps and work items.
- Investigation issues close only with a recorded go/no-go decision and
  evidence; implementation issues close only after merged changes and verified
  live endpoints (cite the commit/PR and a sample endpoint).
- Do not reference upstream endoflife.date issues anywhere (rule 1).

### Known pitfalls

- `engine/hardware.py` fetches live pages; use the saved sample pages in
  tests instead of hitting eosl.date in the test suite.
- `data/manifest.json` counts must match the record files — `validate` checks
  this; a mismatch fails the build.
- The OpenEoX export excludes records with unknown required dates and lists
  them in `v1/openeox/index.json` under `excluded`; do not force records into
  the export by fabricating dates.
- Feeds include only upcoming events (`today <= date`, UTC). Old events
  disappearing from the feed is correct behavior, not a bug.
- Templates are base-path aware (`/eoltracker/` prefix on Pages); never
  hardcode absolute `/v1/...` URLs in templates or JS.
