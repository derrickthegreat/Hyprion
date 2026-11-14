"""Tests for the shell and Python rofi position helpers against rofi 2.0 and 2.1.

rofi 2.1 reads x-offset/y-offset as pointing inward from an east or south
anchor; 2.0 read them as screen right/down. pos.lua has its own Lua test.

Run from the repo root:  python3 Scripts/tests/rofi-pos/test_rofi_pos.py
"""

import importlib.util
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HYDE = Path(__file__).resolve().parents[3] / "Configs/.local/lib/hyde"
BASH = shutil.which("bash")

# 5120x1440 ultrawide with a 38px bar on top.
MONITORS = [
    {
        "name": "DP-1",
        "focused": True,
        "width": 5120,
        "height": 1440,
        "scale": 1.0,
        "x": 0,
        "y": 0,
        "transform": 0,
        "reserved": [0, 38, 0, 0],
    }
]

# Pulls just the functions get_rofi_pos needs out of globalcontrol.sh, which
# does far more than define functions when sourced.
SHELL_DRIVER = r"""
source <(sed -n '/^get_monitor_scale() {/,/^}/p;/^rofi_edge_sign() {/,/^}/p;/^get_rofi_pos() {/,/^}/p' "$GLOBALCONTROL")
get_rofi_pos
"""


def load_compositor():
    spec = importlib.util.spec_from_file_location("hyde_compositor", HYDE / "pyutils/compositor.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ShellRofiPosTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.bin = Path(self.tmp.name)
        hyprctl = self.bin / "hyprctl"
        hyprctl.write_text(
            "#!/bin/bash\n"
            'case "$*" in\n'
            '  "cursorpos -j") printf \'{"x": %s, "y": %s}\' "$CURSOR_X" "$CURSOR_Y" ;;\n'
            '  "-j monitors") printf "%s" "$MONITORS_JSON" ;;\n'
            "  *) exit 1 ;;\n"
            "esac\n"
        )
        rofi = self.bin / "rofi"
        rofi.write_text('#!/bin/bash\n[ -n "$ROFI_VERSION" ] || exit 1\necho "Version: $ROFI_VERSION"\n')
        hyprctl.chmod(0o755)
        rofi.chmod(0o755)

    def tearDown(self):
        self.tmp.cleanup()

    def run_pos(self, cursor, rofi_version):
        env = {
            "PATH": f"{self.bin}:{os.environ['PATH']}",
            "HYPRLAND_INSTANCE_SIGNATURE": "test",
            "GLOBALCONTROL": str(HYDE / "globalcontrol.sh"),
            "MONITORS_JSON": json.dumps(MONITORS),
            "CURSOR_X": str(cursor[0]),
            "CURSOR_Y": str(cursor[1]),
            "ROFI_VERSION": rofi_version,
        }
        result = subprocess.run([BASH, "-c", SHELL_DRIVER], env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def test_rofi_21_east_offset_points_inward(self):
        self.assertEqual(
            self.run_pos((4900, 20), "2.1.1-dirty"),
            "window{location:east north;anchor:east north;x-offset:220px;y-offset:-18px;}",
        )

    def test_rofi_20_east_offset_points_left(self):
        self.assertEqual(
            self.run_pos((4900, 20), "2.0.0"),
            "window{location:east north;anchor:east north;x-offset:-220px;y-offset:-18px;}",
        )

    def test_rofi_21_south_offset_points_inward(self):
        self.assertEqual(
            self.run_pos((100, 1400), "2.1.1"),
            "window{location:west south;anchor:west south;x-offset:100px;y-offset:40px;}",
        )

    def test_unreadable_version_keeps_old_direction(self):
        self.assertEqual(
            self.run_pos((100, 1400), ""),
            "window{location:west south;anchor:west south;x-offset:100px;y-offset:-40px;}",
        )


class PythonRofiPosTests(unittest.TestCase):
    def setUp(self):
        self.compositor = load_compositor()

    def pos(self, cursor, inward):
        replies = {"j/cursorpos": json.dumps({"x": cursor[0], "y": cursor[1]}), "j/monitors": json.dumps(MONITORS)}
        with mock.patch.object(self.compositor.HyprctlWrapper, "_send", side_effect=replies.__getitem__), \
                mock.patch.object(self.compositor, "_installed_rofi_offsets_inward", return_value=inward):
            return self.compositor.HyprctlWrapper.get_rofi_pos()

    def test_version_parsing(self):
        inward = self.compositor.rofi_offsets_inward
        self.assertTrue(inward("Version: 2.1.1-dirty"))
        self.assertTrue(inward("Version: 3.0.0"))
        self.assertFalse(inward("Version: 2.0.0"))
        self.assertFalse(inward("Version: 1.7.5+wayland3"))
        self.assertFalse(inward(""))

    def test_rofi_21_offsets_point_inward(self):
        self.assertEqual(
            self.pos((4900, 1400), inward=True),
            "window{location:east south;anchor:east south;x-offset:220px;y-offset:40px;}",
        )

    def test_rofi_20_offsets_point_left_and_up(self):
        self.assertEqual(
            self.pos((4900, 1400), inward=False),
            "window{location:east south;anchor:east south;x-offset:-220px;y-offset:-40px;}",
        )


if __name__ == "__main__":
    unittest.main()
