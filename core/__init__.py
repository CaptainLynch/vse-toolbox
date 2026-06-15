# -*- coding: utf-8 -*-
"""
core/__init__.py — 核心模块包初始化

导出核心组件，便于上层模块直接导入。
"""

from core.db_manager import DatabaseManager

__all__ = ["DatabaseManager"]
