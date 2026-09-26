# Kiteworks subsidiary brands — scope decision and per-brand findings (#125)

Recorded 2026-09-26. Scope: whether the brands Kiteworks enumerates as its
subsidiaries belong inside a Kiteworks-branded record or require separate,
per-brand investigations.

## Scope decision

**Each subsidiary is its own vendor scope; none is recorded under Kiteworks.**
Kiteworks names the brands in its own press material, and that is enough to
prove corporate ownership — it is not enough to attribute a lifecycle date. A
subsidiary that publishes a lifecycle publishes it under its own identity, with
its own product names and version lines. Storing such a date under a
Kiteworks-branded record would misattribute the vendor, which AGENTS.md rule 6
and the cross-vendor attribution convention both forbid.

The subsidiary brands are: **Zivver, DRACOON, totemo, ownCloud, WAMNET,
Maytech, Bonfy.ai, 123FormBuilder.**

`ownCloud` is handled in its own artifact,
`contributions/owncloud-attribution-decision.md` (#126), because it is the one
brand with a genuine dated lifecycle table and a separate attribution question.

## Vendor enumeration (the ownership evidence, not lifecycle evidence)

[Kiteworks precautionary shutdown advisory](https://www.kiteworks.com/company/press-releases/kiteworks-precautionary-shutdown-advisory/),
public static HTML, 2026-09-25:

> This threat does not affect other Kiteworks subsidiaries, including Zivver,
> DRACOON, totemo, ownCloud, WAMNET, Maytech, Bonfy.ai, and 123FormBuilder.

This sentence establishes ownership only. It states no lifecycle fact for any
brand, and it is the reason a Kiteworks-branded record must not absorb one.

## Per-brand findings

All pages were checked on 2026-09-26. "No public lifecycle statement found"
means every page listed was fetched and returned without an EOL, end-of-support,
lifecycle-table or supported-version statement — it is a statement about the
pages checked, not proof that none exists anywhere.

### Zivver

| URL | Access shape | Result |
| --- | --- | --- |
| https://www.zivver.com/ | public HTML (200) | no EOL / lifecycle / supported-version statement |
| https://www.zivver.com/en/support/ | public HTML (**404**) | no support page at this path |
| https://support.zivver.com/ | public HTML (200) | help-centre shell; no lifecycle statement |

**Finding:** no public lifecycle statement found on the checked pages. No
version support matrix, EOL or end-of-support page was located.

### DRACOON

| URL | Access shape | Result |
| --- | --- | --- |
| https://www.dracoon.com/ | public HTML (200) | no lifecycle keyword in the page body |
| https://www.dracoon.com/en/support | public HTML (**404**) | no support page at this path |
| https://doc.dracoon.com/ | **does not resolve** (ENOTFOUND) | no documentation host at this name |
| https://page.dracoon.com/de/web-session/server-eol | public HTML (**404**) | the most promising lead — an apparent server EOL page surfaced by search — is not retrievable at this path (recorded as 404, not as absence of the content) |

**Finding:** no public lifecycle statement found. DRACOON is simultaneously the
most promising lead and the least verified brand: a page whose path names
`server-eol` exists in search results but returns 404 on fetch. It must be
re-probed under other paths/locales before any conclusion is drawn.

### totemo

| URL | Access shape | Result |
| --- | --- | --- |
| https://www.totemo.com/ | fetch failed — **certificate has expired**; direct fetch returns a near-empty stub (~1.9 KB) for every path | no retrievable lifecycle statement |

**Finding:** no public lifecycle statement could be read. The site is currently
unreachable through a validating client (expired certificate), and the stub
returned does not vary by path, so no honest quote can be recorded either way.

### WAMNET

| URL | Access shape | Result |
| --- | --- | --- |
| https://www.wamnet.jp/ | public HTML (200) | no EOL / lifecycle / supported-version statement |
| https://www.wamnet.jp/support/ | public HTML (200) | same shell; no lifecycle statement |
| https://www.wamnet.jp/lifecycle/ | public HTML (**404**) | no lifecycle page at this path |

**Finding:** no public lifecycle statement found on the checked pages.

### Maytech

| URL | Access shape | Result |
| --- | --- | --- |
| https://www.maytech.net/ | public HTML (200) | the only "lifecycle" hit is a **product feature** — "User lifecycle management" — not a product lifecycle statement |
| https://www.maytech.net/support/ | public HTML (**404**) | no support page at this path |
| https://www.maytech.net/lifecycle | public HTML (**404**) | no lifecycle page at this path |

**Finding:** no public lifecycle statement found. The page's "lifecycle" wording
describes a user-provisioning feature and must not be read as lifecycle
coverage.

### Bonfy.ai

| URL | Access shape | Result |
| --- | --- | --- |
| https://www.bonfy.ai/ | public HTML (200) | the "eol" hit is a **false positive inside an inlined base64 blob**, not page text |
| https://www.bonfy.ai/support | public HTML (**404**) | no support page at this path |
| https://www.bonfy.ai/lifecycle | public HTML (**404**) | no lifecycle page at this path |

**Finding:** no public lifecycle statement found. The apparent keyword hit is an
artifact of encoded data and is not evidence.

### 123FormBuilder

| URL | Access shape | Result |
| --- | --- | --- |
| https://www.123formbuilder.com/ | public HTML (200) | no EOL / lifecycle / supported-version statement |
| https://www.123formbuilder.com/support/ | public HTML (200) | support/help shell; no lifecycle statement |
| https://www.123formbuilder.com/lifecycle/ | public HTML (**404**) | no lifecycle page at this path |

**Finding:** no public lifecycle statement found on the checked pages.

## Acceptance conditions recorded

- No brand record is created without a vendor-published date from that brand's
  own site. None of the checked brands yielded one, so no contribution or
  `data/` record is added by this scope.
- Each record, if ever created, must set `vendor` to the brand's own branding,
  never to Kiteworks.
- DRACOON and totemo are the two brands whose pages could not be read
  (404 at the EOL-shaped path; expired certificate). Reopen those two first.

## Reopen condition

Reopen a brand when that brand publishes its own lifecycle statement (a dated
EOL/EOS/security-support end, or an explicit duration or dated release trigger)
at a public URL. Re-probe DRACOON under alternate paths/locales and totemo once
its certificate is renewed.
