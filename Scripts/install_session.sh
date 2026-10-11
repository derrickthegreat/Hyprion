#!/usr/bin/env bash
# Installs the Hyprion SDDM session: /usr/local/bin/hyprion-session and its
# entry in /usr/local/share/wayland-sessions. It starts Hyprland's safe mode
# when the config doesn't load, where the stock session drops back to the
# greeter (see Configs/.local/lib/hyde/session.sh). install_pst.sh runs this;
# on an existing install, run it once, then pick "Hyprion" in SDDM.

scrDir=$(dirname "$(realpath "$0")")
# shellcheck disable=SC1091
if ! source "${scrDir}/global_fn.sh"; then
    echo "Error: unable to source global_fn.sh..."
    exit 1
fi

flg_DryRun=${flg_DryRun:-0}
sessionSrc="${cloneDir}/Source/session"

if [ "${flg_DryRun}" -eq 1 ]; then
    print_log -g "[SESSION] " -b " :: " "Would install the Hyprion session"
    exit 0
fi

sudo install -Dm755 "${sessionSrc}/hyprion-session" /usr/local/bin/hyprion-session &&
    sudo install -Dm644 "${sessionSrc}/hyprion.desktop" /usr/local/share/wayland-sessions/hyprion.desktop || {
    print_log -r "[SESSION] " -b " :: " "Could not install the Hyprion session"
    exit 1
}
print_log -g "[SESSION] " -b " :: " "Hyprion session installed, pick it in the SDDM session menu"
