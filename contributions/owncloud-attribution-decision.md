# ownCloud core — attribution decision and lifecycle investigation (#126)

Recorded 2026-09-26. Scope: the **ownCloud core** platform release schedule,
which ownCloud publishes under its own project identity even though ownCloud is
now a Kiteworks company.

## Decision

**OwnCloud is its own vendor scope, not a Kiteworks record.** The maintenance
schedule is published by the ownCloud project at an ownCloud-controlled URL, in
ownCloud's own vocabulary ("ownCloud core", major lines 1.0–11), and the page
itself points at ownCloud's own `CHANGELOG.md` as the canonical date source.
Attribution follows the publisher, so a record for this data must set
`vendor` to `ownCloud`, never to Kiteworks. The Kiteworks-owned brand scope is
recorded separately in `contributions/kiteworks-subsidiaries-scope.md`.

**This is not a no-go.** Unlike every other Kiteworks-estate page checked, this
one contains a genuine, dated lifecycle table. The vendor attribution question
is now answered; the remaining decision — whether to adopt it as a
deterministic collector source — is a **GO candidate** recorded below with the
constraints a future implementation must honor.

Tier under AGENTS.md rule 8: (a) deterministic — **viable candidate** (see
"Tier decision"); the public source is a static markdown table on a
GitHub-wiki URL. No parser or registration is written by this investigation.

## Primary-source evidence

All sources were checked on 2026-09-26.

| Source | Access shape | What it states |
| --- | --- | --- |
| [Maintenance and Release Schedule (wiki)](https://github.com/owncloud/core/wiki/Maintenance-and-Release-Schedule) | public static HTML (200); served as markdown at https://raw.githubusercontent.com/wiki/owncloud/core/Maintenance-and-Release-Schedule.md (200) | The table below. Columns: `version`, `release date`, `end of life`, `current version`, `next version`. |
| [owncloud/core `CHANGELOG.md`](https://raw.githubusercontent.com/owncloud/core/master/CHANGELOG.md) | public raw markdown (200, ~609 KB) | Per-release dated changelog entries; the wiki page names this file as canonical for release dates. |

### The published table (verbatim rows)

```
version  | release date   | end of life           | current version          | next version
:-------:|---------------:|:---------------------:|-------------------------:|---------------------:
**11**   | 2026-07-30     | *maintained, EOL TBA* | **11.0.0** (2026-07-30)  | **11.0.1** (TBA)
**10**   | 2017-04-27     | 2027-01               | **10.16.4** (2026-07-29) | **10.16.5** (TBA)
**9.1**  | 2016-07-21     | 2018-02     | 9.1.8 (2018-03-14)  | **End of Life**
**9.0**  | 2016-03-08     | 2017-10     | 9.0.11 (2017-12-05) | **End of Life**
**8.2**  | 2015-10-20     | 2017-05     | 8.2.11 (2017-04-18) | **End of Life**
**8.1**  | 2015-07-07     | 2017-02     | 8.1.12 (2017-02-02) | **End of Life**
**8.0**  | 2015-02-09     | 2016-10     | 8.0.16 (2016-11-08) | **End of Life**
**7.0**  | 2014-06-23     | 2016-05     | 7.0.15 (2016-05-12)     | **End of Life**
**6.0**  | 2013-12-11     | 2015-09     | 6.0.9 (2015-07-07)      | **End of Life**
**5.0**  | 2013-03-14     | 2015-03     | 5.0.19 (2015-03-11)     | **End of Life**
**4.5**  | 2012-10-10     | 2013-07     | 4.5.13 (2013-07-10)     | **End of Life**
**4.0**  | 2012-05-22     | 2013-07     | 4.0.16 (2013-07-06)     | **End of Life**
**3.0**  | 2012-01-31     | 2012-04     | 3.0.3 (2012-04-27)      | **End of Life**
**2.0**  | 2011-10-11     | 2012-01     | *-*                     | **End of Life**
**1.0**  | 2010-06-24     | 2011-10     | *-*                     | **End of Life**
```

The page's own caveat:

> Release dates above are the dates recorded in `CHANGELOG.md`. Please take the
> date from there when updating this page — not the date you happen to edit the
> wiki.

## Tier decision

**Tier (a) deterministic — GO candidate, unattributed implementation.**

- The source is a public, static, unauthenticated markdown table with a stable
  URL, not login-gated and not rate-limited behind an interactive session.
- `endoflife.date/api/all.json` carries **no** `owncloud` slug (checked
  2026-09-26), and no `data/products/` record exists, so this is new coverage
  and would not shadow or conflict with an existing pipeline.
- However, this investigation records the **decision only**. Writing the
  collector, registering the source in `engine/sources.py`, and reconciling row
  accounting are explicitly out of scope here and belong to a follow-up
  implementation issue.

## Constraints a future implementation must honor

1. **Attribution.** `vendor` is `ownCloud`. The record must not be published
   under a Kiteworks-branded id or name.
2. **Month precision stays month precision (rule 4).** Every `end of life`
   value in the table is a month (`2027-01`, `2018-02`, …). It must be stored
   as `YYYY-MM` and never padded to a day. Month-precision milestones are
   excluded from Atom/RSS/iCalendar and from OpenEoX, and must be disclosed in
   `v1/feed-exclusions.json`, exactly as the other month-precision records are.
3. **The `TBA` row is published as an unknown end, never resolved.** Version 11
   states `*maintained, EOL TBA*`. It is a line with no announced end: the
   record must carry version 11 with `ga 2026-07-30` and a **null** `eol`, not
   drop the line and not invent a date. This mirrors the "branch the notice
   leaves undated is published with no dates" rule.
4. **`CHANGELOG.md` is canonical for release dates.** The wiki explicitly
   delegates release dates to `CHANGELOG.md`; the collector's row accounting
   must state whether it reads the wiki's `release date` column or the
   changelog, and must treat the wiki's `current version` / `next version`
   columns as status labels, not milestones.
5. **Row accounting.** Fifteen version lines are published. The collector must
   account for every one, including the two `End of Life` terminal rows for
   `2.0` and `1.0` that carry `-` in `current version`, and must distinguish
   the header row from data rows.
6. **No `eos` / `eossec` invention.** The table publishes a single
   `end of life` column. It must fill `eol` only — never `eos` or `eossec`
   from the same column, and never `ga` from `next version`.
7. **The hidden-tail caveat is cleared.** The current page (checked 2026-09-26)
   renders all fifteen rows with no `Show all versions` collapse control and no
   truncation marker; the raw markdown carries the complete table. A collector
   should nevertheless assert the expected row count so a future collapse
   control cannot silently shrink coverage.

## What must not be done

Do not resolve version 11's `EOL TBA` to any date. Do not pad `2027-01` to a
day. Do not attribute ownCloud's dates to Kiteworks. Do not treat
`current version` or `next version` as GA or EOL milestones. Do not derive an
`eos` or `eossec` from the single `end of life` column. Do not read release
dates from the wiki edit timestamp instead of `CHANGELOG.md`.

## No record published

No contribution file and no `data/products/` record were created by this
investigation. The remaining work — a deterministic ownCloud collector with its
own registered verifier — is a separate implementation issue.
