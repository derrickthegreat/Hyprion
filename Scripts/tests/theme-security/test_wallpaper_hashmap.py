"""get_hashmap treats wallpaper paths and file types as data.

Run from the repo root:  python3 Scripts/tests/theme-security/test_wallpaper_hashmap.py
"""

import hashlib
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sandbox import LIB, Sandbox  # noqa: E402

DRIVER = f"""
source '{LIB}/globalcontrol.sh' >/dev/null
[ -n "$FILETYPES" ] && WALLPAPER_FILETYPES=("$FILETYPES")
get_hashmap "$@" --no-notify --skipstrays || exit 3
printf '%s\\0' "${{wallList[@]}}" >"$OUT_LIST"
printf '%s\\n' "${{wallHash[@]}}" >"$OUT_HASH"
"""


class HashmapTests(unittest.TestCase):
    def setUp(self):
        self.box = Sandbox()
        self.marker = self.box.root / "marker"

    def tearDown(self):
        self.box.cleanup()

    def hashmap(self, *sources, filetypes=""):
        out_list = self.box.root / "list"
        out_hash = self.box.root / "hash"
        env = self.box.env(OUT_LIST=str(out_list), OUT_HASH=str(out_hash), FILETYPES=filetypes)
        result = self.box.bash(DRIVER, *map(str, sources), env=env)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        names = out_list.read_bytes().decode().split("\0")[:-1]
        hashes = out_hash.read_text().split()
        return names, hashes

    def wall(self, folder, name, data=None):
        path = folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data if data is not None else name.encode())
        return path

    def test_hostile_file_names_are_listed_not_run(self):
        walls = self.box.root / "walls"
        m = self.marker
        hostile = [
            f"$(touch {m}).png",
            f"`touch {m}`.jpg",
            'quote".png',
            "single'quote.png",
            f"semi;touch {m};.png",
        ]
        expected = [self.wall(walls, n) for n in hostile]
        names, hashes = self.hashmap(walls)
        self.assertFalse(self.marker.exists())
        self.assertEqual(sorted(names), sorted(map(str, expected)))
        by_name = dict(zip(names, hashes))
        for path in expected:
            self.assertEqual(by_name[str(path)], hashlib.sha1(path.read_bytes()).hexdigest())

    def test_hostile_source_directory_is_searched_not_run(self):
        # The source itself comes from WALLPAPER_CUSTOM_PATHS or a theme name.
        walls = self.box.root / f'theme $(touch {self.marker}) "x"'
        wall = self.wall(walls, "a.png")
        names, _ = self.hashmap(walls)
        self.assertFalse(self.marker.exists())
        self.assertEqual(names, [str(wall)])

    def test_hostile_file_type_is_a_pattern_not_find_arguments(self):
        walls = self.box.root / "walls"
        self.wall(walls, "a.png")
        names, _ = self.hashmap(walls, filetypes=f'webp" -o -exec touch {self.marker} ; -o -name "x')
        self.assertFalse(self.marker.exists())
        self.assertEqual(names, [str(walls / "a.png")])

    def test_normal_names_keep_their_old_behaviour(self):
        walls = self.box.root / "Wallpapers"
        keep = [
            self.wall(walls, "b with space.png"),
            self.wall(walls, "a.jpg"),
            self.wall(walls, "UPPER.PNG"),
            self.wall(walls, "sub dir/c.jpeg"),
            self.wall(walls, "d.gif"),
        ]
        self.wall(walls, "notes.txt")
        self.wall(walls, "logo/skipped.png")
        names, hashes = self.hashmap(walls)
        # Sorted by path like `sort -k2`, which compares from the first blank on
        self.assertEqual(sorted(names), sorted(map(str, keep)))
        self.assertEqual(len(hashes), len(keep))

    def test_extra_file_types_from_config(self):
        walls = self.box.root / "walls"
        self.wall(walls, "a.webp")
        self.wall(walls, "b.png")
        names, _ = self.hashmap(walls, filetypes="webp")
        self.assertEqual(sorted(names), [str(walls / "a.webp"), str(walls / "b.png")])


class NoEvalTests(unittest.TestCase):
    def test_get_hashmap_has_no_eval(self):
        text = (LIB / "globalcontrol.sh").read_text()
        body = text[text.index("get_hashmap() {"):text.index("get_themes() {")]
        code = [line for line in body.splitlines() if not line.lstrip().startswith("#")]
        self.assertFalse([line for line in code if "eval" in line])


if __name__ == "__main__":
    unittest.main()
