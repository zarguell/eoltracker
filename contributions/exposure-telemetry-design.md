# Marrying end-of-life data to internet exposure: feasibility and decision

Recorded 2026-09-26. The question: can this catalog join its vendor-stated
end-of-life dates to internet-scan data and publish a "this many are on the
internet" tracker, and can that start from a free API key?

**Short answer: yes — as a *presence* signal, per product, tracked over time,
from Shodan's free count endpoint. The thing that does not work is pinning a
version, and measuring it is what shows why: not one of nine model names from
this repository's own catalog appears in any page Shodan indexes. Censys remains
excluded, on its terms rather than on its limits. The three findings that decide it, in order of
how much they matter:

1. **Censys cannot be used at all.** Its free tier has no search API, and its
   terms prohibit exactly this use — including the free research route, which
   states that "Repackaging and redistributing Censys data is not a valid
   research access use case."
2. **Shodan can produce the number free.** A free account with no card can call
   `GET /shodan/host/count`, which Shodan's own documentation says "does not
   consume query credits". Attribution to Shodan is required.
3. **A version-pinned count is not merely imprecise; it is usually empty.** Shodan
   counts *banner records over a rolling 30-day index*, its crawlers "don't do
   sweeps of IP ranges the same way a network scanner would", and its `version`
   field is optional and parsed from an advertised banner. Measured: the version
   facet is empty for three of the four families that have a product string, and
   a version-pinned query returns zero for a release that plainly exists.

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

## The decision, revised: presence, not version

The goal is smaller than "how many EOL devices are exposed", and the smaller goal
is the one the data supports. **Publish, per product, how many internet-exposed
instances Shodan observes advertising that product, tracked over time** — a
prevalence and public-facing signal, not a lifecycle claim. Where a specific
fingerprint genuinely pins a version, publish that too; it is never the default,
because measurement says it cannot be.

### What the measurements changed

A free key was used on 2026-09-26, and the evidence settled four things that the
documentation alone left open.

**1. Version fingerprinting does not work, and the reason is not subtle.** Not one
of nine model names taken from this repository's own 170 published WatchGuard
products appears anywhere in the pages Shodan indexes — `http.html:"Firebox T15"`,
`http.title:"WatchGuard AP225W"` and seven others all return **zero**. The
`version` banner field is empty for the three families that do have a product
string, and for the fourth (Citrix NetScaler) it holds firmware *build* strings
such as `13.1-45.64` rather than product versions. So a version-pinned query
returns zero for products that plainly exist, which is the worst possible failure
mode: zero looks like a finding.

What *is* measurable is the favicon hash. Shodan indexes it, facets on it, and the
histograms cluster hard — for the WatchGuard admin UI, one favicon hash covers 64
of 132 hosts with a long tail behind it; for a wider WatchGuard seed, one hash
covers 3,045 of 7,204. So a hash isolates a **cohort of hosts running the same
rendered asset**. What it cannot do is say *which model* that cohort is: mapping
a hash to a model needs ground truth this catalog does not have, and a hash
carries no name to look up. Published as "distinct exposed configurations
observed", never as a model or a version.

**2. Keyword seeds are fiction by an order of magnitude.** `http.html:"WatchGuard"`
returns 7,204 against a `product:WatchGuard` count of 731 — a 9.9× overstatement.
`http.html:"Check Point"` returns 251,678, of which the largest single facet is an
unrelated vendor's product and the next is a source-control tool that merely
shares the vendor's name. The product-facet string is the only defensible unit.

**3. Some families have no product string at all, and zero is not the answer.**
`product:FortiOS` and `product:PAN-OS` return zero because Shodan's fingerprints
never emit those strings — the nearest Fortinet value is a *model* name. A
published "0" for either would be a confident falsehood, so the design now
separates **uncounted** from **zero** as a first-class state, and they must never
share a code path.

**4. A count is stable enough to track.** Five samples a minute apart for three
products returned identical values to the digit (spread 0). Across a half-hour
window the same product moved by about 150 records out of 198,000 — roughly
0.08%. So the index is a stable quantity with a small drift, not a random number,
and a weekly series can carry a real trend with an honest noise floor rather than
noise masquerading as change.

### The artefact this implies

A **`/v1/exposure.json` endpoint and a small panel on `/why/`**, one entry per
product, each carrying:

* the verified Shodan product string, the literal query, and the retrieval
  timestamp;
* the count, labelled in the unit Shodan's own terms require: *banner records
  observed, not devices*;
* `state`: `observed` with a number, or `uncounted` with the reason (no product
  string exists, or the query could not be run);
* the series: previous samples with their timestamps, so a reader sees the trend
  and the noise rather than one number pretending to be precise;
* cohort detail where a favicon fingerprint is defensible — the number of
  distinct exposed configurations, named as such;
* the standing caveat, and "Data: Shodan" with a link.

Five rules, revised from the evidence:

1. **Presence only, at product level.** No version-pinned figure is ever
   published. Rule 1 of the original decision, kept, and now justified by
   measurement rather than caution.
2. **Aggregates only.** No addresses, hostnames, banners, ASNs or organisation
   lists. Shodan's terms forbid redistributing that content, and a published host
   list is a targeting list whatever the licence says.
3. **A family with no verified product string is `uncounted`, never `0`.**
4. **Separate layer, never inside a record.** A presence count is an observation at
   a time about instances worldwide; a record's milestones are vendor-stated
   facts with per-release provenance. Keeping them apart is what stops a changing
   scan number from reading as a lifecycle change.
5. **Say what it is for.** A global count is context for why a date matters. It is
   not a statement about any reader's own estate, and the panel must say so,
   because the natural misreading is "this many of yours".

### What is not built, and why it still is not built

The goal got smaller, not larger, in one respect: there is now no claim to
compute, so there is no risk of a wrong lifecycle date — but there is still a
licence question, because the artefact is a published Shodan-derived aggregate.
The same written permission is required, and it is a smaller and more obviously
ordinary request than before: *may we publish attributed product-level counts,
refreshed weekly?* Nothing here needs Shodan's banner data, their enrichment
fields, or their bulk product.

## What a real key actually returned

A free Shodan account was used to run the probe on 2026-09-26, so the questions
above have measured answers rather than only documented ones. The raw counts are
deliberately **not** committed here: publishing Shodan aggregates is the step
this document says needs written permission, and holding that line on my own
output is the first test of it. What follows is the method and the verdicts,
which are what change the design.

**1. The vendor's product name is usually not a value in the index.** The obvious
queries for the two most-exploited families named in CISA's guidance —
`product:FortiOS` and `product:PAN-OS` — return **zero**, and zero is not a
finding, it is a missing vocabulary. The nearest strings Shodan holds for
Fortinet are *model* names (`Fortinet FortiGate-60F`), not the product family, so
"how many FortiOS devices are exposed" is not a question this dataset can answer
as asked. A catalogue that published either the zero or the naive alternative
would be stating a falsehood with a timestamp on it.

**2. A keyword query is off by roughly an order of magnitude, in the direction
that flatters nobody.** Seeding on text that merely appears in a web page and
faceting the result by product exposes the contamination directly: for one
tracked family the seeded total is about nine times the count of that family's
own product string, and the single largest facet in the seeded result belongs to
an unrelated vendor's product, with a second large facet being a source-control
tool that shares the vendor's name. Nothing about that number is a firewall.

**3. Version-level counting is not merely imprecise — it is usually empty.** The
probe refuses version-pinned queries, and the override confirms why: for three of
the four families that a product string exists for, the `version` facet returns
**no buckets at all**, and a version-pinned query for a release that plainly
exists in the field returns **zero**. The fourth reports firmware *build* strings
rather than product versions. So a version-level end-of-life join would publish
"0" for nearly everything — the most dangerous possible output, because zero
reads as a finding rather than as a gap.

**4. The index moves while you look at it.** The same product string returned
counts differing by ~150 between runs minutes apart. That is the right size of
signal for a 30-day rolling window, and it is the reason a published figure
needs its retrieval timestamp and a refresh cadence slower than the noise.

### What this changes in the design

Rule 1 (product-level only) is confirmed as necessary rather than cautious, and
it needs a fourth clause:

5. **A family with no verified product string is reported as uncounted, never as
   zero.** "Shodan holds no product string for this vendor" is a true statement;
   "0 devices are exposed" is not, and the two must never share a code path.

And the per-family identifiability work in the design becomes a hard
prerequisite, not a nicety: a product string has to be discovered, verified
against a seed that cannot be contaminated, and reviewed — which is the same
standard every collector in this repository already applies to a source it reads.

## What would change the decision

* A written answer from Shodan permitting an attributed aggregate count to be
  published and refreshed. That unblocks the feature in full.
* Shodan publishing a stated coverage figure per product class, which would let
  a number carry an error bar instead of a caveat.
* A vendor publishing its own exposure telemetry — several do, for their own
  customers — which is the only version of this number that is about a reader's
  estate rather than the world's.
