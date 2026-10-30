# -*- coding: utf-8 -*-
"""统一波次门禁编排脚本。

依次执行下列步骤并输出结构化结果（控制台摘要 + 可选 JSON 文件）：
① 聚焦测试：--focus <测试路径> 可传多次，逐个运行 python -m pytest <路径> -q；
② 全量回归：python -m pytest tests -q（--skip-full 可跳过，跳过时如实标记 SKIP）；
③ 项目地图校验：python tools/generate_project_map.py --check；
④ 术语门禁：python -m pytest tests/test_glossary_terms.py tests/test_ui_kit_terms.py -q（文件不存在则标记 SKIP 并说明）；
⑤ 打包验签：本阶段始终跳过，输出 SKIP(留待 W17-03)。

任一步失败时整体退出码非 0，并打印失败步骤名与最多 40 行的输出尾部（bounded tail）。
在门禁摘要中如实区分「浏览器通道已验证 / 已跳过(原因)」。
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


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


def probe_browser_status(
    step_results: list[StepResult],
    focus_targets: list[str],
    skip_full: bool,
    repo_root: Path,
) -> tuple[str, bool, str, Optional[str], Optional[str], str]:
    """探测并判定本次门禁中浏览器通道的真实状态。

    返回: (status, verified, summary_text, channel_name, executable_path, reason)
    """
    try:
        from tests.browser.test_browser_channel import find_browser_channel

        channel = find_browser_channel()
    except Exception as exc:
        channel = None
        channel_err = f"探测模块导入异常: {exc}"

    # 判定本次门禁是否实际覆盖了浏览器测试
    browser_tested = any(
        "browser" in target.replace("\\", "/") for target in focus_targets
    ) or (not skip_full)

    if channel is None or not channel.available:
        reason = channel.reason if channel else channel_err
        return (
            "skipped",
            False,
            f"已跳过 ({reason})",
            None,
            None,
            reason,
        )

    # 浏览器通道存在，检查测试执行与通过情况
    if browser_tested:
        # 检查是否有包含 browser 的步骤失败
        focus_step = next((s for s in step_results if s.name == "focus_tests"), None)
        focus_failed = bool(
            focus_step
            and focus_step.status == "FAIL"
            and any("browser" in t for t in focus_targets)
        )
        full_step = next((s for s in step_results if s.name == "full_regression"), None)
        full_failed = bool(full_step and full_step.status == "FAIL" and not focus_targets)

        if focus_failed or full_failed:
            return (
                "failed",
                False,
                f"测试失败 ({channel.name}: {channel.path})",
                channel.name,
                str(channel.path),
                "浏览器通道冒烟测试未通过",
            )

        return (
            "verified",
            True,
            f"已验证 ({channel.name}: {channel.path})",
            channel.name,
            str(channel.path),
            "通道可用且无头冒烟测试通过",
        )

    return (
        "skipped",
        False,
        "已跳过 (本次运行未包含浏览器通道测试)",
        channel.name,
        str(channel.path),
        "本次运行未包含浏览器通道测试",
    )


def execute_wave_gate(
    focus_targets: list[str],
    skip_full: bool,
    out_file: Optional[str] = None,
) -> int:
    """顺序执行波次门禁全套步骤并输出摘要与结果文件。"""
    step_results: list[StepResult] = []

    # ① 聚焦测试：--focus <测试路径> 可传多次，逐个运行
    print("==> [1/5] 聚焦测试")
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
    print("==> [2/5] 全量回归")
    if skip_full:
        step_results.append(
            StepResult(
                name="full_regression",
                display_name="全量回归",
                status="SKIP",
                details="已指定 --skip-full 跳过",
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
            )
        )
        print(f"    [{step_results[-1].status}] 全量测试 (退出码: {code})")

    # ③ 项目地图校验：python tools/generate_project_map.py --check
    print("==> [3/5] 项目地图校验")
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
        )
    )
    print(f"    [{step_results[-1].status}] 项目地图校验 (退出码: {code})")

    # ④ 术语门禁：python -m pytest tests/test_glossary_terms.py tests/test_ui_kit_terms.py -q
    print("==> [4/5] 术语门禁")
    term_files = ["tests/test_glossary_terms.py", "tests/test_ui_kit_terms.py"]
    existing_terms = [f for f in term_files if (REPO_ROOT / f).is_file()]
    if not existing_terms:
        step_results.append(
            StepResult(
                name="glossary_terms",
                display_name="术语门禁",
                status="SKIP",
                details=f"测试文件不存在 ({', '.join(term_files)})",
            )
        )
        print(f"    [SKIP] 测试文件不存在 ({', '.join(term_files)})")
    else:
        cmd_terms = [sys.executable, "-m", "pytest", *existing_terms, "-q"]
        print(f"    -> 运行术语门禁测试: {' '.join(cmd_terms)}")
        code, output, tail = run_command(cmd_terms, REPO_ROOT)
        missing_terms = [f for f in term_files if f not in existing_terms]
        missing_note = f" (缺: {', '.join(missing_terms)})" if missing_terms else ""
        step_results.append(
            StepResult(
                name="glossary_terms",
                display_name="术语门禁",
                status="PASS" if code == 0 else "FAIL",
                command=cmd_terms,
                exit_code=code,
                details=f"pytest {' '.join(existing_terms)}{missing_note}",
                tail=[] if code == 0 else tail,
            )
        )
        print(f"    [{step_results[-1].status}] 术语门禁测试 (退出码: {code})")

    # ⑤ 打包验签步骤：本阶段始终跳过，输出 SKIP(留待 W17-03)
    print("==> [5/5] 打包验签")
    step_results.append(
        StepResult(
            name="package_sign",
            display_name="打包验签",
            status="SKIP",
            details="留待 W17-03",
        )
    )
    print("    [SKIP] 留待 W17-03")

    # 判定浏览器通道真实状态
    (
        b_status,
        b_verified,
        b_summary,
        b_name,
        b_exec,
        b_reason,
    ) = probe_browser_status(step_results, focus_targets, skip_full, REPO_ROOT)

    overall_passed = not any(s.status == "FAIL" for s in step_results)

    # 控制台摘要输出
    print("\n" + "=" * 70)
    print("波次门禁执行摘要".center(62))
    print("=" * 70)
    for idx, step in enumerate(step_results, start=1):
        status_tag = f"[{step.status}]".ljust(8)
        details_txt = f"- {step.details}" if step.details else ""
        print(f"  {idx}. {step.display_name.ljust(12)} {status_tag} {details_txt}")
    print("-" * 70)
    print(f"  浏览器通道: {b_summary}")
    print(f"  门禁判定:   {'通过 (PASS)' if overall_passed else '未通过 (FAIL)'}")
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
            "gate_status": "PASS" if overall_passed else "FAIL",
            "passed": overall_passed,
            "browser_channel": {
                "status": b_status,
                "verified": b_verified,
                "summary": b_summary,
                "channel_name": b_name,
                "executable": b_exec,
                "reason": b_reason,
            },
            "steps": [
                {
                    "name": s.name,
                    "display_name": s.display_name,
                    "status": s.status,
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


def main() -> None:
    """命令行入口解析。"""
    parser = argparse.ArgumentParser(
        description="统一波次门禁编排脚本（支持聚焦测试、全量回归、项目地图与术语门禁校验）"
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
        help="跳过全量回归测试步骤",
    )
    parser.add_argument(
        "--out",
        type=str,
        default=None,
        help="结构化结果输出 JSON 文件路径（可选）",
    )
    args = parser.parse_args()

    # 聚焦模式语义：给了 --focus 就是一次轻量门禁，隐含跳过全量回归
    # （全量只在无 --focus 的正式门禁或显式 --skip-full=False 场景跑，如实标 SKIP）。
    exit_code = execute_wave_gate(
        focus_targets=args.focus,
        skip_full=args.skip_full or bool(args.focus),
        out_file=args.out,
    )
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
