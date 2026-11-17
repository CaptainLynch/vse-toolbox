"""诊断包字段白名单化与禁止清单防御断言（契约 docs/refactor-v2/CONTRACTS.md C10）。

本测试文件验证：
1. 导出载荷逐键断言 ⊆ 白名单闭集，禁止任何非白名单键进入导出。
2. 对禁止清单逐项断言：原始请求/响应体、环境变量全集、凭据库内容、数据库文件、业务工作簿、日志原文。
3. 脱敏器对内网地址与长随机串的第二道防线处理断言。
4. 保持现有诊断路由对外接口契约（路径、方法、状态码与响应头）完全兼容。
"""
from __future__ import annotations

import io
import json
import logging
import os
import platform
import socket
import uuid
import zipfile

import pytest
from flask import Flask, jsonify

from core.diagnostic_recording import Recorder
from web.diagnostics import (
    BUILD_INFO_FIELDS,
    DIAGNOSTIC_WHITELIST_FIELDS,
    MODULE_HEALTH_FIELDS,
    SAFE_ERROR_CODE_ENUM,
    build_diagnostic_payload,
    get_anonymous_installation_id,
    get_build_info,
    get_module_health,
    get_safe_error_codes,
    install_diagnostics,
    record_module_health,
    record_safe_error_code,
    redact_diagnostics_text,
    reset_module_health,
    reset_safe_error_codes,
    set_user_notes,
)


@pytest.fixture(autouse=True)
def clean_diagnostics_state():
    """每次测试前清理内存计数与安全错误码，防止跨用例污染。"""
    reset_module_health()
    reset_safe_error_codes()
    set_user_notes(None)
    yield
    reset_module_health()
    reset_safe_error_codes()
    set_user_notes(None)


@pytest.fixture
def app_client(tmp_path):
    """创建带有诊断中间件的测试客户端。"""
    app = Flask(__name__)
    recorder = Recorder(tmp_path)
    install_diagnostics(app, recorder)

    @app.post("/api/synthetic-service")
    def synthetic_service():
        return jsonify(
            ok=False,
            error={
                "type": "UpstreamError",
                "diagnostic": {"apiCode": 4001, "stage": "synthetic"},
                "message": "SYNTHETIC_UPSTREAM_PROSE_SECRET",
            },
            data={"business_response_secret": "RESPONSE_BODY_SECRET_9876"},
        ), 502

    @app.get("/api/tdc/projects")
    def tdc_projects():
        return jsonify(ok=True, data=[{"project_id": "PRJ-001"}])

    return app.test_client(), recorder


# ============================================================================
# 1. 导出载荷逐键断言 ⊆ 白名单闭集
# ============================================================================

def test_export_payload_keys_subset_of_whitelist():
    """断言顶层字段严格处于白名单闭集内，无任何未白名单化字段。"""
    record_module_health("tdc", success=True)
    record_safe_error_code("UpstreamError")
    payload = build_diagnostic_payload("测试用户备注说明")

    # 顶层键必须是白名单的子集且完全匹配白名单规范
    assert set(payload.keys()) <= DIAGNOSTIC_WHITELIST_FIELDS
    assert set(payload.keys()) == DIAGNOSTIC_WHITELIST_FIELDS

    # 1. 匿名安装标识（单向哈希，不含机器名/用户名）
    anon_id = payload["anonymous_installation_id"]
    assert isinstance(anon_id, str)
    assert len(anon_id) == 32
    # 严格断言：哈希串中不包含任何机器名或系统用户名
    machine_name = platform.node().lower()
    if machine_name:
        assert machine_name not in anon_id.lower()
    current_user = (os.environ.get("USERNAME") or os.environ.get("USER") or "").lower()
    if current_user:
        assert current_user not in anon_id.lower()

    # 2. 各模块健康计数（成功/失败次数、最近一次时间戳）
    health = payload["module_health"]
    assert isinstance(health, dict)
    for mod_name, counts in health.items():
        assert isinstance(mod_name, str)
        assert set(counts.keys()) <= MODULE_HEALTH_FIELDS
        assert set(counts.keys()) == MODULE_HEALTH_FIELDS
        assert isinstance(counts["success_count"], int)
        assert isinstance(counts["failure_count"], int)
        assert isinstance(counts["last_timestamp"], str)

    # 3. 安全错误码（既有错误 type 码枚举）
    errors = payload["safe_error_codes"]
    assert isinstance(errors, list)
    for code in errors:
        assert code in SAFE_ERROR_CODE_ENUM

    # 4. 版本与构建信息
    build = payload["build_info"]
    assert isinstance(build, dict)
    assert set(build.keys()) <= BUILD_INFO_FIELDS
    assert set(build.keys()) == BUILD_INFO_FIELDS
    assert "version" in build and "build" in build

    # 5. 用户主动勾选的说明文本
    assert payload["user_notes"] == "测试用户备注说明"


def test_anonymous_installation_id_deterministic_and_sanitized():
    """测试单向哈希匿名标识：同一种子确定性生成，不同种子互不碰撞，且不含主机名。"""
    id_1 = get_anonymous_installation_id(seed="fixed-seed-01")
    id_2 = get_anonymous_installation_id(seed="fixed-seed-01")
    id_3 = get_anonymous_installation_id(seed="fixed-seed-02")

    assert id_1 == id_2
    assert id_1 != id_3
    assert len(id_1) == 32
    # 验证不含主机名与 IP
    assert socket.gethostname().lower() not in id_1.lower()


def test_unwhitelisted_error_codes_are_dropped_not_collected():
    """白名单之外的错误码直接不收集，而非脱敏保留。"""
    record_safe_error_code("ValidationError")  # 在白名单中
    record_safe_error_code("ARBITRARY_UNTRUSTED_EXCEPTION_WITH_SECRET_xyz")  # 不在白名单中
    codes = get_safe_error_codes()

    assert "ValidationError" in codes
    assert "ARBITRARY_UNTRUSTED_EXCEPTION_WITH_SECRET_xyz" not in codes


def test_bundle_download_diagnostics_json_strictly_whitelisted(app_client):
    """从导出的实际 zip 包中解析 diagnostics.json 并逐键断言。"""
    client, recorder = app_client
    client.post("/api/diagnostics/start", json={})
    client.get("/api/tdc/projects")
    client.post("/api/diagnostics/stop", json={})

    bundle_id = recorder.status()["latest"]["id"]
    response = client.get(f"/api/diagnostics/bundles/{bundle_id}?note=用户反馈排查说明")
    assert response.status_code == 200

    with zipfile.ZipFile(io.BytesIO(response.data)) as archive:
        assert "diagnostics.json" in archive.namelist()
        data = json.loads(archive.read("diagnostics.json"))
        # 逐键断言顶层字段
        assert set(data.keys()) <= DIAGNOSTIC_WHITELIST_FIELDS
        # 逐键断言各模块健康计数
        for mod, stats in data["module_health"].items():
            assert set(stats.keys()) <= MODULE_HEALTH_FIELDS
        # 逐键断言构建信息
        assert set(data["build_info"].keys()) <= BUILD_INFO_FIELDS


# ============================================================================
# 2. 对禁止清单逐项断言（构造敏感输入，导出后全文不含）
# ============================================================================

def test_forbidden_list_assertions_across_exported_bundle(app_client, monkeypatch):
    """针对禁止清单逐项断言：构造全部类别敏感输入，验证导出包全文不含。

    禁止清单：
    1. 原始请求/响应体
    2. 环境变量全集
    3. 凭据库内容（Token / Cookie / 密码）
    4. 数据库文件
    5. 业务工作簿
    6. 日志原文
    """
    client, recorder = app_client

    # (2) 环境变量全集注入合成敏感变量
    synthetic_env_key = "SYNTHETIC_CLOUD_ROOT_KEY_999"
    synthetic_env_val = "SECRET_ENV_VAL_DO_NOT_EXPORT_9876543210"
    monkeypatch.setenv(synthetic_env_key, synthetic_env_val)

    # 启动录制
    client.post("/api/diagnostics/start", json={})

    # (1) & (3) 构造含原始请求体与凭据库敏感内容的请求
    synthetic_req_body = {
        "sensitive_user_query": "PROJECT-SYNTHETIC-QUERY-BODY-ALPHA",
        "confidential_budget": "999888777",
        "nested_customer": {"applicant_name": "SYNTHETIC_APPLICANT_NAME"},
    }
    trace_id = uuid.uuid4().hex
    resp = client.post(
        "/api/synthetic-service",
        headers={
            "X-VSE-Trace-ID": trace_id,
            "Authorization": "Bearer SYNTHETIC_VAULT_BEARER_TOKEN_ABCD1234EFGH",
            "Cookie": "sid=SYNTHETIC_COOKIE_SID_SECRET; ArasAuth=SYNTHETIC_COOKIE_ARAS_SECRET",
        },
        json=synthetic_req_body,
    )
    assert resp.status_code == 502

    # (6) 日志原文：触发日志记录
    logger = logging.getLogger()
    logger.error("SYNTHETIC_LOGGER_RAW_MESSAGE_SHOULD_NEVER_APPEAR_112233")

    # 停止录制
    client.post("/api/diagnostics/stop", json={})

    # 导出诊断包
    bundle_id = recorder.status()["latest"]["id"]
    download_resp = client.get(f"/api/diagnostics/bundles/{bundle_id}")
    assert download_resp.status_code == 200

    # 提取 zip 全文字节流与文件名清单
    with zipfile.ZipFile(io.BytesIO(download_resp.data)) as archive:
        namelist = archive.namelist()
        all_bytes = b"".join(archive.read(name) for name in namelist)
        all_text = all_bytes.decode("utf-8", errors="replace")

        # --- 断言 1：原始请求/响应体全文不含 ---
        assert "PROJECT-SYNTHETIC-QUERY-BODY-ALPHA" not in all_text
        assert "999888777" not in all_text
        assert "SYNTHETIC_APPLICANT_NAME" not in all_text
        assert "RESPONSE_BODY_SECRET_9876" not in all_text
        assert "SYNTHETIC_UPSTREAM_PROSE_SECRET" not in all_text

        # --- 断言 2：环境变量全集全文不含且无 environment.json ---
        assert synthetic_env_val not in all_text
        assert synthetic_env_key not in all_text
        assert "environment.json" not in namelist

        # --- 断言 3：凭据库内容（Token / Cookie / 密码）全文不含 ---
        assert "SYNTHETIC_VAULT_BEARER_TOKEN_ABCD1234EFGH" not in all_text
        assert "SYNTHETIC_COOKIE_SID_SECRET" not in all_text
        assert "SYNTHETIC_COOKIE_ARAS_SECRET" not in all_text

        # --- 断言 4：数据库文件副本不进入导出 ---
        db_extensions = (".db", ".sqlite", ".sqlite3", ".sql")
        assert not any(name.lower().endswith(db_extensions) for name in namelist)
        assert b"SQLite format 3" not in all_bytes

        # --- 断言 5：业务工作簿不进入导出 ---
        workbook_extensions = (".xlsx", ".xls", ".xlsm", ".csv", ".tsv")
        assert not any(name.lower().endswith(workbook_extensions) for name in namelist)

        # --- 断言 6：日志原文全文不含且无 .log 文件 ---
        assert not any(name.lower().endswith(".log") for name in namelist)
        assert "SYNTHETIC_LOGGER_RAW_MESSAGE_SHOULD_NEVER_APPEAR_112233" not in all_text


# ============================================================================
# 3. 脱敏器对内网地址/长随机串的处理断言
# ============================================================================

@pytest.mark.parametrize("internal_addr", [
    "192.168.1.100",
    "192.168.0.1:8080",
    "10.20.30.40",
    "172.16.5.99",
    "172.31.255.254",
    "127.0.0.1:5000",
    "gateway.corp.local",
    "api.service.internal",
])
def test_redaction_masks_internal_addresses(internal_addr):
    """断言脱敏器将各类内网 IPv4 地址与内部主机名安全收口。"""
    text = f"连接内网服务失败：http://{internal_addr}/api/check 无法访问"
    redacted = redact_diagnostics_text(text)

    # 原始内网地址绝不出现在脱敏后的文本中
    assert internal_addr not in redacted
    assert ("[internal address redacted]" in redacted or "[internal host redacted]" in redacted)


@pytest.mark.parametrize("random_str", [
    "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "4a8f9c0e2b1d3a5e6f7a8b9c0d1e2f3a4b5c6d7e",
    "Kx9Z1pQ4wE7rT2yU5iO8aS3dF6gH0jL9",
])
def test_redaction_masks_long_random_strings(random_str):
    """断言脱敏器将32位以上十六进制串及长随机凭据串安全收口。"""
    text = f"请求流水追踪令牌为 {random_str}，处理失败"
    redacted = redact_diagnostics_text(text)

    assert random_str not in redacted
    assert "[token redacted]" in redacted


def test_user_notes_redaction_in_export_bundle(app_client):
    """用户主动勾选输入的说明文本在导出时必须经过脱敏器第二道防线。"""
    client, recorder = app_client
    client.post("/api/diagnostics/start", json={})
    client.post("/api/diagnostics/stop", json={})

    sensitive_note = (
        "排查说明：连接 192.168.1.50 报错，使用令牌 "
        "d41d8cd98f00b204e9800998ecf8427e12345678 验证未通过"
    )
    bundle_id = recorder.status()["latest"]["id"]
    response = client.get(f"/api/diagnostics/bundles/{bundle_id}?note={sensitive_note}")
    assert response.status_code == 200

    with zipfile.ZipFile(io.BytesIO(response.data)) as archive:
        data = json.loads(archive.read("diagnostics.json"))
        user_notes = data["user_notes"]
        assert "192.168.1.50" not in user_notes
        assert "d41d8cd98f00b204e9800998ecf8427e12345678" not in user_notes
        assert "[internal address redacted]" in user_notes
        assert "[token redacted]" in user_notes


# ============================================================================
# 4. 路由行为兼容性断言（路径/方法/信封保持不变）
# ============================================================================

def test_diagnostic_routes_envelope_and_status_compatibility(app_client):
    """断言诊断各路由对外行为不变：状态码、HTTP 方法与下载信封。"""
    client, recorder = app_client

    # 1. GET /api/diagnostics
    status_resp = client.get("/api/diagnostics")
    assert status_resp.status_code == 200
    assert "active" in status_resp.get_json()

    # 2. POST /api/diagnostics/start
    start_resp = client.post("/api/diagnostics/start", json={})
    assert start_resp.status_code == 200
    assert start_resp.get_json()["active"] is True

    # 重复启动报 409 RecordingAlreadyActive
    dup_resp = client.post("/api/diagnostics/start", json={})
    assert dup_resp.status_code == 409
    assert dup_resp.get_json()["error"] == "RecordingAlreadyActive"

    # 3. POST /api/diagnostics/mark
    mark_resp = client.post("/api/diagnostics/mark", json={"note": "用户标记节点"})
    assert mark_resp.status_code == 202
    assert mark_resp.get_json() == {"ok": True}

    # 4. POST /api/diagnostics/events
    event_resp = client.post(
        "/api/diagnostics/events",
        json={"kind": "action", "action_id": "act-1", "source": "diagnostics.js"},
    )
    assert event_resp.status_code == 202
    assert event_resp.get_json() == {"ok": True}

    # 5. POST /api/diagnostics/stop
    stop_resp = client.post("/api/diagnostics/stop", json={})
    assert stop_resp.status_code == 200
    assert stop_resp.get_json()["active"] is False

    # 6. GET /api/diagnostics/bundles/<id>
    latest_id = recorder.status()["latest"]["id"]
    bundle_resp = client.get(f"/api/diagnostics/bundles/{latest_id}")
    assert bundle_resp.status_code == 200
    assert bundle_resp.headers["Content-Type"] == "application/zip"
    assert "attachment" in bundle_resp.headers["Content-Disposition"]
    assert f"vse-diagnostics-{latest_id}.zip" in bundle_resp.headers["Content-Disposition"]

    # 7. 不存在的 identity 返回 404 RecordingNotFound
    not_found_resp = client.get("/api/diagnostics/bundles/" + "f" * 32)
    assert not_found_resp.status_code == 404
    assert not_found_resp.get_json() == {"ok": False, "error": "RecordingNotFound"}
