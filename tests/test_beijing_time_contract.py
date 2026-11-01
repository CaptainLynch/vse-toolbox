# -*- coding: utf-8 -*-
"""北京时间统一前端格式契约（Node 下以三个 TZ 实际执行 time-format.js）。

锁定的契约（docs/refactor-v2/CONTRACTS.md C9「时间」）：
1. 时间点显示一律明确标注 Asia/Shanghai，不能只靠 zh-CN 语言环境；
2. UTC / Asia/Shanghai / America/Los_Angeles 三个浏览器时区下，同一时刻显示完全一致；
3. 纯日期不做时区换算、不位移；无时区历史值按来源（tdc / aras / local）解释，绝不追加 Z。

测试用 ``node --input-type=module`` 真实 import 宿主模块并在三个 TZ 环境变量下执行，
不检查源码文本包含关系（唯一的源级断言是「不得用 toLocale* 让结果随语言/时区漂移」）。
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

from core.time_rules import format_beijing, pure_date

REPO_ROOT = Path(__file__).resolve().parent.parent
HOST_STATIC = REPO_ROOT / "web" / "static" / "host"
TIME_FORMAT_JS = HOST_STATIC / "time-format.js"

TZ_CASES = ("UTC", "Asia/Shanghai", "America/Los_Angeles")


def _node_major() -> int:
    node = shutil.which("node")
    if node is None:
        return 0
    out = subprocess.run([node, "--version"], capture_output=True, text=True, check=False).stdout
    match = re.match(r"v(\d+)", out.strip())
    return int(match.group(1)) if match else 0


pytestmark = pytest.mark.skipif(
    _node_major() < 22,
    reason="needs Node 22+ to import the host ES module without a package.json",
)


# ── Node 探针：一次输出全部观测值，Python 侧只做契约断言 ─────────────────────────

_PROBE_SCRIPT = r"""
const base = process.argv[1];
const tf = await import(base + "/time-format.js");

// 同一时刻的不同表达：Z 后缀、+08:00 偏移、epoch 毫秒、Date 对象。
const instants = {
  utc_iso: "2026-10-03T01:23:45Z",
  offset_iso: "2026-10-03T09:23:45+08:00",
  epoch_ms: 1790990625123,
  date_object: new Date(Date.UTC(2026, 9, 3, 1, 23, 45)),
  cross_day: "2026-10-31T23:30:00Z",
  year_end: "2026-12-31T20:00:00Z",
  la_spring_forward: "2026-03-08T09:59:59Z",
  la_fall_back: "2026-11-01T08:30:00Z",
  microseconds: "2026-05-01T08:12:34.567890Z",
};

const displayed = {};
for (const [key, value] of Object.entries(instants)) {
  displayed[key] = {
    minutes: tf.formatBeijing(value),
    seconds: tf.formatBeijingSeconds(value),
    date: tf.formatBeijingDate(value),
    zoned: tf.formatBeijingWithZone(value),
    parts: tf.beijingParts(value),
  };
}

const pureDateOut = {};
for (const text of ["2026-10-31", "2026-01-05", "2024-02-29", "2026-12-31"]) {
  pureDateOut[text] = tf.formatPureDate(text);
}

const naive = {};
for (const source of ["tdc", "aras", "local"]) {
  naive[source] = {
    july: tf.interpretNaiveTime("2026-07-01 12:00:00", source),
    january: tf.interpretNaiveTime("2026-01-15 08:30:00", source),
    date_only: tf.interpretNaiveTime("2026-10-31", source),
    slash_july: tf.interpretNaiveTime("2026/07/01 12:00:00", source),
  };
}

const errors = {};
const attempts = {
  instant_is_date_only: () => tf.formatBeijing("2026-10-03"),
  instant_is_naive: () => tf.formatBeijing("2026-10-03T09:23:00"),
  pure_date_is_instant: () => tf.formatPureDate("2026-10-03T00:00:00Z"),
  pure_date_is_date_object: () => tf.formatPureDate(new Date(0)),
  pure_date_bad_calendar: () => tf.formatPureDate("2026-02-30"),
  naive_already_zoned: () => tf.interpretNaiveTime("2026-08-01T10:00:00Z", "tdc"),
  naive_unknown_source: () => tf.interpretNaiveTime("2026-08-01 10:00:00", "nope"),
  naive_date_object: () => tf.interpretNaiveTime(new Date(0), "tdc"),
};
for (const [key, run] of Object.entries(attempts)) {
  try {
    run();
    errors[key] = { threw: false, name: "", message: "" };
  } catch (err) {
    errors[key] = { threw: true, name: err.name, message: err.message };
  }
}

console.log(JSON.stringify({
  tz: process.env.TZ || "",
  constants: { zone: tf.BEIJING_TZ, label: tf.BEIJING_TZ_LABEL, offsetMinutes: tf.BEIJING_OFFSET_MINUTES },
  isPureDate: {
    valid: tf.isPureDate("2026-10-31"),
    invalid: tf.isPureDate("2026-02-30"),
    instant: tf.isPureDate("2026-10-31T00:00:00Z"),
  },
  displayed: displayed,
  pureDateOut: pureDateOut,
  naive: naive,
  errors: errors,
}));
"""


def _run_probe(tz_name: str) -> dict:
    """在指定 TZ 环境下真实执行宿主模块，返回观测值。"""
    env = dict(os.environ)
    env["TZ"] = tz_name
    result = subprocess.run(
        ["node", "--input-type=module", "-e", _PROBE_SCRIPT, HOST_STATIC.as_uri()],
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
    return json.loads(lines[-1])


@pytest.fixture(scope="module")
def probe() -> dict[str, dict]:
    return {tz_name: _run_probe(tz_name) for tz_name in TZ_CASES}


# 与 Node 探针中的 instants 一一对应的 aware UTC 时刻，用于和 core/time_rules.py 对账。
_INSTANT_DATETIMES = {
    "utc_iso": datetime(2026, 10, 3, 1, 23, 45, tzinfo=timezone.utc),
    "offset_iso": datetime(2026, 10, 3, 1, 23, 45, tzinfo=timezone.utc),
    "epoch_ms": datetime(2026, 10, 3, 1, 23, 45, 123000, tzinfo=timezone.utc),
    "date_object": datetime(2026, 10, 3, 1, 23, 45, tzinfo=timezone.utc),
    "cross_day": datetime(2026, 10, 31, 23, 30, tzinfo=timezone.utc),
    "year_end": datetime(2026, 12, 31, 20, 0, tzinfo=timezone.utc),
    "la_spring_forward": datetime(2026, 3, 8, 9, 59, 59, tzinfo=timezone.utc),
    "la_fall_back": datetime(2026, 11, 1, 8, 30, tzinfo=timezone.utc),
    "microseconds": datetime(2026, 5, 1, 8, 12, 34, 567890, tzinfo=timezone.utc),
}


# ── 验收 1：明确 Asia/Shanghai，不仅 zh-CN ─────────────────────────────────────


def test_zone_is_explicit_asia_shanghai(probe: dict[str, dict]) -> None:
    for tz_name, data in probe.items():
        assert data["tz"] == tz_name, f"TZ 环境变量未生效: {data['tz']!r}"
        assert data["constants"]["zone"] == "Asia/Shanghai"
        assert data["constants"]["offsetMinutes"] == 480
        label = data["constants"]["label"]
        assert "Asia/Shanghai" in label, f"时区标签必须写明 Asia/Shanghai，实际: {label!r}"
        for key, shown in data["displayed"].items():
            assert shown["zoned"].endswith("(Asia/Shanghai)"), (tz_name, key, shown["zoned"])
            assert shown["parts"]["tzName"] == "Asia/Shanghai"
            assert shown["parts"]["offsetMinutes"] == 480


def _strip_js_comments(source: str) -> str:
    """去掉注释后再做源级断言：注释里的说明文字不属于运行时依赖。"""
    without_block = re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)
    return re.sub(r"^\s*//.*$", "", without_block, flags=re.MULTILINE)


def test_module_does_not_lean_on_browser_locale() -> None:
    """源级补充断言：格式函数不得依赖 toLocale* / zh-CN 语言环境（行为一致性见下一用例）。"""
    source = _strip_js_comments(TIME_FORMAT_JS.read_text(encoding="utf-8"))
    for banned in ("toLocaleString", "toLocaleDateString", "toLocaleTimeString", "zh-CN"):
        assert banned not in source, f"北京时间显示不能依赖语言环境接口: {banned}"


# ── 验收 2：UTC / 上海 / 洛杉矶同一时刻显示一致 ────────────────────────────────


def test_same_instant_renders_identically_in_three_timezones(probe: dict[str, dict]) -> None:
    for key in probe["UTC"]["displayed"]:
        rendered = {
            tz_name: (
                data["displayed"][key]["minutes"],
                data["displayed"][key]["seconds"],
                data["displayed"][key]["date"],
                data["displayed"][key]["zoned"],
            )
            for tz_name, data in probe.items()
        }
        assert len(set(rendered.values())) == 1, f"{key} 在三地显示不一致: {rendered}"


def test_beijing_anchors_are_exact(probe: dict[str, dict]) -> None:
    """跨日 / 跨年 / 洛杉矶夏令时切换时刻都必须按北京时间落位。"""
    expected = {
        "utc_iso": "2026-10-03 09:23",
        "offset_iso": "2026-10-03 09:23",
        "epoch_ms": "2026-10-03 09:23",
        "date_object": "2026-10-03 09:23",
        "cross_day": "2026-11-01 07:30",
        "year_end": "2027-01-01 04:00",
        "la_spring_forward": "2026-03-08 17:59",
        "la_fall_back": "2026-11-01 16:30",
        "microseconds": "2026-05-01 16:12",
    }
    for tz_name, data in probe.items():
        for key, text in expected.items():
            assert data["displayed"][key]["minutes"] == text, (tz_name, key)
        assert data["displayed"]["cross_day"]["date"] == "2026-11-01"
        assert data["displayed"]["year_end"]["date"] == "2027-01-01"
        assert data["displayed"]["microseconds"]["seconds"] == "2026-05-01 16:12:34"


def test_frontend_text_matches_core_time_rules(probe: dict[str, dict]) -> None:
    """前端北京时间文本必须与 core/time_rules.format_beijing 逐条一致（C9 单一口径）。"""
    for tz_name, data in probe.items():
        for key, utc_dt in _INSTANT_DATETIMES.items():
            assert data["displayed"][key]["minutes"] == format_beijing(utc_dt), (tz_name, key)
        for text, rendered in data["pureDateOut"].items():
            assert rendered == pure_date(text).isoformat(), (tz_name, text)


# ── 验收 3a：纯日期不位移 ─────────────────────────────────────────────────────


def test_pure_date_never_shifts(probe: dict[str, dict]) -> None:
    for tz_name, data in probe.items():
        assert data["pureDateOut"] == {
            "2026-10-31": "2026-10-31",
            "2026-01-05": "2026-01-05",
            "2024-02-29": "2024-02-29",
            "2026-12-31": "2026-12-31",
        }, tz_name
        assert data["isPureDate"] == {"valid": True, "invalid": False, "instant": False}


def test_pure_date_and_instant_inputs_are_not_silently_converted(probe: dict[str, dict]) -> None:
    """纯日期不会被当成 UTC 零点换算（否则北京时间会变成当天 08:00），反之亦然。"""
    for tz_name, data in probe.items():
        errors = data["errors"]
        date_only = errors["instant_is_date_only"]
        assert date_only["threw"] is True, tz_name
        assert "纯日期" in date_only["message"] and "formatPureDate" in date_only["message"]

        naive = errors["instant_is_naive"]
        assert naive["threw"] is True
        assert "interpretNaiveTime" in naive["message"]

        for key in ("pure_date_is_instant", "pure_date_is_date_object", "pure_date_bad_calendar"):
            assert errors[key]["threw"] is True, (tz_name, key)


# ── 验收 3b：无时区历史值按来源契约解释 ───────────────────────────────────────

# local 来源按宿主时区解释：UTC 恒为 +00:00；上海恒为 +08:00；
# 洛杉矶按美国夏令时规则（2026-07 为 PDT -07:00，2026-01 与 2026-10-31 零点为 PST/PDT 见下）。
_EXPECTED_LOCAL_OFFSETS = {
    "UTC": {"july": "+00:00", "january": "+00:00", "date_only": "+00:00"},
    "Asia/Shanghai": {"july": "+08:00", "january": "+08:00", "date_only": "+08:00"},
    # 2026-10-31 00:00 洛杉矶仍在 PDT（11-01 02:00 才回拨）
    "America/Los_Angeles": {"july": "-07:00", "january": "-08:00", "date_only": "-07:00"},
}


def test_naive_tdc_and_aras_are_beijing_and_never_append_z(probe: dict[str, dict]) -> None:
    per_source: dict[str, dict] = {"tdc": {}, "aras": {}}
    for tz_name, data in probe.items():
        for source in ("tdc", "aras"):
            for key in ("july", "january", "date_only"):
                item = data["naive"][source][key]
                assert item["tzName"] == "Asia/Shanghai", (tz_name, source, key)
                assert item["iso"].endswith("+08:00"), (tz_name, source, key, item["iso"])
                assert not item["iso"].endswith("Z")
                assert item["offsetMinutes"] == 480
                assert "Asia/Shanghai" in item["rationale"]
                assert item["beijingText"] == item["naive"][:16]
                per_source[source].setdefault(key, set()).add(item["iso"])
    # 来源语义与宿主时区无关：三地解释出的时刻必须相同
    for source, by_key in per_source.items():
        for key, isos in by_key.items():
            assert len(isos) == 1, f"{source}/{key} 随宿主时区漂移: {isos}"


def test_naive_local_source_follows_host_timezone(probe: dict[str, dict]) -> None:
    for tz_name, data in probe.items():
        expected = _EXPECTED_LOCAL_OFFSETS[tz_name]
        for key, suffix in expected.items():
            item = data["naive"]["local"][key]
            assert item["source"] == "local"
            assert item["iso"].endswith(suffix), (tz_name, key, item["iso"])
            assert not item["iso"].endswith("Z")
            if suffix == "+08:00":
                # 宿主本身就在 UTC+8 时，本地墙钟与北京时间墙钟相同
                assert item["beijingText"] == item["naive"][:16], (tz_name, key)
        if tz_name != "Asia/Shanghai":
            assert data["naive"]["local"]["july"]["tzName"] != "Asia/Shanghai"


def test_naive_rejects_zoned_or_unknown_source(probe: dict[str, dict]) -> None:
    for tz_name, data in probe.items():
        errors = data["errors"]
        zoned = errors["naive_already_zoned"]
        assert zoned["threw"] is True, tz_name
        assert "时区指示" in zoned["message"]

        unknown = errors["naive_unknown_source"]
        assert unknown["threw"] is True
        assert "未知的数据来源" in unknown["message"]

        assert errors["naive_date_object"]["threw"] is True


# ── 交付路径：宿主以 ES module 提供该文件 ──────────────────────────────────────


@pytest.fixture()
def client(monkeypatch, tmp_path):  # type: ignore[no-untyped-def]
    import web.app as web_app

    db_cls = web_app.DatabaseManager
    monkeypatch.setattr(web_app, "DatabaseManager", lambda: db_cls(tmp_path / "time-format.db"))
    monkeypatch.delenv("VSE_TOOLBOX_PLUGIN_ONLY", raising=False)
    app = web_app.create_app(plugin_dirs=[tmp_path / "plugins"])
    app.config.update(TESTING=True)
    return app.test_client()


def test_module_is_served_as_javascript(client) -> None:  # type: ignore[no-untyped-def]
    response = client.get("/static/host/time-format.js")
    assert response.status_code == 200
    assert response.mimetype == "text/javascript"
    body = response.get_data(as_text=True)
    assert 'export const BEIJING_TZ = "Asia/Shanghai"' in body


def test_naive_slash_dates_match_dash_form_like_core_time_rules(probe: dict[str, dict]) -> None:
    """斜杠日期与破折号日期解释为同一时刻（与 core/time_rules.interpret_naive 一致）。"""
    from core.time_rules import interpret_naive

    for tz_name, data in probe.items():
        for source in ("tdc", "aras", "local"):
            slash = data["naive"][source]["slash_july"]
            dash = data["naive"][source]["july"]
            assert slash["epochMs"] == dash["epochMs"], (tz_name, source)
            assert slash["iso"] == dash["iso"], (tz_name, source)
    py = interpret_naive("2026/07/01 12:00:00", "tdc")
    assert int(py.dt.timestamp() * 1000) == probe["UTC"]["naive"]["tdc"]["slash_july"]["epochMs"]
