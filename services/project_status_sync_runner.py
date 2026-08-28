# -*- coding: utf-8 -*-
"""
services/project_status_sync_runner.py — 独立同步运行器与 run_once 执行框架。

架构约束：
- 不 import Flask，不依赖 web/app.py。
- runner 不直接访问 DatabaseManager 的 get_connection 或编写 SQL；
  通过 DatabaseManager 和 ProjectStatusUpdateService 的公共方法操作。
- runner 不复制 M1 的字段归属、游标、审计或事务逻辑。
- connector 只返回标准化 ConnectorSnapshot，不写业务表/audit/run/artifact。
- 生产 registry 本轮不含真实 TDC/Aras connector；未注册 source_type 产生
  确定的 connector_unavailable 结果，不调用外部系统。
- 所有错误分类后经 redact_sensitive_text 限长，禁止输出 traceback 或原始响应。
- lease_token 只在调用链内短暂存在，不放入 dataclass repr、日志或结果对象。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol, Sequence

from core.db_manager import (
    DatabaseManager,
    SyncBindingNotReadyError,
    SyncLeaseBusyError,
    SyncLeaseLostError,
)
from core.redaction import redact_sensitive_text
from services.project_status_deliverable_analysis import (
    ProjectStatusDeliverableAnalysisService,
)
from services.project_status_updates import (
    ConnectorSnapshot,
    ProjectStatusUpdateService,
    SyncResult,
)

logger = logging.getLogger("vse_toolbox.sync_runner")

#: 文本限长。
_RUNNER_TEXT_LIMIT = 1000

#: 退出码定义（与 CLI 共享）。
EXIT_OK = 0
EXIT_FAILED = 1
EXIT_ATTENTION = 2
EXIT_INTERRUPTED = 130


def _sanitize(value: str) -> str:
    """脱敏并限长。"""
    return redact_sensitive_text(value, limit=_RUNNER_TEXT_LIMIT)


def _classify_exception(exc: BaseException) -> str:
    """将异常分类为稳定的非敏感错误类型代码。"""
    if isinstance(exc, SyncLeaseBusyError):
        return "lease_busy"
    if isinstance(exc, SyncLeaseLostError):
        return "lease_lost"
    if isinstance(exc, SyncBindingNotReadyError):
        return "binding_not_ready"
    if isinstance(exc, ConnectionError):
        return "connection_error"
    if isinstance(exc, TimeoutError):
        return "timeout"
    if isinstance(exc, ValueError):
        return "invalid_data"
    if isinstance(exc, KeyError):
        return "missing_entity"
    return "connector_error"


# ── 只读执行上下文 ──────────────────────────────────────────────


@dataclass(frozen=True)
class SyncBindingContext:
    """
    connector 执行所需的非敏感只读上下文。

    不含 lease_token、credential 值、Cookie、Authorization、session 或原始数据库行。
    deliverable_id 仅作只读上下文，最终写入由 binding_id 决定。
    """

    binding_id: int
    deliverable_id: str
    phase_id: str
    source_type: str
    external_key: str
    match_rule: Mapping[str, Any]
    mapping: Mapping[str, Any]
    cursor: Mapping[str, Any]
    expected_deliverable_updated_at: str
    run_id: int = 0
    credential_ref: str = ""


# ── Connector Protocol ──────────────────────────────────────────


class ProjectStatusConnector(Protocol):
    """
    连接器协议：只读抓取外部数据并返回标准化 ConnectorSnapshot。

    实现者不得访问 DatabaseManager，不得写业务表、audit、run 或 artifact。
    """

    def collect(self, context: SyncBindingContext) -> ConnectorSnapshot: ...


# ── Connector Registry ──────────────────────────────────────────


class ConnectorRegistry:
    """
    source_type 到 connector 的显式映射。

    不使用动态 import、eval、字符串类名或任意插件路径。
    未注册 source_type 返回 None，由 runner 产生 connector_unavailable 结果。
    """

    def __init__(self) -> None:
        self._connectors: dict[str, ProjectStatusConnector] = {}

    def register(
        self,
        source_type: str,
        connector: ProjectStatusConnector,
    ) -> None:
        self._connectors[source_type] = connector

    def get(self, source_type: str) -> ProjectStatusConnector | None:
        return self._connectors.get(source_type)

    @property
    def registered_types(self) -> tuple[str, ...]:
        return tuple(sorted(self._connectors))


# ── Dry-run readiness summary ───────────────────────────────────


@dataclass(frozen=True)
class BindingReadiness:
    """dry-run 中单个 binding 的就绪状态（只读，无租约）。"""

    binding_id: int
    deliverable_id: str
    source_type: str
    connector_available: bool
    binding_ready: bool = True


# ── Per-binding result ──────────────────────────────────────────


@dataclass(frozen=True)
class BindingRunResult:
    """
    单个 binding 的运行结果。

    不含 lease_token、credential_ref、cursor_json 原文或外部响应。
    """

    binding_id: int
    deliverable_id: str
    source_type: str
    outcome: str
    run_id: int | None = None
    final_state: str | None = None
    applied_fields: tuple[str, ...] = ()
    skipped_fields: Mapping[str, str] = field(default_factory=dict)
    error_type: str | None = None
    error_message: str | None = None


# ── Batch result ────────────────────────────────────────────────


@dataclass(frozen=True)
class RunOnceResult:
    """单次 run_once 的汇总结果。"""

    results: tuple[BindingRunResult, ...]
    readiness: tuple[BindingReadiness, ...] = ()
    dry_run: bool = False

    @property
    def exit_code(self) -> int:
        if self.dry_run:
            for item in self.readiness:
                if not item.connector_available or not item.binding_ready:
                    return EXIT_ATTENTION
            return EXIT_OK

        has_failed = False
        has_attention = False
        for r in self.results:
            if r.outcome == "failed" or r.final_state == "failed":
                has_failed = True
            elif r.final_state in ("needs_attention", "partial"):
                has_attention = True
        if has_failed:
            return EXIT_FAILED
        if has_attention:
            return EXIT_ATTENTION
        return EXIT_OK


# ── Runner ──────────────────────────────────────────────────────


class ProjectStatusSyncRunner:
    """
    独立同步运行器。

    每个 binding 独立运行；单个 binding 失败不阻断后续 binding。
    不实现常驻循环或 Flask scheduler；run_once 执行一次即返回。
    """

    def __init__(
        self,
        db: DatabaseManager,
        service: ProjectStatusUpdateService,
        registry: ConnectorRegistry,
        analysis_service: ProjectStatusDeliverableAnalysisService | None = None,
    ) -> None:
        self._db = db
        self._service = service
        self._registry = registry
        self._analysis_service = analysis_service or ProjectStatusDeliverableAnalysisService(db)

    def run_once(
        self,
        deliverable_id: str | None = None,
        dry_run: bool = False,
        trigger_type: str = "scheduled",
    ) -> RunOnceResult:
        """
        执行一次同步。

        Args:
            deliverable_id: 若提供则只运行该交付物的绑定。
            dry_run: 若为 True 则完全只读，不获取租约、不创建 run、不调用 connector。

        Returns:
            RunOnceResult 汇总。
        """
        if trigger_type not in {"scheduled", "sync_now"}:
            raise ValueError("unsupported project-status trigger_type")
        bindings = self._db.list_eligible_sync_bindings(deliverable_id)

        if deliverable_id is not None and not bindings:
            return RunOnceResult(results=(), dry_run=dry_run)

        if dry_run:
            return self._dry_run(bindings)

        results: list[BindingRunResult] = []
        for binding in bindings:
            try:
                result = self._run_single_binding(binding, trigger_type)
            except KeyboardInterrupt:
                raise
            except BaseException as exc:
                if isinstance(exc, (SystemExit, GeneratorExit)):
                    raise
                # 单个 binding 的未预期异常不阻断批次。
                error_type = _classify_exception(exc)
                sanitized = _sanitize(str(exc))
                result = BindingRunResult(
                    binding_id=int(binding["id"]),
                    deliverable_id=str(binding["deliverable_id"]),
                    source_type=str(binding["source_type"]),
                    outcome="failed",
                    final_state="failed",
                    error_type=error_type,
                    error_message=sanitized,
                )
            results.append(result)
        return RunOnceResult(results=tuple(results))

    def _dry_run(
        self,
        bindings: Sequence[dict[str, Any]],
    ) -> RunOnceResult:
        """完全只读的就绪检查：不获取租约、不创建 run、不调用 connector。"""
        readiness_items: list[BindingReadiness] = []
        for binding in bindings:
            connector = self._registry.get(str(binding["source_type"]))
            try:
                self._service.assert_sync_ready(str(binding["deliverable_id"]))
                binding_ready = True
            except (KeyError, SyncBindingNotReadyError):
                binding_ready = False
            readiness_items.append(
                BindingReadiness(
                    binding_id=int(binding["id"]),
                    deliverable_id=str(binding["deliverable_id"]),
                    source_type=str(binding["source_type"]),
                    connector_available=connector is not None,
                    binding_ready=binding_ready,
                )
            )
        return RunOnceResult(
            results=(),
            readiness=tuple(readiness_items),
            dry_run=True,
        )

    def _run_single_binding(
        self,
        binding: dict[str, Any],
        trigger_type: str,
    ) -> BindingRunResult:
        """运行单个 binding：获取租约 → start → collect → apply → 归纳结果。"""
        binding_id = int(binding["id"])
        deliverable_id = str(binding["deliverable_id"])
        source_type = str(binding["source_type"])

        connector = self._registry.get(source_type)
        if connector is None:
            return self._handle_connector_unavailable(
                binding_id, deliverable_id, source_type, trigger_type
            )

        # 获取租约。
        try:
            lease = self._service.acquire_sync_lease(
                deliverable_id,
                trigger_type,
            )
        except SyncLeaseBusyError:
            return BindingRunResult(
                binding_id=binding_id,
                deliverable_id=deliverable_id,
                source_type=source_type,
                outcome="busy",
                final_state="busy",
            )
        except SyncBindingNotReadyError as exc:
            return BindingRunResult(
                binding_id=binding_id,
                deliverable_id=deliverable_id,
                source_type=source_type,
                outcome="needs_attention",
                final_state="needs_attention",
                error_type="binding_not_ready",
                error_message=_sanitize(str(exc)),
            )
        except KeyError:
            return BindingRunResult(
                binding_id=binding_id,
                deliverable_id=deliverable_id,
                source_type=source_type,
                outcome="failed",
                final_state="failed",
                error_type="binding_not_ready",
                error_message=_sanitize("binding disappeared before lease acquisition"),
            )

        run_id = int(lease["run_id"])
        lease_token = lease["lease_token"]

        try:
            # leased → running。
            self._db.start_sync_run(binding_id, run_id, lease_token)

            # 构造只读上下文。
            try:
                credential_ref = self._db.get_sync_binding_credential_ref(binding_id)
            except SyncBindingNotReadyError:
                credential_ref = ""
            context = SyncBindingContext(
                binding_id=binding_id,
                deliverable_id=deliverable_id,
                phase_id=str(binding["phase_id"]),
                source_type=source_type,
                external_key=str(binding["external_key"] or ""),
                match_rule=_safe_json_loads(binding["match_rule_json"]),
                mapping=_safe_json_loads(binding["mapping_json"]),
                cursor=_safe_json_loads(binding["cursor_json"]),
                expected_deliverable_updated_at=str(
                    binding["deliverable_updated_at"]
                ),
                run_id=run_id,
                credential_ref=credential_ref,
            )

            # 在数据库事务外调用 connector。
            snapshot = connector.collect(context)

            # 交给统一服务提交。
            sync_result = self._service.apply_sync_update(
                binding_id,
                run_id,
                lease_token,
                snapshot,
                trigger_type,
            )
            if sync_result.final_state in {"success", "partial"} and snapshot.analysis_rows:
                analysis_mapping = context.match_rule.get("analysisMapping")
                try:
                    self._analysis_service.publish(
                        deliverable_id,
                        run_id,
                        snapshot.analysis_rows,
                        snapshot_at=snapshot.fetched_at,
                        mapping=(analysis_mapping if isinstance(analysis_mapping, Mapping) else None),
                    )
                except Exception as exc:
                    logger.warning(
                        "deliverable analysis cache publish failed for %s: %s",
                        deliverable_id,
                        _sanitize(str(exc)),
                    )
            return self._result_from_sync(
                binding_id, deliverable_id, source_type, sync_result
            )

        except SyncLeaseLostError:
            # 租约已丢失或过期：不再次尝试写入或释放其他运行器的租约。
            return BindingRunResult(
                binding_id=binding_id,
                deliverable_id=deliverable_id,
                source_type=source_type,
                outcome="failed",
                run_id=run_id,
                final_state="failed",
                error_type="lease_lost",
                error_message=_sanitize("lease expired or token mismatch"),
            )
        except KeyboardInterrupt:
            # 安全结束当前仍持有的 run，然后向上抛出。
            self._safe_finalize_interrupted(binding_id, run_id, lease_token)
            raise
        except BaseException as exc:  # noqa: BLE001 — connector 异常需隔离
            # 不吞掉 SystemExit/BaseException 以外的退出信号。
            if isinstance(exc, (SystemExit, GeneratorExit)):
                raise
            error_type = _classify_exception(exc)
            sanitized = _sanitize(str(exc))
            try:
                self._db.finalize_sync_failure(
                    binding_id,
                    run_id,
                    lease_token,
                    error_type=error_type,
                    sanitized_message=sanitized,
                    result_summary=_sanitize("connector failure"),
                )
            except Exception:
                pass  # 租约已失效或 DB 临时不可用，无法结束 run；由过期抢占回收。
            return BindingRunResult(
                binding_id=binding_id,
                deliverable_id=deliverable_id,
                source_type=source_type,
                outcome="failed",
                run_id=run_id,
                final_state="failed",
                error_type=error_type,
                error_message=sanitized,
            )

    def _handle_connector_unavailable(
        self,
        binding_id: int,
        deliverable_id: str,
        source_type: str,
        trigger_type: str,
    ) -> BindingRunResult:
        """
        source_type 未注册 connector 时的确定结果。

        创建 run 并安全结束为 needs_attention，不调用外部系统，
        不清除 last_success_at，不推进 cursor。
        """
        try:
            lease = self._service.acquire_sync_lease(
                deliverable_id, trigger_type
            )
        except SyncLeaseBusyError:
            return BindingRunResult(
                binding_id=binding_id,
                deliverable_id=deliverable_id,
                source_type=source_type,
                outcome="busy",
                final_state="busy",
            )
        except SyncBindingNotReadyError as exc:
            return BindingRunResult(
                binding_id=binding_id,
                deliverable_id=deliverable_id,
                source_type=source_type,
                outcome="needs_attention",
                final_state="needs_attention",
                error_type="binding_not_ready",
                error_message=_sanitize(str(exc)),
            )
        except KeyError:
            return BindingRunResult(
                binding_id=binding_id,
                deliverable_id=deliverable_id,
                source_type=source_type,
                outcome="failed",
                final_state="failed",
                error_type="binding_not_ready",
                error_message=_sanitize("binding disappeared before lease acquisition"),
            )

        run_id = int(lease["run_id"])
        lease_token = lease["lease_token"]
        try:
            self._db.finalize_sync_needs_attention(
                binding_id,
                run_id,
                lease_token,
                error_type="connector_unavailable",
                sanitized_message=_sanitize(
                    f"no connector registered for source_type={source_type}"
                ),
                result_summary=_sanitize("connector unavailable"),
            )
        except Exception:
            pass  # 租约已失效或 DB 临时不可用；由过期抢占回收。
        return BindingRunResult(
            binding_id=binding_id,
            deliverable_id=deliverable_id,
            source_type=source_type,
            outcome="needs_attention",
            run_id=run_id,
            final_state="needs_attention",
            error_type="connector_unavailable",
            error_message=_sanitize(
                f"no connector registered for source_type={source_type}"
            ),
        )

    def _safe_finalize_interrupted(
        self,
        binding_id: int,
        run_id: int,
        lease_token: str,
    ) -> None:
        """KeyboardInterrupt 时尝试以 sanitized interrupted 错误结束当前 run。"""
        try:
            self._db.finalize_sync_failure(
                binding_id,
                run_id,
                lease_token,
                error_type="interrupted",
                sanitized_message=_sanitize("run interrupted by user"),
                result_summary=_sanitize("interrupted"),
            )
        except Exception:
            pass  # 租约已失效或 DB 临时不可用；不阻碍 KeyboardInterrupt 上抛。

    @staticmethod
    def _result_from_sync(
        binding_id: int,
        deliverable_id: str,
        source_type: str,
        sync_result: SyncResult,
    ) -> BindingRunResult:
        """将 SyncResult 归纳为 BindingRunResult。"""
        outcome = "completed"
        if sync_result.final_state == "failed":
            outcome = "failed"
        elif sync_result.final_state in ("needs_attention", "partial"):
            outcome = sync_result.final_state
        return BindingRunResult(
            binding_id=binding_id,
            deliverable_id=deliverable_id,
            source_type=source_type,
            outcome=outcome,
            run_id=sync_result.run_id,
            final_state=sync_result.final_state,
            applied_fields=sync_result.applied_fields,
            skipped_fields=dict(sync_result.skipped_fields),
            error_message=sync_result.message,
        )


# ── 生产 registry ──────────────────────────────────────────────


def create_production_registry() -> ConnectorRegistry:
    """
    创建生产 connector registry。

    本轮不含真实 TDC/Aras connector；所有 source_type 均未注册，
    由 runner 产生 connector_unavailable 结果。M2B 将在此注册首个真实 connector。
    """
    from core.archive_store import ArchiveStore
    from core.credential_provider import WindowsCredentialManagerProvider
    from services.project_status_connectors import (
        ArasProjectStatusConnector,
        RetryingConnector,
        TDCProjectStatusConnector,
    )

    credentials = WindowsCredentialManagerProvider()
    archive = ArchiveStore()
    registry = ConnectorRegistry()
    registry.register(
        "aras", RetryingConnector(ArasProjectStatusConnector(credentials, archive))
    )
    registry.register(
        "tdc", RetryingConnector(TDCProjectStatusConnector(credentials, archive))
    )
    return registry


# ── 辅助 ────────────────────────────────────────────────────────


def _safe_json_loads(value: Any) -> Mapping[str, Any]:
    """安全 JSON 解析；非对象或解析失败返回空 dict，不崩溃或泄漏内容。"""
    import json

    if not isinstance(value, str) or not value:
        return {}
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return {}
    if isinstance(parsed, dict):
        return parsed
    return {}
