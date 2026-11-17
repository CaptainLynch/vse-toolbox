# -*- coding: utf-8 -*-
"""严格 release 模式门禁（``tools/wave_gate.py``）的端到端行为测试。

覆盖四条验收标准：

1. dev 与 release 状态明确区分——同一组「有 SKIP」的输入，dev 判定通过、release 判定失败；
2. release 必需项 SKIP / 缺文件 / 未打包 / 未验签时退出码非 0；
3. 浏览器 verified 来自 pytest ``--junit-xml`` 实际报告，而不是「探测到浏览器可执行文件」；
4. ``--focus`` 不会隐式跳过 release 的全量回归。

所有 pytest 子进程都由 ``wave_gate.run_command`` 这一真实进程边界替身驱动；替身会像真 pytest
一样把 junit 报告写到 ``--junit-xml`` 指定路径，因此被测代码走的是「执行 → 解析报告 → 判定」
的真实调用链（``execute_wave_gate`` / ``main``），不是孤立 helper。另有单独用例真的跑一次
pytest，用来校准报告解析器与真 pytest 输出一致。
"""

from __future__ import annotations

import base64
import importlib.util
import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
WAVE_GATE_PATH = REPO_ROOT / "tools" / "wave_gate.py"


def _load_wave_gate():  # type: ignore[no-untyped-def]
    """按文件路径加载被测模块（``tools/`` 不是包，避免污染 sys.path 导入名）。"""
    spec = importlib.util.spec_from_file_location("wave_gate_under_test", WAVE_GATE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # dataclass 装饰器需要模块已登记在 sys.modules 才能解析类型注解。
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(spec.name, None)
        raise
    return module


wave_gate = _load_wave_gate()


# ── 夹具：像真 pytest 一样产出 junit 报告的子进程替身 ──────────────────


def write_junit(
    path: Path,
    *,
    passed: int = 0,
    failed: int = 0,
    skipped: int = 0,
    errors: int = 0,
) -> None:
    """按 pytest junit 报告的真实结构写出一个报告文件。"""
    total = passed + failed + skipped + errors
    cases: list[str] = []
    for index in range(passed):
        cases.append(
            f'<testcase classname="tests.browser.test_browser_channel" '
            f'name="test_headless_smoke_{index}" time="0.2" />'
        )
    for index in range(failed):
        cases.append(
            f'<testcase classname="tests.browser.test_browser_channel" '
            f'name="test_headless_smoke_fail_{index}" time="0.2">'
            f'<failure message="AssertionError: boom">trace</failure></testcase>'
        )
    for index in range(errors):
        cases.append(
            f'<testcase classname="tests.browser.test_browser_channel" '
            f'name="test_headless_smoke_error_{index}" time="0.2">'
            f'<error message="RuntimeError: boom">trace</error></testcase>'
        )
    for index in range(skipped):
        cases.append(
            f'<testcase classname="tests.browser.test_browser_channel" '
            f'name="test_headless_smoke_skip_{index}" time="0.0">'
            f'<skipped message="未探测到浏览器通道" /></testcase>'
        )
    xml = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        f'<testsuites><testsuite name="pytest" errors="{errors}" failures="{failed}" '
        f'skipped="{skipped}" tests="{total}" time="0.4">\n'
        + "\n".join(cases)
        + "\n</testsuite></testsuites>\n"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(xml, encoding="utf-8")


class FakePytest:
    """``run_command`` 替身：按命令识别门禁步骤，并写真实结构的 junit 报告。"""

    def __init__(
        self,
        *,
        browser: dict[str, int] | None = None,
        write_report: bool = True,
        full_ok: bool = True,
        map_ok: bool = True,
        terms_ok: bool = True,
    ) -> None:
        self.browser = {"passed": 1} if browser is None else dict(browser)
        self.write_report = write_report
        self.full_ok = full_ok
        self.map_ok = map_ok
        self.terms_ok = terms_ok
        self.calls: list[list[str]] = []

    def __call__(self, cmd: list[str], cwd: Path):  # type: ignore[no-untyped-def]
        command = [str(part) for part in cmd]
        self.calls.append(command)
        joined = " ".join(command)

        if "test_browser_channel.py" in joined:
            if self.write_report:
                report_path = Path(command[command.index("--junit-xml") + 1])
                write_junit(report_path, **self.browser)
            broken = bool(self.browser.get("failed") or self.browser.get("errors"))
            code = 1 if broken else 0
            return code, "browser channel run", ([] if code == 0 else ["browser boom"])

        if "generate_project_map.py" in joined:
            return (0 if self.map_ok else 1), "map", ([] if self.map_ok else ["map drift"])

        if "test_glossary_terms.py" in joined or "test_ui_kit_terms.py" in joined:
            return (0 if self.terms_ok else 1), "terms", ([] if self.terms_ok else ["term boom"])

        if "tests" in command:  # 全量回归命令形如 [python, -m, pytest, tests, -q]
            return (0 if self.full_ok else 1), "full", ([] if self.full_ok else ["full boom"])

        return 0, "focus", []

    def ran_full_regression(self) -> bool:
        return any("tests" in command for command in self.calls)


@pytest.fixture()
def fake_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """把门禁的 REPO_ROOT 指向临时仓库，并造出各步骤依赖的必需文件。"""
    root = tmp_path / "repo"
    (root / "tests" / "browser").mkdir(parents=True)
    (root / "host").mkdir()
    for relative in (
        "tests/browser/test_browser_channel.py",
        "tests/test_glossary_terms.py",
        "tests/test_ui_kit_terms.py",
    ):
        (root / relative).write_text("# 占位文件：真实执行由 run_command 替身驱动\n", encoding="utf-8")
    monkeypatch.setattr(wave_gate, "REPO_ROOT", root)
    return root


def run_gate(
    monkeypatch: pytest.MonkeyPatch,
    runner: FakePytest,
    *,
    mode: str = "dev",
    focus: list[str] | None = None,
    skip_full: bool = False,
    out_file: Path | None = None,
) -> int:
    """驱动被测门禁（真实调用链：execute_wave_gate → 步骤 → 报告解析 → 判定）。"""
    monkeypatch.setattr(wave_gate, "run_command", runner)
    return wave_gate.execute_wave_gate(
        focus_targets=list(focus or []),
        skip_full=skip_full,
        out_file=str(out_file) if out_file is not None else None,
        mode=mode,
    )


def read_report(path: Path) -> dict:  # type: ignore[type-arg]
    return json.loads(path.read_text(encoding="utf-8"))


def step_by_name(report: dict, name: str) -> dict:  # type: ignore[type-arg]
    return next(step for step in report["steps"] if step["name"] == name)


# ── 合成签名包（不接触真实私钥/真实 dist） ────────────────────────────


def _ed25519():
    cryptography = pytest.importorskip("cryptography")  # noqa: F841 - 缺库时跳过
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    return Ed25519PrivateKey


def build_signed_package(repo_root: Path, *, version: str = "2.0.1"):  # type: ignore[no-untyped-def]
    """用合成 Ed25519 私钥在临时仓库 ``dist/releases`` 造一个真签名包。"""
    Ed25519PrivateKey = _ed25519()
    from cryptography.hazmat.primitives import serialization

    from vse_boot.packages import TARGET_RUNTIME_TAG, build_app_package

    private = Ed25519PrivateKey.generate()
    pem = private.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    name, data = build_app_package(
        {"webui.py": b"def main(argv=None):\n    return 0\n", "core/__init__.py": b""},
        version=version,
        private_key_pem=pem,
        notes="合成测试包",
        runtime_tag=TARGET_RUNTIME_TAG,
    )
    out_dir = repo_root / "dist" / "releases"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / name).write_bytes(data)
    return name, private


def write_trusted_keys(repo_root: Path, private) -> None:  # type: ignore[no-untyped-def]
    """把合成公钥写进临时仓库的 ``host/trusted_keys.json``。"""
    from cryptography.hazmat.primitives import serialization

    from vse_boot.packages import key_id_for

    public = private.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    payload = {
        "keys": [
            {
                "keyId": key_id_for(public),
                "publicKey": base64.b64encode(public).decode("ascii"),
            }
        ]
    }
    (repo_root / "host" / "trusted_keys.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )


# ── 报告解析器校准：真跑一次 pytest ───────────────────────────────────


def test_parse_junit_report_matches_real_pytest(tmp_path: Path) -> None:
    """解析器必须与真 pytest 的 junit 报告一致（2 通过 / 1 跳过）。"""
    sample = tmp_path / "test_sample_report.py"
    sample.write_text(
        textwrap.dedent(
            """
            import pytest


            def test_ok_one():
                assert True


            def test_ok_two():
                assert 1 + 1 == 2


            def test_skipped():
                pytest.skip("通道不可用")
            """
        ),
        encoding="utf-8",
    )
    report_path = tmp_path / "report.xml"
    proc = subprocess.run(
        [
            sys.executable,
            "-B",
            "-m",
            "pytest",
            "-p",
            "no:cacheprovider",
            "--junit-xml",
            str(report_path),
            str(sample),
            "-q",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert report_path.is_file(), "pytest 未写出 junit 报告"

    parsed = wave_gate.parse_junit_report(report_path)
    assert parsed is not None
    assert (parsed.passed, parsed.failed, parsed.errors, parsed.skipped) == (2, 0, 0, 1)
    assert parsed.executed == 2
    assert parsed.total == 3


def test_parse_junit_report_missing_file_returns_none(tmp_path: Path) -> None:
    """没有报告文件 = 没有验证证据（返回 None，绝不默认通过）。"""
    assert wave_gate.parse_junit_report(tmp_path / "not-there.xml") is None


# ── 验收 1：dev 与 release 状态明确区分 ───────────────────────────────


def test_dev_passes_where_release_fails_on_same_skips(
    fake_repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """同一组输入（浏览器跳过 + 未打包）：dev 通过，release 退出非 0。"""
    runner = FakePytest(browser={"passed": 0, "skipped": 1})
    dev_out = tmp_path / "dev.json"
    release_out = tmp_path / "release.json"

    dev_code = run_gate(monkeypatch, runner, mode="dev", out_file=dev_out)
    release_code = run_gate(monkeypatch, runner, mode="release", out_file=release_out)

    assert dev_code == 0
    assert release_code != 0

    dev_report = read_report(dev_out)
    release_report = read_report(release_out)
    assert dev_report["mode"] == "dev"
    assert release_report["mode"] == "release"
    assert dev_report["gate_status"] == "PASS"
    assert release_report["gate_status"] == "FAIL"

    # dev 如实记录 SKIP 原因，不伪装成通过
    dev_package = step_by_name(dev_report, "package_sign")
    assert dev_package["status"] == "SKIP" and dev_package["details"]
    assert dev_report["browser_channel"]["verified"] is False
    assert dev_report["required_steps"] == []

    # release 把这两个 SKIP 视为必需项失败
    assert "package_sign" in release_report["required_steps"]
    assert "browser_channel" in release_report["required_steps"]
    reasons = "\n".join(release_report["gate_reasons"])
    assert "打包验签" in reasons and "浏览器通道" in reasons
    assert any("必需项" in reason and "SKIP" in reason for reason in release_report["gate_reasons"])


def test_dev_requires_skip_reason(fake_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """dev 模式仍要求 SKIP 说明原因（无原因的空 SKIP 视为缺陷）。"""
    monkeypatch.setattr(wave_gate, "run_command", FakePytest())
    steps = [
        wave_gate.StepResult(name="focus_tests", display_name="聚焦测试", status="SKIP", details=""),
    ]
    passed, reasons = wave_gate.evaluate_gate(steps, wave_gate.MODE_DEV)
    assert passed is False
    assert any("未说明原因" in reason for reason in reasons)


# ── 验收 2：release 必需项 SKIP / 缺文件 / 未打包 / 未验签 → 非 0 ──────


def test_release_fails_when_term_test_files_missing(
    fake_repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """缺术语门禁测试文件（缺文件）→ release 非 0。"""
    (fake_repo / "tests" / "test_glossary_terms.py").unlink()
    (fake_repo / "tests" / "test_ui_kit_terms.py").unlink()
    out = tmp_path / "report.json"

    code = run_gate(monkeypatch, FakePytest(), mode="release", out_file=out)

    assert code != 0
    report = read_report(out)
    terms = step_by_name(report, "glossary_terms")
    assert terms["status"] == "SKIP" and "不存在" in terms["details"]
    assert any("术语门禁" in reason for reason in report["gate_reasons"])


def test_release_fails_when_one_term_test_file_missing(
    fake_repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """只缺一个术语门禁测试文件也算缺文件 → release 非 0；dev 下照常运行存在的那个。"""
    (fake_repo / "tests" / "test_ui_kit_terms.py").unlink()
    out = tmp_path / "report.json"

    code = run_gate(monkeypatch, FakePytest(), mode="release", out_file=out)

    assert code != 0
    report = read_report(out)
    terms = step_by_name(report, "glossary_terms")
    assert terms["status"] == "FAIL" and "test_ui_kit_terms.py" in terms["details"]
    assert any("术语门禁" in reason for reason in report["gate_reasons"])

    dev_out = tmp_path / "dev.json"
    run_gate(monkeypatch, FakePytest(), mode="dev", out_file=dev_out)
    assert step_by_name(read_report(dev_out), "glossary_terms")["status"] == "PASS"


def test_release_fails_when_browser_test_file_missing(
    fake_repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """缺浏览器通道测试文件（缺文件）→ 没有验证证据 → release 非 0。"""
    _name, private = build_signed_package(fake_repo)
    write_trusted_keys(fake_repo, private)
    (fake_repo / "tests" / "browser" / "test_browser_channel.py").unlink()
    out = tmp_path / "report.json"

    code = run_gate(monkeypatch, FakePytest(), mode="release", out_file=out)

    assert code != 0
    report = read_report(out)
    browser_step = step_by_name(report, "browser_channel")
    assert browser_step["status"] == "SKIP" and "不存在" in browser_step["details"]
    assert report["browser_channel"]["verified"] is False
    assert any("浏览器通道" in reason for reason in report["gate_reasons"])


def test_release_fails_when_not_packaged(
    fake_repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """没有 dist/releases/*.vsepkg（未打包）→ release 非 0。"""
    out = tmp_path / "report.json"
    code = run_gate(monkeypatch, FakePytest(), mode="release", out_file=out)

    assert code != 0
    report = read_report(out)
    package = step_by_name(report, "package_sign")
    assert package["status"] == "FAIL"
    assert "未打包" in package["details"]
    assert any("未打包" in reason or "打包验签" in reason for reason in report["gate_reasons"])


def test_release_fails_when_trusted_keys_missing(
    fake_repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """有包但仓库没有可信公钥 → 无法验签 → release 非 0。"""
    build_signed_package(fake_repo)
    out = tmp_path / "report.json"

    code = run_gate(monkeypatch, FakePytest(), mode="release", out_file=out)

    assert code != 0
    package = step_by_name(read_report(out), "package_sign")
    assert package["status"] == "FAIL"
    assert "未验签" in package["details"]


def test_release_fails_when_signature_key_untrusted(
    fake_repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """包由 A 签名、仓库只信任 B（未验签）→ release 非 0。"""
    Ed25519PrivateKey = _ed25519()
    build_signed_package(fake_repo)
    write_trusted_keys(fake_repo, Ed25519PrivateKey.generate())
    out = tmp_path / "report.json"

    code = run_gate(monkeypatch, FakePytest(), mode="release", out_file=out)

    assert code != 0
    package = step_by_name(read_report(out), "package_sign")
    assert package["status"] == "FAIL"
    assert "未验签" in package["details"]


def test_release_fails_when_package_tampered(
    fake_repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """包内容被改动（签名不再匹配）→ release 非 0。"""
    import io
    import zipfile

    name, private = build_signed_package(fake_repo)
    write_trusted_keys(fake_repo, private)

    package_path = fake_repo / "dist" / "releases" / name
    entries: dict[str, bytes] = {}
    with zipfile.ZipFile(io.BytesIO(package_path.read_bytes())) as archive:
        for info in archive.infolist():
            entries[info.filename] = archive.read(info.filename)
    entries["files/webui.py"] = b"def main(argv=None):\n    return 1  # tampered\n"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for entry_name, content in entries.items():
            archive.writestr(entry_name, content)
    package_path.write_bytes(buffer.getvalue())

    out = tmp_path / "report.json"
    code = run_gate(monkeypatch, FakePytest(), mode="release", out_file=out)

    assert code != 0
    package = step_by_name(read_report(out), "package_sign")
    assert package["status"] == "FAIL"
    assert "未验签" in package["details"]


def test_release_passes_with_verified_package(
    fake_repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """全部必需项齐备（含真验签通过）→ release 退出 0，且报告写明验签证据。"""
    name, private = build_signed_package(fake_repo)
    write_trusted_keys(fake_repo, private)
    out = tmp_path / "report.json"

    code = run_gate(monkeypatch, FakePytest(), mode="release", out_file=out)

    assert code == 0
    report = read_report(out)
    assert report["gate_status"] == "PASS" and report["passed"] is True
    package = step_by_name(report, "package_sign")
    assert package["status"] == "PASS" and package["required"] is True
    assert name in package["details"] and "已验签" in package["details"]
    assert report["browser_channel"]["verified"] is True
    assert report["browser_channel"]["report"]["passed"] == 1
    assert sorted(report["required_steps"]) == [
        "browser_channel",
        "full_regression",
        "glossary_terms",
        "package_sign",
        "project_map",
    ]


# ── 验收 3：浏览器 verified 来自实际报告 ──────────────────────────────


def test_verified_false_when_channel_found_but_report_skipped(
    fake_repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """探测到浏览器可执行文件、但报告显示用例被跳过 → 不得判 verified。"""
    _name, private = build_signed_package(fake_repo)
    write_trusted_keys(fake_repo, private)
    monkeypatch.setattr(
        wave_gate,
        "detect_browser_channel",
        lambda: wave_gate.ChannelInfo(
            name="Microsoft Edge", path=r"C:\fake\msedge.exe", available=True, reason="探测到"
        ),
    )
    out = tmp_path / "report.json"

    code = run_gate(
        monkeypatch,
        FakePytest(browser={"passed": 0, "skipped": 1}),
        mode="release",
        out_file=out,
    )

    assert code != 0
    report = read_report(out)
    browser = report["browser_channel"]
    assert browser["channel_name"] == "Microsoft Edge"  # 探测结果只用于展示
    assert browser["verified"] is False
    assert browser["status"] != "verified"
    assert browser["report"] == {
        "total": 1,
        "passed": 0,
        "failed": 0,
        "errors": 0,
        "skipped": 1,
    }
    assert any("浏览器通道" in reason for reason in report["gate_reasons"])


def test_verified_true_from_report_even_without_executable(
    fake_repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """即使探测不到可执行文件，报告里有通过用例就判 verified（证据优先）。"""
    _name, private = build_signed_package(fake_repo)
    write_trusted_keys(fake_repo, private)
    monkeypatch.setattr(
        wave_gate,
        "detect_browser_channel",
        lambda: wave_gate.ChannelInfo(reason="未探测到浏览器通道"),
    )
    out = tmp_path / "report.json"

    code = run_gate(monkeypatch, FakePytest(browser={"passed": 1}), mode="release", out_file=out)

    assert code == 0
    browser = read_report(out)["browser_channel"]
    assert browser["verified"] is True
    assert browser["status"] == "verified"
    assert browser["report"]["passed"] == 1


def test_missing_report_is_not_verified(
    fake_repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """pytest 退出 0 但没写报告 → 无验证证据，步骤 FAIL 且 verified 为 False。"""
    out = tmp_path / "report.json"

    code = run_gate(
        monkeypatch, FakePytest(write_report=False), mode="dev", out_file=out
    )

    assert code != 0
    report = read_report(out)
    browser_step = step_by_name(report, "browser_channel")
    assert browser_step["status"] == "FAIL"
    assert "未取得 pytest 报告" in browser_step["details"]
    assert report["browser_channel"]["verified"] is False


def test_failed_browser_report_marks_step_failed(
    fake_repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """报告里有失败用例 → 步骤 FAIL，verified False。"""
    out = tmp_path / "report.json"

    code = run_gate(
        monkeypatch, FakePytest(browser={"passed": 0, "failed": 1}), mode="dev", out_file=out
    )

    assert code != 0
    report = read_report(out)
    assert step_by_name(report, "browser_channel")["status"] == "FAIL"
    assert report["browser_channel"]["status"] == "failed"
    assert report["browser_channel"]["verified"] is False


# ── 验收 4：--focus 不得隐式跳过 release 全量回归 ─────────────────────


def test_resolve_skip_full_mode_semantics() -> None:
    """dev 保留既有隐含语义；release 只认显式 --skip-full。"""
    assert wave_gate.resolve_skip_full("dev", False, ["tests/test_x.py"]) is True
    assert wave_gate.resolve_skip_full("dev", True, []) is True
    assert wave_gate.resolve_skip_full("release", False, ["tests/test_x.py"]) is False
    assert wave_gate.resolve_skip_full("release", True, ["tests/test_x.py"]) is True


def test_main_does_not_let_focus_skip_release_full_regression(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CLI 接线：release + --focus 传给 execute_wave_gate 的 skip_full 必须是 False。"""
    captured: dict[str, object] = {}

    def fake_execute(focus_targets, skip_full, out_file=None, mode="dev"):  # type: ignore[no-untyped-def]
        captured.update(
            focus_targets=list(focus_targets),
            skip_full=skip_full,
            out_file=out_file,
            mode=mode,
        )
        return 0

    monkeypatch.setattr(wave_gate, "execute_wave_gate", fake_execute)

    with pytest.raises(SystemExit) as release_exit:
        wave_gate.main(["--mode", "release", "--focus", "tests/test_x.py"])
    assert release_exit.value.code == 0
    assert captured["mode"] == "release"
    assert captured["skip_full"] is False
    assert captured["focus_targets"] == ["tests/test_x.py"]

    captured.clear()
    with pytest.raises(SystemExit) as dev_exit:
        wave_gate.main(["--focus", "tests/test_x.py"])
    assert dev_exit.value.code == 0
    assert captured["mode"] == "dev"
    assert captured["skip_full"] is True

    captured.clear()
    with pytest.raises(SystemExit):
        wave_gate.main(["--release", "--focus", "tests/test_x.py"])
    assert captured["mode"] == "release"  # --release 是 --mode release 的等价简写
    assert captured["skip_full"] is False


def test_release_with_focus_still_runs_full_regression(
    fake_repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """真实调用链：release + --focus 时全量回归命令仍被执行。"""
    _name, private = build_signed_package(fake_repo)
    write_trusted_keys(fake_repo, private)
    runner = FakePytest()
    monkeypatch.setattr(wave_gate, "run_command", runner)
    out = tmp_path / "report.json"

    with pytest.raises(SystemExit) as excinfo:
        wave_gate.main(
            ["--mode", "release", "--focus", "tests/test_glossary_terms.py", "--out", str(out)]
        )

    assert excinfo.value.code == 0
    assert runner.ran_full_regression() is True
    report = read_report(out)
    assert step_by_name(report, "full_regression")["status"] == "PASS"
    assert step_by_name(report, "focus_tests")["status"] == "PASS"


def test_release_explicit_skip_full_fails(
    fake_repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """显式 --skip-full 让必需项 SKIP → release 非 0，且全量回归确实没跑。"""
    _name, private = build_signed_package(fake_repo)
    write_trusted_keys(fake_repo, private)
    runner = FakePytest()
    out = tmp_path / "report.json"

    code = run_gate(
        monkeypatch, runner, mode="release", skip_full=True, out_file=out
    )

    assert code != 0
    assert runner.ran_full_regression() is False
    report = read_report(out)
    full = step_by_name(report, "full_regression")
    assert full["status"] == "SKIP" and full["required"] is True
    assert any("全量回归" in reason and "必需项" in reason for reason in report["gate_reasons"])


def test_release_fails_when_focus_test_fails(
    fake_repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """release 模式下聚焦测试失败同样整体非 0（其余必需项都通过也不放行）。"""
    _name, private = build_signed_package(fake_repo)
    write_trusted_keys(fake_repo, private)
    base = FakePytest()
    out = tmp_path / "report.json"

    def runner(cmd, cwd):  # type: ignore[no-untyped-def]
        command = [str(part) for part in cmd]
        # 聚焦测试命令形如 [python, -m, pytest, <单个目标>, -q]（共 5 段）
        if len(command) == 5 and command[3] == "tests/test_glossary_terms.py":
            base.calls.append(command)
            return 1, "focus boom", ["focus boom"]
        return base(cmd, cwd)

    code = run_gate(
        monkeypatch,
        runner,  # type: ignore[arg-type]
        mode="release",
        focus=["tests/test_glossary_terms.py"],
        out_file=out,
    )

    assert code != 0
    report = read_report(out)
    assert step_by_name(report, "focus_tests")["status"] == "FAIL"
    assert step_by_name(report, "package_sign")["status"] == "PASS"
    assert any("聚焦测试" in reason for reason in report["gate_reasons"])


def test_dev_still_skips_full_with_focus(
    fake_repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """dev 轻量语义保持不变：--focus 仍隐含跳过全量回归。"""
    runner = FakePytest()
    out = tmp_path / "report.json"

    with pytest.raises(SystemExit) as excinfo:
        monkeypatch.setattr(wave_gate, "run_command", runner)
        wave_gate.main(["--focus", "tests/test_glossary_terms.py", "--out", str(out)])

    assert excinfo.value.code == 0
    assert runner.ran_full_regression() is False
    assert step_by_name(read_report(out), "full_regression")["status"] == "SKIP"
