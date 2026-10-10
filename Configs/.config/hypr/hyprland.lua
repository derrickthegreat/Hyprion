-- Hyprland loads this file when it is started without a config, and it prefers
-- it over hyprland.conf. HyDE loads it too, last, as the override layer below.
-- The block keeps the two apart: hyde.lua sets `hyde` on its first line, so it
-- runs only when this file is the entry point and HyDE has not been loaded.
-- Removing it leaves a session with a cursor and nothing else.
if not hyde then
	local share = os.getenv("XDG_DATA_HOME") or (os.getenv("HOME") .. "/.local/share")
	local entry = share .. "/hypr/hyde.lua"
	local handle = io.open(entry, "r")
	if not handle then
		error("HyDE is not installed at " .. entry .. ". Run install.sh -r, or point Hyprland at your own config.")
	end
	handle:close()
	dofile(entry)
end

-- Your Hyprland configuration. HyDE never overwrites this file.
--
-- It loads after HyDE's own binds, so settings here take precedence. HyDE's
-- defaults live in ~/.local/share/hypr/lua/ and are overwritten on every
-- update, so edits there do not survive.
--
-- Adding a keybind:
--
--     hl.bind("SUPER + SPACE", hl.dsp.exec_cmd(hyde.sh.gamelauncher()), {
--         description = "[Utilities] game launcher",
--     })
--
-- Replacing one of HyDE's: bind the same combination again and yours replaces
-- it, whatever flags either carries. Only a bind that fires on a different
-- event (release, long_press, click, drag, or a device filter) is added next to
-- the old one instead. To make F10 lower the volume instead of muting:
--
--     hl.bind("F10", hl.dsp.exec_cmd(hyde.sh.volumecontrol("-o", "d")), {
--         locked = true,
--         repeating = true,
--         description = "[Hardware Controls|Audio] decrease volume",
--     })
--
-- Removing one of HyDE's without a replacement takes hl.unbind, with the
-- combination spelled as in ~/.local/share/hypr/lua/key_binds.lua:
--
--     hl.unbind("F12")
--
-- Press SUPER + / to see what is actually loaded, your own binds included.
-- The full reference is KEYBINDINGS.md in the HyDE repository.
--
-- Other Lua files next to this one can be pulled in with require("name").
--
-- Monitors. HyDE picks sane defaults for whatever is plugged in, so set these
-- only when the default is wrong. One entry per output; `output = ""` is the
-- catch-all. See https://wiki.hyprland.org/Configuring/Monitors/ for fields.
--
--     hl.monitor({ output = "", mode = "preferred", position = "auto", scale = "auto" })
--     hl.monitor({ output = "DP-1", mode = "5120x1440@240", position = "0x0", scale = 1 })
--
-- A fuller example, including monitor colour management, window rules and
-- rebound keys, is at Source/examples/hyprland.lua in the HyDE repository.
