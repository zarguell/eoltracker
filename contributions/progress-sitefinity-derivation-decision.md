# Sitefinity: the vendor's first-of-month rule, and what this collector does with it

Recorded 2026-09-26, against issue #132 ("Model Sitefinity first-of-month
derived dates with provenance").

## The rule, verbatim

`https://www.progress.com/support/sitefinity-lifecycle-policy` states:

> **Sunset** and **Retired** phases start on the first day of the month indicated
> in the table

and, for the beginning of a release:

> **Active** phase starts on the GA date. The month is provided for reference

This is the only explicit day-derivation rule anywhere in Progress's published
material, and it is exactly the shape AGENTS.md rule 2 admits: an explicit vendor
rule with a stated base, so a derived date would be admissible *with*
`milestone_provenance`.

## Decision: publish the stated months, and keep the derivation available but unused

`engine/progress.py` publishes every Sitefinity milestone at the **month
precision the table states** — `2026-11`, not `2026-11-01`. The rule is not
applied, for two reasons:

1. **AGENTS.md rule 4 is explicit.** "If a source publishes 'July 2028', do not
   invent `-28`. Store the precision the source gives or extend the schema
   deliberately in a reviewed change." The table states a month. A day would be
   a reviewed change to how a whole family is published, and it buys nothing for
   a reader comparing months.
2. **A derived date has costs the stated month does not.** Every derived
   milestone must be labelled derived in every presentation and excluded from
   the exact-day feeds (Atom, RSS, iCalendar) and from OpenEoX, with the
   exclusion document's counts reconciling. Sitefinity's `Retired` column is
   where a fleet manager most wants a date in the feed; publishing `2026-11`
   keeps it there, and publishing a derived `2026-11-01` would remove 23 versions
   from the syndication surface to gain a day the vendor never printed.

The rule is not discarded: `progress.sitefinity_first_of_month(release,
page_text, phases=True)` performs the derivation, requires the licensing
sentence verbatim from the page (so it cannot derive under a rule the vendor
dropped), and returns the derived days plus their base month and rule. The
report records the decision and names the helper, so a future reviewed change
turns it on without re-deriving the evidence.

`tests/test_progress.py::SitefinityTests` pins both halves: the refresh
publishes `2026-11` with no `milestone_provenance`, and the helper independently
derives `2026-11-01` for the same row.

## Two cells this decision also settles

* **`No earlier than Jan 2030***` (Sitefinity 15.4 LTS) is a floor, not a
  deadline.** The page's own footnote says the date "is open and may be extended
  further past Jan 2030 depending on business conditions", so `eol` is null and
  the cell is kept verbatim. A floor narrowed to its first day would be the
  opposite of what the vendor states.
* **A stated year or a month window publishes nothing.** The grouped 13.0/13.1/
  13.2 row states `2020` (a year the schema has no width for) and the grouped
  14.1/14.2/14.3 row states `March-Nov 2022` (a window). Both are reported in
  `rows.not_representable` with a reason, and neither is narrowed to one of its
  ends.
