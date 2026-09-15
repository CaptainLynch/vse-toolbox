from __future__ import annotations

from pathlib import Path

from tools.generate_project_map import (
    build_map,
    discover_source_files,
    route_entries,
    source_fingerprint,
)


ROOT = Path(__file__).resolve().parents[1]


def _relative_paths(paths: list[Path]) -> set[str]:
    return {path.relative_to(ROOT).as_posix() for path in paths}


def test_source_scope_includes_product_code_and_excludes_repository_noise() -> None:
    paths = _relative_paths(discover_source_files(ROOT))

    assert "core/db_manager.py" in paths
    assert "services/tdc_crawler.py" in paths
    assert "web/app.py" in paths
    assert "main.py" in paths
    assert "webui.py" in paths
    assert "excel_worker_entry.py" in paths
    assert "tools/excel_worker_cli.py" in paths
    assert "crawl source/ecm.sgmw.com.cn-EWO明细.har" not in paths
    assert "README.md" not in paths
    assert ".runtime" not in " ".join(paths)


def test_route_entries_extracts_web_api_contract_without_importing_app() -> None:
    source = (ROOT / "web" / "app.py").read_text(encoding="utf-8")

    entries = route_entries(source)

    assert ("/api/tdc/sor/export", "POST", "api_tdc_sor_export") in entries
    assert ("/api/project-status", "GET", "api_project_status") in entries


def test_build_map_contains_task_router_and_explicit_noise_boundary() -> None:
    rendered = build_map(ROOT)

    assert "## Task router" in rendered
    assert "services/tdc_crawler.py" in rendered
    assert "tools/excel_worker_cli.py" in rendered
    assert "## Default-deny paths" in rendered
    assert "crawl source/" in rendered
    assert "Raw HAR/XML/XLSX content is never copied" in rendered


def test_source_fingerprint_is_deterministic_and_sha256_shaped() -> None:
    first = source_fingerprint(ROOT)
    second = source_fingerprint(ROOT)

    assert first == second
    assert len(first) == 64
    assert all(character in "0123456789abcdef" for character in first)


def test_generated_map_does_not_contain_raw_evidence_or_runtime_artifacts() -> None:
    rendered = build_map(ROOT)

    assert "ecm.sgmw.com.cn-EWO明细.har" not in rendered
    assert "ewo_response.xml" not in rendered
    assert ".runtime/" in rendered
    assert "dist/" in rendered


def test_api_inventory_declares_generated_lifecycle() -> None:
    api_inventory = (ROOT / "docs" / "API_ENDPOINTS.md").read_text(encoding="utf-8")

    assert "> 状态：Generated" in api_inventory
    assert "tools/generate_api_endpoints.py" in api_inventory


def test_pull_request_workflow_runs_map_check() -> None:
    workflow = (ROOT / ".github" / "workflows" / "verify-project-map.yml").read_text(
        encoding="utf-8"
    )

    assert "pull_request:" in workflow
    assert "python tools/generate_project_map.py --check" in workflow
    assert "python -m pytest tests/test_project_map.py -q" in workflow
