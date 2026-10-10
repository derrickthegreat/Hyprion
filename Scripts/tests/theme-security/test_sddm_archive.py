"""theme.patch.sh never lets root unpack a downloaded Sddm_*.tar.* archive.

Runs the real theme.patch.sh against a fake theme repository. /usr/share/sddm/themes
is not writable here, so the script takes its root path; the fake sudo maps that
directory into the sandbox and runs the command as the test user.

Run from the repo root:  python3 Scripts/tests/theme-security/test_sddm_archive.py
"""

import io
import os
import stat
import sys
import tarfile
import unittest
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sandbox import LIB, Sandbox  # noqa: E402

SDDM = "/usr/share/sddm/themes"


def add(tar, name, kind=tarfile.REGTYPE, mode=0o644, data=b"", link="", **extra):
    info = tarfile.TarInfo(name)
    info.type, info.mode, info.linkname = kind, mode, link
    info.uid = info.gid = 0
    info.uname = info.gname = "root"
    for key, value in extra.items():
        setattr(info, key, value)
    if kind == tarfile.REGTYPE:
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    else:
        tar.addfile(info)


@unittest.skipIf(os.access(SDDM, os.W_OK) or not os.path.isdir(SDDM),
                 f"{SDDM} must exist and not be writable, so the root path runs")
class SddmArchiveTests(unittest.TestCase):
    def setUp(self):
        self.box = Sandbox()
        self.installed = self.box.root / "sddm-themes"
        self.installed.mkdir()
        self.outside = self.box.root / "outside"
        self.box.fake(
            "sudo",
            f"from='{SDDM}' to='{self.installed}' args=()\n"
            'for a in "$@"; do args+=("${a/#"$from"/$to}"); done\n'
            'exec "${args[@]}"',
        )
        # Unique names: the skip check looks at the real /usr/share/sddm/themes
        self.tag = uuid.uuid4().hex[:8]

    def tearDown(self):
        self.box.cleanup()

    def patch(self, sddm_name, build):
        repo = self.box.root / f"repo-{sddm_name}"
        theme = repo / "Configs/.config/hyde/themes/Test Theme"
        theme.mkdir(parents=True)
        (theme / "hypr.theme").write_text(f"$GTK_THEME = TestGtk\n$SDDM_THEME = {sddm_name}\n")
        (theme / "wallpapers").mkdir()
        (theme / "wallpapers/a.png").write_bytes(b"png")
        arcs = repo / "Source/arcs"
        arcs.mkdir(parents=True)
        with tarfile.open(arcs / "Gtk_TestGtk.tar.gz", "w:gz") as tar:
            add(tar, "TestGtk", tarfile.DIRTYPE, 0o755)
            add(tar, "TestGtk/index.theme", data=b"[X-GTK-Theme]\n")
        with tarfile.open(arcs / f"Sddm_{sddm_name}.tar.gz", "w:gz") as tar:
            build(tar)
        result = self.box.run(["bash", str(LIB / "theme.patch.sh"), "Test Theme", str(repo), "--skipcaching"])
        for argv in self.box.calls("sudo"):
            self.assertNotEqual(argv[1], "tar", f"root unpacked the archive: {argv}")
        return result

    def mode(self, path):
        return stat.S_IMODE(os.lstat(path).st_mode)

    def test_normal_theme_installs_with_plain_modes(self):
        name = f"Normal{self.tag}"

        def build(tar):
            add(tar, name, tarfile.DIRTYPE, 0o700)
            add(tar, f"{name}/Main.qml", data=b"import QtQuick 2.0\n")
            add(tar, f"{name}/theme.conf", mode=0o600, data=b"[General]\n")
            add(tar, f"{name}/scripts", tarfile.DIRTYPE, 0o755)
            add(tar, f"{name}/scripts/run.sh", mode=0o755, data=b"#!/bin/sh\n")
            add(tar, f"{name}/assets", tarfile.DIRTYPE, 0o755)
            add(tar, f"{name}/assets/bg.png", data=b"png")
            add(tar, f"{name}/bg.png", tarfile.SYMTYPE, link="assets/bg.png")

        result = self.patch(name, build)
        theme = self.installed / name
        self.assertTrue((theme / "Main.qml").is_file(), result.stdout + result.stderr)
        self.assertEqual(self.mode(theme), 0o755)
        self.assertEqual(self.mode(theme / "theme.conf"), 0o644)
        self.assertEqual(self.mode(theme / "scripts/run.sh"), 0o755)
        self.assertEqual(os.readlink(theme / "bg.png"), "assets/bg.png")
        self.assertTrue(self.box.calls("sudo"), "the root path was not taken")

    def test_setuid_bits_and_escaping_links_are_stripped(self):
        name = f"Evil{self.tag}"
        self.outside.write_text("keep")

        def build(tar):
            add(tar, name, tarfile.DIRTYPE, 0o7777)
            add(tar, f"{name}/Main.qml", data=b"x")
            add(tar, f"{name}/rootshell", mode=0o4755, data=b"\x7fELF")
            add(tar, f"{name}/group", mode=0o2775, data=b"\x7fELF")
            add(tar, f"{name}/passwd", tarfile.SYMTYPE, link="/etc/passwd")
            add(tar, f"{name}/up", tarfile.SYMTYPE, link="../../outside")
            add(tar, f"{name}/ok", tarfile.SYMTYPE, link="Main.qml")

        result = self.patch(name, build)
        theme = self.installed / name
        self.assertTrue((theme / "Main.qml").is_file(), result.stdout + result.stderr)
        for path in [theme, *theme.iterdir()]:
            if not path.is_symlink():
                self.assertEqual(self.mode(path) & 0o7000, 0, f"{path.name} kept a special bit")
                self.assertEqual(self.mode(path) & 0o022, 0, f"{path.name} is group/world writable")
        self.assertEqual(self.mode(theme / "rootshell"), 0o755)
        self.assertFalse(os.path.lexists(theme / "passwd"))
        self.assertFalse(os.path.lexists(theme / "up"))
        self.assertEqual(os.readlink(theme / "ok"), "Main.qml")
        self.assertEqual(self.outside.read_text(), "keep")

    def refused(self, name, build):
        result = self.patch(name, build)
        self.assertEqual(list(self.installed.iterdir()), [], result.stdout + result.stderr)
        self.assertFalse(self.outside.exists())
        self.assertFalse((self.box.root / "escaped").exists())

    def test_device_node_is_refused(self):
        name = f"Dev{self.tag}"
        self.refused(name, lambda tar: (
            add(tar, f"{name}/Main.qml", data=b"x"),
            add(tar, f"{name}/null", tarfile.CHRTYPE, 0o666, devmajor=1, devminor=3),
        ))

    def test_fifo_is_refused(self):
        name = f"Fifo{self.tag}"
        self.refused(name, lambda tar: (
            add(tar, f"{name}/Main.qml", data=b"x"),
            add(tar, f"{name}/pipe", tarfile.FIFOTYPE, 0o666),
        ))

    def test_dot_dot_member_is_refused(self):
        name = f"Dots{self.tag}"
        self.refused(name, lambda tar: (
            add(tar, f"{name}/Main.qml", data=b"x"),
            add(tar, f"{name}/../../../escaped", data=b"x"),
        ))

    def test_absolute_member_is_refused(self):
        name = f"Abs{self.tag}"
        self.refused(name, lambda tar: (
            add(tar, f"{name}/Main.qml", data=b"x"),
            add(tar, str(self.outside), data=b"x"),
        ))


if __name__ == "__main__":
    unittest.main()
