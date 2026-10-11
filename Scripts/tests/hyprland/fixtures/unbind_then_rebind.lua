-- Unbinds stock combos, then binds them again, as an older
-- Source/examples/hyprland.lua did for the S cluster. hl.unbind expires the
-- handle HyDE keeps for the stock bind, and calling :remove() on that handle
-- segfaulted Hyprland 0.56.2 at every login (fixed after 9f94d749).
local MOD = hyde.config.modifiers.main

hl.unbind(MOD .. " + S")
hl.unbind(MOD .. " + SHIFT + S")
hl.unbind(MOD .. " + ALT + S")
hl.unbind(MOD .. " + CONTROL + A")

hl.bind(MOD .. " + S", hl.dsp.workspace.toggle_special())
hl.bind(MOD .. " + SHIFT + S", hl.dsp.window.move({ workspace = "special" }))
hl.bind(MOD .. " + ALT + S", hl.dsp.window.move({ workspace = "special", follow = false }))
hl.bind(MOD .. " + CONTROL + A", hl.dsp.exec_cmd("true"))
