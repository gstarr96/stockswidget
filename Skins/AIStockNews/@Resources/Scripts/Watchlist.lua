-- AI Stock News Watchlist: reads data\watchlist.json (written by run.py --tracker)
-- and lays the user's tickers out as a grid of tiles with background charts.

local json, chart
local cfg = {}
local state = {
    loaded = false,
    tiles = {},
    busy = false,
    busyTicks = 0,
    pending = {},
}

-- Seconds without a FinishAction before assuming the backend hung.
-- Keep above the RunCommand Timeout in the skin.
local BUSY_TIMEOUT = 150
local PYTHON_HINT = 'Install Python 3.9+ from python.org, or set Python= in Variables.inc.'
local HEADER_H = 24
local EMPTY_H = 34
local TILE_CHART = { top = 26, padding = 4, lineWidth = 1.4, lineAlpha = 190, areaAlpha = 70 }
local TILE_METERS = { 'Card', 'Symbol', 'Price', 'Pct', 'Points', 'Remove' }

local function option(meter, name, value)
    SKIN:Bang('!SetOption', meter, name, value or '')
end

local function numberVariable(name, default)
    return tonumber(SKIN:GetVariable(name)) or default
end

local function colorFor(direction)
    return cfg.colors[direction] or cfg.colors.flat
end

local function readData()
    local file = io.open(cfg.dataFile, 'r')
    if not file then return nil end
    local content = file:read('*all')
    file:close()
    local ok, data = pcall(json.decode, content)
    if ok and type(data) == 'table' then return data end
    return nil
end

local function backendOutput(measureName)
    local measure = SKIN:GetMeasure(measureName)
    local output = measure and measure:GetStringValue() or ''
    output = output:match('^%s*(.-)%s*$') or ''
    return output ~= '' and output:sub(1, 200) or nil
end

local function setStatus(text, status, tooltip)
    local colors = { error = cfg.colors.down, warning = cfg.colors.warn }
    option('MeterStatus', 'Text', text)
    option('MeterStatus', 'FontColor', colors[status] or cfg.colors.dim)
    option('MeterStatus', 'ToolTipText', tooltip)
    SKIN:Bang('!UpdateMeter', 'MeterStatus')
end

local function sanitize(raw)
    return (tostring(raw or ''):upper():gsub('[^A-Z0-9%.%-,]', ''))
end

local function resize(count)
    local height
    if count == 0 then
        height = cfg.padding + HEADER_H + EMPTY_H + cfg.padding
    else
        local rows = math.ceil(count / cfg.columns)
        height = cfg.padding + HEADER_H + rows * cfg.tileH + (rows - 1) * cfg.gap + cfg.padding
    end
    option('MeterBackground', 'Shape', 'Rectangle 0,0,' .. cfg.width .. ',' .. height
        .. ',12 | Fill Color ' .. cfg.colors.background .. ' | StrokeWidth 0')
    SKIN:Bang('!UpdateMeter', 'MeterBackground')
end

local function renderTile(i, tile)
    local prefix = 'Tile' .. i
    local color = colorFor(tile.direction)
    option(prefix .. 'Symbol', 'Text', tile.symbol)
    option(prefix .. 'Price', 'Text', tile.priceText)
    option(prefix .. 'Pct', 'Text', tile.changePctText)
    option(prefix .. 'Pct', 'FontColor', color)
    option(prefix .. 'Points', 'Text', tile.changePointsText)
    option(prefix .. 'Points', 'FontColor', color)
    option(prefix .. 'Card', 'ToolTipText', tile.name ~= tile.symbol and tile.name or '')
    chart.draw(SKIN, prefix .. 'Card', tile, cfg.tileW, cfg.tileH, cfg.colors, TILE_CHART)
end

-- Hidden meters still count toward DynamicWindowSize, so unused tiles are
-- parked at Y=0 instead of leaving empty rows below the grid.
local function placeTile(i, visible)
    for _, name in ipairs(TILE_METERS) do
        local meter = 'Tile' .. i .. name
        option(meter, 'Y', visible and cfg.tileY[meter] or '0')
    end
end

local function render()
    local shown = math.min(#state.tiles, cfg.maxTiles)
    for i = 1, cfg.maxTiles do
        local tile = state.tiles[i]
        if i <= shown and type(tile) == 'table' then
            renderTile(i, tile)
            placeTile(i, true)
            SKIN:Bang('!ShowMeterGroup', 'Tile' .. i)
        else
            placeTile(i, false)
            SKIN:Bang('!HideMeterGroup', 'Tile' .. i)
        end
        SKIN:Bang('!UpdateMeterGroup', 'Tile' .. i)
    end
    if shown == 0 then
        SKIN:Bang('!ShowMeter', 'MeterEmpty')
    else
        SKIN:Bang('!HideMeter', 'MeterEmpty')
    end
    resize(shown)
end

local function run(measure)
    state.busy = true
    state.busyTicks = 0
    state.measure = measure
    SKIN:Bang('!CommandMeasure', measure, 'Run')
end

local function runEdit(args, label)
    setStatus(label, 'ok')
    SKIN:Bang('!Redraw')
    if state.busy then
        table.insert(state.pending, { args = args, label = label })
        return
    end
    SKIN:Bang('!SetOption', 'MeasureTrackerEdit', 'Parameter',
        SKIN:GetVariable('BackendCommand') .. ' --tracker ' .. args)
    SKIN:Bang('!UpdateMeasure', 'MeasureTrackerEdit')
    run('MeasureTrackerEdit')
end

function Initialize()
    local resources = SKIN:GetVariable('@')
    json = dofile(resources .. 'Scripts\\json.lua')
    chart = dofile(resources .. 'Scripts\\chart.lua')
    cfg.dataFile = resources .. 'data\\watchlist.json'
    cfg.maxTiles = numberVariable('WatchMaxTiles', 12)
    cfg.columns = math.max(1, numberVariable('WatchColumns', 3))
    cfg.tileW = numberVariable('WatchTileW', 150)
    cfg.tileH = numberVariable('WatchTileH', 76)
    cfg.gap = numberVariable('WatchGap', 8)
    cfg.padding = numberVariable('Padding', 16)
    cfg.width = cfg.padding * 2 + cfg.columns * cfg.tileW + (cfg.columns - 1) * cfg.gap
    cfg.tileY = {}
    for i = 1, cfg.maxTiles do
        for _, name in ipairs(TILE_METERS) do
            local meter = 'Tile' .. i .. name
            cfg.tileY[meter] = SKIN:GetMeter(meter):GetOption('Y')
        end
    end
    cfg.colors = {
        up = SKIN:GetVariable('ColorUp'),
        down = SKIN:GetVariable('ColorDown'),
        flat = SKIN:GetVariable('ColorFlat'),
        warn = SKIN:GetVariable('ColorWarn'),
        dim = SKIN:GetVariable('ColorDim'),
        background = SKIN:GetVariable('ColorBackground'),
    }
end

function Update()
    if not state.loaded then
        state.loaded = true
        Reload()
    end

    if state.busy then
        state.busyTicks = state.busyTicks + 1
        if state.busyTicks > BUSY_TIMEOUT then
            state.busy = false
            setStatus('Update timed out', 'error', backendOutput(state.measure) or PYTHON_HINT)
            SKIN:Bang('!Redraw')
        end
    end
    return #state.tiles
end

-- fromBackend is true when called by RunCommand's FinishAction. That also fires
-- when Python could not be started, so an unchanged data file means failure.
function Reload(fromBackend)
    state.busy = false
    local data = readData()
    local produced = data ~= nil and data.generatedAt ~= state.generatedAt
    if data then state.generatedAt = data.generatedAt end

    if data then
        state.tiles = type(data.tiles) == 'table' and data.tiles or {}
        render()
        setStatus(data.statusText, data.status, data.message)
    else
        state.tiles = {}
        render()
        setStatus('Loading...', 'ok')
    end

    if fromBackend and not produced then
        local output = backendOutput(state.measure)
        setStatus(output and 'Update failed' or 'Python not found', 'error', output or PYTHON_HINT)
    end
    SKIN:Bang('!Redraw')

    local pending = table.remove(state.pending, 1)
    if pending then runEdit(pending.args, pending.label) end
end

-- Called by the timer. Skipped while another backend run is still going.
function Refresh()
    if not state.busy then run('MeasureTracker') end
end

function RefreshNow()
    if state.busy then return end
    setStatus('Refreshing...', 'ok')
    SKIN:Bang('!Redraw')
    run('MeasureTracker')
end

-- Called by the InputText measure after it stores the text in NewTickers.
function Add()
    local tickers = sanitize(SKIN:GetVariable('NewTickers'))
    SKIN:Bang('!SetVariable', 'NewTickers', '')
    if tickers:gsub(',', '') == '' then return end
    runEdit('--add ' .. tickers, 'Adding ' .. (tickers:gsub(',', ', ')) .. '...')
end

function Remove(i)
    local tile = state.tiles[i]
    local symbol = type(tile) == 'table' and (sanitize(tile.symbol):gsub(',', '')) or ''
    if symbol == '' then return end
    runEdit('--remove ' .. symbol, 'Removing ' .. symbol .. '...')
end
