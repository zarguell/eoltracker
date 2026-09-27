"""Regression tests for the opt-in rendering fetch profile (#154).

These tests never launch a browser. The profile's whole point is that it is
gated, so every gate is exercised here without one: the registry check, the
operator switch, the URL check, and the refusal when nothing renders. The one
test that touches playwright asserts only that its absence is reported clearly.

The rules this profile exists to keep are the ones worth pinning. A rendered
fetch must identify itself as a headless browser rather than impersonating
another one, must never attempt to get past a refusal, and must never run
because a collector forgot to declare it.
"""
import os
import unittest
from unittest import mock

from engine import render, sources


class SwitchTests(unittest.TestCase):
    """The operator switch is off unless the operator turns it on."""

    def setUp(self):
        self.saved = os.environ.pop(render.ENV_SWITCH, None)

    def tearDown(self):
        os.environ.pop(render.ENV_SWITCH, None)
        if self.saved is not None:
            os.environ[render.ENV_SWITCH] = self.saved

    def test_rendering_is_off_with_no_environment_at_all(self):
        self.assertFalse(render.enabled())
        self.assertEqual(render.switch_state(), f"{render.ENV_SWITCH}=off")

    def test_only_a_true_value_enables_it(self):
        for value in ("1", "true", "TRUE", "yes", "on", " On "):
            with self.subTest(value=value):
                os.environ[render.ENV_SWITCH] = value
                self.assertTrue(render.enabled())
                self.assertEqual(render.switch_state(), f"{render.ENV_SWITCH}=on")

    def test_a_falsey_or_unknown_value_does_not_enable_it(self):
        for value in ("", "0", "false", "no", "off", "maybe", "2"):
            with self.subTest(value=value):
                os.environ[render.ENV_SWITCH] = value
                self.assertFalse(render.enabled())


class RegistryGateTests(unittest.TestCase):
    """A collector cannot opt itself in: the profile is named in the registry."""

    def test_a_source_registered_for_rendering_is_accepted(self):
        source = render.declaring("import-netgear")
        self.assertEqual(source.fetch, render.PROFILE)

    def test_a_plain_source_is_refused(self):
        for source_id in ("import-data", "import-watchguard", "import-extreme"):
            with self.subTest(source_id=source_id):
                with self.assertRaisesRegex(render.RenderUnavailable, "registered with fetch="):
                    render.declaring(source_id)

    def test_an_unknown_source_is_refused_by_the_registry(self):
        with self.assertRaises(sources.UnknownSource):
            render.declaring("import-nothing-registers-this")

    def test_only_the_registry_names_the_sources_that_may_be_rendered(self):
        rendered = [source.id for source in sources.all_sources()
                    if source.fetch == render.PROFILE]
        self.assertEqual(rendered, ["import-netgear"])


class RenderGateTests(unittest.TestCase):
    """Every way a render can refuse, with no browser involved."""

    def source(self):
        return sources.source("import-netgear")

    def test_the_switch_is_checked_before_anything_is_launched(self):
        # The switch is off in this environment, so a render must refuse on the
        # gate rather than reach for playwright. If it tried to import playwright
        # first, the missing-dependency message would appear instead.
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(render.ENV_SWITCH, None)
            with self.assertRaisesRegex(render.RenderUnavailable, "EOLTRACKER_ALLOW_RENDER"):
                render.render(self.source().url, "import-netgear")

    def test_a_url_the_registry_does_not_name_is_refused(self):
        with mock.patch.dict(os.environ, {render.ENV_SWITCH: "1"}):
            with self.assertRaisesRegex(render.RenderUnavailable, "does not list"):
                render.render("https://www.netgear.com/privacy/", "import-netgear")

    def test_a_source_that_does_not_register_the_profile_is_refused_before_the_switch(self):
        with mock.patch.dict(os.environ, {render.ENV_SWITCH: "1"}):
            with self.assertRaisesRegex(render.RenderUnavailable, "registered with fetch="):
                render.render(self.source().url, "import-watchguard")

    def test_a_missing_playwright_is_reported_as_an_optional_extra(self):
        with mock.patch.dict(os.environ, {render.ENV_SWITCH: "1"}):
            real_import = __import__

            def no_playwright(name, *args, **kwargs):
                if name == "playwright.sync_api":
                    raise ImportError("no playwright here")
                return real_import(name, *args, **kwargs)

            with mock.patch("builtins.__import__", side_effect=no_playwright):
                with self.assertRaisesRegex(render.RenderUnavailable,
                                            "optional extra.*requirements.txt"):
                    render.render(self.source().url, "import-netgear")

    def test_a_render_that_produces_nothing_refuses(self):
        class Page:
            def goto(self, *args, **kwargs):
                return None

            def wait_for_timeout(self, *args, **kwargs):
                return None

            def content(self):
                return ""

        class Browser:
            def new_page(self):
                return Page()

            def close(self):
                return None

        class Playwright:
            chromium = mock.Mock(**{"launch.return_value": Browser()})

        with mock.patch.dict(os.environ, {render.ENV_SWITCH: "1"}):
            with mock.patch.dict("sys.modules", {"playwright": mock.Mock(),
                                                "playwright.sync_api": mock.Mock()}):
                with mock.patch("playwright.sync_api.sync_playwright") as started:
                    started.return_value.__enter__.return_value = Playwright()
                    with self.assertRaisesRegex(render.RenderRefused, "rendered 0 bytes"):
                        render.render(self.source().url, "import-netgear")


class HonestyTests(unittest.TestCase):
    """The profile must say what it is, because that is the whole condition."""

    def test_the_profile_names_itself_as_a_headless_browser(self):
        note = render.fetch_note()
        self.assertEqual(note["fetch"], "rendered")
        self.assertIn("headless", note["rendered_by"])
        self.assertIn("no user-agent override", note["rendered_by"])
        self.assertIn("no challenge solving", note["rendered_by"])
        self.assertEqual(note["operator_switch"], render.ENV_SWITCH)

    def test_the_module_never_calls_an_identity_override_or_a_challenge_handler(self):
        """A guard against the profile quietly growing an evasion.

        The terms appear in the module's prose — that is the point of the prose —
        so the check reads the *code*: every attribute name and every string
        constant that is not a docstring. An identity override or a challenge
        handler is the line between browser-capable and impersonating, and this
        is where a future change would cross it.
        """
        import ast

        tree = ast.parse(open(render.__file__, encoding="utf-8").read())
        docstrings = {id(node.body[0].value) for node in ast.walk(tree)
                      if isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef))
                      and node.body and isinstance(node.body[0], ast.Expr)
                      and isinstance(node.body[0].value, ast.Constant)
                      and isinstance(node.body[0].value.value, str)}
        forbidden = ("user_agent", "set_extra_http_headers", "add_init_script", "webdriver",
                     "captcha", "bypass", "stealth", "route")
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in forbidden:
                self.fail(f"{render.__file__} calls {node.attr!r}; the rendering profile must not "
                          f"override an identity or evade a challenge")
            if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                    and id(node) not in docstrings):
                for term in forbidden:
                    self.assertNotIn(term, node.value)


if __name__ == "__main__":
    unittest.main()
