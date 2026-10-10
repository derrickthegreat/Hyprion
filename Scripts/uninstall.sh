#!/usr/bin/env bash
#|---/ /+-------------------------------+---/ /|#
#|--/ /-| Script to remove HyDE configs |--/ /-|#
#|-/ /--| Prasanth Rangan               |-/ /--|#
#|/ /---+-------------------------------+/ /---|#

cat <<"EOF"

-------------------------------------------------
        .
       / \                 _  _      ___  ___
      /^  \      _____    | || |_  _|   \| __|
     /  _  \    |_____|   | __ | || | |) | _|
    /  | | ~\             |_||_|\_, |___/|___|
   /.-'   '-.\                  |__/

-------------------------------------------------


.: WARNING :: This will remove all config files related to HyDE :.

please type "DONT HYDE" to continue...
EOF

read -r PROMPT_INPUT
[ "${PROMPT_INPUT}" == "DONT HYDE" ] || exit 0

cat <<"EOF"

         _         _       _ _
 _ _ ___|_|___ ___| |_ ___| | |
| | |   | |   |_ -|  _| .'| | |
|___|_|_|_|_|_|___|_| |__,|_|_|


EOF

scrDir=$(dirname "$(realpath "$0")")
if ! source "${scrDir}/global_fn.sh"; then
    echo "Error: unable to source global_fn.sh..."
    exit 1
fi

CfgLst="${scrDir}/restore_cfg.lst"
if [ ! -f "${CfgLst}" ]; then
    echo "ERROR: '${CfgLst}' does not exist..."
    exit 1
fi

BkpDir="${HOME}/.config/cfg_backups/$(date +'%y%m%d_%Hh%Mm%Ss')_remove"
mkdir -p "${BkpDir}"

cat "${CfgLst}" | while read lst; do
    pth=$(echo "${lst}" | awk -F '|' '{print $3}')
    pth=$(eval echo "${pth}")
    cfg=$(echo "${lst}" | awk -F '|' '{print $4}')

    echo "${cfg}" | xargs -n 1 | while read -r cfg_chk; do
        [[ -z "${pth}" ]] && continue
        if [ -d "${pth}/${cfg_chk}" ] || [ -f "${pth}/${cfg_chk}" ]; then
            tgt=$(echo "${pth}" | sed "s+^${HOME}++g")
            if [ ! -d "${BkpDir}${tgt}" ]; then
                mkdir -p "${BkpDir}${tgt}"
            fi
            mv "${pth}/${cfg_chk}" "${BkpDir}${tgt}"
            echo -e "\033[0;34m[removed]\033[0m ${pth}/${cfg_chk}"
        fi
    done
done

# Moves what is left of a HyDE directory into the backup. restore_cfg.lst may
# already have moved some of its entries there, so it merges instead of nesting.
backup_rest() {
    local src="$1"
    local dst="${BkpDir}${src#"${HOME}"}"
    local moved=1
    [ -d "${src}" ] || return 0
    if [ -e "${dst}" ]; then
        cp -a -- "${src}/." "${dst}/" && rm -rf -- "${src}" || moved=0
    else
        mkdir -p "$(dirname "${dst}")" && mv -- "${src}" "${dst}" || moved=0
    fi
    if [ "${moved}" -eq 1 ]; then
        echo -e "\033[0;34m[removed]\033[0m ${src}"
    else
        echo -e "\033[0;31m[kept]\033[0m ${src} could not be moved to the backup, so it was left in place"
    fi
}

# The Python and Lua environments are rebuilt by the installer and hold nothing
# of the user's. config.toml, imported themes and the migration backups (for
# some, the only copy of their pre-Lua config) go to the backup.
rm -rf "$HOME/.local/state/hyde/python_env" "$HOME/.local/state/hyde/pip_env" "$HOME/.local/state/hyde/lua_env"
backup_rest "$HOME/.config/hyde"
backup_rest "$HOME/.local/state/hyde"
[ -d "$HOME/.cache/hyde" ] && rm -rf "$HOME/.cache/hyde"

cat <<NOTE
-------------------------------------------------------
.: Manual action required to complete uninstallation :.
-------------------------------------------------------

Everything listed as removed above was moved, not deleted, to
${BkpDir}
That includes ~/.config/hyde (config.toml, imported themes) and
~/.local/state/hyde (state and migration backups). Deleted outright: the cache
in ~/.cache/hyde and the Python and Lua environments, which the installer
rebuilds.

Remove HyDE related backups/icons/fonts/themes manually from these paths
$HOME/.config/cfg_backups               # this backup and all previous ones
$HOME/.local/share/fonts                # remove fonts from here
$HOME/.local/share/icons                # remove icons from here
$HOME/.local/share/themes               # remove themes from here
$HOME/.icons                            # remove icons from here
$HOME/.themes                           # remove themes from here

Revert back bootloader/pacman/sddm settings manually from these backups
/boot/loader/entries/*.conf.hyde.bkp    # restore systemd-boot from this backup
/etc/default/grub.hyde.bkp              # restore grub from this backup
/boot/grub/grub.hyde.bkp                # restore grub from this backup
/usr/share/grub/themes                  # remove grub themes from here
/etc/pacman.conf.hyde.bkp               # restore pacman from this backup
/etc/sddm.conf.d/the_hyde_project.conf  # remove to revert sddm
/usr/share/sddm/themes                  # remove sddm themes from here

Uninstall the packages manually that are no longer required based on these list
${scrDir}/pkg_core.lst
${scrDir}/pkg_extra.lst
NOTE
