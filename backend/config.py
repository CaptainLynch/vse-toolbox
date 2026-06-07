"""共享配置、目录常量和路径安全工具。独立模块，无内部导入，避免循环导入。"""

import sys
from pathlib import Path


def _get_data_root() -> Path:
    """持久化数据根目录。PyInstaller 打包后 __file__ 指向临时解压目录，
    因此需要将可写目录（data/logs/temp/output）放在 exe 所在目录下。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).parent.parent


BASE_DIR = Path(__file__).parent.resolve()
DATA_ROOT = _get_data_root()
DATA_DIR = DATA_ROOT / "data"
TEMP_DIR = DATA_ROOT / "temp"
LOGS_DIR = DATA_ROOT / "logs"
DIST_DIR = BASE_DIR / "dist"

# 确保运行时目录存在
for d in (DATA_DIR, TEMP_DIR, LOGS_DIR):
    d.mkdir(parents=True, exist_ok=True)

# 路径安全白名单
SAFE_BASE_DIRS = [
    TEMP_DIR.resolve(),
    DATA_DIR.resolve(),
    (DATA_ROOT / "templates" / "output").resolve(),
    (BASE_DIR / "templates" / "master").resolve(),
    (BASE_DIR / "templates" / "config").resolve(),
]


def safe_path(user_input: str, base_dir: Path | None = None) -> Path:
    """防止路径遍历攻击。使用 is_relative_to 做真正的子目录检查。"""
    if base_dir is not None:
        resolved = (base_dir / user_input).resolve()
        if not resolved.is_relative_to(base_dir.resolve()):
            raise ValueError(f"非法路径: {user_input}")
        return resolved

    candidate = Path(user_input).resolve()
    for safe in SAFE_BASE_DIRS:
        if candidate.is_relative_to(safe):
            return candidate
    raise ValueError(f"非法路径: {user_input}")
