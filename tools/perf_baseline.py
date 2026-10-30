# -*- coding: utf-8 -*-
"""tools/perf_baseline.py — 无副作用性能基准脚本。

本脚本为系统性能提供量化基线，作为重构前后（如 W18-03 复测）对比的权威数据源。
核心设计原则：
1. 零写入仓库：所有数据操作与 Flask 运行时均在操作系统临时目录执行，结束后自动彻底清理。
2. 隔离计时：
   - 模块冷加载耗时（import web.app）：在独立子进程中使用 importlib 计量，排除进程内模块缓存污染。
   - 工厂构建耗时（create_app）：计量扩展初始化、路由注册与依赖装配的净耗时。
3. 代表性路由测试：使用 Flask test_client 对首页与 3 个典型只读 GET 路由进行多轮压测，输出中位数与 p95。
4. 大表分页测量：在合成 SQLite 大表（不少于 5000 行）上计量 LIMIT/OFFSET 浅页与深页耗时。
5. 友好输出与容错：失败时输出结构化可读错误，输出纯净 JSON 摘要到 stdout，并支持 --out 写盘。
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import sqlite3
import statistics
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from typing import Any

ROOT_DIR = Path(__file__).resolve().parent.parent


def calculate_percentile(values: list[float], percentile_rank: float) -> float:
    """计算百分位数（0 <= percentile_rank <= 100），采用线性插值算法。
    
    采用与常见性能统计工具对齐的线性插值法，确保小样本与中等样本下 p95 均具有平滑稳定性。
    """
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    rank = (percentile_rank / 100.0) * (len(sorted_vals) - 1)
    low_idx = int(rank)
    high_idx = min(low_idx + 1, len(sorted_vals) - 1)
    weight = rank - low_idx
    return sorted_vals[low_idx] * (1.0 - weight) + sorted_vals[high_idx] * weight


def measure_import_time_subprocess(sandbox_dir: str) -> float:
    """在全新子进程中计量 import web.app 的冷加载耗时（毫秒）。
    
    使用独立子进程避免 Python 进程的 sys.modules 缓存对冷加载计量产生干扰。
    """
    code = (
        "import sys, os, time, importlib\n"
        "sys.path.insert(0, sys.argv[1])\n"
        "os.environ['VSE_DATA_ROOT'] = sys.argv[2]\n"
        "t0 = time.perf_counter()\n"
        "importlib.import_module('web.app')\n"
        "t1 = time.perf_counter()\n"
        "print(f'{(t1 - t0) * 1000:.3f}')\n"
    )
    cmd = [sys.executable, "-c", code, str(ROOT_DIR), sandbox_dir]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
        )
        return float(proc.stdout.strip())
    except subprocess.CalledProcessError as exc:
        err_msg = exc.stderr.strip() or exc.stdout.strip() or str(exc)
        raise RuntimeError(f"子进程导入 web.app 失败: {err_msg}") from exc


def measure_create_app_time() -> tuple[Any, float]:
    """计量 create_app() 构建耗时（毫秒），并返回创建的 Flask 应用实例。
    
    在导入前已通过环境变量指定沙箱根目录，确保应用工厂不会写向仓库内生产目录。
    """
    from web.app import create_app

    t0 = time.perf_counter()
    app = create_app()
    t1 = time.perf_counter()
    return app, (t1 - t0) * 1000.0


def benchmark_routes(
    app: Any,
    routes: list[tuple[str, str]],
    iterations: int,
) -> dict[str, dict[str, Any]]:
    """使用 Flask test_client 测试指定路由，输出每条路由的中位数与 p95（毫秒）。"""
    client = app.test_client()
    results: dict[str, dict[str, Any]] = {}

    for route_path, description in routes:
        # 先执行 1 次预热请求，排除一次性惰性加载开销
        warmup_resp = client.get(route_path)
        if warmup_resp.status_code != 200:
            raise RuntimeError(
                f"路由预热失败: [{route_path}] 返回状态码 {warmup_resp.status_code}"
            )

        durations_ms: list[float] = []
        for _ in range(iterations):
            start = time.perf_counter()
            resp = client.get(route_path)
            end = time.perf_counter()
            if resp.status_code != 200:
                raise RuntimeError(
                    f"路由请求失败: [{route_path}] 返回状态码 {resp.status_code}"
                )
            durations_ms.append((end - start) * 1000.0)

        results[route_path] = {
            "description": description,
            "status_code": 200,
            "samples": len(durations_ms),
            "median_ms": round(statistics.median(durations_ms), 3),
            "p95_ms": round(calculate_percentile(durations_ms, 95), 3),
            "min_ms": round(min(durations_ms), 3),
            "max_ms": round(max(durations_ms), 3),
        }

    return results


def benchmark_large_table_pagination(
    sandbox_dir: str,
    total_rows: int,
    iterations: int,
) -> dict[str, Any]:
    """在系统临时目录中构建合成大表，计量浅页与深页 LIMIT/OFFSET 分页耗时。"""
    db_path = Path(sandbox_dir) / "synthetic_pagination.db"
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute(
            """
            CREATE TABLE synthetic_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_code TEXT NOT NULL,
                title TEXT NOT NULL,
                department TEXT NOT NULL,
                stage TEXT NOT NULL,
                status TEXT NOT NULL,
                is_completed INTEGER NOT NULL,
                priority INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                details_json TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX idx_synthetic_sort ON synthetic_items (is_completed ASC, priority DESC, id ASC)"
        )

        # 批量合成插入不少于 total_rows 行数据
        batch_size = 1000
        for start_idx in range(1, total_rows + 1, batch_size):
            end_idx = min(start_idx + batch_size, total_rows + 1)
            chunk = [
                (
                    f"ITEM-{i:06d}",
                    f"合成性能基准测试条目-{i}",
                    f"部门-{(i % 6) + 1}",
                    f"阶段-{(i % 4) + 1}",
                    "已完成" if i % 2 == 0 else "进行中",
                    1 if i % 2 == 0 else 0,
                    i % 100,
                    "2026-10-31 12:00:00",
                    '{"synthetic": true, "metric_tag": "perf_test"}',
                )
                for i in range(start_idx, end_idx)
            ]
            conn.executemany(
                """
                INSERT INTO synthetic_items (
                    item_code, title, department, stage, status,
                    is_completed, priority, created_at, details_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                chunk,
            )
        conn.commit()

        page_size = 50
        shallow_offset = 0
        deep_offset = max(0, total_rows - page_size * 20)  # 例如 5000 行时第 81 页（OFFSET 4000）

        query_sql = (
            "SELECT id, item_code, title, department, stage, status, is_completed, priority "
            "FROM synthetic_items "
            "ORDER BY is_completed ASC, priority DESC, id ASC "
            "LIMIT ? OFFSET ?"
        )

        def measure_offset(offset: int) -> dict[str, Any]:
            # 预热 1 次
            conn.execute(query_sql, (page_size, offset)).fetchall()

            durations_ms: list[float] = []
            for _ in range(iterations):
                t0 = time.perf_counter()
                rows = conn.execute(query_sql, (page_size, offset)).fetchall()
                t1 = time.perf_counter()
                if len(rows) != page_size and offset + page_size <= total_rows:
                    raise RuntimeError(f"分页查询异常: 期望 {page_size} 行，实际得到 {len(rows)} 行")
                durations_ms.append((t1 - t0) * 1000.0)

            return {
                "offset": offset,
                "limit": page_size,
                "samples": len(durations_ms),
                "median_ms": round(statistics.median(durations_ms), 3),
                "p95_ms": round(calculate_percentile(durations_ms, 95), 3),
                "min_ms": round(min(durations_ms), 3),
                "max_ms": round(max(durations_ms), 3),
            }

        shallow_metrics = measure_offset(shallow_offset)
        deep_metrics = measure_offset(deep_offset)

        return {
            "total_rows": total_rows,
            "page_size": page_size,
            "iterations": iterations,
            "shallow_page": shallow_metrics,
            "deep_page": deep_metrics,
        }
    finally:
        conn.close()


def run_perf_baseline(
    quick: bool = False,
    custom_iterations: int | None = None,
    total_rows: int = 5000,
) -> dict[str, Any]:
    """执行全部基准测量任务，返回结构化结果字典。"""
    if custom_iterations is not None:
        iterations = max(1, custom_iterations)
    else:
        iterations = 10 if quick else 20

    sandbox_dir = tempfile.mkdtemp(prefix="vse_perf_baseline_")
    try:
        # 在加载任何业务代码前强制指向沙箱数据目录，阻断对仓库 data/ 的一切写入
        os.environ["VSE_DATA_ROOT"] = sandbox_dir
        if str(ROOT_DIR) not in sys.path:
            sys.path.insert(0, str(ROOT_DIR))

        # (1) 计量 import web.app 与 create_app()
        import_ms = measure_import_time_subprocess(sandbox_dir)
        app, create_app_ms = measure_create_app_time()

        # (2) 首页与 3 个代表性只读 GET 路由
        # 代表性路由选择：
        # - `/`: 核心首页模板渲染（Jinja2、前端外壳挂载点）
        # - `/api/version`: 纯内存配置与版本元数据序列化
        # - `/api/overview`: SQLite 核心聚合统计（多表聚合查询）
        # - `/api/settings`: 配置仓储及会话状态聚合查询
        representative_routes = [
            ("/", "首页渲染"),
            ("/api/version", "版本信息查询"),
            ("/api/overview", "全库概览统计"),
            ("/api/settings", "系统设置与状态"),
        ]
        route_metrics = benchmark_routes(app, representative_routes, iterations)

        # (3) 大表分页基准测试
        pagination_metrics = benchmark_large_table_pagination(
            sandbox_dir, total_rows=total_rows, iterations=iterations
        )

        return {
            "meta": {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "quick_mode": quick,
                "iterations": iterations,
                "python_version": sys.version.split()[0],
                "platform": sys.platform,
            },
            "startup": {
                "import_web_app_ms": round(import_ms, 3),
                "create_app_ms": round(create_app_ms, 3),
                "total_startup_ms": round(import_ms + create_app_ms, 3),
            },
            "routes": route_metrics,
            "large_table_pagination": pagination_metrics,
        }
    finally:
        shutil.rmtree(sandbox_dir, ignore_errors=True)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="VSE-Toolbox 无副作用性能基准脚本（零写入仓库，自动清理临时文件）"
    )
    parser.add_argument(
        "--quick",
        action="store_true",
        help="快速模式：测试轮数减半（默认 20 轮，快速模式 10 轮）",
    )
    parser.add_argument(
        "--rounds",
        type=int,
        default=None,
        help="显式指定请求测试轮数（覆盖默认值或 --quick 设置）",
    )
    parser.add_argument(
        "--db-rows",
        type=int,
        default=5000,
        help="合成大表测试行数（默认 5000 行，不得低于 5000）",
    )
    parser.add_argument(
        "--out",
        type=str,
        default=None,
        help="输出结果文件路径（例如 .runtime/perf-w18-01.json）",
    )
    args = parser.parse_args()

    if args.db_rows < 5000:
        sys.stderr.write("错误: --db-rows 参数不能少于 5000 行\n")
        sys.exit(2)

    try:
        report = run_perf_baseline(
            quick=args.quick,
            custom_iterations=args.rounds,
            total_rows=args.db_rows,
        )
    except Exception as exc:
        sys.stderr.write(f"性能基准测试失败: {exc}\n")
        sys.exit(1)

    output_json = json.dumps(report, indent=2, ensure_ascii=False)
    sys.stdout.write(output_json + "\n")

    if args.out:
        out_path = Path(args.out).resolve()
        try:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(output_json + "\n", encoding="utf-8")
        except OSError as exc:
            sys.stderr.write(f"写入输出文件失败 [{args.out}]: {exc}\n")
            sys.exit(1)


if __name__ == "__main__":
    main()
