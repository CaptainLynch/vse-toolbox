from pathlib import Path


def test_overview_details_include_split_paa_and_ncr_rows() -> None:
    source = Path("web/static/app.js").read_text(encoding="utf-8-sig")
    assert "PAA 变更记录" in source
    assert "NCR 审批进度" in source
    assert "NCR 审批明细" in source
    assert "overviewArchiveJobs" in source
    assert "renderExternalSyncSummary" in source


def test_external_rows_preserve_success_time_and_selected_archive_job() -> None:
    source = Path("web/static/app.js").read_text(encoding="utf-8-sig")
    assert "progressOrDate: job.lastSuccessAt" in source
    assert "selectedArchiveJobKey = item.externalJobKey" in source
    assert "overviewArchiveJobs = archiveJobs.slice()" in source
    assert "archiveSyncStateLabel(job.syncState)" in source


def test_archive_failure_does_not_clear_project_overview() -> None:
    source = Path("web/static/app.js").read_text(encoding="utf-8-sig")
    assert "const response = await fetch(\"/api/project-status?phase=VPI-T2\"" in source
    assert "overviewArchiveJobs = [];" in source


def test_external_rows_navigate_to_dedicated_detail_page() -> None:
    source = Path("web/static/app.js").read_text(encoding="utf-8-sig")
    assert "#archive-deliverable/" in source
    assert "renderArchiveDeliverableDetailPage" in source
    assert "archiveDeliverableMatch" in source
    assert "进入任务配置/重试" in source


def test_external_detail_matches_ewo_layout_with_collapsed_bottom_info() -> None:
    source = Path("web/static/app.js").read_text(encoding="utf-8-sig")
    assert "external-progress-chart" in source
    assert "external-detail-info" in source
    assert "详细信息（点击展开）" in source
    assert "立即刷新（交互式查询）" in source
    assert "进入任务配置/重试" in source


def test_paa_detail_interactive_refresh_is_separate_from_archive_sync() -> None:
    source = Path("web/static/app.js").read_text(encoding="utf-8-sig")
    detail = source[source.index("function renderArchiveDeliverableDetailPage"):source.index("function toggleDeliverableDetail")]
    interactive = source[source.index("async function runPaaInteractiveRefresh"):source.index("function renderDeliverableDetailPage")]

    assert "const isPaa = job.jobKey === \"aras_paa\"" in detail
    assert "buildPaaInteractiveFilters" in interactive
    assert 'requestInteractiveArasQuery("paa"' in interactive
    assert "renderInteractiveArasResult" in interactive
    assert "立即刷新（交互式查询）" in detail
    assert "进入任务配置/重试" in detail
    assert "const syncButton = isPaa" in detail
    assert "/api/scheduled-archive/jobs/${encodeURIComponent(job.jobKey)}/sync-now" not in interactive
    assert "interactiveButton.disabled = !job.enabled" not in detail
