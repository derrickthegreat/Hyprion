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


class MigrationDryRunTests(SandboxTestCase):
    def setUp(self):
        super().setUp()
        self.migrations = self.box.root / "migrations"
        self.migrations.mkdir()
        self.ran = self.box.root / "ran"
        for version in ("v1.sh", "v2.sh"):
            (self.migrations / version).write_text(f'touch "{self.ran}-{version}"\n')
        self.state = self.box.home / ".local/state/hyde/migration/applied"

    def migrate(self, dry_run):
        result = self.box.source(f'run_pending_migrations "{self.migrations}" "{self.state}"',
                                 flg_DryRun=str(dry_run))
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def test_test_run_runs_and_records_nothing(self):
        out = self.migrate(dry_run=1)
        self.assertIn("Would run v1.sh", out)
        self.assertIn("Would run v2.sh", out)
        self.assertEqual(list(self.box.root.glob("ran-*")), [])
        self.assertFalse(self.state.parent.exists())

    def test_test_run_skips_recorded_migrations(self):
        self.state.parent.mkdir(parents=True)
        self.state.write_text("v1.sh\n")
        out = self.migrate(dry_run=1)
        self.assertNotIn("v1.sh", out)
        self.assertIn("Would run v2.sh", out)
        self.assertEqual(self.state.read_text(), "v1.sh\n")

    def test_real_run_applies_and_records(self):
        self.migrate(dry_run=0)
        self.assertTrue(Path(f"{self.ran}-v1.sh").exists())
        self.assertEqual(self.state.read_text(), "v1.sh\nv2.sh\n")


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


class DryRunTests(SandboxTestCase):
    """install.sh -t exports flg_DryRun=1 to every script it runs."""

    def script(self, name, *args, stdin="", **env):
        return self.box.run([BASH, str(SCRIPTS / name), *args], stdin=stdin, flg_DryRun="1", **env)

    def test_aur_helper_is_not_built(self):
        result = self.script("install_aur.sh", "yay")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Would build and install yay", result.stdout)
        self.assertEqual(self.box.calls("git", "makepkg", "sudo"), [])
        self.assertFalse((self.box.home / "Clone").exists())

    def test_post_install_changes_nothing(self):
        # Covers restore_shl.sh too, which install_pst.sh runs.
        (self.box.home / ".oh-my-zsh").mkdir()
        (self.box.home / ".oh-my-zsh/oh-my-zsh.sh").touch()
        result = self.script("install_pst.sh", INSTALLED="dolphin xdg-utils zsh", myShell="zsh")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Would set org.kde.dolphin.desktop", result.stdout)
        self.assertEqual(self.box.calls("xdg-mime", "zsh", "curl", "chsh", "git", "sudo"), [])

    def test_post_install_with_sddm_changes_nothing(self):
        (self.box.home / ".oh-my-zsh").mkdir()
        (self.box.home / ".oh-my-zsh/oh-my-zsh.sh").touch()
        # Where SDDM isn't configured yet it asks for a theme, and global_fn.sh's
        # set -e ends the script if nothing answers.
        result = self.script("install_pst.sh", stdin="1\n", INSTALLED="sddm zsh", myShell="zsh")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Would install the Hyprion session", result.stdout)
        self.assertEqual(self.box.calls("sudo"), [])

    def test_theme_import_creates_nothing(self):
        result = self.script("restore_thm.sh")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.box.home / ".config/hyde").exists())
        self.assertEqual(self.box.calls("git", "curl"), [])


class SessionInstallTests(SandboxTestCase):
    def test_installs_the_hyprion_session(self):
        result = self.box.run([BASH, str(SCRIPTS / "install_session.sh")])
        self.assertEqual(result.returncode, 0, result.stderr)
        source = SCRIPTS.parent / "Source/session"
        sudo = self.box.calls("sudo")
        self.assertIn(f"sudo install -Dm755 {source}/hyprion-session /usr/local/bin/hyprion-session", sudo)
        self.assertIn(f"sudo install -Dm644 {source}/hyprion.desktop "
                      "/usr/local/share/wayland-sessions/hyprion.desktop", sudo)

    def test_a_failed_install_says_so(self):
        self.box.stub("sudo", "exit 1")
        result = self.box.run([BASH, str(SCRIPTS / "install_session.sh")])
        self.assertEqual(result.returncode, 1)
        self.assertIn("Could not install the Hyprion session", result.stdout + result.stderr)


class VersionInfoTests(SandboxTestCase):
    def setUp(self):
        super().setUp()
        # version.sh reads the checkout with git, which the sandbox only records.
        self.box.stub("git", 'exec /usr/bin/git "$@"')
        self.version = self.box.home / ".local/state/hyde/version"

    def test_restore_records_the_installed_checkout(self):
        result = self.box.source("save_version_info")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=SCRIPTS.parent,
                              capture_output=True, text=True, check=True).stdout.strip()
        record = self.version.read_text()
        self.assertIn(f"HYDE_CLONE_PATH='{SCRIPTS.parent}'", record)
        self.assertIn(f"HYDE_COMMIT_HASH='{head}'", record)

    def test_test_run_records_nothing(self):
        result = self.box.source("save_version_info", flg_DryRun="1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Would save version info", result.stdout)
        self.assertFalse(self.version.exists())

    def test_install_sh_saves_it_after_the_deploy(self):
        install = (SCRIPTS / "install.sh").read_text()
        self.assertEqual(install.count("save_version_info"), 1)
        self.assertLess(install.index("Dotfiles deployed"), install.index("save_version_info"))


class UninstallTests(SandboxTestCase):
    def setUp(self):
        super().setUp()
        files = {
            ".config/hyde/config.toml": "[theme]\n",
            ".config/hyde/themes/Mine/theme.conf": "imported\n",
            ".config/hyde/wallbash/always/x.dcol": "x\n",
            ".local/state/hyde/migration/v26.8.2/hyprland.conf": "the only copy\n",
            ".local/state/hyde/staterc": "state\n",
            ".local/state/hyde/python_env/bin/python": "",
            ".local/state/hyde/lua_env/lib/x.so": "",
            ".cache/hyde/thumbs/a.png": "",
        }
        for name, text in files.items():
            path = self.box.home / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)

    def test_hyde_directories_are_moved_to_the_backup(self):
        result = self.box.run([BASH, str(SCRIPTS / "uninstall.sh")], stdin="DONT HYDE\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        backups = list((self.box.home / ".config/cfg_backups").glob("*_remove"))
        self.assertEqual(len(backups), 1)
        backup = backups[0]
        self.assertEqual((backup / ".config/hyde/config.toml").read_text(), "[theme]\n")
        self.assertEqual((backup / ".config/hyde/themes/Mine/theme.conf").read_text(), "imported\n")
        self.assertTrue((backup / ".config/hyde/wallbash/always/x.dcol").exists())
        self.assertEqual((backup / ".local/state/hyde/migration/v26.8.2/hyprland.conf").read_text(), "the only copy\n")
        self.assertEqual((backup / ".local/state/hyde/staterc").read_text(), "state\n")
        # The environments are rebuilt by the installer, so they are not kept anywhere.
        self.assertFalse((backup / ".local/state/hyde/python_env").exists())
        self.assertFalse((backup / ".local/state/hyde/lua_env").exists())
        for gone in (".config/hyde", ".local/state/hyde", ".cache/hyde"):
            self.assertFalse((self.box.home / gone).exists(), gone)
        self.assertIn(str(backup), result.stdout)
        self.assertIn(f"{SCRIPTS}/pkg_core.lst", result.stdout)

    def test_anything_but_the_phrase_changes_nothing(self):
        result = self.box.run([BASH, str(SCRIPTS / "uninstall.sh")], stdin="no\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.box.home / ".config/hyde/config.toml").exists())
        self.assertFalse((self.box.home / ".config/cfg_backups").exists())


if __name__ == "__main__":
    unittest.main()
