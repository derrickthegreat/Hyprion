"""Scripts/deploy_live.py replaces only what the repo produced and can undo it.

Each test builds a small repo with history (two commits plus worktree edits)
and a fake HOME, copies deploy_live.py into the repo, and runs it there. The
environment is built from scratch, so it never reaches the live session.

Run from the repo root:  python3 Scripts/tests/deploy/test_deploy_live.py
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
HYPRLAND = shutil.which("Hyprland", path="/usr/bin:/bin")

HYPRLAND_MANIFEST = """
[hyprland]
[[hyprland.files]]
action = "sync"
source_root = "Configs/.local/share/hypr"
target_root = "${XDG_DATA_HOME}/hypr"
paths = ["hyde.lua"]

[[hyprland.files]]
action = "preserve"
source_root = "Configs/.config/hypr"
target_root = "${XDG_CONFIG_HOME}/hypr"
paths = "hyprland.lua"
"""

WAYBAR_MANIFEST = """
[waybar]
[[waybar.files]]
action = "sync"
source_root = "Configs/.config/waybar"
target_root = "${XDG_CONFIG_HOME}/waybar"
paths = ["styles"]
ignored_paths = ["*.bak"]
"""

LSD_MANIFEST = """
[lsd]
[[lsd.files]]
action = "sync"
source_root = "Configs/.config/lsd"
target_root = "${XDG_CONFIG_HOME}/lsd"
paths = "config.yaml"
"""

STUB = 'dofile(os.getenv("XDG_DATA_HOME") .. "/hypr/hyde.lua")\n'


def hyde_lua(gaps):
    return f"HYDE_API = true\nhl.config({{ general = {{ gaps_in = {gaps} }} }})\n"


class DeployLiveTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="hyprion-deploy-")
        root = Path(self._tmp.name)
        self.repo, self.home, self.bin = root / "repo", root / "home", root / "bin"
        self.config, self.data = self.home / ".config", self.home / ".local/share"
        self.state = self.home / ".local/state"
        self.runtime = root / "run"
        for d in (self.repo, self.config, self.data, self.state, self.bin):
            d.mkdir(parents=True)
        self.runtime.mkdir(mode=0o700)
        self.build_repo()
        self.build_home()

    def tearDown(self):
        self._tmp.cleanup()

    def env(self, **extra):
        env = {
            "HOME": str(self.home),
            "XDG_CONFIG_HOME": str(self.config),
            "XDG_DATA_HOME": str(self.data),
            "XDG_STATE_HOME": str(self.state),
            "XDG_CACHE_HOME": str(self.home / ".cache"),
            "XDG_RUNTIME_DIR": str(self.runtime),
            "PATH": f"{self.bin}:/usr/bin:/bin",
            "LANG": "C.UTF-8",
            "GIT_CONFIG_NOSYSTEM": "1",
        }
        env.update(extra)
        return env

    def git(self, *args):
        subprocess.run(["git", "-c", "commit.gpgsign=false", "-c", "user.name=t", "-c", "user.email=t@t",
                        *args], cwd=self.repo, env=self.env(), check=True, capture_output=True)

    def put(self, rel, text, base=None):
        path = (base or self.repo) / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def build_repo(self):
        (self.repo / "Scripts").mkdir()
        shutil.copy2(REPO / "Scripts/deploy_live.py", self.repo / "Scripts/deploy_live.py")
        self.put("Scripts/dots/hyprland.toml", HYPRLAND_MANIFEST)
        self.put("Scripts/dots/waybar.toml", WAYBAR_MANIFEST)
        self.put("Scripts/dots/lsd.toml", LSD_MANIFEST)
        self.put("Configs/.config/hypr/hyprland.lua", STUB)
        self.put("Configs/.config/lsd/config.yaml", "lsd\n")
        self.put("Configs/.local/share/hypr/hyde.lua", hyde_lua(1))
        for name in ("a", "b"):
            self.put(f"Configs/.config/waybar/styles/{name}.css", f"{name} v1\n")
        self.git("init", "-q")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "v1")
        self.put("Configs/.local/share/hypr/hyde.lua", hyde_lua(2))
        for name in ("a", "b", "c"):
            self.put(f"Configs/.config/waybar/styles/{name}.css", f"{name} v2\n")
        self.put("Configs/.config/waybar/styles/d.bak", "backup\n")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "v2")

    def build_home(self):
        for dot in ("hyprland", "waybar"):
            self.put(f"deez/dots/{dot}.toml", f'name = "{dot}"\n', self.data)
        self.live_hyde = self.put("hypr/hyde.lua", hyde_lua(1), self.data)  # a stale deployed copy
        self.live_a = self.put("waybar/styles/a.css", "a v2\n", self.config)  # current
        self.live_b = self.put("waybar/styles/b.css", "b, edited by hand\n", self.config)
        self.live_c = self.config / "waybar/styles/c.css"  # new in v2
        self.live_user = self.put("hypr/hyprland.lua", STUB + "-- mine\n", self.config)

    def deploy(self, *args, **env):
        return subprocess.run([sys.executable, str(self.repo / "Scripts/deploy_live.py"), *args],
                              env=self.env(**env), capture_output=True, text=True, timeout=120)

    def backups(self):
        return sorted((self.state / "hyde/deploy/backups").glob("*"))

    def test_dry_run_writes_nothing(self):
        result = self.deploy("--no-verify")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("update (1):\n  ~/.local/share/hypr/hyde.lua", result.stdout)
        self.assertIn("new (1):\n  ~/.config/waybar/styles/c.css", result.stdout)
        self.assertIn("~/.config/waybar/styles/b.css", result.stdout.split("left alone")[1])
        self.assertEqual(self.live_hyde.read_text(), hyde_lua(1))
        self.assertFalse(self.live_c.exists())
        self.assertFalse((self.state / "hyde/deploy").exists())

    def test_apply_replaces_only_what_the_repo_produced(self):
        result = self.deploy("--apply", "--no-verify")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.live_hyde.read_text(), hyde_lua(2))
        self.assertEqual(self.live_c.read_text(), "c v2\n")
        self.assertEqual(self.live_b.read_text(), "b, edited by hand\n")
        self.assertEqual(self.live_user.read_text(), STUB + "-- mine\n")
        self.assertFalse((self.config / "waybar/styles/d.bak").exists())
        self.assertFalse((self.config / "lsd").exists())
        [backup] = self.backups()
        self.assertEqual((backup / "files/.local/share/hypr/hyde.lua").read_text(), hyde_lua(1))
        manifest = json.loads((backup / "manifest.json").read_text())
        self.assertEqual({f["path"]: f["existed"] for f in manifest["files"]},
                         {".local/share/hypr/hyde.lua": True, ".config/waybar/styles/c.css": False})
        self.assertEqual(list(self.live_hyde.parent.glob(".*hyprion-deploy")), [])

    def test_rollback_restores_and_removes(self):
        self.deploy("--apply", "--no-verify")
        result = self.deploy("--rollback")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.live_hyde.read_text(), hyde_lua(1))
        self.assertFalse(self.live_c.exists())
        self.assertEqual(self.live_b.read_text(), "b, edited by hand\n")

    def test_rollback_keeps_a_new_file_changed_since(self):
        self.deploy("--apply", "--no-verify")
        self.live_c.write_text("c, edited after the deploy\n")
        result = self.deploy("--rollback")
        self.assertIn("kept ~/.config/waybar/styles/c.css", result.stdout)
        self.assertEqual(self.live_c.read_text(), "c, edited after the deploy\n")

    def test_force_replaces_an_edit_and_backs_it_up(self):
        result = self.deploy("--apply", "--no-verify", "--force", str(self.live_b))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.live_b.read_text(), "b v2\n")
        [backup] = self.backups()
        self.assertEqual((backup / "files/.config/waybar/styles/b.css").read_text(), "b, edited by hand\n")

    def test_uncommitted_work_can_be_redeployed(self):
        # Not a committed version, but what the last deploy wrote: still ours.
        self.put("Configs/.config/waybar/styles/a.css", "a v3, uncommitted\n")
        self.deploy("--apply", "--no-verify")
        self.assertEqual(self.live_a.read_text(), "a v3, uncommitted\n")
        self.put("Configs/.config/waybar/styles/a.css", "a v4, uncommitted\n")
        result = self.deploy("--no-verify")
        self.assertIn("~/.config/waybar/styles/a.css  (uncommitted)", result.stdout.split("left alone")[0])

    def test_reload_is_paused_during_a_deploy_in_a_session(self):
        log = self.bin.parent / "hyprctl.log"
        fake = self.bin / "hyprctl"
        fake.write_text(
            "#!/bin/sh\n"
            f"echo \"$*\" >> '{log}'\n"
            'case "$*" in *getoption*) echo \'{"option": "misc:disable_autoreload", "bool": false}\';; esac\n'
        )
        fake.chmod(0o755)
        result = self.deploy("--apply", "--no-verify", HYPRLAND_INSTANCE_SIGNATURE="test")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(log.read_text().splitlines(), [
            "-j getoption misc:disable_autoreload",
            "eval hl.config({misc={disable_autoreload=true}})",
            "eval hl.config({misc={disable_autoreload=false}})",
            "reload config-only",
        ])

    @unittest.skipUnless(HYPRLAND, "Hyprland is not installed")
    def test_a_deploy_that_breaks_the_config_writes_nothing(self):
        self.put("Configs/.local/share/hypr/hyde.lua", 'error("broken deploy")\n')
        result = self.deploy("--apply")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("broken deploy", result.stderr)
        self.assertIn("Nothing was written", result.stderr)
        self.assertEqual(self.live_hyde.read_text(), hyde_lua(1))
        self.assertFalse(self.live_c.exists())
        self.assertEqual(self.backups(), [])

    @unittest.skipUnless(HYPRLAND, "Hyprland is not installed")
    def test_the_check_runs_the_users_own_config(self):
        # The new hyde.lua loads on its own; only the user's hyprland.lua needs HYDE_API.
        self.live_user.write_text(STUB + 'assert(HYDE_API, "my config needs HYDE_API")\n')
        self.put("Configs/.local/share/hypr/hyde.lua", "hl.config({ general = { gaps_in = 3 } })\n")
        result = self.deploy("--apply")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("my config needs HYDE_API", result.stderr)
        self.assertIn("your current one loads", result.stderr)
        self.assertEqual(self.live_hyde.read_text(), hyde_lua(1))

    @unittest.skipUnless(HYPRLAND, "Hyprland is not installed")
    def test_a_deploy_that_loads_goes_through(self):
        result = self.deploy("--apply")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("loads (Hyprland --verify-config)", result.stdout)
        self.assertEqual(self.live_hyde.read_text(), hyde_lua(2))


if __name__ == "__main__":
    unittest.main()
