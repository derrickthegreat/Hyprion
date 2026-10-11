-- luacheck for HyDE's Lua: the Hyprland config under Configs/.local/share/hypr,
-- the Lua tools in Configs/.local/lib/hyde, and the tests.

-- Hyprland provides `hl`; hyde.lua defines `hyde`, and utils.lua puts
-- `check_require` on _G for every config file. HyDE wraps hl's functions, so
-- all three are writable.
globals = { "hl", "hyde", "check_require" }

-- Binds and their descriptions run long.
max_line_length = false

-- A method that ignores `self` still has to accept it.
ignore = { "212/self" }

exclude_files = {
    -- tinytoml and rxi's json.lua, kept as their authors wrote them.
    "Configs/.local/share/hypr/lua/lib/toml.lua",
    "Configs/.local/lib/hyde/luautils/toml.lua",
    "Configs/.local/lib/hyde/luautils/json.lua",
}

-- The tests swap out os.getenv, io.popen and os.execute to sandbox the config.
files["Scripts/tests"] = { ignore = { "122" } }
