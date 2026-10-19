#!/usr/bin/env bash

# Function to set permissions for Spotify path
set_permissions() {
    local path=$1
    chmod a+wr "$path"
    chmod a+wr -R "$path/Apps"
}

# Function to notify and set permissions using pkexec
notify_and_set_permissions() {
    local path=$1
    notify-send -a "HyDE Alert" "Permission needed for Wallbash Spotify theme"
    pkexec chmod a+wr "$path"
    pkexec chmod a+wr -R "$path/Apps"
}

# Function to print the flags Spotify's launcher passes, joined with "|" for spicetify.
# spicetify starts the Spotify binary itself, so its restarts would drop them otherwise.
launch_flags() {
    local spotify_path=$1
    local conf flags=""
    case "$spotify_path" in
    */spotify-launcher/*)
        # spotify-launcher reads the first of these that exists
        for conf in "${XDG_CONFIG_HOME:-$HOME/.config}/spotify-launcher.conf" /etc/spotify-launcher.conf; do
            [ -f "$conf" ] || continue
            flags=$(awk '/^[[:space:]]*extra_arguments[[:space:]]*=/ {f = 1} f {print} f && /]/ {exit}' "$conf" |
                grep -oE "\"[^\"]*\"|'[^']*'" | tr -d "\"'" | paste -sd '|')
            break
        done
        ;;
    /opt/spotify)
        conf="${XDG_CONFIG_HOME:-$HOME/.config}/spotify-flags.conf"
        [ -f "$conf" ] && flags=$(grep -v '^[[:space:]]*#' "$conf" | tr -s '[:space:]' '\n' | grep -v '^$' | paste -sd '|')
        ;;
    esac
    [ -n "$flags" ] || flags='--ozone-platform=wayland'
    echo "$flags"
}

# Function to install the Sleek theme that wallbash colours are copied into
install_sleek() {
    local themes_dir=$1
    local cache_dir=$2

    [ -f "${themes_dir}/Sleek/user.css" ] && return 0
    mkdir -p "$themes_dir" "${cache_dir}/landing"
    curl -fsSL -o "${cache_dir}/landing/Spotify_Sleek.tar.gz" "https://github.com/derrickthegreat/Hyprion/raw/main/Source/arcs/Spotify_Sleek.tar.gz" &&
        tar -xzf "${cache_dir}/landing/Spotify_Sleek.tar.gz" -C "$themes_dir"
}

# Function to configure Spicetify
configure_spicetify() {
    local spotify_path=$1
    local spotify_conf

    spicetify &>/dev/null
    mkdir -p ~/.config/spotify
    touch ~/.config/spotify/prefs
    spotify_conf=$(spicetify -c)

    sed -i -e "/^prefs_path/ s+=.*$+= $HOME/.config/spotify/prefs+g" \
    -e "/^spotify_path/ s+=.*$+= $spotify_path+g" "$spotify_conf"

    spicetify -n backup apply
    spicetify config current_theme Sleek
    spicetify config color_scheme Wallbash
    spicetify config sidebar_config 0
    spicetify -n restore backup
    spicetify -n backup apply
}

# Main script
cacheDir="${cacheDir:-$XDG_CACHE_HOME/hyde}"
shareDir=${XDG_DATA_HOME:-$HOME/.local/share}
spotify_col="${cacheDir}/wallbash/spotify.ini"
spicetify_themes_dir="$HOME/.config/spicetify/Themes"

command -v spicetify &>/dev/null || exit 0

if [ -n "${SPOTIFY_PATH}" ]; then
    spotify_path="${SPOTIFY_PATH}"
    cat <<EOF
[warning]   using custom spotify path
            ensure to have proper permissions for ${SPOTIFY_PATH}
            run:
            chmod a+wr ${SPOTIFY_PATH}
            chmod a+wr -R ${SPOTIFY_PATH}/Apps

            note: run with 'sudo' if only needed.
EOF

    elif [ -d "${XDG_DATA_HOME}/flatpak/app/com.spotify.Client/x86_64/stable/active/files/extra/share/spotify" ]; then
    spotify_path="${XDG_DATA_HOME}/flatpak/app/com.spotify.Client/x86_64/stable/active/files/extra/share/spotify"
    print_log -sec "Spotify" " User Flatpak"
    elif [ -d /var/lib/flatpak/app/com.spotify.Client/x86_64/stable/active/files/extra/share/spotify ]; then
    spotify_path='/var/lib/flatpak/app/com.spotify.Client/x86_64/stable/active/files/extra/share/spotify'
    print_log -sec "Spotify" " System Flatpak"
    elif [ -f "${shareDir}/spotify-launcher/install/usr/bin/spotify" ]; then
    spotify_path="${shareDir}/spotify-launcher/install/usr/share/spotify"
    print_log -sec "Spotify" " Spotify-launcher"
    elif [ -d /opt/spotify ]; then
    spotify_path='/opt/spotify'
    print_log -sec "Spotify" " System Package Manager"
fi

[ -e "${spotify_path}" ] || exit 0

if [ ! -w "${spotify_path}" ] || [ ! -w "${spotify_path}/Apps" ]; then
    notify_and_set_permissions "${spotify_path}"
fi

print_log -sec "Spotify" -stat "path" " ${spotify_path}"
if ! install_sleek "$spicetify_themes_dir" "$cacheDir"; then
    print_log -sec "Spotify" -err "theme" "could not download the Sleek theme"
    exit 1
fi
changed=0
if [ -f "$spotify_col" ] && ! cmp -s "$spotify_col" "${spicetify_themes_dir}/Sleek/color.ini"; then
    cp "$spotify_col" "${spicetify_themes_dir}/Sleek/color.ini"
    changed=1
fi

if [ "$(spicetify config | awk '{if ($1=="color_scheme") print $2}')" != "Wallbash" ] || [[ "${*}" == *"--reset"* ]]; then
    configure_spicetify "$spotify_path"
    changed=1
elif [ -f "${spotify_path}/Apps/xpui.spa" ]; then
    # Spotify updated and replaced the patched files
    spicetify -n backup apply
    changed=1
fi
spicetify -q config spotify_launch_flags -- "$(launch_flags "$spotify_path")"

# watch -s would reload the colours live, but only by running Spotify with an open
# DevTools port. Restart it instead, unless that would interrupt playback.
pkill -f '^[^ ]*spicetify -q watch'
[ "$changed" -eq 1 ] || exit 0
spicetify -q refresh
if pgrep -x spotify >/dev/null && [ "$(playerctl -p spotify status 2>/dev/null)" != "Playing" ]; then
    spicetify -q restart &>/dev/null
fi
