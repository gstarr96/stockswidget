from __future__ import annotations

import pytest

from stocknews.config import Settings, default_config_dir, load_settings
from stocknews.errors import ConfigError


def write_config(paths, text: str) -> None:
    paths.config_dir.mkdir(parents=True, exist_ok=True)
    paths.config_file.write_text(text, encoding="utf-8")


def test_first_run_creates_config_from_example(paths):
    settings = load_settings(paths, environ={})

    assert paths.config_file.exists()
    assert settings == Settings()


def test_only_the_selected_providers_key_is_required():
    assert Settings(ai_provider="anthropic", openai_api_key="sk").missing_keys() == [
        "Anthropic API key"
    ]
    assert Settings(openai_api_key="sk").missing_keys() == []


def test_values_are_read_from_config(paths):
    write_config(
        paths,
        "[stocks]\nwatchlist = aapl, BRK.B; nvda, AAPL\ncount = 3\n"
        "[ai]\nprovider = Anthropic\nanthropic_api_key = ak-123\n"
        "[charts]\ninterval = 15m\n",
    )

    settings = load_settings(paths, environ={})

    assert settings.watchlist == ("AAPL", "BRK-B", "NVDA")
    assert settings.story_count == 3
    assert settings.ai_provider == "anthropic"
    assert settings.ai_api_key == "ak-123"
    assert settings.ai_model == "claude-haiku-4-5"
    assert settings.chart_interval == "15m"


def test_blank_key_falls_back_to_environment(paths):
    write_config(paths, "[ai]\nopenai_api_key =\n")

    settings = load_settings(paths, environ={"OPENAI_API_KEY": "sk-env"})

    assert settings.openai_api_key == "sk-env"


@pytest.mark.parametrize(
    "text",
    [
        "[ai]\nprovider = gemini\n",
        "[stocks]\ncount = many\n",
        "[stocks]\ncount = 50\n",
        "[stocks]\nwatchlist = AAPL, not a ticker\n",
        "[charts]\ninterval = 1h\n",
        "[ai]\nschedule = hourly\n",
    ],
)
def test_invalid_values_raise_config_error(paths, text):
    write_config(paths, text)

    with pytest.raises(ConfigError):
        load_settings(paths, environ={})


def test_config_dir_prefers_override_then_appdata(tmp_path):
    assert default_config_dir({"STOCKNEWS_CONFIG_DIR": str(tmp_path)}) == tmp_path
    assert default_config_dir({"APPDATA": str(tmp_path)}) == tmp_path / "AIStockNewsWidget"
