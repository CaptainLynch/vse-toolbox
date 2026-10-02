# -*- coding: utf-8 -*-
"""Create the Ed25519 signing key for plugin packages (run once on the build machine).

Usage::

    python tools/plugin_keys.py init D:\\vse-signing\\plugin-signing.pem

写出私钥（只放在构建机并离线备份，绝不提交、不发飞书），并把公钥追加到
``host/trusted_keys.json``——提交这个文件后发布的宿主才信任该密钥签名的插件包。
宿主可同时信任多把公钥（主钥 + 备用钥），轮换时先发布含新公钥的宿主。
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from host.updates import TRUSTED_KEYS_FILE, key_id_for  # noqa: E402


def init_key(private_path: Path, trusted_file: Path = TRUSTED_KEYS_FILE, *, label: str = "") -> str:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    private_path = Path(private_path).resolve()
    if REPO_ROOT in private_path.parents:
        raise SystemExit("私钥不能放在仓库目录里")
    if private_path.exists():
        raise SystemExit(f"{private_path} 已存在，拒绝覆盖")
    private = Ed25519PrivateKey.generate()
    pem = private.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )
    public = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    private_path.parent.mkdir(parents=True, exist_ok=True)
    private_path.write_bytes(pem)
    try:
        raw = json.loads(trusted_file.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raw = {"keys": []}
    key_id = key_id_for(public)
    raw.setdefault("keys", []).append(
        {"keyId": key_id, "publicKey": base64.b64encode(public).decode("ascii"), "label": label}
    )
    trusted_file.write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return key_id


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="插件包签名密钥")
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init", help="生成新密钥对，并把公钥加入 host/trusted_keys.json")
    init.add_argument("private_key", type=Path, help="私钥输出路径（仓库外）")
    init.add_argument("--label", default="", help="公钥备注，例如 主钥 / 备用钥")
    args = parser.parse_args(argv)
    key_id = init_key(args.private_key, label=args.label)
    print(f"已生成密钥 {key_id}。私钥：{args.private_key}")
    print("请提交 host/trusted_keys.json，并重新发布宿主。私钥只留在构建机并离线备份。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
