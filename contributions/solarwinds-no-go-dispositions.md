# SolarWinds — no-go dispositions and one naming answer

Recorded 2026-09-26, against issues #120 (SaaS offerings), #121 (DPM, DRE,
Papertrail, Pingdom, Loggly) and #122 (the DPAE / EPM / STM names). Each family
is absent from the catalog on purpose, and each says what would change that.

What *does* ship: 30 product-family records and 509 releases from the vendor's
own release-history tables (`deterministic-solarwinds`), and the mapping
decision behind them in `solarwinds-milestone-mapping.md`.

## SaaS offerings — Observability SaaS and Service Desk: no dated lifecycle

* `https://www.solarwinds.com/legal/end-of-life-policy-for-saas-products` — the
  governing policy. Verbatim: "A SaaS offering will begin the End-of-Service-Life
  (EOSL) process only when SolarWinds decides to terminate the SaaS offering in
  its entirety", with a footnote that a notification precedes the EOSL date by
  at least six months. A policy that starts when the vendor decides states no
  date for any offering.
* `.../en/success_center/observability/content/release_notes/release_notes.htm`
  — serves a meta-redirect stub with no content; the Service Desk page carries
  only a "Service Desk 2026 release notes" heading.

**Tier (c): absent.** A SaaS offering with no version has no version to
retire, and no EOSL notice naming a specific offering has been published.
**Reopens when** SolarWinds publishes an EOSL notice naming an offering with a
date; the policy says it "will aim to provide an EOSL notification six (6)
months prior", so one can appear at any time.

## DPM — Database Performance Monitor: the documentation is off-domain

`https://support.solarwinds.com/database-performance-monitor` is a public
support page with no lifecycle table, and the product's documentation lives at
`https://docs.vividcortex.com/` — a different company, acquired by SolarWinds.
A lifecycle published by VividCortex under the VividCortex identity is not a
SolarWinds-primary source, and one published under the SolarWinds identity does
not exist today.

**Tier (c): absent.** **Reopens when** a dated lifecycle table appears on
`docs.vividcortex.com` naming the product, or SolarWinds publishes a
release-history page for it.

## DRE — Dameware Remote Everywhere: an index with no dates

`https://documentation.solarwinds.com/en/success_center/dre/content/release_notes/dre_all_release_notes.htm`
lists components (Admin Area, Windows Console, Windows Agent, macOS/iOS/Android
Console and Applet, Linux Agent) and shows "Latest Update" cells that are
**empty**. There is no version row, no date, and no support statement.

**Tier (c): absent.** **Reopens when** any SolarWinds page publishes per-version
EoE/EoL dates for a DRE component.

## Papertrail, Pingdom, Loggly — catalog names with no dates

These three appear in SolarWinds' own product catalog and have no EoL date
anywhere SolarWinds publishes. The contrast that proves the gap is publication
rather than product status: **AppOptics and Librato — the same hosted-observability
and hosted-logging categories — do carry EoL dates (AppOptics and Librato both
EoL January 31, 2026)** on SolarWinds' own retired-products table.

**Tier (c): absent.** **Reopens when** SolarWinds publishes EOSL dates for the
remaining hosted offerings, as it has for AppOptics and Librato.

## DPAE, EPM, STM — not SolarWinds product names; no coverage issue

Searched the SolarWinds product catalog, the full release-history page set
discovered from the vendor's sitemap, and the vendor's own documentation. None of
DPAE, EPM or STM appears in any of them. The catalog does contain **DPA**
(Database Performance Analyzer, formerly Confio Ignite — collected, 2 supported
and 21 unsupported rows) and a patch-management product, but nothing that
resolves the three names to a distinct SolarWinds product.

**Answer: these are not current SolarWinds product names.** They are either
internal or legacy abbreviations, or a mis-transcription. **No coverage issue
is filed for them**, and no record is created under any id derived from them —
which is the outcome that matters: a wrong expansion cannot quietly become a
record id. **Reopens when** a SolarWinds page names one of them.

## NetApp — deliberately no issue

NetApp appears in SolarWinds' documentation only as a third-party integration
target inside the SRM guide (`srm-netapp-oncommand-unified-manager.htm`). A
third-party integration is not a SolarWinds product, and NetApp's own portfolio
belongs to NetApp. Recorded here so it stops recurring as a false lead.

## The retired-products table — a host-level block

`support.solarwinds.com` answers every request from this repository's collector
with HTTP 403, including `robots.txt`, while `documentation.solarwinds.com`
serves the same client fine. The 20-row retired-products table on that host
therefore cannot be refreshed, and nothing from it is published. Full evidence
and the unblock condition are in `solarwinds-retired-products-no-go.md`.
