# Contributing

Hyprion is an opinionated, independently maintained fork of [HyDE-Project/HyDE](https://github.com/HyDE-Project/HyDE). It tracks Hyprland releases on its own schedule and has a single long-lived branch, `main`.

## Workflow

1. Branch from `main`.
2. Make the change. Follow [COMMIT_MESSAGE_GUIDELINES.md](COMMIT_MESSAGE_GUIDELINES.md) for the commit message.
3. If the change is visible to a user, add a line under `## Unreleased` in `CHANGELOG.md`. Describe what the user sees, not how the code changed.
4. Run what applies before pushing:
   - `bash -n` on every shell script you touched
   - `lua Scripts/tests/lua/config_toml_test.lua` from the repo root if you touched the Lua config loader
   - `Scripts/install.sh -r` on a scratch machine or VM for anything that changes what gets deployed
5. Open a pull request against `main`.

## Pulling from upstream

Upstream stays configured as the `upstream` remote and is a cherry-pick source, not a merge target:

```bash
git fetch upstream
git log --oneline main..upstream/master -- <path>   # see what changed
git cherry-pick <sha>
```

Their CI, release promotion scripts and the `tests` submodule were removed from this fork on purpose. Do not bring them back with a cherry-pick.

## Where things live

- `Configs/` is what gets deployed into `$HOME`. HyDE's own Hyprland config is under `Configs/.local/share/hypr/lua/` and is overwritten on every deploy.
- `Configs/.config/hypr/hyprland.lua` is the user's override file. It is deployed only when absent and never overwritten. A fuller example lives at `Source/examples/hyprland.lua`.
- `Scripts/dots/*.toml` are the deez-dots manifests that decide which files are synced, preserved or ignored.
- `Scripts/tests/` holds this fork's tests.
