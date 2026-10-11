#!/usr/bin/env bash
# Lints every shell and Lua file in the repo. shellcheck reports warnings and
# errors, plus SC2086 (unquoted expansion), which it only rates a note but is
# the bug behind most of this repo's quoting fixes. Configs: .luacheckrc and
# .shellcheckrc. CI runs this; locally it needs both tools installed.
#   Scripts/tests/lint.sh

set -uo pipefail
cd "$(dirname "$(realpath "$0")")/../.." || exit 1

for tool in git shellcheck luacheck; do
	command -v "${tool}" >/dev/null || {
		echo "${tool} is not installed" >&2
		exit 2
	}
done

# *.sh, and any other file whose shebang runs sh or bash. zsh files are left
# out: shellcheck doesn't read zsh.
shell_files=()
lua_files=()
while IFS= read -r -d '' file; do
	[[ -f ${file} && ! -L ${file} ]] || continue
	case "${file}" in
	*.sh) shell_files+=("${file}") ;;
	*.lua) lua_files+=("${file}") ;;
	*)
		IFS= read -r first <"${file}" 2>/dev/null || continue
		[[ ${first} =~ ^#!\ ?[^\ ]*(/|env\ +)(ba)?sh(\ |$) ]] && shell_files+=("${file}")
		;;
	esac
done < <(git ls-files -z --cached --others --exclude-standard)

status=0
echo "== shellcheck: ${#shell_files[@]} files"
shellcheck --severity=warning "${shell_files[@]}" || status=1
shellcheck --severity=info --include=SC2086 "${shell_files[@]}" || status=1

echo "== luacheck: ${#lua_files[@]} files"
luacheck --codes --no-color --quiet "${lua_files[@]}" || status=1

((status == 0)) && echo "Lint passed."
exit "${status}"
