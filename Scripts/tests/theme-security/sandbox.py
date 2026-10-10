"""A fake HOME and a PATH of shims for running HyDE shell code in tests.

The code under test can reach hyprctl, sudo, notify-send or a package manager.
PATH here holds only links to plain tools plus fakes that log their arguments
and exit, so nothing touches the live session or the system. The environment
is built from scratch: no HYPRLAND_INSTANCE_SIGNATURE, no D-Bus address.
"""

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
LIB = REPO / "Configs/.local/lib/hyde"
BIN = REPO / "Configs/.local/bin"

SAFE_TOOLS = [
    "bash", "sh", "env", "cat", "grep", "sed", "awk", "find", "sort", "head", "tail",
    "cut", "tr", "mkdir", "rm", "rmdir", "cp", "mv", "ln", "chmod", "readlink",
    "realpath", "dirname", "basename", "mktemp", "sha1sum", "touch", "id", "tar",
    "gzip", "wc", "xargs", "ls", "stat", "date", "uniq", "paste", "which", "sleep",
    "true", "false", "tee", "printf", "lua",
]
# Anything that talks to the compositor, the system or the network.
FAKE_TOOLS = [
    "hyprctl", "notify-send", "sudo", "doas", "pkexec", "pacman", "paru", "yay",
    "systemctl", "hyde-shell", "hydectl", "hyprland", "Hyprland", "hyde-ipc", "uwsm",
    "dbus-send", "magick", "parallel", "xdg-user-dir", "curl", "wget", "jq", "hyq",
    "gsettings", "dconf", "swww", "awww",
]
SYSTEM_PATH = "/usr/bin:/bin"


class Sandbox:
    def __init__(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="hyde-sec-")
        self.root = Path(self._tmp.name)
        self.home = self.root / "home"
        self.config = self.home / ".config"
        self.data = self.home / ".local/share"
        self.cache = self.home / ".cache"
        self.state = self.home / ".local/state"
        self.runtime = self.root / "run"
        self.bin = self.root / "bin"
        self.log = self.root / "calls.log"
        for d in (self.config, self.data, self.cache, self.state, self.runtime, self.bin):
            d.mkdir(parents=True)
        (self.config / "hyde/themes").mkdir(parents=True)
        self.runtime.chmod(0o700)
        self.log.touch()
        for tool in SAFE_TOOLS:
            found = shutil.which(tool, path=SYSTEM_PATH)
            if found:
                (self.bin / tool).symlink_to(found)
        for tool in FAKE_TOOLS:
            self.fake(tool)

    def cleanup(self):
        self._tmp.cleanup()

    def fake(self, name, body=""):
        """Replaces a command with one that logs its argv, then runs body."""
        script = (
            "#!/usr/bin/bash\n"
            f"{{ printf '%s' \"${{0##*/}}\"; printf '\\x1f%s' \"$@\"; printf '\\n'; }} >>'{self.log}'\n"
            f"{body}\n"
        )
        path = self.bin / name
        if path.exists() or path.is_symlink():
            path.unlink()
        path.write_text(script)
        path.chmod(0o755)

    def calls(self, name=None):
        """Logged fake-command calls as argv lists, optionally for one command."""
        out = []
        for line in self.log.read_text().splitlines():
            argv = line.split("\x1f")
            if name is None or argv[0] == name:
                out.append(argv)
        return out

    def env(self, **extra):
        env = {
            "PATH": str(self.bin),
            "HOME": str(self.home),
            "USER": "tester",
            "LANG": "C.UTF-8",
            "XDG_CONFIG_HOME": str(self.config),
            "XDG_DATA_HOME": str(self.data),
            "XDG_CACHE_HOME": str(self.cache),
            "XDG_STATE_HOME": str(self.state),
            "XDG_RUNTIME_DIR": str(self.runtime),
            "TMPDIR": str(self.root),
        }
        env.update(extra)
        return env

    def run(self, args, cwd=None, env=None, **kwargs):
        return subprocess.run(
            args,
            cwd=cwd or self.root,
            env=env or self.env(),
            capture_output=True,
            text=True,
            timeout=120,
            **kwargs,
        )

    def bash(self, script, *args, **kwargs):
        """Runs a bash script written to the sandbox root (not next to test data)."""
        path = self.root / "driver.sh"
        path.write_text(script)
        return self.run(["bash", str(path), *args], **kwargs)
