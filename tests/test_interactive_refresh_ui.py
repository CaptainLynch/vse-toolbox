from pathlib import Path


JS_PATH = Path("web/static/app.js")


def _source() -> str:
    return JS_PATH.read_text(encoding="utf-8-sig")


def _slice(source: str, start: str, end: str) -> str:
    return source[source.index(start):source.index(end)]


def test_interactive_helper_uses_existing_ewo_and_paa_query_contract() -> None:
    source = _source()
    helper = _slice(source, "const INTERACTIVE_QUERY_ERROR_LABELS", "function formatApiErrorMessage")

    for marker in (
        "function buildInteractiveArasPayload",
        "async function requestInteractiveArasQuery",
        "function formatInteractiveArasResult",
        "function formatInteractiveArasError",
        "function renderInteractiveArasResult",
        'auth_mode: "browser"',
        'fetch(config.endpoint',
        'base_url: EWO_POLICY_DEFAULT_ARAS_BASE_URL',
    ):
        assert marker in helper
    assert '"/api/aras/ewo/query"' in source
    assert '"/api/aras/paa/query"' in source

    for forbidden in (
        "credentialRef",
        "credential_ref",
        "mapping",
        "leaseToken",
        "lease_token",
        "password",
        "cookie",
        "cookies",
        "authorization",
    ):
        assert forbidden not in helper


def test_interactive_error_and_result_states_are_stable_and_short() -> None:
    source = _source()
    helper = _slice(source, "const INTERACTIVE_QUERY_ERROR_LABELS", "function formatApiErrorMessage")

    for label in ("未认证", "服务不可用", "查询失败", "数据为空", "未匹配"):
        assert label in helper
    assert "同步条件尚未满足" not in helper
    assert "本次结果未写入后台同步状态" in helper
    assert "err.errorCode = err.code" in source
    assert "err.errorType = err.type" in source
    assert "err.errorMessage" in source


def test_interactive_target_matching_supports_contract_table_rows() -> None:
    source = _source()
    helper = _slice(source, "function interactiveRowIdentityValues", "function formatApiErrorMessage")

    assert "Array.isArray(row)" in helper
    assert "sourceFields" in helper
    assert "formatInteractiveArasResult(data, targetKey, mode)" in helper
    assert 'formatInteractiveArasResult(data, spec.targetKey, "ewo")' in source
    assert 'formatInteractiveArasResult(data, targetKey, "paa")' in source


def test_ewo_detail_immediate_refresh_is_not_project_status_sync() -> None:
    source = _source()
    detail = _slice(source, "function renderDeliverableDetailPage", "function renderArchiveDeliverableDetailPage")
    evidence = _slice(source, "function renderDeliverableEvidence", "function renderCustomLabelChart")

    assert "onInteractiveRefresh" in detail
    assert "runEwoInteractiveRefreshFromStatusChart" in detail
    assert "立即刷新（交互式查询）" in source
    assert "requestProjectStatusSync(item)" not in detail
    assert "运行后台同步" in evidence
    assert "requestProjectStatusSync(item)" in evidence
    assert "syncReady" in evidence


def test_paa_detail_uses_query_refresh_and_keeps_archive_route_outside_detail() -> None:
    source = _source()
    detail = _slice(source, "function renderArchiveDeliverableDetailPage", "function toggleDeliverableDetail")
    interactive = _slice(source, "function buildPaaInteractiveFilters", "function renderDeliverableDetailPage")
    background = _slice(source, "async function runArchiveDetailBackgroundSync", "function overviewDeliverableRows")

    assert "const isPaa = job.jobKey === \"aras_paa\"" in detail
    assert "立即刷新（交互式查询）" in detail
    assert "const syncButton = isPaa" in detail
    assert "interactiveButton.disabled = !job.enabled" not in detail
    assert 'requestInteractiveArasQuery("paa"' in interactive
    assert "buildPaaInteractiveFilters" in interactive
    for field in ("paaNo", "ewoNo", "vehicleKeyword", "materialRequestStart", "materialRequestEnd", "department"):
        assert field in interactive
    assert "/api/scheduled-archive/jobs/${encodeURIComponent(job.jobKey)}/sync-now" not in detail
    assert "/api/scheduled-archive/jobs/${encodeURIComponent(job.jobKey)}/sync-now" in background


def test_existing_filter_chart_and_debug_surfaces_remain_present() -> None:
    source = _source()
    for marker in (
        'params.append("departments", department)',
        'params.append("stages", stage)',
        "analysisModelFilter",
        "buildChartLabelEditor",
        "downloadDeliverableDebugBundle",
        "buildDeliverableDebugSummary",
        "redactSensitiveText",
    ):
        assert marker in source
