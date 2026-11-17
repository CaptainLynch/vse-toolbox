# -*- coding: utf-8 -*-
"""签署日报「加密表单」第 0 期：容器嗅探、reason 透传、部署清单自检。

口径（docs/PLAN_20261111_SIGNDAILY_ENCRYPTED.md §5）：只用合成样本，不提交
真实加密件；任何文案都不得回显文件头十六进制；嗅探只做前缀匹配，**不**探测
偏移 1024 处是否为 PK、不剥容器头（那等于实现解密）。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.deploy_manifest import (
    MANIFEST_NAME,
    ManifestCheck,
    build_manifest,
    is_containerized_file,
    verify_manifest,
    write_manifest,
)
from host.registry import PluginRegistry, _containerized_source_hint
from services.tdc_official_rows import (
    OfficialWorkbookContractError,
    OfficialWorkbookUnreadable,
    official_contract_headers,
    read_official_tdc_rows,
)
from services.xlsx_preview import (
    ENCRYPTED_CONTAINER_SIGNATURES,
    SNIFF_BYTES,
    XLSXEncryptedContent,
    XLSXPreviewError,
    read_xlsx_preview,
    sniff_file_kind,
)
from tests.test_ewo_official_rows import write_workbook

CONTAINER_HEAD = ENCRYPTED_CONTAINER_SIGNATURES[0]
DATA_MODEL = "data_model"


def _container_bytes(payload: bytes = b"plaintext workbook") -> bytes:
    """容器样本：16 字节魔数 + 1024 字节头 + 正文（不做任何解密）。"""
    return CONTAINER_HEAD + bytes(1024 - SNIFF_BYTES) + payload


# ── 嗅探 ────────────────────────────────────────────────────────────


def test_sniff_container_signature_is_encrypted_container() -> None:
    assert sniff_file_kind(CONTAINER_HEAD + b"\x00" * 64, 80) == "encrypted_container"


def test_sniff_random_head_is_unknown_binary() -> None:
    assert sniff_file_kind(bytes(range(1, 40)), 39) == "unknown_binary"


def test_sniff_ole2_head_is_ole_container() -> None:
    head = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 24
    assert sniff_file_kind(head, len(head)) == "ole_container"


@pytest.mark.parametrize(
    "head, size",
    [
        (b"", 0),
        (b"PK", 2),
        (b"PK\x03\x04", 4),
        (b"PK\x03\x04" + b"\x00" * 12, SNIFF_BYTES - 1),
    ],
)
def test_sniff_empty_or_truncated(head: bytes, size: int) -> None:
    assert sniff_file_kind(head, size) == "empty_or_truncated"


def test_read_preview_rejects_container_before_opening_zip(tmp_path: Path) -> None:
    target = tmp_path / "encrypted.xlsx"
    target.write_bytes(_container_bytes())
    with pytest.raises(XLSXEncryptedContent) as caught:
        read_xlsx_preview(target)
    assert caught.value.reason == "encrypted_container"


def test_read_preview_truncated_zip_reason_is_corrupt_zip(tmp_path: Path) -> None:
    target = tmp_path / "broken.xlsx"
    target.write_bytes(b"PK\x03\x04" + b"\x00" * 200)
    with pytest.raises(XLSXPreviewError) as caught:
        read_xlsx_preview(target)
    assert caught.value.reason == "corrupt_zip"


def test_read_preview_ole_and_unknown_reasons(tmp_path: Path) -> None:
    ole = tmp_path / "legacy.xls"
    ole.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 300)
    with pytest.raises(XLSXPreviewError) as caught:
        read_xlsx_preview(ole)
    assert caught.value.reason == "ole_container"

    junk = tmp_path / "junk.xlsx"
    junk.write_bytes(bytes(range(64)) * 4)
    with pytest.raises(XLSXPreviewError) as caught:
        read_xlsx_preview(junk)
    assert caught.value.reason == "unknown_binary"


def test_container_file_is_detected_by_shared_helper(tmp_path: Path) -> None:
    target = tmp_path / "x.bin"
    target.write_bytes(_container_bytes())
    assert is_containerized_file(target) is True


# ── reason 透传（官方行读取） ───────────────────────────────────────


def test_official_rows_encrypted_reason_survives(tmp_path: Path) -> None:
    target = tmp_path / "encrypted.xlsx"
    target.write_bytes(_container_bytes())
    with pytest.raises(OfficialWorkbookUnreadable) as caught:
        read_official_tdc_rows(target, DATA_MODEL, max_rows=100)
    assert caught.value.reason == "encrypted_container"


def test_official_rows_header_drift_reports_schema_mismatch(tmp_path: Path) -> None:
    header = list(official_contract_headers(DATA_MODEL))
    header[2] = header[2] + "(旧模板)"
    target = write_workbook(tmp_path / "drift.xlsx", header, [[""] * len(header)])
    with pytest.raises(OfficialWorkbookContractError) as caught:
        read_official_tdc_rows(target, DATA_MODEL, max_rows=100)
    assert caught.value.reason == "schema_mismatch"
    assert caught.value.col_index == 2


def test_official_rows_missing_columns_report_schema_mismatch(tmp_path: Path) -> None:
    header = list(official_contract_headers(DATA_MODEL))[:-1]
    target = write_workbook(tmp_path / "short.xlsx", header, [[""] * len(header)])
    with pytest.raises(OfficialWorkbookContractError) as caught:
        read_official_tdc_rows(target, DATA_MODEL, max_rows=100)
    assert caught.value.reason == "schema_mismatch"
    assert caught.value.col_index == len(header)


# ── 部署清单自检 ───────────────────────────────────────────────────


def _deploy_tree(root: Path) -> Path:
    (root / "plugins" / "demo").mkdir(parents=True)
    (root / "plugins" / "demo" / "plugin.json").write_text("{}", encoding="utf-8")
    (root / "plugins" / "demo" / "backend.py").write_text(
        "def register(host):\n    return None\n", encoding="utf-8"
    )
    (root / "web" / "static").mkdir(parents=True)
    (root / "web" / "static" / "app.js").write_text("export const a = 1;\n", encoding="utf-8")
    return root


def test_manifest_roundtrip_is_ok_and_deterministic(tmp_path: Path) -> None:
    root = _deploy_tree(tmp_path)
    first = write_manifest(root, version="9.9.9")
    payload = json.loads(first.read_text(encoding="utf-8"))
    assert payload["fileCount"] == 3
    assert payload["version"] == "9.9.9"
    assert build_manifest(root, version="9.9.9") == payload
    check = verify_manifest(root)
    assert check.status == "ok" and check.ok is True and check.checked == 3


def test_manifest_absent_is_not_a_failure(tmp_path: Path) -> None:
    check = verify_manifest(_deploy_tree(tmp_path))
    assert check.status == "absent"
    assert check.ok is True
    assert "未提供部署清单" in check.message


def test_manifest_detects_tampered_file(tmp_path: Path) -> None:
    root = _deploy_tree(tmp_path)
    write_manifest(root, version="9.9.9")
    (root / "web" / "static" / "app.js").write_text("export const a = 2;\n", encoding="utf-8")
    check = verify_manifest(root)
    assert check.status == "mismatch"
    assert check.mismatched == ("web/static/app.js",)
    assert "被改动" in check.message


def test_manifest_separates_containerized_from_tampered(tmp_path: Path) -> None:
    root = _deploy_tree(tmp_path)
    write_manifest(root, version="9.9.9")
    (root / "plugins" / "demo" / "backend.py").write_bytes(
        CONTAINER_HEAD + bytes(1024 - SNIFF_BYTES) + b"def register(host):\n    return None\n"
    )
    check = verify_manifest(root)
    assert check.status == "mismatch"
    assert check.containerized == ("plugins/demo/backend.py",)
    assert check.mismatched == ()
    assert check.blocked_plugin_ids() == frozenset({"demo"})
    assert "容器" in check.message


def test_manifest_warns_about_unlisted_plugin_sources(tmp_path: Path) -> None:
    root = _deploy_tree(tmp_path)
    write_manifest(root, version="9.9.9")
    (root / "plugins" / "demo" / "extra.py").write_text("x = 1\n", encoding="utf-8")
    check = verify_manifest(root)
    assert check.extra_plugins == ("plugins/demo/extra.py",)
    assert check.ok is True  # 多出来的文件只告警，不阻断加载


def test_manifest_itself_containerized_is_reported(tmp_path: Path) -> None:
    root = _deploy_tree(tmp_path)
    manifest = write_manifest(root, version="9.9.9")
    manifest.write_bytes(CONTAINER_HEAD + b"{}")
    check = verify_manifest(root)
    assert check.status == "mismatch"
    assert check.containerized == (MANIFEST_NAME,)


# ── 宿主插件加载器：容器化源码要说人话 ────────────────────────────


def test_containerized_plugin_source_gives_readable_error(tmp_path: Path) -> None:
    plugin_dir = _deploy_tree(tmp_path) / "plugins" / "demo"
    (plugin_dir / "backend.py").write_bytes(
        CONTAINER_HEAD + bytes(1024 - SNIFF_BYTES) + b"def register(host):\n    return None\n"
    )
    hint = _containerized_source_hint(
        plugin_dir, "backend", SyntaxError("source code string cannot contain null bytes")
    )
    assert hint is not None
    assert "容器化" in hint and "解压" in hint
    # 用户可见文案不得回显文件头十六进制
    assert CONTAINER_HEAD.hex() not in hint.lower()
    assert "17 da 5f" not in hint.lower()


def test_non_syntax_failure_is_not_blamed_on_deployment(tmp_path: Path) -> None:
    plugin_dir = _deploy_tree(tmp_path) / "plugins" / "demo"
    assert _containerized_source_hint(plugin_dir, "backend", RuntimeError("boom")) is None


def test_deploy_blocked_only_applies_to_bundled_plugins(tmp_path: Path) -> None:
    check = ManifestCheck(
        status="mismatch",
        ok=False,
        containerized=("plugins/demo/backend.py",),
        message="1 个文件被容器化或被改动",
    )
    registry = PluginRegistry([tmp_path / "plugins"], deploy_check=check)
    bundled = tmp_path / "plugins" / "demo"
    installed = tmp_path / "data" / "plugin-updates" / "demo"
    assert registry._deploy_blocked("demo", bundled) is not None
    assert registry._deploy_blocked("demo", installed) is None
    assert registry._deploy_blocked("other", bundled) is None


def test_healthy_manifest_never_blocks_plugins(tmp_path: Path) -> None:
    registry = PluginRegistry([tmp_path / "plugins"], deploy_check=ManifestCheck(status="ok", ok=True))
    assert registry._deploy_blocked("demo", tmp_path / "plugins" / "demo") is None

# ── 两处连接器：reason 不丢（第 0 期 §2.3） ─────────────────────────


def test_project_status_connector_keeps_unreadable_reason(tmp_path: Path, monkeypatch) -> None:
    from services import project_status_connectors as psc

    events: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        psc, "emit", lambda kind, payload, **kw: events.append((kind, payload))
    )
    target = tmp_path / "encrypted.xlsx"
    target.write_bytes(_container_bytes())

    rows, status = psc._read_official_snapshot_rows(target, DATA_MODEL)

    assert rows == ()
    assert status == psc.OFFICIAL_STATUS_UNAVAILABLE  # 不新增状态值
    payload = next(payload for kind, payload in events if kind == "tdc_official_rows_unavailable")
    assert payload == {"report_type": DATA_MODEL, "reason": "encrypted_container"}


def test_scheduled_archive_connector_keeps_unreadable_reason(tmp_path: Path, monkeypatch) -> None:
    from services import scheduled_archive_connectors as sac

    events: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        sac, "emit", lambda kind, payload, **kw: events.append((kind, payload))
    )
    target = tmp_path / "encrypted.xlsx"
    target.write_bytes(_container_bytes())

    assert sac._official_workbook_rows(target, DATA_MODEL) is None  # 仍回退列表
    payload = next(payload for kind, payload in events if kind == "tdc_official_rows_unavailable")
    assert payload == {"report_type": DATA_MODEL, "reason": "encrypted_container"}
