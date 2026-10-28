# -*- coding: utf-8 -*-
"""Build a signed v2 app package (``vse-app-<version>.vsepkg``) from this repository.

    python tools/release.py app --version 2.0.1 --key D:\\keys\\vse-plugin-signing.pem \\
        --notes "首页加载更快" [--migration 0007_add_x] [--out dist/releases]

The package holds every file the app version needs (``core/ services/ host/
web/ plugins/ webui.py tools/excel_worker_cli.py``); it is a full package, not a
diff (architecture §4.1, review R1). The build fails when the package exceeds
the size budget, which keeps it small enough to send over chat tools.
The private key stays on the build machine; never commit or send it.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path, PurePosixPath

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from vse_boot.packages import TARGET_RUNTIME_TAG, build_app_package  # noqa: E402

APP_DIRS = ("core", "services", "host", "web", "plugins")
APP_FILES = ("webui.py", "tools/excel_worker_cli.py")
SKIP_PARTS = frozenset({"__pycache__", ".pytest_cache", ".mypy_cache", "tests"})
SKIP_SUFFIXES = frozenset({".pyc", ".pyo", ".log", ".db"})
DEFAULT_BUDGET_MB = 8.0


def collect_app_files(repo_root: Path = REPO_ROOT) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    for name in APP_DIRS:
        base = repo_root / name
        if not base.is_dir():
            raise FileNotFoundError(f"缺少目录 {name}/")
        for path in sorted(base.rglob("*")):
            if not path.is_file() or path.suffix in SKIP_SUFFIXES:
                continue
            relative = path.relative_to(repo_root).as_posix()
            if any(part in SKIP_PARTS for part in PurePosixPath(relative).parts):
                continue
            files[relative] = path.read_bytes()
    for name in APP_FILES:
        path = repo_root / name
        if not path.is_file():
            raise FileNotFoundError(f"缺少文件 {name}")
        files[name] = path.read_bytes()
    return files


def build_app(
    *,
    version: str,
    key_pem: bytes,
    notes: str = "",
    migrations: tuple[str, ...] = (),
    out_dir: Path,
    budget_mb: float = DEFAULT_BUDGET_MB,
    repo_root: Path = REPO_ROOT,
    runtime_tag: str = TARGET_RUNTIME_TAG,
) -> Path:
    files = collect_app_files(repo_root)
    name, data = build_app_package(
        files, version=version, private_key_pem=key_pem, notes=notes, migrations=migrations, runtime_tag=runtime_tag
    )
    size_mb = len(data) / (1024 * 1024)
    if size_mb > budget_mb:
        raise SystemExit(f"包大小 {size_mb:.2f} MB 超过上限 {budget_mb} MB，请检查是否误收了大文件")
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / name
    target.write_bytes(data)
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="release", description="构建签名的 v2 程序更新包")
    sub = parser.add_subparsers(dest="kind", required=True)
    app = sub.add_parser("app", help="程序（core/services/host/web/plugins）全量包")
    app.add_argument("--version", required=True)
    app.add_argument("--key", required=True, help="Ed25519 私钥 PEM（只放在打包机）")
    app.add_argument("--notes", default="", help="给用户看的更新说明")
    app.add_argument("--migration", action="append", default=[], help="本版本包含的数据库迁移名（会触发迁移前快照）")
    app.add_argument("--out", default=str(REPO_ROOT / "dist" / "releases"))
    app.add_argument("--budget-mb", type=float, default=DEFAULT_BUDGET_MB)
    args = parser.parse_args(argv)
    target = build_app(
        version=args.version,
        key_pem=Path(args.key).read_bytes(),
        notes=args.notes,
        migrations=tuple(args.migration),
        out_dir=Path(args.out),
        budget_mb=args.budget_mb,
    )
    print(f"{target}  ({target.stat().st_size / 1024:.0f} KB, runtime {TARGET_RUNTIME_TAG})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
