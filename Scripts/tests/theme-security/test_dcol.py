"""A theme's theme.dcol is read as colour data, never run.

Run from the repo root:  python3 Scripts/tests/theme-security/test_dcol.py
"""

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sandbox import LIB, Sandbox  # noqa: E402

LOADER = f"""
source '{LIB}/globalcontrol.sh' >/dev/null
[ "$2" = export ] && set -a
load_dcol "$1"
set +a
for name in dcol_mode dcol_pry1 dcol_pry2 dcol_pry3 dcol_pry4 dcol_txt1 dcol_txt1_rgba \\
    dcol_pry1_rgba dcol_1xa1 dcol_1xa1_rgba dcol_4xa9 dcol_4xa9_rgba dcol_pry2_rgb; do
    [ -n "${{!name+x}}" ] && printf '%s=%s\\n' "$name" "${{!name}}"
done
printf 'PATH=%s\\n' "$PATH"
env | grep '^dcol_' | sed 's/^/env:/'
"""


class LoadDcolTests(unittest.TestCase):
    def setUp(self):
        self.box = Sandbox()
        self.markers = [self.box.root / f"marker{i}" for i in range(1, 8)]

    def tearDown(self):
        self.box.cleanup()

    def load(self, text, export=False):
        dcol = self.box.root / "theme.dcol"
        dcol.write_bytes(text.encode())
        result = self.box.bash(LOADER, str(dcol), "export" if export else "")
        self.assertEqual(result.returncode, 0, result.stderr)
        values, exported = {}, set()
        for line in result.stdout.splitlines():
            if line.startswith("env:"):
                exported.add(line[4:].split("=", 1)[0])
            else:
                key, value = line.split("=", 1)
                values[key] = value
        return values, exported, result.stderr

    def malicious(self):
        m = [str(p) for p in self.markers]
        return (
            'dcol_mode="dark"\n'
            f'dcol_pry1="$(touch {m[0]})"\n'
            f"dcol_pry2=`touch {m[1]}`\n"
            f"touch {m[2]}\n"
            f'dcol_pry3="FF0000|g;e touch {m[3]};s|x|"\n'
            'PATH="/evil"\n'
            f'dcol_txt1_rgba="rgba(1,2,3,\\1)$(touch {m[4]})"\n'
            f'dcol_1xa1="ABCDEF"; touch {m[5]}\n'
            f'dcol_mode="dark\nlight"; touch {m[6]}\n'
            'dcol_pry4="112233"\n'
            'dcol_txt1="FFFFFF"\n'
            'dcol_pry1_rgba="rgba(25,25,25,\\1)"\n'
        )

    def test_the_fixture_runs_code_when_sourced(self):
        # Control: this is what color.set.sh's `source` did with the same file.
        dcol = self.box.root / "theme.dcol"
        dcol.write_text(self.malicious())
        self.box.bash('set -a; source "$1" 2>/dev/null; true', str(dcol))
        self.assertTrue(any(p.exists() for p in self.markers))

    def test_code_in_a_theme_dcol_does_not_run(self):
        values, _, stderr = self.load(self.malicious(), export=True)
        self.assertEqual([p.name for p in self.markers if p.exists()], [])
        self.assertNotIn("/evil", values["PATH"])
        self.assertIn("ignored line(s) 2 3 4 5 6 7 8 9 10 of", stderr)

    def test_only_valid_colours_are_taken(self):
        values, _, _ = self.load(self.malicious())
        self.assertEqual(values["dcol_mode"], "dark")
        self.assertEqual(values["dcol_pry4"], "112233")
        self.assertEqual(values["dcol_txt1"], "FFFFFF")
        self.assertEqual(values["dcol_pry1_rgba"], "rgba(25,25,25,\\1)")
        for key in ("dcol_pry1", "dcol_pry2", "dcol_pry3", "dcol_txt1_rgba", "dcol_1xa1"):
            self.assertNotIn(key, values)

    def test_wallbash_output_loads_unchanged(self):
        # What wallbash.sh writes, as in Graphite Mono's theme.dcol.
        values, _, stderr = self.load(
            'dcol_mode="light"\n'
            'dcol_pry1="191919"\n'
            'dcol_pry1_rgba="rgba(25,25,25,\\1)"\n'
            'dcol_1xa1="1a1a1a"\n'
            'dcol_1xa1_rgba="rgba(26,26,26,\\1)"\n'
            'dcol_4xa9="E5E5E5"\n'
            'dcol_4xa9_rgba="rgba(229,229,229,\\1)"\n'
        )
        self.assertEqual(stderr.strip(), "")
        self.assertEqual(values["dcol_mode"], "light")
        self.assertEqual(values["dcol_pry1"], "191919")
        self.assertEqual(values["dcol_pry1_rgba"], "rgba(25,25,25,\\1)")
        self.assertEqual(values["dcol_1xa1"], "1a1a1a")
        self.assertEqual(values["dcol_4xa9_rgba"], "rgba(229,229,229,\\1)")

    def test_hand_written_theme_formats_load(self):
        # Fixed alpha (Vanta Black), color.shuffle.py's 1.00, CRLF, other quoting,
        # comments, an _rgb triplet and a last line without a newline.
        values, _, stderr = self.load(
            "# exported from a theme editor\r\n"
            "\r\n"
            "dcol_mode='dark'\r\n"
            "dcol_pry1=000000\r\n"
            'dcol_pry1_rgba="rgba(0,0,0,1)"\r\n'
            'dcol_txt1_rgba="rgba(229,229,229,1.00)"\r\n'
            'dcol_pry2_rgb="26,26,26"\r\n'
            'dcol_4xa9="E5E5E5"'
        )
        self.assertEqual(stderr.strip(), "")
        self.assertEqual(values["dcol_mode"], "dark")
        self.assertEqual(values["dcol_pry1"], "000000")
        self.assertEqual(values["dcol_pry1_rgba"], "rgba(0,0,0,1)")
        self.assertEqual(values["dcol_txt1_rgba"], "rgba(229,229,229,1.00)")
        self.assertEqual(values["dcol_pry2_rgb"], "26,26,26")
        self.assertEqual(values["dcol_4xa9"], "E5E5E5")

    def test_an_empty_colour_is_kept_empty(self):
        # wallbash.sh writes "" when magick fails; source assigned it as such.
        values, _, stderr = self.load('dcol_txt1=""\n')
        self.assertEqual(stderr.strip(), "")
        self.assertEqual(values["dcol_txt1"], "")

    def test_exported_only_under_set_a(self):
        _, exported, _ = self.load('dcol_pry1="191919"\n', export=True)
        self.assertIn("dcol_pry1", exported)
        _, exported, _ = self.load('dcol_pry1="191919"\n')
        self.assertNotIn("dcol_pry1", exported)


class NoSourcedDcolTests(unittest.TestCase):
    def test_no_script_sources_a_dcol(self):
        sourced = re.compile(r"(^|[;&|{(]\s*|\s)(source|\.)\s+\S*dcol", re.M)
        for name in ("color.set.sh", "logoutlaunch.sh"):
            text = (LIB / name).read_text()
            self.assertIsNone(sourced.search(text), f"{name} still sources a .dcol")


if __name__ == "__main__":
    unittest.main()
