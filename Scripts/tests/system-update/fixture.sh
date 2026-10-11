# shellcheck shell=bash
# Sourced by the fake commands in shims/. UPDATE_FIXTURE picks a directory
# under fixtures/; each file there is the canned output of one command.
fixture="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/fixtures/${UPDATE_FIXTURE:-busy}"
if [ ! -d "$fixture" ]; then
    echo "fake $(basename "$0"): no fixture named '${UPDATE_FIXTURE}'" >&2
    exit 1
fi
# Upgrade markers live here so a second check after a fake upgrade comes back empty
state="${XDG_RUNTIME_DIR:?}/hyde-update-test"
mkdir -p "$state"

show() { if [ -f "$fixture/$1" ]; then cat "$fixture/$1"; fi; }
upgraded() { [ -e "$state/upgraded-$1" ]; }

fake_upgrade() {
    local manager=$1 answer
    echo ":: Starting fake $manager upgrade"
    read -rp ":: Proceed with installation? [Y/n] " answer
    case "$answer" in [nN]*) return 1 ;; esac
    sleep 1
    touch "$state/upgraded-$manager"
    echo ":: Done"
}
