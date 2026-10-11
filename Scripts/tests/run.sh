#!/usr/bin/env bash
# Runs every test suite: Scripts/tests/*/test_*.py and Scripts/tests/lua/*_test.lua.
# Exits non-zero if any suite fails. CI runs this; run it before pushing too.
#   Scripts/tests/run.sh

set -uo pipefail
cd "$(dirname "$(realpath "$0")")/../.." || exit 1

failed=()
for suite in Scripts/tests/*/test_*.py; do
	echo "== ${suite}"
	python3 "${suite}" || failed+=("${suite}")
done
for suite in Scripts/tests/lua/*_test.lua; do
	echo "== ${suite}"
	lua "${suite}" || failed+=("${suite}")
done

if ((${#failed[@]})); then
	printf '\nFailed: %s\n' "${failed[@]}"
	exit 1
fi
printf '\nAll suites passed.\n'
