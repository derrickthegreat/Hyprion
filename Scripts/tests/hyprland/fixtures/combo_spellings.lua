-- One combo spelled several ways (modifier order, CTRL/CONTROL, spacing)
-- is one bind to HyDE's dedup, so unbinding under one spelling and binding
-- under another goes through the same stale-handle path.
hl.unbind("SUPER + SHIFT + S")
hl.bind("SHIFT + SUPER + S", hl.dsp.exec_cmd("order"))
hl.bind("SUPER+SHIFT+S", hl.dsp.exec_cmd("spacing"))

hl.unbind("SUPER + CTRL + P")
hl.bind("SUPER + CONTROL + P", hl.dsp.exec_cmd("control"))
hl.unbind("SUPER + CONTROL + P")
hl.bind("CTRL+SUPER+P", hl.dsp.exec_cmd("order and spacing"))
