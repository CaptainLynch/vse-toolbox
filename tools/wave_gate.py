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
⑥ 打包验签与整包一致性：dev 模式 SKIP（留待 W17-03）；release 模式必须在 ``dist/releases/``
   找到最新 ``.vsepkg`` 包，并用 ``host/trusted_keys.json``（及 ``vse_boot/trusted_keys.json``）
   真实验签，未打包/未验签即失败。验签通过后还要核对整包一致性：包版本 = 仓库当前应用版本
   （复用 ``core.version.get_app_version_info``）、包内已跟踪文件与 ``HEAD`` 内容一致、工作区
   没有涉及包内文件的未提交改动；并且 ``--since REF`` 基线内有 ``vse_boot/`` / ``*.spec``
   等启动器改动时，``dist/releases/`` 必须同时有同版本 onedir 宿主包（``*<version>*.zip``），
   否则「启动器改动不能只发 app 包」直接失败。

两种模式（``--mode dev`` 默认 / ``--mode release``，亦可用 ``--release`` 简写）：
- dev：沿用既有轻量语义——``--focus`` 隐含跳过全量回归；SKIP 只需如实说明原因，不参与判定；
- release：全量回归、项目地图、术语门禁、浏览器通道、打包验签是**必需项**，任一 SKIP/FAIL
  即整体退出码非 0；``--focus`` 只追加聚焦测试，**不会**隐式跳过全量回归（显式
  ``--skip-full`` 会让必需项 SKIP，同样判定失败）；``--since REF`` 是 release 模式的
  比较基线，缺省时打包验签步骤判定失败。

任一步失败时整体退出码非 0，并打印失败步骤名与最多 40 行的输出尾部（bounded tail）。
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from typing import Any, Optional
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
#: 启动器/运行时相关路径：改动这些文件必须整包发 onedir zip，不能只发 app 包
#: （见 docs/refactor-v2/RELEASE_MATRIX.md 的发布通道表）。
LAUNCHER_PATH_PREFIXES = ("vse_boot/", "runtime/")
LAUNCHER_PATH_SUFFIXES = (".spec",)
#: 与 app 包同版本的 onedir 宿主包命名形如 ``VSE-Toolbox-v<version>-test.zip``。
ONEDIR_ZIP_GLOB = "*{version}*.zip"

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


def find_onedir_packages(repo_root: Path, version: str) -> list[Path]:
    """列出 ``dist/releases/`` 下与 app 包同版本的 onedir 宿主包（``*<version>*.zip``）。

    文件名里的版本必须**精确**匹配：``*1.0*.zip`` 这种子串口径会让 1.0.1 的包替 1.0
    通过启动器覆盖检查，所以 glob 之后再用数字/点边界复核一次。
    """
    package_dir = Path(repo_root) / PACKAGE_DIR
    if not package_dir.is_dir():
        return []
    pattern = ONEDIR_ZIP_GLOB.format(version=version)
    exact = re.compile(rf"(?<![\d.]){re.escape(version)}(?!\d|\.\d)")
    return sorted(
        path
        for path in package_dir.glob(pattern)
        if path.is_file() and exact.search(path.name)
    )


def is_launcher_path(path: str) -> bool:
    """判断改动路径是否属于启动器/运行时（这类改动不能只发 app 包）。"""
    normalized = path.replace("\\", "/")
    for prefix in LAUNCHER_PATH_PREFIXES:
        if normalized == prefix.rstrip("/") or normalized.startswith(prefix):
            return True
    lowered = normalized.lower()
    return any(lowered.endswith(suffix) for suffix in LAUNCHER_PATH_SUFFIXES)


def format_paths(paths: list[str], limit: int = 10) -> str:
    """把路径列表压成一行可读文本（最多 ``limit`` 个，其余只报数量）。"""
    shown = ", ".join(paths[:limit])
    if len(paths) > limit:
        return f"{shown} 等 {len(paths)} 个"
    return shown


def _git_command(
    repo_root: Path, args: list[str], *, stdin: bytes = b""
) -> tuple[int, bytes, str]:
    """执行 git 命令（参数数组 + ``cwd=repo_root``），返回 (退出码, stdout 字节, stderr)。

    ``OSError``（git 不可执行）由调用方转成 FAIL——不得把「校验跑不起来」当作通过。
    """
    env = os.environ.copy()
    env.update({"GIT_TERMINAL_PROMPT": "0", "GIT_OPTIONAL_LOCKS": "0", "LC_ALL": "C"})
    proc = subprocess.run(
        ["git", *args],
        cwd=str(repo_root),
        input=stdin,
        capture_output=True,
        env=env,
        check=False,
    )
    stderr = (proc.stderr or b"").decode("utf-8", "replace").strip()
    return proc.returncode, proc.stdout or b"", stderr


class GitCheckError(RuntimeError):
    """git 校验无法完成（仓库损坏、被 git 拒绝、路径口径不一致）；消息可读、可直接展示。"""


def find_git_worktree_root(repo_root: Path) -> Optional[Path]:
    """返回与 ``repo_root`` 完全一致的 git 工作树根。

    只有「目录里根本没有 ``.git``」才返回 ``None``（真的不是仓库，调用方退回仅验签语义，
    以兼容既有测试里的临时非 git 目录）。只要有 ``.git`` 但 git 报错（损坏的 gitdir、
    ``dubious ownership`` 拒绝等），或工作树根与 ``repo_root`` 不一致，一律抛
    :class:`GitCheckError` → FAIL，并带上 git 自己的 stderr，绝不静默降级。
    """
    root = Path(repo_root)
    # lexists：悬空的 .git 符号链接/联接点也算“有 .git”，不得降级为仅验签。
    has_git_entry = os.path.lexists(root / ".git")
    code, out, err = _git_command(root, ["rev-parse", "--show-toplevel"])
    if code != 0:
        if not has_git_entry:
            return None
        raise GitCheckError(f"git 无法识别该仓库（{err or f'退出码 {code}'}）")
    try:
        resolved_top = Path(out.decode("utf-8").strip()).resolve()
        resolved_root = root.resolve()
    except (OSError, ValueError) as exc:
        raise GitCheckError(f"无法解析 git 工作树根（{exc}）") from None
    if os.path.normcase(str(resolved_top)) != os.path.normcase(str(resolved_root)):
        raise GitCheckError(
            f"仓库根不一致：git 工作树根为 {resolved_top}，门禁检查目录为 {resolved_root}"
        )
    return resolved_top


def parse_porcelain_paths(raw: bytes) -> list[str]:
    """解析 ``git status --porcelain -z``，返回已跟踪条目的路径（跳过未跟踪/忽略）。"""
    entries = raw.split(b"\0")
    paths: list[str] = []
    index = 0
    while index < len(entries):
        entry = entries[index]
        index += 1
        if len(entry) < 4:
            continue
        status = entry[:2]
        path = entry[3:].decode("utf-8", "replace")
        if status in (b"??", b"!!"):
            continue
        paths.append(path)
        if b"R" in status or b"C" in status:
            # 重命名/复制条目后面紧跟一条原路径，跳过它。
            index += 1
    return paths


def read_head_blobs(repo_root: Path, paths: list[str]) -> tuple[dict[str, bytes], str]:
    """用 ``git cat-file --batch`` 一次取出 ``HEAD:<path>`` 的原始字节（按字节，不做换行转换）。"""
    if not paths:
        return {}, ""
    payload = b"".join(b"HEAD:" + path.encode("utf-8") + b"\n" for path in paths)
    code, out, err = _git_command(repo_root, ["cat-file", "--batch"], stdin=payload)
    if code != 0:
        return {}, f"无法读取 HEAD 内容（git cat-file 失败：{err or code}）"
    blobs: dict[str, bytes] = {}
    cursor = 0
    for path in paths:
        newline = out.find(b"\n", cursor)
        if newline < 0:
            return {}, "无法读取 HEAD 内容（git cat-file 输出不完整）"
        header = out[cursor:newline].split()
        cursor = newline + 1
        if len(header) != 3:
            continue  # ``<输入> missing``：HEAD 里没有这个路径
        try:
            size = int(header[2])
        except ValueError:
            return {}, "无法读取 HEAD 内容（git cat-file 输出无法解析）"
        blobs[path] = out[cursor : cursor + size]
        cursor += size + 1
    return blobs, ""


def _normalize_version(text: str) -> str:
    return text.strip().lstrip("vV")


def check_release_consistency(
    repo_root: Path, verified: Any, since: Optional[str]
) -> tuple[bool, str]:
    """release 整包一致性校验：版本 / 提交内容 / 工作区 / 启动器覆盖。

    返回 ``(是否通过, 说明)``：通过时说明是证据摘要，失败时说明是可读中文原因。
    只有「``repo_root`` 里根本没有 ``.git``」才退回「仅验签 + 入口」的既有语义（并如实
    写明跳过原因）；只要有 ``.git`` 却无法完成 git 校验（损坏、被 git 拒绝、工作树根与
    ``repo_root`` 不一致）或任何 git 调用失败，一律返回 FAIL，不静默放过。
    """
    try:
        worktree = find_git_worktree_root(Path(repo_root))
    except GitCheckError as exc:
        return False, f"无法校验提交一致性：{exc}"
    except OSError as exc:
        return False, f"无法执行 git 校验提交一致性（{exc}）"
    if worktree is None:
        return True, "非 git 工作树：跳过版本/提交一致性校验（沿用仅验签 + 入口的既有语义）"
    if not since:
        return False, "未指定比较基线（release 模式必须提供 --since REF）"

    # ① 版本一致：包版本必须等于仓库当前应用版本（复用 core.version，不新建版本口径）。
    try:
        from core.version import get_app_version_info  # noqa: PLC0415 - 延迟导入
    except Exception as exc:  # 版本口径不可用同样不能算通过
        return False, f"版本口径不可用（core.version 导入失败：{exc}）"
    try:
        version_info = get_app_version_info()
    except Exception as exc:
        return False, f"读取仓库当前应用版本失败（{exc}）"
    repo_version = str(version_info.get("rawVersion") or "").strip()
    if not repo_version:
        return (
            False,
            f"仓库当前应用版本未知（无 version.json/VERSION/构建注入），"
            f"无法与包版本 v{verified.version} 比对",
        )
    if _normalize_version(repo_version) != _normalize_version(verified.version):
        return (
            False,
            f"版本不一致：包 v{verified.version}，仓库当前应用版本 v{repo_version}",
        )

    package_paths = list(verified.files)

    # ② 工作区状态：已跟踪文件的未提交改动只要涉及包内文件，包就不是当前提交的产物。
    code, status_raw, err = _git_command(Path(repo_root), ["status", "--porcelain", "-z"])
    if code != 0:
        return False, f"无法读取工作区状态（git status 失败：{err or code}）"
    dirty = set(parse_porcelain_paths(status_raw))
    dirty_hits = sorted(path for path in package_paths if path in dirty)
    if dirty_hits:
        return (
            False,
            "工作区与包不一致：已跟踪文件有未提交改动且涉及包内文件（"
            f"{format_paths(dirty_hits)}）",
        )

    # ③ 内容即提交：包内已跟踪文件的 sha256 必须等于 HEAD 内容（按字节，不做换行转换）。
    code, tracked_raw, err = _git_command(Path(repo_root), ["ls-files", "-z"])
    if code != 0:
        return False, f"无法读取 git 跟踪文件列表（git ls-files 失败：{err or code}）"
    tracked = {entry for entry in tracked_raw.split(b"\0") if entry}
    tracked_package = [path for path in package_paths if path.encode("utf-8") in tracked]
    untracked = [path for path in package_paths if path.encode("utf-8") not in tracked]
    blobs, blob_error = read_head_blobs(Path(repo_root), tracked_package)
    if blob_error:
        return False, blob_error

    mismatches: list[str] = []
    checkout_normalized = 0
    for path in tracked_package:
        content = verified.files[path]
        blob = blobs.get(path)
        if blob is not None and hashlib.sha256(blob).digest() == hashlib.sha256(content).digest():
            continue
        worktree_file = Path(repo_root) / path
        # 工作区与 HEAD 无内容差异（git status 已确认干净）时，字节不同只可能来自
        # git 自己的检出换行规范化（本仓库 core.autocrlf=true：blob 存 LF、工作区是 CRLF）。
        # 这时包内文件仍等于 HEAD 在该机器上的检出内容，如实计数但不判 FAIL。
        try:
            worktree_matches = worktree_file.is_file() and worktree_file.read_bytes() == content
        except OSError:
            worktree_matches = False
        if worktree_matches:
            checkout_normalized += 1
            continue
        mismatches.append(path)
    if mismatches:
        return False, f"包内容与 HEAD 不一致（{format_paths(mismatches)}）"

    notes = [f"{len(tracked_package)} 个已跟踪文件与 HEAD 内容一致"]
    if checkout_normalized:
        notes.append(f"{checkout_normalized} 个文件按 git 检出换行规范化后一致")
    if untracked:
        notes.append(f"{len(untracked)} 个生成文件未被 git 跟踪（仅计数）")

    # ④ 启动器覆盖：基线内动了 vse_boot/ 或 *.spec，就必须同时有同版本 onedir 宿主包。
    #    基线先做校验：以 '-' 开头的值会被 git 当成选项（--output=... 会写文件）。
    if since.startswith("-"):
        return False, f"比较基线无效（{since}）：不允许以 '-' 开头的引用"
    code, _out, err = _git_command(
        Path(repo_root),
        ["rev-parse", "--verify", "--end-of-options", f"{since}^{{commit}}"],
    )
    if code != 0:
        return False, f"无法比较基线 {since}（git rev-parse 失败：{err or code}）"
    code, diff_raw, err = _git_command(
        Path(repo_root), ["diff", "--name-only", "-z", f"{since}..HEAD"]
    )
    if code != 0:
        return False, f"无法比较基线 {since}（git diff 失败：{err or code}）"
    changed = [
        entry.decode("utf-8", "replace") for entry in diff_raw.split(b"\0") if entry
    ]
    launcher_changes = [path for path in changed if is_launcher_path(path)]
    if launcher_changes:
        onedir = find_onedir_packages(Path(repo_root), verified.version)
        if not onedir:
            return (
                False,
                "启动器改动不能只发 app 包：基线 "
                f"{since}..HEAD 修改了启动器路径（{format_paths(launcher_changes)}），"
                f"但 {PACKAGE_DIR}/ 下没有与包同版本的 onedir 宿主包"
                f"（*{verified.version}*.zip）",
            )
        notes.append(f"启动器改动已配同版本 onedir 宿主包 {onedir[0].name}")
    else:
        notes.append(f"基线 {since}..HEAD 无启动器改动")

    return True, "；".join(notes)


def execute_package_sign_step(
    repo_root: Path, mode: str, since: Optional[str] = None
) -> StepResult:
    """打包验签步骤：dev 恒 SKIP；release 必须找到包并真实验签 + 核对整包一致性。

    ``since`` 是 release 模式的比较基线（``--since REF``）；为 ``None`` 时，release 模式在
    有 ``.git`` 的仓库里 FAIL「未指定比较基线」；只有目录里根本没有 ``.git`` 才退回既有语义
    （既有直接调用 ``execute_package_sign_step(repo_root, mode)`` 的单元测试不受影响）。
    """
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

    try:
        consistent, consistency_detail = check_release_consistency(
            Path(repo_root), verified, since
        )
    except Exception as exc:  # 一致性校验异常同样不得当作通过
        return StepResult(
            name="package_sign",
            display_name=display,
            status="FAIL",
            details=f"未通过整包一致性：{relative} 校验异常（{exc}）",
        )
    if not consistent:
        return StepResult(
            name="package_sign",
            display_name=display,
            status="FAIL",
            details=f"未通过整包一致性：{relative} {consistency_detail}",
        )

    return StepResult(
        name="package_sign",
        display_name=display,
        status="PASS",
        details=(
            f"{relative} 已验签 (v{verified.version}, keyId={verified.key_id}, "
            f"{len(verified.files)} 个文件, runtime {verified.runtime})；"
            f"{consistency_detail}"
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
    since: Optional[str] = None,
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
    package_step = execute_package_sign_step(REPO_ROOT, mode, since=since)
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
    parser.add_argument(
        "--since",
        type=str,
        default=None,
        help=(
            "release 模式的比较基线 REF（如 HEAD~1 / 上一个发布 tag）：基线内有启动器改动时"
            "必须同时发同版本 onedir 宿主包；release 模式缺省即判定失败"
        ),
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

    if mode == MODE_RELEASE and args.since is None:
        print(
            "警告：release 模式未提供 --since 比较基线，打包验签步骤将判定失败。",
            file=sys.stderr,
        )

    gate_kwargs: dict[str, Any] = {
        "focus_targets": args.focus,
        "skip_full": skip_full,
        "out_file": args.out,
        "mode": mode,
    }
    # 未指定 --since 时不传该关键字：既有调用方/测试替身仍按旧签名接收参数，
    # release 缺基线由打包验签步骤判定 FAIL（见 check_release_consistency）。
    if args.since is not None:
        gate_kwargs["since"] = args.since
    exit_code = execute_wave_gate(**gate_kwargs)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
