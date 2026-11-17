# -*- coding: utf-8 -*-
"""顶栏企业会话状态单胶囊前端渲染与交互门禁测试。

基于真实 Node.js 运行时测试 ES Module 契约与前端交互逻辑：
1. 模块导出完整性：SessionBadges、SessionCapsule、useStore、GLOBAL_LOGIN_NOTICE、
   STATUS_TIERS、TIER_CONFIG、classifySystemTier、aggregateSessionStatus；
2. 三档映射逻辑：
   - connected → 「已连接 ✓」（绿 / ok）；
   - refreshing/expired/checking → 「正在恢复」（黄 / warn）；
   - login_required/signed_out/unknown → 「需要重新登录」（红 / bad）；
3. 两系统聚合规则：
   - 任一需要登录 → 红（bad，需要重新登录）；
   - 任一恢复中且无失败 → 黄（warn，正在恢复）；
   - 全部已连接 → 绿（ok，已连接 ✓）；
4. 红档点击触发登录弹窗回调，绿档/黄档禁用或不可触发；
5. UI Kit 状态色语义（ok / warn / bad）及 DOM 挂点结构；
6. 术语词表门禁：面向用户的文案无任何内部技术黑话或路径特征；
7. 凭据泄露防护：渲染节点与属性只读呈现状态，绝不回显任何敏感凭据。
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
HOST_STATIC = REPO_ROOT / "web" / "static" / "host"


def _node_major() -> int:
    node = shutil.which("node")
    if node is None:
        return 0
    out = subprocess.run([node, "--version"], capture_output=True, text=True, check=False).stdout
    match = re.match(r"v(\d+)", out.strip())
    return int(match.group(1)) if match else 0


pytestmark = pytest.mark.skipif(_node_major() < 22, reason="needs Node 22+ to import ES modules")

_NODE_TEST_SCRIPT = r"""
const base = process.argv[1];
const badgesModule = await import(base + "/chrome/SessionBadges.js");
const glossary = await import(base + "/glossary.js");
const session = await import(base + "/session.js");

const out = {};

// 1. 导出完整性检查
out.exports = {
  hasSessionBadges: typeof badgesModule.SessionBadges === "function",
  hasSessionCapsule: typeof badgesModule.SessionCapsule === "function",
  hasUseStore: typeof badgesModule.useStore === "function",
  hasGlobalNotice: typeof badgesModule.GLOBAL_LOGIN_NOTICE === "string",
  globalNotice: badgesModule.GLOBAL_LOGIN_NOTICE,
  hasStatusTiers: typeof badgesModule.STATUS_TIERS === "object" && badgesModule.STATUS_TIERS !== null,
  hasTierConfig: typeof badgesModule.TIER_CONFIG === "object" && badgesModule.TIER_CONFIG !== null,
  hasSystemClassifier: typeof badgesModule.classifySystemTier === "function",
  hasAggregator: typeof badgesModule.aggregateSessionStatus === "function",
};

// 2. 单系统三档分类归一化验证
const singleCases = {
  // 绿档 connected
  connString: badgesModule.classifySystemTier("connected"),
  connObj: badgesModule.classifySystemTier({ status: "connected" }),
  connAuth: badgesModule.classifySystemTier({ authenticated: true }),
  connAuthNotExp: badgesModule.classifySystemTier({ authenticated: true, expired: false }),

  // 黄档 recovering (refreshing / expired / checking)
  refString: badgesModule.classifySystemTier("refreshing"),
  refObj: badgesModule.classifySystemTier({ status: "refreshing" }),
  refFlag: badgesModule.classifySystemTier({ refreshing: true }),
  expString: badgesModule.classifySystemTier("expired"),
  expObj: badgesModule.classifySystemTier({ status: "expired" }),
  expFlag: badgesModule.classifySystemTier({ expired: true }),
  chkString: badgesModule.classifySystemTier("checking"),
  chkObj: badgesModule.classifySystemTier({ status: "checking" }),
  chkFlag: badgesModule.classifySystemTier({ checking: true }),

  // 红档 login_required (login_required / signed_out / unknown / null / {})
  reqString: badgesModule.classifySystemTier("login_required"),
  reqObj: badgesModule.classifySystemTier({ status: "login_required" }),
  signOutString: badgesModule.classifySystemTier("signed_out"),
  signOutObj: badgesModule.classifySystemTier({ status: "signed_out" }),
  unkString: badgesModule.classifySystemTier("unknown"),
  unkObj: badgesModule.classifySystemTier({ status: "unknown" }),
  emptyObj: badgesModule.classifySystemTier({}),
  nullVal: badgesModule.classifySystemTier(null),
  undefinedVal: badgesModule.classifySystemTier(undefined),
  authFalse: badgesModule.classifySystemTier({ authenticated: false }),
};
out.singleCases = singleCases;

// 3. 两系统聚合规则验证
const aggCases = {
  // 绿档：全部已连接 → 绿
  allConnectedStatus: badgesModule.aggregateSessionStatus({
    aras: { status: "connected" },
    tdc: { status: "connected" },
  }),
  allConnectedString: badgesModule.aggregateSessionStatus({
    aras: "connected",
    tdc: "connected",
  }),
  allConnectedAuth: badgesModule.aggregateSessionStatus({
    aras: { authenticated: true },
    tdc: { authenticated: true },
  }),

  // 黄档：任一恢复中且无失败 → 黄
  recoveringAras: badgesModule.aggregateSessionStatus({
    aras: { status: "refreshing" },
    tdc: { status: "connected" },
  }),
  expiredTdc: badgesModule.aggregateSessionStatus({
    aras: { status: "connected" },
    tdc: { status: "expired" },
  }),
  checkingAras: badgesModule.aggregateSessionStatus({
    aras: { status: "checking" },
    tdc: { status: "connected" },
  }),
  bothRecovering: badgesModule.aggregateSessionStatus({
    aras: { status: "refreshing" },
    tdc: { status: "checking" },
  }),
  recoveringWithAuth: badgesModule.aggregateSessionStatus({
    aras: { expired: true },
    tdc: { authenticated: true },
  }),

  // 红档：任一需要登录 → 红
  arasNeedsLogin: badgesModule.aggregateSessionStatus({
    aras: { status: "login_required" },
    tdc: { status: "connected" },
  }),
  tdcSignedOut: badgesModule.aggregateSessionStatus({
    aras: { status: "connected" },
    tdc: { status: "signed_out" },
  }),
  arasUnknown: badgesModule.aggregateSessionStatus({
    aras: { status: "unknown" },
    tdc: { status: "connected" },
  }),
  loginRequiredOverRecovering: badgesModule.aggregateSessionStatus({
    aras: { status: "login_required" },
    tdc: { status: "refreshing" },
  }),
  emptyObject: badgesModule.aggregateSessionStatus({}),
  nullSessions: badgesModule.aggregateSessionStatus(null),
  missingTdc: badgesModule.aggregateSessionStatus({
    aras: { status: "connected" },
  }),
};
out.aggCases = aggCases;

// 4. VNode 树递归序列化为 HTML
function vnodeToHtml(node) {
  if (node == null || typeof node === "boolean") return "";
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(vnodeToHtml).join("");
  if (typeof node.type === "function") {
    return vnodeToHtml(node.type(node.props || {}));
  }
  const tag = node.type;
  const props = node.props || {};
  let attrs = "";
  for (const [k, v] of Object.entries(props)) {
    if (k === "children" || k.startsWith("on") || v == null || v === false) continue;
    const name = k === "className" ? "class" : k;
    attrs += ` ${name}="${String(v)}"`;
  }
  const children = props.children ? vnodeToHtml(props.children) : "";
  return `<${tag}${attrs}>${children}</${tag}>`;
}

// 5. 渲染三档 HTML
const greenVNode = badgesModule.SessionBadges({
  sessions: { aras: "connected", tdc: "connected" },
});
const yellowVNode = badgesModule.SessionBadges({
  sessions: { aras: "connected", tdc: "refreshing" },
});
const redVNode = badgesModule.SessionBadges({
  sessions: { aras: "login_required", tdc: "connected" },
});

out.greenHtml = vnodeToHtml(greenVNode);
out.yellowHtml = vnodeToHtml(yellowVNode);
out.redHtml = vnodeToHtml(redVNode);

// 6. 点击红档触发登录弹窗回调验证
let customLoginCalled = false;
let customLoginNotice = "";
const clickableRedCapsule = badgesModule.SessionCapsule({
  sessions: { aras: "login_required", tdc: "connected" },
  onLogin: (opts) => {
    customLoginCalled = true;
    customLoginNotice = opts && opts.notice ? opts.notice : "";
  },
});
if (typeof clickableRedCapsule.props.onClick === "function") {
  clickableRedCapsule.props.onClick();
}

// 验证黄档/绿档不可点击（onClick 缺省为 null）
const nonClickableYellow = badgesModule.SessionCapsule({
  sessions: { aras: "refreshing", tdc: "connected" },
});
const nonClickableGreen = badgesModule.SessionCapsule({
  sessions: { aras: "connected", tdc: "connected" },
});

// 验证缺省 onLogin 注入时点击调用全局 openInPlaceLogin
session.closeInPlaceLogin();
const defaultStoreBefore = session.loginStore.get().open;
const defaultRedCapsule = badgesModule.SessionCapsule({
  sessions: { aras: "signed_out", tdc: "connected" },
});
if (typeof defaultRedCapsule.props.onClick === "function") {
  defaultRedCapsule.props.onClick();
}
const defaultStoreAfter = session.loginStore.get();
session.closeInPlaceLogin();

out.clickTests = {
  customLoginCalled,
  customLoginNotice,
  yellowHasOnClick: typeof nonClickableYellow.props.onClick === "function",
  greenHasOnClick: typeof nonClickableGreen.props.onClick === "function",
  yellowDisabled: Boolean(nonClickableYellow.props.disabled),
  greenDisabled: Boolean(nonClickableGreen.props.disabled),
  defaultStoreBefore,
  defaultStoreAfterOpen: defaultStoreAfter.open,
  defaultStoreNotice: defaultStoreAfter.notice,
};

// 7. 术语扫描
out.scans = {
  greenHtml: glossary.scanText(out.greenHtml),
  yellowHtml: glossary.scanText(out.yellowHtml),
  redHtml: glossary.scanText(out.redHtml),
  globalNotice: glossary.scanText(badgesModule.GLOBAL_LOGIN_NOTICE),
  greenTitle: glossary.scanText(badgesModule.TIER_CONFIG[badgesModule.STATUS_TIERS.CONNECTED].title),
  yellowTitle: glossary.scanText(badgesModule.TIER_CONFIG[badgesModule.STATUS_TIERS.RECOVERING].title),
  redTitle: glossary.scanText(badgesModule.TIER_CONFIG[badgesModule.STATUS_TIERS.LOGIN_REQUIRED].title),
};

// 8. 凭据暴露安全检查
const credentialPayload = {
  aras: { status: "connected", token: "synth-token-aras-999", password: "synth-secret-password-123" },
  tdc: { status: "connected", cookie: "synth_cookie=xyz", sid: "synth-sid-456" },
};
const credentialNode = badgesModule.SessionBadges({ sessions: credentialPayload });
out.credentialRenderedHtml = vnodeToHtml(credentialNode);

console.log(JSON.stringify(out));
"""


def _run_node_suite() -> dict:
    result = subprocess.run(
        ["node", "--input-type=module", "-e", _NODE_TEST_SCRIPT, HOST_STATIC.as_uri()],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert result.returncode == 0, f"Node 执行失败:\n{result.stderr}"
    lines = result.stdout.strip().splitlines()
    assert lines, "Node 执行未产生输出"
    return json.loads(lines[-1])


def test_session_badges_module_exports() -> None:
    """断言 SessionBadges.js 导出齐全且类型符合规范。"""
    data = _run_node_suite()
    exp = data["exports"]
    assert exp["hasSessionBadges"] is True
    assert exp["hasSessionCapsule"] is True
    assert exp["hasUseStore"] is True
    assert exp["hasGlobalNotice"] is True
    assert "企业域账号登录" in exp["globalNotice"]
    assert exp["hasStatusTiers"] is True
    assert exp["hasTierConfig"] is True
    assert exp["hasSystemClassifier"] is True
    assert exp["hasAggregator"] is True


def test_single_system_tier_classification() -> None:
    """断言单系统状态字符串及载荷对象的三档归一化逻辑准确无误。"""
    data = _run_node_suite()
    sc = data["singleCases"]

    # 绿档
    assert sc["connString"] == "connected"
    assert sc["connObj"] == "connected"
    assert sc["connAuth"] == "connected"
    assert sc["connAuthNotExp"] == "connected"

    # 黄档
    assert sc["refString"] == "recovering"
    assert sc["refObj"] == "recovering"
    assert sc["refFlag"] == "recovering"
    assert sc["expString"] == "recovering"
    assert sc["expObj"] == "recovering"
    assert sc["expFlag"] == "recovering"
    assert sc["chkString"] == "recovering"
    assert sc["chkObj"] == "recovering"
    assert sc["chkFlag"] == "recovering"

    # 红档
    assert sc["reqString"] == "login_required"
    assert sc["reqObj"] == "login_required"
    assert sc["signOutString"] == "login_required"
    assert sc["signOutObj"] == "login_required"
    assert sc["unkString"] == "login_required"
    assert sc["unkObj"] == "login_required"
    assert sc["emptyObj"] == "login_required"
    assert sc["nullVal"] == "login_required"
    assert sc["undefinedVal"] == "login_required"
    assert sc["authFalse"] == "login_required"


def test_two_system_aggregation_three_tiers() -> None:
    """断言两系统状态聚合规则：任一需要登录→红；任一恢复中且无失败→黄；全部已连接→绿。"""
    data = _run_node_suite()
    ag = data["aggCases"]

    # 全部已连接 → 绿（ok，已连接 ✓）
    for key in ("allConnectedStatus", "allConnectedString", "allConnectedAuth"):
        case = ag[key]
        assert case["tier"] == "connected"
        assert case["tone"] == "ok"
        assert case["text"] == "已连接 ✓"

    # 任一恢复中且无失败 → 黄（warn，正在恢复）
    for key in ("recoveringAras", "expiredTdc", "checkingAras", "bothRecovering", "recoveringWithAuth"):
        case = ag[key]
        assert case["tier"] == "recovering"
        assert case["tone"] == "warn"
        assert case["text"] == "正在恢复"

    # 任一需要登录 → 红（bad，需要重新登录）
    for key in (
        "arasNeedsLogin",
        "tdcSignedOut",
        "arasUnknown",
        "loginRequiredOverRecovering",
        "emptyObject",
        "nullSessions",
        "missingTdc",
    ):
        case = ag[key]
        assert case["tier"] == "login_required"
        assert case["tone"] == "bad"
        assert case["text"] == "需要重新登录"


def test_red_tier_click_triggers_login_dialog_callback() -> None:
    """断言点击红档触发登录弹窗回调，而绿档与黄档不可触发。"""
    data = _run_node_suite()
    clicks = data["clickTests"]

    # 自定义回调触发
    assert clicks["customLoginCalled"] is True
    assert "企业域账号登录" in clicks["customLoginNotice"]

    # 黄档与绿档 onClick 为 null 且处于 disabled 状态
    assert clicks["yellowHasOnClick"] is False
    assert clicks["greenHasOnClick"] is False
    assert clicks["yellowDisabled"] is True
    assert clicks["greenDisabled"] is True

    # 缺省 openInPlaceLogin 触发
    assert clicks["defaultStoreBefore"] is False
    assert clicks["defaultStoreAfterOpen"] is True
    assert "企业域账号登录" in clicks["defaultStoreNotice"]


def test_rendered_capsule_structure_and_u7_tones() -> None:
    """断言单胶囊结构、挂点容器类名以及 U7 状态色语义。"""
    data = _run_node_suite()

    # 绿档
    green = data["greenHtml"]
    assert 'class="hc-session-status"' in green
    assert "hc-session-capsule" in green
    assert "tone-ok" in green
    assert "is-ok" in green
    assert "已连接 ✓" in green

    # 黄档
    yellow = data["yellowHtml"]
    assert 'class="hc-session-status"' in yellow
    assert "hc-session-capsule" in yellow
    assert "tone-warn" in yellow
    assert "is-warn" in yellow
    assert "正在恢复" in yellow

    # 红档
    red = data["redHtml"]
    assert 'class="hc-session-status"' in red
    assert "hc-session-capsule" in red
    assert "tone-bad" in red
    assert "is-bad" in red
    assert "需要重新登录" in red
    assert 'id="hc-login-btn"' in red
    assert 'aria-haspopup="dialog"' in red


def test_session_status_texts_free_of_banned_terms() -> None:
    """断言会话状态用户可见文案与渲染结构中绝对不含禁用技术术语及代码路径。"""
    data = _run_node_suite()
    scans = data["scans"]

    assert scans["greenHtml"] == []
    assert scans["yellowHtml"] == []
    assert scans["redHtml"] == []
    assert scans["globalNotice"] == []
    assert scans["greenTitle"] == []
    assert scans["yellowTitle"] == []
    assert scans["redTitle"] == []


def test_no_credentials_exposed_in_rendered_status() -> None:
    """断言会话状态胶囊只读显示状态，绝对不输出或泄露上游载荷中的敏感凭据。"""
    data = _run_node_suite()
    html = data["credentialRenderedHtml"]

    for secret in (
        "synth-token-aras-999",
        "synth-secret-password-123",
        "synth_cookie=xyz",
        "synth-sid-456",
        "token",
        "password",
        "cookie",
    ):
        assert secret not in html.lower()
