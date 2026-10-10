-- Loads the whole Hyprland config (hyde.lua through events, start_up and the
-- user's hyprland.lua) against a stub `hl` and a throwaway HOME, to check that
-- a config.toml which doesn't parse no longer aborts the load.
-- Run from the repo root:  lua Scripts/tests/lua/hyprland_load_test.lua

local root = arg[0]:match("^(.*)/Scripts/tests/lua/[^/]+$") or "."
if root:sub(1, 1) ~= "/" then
	root = assert(os.getenv("PWD"), "PWD is unset; run from the repo root") .. "/" .. root
end

local function sh(cmd)
	assert(os.execute(cmd), "command failed: " .. cmd)
end

local function q(s)
	return "'" .. s:gsub("'", "'\\''") .. "'"
end

local function write(path, contents)
	local f = assert(io.open(path, "w"))
	f:write(contents)
	f:close()
end

-- Throwaway HOME whose share/lib trees are this checkout's.
local home = os.tmpname()
os.remove(home)
for _, dir in ipairs({"/.config/hypr", "/.config/hyde", "/.local/share", "/.local/lib", "/.local/state/hyde", "/.cache/hyde", "/run"}) do
	sh("mkdir -p " .. q(home .. dir))
end
sh("ln -s " .. q(root .. "/Configs/.local/share/hypr") .. " " .. q(home .. "/.local/share/hypr"))
sh("ln -s " .. q(root .. "/Configs/.local/lib/hyde") .. " " .. q(home .. "/.local/lib/hyde"))
write(home .. "/.config/hypr/hyprland.lua", "_G.__user_hyprland_loaded = true\n")

-- Only the fake HOME's variables exist, so nothing resolves to the real session.
local env = {
	HOME = home,
	XDG_CONFIG_HOME = home .. "/.config",
	XDG_DATA_HOME = home .. "/.local/share",
	XDG_STATE_HOME = home .. "/.local/state",
	XDG_CACHE_HOME = home .. "/.cache",
	XDG_RUNTIME_DIR = home .. "/run"
}
local real_getenv = os.getenv
os.getenv = function(name)
	return env[name]
end

-- Any API the config calls but the test doesn't care about is an inert object:
-- callable, indexable (hl.dsp.window.close()), and empty to ipairs.
local function inert()
	return setmetatable({}, {
		__index = function(_, k)
			if type(k) == "string" then
				return inert()
			end
		end,
		__call = function()
			return inert()
		end
	})
end

local log
local function stub_hl()
	log = {on = {}, notes = {}, execs = {}}
	local hl = inert()
	rawset(hl, "on", function(event, cb)
		log.on[#log.on + 1] = {event = event, cb = cb, src = debug.getinfo(2, "S").short_src}
		return inert()
	end)
	rawset(hl, "exec_cmd", function(cmd)
		log.execs[#log.execs + 1] = cmd
	end)
	rawset(hl, "env", function() end)
	rawset(hl, "notification", {
		create = function(opts)
			log.notes[#log.notes + 1] = opts
			return inert()
		end,
		get = function()
			return {}
		end
	})
	local dsp = inert()
	rawset(dsp, "exec_cmd", function()
		return inert()
	end)
	rawset(hl, "dsp", dsp)
	_G.hl = hl
end

local base_path, base_loaded = package.path, {}
for name in pairs(package.loaded) do
	base_loaded[name] = true
end

-- Fresh Lua-side state per run, the way Hyprland rebuilds it on every reload.
local function load_chain(config_toml)
	for name in pairs(package.loaded) do
		if not base_loaded[name] then
			package.loaded[name] = nil
		end
	end
	package.path = base_path
	_G.hyde, _G.check_require, _G.__user_hyprland_loaded = nil, nil, nil
	os.remove(home .. "/.config/hyde/config.toml")
	if config_toml then
		write(home .. "/.config/hyde/config.toml", config_toml)
	end
	stub_hl()
	return pcall(dofile, home .. "/.local/share/hypr/hyde.lua")
end

local function subscribed(event, pattern)
	for _, sub in ipairs(log.on) do
		if sub.event == event and sub.src:find(pattern) then
			return true
		end
	end
	return false
end

local function fire(event)
	for _, sub in ipairs(log.on) do
		if sub.event == event then
			sub.cb()
		end
	end
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

-- 1. Baseline: a valid config.toml loads and applies.
local ok, err = load_chain('[desktop.start]\nbar = "toml-bar"\n')
check("valid config.toml: load succeeds", ok, true)
if not ok then
	io.stderr:write(tostring(err) .. "\n")
end
check("valid config.toml: value applied", ok and hyde.config.start.bar, "toml-bar")
check("valid config.toml: no notification", #log.notes, 0)

-- 2. A duplicated table header used to raise out of hyprland.lua.
ok, err = load_chain('[desktop.start]\nbar = "first"\n[desktop.start]\nbar = "second"\n')
check("duplicate header: load succeeds", ok, true)
if not ok then
	io.stderr:write(tostring(err) .. "\n")
end
check("duplicate header: default bar kept", ok and hyde.config.start.bar:find("waybar") ~= nil, true)
check("duplicate header: events.lua still loaded", subscribed("window.open", "events%.lua$"), true)
check("duplicate header: start_up.lua still loaded", subscribed("hyprland.start", "start_up%.lua$"), true)
check("duplicate header: user hyprland.lua still loaded", _G.__user_hyprland_loaded, true)
check("duplicate header: nothing shown mid-load", #log.notes, 0)
fire("hyprland.start")
check("duplicate header: one notification on start", #log.notes, 1)
local text = log.notes[1] and log.notes[1].text or ""
check("notification names the file", text:find("~/.config/hyde/config.toml", 1, true) ~= nil, true)
check(
	"notification carries line and reason",
	text:find("line 3: Cannot override existing table 'start' with new table", 1, true) ~= nil,
	true
)
check("notification has a timeout", type(log.notes[1] and log.notes[1].timeout), "number")
fire("config.reloaded")
check("notification repeats on reload", #log.notes, 2)

-- 3. A typo (unclosed table header) is skipped the same way.
ok = load_chain('[desktop.start\nbar = "x"\n')
check("typo: load succeeds", ok, true)
check("typo: user hyprland.lua still loaded", _G.__user_hyprland_loaded, true)

-- 4. A UTF-8 byte order mark is accepted, not reported.
ok = load_chain('\239\187\191[desktop.start]\nbar = "bom-bar"\n')
check("BOM: load succeeds", ok, true)
check("BOM: value applied", ok and hyde.config.start.bar, "bom-bar")
fire("hyprland.start")
check("BOM: no notification", #log.notes, 0)

os.getenv = real_getenv
sh("rm -rf " .. q(home))

if failures > 0 then
	io.stderr:write(failures .. " failure(s)\n")
	os.exit(1)
end
print("all passed")
