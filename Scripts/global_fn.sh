#!/usr/bin/env bash
#|---/ /+------------------+---/ /|#
#|--/ /-| Global functions |--/ /-|#
#|-/ /--| Prasanth Rangan  |-/ /--|#
#|/ /---+------------------+/ /---|#

set -e

scrDir="$(dirname "$(realpath "$0")")"
cloneDir="$(dirname "${scrDir}")" # fallback, we will use CLONE_DIR now
cloneDir="${CLONE_DIR:-${cloneDir}}"
confDir="${XDG_CONFIG_HOME:-$HOME/.config}"
cacheDir="${XDG_CACHE_HOME:-$HOME/.cache}/hyde"
aurList=("yay" "paru" "pikaur" "trizen" "aura" "pakku" "pacaur" "aurman" "pacseek" "aurutils")
shlList=("zsh" "fish")
pacmanCmd=${cloneDir}/Configs/.local/lib/hyde/pm.sh

export cloneDir
export confDir
export cacheDir
export aurList
export shlList

pkg_installed() {
    local PkgIn=$1

    if pacman -Q "${PkgIn}" &>/dev/null; then
        return 0
    else
        return 1
    fi
}

chk_list() {
    vrType="$1"
    local inList=("${@:2}")
    for pkg in "${inList[@]}"; do
        if pkg_installed "${pkg}"; then
            printf -v "${vrType}" "%s" "${pkg}"
            # shellcheck disable=SC2163 # dynamic variable
            export "${vrType}" # export the variable // reference of the variable
            return 0
        fi
    done
    # print_log -sec "install" -warn "no package found in the list..." "${inList[@]}"
    return 1
}

aur_health_check() {
    local helper="$1"
    if command -v "${helper}" &>/dev/null; then
        if "${helper}" --version &>/dev/null; then
            return 0
        fi
    fi
    return 1
}

chk_shell() {
    local candidate="${1:-}"
    local shell
    [ -n "${candidate}" ] || return 1
    for shell in "${shlList[@]}"; do
        [ "${shell}" = "${candidate}" ] && return 0
    done
    return 1
}

login_shell() {
    local entry
    entry="$(getent passwd "${USER}")" || return 1
    [ -n "${entry##*:}" ] || return 1
    basename "${entry##*:}"
}

shell_listed() {
    local wanted listed
    local shells="${2:-/etc/shells}"
    # The same shell is listed under /bin or /usr/bin, so both sides resolve.
    wanted="$(realpath -e "${1}" 2>/dev/null)" || return 1
    [ -f "${shells}" ] || return 0
    # The guard keeps a last line that carries no trailing newline.
    while IFS= read -r listed || [ -n "${listed}" ]; do
        listed="${listed%%#*}"
        listed="${listed//[[:space:]]/}"
        [ -n "${listed}" ] || continue
        [ "$(realpath -e "${listed}" 2>/dev/null)" = "${wanted}" ] && return 0
    done < "${shells}"
    return 1
}

resolve_shell() {
    local current
    chk_shell "${myShell:-}" && return 0
    # The shell already logged in with outranks the order of the list.
    current="$(login_shell || true)"
    if chk_shell "${current}"; then
        myShell="${current}"
        export myShell
        return 0
    fi
    chk_list "myShell" "${shlList[@]}"
}

pkg_available() {
    local PkgIn=$1

    if ${pacmanCmd} query "${PkgIn}" &>/dev/null; then
        return 0
    else
        return 1
    fi
}

aur_available() {
    local PkgIn=$1

    # shellcheck disable=SC2154
    if ${pacmanCmd} info "${PkgIn}" &>/dev/null; then
        return 0
    else
        return 1
    fi
}

# The utils package a driver from nvidia-db/ runs with. The legacy branches ship
# their own, which conflicts with the repo's nvidia-utils.
nvidia_utils() {
    case "${1}" in
    nvidia-open-dkms) echo "nvidia-utils" ;;
    *) echo "${1%-dkms}-utils" ;;
    esac
}

nvidia_detect() {
    readarray -t dGPU < <(lspci -k | grep -E "(VGA|3D)" | awk -F ': ' '{print $NF}')
    if [ "${1}" == "--verbose" ]; then
        for indx in "${!dGPU[@]}"; do
            echo -e "\033[0;32m[gpu$indx]\033[0m detected :: ${dGPU[indx]}"
        done
        return 0
    fi
    if [ "${1}" == "--drivers" ]; then
        # "--drivers pacman" or "--drivers aur" keeps the packages from that
        # source: only nvidia-open-dkms is in the official repos, the legacy
        # branches are in the AUR (and Chaotic-AUR) alone.
        local driver origin
        while read -r driver; do
            origin="aur"
            [ "${driver}" != "nvidia-open-dkms" ] || origin="pacman"
            [ -z "${2:-}" ] || [ "${2}" = "${origin}" ] || continue
            printf '%s\n%s\n' "${driver}" "$(nvidia_utils "${driver}")"
        done < <(awk -F '|' -v gpus="${dGPU[*]}" '
            BEGIN { n = split(gpus, word, " ") }
            {
                for (i = 1; i <= n; i++) {
                    if (substr(word[i], 1, length($3)) != $3) continue
                    k = split(FILENAME, path, "/")
                    if (!seen[path[k]]++) print path[k]
                }
            }' "${scrDir}"/nvidia-db/nvidia*dkms)
        return 0
    fi
    if grep -iq nvidia <<<"${dGPU[@]}"; then
        return 0
    else
        return 1
    fi
}

# Prints the legacy NVIDIA drivers as a TOML dependency block for the AUR
# helpers. deez installs those through yay or paru and passes over them without
# a word when neither is installed, so that case is caught here instead.
nvidia_aur_deps() {
    local pkgs=() missing=() pkg manager
    while read -r pkg; do
        [ -z "${pkg}" ] || pkgs+=("${pkg}")
    done < <(nvidia_detect --drivers aur)
    [ "${#pkgs[@]}" -gt 0 ] || return 0

    if ! command -v yay &>/dev/null && ! command -v paru &>/dev/null; then
        for pkg in "${pkgs[@]}"; do
            pkg_installed "${pkg}" || missing+=("${pkg}")
        done
        if [ "${#missing[@]}" -gt 0 ] && [ "${flg_DryRun:-0}" -ne 1 ]; then
            print_log -r "[NVIDIA] " -crit "ERROR" "${missing[*]} come from the AUR, which needs yay or paru, and neither is installed. Install one, or run the installer with -n to leave the NVIDIA driver alone." >&2
            return 1
        fi
        return 0
    fi

    printf '\n[[global.dependency]]\n'
    for manager in yay paru; do
        printf '%s = [' "${manager}"
        printf ' "%s",' "${pkgs[@]}"
        printf ' ]\n'
    done
}

# Installs the dependencies of the deez config given in "$@" and checks they
# landed. deez exits 0 whatever the package manager did (a failed transaction, a
# missing target, a declined prompt), so the result is read back with --check.
deez_deps_install() {
    local report
    "${deez_exe:?}" deps --install "$@" || return 1
    report="$("${deez_exe}" deps --check "$@" 2>&1)" || {
        printf '%s\n' "${report}"
        return 1
    }
    if grep -q 'Deps: missing' <<<"${report}"; then
        grep -F '[err]' <<<"${report}" || printf '%s\n' "${report}"
        return 1
    fi
    return 0
}

prompt_timer() {
    set +e
    unset PROMPT_INPUT
    local timsec=$1
    local msg=$2
    while [[ ${timsec} -ge 0 ]]; do
        echo -ne "\r :: ${msg} (${timsec}s) : "
        read -rt 1 -n 1 PROMPT_INPUT && break
        ((timsec--))
    done
    export PROMPT_INPUT
    echo ""
    set -e
}
print_log() {
    local executable="${0##*/}"
    local logFile="${cacheDir}/logs/${HYDE_LOG}/${executable}.log"
    mkdir -p "$(dirname "${logFile}")"
    local section=${log_section:-}
    {
        [ -n "${section}" ] && echo -ne "\e[32m[$section] \e[0m"
        while (("$#")); do
            case "$1" in
            -r | +r)
                echo -ne "\e[31m$2\e[0m"
                shift 2
                ;; # Red
            -g | +g)
                echo -ne "\e[32m$2\e[0m"
                shift 2
                ;; # Green
            -y | +y)
                echo -ne "\e[33m$2\e[0m"
                shift 2
                ;; # Yellow
            -b | +b)
                echo -ne "\e[34m$2\e[0m"
                shift 2
                ;; # Blue
            -m | +m)
                echo -ne "\e[35m$2\e[0m"
                shift 2
                ;; # Magenta
            -c | +c)
                echo -ne "\e[36m$2\e[0m"
                shift 2
                ;; # Cyan
            -wt | +w)
                echo -ne "\e[37m$2\e[0m"
                shift 2
                ;; # White
            -n | +n)
                echo -ne "\e[96m$2\e[0m"
                shift 2
                ;; # Neon
            -stat)
                echo -ne "\e[30;46m $2 \e[0m :: "
                shift 2
                ;; # status
            -crit)
                echo -ne "\e[97;41m $2 \e[0m :: "
                shift 2
                ;; # critical
            -warn)
                echo -ne "WARNING :: \e[30;43m $2 \e[0m :: "
                shift 2
                ;; # warning
            +)
                echo -ne "\e[38;5;$2m$3\e[0m"
                shift 3
                ;; # Set color manually
            -sec)
                echo -ne "\e[32m[$2] \e[0m"
                shift 2
                ;; # section use for logs
            -err)
                echo -ne "ERROR :: \e[4;31m$2 \e[0m"
                shift 2
                ;; #error
            *)
                echo -ne "$1"
                shift
                ;;
            esac
        done
        echo ""
    } | if [ -n "${HYDE_LOG}" ]; then
        tee >(sed 's/\x1b\[[0-9;]*m//g' >>"${logFile}")
    else
        cat
    fi
}

# Creates the Python environment and syncs it against this checkout's lock.
#
# The dot deployment, the dependency checks and hyde-shell all run out of that
# environment, and the revisions they run are the ones this checkout pins. A
# run that skips this works with whatever was installed the last time it did
# not, so a corrected pin never reaches the machine that needs it. It lives
# here rather than in a script of its own so the pre-install path and the
# installer cannot drift apart.
setup_python_env() {
    local pyutils="${cloneDir}/Configs/.local/lib/hyde/pyutils/python_env.py"
    local python_env_dir="${HOME}/.local/state/hyde/python_env"

    if [ "${flg_DryRun:-0}" -eq 1 ]; then
        print_log -y "[PYTHON] " -b "dry-run :: " "Would setup Python environment"
        return 0
    fi

    if ! python3 "${pyutils}" create; then
        print_log -r "[PYTHON] " -crit "ERROR" "Failed to create the Python environment; the error above says why"
        print_log -r "[PYTHON] " -stat "HINT" "A missing python3 or base-devel is the usual cause"
        return 1
    fi

    if ! "${python_env_dir}/bin/python" "${pyutils}" sync; then
        print_log -r "[PYTHON] " -crit "ERROR" "Failed to install dependencies"
        return 1
    fi

    print_log -g "[PYTHON] " -b "complete :: " "Environment setup complete"
}

# Runs each migration in "$1" missing from the record in "$2", in version order,
# and records the ones that exit zero. Migrations must therefore be safe to run
# on a machine that has no record yet, which replays all of them once.
run_pending_migrations() {
    local migrationDir="$1"
    local stateFile="$2"
    local migrationFile
    local applied=0
    local pending=0

    [ -d "${migrationDir}" ] || return 0
    find "${migrationDir}" -maxdepth 1 -type f | grep -q . || return 0

    mkdir -p "$(dirname "${stateFile}")"
    [ -f "${stateFile}" ] || : >"${stateFile}"

    while read -r migrationFile; do
        [ -n "${migrationFile}" ] || continue
        grep -qxF "${migrationFile}" "${stateFile}" && continue
        pending=$((pending + 1))
        echo "Found migration file: ${migrationFile}"
        # stdin is closed for the migration: inheriting the loop's stdin let one
        # that reads input swallow the names of every migration after it.
        if sh "${migrationDir}/${migrationFile}" </dev/null; then
            printf '%s\n' "${migrationFile}" >>"${stateFile}"
            applied=$((applied + 1))
        else
            print_log -warn "Migration" "Failed to execute ${migrationFile}"
        fi
    done < <(find "${migrationDir}" -maxdepth 1 -type f -printf '%f\n' | sort -V)

    [ "${pending}" -gt 0 ] || echo "No outstanding migrations in ${migrationDir}."
    return 0
}
