"""The version cache round-trips any commit message and is never run.

Run from the repo root:  python3 Scripts/tests/theme-security/test_version_file.py
"""

import shutil
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sandbox import BIN, REPO, Sandbox  # noqa: E402

GIT = shutil.which("git", path="/usr/bin:/bin")
FIELDS = ["HYDE_CLONE_PATH", "HYDE_BRANCH", "HYDE_REMOTE", "HYDE_VERSION",
          "HYDE_VERSION_LAST_CHECKED", "HYDE_VERSION_COMMIT_MSG", "HYDE_COMMIT_HASH"]


@unittest.skipUnless(GIT, "git is not installed")
class VersionFileTests(unittest.TestCase):
    def setUp(self):
        self.box = Sandbox()
        (self.box.bin / "git").symlink_to(GIT)
        self.marker = self.box.root / "marker"
        self.version_file = self.box.state / "hyde/version"
        self.repo = self.box.root / "Hyprion's clone"
        (self.repo / "Scripts").mkdir(parents=True)
        shutil.copy(REPO / "Scripts/version.sh", self.repo / "Scripts/version.sh")
        self.git("init", "-q", "-b", "main")
        self.git("remote", "add", "origin", "https://example.org/it's/repo.git")

    def tearDown(self):
        self.box.cleanup()

    def git(self, *args):
        env = self.box.env(GIT_CONFIG_NOSYSTEM="1", GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
                           GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
        result = self.box.run(["git", *args], cwd=self.repo, env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def cache(self, message):
        self.git("add", "-A")
        self.git("commit", "-q", "--allow-empty", "--cleanup=verbatim", "-m", message)
        result = self.box.run(["bash", "Scripts/version.sh", "--cache"], cwd=self.repo)
        self.assertEqual(result.returncode, 0, result.stderr)
        return self.git("log", "-1", "--pretty=%B").rstrip("\n")

    def hyde_shell(self, *args):
        return self.box.run(["bash", str(BIN / "hyde-shell"), *args])

    def hostile_message(self):
        return (
            f"fix(theme): don't run `touch {self.marker}` or $(touch {self.marker})\n"
            "\n"
            f"It's 'quoted' and \"double\" and '`touch {self.marker}`' and a \\ backslash"
        )

    def test_hostile_commit_message_round_trips_through_bash(self):
        message = self.cache(self.hostile_message())
        script = f'source "{self.version_file}"; printf "%s\\0" ' + " ".join(f'"${f}"' for f in FIELDS)
        result = self.box.bash(script)
        self.assertEqual(result.returncode, 0, result.stderr)
        values = dict(zip(FIELDS, result.stdout.split("\0")))
        self.assertEqual(values["HYDE_VERSION_COMMIT_MSG"], message)
        self.assertEqual(values["HYDE_REMOTE"], "https://example.org/it's/repo.git")
        self.assertEqual(values["HYDE_CLONE_PATH"], str(self.repo))
        self.assertFalse(self.marker.exists())

    def test_hyde_shell_version_shows_the_message_without_running_it(self):
        message = self.cache(self.hostile_message())
        result = self.hyde_shell("version")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(f"Last Commit Message: {message}\n", result.stdout)
        self.assertIn("Branch: main\n", result.stdout)
        self.assertIn("Remote: https://example.org/it's/repo.git\n", result.stdout)
        self.assertFalse(self.marker.exists())

    def test_plain_message_is_written_as_before(self):
        self.cache("fix(waybar): stop layout switches from taking the bar down")
        lines = self.version_file.read_text().splitlines()
        self.assertEqual([line.split("=", 1)[0] for line in lines], FIELDS)
        self.assertIn("HYDE_VERSION_COMMIT_MSG='fix(waybar): stop layout switches from taking the bar down'", lines)

    def test_old_unescaped_file_is_not_run(self):
        # What the old writer produced for a message with apostrophes: the
        # backticks sat between an even number of quotes and ran on `version`.
        self.version_file.parent.mkdir(parents=True)
        self.version_file.write_text(
            "HYDE_BRANCH='main'\n"
            f"HYDE_VERSION_COMMIT_MSG='don't `touch {self.marker}` won't'\n"
            f"HYDE_COMMIT_HASH='abc'; touch {self.marker}\n"
            "HYDE_VERSION='v1'\n"
        )
        result = self.hyde_shell("version")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.marker.exists())
        self.assertIn("Branch: main\n", result.stdout)
        self.assertIn("Version: v1\n", result.stdout)

    def test_unknown_keys_are_ignored(self):
        self.version_file.parent.mkdir(parents=True)
        self.version_file.write_text("HYDE_SCRIPTS_PATH='/evil'\nHYDE_VERSION='v2'\n")
        result = self.hyde_shell("version")
        self.assertIn("Version: v2\n", result.stdout)

    def test_release_notes_reads_the_file_without_running_it(self):
        self.cache(self.hostile_message())
        result = self.hyde_shell("release-notes")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("HyDE Release Notes:", result.stdout)
        self.assertFalse(self.marker.exists())


if __name__ == "__main__":
    unittest.main()
