"""The cursor theme reaches `hyprctl setcursor` as one argument, never as shell code.

The value comes from a downloaded theme's hypr.theme (through lua_state/ui.lua)
or from config.toml. lua_sinks.lua records the command strings HyDE's Lua hands
to Hyprland; each one is then run by sh in the sandbox against a fake hyprctl.

Run from the repo root:  python3 Scripts/tests/theme-security/test_cursor_quoting.py
"""

import shutil
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sandbox import LIB, REPO, Sandbox  # noqa: E402

HARNESS = Path(__file__).resolve().parent / "lua_sinks.lua"
LUA = shutil.which("lua", path="/usr/bin:/bin")


def lua_string(value):
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'


@unittest.skipUnless(LUA, "lua is not installed")
class CursorQuotingTests(unittest.TestCase):
    def setUp(self):
        self.box = Sandbox()
        self.marker = self.box.root / "marker"
        mk = f"touch {self.marker}"
        self.hostile = f"Bibata' ; {mk}; echo '$({mk}) `{mk}` \"x\""
        local = self.box.home / ".local"
        (local / "lib").mkdir(parents=True)
        (local / "lib/hyde").symlink_to(LIB)
        (self.box.data / "hypr").symlink_to(REPO / "Configs/.local/share/hypr")
        (self.box.state / "hyde/lua_state").mkdir(parents=True)
        self.exec_log = self.box.root / "exec.log"

    def tearDown(self):
        self.box.cleanup()

    def ui_state(self, cursor_theme, cursor_size="24"):
        (self.box.state / "hyde/lua_state/ui.lua").write_text(
            "return {ui = {cursor_theme = %s, cursor_size = %s}, wallbash = {mode = \"theme\"}}\n"
            % (lua_string(cursor_theme), cursor_size)
        )

    def recorded(self, mode, entry):
        result = self.box.run([LUA, str(HARNESS), mode, str(entry)], env=self.box.env(EXEC_LOG=str(self.exec_log)))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        commands = self.exec_log.read_text().split("\0")[:-1]
        return [c for c in commands if c.startswith("hyprctl setcursor")]

    def run_through_sh(self, commands):
        """What hl.exec_cmd and os.execute do with the string: sh -c."""
        self.assertTrue(commands, "no setcursor command was built")
        for cmd in commands:
            self.box.run(["sh", "-c", cmd])
        self.assertFalse(self.marker.exists(), commands)
        return [argv[1:] for argv in self.box.calls("hyprctl")]

    def hypr(self):
        return self.recorded("hypr", self.box.data / "hypr/hyde.lua")

    def test_theme_value_from_ui_state_is_one_argument(self):
        self.ui_state(self.hostile)
        calls = self.run_through_sh(self.hypr())
        # dynamic.lua on every reload, start_up.lua once at start
        self.assertEqual(calls, [["setcursor", self.hostile, "24"]] * 2)

    def test_theme_value_from_config_toml_is_one_argument(self):
        self.ui_state("Bibata-Modern-Ice")
        toml = self.box.config / "hyde/config.toml"
        toml.write_text(
            "[desktop.ui]\n"
            f"cursor_theme = {lua_string(self.hostile)}\n"
            f'cursor_size = "32; touch {self.marker}"\n'
        )
        calls = self.run_through_sh(self.hypr())
        self.assertIn(["setcursor", self.hostile, f"32; touch {self.marker}"], calls)

    def test_plain_cursor_theme_is_unchanged(self):
        self.ui_state("Bibata-Modern-Ice", "32")
        commands = self.hypr()
        self.assertIn("hyprctl setcursor 'Bibata-Modern-Ice' '32'", commands)
        self.assertEqual(self.run_through_sh(commands)[0], ["setcursor", "Bibata-Modern-Ice", "32"])

    def test_dconf_setcursor_is_one_argument(self):
        self.ui_state(self.hostile)
        calls = self.run_through_sh(self.recorded("dconf", LIB / "color/dconf.lua"))
        self.assertEqual(calls, [["setcursor", self.hostile, "24"]])

    def test_dconf_skips_setcursor_without_a_theme(self):
        (self.box.state / "hyde/lua_state/ui.lua").write_text("return {ui = {}}\n")
        self.assertEqual(self.recorded("dconf", LIB / "color/dconf.lua"), [])


if __name__ == "__main__":
    unittest.main()
