# -*- coding: utf-8 -*-
"""Generate docs/API_ENDPOINTS.md from web/app.py route decorators.

用法: python tools/generate_api_endpoints.py
路由以 AST 解析 web/app.py 中 create_app 内的 @app.<method>("path")
装饰器，输出按路径前缀分组的 Markdown 端点清单，供后续开发参考。
"""

import ast
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP_SOURCE = ROOT / "web" / "app.py"
OUTPUT = ROOT / "docs" / "API_ENDPOINTS.md"

METHODS = {"get", "post", "patch", "put", "delete", "route"}

GROUP_NAMES = {
    "/api/overview": "总览",
    "/api/project-status": "项目状态与交付物",
    "/api/deliverables": "交付物目录与统一状态",
    "/api/deliverable-forms": "统一表单分析",
    "/api/scheduled-archive": "定时归档任务",
    "/api/excel": "Excel 任务",
    "/api/aras": "Aras 交互查询",
    "/api/tdc": "TDC 交互查询",
    "/api/agent": "Agent 中继",
    "/api/settings": "系统设置",
    "/api/diagnostics": "安全诊断录制",
    "/api/debug": "诊断与调试",
}


def route_entries(source: str) -> list[tuple[str, str, str]]:
    tree = ast.parse(source)
    entries: list[tuple[str, str, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call):
                continue
            func = decorator.func
            if not isinstance(func, ast.Attribute) or func.attr not in METHODS:
                continue
            if not (
                isinstance(func.value, ast.Name) and func.value.id == "app"
            ):
                continue
            if not decorator.args or not isinstance(
                decorator.args[0], ast.Constant
            ):
                continue
            path = str(decorator.args[0].value)
            method = "GET/POST" if func.attr == "route" else func.attr.upper()
            entries.append((path, method, node.name))
    return sorted(set(entries), key=lambda item: (item[0], item[1]))


def group_of(path: str) -> str:
    for prefix, name in GROUP_NAMES.items():
        if path.startswith(prefix):
            return name
    return "页面与其他"


def main() -> int:
    source = APP_SOURCE.read_text(encoding="utf-8")
    entries = route_entries(source)
    diagnostic_source = ROOT / "web" / "diagnostics.py"
    if diagnostic_source.is_file():
        entries += route_entries(diagnostic_source.read_text(encoding="utf-8"))
    enrichment_source = ROOT / "web" / "ewo_enrichment.py"
    if enrichment_source.is_file():
        entries += route_entries(enrichment_source.read_text(encoding="utf-8"))
    grouped: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    for path, method, func in entries:
        grouped[group_of(path)].append((path, method, func))

    lines = [
        "# VSE Toolbox Web API 端点清单",
        "",
        "> 状态：Generated",
        "> 读者：Developer、Agent（API 任务）",
        "> 权威来源：`web/app.py`、`web/diagnostics.py`、`web/ewo_enrichment.py` 路由装饰器；参数行为以代码和测试为准",
        "> 默认读取：按 API/UI 任务读取",
        "> 由 `tools/generate_api_endpoints.py` 从上述路由模块 AST 解析自动生成，",
        f"> 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}，共 {len(entries)} 个端点。",
        "> 手工新增路由后请重跑该脚本刷新本清单。",
        "",
        "通用约定：",
        "",
        "- 写操作（POST/PATCH/PUT/DELETE）仅接受本机回环访问（loopback 校验）。",
        "- 响应统一为 `{\"ok\": true, \"data\": ...}` 或 `{\"ok\": false, \"error\": {...}}`。",
        "- 本清单只列路由与方法，参数契约以 `web/app.py`、`web/diagnostics.py` 对应处理函数与测试为准。",
        "",
    ]
    for group in sorted(grouped):
        lines.append(f"## {group}")
        lines.append("")
        lines.append("| 方法 | 路径 | 处理函数 |")
        lines.append("| --- | --- | --- |")
        for path, method, func in grouped[group]:
            lines.append(f"| {method} | `{path}` | `{func}` |")
        lines.append("")
    OUTPUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"已生成 {OUTPUT}（{len(entries)} 个端点，{len(grouped)} 组）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
