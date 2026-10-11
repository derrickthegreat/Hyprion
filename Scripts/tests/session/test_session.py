"""The Hyprion session starts safe mode, not the greeter, when Hyprland can't run the config.

session.sh runs against a fake start-hyprland that, like the real 0.56.2 one,
exits 0 even when Hyprland crashed, leaving only a crash report behind. The
config check runs a fake Hyprland, except in the last tests, which use the
real `Hyprland --verify-config` on the shipped config. The fakes take their
behaviour from files because the check clears the environment.

Run from the repo root:  python3 Scripts/tests/session/test_session.py
"""

import os
import shutil
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "theme-security"))
from sandbox import LIB, REPO, Sandbox  # noqa: E402

SESSION = LIB / "session.sh"
LAUNCHER = REPO / "Source/session/hyprion-session"
HYPRLAND = shutil.which("Hyprland", path="/usr/bin:/bin")
SAFE_MODE = "-- --safe-mode"


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.box = Sandbox()
        (self.box.bin / "timeout").symlink_to(shutil.which("timeout", path="/usr/bin:/bin"))
        self.crash_dir = self.box.cache / "hyprland"
        self.state_dir = self.box.state / "hyde/session"
        # PATH is empty inside the check, so only builtins: $(<file), not cat.
        self.fake_hyprland = self.script("fake-Hyprland", f"""
            {{ printf 'PATH=%s\\n' "$PATH"
               printf 'XDG_RUNTIME_DIR=%s\\n' "$XDG_RUNTIME_DIR"
               printf 'WAYLAND_DISPLAY=%s\\n' "${{WAYLAND_DISPLAY-unset}}"
               printf 'HYPRLAND_INSTANCE_SIGNATURE=%s\\n' "${{HYPRLAND_INSTANCE_SIGNATURE-unset}}"
            }} > '{self.box.root}/verify-env'
            case "$(<'{self.box.root}/verify-mode')" in
                ok) echo "config ok"; exit 0 ;;
                error) echo "hyprland.lua:3: boom"; exit 1 ;;
                crash) kill -SEGV $$ ;;
            esac
        """)
        self.fake_start = self.script("fake-start-hyprland", f"""
            echo "$*" >> '{self.box.root}/starts'
            mode=$(<'{self.box.root}/session-mode')
            case "$*" in *--safe-mode*) mode=$(<'{self.box.root}/safe-mode-mode') ;; esac
            if [ "$mode" = crash ]; then
                mkdir -p '{self.crash_dir}'
                echo report > '{self.crash_dir}'/hyprlandCrashReport$$.txt
            fi
            exit 0
        """)
        self.set_mode(verify="ok", session="clean", safe_mode="clean")

    def tearDown(self):
        self.box.cleanup()

    def script(self, name, body):
        path = self.box.root / name
        path.write_text("#!/usr/bin/bash\n" + "\n".join(line.strip() for line in body.splitlines()) + "\n")
        path.chmod(0o755)
        return path

    def set_mode(self, verify=None, session=None, safe_mode=None):
        for name, value in (("verify-mode", verify), ("session-mode", session), ("safe-mode-mode", safe_mode)):
            if value:
                (self.box.root / name).write_text(value)

    def run_session(self, hyprland=None, program=SESSION):
        env = self.box.env(
            HYPRION_START_HYPRLAND=str(self.fake_start),
            HYPRION_HYPRLAND=str(hyprland or self.fake_hyprland),
            WAYLAND_DISPLAY="wayland-live",
            HYPRLAND_INSTANCE_SIGNATURE="live-session",
        )
        result = self.box.run(["bash" if program == SESSION else "sh", str(program)], env=env)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def starts(self):
        path = self.box.root / "starts"
        return path.read_text().splitlines() if path.exists() else []

    def session_log(self):
        return (self.state_dir / "session.log").read_text()

    def test_a_config_that_loads_starts_hyprland_once(self):
        self.run_session()
        self.assertEqual(self.starts(), [""])
        self.assertIn("session ended", self.session_log())

    def test_a_config_that_fails_starts_safe_mode(self):
        self.set_mode(verify="error")
        self.run_session()
        self.assertEqual(self.starts(), [SAFE_MODE])
        self.assertIn("boom", (self.state_dir / "verify.log").read_text())
        self.assertIn("config failed to load", self.session_log())

    def test_a_config_that_crashes_hyprland_starts_safe_mode(self):
        self.set_mode(verify="crash")
        self.run_session()
        self.assertEqual(self.starts(), [SAFE_MODE])

    def test_a_crashed_session_restarts_in_safe_mode(self):
        self.set_mode(session="crash")
        self.run_session()
        self.assertEqual(self.starts(), ["", SAFE_MODE])
        self.assertIn("Hyprland crashed", self.session_log())

    def test_safe_mode_is_tried_once(self):
        self.set_mode(session="crash", safe_mode="crash")
        self.run_session()
        self.assertEqual(self.starts(), ["", SAFE_MODE])

    def test_an_older_crash_report_is_ignored(self):
        self.crash_dir.mkdir(parents=True)
        old = self.crash_dir / "hyprlandCrashReport1234.txt"
        old.write_text("from last week\n")
        os.utime(old, (1_000_000_000, 1_000_000_000))
        self.run_session()
        self.assertEqual(self.starts(), [""])

    def test_the_check_cannot_reach_the_live_session(self):
        self.run_session()
        seen = dict(line.split("=", 1) for line in (self.box.root / "verify-env").read_text().splitlines())
        self.assertEqual(seen["WAYLAND_DISPLAY"], "unset")
        self.assertEqual(seen["HYPRLAND_INSTANCE_SIGNATURE"], "unset")
        self.assertNotEqual(seen["XDG_RUNTIME_DIR"], str(self.box.runtime))
        self.assertFalse(Path(seen["PATH"]).exists(), "the check's scratch dir was left behind")
        self.assertNotIn(str(self.box.bin), seen["PATH"])

    def test_without_hyprland_to_check_with_it_starts_normally(self):
        self.run_session(hyprland=self.box.root / "no-such-Hyprland")
        self.assertEqual(self.starts(), [""])

    def install_session(self, text):
        path = self.box.home / ".local/lib/hyde/session.sh"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        path.chmod(0o755)

    def test_the_launcher_runs_the_users_session_script(self):
        self.install_session(f"#!/usr/bin/bash\necho 'session.sh' >> '{self.box.root}/starts'\n")
        self.run_session(program=LAUNCHER)
        self.assertEqual(self.starts(), ["session.sh"])

    def test_the_launcher_falls_back_when_the_script_is_broken(self):
        self.install_session("#!/usr/bin/bash\nif then fi\n")
        self.run_session(program=LAUNCHER)
        self.assertEqual(self.starts(), [""])

    def test_the_launcher_falls_back_when_the_script_is_missing(self):
        self.run_session(program=LAUNCHER)
        self.assertEqual(self.starts(), [""])

    def real_config(self, extra=""):
        (self.box.home / ".local/lib").mkdir(parents=True)
        (self.box.home / ".local/lib/hyde").symlink_to(LIB)
        (self.box.data / "hypr").symlink_to(REPO / "Configs/.local/share/hypr")
        (self.box.config / "hypr").mkdir()
        stock = (REPO / "Configs/.config/hypr/hyprland.lua").read_text()
        (self.box.config / "hypr/hyprland.lua").write_text(stock + extra)

    @unittest.skipUnless(HYPRLAND, "Hyprland is not installed")
    def test_the_shipped_config_starts_normally(self):
        self.real_config()
        self.run_session(hyprland=HYPRLAND)
        self.assertEqual(self.starts(), [""])
        self.assertIn("config ok", (self.state_dir / "verify.log").read_text())

    @unittest.skipUnless(HYPRLAND, "Hyprland is not installed")
    def test_a_broken_user_config_starts_safe_mode(self):
        self.real_config('\nerror("broken at login")\n')
        self.run_session(hyprland=HYPRLAND)
        self.assertEqual(self.starts(), [SAFE_MODE])
        self.assertIn("broken at login", (self.state_dir / "verify.log").read_text())


if __name__ == "__main__":
    unittest.main()
