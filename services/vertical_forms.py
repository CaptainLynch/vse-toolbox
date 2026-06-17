# -*- coding: utf-8 -*-
"""
services/vertical_forms.py — 垂类表单占位模块

本模块为四类垂直业务表单提供空类占位骨架。
当前版本仅包含 NotImplementedError 占位，待真实模板接入后由后续 Sprint 实现。

包含的表单类:
    - EWOForm         工程变更单
    - NCRForm         不合格报告
    - DMUReviewForm   数模审核单
    - StylingReviewForm 造型数据审核单
"""

from typing import Any


class EWOForm:
    """工程变更单（Engineering Work Order）表单占位类。"""

    def fill(self, *args: Any, **kwargs: Any) -> None:
        """填写工程变更单，待真实模板接入后实现。"""
        raise NotImplementedError("待真实模板接入")


class NCRForm:
    """不合格报告（Non-Conformance Report）表单占位类。"""

    def fill(self, *args: Any, **kwargs: Any) -> None:
        """填写不合格报告，待真实模板接入后实现。"""
        raise NotImplementedError("待真实模板接入")


class DMUReviewForm:
    """数模审核单（DMU Review）表单占位类。"""

    def fill(self, *args: Any, **kwargs: Any) -> None:
        """填写数模审核单，待真实模板接入后实现。"""
        raise NotImplementedError("待真实模板接入")


class StylingReviewForm:
    """造型数据审核单（Styling Review）表单占位类。"""

    def fill(self, *args: Any, **kwargs: Any) -> None:
        """填写造型数据审核单，待真实模板接入后实现。"""
        raise NotImplementedError("待真实模板接入")
