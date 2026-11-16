"""回滚静默化工具：部署上一版代码前冻结 EWO 导出任务。

为什么存在：旧版本把 ``generating``/``downloading`` 视为可恢复状态，其重试分支还接受
``interrupted``/``failed``。若直接在“有在途任务”的库上回滚，旧代码可能对已生成过的
任务再次调用官方导出（服务端副作用不可幂等）。本工具把在途任务冻结到旧代码只会
“人工核查/续下载”的状态。

默认只预览（不写库）；``--apply`` 才执行。库路径必须显式给出，避免误操作生产库。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from core.ewo_export_jobs import ACTIVE_STATES, EWOExportJobs


def _preview(jobs: EWOExportJobs) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in jobs.list_jobs(limit=200):
        state = str(row.get('state') or '')
        if state in ACTIVE_STATES:
            counts[state] = counts.get(state, 0) + 1
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', required=True, help='EWO 作业库（SQLite）路径')
    parser.add_argument('--apply', action='store_true', help='执行冻结（默认只预览）')
    args = parser.parse_args(argv)
    path = Path(args.db)
    if not path.is_file():
        print(f'database not found: {path}', file=sys.stderr)
        return 2
    jobs = EWOExportJobs(path)
    if not args.apply:
        print(json.dumps({'mode': 'preview', 'active': _preview(jobs)}, ensure_ascii=False))
        return 0
    counts = jobs.quiesce(for_rollback=True)
    print(json.dumps({'mode': 'applied', **counts}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
