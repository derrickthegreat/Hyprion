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


-- ============================================================================
-- The maintainer's own ~/.config/hypr/hyprland.lua, kept here as a worked
-- example of what the user override layer can do. Copy the pieces you want
-- into your own file; do not copy it whole. The monitor block in particular is
-- for a 5120x1440 Samsung Odyssey G9 with 10-bit wide-gamut output and will
-- not suit a VM or a laptop panel.
-- ============================================================================

-- // █▀▄▀█ █▀█ █▄░█ █ ▀█▀ █▀█ █▀█ █▀
-- // █░▀░█ █▄█ █░▀█ █ ░█░ █▄█ █▀▄ ▄█
hl.monitor({
	output = "",
	mode = "highres",
	position = "auto",
	scale = "auto",
	cm = "wide",
	bitdepth = 10,
  -- sdr_min_luminance = 0.0,
  -- sdr_max_luminance = 200,
  -- min_luminance = 0.0,
  -- max_luminance = 1015,
  -- sdrbrightness = 1.2,
  -- sdrsaturation = 0.98
})

-- // █░█ █▀ █▀▀ █▀█   █▀█ █▀█ █▀▀ █▀▀ █▀
-- // █▄█ ▄█ ██▄ █▀▄   █▀▀ █▀▄ ██▄ █▀░ ▄█

hl.config({
	render = {
		cm_auto_hdr = 2,
	},
	input = {
		touchpad = {
			natural_scroll = false,
		},
	},
	dwindle = {
		preserve_split = true,
	},
	binds = {
		drag_threshold = 10,
	},
})

-- // █░█░█ █ █▄░█ █▀▄ █▀█ █░█░█   █▀█ █░█ █░░ █▀▀ █▀
-- // ▀▄▀▄▀ █ █░▀█ █▄▀ █▄█ ▀▄▀▄▀   █▀▄ █▄█ █▄▄ ██▄ ▄█

hl.window_rule({
	name = "battlenet_float",
	match = { initial_class = "battle.net" },
	float = true,
})

-- Keep the screen awake while video is fullscreen. The stock Lua config no
-- longer ships these; they used to live in windowrules.conf.
hl.window_rule({
	name = "idle_inhibit_media",
	match = { class = "^(.*(celluloid|mpv|vlc|[Ss]potify).*)$" },
	idle_inhibit = "fullscreen",
})

hl.window_rule({
	name = "idle_inhibit_browsers",
	match = { class = "^(.*([Ll]ibre[Ww]olf|floorp|brave-browser|firefox|chromium|zen|vivaldi).*)$" },
	idle_inhibit = "fullscreen",
})

-- // █▄▀ █▀▀ █▄█ █▄▄ █ █▄░█ █▀▄ █ █▄░█ █▀▀ █▀
-- // █░█ ██▄ ░█░ █▄█ █ █░▀█ █▄▀ █ █░▀█ █▄█ ▄█

local MOD = hyde.config.modifiers.main

-- Volume on the function row (F9/F10/F11 instead of the stock F10/F11/F12)
hl.bind(
	"F9",
	hl.dsp.exec_cmd(hyde.sh.volumecontrol("-o", "m")),
	{ description = "[Hardware Controls|Audio] toggle mute output", locked = true }
)
hl.bind(
	"F10",
	hl.dsp.exec_cmd(hyde.sh.volumecontrol("-o", "d")),
	{ description = "[Hardware Controls|Audio] decrease volume", locked = true, repeating = true }
)
hl.bind(
	"F11",
	hl.dsp.exec_cmd(hyde.sh.volumecontrol("-o", "i")),
	{ description = "[Hardware Controls|Audio] increase volume", locked = true, repeating = true }
)
-- Nothing rebinds F12, so drop the stock volume-up there instead of leaving it live
hl.unbind("F12")

-- Toggle focused window split (dwindle)
hl.bind(MOD .. " + J", hl.dsp.layout("togglesplit"), { description = "[Layout Management|Dwindle] toggle split" })

-- Middle-click to toggle floating
hl.bind(
	MOD .. " + mouse:274",
	hl.dsp.window.float({ action = "toggle" }),
	{ description = "[Window Management] click to toggle float", click = true }
)

-- ============================================================================
-- Scratchpad (special workspace) reclaims the S cluster; the screenshot binds
-- that the stock Lua config put there move back to the P cluster they used to
-- occupy. Rebinding a combo replaces the stock bind whatever its flags, so no
-- unbind is needed first.
-- ============================================================================

-- Scratchpad, as it was before the Lua migration dropped it
hl.bind(
	MOD .. " + S",
	hl.dsp.workspace.toggle_special(),
	{ description = "[Workspaces|Navigation|Special workspace] toggle scratchpad" }
)
hl.bind(
	MOD .. " + SHIFT + S",
	hl.dsp.window.move({ workspace = "special" }),
	{ description = "[Workspaces|Navigation|Special workspace] move to scratchpad" }
)
hl.bind(
	MOD .. " + ALT + S",
	hl.dsp.window.move({ workspace = "special", follow = false }),
	{ description = "[Workspaces|Navigation|Special workspace] move to scratchpad (silent)" }
)

-- Print Screen Keybinds
hl.bind(
	MOD .. " + P",
	hl.dsp.exec_cmd(hyde.sh.screenshot.snip()),
	{ description = "[Utilities] partial screenshot capture", locked = true }
)
hl.bind(
	MOD .. " + CONTROL + P",
	hl.dsp.exec_cmd(hyde.sh.screenshot.freeze()),
	{ description = "[Utilities] freeze and snip screen", locked = true }
)
hl.bind(
	MOD .. " + ALT + P",
	hl.dsp.exec_cmd(hyde.sh.screenshot.monitor()),
	{ description = "[Utilities] print monitor", locked = true }
)
hl.bind(
	"Print",
	hl.dsp.exec_cmd(hyde.sh.screenshot.full()),
	{ description = "[Utilities] print all monitors", locked = true }
)
