"""Local-only command line entry point for the Excel task worker."""

from __future__ import annotations

import argparse
import json
import re
import signal
import sys
import threading
from pathlib import Path
from typing import Any, Sequence

# Allow `python tools/excel_worker_cli.py ...` as well as `python -m ...`.
if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.db_manager import DatabaseManager  # noqa: E402
from core.excel_tasks import (
    DEFAULT_LEASE_SECONDS,
    LEASE_MAX_SECONDS,
    LEASE_MIN_SECONDS,
    ApprovedExcelRoots,
    ExcelTaskRepository,
)  # noqa: E402
from core.excel_worker import ExcelTaskRunStatus, ExcelTaskWorker  # noqa: E402
from core.redaction import redact_sensitive_text  # noqa: E402

EXIT_OK = 0
EXIT_TASK_FAILED = 1
EXIT_CONFIG_ERROR = 2


class ExcelWorkerConfigError(ValueError):
    """Invalid local worker CLI configuration."""


def parse_root_spec(value: str) -> tuple[str, Path]:
    root_id, separator, path_text = value.partition("=")
    if not separator or not root_id.strip() or not path_text.strip():
        raise ExcelWorkerConfigError("--root must use ROOT_ID=PATH")
    try:
        canonical_id = ApprovedExcelRoots.canonicalize_root_id(root_id.strip())
    except ValueError as exc:
        raise ExcelWorkerConfigError(f"invalid root id: {exc}") from exc
    return canonical_id, Path(path_text.strip()).expanduser().absolute()


def validate_numeric_args(lease_seconds: int, renew_interval_seconds: float | None, poll_interval_seconds: float) -> None:
    if not isinstance(lease_seconds, int) or isinstance(lease_seconds, bool) or not LEASE_MIN_SECONDS <= lease_seconds <= LEASE_MAX_SECONDS:
        raise ExcelWorkerConfigError(f"--lease-seconds must be between {LEASE_MIN_SECONDS} and {LEASE_MAX_SECONDS}")
    if renew_interval_seconds is not None and (
        not isinstance(renew_interval_seconds, (int, float))
        or isinstance(renew_interval_seconds, bool)
        or renew_interval_seconds <= 0
        or renew_interval_seconds >= lease_seconds
    ):
        raise ExcelWorkerConfigError("--renew-interval-seconds must be positive and less than --lease-seconds")
    if not isinstance(poll_interval_seconds, (int, float)) or isinstance(poll_interval_seconds, bool) or poll_interval_seconds < 0:
        raise ExcelWorkerConfigError("--poll-interval-seconds must be non-negative")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="excel_worker_cli", description="Run the local Excel task worker")
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_common_options(subparser: argparse.ArgumentParser) -> None:
        subparser.add_argument("--db", required=True, type=Path)
        subparser.add_argument("--root", action="append", dest="roots", required=True, metavar="ID=PATH")
        subparser.add_argument("--lease-seconds", type=int, default=DEFAULT_LEASE_SECONDS)
        subparser.add_argument("--renew-interval-seconds", type=float, default=None)
        subparser.add_argument("--poll-interval-seconds", type=float, default=0.1)
        subparser.add_argument("--json", action=argparse.BooleanOptionalAction, default=True)
        subparser.add_argument("--stop-file", type=Path, default=None, help=argparse.SUPPRESS)

    add_common_options(subparsers.add_parser("run-once", help="Process at most one task"))
    add_common_options(subparsers.add_parser("run", help="Poll until interrupted"))
    return parser


def _build_worker(args: argparse.Namespace) -> tuple[ExcelTaskWorker, ExcelTaskRepository]:
    roots_map: dict[str, Path] = {}
    for spec in args.roots:
        root_id, path = parse_root_spec(spec)
        if root_id in roots_map:
            raise ExcelWorkerConfigError(f"duplicate root id: {root_id!r}")
        if not path.exists() or not path.is_dir():
            raise ExcelWorkerConfigError(f"approved root directory does not exist for root id {root_id!r}")
        roots_map[root_id] = path

    validate_numeric_args(args.lease_seconds, args.renew_interval_seconds, args.poll_interval_seconds)
    db_path = args.db.expanduser().absolute()
    if db_path.exists() and db_path.is_dir():
        raise ExcelWorkerConfigError("--db must be a file path, not a directory")
    if not db_path.parent.exists() or not db_path.parent.is_dir():
        raise ExcelWorkerConfigError("database parent directory does not exist")

    roots = ApprovedExcelRoots(roots_map)
    database = DatabaseManager(db_path=db_path)
    database.init_database()
    repository = ExcelTaskRepository(database, roots)
    worker = ExcelTaskWorker(repository, lease_seconds=args.lease_seconds, renew_interval_seconds=args.renew_interval_seconds, poll_interval_seconds=args.poll_interval_seconds)
    return worker, repository


def _emit(payload: dict[str, Any], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        print(" ".join(f"{key}={value}" for key, value in payload.items()))


def _safe_task_error_message(message: str, repository: ExcelTaskRepository) -> str:
    safe = redact_sensitive_text(message, limit=1000)
    roots = getattr(repository, "roots", None)
    if roots is None:
        return safe
    for root_id in roots.root_ids:
        root_text = str(roots.get_root(root_id))
        replacement = f"<approved-root:{root_id}>"
        safe = re.sub(re.escape(root_text), replacement, safe, flags=re.IGNORECASE)
        safe = re.sub(
            re.escape(root_text.replace("\\", "/")),
            replacement,
            safe,
            flags=re.IGNORECASE,
        )
    return safe


class _StopSignalHandlers:
    """Translate process stop signals into a worker stop event."""

    def __init__(self, stop_event: threading.Event) -> None:
        self._stop_event = stop_event
        self._previous: dict[signal.Signals, Any] = {}

    def __enter__(self) -> _StopSignalHandlers:
        if threading.current_thread() is not threading.main_thread():
            return self
        for name in ("SIGINT", "SIGTERM", "SIGBREAK"):
            signum = getattr(signal, name, None)
            if signum is None:
                continue
            self._previous[signum] = signal.getsignal(signum)
            signal.signal(signum, self._handle)
        return self

    def _handle(self, signum: int, frame: Any) -> None:
        self._stop_event.set()

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        for signum, previous in self._previous.items():
            signal.signal(signum, previous)


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
        worker, repository = _build_worker(args)
        if args.command == "run-once":
            result = worker.run_once()
            payload = {
                "command": args.command,
                "completed": result.processed,
                "succeeded": result.succeeded,
                "status": result.status.value,
                "task_id": result.task_id,
                "output_committed": result.output_committed,
            }
            if result.error_type:
                payload["error_type"] = redact_sensitive_text(result.error_type, limit=200)
            if result.error_message:
                payload["error_message"] = _safe_task_error_message(
                    result.error_message,
                    repository,
                )
            _emit(payload, as_json=args.json)
            return (
                EXIT_OK
                if result.status in {ExcelTaskRunStatus.IDLE, ExcelTaskRunStatus.SUCCEEDED}
                else EXIT_TASK_FAILED
            )

        stop_event = threading.Event()
        watcher_stop = threading.Event()
        watcher: threading.Thread | None = None
        if args.stop_file is not None:
            def watch_stop_file() -> None:
                while not watcher_stop.wait(0.1):
                    if args.stop_file.exists():
                        stop_event.set()
                        return
            watcher = threading.Thread(target=watch_stop_file, name="excel-worker-stop-file", daemon=True)
            watcher.start()
        with _StopSignalHandlers(stop_event):
            summary = worker.run(stop_event=stop_event)
        watcher_stop.set()
        if watcher is not None:
            watcher.join(timeout=1.0)
        _emit(
            {
                "command": args.command,
                "processed": summary.processed,
                "succeeded": summary.succeeded,
                "failed": summary.failed,
                "lease_lost": summary.lease_lost,
                "stopped": stop_event.is_set(),
            },
            as_json=args.json,
        )
        return EXIT_OK
    except KeyboardInterrupt:
        _emit({"command": "run", "completed": 0, "stopped": True}, as_json=True)
        return EXIT_OK
    except (OSError, ValueError) as exc:
        print(f"excel worker configuration error: {exc}", file=sys.stderr)
        return EXIT_CONFIG_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
