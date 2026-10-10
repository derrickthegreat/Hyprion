#!/usr/bin/env python3
"""System update helper using pm.py backends."""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import pm

XDG_RUNTIME_DIR = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp"))
STATE_DIR = XDG_RUNTIME_DIR / "hyde"
UPDATE_INFO = STATE_DIR / "update_info.json"
CACHE_DIR = STATE_DIR / "pm" / "system_update"
SCRIPT_PATH = Path(__file__).resolve()
MODULES_ROOT = Path("/usr/lib/modules")

# Nerd Font glyphs, by name
ICON_UPDATES = "\U000f0baf"  # md-pac_man, same as the waybar module
ICON_UP_TO_DATE = "\uf058"  # fa-ok_sign
ICON_NEWS = "\U000f0395"  # md-newspaper
ICON_REBOOT = "\U000f0709"  # md-restart
ICON_LOGOUT = "\U000f0343"  # md-logout
ICON_PACNEW = "\U000f08aa"  # md-file_compare
ICON_ORPHANS = "\U000f03d7"  # md-package_variant_closed
ICON_CACHE = "\U000f05e9"  # md-delete_sweep
MANAGER_ICONS = {
    "pacman": "\uf303",  # linux-archlinux
    "paru": "\U000f03d7",  # md-package_variant_closed
    "yay": "\U000f03d7",
    "flatpak": "\uf324",  # linux-flathub
}
DEFAULT_MANAGER_ICON = "\U000f03d6"  # md-package_variant

# Updates to these only take effect after a reboot. Installed kernels are added
# at runtime from the pkgbase file each Arch kernel ships in its modules dir.
KERNEL_PACKAGES = {"linux", "linux-lts", "linux-zen", "linux-hardened", "linux-rt", "linux-rt-lts"}
REBOOT_PACKAGES = {
    "systemd", "glibc", "amd-ucode", "intel-ucode",
    "nvidia", "nvidia-open", "nvidia-dkms", "nvidia-open-dkms", "nvidia-lts", "nvidia-utils",
}
# Updates to these take effect on the next login
RELOG_PACKAGES = {"hyprland", "hyprland-git", "aquamarine", "xdg-desktop-portal-hyprland", "mesa"}

TOOLTIP_PACKAGES = 5
NEWS_ITEMS = 3
NAME_WIDTH = 32

COLOR = sys.stdout.isatty() and "NO_COLOR" not in os.environ
BOLD, MUTED, RED, GREEN, YELLOW, MAGENTA, CYAN = "1", "90", "31", "32", "33", "35", "36"
TAG_STYLES = {"reboot": (BOLD, RED), "relog": (BOLD, YELLOW), "new": (CYAN,), "rebuild": (MUTED,)}


@dataclass(slots=True)
class Pending:
    name: str
    old: str | None
    new: str | None
    size: int | None = None


@dataclass(slots=True)
class ManagerUpdates:
    name: str
    count: int
    # None when the backend can only count its updates, not list them
    packages: list[Pending] | None = None
    error: str | None = None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="System update status helper.")
    parser.add_argument(
        "action",
        nargs="?",
        choices=["status", "up", "interactive", "refresh-waybar"],
        default="status",
    )
    return parser


def paint(text: str, *codes: str) -> str:
    if not COLOR or not text:
        return text
    return f"\033[{';'.join(codes)}m{text}\033[0m"


def plural(count: int, word: str) -> str:
    return f"{count} {word}{'' if count == 1 else 's'}"


def human_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if value < 1024 or unit == "GiB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GiB"


def ago(timestamp: float, now: float | None = None) -> str:
    seconds = max(0.0, (time.time() if now is None else now) - timestamp)
    for unit, length in (("day", 86400), ("hour", 3600), ("minute", 60)):
        if seconds >= length:
            return f"{plural(int(seconds // length), unit)} ago"
    return "just now"


def truncate(text: str, width: int) -> str:
    return text if len(text) <= width else text[: width - 1] + "…"


_VERSION_PART = re.compile(r"[.:+~_-]|[^.:+~_-]+")


def split_version(old: str | None, new: str | None) -> tuple[str, str]:
    """Split `new` into the leading segments it shares with `old` and the part that changed."""
    if not old or not new:
        return "", new or ""
    shared = []
    for old_part, new_part in zip(_VERSION_PART.findall(old), _VERSION_PART.findall(new)):
        if old_part != new_part:
            break
        shared.append(new_part)
    prefix = "".join(shared)
    return prefix, new[len(prefix):]


def is_rebuild(old: str | None, new: str | None) -> bool:
    """Only the pkgrel after the last dash changed, e.g. 1.2-1 -> 1.2-2."""
    if not old or not new or old == new or "-" not in old or "-" not in new:
        return False
    return old.rsplit("-", 1)[0] == new.rsplit("-", 1)[0]


def kernel_packages(modules_root: Path = MODULES_ROOT) -> set[str]:
    names = set(KERNEL_PACKAGES)
    for pkgbase in modules_root.glob("*/pkgbase"):
        try:
            names.add(pkgbase.read_text(encoding="utf-8").strip())
        except OSError:
            continue
    return names


def kernel_replaced(release: str, modules_root: Path = MODULES_ROOT) -> bool:
    """The running kernel's modules are gone, so it was upgraded or removed since boot."""
    return modules_root.is_dir() and not (modules_root / release).is_dir()


def needs_reboot(name: str, kernels: set[str]) -> bool:
    return name in kernels or name in REBOOT_PACKAGES or name.startswith("linux-firmware")


def package_tag(pkg: Pending, kernels: set[str]) -> str | None:
    if needs_reboot(pkg.name, kernels):
        return "reboot"
    if pkg.name in RELOG_PACKAGES:
        return "relog"
    if pkg.old is None:
        return "new"
    if is_rebuild(pkg.old, pkg.new):
        return "rebuild"
    return None


def state_for(name: str, color_mode: str = "never") -> pm.PMState:
    cache_dir = CACHE_DIR / name
    cache_dir.mkdir(parents=True, exist_ok=True)
    ctx = pm.ManagerContext(name, color_mode, cache_dir, no_confirm=False)
    return pm.PMState(
        name=name,
        module=pm.load_manager(name),
        ctx=ctx,
        colors=pm.build_color_profile(color_mode),
        script_path=SCRIPT_PATH,
        no_confirm=False,
    )


def requirements(name: str) -> tuple[str, ...]:
    return getattr(getattr(pm.load_manager(name), "META", None), "requires", ())


def call_hook(func_name: str, *args: object, default=None):
    """Call an optional backend function on the first manager that provides it."""
    for name in pm.list_available_managers():
        state = state_for(name)
        if hasattr(state.module, func_name):
            try:
                return pm.call_module(state, func_name, *args)
            except (subprocess.CalledProcessError, OSError):
                return default
    return default


def error_text(exc: Exception) -> str:
    if isinstance(exc, subprocess.CalledProcessError):
        lines = [line.strip() for line in (exc.stderr or "").splitlines() if line.strip()]
        # Drop the "==> ERROR: " banner checkupdates and makepkg put in front
        return re.sub(r"^(==> )?(ERROR|error): ", "", lines[-1]) if lines else f"exit code {exc.returncode}"
    return str(exc) or type(exc).__name__


def check_manager(name: str) -> ManagerUpdates | None:
    state = state_for(name)
    try:
        if hasattr(state.module, "get_updates"):
            packages = [Pending(*entry) for entry in pm.call_module(state, "get_updates")]
            return ManagerUpdates(name, len(packages), packages)
        if hasattr(state.module, "count_updates"):
            return ManagerUpdates(name, max(int(pm.call_module(state, "count_updates") or 0), 0))
    except (subprocess.CalledProcessError, OSError, SystemExit, ValueError) as exc:
        return ManagerUpdates(name, 0, error=error_text(exc))
    return None


def collect_updates(progress: bool = False) -> list[ManagerUpdates]:
    updates = []
    for name in pm.list_available_managers():
        if progress and COLOR:
            print(f"\r\033[K{paint(f'Checking {name}…', MUTED)}", end="", flush=True)
        result = check_manager(name)
        if result is not None:
            updates.append(result)
    if progress and COLOR:
        print("\r\033[K", end="", flush=True)
    return updates


def total_updates(updates: list[ManagerUpdates]) -> int:
    return sum(manager.count for manager in updates)


def download_size(packages: list[Pending]) -> int | None:
    sizes = [pkg.size for pkg in packages if pkg.size is not None]
    return sum(sizes) if sizes else None


def store_records(updates: list[ManagerUpdates]) -> None:
    UPDATE_INFO.parent.mkdir(parents=True, exist_ok=True)
    payload = {"managers": [{"name": manager.name, "count": manager.count} for manager in updates]}
    UPDATE_INFO.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def refresh_waybar() -> None:
    subprocess.run(["pkill", "-RTMIN+20", "waybar"], check=False)


def build_tooltip(updates: list[ManagerUpdates], kernels: set[str], reboot_pending: bool) -> str:
    if not updates:
        return "No supported package managers found"
    total = total_updates(updates)
    lines = [f"<b>{plural(total, 'update')}</b>"] if total else [f"{ICON_UP_TO_DATE} Packages are up to date"]
    for manager in updates:
        icon = MANAGER_ICONS.get(manager.name, DEFAULT_MANAGER_ICON)
        if manager.error:
            lines.append(f"{icon} {manager.name}: couldn't check")
            continue
        if not manager.count:
            continue
        lines.append(f"{icon} {manager.name}: {manager.count}")
        for pkg in (manager.packages or [])[:TOOLTIP_PACKAGES]:
            tag = package_tag(pkg, kernels)
            note = f" <i>({tag})</i>" if tag in ("reboot", "relog") else ""
            lines.append(f"    {html.escape(pkg.name)} {html.escape(pkg.new or '')}{note}".rstrip())
        hidden = len(manager.packages or []) - TOOLTIP_PACKAGES
        if hidden > 0:
            lines.append(f"    …and {hidden} more")
    if reboot_pending:
        lines.append(f"{ICON_REBOOT} Reboot needed: the running kernel was replaced")
    return "\n".join(lines)


def status_json(updates: list[ManagerUpdates], kernels: set[str], reboot_pending: bool) -> str:
    total = total_updates(updates)
    classes = ["updates" if total else "up-to-date"]
    if reboot_pending:
        classes.append("reboot-needed")
    tags = {package_tag(pkg, kernels) for manager in updates for pkg in manager.packages or []}
    if tags & {"reboot", "relog"}:
        classes.append("important")
    if total:
        text = f"{ICON_UPDATES} {total}"
    else:
        text = ICON_REBOOT if reboot_pending else ""
    payload = {"text": text, "tooltip": build_tooltip(updates, kernels, reboot_pending), "class": classes}
    return json.dumps(payload, ensure_ascii=False)


def term_width() -> int:
    return max(60, min(shutil.get_terminal_size((80, 24)).columns, 100))


def print_rule(width: int) -> None:
    print(paint("─" * width, MUTED))


def print_spread(left: str, right: str, width: int) -> None:
    """Print `left` with `right` aligned to the right edge, measuring without color codes."""
    if not right:
        print(left)
        return
    gap = max(width - len(pm.strip_ansi(left)) - len(pm.strip_ansi(right)), 2)
    print(left + " " * gap + right)


def print_header(width: int, last_run: float | None) -> None:
    title = f"{ICON_UPDATES} System Update"
    right = paint(f"last updated {ago(last_run)}", MUTED) if last_run else ""
    print_spread(paint(title, BOLD), right, width)
    print_rule(width)


def print_news(items: list[tuple[float, str, str]]) -> None:
    print(f"{ICON_NEWS} {paint('Arch news since your last update', BOLD, YELLOW)}")
    for published, title, link in items[:NEWS_ITEMS]:
        date = time.strftime("%b %d", time.localtime(published))
        print(f"   {paint(date, MUTED)}  {paint(title, BOLD)}")
        print(f"   {' ' * len(date)}  {paint(link, MUTED)}")


def package_rows(packages: list[Pending], kernels: set[str]) -> list[str]:
    names = [truncate(pkg.name, NAME_WIDTH) for pkg in packages]
    name_width = max(map(len, names))
    old_width = max(len(pkg.old or "") for pkg in packages)
    new_width = max(len(pkg.new or "") for pkg in packages)
    rows = []
    for pkg, name in zip(packages, names):
        old, new = pkg.old or "", pkg.new or ""
        prefix, changed = split_version(old, new)
        old_cell = paint(old[: len(prefix)], MUTED) + old[len(prefix):] + " " * (old_width - len(old))
        new_cell = paint(prefix, MUTED) + paint(changed, BOLD, GREEN) + " " * (new_width - len(new))
        if not old and not new:
            # Flatpak runtimes often carry no version, only a new commit
            new_cell = paint("new commit", MUTED)
        arrow = paint("→", MUTED) if old else " "
        tag = package_tag(pkg, kernels)
        tag_cell = paint(tag, *TAG_STYLES[tag]) if tag else ""
        rows.append(f"   {name.ljust(name_width)}  {old_cell}  {arrow}  {new_cell}  {tag_cell}".rstrip())
    return rows


def print_manager(manager: ManagerUpdates, kernels: set[str], width: int) -> None:
    icon = MANAGER_ICONS.get(manager.name, DEFAULT_MANAGER_ICON)
    # Each manager opens its own block, set off by a blank line and the accent color
    print()
    title = paint(f"{icon} {manager.name}", BOLD, MAGENTA)
    if manager.error:
        print(f"{title} " + paint(f"· couldn't check: {manager.error}", RED))
        return
    if not manager.count:
        print(f"{title} {paint('· up to date', GREEN)}")
        return
    summary = paint(f"· {manager.count} pending", MUTED)
    size = download_size(manager.packages or [])
    right = f"↓ {human_size(size)}" if size is not None else ""
    print_spread(f"{title} {summary}", paint(right, CYAN), width)
    if manager.packages is None:
        # The backend can't describe its updates, so show its own listing
        try:
            pm.call_module(state_for(manager.name, color_mode="always"), "list_updates")
        except (subprocess.CalledProcessError, OSError, SystemExit) as exc:
            print(paint(f"   Could not list updates: {error_text(exc)}", RED))
        return
    for row in package_rows(manager.packages, kernels):
        print(row)


def print_footer(updates: list[ManagerUpdates], width: int) -> None:
    print_rule(width)
    total = total_updates(updates)
    if not total:
        print(paint(f"{ICON_UP_TO_DATE} System is up to date.", GREEN))
        return
    parts = [plural(total, "update")]
    size = download_size([pkg for manager in updates for pkg in manager.packages or []])
    if size is not None:
        parts.append(f"↓ {human_size(size)} to download")
    print(paint(" · ".join(parts), BOLD))


def prompt_yes_no(prompt: str, default_yes: bool = True, spaced: bool = True) -> bool:
    default = "[Y/n]" if default_yes else "[y/N]"
    try:
        answer = input(f"{chr(10) if spaced else ''}{prompt} {default} ").strip().lower()
    except EOFError:
        return default_yes
    if not answer:
        return default_yes
    return answer in {"y", "yes"}


def keep_requirements(chosen: list[str], pending: list[str]) -> list[str]:
    """Drop managers whose required manager has pending updates that won't be applied."""
    kept = []
    for name in chosen:
        skipped = [base for base in requirements(name) if base in pending and base not in chosen]
        if skipped:
            print(paint(f"Skipping {name}: it builds against {', '.join(skipped)} packages you chose not to update.", YELLOW))
            continue
        kept.append(name)
    return kept


def choose_managers(updates: list[ManagerUpdates]) -> list[str]:
    pending = [manager for manager in updates if manager.count]
    if len(pending) == 1:
        return [pending[0].name] if prompt_yes_no("Apply updates now?") else []
    keys = f"[{paint('A', BOLD)}]ll  [{paint('p', BOLD)}]ick  [{paint('n', BOLD)}]o"
    try:
        answer = input(f"\nApply updates? {keys} ").strip().lower()[:1] or "a"
    except EOFError:
        return []
    if answer == "a":
        chosen = [manager.name for manager in pending]
    elif answer == "p":
        chosen = [m.name for m in pending if prompt_yes_no(f"  Update {m.name} ({m.count})?", spaced=False)]
    else:
        return []
    return keep_requirements(chosen, [manager.name for manager in pending])


def run_upgrades(names: list[str], width: int) -> tuple[list[str], list[str]]:
    done: list[str] = []
    failed: list[str] = []
    for name in names:
        blocked = [base for base in requirements(name) if base in failed]
        if blocked:
            print(paint(f"\nSkipping {name}: {', '.join(blocked)} didn't finish updating.", YELLOW))
            failed.append(name)
            continue
        print(f"\n{MANAGER_ICONS.get(name, DEFAULT_MANAGER_ICON)} {paint(f'Updating {name}', BOLD)}")
        print_rule(width)
        try:
            pm.call_module(state_for(name, color_mode="always"), "upgrade")
            done.append(name)
        except (subprocess.CalledProcessError, OSError, SystemExit):
            failed.append(name)
    return done, failed


def print_after(done: list[str], failed: list[str], pacnew_before: list[str], width: int) -> list[str]:
    """Report what the update left to do. Returns the orphaned packages."""
    print()
    print_rule(width)
    print(paint("After the update", BOLD))
    if done:
        print(f"   {paint('✓', GREEN)} {', '.join(done)} updated")
    if failed:
        print(f"   {paint('✗', RED)} {', '.join(failed)} didn't finish")
    new_pacnew = [path for path in call_hook("pacnew_files", default=[]) if path not in pacnew_before]
    if new_pacnew:
        print(f"   {ICON_PACNEW} {plural(len(new_pacnew), 'new .pacnew file')}, merge with {paint('sudo pacdiff', CYAN)}")
        for path in new_pacnew:
            print(f"      {paint(path, MUTED)}")
    orphans = call_hook("orphans", default=[])
    if orphans:
        print(f"   {ICON_ORPHANS} {plural(len(orphans), 'orphaned package')}, nothing installed needs them")
    savings = call_hook("cache_savings")
    if savings:
        print(f"   {ICON_CACHE} {savings} of old packages in the cache, clear with {paint('sudo paccache -r', CYAN)}")
    return orphans


def pick_orphans(orphans: list[str]) -> list[str]:
    """Mark orphans to remove in fzf, each shown with its description."""
    if not shutil.which("fzf"):
        print(paint("fzf isn't installed, so there's nothing to pick with.", YELLOW))
        return []
    descriptions = call_hook("describe", orphans, default={})
    width = max(map(len, orphans))
    lines = [f"{name.ljust(width)}  {paint(descriptions.get(name, ''), MUTED)}".rstrip() for name in orphans]
    result = subprocess.run(
        [
            "fzf", "--multi", "--ansi", "--layout=reverse", "--bind=ctrl-a:toggle-all", "--prompt=Remove> ",
            "--header=Tab marks a package · Ctrl-A toggles all · Enter removes the marked · Esc cancels",
        ],
        input="\n".join(lines),
        stdout=subprocess.PIPE,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return []
    return [pm.strip_ansi(line).split()[0] for line in result.stdout.splitlines() if line.strip()]


def clean_orphans(orphans: list[str]) -> None:
    """Offer to remove orphans, then to mark the ones kept so they stop showing up."""
    keys = f"[{paint('a', BOLD)}]ll  [{paint('p', BOLD)}]ick  [{paint('N', BOLD)}]o"
    try:
        answer = input(f"\nRemove orphaned packages? {keys} ").strip().lower()[:1]
    except EOFError:
        return
    if answer == "a":
        chosen = orphans
    elif answer == "p":
        chosen = pick_orphans(orphans)
    else:
        return
    if not chosen:
        return
    if not call_hook("remove_orphans", chosen, default=False):
        print(paint("Orphans left in place.", YELLOW))
        return
    # -Rns can't take an unpicked orphan with it, since by definition nothing depends on one
    kept = [name for name in orphans if name not in chosen]
    if kept and prompt_yes_no(f"Mark the other {plural(len(kept), 'orphan')} as explicitly installed so they stop showing up?", default_yes=False):
        if not call_hook("mark_explicit", kept, default=False):
            print(paint("Couldn't mark them, they'll show up again next time.", YELLOW))


def offer_restart(upgraded: list[Pending], kernels: set[str]) -> bool:
    """Ask to reboot or log out when updated packages need it. True if the session is ending."""
    release = os.uname().release
    reboot_for = sorted({pkg.name for pkg in upgraded if needs_reboot(pkg.name, kernels)})
    if reboot_for or kernel_replaced(release):
        reason = f"{', '.join(reboot_for)} updated" if reboot_for else f"The running kernel ({release}) was replaced"
        print(f"\n{ICON_REBOOT} {paint('Reboot recommended', BOLD, YELLOW)}: {reason}.")
        if prompt_yes_no("Reboot now?", default_yes=False, spaced=False):
            subprocess.run(["systemctl", "reboot"], check=False)
            return True
        return False
    relog_for = sorted({pkg.name for pkg in upgraded if pkg.name in RELOG_PACKAGES})
    if relog_for:
        print(f"\n{ICON_LOGOUT} {paint('Log out to finish', BOLD, YELLOW)}: {', '.join(relog_for)} updated.")
        if prompt_yes_no("Log out now?", default_yes=False, spaced=False):
            subprocess.run(["hyde-shell", "logout"], check=False)
            return True
    return False


def wait_for_enter() -> None:
    try:
        input("\nPress Enter to close...")
    except EOFError:
        pass


def interactive() -> int:
    width = term_width()
    kernels = kernel_packages()
    last_run = call_hook("last_upgrade")
    print_header(width, last_run)
    updates = collect_updates(progress=True)
    store_records(updates)
    if last_run:
        news = call_hook("news", last_run, default=[])
        if news:
            print_news(news)
    for manager in updates:
        print_manager(manager, kernels, width)
    print_footer(updates, width)

    exit_code = 0
    upgraded: list[Pending] = []
    if total_updates(updates):
        chosen = choose_managers(updates)
        if chosen:
            pacnew_before = call_hook("pacnew_files", default=[])
            done, failed = run_upgrades(chosen, width)
            upgraded = [pkg for manager in updates if manager.name in done for pkg in manager.packages or []]
            exit_code = 1 if failed else 0
            orphans = print_after(done, failed, pacnew_before, width)
            remaining = collect_updates(progress=True)
            store_records(remaining)
            left = total_updates(remaining)
            if left:
                print("   " + paint(f"{plural(left, 'update')} still pending", YELLOW))
            if orphans:
                clean_orphans(orphans)
        else:
            print(paint("\nSkipped updates.", YELLOW))
    refresh_waybar()

    if offer_restart(upgraded, kernels):
        return exit_code
    wait_for_enter()
    return exit_code


def launch_interactive() -> int:
    launcher = shutil.which("xdg-terminal-exec")
    if launcher is not None:
        # Own session: Waybar SIGTERMs its on-click's process group on every reload,
        # and a theme change mid-update must not take pacman down with the terminal.
        subprocess.run(
            [launcher, "--title=systemupdate", "--", sys.executable, str(SCRIPT_PATH), "interactive"],
            check=False,
            start_new_session=True,
        )
        return 0
    if sys.stdout.isatty():
        return interactive()
    print("system_update: xdg-terminal-exec is not available", file=sys.stderr)
    return 1


def status_mode() -> int:
    updates = collect_updates()
    store_records(updates)
    print(status_json(updates, kernel_packages(), kernel_replaced(os.uname().release)))
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.action == "refresh-waybar":
        refresh_waybar()
        return 0
    if args.action == "interactive":
        try:
            return interactive()
        except KeyboardInterrupt:
            print("\nCancelled.")
            return 130
    if args.action == "up":
        return launch_interactive()
    return status_mode()


if __name__ == "__main__":
    raise SystemExit(main())
