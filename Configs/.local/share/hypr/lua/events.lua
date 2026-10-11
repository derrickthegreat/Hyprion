local floating_window_boundary = function(win)
	-- HyDE's helper to limit the window size when floating, based on the monitor's usable area.
	-- This prevents windows from opening larger than the screen, eg annoying  dolphin window
	if not win or not win.floating then
		return
	end

	if hyde.handle and hyde.handle.float_size_bounds then
		hyde.handle.float_size_bounds(win)
	end
end

-- Float mode (hyde-shell floatmode): while it is on, new windows open floating
-- and are tagged so switching it off can re-tile them
local float_mode_file = (os.getenv("XDG_RUNTIME_DIR") or "/tmp") .. "/hyde/floatmode"
-- Size and position each app's last float-mode window had when it closed, one
-- "app<TAB>w<TAB>h<TAB>x<TAB>y" per line (older lines carry only the size)
local float_sizes_file = (os.getenv("XDG_STATE_HOME") or (os.getenv("HOME") .. "/.local/state")) .. "/hyde/float_sizes"

local read_float_sizes = function()
	local sizes = {}
	local f = io.open(float_sizes_file, "r")
	if not f then
		return sizes
	end
	for line in f:lines() do
		local app, w, h, pos = line:match("^([^\t]+)\t(%d+)\t(%d+)(.*)$")
		if app then
			local x, y = pos:match("^\t(%-?%d+)\t(%-?%d+)$")
			sizes[app] = {w = tonumber(w), h = tonumber(h), x = tonumber(x), y = tonumber(y)}
		end
	end
	f:close()
	return sizes
end

-- Only windows float mode floated are remembered: dialogs often share their app's
-- class, and closing one must not replace the main window's size
local remember_float_size = function(win)
	if not win or not win.floating or not win.size then
		return
	end
	local app = win.initial_class or win.class
	if not app or app == "" or app:find("[\t\n]") then
		return
	end
	for _, tag in ipairs(win.tags or {}) do
		if tag:match("^hyde_floatmode") then
			local sizes = read_float_sizes()
			sizes[app] = {w = win.size.x, h = win.size.y, x = win.at and win.at.x, y = win.at and win.at.y}
			local f = io.open(float_sizes_file, "w")
			if not f then
				return
			end
			for name, size in pairs(sizes) do
				if size.x and size.y then
					f:write(string.format("%s\t%d\t%d\t%d\t%d\n", name, size.w, size.h, size.x, size.y))
				else
					f:write(string.format("%s\t%d\t%d\n", name, size.w, size.h))
				end
			end
			f:close()
			return
		end
	end
end

local float_mode_window = function(win)
	if not win or win.floating then
		return
	end
	local f = io.open(float_mode_file, "r")
	if not f then
		return
	end
	f:close()
	hl.dispatch(hl.dsp.window.float({window = win, action = "enable"}))
	hl.dispatch(hl.dsp.window.tag({window = win, tag = "+hyde_floatmode"}))

	-- Floated on open, a window keeps the tiled size it was just given, which fills
	-- the screen, and some clients (kitty) ask to be maximized just after mapping.
	-- Once that has landed, put it back where the app's last window closed, kept
	-- inside the usable area; without a saved place, use half the usable width and
	-- most of the height, centered.
	local l_mon = hyde.get_logical_monitor and hyde.get_logical_monitor()
	if not l_mon then
		return
	end
	local max_w = math.floor((l_mon.w - (l_mon.res.left + l_mon.res.right)) * l_mon.inv_scale)
	local max_h = math.floor((l_mon.h - (l_mon.res.top + l_mon.res.bottom)) * l_mon.inv_scale)
	local saved = read_float_sizes()[win.initial_class or win.class]
	local w = saved and math.min(saved.w, max_w) or math.floor(max_w * 0.5)
	local h = saved and math.min(saved.h, max_h) or math.floor(max_h * 0.7)
	local left = l_mon.x + l_mon.res.left * l_mon.inv_scale
	local top = l_mon.y + l_mon.res.top * l_mon.inv_scale
	hl.timer(function()
		hl.dispatch(hl.dsp.window.fullscreen({window = win, action = "unset", mode = "maximized"}))
		hl.dispatch(hl.dsp.window.resize({window = win, x = w, y = h, exact = true}))
		if saved and saved.x and saved.y then
			local x = math.max(left, math.min(saved.x, left + max_w - w))
			local y = math.max(top, math.min(saved.y, top + max_h - h))
			hl.dispatch(hl.dsp.window.move({window = win, x = math.floor(x), y = math.floor(y), exact = true}))
		else
			hl.dispatch(hl.dsp.window.center({window = win}))
		end
	end, {timeout = 150, type = "oneshot"})
end

local exit_handler = function()
	hl.dispatch(hl.dsp.exec_cmd("uwsm stop"))
	hl.dispatch(hl.dsp.exec_cmd("hyprshutdown"))
end

hl.on("window.open", float_mode_window)
hl.on("window.close", remember_float_size)
hl.on("window.open", floating_window_boundary)
-- hl.on("window.update_rules", floating_window_boundary)
hl.on("hyprland.shutdown", exit_handler)
