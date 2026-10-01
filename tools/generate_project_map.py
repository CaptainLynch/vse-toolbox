# -*- coding: utf-8 -*-
"""Generate and verify the Agent-facing VSE Toolbox project map.

The generator is deliberately scope-first.  It walks only approved product
roots and entrypoints, parses Python source with :mod:`ast`, and never imports
the application or reads raw crawler evidence.  ``--check`` is safe to run in
CI and does not write files; ``--write`` refreshes ``PROJECT_MAP.md``.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import textwrap
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence


ROOT = Path(__file__).resolve().parent.parent
MAP_FILE = ROOT / "PROJECT_MAP.md"
MAP_SCHEMA_VERSION = 1

# These are the only source roots the map generator traverses.  Do not replace
# this with a repository-root glob: tracked HAR/HTML/XLSX evidence is not
# production code and is intentionally outside the map.
SOURCE_DIRS = ("core", "host", "services", "web")
SOURCE_FILES = (
    "main.py",
    "webui.py",
    "excel_worker_entry.py",
    "tdc_probe_main.py",
    "tdc_probe_cli.py",
    "tools/excel_worker_cli.py",
)
SOURCE_SUFFIXES = frozenset({".py", ".html", ".js", ".css", ".json"})
SKIP_PARTS = frozenset(
    {
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".runtime",
        ".agents",
        ".zcode",
        ".excel_workbench",
    }
)

DEFAULT_DENY_PATHS = (
    "crawl source/",
    "爬虫源文件/",
    "error data/",
    "build/",
    "dist/",
    "dist-probe/",
    "production*/",
    ".build_production*/",
    ".runtime/",
    "artifacts/",
    "tmp/",
    ".tmp_*/",
    ".agents/runs/",
    ".agents/logs/",
    ".agents/worktrees/",
    ".zcode/",
    ".excel_workbench/",
    "__pycache__/",
    ".pytest_cache/",
    ".mypy_cache/",
    "design-previews/",
    "meeting_outputs/",
    "root exploratory scripts and raw XML/HAR/XLSX samples",
)

ROUTE_METHODS = frozenset({"get", "post", "patch", "put", "delete", "route"})
ROUTE_GROUPS = (
    ("/api/overview", "Overview"),
    ("/api/project-status", "Project status and deliverables"),
    ("/api/deliverables", "Deliverables catalog"),
    ("/api/deliverable-forms", "Unified form analysis"),
    ("/api/scheduled-archive", "Scheduled archive"),
    ("/api/excel", "Excel tasks"),
    ("/api/aras", "Aras"),
    ("/api/tdc", "TDC"),
    ("/api/settings", "Settings"),
)

ROLE_OVERRIDES = {
    "core/archive_store.py": "Atomic local archive storage and retention",
    "core/credential_provider.py": "Windows credential lookup boundary",
    "core/db_manager.py": "SQLite schema, migrations, leases and persistence",
    "core/domain_identity.py": "DPAPI-backed domain identity/session state",
    "core/excel_tasks.py": "Excel task contracts, path safety and repository",
    "core/excel_worker.py": "Excel task execution core",
    "core/redaction.py": "Credential-safe display and redaction helpers",
    "core/report_contracts.py": "Approved report/table field contracts",
    "core/runtime_paths.py": "Source/frozen runtime root resolution",
    "core/settings_store.py": "Non-sensitive local settings validation",
    "core/unified_status.py": "Shared authentication/query/sync status contract",
    "services/aras_auth.py": "Aras OIDC/ValidateUser authentication",
    "services/aras_crawler.py": "Aras EWO/PAA/NCR SOAP/XML client",
    "services/aras_export.py": "Aras local CSV/XML export adapters",
    "services/deliverable_form_analysis.py": "Unified deliverable form snapshots and analysis",
    "services/excel_toolbox.py": "Local Excel/PPT automation helpers",
    "services/excel_worker_process_controller.py": "Out-of-process Excel Worker lifecycle",
    "services/project_status_analytics.py": "Read-only project-status analytics",
    "services/project_status_connectors.py": "Fixed-contract Aras/TDC status connectors",
    "services/project_status_deliverable_analysis.py": "Cached deliverable filtering and chart analysis",
    "services/project_status_discovery.py": "Stable-key and mapping discovery evidence",
    "services/project_status_sync_runner.py": "Project-status sync orchestration and leases",
    "services/project_status_updates.py": "Approved project-status update policy and audit",
    "services/scheduled_archive_admin.py": "Scheduled archive configuration administration",
    "services/scheduled_archive_connectors.py": "Six fixed scheduled archive collectors",
    "services/scheduled_archive_runner.py": "One-shot scheduled archive orchestration",
    "services/tdc_auth.py": "TDC OIDC/password authentication",
    "services/tdc_contract_probe.py": "Offline-safe TDC contract profiling",
    "services/tdc_crawler.py": "TDC data-model/SOR/A-face HTTP client",
    "services/tdc_export_cache.py": "Bounded official TDC export cache",
    "services/windows_http.py": "WinHTTP/Schannel transport boundary",
    "services/xlsx_preview.py": "Dependency-free bounded XLSX preview",
    "web/app.py": "Flask composition adapter and Web API routes",
    "host/__init__.py": "Plugin host package exports",
    "host/context.py": "HostContext: shared services handed to plugins",
    "host/plugin.py": "plugin.json manifest contract and host API compatibility",
    "host/registry.py": "Plugin discovery, isolated loading and blueprint registration",
    "main.py": "Rich CLI adapter, menu routing and legacy operations",
    "webui.py": "WebUI source/frozen launcher",
    "excel_worker_entry.py": "Frozen Excel Worker launcher",
    "tdc_probe_main.py": "Standalone TDC probe launcher",
    "tdc_probe_cli.py": "Standalone TDC probe CLI adapter",
    "tools/excel_worker_cli.py": "Excel Worker process CLI adapter",
}


@dataclass(frozen=True)
class ModuleSummary:
    relative_path: str
    role: str
    symbols: tuple[str, ...]
    imports: tuple[str, ...]
    test_hint: str


def _relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def discover_source_files(root: Path = ROOT) -> list[Path]:
    """Return only approved source files, in deterministic relative order."""

    root = root.resolve()
    paths: set[Path] = set()
    for directory in SOURCE_DIRS:
        base = root / directory
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in SOURCE_SUFFIXES:
                continue
            relative_parts = path.relative_to(root).parts
            if any(part in SKIP_PARTS for part in relative_parts):
                continue
            paths.add(path.resolve())

    for relative in SOURCE_FILES:
        path = root / relative
        if path.is_file():
            paths.add(path.resolve())

    return sorted(paths, key=lambda path: _relative(path, root))


def route_entries(source: str) -> list[tuple[str, str, str]]:
    """Extract Flask route decorators without importing ``web.app``."""

    tree = ast.parse(source)
    entries: set[tuple[str, str, str]] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call):
                continue
            function = decorator.func
            if not isinstance(function, ast.Attribute):
                continue
            if function.attr not in ROUTE_METHODS:
                continue
            if not isinstance(function.value, ast.Name) or function.value.id != "app":
                continue
            if not decorator.args or not isinstance(decorator.args[0], ast.Constant):
                continue
            if not isinstance(decorator.args[0].value, str):
                continue
            method = "GET/POST" if function.attr == "route" else function.attr.upper()
            entries.add((decorator.args[0].value, method, node.name))
    return sorted(entries, key=lambda item: (item[0], item[1], item[2]))


def _first_doc_line(tree: ast.AST) -> str:
    docstring = ast.get_docstring(tree, clean=True) or ""
    return " ".join(docstring.splitlines()).strip().split(".")[0].strip()


def _public_symbols(tree: ast.Module) -> tuple[str, ...]:
    names = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if not node.name.startswith("_"):
                names.append(node.name)
    return tuple(names[:8])


def _internal_imports(tree: ast.Module) -> tuple[str, ...]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            candidates = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            candidates = [node.module or ""]
        else:
            continue
        for name in candidates:
            if name.startswith(("core", "host", "services", "web", "tools", "main", "tdc_probe")):
                names.add(name)
    return tuple(sorted(names)[:6])


def _test_hint(relative_path: str, root: Path) -> str:
    stem = Path(relative_path).stem
    exact = root / "tests" / f"test_{stem}.py"
    if exact.is_file():
        return f"tests/{exact.name}"
    if relative_path == "web/app.py":
        return "tests/*web*.py"
    if relative_path == "main.py":
        return "tests/*cli*.py"
    if relative_path.startswith("services/tdc_") or relative_path.startswith("tdc_probe"):
        return "tests/*tdc*.py"
    if relative_path.startswith("services/aras_"):
        return "tests/*aras*.py"
    if relative_path.startswith("services/project_status_"):
        return "tests/*project_status*.py"
    if relative_path.startswith("services/scheduled_archive_"):
        return "tests/*scheduled_archive*.py"
    if relative_path.startswith("core/excel_") or relative_path.startswith("tools/excel_worker"):
        return "tests/*excel*.py"
    return "—"


def _module_summary(path: Path, root: Path) -> ModuleSummary:
    relative_path = _relative(path, root)
    source = path.read_text(encoding="utf-8-sig")
    tree = ast.parse(source, filename=relative_path)
    role = ROLE_OVERRIDES.get(relative_path) or _first_doc_line(tree) or "See module source"
    return ModuleSummary(
        relative_path=relative_path,
        role=role,
        symbols=_public_symbols(tree),
        imports=_internal_imports(tree),
        test_hint=_test_hint(relative_path, root),
    )


def source_fingerprint(root: Path = ROOT) -> str:
    """Hash the approved scope, including paths and bytes, deterministically."""

    digest = hashlib.sha256()
    for path in discover_source_files(root):
        relative = _relative(path, root).encode("utf-8")
        digest.update(relative)
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _markdown_cell(value: object) -> str:
    text = str(value).replace("|", "\\|").replace("\n", " ").strip()
    return text or "—"


def _route_group(path: str) -> str:
    for prefix, name in ROUTE_GROUPS:
        if path.startswith(prefix):
            return name
    return "Other"


def _manual_sections() -> str:
    deny_paths = "\n".join(f"- `{path}`" for path in DEFAULT_DENY_PATHS)
    template = textwrap.dedent(
        """
        ## Retrieval contract

        This file is the default code-navigation entrypoint for Agents. The
        repository and tests remain the authority; this map is navigation,
        not a substitute for reading the target implementation.

        **Approved production scope:** `core/`, `host/`, `services/`, `web/`,
        `main.py`, `webui.py`, `excel_worker_entry.py`,
        `tools/excel_worker_cli.py`, `tdc_probe_main.py`, and
        `tdc_probe_cli.py`.

        ## Default-deny paths

        __DENY_PATHS__

        Raw HAR/XML/XLSX content is never copied into this map. Read raw
        evidence only when the task explicitly concerns parsing or forensic
        validation, and prefer the redacted summaries under `docs/agents/`.

        ## Runtime products

        | Product | Entry point | Main implementation | Packaging |
        | --- | --- | --- | --- |
        | WebUI | `webui.py` | `web/app.py`, `web/templates/`, `web/static/` | `VSE-WebUI.spec` |
        | CLI | `main.py` | `main.py`, `services/` | `VSE-Toolbox.spec` |
        | Excel Worker | `excel_worker_entry.py` | `tools/excel_worker_cli.py`, `core/excel_worker.py` | `VSE-ExcelWorker.spec` |
        | TDC Probe | `tdc_probe_main.py` | `tdc_probe_cli.py`, `services/tdc_contract_probe.py` | `VSE-TDC-Probe.spec` |

        ## Task router

        | Task cue | Start here | Continue with | Focused tests |
        | --- | --- | --- | --- |
        | 插件宿主/新功能插件 | `host/registry.py` | `host/plugin.py`, `host/context.py`, `docs/PLUGIN_REFACTOR_PLAN_20261001.md` | `tests/test_plugin_host.py` |
        | Web/API/UI | `web/app.py` | `web/static/app.js`, `web/templates/dashboard.html` | `tests/*web*.py` |
        | Aras EWO/PAA/NCR | `web/app.py` | `services/aras_auth.py`, `services/aras_crawler.py`, `services/aras_export.py` | `tests/*aras*.py` |
        | TDC/SOR/数模/A 面 | `web/app.py` | `services/tdc_auth.py`, `services/tdc_crawler.py`, `services/tdc_export_cache.py` | `tests/*tdc*.py` |
        | 项目状态/交付物 | `services/project_status_sync_runner.py` | `services/project_status_*.py`, `core/db_manager.py` | `tests/*project_status*.py` |
        | 定时归档 | `services/scheduled_archive_runner.py` | `services/scheduled_archive_*.py`, `core/archive_store.py` | `tests/*scheduled_archive*.py` |
        | Excel/COM/Worker | `core/excel_tasks.py` | `core/excel_worker.py`, `services/excel_*.py`, `tools/excel_worker_cli.py` | `tests/*excel*.py` |
        | 认证/凭据/脱敏 | `core/credential_provider.py` | `core/domain_identity.py`, `core/redaction.py`, `services/*_auth.py`, `services/windows_http.py` | `tests/*credential*.py` |
        | EXE/打包 | matching `*.spec` | `.github/workflows/`, `tools/build_excel_bundle.ps1` | `tests/*packaging*.py` |

        ## Core boundaries

        - `web/` and `main.py` are adapters; business and integration logic is
          under `services/` and shared contracts/storage under `core/`.
        - `core/` owns SQLite, credentials, redaction, status contracts,
          archive storage and Excel task primitives.
        - `services/` owns Aras/TDC/Office integrations and orchestration.
        - Excel automation has a production out-of-process boundary through
          `VSE-ExcelWorker.exe`.

        ## Key flows

        Browser/CLI → adapter → service → Aras/TDC/Office → normalized rows or
        snapshots → SQLite/ArchiveStore → API/UI or exported artifact.

        - Web routes: `docs/API_ENDPOINTS.md` (generated, route-only inventory).
        - SQLite schema and migrations: `core/db_manager.py`.
        - Report fields: `core/report_contracts.py`, `core/report_headers.json`.
        - Status contracts: `core/unified_status.py`,
          `core/project_status_contracts.py`.
        - Worker process contract: `services/excel_worker_process_controller.py`.

        ## Documentation authority

        - Current execution frontier: `memory/CURRENT_STATE.md`.
        - Durable choices: `memory/DECISIONS.md`.
        - Recovery facts: `memory/RECOVERY_NOTES.md`.
        - Agent runtime: `docs/ZCODE_WORKER_RUNTIME.md`, `tools/agents/README.md`.
        - User operation: `README.md`, `docs/PRODUCTION_OPERATION_GUIDE.md`,
          and `docs/USER_GUIDE_STANDALONE_EXE.md`.
        - Current issue dossiers such as `docs/SOR_EXPORT_*.md` are
          task-scoped until their production retest is closed.
        - Historical plans, external snapshots, and session handoffs are
          task-scoped and never override source code or tests.

        """
    ).strip()
    return template.replace("__DENY_PATHS__", deny_paths)


def _generated_inventory(root: Path, modules: Sequence[ModuleSummary], routes: Sequence[tuple[str, str, str]]) -> str:
    source_files = discover_source_files(root)
    route_counts = Counter(_route_group(path) for path, _, _ in routes)
    lines = [
        "## Generated inventory",
        "",
        f"- Scoped files: {len(source_files)}",
        f"- Python modules: {len(modules)}",
        f"- Flask route decorators: {len(routes)}",
        "",
        "### Flask route groups",
        "",
        "| Group | Routes |",
        "| --- | ---: |",
    ]
    for group in sorted(route_counts):
        lines.append(f"| {_markdown_cell(group)} | {route_counts[group]} |")

    lines.extend(
        [
            "",
            "### Production module index",
            "",
            "| Path | Responsibility | Public symbols | Internal imports | Test hint |",
            "| --- | --- | --- | --- | --- |",
        ]
    )
    for module in modules:
        symbols = ", ".join(module.symbols) if module.symbols else "—"
        imports = ", ".join(module.imports) if module.imports else "—"
        lines.append(
            "| {path} | {role} | {symbols} | {imports} | {tests} |".format(
                path=f"`{_markdown_cell(module.relative_path)}`",
                role=_markdown_cell(module.role),
                symbols=_markdown_cell(symbols),
                imports=_markdown_cell(imports),
                tests=_markdown_cell(module.test_hint),
            )
        )
    return "\n".join(lines)


def build_map(root: Path = ROOT) -> str:
    """Render the complete deterministic project map."""

    root = root.resolve()
    modules = []
    for path in discover_source_files(root):
        if path.suffix.lower() != ".py":
            continue
        modules.append(_module_summary(path, root))

    app_source_path = root / "web" / "app.py"
    routes = route_entries(app_source_path.read_text(encoding="utf-8-sig")) if app_source_path.is_file() else []
    diagnostic_source = root / "web" / "diagnostics.py"
    if diagnostic_source.is_file():
        routes += route_entries(diagnostic_source.read_text(encoding="utf-8-sig"))
    fingerprint = source_fingerprint(root)
    header = textwrap.dedent(
        f"""
        # VSE Toolbox Project Map

        > Generated by `tools/generate_project_map.py`; do not hand-edit generated facts.
        > Map schema: {MAP_SCHEMA_VERSION} · Source fingerprint: `{fingerprint}`
        > Scope is intentionally allowlist-driven; raw evidence and runtime artifacts are not indexed.

        """
    ).strip()
    return f"{header}\n\n{_manual_sections()}\n\n{_generated_inventory(root, modules, routes)}\n"


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--write", action="store_true", help="write PROJECT_MAP.md")
    mode.add_argument("--check", action="store_true", help="verify PROJECT_MAP.md without writing")
    args = parser.parse_args(argv)

    root = ROOT
    rendered = build_map(root)
    if args.check:
        if not MAP_FILE.is_file():
            print(f"Missing generated map: {MAP_FILE}")
            return 1
        current = MAP_FILE.read_text(encoding="utf-8")
        if current != rendered:
            print(f"Project map is out of date: {MAP_FILE}")
            return 1
        print(f"Project map verified: {MAP_FILE}")
        return 0

    if args.write:
        MAP_FILE.write_text(rendered, encoding="utf-8", newline="\n")
        print(f"Generated {MAP_FILE}")
        return 0

    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
