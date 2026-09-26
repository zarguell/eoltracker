# Marrying end-of-life data to internet exposure: feasibility and decision

Recorded 2026-09-26. The question: can this catalog join its vendor-stated
end-of-life dates to internet-scan data and publish a "this many are on the
internet" tracker, and can that start from a free API key?

**Short answer: yes, with one service, for one number per product, under
conditions. No, not for the thing most people picture, and no, not on the
service with the better data.** The three findings that decide it, in order of
how much they matter:

1. **Censys cannot be used at all.** Its free tier has no search API, and its
   terms prohibit exactly this use — including the free research route, which
   states that "Repackaging and redistributing Censys data is not a valid
   research access use case."
2. **Shodan can produce the number free.** A free account with no card can call
   `GET /shodan/host/count`, which Shodan's own documentation says "does not
   consume query credits". Attribution to Shodan is required.
3. **The number is weaker than it looks, and version-level counts are not
   defensible at all.** Shodan counts *banner records over a rolling 30-day
   index*, its crawlers "don't do sweeps of IP ranges the same way a network
   scanner would", its `version` field is optional and parsed from an advertised
   banner, and a patched device routinely reports an older version. Shodan
   disclaims that "any information obtained by you as a result of your use of
   the services will be accurate or reliable".

## What you can get today, per service

### Shodan — the only viable path

| Fact | Evidence |
| --- | --- |
| A free API key exists | "To use the API you need to have an API key, which you can get for free by creating a Shodan account." (developer.shodan.io/api/requirements) |
| **Counting is free** | "As a result this method does not consume query credits." (developer.shodan.io/api, `/shodan/host/count`) |
| A free key can count | "Everything on this page can be done with a free API key" (help.shodan.io, the `stats`/facet path) |
| Enumerating is not free | "1 query credit lets you download 100 results"; Membership's 100 credits/month "means that you can download at least 10,000 results every month" (help.shodan.io) |
| Attribution is required | "if any Shodan information or materials are included with any of Your materials, You must attribute such usage to Shodan" (terms §6.7) |
| Accuracy is disclaimed | "any information obtained by you as a result of your use of the services will be accurate or reliable" — as something Shodan does *not* represent or warrant (terms §15.3(c)) |
| Redistribution is restricted | "You may not modify, rent, lease, loan, sell, distribute or create derivative works based on this Content (either in whole or in part) unless you have been specifically told that you may do so by SHODAN ... in a separate agreement" (terms §9.2) |
| Integration with attribution is blessed | "Can we use the API to build products? Yes, you can integrate the API in your products as long as the data is attributed to Shodan" (account.shodan.io/billing) |
| Rate limit | "All API plans are subject to a rate limit of 1 request per second" |

The workhorse is one endpoint:

```
GET https://api.shodan.io/shodan/host/count
      ?key=YOUR_KEY
      &query=product:FortiOS
      &facets=country:20,org:20
```

which returns `{"matches": [], "facets": {...}, "total": N}` — a count, no host
records, and no credit cost. `tools/exposure_count.py` in this repository calls
exactly that, and the decision below is what it enforces.

**InternetDB** is the one keyless Shodan surface, and it is not a way in: its
OpenAPI spec declares a single path, `/{ip}`, and it "doesn't return any
banners" and is "updated once a week". There is no search endpoint, no `total`,
and no product or version field. Confirmed by hand: `internetdb.shodan.io/8.8.8.8`
returns ports, hostnames and tags, and nothing countable. It is also "free for
non-commercial use", which a published site is not.

### Censys — excluded on licence, before measurement

The technical limits would already be fatal, but the licence decides it:

* **Free tier has no search API.** "Censys Free users only have access to host,
  web property, and certificate lookup ... endpoints" (docs.censys.com,
  get-started). 100 credits a month at 5 per standard query is about twenty
  queries; results are capped at one page of 100; regex — the tool for "any EOL
  version of X" — is Starter+.
* **Censys Data is confidential, including where it is public.** "any elements
  of Censys Data that may be available to the public shall not diminish the
  confidentiality of Censys Data" (Terms §5.1).
* **A published catalogue is the prohibited use.** "use the Service or any
  Censys Property ... to create any service, software, product or system" and
  providing data "as a stand-alone product, service, application, file, report
  or database" (Terms §3.1(a)–(b)).
* **Erase on request.** "Promptly upon the disclosing party's request at any
  time, the receiving party shall return all of the disclosing party's tangible
  Confidential Information, permanently erase all ... and destroy all
  information, records, copies, summaries, analyses and materials developed
  therefrom" (Terms §5.2).
* **The free research route refuses this use case by name.** "Repackaging and
  redistributing Censys data is not a valid research access use case."
* **The lifecycle join is enterprise-only anyway.** `host.services.software.life_cycle`
  is "available to enterprise customers", as is `software.confidence`.

So the strongest dataset for this idea is also the one whose terms forbid
publishing it, and Censys already sells the same join as a paid field.

## What the number actually measures

This matters more than the licence, because it decides whether the number is
worth publishing at all.

**It is a scan sample, not a census.** Shodan's own methodology: "data is not
based on point-in-time scans but rather an aggregate view of the active IPs
during a month", and its search "will look at the data collected within the past
30 days". Censys's own self-evaluation of Shodan (SIGCOMM '25) puts Shodan's
estimated accuracy at 68% and its coverage of services across all 65,535 ports
at about 10%, against Censys's own 62% and 92%. Censys also notes the port-range
effect directly: "Censys sees 98% of IPv4 services on the top 10 ports, 97% of
the top 100, and 62% of services across all 65K ports" — so a device whose
management interface sits on 8291 is largely invisible, and Shodan is far worse.

**It is biased by geography and vantage point.** "Censys is unable to reach 27%
of hosts in South Africa and 43% of hosts in Bangladesh" (multi-perspective
scan study). Academic measurements put single-probe misses at 1.6–18.2% by
protocol.

**It is biased by what is behind NAT and in the cloud.** A residential FortiGate
behind carrier-grade NAT is not in any scan dataset; a cloud instance with the
same software is over-represented.

**It over-counts hosts that no longer exist and under-counts quiet ones.**
Censys evicts a service 72 hours after it stops responding; Shodan's index
retains a month.

**Most importantly: the version is not evidence of end of life.** Shodan's
Datapedia marks `version` as an *optional* banner property, parsed from the
advertised string. Independent work on banner-derived version detection records
that "version information may not be accurate ... since some of them may apply
a backport version, i.e., a new patched software based on an old version" — a
patched appliance reporting an end-of-life version is routine, and that is
precisely the claim a lifecycle catalog would be making. Shodan's own banner
fields have been measured as unreliable in the same way: "Nuclei finds 95% of
Shodan's banner-based detections to be false positives".

**Per family, the count measures very different things.**

| Family | What a scan can actually see | What the count would measure |
| --- | --- | --- |
| Ivanti Connect Secure | Exposed portals, with a version in the page | Measured precedent: 26,095 unique exposed hosts, Jan 2024 |
| MikroTik RouterOS | Devices leaking management protocols | Measured: 38,134 responsive devices, of which 1.7% of router addresses answered at all |
| Juniper Junos | Only with J-Web exposed | 4,065 banner-labelled devices measured |
| Cisco IOS / ASA | SSH/Telnet/SNMP banners, or a published portal | Routers that leak a management interface — a small, non-random subset |
| Fortinet, PAN-OS, F5, Check Point, Aruba, SonicWall, Extreme, NETGEAR | Admin UI, portal, or nothing | Nothing reliable at product level; a version-pinned count would be fiction |

## The decision

**Build a Shodan product-level exposure layer, if and only if Shodan confirms
in writing that an attributed aggregate count may be published. Nothing ships
until it does.** The reasoning:

* The licence is genuinely ambiguous in the place that matters. The pricing
  page blesses building products with attribution; the terms forbid
  distributing "Content" without a separate agreement. A single attributed
  integer is the lowest-risk artifact and is almost certainly what a free key
  is for, but "almost certainly" is not the standard this repository holds
  itself to, and a wrong reading is a takedown of the site, not a bug.
* The measurement only supports one number per product, with its basis printed
  beside it. Anything finer is not supportable.
* The **version-pinned** case is refused outright, in code, not only in prose.

### Rules any implementation must hold

1. **Product-level only.** No version-pinned counts. `tools/exposure_count.py`
   refuses them unless explicitly overridden.
2. **Aggregates only.** No IP addresses, no hostnames, no banners, no ASN or
   organisation lists, no per-host anything. Shodan's terms forbid
   redistributing that content, and a published host list is a targeting list
   regardless of the licence.
3. **Attribution and basis travel with every number**: "Data: Shodan", the
   literal query, the retrieval timestamp, and the standing caveat that this is
   a 30-day banner-record sample rather than a device census.
4. **A separate layer, never inside a record.** An exposure count is an
   observation at a time about instances worldwide. A record's milestones are
   vendor-stated facts with per-release provenance. Mixing them would make a
   changing scan number look like a lifecycle change, and would put a claim in a
   place where the catalog's rules say only a vendor statement belongs. The
   natural shape is a `/v1/exposure.json` endpoint and a small, heavily-caveated
   panel on the priority page — not a field on a product, not a feed event, and
   not in OpenEoX.
5. **Say what it is for.** A global count is context for why a date matters. It
   is *not* a statement about any reader's own estate, and the page must say so,
   because the natural misreading is "this many of yours".

### What is deliberately not built here

* No collector, no registry entry, no site section, no data. Those need a key
  and a written permission, and shipping a feature pointed at an unwritten
  licence is the failure mode this repository's rules exist to prevent.
* `tools/exposure_count.py` is a probe: it makes the number checkable by anyone
  with a free key, in five minutes, and its shape is the shape a future
  `/v1/exposure.json` entry would take.

## The five-minute path to a real number

```
1. Register a free Shodan account      https://account.shodan.io/register
2. Copy the API key                    https://account.shodan.io/
3. export SHODAN_API_KEY=...            # no card, and counting costs no credits
4. python3 tools/exposure_count.py --facets country:20,org:20 product:FortiOS
5. python3 tools/exposure_count.py --facets country:20 product:"MikroTik RouterOS"
```

Step 5's product names are the vendor's own words, not ours; a query that pins a
version is refused unless `--allow-version` is passed, and the reason is printed
when it is.

## What would change the decision

* A written answer from Shodan permitting an attributed aggregate count to be
  published and refreshed. That unblocks the feature in full.
* Shodan publishing a stated coverage figure per product class, which would let
  a number carry an error bar instead of a caveat.
* A vendor publishing its own exposure telemetry — several do, for their own
  customers — which is the only version of this number that is about a reader's
  estate rather than the world's.
