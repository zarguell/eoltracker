# AGENTS.md — eoltracker

Instructions for coding agents working in this repository. This is the
authoritative technical brief; the [README](README.md) is the public overview.

## Non-negotiable rules

1. **Never link to `endoflife-date/endoflife.date` issues in any issue, PR,
   commit message, comment or file created in this repository.** We do not
   backlink our planning to upstream's tracker. Upstream *sources* (the API,
   docs, schemas) may be referenced; upstream issue/PR URLs may not.
2. **No fabricated dates, ever.** A milestone is normally published only when
   the upstream data or label explicitly carries it. Never infer EOL from
   release cadence, support status, a newer release, or "the product is old".
   A date calculated from an explicit vendor duration or release trigger may
   be published only through `milestone_provenance`, with its base date, rule,
   source URL, and exact vendor quote retained; it must be labeled derived in
   every presentation and excluded from exact-day feeds and OpenEoX. Absent
   stays absent when neither a stated date nor an explicit vendor rule supports
   a derivation.
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
6. **Exclusions are published data too.** Every source row a collector drops
   goes into its import report with a truthful, verifiable reason. Verify
   product classification against the vendor's own notice — never from the
   table the row sits in or its name.
7. **Completion means the full picture, not a convenient subset.** For a
   vendor lifecycle integration, cover the current product catalog, announced
   retirements, and historical lifecycle records together. Reconcile their
   model/part/revision scopes and account for every source row. Unknown dates
   remain unknown; catalog presence is not support entitlement, and catalog
   disappearance is not EOL. Verify discovery, refresh, transitions, API,
   website, and feeds end to end before calling the integration complete.
   Explicitly report source limitations; never present partial coverage as
   complete merely because its parser and deployment succeed.
8. **Deterministic first, researched second, derived only with provenance,
   invented never.** For every product ask, in order: (a) does a deterministic
   pipeline cover it today? If yes, extend that pipeline; a manual copy of what
   automation can fetch rots silently. (b) If not, can a human or agent find an
   *authoritative primary source* whose exact dates or explicit duration /
   release-trigger rule can be stored verbatim? A correct, manually
   contributed date with a verifiable citation beats an absent one: users
   managing real fleets need stable facts even when no pipeline can re-derive
   them. A calculated date is admitted only with `milestone_provenance`; the
   result is derived, not vendor-stated. (c) Only when neither a stated date
   nor an explicit vendor rule supports a defensible record does the product
   stay absent. A researched contribution is never a substitute for an
   existing deterministic source: it may not overwrite or shadow a
   deterministic record, and its provenance must carry the verbatim quote,
   source URL, contributor, and research date so staleness is visible. When
   implementing any new coverage, name which tier (deterministic, researched,
   absent) the source supports before writing code.

## Repository layout

```
engine/
  importer.py     software catalog: endoflife.date API -> data/products/*.json
  hardware.py     hardware catalog: eosl.date HTML -> data/hardware/*.json
  opengear.py     Opengear hardware: opengear.com tables -> data/hardware/opengear-*.json
  transaction.py  shared single-product software staging and timestamp preservation
  validation.py   JSON Schema + catalog integrity checks (manifest counts,
                  provenance coherence, duplicate/conflict detection)
  site.py         Jinja2 HTML site (index, per-product, per-hardware pages)
  openeox.py      OpenEoX Core v1.0 CSD01 export with honest exclusions
  feeds.py        upcoming-milestone Atom (RFC 4287) / RSS 2.0 / iCal (RFC 5545)
  templates/      all markup (Jinja2); no HTML in the python modules
  __main__.py     CLI: import-data | import-hardware | import-opengear | validate | build
data/
  products/<id>.json    one normalized record per software product
  hardware/<id>.json    one normalized record per hardware model
  manifest.json         snapshot metadata (counts, generated_at, exclusions)
  opengear-import.json  per-source import report (excluded rows + reasons)
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
.venv/bin/python -m unittest discover       # regression suite; run before every commit
```

`build` renders committed data; it does not crawl upstream. Refresh commands
perform network ingestion. Publication happens through
`.github/workflows/publish.yml` on `main`.

## Data model (what agents must not break)

Software record (`data/products/<slug>.json`):

- `id` — URL-safe slug, also the filename. Renaming an id breaks every
  permalink and feed identity; treat id changes as destructive migrations.
- `releases[]` — each has `id`, `milestones` (`ga`/`eos`/`eossec`/`eol`, ISO
  dates, month-precision `YYYY-MM`, or `null`), optional `milestone_provenance`
  for dates derived from an explicit vendor duration, release trigger, or
  support-inheritance rule, `upstream` (the raw upstream release object, kept
  verbatim for transparency), and record-level `provenance` (`source_url`,
  `verifier`, `last_checked`, `upstream_modified`).
- A milestone is a day (`YYYY-MM-DD`) or a month (`YYYY-MM`) when its source
  states no day; the two widths are distinct values, never padded from one into
  the other. A source that publishes only a day form still stores days.
- `milestone_provenance` is keyed by milestone and contains `kind: derived`, the
  method, source URL, exact quote, base date/label, and exactly one calculation
  input: a duration, dated release trigger, or named parent product/release and
  terminal milestone for support inheritance. Validation recomputes or matches
  the result. Derived dates remain visible in the catalog and product page, but
  never in Atom/RSS/iCalendar or OpenEoX; exclusion documents state why.
- `upstream` for a vendor collector (a source other than endoflife.date) holds
  that vendor's own declared columns under `upstream.cells` and the table they
  came from under `upstream.table`, rather than endoflife.date field names.
- `labels` — upstream column-label wording, the evidence the mapper matched.

Hardware record (`data/hardware/<id>.json`): `id`, `name`, `vendor`,
`product_line`, `milestones`, `status`, `upstream` (raw per-row cells),
`provenance`. Hardware uses eosl.date's own vocabulary; its `eol` is the
terminal support end (their "End of Support Date"), not a software-style
support-contract end. Do not blur the two vocabularies.

Hardware records are source-isolated by `provenance.verifier`
(`deterministic-eosl-date`, `deterministic-opengear`): a refresh may only
replace or prune records carrying its own verifier, must validate the
complete snapshot before writing, and preserves `last_checked` when content
is unchanged (`hardware.publish_records`). When the registry names an
accounting sidecar for the verifier, `publish_records` stages it — the
prospective report when the caller passes `report=`, else the committed one —
beside the staged records so `validate` checks the sidecar's record count
against the snapshot before anything is written; a count disagreement aborts
the refresh instead of publishing a catalog its own report does not describe.

Milestone semantics (shared contract):

- `ga` — general availability (release).
- `eos` — end of sale / orderability.
- `eossec` — end of *security* support only (fixes stop).
- `eol` — end of life / full support end (terminal date).
- Rule: a generic "support" date never fills `eossec`; an announced extension
  with unknown end date must not collapse into an earlier known deadline;
  extended-security dates fill both `eossec` and `eol` only per the mapping
  evidence rules in the importers.
- A derived milestone is never described as vendor-stated. Duration arithmetic
  uses calendar units; a trigger uses the dated release named by the vendor;
  support inheritance uses the explicitly named parent product/release and its
  terminal milestone. Cadence, age, current support and “a newer version exists”
  without an explicit vendor rule are not derivation evidence.

Published endpoints (all under `https://zarguell.github.io/eoltracker/`):
`/v1/products.json`, `/v1/products/{id}.json`, `/v1/hardware.json`,
`/v1/hardware/{id}.json`, `/v1/feed.{atom,rss}`, `/v1/calendar.ics`,
`/v1/feed-exclusions.json`, `/v1/openeox/index.json` +
`/v1/openeox/{product}/{release}.json`, `/v1/schema/*.json`. Feed events carry
permanent `tag:eoltracker,2026:...` identities (RFC 4151) — never re-mint or
reformat them.

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
   access constraints, and that a live fetch of the URL returns a real page
   (a 301 with an empty body is not a source). Record findings in the issue,
   including blockers.
2. **Get a go/no-go decision recorded on the issue** before writing a parser.
   If no-go, document why (no public dates, login-gated, licensing) and close.
3. **Implement as a deterministic module** (patterns: `hardware.py` — sitemap
   discovery, polite fetching, heterogeneous tables; `opengear.py` — exact
   header-matched tables with row accounting). Never scrape behind logins;
   respect robots/ToS. Reuse `hardware.publish_records()` with the source's
   own verifier id so one source's refresh can never touch another's records.
   Single-product software collectors use `engine.transaction` for committed
   ownership checks and staged publication; do not copy the transaction into
   another vendor module. Keep vendor parsing and offline re-derivation in the
   collector. Check committed ownership before fetching upstream.
4. **Extend the schema deliberately** if the source has semantics the current
   schema cannot represent honestly (e.g. month precision, per-firmware
   milestones). Schema changes are reviewed changes with tests.
5. **Import → validate → build → verify live output** — check generated JSON
   against the source values for a sample, run the import twice, and compare
   both product and report bytes. Quiet single-product software refreshes
   preserve `last_checked` and report `checked_at`; these mark content revisions,
   not every fetch attempt. Changed report content advances its timestamp.
   Count source data rows independently of the report's own arithmetic. Define
   whether `published` includes retained history: NetScaler excludes it, while
   Ceph includes it. Do not count retained history as newly seen source rows;
   account separately for duplicate source rows when reconciled.
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
  `tests/fixtures/eosl-*.html` (plus the family sitemap copy) instead of hitting
  eosl.date in the test suite. They are required: a missing fixture fails test
  setup rather than skipping, so markup drift cannot pass CI unnoticed.
- The eosl.date parser fails closed on drift: a row class that names no
  lifecycle this mapper knows, a row whose declared width disagrees with the
  header, a date-shaped milestone that is not a real calendar day, and a
  dated row with no identity all raise. Rows the page legitimately does not
  publish (advertisement/layout rows, blank separators) are counted and named
  per page in the parse result's `accounting`; a family that stops publishing
  models, or drops out of the sitemap, refuses the refresh instead of pruning
  its committed records.
- `data/manifest.json` counts must match the record files — `validate` checks
  this; a mismatch fails the build.
- The OpenEoX export excludes records with unknown required dates and lists
  them in `v1/openeox/index.json` under `excluded`; do not force records into
  the export by fabricating dates. A release whose source states a milestone as
  a month is excluded under `<property>_month_precision` for the same reason:
  OpenEoX Core carries a stated day, so publishing it would invent one.
- Feeds include only upcoming events (`today <= date`, UTC). Old events
  disappearing from the feed is correct behavior, not a bug. A month-precision
  event is upcoming through the last day of its month.
- Atom, RSS and iCalendar each carry an exact calendar day, so a month-precision
  event is not syndicated: `v1/feed-exclusions.json` enumerates it with its
  identity and the stored month, and the document's counts plus the feeds'
  cover every upcoming event. A consumer wanting every deadline reads both.
- Templates are base-path aware (`/eoltracker/` prefix on Pages); never
  hardcode absolute `/v1/...` URLs in templates or JS.
- Classify products from the vendor's own notice, not table position: CMS6100
  was mislabeled "software" because it sat among software exclusions; its own
  EoL PDF proves a hardware appliance (sale dates, hardware specs). Check the
  product's notice before writing an exclusion reason.
- Local `yaml.safe_load` is not a workflow validator: a publish.yml missing
  `runs-on` parsed locally and failed only in Actions. After editing
  workflows, diff against origin/main; every job needs `runs-on` and `steps`.
- A missing date does not justify dropping a firmware line. Test unknown dates,
  blank/rowspan groups, appliance exclusions, duplicate lines, renamed headers
  and tampered cells. Use minimal valid tables for refusal paths and saved
  vendor pages for real inventory; distinguish header rows from data rows.
- Regression assertions must exercise the intended boundary. To test EOM/EOL
  ordering, change the EOM source cell; changing normalized EOL only tests
  re-derivation. Assert exception types rather than incidental Python wording.
  Do not change production behavior merely to satisfy an invented test claim.
- After an edit changes line numbers, use its returned anchors or re-read the
  affected construct. Never apply remembered line ranges. A syntax warning
  stops further edits until the damaged construct is repaired and checked.
- Give each file one concurrent editing owner; hand off only after writes stop.
  A saved runnable collector is the integration checkpoint, not an agent's
  readiness claim. Run its real CLI before treating coverage as implemented.
- Verify the `publish.yml` run for the exact pushed commit, not simply the newest
  Actions run (which may be a dependency job). Close implementation issues only
  after that deployment succeeds and its live JSON is checked.
- Stage existing registered source reports alongside product records so sibling
  report consistency checks are not silently skipped. Validation-before-write
  is not filesystem atomicity: orchestrated refresh rollback is supplied by
  `engine.refresh`, while direct collector CLI writes remain sequential.
- Test quiet refreshes at different timestamps, comparing both product and
  report bytes. Also change only an excluded row: the report revision must
  advance while the unchanged product keeps its revision timestamp.
- Inspect response types and bodies before parsing: the legacy
  `endoflife.date/api/all.json` is a list of strings, while the v1 product
  listing is an object containing `result`. HTTP 200 alone is not source
  evidence: Odoo's old documentation URLs serve HTML meta-refresh pages.
  Follow the declared destination and inspect its actual table.
- Follow the policy page's primary-source links before declaring a no-go.
  PowerDNS Recursor's dated support grid lives on its support-commitment page,
  not its prose-only EOL page. A failed URL or empty extraction is not proof
  that the vendor publishes no lifecycle dates.
- Contribution installation uses `python -m engine contribute --install FILE`,
  not an `install` subcommand. Read the parser/help before retrying a CLI error.
- Publish a new collector's registry entry, implementation and generated data
  together. Omitting `engine/sources.py` causes `UnknownVerifier` in CI even
  when the local checkout validates.
- Coverage-loop counts are deduplicated work items, not issue numbers:
  investigation and implementation follow-ups count once, corrections do not
  count again, and refactors do not increase product coverage. Report no-go
  dispositions separately from published data.
