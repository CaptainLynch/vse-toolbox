# -*- coding: utf-8 -*-
"""正式发布门禁（``tools/wave_gate.py``）的包验签与整包一致性测试。

全部在 ``tmp_path`` 内执行，**不接触仓库或 dist 里任何既有私钥**：

* 每个用例现场生成临时 Ed25519 私钥，用 ``vse_boot.packages.build_app_package`` /
  ``key_id_for`` 造包，并把对应公钥写进临时仓库的 ``host/trusted_keys.json``；
* 提交一致性用临时 git 仓库（``git init`` + 合成文件 + 本地 user.name/user.email），
  不碰工作区仓库的索引与 HEAD。

覆盖：
1. 正向：签名正确 + 版本一致 + 内容与 HEAD 一致 + 无启动器改动 → PASS；
2. 负向：篡改包内文件 / 篡改清单 / 错误运行时 / 缺入口 / 版本不一致 /
   包内容与 HEAD 不一致 / 未提交改动 / vse_boot 改动但无 onedir zip / 缺 --since；
3. 启动失败与试用回退：``vse_boot.state`` 的 stage → 试用 → 回滚不覆盖业务数据；
4. 已生效版本手动回退：``rollback()`` 同样不覆盖新业务数据。
"""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import zipfile

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
WAVE_GATE_PATH = REPO_ROOT / "tools" / "wave_gate.py"
TEST_VERSION = "9.9.1"
BASELINE = "HEAD~1"


def _load_wave_gate():  # type: ignore[no-untyped-def]
    """按文件路径加载被测模块（``tools/`` 不是包，避免污染 sys.path 导入名）。"""
    spec = importlib.util.spec_from_file_location(
        "wave_gate_release_package", WAVE_GATE_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(spec.name, None)
        raise
    return module


wave_gate = _load_wave_gate()

#: 合成 app 包内容：与临时仓库 HEAD 提交的文件逐字节一致。
BASE_FILES: dict[str, bytes] = {
    "webui.py": b"def main(argv=None):\n    return 0\n",
    "core/version.py": b"APP_VERSION = '9.9.1'\n",
    "plugins/demo/backend.py": b"def register(host):\n    return None\n",
}


# ── 临时信任链（每个用例现场生成，绝不读取既有私钥） ──────────────────


def _private_key_pem() -> bytes:
    pytest.importorskip("cryptography")
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    private = Ed25519PrivateKey.generate()
    return private.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )


def _public_key(pem: bytes) -> bytes:
    from cryptography.hazmat.primitives import serialization

    private = serialization.load_pem_private_key(pem, password=None)
    return private.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )


def _write_trusted_keys(repo_root: Path, pem: bytes) -> None:
    """把临时公钥写进临时仓库的 ``host/trusted_keys.json``（模拟发布信任链）。"""
    from vse_boot.packages import key_id_for

    public = _public_key(pem)
    payload = {
        "keys": [
            {
                "keyId": key_id_for(public),
                "publicKey": base64.b64encode(public).decode("ascii"),
            }
        ]
    }
    (repo_root / "host").mkdir(parents=True, exist_ok=True)
    (repo_root / "host" / "trusted_keys.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )


def _build_package(
    repo_root: Path,
    *,
    version: str = TEST_VERSION,
    files: dict[str, bytes] | None = None,
    runtime_tag: str | None = None,
    trusted: bool = True,
) -> Path:
    """用临时私钥在临时仓库 ``dist/releases`` 造一个真签名包。"""
    from vse_boot.packages import TARGET_RUNTIME_TAG, build_app_package

    pem = _private_key_pem()
    if trusted:
        _write_trusted_keys(repo_root, pem)
    name, data = build_app_package(
        dict(BASE_FILES if files is None else files),
        version=version,
        private_key_pem=pem,
        notes="合成测试包",
        runtime_tag=TARGET_RUNTIME_TAG if runtime_tag is None else runtime_tag,
    )
    out_dir = repo_root / "dist" / "releases"
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / name
    target.write_bytes(data)
    return target


def _build_package_with_manifest(
    repo_root: Path, *, manifest_files: dict[str, bytes], version: str = TEST_VERSION
) -> Path:
    """绕过 ``build_app_package`` 的入口检查，手写清单并签名（用于缺入口负向用例）。"""
    from vse_boot.packages import PACKAGE_FORMAT, TARGET_RUNTIME_TAG, sign_manifest

    pem = _private_key_pem()
    _write_trusted_keys(repo_root, pem)
    manifest = {
        "format": PACKAGE_FORMAT,
        "kind": "app",
        "id": "app",
        "version": version,
        "requires": {"runtime": TARGET_RUNTIME_TAG},
        "notes": "缺入口的合成包",
        "migrations": [],
        "files": {
            name: hashlib.sha256(content).hexdigest()
            for name, content in sorted(manifest_files.items())
        },
    }
    manifest_bytes = json.dumps(
        manifest, ensure_ascii=False, indent=2, sort_keys=True
    ).encode("utf-8")
    signature = sign_manifest(manifest_bytes, pem)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("package.json", manifest_bytes)
        archive.writestr("package.sig", json.dumps(signature).encode("utf-8"))
        for name, content in sorted(manifest_files.items()):
            archive.writestr(f"files/{name}", content)
    out_dir = repo_root / "dist" / "releases"
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"vse-app-{version}.vsepkg"
    target.write_bytes(buffer.getvalue())
    return target


def _rewrite_package(path: Path, updates: dict[str, bytes]) -> None:
    """按条目重写包（保留其余字节），用于篡改负向用例。"""
    entries: dict[str, bytes] = {}
    with zipfile.ZipFile(path) as archive:
        for info in archive.infolist():
            entries[info.filename] = archive.read(info.filename)
    entries.update(updates)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    path.write_bytes(buffer.getvalue())


# ── 临时 git 仓库 ────────────────────────────────────────────────────


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    proc = subprocess.run(
        ["git", *args], cwd=str(repo), capture_output=True, check=False
    )
    assert proc.returncode == 0, (
        f"git {' '.join(args)} 失败: {proc.stderr.decode('utf-8', 'replace')}"
    )
    return proc


def _init_repo(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "-q")
    _git(root, "config", "user.name", "Gate Tester")
    _git(root, "config", "user.email", "gate@example.invalid")
    # 与构建机口径一致：包内文件按字节与 HEAD 比较，不做换行转换。
    _git(root, "config", "core.autocrlf", "false")
    _git(root, "config", "commit.gpgsign", "false")
    return root


def _write_files(root: Path, files: dict[str, bytes]) -> None:
    for relative, content in files.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)


def _commit_all(repo: Path, message: str) -> str:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD").stdout.decode("utf-8").strip()


@pytest.fixture(autouse=True)
def _version_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """版本口径走构建注入路径（真实调用 ``core.version.get_app_version_info``）。"""
    monkeypatch.delenv("VSE_DATA_ROOT", raising=False)
    monkeypatch.setenv("VSE_TOOLBOX_VERSION", TEST_VERSION)


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    """临时 git 仓库：基线提交 + 一次 app 文件提交（``HEAD~1`` 可用）。"""
    root = _init_repo(tmp_path / "repo")
    (root / "README.md").write_text("baseline\n", encoding="utf-8")
    _commit_all(root, "baseline")
    _write_files(root, BASE_FILES)
    _commit_all(root, "app files")
    return root


def _run_step(repo_root: Path, *, since: str | None = BASELINE, mode: str = "release"):  # type: ignore[no-untyped-def]
    """真实调用链：``execute_package_sign_step`` → 验签 → 整包一致性。"""
    return wave_gate.execute_package_sign_step(repo_root, mode, since=since)


# ── 正向：签名正确 + 版本一致 + 内容与 HEAD 一致 + 无启动器改动 ────────


def test_release_package_passes_when_signed_and_consistent(repo: Path) -> None:
    target = _build_package(repo)

    step = _run_step(repo)

    assert step.status == "PASS", step.details
    assert step.name == "package_sign"
    assert target.name in step.details
    assert "已验签" in step.details
    assert "与 HEAD 内容一致" in step.details
    assert "无启动器改动" in step.details


def test_untracked_generated_file_is_only_counted(repo: Path) -> None:
    """包内未被 git 跟踪的生成文件只计数提示，不判 FAIL。"""
    files = dict(BASE_FILES)
    files["core/generated_tables.py"] = b"TABLES = {}\n"
    _write_files(repo, {"core/generated_tables.py": files["core/generated_tables.py"]})
    _build_package(repo, files=files)

    step = _run_step(repo)

    assert step.status == "PASS", step.details
    assert "1 个生成文件未被 git 跟踪" in step.details


def test_non_git_directory_keeps_signature_only_semantics(tmp_path: Path) -> None:
    """非 git 目录无法做提交一致性校验：退回仅验签 + 入口，并如实写明跳过原因。"""
    plain = tmp_path / "plain"
    plain.mkdir()
    _build_package(plain)

    step = _run_step(plain)

    assert step.status == "PASS", step.details
    assert "非 git 工作树" in step.details


def test_crlf_checkout_normalization_is_counted_not_failed(tmp_path: Path) -> None:
    """``core.autocrlf=true``：HEAD 存 LF、工作区是 CRLF 时按检出内容比对，只计数不 FAIL。"""
    root = _init_repo(tmp_path / "crlf-repo")
    _git(root, "config", "core.autocrlf", "true")
    (root / "README.md").write_text("baseline\n", encoding="utf-8")
    _commit_all(root, "baseline")
    crlf_files = {
        "webui.py": b"def main(argv=None):\r\n    return 0\r\n",
        "core/version.py": b"APP_VERSION = '9.9.1'\r\n",
    }
    _write_files(root, crlf_files)
    _commit_all(root, "app files with CRLF worktree")
    _build_package(root, files=crlf_files)

    # HEAD 里是 LF 字节，工作区是 CRLF：只有检出规范化这一条路径能让它通过。
    assert b"\r\n" not in _git(root, "show", "HEAD:webui.py").stdout

    step = _run_step(root)

    assert step.status == "PASS", step.details
    assert "2 个文件按 git 检出换行规范化后一致" in step.details


def test_release_package_passes_when_launcher_change_has_onedir_zip(repo: Path) -> None:
    """启动器改动 + 同版本 onedir 宿主包齐备 → 允许只发（并发的）app 包。"""
    _write_files(repo, {"vse_boot/layout.py": b"# launcher change\n"})
    _commit_all(repo, "launcher change")
    _build_package(repo)
    zip_path = repo / "dist" / "releases" / f"VSE-Toolbox-v{TEST_VERSION}-test.zip"
    zip_path.write_bytes(b"PK\x05\x06" + b"\0" * 18)

    step = _run_step(repo)

    assert step.status == "PASS", step.details
    assert "启动器改动已配同版本 onedir 宿主包" in step.details
    assert zip_path.name in step.details


# ── 负向：验签 / 运行时 / 入口 ────────────────────────────────────────


def test_tampered_payload_fails(repo: Path) -> None:
    """包内文件被改动（签名有效但文件哈希不符）→ FAIL。"""
    target = _build_package(repo)
    _rewrite_package(
        target, {"files/webui.py": b"def main(argv=None):\n    return 1  # tampered\n"}
    )

    step = _run_step(repo)

    assert step.status == "FAIL"
    assert "未验签" in step.details
    assert "webui.py" in step.details


def test_tampered_manifest_fails(repo: Path) -> None:
    """清单被改动（签名不再匹配）→ FAIL。"""
    target = _build_package(repo)
    with zipfile.ZipFile(target) as archive:
        manifest = json.loads(archive.read("package.json"))
    manifest["notes"] = "被篡改的更新说明"
    _rewrite_package(
        target,
        {
            "package.json": json.dumps(
                manifest, ensure_ascii=False, indent=2, sort_keys=True
            ).encode("utf-8")
        },
    )

    step = _run_step(repo)

    assert step.status == "FAIL"
    assert "未验签" in step.details
    assert "签名" in step.details


def test_wrong_runtime_fails(repo: Path) -> None:
    """包声明了错误的运行环境（cp311）→ FAIL。"""
    _build_package(repo, runtime_tag="cp311")

    step = _run_step(repo)

    assert step.status == "FAIL"
    assert "未验签" in step.details
    assert "运行环境" in step.details
    assert "cp311" in step.details


def test_missing_entry_fails(repo: Path) -> None:
    """清单里没有程序入口 webui.py（签名有效）→ FAIL。"""
    _build_package_with_manifest(
        repo, manifest_files={"core/version.py": BASE_FILES["core/version.py"]}
    )

    step = _run_step(repo)

    assert step.status == "FAIL"
    assert "未验签" in step.details
    assert "程序入口" in step.details


# ── 负向：版本 / 提交内容 / 工作区 / 启动器覆盖 / 基线 ────────────────


def test_version_mismatch_fails(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """包版本 9.9.1 与仓库当前应用版本 9.9.2 不一致 → FAIL。"""
    _build_package(repo)
    monkeypatch.setenv("VSE_TOOLBOX_VERSION", "9.9.2")

    step = _run_step(repo)

    assert step.status == "FAIL"
    assert "未通过整包一致性" in step.details
    assert "版本不一致" in step.details
    assert "9.9.1" in step.details and "9.9.2" in step.details


def test_unknown_repo_version_fails(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """仓库版本未知时不能当作一致 → FAIL。"""
    _build_package(repo)
    monkeypatch.delenv("VSE_TOOLBOX_VERSION", raising=False)

    step = _run_step(repo)

    assert step.status == "FAIL"
    assert "版本未知" in step.details


def test_package_content_not_matching_head_fails(repo: Path) -> None:
    """包内容与 HEAD 不一致（工作区已恢复干净，只有包是旧内容）→ FAIL 并列出路径。"""
    stale = dict(BASE_FILES)
    stale["webui.py"] = "def main(argv=None):\n    return 1  # 未提交的改动\n".encode(
        "utf-8"
    )
    _build_package(repo, files=stale)
    (repo / "webui.py").write_bytes(BASE_FILES["webui.py"])  # 工作区回到 HEAD 内容

    step = _run_step(repo)

    assert step.status == "FAIL"
    assert "包内容与 HEAD 不一致" in step.details
    assert "webui.py" in step.details


def test_uncommitted_change_fails(repo: Path) -> None:
    """包内已跟踪文件有未提交改动 → FAIL「工作区与包不一致」。"""
    _build_package(repo)
    (repo / "webui.py").write_bytes(b"def main(argv=None):\n    return 1\n")

    step = _run_step(repo)

    assert step.status == "FAIL"
    assert "工作区与包不一致" in step.details
    assert "webui.py" in step.details


def test_launcher_change_without_onedir_zip_fails(repo: Path) -> None:
    """基线内有 vse_boot/ 改动、却没有同版本 onedir zip → FAIL「启动器改动不能只发 app 包」。"""
    _write_files(repo, {"vse_boot/layout.py": b"# launcher change\n"})
    _commit_all(repo, "launcher change")
    _build_package(repo)

    step = _run_step(repo)

    assert step.status == "FAIL"
    assert "启动器改动不能只发 app 包" in step.details
    assert "vse_boot/layout.py" in step.details
    assert f"*{TEST_VERSION}*.zip" in step.details


def test_launcher_spec_change_without_onedir_zip_fails(repo: Path) -> None:
    """``*.spec``（PyInstaller 启动器）改动同样要求 onedir 宿主包。"""
    _write_files(repo, {"VSE-Launcher.spec": b"# spec change\n"})
    _commit_all(repo, "spec change")
    _build_package(repo)

    step = _run_step(repo)

    assert step.status == "FAIL"
    assert "启动器改动不能只发 app 包" in step.details
    assert "VSE-Launcher.spec" in step.details


def test_onedir_zip_with_other_version_does_not_satisfy_launcher_check(
    repo: Path,
) -> None:
    """子串命中的旧/新版本 zip（9.9.11 之于 9.9.1）不能顶替同版本 onedir 包 → FAIL。"""
    _write_files(repo, {"vse_boot/layout.py": b"# launcher change\n"})
    _commit_all(repo, "launcher change")
    _build_package(repo)
    decoy = repo / "dist" / "releases" / f"VSE-Toolbox-v{TEST_VERSION}1-test.zip"
    decoy.write_bytes(b"PK\x05\x06" + b"\0" * 18)

    step = _run_step(repo)

    assert step.status == "FAIL"
    assert "启动器改动不能只发 app 包" in step.details


def test_broken_git_entry_fails(tmp_path: Path) -> None:
    """有 .git 但 git 认不出（损坏的 gitdir）→ FAIL，绝不退回仅验签。"""
    root = tmp_path / "broken"
    root.mkdir()
    (root / ".git").write_text("gitdir: C:/nonexistent/gitdir\n", encoding="utf-8")
    _build_package(root)

    step = _run_step(root)

    assert step.status == "FAIL"
    assert "无法校验提交一致性" in step.details
    assert "跳过" not in step.details


def test_repo_subdirectory_is_not_silently_accepted(repo: Path) -> None:
    """repo_root 只是仓库子目录（工作树根不一致）→ FAIL，不做半套校验。"""
    sub = repo / "core"
    _build_package(sub)

    step = _run_step(sub)

    assert step.status == "FAIL"
    assert "仓库根不一致" in step.details


def test_missing_since_fails(repo: Path) -> None:
    """release 模式缺 --since 比较基线 → FAIL。"""
    _build_package(repo)

    step = wave_gate.execute_package_sign_step(repo, "release")

    assert step.status == "FAIL"
    assert "未指定比较基线" in step.details
    assert "--since" in step.details


def test_unknown_baseline_fails(repo: Path) -> None:
    """基线 REF 不存在（git rev-parse 失败）→ FAIL，不静默放过。"""
    _build_package(repo)

    step = _run_step(repo, since="no-such-ref")

    assert step.status == "FAIL"
    assert "无法比较基线 no-such-ref" in step.details


def test_since_starting_with_dash_is_rejected(repo: Path) -> None:
    """--since 以 '-' 开头会被 git 当选项（--output=... 会写文件）→ 直接 FAIL。"""
    _build_package(repo)

    step = _run_step(repo, since="--output=dist/leak.txt")

    assert step.status == "FAIL"
    assert "比较基线无效" in step.details
    assert not (repo / "dist" / "leak.txt").exists()


def test_dev_mode_still_skips(tmp_path: Path) -> None:
    """dev 模式行为不变：不校验打包，如实 SKIP 并说明原因。"""
    step = wave_gate.execute_package_sign_step(tmp_path, "dev", since="HEAD~1")

    assert step.status == "SKIP"
    assert step.details


def test_main_passes_since_to_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    """CLI 接线：release + --since 传给门禁；dev 不传新参数（既有签名兼容）。"""
    captured: dict[str, object] = {}

    def fake_execute(**kwargs):  # type: ignore[no-untyped-def]
        captured.update(kwargs)
        return 0

    monkeypatch.setattr(wave_gate, "execute_wave_gate", fake_execute)

    with pytest.raises(SystemExit) as release_exit:
        wave_gate.main(["--mode", "release", "--since", BASELINE])
    assert release_exit.value.code == 0
    assert captured["mode"] == "release"
    assert captured["since"] == BASELINE

    captured.clear()
    with pytest.raises(SystemExit) as dev_exit:
        wave_gate.main(["--focus", "tests/test_x.py"])
    assert dev_exit.value.code == 0
    assert captured["mode"] == "dev"
    assert "since" not in captured


# ── 启动失败 / 试用回退 / 手动回退：业务数据不被覆盖 ──────────────────


def _verified_app(version: str, entry_source: bytes):  # type: ignore[no-untyped-def]
    """用临时信任链造一个真签名的 app 包并验签（不读任何既有私钥）。"""
    from vse_boot.packages import (
        TARGET_RUNTIME_TAG,
        build_app_package,
        key_id_for,
        verify_app_package,
    )

    pem = _private_key_pem()
    public = _public_key(pem)
    _name, data = build_app_package(
        {"webui.py": entry_source},
        version=version,
        private_key_pem=pem,
        runtime_tag=TARGET_RUNTIME_TAG,
    )
    return verify_app_package(
        data, {key_id_for(public): public}, runtime_tag=TARGET_RUNTIME_TAG
    )


def _write_business_data(layout) -> tuple[Path, bytes, int]:  # type: ignore[no-untyped-def]
    data_file = layout.data_dir / "projects" / "demo" / "records.json"
    data_file.parent.mkdir(parents=True, exist_ok=True)
    payload = '{"rows": [{"id": 1, "value": "试用期间写入的新业务数据"}]}'.encode("utf-8")
    data_file.write_bytes(payload)
    return data_file, payload, data_file.stat().st_mtime_ns


def test_failed_trial_rolls_back_without_touching_business_data(
    tmp_path: Path,
) -> None:
    """v1 生效 → 写业务数据 → 试用 v2（入口启动失败）→ 回滚 v1，业务数据不变。"""
    from vse_boot.layout import InstallLayout
    from vse_boot.packages import stage_app
    from vse_boot.state import BootState

    layout = InstallLayout(tmp_path / "install").ensure()

    stage_app(_verified_app("1.0.0", b"def main(argv=None):\n    return 0\n"), layout)
    assert BootState(layout).install_staged() == ["1.0.0"]
    assert BootState(layout).app["current"] == "1.0.0"
    assert BootState(layout).select_for_boot() == ("1.0.0", False)

    data_file, payload, mtime = _write_business_data(layout)

    stage_app(
        _verified_app("2.0.0", "raise SystemExit('启动失败')\n".encode("utf-8")), layout
    )
    assert BootState(layout).install_staged() == ["2.0.0"]
    assert BootState(layout).app["trial"] == "2.0.0"

    # 试用版本的入口真的启动失败（不是假设）。
    entry = layout.app_dir("2.0.0") / "webui.py"
    failed = subprocess.run(
        [sys.executable, "-B", str(entry)],
        cwd=str(layout.app_dir("2.0.0")),
        capture_output=True,
        timeout=120,
        check=False,
    )
    assert failed.returncode != 0

    assert BootState(layout).select_for_boot() == ("2.0.0", True)

    # 试用后再没提交健康信号：下次启动按「意外退出」回滚到 1.0.0。
    recovered = BootState(layout)
    assert recovered.select_for_boot() == ("1.0.0", False)
    assert recovered.app["current"] == "1.0.0"
    assert recovered.app["trial"] is None
    assert any(event["kind"] == "rolledBack" for event in recovered.events)
    assert not layout.app_dir("2.0.0").exists()

    assert data_file.read_bytes() == payload
    assert data_file.stat().st_mtime_ns == mtime


def test_manual_rollback_after_activation_keeps_new_business_data(
    tmp_path: Path,
) -> None:
    """已生效版本手动回退：v2 生效后写入的业务数据不被 v1 覆盖。"""
    from vse_boot.layout import InstallLayout
    from vse_boot.packages import stage_app
    from vse_boot.state import BootState

    layout = InstallLayout(tmp_path / "install").ensure()

    stage_app(_verified_app("1.0.0", b"def main(argv=None):\n    return 0\n"), layout)
    BootState(layout).install_staged()

    stage_app(_verified_app("2.0.0", b"def main(argv=None):\n    return 0\n"), layout)
    BootState(layout).install_staged()
    assert BootState(layout).select_for_boot() == ("2.0.0", True)
    BootState(layout).commit("2.0.0")
    activated = BootState(layout)
    assert activated.app["current"] == "2.0.0"
    assert activated.app["previous"] == "1.0.0"

    data_file, payload, mtime = _write_business_data(layout)

    assert BootState(layout).rollback() == "1.0.0"
    rolled_back = BootState(layout)
    assert rolled_back.app["current"] == "1.0.0"
    assert rolled_back.select_for_boot() == ("1.0.0", False)
    assert any(event["kind"] == "manualRollback" for event in rolled_back.events)

    assert data_file.read_bytes() == payload
    assert data_file.stat().st_mtime_ns == mtime


def test_onedir_zip_version_match_is_exact(tmp_path: Path) -> None:
    """精确版本：后缀 .zip 不算版本延续；2.3.0 不被 2.3.0.1 / 12.3.0 冒充。"""
    from tools import wave_gate as gate

    releases = tmp_path / "dist" / "releases"
    releases.mkdir(parents=True)
    names = [
        "VSE-Toolbox-2.3.0.zip",
        "VSE-Toolbox-v2.3.0-onedir.zip",
        "VSE-Toolbox-2.3.0.1.zip",
        "VSE-Toolbox-12.3.0.zip",
    ]
    for name in names:
        (releases / name).write_bytes(b"zip")
    found = sorted(path.name for path in gate.find_onedir_packages(tmp_path, "2.3.0"))
    assert found == ["VSE-Toolbox-2.3.0.zip", "VSE-Toolbox-v2.3.0-onedir.zip"]
