# -*- coding: utf-8 -*-
"""执行槽持久化的薄再导出（实现已下沉 ``services/schedule_slots``，DSH-V2-20）。

分层原因（勿破）：调度器在 ``services.project_status_scheduler``，服务层不得 import
插件；因此 DSH-V2-19 的实现原样下沉到 ``services.schedule_slots``，本模块只做再导出，
插件 ``backend.py`` 与 ``tests/test_schedule_slots.py`` 因此不需要任何改动。
"""

from __future__ import annotations

from services.schedule_slots import *  # noqa: F401,F403
from services.schedule_slots import __all__ as __all__
