# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.2.0] - 2026-10-01

### Added

- Watchlist skin (`AIStockNews\Watchlist`): a grid of tiles for your own tickers, each
  with live price, % change, point change and an intraday chart in the background.
  It starts with AAPL, NFLX, PLTR, SPCX (SpaceX) and NVDA. Add stocks with the **+**
  button and remove them with the **x** on a tile. The list is saved in the `[tracker]`
  section of `config.ini`. Prices refresh every minute from Yahoo Finance with no AI
  calls.
- Index cards in the news widget show the point change under the % change.

## [0.1.0] - 2026-09-24

### Added

- Rainmeter skin with a "why did it move?" carousel, per-story intraday chart, and
  S&P 500, Dow Jones and Nasdaq index cards.
- Python backend (standard library only). It picks the day's biggest movers (or a
  watchlist) and fetches prices from Yahoo Finance. It then has OpenAI or Anthropic
  explain each move using their built-in web search tools.
- Per-stock research cache. The default researches each stock once, after the US
  market closes. Set `schedule = interval` to research during the session.
- Settings stored in `%APPDATA%\AIStockNewsWidget\config.ini`, outside the skin folder.
- Test suite, lint configuration, CI, and `.rmskin` packaging script.
