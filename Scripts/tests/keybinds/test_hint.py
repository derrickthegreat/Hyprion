"""Checks that hint-hyprland.py turns Lua binds back into runnable commands.

hyprctl reports a Lua bind as "__lua" up to Hyprland 0.56 and as
"HL.Dispatcher(<name>)" or "function: 0x..." from 0.57. Each form has to reach
the combo->command cache hyde/binds.lua writes, or the hint menu can't run it.

Run from the repo root:  python3 Scripts/tests/keybinds/test_hint.py
"""

import importlib.util
import unittest
from pathlib import Path

HINT = Path(__file__).resolve().parents[3] / "Configs/.local/lib/hyde/keybinds/hint-hyprland.py"

spec = importlib.util.spec_from_file_location("hint_hyprland", HINT)
hint = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hint)

SUPER = 64
CACHE = {"SUPER + T": "hyde-shell app -t"}


def bind(dispatcher, arg="8", modmask=SUPER, key="T"):
    # The fields hyprctl binds -j gives a described bind, as Hyprland 0.57 prints them.
    return {
        "modmask": modmask,
        "submap": "",
        "key": key,
        "keycode": 0,
        "catch_all": False,
        "has_description": True,
        "description": "[Launcher|Apps] terminal emulator",
        "dispatcher": dispatcher,
        "arg": arg,
    }


def expand(*binds):
    binds = list(binds)
    hint.expand_meta_data(binds, dict(CACHE))
    return binds


class LuaBindTests(unittest.TestCase):
    def assertRunsCommand(self, dispatcher):
        (result,) = expand(bind(dispatcher))
        self.assertEqual(result["dispatcher"], 'hl.dsp.exec_cmd("hyde-shell app -t")')
        self.assertEqual(result["arg"], "")

    def test_hyprland_057_dispatcher_name(self):
        self.assertRunsCommand("HL.Dispatcher(exec_cmd)")

    def test_hyprland_057_lua_function(self):
        self.assertRunsCommand("function: 0x55d51b9a8440")

    def test_hyprland_056_lua_reference(self):
        self.assertRunsCommand("__lua")

    def test_lua_bind_missing_from_the_cache_is_left_alone(self):
        (result,) = expand(bind("HL.Dispatcher(move)", key="LEFT"))
        self.assertEqual(result["dispatcher"], "HL.Dispatcher(move)")
        self.assertEqual(result["arg"], "8")

    def test_plain_dispatcher_is_left_alone(self):
        (result,) = expand(bind("exec", arg="kitty"))
        self.assertEqual(result["dispatcher"], "exec")
        self.assertEqual(result["arg"], "kitty")


if __name__ == "__main__":
    unittest.main()
