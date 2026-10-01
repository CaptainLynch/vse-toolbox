# -*- coding: utf-8 -*-
"""Scheduled-archive plugin backend.

The module page talks to the existing legacy endpoints under
``/api/scheduled-archive/*`` (owned by ``web/app.py``, which already applies
the local-only write guard). This plugin therefore adds no routes of its own;
``register`` is intentionally a no-op so the host can mount the plugin.
"""

from __future__ import annotations


def register(host):  # noqa: ARG001 - host contract requires the hook
    return None
