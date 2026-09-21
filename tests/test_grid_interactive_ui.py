# -*- coding: utf-8 -*-
"""Phase 4 高密度数据网格交互契约测试：排序 / 快筛高亮 / 分页 / 列显隐 / 一键复制。"""

from __future__ import annotations

import pytest

from tests.test_sor_ui_behavior import run_node_vm_test


def test_grid_sort_toggle_and_multi_sort() -> None:
    """表头点击：升序 → 降序 → 取消；Shift+点击 追加二级排序并显示次序标号。"""
    js_test = """
    const rows = [
      ["A-3", "3", "x"],
      ["A-1", "10", "y"],
      ["A-2", "2", "z"],
    ];
    const data = { rows, headerRows: [["单号", "数量", "备注"]] };
    const wrap = app.renderRows(data, [], "tdc-data-model");
    const table = wrap.querySelector("table");
    const headRow = table.children[0].children[0];
    const firstTh = headRow.children[0];

    // 首次点击：升序
    firstTh.dispatchEvent({ type: "click", shiftKey: false });
    let body = table.children[1];
    const stripIcon = (s) => s.replace(/📋/g, "");
    let firstCell = stripIcon(body.children[0].children[0].textContent);
    // 升序后首行应为 A-1
    const ascFirst = firstCell;

    // 第二次点击：降序
    firstTh.dispatchEvent({ type: "click", shiftKey: false });
    body = table.children[1];
    const descFirst = stripIcon(body.children[0].children[0].textContent);

    // 第三次点击：取消排序
    firstTh.dispatchEvent({ type: "click", shiftKey: false });
    body = table.children[1];
    const clearedFirst = stripIcon(body.children[0].children[0].textContent);

    // Shift+点击 两列：多列排序指示器带次序标号（重渲染后需重新取表头引用）
    table.children[0].children[0].children[0].dispatchEvent({ type: "click", shiftKey: true });
    table.children[0].children[0].children[1].dispatchEvent({ type: "click", shiftKey: true });
    const headAfterSecond = table.children[0].children[0];
    const indicator1 = headAfterSecond.children[0].querySelector(".grid-sort-indicator");
    const indicator2 = headAfterSecond.children[1].querySelector(".grid-sort-indicator");

    return {
      ascFirst,
      descFirst,
      clearedFirst,
      indicator1: indicator1 ? indicator1.textContent : null,
      indicator2: indicator2 ? indicator2.textContent : null,
    };
    """
    res = run_node_vm_test(js_test)
    assert res["ascFirst"] == "A-1"
    assert res["descFirst"] == "A-3"
    assert res["clearedFirst"] == "A-3"  # 原始顺序（A-3 在前）
    assert res["indicator1"] == "▲1"
    assert res["indicator2"] == "▲2"


def test_grid_sort_numeric_aware() -> None:
    """数值列按数值排序：10 排在 2 之后（升序）。"""
    js_test = """
    const rows = [
      ["r1", "10"],
      ["r2", "2"],
      ["r3", "100"],
    ];
    const data = { rows, headerRows: [["单号", "数量"]] };
    const wrap = app.renderRows(data, [], "tdc-data-model");
    const table = wrap.querySelector("table");
    const headRow = table.children[0].children[0];
    headRow.children[1].dispatchEvent({ type: "click", shiftKey: false });
    const body = table.children[1];
    const order = Array.from(body.children).map((tr) => tr.children[1].textContent.replace(/📋/g, ""));
    return { order };
    """
    res = run_node_vm_test(js_test)
    assert res["order"] == ["2", "10", "100"]


def test_grid_filter_realtime_highlight() -> None:
    """关键字快筛：实时过滤 + mark 高亮节点，清除后恢复。"""
    js_test = """
    const rows = [
      ["EWO-100", "Open"],
      ["EWO-200", "Closed"],
      ["NCR-300", "Open"],
    ];
    const data = { rows, headerRows: [["单号", "状态"]] };
    const wrap = app.renderRows(data, [], "tdc-data-model");
    const table = wrap.querySelector("table");
    const input = wrap.querySelector(".grid-filter-input");
    const count = wrap.querySelector(".grid-filter-count");

    input.value = "ewo";
    input.dispatchEvent({ type: "input" });
    let body = table.children[1];
    const filteredCount = body.children.length;
    const countText = count.textContent;
    const firstRowCells = body.children[0] ? Array.from(body.children[0].children) : [];
    const marks = [];
    firstRowCells.forEach((td) => {
      const mark = td.querySelector(".grid-highlight");
      if (mark) marks.push(mark.textContent);
    });

    input.value = "";
    input.dispatchEvent({ type: "input" });
    body = table.children[1];
    const restoredCount = body.children.length;
    const restoredCountText = count.textContent;

    return {
      filteredCount,
      countText,
      marks,
      restoredCount,
      restoredCountText,
    };
    """
    res = run_node_vm_test(js_test)
    assert res["filteredCount"] == 2
    assert "2/3 条" in res["countText"]
    assert any("ewo" in m.lower() for m in res["marks"])
    assert res["restoredCount"] == 3
    assert res["restoredCountText"] == ""


def test_grid_pagination_50_100() -> None:
    """紧凑分页：默认 50 条/页，可切换 100 条/页，翻页正确。"""
    js_test = """
    const rows = [];
    for (let i = 1; i <= 230; i++) {
      rows.push(["NO-" + String(i).padStart(4, "0"), "v" + i]);
    }
    const data = { rows, headerRows: [["单号", "内容"]] };
    const wrap = app.renderRows(data, [], "tdc-data-model");
    const table = wrap.querySelector("table");
    const pager = wrap.children[2];
    const info = pager.children[0].textContent;

    const body1 = table.children[1].children.length;

    // 下一页
    const nextBtn = pager.children[2];
    nextBtn.dispatchEvent({ type: "click" });
    const info2 = pager.children[0].textContent;

    // 切换每页 100
    const sizeSelect = pager.children[4];
    sizeSelect.value = "100";
    sizeSelect.dispatchEvent({ type: "change" });
    const body100 = table.children[1].children.length;
    const info3 = pager.children[0].textContent;

    return { info, body1, info2, body100, info3 };
    """
    res = run_node_vm_test(js_test)
    assert "共 230 条" in res["info"]
    assert "第 1/5 页" in res["info"]
    assert res["body1"] == 50
    assert "第 2/5 页" in res["info2"]
    assert res["body100"] == 100
    assert "第 1/3 页" in res["info3"]


def test_grid_copy_button_on_id_columns() -> None:
    """单号列悬浮出现一键复制图标；普通列不出现。"""
    js_test = """
    const rows = [
      ["EW-0001", "备注文本", "2026-01-01"],
    ];
    const data = { rows, headerRows: [["EWO号", "备注", "创建日期"]] };
    const wrap = app.renderRows(data, [], "tdc-data-model");
    const table = wrap.querySelector("table");
    const body = table.children[1];
    const cells = Array.from(body.children[0].children);
    const hasCopy = cells.map((td) => Boolean(td.querySelector(".grid-copy-btn")));
    const copyCell = cells[0].querySelector(".grid-copy-btn");
    return {
      hasCopy,
      copyText: copyCell ? copyCell.textContent : null,
      ariaLabel: copyCell ? copyCell.getAttribute("aria-label") : null,
    };
    """
    res = run_node_vm_test(js_test)
    assert res["hasCopy"] == [True, False, False]
    assert res["copyText"] == "📋"
    assert "复制" in (res["ariaLabel"] or "")


def test_grid_column_picker_persists_to_local_storage() -> None:
    """列显隐：常用列/全量列切换与多选自定义均持久化到 localStorage。"""
    js_test = """
    const rows = [
      ["A", "B", "C", "D"],
      ["1", "2", "3", "4"],
    ];
    const data = { rows, headerRows: [["单号", "名称", "部门", "日期"]], defaultVisibleCount: 2 };
    const wrap = app.renderRows(data, [], "tdc-data-model");
    const table = wrap.querySelector("table");
    const toolbar = wrap.children[0];
    const columnBtn = toolbar.querySelector(".grid-column-btn");
    columnBtn.dispatchEvent({ type: "click" });
    const panel = toolbar.querySelector(".grid-column-panel");
    const quickBtns = panel.children[0].children;

    // 切换常用列
    quickBtns[0].dispatchEvent({ type: "click" });
    const headerColsCommon = table.children[0].children[0].children.length;
    const saved1 = JSON.parse(window.localStorage.getItem("vse-grid-column-prefs") || "{}");

    // 全量列
    quickBtns[1].dispatchEvent({ type: "click" });
    const headerColsAll = table.children[0].children[0].children.length;

    // 自定义隐藏第 2 列
    const checklist = panel.children[1];
    const secondCheckbox = checklist.children[1].children[0];
    secondCheckbox.checked = false;
    secondCheckbox.dispatchEvent({ type: "change" });
    const headerColsCustom = table.children[0].children[0].children.length;
    const saved2 = JSON.parse(window.localStorage.getItem("vse-grid-column-prefs") || "{}");

    return {
      headerColsCommon,
      saved1,
      headerColsAll,
      headerColsCustom,
      saved2,
    };
    """
    res = run_node_vm_test(js_test)
    assert res["headerColsCommon"] == 2
    assert res["saved1"]["tdc-data-model"]["mode"] == "common"
    assert res["headerColsAll"] == 4
    assert res["headerColsCustom"] == 3
    assert res["saved2"]["tdc-data-model"]["mode"] == "custom"
    assert res["saved2"]["tdc-data-model"]["hidden"] == [1]


def test_grid_respects_sensitive_columns() -> None:
    """敏感列（SENSITIVE_COLUMNS 键）不进入网格列清单，不提供显隐选择。"""
    js_test = """
    const rows = [{ no: "N-1", cookie: "sid=secret", token: "t", name: "x" }];
    const data = { rows, columns: [
      { key: "no", label: "单号" },
      { key: "cookie", label: "Cookie" },
      { key: "token", label: "Token" },
      { key: "name", label: "名称" },
    ] };
    const wrap = app.renderRows(data, [], "tdc-data-model");
    const table = wrap.querySelector("table");
    const headerCells = Array.from(table.children[0].children[0].children);
    const labels = headerCells.map((th) => th.textContent);
    const bodyText = table.children[1].textContent;
    return { labels, bodyText };
    """
    res = run_node_vm_test(js_test)
    assert res["labels"] == ["单号", "名称"]
    assert "secret" not in res["bodyText"]
    assert "sid=" not in res["bodyText"]


def test_grid_2000_rows_render_performance() -> None:
    """2000+ 行超大数据集：初始渲染与翻页/筛选重渲染性能预算。"""
    js_test = """
    const N = 2000;
    const rows = [];
    for (let i = 1; i <= N; i++) {
      rows.push([
        "EW-" + String(i).padStart(5, "0"),
        "零件" + i,
        "部门" + (i % 10),
        "2026-" + String((i % 12) + 1).padStart(2, "0") + "-" + String((i % 28) + 1).padStart(2, "0"),
        "Open",
      ]);
    }
    const data = { rows, headerRows: [["单号", "名称", "部门", "日期", "状态"]] };
    const t0 = Date.now();
    const wrap = app.renderRows(data, [], "tdc-data-model");
    const t1 = Date.now();
    const table = wrap.querySelector("table");
    const rowsRendered = table.children[1].children.length;
    const pager = wrap.children[2];
    pager.children[2].dispatchEvent({ type: "click" });
    const t2 = Date.now();
    const input = wrap.querySelector(".grid-filter-input");
    input.value = "零件199";
    input.dispatchEvent({ type: "input" });
    const t3 = Date.now();
    const filteredRows = table.children[1].children.length;
    return {
      initialMs: t1 - t0,
      rowsRendered,
      pageFlipMs: t2 - t1,
      filterMs: t3 - t2,
      filteredRows,
    };
    """
    res = run_node_vm_test(js_test)
    assert res["rowsRendered"] == 50  # 分页 caps DOM 规模
    assert res["filteredRows"] <= 50
    # 分页使 DOM 规模恒定，重渲染为毫秒级
    assert res["pageFlipMs"] < 300, f"page flip took {res['pageFlipMs']}ms"
    assert res["filterMs"] < 300, f"filter re-render took {res['filterMs']}ms"
    # 初始构建含 2000 行排序数据结构，但 DOM 仅一页
    assert res["initialMs"] < 1500, f"initial render took {res['initialMs']}ms"


def test_grid_css_classes_defined() -> None:
    """网格新增类必须在 style.css 中有定义（防止样式漂移）。"""
    css = pytest.importorskip("pathlib").Path("web/static/style.css").read_text(encoding="utf-8-sig")
    for cls in (
        ".grid-toolbar",
        ".grid-filter-input",
        ".grid-column-panel",
        ".grid-sort-indicator",
        ".grid-highlight",
        ".grid-copy-btn",
        ".grid-pager",
    ):
        assert cls in css
