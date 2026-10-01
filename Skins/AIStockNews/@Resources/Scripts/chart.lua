-- Draws an intraday chart into a Shape meter that uses StyleChart.
-- Shared by Widget.lua and Watchlist.lua; load it with dofile.
--
-- chart.draw(skin, meter, series, width, height, colors, style)
--   series: a chart object from the backend ({ points, baseline, direction }) or nil
--   colors: { up, down, flat } as "R,G,B" strings
--   style (optional): top (offset in px), padding, lineWidth, lineAlpha, areaAlpha

local chart = {}

local function fmt(n)
    return string.format('%.1f', n)
end

function chart.draw(skin, meter, series, width, height, colors, style)
    style = style or {}
    local function option(name, value)
        skin:Bang('!SetOption', meter, name, value)
    end

    local top = style.top or 0
    local padding = style.padding or 3
    local usable = height - top - 2 * padding
    local points = type(series) == 'table' and series.points or nil
    local color = colors[type(series) == 'table' and series.direction or 'flat'] or colors.flat
    local line, area, areaAlpha

    if type(points) == 'table' and #points >= 2 then
        local coords = {}
        for i, value in ipairs(points) do
            local x = (i - 1) / (#points - 1) * width
            local y = top + padding + (1 - value) * usable
            coords[i] = fmt(x) .. ',' .. fmt(y)
        end
        line = table.concat(coords, ' | LineTo ')
        area = line .. ' | LineTo ' .. fmt(width) .. ',' .. fmt(height)
            .. ' | LineTo 0,' .. fmt(height) .. ' | ClosePath 1'
        areaAlpha = style.areaAlpha or 80
    else
        local middle = fmt(top + (height - top) / 2)
        line = '0,' .. middle .. ' | LineTo ' .. fmt(width) .. ',' .. middle
        area = line
        areaAlpha = 0
        color = colors.flat
    end

    option('LinePath', line)
    option('AreaPath', area)
    option('AreaGradient', '90 | ' .. color .. ',' .. areaAlpha .. ' ; 0.0 | ' .. color .. ',0 ; 1.0')
    option('Shape2', 'Path AreaPath | StrokeWidth 0 | Fill LinearGradient AreaGradient')
    option('Shape3', 'Path LinePath | StrokeWidth ' .. (style.lineWidth or 1.5)
        .. ' | Stroke Color ' .. color .. ',' .. (style.lineAlpha or 255)
        .. ' | Fill Color 0,0,0,0 | StrokeLineJoin Round')

    local baseline = type(series) == 'table' and tonumber(series.baseline) or nil
    if baseline then
        local y = fmt(top + padding + (1 - baseline) * usable)
        option('Shape4', 'Line 0,' .. y .. ',' .. fmt(width) .. ',' .. y
            .. ' | StrokeWidth 1 | Stroke Color ' .. colors.flat .. ',120 | StrokeDashes 2,3')
    else
        option('Shape4', 'Line 0,0,0,0 | StrokeWidth 0 | Stroke Color 0,0,0,0')
    end
end

return chart
