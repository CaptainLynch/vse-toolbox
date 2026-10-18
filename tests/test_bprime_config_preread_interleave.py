# -*- coding: utf-8 -*-
"""B′ P1c interleave：三投影策略读必须来自同一 DEFERRED 快照。

``ProjectStatusRepo.read_project_status_update_policy_snapshot`` 在
``_begin_read_snapshot`` 之后由 ``_read_policy_rows`` 依次读三个投影：

1. ``project_status_update_bindings``      → ``binding``
2. ``project_status_field_authority``      → ``authorities``
3. ``project_status_update_audit``         → ``latest_audit``

WAL 下读事务在读到第一行时即固定快照，随后另一个连接提交的策略变更不得
污染本次读的任何一个投影。接缝是确定的 ``set_trace_callback``：pysqlite 的
trace 回调在语句**执行前**触发，因此把提交点绑在「第 N 个投影的语句开始」
就等价于「前面的投影已经返回、后面的投影尚未执行」，全程不使用 sleep/轮询。
"""

from contextlib import contextmanager

import pytest

from services.project_status_updates import PROJECT_STATUS_FIELD_NAME_TO_API

DID = "VPI-T2-D5"

OLD_REVISION, NEW_REVISION = 7, 8
OLD_MODE, NEW_MODE = "hybrid", "automatic"
OLD_ENABLED, NEW_ENABLED = 0, 1
OLD_AUTHORITY, NEW_AUTHORITY = "manual", "automatic"
OLD_RESULT, NEW_RESULT = "skipped", "applied"
OLD_STAMP, NEW_STAMP = "2026-01-05 09:00:00", "2026-01-05 10:00:00"
AUTHORITY_FIELDS = ("owner", "progress")
API_AUTHORITY_FIELDS = tuple(PROJECT_STATUS_FIELD_NAME_TO_API[name] for name in AUTHORITY_FIELDS)
PROJECTIONS = ("binding", "authorities", "audit")
_MISSING = object()


def _statement_kind(sql):
    """把 trace 到的 SQL 归到投影名；读入口里的其它语句归为 other/existence。"""
    text = " ".join(sql.split())
    if text.upper().startswith("BEGIN DEFERRED"):
        return "begin_deferred"
    if "FROM project_status_update_bindings" in text:
        return "binding"
    if "FROM project_status_field_authority" in text:
        return "authorities"
    if "FROM project_status_update_audit" in text:
        return "audit"
    if "FROM project_status_deliverables" in text:
        return "existence"
    return "other"


def _commit_policy_change(get_connection):
    """独立连接、单次提交：绑定 + 字段归属 + 更新审计（等价策略保存的写入集）。"""
    with get_connection() as writer:
        writer.execute("BEGIN IMMEDIATE")
        writer.execute(
            "UPDATE project_status_update_bindings "
            "SET mode = ?, enabled = ?, external_key = ?, sync_config_revision = ?, "
            "updated_at = ? WHERE deliverable_id = ?",
            (NEW_MODE, NEW_ENABLED, "BPRIME-EXT-8", NEW_REVISION, NEW_STAMP, DID),
        )
        writer.execute(
            "UPDATE project_status_field_authority "
            "SET authority = ?, locked_at = NULL, updated_at = ? "
            "WHERE deliverable_id = ? AND field_name IN ('owner', 'progress')",
            (NEW_AUTHORITY, NEW_STAMP, DID),
        )
        writer.execute(
            "INSERT INTO project_status_update_audit "
            "(deliverable_id, trigger_type, source_type, external_version, "
            "proposed_changes_json, applied_changes_json, skipped_fields_json, "
            "result, error_summary, created_at) "
            "VALUES (?, 'sync_now', 'tdc', 'BPRIME-EXT-8', '{}', '{}', '{}', ?, NULL, ?)",
            (DID, NEW_RESULT, NEW_STAMP),
        )
        writer.commit()


@contextmanager
def _armed_read(db, trigger, writer=_commit_policy_change, after=None):
    """只给本次读的第一个连接装 trace 回调，命中 ``trigger`` 投影时提交一次。

    ``after`` 用于 GET 路径：补行阶段会先整读一遍三投影（此刻尚未开读事务），
    只有等到它出现之后命中的 ``trigger`` 才算落在正式读的区间里。
    """
    original_get = db.get_connection
    slot = db.__dict__.get("get_connection", _MISSING)
    state = {"armed": False, "fired": False, "error": None, "timeline": []}

    @contextmanager
    def get_connection(*args, **kwargs):
        with original_get(*args, **kwargs) as conn:
            if not state["armed"]:
                state["armed"] = True

                def on_sql(sql):
                    kind = _statement_kind(sql)
                    state["timeline"].append(kind)
                    if kind == trigger and not state["fired"] and (
                        after is None or after in state["timeline"]
                    ):
                        state["fired"] = True
                        try:
                            writer(original_get)
                        except BaseException as exc:  # 提交失败要显式暴露，不吞掉
                            state["error"] = exc
                        else:
                            state["timeline"].append("committed")

                conn.set_trace_callback(on_sql)
            yield conn

    db.get_connection = get_connection
    try:
        yield state
    finally:
        if slot is _MISSING:
            db.__dict__.pop("get_connection", None)
        else:
            db.__dict__["get_connection"] = slot


def _pick(value, old, new):
    """未知取值直接失败，避免「不认识的值也算旧版本」造成静默通过。"""
    assert value in (old, new), f"unexpected policy projection value: {value!r}"
    return "old" if value == old else "new"


def _policy_version(raw):
    """把三个投影各自映射到 old/new，逐投影留痕以便报告混合状态。"""
    binding, authorities, latest = raw["binding"], raw["authorities"], raw["latest_audit"]
    assert latest is not None, "latest audit projection is missing"
    by_name = {row["field_name"]: row["authority"] for row in authorities}
    return {
        "binding_revision": _pick(int(binding["sync_config_revision"]), OLD_REVISION, NEW_REVISION),
        "binding_mode": _pick(binding["mode"], OLD_MODE, NEW_MODE),
        "binding_enabled": _pick(int(binding["enabled"]), OLD_ENABLED, NEW_ENABLED),
        "binding_updated_at": _pick(binding["updated_at"], OLD_STAMP, NEW_STAMP),
        "authorities": _pick(
            tuple(by_name[name] for name in AUTHORITY_FIELDS),
            (OLD_AUTHORITY,) * len(AUTHORITY_FIELDS),
            (NEW_AUTHORITY,) * len(AUTHORITY_FIELDS),
        ),
        "latest_audit_result": _pick(latest["result"], OLD_RESULT, NEW_RESULT),
    }


def _uniform_version(raw):
    """一个返回对象只允许是完整的旧版本或完整的新版本。"""
    tags = _policy_version(raw)
    versions = set(tags.values())
    assert len(versions) == 1, f"policy read mixed versions across projections: {tags}"
    return versions.pop()


def _writer_state(db):
    """独立连接直读三张表：证明 interleave 的提交真的落库了。"""
    with db.get_connection() as conn:
        binding = conn.execute(
            "SELECT sync_config_revision, mode, enabled, updated_at "
            "FROM project_status_update_bindings WHERE deliverable_id = ?",
            (DID,),
        ).fetchone()
        authorities = {
            row["field_name"]: row["authority"]
            for row in conn.execute(
                "SELECT field_name, authority FROM project_status_field_authority "
                "WHERE deliverable_id = ?",
                (DID,),
            ).fetchall()
        }
        latest = conn.execute(
            "SELECT result FROM project_status_update_audit WHERE deliverable_id = ? "
            "ORDER BY id DESC LIMIT 1",
            (DID,),
        ).fetchone()
        return {
            "revision": int(binding["sync_config_revision"]),
            "mode": str(binding["mode"]),
            "enabled": int(binding["enabled"]),
            "updated_at": str(binding["updated_at"]),
            "authorities": tuple(authorities[name] for name in AUTHORITY_FIELDS),
            "result": str(latest["result"]),
        }


def _assert_old_baseline(db):
    """前提：WAL 生效、夹具是完整旧版本，并且读一次就是旧版本。"""
    with db.get_connection() as conn:
        journal = str(conn.execute("PRAGMA journal_mode").fetchone()[0]).lower()
        assert journal == "wal", journal
        exists = conn.execute(
            "SELECT 1 FROM project_status_deliverables WHERE id = ?", (DID,)
        ).fetchone()
        assert exists is not None
        audits = conn.execute(
            "SELECT COUNT(*) FROM project_status_update_audit WHERE deliverable_id = ?",
            (DID,),
        ).fetchone()[0]
        assert int(audits) == 1
    assert _writer_state(db) == {
        "revision": OLD_REVISION,
        "mode": OLD_MODE,
        "enabled": OLD_ENABLED,
        "updated_at": OLD_STAMP,
        "authorities": (OLD_AUTHORITY,) * len(AUTHORITY_FIELDS),
        "result": OLD_RESULT,
    }
    assert _uniform_version(db.read_project_status_update_policy_snapshot(DID)) == "old"


def _interleave_events(state):
    return [item for item in state["timeline"] if item in set(PROJECTIONS) | {"committed"}]


def test_interleave_commit_between_projections_returns_old_snapshot(bprime_audit_case):
    """第 2 个投影语句开始时提交：在飞的读仍返回完整旧版本。"""
    db = bprime_audit_case["db"]
    _assert_old_baseline(db)

    with _armed_read(db, trigger="authorities") as state:
        raw = db.read_project_status_update_policy_snapshot(DID)

    assert state["error"] is None
    assert state["fired"] is True
    # trace 在执行前触发 ⇒ 提交点严格落在「binding 已返回」与「authorities/audit 未执行」之间
    assert _interleave_events(state) == ["binding", "authorities", "committed", "audit"]
    assert "begin_deferred" in state["timeline"]

    tags = _policy_version(raw)
    assert set(tags.values()) == {"old"}, tags
    assert _uniform_version(raw) == "old"
    assert int(raw["binding"]["sync_config_revision"]) == OLD_REVISION
    assert {row["field_name"]: row["authority"] for row in raw["authorities"]}["progress"] == OLD_AUTHORITY
    assert raw["latest_audit"]["result"] == OLD_RESULT

    # 反向证据：这次提交不是空写，独立连接看到的是完整新版本
    assert _writer_state(db) == {
        "revision": NEW_REVISION,
        "mode": NEW_MODE,
        "enabled": NEW_ENABLED,
        "updated_at": NEW_STAMP,
        "authorities": (NEW_AUTHORITY,) * len(AUTHORITY_FIELDS),
        "result": NEW_RESULT,
    }


def test_interleave_next_read_returns_complete_new_snapshot(bprime_audit_case):
    """紧接着的下一次读返回完整新版本（旧快照不泄漏到后续读）。"""
    db = bprime_audit_case["db"]
    _assert_old_baseline(db)

    with _armed_read(db, trigger="authorities") as state:
        during = db.read_project_status_update_policy_snapshot(DID)
    assert state["error"] is None
    assert state["fired"] is True
    assert _uniform_version(during) == "old"

    after = db.read_project_status_update_policy_snapshot(DID)
    tags = _policy_version(after)
    assert set(tags.values()) == {"new"}, tags
    assert _uniform_version(after) == "new"

    binding = after["binding"]
    assert int(binding["sync_config_revision"]) == NEW_REVISION
    assert str(binding["mode"]) == NEW_MODE
    assert int(binding["enabled"]) == NEW_ENABLED
    assert str(binding["updated_at"]) == NEW_STAMP
    by_name = {row["field_name"]: row["authority"] for row in after["authorities"]}
    assert tuple(by_name[name] for name in AUTHORITY_FIELDS) == (NEW_AUTHORITY,) * len(AUTHORITY_FIELDS)
    assert after["latest_audit"]["result"] == NEW_RESULT

    # 新快照稳定：再读一次仍是同一版本，不会退回旧快照
    assert _uniform_version(db.read_project_status_update_policy_snapshot(DID)) == "new"


def test_interleave_never_mixes_versions_across_projections(bprime_audit_case):
    """最靠后的投影开始时提交：任一跨版本组合都必须被同一条不变量判为 mixed。"""
    db = bprime_audit_case["db"]
    _assert_old_baseline(db)

    with _armed_read(db, trigger="audit") as state:
        raw = db.read_project_status_update_policy_snapshot(DID)

    assert state["error"] is None
    assert state["fired"] is True
    # binding 与 authorities 已经返回，提交完成之后才执行 audit 投影
    assert _interleave_events(state) == ["binding", "authorities", "audit", "committed"]
    assert _uniform_version(raw) == "old"
    assert _policy_version(raw)["latest_audit_result"] == "old"

    # 反空断言：把任一投影换成新版本都必须触发 mixed 判定
    flips = {
        "binding": dict(raw, binding=dict(
            raw["binding"], sync_config_revision=NEW_REVISION, mode=NEW_MODE,
            enabled=NEW_ENABLED, updated_at=NEW_STAMP)),
        "authorities": dict(raw, authorities=[
            dict(row, authority=NEW_AUTHORITY) for row in raw["authorities"]]),
        "latest_audit": dict(raw, latest_audit=dict(raw["latest_audit"], result=NEW_RESULT)),
        "binding_stamp": dict(raw, binding=dict(raw["binding"], updated_at=NEW_STAMP)),
    }
    for name, candidate in flips.items():
        with pytest.raises(AssertionError) as caught:
            _uniform_version(candidate)
        assert "mixed versions" in str(caught.value), (name, str(caught.value))

    # 同一个判定器也必须接受完整新版本（不是恒真的「永远是旧」）
    assert _uniform_version(db.read_project_status_update_policy_snapshot(DID)) == "new"


def _api_version(policy):
    """服务层 API 形状的三投影版本映射；未知取值直接失败。"""
    tags = {
        "mode": _pick(policy["mode"], OLD_MODE, NEW_MODE),
        "enabled": _pick(int(bool(policy["enabled"])), OLD_ENABLED, NEW_ENABLED),
        "updated_at": _pick(policy["updatedAt"], OLD_STAMP, NEW_STAMP),
        "authorities": _pick(
            tuple(policy["fieldAuthority"][name] for name in API_AUTHORITY_FIELDS),
            (OLD_AUTHORITY,) * len(AUTHORITY_FIELDS),
            (NEW_AUTHORITY,) * len(AUTHORITY_FIELDS),
        ),
        "latest_result": _pick(policy["latestUpdate"]["result"], OLD_RESULT, NEW_RESULT),
    }
    versions = set(tags.values())
    assert len(versions) == 1, f"policy read mixed versions across projections: {tags}"
    return versions.pop()


def test_interleave_service_get_path_holds_snapshot_after_seeding(bprime_audit_case):
    """A77 首要入口：策略 GET（先补行、再开读事务）也必须整读同快照。

    预热调用一次以让 ``_ensure_project_status_policy`` 无行可补；此后连接不在
    事务中，因此 ``_begin_read_snapshot`` 必须恰好开一次 DEFERRED —— timeline
    里出现 ``begin_deferred`` 就是「GET 路径真的开了读事务」的证据。
    """
    db, service = bprime_audit_case["db"], bprime_audit_case["service"]
    assert _api_version(service.get_update_policy(DID)) == "old"
    _assert_old_baseline(db)

    with _armed_read(db, trigger="authorities", after="begin_deferred") as state:
        policy = service.get_update_policy(DID)

    assert state["error"] is None
    assert state["fired"] is True
    # 补行阶段会先整读一遍三投影（在事务外），DEFERRED 只为补行之后的正式读开一次
    assert state["timeline"].count("begin_deferred") == 1, state["timeline"]
    assert _interleave_events(state)[-3:] == ["authorities", "committed", "audit"], state["timeline"]
    assert _api_version(policy) == "old"
    assert policy["latestUpdate"]["result"] == OLD_RESULT

    # 独立连接已看到完整新版本；下一轮 GET 必须紧跟新快照，不回退
    assert _api_version(service.get_update_policy(DID)) == "new"
