# -*- coding: utf-8 -*-
"""统一波次门禁编排脚本（dev / release 双模式）。

依次执行下列步骤并输出结构化结果（控制台摘要 + 可选 JSON 文件）：
① 聚焦测试：--focus <测试路径> 可传多次，逐个运行 python -m pytest <路径> -q；
② 全量回归：python -m pytest tests -q（--skip-full 可跳过，跳过时如实标记 SKIP）；
③ 项目地图校验：python tools/generate_project_map.py --check；
④ 术语门禁：python -m pytest tests/test_glossary_terms.py tests/test_ui_kit_terms.py -q
   （文件不存在则标记 SKIP 并说明）；
⑤ 浏览器通道：运行 tests/browser/test_browser_channel.py，并用 ``--junit-xml`` 实际报告
   判定 verified——只看报告里的通过/失败/跳过计数，不再以「探测到浏览器可执行文件」
   代替验证；
⑥ 打包验签：dev 模式 SKIP（留待 W17-03）；release 模式必须在 ``dist/releases/`` 找到
   最新 ``.vsepkg`` 包，并用 ``host/trusted_keys.json``（及 ``vse_boot/trusted_keys.json``）
   真实验签，未打包/未验签即失败。

两种模式（``--mode dev`` 默认 / ``--mode release``，亦可用 ``--release`` 简写）：
- dev：沿用既有轻量语义——``--focus`` 隐含跳过全量回归；SKIP 只需如实说明原因，不参与判定；
- release：全量回归、项目地图、术语门禁、浏览器通道、打包验签是**必需项**，任一 SKIP/FAIL
  即整体退出码非 0；``--focus`` 只追加聚焦测试，**不会**隐式跳过全量回归（显式
  ``--skip-full`` 会让必需项 SKIP，同样判定失败）。

任一步失败时整体退出码非 0，并打印失败步骤名与最多 40 行的输出尾部（bounded tail）。
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from typing import Optional
import xml.etree.ElementTree as ET

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

MODE_DEV = "dev"
MODE_RELEASE = "release"
MODES = (MODE_DEV, MODE_RELEASE)

BROWSER_TEST_FILE = "tests/browser/test_browser_channel.py"
TERM_TEST_FILES = ("tests/test_glossary_terms.py", "tests/test_ui_kit_terms.py")
PACKAGE_DIR = "dist/releases"
TRUSTED_KEY_FILES = ("host/trusted_keys.json", "vse_boot/trusted_keys.json")
APP_ENTRY = "webui.py"

#: 各模式的「必需步骤」：必需步骤一旦 SKIP 或 FAIL，整体门禁即判定失败。
#: dev 保持既有语义（只看有无 FAIL）；release 严格模式把这些步骤列为必需项。
REQUIRED_STEPS: dict[str, tuple[str, ...]] = {
    MODE_DEV: (),
    MODE_RELEASE: (
        "full_regression",
        "project_map",
        "glossary_terms",
        "browser_channel",
        "package_sign",
    ),
}


@dataclass
class StepResult:
    """门禁步骤执行结果。"""

    name: str
    display_name: str
    status: str  # "PASS" | "FAIL" | "SKIP"
    command: list[str] = field(default_factory=list)
    exit_code: Optional[int] = None
    details: str = ""
    tail: list[str] = field(default_factory=list)
    required: bool = False


@dataclass(frozen=True)
class PytestReport:
    """从 pytest ``--junit-xml`` 实际报告里解析出的计数。"""

    total: int = 0
    passed: int = 0
    failed: int = 0
    errors: int = 0
    skipped: int = 0

    @property
    def executed(self) -> int:
        """真正执行过的用例数（通过 + 失败 + 错误）。"""
        return self.passed + self.failed + self.errors

    def summary(self) -> str:
        """人类可读的计数摘要。"""
        return (
            f"通过 {self.passed} / 失败 {self.failed} / "
            f"错误 {self.errors} / 跳过 {self.skipped}"
        )


@dataclass(frozen=True)
class ChannelInfo:
    """浏览器通道探测结果（仅用于展示；verified 由测试报告决定）。"""

    name: Optional[str] = None
    path: Optional[str] = None
    available: bool = False
    reason: str = ""


@dataclass(frozen=True)
class BrowserChannelStatus:
    """门禁摘要里的浏览器通道状态。"""

    status: str  # "verified" | "failed" | "skipped"
    verified: bool
    summary: str
    channel_name: Optional[str] = None
    executable: Optional[str] = None
    reason: str = ""
    report: Optional[PytestReport] = None


def run_command(cmd: list[str], cwd: Path) -> tuple[int, str, list[str]]:
    """执行外部命令并提取退出码、完整输出与最多 40 行尾部内容。"""
    env = os.environ.copy()
    env.update({"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"})
    try:
        proc = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            check=False,
        )
        stdout = proc.stdout or ""
        stderr = proc.stderr or ""
        combined = stdout + ("\n" if stdout and stderr else "") + stderr
        lines = combined.splitlines()
        tail = lines[-40:] if len(lines) > 40 else lines
        return proc.returncode, combined, tail
    except Exception as exc:
        err_msg = f"启动进程异常: {exc}"
        return 1, err_msg, [err_msg]


def parse_junit_report(path: Path) -> Optional[PytestReport]:
    """解析 pytest ``--junit-xml`` 报告；文件缺失或损坏时返回 None（=没有证据）。"""
    try:
        root = ET.parse(str(path)).getroot()
    except (OSError, ET.ParseError, ValueError):
        return None
    if root.tag == "testsuite":
        suites = [root]
    else:
        suites = list(root.iter("testsuite"))
    if not suites:
        return None

    def attr(node: ET.Element, name: str) -> int:
        try:
            return max(int(float(node.get(name) or 0)), 0)
        except (TypeError, ValueError):
            return 0

    total = failed = errors = skipped = 0
    for suite in suites:
        total += attr(suite, "tests")
        failed += attr(suite, "failures")
        errors += attr(suite, "errors")
        skipped += attr(suite, "skipped")
    passed = max(total - failed - errors - skipped, 0)
    return PytestReport(
        total=total, passed=passed, failed=failed, errors=errors, skipped=skipped
    )


def detect_browser_channel() -> ChannelInfo:
    """探测本机浏览器通道（仅用于展示通道名/路径，不作为 verified 依据）。"""
    try:
        from tests.browser.test_browser_channel import find_browser_channel

        channel = find_browser_channel()
    except Exception as exc:  # 探测模块不可用不影响门禁判定，只影响摘要文案
        return ChannelInfo(reason=f"探测模块导入异常: {exc}")
    return ChannelInfo(
        name=getattr(channel, "name", None),
        path=str(channel.path) if getattr(channel, "path", None) else None,
        available=bool(getattr(channel, "available", False)),
        reason=str(getattr(channel, "reason", "") or ""),
    )


def execute_browser_channel_step(
    repo_root: Path, report_dir: Path
) -> tuple[StepResult, Optional[PytestReport]]:
    """运行浏览器通道测试，并返回基于实际报告解析出的步骤结果。"""
    display = "浏览器通道"
    if not (repo_root / BROWSER_TEST_FILE).is_file():
        details = f"测试文件不存在 ({BROWSER_TEST_FILE})"
        return (
            StepResult(
                name="browser_channel",
                display_name=display,
                status="SKIP",
                details=details,
            ),
            None,
        )

    report_path = Path(report_dir) / "browser_channel.xml"
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        "-p",
        "no:cacheprovider",
        "--junit-xml",
        str(report_path),
        BROWSER_TEST_FILE,
        "-q",
    ]
    code, _output, tail = run_command(cmd, repo_root)
    report = parse_junit_report(report_path)

    if report is None:
        # 没有报告 = 没有验证证据：不能因为「探测到可执行文件」就判 verified。
        return (
            StepResult(
                name="browser_channel",
                display_name=display,
                status="FAIL",
                command=cmd,
                exit_code=code if code != 0 else 1,
                details="未取得 pytest 报告（无 verified 依据）",
                tail=tail,
            ),
            None,
        )

    if code != 0 or report.failed or report.errors:
        return (
            StepResult(
                name="browser_channel",
                display_name=display,
                status="FAIL",
                command=cmd,
                exit_code=code if code != 0 else 1,
                details=f"测试失败 ({report.summary()})",
                tail=tail,
            ),
            report,
        )

    if report.passed == 0:
        return (
            StepResult(
                name="browser_channel",
                display_name=display,
                status="SKIP",
                command=cmd,
                exit_code=code,
                details=f"浏览器通道不可用，测试全部跳过 ({report.summary()})",
            ),
            report,
        )

    return (
        StepResult(
            name="browser_channel",
            display_name=display,
            status="PASS",
            command=cmd,
            exit_code=code,
            details=f"来自实际测试报告 ({report.summary()})",
        ),
        report,
    )


def probe_browser_status(
    channel: ChannelInfo,
    report: Optional[PytestReport],
    step: Optional[StepResult] = None,
) -> BrowserChannelStatus:
    """由实际测试报告判定浏览器通道状态；探测到的可执行文件只用于展示。"""
    exec_path = channel.path
    name = channel.name

    if report is None:
        reason = "未取得浏览器测试报告，不能判定已验证"
        if step is not None and step.details:
            reason = f"{reason}（{step.details}）"
        return BrowserChannelStatus(
            status="skipped",
            verified=False,
            summary=f"未验证 ({reason})",
            channel_name=name,
            executable=exec_path,
            reason=reason,
        )

    counts = report.summary()
    if step is not None and step.status == "FAIL":
        reason = f"浏览器通道测试失败（{counts}）"
        return BrowserChannelStatus(
            status="failed",
            verified=False,
            summary=f"测试失败 ({name or '未知通道'}: {exec_path or '未探测到路径'})",
            channel_name=name,
            executable=exec_path,
            reason=reason,
            report=report,
        )

    if report.passed > 0 and not report.failed and not report.errors:
        reason = f"来自实际测试报告（{counts}）"
        return BrowserChannelStatus(
            status="verified",
            verified=True,
            summary=f"已验证 ({name or '浏览器通道'}: {exec_path or '未探测到路径'})",
            channel_name=name,
            executable=exec_path,
            reason=reason,
            report=report,
        )

    reason = f"浏览器测试未产生通过用例（{counts}）"
    if not channel.available and channel.reason:
        reason = f"{reason}；{channel.reason}"
    return BrowserChannelStatus(
        status="skipped",
        verified=False,
        summary=f"已跳过 ({reason})",
        channel_name=name,
        executable=exec_path,
        reason=reason,
        report=report,
    )


def find_release_packages(repo_root: Path) -> list[Path]:
    """列出 ``dist/releases/`` 下的 .vsepkg 包，版本号高的排前面。"""
    package_dir = Path(repo_root) / PACKAGE_DIR
    if not package_dir.is_dir():
        return []
    packages = [p for p in package_dir.glob("*.vsepkg") if p.is_file()]

    def version_key(path: Path) -> tuple[int, ...]:
        numbers = re.findall(r"\d+", path.stem)
        return tuple(int(n) for n in numbers) if numbers else (0,)

    return sorted(packages, key=lambda p: (version_key(p), p.name), reverse=True)


def execute_package_sign_step(repo_root: Path, mode: str) -> StepResult:
    """打包验签步骤：dev 恒 SKIP；release 必须找到包并真实验签。"""
    display = "打包验签"
    if mode != MODE_RELEASE:
        return StepResult(
            name="package_sign",
            display_name=display,
            status="SKIP",
            details="留待 W17-03（dev 模式不校验打包）",
        )

    try:
        from vse_boot.packages import (  # noqa: PLC0415 - 延迟导入，避免 dev 门禁强依赖
            TARGET_RUNTIME_TAG,
            PackageError,
            load_trusted_keys,
            verify_app_package,
        )
    except Exception as exc:
        return StepResult(
            name="package_sign",
            display_name=display,
            status="FAIL",
            details=f"验签模块不可用: {exc}",
        )

    packages = find_release_packages(repo_root)
    if not packages:
        return StepResult(
            name="package_sign",
            display_name=display,
            status="FAIL",
            details=f"未打包：{PACKAGE_DIR}/ 下没有 .vsepkg 包",
        )

    keys = load_trusted_keys([Path(repo_root) / name for name in TRUSTED_KEY_FILES])
    if not keys:
        return StepResult(
            name="package_sign",
            display_name=display,
            status="FAIL",
            details=f"未验签：未配置可信公钥 ({', '.join(TRUSTED_KEY_FILES)})",
        )

    target = packages[0]
    relative = target.relative_to(Path(repo_root)).as_posix()
    try:
        data = target.read_bytes()
    except OSError as exc:
        return StepResult(
            name="package_sign",
            display_name=display,
            status="FAIL",
            details=f"未打包：无法读取 {relative}（{exc}）",
        )

    try:
        verified = verify_app_package(data, keys, runtime_tag=TARGET_RUNTIME_TAG)
    except PackageError as exc:
        return StepResult(
            name="package_sign",
            display_name=display,
            status="FAIL",
            details=f"未验签：{relative} 校验失败（{exc}）",
        )
    except Exception as exc:  # 任何异常都不得当作验签通过
        return StepResult(
            name="package_sign",
            display_name=display,
            status="FAIL",
            details=f"未验签：{relative} 校验异常（{exc}）",
        )

    if APP_ENTRY not in verified.files:
        return StepResult(
            name="package_sign",
            display_name=display,
            status="FAIL",
            details=f"未打包：{relative} 缺少程序入口 {APP_ENTRY}",
        )

    return StepResult(
        name="package_sign",
        display_name=display,
        status="PASS",
        details=(
            f"{relative} 已验签 (v{verified.version}, keyId={verified.key_id}, "
            f"{len(verified.files)} 个文件, runtime {verified.runtime})"
        ),
    )


def resolve_skip_full(mode: str, skip_full: bool, focus_targets: list[str]) -> bool:
    """决定是否跳过全量回归。

    dev 模式沿用既有轻量语义：给了 ``--focus`` 就隐含跳过全量回归。
    release 模式只认显式 ``--skip-full``——``--focus`` 绝不隐式跳过全量回归
    （显式跳过会让必需项 SKIP，门禁判定失败）。
    """
    if mode == MODE_RELEASE:
        return bool(skip_full)
    return bool(skip_full) or bool(focus_targets)


def evaluate_gate(
    step_results: list[StepResult],
    mode: str,
    browser_verified: bool = False,
) -> tuple[bool, list[str]]:
    """按模式判定整体门禁：返回 (是否通过, 未通过原因列表)。"""
    required = set(REQUIRED_STEPS.get(mode, ()))
    reasons: list[str] = []

    for step in step_results:
        if step.status == "FAIL":
            reasons.append(f"{step.display_name} 失败（退出码: {step.exit_code}）")
        elif step.status == "SKIP":
            if step.name in required:
                detail = f"：{step.details}" if step.details else ""
                reasons.append(
                    f"{step.display_name} 是 {mode} 模式必需项，但被 SKIP{detail}"
                )
            elif not step.details.strip():
                reasons.append(f"{step.display_name} SKIP 未说明原因")

    if mode == MODE_RELEASE and not browser_verified:
        browser_step = next(
            (s for s in step_results if s.name == "browser_channel"), None
        )
        # 步骤 PASS 但报告没给出通过用例：属于自相矛盾，单独记一条原因。
        if browser_step is not None and browser_step.status == "PASS":
            reasons.append("release 模式要求浏览器通道 verified，但报告未给出通过用例")

    return (not reasons, reasons)


def execute_wave_gate(
    focus_targets: list[str],
    skip_full: bool,
    out_file: Optional[str] = None,
    mode: str = MODE_DEV,
) -> int:
    """顺序执行波次门禁全套步骤并输出摘要与结果文件。"""
    if mode not in MODES:
        raise ValueError(f"未知门禁模式: {mode}")
    step_results: list[StepResult] = []
    required_names = set(REQUIRED_STEPS[mode])
    print(f"==> 门禁模式: {mode}" + ("（严格 release：必需项 SKIP 即失败）" if mode == MODE_RELEASE else ""))

    # ① 聚焦测试：--focus <测试路径> 可传多次，逐个运行
    print("==> [1/6] 聚焦测试")
    if not focus_targets:
        step_results.append(
            StepResult(
                name="focus_tests",
                display_name="聚焦测试",
                status="SKIP",
                details="未指定聚焦测试路径",
            )
        )
        print("    [SKIP] 未指定 --focus 目标")
    else:
        focus_success = True
        focus_details: list[str] = []
        combined_tail: list[str] = []
        first_fail_code: Optional[int] = None

        for target in focus_targets:
            cmd = [sys.executable, "-m", "pytest", target, "-q"]
            print(f"    -> 运行聚焦测试: {' '.join(cmd)}")
            code, output, tail = run_command(cmd, REPO_ROOT)
            if code != 0:
                focus_success = False
                if first_fail_code is None:
                    first_fail_code = code
                focus_details.append(f"{target} (FAIL)")
                combined_tail.extend(tail)
            else:
                focus_details.append(f"{target} (PASS)")

        bounded_tail = (
            combined_tail[-40:] if len(combined_tail) > 40 else combined_tail
        )
        step_results.append(
            StepResult(
                name="focus_tests",
                display_name="聚焦测试",
                status="PASS" if focus_success else "FAIL",
                command=[sys.executable, "-m", "pytest", *focus_targets, "-q"],
                exit_code=0 if focus_success else (first_fail_code or 1),
                details="; ".join(focus_details),
                tail=[] if focus_success else bounded_tail,
            )
        )
        print(f"    [{step_results[-1].status}] {'; '.join(focus_details)}")

    # ② 全量回归：python -m pytest tests -q（--skip-full 可跳过）
    print("==> [2/6] 全量回归")
    if skip_full:
        step_results.append(
            StepResult(
                name="full_regression",
                display_name="全量回归",
                status="SKIP",
                details="已指定 --skip-full 跳过",
                required="full_regression" in required_names,
            )
        )
        print("    [SKIP] 已指定 --skip-full 跳过")
    else:
        cmd = [sys.executable, "-m", "pytest", "tests", "-q"]
        print(f"    -> 运行全量测试: {' '.join(cmd)}")
        code, output, tail = run_command(cmd, REPO_ROOT)
        step_results.append(
            StepResult(
                name="full_regression",
                display_name="全量回归",
                status="PASS" if code == 0 else "FAIL",
                command=cmd,
                exit_code=code,
                details="python -m pytest tests -q",
                tail=[] if code == 0 else tail,
                required="full_regression" in required_names,
            )
        )
        print(f"    [{step_results[-1].status}] 全量测试 (退出码: {code})")

    # ③ 项目地图校验：python tools/generate_project_map.py --check
    print("==> [3/6] 项目地图校验")
    cmd_map = [sys.executable, "tools/generate_project_map.py", "--check"]
    print(f"    -> 校验项目地图: {' '.join(cmd_map)}")
    code, output, tail = run_command(cmd_map, REPO_ROOT)
    step_results.append(
        StepResult(
            name="project_map",
            display_name="项目地图校验",
            status="PASS" if code == 0 else "FAIL",
            command=cmd_map,
            exit_code=code,
            details="tools/generate_project_map.py --check",
            tail=[] if code == 0 else tail,
            required="project_map" in required_names,
        )
    )
    print(f"    [{step_results[-1].status}] 项目地图校验 (退出码: {code})")

    # ④ 术语门禁：python -m pytest tests/test_glossary_terms.py tests/test_ui_kit_terms.py -q
    print("==> [4/6] 术语门禁")
    term_files = list(TERM_TEST_FILES)
    existing_terms = [f for f in term_files if (REPO_ROOT / f).is_file()]
    if not existing_terms:
        step_results.append(
            StepResult(
                name="glossary_terms",
                display_name="术语门禁",
                status="SKIP",
                details=f"测试文件不存在 ({', '.join(term_files)})",
                required="glossary_terms" in required_names,
            )
        )
        print(f"    [SKIP] 测试文件不存在 ({', '.join(term_files)})")
    else:
        cmd_terms = [sys.executable, "-m", "pytest", *existing_terms, "-q"]
        print(f"    -> 运行术语门禁测试: {' '.join(cmd_terms)}")
        code, output, tail = run_command(cmd_terms, REPO_ROOT)
        missing_terms = [f for f in term_files if f not in existing_terms]
        missing_note = f" (缺: {', '.join(missing_terms)})" if missing_terms else ""
        # release 下必需项缺任何一个测试文件都不得 PASS（缺文件即失败）。
        terms_status = "PASS" if code == 0 else "FAIL"
        if mode == MODE_RELEASE and missing_terms:
            terms_status = "FAIL"
        step_results.append(
            StepResult(
                name="glossary_terms",
                display_name="术语门禁",
                status=terms_status,
                command=cmd_terms,
                exit_code=code,
                details=f"pytest {' '.join(existing_terms)}{missing_note}",
                tail=[] if code == 0 else tail,
                required="glossary_terms" in required_names,
            )
        )
        print(f"    [{step_results[-1].status}] 术语门禁测试 (退出码: {code})")

    # ⑤ 浏览器通道：运行浏览器测试并解析实际报告（verified 只来自报告）
    print("==> [5/6] 浏览器通道")
    with tempfile.TemporaryDirectory(prefix="wave_gate_browser_") as report_dir:
        browser_step, browser_report = execute_browser_channel_step(
            REPO_ROOT, Path(report_dir)
        )
    browser_step.required = "browser_channel" in required_names
    step_results.append(browser_step)
    print(f"    [{browser_step.status}] {browser_step.details}")

    # ⑥ 打包验签步骤
    print("==> [6/6] 打包验签")
    package_step = execute_package_sign_step(REPO_ROOT, mode)
    package_step.required = "package_sign" in required_names
    step_results.append(package_step)
    print(f"    [{package_step.status}] {package_step.details}")

    # 浏览器通道真实状态（由报告判定）
    browser_status = probe_browser_status(
        detect_browser_channel(), browser_report, browser_step
    )

    overall_passed, gate_reasons = evaluate_gate(
        step_results, mode, browser_status.verified
    )

    # 控制台摘要输出
    print("\n" + "=" * 70)
    print(f"波次门禁执行摘要（模式: {mode}）".center(62))
    print("=" * 70)
    for idx, step in enumerate(step_results, start=1):
        status_tag = f"[{step.status}]".ljust(8)
        required_tag = "*" if step.required else " "
        details_txt = f"- {step.details}" if step.details else ""
        print(f"  {idx}.{required_tag}{step.display_name.ljust(12)} {status_tag} {details_txt}")
    print("-" * 70)
    print(f"  浏览器通道: {browser_status.summary}")
    print(f"  必需项:     {', '.join(sorted(required_names)) if required_names else '（dev 模式无必需项，只看 FAIL）'}")
    print(f"  门禁判定:   {'通过 (PASS)' if overall_passed else '未通过 (FAIL)'}")
    if gate_reasons:
        for reason in gate_reasons:
            print(f"    - {reason}")
    print("=" * 70)

    # 若有步骤失败，打印失败步骤名与最多 40 行的输出尾部（bounded tail）
    failed_steps = [s for s in step_results if s.status == "FAIL"]
    if failed_steps:
        print("\n" + "#" * 70)
        print("失败步骤详情与输出尾部（最多 40 行）".center(56))
        print("#" * 70)
        for s in failed_steps:
            print(f"\n--- [失败步骤: {s.display_name}] (退出码: {s.exit_code}) ---")
            if s.tail:
                for line in s.tail:
                    print(line)
            else:
                print("(无详细输出)")
        print("#" * 70)

    # 若指定了 --out 则导出结构化 JSON 报告
    if out_file:
        out_path = Path(out_file)
        if not out_path.is_absolute():
            out_path = REPO_ROOT / out_path
        out_path.parent.mkdir(parents=True, exist_ok=True)
        report_data = {
            "mode": mode,
            "gate_status": "PASS" if overall_passed else "FAIL",
            "passed": overall_passed,
            "gate_reasons": gate_reasons,
            "required_steps": sorted(required_names),
            "browser_channel": {
                "status": browser_status.status,
                "verified": browser_status.verified,
                "summary": browser_status.summary,
                "channel_name": browser_status.channel_name,
                "executable": browser_status.executable,
                "reason": browser_status.reason,
                "report": (
                    {
                        "total": browser_status.report.total,
                        "passed": browser_status.report.passed,
                        "failed": browser_status.report.failed,
                        "errors": browser_status.report.errors,
                        "skipped": browser_status.report.skipped,
                    }
                    if browser_status.report is not None
                    else None
                ),
            },
            "steps": [
                {
                    "name": s.name,
                    "display_name": s.display_name,
                    "status": s.status,
                    "required": s.required,
                    "exit_code": s.exit_code,
                    "details": s.details,
                    "tail": s.tail,
                }
                for s in step_results
            ],
        }
        out_path.write_text(
            json.dumps(report_data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"\n结构化门禁报告已写入: {out_path}")

    return 0 if overall_passed else 1


def build_parser() -> argparse.ArgumentParser:
    """构造命令行解析器（便于测试直接驱动 main）。"""
    parser = argparse.ArgumentParser(
        description=(
            "统一波次门禁编排脚本（聚焦测试、全量回归、项目地图、术语门禁、"
            "浏览器通道报告、打包验签）"
        )
    )
    parser.add_argument(
        "--focus",
        action="append",
        default=[],
        help="聚焦测试路径，可传多次逐个运行",
    )
    parser.add_argument(
        "--skip-full",
        action="store_true",
        help="跳过全量回归测试步骤（release 模式下会让必需项 SKIP 并判定失败）",
    )
    parser.add_argument(
        "--out",
        type=str,
        default=None,
        help="结构化结果输出 JSON 文件路径（可选）",
    )
    parser.add_argument(
        "--mode",
        choices=MODES,
        default=MODE_DEV,
        help="门禁模式：dev（默认，轻量）/ release（严格，必需项 SKIP 即失败）",
    )
    parser.add_argument(
        "--release",
        action="store_true",
        help="等价于 --mode release（严格 release 门禁）",
    )
    return parser


def main(argv: Optional[list[str]] = None) -> None:
    """命令行入口解析。"""
    args = build_parser().parse_args(argv)
    mode = MODE_RELEASE if args.release else args.mode

    # dev 模式语义：给了 --focus 就是一次轻量门禁，隐含跳过全量回归
    # （全量只在无 --focus 的正式门禁或显式 --skip-full=False 场景跑，如实标 SKIP）。
    # release 模式不继承这条隐含规则：--focus 只追加聚焦测试，全量回归照跑。
    skip_full = resolve_skip_full(mode, args.skip_full, args.focus)
    if mode == MODE_RELEASE and args.skip_full:
        print(
            "警告：release 模式下 --skip-full 会让必需项「全量回归」SKIP，门禁将判定失败。",
            file=sys.stderr,
        )

    exit_code = execute_wave_gate(
        focus_targets=args.focus,
        skip_full=skip_full,
        out_file=args.out,
        mode=mode,
    )
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
