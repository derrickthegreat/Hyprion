"""Unit tests for waybar.py's file writes, run lock and reload signalling.

Run from the repo root:  python3 Scripts/tests/waybar/test_waybar.py
"""

import fcntl
import importlib.util
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

LIB = Path(__file__).resolve().parents[3] / "Configs/.local/lib/hyde"
sys.path.insert(0, str(LIB))


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


# waybar.py exits on import when the waybar binary is missing.
with mock.patch("shutil.which", return_value="/usr/bin/waybar"):
    wb = load("waybar_py", LIB / "waybar.py")


def start_child(code):
    child = subprocess.Popen([sys.executable, "-c", code])
    time.sleep(0.05)
    return child


class WriteAtomicTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_replaces_content_and_leaves_no_temp_file(self):
        path = self.dir / "config.jsonc"
        path.write_text("old")
        wb.write_atomic(path, "new")
        self.assertEqual(path.read_text(), "new")
        self.assertEqual(os.listdir(self.dir), ["config.jsonc"])

    def test_writes_through_a_symlink(self):
        real = self.dir / "real.css"
        real.write_text("old")
        link = self.dir / "style.css"
        link.symlink_to(real)
        wb.write_atomic(link, "new")
        self.assertTrue(link.is_symlink())
        self.assertEqual(real.read_text(), "new")

    def test_keeps_the_file_mode(self):
        path = self.dir / "staterc"
        path.write_text("old")
        path.chmod(0o600)
        wb.write_atomic(path, "new")
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_failed_write_keeps_the_old_file(self):
        path = self.dir / "includes.json"
        path.write_text("old")
        with mock.patch("os.replace", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                wb.write_atomic(path, "new")
        self.assertEqual(path.read_text(), "old")
        self.assertEqual(os.listdir(self.dir), ["includes.json"])

    def test_readers_never_see_a_partial_file(self):
        # What waybar hit at 16:05: a reload read config.jsonc mid-rewrite and found it empty.
        path = self.dir / "config.jsonc"
        versions = [b"a" * 200_000, b"b" * 300_000]
        path.write_bytes(versions[0])
        seen = set()
        done = threading.Event()

        def read_loop():
            while not done.is_set():
                seen.add(len(path.read_bytes()))

        reader = threading.Thread(target=read_loop)
        reader.start()
        src = self.dir / "layout.jsonc"
        for i in range(200):
            src.write_bytes(versions[i % 2])
            wb.copy_atomic(src, path)
        done.set()
        reader.join()
        self.assertTrue(seen <= {len(v) for v in versions}, seen)


class LockTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": self.tmp.name})
        self.env.start()

    def tearDown(self):
        wb.release_lock()
        self.env.stop()
        self.tmp.cleanup()

    def test_waits_for_another_run_to_finish(self):
        lock_path = Path(self.tmp.name) / "hyde" / "waybar.py.lock"
        lock_path.parent.mkdir()
        holder = start_child(
            "import fcntl, time\n"
            f"f = open({str(lock_path)!r}, 'w')\n"
            "fcntl.flock(f, fcntl.LOCK_EX)\n"
            "time.sleep(0.5)\n"
        )
        time.sleep(0.15)
        started = time.monotonic()
        wb.acquire_lock()
        waited = time.monotonic() - started
        holder.wait()
        self.assertGreater(waited, 0.2)

    def test_lock_is_released_for_the_next_run(self):
        wb.acquire_lock()
        wb.release_lock()
        with open(Path(self.tmp.name) / "hyde" / "waybar.py.lock", "w") as f:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)


class HandlesSignalTests(unittest.TestCase):
    def test_waits_until_the_handler_is_installed(self):
        child = start_child(
            "import signal, time\n"
            "time.sleep(0.3)\n"
            "signal.signal(signal.SIGUSR2, lambda *a: None)\n"
            "time.sleep(5)\n"
        )
        try:
            started = time.monotonic()
            self.assertTrue(wb._handles_signal(child.pid, signal.SIGUSR2))
            self.assertGreater(time.monotonic() - started, 0.15)
        finally:
            child.kill()
            child.wait()

    def test_gives_up_on_a_process_without_a_handler(self):
        child = start_child("import time; time.sleep(5)")
        try:
            self.assertFalse(wb._handles_signal(child.pid, signal.SIGUSR2, timeout=0.3))
        finally:
            child.kill()
            child.wait()

    def test_missing_process(self):
        child = start_child("pass")
        child.wait()
        self.assertFalse(wb._handles_signal(child.pid, signal.SIGUSR2, timeout=0.3))


class SignalWaybarTests(unittest.TestCase):
    def test_signals_only_the_main_process(self):
        with mock.patch.object(wb, "HAS_SYSTEMD", True), \
             mock.patch.object(wb, "_waybar_pids", return_value=[1234]), \
             mock.patch.object(wb, "_handles_signal", return_value=True), \
             mock.patch.object(wb.subprocess, "run") as run:
            wb._signal_waybar("SIGUSR2")
        args = run.call_args.args[0]
        self.assertIn("--kill-whom=main", args)
        self.assertIn("SIGUSR2", args)

    def test_holds_the_signal_for_a_bar_that_is_still_starting(self):
        with mock.patch.object(wb, "_waybar_pids", return_value=[1234]), \
             mock.patch.object(wb, "_handles_signal", return_value=False), \
             mock.patch.object(wb.subprocess, "run") as run:
            wb._signal_waybar("SIGUSR2")
        run.assert_not_called()


class RestartTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        config = Path(self.tmp.name) / "waybar"
        (config / "includes").mkdir(parents=True)
        (config / "config.jsonc").write_text("{}")
        self.style = config / "style.css"
        self.style.write_text("/* a */")
        self.patches = [
            mock.patch.object(wb, "xdg_config_home", return_value=Path(self.tmp.name)),
            mock.patch.object(wb, "CONFIG_JSONC", config / "config.jsonc"),
            mock.patch.object(wb, "is_waybar_running_for_current_user", return_value=True),
            mock.patch.object(wb, "_reloaded_inputs", None),
        ]
        for patch in self.patches:
            patch.start()
        self.signal = mock.patch.object(wb, "_signal_waybar").start()

    def tearDown(self):
        mock.patch.stopall()
        self.tmp.cleanup()

    def test_second_reload_without_changes_is_skipped(self):
        wb.restart_waybar()
        wb.restart_waybar()
        self.assertEqual(self.signal.call_count, 1)

    def test_reloads_again_after_a_file_changed(self):
        # --update --next: a theme's layout reloads first, then --next writes a new config.
        wb.restart_waybar()
        self.style.write_text("/* b */")
        wb.restart_waybar()
        self.assertEqual(self.signal.call_count, 2)


if __name__ == "__main__":
    unittest.main()
