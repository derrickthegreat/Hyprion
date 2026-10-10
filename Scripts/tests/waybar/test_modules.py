"""Checks that module click and scroll commands survive a Waybar reload.

Waybar runs each on-click / on-scroll command in its own process group and, when a
reload (SIGUSR2, sent on every theme or wallpaper change) destroys the module,
SIGTERMs that whole group. Anything meant to outlive the click has to leave the
group with `setsid -f`. menu-actions aren't tracked that way, so they're exempt.

Run from the repo root:  python3 Scripts/tests/waybar/test_modules.py
"""

import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
WAYBAR_DIRS = [ROOT / "Configs/.local/share/waybar", ROOT / "Configs/.config/waybar"]

# Commands that finish in a moment, or detach on their own, and may stay in the group.
QUICK_PROGRAMS = {"playerctl", "dunstctl", "swaync-client", "pkill", "hyprctl", "sleep"}
QUICK_HYDE_SCRIPTS = {
    "volumecontrol",
    "brightnesscontrol",
    "hyprsunset",  # starts the daemon through `hyprctl dispatch exec`
    "caffeine",  # detaches its inhibitor itself
    "gamemode",
    "gpuinfo",
    "keyboardswitch",
    "sensorsinfo",
}
OPERATORS = {";", "&&", "||", "|", "&"}


def strip_jsonc(text):
    out, i, n, in_str = [], 0, len(text), False
    while i < n:
        c = text[i]
        if in_str:
            out.append(c)
            if c == "\\":
                out.append(text[i + 1])
                i += 1
            elif c == '"':
                in_str = False
        elif c == '"':
            in_str = True
            out.append(c)
        elif text.startswith("//", i):
            while i < n and text[i] != "\n":
                i += 1
            continue
        elif text.startswith("/*", i):
            i = text.index("*/", i) + 2
            continue
        else:
            out.append(c)
        i += 1
    return re.sub(r",(\s*[}\]])", r"\1", "".join(out))


def config_files():
    for base in WAYBAR_DIRS:
        yield from sorted(p for p in base.rglob("*.json*") if p.suffix in (".json", ".jsonc"))


def tracked_commands():
    """Yield (file, module, key, command) for every command Waybar killpg()s on reload."""
    for path in config_files():
        data = json.loads(strip_jsonc(path.read_text()))
        for module, conf in data.items():
            # wlr/taskbar reads on-click as a taskbar action (activate, close), not a command
            if not isinstance(conf, dict) or module.startswith("wlr/taskbar"):
                continue
            for key, value in conf.items():
                if key.startswith(("on-click", "on-scroll")) and isinstance(value, str):
                    yield path.relative_to(ROOT), module, key, value


def tokens(command):
    lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    return list(lexer)


def segments(toks):
    seg = []
    for tok in toks:
        if tok in OPERATORS:
            yield seg
            seg = []
        else:
            seg.append(tok)
    yield seg


def is_quick(toks):
    for seg in segments(toks):
        if not seg:
            return False
        if seg[0] == "hyde-shell":
            if len(seg) < 2 or seg[1] not in QUICK_HYDE_SCRIPTS:
                return False
        elif seg[0] not in QUICK_PROGRAMS:
            return False
    return True


def is_detached(toks):
    # A leading "sleep 0.1 &&" lets the click release before a menu grabs the pointer.
    if toks[:1] == ["sleep"] and toks[2:3] == ["&&"]:
        toks = toks[3:]
    # Everything after setsid -f must be one command: `setsid -f a || b` only detaches a.
    return toks[:2] == ["setsid", "-f"] and len(toks) > 2 and not OPERATORS & set(toks)


class ModuleCommandTests(unittest.TestCase):
    def test_config_files_parse(self):
        for path in config_files():
            with self.subTest(path=str(path.relative_to(ROOT))):
                json.loads(strip_jsonc(path.read_text()))

    def test_long_running_commands_are_detached(self):
        checked = 0
        for path, module, key, command in tracked_commands():
            checked += 1
            toks = tokens(command)
            with self.subTest(file=str(path), module=module, key=key):
                self.assertTrue(
                    is_detached(toks) or is_quick(toks),
                    f"{command!r} would be killed by the next Waybar reload; "
                    "prefix it with `setsid -f` (wrap chains in sh -c '...') "
                    "or add it to the quick list if it really ends at once",
                )
        self.assertGreater(checked, 50)

    def test_known_launchers_are_detached(self):
        # The cases that were killed: pacman under the Updates terminal, a theme switch
        # cut short by its own reload, pavucontrol and nwg-displays closing.
        expected = {
            ("custom/updates", "on-click"),
            ("custom/theme", "on-click"),
            ("custom/theme", "on-click-right"),
            ("custom/theme", "on-click-middle"),
            ("custom/wallchange", "on-click"),
            ("image#wallpaper", "on-click"),
            ("image#wallpaper", "on-click-right"),
            ("pulseaudio", "on-click"),
            ("pulseaudio#microphone", "on-click"),
            ("custom/display", "on-click"),
            ("custom/github_hyde", "on-click"),
        }
        found = {(m, k) for _, m, k, c in tracked_commands() if is_detached(tokens(c))}
        self.assertEqual(expected - found, set())

    def test_rules(self):
        self.assertTrue(is_detached(tokens("setsid -f nwg-displays")))
        self.assertTrue(is_detached(tokens("sleep 0.1 && setsid -f hyde-shell cliphist -c")))
        self.assertTrue(is_detached(tokens("setsid -f sh -c 'pavucontrol-qt -t 3 || pavucontrol -t 3'")))
        self.assertFalse(is_detached(tokens("setsid -f pavucontrol-qt -t 3 || pavucontrol -t 3")))
        self.assertFalse(is_detached(tokens("hyde-shell app -t scope -- theme.switch.sh -n")))
        self.assertTrue(is_quick(tokens("sleep 0.1 && dunstctl history-pop")))
        self.assertFalse(is_quick(tokens("hyde-shell volumecontrol -o i; pavucontrol")))


@unittest.skipUnless(shutil.which("setsid"), "setsid is not installed")
class KillpgTests(unittest.TestCase):
    """Reproduces what Waybar does to an on-click: own group via setpgid, then killpg."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.pidfile = Path(self.tmp.name) / "pid"

    def tearDown(self):
        try:
            os.kill(int(self.pidfile.read_text()), signal.SIGKILL)
        except (FileNotFoundError, ProcessLookupError, ValueError):
            pass
        self.tmp.cleanup()

    def survives_killpg(self, command):
        child = subprocess.Popen(["/bin/sh", "-c", command], process_group=0)
        for _ in range(100):
            if self.pidfile.exists() and self.pidfile.read_text().strip():
                break
            time.sleep(0.02)
        launched = int(self.pidfile.read_text())
        try:
            os.killpg(child.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass  # `setsid -f` had already returned and the group was empty
        child.wait()
        time.sleep(0.1)
        try:
            os.kill(launched, 0)
            with open(f"/proc/{launched}/stat") as stat:
                return stat.read().split(") ")[1].split()[0] != "Z"
        except ProcessLookupError:
            return False

    def test_plain_on_click_dies_with_the_reload(self):
        self.assertFalse(self.survives_killpg(f"sh -c 'echo $$ >{self.pidfile}; exec sleep 30'"))

    def test_setsid_on_click_survives_the_reload(self):
        self.assertTrue(self.survives_killpg(f"setsid -f sh -c 'echo $$ >{self.pidfile}; exec sleep 30'"))


if __name__ == "__main__":
    unittest.main()
