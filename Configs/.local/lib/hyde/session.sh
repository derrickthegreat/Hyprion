#!/usr/bin/env bash
# Starts Hyprland for the Hyprion SDDM session (/usr/local/bin/hyprion-session
# runs this), falling back to Hyprland's safe mode instead of the greeter.
#
# start-hyprland is meant to restart Hyprland in safe mode after a crash, but
# 0.56.2 loses the exit status ("Couldn't waitpid for hyprland: No child
# processes") and reports every crash as a clean exit. A config that crashed
# Hyprland at load therefore bounced each login back to SDDM. This checks the
# config before starting, and starts safe mode itself when the config doesn't
# load or the session crashed. Safe mode skips the config and has a button to
# load it once it's fixed.
#
# What happened is logged to $XDG_STATE_HOME/hyde/session/session.log, and the
# output of the last config check to verify.log next to it.

state_dir="${XDG_STATE_HOME:-$HOME/.local/state}/hyde/session"
crash_dir="${XDG_CACHE_HOME:-$HOME/.cache}/hyprland"
start_hyprland="${HYPRION_START_HYPRLAND:-/usr/bin/start-hyprland}"
hyprland="${HYPRION_HYPRLAND:-/usr/bin/Hyprland}"

mkdir -p "${state_dir}"
log="${state_dir}/session.log"

note() {
    printf '%s %s\n' "$(date '+%F %T')" "$*" >>"${log}"
}

# Loads the config without starting a session. The config runs hyprctl and
# hyde-shell while loading; with an empty PATH and a private runtime dir they
# go nowhere. Returns 0 when the check can't run, so it never blocks a login.
config_loads() {
    local scratch rc
    [[ -x ${hyprland} ]] || return 0
    scratch=$(mktemp -d) || return 0
    mkdir -m 700 "${scratch}/run" "${scratch}/bin"
    (
        cd "${scratch}" || exit 1
        ulimit -c 0
        # timeout goes first: env looks the command up on the PATH it sets.
        exec timeout 30 env -i \
            HOME="${HOME}" \
            ${XDG_CONFIG_HOME:+"XDG_CONFIG_HOME=${XDG_CONFIG_HOME}"} \
            ${XDG_DATA_HOME:+"XDG_DATA_HOME=${XDG_DATA_HOME}"} \
            ${XDG_STATE_HOME:+"XDG_STATE_HOME=${XDG_STATE_HOME}"} \
            ${XDG_CACHE_HOME:+"XDG_CACHE_HOME=${XDG_CACHE_HOME}"} \
            XDG_RUNTIME_DIR="${scratch}/run" \
            PATH="${scratch}/bin" \
            LANG=C.UTF-8 \
            "${hyprland}" --verify-config
    ) >"${state_dir}/verify.log" 2>&1
    rc=$?
    rm -rf "${scratch}"
    # The exit code, not the "config ok" text: a reworded message must not
    # send every login to safe mode.
    ((rc == 0))
}

# Crash reports newer than this marker belong to the session started below.
marker="${state_dir}/started"
: >"${marker}"

if config_loads; then
    note "config loads, starting Hyprland"
    "${start_hyprland}" "$@"
    crash=$(find "${crash_dir}" -maxdepth 1 -name 'hyprlandCrashReport*.txt' -newer "${marker}" -print -quit 2>/dev/null)
    if [[ -z ${crash} ]]; then
        note "session ended"
        exit 0
    fi
    note "Hyprland crashed (${crash}), starting safe mode"
else
    note "config failed to load (see ${state_dir}/verify.log), starting safe mode"
fi
exec "${start_hyprland}" -- --safe-mode
