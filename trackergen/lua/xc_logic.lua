-- Generic evaluator for the Xenoblade AP worlds' logic (mirrors xc_core.py's RuleCompiler).
--
-- Data comes from scripts/logic_data.lua (XC_DATA), generated from the apworld's data files:
--   XC_DATA.codes   item name -> tracker item code
--   XC_DATA.pool    item name -> number of copies in the progression pool (for ALL / half / %)
--   XC_DATA.cats    category  -> list of item / event names
--   XC_DATA.regions region -> { req = "<requires>", to = { connected regions } }
--   XC_DATA.start   list of starting regions (reachable from "Manual")
--   XC_DATA.events  list of { name = "...", region = "..." } (locked progression events)
--   XC_DATA.locs    [index] = { name, region, req, own_region_rule = true|false }
--   XC_DATA.opts    default option values (replaced by slot_data on connect)

XC = XC or {}
XC.funcs = XC.funcs or {}
XC.opts = XC.opts or {}
XC.events_have = {}
XC.reach = {}
XC.dirty = true

local G = XC_DATA

for k, v in pairs(G.opts or {}) do
    if XC.opts[k] == nil then XC.opts[k] = v end
end

------------------------------------------------------------------------------------------------------------------
-- counting
------------------------------------------------------------------------------------------------------------------
local function cnt(name)
    local n = 0
    local code = G.codes[name]
    if code then
        n = Tracker:ProviderCountForCode(code)
    end
    if XC.events_have[name] then
        n = n + 1
    end
    return n
end
XC.count = cnt

function XC.opt(name)
    local v = XC.opts[name]
    if v == nil then return 0 end
    if v == true then return 1 end
    if v == false then return 0 end
    return tonumber(v) or 0
end

------------------------------------------------------------------------------------------------------------------
-- tokenizer / parser (AND and OR evaluate left-to-right at equal precedence, like the Manual engine)
------------------------------------------------------------------------------------------------------------------
local function tokenize(s)
    local toks, i, n = {}, 1, #s
    while i <= n do
        local c = s:sub(i, i)
        if c:match("%s") then
            i = i + 1
        elseif c == "|" then
            local j = s:find("|", i + 1, true)
            toks[#toks + 1] = { t = "atom", v = s:sub(i + 1, j - 1) }
            i = j + 1
        elseif c == "{" then
            local j = s:find("}", i, true)
            toks[#toks + 1] = { t = "fn", v = s:sub(i + 1, j - 1) }
            i = j + 1
        elseif c == "(" or c == ")" then
            toks[#toks + 1] = { t = c }
            i = i + 1
        elseif c == "0" or c == "1" then
            toks[#toks + 1] = { t = "lit", v = (c == "1") }
            i = i + 1
        else
            local w = s:match("^%a+", i)
            if w and (w:upper() == "AND" or w:upper() == "OR") then
                toks[#toks + 1] = { t = w:upper() }
                i = i + #w
            else
                error("xc_logic: cannot tokenize '" .. s:sub(i, i + 20) .. "' in: " .. s)
            end
        end
    end
    return toks
end

local compile_text

local function resolve_count(spec, total)
    local c = spec:lower()
    if c == "all" then return total end
    if c == "half" then return math.floor(total / 2) end
    if c:sub(-1) == "%" and #c > 1 then
        local pct = math.max(0, math.min(1, (tonumber(c:sub(1, -2)) or 0) / 100))
        return math.ceil(total * pct)
    end
    return tonumber(c) or 1
end

------------------------------------------------------------------------------------------------------------------
-- field skills derived from blades (XC2; mirrors XCMixin.field_level in xc_core.py).  XC_DATA.skills is nil for the other games.
------------------------------------------------------------------------------------------------------------------
local SK = G.skills
local skill_blades = {}
if SK then
    for skill, _ in pairs(SK.skills) do skill_blades[skill] = {} end
    for name, b in pairs(SK.blades) do
        for skill, levels in pairs(b.levels) do
            table.insert(skill_blades[skill], { name = name, trust = b.trust, driver = b.driver, group = b.group, levels = levels })
        end
    end
end

local function field_level(skill)
    local mode
    if XC.opt("progressive_blade_trust") == 0 then mode = 0
    elseif XC.opt("trust_per_blade") > 0 then mode = 2
    else mode = 1 end
    local slots = math.max(1, XC.opt("blade_slots_per_driver"))
    local g_hearts = 5
    if mode == 1 then g_hearts = 1 + math.min(4, cnt("Progressive Blade Trust")) end
    local flex, groups = {}, {}
    for _, b in ipairs(skill_blades[skill]) do
        if cnt(b.name) > 0 then
            local hearts = 5
            if mode == 1 then hearts = g_hearts
            elseif mode == 2 and b.trust then hearts = 1 + math.min(4, cnt(b.trust)) end
            local v = b.levels[hearts]
            if v > 0 then
                if not b.group then
                    table.insert(flex, v)
                else
                    local key = (b.driver or "") .. "|" .. b.group
                    local g = groups[key]
                    if not g then groups[key] = { driver = b.driver, v = v } elseif v > g.v then g.v = v end
                end
            end
        end
    end
    local avail, excl_set, excl = 0, {}, {}
    for _, g in pairs(groups) do
        if g.driver and not excl_set[g.driver] and cnt(g.driver) > 0 then
            excl_set[g.driver] = true
            table.insert(excl, g.driver)
        end
    end
    for _, d in ipairs(SK.drivers) do if cnt(d) > 0 then avail = avail + 1 end end
    local generic = avail - #excl
    local seats = 2
    local best = 0
    local function try(chosen)
        local chosen_set = {}
        for _, d in ipairs(chosen) do chosen_set[d] = true end
        local n_party = 1 + #chosen + math.min(seats - #chosen, generic)
        local vals = {}
        for _, v in ipairs(flex) do table.insert(vals, v) end
        for _, g in pairs(groups) do
            if not g.driver or chosen_set[g.driver] then table.insert(vals, g.v) end
        end
        table.sort(vals, function(a, b) return a > b end)
        local total = 0
        for i = 1, math.min(#vals, n_party * slots) do total = total + vals[i] end
        if total > best then best = total end
    end
    try({})
    for i = 1, #excl do
        try({ excl[i] })
        if seats >= 2 then
            for j = i + 1, #excl do try({ excl[i], excl[j] }) end
        end
    end
    return best
end
XC.field_level = field_level

local function atom(text)
    local is_cat = text:sub(1, 1) == "@"
    local inner = text:gsub("^[@$]+", "")
    local name, count = inner:match("^(.-):(.*)$")
    if not name then name, count = inner, "1" end
    name = name:match("^%s*(.-)%s*$")
    count = count:match("^%s*(.-)%s*$")
    if is_cat then
        local members = G.cats[name]
        if not members then return function() return false end end
        local total = 0
        for _, m in ipairs(members) do total = total + (G.pool[m] or 0) end
        local n = resolve_count(count, total)
        if n <= 0 then return true end
        return function()
            local s = 0
            for _, m in ipairs(members) do
                s = s + cnt(m)
                if s >= n then return true end
            end
            return false
        end
    end
    if SK and SK.skills[name] and XC.opt("field_skill_logic") > 0 then
        local n = tonumber(count) or 1
        if n <= 0 then return true end
        return function() return field_level(name) >= n end
    end
    local n = resolve_count(count, G.pool[name] or 0)
    if n <= 0 then return true end
    if not G.codes[name] and not G.event_names[name] then return false end
    return function() return cnt(name) >= n end
end

local function combine(op, a, b)
    if op == "AND" then
        if a == false or b == false then return false end
        if a == true then return b end
        if b == true then return a end
        return function() return a() and b() end
    else
        if a == true or b == true then return true end
        if a == false then return b end
        if b == false then return a end
        return function() return a() or b() end
    end
end

local function call_function(spec)
    local fname, args = spec:match("^(%w+)%((.*)%)$")
    local f = XC.funcs[fname]
    if not f then error("xc_logic: unknown rule function " .. tostring(fname)) end
    local r = f((args or ""):match("^%s*(.-)%s*$"))
    if type(r) == "boolean" then return r end
    if type(r) == "string" then
        if r:match("^%s*$") then return true end
        return compile_text(r)
    end
    return r -- a function
end

compile_text = function(s)
    local toks = tokenize(s)
    local pos = 1
    local parse_expr

    local function operand()
        local t = toks[pos]
        if not t then error("xc_logic: unexpected end in: " .. s) end
        pos = pos + 1
        if t.t == "(" then
            local node = parse_expr()
            if toks[pos] and toks[pos].t == ")" then pos = pos + 1 end -- a missing ')' at the end is tolerated
            return node
        elseif t.t == "lit" then
            return t.v
        elseif t.t == "atom" then
            return atom(t.v)
        elseif t.t == "fn" then
            return call_function(t.v)
        end
        error("xc_logic: unexpected token " .. tostring(t.t) .. " in: " .. s)
    end

    parse_expr = function()
        local left = operand()
        while toks[pos] and (toks[pos].t == "AND" or toks[pos].t == "OR") do
            local op = toks[pos].t
            pos = pos + 1
            left = combine(op, left, operand())
        end
        return left
    end

    return parse_expr()
end

local compiled = {}
local region_rule = {}
function XC.compile(s)
    if s == nil or s == "" then return true end
    local c = compiled[s]
    if c == nil then
        c = compile_text(s)
        compiled[s] = c
    end
    return c
end

local function truthy(node)
    if type(node) == "function" then return node() end
    return node
end

function XC.reset_options(new_opts)
    if new_opts then
        for k, v in pairs(new_opts) do XC.opts[k] = v end
    end
    compiled = {}
    region_rule = {}
    XC.loc_rules = {}
    XC.dirty = true
end

------------------------------------------------------------------------------------------------------------------
-- built-in functions shared by every game
------------------------------------------------------------------------------------------------------------------
XC.funcs.YamlEnabled = function(name) return XC.opt(name) > 0 end
XC.funcs.YamlDisabled = function(name) return XC.opt(name) == 0 end
XC.funcs.YamlCompare = function(arg)
    local neg, name, op, val = arg:match("^%s*(!?)([%w_]+)%s*([<>=!]+)%s*(.-)%s*$")
    local cur = XC.opt(name)
    local target = tonumber(val)
    if target == nil then
        if val:lower() == "true" then target = 1 elseif val:lower() == "false" then target = 0 else target = 0 end
    end
    local r
    if op == "==" or op == "=" then r = cur == target
    elseif op == "!=" then r = cur ~= target
    elseif op == ">=" then r = cur >= target
    elseif op == "<=" then r = cur <= target
    elseif op == "<" then r = cur < target
    elseif op == ">" then r = cur > target
    else r = false end
    if neg == "!" then r = not r end
    return r
end

------------------------------------------------------------------------------------------------------------------
-- region reachability (with locked events) - recomputed lazily, at most once per UI frame
------------------------------------------------------------------------------------------------------------------
local function rule_of_region(name)
    local r = region_rule[name]
    if r == nil then
        local d = G.regions[name]
        r = XC.compile(d and d.req or "")
        region_rule[name] = r
    end
    return r
end

local function recompute()
    XC.events_have = {}
    local reach = {}
    local guard = 0
    while true do
        guard = guard + 1
        reach = {}
        local queue = {}
        for _, r in ipairs(G.start) do
            if not reach[r] and truthy(rule_of_region(r)) then
                reach[r] = true
                queue[#queue + 1] = r
            end
        end
        local qi = 1
        while qi <= #queue do
            local cur = queue[qi]
            qi = qi + 1
            local d = G.regions[cur]
            if d then
                for _, nxt in ipairs(d.to) do
                    if not reach[nxt] and truthy(rule_of_region(nxt)) then
                        reach[nxt] = true
                        queue[#queue + 1] = nxt
                    end
                end
            end
        end
        local grew = false
        for _, ev in ipairs(G.events) do
            if reach[ev.region] and not XC.events_have[ev.name] then
                XC.events_have[ev.name] = true
                grew = true
            end
        end
        if not grew or guard > 60 then break end
    end
    XC.reach = reach
    XC.dirty = false
end

local function fresh()
    if XC.dirty then recompute() end
end

XC.loc_rules = {}
function XC.location_accessible(idx)
    fresh()
    local L = G.locs[idx]
    if not L then return false end
    if not XC.reach[L.region] then return false end
    local r = XC.loc_rules[idx]
    if r == nil then
        r = XC.compile(L.req)
        XC.loc_rules[idx] = r
    end
    if XC.game_override then
        local o = XC.game_override(L, idx)
        if o ~= nil then return o end
    end
    return truthy(r)
end

-- PopTracker rule entry point:  "$xc|<index>"
function xc(idx)
    local ok, res = pcall(XC.location_accessible, tonumber(idx))
    if not ok then
        print("xc_logic error: " .. tostring(res))
        return false
    end
    return res and true or false
end

function xc_region(name)
    fresh()
    return XC.reach[name] and true or false
end

ScriptHost:AddOnFrameHandler("xc dirty", function() XC.dirty = true end)
for _, code in pairs(G.codes) do
    ScriptHost:AddWatchForCode("xc watch " .. code, code, function() XC.dirty = true end)
end
