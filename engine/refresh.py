"""Per-source refresh transactions: one source's failure never damages another's.

Each registered source refresh writes several files — its records, the catalog
manifest, and whatever sidecar that source publishes — and an upstream or disk
failure can strike after some of them are already on disk. The committed
``data/`` directory is the source of truth the site is built from, so a partial
write is not a smaller success: it is a corrupt catalog.

The transaction therefore snapshots the data directory immediately before each
source runs and restores it byte-for-byte if that source raises anything. That
one mechanism covers every partial-write shape at once (records written before
the failure, a manifest but no records, a ledger written after the records it
describes, an OSError from a full disk mid-copy), and it keeps the sources
independent by contract: the snapshot is taken per source, so a source that
succeeded keeps its results and a source that failed leaves the directory
exactly as its own predecessor left it.

Sources are passed the directory to write into, so a refresh never has to reach
into another module's global state to be pointed somewhere else.

A partial refresh is a partial catalog, and the run says so. Every source that
succeeded keeps its results — an outage at one vendor must not freeze the
others — but the *aggregate* outcome is truthful: `exit_code` is zero only when
every registered source refreshed, `freshness()` publishes the same verdict as
data, and the report names the stale slices. Internal consistency validation
cannot detect staleness (a record from last week validates exactly like today's),
so this exit code is what stops the publication workflow from shipping a
catalog whose timestamps promise more than its contents deliver.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .importer import ROOT

DATA = "data"
# Written by GitHub Actions for the run's summary page; optional everywhere else.
STEP_SUMMARY = "GITHUB_STEP_SUMMARY"


@dataclass(frozen=True)
class Outcome:
    """What one source's refresh did: the unit the CLI and workflow report."""

    id: str
    ok: bool
    error: str = ""
    detail: str = ""

    def line(self):
        """One-line report of this source's result, truthful in both directions."""
        if self.ok:
            return f"OK    {self.id}" + (f": {self.detail}" if self.detail else "")
        return f"FAIL  {self.id}: {self.error}"


def data_directory(directory=None):
    """The catalog directory a refresh reads and writes."""
    return Path(directory) if directory is not None else ROOT / DATA


def snapshot(directory):
    """Every committed file of a catalog directory, verbatim, keyed by path."""
    root = Path(directory)
    return {path: path.read_bytes() for path in sorted(root.rglob("*")) if path.is_file()}


def restore(directory, before):
    """Put a catalog directory back exactly as the snapshot found it.

    Files the failed source added are removed and files it changed or deleted
    are written back, so records, the manifest and every sidecar return to the
    committed bytes together. If restoration itself fails (for example, disk
    failure), the exception propagates and aborts the run before publication.
    """
    root = Path(directory)
    for path in sorted(root.rglob("*"), reverse=True):
        if path.is_file() and path not in before:
            path.unlink()
    for path, data in before.items():
        if not path.exists() or path.read_bytes() != data:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)


def refresh_source(source, directory=None):
    """Run one source refresh transactionally; returns its outcome."""
    root = data_directory(directory)
    before = snapshot(root)
    try:
        detail = source.run(root)
    except Exception as error:  # noqa: BLE001 - every failure must roll back
        restore(root, before)
        return Outcome(source.id, False, f"{type(error).__name__}: {error}")
    return Outcome(source.id, True, detail=detail or "")


def refresh_all(sources, directory=None):
    """Refresh every source in order; one failure never stops or corrupts another.

    The order is the registry's, and it is preserved in the returned outcomes so
    the report matches what ran. A source that fails is rolled back and the next
    source still runs: an upstream outage at one vendor must not freeze the
    others' updates. The outcomes carry the per-source truth; the aggregate
    verdict is `exit_code`/`freshness`, and it is failure when any source failed,
    so a partial refresh cannot be published as a complete one.
    """
    return [refresh_source(source, directory) for source in sources]


def failed(outcomes):
    """The outcomes that failed, in order."""
    return [outcome for outcome in outcomes if not outcome.ok]


def exit_code(outcomes):
    """Zero only when every registered source refreshed (#87).

    A partial refresh is not a smaller success: the catalog is a single
    published artifact, and a source that failed kept its previously committed
    records, so those slices are *stale* rather than wrong. Internal
    consistency validation cannot see that — a stale record still validates —
    so the run's exit code is the only signal that distinguishes "this catalog
    is today's" from "this catalog is last week's with today's date on it".
    Publication is therefore blocked on any failed source, while the sources
    that succeeded keep their committed results.

    Baseline failure is included implicitly: the software importer that owns
    the manifest counts and most records is one of the sources, so its failure
    blocks publication by the same rule. An empty registry is not success
    either — there is nothing to have refreshed.
    """
    outcomes = list(outcomes)
    return 0 if outcomes and not failed(outcomes) else 1


def freshness(outcomes):
    """The run's freshness verdict, as a machine-readable statement (#87).

    `complete` is true only when every registered source refreshed, which is
    the same condition `exit_code` enforces. `blocking` names it for the
    workflow: a consumer or a CI step can fail on this field instead of
    re-deriving the policy from the exit code. `failed` lists the sources whose
    committed records are stale after this run.
    """
    outcomes = list(outcomes)
    failures = failed(outcomes)
    return {
        "sources": len(outcomes),
        "refreshed": len(outcomes) - len(failures),
        "failed": [outcome.id for outcome in failures],
        "complete": bool(outcomes) and not failures,
        "blocking": not bool(outcomes) or bool(failures),
    }


def report(outcomes):
    """The refresh report, one line per source plus the run's own verdict."""
    outcomes = list(outcomes)
    lines = [outcome.line() for outcome in outcomes]
    failures = failed(outcomes)
    if not outcomes:
        lines.append("No sources registered: nothing refreshed, and publication is blocked.")
    elif not failures:
        lines.append(f"All {len(outcomes)} sources refreshed.")
    elif len(failures) == len(outcomes):
        lines.append("Every source failed; the committed catalog is unchanged and publication is blocked.")
    else:
        names = ", ".join(outcome.id for outcome in failures)
        lines.append(f"{len(outcomes) - len(failures)} of {len(outcomes)} sources refreshed; "
                     f"failed sources kept their previously committed (now stale) records and publication "
                     f"is blocked: {names}.")
    return lines


def summary_markdown(outcomes):
    """The same report as a GitHub step summary, or None when not asked for one."""
    path = os.environ.get(STEP_SUMMARY)
    if not path:
        return None
    outcomes = list(outcomes)
    rows = ["| Source | Result | Detail |", "| --- | --- | --- |"]
    for outcome in outcomes:
        detail = outcome.detail if outcome.ok else outcome.error
        rows.append(f"| `{outcome.id}` | {'ok' if outcome.ok else 'failed'} | {detail.replace('|', '\\|') or '-'} |")
    verdict = freshness(outcomes)
    return "\n".join([
        "## Catalog refresh", "", *rows, "", report(outcomes)[-1], "",
        f"Freshness: {verdict['refreshed']}/{verdict['sources']} sources refreshed; "
        f"{'complete' if verdict['complete'] else 'incomplete — publication blocked'}.", "",
    ])
