"""Command-line entry point. The skin runs this every few minutes via RunCommand."""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path

from . import __version__, pipeline, tracker
from .config import Paths, ensure_config_file, load_settings
from .errors import StockNewsError
from .market import YahooFinanceClient
from .output import build_payload, read_json, write_json_atomic

log = logging.getLogger("stocknews")


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    paths = Paths.create(resources=args.resources, config_dir=args.config_dir)
    log_file = paths.tracker_log_file if args.tracker else paths.log_file
    _configure_logging(log_file, verbose=args.verbose)

    if args.edit_config:
        _open_in_editor(ensure_config_file(paths))
        return 0
    if args.tracker:
        return _run_tracker(paths, args)

    try:
        settings = load_settings(paths)
        services = pipeline.Services.from_settings(settings)
        payload = pipeline.run(settings, paths, services, force_summaries=args.force)
    except StockNewsError as exc:
        log.error("%s", exc)
        _write_failure(paths, str(exc))
        print(exc)
        return 1
    except Exception:
        log.exception("Unexpected error")
        message = f"Unexpected error. Details are in {paths.log_file}."
        _write_failure(paths, message)
        print(message)
        return 1

    write_json_atomic(paths.output_file, payload)
    log.info("%s: %d stories", payload["statusText"], len(payload["stories"]))
    if args.print:
        print(json.dumps(payload, indent=2))
    return 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="stocknews", description="Refresh data for the AI Stock News Rainmeter widget."
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument(
        "--force", action="store_true", help="regenerate AI summaries even if the cache is fresh"
    )
    parser.add_argument(
        "--edit-config", action="store_true", help="open config.ini (created if missing) and exit"
    )
    parser.add_argument(
        "--tracker", action="store_true", help="refresh the Watchlist skin instead (no AI calls)"
    )
    parser.add_argument(
        "--add", metavar="TICKERS", help="with --tracker: add comma-separated tickers"
    )
    parser.add_argument(
        "--remove", metavar="TICKERS", help="with --tracker: remove comma-separated tickers"
    )
    parser.add_argument("--print", action="store_true", help="print the generated widget data")
    parser.add_argument("--verbose", "-v", action="store_true", help="log debug output to stderr")
    parser.add_argument("--resources", type=Path, help="override the skin's @Resources folder")
    parser.add_argument("--config-dir", type=Path, help="override the folder holding config.ini")
    args = parser.parse_args(argv)
    if (args.add or args.remove) and not args.tracker:
        parser.error("--add and --remove require --tracker")
    return args


def _run_tracker(paths: Paths, args: argparse.Namespace) -> int:
    code = 0
    try:
        settings = load_settings(paths)
        market = YahooFinanceClient(interval=settings.chart_interval)
        notes: list[str] = []
        if args.add:
            settings, notes = tracker.add_tickers(paths, settings, market, args.add)
        if args.remove:
            settings = tracker.remove_tickers(paths, settings, args.remove)
        payload = tracker.build_tracker_payload(settings, market, notes=notes)
    except StockNewsError as exc:
        log.error("%s", exc)
        payload, code = tracker.failure_payload(paths, str(exc)), 1
    except Exception:
        log.exception("Unexpected error")
        message = f"Unexpected error. Details are in {paths.tracker_log_file}."
        payload, code = tracker.failure_payload(paths, message), 1

    write_json_atomic(paths.tracker_file, payload)
    if code:
        print(payload["message"])
    else:
        log.info("%s: %d tiles", payload["statusText"], len(payload["tiles"]))
    if args.print:
        print(json.dumps(payload, indent=2))
    return code


def _configure_logging(log_file: Path, *, verbose: bool) -> None:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    handlers: list[logging.Handler] = [
        RotatingFileHandler(log_file, maxBytes=256_000, backupCount=1, encoding="utf-8")
    ]
    if verbose:
        handlers.append(logging.StreamHandler())
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
        force=True,
    )


def _write_failure(paths: Paths, message: str) -> None:
    """Record the error while keeping the last good stories on screen."""
    previous = read_json(paths.output_file)
    if not isinstance(previous, dict):
        previous = {}
    payload = build_payload(
        status="error",
        status_text="Update failed (hover for details)",
        message=message,
        stories=previous.get("stories") or [],
        indices=previous.get("indices") or [],
        generated_at=datetime.now(timezone.utc),
    )
    try:
        write_json_atomic(paths.output_file, payload)
    except OSError:
        log.exception("Could not write %s", paths.output_file)


def _open_in_editor(path: Path) -> None:
    if sys.platform == "win32":
        os.startfile(path)  # type: ignore[attr-defined]
    else:
        opener = "open" if sys.platform == "darwin" else "xdg-open"
        subprocess.run([opener, str(path)], check=False)
