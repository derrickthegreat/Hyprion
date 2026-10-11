-- Checks that a bind in the user's hyprland.lua replaces HyDE's bind on the
-- same combo whatever flags either carries, against a stubbed Hyprland API.
-- Run from the repo root:  lua Scripts/tests/lua/bind_override_test.lua

local root = arg[0]:match("^(.*)/Scripts/tests/lua/[^/]+$") or "."
local lua_root = root .. "/Configs/.local/share/hypr/lua"
-- dispatcher.lua requires hyde.utils, which hyde.lua's search path finds live.
package.path = lua_root .. "/?.lua;" .. package.path

local ALIASES = {CONTROL = "CTRL", WIN = "SUPER", LOGO = "SUPER", MOD1 = "ALT", MOD4 = "SUPER"}

-- What Hyprland matches a bind on: a set of modifiers plus the key.
local function canon(combo)
	local tokens = {}
	for token in combo:gmatch("[^+]+") do
		tokens[#tokens + 1] = token:match("^%s*(.-)%s*$"):upper()
	end
	local key = table.remove(tokens) or ""
	local seen, mods = {}, {}
	for _, token in ipairs(tokens) do
		token = ALIASES[token] or token
		if not seen[token] then
			seen[token] = true
			mods[#mods + 1] = token
		end
	end
	table.sort(mods)
	mods[#mods + 1] = key
	return table.concat(mods, "+")
end

local function dsp_proxy(name)
	return setmetatable({}, {
		__index = function(_, key)
			return dsp_proxy(name == "" and key or name .. "." .. key)
		end,
		__call = function(_, ...)
			return {dispatcher = name, args = {...}}
		end
	})
end

-- Binds Hyprland would run, in registration order.
local live
-- :remove() calls on an expired handle. Hyprland segfaults on the first one.
local expired_removes

local function drop(entry)
	for i = #live, 1, -1 do
		if live[i] == entry then
			table.remove(live, i)
		end
	end
	entry.expired = true
end

-- Models Hyprland 0.56.2: every bind on a combo fires, hl.unbind(combo) drops
-- all of them, and the handle hl.bind returns removes only its own bind, then
-- prints as expired. :remove() on an expired handle, including one that
-- hl.unbind expired, crashes Hyprland. "none" (no handle) and "inert" (a
-- remove that never takes) exercise the hl.unbind fallback in hyde/binds.lua.
local function fresh(handles)
	live = {}
	expired_removes = 0
	local noop = function()
	end
	_G.hl = {dsp = dsp_proxy(""), on = noop, monitor = noop, config = noop, window_rule = noop}
	hl.bind = function(combo, action, opts)
		local entry = {canon = canon(combo), action = action, opts = opts or {}}
		live[#live + 1] = entry
		if handles == "none" then
			return nil
		end
		return setmetatable({}, {
			__index = {
				remove = function()
					if entry.expired then
						expired_removes = expired_removes + 1
					elseif handles == "handle" then
						drop(entry)
					end
				end
			},
			__tostring = function()
				return entry.expired and "HL.Keybind(expired)" or "HL.Keybind(live)"
			end
		})
	end
	hl.unbind = function(combo)
		local target = canon(combo)
		for i = #live, 1, -1 do
			if live[i].canon == target then
				drop(live[i])
			end
		end
	end

	_G.hyde = {
		config = {
			app = {terminal = "kitty", explorer = "dolphin", browser = "firefox", editor = "code"},
			modifiers = {main = "SUPER"}
		}
	}
	dofile(lua_root .. "/hyde/dispatcher.lua")
	dofile(lua_root .. "/hyde/binds.lua")
	dofile(lua_root .. "/key_binds.lua")
end

local function commands_on(combo)
	local target, out = canon(combo), {}
	for _, bind in ipairs(live) do
		if bind.canon == target then
			local action = bind.action
			out[#out + 1] = action.dispatcher == "exec_cmd" and action.args[1] or action.dispatcher
		end
	end
	table.sort(out)
	return out
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

local function expect_only(label, combo, command)
	check(("%s: %s runs only %s"):format(label, combo, command), table.concat(commands_on(combo), " | "), command)
end

local VOL = "hyde-shell volumecontrol '-o' "

-- The move from Source/examples/hyprland.lua. Stock F10 mute is {locked},
-- stock F11 is {locked, repeating}: neither matches the override's flags.
local function user_override()
	hl.bind("F9", hl.dsp.exec_cmd(hyde.sh.volumecontrol("-o", "m")), {locked = true})
	hl.bind("F10", hl.dsp.exec_cmd(hyde.sh.volumecontrol("-o", "d")), {locked = true, repeating = true})
	hl.bind("F11", hl.dsp.exec_cmd(hyde.sh.volumecontrol("-o", "i")), {description = "no flags at all"})
	-- Stock spells this "SUPER + CTRL + B" and sets no flags.
	hl.bind("super+control+b", hl.dsp.exec_cmd("user-b"), {locked = true, transparent = true})
end

-- Binds HyDE still tracks on a combo, whatever event they fire on.
local function active_on(combo)
	local prefix = hyde.binds.canonicalize(combo) .. "|"
	local n = 0
	for id in pairs(hyde.binds._active) do
		if id:sub(1, #prefix) == prefix then
			n = n + 1
		end
	end
	return n
end

-- 1. Overrides replace the stock bind whatever its flags; untouched stock binds stay.
for _, mode in ipairs({"handle", "none", "inert"}) do
	fresh(mode)
	local stock_count = #live
	user_override()
	expect_only(mode, "F9", VOL .. "'m'")
	expect_only(mode, "F10", VOL .. "'d'")
	expect_only(mode, "F11", VOL .. "'i'")
	expect_only(mode, "SUPER + CTRL + B", "user-b")
	expect_only(mode, "F12", VOL .. "'i'")
	expect_only(mode, "XF86AudioMute", VOL .. "'m'")
	check(mode .. ": only the new F9 bind is added", #live, stock_count + 1)

	-- The entry point runs hyprland.lua and hyde.lua requires it again.
	user_override()
	expect_only(mode .. ", override run twice", "F10", VOL .. "'d'")
	check(mode .. ", override run twice: bind count unchanged", #live, stock_count + 1)

	-- hl.unbind expires the stock handle, so HyDE forgets it and rebinding
	-- must not remove it again.
	hl.unbind("SUPER + S")
	check(mode .. ": unbind forgets the stock bind", active_on("SUPER + S"), 0)
	hl.bind("SUPER + S", hl.dsp.exec_cmd("user-s"))
	expect_only(mode .. ", unbind then rebind", "SUPER + S", "user-s")
	check(mode .. ": no remove() on an expired handle", expired_removes, 0)
end

-- 2. A bind that fires on another event is added next to the stock one, and
-- survives the stock press bind being replaced.
fresh("handle")
hl.bind("SUPER + L", hl.dsp.exec_cmd("on-release"), {release = true})
check("release bind is added next to the stock press bind", #commands_on("SUPER + L"), 2)
hl.bind("SUPER + L", hl.dsp.exec_cmd("user-lock"), {locked = true})
check("press override keeps the release bind", table.concat(commands_on("SUPER + L"), " | "), "on-release | user-lock")
hl.bind("SUPER + L", hl.dsp.exec_cmd("user-lock-2"), {release = false})
check("release = false counts as a press bind", table.concat(commands_on("SUPER + L"), " | "), "on-release | user-lock-2")
hl.bind("F10", hl.dsp.exec_cmd("pad-a"), {device = {inclusive = true, list = {"macropad"}}})
check("device-filtered bind is added next to the stock bind", #commands_on("F10"), 2)
hl.bind("F10", hl.dsp.exec_cmd("pad-b"), {device = {list = {"macropad"}, inclusive = true}})
check("the same device filter replaces it", table.concat(commands_on("F10"), " | "), VOL .. "'m' | pad-b")
-- Stock SUPER + Z is a mouse (hold-to-drag) bind; a plain bind replaces it.
hl.bind("SUPER + Z", hl.dsp.exec_cmd("user-z"))
expect_only("plain bind over a mouse bind", "SUPER + Z", "user-z")

-- 3. The maintainer's example moves volume to F9-F11 and frees F12.
fresh("handle")
dofile(root .. "/Source/examples/hyprland.lua")
for _, key in ipairs({"F9", "F10", "F11", "F12"}) do
	local commands = commands_on(key)
	print(("     example %-3s -> %s"):format(key, #commands == 0 and "(unbound)" or table.concat(commands, " | ")))
end
expect_only("example", "F9", VOL .. "'m'")
expect_only("example", "F10", VOL .. "'d'")
expect_only("example", "F11", VOL .. "'i'")
check("example: F12 is unbound", #commands_on("F12"), 0)
expect_only("example", "SUPER + S", "workspace.toggle_special")
expect_only("example", "SUPER + P", "hyde-shell screenshot s")
check("example: no remove() on an expired handle", expired_removes, 0)

if failures > 0 then
	io.stderr:write(failures .. " failure(s)\n")
	os.exit(1)
end
print("all passed")
