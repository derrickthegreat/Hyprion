-- Moving volume to F9-F11 as Source/examples/hyprland.lua does: each bind
-- replaces the stock one whatever flags either carries, a second bind replaces
-- the user's first, and F12 is dropped without a replacement.
hl.bind("F9", hl.dsp.exec_cmd(hyde.sh.volumecontrol("-o", "m")), { locked = true })
hl.bind("F10", hl.dsp.exec_cmd(hyde.sh.volumecontrol("-o", "d")), { locked = true, repeating = true })
hl.bind("F10", hl.dsp.exec_cmd(hyde.sh.volumecontrol("-o", "d")), { locked = true, repeating = true })
hl.bind("F11", hl.dsp.exec_cmd(hyde.sh.volumecontrol("-o", "i")))
hl.unbind("F12")
hl.unbind("F12")
