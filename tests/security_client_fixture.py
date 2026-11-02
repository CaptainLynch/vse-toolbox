# -*- coding: utf-8 -*-
"""认证测试客户端（DSH-V2-05：从产品安全模块移到 ``tests/``）。

背景：DSH-V2-03 期间 ``web/security.py`` 的 ``install_local_security()`` 末尾会调用
``install_security_aware_test_client(app)``，把 ``app.test_client_class`` 换成「写请求
自动补 Origin + 首次写前真实调用 boot-exchange 取会话」的客户端。那是测试便利设施，
却安装在**生产安全模块**里：任何人忘记用原生客户端，都可能让未认证访问看起来是放行的。

本模块承接该替身（行为与迁移前逐字等价，不旁路任何服务端判定）：

- 写请求自动补 ``Origin: http://<Host>``（真实浏览器同源写必带）；
- 首次写之前用 ``app.config["VSE_BOOT_TOKEN"]`` **真实调用**
  ``POST /api/security/boot-exchange`` 换会话 Cookie；
- fail-closed 路径（无票据 / 无会话 / 无 Origin / 跨源）必须用原生 werkzeug Client
  （``werkzeug.test.Client(app, Response)`` 或未安装本替身的 ``app.test_client()``）断言。

用法：

- 显式安装：``install_authenticated_test_client(app)``（返回装好替身的 app）；
- pytest fixture：``authed_client``（依赖同名 ``app`` fixture，返回已认证客户端）；
- 默认安装（普通业务测试）：``tests/conftest.py`` 的 autouse fixture 包装
  ``web.security.install_local_security``，在 create_app 装配本机安全之后安装本替身；
  带 ``raw_security`` marker 的测试与安全测试模块（``test_local_security.py``、
  ``test_local_security_integration.py``、``test_boot_ticket_transport.py``）不安装。
"""

from __future__ import annotations

from typing import Any

import pytest

from web.security import BOOT_EXCHANGE_PATH, WRITE_METHODS


def install_authenticated_test_client(app: Any) -> Any:
    """把 ``app.test_client()`` 替换为带浏览器等价行为的客户端，返回 ``app``。

    与迁移前的 ``web.security.install_security_aware_test_client`` 行为一致：
    只补「真实浏览器本来就会带」的 Origin，并用 app.config 里的票据真实走一次
    boot-exchange；服务端判定（会话、Origin、票据、限流）一律不绕过。
    """
    from flask.testing import FlaskClient

    base = app.test_client_class if app.test_client_class else FlaskClient
    base_open = base.open

    class _SecurityAwareTestClient(base):  # type: ignore[valid-type,misc]
        _bootstrapped = False

        def open(self, *args: Any, **kwargs: Any):  # type: ignore[override]
            method = str(
                kwargs.get("method") or (args[1] if len(args) > 1 else "GET")
            ).upper()
            if method in WRITE_METHODS:
                host = self._outer_host(kwargs)
                self._ensure_bootstrap(host)
                kwargs["headers"] = self._with_origin(kwargs.get("headers"), host)
            return base_open(self, *args, **kwargs)

        def _outer_host(self, kwargs: dict) -> str:
            """外层请求实际使用的 Host（cookie 按 host 隔离，交换须同 host）。"""
            environ = kwargs.get("environ_base") or {}
            if isinstance(environ, dict) and environ.get("HTTP_HOST"):
                return str(environ["HTTP_HOST"])
            headers = kwargs.get("headers") or {}
            if isinstance(headers, dict) and headers.get("Host"):
                return str(headers["Host"])
            return "localhost"

        def _with_origin(self, headers: Any, host: str) -> Any:
            origin = self._origin(host)
            if headers is None:
                return {"Origin": origin}
            if isinstance(headers, dict):
                merged = dict(headers)
                merged.setdefault("Origin", origin)
                return merged
            # （headers, environ）或 Header 对象等罕见形态：原样返回，交由用例自带。
            return headers

        def _origin(self, host: str = "localhost") -> str:
            # 真实浏览器对同源写请求必带 Origin 且端口与 Host 一致；
            # 测试客户端默认 Host 为 "localhost"（省略 80 端口）。
            if host.endswith(":80"):
                host = host[:-3]
            return f"http://{host}"

        def _ensure_bootstrap(self, host: str) -> None:
            if self._bootstrapped:
                return
            self._bootstrapped = True
            token = self.application.config.get("VSE_BOOT_TOKEN")
            if not token:
                return
            base_open(
                self,
                BOOT_EXCHANGE_PATH,
                method="POST",
                json={"token": token},
                headers={"Origin": self._origin(host), "Host": host},
            )

    app.test_client_class = _SecurityAwareTestClient
    return app


def authenticated_test_client(app: Any) -> Any:
    """安装替身并返回该 app 的已认证测试客户端。"""
    install_authenticated_test_client(app)
    return app.test_client()


@pytest.fixture()
def authed_client(request):
    """显式选择已认证测试客户端（需同名 ``app`` fixture，见 DSH-V2-05 契约 2）。

    普通业务测试若想显式声明依赖，用 ``def test_x(app, authed_client)``；
    默认替身由 ``tests/conftest.py`` 的 autouse fixture 安装，负向安全测试用
    ``@pytest.mark.raw_security`` 或安全测试模块名豁免。
    """
    app = request.getfixturevalue("app")
    return authenticated_test_client(app)
