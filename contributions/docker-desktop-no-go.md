# Docker Desktop 4.x — lifecycle investigation: NO-GO

Disposition for the Docker Desktop lifecycle investigation (master tracker #13).
Recorded 2026-09-17. Scope: Docker Desktop 4.x, the desktop application, only.
Docker Engine is covered by `data/products/docker-engine.json` and was not
touched; Desktop carries its own 4.x versioning independent of Engine semver.

## Decision

**NO-GO for a dated lifecycle record.** Docker publishes release dates for
Desktop, but no version-specific end-of-life, end-of-support or retirement date —
and no calendar date at all. The relative statements it does publish are policy
arithmetic waiting to happen, so no contribution was written and no record was
installed.

Tier under AGENTS.md rule 8: (a) deterministic — fails, no API and no lifecycle
table to collect; (b) researched — fails, no authoritative primary source states
an explicit date; (c) absent — stands. Building a 146-row GA-only record with
every `eol` null was explicitly rejected: it would publish no lifecycle fact the
vendor's own release-notes page does not already publish, while reading as
lifecycle coverage in the catalog.

## Sources checked (all fetched live, HTTP 200, 2026-09-17)

| Source | What it states | Why it is not lifecycle coverage |
| --- | --- | --- |
| `https://docs.docker.com/desktop/release-notes/` | Complete per-version release history with day-precision dates: 146 `version + YYYY-MM-DD` pairs from 4.0.0 (2021-08-31) to 4.91.0 (2026-09-14) | Release dates only. Its one quantitative statement is "Docker Desktop versions older than 6 months from the latest release are not available for download." — a **download-availability cutoff**, not an EOL commitment |
| `https://docs.docker.com/desktop/troubleshoot-and-support/faqs/releases/` | "New releases are available every week, unless there are critical fixes that need to be released sooner." | Release cadence and update behaviour. No lifecycle or EOL statement |
| `https://docs.docker.com/support/` | "Supported versions — Docker Business: Versions up to six months older than the latest version (fixes applied to latest version only) Docker Pro and Team: Latest version only" | A **rolling subscription support entitlement**, relative to "the latest version", stating no per-version end date. Even the one number is a Business-plan support window, not a product lifecycle policy, and it excludes Docker Pro/Team entirely |
| `https://docs.docker.com/release-lifecycle/` | Docker's product release lifecycle: stages (Experimental, Beta, Early Access, General Availability) and a retirement process, e.g. "Advance notice: For retirement of major features or products, we will attempt to notify customers at least 6 months in advance." | Feature/product-level process, no per-version Desktop table. It is also self-declared non-binding: "This document is not a contract and all use of Docker's services are subject to Docker's Subscription Service Agreement." A best-effort "we will attempt to notify" is a notice policy, never a dated milestone |
| `https://docs.docker.com/retired/` | Deprecated/retired features and products, including Desktop-adjacent ones: "It was deprecated and removed from Docker Desktop version 4." and "The docker sandbox plugin was removed in Docker Desktop 4." | Feature retirement entries; none names a Desktop *version* with a support-end date. Docker Desktop itself is not listed as retired |
| `https://endoflife.date/api/all.json` | 475 products; no `docker-desktop` slug (only `docker-engine`) | Confirms no upstream community record to extend |

## Verbatim evidence

Stored here so the decision can be re-read at its sources; every sentence below
was confirmed to appear verbatim in the live page text on 2026-09-17.

- `docs.docker.com/desktop/release-notes/`
  > Docker Desktop versions older than 6 months from the latest release are not available for download.
- `docs.docker.com/desktop/troubleshoot-and-support/faqs/releases/`
  > New releases are available every week, unless there are critical fixes that need to be released sooner.
- `docs.docker.com/support/`
  > Docker Business: Versions up to six months older than the latest version (fixes applied to latest version only) Docker Pro and Team: Latest version only
- `docs.docker.com/release-lifecycle/`
  > The decision to retire or deprecate features follows a rigorous process including understanding the demand, use, impact of feature retirement and, most importantly, customer feedback.
  > Advance notice: For retirement of major features or products, we will attempt to notify customers at least 6 months in advance.
  > Docker commits to providing continued support for functionality until its retirement date.
  > This document is not a contract and all use of Docker's services are subject to Docker's Subscription Service Agreement.
- `docs.docker.com/retired/`
  > This document provides an overview of Docker features, products, and open-source projects that have been deprecated, retired, or transitioned.
  > It was deprecated and removed from Docker Desktop version 4.
  > The docker sandbox plugin was removed in Docker Desktop 4.

## Why the relative statements were not converted into dates

Every quantity Docker states is relative to "the latest release" or is a notice
period — never a fixed calendar day for a named version:

| Statement | Source | Why it is not a stored date |
| --- | --- | --- |
| "older than 6 months from the latest release are not available for download" | release-notes | Download availability, not support end. Deriving `latest + 6 months` invents a date Docker never published, and it would move every time a release ships |
| "Versions up to six months older than the latest version" | support | Rolling plan entitlement (Docker Business only), same arithmetic trap |
| "at least 6 months in advance" | release-lifecycle | A best-effort notice horizon for feature/product retirement, not a version deadline |
| "available every week" | releases FAQ | Cadence, explicitly the kind of statement the contribution rules call evidence that no end date exists |

`contributions/README.md` states the rule directly: "A rolling support policy
('only the latest minor branch is maintained') is evidence that no end date
exists, never a date in itself." Docker Desktop's policy is that shape.

## Source limitations

1. No per-version Desktop lifecycle or EOL table exists anywhere in Docker's
   documentation as of 2026-09-17, so there is no date to collect deterministically
   and no quote to store as a researched contribution.
2. Docker Desktop's version-specific lifecycle is effectively undefined and
   shifting: support follows the movable "latest version" (Pro/Team) or "up to six
   months older than the latest version" (Business), so any published end would be
   superseded by the next weekly release rather than by a vendor announcement.
3. Feature-level retirement exists (`docs.docker.com/retired/`,
   `docs.docker.com/release-lifecycle/`) but is scoped to features and products,
   not to Desktop releases, so it cannot populate `releases[].milestones`.
4. The lifecycle page is explicitly not contractual, which further weakens any
   future date-bearing statement from it as a lifecycle commitment.
5. `docs.docker.com/desktop/support/` returns 404; Docker Desktop support content
   lives at `docs.docker.com/support/`.

## Reopen condition

Reopen when Docker publishes an authoritative, day-precision statement tying a
**named Desktop version** to a lifecycle end — e.g. a per-version Desktop
lifecycle/EOL table under `docs.docker.com/desktop/`, or a vendor notice naming a
Desktop version and its support-end or retirement date. At that point the date is
a tier (b) researched contribution (or tier (a) if a table appears that a
collector can re-derive). Until then the product stays absent, with release dates
available from Docker's own release notes.

## No record published

No `docker-desktop` contribution file and no entry under `data/products/` were
created. The catalog is unchanged apart from the PowerDNS Recursor record above.
