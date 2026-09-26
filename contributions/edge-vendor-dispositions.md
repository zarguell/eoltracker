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
| **Palo Alto Networks** | Deterministic — not yet built | Public per-series end-of-life tables |
| **Check Point** | Deterministic — not yet built | One page, dozens of tables, month precision mostly |
| **Barracuda** | Deterministic — not yet built | One Confluence page per product space, ISO day precision |
| **Extreme Networks** | Deterministic — not yet built | Vendor-hosted XLSX extracts |
| **NETGEAR** | Deterministic — not yet built | One monthly-stamped PDF table |
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
