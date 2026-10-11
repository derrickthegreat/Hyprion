#!/usr/bin/env python3
"""Deploys this checkout's Configs/ into $HOME without risking the session.

    Scripts/deploy_live.py                 show what would change, check it loads
    Scripts/deploy_live.py --apply         deploy it
    Scripts/deploy_live.py --rollback [ID] undo a deploy (the latest by default)
    Scripts/deploy_live.py --list-backups

Files are mapped the way install.sh -r maps them, through Scripts/dots/*.toml,
for the dots deez has installed. Only "sync" files are written; "preserve"
files such as ~/.config/hypr/hyprland.lua are never touched.

A live file is replaced only when it is a copy this repo produced: it matches
a committed version of its source, or what this script last deployed there.
Anything else is treated as your edit (or generated, like wallbash output) and
left alone unless named with --force.

Before writing, the result is loaded with `Hyprland --verify-config` in a
staged copy of your Hyprland config, your own hyprland.lua included, and the
deploy stops if it fails. Overwritten files are backed up under
$XDG_STATE_HOME/hyde/deploy/backups, and --rollback works from a TTY.
"""

import argparse
import fnmatch
import hashlib
import json
import os
import resource
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


@dataclass
class Places:
    home: Path
    config: Path
    data: Path
    state: Path
    cache: Path

    @classmethod
    def from_env(cls):
        home = Path(os.environ["HOME"])

        def xdg(name, default):
            value = os.environ.get(name)
            return Path(value) if value else home / default

        return cls(
            home=home,
            config=xdg("XDG_CONFIG_HOME", ".config"),
            data=xdg("XDG_DATA_HOME", ".local/share"),
            state=xdg("XDG_STATE_HOME", ".local/state"),
            cache=xdg("XDG_CACHE_HOME", ".cache"),
        )

    @property
    def deploy_dir(self):
        return self.state / "hyde/deploy"

    def hyprland_roots(self):
        """What the Hyprland config reads while loading, live path -> staged path."""
        return {
            self.config / "hypr": ".config/hypr",
            self.config / "hyde/config.toml": ".config/hyde/config.toml",
            self.data / "hypr": ".local/share/hypr",
            self.home / ".local/lib/hyde": ".local/lib/hyde",
            self.state / "hyde/lua_state": ".local/state/hyde/lua_state",
            self.state / "hyde/lua_env": ".local/state/hyde/lua_env",
            self.state / "hyde/float_sizes": ".local/state/hyde/float_sizes",
        }

    def staged_path(self, dst):
        for live, staged in self.hyprland_roots().items():
            if dst == live or live in dst.parents:
                return Path(staged) / dst.relative_to(live)
        return None


@dataclass
class Target:
    dot: str
    rel: str  # source path relative to the repo, as git names it
    dst: Path
    action: str


@dataclass
class Write:
    target: Target
    content: bytes
    mode: int
    reason: str  # "new", "update" or "forced"


def git(*args, cwd=REPO):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True).stdout


def blob_id(data):
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def expand(path, places):
    for name, value in (
        ("XDG_CONFIG_HOME", places.config),
        ("XDG_DATA_HOME", places.data),
        ("XDG_STATE_HOME", places.state),
        ("XDG_CACHE_HOME", places.cache),
        ("HOME", places.home),
    ):
        path = path.replace("${%s}" % name, str(value)).replace("$" + name, str(value))
    return Path(path)


def ignored(rel, patterns):
    return any(fnmatch.fnmatch(part, pat) for pat in patterns for part in Path(rel).parts)


def load_targets(places):
    """Every repo file the dot manifests deploy, with where it goes."""
    worktree = set(git("ls-files", "-z", "-co", "--exclude-standard", "--", "Configs").decode().split("\0"))
    targets = []
    for manifest in sorted((REPO / "Scripts/dots").glob("*.toml")):
        for dot, body in tomllib.loads(manifest.read_text()).items():
            if not isinstance(body, dict):
                continue
            for entry in body.get("files", []):
                if "source_root" not in entry:
                    continue  # downloaded archives, not files from this repo
                action = entry.get("action") or body.get("action") or "preserve"
                paths = entry.get("paths", [])
                paths = [paths] if isinstance(paths, str) else paths
                source_root = entry["source_root"].rstrip("/")
                target_root = expand(entry["target_root"], places)
                patterns = entry.get("ignored_paths", [])
                for path in paths:
                    base = f"{source_root}/{path}".rstrip("/")
                    if base in worktree:
                        targets.append(Target(dot, base, target_root / path, action))
                        continue
                    for rel in sorted(f for f in worktree if f.startswith(base + "/")):
                        inner = rel[len(base) + 1:]
                        if not ignored(inner, patterns):
                            targets.append(Target(dot, rel, target_root / path / inner, action))
    return targets


def installed_dots(places):
    records = places.data / "deez/dots"
    if not records.is_dir():
        sys.exit(f"No deez records in {records}. Install with Scripts/install.sh first.")
    return {p.stem for p in records.glob("*.toml")}


def committed_blobs():
    """Every blob each Configs/ path has had on any branch, upstream included."""
    blobs = {}
    log = git("log", "--all", "--format=", "--raw", "--no-abbrev", "--no-renames", "--", "Configs")
    for line in log.decode().splitlines():
        if not line.startswith(":"):
            continue
        meta, path = line.split("\t", 1)
        _, _, old, new, _ = meta[1:].split(" ")
        blobs.setdefault(path, set()).update(b for b in (old, new) if b.strip("0"))
    return blobs


def load_state(places):
    path = places.deploy_dir / "state.json"
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {"files": {}}


def save_state(places, state):
    places.deploy_dir.mkdir(parents=True, exist_ok=True)
    path = places.deploy_dir / "state.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=1, sort_keys=True) + "\n")
    os.replace(tmp, path)


def plan(places, force):
    """Sorts each target into writes and the reasons the rest are left alone."""
    installed = installed_dots(places)
    blobs = committed_blobs()
    deployed = load_state(places)["files"]
    writes, skipped = [], {"edited": [], "symlink": [], "preserve": 0, "current": 0, "not installed": set()}
    for t in load_targets(places):
        if t.dot not in installed:
            skipped["not installed"].add(t.dot)
            continue
        if t.action != "sync":
            skipped["preserve"] += 1
            continue
        src = REPO / t.rel
        content = src.read_bytes()
        mode = 0o755 if os.access(src, os.X_OK) else 0o644
        if t.dst.is_symlink():
            skipped["symlink"].append(t)
            continue
        if not t.dst.exists():
            writes.append(Write(t, content, mode, "new"))
            continue
        live = t.dst.read_bytes()
        live_mode = 0o755 if os.access(t.dst, os.X_OK) else 0o644
        if live == content and live_mode == mode:
            skipped["current"] += 1
        elif blob_id(live) in blobs.get(t.rel, ()) or deployed.get(str(t.dst)) == sha256(live):
            writes.append(Write(t, content, mode, "update"))
        elif str(t.dst) in force or t.rel in force:
            writes.append(Write(t, content, mode, "forced"))
        else:
            skipped["edited"].append(t)
    return writes, skipped


def no_core_dump():
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def verify(places, writes):
    """Loads the config as it would be after the deploy, in a staged copy.

    Returns (ok, output), or (None, reason) when it can't run.
    """
    hyprland = shutil.which("Hyprland")
    if not hyprland:
        return None, "Hyprland is not installed"
    with tempfile.TemporaryDirectory(prefix="hyprion-verify-", ignore_cleanup_errors=True) as tmp:
        root = Path(tmp)
        home = root / "home"
        for live, staged in places.hyprland_roots().items():
            dest = home / staged
            dest.parent.mkdir(parents=True, exist_ok=True)
            if live.is_dir():
                shutil.copytree(live, dest, symlinks=True)
            elif live.is_file():
                shutil.copy2(live, dest)
        for w in writes:
            staged = places.staged_path(w.target.dst)
            if staged:
                (home / staged).parent.mkdir(parents=True, exist_ok=True)
                (home / staged).write_bytes(w.content)
        runtime, empty_bin = root / "run", root / "bin"
        runtime.mkdir(mode=0o700)
        empty_bin.mkdir()
        # Only the staged home, and a PATH with nothing on it: the config runs
        # hyprctl and hyde-shell while loading, and they must not reach the session.
        env = {
            "HOME": str(home),
            "XDG_CONFIG_HOME": str(home / ".config"),
            "XDG_DATA_HOME": str(home / ".local/share"),
            "XDG_STATE_HOME": str(home / ".local/state"),
            "XDG_CACHE_HOME": str(home / ".cache"),
            "XDG_RUNTIME_DIR": str(runtime),
            "PATH": str(empty_bin),
            "LANG": "C.UTF-8",
        }
        args = [hyprland, "--verify-config"]
        if os.geteuid() == 0:
            args.append("--i-am-really-stupid")
        try:
            result = subprocess.run(args, cwd=root, env=env, capture_output=True, text=True,
                                    timeout=60, preexec_fn=no_core_dump)
        except subprocess.TimeoutExpired:
            return False, "Hyprland --verify-config timed out after 60s"
    output = (result.stdout + result.stderr).strip()
    if result.returncode < 0:
        output += f"\nHyprland crashed (signal {-result.returncode})"
    return result.returncode == 0 and "config ok" in output, output


def hyprctl(*args):
    return subprocess.run(["hyprctl", *args], capture_output=True, text=True, timeout=10)


class PausedReload:
    """Stops Hyprland reloading on each file, then reloads once at the end.

    Without this a deploy reloads Hyprland while it is still copying files,
    on a mix of old and new ones. Does nothing outside a Hyprland session.
    """

    def __init__(self, active):
        self.active = active and bool(os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")) and bool(shutil.which("hyprctl"))
        self.prior = False

    def __enter__(self):
        if self.active:
            try:
                self.prior = bool(json.loads(hyprctl("-j", "getoption", "misc:disable_autoreload").stdout)["bool"])
            except (json.JSONDecodeError, KeyError, TypeError):
                self.prior = False
            hyprctl("eval", "hl.config({misc={disable_autoreload=true}})")
        return self

    def __exit__(self, *exc):
        if self.active:
            value = "true" if self.prior else "false"
            hyprctl("eval", f"hl.config({{misc={{disable_autoreload={value}}}}})")
            result = hyprctl("reload", "config-only")
            print(f"Reloaded Hyprland: {result.stdout.strip() or result.stderr.strip()}")


def replace_all(items):
    """Writes every (path, content, mode) to a temp file first, then renames them all."""
    staged = []
    try:
        for path, content, mode in items:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.parent / f".{path.name}.hyprion-deploy"
            tmp.write_bytes(content)
            tmp.chmod(mode)
            staged.append((tmp, path))
    except BaseException:
        for tmp, _ in staged:
            tmp.unlink(missing_ok=True)
        raise
    for tmp, path in staged:
        os.replace(tmp, path)


def tilde(path, places):
    try:
        return "~/" + str(path.relative_to(places.home))
    except ValueError:
        return str(path)


def new_backup_dir(places):
    stamp = time.strftime("%Y%m%d-%H%M%S")
    backups = places.deploy_dir / "backups"
    for n in range(100):
        candidate = backups / (stamp if n == 0 else f"{stamp}-{n}")
        try:
            candidate.mkdir(parents=True)
            return candidate
        except FileExistsError:
            continue
    sys.exit("Could not create a backup directory")


def apply(places, writes):
    for w in writes:
        if places.home not in w.target.dst.parents:
            sys.exit(f"Refusing to write outside $HOME: {w.target.dst}")
    backup = new_backup_dir(places)
    entries = []
    for w in writes:
        dst = w.target.dst
        rel = dst.relative_to(places.home)
        existed = dst.exists()
        if existed:
            (backup / "files" / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(dst, backup / "files" / rel)
        entries.append({"path": str(rel), "existed": existed, "after": sha256(w.content)})
    head = git("rev-parse", "HEAD").decode().strip()
    (backup / "manifest.json").write_text(json.dumps({"commit": head, "files": entries}, indent=1) + "\n")

    touches_hyprland = any(places.staged_path(w.target.dst) for w in writes)
    with PausedReload(touches_hyprland):
        replace_all((w.target.dst, w.content, w.mode) for w in writes)

    state = load_state(places)
    for w in writes:
        state["files"][str(w.target.dst)] = sha256(w.content)
    save_state(places, state)
    return backup


def rollback(places, backup_id):
    backups = places.deploy_dir / "backups"
    if backup_id:
        backup = backups / backup_id
    else:
        found = sorted(p for p in backups.glob("*") if (p / "manifest.json").is_file()) if backups.is_dir() else []
        if not found:
            sys.exit(f"No backups in {backups}")
        backup = found[-1]
    manifest = json.loads((backup / "manifest.json").read_text())
    restores, removals, kept = [], [], []
    for entry in manifest["files"]:
        dst = places.home / entry["path"]
        if entry["existed"]:
            saved = backup / "files" / entry["path"]
            restores.append((dst, saved.read_bytes(), saved.stat().st_mode & 0o7777))
        elif dst.exists() and sha256(dst.read_bytes()) == entry["after"]:
            removals.append(dst)
        elif dst.exists():
            kept.append(dst)  # created by the deploy, changed since: not ours to delete
    touches_hyprland = any(places.staged_path(dst) for dst, _, _ in restores) or any(
        places.staged_path(dst) for dst in removals)
    with PausedReload(touches_hyprland):
        replace_all(restores)
        for dst in removals:
            dst.unlink()
    state = load_state(places)
    for dst, content, _ in restores:
        state["files"][str(dst)] = sha256(content)
    for dst in removals:
        state["files"].pop(str(dst), None)
    save_state(places, state)
    print(f"Rolled back {backup.name}: restored {len(restores)}, removed {len(removals)}.")
    for dst in kept:
        print(f"  kept {tilde(dst, places)}: it changed after the deploy created it")


def list_backups(places):
    backups = places.deploy_dir / "backups"
    found = sorted(backups.glob("*/manifest.json")) if backups.is_dir() else []
    if not found:
        print("No backups.")
    for manifest in found:
        data = json.loads(manifest.read_text())
        print(f"{manifest.parent.name}  {len(data['files'])} files  from {data['commit'][:10]}")


def report(places, writes, skipped, verbose):
    dirty = set()
    for line in git("status", "--porcelain", "-z", "--", "Configs").decode().split("\0"):
        if len(line) > 3:
            dirty.add(line[3:])
    for reason in ("new", "update", "forced"):
        group = [w for w in writes if w.reason == reason]
        if group:
            print(f"{reason} ({len(group)}):")
            for w in group:
                note = "  (uncommitted)" if w.target.rel in dirty else ""
                print(f"  {tilde(w.target.dst, places)}{note}")
    if skipped["edited"]:
        print(f"left alone, not a version this repo produced ({len(skipped['edited'])}; --force PATH to replace):")
        for t in skipped["edited"]:
            print(f"  {tilde(t.dst, places)}")
    if skipped["symlink"]:
        print(f"left alone, symlinks ({len(skipped['symlink'])}):")
        for t in skipped["symlink"]:
            print(f"  {tilde(t.dst, places)}")
    print(f"up to date: {skipped['current']}, preserve (never written): {skipped['preserve']}")
    if verbose and skipped["not installed"]:
        print(f"dots not installed here: {', '.join(sorted(skipped['not installed']))}")


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--apply", action="store_true", help="deploy (default: dry run)")
    parser.add_argument("--force", action="append", default=[], metavar="PATH",
                        help="replace this file even if it isn't a version this repo produced")
    parser.add_argument("--rollback", nargs="?", const="", metavar="ID", help="undo a deploy, the latest by default")
    parser.add_argument("--list-backups", action="store_true")
    parser.add_argument("--no-verify", action="store_true",
                        help="skip the Hyprland load check (when Hyprland isn't installed)")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()
    places = Places.from_env()

    if args.list_backups:
        return list_backups(places)
    if args.rollback is not None:
        return rollback(places, args.rollback)

    force = {str(Path(os.path.expanduser(p)).absolute()) for p in args.force} | set(args.force)
    writes, skipped = plan(places, force)
    report(places, writes, skipped, args.verbose)
    if not writes:
        print("Nothing to deploy.")
        return 0

    if any(places.staged_path(w.target.dst) for w in writes) and not args.no_verify:
        ok, output = verify(places, writes)
        if ok is None:
            sys.exit(f"Can't check the Hyprland config: {output}. Pass --no-verify to deploy anyway.")
        if not ok:
            print("\n".join(output.splitlines()[-20:]), file=sys.stderr)
            before, _ = verify(places, [])
            state = "loads" if before else "already fails too"
            sys.exit(f"\nThe Hyprland config fails to load after this deploy (your current one {state}). "
                     "Nothing was written.")
        print("Hyprland config with these changes: loads (Hyprland --verify-config)")

    if not args.apply:
        print("Dry run. Pass --apply to deploy.")
        return 0

    backup = apply(places, writes)
    print(f"\nDeployed {len(writes)} files. Backup: {backup.name}")
    print(f"Undo:  {REPO / 'Scripts/deploy_live.py'} --rollback {backup.name}")
    print(f"Or by hand, from a TTY:  cp -a {backup / 'files'}/. ~/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
