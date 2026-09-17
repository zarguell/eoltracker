# UniFi Security Gateway (USG) — lifecycle investigation: NO-GO

Disposition for the UniFi Security Gateway hardware lifecycle investigation
(local issue #33). Recorded 2026-09-17. Scope: the **USG hardware family** as
Ubiquiti lists it — the single legacy UniFi gateway series.

## Decision

**NO-GO for a dated lifecycle record.** Ubiquiti classifies the USG family as
`Legacy` in its own Vintage/Legacy list, but publishes **no date** anywhere for
that classification — not an end-of-support date, not an end-of-sale date, not
an obsoletion date. Tier (b) researched coverage requires a verbatim vendor
sentence stating the date beside it; no such sentence exists for this family. No
contribution file was written and no record was installed.

This is **not** a claim that Ubiquiti never publishes dates for hardware. The
vendor demonstrably does: its `UAP` obsoletion announcement names eight models
and states a day-precision date ("… will no longer receive new system releases,
critical bug fixes, or security updates after **March 1, 2021**"), and that link
is published on the very same Vintage/Legacy page. The USG rows on that page
carry **no** such link. That contrast is the finding, and it is also the reopen
condition.

Tier under AGENTS.md rule 8:

- **(a) deterministic — fails.** `eosl.date`, the catalog's hardware pipeline,
  publishes 9 vendors (apple, brocade, cisco, dell-emc, hpe, ibm,
  juniper-networks, netapp, pure-storage) and contains none of the USG family.
  Ubiquiti is not a covered vendor, so extending that pipeline is not available.
  A USG-specific collector was rejected below.
- **(b) researched — fails.** No authoritative primary source states a
  lifecycle date for any USG model. The only quantitative vendor statements are
  *release* dates and a *security-fix availability* date, neither of which is a
  lifecycle end (see "Why the available dates were not stored" below).
- **(c) absent — stands.**

## Model scope, kept separate

The Vintage/Legacy page lists three distinct SKUs, and each went through its own
status change. They must not be collapsed into one record:

| SKU on the vendor page | Status (2026-09-17) | Last firmware listed |
| --- | --- | --- |
| `USG` | Legacy | 4.4.57, published 2023-01-23 |
| `USG-Pro` | Legacy | 4.4.57, published 2023-01-23 |
| `USG-XG-8` | Legacy | 4.4.57, published 2023-01-23 |

The coverage request names one product ("USG"). Any future coverage would have
to decide whether it tracks the 3-port `USG` alone or the family, because the
three did **not** change status together: across archived snapshots of the same
vendor page, `USG-XG-8` was already `Legacy` on 2023-01-27 while `USG` and
`USG-Pro` were still absent from the list; by 2024-03-13 `USG` and `USG-Pro`
appeared as **`Vintage`**; by 2024-04-20 both read **`Legacy`**. A record that
flattened these three into one model would misstate at least two of them.

## Sources checked (fetched live, 2026-09-17)

| Source | What it states | Why it is not lifecycle coverage |
| --- | --- | --- |
| `https://help.ui.com/hc/en-us/articles/1500001268521-Ubiquiti-s-Vintage-and-Legacy-Products` (updated 2026-09-07) | The vendor's own status list. Contains `USG Legacy`, `USG-Pro Legacy`, `USG-XG-8 Legacy`, plus both status definitions | **No dates at all.** The 587-word article contains no four-digit year, no date-precision string and no month-year string. Of the 39 model cells in the UniFi table, only the eight `UAP` rows carry a link, and all eight point to the same dated announcement; every other model cell — including all three USG rows — carries no link, while the third column holds only upgrade-page links |
| The same page, archived | 17 day-distinct snapshots recorded 2023-01-27 … 2025-11-24; six re-fetched and read at the row level. `USG-XG-8` Legacy in all six. `USG`/`USG-Pro` absent 2023-01-27 and 2023-09-24; **`Vintage`** on 2024-03-13; **`Legacy`** from 2024-04-20 onward | A status change with no accompanying dated notice. The archive narrows *when* the page changed but is not the vendor's statement of *when support ends* |
| `https://download.svc.ui.com/v1/downloads?page=N` | 30 USG firmware rows across 16 versions, 2018-12-03 … 2023-01-23. The 4.4.57 rows (all three SKUs) carry `date_published` 2023-01-23 and link to the release post | **Release/publication dates only.** No `eol`, `eos`, `eol_date`, `support_end`, `lifecycle` or `status` field exists on any of the 3,694 rows |
| `https://ui.com/download/releases/firmware` | The live firmware listing. Rendered for 2026-09-17, it lists current UniFi OS and firmware releases and does **not** list the USG | A current-catalog listing. Catalog disappearance is not EOL (rule 7), and its absence here is not a date either |
| `https://community.ui.com/releases/72409267-0f18-400f-8f44-7242a553e449` (USG 4.4.57, 2023-01-23) | The last USG firmware release post: three download links (`UGW3`, `UGW4`, `UGWXG`) and one bugfix, "Fix disclosed security issue." | A release post. It states no support end |
| `https://community.ui.com/releases/USG-XG-8-Product-Status-Update-8-Product/e27285b4-…` (2019-03-30) | The only lifecycle-titled post in the entire 4,231-post release corpus, and it is **dated**: "We fully plan to continue providing support, deliver firmware updates, and ensure controller support for the device." | An explicit statement that support **continues**. It contains **no calendar date at all** (no four-digit year). It is the opposite of an end-date notice and it covers only `USG-XG-8` |
| `https://community.ui.com/releases/Security-Advisory-Bulletin-028-028/696e4e3b-…` (published 2023-01-23) | "All USGs running Version 4.4.56 and earlier." / "Update your USG(s) to Version 4.4.57 or later." | A security-fix advisory: it names the fixed version and the publication date, not a lifecycle end |
| The full release corpus — 4,231 posts enumerated | Exactly **one** lifecycle-titled post (the `USG-XG-8` status update above). Zero USG-titled posts contain end-of-life, end-of-support, end-of-sale, discontinuation, obsoletion or retirement wording | No USG lifecycle announcement exists in the corpus |
| `https://help.ui.com/api/v2/help_center/…/articles/search.json` | Searches for "end of life", "EOL", "EOS", "end of sale", "discontinued", "product retirement", "USG end of support date", "firmware end of life" — none returns a USG lifecycle article | No lifecycle article exists in the help center |
| `https://blog.ui.com/` | The vendor blog index. Zero occurrences of "USG" or "Network Server" in the rendered index | No lifecycle announcement |
| `https://ui.com/sitemap.xml` | 81 URLs; no lifecycle, EOL or support-policy page | No vendor lifecycle page to read |
| `https://endoflife.date/api/all.json` | 483 product slugs; no UniFi/Ubiquiti slug | Confirms no upstream community record to extend |

## Verbatim evidence

Confirmed to appear in the live page text on 2026-09-17 (tags stripped, entities
decoded, whitespace folded). Quoted because they are the evidence that the
classification exists while the dates do not.

- `help.ui.com/…/1500001268521` — the status definitions
  > Vintage Products - These products are no longer manufactured or actively developed but may still be available for purchase.
  > Legacy Products - These products have stopped receiving updates and are no longer distributed by Ubiquiti, though they may still be available from third-party sellers.
- `help.ui.com/…/1500001268521` — the USG rows, as published (the trailing statuses are the vendor's cells)
  > UniFi Application Server (all models) Legacy USG Legacy USG-Pro Legacy USG-XG-8 Legacy UVP Legacy
- `community.ui.com/releases/USG-XG-8-Product-Status-Update-8-Product/…` (2019-03-30, `USG-XG-8` only)
  > We fully plan to continue providing support, deliver firmware updates, and ensure controller support for the device.
- `community.ui.com/releases/Security-Advisory-Bulletin-028-028/…` (published 2023-01-23)
  > All USGs running Version 4.4.56 and earlier .
  > Update your USG(s) to Version 4.4.57 or later .
- `ui.com/download/releases/network-server` — the availability notice, recorded because it is the closest thing to a lifecycle sentence anywhere on the download surface, and it is still not one
  > Certain releases are no longer available due to security and/or regulatory requirements. We always recommend running the latest software to ensure optimal network performance and security. If you require an unlisted release, please contact Ubiquiti Support.

For contrast, the dated hardware announcement the vendor *does* publish for a
sibling product line — same page, linked from the `UAP` rows, and the template
any future USG notice would follow:

- `community.ui.com/questions/Select-UniFi-AP-models-with-support-ending-Mar-2021/…` — titled "Select UniFi Access Point (AP) Models Obsoletion Date: March 1, 2021"
  > The following UniFi Access Point (AP) models will no longer receive new system releases, critical bug fixes, or security updates after March 1, 2021 : UAP-Outdoor UAP-Outdoor+ UAP-Pro UAP-IW UAP (v1+v2) UAP-LR (v1+v2) UAP-AC-EDU UAP-AC-IW-PRO

## Why the available dates were not stored

| Available date | Source | Why it is not a lifecycle milestone |
| --- | --- | --- |
| `2023-01-23` — 4.4.57 published | download feed; release post | A **release** date. Storing it as `eol` would infer an end from "no newer release followed", which rule 2 forbids explicitly. It is a `ga` of sorts, and a GA-only record was rejected below |
| `2023-01-23` — Security Advisory Bulletin 028 published | community release post | The date the **fix shipped**, not the date support ended. Calling it `eossec` would collapse a "fixed in 4.4.57" statement into an "end of security support" claim the vendor never made, breaking the rule that a generic support statement never fills `eossec` |
| `2019-03-30` — the `USG-XG-8` status post | community release post | The post's own **publication** date, not a stated deadline. The post says support continues, so using it as an end date would invert its meaning |
| `2024-03-13` → `2024-04-20` — `USG` Vintage → Legacy | archived snapshots | A status change inferred by diffing archives, not a vendor statement about a date. It bounds when the page changed; it does not state when support ended, and the vendor published no notice alongside it |
| 4.4.55 (2021-04-07) / 4.4.56 (2021-11-08) / 4.4.57 (2023-01-23) | download feed | Release cadence. The 14.5-month gap between 4.4.56 and 4.4.57 is exactly the "product is old" reasoning rule 2 prohibits |

Community thread answers were checked for a vendor statement and are not
evidence: across five USG lifecycle threads consulted (51 answers total, none
employee-authored), the substantive replies are community users reasoning from
the Legacy list. One of them is directly relevant as corroboration that no
announcement was made — a 2024-05-06 thread opened after the SKUs appeared on
the EOL list says so:

- `community.ui.com/questions/Hardware-support-dates-for-Ubiquiti-hardware-EOL-LTS-etc/…` (2024-05-06, non-employee)
  > I've just noticed that the Unifi Security Gateway (USG/USG Pro) hardware is placed on the EOL list on the Ubiquiti website . As far as I know there was no announcement about this.

## Why a GA-only or status-only record was not published

A USG record with every milestone null would publish no lifecycle fact the
vendor's own Legacy list does not already publish, while reading as lifecycle
coverage in the catalog — the same reasoning that rejected a Docker Desktop
GA-only record. It is also **not expressible**: the contribution format requires
a non-empty milestone set and refuses null dates outright. Verified against
`engine.contribute.parse_contribution` on 2026-09-17:

```
no milestones key      REFUSED  -> milestones must be a non-empty object
empty milestones       REFUSED  -> milestones must be a non-empty object
all-null milestones    REFUSED  -> milestones.ga: None is not an ISO day (YYYY-MM-DD); month-only or inferred dates are never accepted
one real date          REFUSED  -> no stored quote states the end of life date; every milestone must be quoted verbatim from the source
```

That fourth line is the decisive one for this investigation: even if a date were
chosen, admission requires a stored quote that states it at day precision. No
USG source contains such a sentence, so the gate would refuse the contribution —
correctly. There is no format in which "Legacy, undated" can be published, and
inventing a date to fit the format is exactly what the rules prohibit.

## Why no USG-specific collector was written

Investigated and rejected on the same evidence that makes the researched tier
fail:

1. The only machine-readable UniFi feed
   (`download.svc.ui.com/v1/downloads`) carries release metadata and **no
   lifecycle field on any of 3,694 rows**, so there is nothing for a collector
   to read. It could only re-derive release dates, which is not lifecycle
   coverage.
2. There is no per-model lifecycle table to parse. The Vintage/Legacy page is a
   three-column status list with no dates, and per AGENTS.md a collector must
   match the vendor's own notice rather than infer from a table's position.
3. Building a collector would also mean owning discovery, refresh and
   `publish_records` plumbing for a source that yields no lifecycle date — cost
   with no coverage, and a fresh maintenance surface for a discontinued family.
4. The registry integration (`engine/sources.py`) is the main agent's
   responsibility, and no descriptor was sent because there is no source to
   register.

## Source limitations

1. No dated USG lifecycle notice exists in any Ubiquiti property checked as of
   2026-09-17: vendor help center, download surface, community release corpus,
   blog, and sitemap.
2. The vendor's `Legacy` status is a **defined state** ("These products have
   stopped receiving updates"), so the family's lifecycle *fact* is published.
   What is absent is any date attached to it, and this catalog's milestone model
   stores dates, not status claims.
3. Ubiquiti's release corpus search is a relevance-ranked full-text search, not
   an exhaustive index. Title-level scanning of all 4,231 enumerated posts is
   exhaustive for titles; body-level scanning was performed for every
   USG-titled post and returned no lifecycle wording. A statement that exists
   only in an untitled reply is not fully ruled out by this investigation.
4. The archived Vintage/Legacy snapshots narrow the `USG`/`USG-Pro` status
   change to between 2024-03-13 and 2024-04-20, but an archive is a
   third-party record of a page, not a vendor statement, and Wayback coverage is
   uneven. Nothing in this disposition depends on those dates.
5. Community answers were checked for vendor statements and contain none: the
   five USG lifecycle threads consulted (51 answers) have zero employee-authored
   answers. This is recorded as a limitation, not as proof that no employee
   statement exists anywhere.
6. The download feed is undocumented, needs an `Origin` header, and its CDN
   ignores the `page` parameter on cache hits; converging on all 3,694 rows
   required retrying until each response's echoed `pagination.page` matched the
   request. Any future reader reproducing these figures must do the same, or
   they will silently collect only 900 unique rows.

## Reopen condition

Reopen when Ubiquiti publishes a dated lifecycle statement for a named USG
model — in practice, when the `USG`, `USG-Pro` or `USG-XG-8` row on
`help.ui.com/…/1500001268521` gains a link to a dated notice, the way the `UAP`
rows already do, or when the vendor publishes an announcement of the form "…
will no longer receive new system releases, critical bug fixes, or security
updates after \<date>". At that point:

- the date is a tier (b) researched **hardware** contribution, admitted through
  `engine contribute` with the vendor sentence stored verbatim, one record per
  SKU the notice actually names; or
- tier (a) if a machine-readable per-model table appears that a collector can
  re-derive, in which case the collector — not a contribution — owns the record.

Until then the family stays absent. Users who need the lifecycle fact today have
it from Ubiquiti's own Legacy list: the status is published, the date is not.

## No record published

No `unifi-security-gateway*` contribution file and no entry under
`data/hardware/` were created. The catalog is unchanged by this investigation.
