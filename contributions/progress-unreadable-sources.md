# Progress sources an agent cannot read — scoping note

Recorded 2026-09-26, against issue #134. This is a scoping note, not work: it
exists so the next person knows exactly what is blocked and what unblocks it,
without re-walking the same dead ends.

## The one-line answer

Two Progress-owned sources are public and carry per-release lifecycle dates, but
serve their content only to a browser. Nothing may be published from them until
a human reads the page in a browser and contributes the rows with a verbatim
quote, a source URL, a contributor and a research date.

| Family | URL | State |
| --- | --- | --- |
| MOVEit / WS_FTP / MOVEit Transfer / MOVEit Automation | `https://community.progress.com/s/life-cycle-file-transfer` | Public, JS-only. Body is `Loading`. |
| MarkLogic Server | `https://community.progress.com/s/products/marklogic/supported-versions` | Public, JS-only. Body is `Loading`. |

Also checked and also `Loading`:
`community.progress.com/s/products/moveit/product-lifecycle`,
`community.progress.com/s/article/000047078`,
`progress.my.site.com/s/article/End-of-Life`,
`progress.my.site.com/s/article/MOVEit-Analytics-End-of-Life-EOL`.

## Why an agent cannot read them

Both are Salesforce Experience Cloud. Content is delivered by a POST to
`/s/sfsites/aura`; there is no public GET endpoint that returns the article
body. The Zendesk-style help-centre search endpoint 404s. Every attempt through
`engine.net` and through a plain fetch returns the shell.

## What is NOT blocked, and already ships

The six families Progress renders as static, server-side tables are implemented
in `engine/progress.py` and published today:

| Family | Records | Source |
| --- | --- | --- |
| OpenEdge, OpenEdge Pro2 | `openedge`, `openedge-pro2` | `docs.progress.com/bundle/openedge-life-cycle` |
| Corticon, Corticon.js | `corticon`, `corticon-js` | `docs.progress.com/bundle/corticon-life-cycle`, `.../corticon-js-life-cycle` |
| WhatsUp Gold | `whatsup-gold` | `docs.progress.com/bundle/whatsup-gold-life-cycle` |
| Sitefinity | `sitefinity` | `www.progress.com/support/sitefinity-lifecycle-policy` |

## The unblock, stated so it can be checked

1. Open the two URLs above in a browser, without a Progress account.
2. Report whether the page renders without a login, and whether it states
   per-release dates (not just support tiers).
3. If it does, contribute the rows: exact dates as stated, the verbatim sentence
   that states them, the URL, the contributor and the research date. A
   contribution may not overwrite or shadow a deterministic record; there is
   none for MOVEit or MarkLogic today, so a researched record is admissible.
4. If the page is login-gated, record that instead and the family joins the
   no-go list in `progress-no-go-dispositions.md`.

There is also a `https://www.progress.com/support/end-of-life` style vendor-wide
page to look for first: the natural candidate,
`https://www.progress.com/support/policies/end-of-life`, returns HTTP 404, so
Progress publishes no vendor-wide EOL page and coverage is necessarily
per-family.
