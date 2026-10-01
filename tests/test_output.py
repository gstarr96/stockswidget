from __future__ import annotations

import json

from stocknews.market import PriceSeries
from stocknews.output import clean_text, safe_url, series_to_dict, write_json_atomic


def test_clean_text_converts_to_ascii_and_collapses_whitespace():
    text = "Apple\u2019s \u201cbig\u201d  day \u2014 shares\u2026\n up \u00e9"

    assert clean_text(text, 100) == 'Apple\'s "big" day - shares... up e'


def test_clean_text_truncates_on_word_boundary():
    assert clean_text("one two three four", 12) == "one two..."


def test_safe_url_rejects_non_http_and_unsafe_characters():
    assert safe_url("https://example.com/a?b=1#frag") == "https://example.com/a?b=1"
    assert safe_url("javascript:alert(1)") == ""
    assert safe_url('https://example.com/"][!Quit]') == ""
    assert safe_url("") == ""


def test_series_to_dict_formats_prices_and_direction():
    series = PriceSeries("AAPL", "Apple", 1234.5, 1250.0, (1250.0, 1240.0, 1234.5))

    data = series_to_dict(series, symbol="AAPL", name="Apple", max_points=10)

    assert data["priceText"] == "1,234.50"
    assert data["changeText"] == "-15.50 (-1.24%)"
    assert data["changePctText"] == "-1.24%"
    assert data["changePointsText"] == "-15.50"
    assert data["direction"] == "down"
    assert data["points"][0] == 1.0 and data["points"][-1] == 0.0


def test_series_to_dict_placeholder_when_unavailable():
    data = series_to_dict(None, symbol="^DJI", name="Dow Jones", max_points=10)

    assert data["available"] is False
    assert data["priceText"] == "--"
    assert data["points"] == []


def test_write_json_atomic_writes_ascii_and_leaves_no_temp_file(tmp_path):
    target = tmp_path / "data" / "widget.json"

    write_json_atomic(target, {"text": "caf\u00e9"})

    assert json.loads(target.read_text(encoding="ascii")) == {"text": "caf\u00e9"}
    assert list(target.parent.iterdir()) == [target]
