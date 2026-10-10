-- Exercises hyde.config.load_toml outside Hyprland.
-- Run from the repo root:  lua Scripts/tests/lua/config_toml_test.lua

local root = arg[0]:match("^(.*)/Scripts/tests/lua/[^/]+$") or "."
package.path = table.concat({
	root .. "/Configs/.local/share/hypr/lua/?.lua",
	root .. "/Configs/.local/lib/hyde/luautils/?.lua",
	package.path
}, ";")

-- Hyprland globals the config module touches lazily.
_G.hl = {exec_cmd = function() end, notification = {}, dsp = {}, dispatch = function() end}
require("hyde.utils")
require("hyde.config")

local function write_tmp(contents)
	local path = os.tmpname()
	local f = assert(io.open(path, "w"))
	f:write(contents)
	f:close()
	return path
end

local function fresh_defaults()
	-- Mirror the shape variables.lua establishes; values are placeholders.
	hyde.config.app = {browser = "default-browser", editor = "default-editor", quickapps = nil}
	hyde.config.ui = {font = "Default Font", cursor_size = 24, font_hinting = "", gtk_theme = "Default-Gtk"}
	hyde.config.start = {bar = "default-bar", notifications = "default-notify"}
	hyde.config.anim = {duration_scale = 1.0}
	hyde.config.window = {float = {no_bounds = {class = {}}}}
	hyde.config.bar = nil
	hyde.config.background_path = nil
	hyde.config.browser = nil
	hyde.config.font = nil
end

local failures = 0
local function check(label, got, want)
	if got ~= want then
		failures = failures + 1
		io.stderr:write(("FAIL %s: got %s, want %s\n"):format(label, tostring(got), tostring(want)))
	else
		print("ok   " .. label)
	end
end

local function load(contents)
	fresh_defaults()
	local path = write_tmp(contents)
	hyde.config.load_toml(path)
	os.remove(path)
	return hyde.config
end

-- 1. Legacy flat [hyprland] keys (pre-Lua schema) land in app/ui, not at the top level.
local c = load([[
[hyprland]
browser = "firefox-developer-edition"
editor = "zeditor"
font = "Cantarell"
cursor_size = 32
font_hinting = "full"
bar = "waybar"
background_path = "/tmp/wall.png"
]])
check("legacy hyprland.browser -> app.browser", c.app.browser, "firefox-developer-edition")
check("legacy hyprland.editor -> app.editor", c.app.editor, "zeditor")
check("legacy hyprland.font -> ui.font", c.ui.font, "Cantarell")
check("legacy hyprland.cursor_size -> ui.cursor_size", c.ui.cursor_size, 32)
check("legacy hyprland.font_hinting -> ui.font_hinting", c.ui.font_hinting, "full")
check("legacy hyprland.bar stays top level", c.bar, "waybar")
check("legacy hyprland.background_path stays top level", c.background_path, "/tmp/wall.png")
check("no stray top-level browser", c.browser, nil)
check("no stray top-level font", c.font, nil)
check("untouched app key keeps default", c.app.quickapps, nil)
check("untouched ui key keeps default", c.ui.gtk_theme, "Default-Gtk")

-- 2. Legacy flat [desktop] keys route the same way.
c = load([[
[desktop]
terminal = "foot"
gtk_theme = "Adwaita-dark"
]])
check("legacy desktop.terminal -> app.terminal", c.app.terminal, "foot")
check("legacy desktop.gtk_theme -> ui.gtk_theme", c.ui.gtk_theme, "Adwaita-dark")

-- 3. Current nested schema merges 1:1, with the `apps` alias.
c = load([[
[desktop]
bar = "waybar"
[desktop.apps]
browser = "brave"
[desktop.ui]
font = "Inter"
[desktop.start]
bar = "custom-bar"
[hyprland.anim]
duration_scale = 0.5
[hyprland.window.float.no_bounds]
class = ["kitty", "foot"]
]])
check("desktop.apps alias -> app.browser", c.app.browser, "brave")
check("desktop.ui.font", c.ui.font, "Inter")
check("desktop.start.bar overrides", c.start.bar, "custom-bar")
check("desktop.start untouched key keeps default", c.start.notifications, "default-notify")
check("desktop.bar", c.bar, "waybar")
check("hyprland.anim.duration_scale", c.anim.duration_scale, 0.5)
check("hyprland.window.float.no_bounds.class[2]", c.window.float.no_bounds.class[2], "foot")

-- 4. Legacy [hyprland-start] still feeds start.*.
c = load([[
[hyprland-start]
bar = "legacy-bar"
]])
check("legacy hyprland-start.bar -> start.bar", c.start.bar, "legacy-bar")

-- 5. Precedence: [hyprland] beats [hyprland-start] beats [desktop].
c = load([[
[desktop]
browser = "generic"
[desktop.start]
bar = "generic-bar"
[hyprland-start]
bar = "legacy-bar"
[hyprland]
browser = "specific"
[hyprland.start]
bar = "specific-bar"
]])
check("hyprland.browser beats desktop.browser", c.app.browser, "specific")
check("hyprland.start.bar beats hyprland-start and desktop.start", c.start.bar, "specific-bar")

-- 6. Empty value is honoured as an explicit override, like the .conf era.
c = load([[
[desktop.ui]
font_hinting = ""
]])
check("empty string overrides", c.ui.font_hinting, "")

-- 7. A file that doesn't parse is skipped, not raised, and keeps every default.
fresh_defaults()
local bad = write_tmp([[
[desktop.start]
bar = "first"
[desktop.start]
bar = "second"
]])
local ok, result, reason = pcall(hyde.config.load_toml, bad)
os.remove(bad)
check("bad TOML does not raise", ok, true)
check("bad TOML returns nil", result, nil)
check("bad TOML reason is line + message", reason, "line 3: Cannot override existing table 'start' with new table")
check("bad TOML keeps start.bar default", hyde.config.start.bar, "default-bar")

-- 8. A leading UTF-8 byte order mark is not part of the document.
c = load('\239\187\191[desktop.start]\nbar = "bom-bar"\n')
check("BOM-prefixed file parses", c.start.bar, "bom-bar")

if failures > 0 then
	io.stderr:write(failures .. " failure(s)\n")
	os.exit(1)
end
print("all passed")
