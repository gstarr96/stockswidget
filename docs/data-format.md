# `widget.json` data format

The Python backend writes `Skins/AIStockNews/@Resources/data/widget.json` on every
refresh, and `Scripts/Widget.lua` reads it. This file is the only contract between
the two halves. Text fields contain ASCII only, which keeps Rainmeter's Lua bridge
simple and reliable.

When you make a breaking change, bump `SCHEMA_VERSION` in `stocknews/output.py` and
update `Widget.lua` in the same pull request.

```jsonc
{
  "schemaVersion": 1,
  "status": "ok",                      // "ok" | "warning" | "error" | "setup"
  "statusText": "Updated 3:05 PM",     // shown in the widget's top-right corner
  "message": "",                       // details: shown as a tooltip, or in the story area when there are no stories
  "generatedAt": "2026-09-24T22:05:00+00:00",
  "stories": [
    {
      "ticker": "NVDA",
      "company": "Nvidia",
      "headline": "Nvidia jumps on record data-center sales",
      "summary": "Two or three sentences from the AI's web research on why it moved.",
      "sentiment": "positive",         // "positive" | "negative" | "neutral"
      "source": "Reuters",
      "url": "https://...",            // a URL from the AI's search results, or ""
      "chart": { /* Series, or null when prices were unavailable */ }
    }
  ],
  "indices": [ /* exactly three Series: S&P 500, Dow Jones, Nasdaq */ ]
}
```

## Series

```jsonc
{
  "symbol": "^GSPC",
  "name": "S&P 500",
  "available": true,                   // false: placeholder with priceText "--"
  "price": 5712.34,
  "priceText": "5,712.34",
  "changeText": "+21.50 (+0.38%)",
  "changePctText": "+0.38%",
  "changePointsText": "+21.50",
  "direction": "up",                   // "up" | "down" | "flat"
  "points": [0.0, 0.12, 0.5, 1.0],     // intraday closes scaled to 0..1 (1 = day's high)
  "baseline": 0.31                     // previous close on the same scale, or null if off-chart
}
```

## `watchlist.json`

The Watchlist skin reads `data/watchlist.json`, written by `run.py --tracker` and read
by `Scripts/Watchlist.lua`. It holds one Series per ticker in `[tracker] tickers`, in
the same order. The AI is never involved.

```jsonc
{
  "schemaVersion": 1,
  "status": "ok",                      // "ok" | "warning" | "error"
  "statusText": "Updated 3:05 PM",
  "message": "",                       // e.g. "Yahoo Finance has no stock called ZZZZ."
  "generatedAt": "2026-09-24T22:05:00+00:00",
  "tiles": [ /* Series, up to 12 */ ]
}
```

## Status values

| Status    | Meaning                                                                   |
| --------- | ------------------------------------------------------------------------- |
| `ok`      | Everything refreshed.                                                     |
| `warning` | Partial data: some stocks couldn't be researched, so older explanations are shown. In the watchlist: a ticker couldn't be added, or has no price data right now. |
| `error`   | The refresh failed. The previous stories and indices are kept on screen.  |
| `setup`   | The AI key is missing. Indices still load because they need no key.       |
