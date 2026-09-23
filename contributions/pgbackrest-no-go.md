# pgBackRest — lifecycle investigation: NO-GO

Disposition for the pgBackRest lifecycle investigation (master tracker #13).
Recorded 2026-09-17. Scope: pgBackRest 2.x, the PostgreSQL backup tool, only.
PostgreSQL itself is covered by `data/products/postgresql.json` and was not
touched.

## Decision

**NO-GO for a dated lifecycle record.** pgBackRest publishes complete per-version
release dates, but no version-specific end-of-life, end-of-support, or retirement
date — and no calendar date at all beyond release timing.

Tier under AGENTS.md rule 8: (a) deterministic — fails, no API and no lifecycle
table to collect; (b) researched — fails, no authoritative primary source states
an explicit EOL date; (c) absent — stands.

## Sources checked (refreshed 2026-09-23)

| Source | What it states | Why it is not lifecycle coverage |
| --- | --- | --- |
| `https://pgbackrest.org/release.html` | Complete per-version release history with day-precision dates | Release dates only; no EOL, end-of-support, or retirement date for any version |
| `https://pgbackrest.org/news.html` | A 2026-04-27 maintenance-stop notice was explicitly reversed by a 2026-05-18 “pgBackRest Will Continue!” announcement | The dated notice is superseded, not a terminal lifecycle event |
| `https://github.com/pgbackrest/pgbackrest/releases` | Current and historical release tags with publication dates | Release dates only; no EOL policy |

## Verbatim evidence

Stored here so the decision can be re-read at its sources:

- `https://pgbackrest.org/news.html`
  > pgBackRest Is No Longer Being Maintained
  > April 27, 2026

- `https://pgbackrest.org/news.html`
  > pgBackRest Will Continue!
  > May 18, 2026

- `https://pgbackrest.org/news.html`
  > Over the last few weeks, a coalition of sponsors has come together to fund ongoing development.

The April notice is not used as EOL because the project explicitly reversed it and shipped later releases.

## Why release dates were not converted into EOL dates

pgBackRest publishes release dates but no version support window, duration, terminal trigger, or
support-inheritance rule. The 2026 maintenance-stop notice was reversed, and later releases continued,
so it cannot anchor a lifecycle date. Compatibility with PostgreSQL versions describes product
compatibility, not pgBackRest EOL.

## Source limitations

1. No current per-version lifecycle or EOL table with a non-retracted terminal date exists.
2. `https://endoflife.date/api/all.json` has no `pgbackrest` slug, so no deterministic record can be extended.
3. The current stable release is 2.59.1, published 2026-08-17; its release date is not a support end.

## Reopen condition

Reopen when pgBackRest publishes a current, authoritative statement tying a named version to a lifecycle
end, or an explicit support duration/trigger with a stated base. The reversed April 2026 notice must not
be reused as EOL.

## No record published

No `pgbackrest` contribution file and no entry under `data/products/` were created. The catalog remains
unchanged for this product.

