-- Checks luautils/rofi/pos.lua against rofi 2.0 and 2.1, which read east/south
-- offsets in opposite directions, with Hyprland and `rofi -v` stubbed out.
-- Run from the repo root:  lua Scripts/tests/lua/rofi_pos_test.lua

local root = arg[0]:match("^(.*)/Scripts/tests/lua/[^/]+$") or "."
package.path = root .. "/Configs/.local/lib/hyde/?.lua;" .. package.path

-- 5120x1440 ultrawide with a 38px bar on top.
local MONITOR = {name = "DP-1", width = 5120, height = 1440, x = 0, y = 0, scale = 1, transform = 0, reserved = {0, 38, 0, 0}}
local cursor = {x = 0, y = 0}
package.loaded["luautils.hypr.hyprctl"] = {
	cursorpos = function()
		return cursor
	end,
	get_active_monitor = function()
		return MONITOR
	end
}

local rofi_version = ""
local real_popen = io.popen
io.popen = function(cmd, ...)
	if cmd:match("^rofi %-v") then
		return {
			read = function()
				return rofi_version
			end,
			close = function()
				return true
			end
		}
	end
	return real_popen(cmd, ...)
end

-- pos.lua caches the version for the life of the module, so load it fresh.
local function pos_for(version)
	rofi_version = version
	package.loaded["luautils.rofi.pos"] = nil
	return require("luautils.rofi.pos")
end

local failures = 0
local function check(name, got, want)
	if got == want then
		print("ok   " .. name)
	else
		failures = failures + 1
		print("FAIL " .. name .. "\n     got:  " .. tostring(got) .. "\n     want: " .. tostring(want))
	end
end

local pos = pos_for("")
check("2.1.1 build string reads as inward", pos.offsets_inward("Version: 2.1.1-dirty"), true)
check("2.0.0 reads as screen direction", pos.offsets_inward("Version: 2.0.0"), false)
check("1.7.x reads as screen direction", pos.offsets_inward("Version: 1.7.5+wayland3"), false)
check("3.0 reads as inward", pos.offsets_inward("Version: 3.0.0"), true)
check("no rofi reads as screen direction", pos.offsets_inward(""), false)

-- The clipboard dropdown's estimated size: 23em x 30em at scale 10.
local SIZE = {min_width = 23 * 40 / 3, min_height = 30 * 40 / 3}

cursor = {x = 4900, y = 20}
check(
	"rofi 2.1, top-right cursor: east offset points inward",
	pos_for("Version: 2.1.1").get_rofi_pos(SIZE).str,
	"window{location:east north;anchor:east north;x-offset:220px;y-offset:-18px;}"
)
check(
	"rofi 2.0, top-right cursor: east offset points left",
	pos_for("Version: 2.0.0").get_rofi_pos(SIZE).str,
	"window{location:east north;anchor:east north;x-offset:-220px;y-offset:-18px;}"
)

cursor = {x = 100, y = 1400}
check(
	"rofi 2.1, bottom-left cursor: south offset points inward",
	pos_for("Version: 2.1.1").get_rofi_pos(SIZE).str,
	"window{location:west south;anchor:west south;x-offset:100px;y-offset:40px;}"
)
check(
	"rofi 2.0, bottom-left cursor: south offset points up",
	pos_for("Version: 2.0.0").get_rofi_pos(SIZE).str,
	"window{location:west south;anchor:west south;x-offset:100px;y-offset:-40px;}"
)

cursor = {x = 2000, y = 300}
check(
	"rofi 2.1, top-left cursor: west/north offsets unchanged",
	pos_for("Version: 2.1.1").get_rofi_pos(SIZE).str,
	"window{location:west north;anchor:west north;x-offset:2000px;y-offset:262px;}"
)

io.popen = real_popen
if failures > 0 then
	print(failures .. " failed")
	os.exit(1)
end
print("all passed")
