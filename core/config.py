# -*- coding: utf-8 -*-
"""
core/config.py — 集中配置常量模块

职责:
    为整个 VSE TOOLBOX 项目提供统一的路径常量与无敏感默认配置值。

架构约束:
    - 无类、无业务逻辑
    - 不 import rich / flask / 任何界面库
    - 严禁存放任何明文密码 / token / 凭据
    - service 层与 core 层通过本模块获取路径，禁止各模块自行拼接路径
"""

from pathlib import Path

from core.runtime_paths import app_root

# ── 项目根目录（本文件位于 core/，向上一级即为项目根） ─────────────
PROJECT_ROOT: Path = app_root()

# ── 数据目录体系 ────────────────────────────────────────────────
DATA_DIR: Path = PROJECT_ROOT / "data"
OUTPUT_DIR: Path = DATA_DIR / "output"
TEMPLATE_DIR: Path = DATA_DIR / "templates"
BACKUP_DIR: Path = DATA_DIR / ".backup"

# ── 数据库路径 ──────────────────────────────────────────────────
DB_PATH: Path = DATA_DIR / "vse_toolbox.db"

# ── 网络默认值（无敏感信息） ────────────────────────────────────
DEFAULT_INTRANET_URL: str = "https://intranet.example.com"
DEFAULT_IMAP_HOST: str = "imap.example.com"
DEFAULT_IMAP_PORT: int = 993

# ── Flask WEB 服务默认绑定 ──────────────────────────────────────
FLASK_HOST: str = "127.0.0.1"
FLASK_PORT: int = 5000
