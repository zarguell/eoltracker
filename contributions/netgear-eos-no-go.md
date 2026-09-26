# NETGEAR product lifecycle — no-go for a deterministic collector

**Disposition:** no-go for a plain-HTTP deterministic collector, as of 2026-09-26.
**Verdict tier:** absent. Nothing is published for NETGEAR, and this file is the
evidence for that absence rather than a placeholder record.

NETGEAR publishes a global End-of-Service product list. It is the only one of
the five open edge vendors in #150 whose dates are *not* reachable by an honest
plain-HTTP client, and the reason is rendering, not access control: the page
returns HTTP 200 and roughly 480 KB of markup containing no dates at all.

## What was fetched, and what came back

Each verdict below was confirmed twice — once directly, and (for the global
page) against a 2026-09-17 Wayback capture of the same URL.

| URL | Status | Dated rows in the server HTML |
| --- | --- | --- |
| `https://www.netgear.com/about/eos/` | 200, 479,462 bytes | **none** — 0 date-like strings, 0 `<td>` cells, neither "Item Number" nor "EOS Date" appears anywhere in the body |
| `https://www.netgear.com/about/end-of-service/routers-eos/` | 200, 496,923 bytes | **none** |
| `https://www.netgear.com/about/end-of-service/mesh-eos/` | 200, 492,663 bytes | **none** |
| `https://www.netgear.com/au/about/eos/` | 200, 487,047 bytes | 45 dates, 96 `<td>` cells, headers `Item Number \| EOS Date` |
| `https://www.netgear.com/sitemap.xml` | 200, 138,199 bytes | lists the three EoS URLs above, so the sitemap is the complete set of lifecycle URLs the vendor publishes |
| `https://www.netgear.com/robots.txt` | 200, 2,122 bytes | a real, readable ruleset; nothing here disallows the EoS pages |

## Why this is a no-go, on three independent grounds

**1. The data that matters is client-rendered.** The global page is a
Salesforce/Mobify single-page application: the response is the application
shell, and the product list is injected after load. There is nothing to parse,
so a collector would have to run JavaScript. That is precisely the opt-in
browser-fetch path tracked in #151 (with #154 as its implementation issue), and
it is a decision this repository does not make by default: it trades
politeness and simplicity of reach for browser emulation, and it is the user's
call, not a collector's default.

**2. The one server-rendered table is the wrong scope, twice over.** The AU
locale is the only NETGEAR EoS page whose dates are in the HTML, and it is
narrower than the catalog on every axis:

- *Geography.* Its part numbers are AU-region SKUs — `A6150-10000S`,
  `A7500-100PAS`, `A8000-100PAS`, `A9000-10000S`, `EAX12-100AUS`,
  `EAX15-200AUS`, `EAX17-100AUS` — which are not the US or global part numbers
  the rest of this catalog names.
- *Category.* The tables cover Mobile Hotspot, Gateway Modem and WiFi Router:
  consumer SKUs. The business hardware CISA prioritised — firewalls, managed
  switches, VPN gateways, wireless business access points — is absent.

**3. A blanket date is not per-product lifecycle data.** All 45 dated rows carry
the identical `09/01/2029`. Publishing that as NETGEAR's hardware end-of-life
would convert one AU region's blanket consumer-SKU date into a fact about every
NETGEAR product, which is exactly the fabrication rule 2 forbids: inferring a
date for a product because a table sits near it.

## What would change this verdict

- A **public JSON endpoint** for the global EoS list that an unauthenticated GET
  returns. If one exists and carries per-SKU dates for the business catalog,
  this becomes a straightforward deterministic collector and this file should be
  replaced by one. (The Mobify storefront API is the likely mechanism; it needs
  a store id and usually a token, so it is an access decision as much as a
  parsing one.)
- The user's **opt-in approval of the browser-fetch path** in #151/#154. That
  would unblock NETGEAR and five CISA-prioritised vendors with no data of their
  own (Fortinet, F5, SonicWall, Sophos, Ivanti, Aruba) in one change, which makes
  it the highest-leverage unblock in the tracker.

Until one of those happens, NETGEAR stays absent, and this file is the evidence.

## Correction to an earlier research note

An earlier note in `edge-vendor-dispositions.md` described NETGEAR as "a single
PDF, monthly-stamped, with no column legend". All three particulars are wrong:
NETGEAR publishes **HTML, not a PDF**; there is **no monthly stamp** anywhere in
the response; and there **is** a legend for the EOS date (`Item Number` and
`EOS Date` are the only column headers on the AU page). The row has been
corrected there.
