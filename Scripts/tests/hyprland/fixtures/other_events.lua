-- A bind that fires on another event (release, long press, click) is added
-- next to the bind already on the combo, and hl.unbind(combo) drops all of them
-- at once, which expires the handles HyDE still holds.
local MOD = hyde.config.modifiers.main

hl.bind(MOD .. " + S", hl.dsp.exec_cmd("on-release"), { release = true })
hl.bind(MOD .. " + S", hl.dsp.workspace.toggle_special())
hl.unbind(MOD .. " + S")
hl.bind(MOD .. " + S", hl.dsp.exec_cmd("on-release"), { release = true })
hl.bind(MOD .. " + S", hl.dsp.workspace.toggle_special())

hl.unbind("ALT + ALT_R")
hl.bind("ALT + ALT_R", hl.dsp.exec_cmd("on-release"), { release = true, transparent = true })

hl.bind(MOD .. " + mouse:272", hl.dsp.window.float({ action = "toggle" }), { click = true })
hl.bind(MOD .. " + mouse:272", hl.dsp.window.drag(), { mouse = true })

hl.bind(MOD .. " + CONTROL + ALT + F3", hl.dsp.exec_cmd("tap"))
hl.bind(MOD .. " + CONTROL + ALT + F3", hl.dsp.exec_cmd("hold"), { long_press = true })
hl.unbind(MOD .. " + CONTROL + ALT + F3")
hl.bind(MOD .. " + CONTROL + ALT + F3", hl.dsp.exec_cmd("hold"), { long_press = true })
