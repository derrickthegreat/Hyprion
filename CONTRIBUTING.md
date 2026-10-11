# Contributing

Hyprion is an opinionated, independently maintained fork of [HyDE-Project/HyDE](https://github.com/HyDE-Project/HyDE). It tracks Hyprland releases on its own schedule and has a single long-lived branch, `main`.

## Workflow

1. Branch from `main`.
2. Make the change. Follow [COMMIT_MESSAGE_GUIDELINES.md](COMMIT_MESSAGE_GUIDELINES.md) for the commit message.
3. If the change is visible to a user, add a line under `## Unreleased` in `CHANGELOG.md`. Describe what the user sees, not how the code changed.
4. Run what applies before pushing:
   - `Scripts/tests/run.sh`, which runs every suite under `Scripts/tests/`. CI runs it on every push and pull request, in an Arch container with Hyprland installed. Locally, the Hyprland config check is skipped if Hyprland isn't installed.
   - `bash -n` on every shell script you touched
   - `Scripts/install.sh -r` on a scratch machine or VM for anything that changes what gets deployed
   - If you change how HyDE's Lua handles binds or other user config, add a user config to `Scripts/tests/hyprland/fixtures/` that does what you're worried about. Each fixture is loaded by the real `Hyprland --verify-config`, which catches crashes the stubbed Lua tests can't.
5. Open a pull request against `main`.

## Trying a change on your own desktop

`Scripts/deploy_live.py` copies this checkout into your home the way `install.sh -r` would, for the dots you have installed. Run it without arguments first. It lists what it would write, then loads the result in Hyprland (`--verify-config`, with your own `hyprland.lua`) in a scratch copy, so a config that would crash your session is caught before anything is written. `--apply` deploys, with Hyprland's autoreload paused until every file is in place. `--rollback` undoes the last deploy and works from a TTY.

It only replaces files that match a version this repo produced. A file you edited, or one wallbash generates, is listed and left alone unless you name it with `--force`. "preserve" files such as your `hyprland.lua` are never written.

## Pulling from upstream

Upstream stays configured as the `upstream` remote and is a cherry-pick source, not a merge target:

```bash
git fetch upstream
git log --oneline main..upstream/master -- <path>   # see what changed
git cherry-pick <sha>
```

Their CI, release promotion scripts and the `tests` submodule were removed from this fork on purpose. Do not bring them back with a cherry-pick. This fork's own CI is `.github/workflows/tests.yml`.

## Where things live

- `Configs/` is what gets deployed into `$HOME`. HyDE's own Hyprland config is under `Configs/.local/share/hypr/lua/` and is overwritten on every deploy.
- `Configs/.config/hypr/hyprland.lua` is the user's override file. It is deployed only when absent and never overwritten. A fuller example lives at `Source/examples/hyprland.lua`.
- `Scripts/dots/*.toml` are the deez-dots manifests that decide which files are synced, preserved or ignored.
- `Scripts/tests/` holds this fork's tests.
