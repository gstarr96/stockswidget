-- Minimal JSON decoder for Rainmeter's Lua 5.1: objects, arrays, strings,
-- numbers, booleans and null (null becomes nil). Decoding only.

local json = {}

local ESCAPES = {
    ['"'] = '"', ['\\'] = '\\', ['/'] = '/',
    b = '\b', f = '\f', n = '\n', r = '\r', t = '\t',
}

local decodeValue

local function fail(message, pos)
    error(string.format('JSON error at position %d: %s', pos, message), 0)
end

local function skipWhitespace(str, pos)
    local _, finish = string.find(str, '^[ \n\r\t]*', pos)
    return finish + 1
end

local function utf8Char(code)
    if code < 0x80 then
        return string.char(code)
    elseif code < 0x800 then
        return string.char(0xC0 + math.floor(code / 0x40), 0x80 + code % 0x40)
    end
    return string.char(
        0xE0 + math.floor(code / 0x1000),
        0x80 + math.floor(code / 0x40) % 0x40,
        0x80 + code % 0x40)
end

local function decodeString(str, pos)
    local parts = {}
    local i = pos + 1
    while true do
        local special = string.find(str, '["\\]', i)
        if not special then fail('unterminated string', pos) end
        parts[#parts + 1] = string.sub(str, i, special - 1)
        if string.sub(str, special, special) == '"' then
            return table.concat(parts), special + 1
        end
        local escape = string.sub(str, special + 1, special + 1)
        if escape == 'u' then
            local code = tonumber(string.sub(str, special + 2, special + 5), 16)
            if not code then fail('invalid unicode escape', special) end
            parts[#parts + 1] = utf8Char(code)
            i = special + 6
        else
            local char = ESCAPES[escape]
            if not char then fail('invalid escape', special) end
            parts[#parts + 1] = char
            i = special + 2
        end
    end
end

local function decodeNumber(str, pos)
    local start, finish = string.find(str, '^-?%d+%.?%d*[eE]?[-+]?%d*', pos)
    if not start then fail('unexpected character', pos) end
    local value = tonumber(string.sub(str, start, finish))
    if not value then fail('invalid number', pos) end
    return value, finish + 1
end

local function decodeArray(str, pos)
    local result = {}
    pos = skipWhitespace(str, pos + 1)
    if string.sub(str, pos, pos) == ']' then return result, pos + 1 end
    while true do
        local value
        value, pos = decodeValue(str, pos)
        result[#result + 1] = value
        pos = skipWhitespace(str, pos)
        local char = string.sub(str, pos, pos)
        if char == ']' then return result, pos + 1 end
        if char ~= ',' then fail("expected ',' or ']'", pos) end
        pos = pos + 1
    end
end

local function decodeObject(str, pos)
    local result = {}
    pos = skipWhitespace(str, pos + 1)
    if string.sub(str, pos, pos) == '}' then return result, pos + 1 end
    while true do
        pos = skipWhitespace(str, pos)
        if string.sub(str, pos, pos) ~= '"' then fail('expected a key', pos) end
        local key
        key, pos = decodeString(str, pos)
        pos = skipWhitespace(str, pos)
        if string.sub(str, pos, pos) ~= ':' then fail("expected ':'", pos) end
        local value
        value, pos = decodeValue(str, pos + 1)
        result[key] = value
        pos = skipWhitespace(str, pos)
        local char = string.sub(str, pos, pos)
        if char == '}' then return result, pos + 1 end
        if char ~= ',' then fail("expected ',' or '}'", pos) end
        pos = pos + 1
    end
end

decodeValue = function(str, pos)
    pos = skipWhitespace(str, pos)
    local char = string.sub(str, pos, pos)
    if char == '{' then return decodeObject(str, pos) end
    if char == '[' then return decodeArray(str, pos) end
    if char == '"' then return decodeString(str, pos) end
    if string.sub(str, pos, pos + 3) == 'true' then return true, pos + 4 end
    if string.sub(str, pos, pos + 4) == 'false' then return false, pos + 5 end
    if string.sub(str, pos, pos + 3) == 'null' then return nil, pos + 4 end
    return decodeNumber(str, pos)
end

function json.decode(str)
    local value, pos = decodeValue(str, 1)
    pos = skipWhitespace(str, pos)
    if pos <= #str then fail('trailing characters', pos) end
    return value
end

return json
