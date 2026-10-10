"""Unit tests for the system update helper and the pacman backend extras.

Run from the repo root:  python3 Scripts/tests/system-update/test_system_update.py
"""

import contextlib
import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

LIB = Path(__file__).resolve().parents[3] / "Configs/.local/lib/hyde"
BASH = shutil.which("bash")
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


# Never reachable from the sandbox PATH except as the stubs written below.
GUARDED = ("pacman", "paru", "yay", "sudo", "makepkg", "git", "flatpak", "apt", "dnf", "zypper", "checkupdates")
LISTING = "extra foo 1.0-1\nextra bar 2.0-1\n"


class Sandbox:
    """A fake HOME and a PATH holding only recording stubs and a few named tools."""

    def __init__(self, stubs, tools=()):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.bin = root / "bin"
        self.home = root / "home"
        self.log = root / "calls.log"
        self.bin.mkdir()
        self.home.mkdir()
        # The stubs' shebang finds bash on PATH, so it is always linked in.
        for tool in ("bash", *tools):
            (self.bin / tool).symlink_to(shutil.which(tool))
        for name, body in stubs.items():
            path = self.bin / name
            path.write_text(f'#!/usr/bin/env bash\nprintf "%s\\n" "${{0##*/}}${{*:+ $*}}" >>"$SHIM_LOG"\n{body}\n')
            path.chmod(0o755)
        for name in GUARDED:
            found = shutil.which(name, path=str(self.bin))
            assert found is None or not Path(found).is_symlink(), f"{name} would reach the real system"
        self.env = {
            "PATH": str(self.bin),
            "HOME": str(self.home),
            "XDG_CACHE_HOME": str(self.home / ".cache"),
            "XDG_CONFIG_HOME": str(self.home / ".config"),
            "XDG_RUNTIME_DIR": str(root),
            "SHIM_LOG": str(self.log),
            "LANG": "C",
        }

    def calls(self):
        return self.log.read_text().splitlines() if self.log.exists() else []

    def reset(self):
        self.log.unlink(missing_ok=True)

    def cleanup(self):
        self.tmp.cleanup()


def bare_refreshes(lines):
    """Calls that refresh pacman's databases without upgrading in the same transaction."""
    found = []
    for line in lines:
        words = line.split()
        if not {"pacman", "paru", "yay"} & set(words[:2]):
            continue
        if any(re.fullmatch(r"-S[a-zA-Z]*", w) and "y" in w[2:] and "u" not in w[2:] for w in words):
            found.append(line)
    return found


ARCH_STUBS = {
    "pacman": f'[ "$1" = -Sl ] && printf "{LISTING}"; exit 0',
    "paru": f'[ "$1" = -Sl ] && printf "{LISTING}"; exit 0',
    "yay": "exit 0",
    "sudo": "exit 0",
    "checkupdates": 'echo "foo 1.0-1 -> 1.1-1"',
    "flatpak": "exit 0",
    "git": "exit 1",
    "makepkg": "exit 1",
    # Picks the first candidate, as a user pressing Enter would.
    "fzf": 'first=""; while IFS= read -r line || [ -n "$line" ]; do [ -n "$first" ] || first=$line; done; printf "%s\\n" "$first"',
}
# What pm.sh runs besides the package managers.
PM_SH_TOOLS = ("mkdir", "cat", "date", "basename", "grep", "sed", "awk", "cut", "xargs", "mktemp", "rm")


class PmRefreshTests(unittest.TestCase):
    """pm.py and pm.sh never refresh pacman's databases without upgrading in the same transaction."""

    def setUp(self):
        self.box = Sandbox(ARCH_STUBS, PM_SH_TOOLS)

    def tearDown(self):
        self.box.cleanup()

    def pm(self, *args, stdin="", script="py"):
        self.box.reset()
        command = [sys.executable, str(LIB / "pm.py")] if script == "py" else [BASH, str(LIB / "pm.sh")]
        result = subprocess.run([*command, *args], input=stdin, env=self.box.env,
                                capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = [line for line in self.box.calls() if not line.startswith("fzf")]
        self.assertEqual(bare_refreshes(calls), [])
        return calls

    def test_install_uses_the_databases_as_they_are(self):
        expected = {"pacman": "sudo pacman -S --needed foo", "paru": "paru -S --needed foo", "yay": "yay -S --needed foo"}
        for manager, line in expected.items():
            with self.subTest(manager=manager):
                self.assertEqual(self.pm("--pm", manager, "install", "foo"), [line])
                self.assertEqual(self.pm("--pm", manager, "install", "foo", script="sh"), [line])

    def test_interactive_install_does_not_refresh_first(self):
        # The `in` alias with no arguments; stdin narrows the list as a filter.
        self.assertEqual(self.pm("--pm", "paru", "install", stdin="foo\n"),
                         ["paru -Sl --color=never", "paru -S --needed foo"])
        self.assertEqual(self.pm("--pm", "pacman", "install", stdin="foo\n"),
                         ["pacman -Sl --color=never", "sudo pacman -S --needed foo"])

    def test_installer_unattended_install(self):
        # Scripts/restore_cfg.sh's ensure_hyq and uv_hook
        self.assertEqual(self.pm("--pm", "paru", "install", "--no-confirm", "hyprquery", script="sh"),
                         ["paru -S --needed --noconfirm hyprquery"])
        self.assertEqual(self.pm("--pm", "pacman", "install", "--no-confirm", "uv", script="sh"),
                         ["sudo pacman -S --needed --noconfirm uv"])

    def test_upgrade_refreshes_in_the_same_transaction(self):
        expected = {"pacman": "sudo pacman -Syu", "paru": "paru -Syu", "yay": "yay -Syu"}
        for manager, line in expected.items():
            with self.subTest(manager=manager):
                self.assertEqual(self.pm("--pm", manager, "upgrade"), [line])
                self.assertEqual(self.pm("--pm", manager, "upgrade", script="sh"), [line])

    def test_fetch_reads_a_private_copy(self):
        for manager in ("pacman", "paru", "yay"):
            for script in ("py", "sh"):
                with self.subTest(manager=manager, script=script):
                    self.assertEqual(self.pm("--pm", manager, "fetch", script=script), ["checkupdates"])

    def test_default_manager_installs_through_the_aur_helper(self):
        self.assertEqual(self.pm("install", "foo"), ["paru -S --needed foo"])
        self.assertEqual(self.pm("upgrade"), ["paru -Syu"])

    def test_flatpak_keeps_its_own_refresh(self):
        self.assertEqual(self.pm("--pm", "flatpak", "install", "foo"), ["flatpak install foo"])
        self.assertEqual(self.pm("--pm", "flatpak", "upgrade"), ["flatpak update"])
        self.assertEqual(self.pm("--pm", "flatpak", "fetch"), ["flatpak update --appstream"])
        self.assertEqual(self.pm("--pm", "flatpak", "upgrade", script="sh"),
                         ["flatpak update --appstream", "flatpak update"])


class OtherBackendRefreshTests(unittest.TestCase):
    def setUp(self):
        self.box = Sandbox({name: "exit 0" for name in ("sudo", "apt", "dnf", "zypper")})

    def tearDown(self):
        self.box.cleanup()

    def test_upgrade_refreshes_first(self):
        expected = {
            "apt": ["sudo apt update", "sudo apt upgrade"],
            "dnf": ["sudo dnf upgrade --refresh"],
            "zypper": ["sudo zypper refresh", "sudo zypper update"],
        }
        for manager, lines in expected.items():
            with self.subTest(manager=manager):
                self.box.reset()
                result = subprocess.run([sys.executable, str(LIB / "pm.py"), "--pm", manager, "upgrade"],
                                        env=self.box.env, capture_output=True, text=True, timeout=60)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.box.calls(), lines)


class SystemUpdateRefreshTests(unittest.TestCase):
    """The update window's upgrades refresh too, even when only the AUR has updates."""

    def setUp(self):
        self.box = Sandbox(ARCH_STUBS)

    def tearDown(self):
        self.box.cleanup()

    def test_upgrades_refresh(self):
        with mock.patch.dict(os.environ, self.box.env, clear=True), \
                mock.patch.object(su, "CACHE_DIR", self.box.home / "cache"), \
                contextlib.redirect_stdout(io.StringIO()):
            done, failed = su.run_upgrades(["paru"], 40)
            self.assertEqual((done, failed), (["paru"], []))
            self.assertEqual(self.box.calls(), ["paru -Syu"])
            self.box.reset()
            su.run_upgrades(["pacman"], 40)
            self.assertEqual(self.box.calls(), ["sudo pacman -Syu"])


if __name__ == "__main__":
    unittest.main()
