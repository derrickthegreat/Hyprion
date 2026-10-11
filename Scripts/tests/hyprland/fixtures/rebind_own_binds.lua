-- The same unbind-then-rebind sequence on a combo HyDE doesn't bind, so the
-- expired handle is the user's own, plus unbinds of combos nothing bound.
hl.bind("SUPER + CONTROL + ALT + F1", hl.dsp.exec_cmd("first"))
hl.unbind("SUPER + CONTROL + ALT + F1")
hl.bind("SUPER + CONTROL + ALT + F1", hl.dsp.exec_cmd("second"))
hl.bind("SUPER + CONTROL + ALT + F1", hl.dsp.exec_cmd("third"))
hl.unbind("SUPER + CONTROL + ALT + F1")
hl.unbind("SUPER + CONTROL + ALT + F1")
hl.bind("SUPER + CONTROL + ALT + F1", hl.dsp.exec_cmd("fourth"))

hl.unbind("SUPER + CONTROL + ALT + F2")
