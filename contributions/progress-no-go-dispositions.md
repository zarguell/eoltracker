# Progress Software — no-go dispositions

Recorded 2026-09-26, against issue #133. Four families carry the Progress name in
a catalog, a marketing page or a search result, and none of them publishes a
per-release lifecycle date this repository can normalize. Each is recorded here
rather than in the catalog, and each states what would change the decision.

The four deterministic sources that *do* exist (OpenEdge, OpenEdge Pro2,
Corticon, Corticon.js, WhatsUp Gold, Sitefinity) ship in `engine/progress.py`
with their own verifiers and reports.

## Semaphore — no dates anywhere

* Policy: `https://docs.progress.com/bundle/Semaphore-Product-Life-Cycle/resource/Semaphore-Product-Life-Cycle-Policy.pdf`
  (`meta-lastMod: Feb 28, 2024`) — the same document as MarkLogic's, covering
  both products, and it is policy prose with no version table.
* The only Semaphore version table found is a marketing data sheet,
  `https://www.progress.com/docs/default-source/semaphore-docs/progress-semaphore---lts-vs-innovation-release-rev.pdf`,
  listing Semaphore 5.0 through 5.10 under `Version | Active | Sunset | Retired`
  — **with every date cell empty**. Its only lifecycle statement is prose: "All
  versions older than Semaphore 5.0 are considered retired."

**Tier (c): absent.** The 4-active / 2-sunset policy has no dated base per
release, so even the derivation tier has nothing to derive from.
**Reopens when** any Progress page or PDF gives a dated base per Semaphore
release.

## Redgate — a whole vendor with no lifecycle data

Redgate is not on Progress's Product Life Cycles index, and publishes no
lifecycle dates of its own. What was checked:

| Source | What it states |
| --- | --- |
| `documentation.red-gate.com/flyway/release-notes-and-older-versions` | Release dates only (Flyway Desktop 1.0, Oct 2019 → 9.0, Jan 2026) |
| `documentation.red-gate.com/sp/release-notes-and-other-versions` | Release dates only (SQL Prompt 3.0, Jan 2007 → 11.5, Aug 2026) |
| `documentation.red-gate.com/rp` | A 22-product "retired products" list, **no dates** |
| `documentation.red-gate.com/xx/archived-documentation` | The same list, "Page last updated 07 January 2016" |
| `www.red-gate.com/support/standard-support/` | Response times and coverage hours only |
| `productsupport.red-gate.com` search for "end of life" | 12 knowledge-base articles, all of them community questions **asking where to find the EOL dates** |

That last row is the decisive evidence: the vendor's own help centre is full of
customers asking for dates that are not published.
**Tier (c): absent for every Redgate product.**
**Reopens when** Redgate publishes a per-product version-support/EOS table, or a
support-duration rule with an explicit stated base.

## MarkLogic — researched at best, and the evidence is weak

* Policy: `https://docs-be.progress.com/bundle/MarkLogic-Product-Life-Cycle/raw/resource/enus/MarkLogic-Product-Life-Cycle-Policy.pdf`
  — "Effective Date: November 2023", change log with one entry. Policy prose, no
  version table. It does state the rule shape ("the start of the four-year
  countdown to the release entering the Sunset life cycle phase", "The duration
  of the Sunset Phase for LTS releases is fixed at two years"), but a 4+2 model
  needs a dated base per release and supplies none.
* The only dated table is a marketing data sheet,
  `https://www.progress.com/docs/default-source/data-sheets/v2-new-lifecycle-policy-summary-ritm0234657.pdf`,
  stamped Aug 2025. Its five rows read, in part, `MarkLogic Server 10 | June 2019
  | Sunset | (March, 2026)` and `MarkLogic Server 11.3 | June 2024 | Long-Term
  Support | Active | Supported (2030)`. The only terminal value is a bare year
  with no month, and the sheet is a sales document, not the lifecycle guide.
* The page that looks authoritative,
  `https://community.progress.com/s/products/marklogic/supported-versions`,
  serves a Salesforce Experience Cloud shell whose entire body is `Loading` — it
  is not agent-readable, and no public GET API was found.

**Tier (b), blocked.** Admissible only as a human-read researched contribution
with a verbatim quote, URL, contributor and research date; it must not shadow a
deterministic record (there is none today).
**Reopens when** someone opens that page in a browser and reports whether it is
reachable without a Progress account and what dates it states.

## MOVEit, WS_FTP, MOVEit Analytics, MOVEit Automation — public but not machine-readable

The Product Life Cycles index links MOVEit to
`https://community.progress.com/s/life-cycle-file-transfer`. Every candidate was
fetched and every one serves `Loading`:
`community.progress.com/s/life-cycle-file-transfer`,
`community.progress.com/s/products/moveit/product-lifecycle`,
`progress.my.site.com/s/article/End-of-Life`,
`progress.my.site.com/s/article/MOVEit-Analytics-End-of-Life-EOL`. The
help-centre search endpoint 404s and Salesforce Experience Cloud serves content
through a POST to `/s/sfsites/aura`, so there is no public GET path.

**Tier (b), blocked** — the source exists and is public, but no agent can read
it, so nothing may be quoted from it.
**Reopens when** a GET-reachable rendering or a public API appears, or a
contributor reads the article in a browser and contributes the rows with a
verbatim quote.

## Progress Cortex — not established, so no disposition

`https://www.progress.com/cortex` returns HTTP 404 and the product does not
appear on the Product Life Cycles index; searches returned unrelated vendors
(Cortex.io, Snowflake Cortex, Palo Alto Cortex). This is an open question, not a
no-go, and no coverage issue should be filed before a human locates the
product's own page.
