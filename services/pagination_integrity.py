# -*- coding: utf-8 -*-
"""分页与工作簿完整性契约（纯函数，无 IO）。

本模块是 `stop_reason` 词表与「元数据驱动分页」「官方工作簿准入」终局判定的
**唯一拥有者**：TDC 与 Aras 两个爬虫以及 ARAS 官方工作簿（NCR）的 `complete`
语义都必须经 `is_complete()` 派生，避免同一语义在多个爬虫里各自实现后漂移。

设计边界（架构约束，勿破）：
- 本模块只消费**簿记事实**（页号、页大小、声明总数/页数、累计数、去重后条数、
  重复数、上限；工作簿的读取/解析/跳过/未归类行数、表头契约与截断标志），
  **不消费任何业务字段语义**；业务身份属于 `services/project_status_records`，
  工作簿的行级业务解释属于 `services/aras_ncr_workbook`。
- 无第三方依赖，不 import 上层（web/、project_status_*），可被任意爬虫安全引用。
"""

from __future__ import annotations

from dataclasses import dataclass
import math

#: 证明「服务端声明的记录已全部取回」或「官方工作簿满足准入策略」的停机原因
#: （唯一权威定义）。
#:
#: 变更本集合等同于变更对外契约：`services/project_status_records`、
#: `services/project_status_connectors`、`web/app.py` 的准入门控都依赖它。
#:
#: 语义边界（勿混淆）：`complete` 只表示「满足准入策略」，**不等于**证明源端
#: 零丢失。官方工作簿（NCR）没有声明总数，因此 `workbook_rows` 只证明
#: 「表头契约成立 + 逐行归类无剩余 + 未被预览截断」。
COMPLETE_STOP_REASONS: frozenset[str] = frozenset(
    {"reported_pages", "reported_total", "empty_page", "short_page", "workbook_rows"}
)

#: 非终局状态：本页正常，继续请求下一页。
CONTINUE_STOP_REASON = "continue"


def is_complete(stop_reason: str) -> bool:
    """停机原因是否构成「已取完全部声明记录」的证明。"""
    return stop_reason in COMPLETE_STOP_REASONS


@dataclass(frozen=True)
class PageBookkeeping:
    """单页返回后可直接观测到的簿记事实（不含业务字段语义）。

    调用方负责在构造前完成**观测性**计算（累计条数、去重后条数、页元数据
    一致性），本结构只承载判定所需的既成事实。
    """

    page: int
    page_size: int
    rows_on_page: int
    accumulated_count: int
    unique_count: int
    duplicate_count: int
    reported_total: int | None
    reported_pages: int | None
    max_records: int
    max_pages: int
    overflowed: bool = False
    page_mismatch: bool = False
    size_mismatch: bool = False
    metadata_inconsistent: bool = False


def decide_page_outcome(book: PageBookkeeping) -> str:
    """返回本页之后的 `stop_reason`（`continue` 表示继续翻页）。

    分支优先级与顺序即契约：页号错乱 → 页大小不一致 → 页元数据自相矛盾 →
    声明记录已齐 → 空页 → 短页 → 重复行判定 → 记录上限 → 页数上限 → 继续。
    """
    pages_reached = book.reported_pages is not None and book.page >= book.reported_pages
    # 方案 1-A：放宽完整性门禁
    # 当已翻完全部声明页数（pages_reached）且总记录数较多（>=20）时，允许极轻微的业务重复（去重行数覆盖绝大部分总数，如 >= 95%）；
    # 少量记录样本（<20）或去重行数严重不足时，依然 fail-closed 判为 duplicate_records。
    if pages_reached and book.reported_total is not None and book.reported_total >= 20:
        unique_sufficient = book.unique_count >= math.ceil(book.reported_total * 0.95)
    else:
        unique_sufficient = (
            book.reported_total is None or book.unique_count >= book.reported_total
        )

    total_proven = book.reported_total is None or (
        book.reported_total <= book.max_records
        and book.accumulated_count >= book.reported_total
        and unique_sufficient
    )
    reported_end = pages_reached and total_proven
    total_end = (
        book.reported_total is not None
        and book.reported_total <= book.max_records
        and book.reported_pages is None
        and book.accumulated_count >= book.reported_total
        and book.unique_count >= book.reported_total
    )

    if book.page_mismatch:
        return "inconsistent_page"
    if book.size_mismatch:
        return "inconsistent_page_size"
    if book.metadata_inconsistent:
        return "inconsistent_metadata"
    if not book.overflowed and (reported_end or total_end):
        return "reported_pages" if reported_end else "reported_total"
    if not book.overflowed and not book.rows_on_page:
        # 空页只有在不与服务端声明矛盾时才算取完。
        if (
            book.reported_total is not None
            and book.accumulated_count < book.reported_total
        ) or (book.reported_pages is not None and book.page < book.reported_pages):
            return "incomplete_page"
        if book.duplicate_count and not unique_sufficient:
            return "duplicate_records"
        return "empty_page"
    if not book.overflowed and book.rows_on_page < book.page_size:
        if (
            book.reported_total is None or book.accumulated_count >= book.reported_total
        ) and (
            book.reported_pages is None or book.page >= book.reported_pages
        ):
            if book.duplicate_count and not unique_sufficient:
                return "duplicate_records"
            return "short_page"
        return "incomplete_page"
    if book.duplicate_count:
        # 翻页中途（尚未到达声明页数或声明总数），若单页出现轻微重复，不提前熔断，继续翻后续页；
        # 仅当已到达终局（或未声明分页信息），去重后数量不足时才返回 duplicate_records 阻止。
        can_continue_pagination = (
            book.reported_pages is not None and book.page < book.reported_pages
        ) or (
            book.reported_pages is None
            and book.reported_total is not None
            and book.accumulated_count < book.reported_total
        )
        if not can_continue_pagination:
            return "duplicate_records"
    if book.unique_count >= book.max_records:
        return "max_records"
    if book.page >= book.max_pages:
        return "max_pages"
    return CONTINUE_STOP_REASON


@dataclass(frozen=True)
class WorkbookBookkeeping:
    """官方工作簿解析后可直接观测到的簿记事实（不含业务字段语义）。

    - `read_rows`：在工作表数据区实际读取到的行数（含空行）；
    - `parsed_rows`：归类为业务记录的行数；
    - `blank_rows`：整行为空被跳过的行数；
    - `header_rows`：契约声明为表头/过滤摘要、按规则跳过的行数；
    - `unclassified_rows`：非空但既非记录也未被规则声明的行数，以及被读取却无法
      安全解析的行（**必须为 0**）；
    - `header_contract_ok`：表头是否满足已批准的列契约；
    - `truncated`：预览是否因上限截断（截断即不可信）；
    - `row_rejected`：行内出现了无法安全解析的结构性错误（如列数不足无法定位）。
    """

    read_rows: int
    parsed_rows: int
    blank_rows: int = 0
    header_rows: int = 0
    unclassified_rows: int = 0
    header_contract_ok: bool = True
    truncated: bool = False
    row_rejected: bool = False
    unreadable: bool = False

    def accounted_rows(self) -> int:
        return self.parsed_rows + self.blank_rows + self.header_rows + self.unclassified_rows


#: 工作簿准入的停机原因（非 `COMPLETE_STOP_REASONS` 即为 fail-closed）。
WORKBOOK_UNREADABLE_STOP_REASON = "workbook_unreadable"
WORKBOOK_HEADER_STOP_REASON = "workbook_header_mismatch"
WORKBOOK_TRUNCATED_STOP_REASON = "workbook_truncated"
WORKBOOK_ACCOUNTING_STOP_REASON = "workbook_accounting_mismatch"
WORKBOOK_UNCLASSIFIED_STOP_REASON = "workbook_rows_unclassified"
WORKBOOK_REJECTED_STOP_REASON = "workbook_rows_rejected"
WORKBOOK_EMPTY_STOP_REASON = "workbook_empty"


def decide_workbook_outcome(book: WorkbookBookkeeping) -> str:
    """返回官方工作簿的 `stop_reason`；只有 `workbook_rows` 视为准入通过。

    分支优先级即契约：不可读 → 表头不符 → 截断 → 行被拒 → 簿记不平 →
    存在未归类行 → 空表 → 通过。任何"少行但看起来正常"的情况都不得
    以 `workbook_rows` 放行（fail-closed）。
    """
    if min(
        book.read_rows,
        book.parsed_rows,
        book.blank_rows,
        book.header_rows,
        book.unclassified_rows,
    ) < 0:
        # 五个计数任一为负都会让账目等式假平衡（例如 blank_rows=-1 抵消一行
        # 未归类），因此整组纳入守卫，不只守卫读/解析两列。
        return WORKBOOK_ACCOUNTING_STOP_REASON
    if book.unreadable:
        return WORKBOOK_UNREADABLE_STOP_REASON
    if not book.header_contract_ok:
        return WORKBOOK_HEADER_STOP_REASON
    if book.truncated:
        return WORKBOOK_TRUNCATED_STOP_REASON
    if book.row_rejected:
        return WORKBOOK_REJECTED_STOP_REASON
    if book.read_rows != book.accounted_rows():
        return WORKBOOK_ACCOUNTING_STOP_REASON
    if book.unclassified_rows:
        return WORKBOOK_UNCLASSIFIED_STOP_REASON
    if book.parsed_rows == 0:
        return WORKBOOK_EMPTY_STOP_REASON
    return "workbook_rows"
