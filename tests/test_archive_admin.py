# -*- coding: utf-8 -*-
"""
tests/test_archive_admin.py — 归档任务配置管理与安全审计契约测试

覆盖验收标准:
1. 断言 schema 版本为 3，且 scheduled_archive_config_audit 表与索引存在
2. 成功更新覆盖: enable, alias configured 布尔, filters, 嵌套 output_subdir,
   固定 60 分钟 interval, needs_attention 状态, 乐观 updatedAt 变更, 无秘钥审计
3. 省略 alias 保留原值, null 仅在 disabled 时清空, enabled 缺失 alias 时拒绝
4. 过期 updatedAt, 活跃租约, 未知 job, 非法 actor, 非 bool enabled, 超大 filters,
   非 string/list 过滤值, 嵌套对象, 敏感过滤键名, 不安全输出路径, 非法 alias 在前置校验拒绝,
   保证零配置与零审计变更
5. No-op 幂等更新不写审计且保持 updatedAt 不变
6. 审计查询严格受界 (1~500), 绝不包含 credential_ref, alias 值, lease_token, filter 值或绝对路径
7. 已有的 last_success_at 跨配置更新完整保留
8. 遵循 pytest 参数化与共享 helper
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

import pytest

from core.archive_store import ArchiveSafetyError
from core.db_manager import (
    ARCHIVE_CREDENTIAL_UNCHANGED,
    CURRENT_SCHEMA_VERSION,
    ArchiveJobNotReadyError,
    ArchiveLeaseBusyError,
    DatabaseManager,
)


@pytest.fixture()
def db(tmp_path: Path) -> DatabaseManager:
    """返回已初始化的隔离 SQLite DatabaseManager。"""
    manager = DatabaseManager(db_path=tmp_path / "admin_test.db")
    manager.init_database()
    return manager


def _fake_alias(prefix: str = "cred_alias") -> str:
    """生成动态假凭据别名，不涉及任何外部或真实凭据服务。"""
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _get_raw_job(db: DatabaseManager, job_key: str) -> dict[str, Any]:
    """获取原始数据库中的 job 行数据。"""
    with db.get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM scheduled_archive_jobs WHERE job_key = ?",
            (job_key,),
        ).fetchone()
    assert row is not None, f"任务 {job_key} 不存在"
    return dict(row)


def _get_raw_audits(db: DatabaseManager, job_key: str | None = None) -> list[dict[str, Any]]:
    """获取原始数据库中的审计记录。"""
    with db.get_connection() as conn:
        if job_key:
            rows = conn.execute(
                "SELECT * FROM scheduled_archive_config_audit WHERE job_key = ? ORDER BY id ASC",
                (job_key,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM scheduled_archive_config_audit ORDER BY id ASC",
            ).fetchall()
    return [dict(r) for r in rows]


# ── 1. Schema 契约与表结构断言 ──────────────────────────────────────────────


def test_archive_admin_schema_and_audit_table_exists(db: DatabaseManager) -> None:
    """断言 schema 版本为 3 且 scheduled_archive_config_audit 表与索引存在。"""
    assert CURRENT_SCHEMA_VERSION == 3

    with db.get_connection() as conn:
        user_version = conn.execute("PRAGMA user_version").fetchone()[0]
        assert user_version == 3

    assert db.table_exists("scheduled_archive_config_audit")

    with db.get_connection() as conn:
        cols = {row["name"] for row in conn.execute("PRAGMA table_info(scheduled_archive_config_audit)")}
        assert {"id", "job_id", "job_key", "actor", "event_type", "changes_json", "created_at"}.issubset(cols)

        indices = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name = 'scheduled_archive_config_audit'"
            )
        }
        assert "idx_archive_config_audit_job" in indices


# ── 2. 成功更新全生命周期与无秘钥审计 ──────────────────────────────────────────


def test_successful_update_lifecycle_and_audit(db: DatabaseManager) -> None:
    """断言成功更新覆盖各字段、固定 60 分钟 interval、needs_attention 状态及 secret-free 审计。"""
    job_key = "aras_ewo"
    initial_job = _get_raw_job(db, job_key)
    initial_updated_at = str(initial_job["updated_at"])
    alias = _fake_alias("ewo_secret_alias")
    filters = {"model": "EP35", "status": "active", "tags": ["prod", "v2"]}
    subdir = "aras/nested/reports_v2"

    res = db.update_archive_job_config(
        job_key,
        enabled=True,
        credential_ref=alias,
        filters=filters,
        output_subdir=subdir,
        expected_updated_at=initial_updated_at,
        actor="local_web",
    )

    # 1. 验证方法返回值
    assert res["job_key"] == job_key
    assert res["enabled"] is True
    assert res["credential_configured"] is True
    assert "credential_ref" not in res, "返回值严禁泄露 credential_ref"
    assert "lease_token" not in res, "返回值严禁泄露 lease_token"
    assert res["interval_minutes"] == 60, "interval 必须固定为 60 分钟"
    assert res["output_subdir"] == subdir
    assert res["filters_json"] == json.dumps(filters, sort_keys=True, separators=(",", ":"))
    assert res["sync_state"] == "needs_attention", "启用后 sync_state 应迁移至 needs_attention"
    assert res["updated_at"] != initial_updated_at

    # 2. 验证数据库底层行
    raw_job = _get_raw_job(db, job_key)
    assert raw_job["enabled"] == 1
    assert raw_job["credential_ref"] == alias
    assert raw_job["interval_minutes"] == 60
    assert raw_job["sync_state"] == "needs_attention"
    assert raw_job["output_subdir"] == subdir

    # 3. 验证审计表记录
    audits = _get_raw_audits(db, job_key)
    assert len(audits) == 1
    audit = audits[0]
    assert audit["job_id"] == initial_job["id"]
    assert audit["job_key"] == job_key
    assert audit["actor"] == "local_web"
    assert audit["event_type"] == "configuration_updated"

    changes = json.loads(audit["changes_json"])
    assert changes["credentialConfigured"] is True
    assert set(changes["fields"]) == {"credentialRef", "enabled", "filters", "outputSubdir"}

    # 4. 绝密性断言: 审计内容绝不包含 alias 字符串、过滤键值或输出路径
    raw_audit_str = json.dumps(audit)
    assert alias not in raw_audit_str, "审计日志严禁记录凭据别名具体字符串"
    for secret_val in ["EP35", "active", "prod", "v2", "reports_v2", "nested"]:
        assert secret_val not in raw_audit_str, f"审计日志严禁记录参数或路径具体值: {secret_val}"


# ── 3. Alias 省略、清空与缺失约束 ───────────────────────────────────────────


def test_omitted_alias_preserves_existing_configured_alias(db: DatabaseManager) -> None:
    """断言省略 credential_ref (默认 ARCHIVE_CREDENTIAL_UNCHANGED) 保留已配置的 alias。"""
    job_key = "tdc_sor"
    initial_job = _get_raw_job(db, job_key)
    alias = _fake_alias("sor_alias")

    # 先初始化配置 alias
    res1 = db.update_archive_job_config(
        job_key,
        enabled=True,
        credential_ref=alias,
        filters={"phase": "T2"},
        output_subdir="tdc/sor",
        expected_updated_at=str(initial_job["updated_at"]),
        actor="cli",
    )
    assert res1["credential_configured"] is True

    # 再次更新仅修改 filters，省略 credential_ref
    res2 = db.update_archive_job_config(
        job_key,
        enabled=True,
        filters={"phase": "T3"},
        output_subdir="tdc/sor",
        expected_updated_at=res1["updated_at"],
        actor="cli",
    )
    assert res2["credential_configured"] is True

    # 验证底层 alias 未被修改
    raw_job = _get_raw_job(db, job_key)
    assert raw_job["credential_ref"] == alias

    # 验证第二次审计记录中的 fields 不包含 credentialRef
    audits = _get_raw_audits(db, job_key)
    assert len(audits) == 2
    second_changes = json.loads(audits[1]["changes_json"])
    assert second_changes["fields"] == ["filters"]
    assert second_changes["credentialConfigured"] is True


def test_null_alias_clears_only_when_disabled(db: DatabaseManager) -> None:
    """断言 disabled 任务传入 credential_ref=None 可清空别名，而 enabled 传 null 被拒绝。"""
    job_key = "aras_paa"
    initial_job = _get_raw_job(db, job_key)
    alias = _fake_alias("paa_alias")

    # 1. 先配置启用
    res1 = db.update_archive_job_config(
        job_key,
        enabled=True,
        credential_ref=alias,
        filters={},
        output_subdir="",
        expected_updated_at=str(initial_job["updated_at"]),
        actor="local_web",
    )
    assert res1["credential_configured"] is True

    # 2. 禁用且传入 credential_ref=None -> 成功清空别名
    res2 = db.update_archive_job_config(
        job_key,
        enabled=False,
        credential_ref=None,
        filters={},
        output_subdir="",
        expected_updated_at=res1["updated_at"],
        actor="local_web",
    )
    assert res2["enabled"] is False
    assert res2["credential_configured"] is False
    assert res2["sync_state"] == "idle", "禁用后 sync_state 应迁移至 idle"

    raw_job = _get_raw_job(db, job_key)
    assert raw_job["credential_ref"] is None

    # 3. 试图在 enabled=True 时传入 credential_ref=None -> 抛出 ArchiveJobNotReadyError 且零突变
    _assert_zero_mutation(
        db,
        lambda: db.update_archive_job_config(
            job_key,
            enabled=True,
            credential_ref=None,
            filters={},
            output_subdir="",
            expected_updated_at=res2["updated_at"],
            actor="local_web",
        ),
        ArchiveJobNotReadyError,
        match="requires a credential reference alias",
    )


def test_enabled_without_alias_on_unconfigured_job_rejected(db: DatabaseManager) -> None:
    """断言在未配置凭据的任务上启用且不传 alias 时被拒绝且零突变。"""
    job_key = "aras_ncr_progress"
    initial_job = _get_raw_job(db, job_key)
    assert initial_job["credential_ref"] is None

    _assert_zero_mutation(
        db,
        lambda: db.update_archive_job_config(
            job_key,
            enabled=True,
            filters={},
            output_subdir="",
            expected_updated_at=str(initial_job["updated_at"]),
            actor="cli",
        ),
        ArchiveJobNotReadyError,
        match="requires a credential reference alias",
    )


# ── 4. 幂等 No-op 更新 ───────────────────────────────────────────────────────


def test_noop_update_writes_no_audit_and_retains_updated_at(db: DatabaseManager) -> None:
    """断言无任何字段变更的更新不写审计且保留 updated_at。"""
    job_key = "tdc_data_model"
    initial_job = _get_raw_job(db, job_key)
    initial_updated_at = str(initial_job["updated_at"])

    # 默认初始配置上的 No-op
    res = db.update_archive_job_config(
        job_key,
        enabled=False,
        filters={},
        output_subdir="",
        expected_updated_at=initial_updated_at,
        actor="cli",
    )
    assert res["updated_at"] == initial_updated_at
    assert len(_get_raw_audits(db, job_key)) == 0

    # 先做一次有效变更
    alias = _fake_alias("dm_alias")
    res1 = db.update_archive_job_config(
        job_key,
        enabled=True,
        credential_ref=alias,
        filters={"category": "exterior"},
        output_subdir="tdc/dm",
        expected_updated_at=initial_updated_at,
        actor="cli",
    )
    assert len(_get_raw_audits(db, job_key)) == 1
    updated_at_after_change = res1["updated_at"]

    # 再次传入完全相同配置（省略 alias）
    res2 = db.update_archive_job_config(
        job_key,
        enabled=True,
        credential_ref=ARCHIVE_CREDENTIAL_UNCHANGED,
        filters={"category": "exterior"},
        output_subdir="tdc/dm",
        expected_updated_at=updated_at_after_change,
        actor="local_web",
    )
    assert res2["updated_at"] == updated_at_after_change
    assert len(_get_raw_audits(db, job_key)) == 1, "No-op 更新绝不能产生新的审计记录"


# ── 5. last_success_at 保持约束 ──────────────────────────────────────────────


def test_last_success_at_preserved_across_config_changes(db: DatabaseManager) -> None:
    """断言已有 last_success_at 在多次配置变更中被完整保留。"""
    job_key = "aras_ncr_detail"
    fixed_success_time = "2026-08-20T15:30:00.123456Z"

    with db.get_connection() as conn:
        conn.execute(
            "UPDATE scheduled_archive_jobs SET last_success_at = ? WHERE job_key = ?",
            (fixed_success_time, job_key),
        )

    initial_job = _get_raw_job(db, job_key)
    assert initial_job["last_success_at"] == fixed_success_time

    # 1. 启用任务
    alias = _fake_alias("ncr_detail_alias")
    res1 = db.update_archive_job_config(
        job_key,
        enabled=True,
        credential_ref=alias,
        filters={"severity": "high"},
        output_subdir="aras/ncr",
        expected_updated_at=str(initial_job["updated_at"]),
        actor="local_web",
    )
    assert res1["last_success_at"] == fixed_success_time
    assert _get_raw_job(db, job_key)["last_success_at"] == fixed_success_time

    # 2. 禁用任务
    res2 = db.update_archive_job_config(
        job_key,
        enabled=False,
        filters={},
        output_subdir="",
        expected_updated_at=res1["updated_at"],
        actor="cli",
    )
    assert res2["last_success_at"] == fixed_success_time
    assert _get_raw_job(db, job_key)["last_success_at"] == fixed_success_time


# ── 6. 负向边界测试：前置拒绝与零配置/零审计突变 ──────────────────────────────


def _assert_zero_mutation(
    db: DatabaseManager,
    call_fn: Any,
    expected_exc: type[Exception],
    match: str | None = None,
) -> None:
    """辅助检查: 捕获预期异常并断言 scheduled_archive_jobs 与 audit 表零变更。"""
    with db.get_connection() as conn:
        before_all_jobs = conn.execute("SELECT * FROM scheduled_archive_jobs ORDER BY id").fetchall()
        before_audits = conn.execute("SELECT * FROM scheduled_archive_config_audit ORDER BY id").fetchall()

    if match:
        with pytest.raises(expected_exc, match=match):
            call_fn()
    else:
        with pytest.raises(expected_exc):
            call_fn()

    with db.get_connection() as conn:
        after_all_jobs = conn.execute("SELECT * FROM scheduled_archive_jobs ORDER BY id").fetchall()
        after_audits = conn.execute("SELECT * FROM scheduled_archive_config_audit ORDER BY id").fetchall()

    assert [dict(r) for r in before_all_jobs] == [dict(r) for r in after_all_jobs], "任务配置表发生了意外突变"
    assert [dict(r) for r in before_audits] == [dict(r) for r in after_audits], "审计表发生了意外突变"


@pytest.mark.parametrize(
    "invalid_filters",
    [
        {123: "val"},  # 非 string 键
        {"key": 12345},  # 非 string/list 值 (int)
        {"key": True},  # 非 string/list 值 (bool)
        {"key": 3.14},  # 非 string/list 值 (float)
        {"key": {"nested": "dict"}},  # 嵌套 dict
        {"key": [{"nested": "in_list"}]},  # list 内嵌套 dict
        {"key": [1, 2, 3]},  # list 内包含非 string
        {"authorization": "Bearer xxx"},  # 敏感键名 authorization
        {"AUTH_TOKEN": "secret"},  # 敏感键名 token
        {"cookie": "session=123"},  # 敏感键名 cookie
        {"user_password": "p"},  # 敏感键名 password
        {"client_secret": "s"},  # 敏感键名 secret
        {"my_credential": "c"},  # 敏感键名 credential
        {"user_session": "sess"},  # 敏感键名 session
        {"csrf_token": "token"},  # 敏感键名 csrf
        {"": "empty_key"},  # 空键名
        {"   ": "whitespace_key"},  # 空白键名
        {"oversize": "a" * (17 * 1024)},  # 超过 16KB 限制
    ],
)
def test_rejected_invalid_filters(db: DatabaseManager, invalid_filters: Any) -> None:
    """断言各种非法/敏感/超大 filters 被拒绝且零突变。"""
    job_key = "aras_ewo"
    job = _get_raw_job(db, job_key)

    _assert_zero_mutation(
        db,
        lambda: db.update_archive_job_config(
            job_key,
            enabled=False,
            filters=invalid_filters,
            output_subdir="",
            expected_updated_at=str(job["updated_at"]),
            actor="cli",
        ),
        ValueError,
    )


@pytest.mark.parametrize(
    "unsafe_subdir",
    [
        r"/absolute/unix/path",
        r"C:\absolute\windows\path",
        r"D:/absolute",
        r"\leading_backslash",
        r"folder/../escape",
        r"../escape",
        r"COM1",
        r"NUL",
        r"aux",
        r"lpt1",
        r"sub\backslash\sep",
        r"  leading_space",
        r"trailing_space  ",
        r"nested/./dot",
        r"nested/../escape",
        r"bad:colon",
        r"bad*star",
        r"bad?question",
    ],
)
def test_rejected_unsafe_output_subdirs(db: DatabaseManager, unsafe_subdir: str) -> None:
    """断言各种不安全/逃逸 output_subdir 被拒绝且零突变。"""
    job_key = "aras_ewo"
    job = _get_raw_job(db, job_key)

    _assert_zero_mutation(
        db,
        lambda: db.update_archive_job_config(
            job_key,
            enabled=False,
            filters={},
            output_subdir=unsafe_subdir,
            expected_updated_at=str(job["updated_at"]),
            actor="cli",
        ),
        ArchiveSafetyError,
    )


@pytest.mark.parametrize(
    "invalid_alias,expected_exc",
    [
        ("", ValueError),  # 空字符串
        ("   ", ValueError),  # 空白字符串
        ("alias\x00null", ValueError),  # 包含控制字符
        ("alias\nnewline", ValueError),  # 包含控制字符
        ("a" * 257, ValueError),  # 超过 256 字符
        (12345, TypeError),  # 非法类型 (int)
        (["alias_list"], TypeError),  # 非法类型 (list)
    ],
)
def test_rejected_invalid_aliases(db: DatabaseManager, invalid_alias: Any, expected_exc: type[Exception]) -> None:
    """断言各种非法格式的 credential_ref 被拒绝且零突变。"""
    job_key = "aras_ewo"
    job = _get_raw_job(db, job_key)

    _assert_zero_mutation(
        db,
        lambda: db.update_archive_job_config(
            job_key,
            enabled=False,
            credential_ref=invalid_alias,
            filters={},
            output_subdir="",
            expected_updated_at=str(job["updated_at"]),
            actor="cli",
        ),
        expected_exc,
    )


def test_rejected_stale_updated_at_optimistic_locking(db: DatabaseManager) -> None:
    """断言过期的 expected_updated_at 触发乐观锁冲突并拒绝。"""
    job_key = "aras_ewo"
    stale_time = "2020-01-01T00:00:00.000000Z"

    _assert_zero_mutation(
        db,
        lambda: db.update_archive_job_config(
            job_key,
            enabled=False,
            filters={},
            output_subdir="",
            expected_updated_at=stale_time,
            actor="cli",
        ),
        RuntimeError,
        match="has changed",
    )


def test_rejected_update_during_active_lease(db: DatabaseManager) -> None:
    """断言在租约活跃期间更新配置被拒绝且零突变。"""
    job_key = "aras_ewo"
    job = _get_raw_job(db, job_key)
    alias = _fake_alias("ewo_leased_alias")

    # 先正常启用
    db.update_archive_job_config(
        job_key,
        enabled=True,
        credential_ref=alias,
        filters={},
        output_subdir="",
        expected_updated_at=str(job["updated_at"]),
        actor="cli",
    )

    # 获取活跃租约
    lease = db.acquire_archive_job_lease(int(job["id"]), "sync_now", lease_seconds=900)
    assert lease["lease_token"] is not None

    current_job = _get_raw_job(db, job_key)
    # 尝试在租约有效期内更新 (即使 expected_updated_at 是最新的，也必须因 active lease 被拒绝)
    _assert_zero_mutation(
        db,
        lambda: db.update_archive_job_config(
            job_key,
            enabled=False,
            filters={},
            output_subdir="",
            expected_updated_at=str(current_job["updated_at"]),
            actor="cli",
        ),
        ArchiveLeaseBusyError,
        match="cannot change during an active lease",
    )


@pytest.mark.parametrize(
    "invalid_actor",
    ["", "admin", "root", "system", "web", "CLI", "LOCAL_WEB", 123, None],
)
def test_rejected_invalid_actor(db: DatabaseManager, invalid_actor: Any) -> None:
    """断言非 ('local_web', 'cli') 的 actor 被拒绝且零突变。"""
    job_key = "aras_ewo"
    job = _get_raw_job(db, job_key)

    _assert_zero_mutation(
        db,
        lambda: db.update_archive_job_config(
            job_key,
            enabled=False,
            filters={},
            output_subdir="",
            expected_updated_at=str(job["updated_at"]),
            actor=invalid_actor,
        ),
        ValueError,
    )


@pytest.mark.parametrize("non_bool_enabled", [0, 1, "true", "false", None, [True]])
def test_rejected_non_bool_enabled(db: DatabaseManager, non_bool_enabled: Any) -> None:
    """断言非 bool 类型的 enabled 抛出 TypeError 且零突变。"""
    job_key = "aras_ewo"
    job = _get_raw_job(db, job_key)

    _assert_zero_mutation(
        db,
        lambda: db.update_archive_job_config(
            job_key,
            enabled=non_bool_enabled,  # type: ignore[arg-type]
            filters={},
            output_subdir="",
            expected_updated_at=str(job["updated_at"]),
            actor="cli",
        ),
        TypeError,
        match="enabled must be a bool",
    )


def test_rejected_unknown_job_key(db: DatabaseManager) -> None:
    """断言不存在的 job_key 抛出 KeyError 且零突变。"""
    _assert_zero_mutation(
        db,
        lambda: db.update_archive_job_config(
            "unknown_non_existent_key",
            enabled=False,
            filters={},
            output_subdir="",
            expected_updated_at="2026-08-22T00:00:00.000Z",
            actor="cli",
        ),
        KeyError,
    )


# ── 7. 审计列表受界查询与隐私安全断言 ──────────────────────────────────────────


def test_audit_listing_bounds_and_privacy(db: DatabaseManager) -> None:
    """断言审计列表分页边界 (1~500)、job_key 过滤与全局不泄露敏感信息。"""
    job1 = "aras_ewo"
    job2 = "tdc_sor"

    alias1 = _fake_alias("audit_sec_alias_1")
    alias2 = _fake_alias("audit_sec_alias_2")

    # 对 job1 产生 3 次变更
    j1 = _get_raw_job(db, job1)
    res = db.update_archive_job_config(
        job1, enabled=True, credential_ref=alias1, filters={"mod": "alpha_filter_1"}, output_subdir="dir1_custom",
        expected_updated_at=str(j1["updated_at"]), actor="local_web",
    )
    res = db.update_archive_job_config(
        job1, enabled=True, filters={"mod": "beta_filter_2"}, output_subdir="dir2_custom",
        expected_updated_at=res["updated_at"], actor="cli",
    )
    db.update_archive_job_config(
        job1, enabled=False, filters={"mod": "gamma_filter_3"}, output_subdir="",
        expected_updated_at=res["updated_at"], actor="local_web",
    )

    # 对 job2 产生 2 次变更
    j2 = _get_raw_job(db, job2)
    res2 = db.update_archive_job_config(
        job2, enabled=True, credential_ref=alias2, filters={"team": "team_x_delta"}, output_subdir="dir_x_special",
        expected_updated_at=str(j2["updated_at"]), actor="cli",
    )
    db.update_archive_job_config(
        job2, enabled=True, filters={"team": "team_y_epsilon"}, output_subdir="dir_y_special",
        expected_updated_at=res2["updated_at"], actor="local_web",
    )

    # 1. 查询全部与 job 过滤
    all_audits = db.list_archive_config_audit(limit=100)
    assert len(all_audits) == 5

    j1_audits = db.list_archive_config_audit(job_key=job1, limit=100)
    assert len(j1_audits) == 3
    assert all(a["job_key"] == job1 for a in j1_audits)

    j2_audits = db.list_archive_config_audit(job_key=job2, limit=100)
    assert len(j2_audits) == 2
    assert all(a["job_key"] == job2 for a in j2_audits)

    # 2. 排序断言: ID 降序 (最新在前)
    ids = [a["id"] for a in all_audits]
    assert ids == sorted(ids, reverse=True)

    # 3. 边界限制 (limit clamp: min=1, max=500)
    clamped_min = db.list_archive_config_audit(limit=0)
    assert len(clamped_min) == 1

    clamped_negative = db.list_archive_config_audit(limit=-99)
    assert len(clamped_negative) == 1

    clamped_small = db.list_archive_config_audit(limit=2)
    assert len(clamped_small) == 2

    # 4. 隐私安全断言: 遍历所有记录，检查字典键名与内容
    allowed_keys = {"id", "job_id", "job_key", "actor", "event_type", "changes_json", "created_at"}
    distinctive_values = [
        alias1,
        alias2,
        "alpha_filter_1",
        "beta_filter_2",
        "gamma_filter_3",
        "team_x_delta",
        "team_y_epsilon",
        "dir1_custom",
        "dir2_custom",
        "dir_x_special",
        "dir_y_special",
    ]

    for record in all_audits:
        assert set(record.keys()) == allowed_keys
        assert "credential_ref" not in record
        assert "lease_token" not in record

        # 检查 changes_json
        changes = json.loads(record["changes_json"])
        assert set(changes.keys()) == {"fields", "credentialConfigured"}
        assert isinstance(changes["fields"], list)
        assert isinstance(changes["credentialConfigured"], bool)

        # 绝密性检查: 绝不包含别名具体值、filter 参数具体值、路径具体值
        serialized = json.dumps(record)
        for distinctive in distinctive_values:
            assert distinctive not in serialized, f"审计日志泄露了敏感/业务值: {distinctive}"


def test_audit_listing_large_dataset_clamped_to_500(db: DatabaseManager) -> None:
    """断言当审计记录超过 500 条时，list_archive_config_audit(limit=501+) 精确返回 500 条且 ID 降序。"""
    job_key = "aras_ewo"
    job = _get_raw_job(db, job_key)
    job_id = int(job["id"])

    # 批量直接插入 520 条审计记录
    total_records = 520
    rows = [
        (
            job_id,
            job_key,
            "cli",
            "configuration_updated",
            json.dumps({"fields": ["filters"], "credentialConfigured": True}, sort_keys=True),
        )
        for _ in range(total_records)
    ]

    with db.get_connection() as conn:
        conn.executemany(
            """
            INSERT INTO scheduled_archive_config_audit
                (job_id, job_key, actor, event_type, changes_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            rows,
        )

    # 1. 不带 job_key 过滤，请求 limit=501 与 limit=1000
    res_501 = db.list_archive_config_audit(limit=501)
    assert len(res_501) == 500, f"期望最多返回 500 条，实际返回 {len(res_501)} 条"
    ids_501 = [r["id"] for r in res_501]
    assert ids_501 == sorted(ids_501, reverse=True), "审计记录必须按 ID 降序排列"

    res_1000 = db.list_archive_config_audit(limit=1000)
    assert len(res_1000) == 500
    ids_1000 = [r["id"] for r in res_1000]
    assert ids_1000 == ids_501

    # 2. 带 job_key 过滤，请求 limit=600
    res_job_filtered = db.list_archive_config_audit(job_key=job_key, limit=600)
    assert len(res_job_filtered) == 500
    ids_filtered = [r["id"] for r in res_job_filtered]
    assert ids_filtered == sorted(ids_filtered, reverse=True)
