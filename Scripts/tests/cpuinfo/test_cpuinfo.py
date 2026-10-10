"""Tests for cpuinfo.sh's cache file under $XDG_RUNTIME_DIR.

Run from the repo root:  python3 Scripts/tests/cpuinfo/test_cpuinfo.py
"""

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[3] / "Configs/.local/lib/hyde/cpuinfo.sh"
BASH = shutil.which("bash")
# The only real tools cpuinfo.sh runs; everything else on PATH is a stub.
TOOLS = ("awk", "cat", "head", "sed", "perl", "mv")

LSCPU_VM = "Model name:                              AMD Ryzen 9 7950X3D 16-Core Processor\n"
LSCPU_HOST = LSCPU_VM + "CPU max MHz:                             5759.0000\nCPU min MHz:  545.0000\n"


class CpuinfoCacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.runtime = root / "run"
        self.runtime.mkdir()
        self.bin = root / "bin"
        self.bin.mkdir()
        for tool in TOOLS:
            (self.bin / tool).symlink_to(shutil.which(tool))
        self.calls = root / "lscpu-calls"
        lscpu = self.bin / "lscpu"
        lscpu.write_text('#!/bin/bash\nprintf "x\\n" >>"$LSCPU_CALLS"\nprintf "%s" "$LSCPU_TEXT"\n')
        sensors = self.bin / "sensors"
        sensors.write_text("#!/bin/bash\nexit 1\n")
        lscpu.chmod(0o755)
        sensors.chmod(0o755)
        self.cache = self.runtime / f"hyde-{os.getuid()}-processors"

    def tearDown(self):
        self.tmp.cleanup()

    def poll(self, lscpu_text=LSCPU_VM):
        env = {
            "PATH": str(self.bin),
            "HOME": self.tmp.name,
            "XDG_RUNTIME_DIR": str(self.runtime),
            "LSCPU_CALLS": str(self.calls),
            "LSCPU_TEXT": lscpu_text,
        }
        out = subprocess.run([BASH, str(SCRIPT)], env=env, capture_output=True, text=True)
        self.assertEqual((out.returncode, out.stderr), (0, ""))
        return json.loads(out.stdout)

    def lscpu_calls(self):
        return len(self.calls.read_text().splitlines()) if self.calls.exists() else 0

    def keys(self):
        return [line.split("=", 1)[0] for line in self.cache.read_text().splitlines()]

    def test_missing_max_mhz_is_looked_up_once(self):
        # What a VM hit: every poll re-ran lscpu and appended another CPUINFO_MAX_FREQ="".
        for _ in range(30):
            self.poll()
        self.assertEqual(sorted(self.keys()), ["CPUINFO_MAX_FREQ", "CPUINFO_MODEL", "CPUINFO_PREV_IDLE", "CPUINFO_PREV_STAT"])
        self.assertIn('CPUINFO_MAX_FREQ=""', self.cache.read_text().splitlines())
        self.assertEqual(self.lscpu_calls(), 2)

    def test_missing_model_is_looked_up_once(self):
        for _ in range(10):
            self.poll(lscpu_text="")
        self.assertEqual(len(self.keys()), 4)
        self.assertEqual(self.lscpu_calls(), 2)

    def test_bloated_file_is_repaired(self):
        self.cache.write_text(
            'CPUINFO_MODEL="AMD Ryzen 9 7950X3D 16-Core Processor"\n'
            'CPUINFO_MAX_FREQ=""\n'
            'CPUINFO_PREV_STAT="526023"\n'
            'CPUINFO_PREV_IDLE="7275578"\n' + 'CPUINFO_MAX_FREQ=""\n' * 1636
        )
        out = self.poll()
        self.assertEqual(sorted(self.keys()), ["CPUINFO_MAX_FREQ", "CPUINFO_MODEL", "CPUINFO_PREV_IDLE", "CPUINFO_PREV_STAT"])
        self.assertIn('CPUINFO_MODEL="AMD Ryzen 9 7950X3D 16-Core Processor"', self.cache.read_text())
        self.assertEqual(self.lscpu_calls(), 0)
        self.assertIn("AMD Ryzen 9 7950X3D 16-Core Processor", out["tooltip"])
        self.assertEqual(list(self.runtime.iterdir()), [self.cache])

    def test_output_without_max_mhz(self):
        out = self.poll()
        self.assertTrue(out["tooltip"].split("\n")[0].endswith(" AMD Ryzen 9 7950X3D 16-Core Processor"))
        clock = [line for line in out["tooltip"].split("\n") if "Clock Speed" in line]
        if clock:  # absent only when /proc/cpuinfo has no "cpu MHz"
            self.assertRegex(clock[0], r"Clock Speed: [\d.]+ MHz$")
        self.assertEqual(out["class"][0], "no-sensor")

    def test_output_with_max_mhz(self):
        out = self.poll(lscpu_text=LSCPU_HOST)
        self.assertIn('CPUINFO_MAX_FREQ="5759"', self.cache.read_text())
        clock = [line for line in out["tooltip"].split("\n") if "Clock Speed" in line]
        if clock:
            self.assertRegex(clock[0], r"Clock Speed: [\d.]+/5759 MHz$")


if __name__ == "__main__":
    unittest.main()
