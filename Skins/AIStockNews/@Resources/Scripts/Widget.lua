-- AI Stock News: reads data\widget.json (written by the Python backend),
-- rotates the story carousel and draws the story and index charts.

local json, chart
local cfg = {}
local state = {
    loaded = false,
    stories = {},
    index = 1,
    tick = 0,
    paused = false,
    busy = false,
    busyTicks = 0,
}

-- Seconds without a FinishAction before assuming the backend hung.
-- Keep above the RunCommand Timeout in the skin.
local BUSY_TIMEOUT = 320
local PYTHON_HINT = 'Install Python 3.9+ from python.org, or set Python= in Variables.inc.'
local INDEX_COUNT = 3
local SENTIMENT_DIRECTION = { positive = 'up', negative = 'down' }

local function option(meter, name, value)
    SKIN:Bang('!SetOption', meter, name, value or '')
end

local function numberVariable(name, default)
    return tonumber(SKIN:GetVariable(name)) or default
end

local function colorFor(direction)
    return cfg.colors[direction] or cfg.colors.flat
end

local function drawChart(meter, series, width, height)
    chart.draw(SKIN, meter, series, width, height, cfg.colors)
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

local function backendOutput()
    local measure = SKIN:GetMeasure('MeasureBackend')
    local output = measure and measure:GetStringValue() or ''
    output = output:match('^%s*(.-)%s*$') or ''
    return output ~= '' and output:sub(1, 200) or nil
end

local function setStatus(text, status, tooltip)
    local colors = { error = cfg.colors.down, warning = cfg.colors.warn, setup = cfg.colors.warn }
    option('MeterStatus', 'Text', text)
    option('MeterStatus', 'FontColor', colors[status] or cfg.colors.dim)
    option('MeterStatus', 'ToolTipText', tooltip)
    SKIN:Bang('!UpdateMeter', 'MeterStatus')
end

local function renderEmpty(title, message)
    for _, meter in ipairs({ 'MeterTicker', 'MeterCompany', 'MeterSentiment', 'MeterStoryPrice',
        'MeterStoryChange', 'MeterSource', 'MeterPager' }) do
        option(meter, 'Text', '')
    end
    option('MeterHeadline', 'Text', title)
    option('MeterHeadline', 'ToolTipText', '')
    option('MeterSummary', 'Text', message)
    drawChart('MeterStoryChart', nil, cfg.storyW, cfg.storyH)
    SKIN:Bang('!UpdateMeterGroup', 'Story')
end

local function reportBackendFailure()
    local output = backendOutput()
    if output then
        setStatus('Update failed', 'error', output)
        if #state.stories == 0 then renderEmpty('Could not load market data', output) end
    else
        setStatus('Python not found', 'error', PYTHON_HINT)
        if #state.stories == 0 then renderEmpty('Python not found', PYTHON_HINT) end
    end
end

local function renderStory()
    local story = state.stories[state.index]
    if type(story) ~= 'table' then
        renderEmpty('No stories yet', '')
        return
    end

    option('MeterTicker', 'Text', story.ticker)
    option('MeterCompany', 'Text', story.company)
    option('MeterSentiment', 'Text', (story.sentiment or ''):upper())
    option('MeterSentiment', 'FontColor', colorFor(SENTIMENT_DIRECTION[story.sentiment]))
    option('MeterHeadline', 'Text', story.headline)
    option('MeterSummary', 'Text', story.summary)
    option('MeterSource', 'Text', (story.source or '') ~= '' and ('Source: ' .. story.source) or '')
    option('MeterPager', 'Text', state.index .. ' / ' .. #state.stories)

    option('MeterHeadline', 'ToolTipText', (story.url or '') ~= '' and 'Open article' or '')

    local chart = story.chart
    if type(chart) == 'table' then
        option('MeterStoryPrice', 'Text', chart.priceText)
        option('MeterStoryChange', 'Text', chart.changeText)
        option('MeterStoryChange', 'FontColor', colorFor(chart.direction))
    else
        option('MeterStoryPrice', 'Text', '')
        option('MeterStoryChange', 'Text', 'Chart unavailable')
        option('MeterStoryChange', 'FontColor', cfg.colors.dim)
    end
    drawChart('MeterStoryChart', chart, cfg.storyW, cfg.storyH)
    SKIN:Bang('!UpdateMeterGroup', 'Story')
end

local function renderIndices(indices)
    for i = 1, INDEX_COUNT do
        local prefix = 'MeterIndex' .. i
        local index = indices[i]
        if type(index) == 'table' then
            option(prefix .. 'Name', 'Text', index.name)
            option(prefix .. 'Price', 'Text', index.priceText)
            option(prefix .. 'Change', 'Text', index.changePctText)
            option(prefix .. 'Change', 'FontColor', colorFor(index.direction))
            option(prefix .. 'Points', 'Text', index.changePointsText)
            option(prefix .. 'Points', 'FontColor', colorFor(index.direction))
        else
            option(prefix .. 'Price', 'Text', '--')
            option(prefix .. 'Change', 'Text', '')
            option(prefix .. 'Points', 'Text', '')
        end
        drawChart(prefix .. 'Chart', index, cfg.indexW, cfg.indexH)
    end
    SKIN:Bang('!UpdateMeterGroup', 'Markets')
end

function Initialize()
    local resources = SKIN:GetVariable('@')
    json = dofile(resources .. 'Scripts\\json.lua')
    chart = dofile(resources .. 'Scripts\\chart.lua')
    cfg.dataFile = resources .. 'data\\widget.json'
    cfg.slideSeconds = math.max(3, numberVariable('SlideSeconds', 12))
    cfg.storyW = numberVariable('StoryW', 410)
    cfg.storyH = numberVariable('StoryChartH', 62)
    cfg.indexW = numberVariable('IndexChartW', 182)
    cfg.indexH = numberVariable('IndexChartH', 28)
    cfg.colors = {
        up = SKIN:GetVariable('ColorUp'),
        down = SKIN:GetVariable('ColorDown'),
        flat = SKIN:GetVariable('ColorFlat'),
        warn = SKIN:GetVariable('ColorWarn'),
        dim = SKIN:GetVariable('ColorDim'),
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
            reportBackendFailure()
            SKIN:Bang('!Redraw')
        end
    end

    if not state.paused and #state.stories > 1 then
        state.tick = state.tick + 1
        if state.tick >= cfg.slideSeconds then Next() end
    end
    return state.index
end

-- fromBackend is true when called by RunCommand's FinishAction. That also fires
-- when Python could not be started, so an unchanged data file means failure.
function Reload(fromBackend)
    state.busy = false
    local data = readData()
    local produced = data ~= nil and data.generatedAt ~= state.generatedAt
    if data then state.generatedAt = data.generatedAt end

    if data then
        state.stories = type(data.stories) == 'table' and data.stories or {}
        if state.index > #state.stories then state.index = 1 end
        state.tick = 0
        renderIndices(type(data.indices) == 'table' and data.indices or {})
        if #state.stories == 0 then
            local title = data.status == 'setup' and 'Setup required' or 'No stories right now'
            renderEmpty(title, data.message)
        else
            renderStory()
        end
        setStatus(data.statusText, data.status, data.message)
    else
        state.stories = {}
        renderIndices({})
        renderEmpty('Loading market news...', 'The first update can take up to a minute.')
        setStatus('Starting', 'ok')
    end

    if fromBackend and not produced then reportBackendFailure() end
    SKIN:Bang('!Redraw')
end

function SetBusy()
    state.busy = true
    state.busyTicks = 0
    setStatus('Refreshing...', 'ok')
    SKIN:Bang('!Redraw')
end

function OpenArticle()
    local story = state.stories[state.index]
    local url = type(story) == 'table' and story.url or ''
    if url ~= '' then
        -- [&] keeps query strings intact; Rainmeter treats & as a command separator.
        SKIN:Bang('["' .. url:gsub('&', '[&]') .. '"]')
    end
end

function Next()
    if #state.stories == 0 then return end
    state.index = state.index % #state.stories + 1
    state.tick = 0
    renderStory()
    SKIN:Bang('!Redraw')
end

function Previous()
    if #state.stories == 0 then return end
    state.index = (state.index - 2) % #state.stories + 1
    state.tick = 0
    renderStory()
    SKIN:Bang('!Redraw')
end

function Pause(paused)
    state.paused = paused
end
