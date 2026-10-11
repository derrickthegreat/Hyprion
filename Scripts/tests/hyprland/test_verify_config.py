"""The shipped Lua config loads in the real Hyprland, under the user configs in fixtures/.

The Lua suites run HyDE's config against a stubbed `hl`, which can't model
Hyprland itself crashing: a segfault in its keybind code passed every stub test
and then killed every login. This runs `Hyprland --verify-config`, which
executes the whole config without starting a session, in a sandbox HOME built
from this checkout. Commands the config runs while loading go to the
sandbox's fake hyprctl and friends, never to a live session.

Each fixture is appended to the stock ~/.config/hypr/hyprland.lua, as a user's
own binds would be. Skipped where Hyprland isn't installed; CI installs it.

Run from the repo root:  python3 Scripts/tests/hyprland/test_verify_config.py
"""

import ctypes
import os
import resource
import shutil
import signal
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "theme-security"))
from sandbox import LIB, REPO, Sandbox  # noqa: E402

HYPRLAND = shutil.which("Hyprland", path="/usr/bin:/bin")
FIXTURES = Path(__file__).resolve().parent / "fixtures"
STOCK_CONFIG = REPO / "Configs/.config/hypr/hyprland.lua"
EXAMPLE_CONFIG = REPO / "Source/examples/hyprland.lua"
PR_SET_CHILD_SUBREAPER = 36


def no_core_dump():
    # A crash is the failure being tested for; its core file adds nothing.
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def adopt_orphans():
    # Hyprland exits without waiting for the commands it started, and those
    # write to the sandbox. As subreaper, this process inherits them instead of
    # init, so it can wait for them before the sandbox is deleted.
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(PR_SET_CHILD_SUBREAPER, 1, 0, 0, 0) != 0:
        raise OSError(ctypes.get_errno(), "prctl(PR_SET_CHILD_SUBREAPER) failed")


def reap_orphans(timeout=10):
    deadline = time.monotonic() + timeout
    while True:
        try:
            pid, _ = os.waitpid(-1, os.WNOHANG)
        except ChildProcessError:
            return
        if pid == 0:
            if time.monotonic() > deadline:
                raise TimeoutError("commands started by Hyprland are still running")
            time.sleep(0.01)


@unittest.skipUnless(HYPRLAND, "Hyprland is not installed")
class VerifyConfigTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        adopt_orphans()

    def setUp(self):
        self.box = Sandbox()
        (self.box.home / ".local/lib").mkdir(parents=True)
        (self.box.home / ".local/lib/hyde").symlink_to(LIB)
        (self.box.data / "hypr").symlink_to(REPO / "Configs/.local/share/hypr")
        (self.box.config / "hypr").mkdir()

    def tearDown(self):
        self.box.cleanup()

    def verify(self, user_config):
        (self.box.config / "hypr/hyprland.lua").write_text(user_config)
        args = [HYPRLAND, "--verify-config"]
        # Even --verify-config refuses root without this, e.g. in a bare container.
        if os.geteuid() == 0:
            args.append("--i-am-really-stupid")
        result = self.box.run(args, preexec_fn=no_core_dump)
        reap_orphans()
        return result

    def assertLoads(self, result):
        output = (result.stdout + result.stderr).strip()
        tail = "\n".join(output.splitlines()[-15:])
        if result.returncode < 0:
            self.fail(f"Hyprland crashed with {signal.Signals(-result.returncode).name}:\n{tail}")
        self.assertEqual(result.returncode, 0, f"config failed to verify:\n{tail}")
        self.assertIn("config ok", output, tail)

    def test_stock_config_loads(self):
        self.assertLoads(self.verify(STOCK_CONFIG.read_text()))

    def test_example_config_loads(self):
        self.assertLoads(self.verify(EXAMPLE_CONFIG.read_text()))

    def test_fixtures_load(self):
        fixtures = sorted(FIXTURES.glob("*.lua"))
        self.assertTrue(fixtures, f"no fixtures in {FIXTURES}")
        stock = STOCK_CONFIG.read_text()
        for fixture in fixtures:
            with self.subTest(fixture=fixture.name):
                self.assertLoads(self.verify(f"{stock}\n{fixture.read_text()}"))

    def test_a_broken_user_config_fails(self):
        # Proves the user config is loaded at all, so the passes above mean something.
        result = self.verify(f'{STOCK_CONFIG.read_text()}\nerror("fixture marker")\n')
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("fixture marker", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
