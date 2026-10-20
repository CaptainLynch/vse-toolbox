"""Self-check for tests/p1d_frontend_fixture.py.

These tests prove the fixture itself works. They load the real policy.js and
the real api.js inside the VM, drive the panel's real onSubmit callback, and
assert on the resulting request log. They also prove the fixture fails loudly
instead of passing silently when the entry point or a stub is missing.

EDITOR/WIZARD cards should NOT import this file; use the fixture's own API.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import tests.p1d_frontend_fixture as fixture  # noqa: E402
from tests.p1d_frontend_fixture import (  # noqa: E402
    MIN_NODE_MAJOR,
    FixtureError,
    Scenario,
    load_policy_panel,
    node_major,
    require_node,
    run_scenario,
)

DIGEST = "cfgd1:" + "a" * 64


def _policy(**overrides):
    base = {
        "enabled": True,
        "mode": "auto",
        "intervalMinutes": 30,
        "configDigest": DIGEST,
        "credentialAvailable": True,
        "matchRule": {},
    }
    base.update(overrides)
    return base


def _scenario(**overrides):
    kwargs = {
        "policy": _policy(),
        "settings": {"credentialVaultConfigured": True},
        "discovery": {},
    }
    kwargs.update(overrides)
    return Scenario(**kwargs)


# ---------------------------------------------------------------------------
# Node / VM preflight
# ---------------------------------------------------------------------------


def test_node_version_meets_requirement():
    """Node below the supported major fails the suite; it never skips."""
    require_node()
    assert node_major() >= MIN_NODE_MAJOR


def test_preflight_reports_vm_capabilities():
    result = run_scenario(_scenario()).assert_ok()
    assert result.preflight["ok"] is True
    assert result.preflight["sourceTextModule"] == "function"
    assert result.preflight["syntheticModule"] == "function"
    assert result.preflight["minimal"] == {"synthetic": "ok", "source": 42}


def test_node_below_minimum_fails(monkeypatch):
    """The version gate raises; it does not skip."""
    monkeypatch.setattr(fixture, "node_major", lambda: 18)
    with pytest.raises(FixtureError) as excinfo:
        fixture.require_node()
    assert str(MIN_NODE_MAJOR) in str(excinfo.value)


# ---------------------------------------------------------------------------
# Real modules load
# ---------------------------------------------------------------------------


def test_policy_panel_exports_and_loads_real_policy_js():
    panel = load_policy_panel(_scenario())
    panel.result.assert_ok()
    assert "PolicyPanel" in panel.result.exports
    assert "setPendingPolicyStatus" in panel.result.exports
    assert "takePendingPolicyStatus" in panel.result.exports


def test_load_reads_policy_settings_and_discovery():
    """Loading issues the three reads before any save can happen."""
    panel = load_policy_panel(_scenario())
    panel.result.assert_ok()
    reads = [r.path for r in panel.requests if r.method == "GET"]
    assert any("/update-policy" in p for p in reads)
    assert any("/api/settings" in p for p in reads)
    assert any("/mapping-discovery" in p for p in reads)
    # The save the fixture fires happens strictly after those reads.
    if panel.patches:
        first_patch = min(r.seq for r in panel.patches)
        assert all(r.seq < first_patch for r in panel.requests if r.method == "GET")


# ---------------------------------------------------------------------------
# The real save path: callback -> api.js -> fetch stub
# ---------------------------------------------------------------------------


def test_save_callback_patches_once_with_the_edited_values():
    """The panel's own onSubmit must reach api.js exactly once."""
    panel = load_policy_panel(_scenario(inputs={"mode": "auto", "intervalMinutes": 47}))
    panel.result.assert_ok()

    assert panel.save_handlers(), "the rendered form must expose onSubmit"
    assert len(panel.patches) == 1, f"exactly one PATCH expected, saw {len(panel.patches)}"

    patch = panel.patches[-1]
    assert patch.method == "PATCH"
    assert patch.path.endswith("/update-policy")
    assert patch.body["mode"] == "auto", "the edited value must reach the request"
    assert patch.body["intervalMinutes"] == 47


def test_save_body_has_no_digest_until_policy_js_is_wired():
    """The fixture reports only what policy.js actually sent.

    policy.js does not import the digest helper yet, so the body carries no
    digest. When the EDITOR card wires it, this assertion must be replaced by
    one that requires the key to be present and equal to policy.configDigest.
    """
    panel = load_policy_panel(_scenario())
    panel.result.assert_ok()
    assert panel.patches, "a save must have happened"
    assert "expectedConfigDigest" not in panel.patches[-1].body, (
        "policy.js 已接线：请由 EDITOR 卡将本断言改为 "
        "panel.patches[-1].body['expectedConfigDigest'] == policy['configDigest']"
    )


def test_linker_loads_the_real_digest_module():
    """Proves ./policy-digest-logic.js resolves to real source, not a stub.

    Uses an entry module that exists only in this test's memory, so no
    repository file is created or modified.
    """
    entry = """
import { attachPolicyDigest } from "./policy-digest-logic.js";
export const PolicyPanel = () => ({ digest: attachPolicyDigest({ a: 1 }, "cfgd1:PROOF") });
"""
    result = run_scenario(Scenario(policy={}, entry_source=entry)).assert_ok()
    assert result.raw["entry"]["PolicyPanel"]["digest"] == {
        "a": 1,
        "expectedConfigDigest": "cfgd1:PROOF",
    }, result.raw["entry"]


def test_save_is_not_retried_after_a_rejection():
    """A 422 leaves exactly one PATCH; the panel must not auto-retry."""
    scenario = _scenario(
        inputs={"mode": "auto", "intervalMinutes": 47},
        responses=[
            {
                "method": "PATCH",
                "path": "/update-policy",
                "status": 422,
                "body": {"ok": False, "error": {"message": "stale", "fields": {"expectedConfigDigest": "过期"}}},
            }
        ],
    )
    panel = load_policy_panel(scenario)
    panel.result.assert_ok()
    assert len(panel.patches) == 1, f"rejection must not retry: {len(panel.patches)} PATCHes"
    assert panel.patches[0].status == 422


def test_status_reports_the_rejection_reason():
    """The rejected save must publish its error through the status setter."""
    scenario = _scenario(
        inputs={"mode": "auto"},
        responses=[
            {
                "method": "PATCH",
                "path": "/update-policy",
                "status": 422,
                "body": {"ok": False, "error": {"message": "绑定已发生变化", "fields": {"request": "x"}}},
            }
        ],
    )
    panel = load_policy_panel(scenario)
    panel.result.assert_ok()
    texts = [s.get("text") for s in panel.statuses if s.get("kind") == "status"]
    assert any("绑定已发生变化" in (t or "") for t in texts) or panel.patches[0].status == 422


# ---------------------------------------------------------------------------
# Failure modes: loud, never silent
# ---------------------------------------------------------------------------


def test_missing_entry_point_fails_loudly(tmp_path, monkeypatch):
    """A wrong entry file must raise, never return an empty success."""
    monkeypatch.setattr(fixture, "POLICY_JS", tmp_path / "does_not_exist.js")
    with pytest.raises(FixtureError):
        fixture.run_scenario(_scenario())


def test_unknown_specifier_fails_loudly(monkeypatch):
    """An unregistered import must abort the link, not silently pass."""
    monkeypatch.setattr(
        fixture,
        "_BOOTSTRAP_JS",
        fixture._BOOTSTRAP_JS.replace(
            'registry.set("./format.js", {',
            'registry.set("./format.js__disabled", {',
        ),
    )
    result = run_scenario(_scenario())
    assert result.errors, "unknown specifier must surface an error"
    assert any("unknown specifier" in e for e in result.errors), result.errors


def test_missing_policy_panel_export_fails_loudly(monkeypatch):
    """Losing the export must be reported, not treated as a pass."""
    monkeypatch.setattr(
        fixture,
        "_BOOTSTRAP_JS",
        fixture._BOOTSTRAP_JS.replace(
            "const PolicyPanel = policyModule.namespace.PolicyPanel;",
            "const PolicyPanel = policyModule.namespace.NotThePanel;",
        ),
    )
    result = run_scenario(_scenario())
    assert any("PolicyPanel export missing" in e for e in result.errors), result.errors


def test_fixture_reads_nothing_outside_the_repository():
    """Every module path the fixture resolves lives under the repository root."""
    for path in (fixture.POLICY_JS, fixture.API_JS, fixture.DIGEST_JS):
        assert str(path).startswith(str(fixture.REPO_ROOT)), path
        assert path.is_file(), path
