"""Pacman manager implementation."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from contextlib import contextmanager
from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from tempfile import TemporaryDirectory, mktemp
from typing import Iterator, Sequence
from xml.etree import ElementTree

import sys
from pathlib import Path as _Path
_BASE_DIR = _Path(__file__).resolve().parent
if str(_BASE_DIR) not in sys.path:
    sys.path.insert(0, str(_BASE_DIR))

from meta import PMMetadata, UpdateEntry, parse_update_lines

AUR_HELPERS = ("paru", "paru-bin", "yay", "yay-bin")
PackageEntry = tuple[str, str | None, str | None, str | None]
PACMAN_LOG = Path("/var/log/pacman.log")
NEWS_FEED = "https://archlinux.org/feeds/news/"

# Metadata: pacman is a base package manager with high priority
META = PMMetadata(
    name="pacman",
    priority=10,
    is_base=True,
    conflicts=("paru", "paru-bin", "yay", "yay-bin"),
    overrides=("paru", "paru-bin", "yay", "yay-bin"),
    refresh_with_upgrade=True,
)


def install(ctx, packages: Sequence[str], no_confirm: bool = False) -> None:
    remaining = list(packages)
    for helper in AUR_HELPERS:
        if helper in remaining:
            _install_aur_helper(ctx, helper, no_confirm=no_confirm)
            remaining = [pkg for pkg in remaining if pkg != helper]
    if remaining:
        args = ["sudo", "pacman", "-S", "--needed"]
        if no_confirm:
            args.append("--noconfirm")
        args.extend(remaining)
        ctx.run(args)


def remove(ctx, packages: Sequence[str], no_confirm: bool = False) -> None:
    args = ["sudo", "pacman", "-Rsc"]
    if no_confirm:
        args.append("--noconfirm")
    args.extend(packages)
    ctx.run(args)


def upgrade(ctx, no_confirm: bool = False) -> None:
    args = ["sudo", "pacman", "-Syu"]
    if no_confirm:
        args.append("--noconfirm")
    ctx.run(args)


def fetch(ctx) -> None:
    """List what an upgrade would bring, from checkupdates' own copy of the databases.

    `pacman -Sy` would leave the system's databases ahead of what is installed,
    and the next install would be a partial upgrade. Only upgrade() refreshes them.
    """
    list_updates(ctx)


def info(ctx, package: str) -> None:
    if package in AUR_HELPERS:
        print("\033[1mRepository  :\033[0m aur")
        print(f"\033[1mName        :\033[0m {package}")
        print("\033[1mDescription :\033[0m AUR helper")
        return
    ctx.run(["pacman", "-Si", f"--color={_color_flag(ctx)}", package])


def list_all(ctx) -> list[PackageEntry]:
    entries: list[PackageEntry] = []
    output = ctx.capture(["pacman", "-Sl", "--color=never"])
    for line in output.splitlines():
        parts = line.split()
        if len(parts) < 3:
            continue
        repo, name, version = parts[:3]
        status = parts[3] if len(parts) > 3 else None
        entries.append((name, repo, version, status))
    entries.extend((helper, "aur", None, "AUR helper") for helper in AUR_HELPERS)
    return entries


def list_installed(ctx) -> list[PackageEntry]:
    entries: list[PackageEntry] = []
    output = ctx.capture(["pacman", "-Q", "--color=never"])
    for line in output.splitlines():
        parts = line.split()
        if len(parts) >= 2:
            entries.append((parts[0], None, parts[1], None))
    return entries


def is_installed(ctx, package: str) -> bool:
    return ctx.run(["pacman", "-Q", package], check=False, capture=True).returncode == 0


def file_query(ctx, target: str) -> int:
    return ctx.run(["pacman", "-F", target], check=False).returncode


def count_updates(ctx) -> int:
    with _checkupdates_env() as env:
        output = ctx.capture(["checkupdates"], check=False, env=env)
        return sum(1 for line in output.splitlines() if line.strip())


def list_updates(ctx) -> None:
    with _checkupdates_env() as env:
        ctx.run(["checkupdates"], check=False, env=env)


def get_updates(ctx) -> list[UpdateEntry]:
    with _checkupdates_env() as env:
        # checkupdates exits 2 when nothing is pending and 1 when it couldn't check
        result = ctx.run(["checkupdates", "--nocolor"], check=False, capture=True, env=env)
        if result.returncode not in (0, 2):
            raise subprocess.CalledProcessError(result.returncode, result.args, result.stdout, result.stderr)
        entries = parse_update_lines(result.stdout)
        downloads = _pending_downloads(ctx, env["CHECKUPDATES_DB"]) if entries else {}
    listed = {name for name, *_ in entries}
    updates = [(name, old, new, downloads.get(name, (None, None))[1]) for name, old, new, _ in entries]
    # New dependencies the upgrade pulls in show up in the download list only
    updates.extend((name, None, version, size) for name, (version, size) in downloads.items() if name not in listed)
    return updates


def last_upgrade(ctx) -> float | None:
    """Timestamp of the last full system upgrade, from the pacman log."""
    stamp = None
    try:
        with PACMAN_LOG.open(encoding="utf-8", errors="replace") as log:
            for line in log:
                if "starting full system upgrade" in line:
                    stamp = line[1:line.find("]")]
    except OSError:
        return None
    return _parse_log_time(stamp) if stamp else None


def news(ctx, since: float) -> list[tuple[float, str, str]]:
    """Arch news published after `since`, newest first, as (timestamp, title, link)."""
    feed = ctx.capture(["curl", "-fsSL", "--max-time", "5", NEWS_FEED], check=False)
    try:
        root = ElementTree.fromstring(feed)
    except ElementTree.ParseError:
        return []
    items = []
    for item in root.iter("item"):
        try:
            published = parsedate_to_datetime(item.findtext("pubDate", "")).timestamp()
        except (TypeError, ValueError):
            continue
        if published > since:
            items.append((published, item.findtext("title", "").strip(), item.findtext("link", "").strip()))
    return items


def pacnew_files(ctx) -> list[str]:
    if not shutil.which("pacdiff"):
        return []
    return ctx.capture(["pacdiff", "--output"], check=False).splitlines()


def orphans(ctx) -> list[str]:
    return ctx.capture(["pacman", "-Qdtq"], check=False).split()


def remove_orphans(ctx, packages: Sequence[str]) -> bool:
    """Remove with -Rns, not remove()'s cascading -Rsc. pacman lists the packages and asks first."""
    return ctx.run(["sudo", "pacman", "-Rns", *packages], check=False).returncode == 0


def mark_explicit(ctx, packages: Sequence[str]) -> bool:
    """Record packages as explicitly installed so they stop counting as orphans."""
    return ctx.run(["sudo", "pacman", "-D", "--asexplicit", *packages], check=False).returncode == 0


def describe(ctx, packages: Sequence[str]) -> dict[str, str]:
    """Map installed packages to their one-line descriptions."""
    descriptions = {}
    name = None
    # ctx.run forces LC_ALL=C, so the field names aren't translated
    for line in ctx.capture(["pacman", "-Qi", *packages], check=False).splitlines():
        key, _, value = line.partition(":")
        if key.strip() == "Name":
            name = value.strip()
        elif key.strip() == "Description" and name:
            descriptions[name] = value.strip()
    return descriptions


def cache_savings(ctx) -> str | None:
    """How much `paccache -r` would free, e.g. "1.2 GiB"."""
    if not shutil.which("paccache"):
        return None
    match = re.search(r"disk space saved: ([^)]+)\)", ctx.capture(["paccache", "-d"], check=False))
    return match.group(1) if match else None


def _pending_downloads(ctx, db_path: str) -> dict[str, tuple[str, int]]:
    """Map each package `pacman -Su` would fetch to (version, download bytes), using checkupdates' database."""
    output = ctx.capture(
        ["pacman", "-Sup", "--noconfirm", "--dbpath", db_path, "--logfile", "/dev/null", "--print-format", "%n %v %s"],
        check=False,
    )
    downloads = {}
    for line in output.splitlines():
        parts = line.split()
        if len(parts) == 3 and parts[2].isdigit():
            downloads[parts[0]] = (parts[1], int(parts[2]))
    return downloads


def _parse_log_time(stamp: str) -> float | None:
    # Current pacman logs ISO timestamps; entries from older versions use the short form
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(stamp, fmt).timestamp()
        except ValueError:
            continue
    return None


@contextmanager
def _checkupdates_env() -> Iterator[dict[str, str]]:
    temp_db = mktemp(
        dir=os.environ.get("XDG_RUNTIME_DIR", "/tmp"),
        prefix="checkupdates_db_",
    )
    env = os.environ.copy()
    env["CHECKUPDATES_DB"] = temp_db
    try:
        yield env
    finally:
        _cleanup_checkupdates_db(temp_db)


def _cleanup_checkupdates_db(path: str) -> None:
    try:
        p = Path(path)
    except (TypeError, ValueError):
        return
    try:
        if p.is_dir() and not p.is_symlink():
            shutil.rmtree(p)
        elif p.exists() or p.is_symlink():
            p.unlink()
    except FileNotFoundError:
        pass


def _install_aur_helper(ctx, helper: str, no_confirm: bool = False) -> None:
    args = ["sudo", "pacman", "-S", "--needed", "git", "base-devel"]
    ctx.run(args)
    with TemporaryDirectory() as tmp:
        repo_path = Path(tmp) / helper
        ctx.run(["git", "clone", f"https://aur.archlinux.org/{helper}.git", str(repo_path)])
        mk_args = ["makepkg", "-si"]
        if no_confirm or getattr(ctx, "no_confirm", False):
            mk_args.append("--noconfirm")
        ctx.run(mk_args, cwd=repo_path)


def _color_flag(ctx) -> str:
    return "always" if ctx.color_mode == "always" else "never"
