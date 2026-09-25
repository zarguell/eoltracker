"""Workflow contracts: publication ordering, action pinning and the hash lock.

These are claims about the workflows themselves, which no unit test of the
engine can reach and which fail silently in production: an action referenced by
a mutable tag, a build that runs before the catalog is synchronized, or a
dependency installed without a hash lock. Each test reads the committed YAML
and asserts the property, so a future edit that reintroduces one fails here
instead of on a separate branch's run (#81, #101).
"""
import re
import unittest
from pathlib import Path

import yaml

from engine.importer import ROOT

WORKFLOWS = ROOT / ".github" / "workflows"
PUBLISH = WORKFLOWS / "publish.yml"
CI = WORKFLOWS / "ci.yml"

# `owner/repo@ref`, where `ref` must be a full 40-character commit SHA.
ACTION_USE = re.compile(r"^(?P<action>[\w.-]+/[\w.-]+)@(?P<ref>[^\s#]+)(?P<comment>\s*#.*)?$")
FULL_SHA = re.compile(r"^[0-9a-f]{40}$")


def workflow(path):
    """A workflow parsed as YAML.

    PyYAML reads the bare `on:` key as the boolean True (YAML 1.1), so callers
    read `jobs` and never `on`; the trigger shape is not what these tests pin.
    """
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def steps(path, job=None):
    """Every step of a workflow, or of one job, with its index."""
    document = workflow(path)
    jobs = document["jobs"]
    if job is not None:
        jobs = {job: jobs[job]}
    return [(name, index, step) for name, definition in jobs.items()
            for index, step in enumerate(definition.get("steps") or [])]


def run_commands(path, job=None):
    """The `run:` command text of every step, in order, with its job and name."""
    return [(name, step.get("name", ""), step["run"])
            for name, _, step in steps(path, job) if "run" in step]


def uses_actions(path):
    """Every `uses:` value in a workflow, with the step that carries it."""
    return [(step.get("name", ""), step["uses"])
            for _, _, step in steps(path) if "uses" in step]


USES_LINE = re.compile(r"(?m)^\s*uses:\s*(?P<uses>\S+)(?P<comment>\s*#.*)?$")


def uses_lines(path):
    """Every `uses:` line with any trailing comment, read from the raw YAML.

    PyYAML discards the trailing comment, and the comment is the only readable
    record of which release a pinned SHA corresponds to, so it is read here
    rather than from the parsed document.
    """
    return [(match.group("uses"), (match.group("comment") or "").strip())
            for match in USES_LINE.finditer(Path(path).read_text(encoding="utf-8"))]


class PublishOrderingTests(unittest.TestCase):
    """The published tree is built after the catalog is synchronized (#81)."""

    def test_rebase_or_fetch_precedes_the_authoritative_build(self):
        commands = run_commands(PUBLISH)
        names = [name for _, name, _ in commands]
        synchronize = next(index for index, name in enumerate(names) if "synchronize" in name.lower())
        build = next(index for index, name in enumerate(names) if name.strip().lower() == "build the complete site")
        validate = next(index for index, name in enumerate(names) if "validate" in name.lower())
        tests = next(index for index, name in enumerate(names) if "unit tests" in name.lower())
        # Synchronization comes before validation, tests and the build: those
        # three describe one revision, and it must be the one that is pushed.
        self.assertLess(synchronize, validate)
        self.assertLess(synchronize, tests)
        self.assertLess(synchronize, build)
        text = commands[synchronize][2]
        self.assertIn("git fetch origin main", text)
        self.assertIn("git rebase origin/main", text)

    def test_the_push_happens_after_the_build_and_is_never_forced(self):
        commands = run_commands(PUBLISH)
        names = [name for _, name, _ in commands]
        build = next(index for index, name in enumerate(names) if name.strip().lower() == "build the complete site")
        push = next(index for index, name in enumerate(names) if name.startswith("Push the synchronized"))
        self.assertLess(build, push)
        # A forced push would overwrite whatever advanced main while this ran.
        for _, name, text in commands:
            self.assertNotIn("--force", text, name)
            self.assertNotIn("-f origin main", text, name)

    def test_both_pages_paths_consume_the_one_built_tree(self):
        # The gh-pages branch publish and the Pages artifact must take the same
        # directory, built once above, rather than one of them rebuilding.
        directories = {}
        for _, _, step in steps(PUBLISH, "build"):
            uses = step.get("uses", "")
            if uses.startswith("peaceiris/actions-gh-pages@"):
                directories["gh-pages"] = step["with"]["publish_dir"]
            elif uses.startswith("actions/upload-pages-artifact@"):
                directories["artifact"] = step["with"]["path"]
        self.assertEqual(directories["gh-pages"], "./_site")
        self.assertEqual(directories["artifact"], "_site")
        # ...and no step after the build runs `engine build` again.
        build_index = next(index for _, index, step in steps(PUBLISH, "build")
                           if step.get("name", "").strip().lower() == "build the complete site")
        for _, index, step in steps(PUBLISH, "build"):
            if index > build_index and "run" in step:
                self.assertNotIn("engine build", step["run"], step.get("name"))

    def test_the_built_tree_carries_the_commit_it_was_built_from(self):
        # The artifact marker is what makes "the site matches the pushed commit"
        # checkable rather than asserted; it is written from the live HEAD the
        # build ran against, and travels with the tree.
        commands = run_commands(PUBLISH, "build")
        stamp = next(text for _, name, text in commands if "Stamp the built tree" in name)
        self.assertIn("git rev-parse HEAD", stamp)
        self.assertIn("_site/BUILD-COMMIT.txt", stamp)

    def test_every_job_declares_runs_on_and_steps(self):
        # A locally parsed workflow with no `runs-on` failed only in Actions.
        for name, definition in workflow(PUBLISH)["jobs"].items():
            self.assertTrue(definition.get("runs-on"), name)
            self.assertTrue(definition.get("steps"), name)
        for name, definition in workflow(CI)["jobs"].items():
            self.assertTrue(definition.get("runs-on"), name)
            self.assertTrue(definition.get("steps"), name)


class ActionPinTests(unittest.TestCase):
    """Every action is pinned to a reviewed full commit SHA (#101)."""

    def test_every_uses_is_a_full_sha(self):
        for path in (PUBLISH, CI):
            pinned = uses_actions(path)
            self.assertTrue(pinned, path)
            for name, uses in pinned:
                match = ACTION_USE.match(uses)
                self.assertIsNotNone(match, f"{path.name}: {name}: unparseable uses {uses!r}")
                self.assertRegex(match.group("ref"), FULL_SHA,
                                 f"{path.name}: {name}: {match.group('action')} is not pinned to a full SHA "
                                 f"(got {match.group('ref')!r})")

    def test_each_pin_records_the_tag_it_replaces(self):
        # The trailing comment is the only readable record of which release the
        # SHA is; Renovate updates the pair, and a pin without it is unreviewable.
        for path in (PUBLISH, CI):
            lines = uses_lines(path)
            self.assertTrue(lines, path)
            for uses, comment in lines:
                self.assertRegex(comment, r"^#\s*\S+\s+@?v?\d",
                                 f"{path.name}: {uses!r} has no readable tag comment")

    def test_the_pinned_shas_are_the_ones_the_tags_resolved_to(self):
        # The SHAs below are the values these tags resolved to when reviewed;
        # a bump changes both the workflow and this table together.
        reviewed = {
            "actions/checkout": "3d3c42e5aac5ba805825da76410c181273ba90b1",
            "actions/setup-python": "5fda3b95a4ea91299a34e894583c3862153e4b97",
            "actions/upload-pages-artifact": "fc324d3547104276b827a68afc52ff2a11cc49c9",
            "actions/deploy-pages": "368f82528645a54fb793d4d04e342629a3f51346",
            "peaceiris/actions-gh-pages": "84c30a85c19949d7eee79c4ff27748b70285e453",
        }
        seen = set()
        for path in (PUBLISH, CI):
            for name, uses in uses_actions(path):
                action, _, ref = uses.partition("@")
                ref = ref.split("#")[0].strip()
                self.assertIn(action, reviewed, f"{path.name}: {name}: unreviewed action {action}")
                self.assertEqual(ref, reviewed[action], f"{path.name}: {name}: pin drift for {action}")
                seen.add(action)
        self.assertEqual(seen, set(reviewed))


class HashLockTests(unittest.TestCase):
    """Dependencies install from a resolved, hash-locked set (#101)."""

    def setUp(self):
        self.lock = ROOT / "requirements.lock"

    def test_every_install_step_uses_require_hashes_and_the_lock(self):
        for path in (PUBLISH, CI):
            installs = [(name, text) for _, name, text in run_commands(path)
                        if "pip install" in text]
            self.assertTrue(installs, path)
            for name, text in installs:
                self.assertIn("--require-hashes", text, f"{path.name}: {name}")
                self.assertIn("requirements.lock", text, f"{path.name}: {name}")
                self.assertNotIn("requirements.txt", text, f"{path.name}: {name}")

    def test_the_lock_is_fully_hashed_and_covers_the_direct_requirements(self):
        text = self.lock.read_text(encoding="utf-8")
        requirements = [line.split("==")[0].split("[")[0].strip().lower()
                        for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
                        if line.strip() and not line.startswith("#")]
        pinned = {line.split("==")[0].split("[")[0].strip().lower()
                  for line in text.splitlines() if "==" in line and line[0].isalnum()}
        for name in requirements:
            self.assertIn(name, pinned, f"{name} is not pinned in requirements.lock")
        for block in re.findall(r"(?m)^([a-z0-9][\w.-]*==[^\n]*(?:\n\s+--hash[^\n]*)+)", text):
            self.assertIn("--hash=sha256:", block, block.splitlines()[0])

    def test_the_lock_is_not_a_second_direct_requirements_list(self):
        # The lock is generated from requirements.txt; the direct list is the
        # only place a dependency is chosen. A direct requirement that vanished
        # from requirements.txt would otherwise stay installed and unnoticed.
        direct = {line.split("==")[0].split("[")[0].strip().lower()
                  for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
                  if line.strip() and not line.startswith("#")}
        self.assertEqual(direct, {"jinja2", "jsonschema", "requests", "pyyaml"})
