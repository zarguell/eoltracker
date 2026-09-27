# Edge-device vendors named by CISA's guidance — dispositions

Recorded 2026-09-26, following the BOD 26-02 investigation
(`cisa-bod-26-02-eos-list.md`), which measured the gap this file closes.

CISA's own guidance names the product families to worry about: "load balancers,
firewalls, routers, and virtual private network (VPN) gateways" in the joint
CISA/FBI/NCSC fact sheet, and a wider set — switches, wireless access points,
network security appliances, IoT edge devices — in the directive's own
definition. Sixteen vendors were checked against their own pages. This file
records the outcome per vendor, so the next pass starts from decisions rather
than from a fresh search.

## Summary

| Vendor | Verdict | Why |
| --- | --- | --- |
| **WatchGuard** | **Deterministic — published** | 170 products, day precision, one page. `deterministic-watchguard` |
| **Palo Alto Networks** | **Deterministic — published** | 34 SKUs from the per-series end-of-life tables. `deterministic-paloalto` |
| **Check Point** | **Deterministic — published** | 220 appliances from the lifecycle page, plus a 9-table date grammar. `deterministic-checkpoint-appliances` |
| **Barracuda** | **Deterministic — published** | 120 appliances across all four dated product spaces. `deterministic-barracuda` |
| **Extreme Networks** | **Deterministic — published** | 7,846 products from the vendor's two XLSX extracts. `deterministic-extreme` |
| **NETGEAR** | **Deterministic — published (rendered)** | 9,405 item numbers from the global EoS page, read through the opt-in rendering profile because the list is client-rendered — 0 dated rows in ~480 KB of server HTML. `deterministic-netgear` |
| **Brocade / Broadcom** | Deterministic, additive | 98 records exist with community-catalog dates; the vendor's own dates are not yet used |
| **Citrix NetScaler** | Already covered | `deterministic-netscaler` in `engine/netscaler.py` |
| **Aruba / HPE networking** | Researched | Vendor's consolidated list frozen at 2020-05-06; live data behind a JS app |
| **Sophos** | Researched | Policy pages are fetchable; every dated appliance table is WAF- or SPA-gated |
| **Fortinet** | Absent | Lifecycle tool is behind a login; no anonymous endpoint found |
| **F5** | Absent | Lifecycle matrix is behind a login |
| **Ivanti** | Absent | Per-product notices are JS-only; the policy states durations, not dates |
| **MikroTik** | Absent — vendor publishes no dated lifecycle | Only an undated "Long-term" channel statement |
| **SonicWall** | Absent | Lifecycle tables blocked by a WAF on every path from this network |

## What shipped

**WatchGuard** — `https://www.watchguard.com/wgrd-trust-center/end-of-life-policy`,
verifier `deterministic-watchguard`, report `watchguard-import.json`, 170
products across five families (Firebox, access points, AuthPoint, Datablink, XCS).
`End of Sale (EOS)` becomes `eos` and `End of Life (EOL)` becomes `eol`, in
WatchGuard's own words: the last date a partner may purchase, and the conclusion
of development and support. `ga` and `eossec` are null because the page states
neither a release date nor an engineering-end or security-support column.

Two properties of that page are worth carrying to any other vendor collector
here:

1. **Its tables carry no `<th>` cells.** The column names are rendered as a line
   of page text above each table. The collector therefore requires that
   declaration verbatim before reading a single row, and refuses any table whose
   row width disagrees with it — a dropped or reordered column is a refusal, not
   a shifted date.
2. **Its endpoint-security and security-services tables declare different column
   sets** (five columns with a second product column, three with no migration
   path). None of them is read, and each is named in the report with its shape,
   so the page's full content is accounted for rather than silently skipped.

**Extreme Networks** — the two spreadsheet extracts the vendor links from
`https://www.extremenetworks.com/support/end-of-sale-and-end-of-support-products/`,
verifier `deterministic-extreme`, report `extreme-import.json`, 7,846 products:
1,779 from the EOS extract and 6,067 from the EOSL extract, sharing no part
number between them — two different cuts of the catalog, and the vendor states no
membership rule for either, so both are reported and neither is characterised. `EOS date` becomes `eos` and `EOSL date` becomes `eol` in
the vendor's own definitions — the last date a product is available for sale,
and the last date to receive service and support from the vendor's technical
assistance team. Nothing is derived: the same index page states a five-year
support window from the end of sale for hardware, and the collector applies it
nowhere.

Three properties of those files are worth carrying to any future spreadsheet
source:

1. **The dates are Excel serials, and the vendor documents no encoding.** The
   reader is therefore explicit rather than lenient: a blank or zero cell is
   absent, a serial at or below 59 is refused because Excel's 1900 epoch cannot
   distinguish those days, a serial resolving outside 1990-2100 is refused
   rather than published, and a non-numeric cell is refused. Each record keeps
   the raw serial beside the day read, so a future re-derivation can be checked
   against the vendor's own bytes.
2. **`EOSM` is published and never mapped.** It is the date firmware and
   applications stop receiving maintenance releases — a maintenance window, not
   a stated security-support end — so `eossec` is null everywhere and the cell
   travels verbatim with a note saying why.
3. **The file's only version signal is its own `Run date` cell** ("Run date
   December 16, 2025" on the live extracts). It is required, and a sheet that
   states none refuses the run — a spreadsheet that reshapes usually re-dates
   itself first.

The file also contradicts itself about identity: it states `RPS9DC-I` and
`RPS9DC+I`, which are different hardware that slugifies identically, and one
product twice with two spellings (`SALSA-Ent-edition-XL` and
`SALSA-Ent-edition XL`). Nothing is merged — fusing two real SKUs would be worse
than publishing one product twice — so colliding part numbers take a digest of
their exact spelling and the group is named in the report for a human.

**NETGEAR** — published through the opt-in rendering profile; the evidence that
a browser is required is in `netgear-eos-no-go.md`. Its global
End-of-Service list is a client-rendered application: 200 and roughly 480 KB of
markup with zero dates and zero table cells, confirmed on all three lifecycle
URLs the sitemap lists. Rendered, it carries **68 category tables and 9,405 SKU
rows** with per-item dates, which is what the collector now publishes.

Two decisions the rendered page forced, both from the vendor's own words. The
page states **no column names at all** — no caption, no header row, no
`data-title`, no `aria-label` — and each row is five bare cells, so `eol` is the
date in the row's own `DD-MMM-YYYY` sentence, not either date cell; the cell
beside it is verified against that sentence on every dated row, in either order,
because `9/12/2013` is 9 December on one row and 12 September on another. And the
record is per **item number**, because the page's own policy says "the last sale
date may be limited to a particular SKU in an identified country or region" —
and 783 of 1,273 dated models have item numbers that disagree on the date.

## Why a vendor with no record is not a no-go

Two of the four "absent" verdicts are about *access*, not about data. Fortinet's
lifecycle tool states "End of Order (EOO) dates, End of Support (EOS) dates, and
Last Service Extension Date (LSED)" and can export them — behind a login, which
this repository does not scrape. SonicWall's tables exist and are
vendor-operated; the host answers every request from this network with a WAF
interstitial, exactly as SolarWinds' support host answers with 403.

Neither is a statement that the data does not exist. Both are statements that a
browser-capable fetcher, or a person reading the page, would get it. That is
the researched tier: a human read with a verbatim quote, URL, contributor and
research date.

## MikroTik is the real negative

MikroTik publishes a "Long-term" release channel with no date attached, and no
per-version lifecycle of any kind. An undated support tier is not a lifecycle
date, so there is nothing to record and nothing to derive. Recorded here so it is
not re-researched.

## Coverage after WatchGuard

Against the CISA-prioritized classes, measured from the committed catalog:

| Device class | Records | With an end-of-life date |
| --- | --- | --- |
| Firewalls and network security appliances | 170 | 170 |
| VPN gateways and remote access | 772 | 666 |
| Routers and switches | 4,271 | 3,780 |
| Wireless access points | 772 | 666 |
| Load balancers and application delivery controllers | 0 | 0 |
| Email and web security appliances | 0 | 0 |

The two empty classes are the next work, and both have vendors that publish
their own dates: F5 and Citrix (already covered as software) for load balancers;
Proofpoint, Barracuda, Sophos and SonicWall for email and web security — of
which Barracuda is fetchable today and the other three are access-blocked or
SPA-rendered.

## What would change a verdict

* A browser-capable fetcher, for the WAF-blocked and SPA-rendered vendors.
* A login, for Fortinet and F5 — which this repository does not use.
* A vendor publishing a consolidated machine-readable feed, which would remove
  the per-vendor parser work entirely.
