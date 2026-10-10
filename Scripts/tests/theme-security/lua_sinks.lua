-- Records the shell commands HyDE's Lua builds, without running any of them.
--
--   lua lua_sinks.lua hypr <hyde.lua>    loads the Hyprland config under a stub
--                                        `hl`, then fires hyprland.start
--   lua lua_sinks.lua dconf <dconf.lua>  runs color/dconf.lua with a fake lgi
--
-- Every command string goes to $EXEC_LOG, NUL-separated. Paths come from the
-- environment (HOME, XDG_*), so run it with a fake home.

local mode, entry = arg[1], arg[2]
local commands = {}

local function save()
	local out = assert(io.open(assert(os.getenv("EXEC_LOG"), "EXEC_LOG unset"), "w"))
	for _, cmd in ipairs(commands) do
		out:write(cmd, "\0")
	end
	out:close()
end

-- Nothing in here may reach a real shell or the session
os.execute = function(cmd)
	commands[#commands + 1] = cmd
	return true, "exit", 0
end
io.popen = function()
	return {read = function() end, lines = function() return function() end end, close = function() return true end}
end

if mode == "dconf" then
	package.preload["lgi"] = function()
		local settings = {set_string = function() end, set_int = function() end}
		local Settings = {new = function() return setmetatable({}, {__index = settings}) end, sync = function() end}
		return {Gio = {Settings = Settings}}
	end
	local getenv = os.getenv
	os.getenv = function(name)
		if name == "HYPRLAND_INSTANCE_SIGNATURE" then
			return "test"
		end
		return getenv(name)
	end
	dofile(entry)
	save()
	return
end

-- A stub of the hl API, after the audit harness. Unknown members are no-ops
-- that return an empty table, so an ipairs over a result ends at once.
local function noop()
	return {}
end
local function dsp_ns()
	return setmetatable({}, {__index = function(t, k)
		local v = (k == "window" or k == "workspace" or k == "group" or k == "cursor") and dsp_ns() or noop
		rawset(t, k, v)
		return v
	end})
end
local starts = {}
hl = setmetatable({}, {__index = function()
	return noop
end})
hl.dsp = dsp_ns()
hl.dsp.exec_cmd = function(cmd)
	return {exec = cmd}
end
hl.exec_cmd = function(cmd)
	commands[#commands + 1] = cmd
end
hl.dispatch = function(d)
	if type(d) == "table" and d.exec then
		commands[#commands + 1] = d.exec
	end
end
hl.on = function(event, cb)
	if event == "hyprland.start" then
		starts[#starts + 1] = cb
	end
	return {}
end
hl.notification = {create = noop, get = noop}
hl.layout = {register = noop}
hl.get_active_monitor = function()
	return {name = "DP-1", x = 0, y = 0, width = 1920, height = 1080, scale = 1, reserved = {0, 0, 0, 0}}
end
hl.get_monitors = function()
	return {hl.get_active_monitor()}
end
hl.get_cursor_pos = function()
	return {x = 0, y = 0}
end
hl.get_active_window = function() end
hl.get_config = function() end
hl.version = function()
	return "0.56.2"
end

dofile(entry)
for _, cb in ipairs(starts) do
	cb()
end
save()
