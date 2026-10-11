#!/usr/bin/env bash
export XDG_CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}"
export XDG_DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
export XDG_CACHE_HOME="${XDG_CACHE_HOME:-$HOME/.cache}"
export XDG_STATE_HOME="${XDG_STATE_HOME:-$HOME/.local/state}"
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
export HYDE_CONFIG_HOME="$XDG_CONFIG_HOME/hyde"
export HYDE_DATA_HOME="$XDG_DATA_HOME/hyde"
export HYDE_CACHE_HOME="$XDG_CACHE_HOME/hyde"
export HYDE_STATE_HOME="$XDG_STATE_HOME/hyde"
export HYDE_RUNTIME_DIR="$XDG_RUNTIME_DIR/hyde"
export ICONS_DIR="$XDG_DATA_HOME/icons"
export FONTS_DIR="$XDG_DATA_HOME/fonts"
export THEMES_DIR="$XDG_DATA_HOME/themes"
export scrDir="${LIB_DIR:-$HOME/.local/lib}/hyde"
export confDir="${XDG_CONFIG_HOME:-$HOME/.config}"
export hydeConfDir="$HYDE_CONFIG_HOME"
export cacheDir="$HYDE_CACHE_HOME"
export thmbDir="$HYDE_CACHE_HOME/thumbs"
export dcolDir="$HYDE_CACHE_HOME/dcols"
export iconsDir="$ICONS_DIR"
export themesDir="$THEMES_DIR"
export fontsDir="$FONTS_DIR"
export hashMech="sha1sum"

export HYDE_STATUS_CACHE_FAILED=3
export HYDE_STATUS_COLOURS_FAILED=4

##
# Creates the directories HyDE writes its own generated state into. A template
# whose target directory is absent is skipped as an optional dependency, so a
# first run on a clean machine would otherwise leave the colour state unwritten.
#
# Globals:
#   HYDE_STATE_HOME, HYDE_CACHE_HOME, HYDE_RUNTIME_DIR, XDG_CONFIG_HOME
##
hyde_state_dirs() {
    local dir
    for dir in "$HYDE_STATE_HOME/lua_state" "$HYDE_CACHE_HOME/wallbash" "$HYDE_RUNTIME_DIR" \
        "${XDG_CONFIG_HOME:-$HOME/.config}/hypr/themes"; do
        [ -d "$dir" ] && continue
        if ! mkdir -p "$dir"; then
            printf '[hyde] could not create %s\n' "$dir" >&2
            return 1
        fi
    done
}
hyde_state_dirs
hyde_state_dirs_status=$?

send_notifs() {
    local args=("$@")
    notify-send "${args[@]}"
}

##
# Announces a saved file and offers to open it or show it in the file manager.
# notify-send waits for the notification to close, so call this in the
# background. Notifications sharing a tag replace each other.
#
# Arguments:
#   $1 - tag, e.g. "screenshot"
#   $2 - summary
#   $3 - saved file
#   $4 - icon (defaults to the file itself)
##
notify_saved_file() {
    local tag=$1 summary=$2 file=$3 icon=${4:-$3}
    local action
    action=$(notify-send -a "HyDE Alert" -h "string:x-canonical-private-synchronous:hyde.$tag" -i "$icon" \
        -A "default=Open" -A "folder=Show in folder" "$summary" "${file##*/}")
    case $action in
    default) xdg-open "$file" ;;
    folder)
        dbus-send --session --dest=org.freedesktop.FileManager1 --type=method_call /org/freedesktop/FileManager1 \
            org.freedesktop.FileManager1.ShowItems array:string:"file://$file" string:"" ||
            xdg-open "${file%/*}"
        ;;
    esac
}
print_log() {
    [[ "${PRINT_LOG}" == "false" ]] && return 0
    while (("$#")); do
        case "$1" in
        -r | +r)
            echo -ne "\e[31m$2\e[0m" >&2
            shift 2
            ;;
        -g | +g)
            echo -ne "\e[32m$2\e[0m" >&2
            shift 2
            ;;
        -y | +y)
            echo -ne "\e[33m$2\e[0m" >&2
            shift 2
            ;;
        -b | +b)
            echo -ne "\e[34m$2\e[0m" >&2
            shift 2
            ;;
        -m | +m)
            echo -ne "\e[35m$2\e[0m" >&2
            shift 2
            ;;
        -c | +c)
            echo -ne "\e[36m$2\e[0m" >&2
            shift 2
            ;;
        -wt | +w)
            echo -ne "\e[37m$2\e[0m" >&2
            shift 2
            ;;
        -n | +n)
            echo -ne "\e[96m$2\e[0m" >&2
            shift 2
            ;;
        -stat)
            echo -ne "\e[4;30;46m $2 \e[0m :: " >&2
            shift 2
            ;;
        -crit)
            echo -ne "\e[30;41m $2 \e[0m :: " >&2
            shift 2
            ;;
        -warn)
            echo -ne "WARNING :: \e[30;43m $2 \e[0m :: " >&2
            shift 2
            ;;
        +)
            echo -ne "\e[38;5;$2m$3\e[0m" >&2
            shift 3
            ;;
        -sec)
            echo -ne "\e[32m[$2] \e[0m" >&2
            shift 2
            ;;
        -err)
            echo -ne "ERROR :: \e[4;31m$2 \e[0m" >&2
            shift 2
            ;;
        *)
            echo -ne "$1" >&2
            shift
            ;;
        esac
    done
    echo "" >&2
}

get_hashmap() {
    unset wallHash
    unset wallList
    unset skipStrays
    unset filetypes
    unset no_notify
    unset no_wallpapers
    # The find command is built as an array: it used to be a string run
    # through eval, so a wallpaper path holding $(...), backticks or a quote
    # (theme repos and WALLPAPER_CUSTOM_PATHS name them) ran or broke it.
    find_wallpapers() {
        local wallSource="$1"
        if [ -z "$wallSource" ]; then
            print_log -err "ERROR: wallSource is empty"
            return 1
        fi
        local supported_files=(
            "gif"
            "jpg"
            "jpeg"
            "png"
            "${WALLPAPER_FILETYPES[@]}")
        if [ -n "$WALLPAPER_OVERRIDE_FILETYPES" ]; then
            supported_files=("${WALLPAPER_OVERRIDE_FILETYPES[@]}")
        fi
        local ext name_args=()
        for ext in "${supported_files[@]}"; do
            name_args+=(-o -iname "*.$ext")
        done
        local find_command=(find -H "$wallSource" -type f \( "${name_args[@]:1}" \) ! -path "*/logo/*" -exec "$hashMech" {} +)
        [ "$LOG_LEVEL" == "debug" ] && print_log -g "DEBUG:" -b "Running command:" "${find_command[*]}"
        tmpfile=$(mktemp)
        "${find_command[@]}" 2>"$tmpfile" | sort -k2
        error_output=$(<"$tmpfile") && rm -f "$tmpfile"
        [ -n "$error_output" ] && print_log -err "ERROR:" -b "found an error: " -r "$error_output" -y " skipping..."
    }
    for wallSource in "$@"; do
        [ "$LOG_LEVEL" == "debug" ] && print_log -g "DEBUG:" -b "wallpaper source path:" "$wallSource"
        [ -z "$wallSource" ] && continue
        [ "$wallSource" == "--no-notify" ] && no_notify=1 && continue
        [ "$wallSource" == "--skipstrays" ] && skipStrays=1 && continue
        [ "$wallSource" == "--verbose" ] && verboseMap=1 && continue
        wallSource="$(realpath "$wallSource")"
        [ -e "$wallSource" ] || {
            print_log -err "ERROR:" -b "wallpaper source does not exist:" "$wallSource" -y " skipping..."
            continue
        }
        [ "$LOG_LEVEL" == "debug" ] && print_log -g "DEBUG:" -b "wallSource path:" "$wallSource"
        hashMap=$(find_wallpapers "$wallSource")
        if [ -z "$hashMap" ]; then
            no_wallpapers+=("$wallSource")
            print_log -warn "No compatible wallpapers found in: " "$wallSource"
            continue
        fi
        while read -r hash image; do
            wallHash+=("$hash")
            wallList+=("$image")
        done <<<"$hashMap"
    done
    if [ "${#no_wallpapers[@]}" -gt 0 ]; then
        print_log -warn "No compatible wallpapers found in:" "${no_wallpapers[*]}"
    fi
    if [ -z "${#wallList[@]}" ] || [[ ${#wallList[@]} -eq 0 ]]; then
        if [[ $skipStrays -eq 1 ]]; then
            return 1
        else
            echo "ERROR: No image found in any source"
            # Background callers such as the cache job pass --no-notify; interactive ones should hear about it
            [ -z "$no_notify" ] && notify-send -a "HyDE Alert" -h string:x-canonical-private-synchronous:hyde.wallpaper \
                "No wallpapers found" "$(printf '%s\n' "${no_wallpapers[@]/#"$HOME"/\~}")"
            exit 1
        fi
    fi
    if [[ $verboseMap -eq 1 ]]; then
        echo "// Hash Map //"
        for indx in "${!wallHash[@]}"; do
            echo ":: \${wallHash[$indx]}=\"${wallHash[indx]}\" :: \${wallList[$indx]}=\"${wallList[indx]}\""
        done
    fi
}
# shellcheck disable=SC2120 # --verbose is optional, and no caller here passes it
get_themes() {
    unset thmSortS
    unset thmListS
    unset thmWallS
    unset thmSort
    unset thmList
    unset thmWall
    if [ ! -d "$HYDE_CONFIG_HOME/themes" ]; then
        print_log -sec "theme" -warn "themes" "no theme directory at $HYDE_CONFIG_HOME/themes"
        return 1
    fi
    while read -r thmDir; do
        local realWallPath
        realWallPath="$(readlink "$thmDir/wall.set")"
        if [ ! -e "$realWallPath" ]; then
            get_hashmap "$thmDir" --skipstrays || continue
            echo "fixing link :: $thmDir/wall.set"
            ln -fs "${wallList[0]}" "$thmDir/wall.set"
        fi
        [ -f "$thmDir/.sort" ] && thmSortS+=("$(head -1 "$thmDir/.sort")") || thmSortS+=("0")
        thmWallS+=("$realWallPath")
        thmListS+=("${thmDir##*/}")
    done < <(find -H "$HYDE_CONFIG_HOME/themes" -mindepth 1 -maxdepth 1 -type d)
    while IFS='|' read -r sort theme wall; do
        thmSort+=("$sort")
        thmList+=("$theme")
        thmWall+=("$wall")
    done < <(paste -d '|' <(printf "%s\n" "${thmSortS[@]}") <(printf "%s\n" "${thmListS[@]}") <(printf "%s\n" "${thmWallS[@]}") | sort -n -k 1 -k 2)
    if [ "$1" == "--verbose" ]; then
        echo "// Theme Control //"
        for indx in "${!thmList[@]}"; do
            echo -e ":: \${thmSort[$indx]}=\"${thmSort[indx]}\" :: \${thmList[$indx]}=\"${thmList[indx]}\" :: \${thmWall[$indx]}=\"${thmWall[indx]}\""
        done
    fi
}
##
# Sources the two optional user-override files, if present.
#
# Both are optional -- most installs have neither -- so a missing file is
# not a failure and must not make the function return non-zero: a function
# call is not exempt from `set -e` the way a command inside an `&&`/`||`
# list is, so every caller that runs with `set -e` (directly, or via
# `hyde-shell init`, which calls this) would silently die right here,
# before doing anything, on any system that never created these files.
#
# A file that *does* exist and fails to source (e.g. broken syntax) is a
# real error and must still fail loudly -- that case is deliberately not
# swallowed, only "the file is absent" is treated as success.
##
export_hyde_config() {
    local user_conf_state="$XDG_STATE_HOME/hyde/staterc"
    local user_conf="$XDG_STATE_HOME/hyde/config"
    [ -f "$user_conf_state" ] && { source "$user_conf_state" || return; }
    [ -f "$user_conf" ] && { source "$user_conf" || return; }
    return 0
}
export_hyde_config
case "$enableWallDcol" in
0 | 1 | 2 | 3) ;;
*) enableWallDcol=0 ;;
esac
if [ -z "$HYDE_THEME" ] || [ ! -d "$HYDE_CONFIG_HOME/themes/$HYDE_THEME" ]; then
    get_themes
    HYDE_THEME="${thmList[0]}"
fi
HYDE_THEME_DIR="$HYDE_CONFIG_HOME/themes/$HYDE_THEME"
WALLBASH_DIRS=(
    "$XDG_CONFIG_HOME/wallbash"
    "$XDG_CONFIG_HOME/hyde/wallbash"
    "$XDG_DATA_HOME/wallbash"
    "$XDG_DATA_HOME/hyde/wallbash"
    "/usr/local/share/hyde/wallbash"
    "/usr/share/hyde/wallbash")
wallbashDirs=("${WALLBASH_DIRS[@]}")
export HYDE_THEME HYDE_THEME_DIR WALLBASH_DIRS wallbashDirs enableWallDcol
if [ -n "$HYPRLAND_INSTANCE_SIGNATURE" ]; then
    hypr_border="$(hyprctl -j getoption decoration:rounding | jq '.int')"
    hypr_width="$(hyprctl -j getoption general:border_size | jq '.int')"
fi
export hypr_border=${hypr_border:-${HYDE_BORDER_RADIUS:-2}}
export hypr_width=${hypr_width:-${HYDE_BORDER_WIDTH:-2}}
pkg_installed() {
    local pkgIn=$1
    if command -v "$pkgIn" &>/dev/null; then
        return 0
    elif command -v "flatpak" &>/dev/null && flatpak info "$pkgIn" &>/dev/null; then
        return 0
    elif hyde-shell pm.sh pq "$pkgIn" &>/dev/null; then
        return 0
    else
        return 1
    fi
}
# shellcheck disable=SC2034 # sets aurhlpr for the caller
get_aurhlpr() {
    if pkg_installed yay; then
        aurhlpr="yay"
    elif pkg_installed paru; then
        aurhlpr="paru"
    fi
}
set_conf() {
    local varName="$1"
    local varData="$2"
    touch "$XDG_STATE_HOME/hyde/staterc"
    if [ "$(grep -c "^$varName=" "$XDG_STATE_HOME/hyde/staterc")" -eq 1 ]; then
        sed -i "/^$varName=/c$varName=\"$varData\"" "$XDG_STATE_HOME/hyde/staterc"
    else
        echo "$varName=\"$varData\"" >>"$XDG_STATE_HOME/hyde/staterc"
    fi
}
set_hash() {
    local hashImage="$1"
    "$hashMech" "$hashImage" | awk '{print $1}'
}
##
# Loads a .dcol file as data. theme.dcol comes verbatim from a downloaded
# theme and its values land in sed scripts, so only the keys and formats
# wallbash.sh writes are set; other lines get one warning. Exports under set -a.
#
# Arguments:
#   $1 - .dcol file
##
load_dcol() {
    local file=$1 line key value n=0 skipped=()
    local colour='^dcol_(pry[1-4]|txt[1-4]|[1-4]xa[1-9])'
    local hex='^[0-9A-Fa-f]{6}$'
    local rgba='^rgba\([0-9]{1,3},[0-9]{1,3},[0-9]{1,3},(\\1|[0-9]*\.?[0-9]+)\)$'
    local rgb='^[0-9]{1,3},[0-9]{1,3},[0-9]{1,3}$'
    while IFS= read -r line || [ -n "$line" ]; do
        n=$((n + 1))
        line=${line%$'\r'}
        [[ $line =~ ^[[:space:]]*(#|$) ]] && continue
        if [[ ! $line =~ ^(dcol_[A-Za-z0-9_]+)=(.*)$ ]]; then
            skipped+=("$n")
            continue
        fi
        key=${BASH_REMATCH[1]}
        value=${BASH_REMATCH[2]}
        [[ $value =~ ^\"(.*)\"$ || $value =~ ^\'(.*)\'$ ]] && value=${BASH_REMATCH[1]}
        if [[ -z $value && $key =~ ${colour}(_rgba|_rgb)?$ ]] ||
            [[ $key == dcol_mode && $value =~ ^(dark|light)$ ]] ||
            [[ $key =~ ${colour}$ && $value =~ $hex ]] ||
            [[ $key =~ ${colour}_rgba$ && $value =~ $rgba ]] ||
            [[ $key =~ ${colour}_rgb$ && $value =~ $rgb ]]; then
            printf -v "$key" '%s' "$value"
        else
            skipped+=("$n")
        fi
    done <"$file" || return 1
    [ "${#skipped[@]}" -eq 0 ] ||
        print_log -sec "wallbash" -warn "dcol" "ignored line(s) ${skipped[*]} of $file: not a wallbash colour"
    return 0
}
check_package() {
    local lock_file="${XDG_RUNTIME_DIR:-/tmp}/hyde/__package.lock"
    mkdir -p "${XDG_RUNTIME_DIR:-/tmp}/hyde"
    if [ -f "$lock_file" ]; then
        return 0
    fi
    for pkg in "$@"; do
        if ! pkg_installed "$pkg"; then
            print_log -err "Package is not installed" "'$pkg'"
            rm -f "$lock_file"
            exit 1
        fi
    done
    touch "$lock_file"
}
get_hyprConf() {
    local hyArg="$1"
    local file="${2:-"$HYDE_THEME_DIR/hypr.theme"}"
    local hyVar="$hyArg"
    local hyType=""

    #? Allow optional type hint: e.g., FONT_SIZE[int]
    if [[ "$hyArg" =~ ^([^[]+)\[([a-zA-Z0-9_]+)\]$ ]]; then
        hyVar="${BASH_REMATCH[1]}"
        hyType="${BASH_REMATCH[2]}"
    fi

    #? hyq first (sanitized, then raw), with optional type
    #? hyq cannot handle $FOO and $FOO_BAR so we will impose hints to make it work
    if command -v hyq &>/dev/null; then
        local query="\$$hyVar"
        [ -n "$hyType" ] && query="${query}[${hyType}]"
        local hyq_result
        hyq_result=$(hyq -s --query "$query" "$file" 2>/dev/null)
        if [ -z "$hyq_result" ]; then
            hyq_result=$(hyq --query "$query" "$file" 2>/dev/null)
        fi
        [ -n "$hyq_result" ] && echo "$hyq_result" && return 0
    fi

    local gsVal
    gsVal="$(grep "^[[:space:]]*\$$hyVar\s*=" "$file" | cut -d '=' -f2 | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
    [ -n "$gsVal" ] && [[ $gsVal != \$* ]] && echo "$gsVal" && return 0
    declare -A gsMap=(
        [GTK_THEME]="gtk-theme"
        [ICON_THEME]="icon-theme"
        [COLOR_SCHEME]="color-scheme"
        [CURSOR_THEME]="cursor-theme"
        [CURSOR_SIZE]="cursor-size"
        [FONT]="font-name"
        [DOCUMENT_FONT]="document-font-name"
        [MONOSPACE_FONT]="monospace-font-name"
        [FONT_SIZE]="font-size"
        [DOCUMENT_FONT_SIZE]="document-font-size"
        [MONOSPACE_FONT_SIZE]="monospace-font-size")
    if [[ -n ${gsMap[$hyVar]} ]]; then
        gsVal="$(awk -F"[\"']" '/^[[:space:]]*exec[[:space:]]*=[[:space:]]*gsettings[[:space:]]*set[[:space:]]*org.gnome.desktop.interface[[:space:]]*'"${gsMap[$hyVar]}"'[[:space:]]*/ {last=$2} END {print last}' "$file")"
    fi
    if [ -z "$gsVal" ] || [[ $gsVal == \$* ]]; then
        case "$hyVar" in
        "CODE_THEME") echo "Wallbash" ;;
        "SDDM_THEME") echo "" ;;
        *) grep "^[[:space:]]*\$default.$hyVar\s*=" \
            "$XDG_DATA_HOME/hyde/hyde.conf" \
            "$XDG_DATA_HOME/hyde/hyprland.conf" \
            "/usr/local/share/hyde/hyde.conf" \
            "/usr/local/share/hyde/hyprland.conf" \
            "/usr/share/hyde/hyde.conf" \
            "/usr/share/hyde/hyprland.conf" 2>/dev/null | cut -d '=' -f2 | sed 's/^[[:space:]]*//;s/[[:space:]]*$//' | head -n 1 ;;
        esac
    else
        echo "$gsVal"
    fi
}
# Reads a monitor scale as a whole percent, so 100 comes back for 1, 1.0 and
# 1.00 alike. Deleting the dot instead makes the result depend on how many
# decimals the compositor printed, and a scale that arrives as 1 rather than
# 1.00 leaves every measurement dividing by it a hundred times too large.
get_monitor_scale() {
    local raw=${1:-}
    if [ -z "${raw}" ]; then
        raw=$(hyprctl -j monitors 2>/dev/null | jq -r 'first(.[] | select(.focused==true) | .scale) // empty' 2>/dev/null)
    fi
    awk -v raw="${raw}" 'BEGIN {
        scale = raw + 0
        if (scale <= 0) scale = 1
        printf "%d", scale * 100 + 0.5
    }'
}
# A wallpaper narrower than the screen (anything but a true 32:9 image on an
# ultrawide) has to give up either its edges or the screen's. Cropping to fill
# throws away most of an ordinary 16:9 wallpaper; fitting keeps all of it but
# strands it in flat bars. "ambient" does neither: it fits the image over a
# blurred, dimmed copy of itself scaled to fill, so the padding carries the
# wallpaper's own colours and light. The composite is cached per source *and*
# per screen size, and only built when the aspect ratios actually differ enough
# to matter -- an image already close to the screen's shape is left for the
# backend to crop, which costs nothing and loses nothing visible.
#
# Echoes "<resize-mode>\t<image path>" for the backend to apply. On any failure
# it falls back to the original image with a plain resize mode, so a missing
# ImageMagick or an unreadable file degrades to upstream behaviour.
get_screen_geometry() {
    local geo
    [[ -n $HYPRLAND_INSTANCE_SIGNATURE ]] && geo="$(hyprctl -j monitors 2>/dev/null |
        jq -r 'first(.[] | select(.focused==true)) |
            if (.transform % 2 == 0) then "\(.width) \(.height)" else "\(.height) \(.width)" end' 2>/dev/null)"
    [[ $geo =~ ^[0-9]+\ [0-9]+$ ]] || geo="1920 1080"
    echo "$geo"
}
# No band rule survives contact with every image, so any single wallpaper can be
# pinned to its own mode. Keyed by content hash, which follows the file when it
# is renamed or moved between theme folders; the trailing basename is a comment
# for whoever opens the file, and is not matched on.
wallpaper_fit_overrides() { echo "$HYDE_STATE_HOME/wallpaper.fit"; }
get_wallpaper_fit_override() {
    local file
    file="$(wallpaper_fit_overrides)"
    [ -f "$file" ] || return 0
    awk -v h="$(set_hash "$1")" '$1 == h { print $2; exit }' "$file"
}
set_wallpaper_fit_override() {
    local image="$1" mode="$2" file hash
    file="$(wallpaper_fit_overrides)"
    hash="$(set_hash "$image")"
    mkdir -p "$(dirname "$file")"
    touch "$file"
    sed -i "/^$hash /d" "$file"
    [ "$mode" == "auto" ] && return 0
    printf '%s %s # %s\n' "$hash" "$mode" "$(basename "$image")" >> "$file"
}
# How much of an image we are willing to crop away before padding the rest.
# Deliberately not a straight function of the mismatch, because the useful
# signal is what the image was authored for rather than its geometry:
# 21:9 art is composed edge to edge for wide screens and loses captions and
# heads to even a small crop, while the 16:9 majority carries a third of a frame
# in slack sky and ground that nobody misses. So the band that is *closer* to
# the screen's shape is the one we crop least.
get_crop_budget() {
    local img_w="$1" img_h="$2" scr_w="$3" scr_h="$4"
    if [[ $WALLPAPER_CROP_BUDGET =~ ^[0-9]+$ ]]; then
        echo "$WALLPAPER_CROP_BUDGET"
        return 0
    fi
    awk -v iw="$img_w" -v ih="$img_h" -v sw="$scr_w" -v sh="$scr_h" \
        -v wide="${WALLPAPER_CROP_BUDGET_WIDE:-0}" \
        -v standard="${WALLPAPER_CROP_BUDGET_STANDARD:-15}" \
        -v tall="${WALLPAPER_CROP_BUDGET_TALL:-10}" \
        'BEGIN { m = (iw / ih) / (sw / sh); if (m < 1) m = 1 / m
                 print (m < 1.6) ? wide : (m < 2.2) ? standard : tall }'
}
fit_wallpaper() {
    local image="$1" mode="${2:-ambient}" budget=""
    # A pinned wallpaper wins over the configured mode. "ambient:0" pins the
    # mode and its crop budget together, which is the usual reason to pin one.
    local pinned
    pinned="$(get_wallpaper_fit_override "$image")"
    [ -n "$pinned" ] && mode="$pinned"
    if [[ $mode == *:* ]]; then
        budget="${mode#*:}"
        mode="${mode%%:*}"
    fi
    if [ "$mode" != "ambient" ]; then
        printf '%s\t%s' "$mode" "$image"
        return 0
    fi
    local scr_w scr_h img_w img_h
    read -r scr_w scr_h < <(get_screen_geometry)
    read -r img_w img_h < <(magick identify -format '%w %h' "${image}[0]" 2>/dev/null)
    # No ImageMagick, an unreadable image, or an animation we would freeze:
    # hand it back and let the backend crop as it always did.
    if [[ ! $img_w =~ ^[0-9]+$ ]] || [[ ! $img_h =~ ^[0-9]+$ ]] ||
        [[ $(file --mime-type -b "$image" 2>/dev/null) == "image/gif" ]]; then
        printf '%s\t%s' "crop" "$image"
        return 0
    fi
    local tolerance="${WALLPAPER_FIT_TOLERANCE:-0.05}"
    if awk -v iw="$img_w" -v ih="$img_h" -v sw="$scr_w" -v sh="$scr_h" -v t="$tolerance" \
        'BEGIN { exit !( (iw/ih) / (sw/sh) > 1 - t && (iw/ih) / (sw/sh) < 1 + t ) }'; then
        printf '%s\t%s' "crop" "$image"
        return 0
    fi
    # The backdrop is the image zoomed to fill, so the further its shape is from
    # the screen's the more it is magnified -- and a fixed blur that dissolves a
    # 16:9 backdrop leaves a poster's faces perfectly readable at 5x. Scale the
    # radius with that mismatch so the padding stays an abstract wash whatever
    # the source shape is.
    local base_blur="${WALLPAPER_AMBIENT_BLUR:-12}" dim="${WALLPAPER_AMBIENT_DIM:--35}" blur
    blur=$(awk -v iw="$img_w" -v ih="$img_h" -v sw="$scr_w" -v sh="$scr_h" -v b="$base_blur" \
        'BEGIN { m = (iw / ih) / (sw / sh); if (m < 1) m = 1 / m
                 r = int(b * m / 2 + 0.5); if (r < b) r = b; if (r > b * 4) r = b * 4; print r }')
    # Zoom past a plain fit until we have given up `budget` percent of the
    # image, then let the ambient backdrop cover whatever is still uncovered.
    # Capped at the fill scale, past which there would be nothing left to pad.
    [[ $budget =~ ^[0-9]+$ ]] || budget="$(get_crop_budget "$img_w" "$img_h" "$scr_w" "$scr_h")"
    local fg_w fg_h
    read -r fg_w fg_h < <(awk -v iw="$img_w" -v ih="$img_h" -v sw="$scr_w" -v sh="$scr_h" -v b="$budget" \
        'BEGIN { f = (sw / iw < sh / ih) ? sw / iw : sh / ih
                 s = (sw / iw > sh / ih) ? sw / iw : sh / ih
                 z = f / (1 - b / 100); if (z > s) z = s
                 printf "%d %d\n", iw * z + 0.5, ih * z + 0.5 }')
    local cache_dir="$HYDE_CACHE_HOME/wallpapers/ambient"
    local cached
    cached="$cache_dir/$(set_hash "$image")-${scr_w}x${scr_h}-${blur}-${dim}-${budget}.jpg"
    if [ ! -s "$cached" ]; then
        mkdir -p "$cache_dir"
        # The backdrop is blurred at an eighth scale and stretched back up: a
        # radius-12 blur on a thumbnail is indistinguishable from a radius-96
        # blur on the full canvas and finishes in a fraction of the time.
        if ! magick "${image}[0]" \
            \( -clone 0 -resize "$((scr_w / 8))x$((scr_h / 8))^" -gravity center \
            -extent "$((scr_w / 8))x$((scr_h / 8))" -blur "0x${blur}" \
            -brightness-contrast "${dim}x-20" -resize "${scr_w}x${scr_h}!" \) \
            \( -clone 0 -resize "${fg_w}x${fg_h}!" -gravity center \
            -crop "${scr_w}x${scr_h}+0+0" +repage \) \
            -delete 0 -gravity center -composite -quality 95 "$cached" 2> /dev/null; then
            rm -f "$cached"
            printf '%s\t%s' "crop" "$image"
            return 0
        fi
        # Every wallpaper the user cycles past leaves a screen-sized composite
        # behind, so keep only the most recent ones; anything evicted is one
        # magick call away from coming back.
        find "$cache_dir" -maxdepth 1 -type f -printf '%T@ %p\0' 2> /dev/null |
            sort -zrn | tail -zn "+$((${WALLPAPER_AMBIENT_CACHE_KEEP:-50} + 1))" |
            cut -zd' ' -f2- | xargs -0r rm -f
    fi
    touch "$cached"
    printf '%s\t%s' "crop" "$cached"
}
# Padding colour for plain `fit` mode, taken from the wallpaper's own wallbash
# primary so the bars read as a matte rather than a black void. The dcol is
# written asynchronously by color.set.sh, so a wallpaper being seen for the
# first time falls back to the global one, then to black.
get_wallpaper_fill_color() {
    local image="$1" dcol_file color=""
    if [[ $WALLPAPER_FILL_COLOR =~ ^[0-9a-fA-F]{8}$ ]]; then
        echo "$WALLPAPER_FILL_COLOR"
        return 0
    fi
    [ -f "$image" ] && dcol_file="$dcolDir/$(set_hash "$image").dcol"
    [ -f "$dcol_file" ] || dcol_file="$HYDE_CACHE_HOME/wall.dcol"
    [ -f "$dcol_file" ] && color="$(grep -m1 '^dcol_pry1=' "$dcol_file" | cut -d '"' -f2)"
    [[ $color =~ ^[0-9a-fA-F]{6}$ ]] || color="000000"
    echo "${color}ff"
}
get_rofi_pos() {
    [[ -n $HYPRLAND_INSTANCE_SIGNATURE ]] || return 1
    readarray -t curPos < <(hyprctl cursorpos -j | jq -r '.x,.y')
    eval "$(hyprctl -j monitors | jq -r '.[] | select(.focused==true) |
        "monRes=(\(.width) \(.height) \(.scale) \(.x) \(.y)) offRes=(\(.reserved | join(" "))) monTransform=\(.transform // 0)"')"
    # hyprctl reports width/height as the monitor's pre-transform mode, not
    # swapped for a 90/270-degree rotation (verified against a headless test
    # output: transform=1 left width/height unchanged) -- so on a portrait
    # monitor these still carried its landscape resolution, landing rofi
    # menus off-screen near the bottom/right (#975).
    if ((monTransform % 2 == 1)); then
        local mon_swap="${monRes[0]}"
        monRes[0]="${monRes[1]}"
        monRes[1]="$mon_swap"
    fi
    monRes[2]="$(get_monitor_scale "${monRes[2]}")"
    monRes[0]=$((monRes[0] * 100 / monRes[2]))
    monRes[1]=$((monRes[1] * 100 / monRes[2]))
    curPos[0]=$((curPos[0] - monRes[3]))
    curPos[1]=$((curPos[1] - monRes[4]))
    # offRes is already a correctly-parsed 4-element array from the eval
    # above ("${offRes// / }" with no index means offRes[0]: a no-op
    # substitution that then collapsed the whole array down to that one
    # element, discarding offRes[1..3] -- so any menu anchored north, east,
    # or south of the cursor ignored reserved space on that edge (e.g. a
    # bar) entirely. Caught by a reserved-margin test case with no HyDE
    # issue number of its own; found while testing #975's fix.
    if [ "${curPos[0]}" -ge "$((monRes[0] / 2))" ]; then
        local x_pos="east"
        local x_off="-$((monRes[0] - curPos[0] - offRes[2]))"
    else
        local x_pos="west"
        local x_off="$((curPos[0] - offRes[0]))"
    fi
    if [ "${curPos[1]}" -ge "$((monRes[1] / 2))" ]; then
        local y_pos="south"
        local y_off="-$((monRes[1] - curPos[1] - offRes[3]))"
    else
        local y_pos="north"
        local y_off="$((curPos[1] - offRes[1]))"
    fi
    local coordinates="window{location:$x_pos $y_pos;anchor:$x_pos $y_pos;x-offset:${x_off}px;y-offset:${y_off}px;}"
    echo "$coordinates"

}
paste_string() {
    if ! command -v wtype >/dev/null; then exit 0; fi
    if [ -t 1 ]; then return 0; fi
    ignore_paste_file="$HYDE_STATE_HOME/ignore.paste"
    if [[ ! -e $ignore_paste_file ]]; then
        cat <<EOF >"$ignore_paste_file"
kitty
org.kde.konsole
terminator
XTerm
Alacritty
xterm-256color
EOF
    fi
    ignore_class=$(echo "$@" | awk -F'--ignore=' '{print $2}')
    [ -n "$ignore_class" ] && echo "$ignore_class" >>"$ignore_paste_file" && print_log -y "[ignore]" "'$ignore_class'" && exit 0
    class=$(hyprctl -j activewindow | jq -r '.initialClass')
    if ! grep -q "$class" "$ignore_paste_file"; then
        hyprctl -q dispatch exec 'wtype -M ctrl V -m ctrl'
    fi
}
is_hovered() {
    data=$(hyprctl --batch -j "cursorpos;activewindow" | jq -s '.[0] * .[1]')
    eval "$(echo "$data" | jq -r '@sh "cursor_x=\(.x) cursor_y=\(.y) window_x=\(.at[0]) window_y=\(.at[1]) window_size_x=\(.size[0]) window_size_y=\(.size[1])"')"
    cursor_x=${cursor_x:-$(jq -r '.x // 0' <<<"$data")}
    cursor_y=${cursor_y:-$(jq -r '.y // 0' <<<"$data")}
    window_x=${window_x:-$(jq -r '.at[0] // 0' <<<"$data")}
    window_y=${window_y:-$(jq -r '.at[1] // 0' <<<"$data")}
    window_size_x=${window_size_x:-$(jq -r '.size[0] // 0' <<<"$data")}
    window_size_y=${window_size_y:-$(jq -r '.size[1] // 0' <<<"$data")}
    if ((cursor_x >= window_x && cursor_x <= window_x + window_size_x && cursor_y >= window_y && cursor_y <= window_y + window_size_y)); then
        return 0
    fi
    return 1
}
##
# Reports whether the generated colour state this installation reads is on disk.
# Hyprland reads the Lua state, and the colour include is required alongside it
# because hyprlock, which has no Lua configuration, sources that file.
#
# Globals:
#   HYDE_STATE_HOME, confDir
# Returns:
#   0 when every artefact exists and carries content, 1 otherwise
##
wallbash_state_is_complete() {
    local required=(
        "$confDir/hypr/themes/colors.conf"
        "$HYDE_STATE_HOME/lua_state/colors.lua"
        "$HYDE_STATE_HOME/lua_state/ui.lua"
    )
    local artefact
    for artefact in "${required[@]}"; do
        if [ ! -f "$artefact" ] || [ ! -s "$artefact" ]; then
            return 1
        fi
    done
    return 0
}
##
# Serializes wallpaper-backend invocations (awww/swww/waydeeper/hyprpaper) so
# concurrent theme/wallpaper switches apply in order instead of racing.
#
# A plain "does the lock file exist" check-then-touch lock has two problems:
# the check and the touch aren't atomic, and once a second invocation sees
# the file it gives up immediately instead of waiting its turn, so its own
# wallpaper apply is silently skipped while the rest of the theme still
# switches. flock instead blocks the caller until the current holder exits,
# and releases itself automatically (even on a crash) since it is tied to
# the open file descriptor, not the file's mere existence on disk -- so,
# unlike the old lock, deleting the lock file while it's held does not help
# and should not be suggested: unlinking it just lets a second invocation
# open and lock a *new* inode at the same path, running concurrently with
# whatever still holds the old one.
#
# Callers must hold the lock for as long as their actual apply command
# runs, not just until it's been backgrounded, or two overlapping switches
# can still race to be the one left on screen.
#
# The lock file name is fixed (not derived from $0): "which wallpaper is on
# screen" is one shared resource regardless of which backend script touches
# it, so a switch to backend A must still serialize against one still
# in-flight on backend B, e.g. right after WALLPAPER_BACKEND changes.
#
# Globals:
#   Sets WALLPAPER_LOCK_FD, to be released via `flock -u "$WALLPAPER_LOCK_FD"`
# Arguments:
#   $1 - seconds to wait for a held lock before giving up (default: 15)
# Returns:
#   0 once the lock is held; exits 1 after printing an error on timeout
##
wallpaper_acquire_lock() {
    local timeout="${1:-15}"
    local lockDir="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/hyde"
    mkdir -p "$lockDir"
    exec {WALLPAPER_LOCK_FD}>"$lockDir/wallpaper.lock"
    if ! flock -w "$timeout" "$WALLPAPER_LOCK_FD"; then
        echo "Error: Another wallpaper backend is still running after waiting ${timeout}s." >&2
        exit 1
    fi
}

toml_write() {
    local config_file=$1
    local group=$2
    local key=$3
    local value=$4
    if ! kwriteconfig6 --file "$config_file" --group "$group" --key "$key" "$value" >/dev/null; then
        if ! grep -q "^\[$group\]" "$config_file"; then
            echo -e "\n[$group]\n$key=$value" >>"$config_file"
        elif ! grep -q "^$key=" "$config_file"; then
            sed -i "/^\[$group\]/a $key=$value" "$config_file"
        else
            sed -i "/^\[$group\]/,/^\[.*\]/s/^$key=.*/$key=$value/" "$config_file"
        fi
    fi
}
extract_thumbnail() {
    local x_wall="$1"
    x_wall=$(realpath "$x_wall")
    local temp_image="$2"
    ffmpeg -y -i "$x_wall" -vf "thumbnail,scale=1000:-1" -frames:v 1 -update 1 "$temp_image" &>/dev/null
}
accepted_mime_types() {
    local mime_types_array=$1
    local file=$2
    for mime_type in "${mime_types_array[@]}"; do
        if file --mime-type -b "$file" | grep -q "^$mime_type"; then
            return 0
        else
            print_log -err "File type not supported for this wallpaper backend."
            notify-send -u critical -a "HyDE Alert" "File type not supported for this wallpaper backend."
        fi
    done
}
dconf_write() {
    local key="$1"
    local value="$2"
    if dconf write "$key" "'$value'"; then
        print_log -sec "dconf" -stat "set" "$key to $value"
    else
        print_log -sec "dconf" -warn "failed to set" "$key"
    fi
}
# Rofi lays out exactly as many columns as it is told, so a bad monitor
# resolution degrades silently into unreadable slivers. Clamp to [1, max].
clamp_col_count() {
    local count="${1:-1}" max="${2:-5}"
    [[ $count =~ ^-?[0-9]+$ ]] || count=1
    ((count < 1)) && count=1
    ((count > max)) && count=$max
    printf "%d" "$count"
}
export -f get_hyprConf get_monitor_scale clamp_col_count get_wallpaper_fill_color get_rofi_pos is_hovered toml_write get_hashmap get_aurhlpr set_conf set_hash check_package get_themes print_log pkg_installed paste_string extract_thumbnail accepted_mime_types dconf_write send_notifs notify_saved_file export_hyde_config wallbash_state_is_complete get_screen_geometry fit_wallpaper wallpaper_fit_overrides get_wallpaper_fit_override set_wallpaper_fit_override get_crop_budget

##
# Fails the source when the generated-state directories could not be created,
# so a caller does not render templates into a directory that is not there.
##
if [ "${hyde_state_dirs_status:-0}" -ne 0 ]; then
    return "$hyde_state_dirs_status" 2>/dev/null || exit "$hyde_state_dirs_status"
fi
