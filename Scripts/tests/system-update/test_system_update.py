"""Unit tests for the system update helper and the pacman backend extras.

Run from the repo root:  python3 Scripts/tests/system-update/test_system_update.py
"""

import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

LIB = Path(__file__).resolve().parents[3] / "Configs/.local/lib/hyde"
sys.path.insert(0, str(LIB))
sys.path.insert(0, str(LIB / "package_managers"))


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


su = load("system_update", LIB / "system.update.py")
pacman = load("pacman_backend", LIB / "package_managers/pacman.py")
meta = load("meta", LIB / "package_managers/meta.py")


class FakeCtx:
    def __init__(self, output=""):
        self.output = output

    def capture(self, args, **kwargs):
        return self.output


class VersionTests(unittest.TestCase):
    def test_split_at_first_changed_segment(self):
        self.assertEqual(su.split_version("7.2.9.zen1-1", "7.2.10.zen1-1"), ("7.2.", "10.zen1-1"))
        self.assertEqual(su.split_version("1:2.37.10-1", "1:2.37.11-1"), ("1:2.37.", "11-1"))
        self.assertEqual(su.split_version("15.0.0-1", "15.0.0-2"), ("15.0.0-", "2"))

    def test_split_without_shared_prefix(self):
        self.assertEqual(su.split_version("r110.g3112b12-1", "latest-commit"), ("", "latest-commit"))
        self.assertEqual(su.split_version(None, "2.1.0-1"), ("", "2.1.0-1"))
        self.assertEqual(su.split_version("", ""), ("", ""))

    def test_rebuild_is_pkgrel_only(self):
        self.assertTrue(su.is_rebuild("15.0.0-1", "15.0.0-2"))
        self.assertTrue(su.is_rebuild("1:26.1.2-1", "1:26.1.2-3"))
        self.assertFalse(su.is_rebuild("15.0.0-1", "15.0.1-1"))
        self.assertFalse(su.is_rebuild("144.0", "144.0.1"))
        self.assertFalse(su.is_rebuild(None, "1.0-1"))


class TagTests(unittest.TestCase):
    kernels = {"linux-zen"}

    def tag(self, name, old="1.0-1", new="1.1-1"):
        return su.package_tag(su.Pending(name, old, new), self.kernels)

    def test_tags(self):
        self.assertEqual(self.tag("linux-zen"), "reboot")
        self.assertEqual(self.tag("linux-firmware-amdgpu"), "reboot")
        self.assertEqual(self.tag("systemd"), "reboot")
        self.assertEqual(self.tag("hyprland"), "relog")
        self.assertEqual(self.tag("libfreshdep", old=None), "new")
        self.assertEqual(self.tag("python-rich", "1.0-1", "1.0-2"), "rebuild")
        self.assertIsNone(self.tag("firefox"))
        self.assertIsNone(self.tag("linux-zen-headers"))

    def test_kernel_names_come_from_pkgbase(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "6.1.0-custom").mkdir()
            (Path(tmp) / "6.1.0-custom/pkgbase").write_text("linux-custom\n")
            self.assertIn("linux-custom", su.kernel_packages(Path(tmp)))

    def test_kernel_replaced_when_modules_are_gone(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "7.2.10-zen1-1-zen").mkdir()
            self.assertTrue(su.kernel_replaced("7.2.9-zen1-1-zen", Path(tmp)))
            self.assertFalse(su.kernel_replaced("7.2.10-zen1-1-zen", Path(tmp)))
            self.assertFalse(su.kernel_replaced("7.2.9-zen1-1-zen", Path(tmp) / "missing"))


class FormatTests(unittest.TestCase):
    def test_ago(self):
        now = 1_000_000.0
        self.assertEqual(su.ago(now - 30, now), "just now")
        self.assertEqual(su.ago(now - 60, now), "1 minute ago")
        self.assertEqual(su.ago(now - 2 * 3600, now), "2 hours ago")
        self.assertEqual(su.ago(now - 3 * 86400, now), "3 days ago")

    def test_human_size(self):
        self.assertEqual(su.human_size(512), "512 B")
        self.assertEqual(su.human_size(1536), "1.5 KiB")
        self.assertEqual(su.human_size(294 * 1024**2), "294.0 MiB")
        self.assertEqual(su.human_size(3 * 1024**4), "3072.0 GiB")

    def test_rows_align_without_color(self):
        su.COLOR = False
        rows = su.package_rows(
            [su.Pending("linux-zen", "7.2.9-1", "7.2.10-1"), su.Pending("libfreshdep", None, "2.1-1")],
            {"linux-zen"},
        )
        self.assertEqual(rows[0], "   linux-zen    7.2.9-1  →  7.2.10-1  reboot")
        # The new version lines up under the row above even with no old version
        self.assertEqual(rows[1], "   libfreshdep              2.1-1     new")


class StatusTests(unittest.TestCase):
    def test_waybar_payload(self):
        updates = [
            su.ManagerUpdates("pacman", 2, [su.Pending("linux-zen", "1-1", "2-1"), su.Pending("a&b", "1-1", "2-1")]),
            su.ManagerUpdates("flatpak", 0, []),
        ]
        payload = json.loads(su.status_json(updates, {"linux-zen"}, reboot_pending=True))
        self.assertEqual(payload["text"], f"{su.ICON_UPDATES} 2")
        self.assertEqual(payload["class"], ["updates", "reboot-needed", "important"])
        self.assertIn("a&amp;b", payload["tooltip"])
        self.assertIn("<i>(reboot)</i>", payload["tooltip"])

    def test_reboot_icon_when_up_to_date(self):
        payload = json.loads(su.status_json([su.ManagerUpdates("pacman", 0, [])], set(), reboot_pending=True))
        self.assertEqual(payload["text"], su.ICON_REBOOT)


class LaunchTests(unittest.TestCase):
    def test_terminal_leaves_the_callers_session(self):
        # Waybar killpg()s an on-click's group on reload; the terminal running pacman must not be in it.
        with mock.patch.object(su.shutil, "which", return_value="/usr/bin/xdg-terminal-exec"), \
             mock.patch.object(su.subprocess, "run") as run:
            self.assertEqual(su.launch_interactive(), 0)
        args, kwargs = run.call_args
        self.assertEqual(args[0][0], "/usr/bin/xdg-terminal-exec")
        self.assertEqual(args[0][-1], "interactive")
        self.assertTrue(kwargs.get("start_new_session"))


class RequirementTests(unittest.TestCase):
    def test_aur_helper_waits_for_pacman(self):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            kept = su.keep_requirements(["paru", "flatpak"], ["pacman", "paru", "flatpak"])
        self.assertEqual(kept, ["flatpak"])
        self.assertIn("Skipping paru", out.getvalue())
        # Nothing pending for pacman, so paru can go alone
        self.assertEqual(su.keep_requirements(["paru"], ["paru"]), ["paru"])


class OrphanTests(unittest.TestCase):
    orphans = ["go", "meson", "uv"]

    def clean(self, answers, picked=(), removed=True):
        calls = []

        def hook(name, *args, default=None):
            calls.append((name, *args))
            return removed

        with mock.patch("builtins.input", side_effect=answers), \
                mock.patch.object(su, "call_hook", hook), \
                mock.patch.object(su, "pick_orphans", return_value=list(picked)), \
                contextlib.redirect_stdout(io.StringIO()):
            su.clean_orphans(self.orphans)
        return calls

    def test_enter_keeps_everything(self):
        self.assertEqual(self.clean([""]), [])

    def test_remove_all(self):
        self.assertEqual(self.clean(["a"]), [("remove_orphans", self.orphans)])

    def test_pick_then_mark_the_rest(self):
        calls = self.clean(["p", "y"], picked=["meson"])
        self.assertEqual(calls, [("remove_orphans", ["meson"]), ("mark_explicit", ["go", "uv"])])

    def test_nothing_picked(self):
        self.assertEqual(self.clean(["p"]), [])

    def test_declined_removal_stops_there(self):
        self.assertEqual(self.clean(["p"], picked=["meson"], removed=False), [("remove_orphans", ["meson"])])


class PacmanBackendTests(unittest.TestCase):
    def test_parse_update_lines(self):
        output = "foo 1.0-1 -> 1.1-1\n\x1b[1mbar\x1b[0m 2-1 -> 3-1\nheld 1-1 -> 2-1 [ignored]\n:: warning\n"
        self.assertEqual(meta.parse_update_lines(output), [("foo", "1.0-1", "1.1-1", None), ("bar", "2-1", "3-1", None)])

    def test_last_upgrade_reads_latest_entry(self):
        with tempfile.NamedTemporaryFile("w", suffix=".log", delete=False) as log:
            log.write("[2019-01-01 12:00] [PACMAN] starting full system upgrade\n")
            log.write("[2026-10-09T09:24:49-0400] [PACMAN] starting full system upgrade\n")
            log.write("[2026-10-09T09:30:00-0400] [ALPM] upgraded foo (1-1 -> 2-1)\n")
        original, pacman.PACMAN_LOG = pacman.PACMAN_LOG, Path(log.name)
        try:
            stamp = pacman.last_upgrade(FakeCtx())
        finally:
            pacman.PACMAN_LOG = original
            Path(log.name).unlink()
        self.assertEqual(time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(stamp)), "2026-10-09 13:24:49")

    def test_news_after_cutoff(self):
        feed = """<rss><channel>
            <item><title>New</title><link>https://example/new</link><pubDate>Fri, 09 Oct 2026 10:00:00 +0000</pubDate></item>
            <item><title>Old</title><link>https://example/old</link><pubDate>Mon, 06 Jan 2020 10:00:00 +0000</pubDate></item>
        </channel></rss>"""
        cutoff = time.mktime((2026, 1, 1, 0, 0, 0, 0, 0, -1))
        self.assertEqual([title for _, title, _ in pacman.news(FakeCtx(feed), cutoff)], ["New"])
        self.assertEqual(pacman.news(FakeCtx(""), cutoff), [])

    def test_cache_savings(self):
        output = "\n==> finished dry run: 443 candidates (disk space saved: 13.94 GiB)\n"
        original = pacman.shutil.which
        pacman.shutil.which = lambda name: "/usr/bin/" + name
        try:
            self.assertEqual(pacman.cache_savings(FakeCtx(output)), "13.94 GiB")
            self.assertIsNone(pacman.cache_savings(FakeCtx("==> no candidate packages found for pruning")))
        finally:
            pacman.shutil.which = original

    def test_describe(self):
        output = (Path(__file__).parent / "fixtures/busy/orphans-info").read_text()
        descriptions = pacman.describe(FakeCtx(output), ["asciidoc", "dos2unix", "cdrtools"])
        self.assertEqual(descriptions["dos2unix"], "Text file format converter")
        self.assertEqual(len(descriptions), 3)


if __name__ == "__main__":
    unittest.main()
