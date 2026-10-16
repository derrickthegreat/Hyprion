"""Checks how weather.py fills [weather] location_format from wttr.in's nearest_area.

Run from the repo root:  python3 Scripts/tests/waybar/test_weather.py
"""

import ast
import unittest
from pathlib import Path
from typing import TypedDict, cast

ROOT = Path(__file__).resolve().parents[3]
WEATHER = ROOT / "Configs/.local/lib/hyde/weather.py"


def extract(*names):
    """Compiles only the named top-level definitions, so the test doesn't need requests."""
    tree = ast.parse(WEATHER.read_text())
    nodes = [n for n in tree.body if getattr(n, "name", None) in names or _assigns(n, names)]
    namespace = {"cast": cast, "TypedDict": TypedDict}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(WEATHER), "exec"), namespace)
    return namespace


def _assigns(node, names):
    return isinstance(node, ast.Assign) and any(getattr(t, "id", None) in names for t in node.targets)


def response(city="Boca Raton", region="Florida", country="United States of America"):
    area = {"areaName": [{"value": city}], "country": [{"value": country}]}
    if region is not None:
        area["region"] = [{"value": region}]
    return {"nearest_area": [area]}


class LocationFormatTests(unittest.TestCase):
    def setUp(self):
        ns = extract("DEFAULT_LOCATION_FORMAT", "get_area_value", "get_location_name")
        self.name = ns["get_location_name"]
        self.default = ns["DEFAULT_LOCATION_FORMAT"]

    def test_default_keeps_the_old_text(self):
        self.assertEqual(self.name(response(), self.default), "Boca Raton, United States of America")

    def test_city_and_region(self):
        self.assertEqual(self.name(response(), "{city}, {region}"), "Boca Raton, Florida")

    def test_literal_text_and_any_order(self):
        self.assertEqual(self.name(response(), "{region} / {city}"), "Florida / Boca Raton")

    def test_unknown_placeholder_falls_back_to_default(self):
        self.assertEqual(self.name(response(), "{city}, {state}"), "Boca Raton, United States of America")

    def test_unparseable_format_falls_back_to_default(self):
        for fmt in ("{city", "{0}", "{city.nope}"):
            self.assertEqual(self.name(response(), fmt), "Boca Raton, United States of America", fmt)

    def test_missing_region_leaves_no_dangling_comma(self):
        self.assertEqual(self.name(response(region=None), "{city}, {region}"), "Boca Raton")
        self.assertEqual(self.name(response(region=""), "{city}, {region}"), "Boca Raton")


if __name__ == "__main__":
    unittest.main()
