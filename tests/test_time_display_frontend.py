# -*- coding: utf-8 -*-
"""前端时间展示门禁（契约 C9「时间」/ REQUIREMENTS F8）：按**时区**断言，不按语言断言。

本轮（DSH-V2-10）把用户页面已定位的时间显示点接入宿主 ``web/static/host/time-format.js``：

* 时间点（结果生成时间、Excel 任务时间、上次同步时间）一律显示北京时间
  ``Asia/Shanghai``，与浏览器 TZ / 语言环境无关；
* 纯日期（今天 / businessDate / retention 截止日）原样 ``YYYY-MM-DD``，不做时区换算；
* 无时区历史值（例如 SQLite 无时区 UTC 时间）来源不明：保持原文本，**绝不按宿主
  时区换算**（换算会造成静默偏移）；
* 保存值（请求体、任务载荷、文件名时间戳）不改。

测试用 ``node --experimental-vm-modules`` 真实加载被改的插件模块（宿主 time-format.js
用真源码，其余宿主依赖用最小桩），在 ``TZ=UTC`` 与 ``TZ=America/Los_Angeles`` 下执行
同一条显示路径，断言两次输出**完全一致**且等于北京时间。

源级断言只做两件事：①已转换的文件不得残留 toLocale* / Intl.DateTimeFormat、不得复制
时区常量；②未转换的显示点必须留在显式冻结清单里（新增显示点会失败）。
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from core.time_rules import format_beijing, pure_date

REPO_ROOT = Path(__file__).resolve().parent.parent
PLUGINS = REPO_ROOT / "plugins"

#: 本轮接入宿主 time-format.js 的文件（必须零 toLocale*，且不得复制时区逻辑）。
CONVERTED = (
    "plugins/workbench/static/common.js",
    "plugins/system_query/static/query.js",
    "plugins/excel_tasks/static/logic.js",
)

#: 仍在使用 toLocale* / Intl.DateTimeFormat 的显示点（冻结清单）。
#:
#: 冻结的是「当前已知的、本轮没有权限改动的」显示点：新增显示点会失败，
#: 转换完成后从清单里删掉即可（清单外出现 offender 才是失败条件）。
PENDING = {
    "plugins/deliverable_forms/static/index.js": "交付物表单时间戳 toLocaleString('zh-CN')",
    "plugins/settings/static/updates.js": "设置页更新时间 toLocaleString('zh-CN')",
    "plugins/project_overview/static/deliverable/format.js": "toLocaleDateString() + 数字 toLocaleString('zh-CN')",
    "plugins/sign_daily/static/report-logic.js": "Intl.DateTimeFormat('zh-CN') 手工拼装",
}

#: toISOString 只允许用于内部时间戳/文件名（白名单钉住现有内部用法）。
ISO_WHITELIST = {
    "plugins/workbench/static/wizard.js",
    "plugins/system_query/static/query.js",
}

LOCALE_DISPLAY_RE = re.compile(
    r"toLocaleString|toLocaleDateString|toLocaleTimeString|Intl\.DateTimeFormat"
)

TZ_CASES = ("UTC", "America/Los_Angeles")

#: 带显式时区的时间点输入（同一时刻的不同写法 + 跨日/跨年/DST 边界）。
ZONED_INSTANTS = {
    "utc_iso": "2026-10-03T01:23:45Z",
    "offset_iso": "2026-10-03T09:23:45+08:00",
    "epoch_ms": 1790990625123,
    "cross_day": "2026-10-31T23:30:00Z",
    "year_end": "2026-12-31T20:00:00Z",
    "la_fall_back": "2026-11-01T08:30:00Z",
}

ZONED_DATETIMES = {
    "utc_iso": datetime(2026, 10, 3, 1, 23, 45, tzinfo=timezone.utc),
    "offset_iso": datetime(2026, 10, 3, 1, 23, 45, tzinfo=timezone.utc),
    "epoch_ms": datetime(2026, 10, 3, 1, 23, 45, 123000, tzinfo=timezone.utc),
    "cross_day": datetime(2026, 10, 31, 23, 30, tzinfo=timezone.utc),
    "year_end": datetime(2026, 12, 31, 20, 0, tzinfo=timezone.utc),
    "la_fall_back": datetime(2026, 11, 1, 8, 30, tzinfo=timezone.utc),
}

#: 无时区历史值：来源不明，保持原文本行为，绝不按宿主时区换算。
NAIVE_INPUT = "2026-10-03 01:23:45"
#: 纯日期：原样返回，不做任何时区换算（跨时区不位移）。
PURE_DATE_INPUT = "2026-10-31"
#: 解析不了的取值必须降级成原文，不能抛错让整页白屏。
GARBAGE_INPUT = "not-a-time"


def _node_major() -> int:
    node = shutil.which("node")
    if node is None:
        return 0
    out = subprocess.run([node, "--version"], capture_output=True, text=True, check=False).stdout
    match = re.match(r"v(\d+)", out.strip())
    return int(match.group(1)) if match else 0


pytestmark = pytest.mark.skipif(
    _node_major() < 22,
    reason="needs Node 22+ for vm.SourceTextModule (--experimental-vm-modules)",
)


# ── Node 探针：真实加载被改的插件模块，一次输出全部观测值 ─────────────────────

_PROBE_SCRIPT = r"""
import * as vm from "node:vm";
import { readFileSync } from "node:fs";
import { pathToFileURL } from "node:url";
import path from "node:path";

const [, REPO_ROOT, PAYLOAD_JSON] = process.argv;
const payload = JSON.parse(PAYLOAD_JSON);
const HOST = path.join(REPO_ROOT, "web", "static", "host");
const SYSTEM_QUERY = path.join(REPO_ROOT, "plugins", "system_query", "static");
const EXCEL_TASKS = path.join(REPO_ROOT, "plugins", "excel_tasks", "static");

// 最小桩：只为让被改模块的导入图能求值，时间显示路径本身全部走真源码。
const PREACT_STUB = `
export const html = (strings, ...values) => ({ strings, values });
export const useCallback = (fn) => fn;
export const useEffect = () => undefined;
export const useMemo = (fn) => fn();
export const useRef = (value) => ({ current: value });
export const useState = (initial) => [typeof initial === "function" ? initial() : initial, () => undefined];
`;
const API_STUB = `
export class ApiError extends Error {}
export const api = async () => ({});
`;
const KIT_STUB = `export const useStylesheet = () => undefined;\n`;
const UI_KIT_STUB = `
export const ErrorCard = () => null;
export const Skeleton = () => null;
export const TONE = {};
`;
const GRID_STUB = `export const DataGrid = () => null;\n`;

const context = vm.createContext({
  console,
  setTimeout, clearTimeout, setInterval, clearInterval, queueMicrotask,
  Promise, JSON, Math, Date, Object, Array, String, Number, Boolean,
  Error, TypeError, RangeError, Map, Set, WeakMap, WeakSet, Symbol, Reflect, RegExp, Intl,
  encodeURIComponent, decodeURIComponent, parseInt, parseFloat, isNaN, undefined,
  fetch: async () => { throw new Error("frontend time gate must not touch the network"); },
  window: {},
  document: { getElementById: () => null },
  localStorage: { getItem: () => null, setItem: () => undefined, removeItem: () => undefined },
});

// 宿主时间模块一律用真源码，绝不桩掉——门禁要证明的就是「插件真的复用了它」。
// excel_tasks/logic.js 用动态 import 引入该模块（见文件内注释），这里同时提供
// importModuleDynamically：静态导入由 VM 自己 link+evaluate，动态导入的模块
// VM 不会替它求值，必须在这里 link+evaluate 后返回，否则拿到的是 TDZ 命名空间。
function hostTimeModule() {
  return sourceModule(path.join(HOST, "time-format.js"));
}

async function hostTimeDynamicModule() {
  const module = hostTimeModule();
  await module.link(linker);
  await module.evaluate();
  return module;
}

async function importModuleDynamically(specifier) {
  if (specifier === "/static/host/time-format.js") return hostTimeDynamicModule();
  throw new Error("unexpected dynamic specifier: " + specifier);
}

function sourceModule(filePath) {
  return new vm.SourceTextModule(readFileSync(filePath, "utf8"), {
    context,
    identifier: pathToFileURL(filePath).href,
    importModuleDynamically,
  });
}

function stubModule(text, name) {
  return new vm.SourceTextModule(text, { context, identifier: "stub:" + name });
}

async function linker(specifier) {
  if (specifier === "/static/host/time-format.js") return hostTimeModule();
  if (specifier === "/static/host/vendor/preact-htm.js") return stubModule(PREACT_STUB, "preact-htm");
  if (specifier === "/static/host/api.js") return stubModule(API_STUB, "api");
  if (specifier === "/static/host/kit.js") return stubModule(KIT_STUB, "kit");
  if (specifier === "/static/host/ui-kit.js") return stubModule(UI_KIT_STUB, "ui-kit");
  // 系统查询的同插件纯数据/纯函数模块：真源码。
  if (specifier === "./grid.js") return stubModule(GRID_STUB, "grid");
  if (specifier === "./lib.js") return sourceModule(path.join(SYSTEM_QUERY, "lib.js"));
  if (specifier === "./modes.js") return sourceModule(path.join(SYSTEM_QUERY, "modes.js"));
  // Excel 文件处理：logic.js 真源码（shared.js 再导出它，页面经 shared.js 取 formatDate）。
  if (specifier === "./logic.js") return sourceModule(path.join(EXCEL_TASKS, "logic.js"));
  throw new Error("unexpected specifier: " + specifier);
}

async function loadModule(filePath) {
  const module = sourceModule(filePath);
  await module.link(linker);
  await module.evaluate();
  return module.namespace;
}

const common = await loadModule(path.join(REPO_ROOT, "plugins", "workbench", "static", "common.js"));
const query = await loadModule(path.join(REPO_ROOT, "plugins", "system_query", "static", "query.js"));
const excelLogic = await loadModule(path.join(EXCEL_TASKS, "logic.js"));
const excelShared = await loadModule(path.join(EXCEL_TASKS, "shared.js"));

const missing = [];
for (const name of ["todayString", "shortTime"]) {
  if (typeof common[name] !== "function") missing.push("common.js:" + name);
}
if (typeof query.formatResultAt !== "function") missing.push("query.js:formatResultAt");
if (typeof excelLogic.formatDate !== "function") missing.push("excel_tasks/logic.js:formatDate");
if (typeof excelShared.formatDate !== "function") missing.push("excel_tasks/shared.js:formatDate");
if (missing.length) {
  console.log(JSON.stringify({ protocol: "time-display", ok: false, missing }));
  process.exit(2);
}

const shortTime = {};
for (const [key, value] of Object.entries(payload.shortTimeInputs)) {
  shortTime[key] = common.shortTime(value);
}
const formatDate = {};
for (const [key, value] of Object.entries(payload.formatDateInputs)) {
  formatDate[key] = { logic: excelLogic.formatDate(value), shared: excelShared.formatDate(value) };
}
const resultAt = {};
for (const [key, value] of Object.entries(payload.resultAtInputs)) {
  resultAt[key] = query.formatResultAt(value);
}

console.log(JSON.stringify({
  protocol: "time-display",
  ok: true,
  tz: process.env.TZ || "",
  todayString: common.todayString(),
  shortTime,
  formatDate,
  resultAt,
  exports: {
    common: Object.keys(common).sort(),
    query: Object.keys(query).sort(),
    logic: Object.keys(excelLogic).sort(),
    shared: Object.keys(excelShared).sort(),
  },
}));
"""


def _run_probe(tz_name: str) -> dict:
    """在指定 TZ 环境下真实执行被改的插件模块，返回观测值。"""
    env = dict(os.environ)
    env["TZ"] = tz_name
    payload = {
        "shortTimeInputs": {
            **ZONED_INSTANTS,
            "empty": "",
            "naive_local": NAIVE_INPUT,
            "garbage": GARBAGE_INPUT,
        },
        "formatDateInputs": {
            **ZONED_INSTANTS,
            "pure_date": PURE_DATE_INPUT,
            "naive_local": NAIVE_INPUT,
            "garbage": GARBAGE_INPUT,
            "empty": "",
        },
        "resultAtInputs": {"utc_iso": ZONED_INSTANTS["utc_iso"], "epoch_ms": ZONED_INSTANTS["epoch_ms"]},
    }
    result = subprocess.run(
        [
            "node",
            "--experimental-vm-modules",
            "--input-type=module",
            "-e",
            _PROBE_SCRIPT,
            str(REPO_ROOT),
            json.dumps(payload),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        cwd=str(REPO_ROOT),
        check=False,
    )
    assert result.returncode == 0, f"Node 在 TZ={tz_name} 下执行失败:\n{result.stderr[-2000:]}"
    lines = result.stdout.strip().splitlines()
    assert lines, f"Node 在 TZ={tz_name} 下未产生输出"
    data = json.loads(lines[-1])
    assert data.get("protocol") == "time-display", data
    assert data.get("ok") is True, f"探针缺少被改函数: {data.get('missing')}"
    return data


@pytest.fixture(scope="module")
def probe() -> dict[str, dict]:
    return {tz_name: _run_probe(tz_name) for tz_name in TZ_CASES}


def _beijing_today() -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=8)).strftime("%Y-%m-%d")


# ── 验收 1：TZ 真的生效，且同一时刻两地说法一致（时区断言，不是语言断言）──────


def test_probe_ran_under_each_timezone(probe: dict[str, dict]) -> None:
    for tz_name, data in probe.items():
        assert data["tz"] == tz_name, f"TZ 环境变量未生效: {data['tz']!r}"
        assert "formatResultAt" in data["exports"]["query"]
        assert {"todayString", "shortTime"} <= set(data["exports"]["common"])
        assert "formatDate" in data["exports"]["logic"]
        assert "formatDate" in data["exports"]["shared"]


def test_zoned_instants_render_identically_in_both_timezones(probe: dict[str, dict]) -> None:
    """UTC 浏览器与洛杉矶浏览器对同一时刻必须显示同一串北京时间。"""
    for key in ZONED_INSTANTS:
        rendered = {tz_name: data["shortTime"][key] for tz_name, data in probe.items()}
        assert len(set(rendered.values())) == 1, f"{key} 随宿主时区漂移: {rendered}"
        rendered = {tz_name: data["formatDate"][key]["logic"] for tz_name, data in probe.items()}
        assert len(set(rendered.values())) == 1, f"{key} 的 Excel 时间随宿主时区漂移: {rendered}"
    for key in ("utc_iso", "epoch_ms"):
        rendered = {tz_name: data["resultAt"][key] for tz_name, data in probe.items()}
        assert len(set(rendered.values())) == 1, f"结果生成时间随宿主时区漂移: {rendered}"


def test_displayed_values_are_exactly_beijing(probe: dict[str, dict]) -> None:
    """与 core/time_rules.format_beijing 逐条对账（C9 单一口径）。"""
    for tz_name, data in probe.items():
        for key, moment in ZONED_DATETIMES.items():
            expected = format_beijing(moment)[5:16]
            assert data["shortTime"][key] == expected, (tz_name, key, data["shortTime"][key])
        # 跨日 / 跨年必须按北京时间落位，而不是宿主时区当天。
        assert data["shortTime"]["cross_day"] == "11-01 07:30"
        assert data["shortTime"]["year_end"] == "01-01 04:00"
        assert data["shortTime"]["la_fall_back"] == "11-01 16:30"


def test_excel_format_date_is_beijing_seconds(probe: dict[str, dict]) -> None:
    """excel_tasks/logic.js 的 formatDate 走宿主 formatBeijingSeconds（带秒、北京时间）。"""
    expected = {
        "utc_iso": "2026-10-03 09:23:45",
        "offset_iso": "2026-10-03 09:23:45",
        "epoch_ms": "2026-10-03 09:23:45",
        "cross_day": "2026-11-01 07:30:00",
        "year_end": "2027-01-01 04:00:00",
        "la_fall_back": "2026-11-01 16:30:00",
    }
    for tz_name, data in probe.items():
        for key, text in expected.items():
            assert data["formatDate"][key]["logic"] == text, (tz_name, key, data["formatDate"][key]["logic"])
            # shared.js 只是再导出 logic.js：页面经 shared.js 取到同一实现，无第二份显示逻辑。
            assert data["formatDate"][key]["shared"] == text, (tz_name, key)


def test_excel_format_date_keeps_pure_dates_and_unknown_values_verbatim(probe: dict[str, dict]) -> None:
    """纯日期不位移；无时区/无法判定的取值来源不明，原样显示（绝不按宿主时区换算）。"""
    for tz_name, data in probe.items():
        assert data["formatDate"]["pure_date"]["logic"] == "2026-10-31", tz_name
        assert data["formatDate"]["naive_local"]["logic"] == NAIVE_INPUT, (tz_name, data["formatDate"]["naive_local"])
        assert data["formatDate"]["garbage"]["logic"] == GARBAGE_INPUT, tz_name
        assert data["formatDate"]["empty"]["logic"] == "-", tz_name
        assert pure_date(data["formatDate"]["pure_date"]["logic"]).isoformat() == "2026-10-31"


def test_result_timestamp_labels_beijing_zone(probe: dict[str, dict]) -> None:
    """结果生成时间必须显式写 Asia/Shanghai，而不是靠 zh-CN 语言环境。"""
    for tz_name, data in probe.items():
        for key in ("utc_iso", "epoch_ms"):
            shown = data["resultAt"][key]
            assert shown == "2026-10-03 09:23 (Asia/Shanghai)", (tz_name, key, shown)
            assert shown.endswith("(Asia/Shanghai)")
        assert "zh-CN" not in json.dumps(data, ensure_ascii=False)


# ── 验收 2：日期与时间点分开，日期不位移 ─────────────────────────────────────


def test_today_string_is_beijing_date_not_browser_date(probe: dict[str, dict]) -> None:
    """todayString 是纯日期，取北京时间当天；与浏览器时区无关，也不做时区换算。"""
    before = _beijing_today()
    for tz_name, data in probe.items():
        text = data["todayString"]
        after = _beijing_today()
        assert text in {before, after}, (tz_name, text, before, after)
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", text), (tz_name, text)
        # 纯日期原样返回：round-trip 不做任何位移。
        assert pure_date(text).isoformat() == text


def test_naive_values_keep_their_text_and_are_never_shifted(probe: dict[str, dict]) -> None:
    """无时区历史值来源不明：保持原有文本行为，两地说法一致，绝不按宿主时区换算。

    后端存在 SQLite 无时区 UTC 时间等来源；按宿主时区解释会造成静默偏移，
    因此这里断言「原样保留」而不是「换算成某个时刻」。
    """
    for tz_name, data in probe.items():
        assert data["shortTime"]["naive_local"] == "10-03 01:23", (tz_name, data["shortTime"]["naive_local"])
        # 反证：若按 UTC 追加 Z 再换算，会得到 09:23；若按宿主本地时区换算，洛杉矶会得到 16:23。
        assert data["shortTime"]["naive_local"] != "10-03 09:23", tz_name
        assert data["shortTime"]["naive_local"] != "10-03 16:23", tz_name


def test_unparsable_and_empty_values_degrade_instead_of_throwing(probe: dict[str, dict]) -> None:
    for tz_name, data in probe.items():
        assert data["shortTime"]["empty"] == ""
        assert data["shortTime"]["garbage"] == "-time", (tz_name, data["shortTime"]["garbage"])


# ── 验收 3：已转换的文件复用宿主模块，且不再依赖语言环境 ──────────────────────


def _read(rel: str) -> str:
    return (REPO_ROOT / rel).read_text(encoding="utf-8")


def _strip_js_comments(source: str) -> str:
    without_block = re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)
    return re.sub(r"^\s*//.*$", "", without_block, flags=re.MULTILINE)


def test_converted_files_import_the_host_module_and_do_not_copy_it() -> None:
    for rel in CONVERTED:
        code = _strip_js_comments(_read(rel))
        assert '"/static/host/time-format.js"' in code, f"{rel} 未接入宿主时间模块"
        assert not LOCALE_DISPLAY_RE.search(code), f"{rel} 仍残留 toLocale*/Intl.DateTimeFormat 显示点"
        # 不复制宿主逻辑：时区名与 +08:00 偏移只能来自 time-format.js。
        assert "Asia/Shanghai" not in code, f"{rel} 复制了时区名，应调用 formatBeijing*"
        assert not re.search(r"\b480\b|\b8\s*\*\s*60\b", code), f"{rel} 复制了 +08:00 偏移计算"


def test_workbench_common_no_longer_builds_display_dates_from_new_date() -> None:
    """workbench/common.js 的两个显示点都改走宿主模块，不再自己拼年月日。"""
    code = _strip_js_comments(_read("plugins/workbench/static/common.js"))
    assert "new Date(" not in code
    assert "getFullYear()" not in code and "getMonth()" not in code
    assert "formatBeijingDate(Date.now())" in code
    assert "formatBeijing(millis).slice(5, 16)" in code
    # 无时区历史值不再按宿主时区解释（后端存在无时区 UTC 来源，换算会造成静默偏移）。
    assert "interpretNaiveTime" not in code


def test_excel_tasks_display_points_use_host_formatters() -> None:
    """excel_tasks：时间点走 formatBeijingSeconds，纯日期走 formatPureDate，不再自己 new Date。"""
    logic = _strip_js_comments(_read("plugins/excel_tasks/static/logic.js"))
    assert "new Date(" not in logic
    assert "isPureDate" in logic and "formatPureDate" in logic
    assert "formatBeijingSeconds" in logic
    # shared.js 只做再导出，不另起一套显示逻辑（无遗漏显示点）。
    shared = _strip_js_comments(_read("plugins/excel_tasks/static/shared.js"))
    assert 'export * from "./logic.js"' in shared
    assert "formatDate" not in shared
    assert "new Date(" not in shared and not LOCALE_DISPLAY_RE.search(shared)


def test_no_new_locale_based_time_display_points() -> None:
    """冻结清单之外出现任何 toLocale*/Intl.DateTimeFormat 都算新增语言依赖显示点。"""
    offenders = set()
    for js in sorted(PLUGINS.glob("*/static/**/*.js")):
        if LOCALE_DISPLAY_RE.search(js.read_text(encoding="utf-8")):
            offenders.add(js.relative_to(REPO_ROOT).as_posix())
    unexpected = sorted(offenders - set(PENDING))
    assert not unexpected, "新增时间显示点必须走 /static/host/time-format.js：\n" + "\n".join(unexpected)


def test_to_iso_string_only_for_internal_stamps() -> None:
    """toISOString 现存用法均为内部时间戳/文件名（白名单钉住）；展示点必须走北京时间格式化。"""
    for js in sorted(PLUGINS.glob("*/static/**/*.js")):
        rel = js.relative_to(REPO_ROOT).as_posix()
        if rel in ISO_WHITELIST:
            continue
        assert "toISOString()" not in js.read_text(encoding="utf-8"), (
            f"{rel} 出现新的 toISOString 展示点，请走 formatBeijing*"
        )
