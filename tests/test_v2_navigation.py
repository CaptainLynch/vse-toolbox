# -*- coding: utf-8 -*-
"""v2 simplified navigation: five everyday entries, legacy entries only in expert mode."""

from __future__ import annotations

from pathlib import Path

import pytest

from host.plugin import PluginManifestError, load_manifest, parse_manifest

REPO = Path(__file__).resolve().parent.parent
BASE = {"id": "demo", "name": "演示", "version": "1.0.0", "hostApi": ">=1,<2", "pages": [{"id": "main", "title": "主页"}]}


def all_nav() -> list[dict]:
    entries = []
    for manifest_file in sorted((REPO / "plugins").glob("*/plugin.json")):
        manifest = load_manifest(manifest_file.parent)
        entries += [{"plugin": manifest.id, **entry.to_payload()} for entry in manifest.nav]
    return sorted(entries, key=lambda e: e["order"])


def test_everyday_navigation_is_today_project_reports_tools_settings() -> None:
    visible = [e["title"] for e in all_nav() if not e.get("expert")]
    assert visible == ["今天", "项目", "报告", "工具", "设置"]


def test_every_hidden_entry_points_at_a_visible_parent() -> None:
    entries = all_nav()
    visible = {f"{e['plugin']}/{e['page']}" for e in entries if not e.get("expert")}
    hidden = [e for e in entries if e.get("expert")]
    assert hidden, "旧入口应在专家模式下仍然可用"
    assert all(e.get("parent") in visible for e in hidden)


def test_nav_expert_and_parent_are_optional_and_validated() -> None:
    plain = parse_manifest({**BASE, "nav": [{"title": "演示", "page": "main"}]})
    assert plain.nav[0].to_payload() == {"title": "演示", "page": "main", "order": 100}
    flagged = parse_manifest({**BASE, "nav": [{"title": "演示", "page": "main", "expert": True, "parent": "workbench/tools"}]})
    assert flagged.nav[0].to_payload()["expert"] is True and flagged.nav[0].parent == "workbench/tools"
    with pytest.raises(PluginManifestError):
        parse_manifest({**BASE, "nav": [{"title": "演示", "page": "main", "expert": "yes"}]})
    with pytest.raises(PluginManifestError):
        parse_manifest({**BASE, "nav": [{"title": "演示", "page": "main", "parent": "no-slash"}]})
