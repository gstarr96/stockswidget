"""File locations and user settings.

User settings (including API keys) live outside the skin folder, in
%APPDATA%\\AIStockNewsWidget\\config.ini, so they survive skin upgrades and are
never shipped when someone shares or packages the skin.
"""

from __future__ import annotations

import configparser
import os
import re
import shutil
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

from .errors import ConfigError
from .market import normalize_ticker

APP_DIR_NAME = "AIStockNewsWidget"
PROVIDER_LABELS = {"openai": "OpenAI", "anthropic": "Anthropic"}
CHART_INTERVALS = ("1m", "2m", "5m", "15m", "30m")
DEFAULT_TRACKER_TICKERS = ("AAPL", "NFLX", "PLTR", "SPCX", "NVDA")
# The Watchlist skin has a fixed number of tiles; keep in sync with WatchMaxTiles.
MAX_TRACKER_TICKERS = 12


def default_config_dir(environ: Mapping[str, str] | None = None) -> Path:
    environ = os.environ if environ is None else environ
    override = environ.get("STOCKNEWS_CONFIG_DIR")
    if override:
        return Path(override)
    appdata = environ.get("APPDATA")
    if appdata:
        return Path(appdata) / APP_DIR_NAME
    return Path.home() / ".config" / APP_DIR_NAME


@dataclass(frozen=True)
class Paths:
    resources: Path
    config_dir: Path

    @classmethod
    def create(cls, resources: Path | None = None, config_dir: Path | None = None) -> Paths:
        return cls(
            resources=resources or Path(__file__).resolve().parents[2],
            config_dir=config_dir or default_config_dir(),
        )

    @property
    def config_file(self) -> Path:
        return self.config_dir / "config.ini"

    @property
    def example_config(self) -> Path:
        return self.resources / "config.example.ini"

    @property
    def data_dir(self) -> Path:
        return self.resources / "data"

    @property
    def output_file(self) -> Path:
        return self.data_dir / "widget.json"

    @property
    def summary_cache(self) -> Path:
        return self.data_dir / "summaries.json"

    @property
    def log_file(self) -> Path:
        return self.data_dir / "stocknews.log"

    @property
    def tracker_file(self) -> Path:
        return self.data_dir / "watchlist.json"

    @property
    def tracker_log_file(self) -> Path:
        return self.data_dir / "watchlist.log"


@dataclass(frozen=True)
class Settings:
    ai_provider: str = "openai"
    openai_api_key: str = ""
    openai_model: str = "gpt-5-mini"
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-haiku-4-5"
    story_count: int = 5
    schedule: str = "close"
    summary_refresh_minutes: int = 120
    watchlist: tuple[str, ...] = ()
    chart_interval: str = "5m"
    tracker_tickers: tuple[str, ...] = DEFAULT_TRACKER_TICKERS

    @property
    def provider_label(self) -> str:
        return PROVIDER_LABELS[self.ai_provider]

    @property
    def ai_api_key(self) -> str:
        return self.openai_api_key if self.ai_provider == "openai" else self.anthropic_api_key

    @property
    def ai_model(self) -> str:
        return self.openai_model if self.ai_provider == "openai" else self.anthropic_model

    def missing_keys(self) -> list[str]:
        """Human-readable names of the API keys that still need to be filled in."""
        return [] if self.ai_api_key else [f"{self.provider_label} API key"]


def ensure_config_file(paths: Paths) -> Path:
    """Create config.ini from the bundled example on first run."""
    if not paths.config_file.exists():
        paths.config_dir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(paths.example_config, paths.config_file)
    return paths.config_file


def load_settings(paths: Paths, environ: Mapping[str, str] | None = None) -> Settings:
    """Read config.ini. Blank API keys fall back to the usual environment variables."""
    environ = os.environ if environ is None else environ
    ensure_config_file(paths)

    parser = configparser.ConfigParser(interpolation=None)
    try:
        parser.read(paths.config_file, encoding="utf-8-sig")
    except configparser.Error as exc:
        raise ConfigError(f"{paths.config_file} could not be read: {exc}") from exc

    def text(section: str, key: str, default: str = "", env: str | None = None) -> str:
        value = parser.get(section, key, fallback="").strip()
        if not value and env:
            value = environ.get(env, "").strip()
        return value or default

    defaults = Settings()
    provider = text("ai", "provider", defaults.ai_provider).lower()
    if provider not in PROVIDER_LABELS:
        choices = ", ".join(PROVIDER_LABELS)
        raise ConfigError(f"Unknown AI provider '{provider}' in config.ini. Use one of: {choices}.")

    interval = text("charts", "interval", defaults.chart_interval)
    if interval not in CHART_INTERVALS:
        choices = ", ".join(CHART_INTERVALS)
        raise ConfigError(
            f"Unknown chart interval '{interval}' in config.ini. Use one of: {choices}."
        )

    return Settings(
        ai_provider=provider,
        openai_api_key=text("ai", "openai_api_key", env="OPENAI_API_KEY"),
        openai_model=text("ai", "openai_model", defaults.openai_model),
        anthropic_api_key=text("ai", "anthropic_api_key", env="ANTHROPIC_API_KEY"),
        anthropic_model=text("ai", "anthropic_model", defaults.anthropic_model),
        story_count=_integer(parser, "stocks", "count", defaults.story_count, 1, 10),
        schedule=_schedule(text("ai", "schedule", defaults.schedule)),
        summary_refresh_minutes=_integer(
            parser, "ai", "summary_refresh_minutes", defaults.summary_refresh_minutes, 5, 1440
        ),
        watchlist=_ticker_list(text("stocks", "watchlist"), "[stocks] watchlist"),
        chart_interval=interval,
        tracker_tickers=_tracker_tickers(parser),
    )


def save_tracker_tickers(paths: Paths, tickers: Iterable[str]) -> None:
    """Rewrite only the [tracker] tickers line so the user's comments and keys survive."""
    ensure_config_file(paths)
    raw = paths.config_file.read_bytes()
    newline = "\r\n" if b"\r\n" in raw else "\n"
    text = raw.decode("utf-8-sig").replace("\r\n", "\n")
    line = "tickers = " + ", ".join(tickers)

    section = re.search(r"(?ms)^\[tracker\][^\n]*\n?(.*?)(?=^\[|\Z)", text)
    if section is None:
        text = text.rstrip("\n") + f"\n\n[tracker]\n{line}\n"
    else:
        body = section.group(1)
        key = re.compile(r"(?im)^[ \t]*tickers[ \t]*[=:].*$")
        body = key.sub(lambda _: line, body, count=1) if key.search(body) else f"{line}\n{body}"
        text = text[: section.start(1)] + body + text[section.end(1) :]

    temp = paths.config_file.with_name(paths.config_file.name + ".tmp")
    with open(temp, "w", encoding="utf-8", newline=newline) as handle:
        handle.write(text)
    os.replace(temp, paths.config_file)


def _tracker_tickers(parser: configparser.ConfigParser) -> tuple[str, ...]:
    if not parser.has_option("tracker", "tickers"):
        return DEFAULT_TRACKER_TICKERS
    tickers = _ticker_list(parser.get("tracker", "tickers"), "[tracker] tickers")
    if len(tickers) > MAX_TRACKER_TICKERS:
        raise ConfigError(
            f"[tracker] tickers in config.ini can list at most {MAX_TRACKER_TICKERS} stocks."
        )
    return tickers


def _schedule(raw: str) -> str:
    schedule = raw.lower()
    if schedule not in ("close", "interval"):
        raise ConfigError("[ai] schedule in config.ini must be 'close' or 'interval'.")
    return schedule


def _ticker_list(raw: str, setting: str) -> tuple[str, ...]:
    symbols: list[str] = []
    for entry in raw.replace(";", ",").split(","):
        if not entry.strip():
            continue
        symbol = normalize_ticker(entry)
        if not symbol:
            raise ConfigError(f"'{entry.strip()}' in {setting} is not a valid ticker.")
        if symbol not in symbols:
            symbols.append(symbol)
    return tuple(symbols)


def _integer(
    parser: configparser.ConfigParser,
    section: str,
    key: str,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    raw = parser.get(section, key, fallback="").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigError(f"[{section}] {key} in config.ini must be a whole number.") from exc
    if not minimum <= value <= maximum:
        raise ConfigError(
            f"[{section}] {key} in config.ini must be between {minimum} and {maximum}."
        )
    return value
