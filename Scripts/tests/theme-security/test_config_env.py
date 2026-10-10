"""config.lua writes config.toml values into the shell env file as data.

Run from the repo root:  python3 Scripts/tests/theme-security/test_config_env.py
"""

import ast
import os
import shlex
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sandbox import LIB, Sandbox  # noqa: E402

# config.lua needs luafilesystem: HyDE's own Lua env, else a system install.
LFS_DIRS = [
    Path(os.path.expanduser("~/.local/state/hyde/lua_env/lib/lua/5.5")),
    Path("/usr/lib/lua/5.5"),
    Path("/usr/local/lib/lua/5.5"),
]
LFS_DIR = next((d for d in LFS_DIRS if (d / "lfs.so").exists()), None)

READ_ENV = f"""
source '{LIB}/globalcontrol.sh' >/dev/null 2>&1
for name in BATTERY_NOTIFY_EXECUTE_CRITICAL WEATHER_LOCATION SEC_DOLLAR SEC_TRAILING \\
    SEC_LITERAL SEC_QUOTE SEC_NEWLINE SEC_NUM SEC_FLOAT SEC_FLAG SEC_EMPTY WAYBAR_FONT; do
    printf '%s=%s\\0' "$name" "${{!name}}"
done
for path in "${{WALLPAPER_CUSTOM_PATHS[@]}}"; do printf 'PATH[]=%s\\0' "$path"; done
env | grep -c '^SEC_NUM=' | sed 's/^/exported=/'
"""


def m(marker):
    return f"touch {marker}"


def extract(path, *names, **namespace):
    """Compiles only the named top-level functions or classes of a script."""
    tree = ast.parse(Path(path).read_text())
    nodes = [n for n in tree.body if getattr(n, "name", None) in names]
    namespace.update({"os": os, "sys": sys, "shlex": shlex, "Path": Path})
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), "exec"), namespace)
    return namespace


@unittest.skipUnless(LFS_DIR, "luafilesystem is not installed")
class ConfigEnvTests(unittest.TestCase):
    def setUp(self):
        self.box = Sandbox()
        self.marker = self.box.root / "marker"
        self.env_file = self.box.state / "hyde/config"
        self.toml = self.box.config / "hyde/config.toml"
        self.toml.parent.mkdir(parents=True, exist_ok=True)
        mk = m(self.marker)
        self.toml.write_text(
            "[battery.notify]\n"
            f"execute_critical = 'notify-send \"Battery low; {mk}; true\"'\n"
            "[wallpaper]\n"
            f'custom_paths = ["$HOME/Pictures/Walls", "${{XDG_DATA_HOME}}/walls", "x $({mk}) `{mk}` y"]\n'
            "[weather]\n"
            "location = \"St John's\"\n"
            "[waybar]\n"
            "font = \"Font's Name\"\n"
            "[sec]\n"
            f'dollar = "cost $5, $({mk}) and ${{HOME:-$({mk})}}"\n'
            'trailing = "ends with $"\n'
            "literal = 'C:\\path\\to'\n"
            'quote = "say \\"hi\\""\n'
            'newline = "a\\nb"\n'
            "num = 42\n"
            "float = 0.5\n"
            "flag = true\n"
            'empty = ""\n'
            f'"bad;{mk}" = "x"\n'
        )
        self.lua_output = self.generate(self.toml, self.env_file)

    def generate(self, toml, env_file):
        env = self.box.env(LUA_CPATH=f"{LFS_DIR}/?.so;;")
        result = self.box.run(
            ["lua", str(LIB / "config.lua"), "--no-daemon", "--input", str(toml),
             "--env", str(env_file), "--hypr", str(self.box.state / "hyde/hyprland.conf"),
             "--hypr-env", str(self.box.state / "hyde/hypr.conf")],
            env=env,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(env_file.exists(), result.stdout + result.stderr)
        return result.stdout

    def tearDown(self):
        self.box.cleanup()

    def sourced(self):
        result = self.box.bash(READ_ENV)
        self.assertEqual(result.returncode, 0, result.stderr)
        values, paths = {}, []
        for item in result.stdout.split("\0"):
            if item.startswith("PATH[]="):
                paths.append(item[7:])
            elif "=" in item:
                key, value = item.split("=", 1)
                values[key.strip()] = value
        return values, paths

    def test_values_do_not_run_when_hyde_shell_sources_the_file(self):
        values, paths = self.sourced()
        self.assertFalse(self.marker.exists())
        mk = m(self.marker)
        self.assertEqual(values["BATTERY_NOTIFY_EXECUTE_CRITICAL"], f'notify-send "Battery low; {mk}; true"')
        self.assertEqual(values["SEC_DOLLAR"], f"cost $5, $({mk}) and ${{HOME:-$({mk})}}")
        self.assertEqual(paths[2], f"x $({mk}) `{mk}` y")

    def test_strings_survive_exactly(self):
        values, _ = self.sourced()
        self.assertEqual(values["WEATHER_LOCATION"], "St John's")
        self.assertEqual(values["WAYBAR_FONT"], "Font's Name")
        self.assertEqual(values["SEC_TRAILING"], "ends with $")
        self.assertEqual(values["SEC_LITERAL"], "C:\\path\\to")
        self.assertEqual(values["SEC_QUOTE"], 'say "hi"')
        self.assertEqual(values["SEC_NEWLINE"], "a\nb")
        self.assertEqual(values["SEC_EMPTY"], "")
        self.assertEqual(values["SEC_NUM"], "42")
        self.assertEqual(values["SEC_FLOAT"], "0.5")
        self.assertEqual(values["SEC_FLAG"], "true")
        self.assertEqual(values["exported"].strip(), "1")

    def test_variable_references_still_expand(self):
        # custom_paths = ["$HOME/..."] worked through the old double quotes
        _, paths = self.sourced()
        self.assertEqual(paths[0], f"{self.box.home}/Pictures/Walls")
        self.assertEqual(paths[1], f"{self.box.data}/walls")

    def test_a_key_that_is_not_a_variable_name_is_skipped(self):
        self.assertNotIn("bad;", self.env_file.read_text().upper().replace("BAD;", "bad;"))
        self.assertIn("Skipping SEC_BAD;", self.lua_output)
        self.sourced()
        self.assertFalse(self.marker.exists())

    def test_plain_values_keep_their_shape(self):
        lines = self.env_file.read_text().splitlines()
        self.assertIn("export SEC_NUM=42", lines)
        self.assertIn("export SEC_FLAG=true", lines)
        self.assertIn("export WEATHER_LOCATION='St John'\\''s'", lines)
        self.assertIn("export SEC_TRAILING='ends with $'", lines)

    def test_python_readers_get_the_plain_values(self):
        # These readers go line by line, so this config has no multi-line value
        mk = m(self.marker)
        text = "\n".join(line for line in self.toml.read_text().splitlines() if "newline" not in line)
        self.toml.write_text(text + "\n")
        self.generate(self.toml, self.env_file)
        for script in ("weather.py", "mediaplayer.py"):
            ns = extract(LIB / script, "shell_value", "load_env_file", logger=None)
            saved = dict(os.environ)
            try:
                ns["load_env_file"](self.env_file)
                self.assertEqual(os.environ["WEATHER_LOCATION"], "St John's", script)
                self.assertEqual(os.environ["SEC_DOLLAR"], f"cost $5, $({mk}) and ${{HOME:-$({mk})}}", script)
                self.assertEqual(os.environ["SEC_LITERAL"], "C:\\path\\to", script)
                self.assertEqual(os.environ["SEC_NUM"], "42", script)
            finally:
                os.environ.clear()
                os.environ.update(saved)

        cava = extract(LIB / "cava.py", "HydeConfig")["HydeConfig"]
        saved = os.environ.get("XDG_STATE_HOME")
        os.environ["XDG_STATE_HOME"] = str(self.box.state)
        try:
            config = cava().config
        finally:
            if saved is None:
                del os.environ["XDG_STATE_HOME"]
            else:
                os.environ["XDG_STATE_HOME"] = saved
        self.assertEqual(config["WEATHER_LOCATION"], "St John's")
        self.assertEqual(config["WALLPAPER_CUSTOM_PATHS"][0], "$HOME/Pictures/Walls")

        waybar = extract(LIB / "waybar.py", "get_config_value", HYDE_CONFIG=self.env_file)
        self.assertEqual(waybar["get_config_value"]("WAYBAR_FONT"), "Font's Name")
        self.assertEqual(waybar["get_config_value"]("SEC_NUM"), "42")

    def test_python_readers_still_read_the_old_format(self):
        old = self.box.root / "old-config"
        old.write_text('export WEATHER_LOCATION="Cape Town"\nexport SEC_NUM=7\nWAYBAR_FONT="Old Font"\n')
        for script in ("weather.py", "mediaplayer.py"):
            ns = extract(LIB / script, "shell_value", "load_env_file", logger=None)
            saved = dict(os.environ)
            try:
                ns["load_env_file"](old)
                self.assertEqual(os.environ["WEATHER_LOCATION"], "Cape Town", script)
                self.assertEqual(os.environ["SEC_NUM"], "7", script)
            finally:
                os.environ.clear()
                os.environ.update(saved)
        waybar = extract(LIB / "waybar.py", "get_config_value", HYDE_CONFIG=old)
        self.assertEqual(waybar["get_config_value"]("WAYBAR_FONT").strip('"'), "Old Font")


if __name__ == "__main__":
    unittest.main()
