"""Types and helpers shared by the package manager modules."""

import re
from dataclasses import dataclass


@dataclass(slots=True)
class PMMetadata:
    """Metadata that a package manager module declares about itself."""
    # Display name (defaults to module name)
    name: str = ""
    # Priority: lower = higher priority (checked first)
    # Base package managers: 10, AUR helpers: 20, Others: 30
    priority: int = 20
    # List of managers this one conflicts with/replaces
    # If both are available, the higher priority (lower number) wins
    conflicts: tuple[str, ...] = ()
    # Whether this is a base system package manager
    is_base: bool = False
    # Manager this one overrides (takes precedence when both available)
    overrides: tuple[str, ...] = ()
    # Managers whose pending updates must be applied before this one's
    requires: tuple[str, ...] = ()
    # Managers this one is a superset of (an AUR helper does everything pacman
    # does); interactive commands use it in their place
    extends: tuple[str, ...] = ()
    # The package databases may only be refreshed together with a full upgrade
    # (pacman and the AUR helpers): refreshed alone, the next install is a
    # partial upgrade. Installs then never fetch first.
    refresh_with_upgrade: bool = False


# Default metadata for managers that don't declare one
DEFAULT_META = PMMetadata()

# A pending update: (name, installed version, new version, download bytes).
# The installed version is None when the update installs the package fresh,
# and "" when the manager doesn't report it.
UpdateEntry = tuple[str, str | None, str | None, int | None]

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def parse_update_lines(output: str) -> list[UpdateEntry]:
    """Parse `name old -> new` lines (pacman -Qu style), skipping ignored packages."""
    entries: list[UpdateEntry] = []
    for line in output.splitlines():
        parts = _ANSI_RE.sub("", line).split()
        if len(parts) < 4 or parts[2] != "->" or "[ignored]" in parts[4:]:
            continue
        entries.append((parts[0], parts[1], parts[3], None))
    return entries
