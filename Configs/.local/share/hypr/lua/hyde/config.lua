-- config.lua

-- Main Hyprland Lua config file
-- This is loaded before any other files
-- Users can declare their config in ~/.config/hypr/hyprland.lua

_G.hyde = _G.hyde or {}
hyde.config = hyde.config or {}

-- ! Experimental! !
hyde.get_config = hyde.get_config or {}
function hyde.get_config(path)
	local cur = hyde.config
	for part in path:gmatch("[^.]+") do
		cur = cur[part]
	end
	return cur
end

function hyde.config.get(path)
	return function()
		return hyde.get_config(path)
	end
end

-- We use this to make hyde.config reactive in binds and handlers
-- this is not so cheap , but useful if we want to respect `hyde.config...  = values otf
-- without redeclaring binds and handlers, so we can change behavior on the fly by just changing config values!
-- This is analoggus to `hyde.dsp.exec_cmd`
function hyde.config.exec(path)
	return function()
		local cmd = hyde.get_config(path)
		if type(cmd) ~= "string" or cmd == "" then
			return
		end
		if type(hl.notification.create) == "function" then
			hl.notification.create(
				{
					text = "Launching " .. cmd,
					timeout = 1000
				}
			)
		end
		if type(hl.dsp.exec_cmd) == "function" then
			hl.dispatch(hl.dsp.exec_cmd(cmd))
		end
	end
end

-- * Stable *

local function merge_config(dest, src, opts)
	for k, v in pairs(src) do
		if type(v) == "table" and type(dest[k]) == "table" then
			merge_config(dest[k], v, opts)
		elseif opts and opts.skip_empty and (v == "" or v == nil) then -- luacheck: ignore 542
			-- preserve existing destination value when source is empty
		else
			dest[k] = v
		end
	end
end

function hyde.config.apply(cfg, opts)
	if type(cfg) ~= "table" then
		return hyde.config
	end
	merge_config(hyde.config, cfg, opts)
	return hyde.config
end

setmetatable(
	hyde.config,
	{
		__call = function(_, cfg, opts)
			return hyde.config.apply(cfg, opts)
		end
	}
)

-- * config.toml
local ok, toml = pcall(check_require, "toml")
if not ok then
	local message = "[HyDE] Hyprland does not detect TOML parser! Run: hyde-shell luainit"
	if type(hl.exec_cmd) == "function" then
		hl.exec_cmd("hyprctl seterror 'rgba(c79bf0ff)' " .. message)
	end
	toml = nil
end

-- config.toml -> hyde.config routing.
--
-- The current schema nests everything ([desktop.app], [desktop.ui],
-- [desktop.start], [hyprland.anim], ...) and merges 1:1 onto hyde.config.
-- The pre-Lua schema put app/ui keys flat under [hyprland] and [desktop] and
-- had a [hyprland-start] table. Those are routed here so an untouched
-- config.toml keeps overriding variables.lua exactly as it overrode the .conf
-- defaults. Precedence, lowest first: variables.lua, [desktop], [hyprland-start],
-- [hyprland], then the user's hyprland.lua.
local TOML_APP_KEYS = {
	browser = true,
	editor = true,
	explorer = true,
	terminal = true,
	lockscreen = true,
	quickapps = true
}

local TOML_UI_KEYS = {
	hyde_theme = true,
	gtk_theme = true,
	icon_theme = true,
	color_scheme = true,
	button_layout = true,
	cursor_theme = true,
	cursor_size = true,
	font = true,
	font_size = true,
	document_font = true,
	document_font_size = true,
	monospace_font = true,
	monospace_font_size = true,
	notification_font = true,
	bar_font = true,
	menu_font = true,
	groupbar_font = true,
	font_antialiasing = true,
	font_hinting = true,
	code_theme = true,
	sddm_theme = true
}

-- Sub-tables that are already in hyde.config shape; `apps` is an accepted alias of `app`.
local TOML_SECTION_ALIASES = {apps = "app"}

-- Returns a table shaped like hyde.config for one TOML section ([desktop] or [hyprland]).
local function route_toml_section(section)
	local out = {}
	for k, v in pairs(section) do
		if type(v) == "table" and next(v) ~= nil and type(next(v)) == "string" then
			-- nested table: already hyde.config shaped (app, ui, start, anim, window, ...)
			local name = TOML_SECTION_ALIASES[k] or k
			out[name] = out[name] or {}
			merge_config(out[name], v)
		elseif TOML_APP_KEYS[k] then
			out.app = out.app or {}
			out.app[k] = v
		elseif TOML_UI_KEYS[k] or (type(hyde.config.ui) == "table" and hyde.config.ui[k] ~= nil) then
			out.ui = out.ui or {}
			out.ui[k] = v
		else
			-- scalars and arrays that have no nested home (bar, background_path, ...)
			out[k] = v
		end
	end
	return out
end

function hyde.config.route_toml(data)
	if type(data) ~= "table" then
		return hyde.config
	end
	if type(data.desktop) == "table" then
		hyde.config.apply(route_toml_section(data.desktop))
	end
	if type(data["hyprland-start"]) == "table" then
		hyde.config.apply({start = data["hyprland-start"]})
	end
	if type(data.hyprland) == "table" then
		hyde.config.apply(route_toml_section(data.hyprland))
	end
	return hyde.config
end

-- tinytoml's error spans a source excerpt and a spec link; keep "line N: reason".
local function toml_error_summary(err)
	err = tostring(err)
	local line = err:match(", line (%d+):")
	local reason = err:match("\n%s*%d+ |[^\n]*\n\n?([^\n]+)")
	if not reason then
		reason = err:gsub("^[^\n]-:%d+: ", ""):match("[^\n]*%S[^\n]*") or err
	end
	return line and ("line " .. line .. ": " .. reason) or reason
end

-- Shown on "hyprland.start" (first load) or "config.reloaded" (later ones), as
-- binds.lua does, so the message waits for a screen instead of firing mid-load.
local function notify_toml_error(text)
	local function show()
		if type(hl.notification) == "table" and type(hl.notification.create) == "function" then
			pcall(hl.notification.create, {text = text, timeout = 15000})
		end
	end
	if type(hl.on) == "function" then
		hl.on("hyprland.start", show)
		hl.on("config.reloaded", show)
	else
		show()
	end
end

-- A file that doesn't parse is skipped, not raised: an error here would abort
-- hyprland.lua and drop Hyprland to its example config. Returns nil, reason.
function hyde.config.load_toml(filename)
	if type(toml) ~= "table" or type(toml.parse) ~= "function" then
		-- error("TOML parser not available")
		return -- Silent failure if TOML parser is not available, as this is an optional feature
	end
	local parsed, data = pcall(toml.parse, filename)
	if not parsed then
		local reason = toml_error_summary(data)
		local home = os.getenv("HOME")
		local shown = tostring(filename)
		if home and shown:find(home .. "/", 1, true) == 1 then
			shown = "~" .. shown:sub(#home + 1)
		end
		notify_toml_error("[Hyprion] Ignoring " .. shown .. ", " .. reason)
		return nil, reason
	end

	return hyde.config.route_toml(data)
end

local default_config = {
	ui = {
		hyde_theme = nil,
		-- gtk
		gtk_theme = nil,
		icon_theme = nil,
		color_scheme = nil,
		button_layout = nil,
		-- Cursor
		cursor_theme = nil,
		cursor_size = nil,
		-- Fonts
		font = nil,
		font_size = nil,
		document_font = nil,
		document_font_size = nil,
		monospace_font = nil,
		monospace_font_size = nil,
		notification_font = nil,
		bar_font = nil,
		menu_font = nil,
		font_antialiasing = nil,
		font_hinting = nil,
		-- Extra Themes
		code_theme = nil,
		sddm_theme = nil
	},
	wallbash = {
		mode = "theme"
	},
	window = {
		float_size_bounds = {
			enabled = true,
			scale = 0.95,
			force_center = false
		},
		float_follow_cursor = {
			enabled = true,
			mode = "default"
		}
	},
	monitor = {
		edge_margin = {0.01}
	},
	anim = {
		duration_scale = 1.0
	}
}

hyde.config(default_config)
hyde.config.ui = hyde.config.ui or {}
hyde.config.wallbash = hyde.config.wallbash or {}
hyde.config.window = hyde.config.window or {}
hyde.config.window.float = hyde.config.window.float or {}
hyde.config.monitor = hyde.config.monitor or {}
hyde.config.anim = hyde.config.anim or {}
hyde.config.app = hyde.config.app or {}
hyde.config.modifiers = hyde.config.modifiers or {}
hyde.config.start = hyde.config.start or {}

-- Example usage:
--
-- Direct table assignment:
-- hyde.config.ui.groupbar_font = "JetBrainsMono Nerd Font"
-- hyde.config.anim.duration_scale = 0.9
-- hyde.config.window.float_follow_cursor.enabled = true
--
-- Merge a config block safely:
-- hyde.config({
--     ui = {
--         groupbar_font = "JetBrainsMono Nerd Font",
--         icon_theme = "Tela-circle-dracula",
--     },
--     anim = {
--         duration_scale = 0.9,
--     },
--     other = {
--         added = "some other config",
--     },
-- })s
--
-- Bad: do not reassign hyde.config to a new table.
-- This file establishes defaults and merge behavior, so keep the table object intact.
-- Devs! Defualts are in `variables.lua`! Do not set defaults here, only in `variables.lua`! This file is for merge behavior and helper functions!
