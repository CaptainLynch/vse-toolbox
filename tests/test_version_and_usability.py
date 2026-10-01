# -*- coding: utf-8 -*-
"""自动化测试：WebUI 易用性优化（真实版本检测、原位登录结构、设置分层与共享状态）。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from flask.testing import FlaskClient

from core.db_manager import DatabaseManager
from core.version import get_app_version_info
import web.app as web_app
from web.app import create_app


# ── 1. 版本探测与环境退化测试 ───────────────────────────────────────────────────


def test_version_source_development(monkeypatch: pytest.MonkeyPatch) -> None:
    """源码工作区在无版本元数据时应安全显示「开发工作区」，不伪造假版本。"""
    monkeypatch.delenv("VSE_TOOLBOX_VERSION", raising=False)
    monkeypatch.delenv("VSE_TOOLBOX_CHANNEL", raising=False)
    monkeypatch.setattr(sys, "frozen", False, raising=False)

    info = get_app_version_info()
    assert info["displayVersion"] == "开发工作区"
    assert info["channel"] == "source"
    assert info["isFrozen"] is False
    assert "开发工作区" in info["detail"]


def test_version_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """构建或 CI 注入环境变量时优先使用注入的版本与渠道。"""
    monkeypatch.setenv("VSE_TOOLBOX_VERSION", "1.2.3")
    monkeypatch.setenv("VSE_TOOLBOX_CHANNEL", "ci-build")

    info = get_app_version_info()
    assert info["displayVersion"] == "v1.2.3"
    assert info["rawVersion"] == "1.2.3"
    assert info["channel"] == "ci-build"
    assert "v1.2.3" in info["detail"]


def test_version_file_json_detection(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """存在合法 version.json 时能正确解析版本号与 buildId。"""
    vjson = tmp_path / "version.json"
    vjson.write_text(json.dumps({"version": "2.0.0", "buildId": "build-987"}), encoding="utf-8")

    monkeypatch.delenv("VSE_TOOLBOX_VERSION", raising=False)
    monkeypatch.setattr("core.version.app_root", lambda: tmp_path)

    info = get_app_version_info()
    assert info["displayVersion"] == "v2.0.0"
    assert info["buildId"] == "build-987"


def test_version_frozen_fallback_without_metadata(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """独立运行 EXE 在缺少版本文件时安全退化为「独立运行包」，不崩溃、不报错。"""
    monkeypatch.delenv("VSE_TOOLBOX_VERSION", raising=False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr("core.version.app_root", lambda: tmp_path)

    info = get_app_version_info()
    assert info["displayVersion"] == "独立运行包"
    assert info["isFrozen"] is True
    assert "独立运行包" in info["detail"]


def test_version_frozen_with_metadata_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """独立运行 EXE 包含打包嵌入的 version.json 时能正确读取版本和 buildId。"""
    vjson = tmp_path / "version.json"
    vjson.write_text(
        json.dumps({
            "version": "1.5.0",
            "channel": "standalone-release",
            "buildId": "git-commit-abc1234",
        }),
        encoding="utf-8",
    )
    monkeypatch.delenv("VSE_TOOLBOX_VERSION", raising=False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr("core.version.app_root", lambda: tmp_path)

    info = get_app_version_info()
    assert info["displayVersion"] == "v1.5.0"
    assert info["channel"] == "standalone-release"
    assert info["buildId"] == "git-commit-abc1234"
    assert info["isFrozen"] is True
    assert "v1.5.0 (standalone-release)" in info["detail"]


def test_version_frozen_with_meipass_metadata(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """PyInstaller 单文件解压目录 (sys._MEIPASS) 下包含 version.json 时能正确识别。"""
    meipass_dir = tmp_path / "meipass_bundle"
    meipass_dir.mkdir()
    vjson = meipass_dir / "version.json"
    vjson.write_text(
        json.dumps({
            "version": "2.4.6",
            "channel": "standalone-exe",
            "buildId": "git-commit-test1234",
        }),
        encoding="utf-8-sig",
    )
    monkeypatch.delenv("VSE_TOOLBOX_VERSION", raising=False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(meipass_dir), raising=False)
    monkeypatch.setattr("core.version.app_root", lambda: tmp_path / "empty_app_root")

    info = get_app_version_info()
    assert info["displayVersion"] == "v2.4.6"
    assert info["channel"] == "standalone-exe"
    assert info["buildId"] == "git-commit-test1234"
    assert info["isFrozen"] is True


def test_version_file_with_utf8_bom(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """带 UTF-8 BOM (EF BB BF) 的 version.json 必须能被正确解析，不回退。"""
    vjson = tmp_path / "version.json"
    payload = json.dumps({
        "version": "3.1.0",
        "channel": "bom-channel",
        "buildId": "sha-bom-1234",
    }, ensure_ascii=False).encode("utf-8")
    vjson.write_bytes(b"\xef\xbb\xbf" + payload)

    monkeypatch.delenv("VSE_TOOLBOX_VERSION", raising=False)
    monkeypatch.setattr("core.version.app_root", lambda: tmp_path)

    info = get_app_version_info()
    assert info["displayVersion"] == "v3.1.0"
    assert info["rawVersion"] == "3.1.0"
    assert info["channel"] == "bom-channel"
    assert info["buildId"] == "sha-bom-1234"
    assert "v3.1.0 (bom-channel)" in info["detail"]


def test_version_file_without_bom(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """无 BOM 的 UTF-8 version.json 能被正确解析。"""
    vjson = tmp_path / "version.json"
    payload = json.dumps({
        "version": "3.2.0",
        "channel": "standard-channel",
        "buildId": "sha-nobom-5678",
    }, ensure_ascii=False).encode("utf-8")
    vjson.write_bytes(payload)

    monkeypatch.delenv("VSE_TOOLBOX_VERSION", raising=False)
    monkeypatch.setattr("core.version.app_root", lambda: tmp_path)

    info = get_app_version_info()
    assert info["displayVersion"] == "v3.2.0"
    assert info["channel"] == "standard-channel"
    assert info["buildId"] == "sha-nobom-5678"


def test_version_file_invalid_json_fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """version.json 内容损坏时安全退化，不抛出异常。"""
    vjson = tmp_path / "version.json"
    vjson.write_text("{broken json content", encoding="utf-8")

    monkeypatch.delenv("VSE_TOOLBOX_VERSION", raising=False)
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    monkeypatch.setattr("core.version.app_root", lambda: tmp_path)

    info = get_app_version_info()
    assert info["displayVersion"] == "开发工作区"


def test_webui_spec_behavior_without_version_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """无 VSE_TOOLBOX_VERSION 时，spec 评估结果不含 version.json，且不打包工作区残留旧文件。"""
    spec_path = Path("VSE-WebUI.spec").resolve()
    spec_code = spec_path.read_text(encoding="utf-8")

    # 模拟工作区残留旧 version.json
    stale_vjson = tmp_path / "version.json"
    stale_vjson.write_text(json.dumps({"version": "9.9.9-stale"}), encoding="utf-8")

    monkeypatch.delenv("VSE_TOOLBOX_VERSION", raising=False)
    monkeypatch.chdir(tmp_path)

    class FakeAnalysis:
        def __init__(self, *args, **kwargs):
            self.datas = kwargs.get("datas", [])
            self.pure = []
            self.scripts = []
            self.binaries = []

    fake_globals = {
        "__file__": str(spec_path),
        "Analysis": FakeAnalysis,
        "PYZ": lambda *args, **kwargs: None,
        "EXE": lambda *args, **kwargs: None,
        "COLLECT": lambda *args, **kwargs: None,
    }
    exec(compile(spec_code, str(spec_path), "exec"), fake_globals)

    version_datas = fake_globals.get("version_datas", [])
    assert version_datas == [], "无版本环境变量时不应将任何 version.json 加入 datas"


def test_webui_spec_behavior_with_version_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """提供 VSE_TOOLBOX_VERSION 时，spec 生成临时 version.json 并在 datas 中携带，不污染工作区。"""
    spec_path = Path("VSE-WebUI.spec").resolve()
    spec_code = spec_path.read_text(encoding="utf-8")

    monkeypatch.setenv("VSE_TOOLBOX_VERSION", "2.1.0")
    monkeypatch.setenv("VSE_TOOLBOX_CHANNEL", "release-test")
    monkeypatch.setenv("VSE_TOOLBOX_BUILD_ID", "commit-8888")
    monkeypatch.chdir(tmp_path)

    class FakeAnalysis:
        def __init__(self, *args, **kwargs):
            self.datas = kwargs.get("datas", [])
            self.pure = []
            self.scripts = []
            self.binaries = []

    fake_globals = {
        "__file__": str(spec_path),
        "Analysis": FakeAnalysis,
        "PYZ": lambda *args, **kwargs: None,
        "EXE": lambda *args, **kwargs: None,
        "COLLECT": lambda *args, **kwargs: None,
    }
    exec(compile(spec_code, str(spec_path), "exec"), fake_globals)

    version_datas = fake_globals.get("version_datas", [])
    assert len(version_datas) == 1
    src_file, dest = version_datas[0]
    assert dest == "."
    src_path = Path(src_file)
    assert src_path.is_file()
    assert src_path.name == "version.json"
    data = json.loads(src_path.read_text(encoding="utf-8"))
    assert data["version"] == "2.1.0"
    assert data["channel"] == "release-test"
    assert data["buildId"] == "commit-8888"
    assert not (tmp_path / "version.json").exists(), "工作区根目录不应生成残留 version.json"


# ── 2. Web API 与前端模板集成测试 ──────────────────────────────────────────────


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FlaskClient:
    """创建隔离的 Web 测试客户端，严格保证不读写默认数据库。"""
    isolated_db_path = tmp_path / "isolated_version_test.db"
    db_instance = DatabaseManager(db_path=isolated_db_path)
    db_instance.init_database()

    monkeypatch.setattr(web_app, "DatabaseManager", lambda *args, **kwargs: db_instance)

    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


def test_api_version_endpoint(client: FlaskClient) -> None:
    """GET /api/version 返回合法的 JSON 结构与版本数据。"""
    resp = client.get("/api/version")
    assert resp.status_code == 200
    assert resp.headers.get("Cache-Control") == "no-store"
    data = resp.get_json()
    assert data["ok"] is True
    assert "displayVersion" in data["data"]
    assert "channel" in data["data"]
    assert "detail" in data["data"]


def test_dashboard_renders_usability_elements(client: FlaskClient) -> None:
    """首页 dashboard.html 正确渲染顶栏会话徽章、版本展示及原位登录对话框。"""
    resp = client.get("/")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)

    # 1. 顶栏企业会话指示器
    assert 'class="global-session-status"' in html
    assert 'id="global-badge-aras"' in html
    assert 'id="global-badge-tdc"' in html
    assert 'id="global-login-btn"' in html

    # 2. 版本展示与维护详情入口
    assert 'id="app-version-chip"' in html
    assert 'id="version-detail-modal"' in html

    # 3. 原位登录对话框
    assert 'id="in-place-login-modal"' in html
    assert 'id="in-place-login-form"' in html
    assert 'id="in-place-login-save-vault"' in html

    # 4. 设置分层与高级维护折叠卡片
    assert 'id="settings-advanced-details"' in html
    assert '高级与维护设置（点击展开）' in html
    assert 'id="settings-field-temp-dir"' in html
    assert 'id="settings-field-diag-dir"' in html


def test_settings_patch_and_read_preserves_advanced_values(client: FlaskClient, tmp_path: Path) -> None:
    """设置分层后，通过 API 进行修改与查询能够完整保留高级与日常字段。"""
    get_resp = client.get("/api/settings")
    assert get_resp.status_code == 200
    initial_settings = get_resp.get_json()["data"]["settings"]
    assert "archiveDirectory" in initial_settings
    assert "temporaryDirectory" in initial_settings
    assert "retryCount" in initial_settings

    my_archive = tmp_path / "my_archive"
    my_archive.mkdir(parents=True, exist_ok=True)

    # 仅修改日常目录
    patch_resp = client.patch(
        "/api/settings",
        json={"archiveDirectory": str(my_archive)},
        headers={"X-Forwarded-For": "127.0.0.1"},
    )
    assert patch_resp.status_code == 200
    updated = patch_resp.get_json()["data"]["settings"]
    assert Path(updated["archiveDirectory"]).resolve() == my_archive.resolve()
    # 其它高级字段未受损
    assert updated["temporaryDirectory"] == initial_settings.get("temporaryDirectory", "")
    assert updated["retryCount"] == initial_settings.get("retryCount", 2)


def test_domain_login_validation_and_safety(client: FlaskClient) -> None:
    """登录接口空参数返回 400/422，不泄漏凭据。"""
    resp = client.post(
        "/api/settings/domain-login",
        json={"username": "", "password": ""},
        headers={"X-Forwarded-For": "127.0.0.1"},
    )
    assert resp.status_code in (400, 422)
    data = resp.get_json()
    assert data["ok"] is False


def test_settings_patch_does_not_mutate_default_database(client: FlaskClient, tmp_path: Path) -> None:
    """回归保障：设置更新操作必须写入隔离的 tmp 数据库，严禁写入默认的 data/vse_toolbox.db。"""
    from core.config import DB_PATH

    default_db_mtime_before = DB_PATH.stat().st_mtime if DB_PATH.exists() else None

    my_archive = tmp_path / "safety_check_archive"
    my_archive.mkdir(parents=True, exist_ok=True)

    resp = client.patch(
        "/api/settings",
        json={"archiveDirectory": str(my_archive)},
        headers={"X-Forwarded-For": "127.0.0.1"},
    )
    assert resp.status_code == 200

    if DB_PATH.exists() and default_db_mtime_before is not None:
        assert DB_PATH.stat().st_mtime == default_db_mtime_before, (
            "FATAL: Default database data/vse_toolbox.db was modified during test run!"
        )
