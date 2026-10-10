"""Tests for the installer's shell helpers and scripts, run against stubs.

Every script runs with a fake HOME and a PATH holding nothing but recording
stubs and a few named tools, so no package manager, sudo or git is reachable.

Run from the repo root:  python3 Scripts/tests/install/test_install.py
"""

import shutil
import subprocess
import tempfile
import tomllib
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2]
BASH = shutil.which("bash")

# Never reachable from the sandbox PATH except as the stubs written below.
GUARDED = ("pacman", "paru", "yay", "sudo", "makepkg", "git", "systemctl", "chsh", "flatpak", "curl", "zsh")
# pacman answers -Q from $INSTALLED; the others only record that they ran.
SYSTEM_STUBS = {
    "pacman": 'if [ "$1" = -Q ]; then case " ${INSTALLED:-} " in *" $2 "*) exit 0 ;; esac; exit 1; fi',
    **{name: "exit 0" for name in ("sudo", "makepkg", "git", "systemctl", "chsh", "flatpak", "curl", "zsh", "xdg-mime")},
    "lspci": 'printf "%s\\n" "${LSPCI:-}"',
}
TOOLS = ("realpath", "dirname", "basename", "mkdir", "cat", "grep", "awk", "sed", "cut", "find", "sort",
         "sh", "touch", "date", "xargs", "echo", "mv", "cp", "rm")


class Sandbox:
    """A fake HOME and a PATH holding only recording stubs and named tools."""

    def __init__(self, stubs, tools=TOOLS):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.bin = self.root / "bin"
        self.home = self.root / "home"
        self.log = self.root / "calls.log"
        self.bin.mkdir()
        self.home.mkdir()
        # The stubs' shebang finds bash on PATH, so it is always linked in.
        for tool in ("bash", *tools):
            (self.bin / tool).symlink_to(shutil.which(tool))
        for name, body in stubs.items():
            self.stub(name, body)
        self.env = {
            "PATH": str(self.bin),
            "HOME": str(self.home),
            "USER": "tester",
            "XDG_CONFIG_HOME": str(self.home / ".config"),
            "XDG_CACHE_HOME": str(self.home / ".cache"),
            "XDG_STATE_HOME": str(self.home / ".local/state"),
            "XDG_DATA_HOME": str(self.home / ".local/share"),
            "XDG_RUNTIME_DIR": str(self.root),
            "SHIM_LOG": str(self.log),
            "LANG": "C",
        }

    def stub(self, name, body):
        path = self.bin / name
        path.write_text(f'#!/usr/bin/env bash\nprintf "%s\\n" "${{0##*/}}${{*:+ $*}}" >>"$SHIM_LOG"\n{body}\n')
        path.chmod(0o755)
        for guarded in GUARDED:
            found = shutil.which(guarded, path=str(self.bin))
            assert found is None or not Path(found).is_symlink(), f"{guarded} would reach the real system"

    def calls(self, *names):
        lines = self.log.read_text().splitlines() if self.log.exists() else []
        return [line for line in lines if not names or line.split()[0] in names]

    def run(self, command, stdin="", **env):
        return subprocess.run(command, input=stdin, env={**self.env, **env}, cwd=self.root,
                              capture_output=True, text=True, timeout=120)

    def source(self, snippet, **env):
        """Runs a snippet after sourcing global_fn.sh, as a script in Scripts/ would."""
        script = f'source "{SCRIPTS}/global_fn.sh"\n{snippet}'
        return self.run([BASH, "-c", script, str(SCRIPTS / "install.sh")], **env)

    def cleanup(self):
        self.tmp.cleanup()


class SandboxTestCase(unittest.TestCase):
    def setUp(self):
        self.box = Sandbox(SYSTEM_STUBS)
        self.addCleanup(self.box.cleanup)


GPUS = {
    "pascal": "01:00.0 VGA compatible controller: NVIDIA Corporation GP104 [GeForce GTX 1080] (rev a1)",
    "turing": "01:00.0 VGA compatible controller: NVIDIA Corporation TU104 [GeForce RTX 2080] (rev a1)",
    "hybrid": "00:02.0 VGA compatible controller: Intel Corporation Alder Lake-P GT2 [Iris Xe Graphics] (rev 0c)\n"
              "01:00.0 3D controller: NVIDIA Corporation GA107M [GeForce RTX 3050 Mobile] (rev a1)",
}


class NvidiaDriverTests(SandboxTestCase):
    def detect(self, lspci, *args, **env):
        result = self.box.source(f"nvidia_detect --drivers {' '.join(args)}", LSPCI=lspci, **env)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.split()

    def test_each_driver_gets_its_own_utils(self):
        chips = {
            "G92": "nvidia-340xx", "GF108": "nvidia-390xx", "GK104": "nvidia-470xx",
            "GM206": "nvidia-580xx", "GP104": "nvidia-580xx",
        }
        for chip, branch in chips.items():
            with self.subTest(chip=chip):
                lspci = f"01:00.0 VGA compatible controller: NVIDIA Corporation {chip} [GeForce] (rev a1)"
                self.assertEqual(self.detect(lspci, "aur"), [f"{branch}-dkms", f"{branch}-utils"])
                self.assertEqual(self.detect(lspci, "pacman"), [])

    def test_current_gpus_stay_on_pacman(self):
        for gpu in ("turing", "hybrid"):
            with self.subTest(gpu=gpu):
                self.assertEqual(self.detect(GPUS[gpu], "pacman"), ["nvidia-open-dkms", "nvidia-utils"])
                self.assertEqual(self.detect(GPUS[gpu], "aur"), [])

    def test_unfiltered_lists_everything_once(self):
        both = f"{GPUS['pascal']}\n{GPUS['pascal'].replace('01:00.0', '02:00.0')}"
        self.assertEqual(self.detect(both), ["nvidia-580xx-dkms", "nvidia-580xx-utils"])

    def test_chip_code_as_the_last_word(self):
        lspci = "01:00.0 3D controller: NVIDIA Corporation GP108"
        self.assertEqual(self.detect(lspci, "aur"), ["nvidia-580xx-dkms", "nvidia-580xx-utils"])

    def aur_deps(self, lspci, **env):
        return self.box.source("nvidia_aur_deps", LSPCI=lspci, **env)

    def test_legacy_block_for_the_aur_helpers(self):
        self.box.stub("yay", "exit 0")
        result = self.aur_deps(GPUS["pascal"])
        self.assertEqual(result.returncode, 0, result.stderr)
        # Appended after the pacman list in install.sh's transient TOML
        config = tomllib.loads(f'[[global.dependency]]\npacman = [ "linux-headers", ]\n{result.stdout}')
        blocks = config["global"]["dependency"]
        self.assertEqual(blocks[0], {"pacman": ["linux-headers"]})
        self.assertEqual(blocks[1], {
            "yay": ["nvidia-580xx-dkms", "nvidia-580xx-utils"],
            "paru": ["nvidia-580xx-dkms", "nvidia-580xx-utils"],
        })

    def test_no_block_for_current_gpus(self):
        self.box.stub("yay", "exit 0")
        result = self.aur_deps(GPUS["turing"])
        self.assertEqual((result.returncode, result.stdout), (0, ""))

    def test_missing_legacy_driver_without_a_helper_stops(self):
        result = self.aur_deps(GPUS["pascal"])
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertIn("nvidia-580xx-dkms nvidia-580xx-utils come from the AUR", result.stderr)
        self.assertIn("-n", result.stderr)

    def test_installed_legacy_driver_without_a_helper_is_fine(self):
        result = self.aur_deps(GPUS["pascal"], INSTALLED="nvidia-580xx-dkms nvidia-580xx-utils")
        self.assertEqual((result.returncode, result.stdout), (0, ""))

    def test_test_run_without_a_helper_carries_on(self):
        result = self.aur_deps(GPUS["pascal"], flg_DryRun="1")
        self.assertEqual((result.returncode, result.stdout), (0, ""))

    def test_install_sh_routes_the_drivers(self):
        install = (SCRIPTS / "install.sh").read_text()
        self.assertEqual(install.count("nvidia_detect --drivers pacman"), 2)
        self.assertEqual(install.count("nvidia_aur_deps >>"), 2)
        self.assertNotIn("nvidia_detect --drivers |", install)


# deez's own output for `deps --check`, captured without a terminal
CHECK_OK = "[ok] Deps: all satisfied.\n"
CHECK_MISSING = "[warn] pacman: hyprland missing\n[err] Deps: missing\n[err]   pacman: hyprland, uwsm\n"


class DeezCheckTests(SandboxTestCase):
    def setUp(self):
        super().setUp()
        self.box.stub("deez", 'case "$2" in\n'
                              '--install) printf "%s" "${DEEZ_INSTALL_OUT:-}"; exit "${DEEZ_INSTALL_RC:-0}" ;;\n'
                              '--check) printf "%s" "${DEEZ_CHECK_OUT:-}"; exit "${DEEZ_CHECK_RC:-0}" ;;\n'
                              'esac')

    def install(self, **env):
        snippet = ('deez_exe="$(command -v deez)"\n'
                   'if deez_deps_install --config core.toml --source src; then echo "rc=0"; else echo "rc=1"; fi')
        result = self.box.source(snippet, **env)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def test_installed_packages_pass(self):
        out = self.install(DEEZ_CHECK_OUT=CHECK_OK)
        self.assertTrue(out.endswith("rc=0\n"), out)
        self.assertEqual(self.box.calls("deez"), [
            "deez deps --install --config core.toml --source src",
            "deez deps --check --config core.toml --source src",
        ])

    def test_failed_install_reported_as_success_is_caught(self):
        # pacman failed (target not found, conflict, declined prompt) and deez still exited 0
        out = self.install(DEEZ_INSTALL_OUT="[err] Failed to install packages for pacman: \n",
                           DEEZ_CHECK_OUT=CHECK_MISSING)
        self.assertTrue(out.endswith("rc=1\n"), out)
        self.assertIn("pacman: hyprland, uwsm", out)
        self.assertNotIn("[warn]", out)

    def test_failing_exit_status_is_caught(self):
        self.assertTrue(self.install(DEEZ_INSTALL_RC="1").endswith("rc=1\n"))
        self.assertEqual(len(self.box.calls("deez")), 1)
        self.assertTrue(self.install(DEEZ_CHECK_OUT=CHECK_OK, DEEZ_CHECK_RC="1").endswith("rc=1\n"))

    def test_install_sh_checks_every_install(self):
        install = (SCRIPTS / "install.sh").read_text()
        self.assertNotIn('"${deez_exe}" deps --install', install)
        self.assertEqual(install.count("deez_deps_install --config"), 4)


if __name__ == "__main__":
    unittest.main()
