# -*- coding: utf-8 -*-
"""Excel 路径安全校验服务。

范围说明（DSH-V2-26，P1）：本模块不是生产执行边界。生产路径的提交与执行边界是
core.excel_tasks.ApprovedExcelRoots（ExcelTaskFileRef 规范化 + resolve_ref），
消费点为 core/excel_tasks.py 的 create_task、core/excel_worker.py 的执行期解析，
以及 services/excel_task_admin.py 的只读展示。本模块在生产代码中没有任何调用方，
保留仅供既有测试（tests/test_excel_path_safety.py）与后续退役评估；不要把它接入
生产路径，否则会形成第二套不一致的路径规则。

根据 docs/refactor-v2/CONTRACTS.md C10 契约，对用户输入的路径进行安全校验：
1. 拒绝目录穿越（.. 段）；
2. 拒绝 UNC 网络共享路径（以 \\\\ 或 // 开头）；
3. 拒绝 NTFS ADS 备用数据流（文件名中含有冒号的流名称）；
4. 拒绝白名单根目录外的越界访问（包括符号链接、junction、重解析点解析后越界）；
5. 拒绝白名单根内路径替换（如盘符根目录替换等）。

对外接口：
- ExcelPathSafetyError: 路径安全校验失败异常（继承 ValueError）。
- validate_excel_path(root, user_path): 单白名单根安全校验，返回解析后的安全绝对路径。
- validate_excel_paths(roots, user_path): 多白名单根安全校验。
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Sequence


class ExcelPathSafetyError(ValueError):
    """Excel 路径安全校验异常。

    面向用户的错误原因均采用通俗中文，避免暴露内部实现细节与敏感系统信息。
    """


def _check_intrinsic_safety(user_path: str) -> None:
    """对用户输入进行基础结构安全检测（无需依赖白名单根）。

    拦截：空输入、空字符注入、UNC 共享、目录穿越段（..）、ADS 备用数据流、驱动器相对路径。
    """
    if not isinstance(user_path, str):
        raise ExcelPathSafetyError("所选位置格式无效")

    raw = user_path.strip()
    if not raw:
        raise ExcelPathSafetyError("所选位置不能为空")

    # 拦截空字符截断注入
    if "\x00" in raw:
        raise ExcelPathSafetyError("所选位置包含非法空字符")

    # 1. 拦截 UNC 路径（如 \\server\share 或 //server/share 等）
    if raw.startswith(("\\\\", "//", "\\/", "/\\")):
        raise ExcelPathSafetyError("所选位置属于网络共享（UNC），只支持本地存储")

    # 2. 拦截目录穿越（.. 段）
    # 无论是正斜杠还是反斜杠分隔，任何段名为 ".." 均属穿越攻击
    raw_segments = [seg.strip() for seg in re.split(r"[\\/]+", raw) if seg.strip()]
    if any(seg == ".." for seg in raw_segments):
        raise ExcelPathSafetyError("所选位置包含上级目录（..），禁止跨级访问")

    # 3. 拦截 NTFS ADS 备用数据流
    # 在 Windows 下，仅允许合法的盘符冒号（如 C:），其余任何位置出现冒号均视为 ADS 数据流
    drive_match = re.match(r"^[A-Za-z]:", raw)
    remainder = raw[drive_match.end() :] if drive_match else raw
    if ":" in remainder:
        raise ExcelPathSafetyError("所选位置包含附加数据流（:），只支持常规文件")

    # 4. 拦截驱动器相对路径（如 C:file.xlsx，没有前置斜杠，极易受当前工作目录污染）
    if drive_match and not raw[2:].startswith(("\\", "/")):
        raise ExcelPathSafetyError("不支持驱动器相对位置，必须使用完整位置或纯相对位置")


def _is_within_root(resolved_target: Path, resolved_root: Path) -> bool:
    """判断已解析的绝对路径是否严格位于白名单根目录内部。

    在 Windows 环境下做大小写不敏感匹配，同时支持标准 relative_to 计算。
    """
    # 先尝试标准 relative_to
    try:
        resolved_target.relative_to(resolved_root)
        return True
    except ValueError:
        pass

    # Windows 文件系统通常不区分大小写，规范化各段后比对前缀
    if sys.platform == "win32":
        try:
            target_parts = tuple(p.lower() for p in resolved_target.parts)
            root_parts = tuple(p.lower() for p in resolved_root.parts)
            if len(target_parts) >= len(root_parts) and target_parts[: len(root_parts)] == root_parts:
                return True
        except Exception:
            return False

    return False


def validate_excel_path(root: Path | str, user_path: str) -> Path:
    """校验用户提供的路径是否安全且严格限定在给定的白名单根目录内。

    Args:
        root: 白名单根目录（Path 或目录字符串）。
        user_path: 用户提供的相对或绝对路径。

    Returns:
        解析后的安全绝对路径（Path 对象）。

    Raises:
        ExcelPathSafetyError: 存在目录穿越、UNC、ADS、越界或路径替换等安全风险。
    """
    _check_intrinsic_safety(user_path)

    raw = user_path.strip()
    root_path = Path(root).resolve()

    # 判断用户输入是否为绝对路径或带盘符根目录
    has_drive = bool(re.match(r"^[A-Za-z]:[\\/]", raw))
    has_leading_slash = raw.startswith(("/", "\\"))

    if has_drive or (has_leading_slash and sys.platform != "win32"):
        candidate = Path(raw)
    elif has_leading_slash and sys.platform == "win32":
        # Windows 下带根斜杠但无盘符，属于驱动器根替换（如 \outside\file.xlsx）
        candidate = Path(raw)
    else:
        # 纯相对路径：拼接到白名单根目录下
        candidate = root_path / raw

    # 解析符号链接、junction、重解析点与真实物理路径
    try:
        resolved_target = candidate.resolve()
    except (OSError, RuntimeError) as exc:
        raise ExcelPathSafetyError(f"所选位置无法解析：{exc}") from exc

    # 必须严格落在白名单根内（解决软链接越界、junction 逃逸以及路径替换等）
    if not _is_within_root(resolved_target, root_path):
        raise ExcelPathSafetyError("所选位置超出允许的安全目录范围")

    return resolved_target


def validate_excel_paths(roots: Sequence[Path | str], user_path: str) -> Path:
    """校验用户提供的路径是否安全且落在多个白名单根目录中的至少一个内。

    Args:
        roots: 白名单根目录列表。
        user_path: 用户提供的相对或绝对路径。

    Returns:
        解析后的安全绝对路径（Path 对象）。

    Raises:
        ExcelPathSafetyError: 路径不安全或不属于任何已配置的白名单根。
    """
    if not roots:
        raise ExcelPathSafetyError("未配置任何允许的安全目录")

    # 优先执行基础语法检测，确保语法违规报出具体原因（如穿越、UNC、ADS 等）
    _check_intrinsic_safety(user_path)

    raw = user_path.strip()
    is_absolute_form = bool(re.match(r"^[A-Za-z]:[\\/]", raw)) or raw.startswith(("/", "\\"))

    if is_absolute_form:
        # 绝对路径形态：依次比对各白名单根
        for root in roots:
            try:
                return validate_excel_path(root, user_path)
            except ExcelPathSafetyError:
                continue
        raise ExcelPathSafetyError("所选位置不在任何允许的安全目录范围内")

    # 相对路径形态：优先匹配已存在文件的白名单根，不存在时匹配首个有效白名单根
    for root in roots:
        try:
            target = validate_excel_path(root, user_path)
            if target.exists():
                return target
        except ExcelPathSafetyError:
            continue

    # 若尚未创建文件，尝试挂载在首个能安全容纳的白名单根下
    for root in roots:
        try:
            return validate_excel_path(root, user_path)
        except ExcelPathSafetyError:
            continue

    raise ExcelPathSafetyError("所选位置不在任何允许的安全目录范围内")
