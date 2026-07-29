"""Manual, deidentified Chrome verification for the Aras auth navigation path.

This script has no embedded target.  The approved base URL is accepted only as
one standard-input line and cleared before exit.  Output contains only fixed
categories and booleans.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import requests
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait

from services.aras_auth import (
    CALLBACK_ROUTE,
    CLIENT_ROUTE,
    _CALLBACK_MEMORY_KEY,
    ArasAuthError,
    ArasPasswordAuthClient,
    _install_callback_capture_hook,
    _navigate_authorize_with_cdp,
    _read_callback_capture,
)


class _QuietHandler(BaseHTTPRequestHandler):
    control_body = (
        b"<!doctype html><body data-loopback-marker='ok'>"
        b"<script>window.loopbackJs=true;</script></body>"
    )
    authorize_body = (
        b"<!doctype html><body><form method='post' action='/login'>"
        b"<input type='text' name='username'>"
        b"<input type='password' name='password'>"
        b"<button type='submit' formmethod='post' formaction='/login'>Continue</button>"
        b"</form></body>"
    )
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        body = self.authorize_body if path == "/authorize" else self.control_body
        self.server.request_count += 1  # type: ignore[attr-defined]
        self.server.last_status = 200  # type: ignore[attr-defined]
        self.server.last_body_bytes = len(body)  # type: ignore[attr-defined]
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        content_length = max(0, int(self.headers.get("Content-Length", "0") or "0"))
        submitted = self.rfile.read(content_length)
        self.server.post_count += 1  # type: ignore[attr-defined]
        self.server.last_post_nonempty = bool(submitted)  # type: ignore[attr-defined]
        submitted = b""
        self.send_response(302)
        self.send_header(
            "Location",
            self.server.callback_location + "#marker=synthetic-callback",  # type: ignore[attr-defined]
        )
        self.send_header("Content-Length", "0")
        self.send_header("Connection", "close")
        self.end_headers()

    def log_message(self, *_args: object) -> None:
        return


def _start_server() -> tuple[ThreadingHTTPServer, threading.Thread]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _QuietHandler)
    server.request_count = 0  # type: ignore[attr-defined]
    server.last_status = None  # type: ignore[attr-defined]
    server.last_body_bytes = 0  # type: ignore[attr-defined]
    server.post_count = 0  # type: ignore[attr-defined]
    server.last_post_nonempty = False  # type: ignore[attr-defined]
    server.callback_location = ""  # type: ignore[attr-defined]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def _chrome_options(profile: str) -> webdriver.ChromeOptions:
    options = webdriver.ChromeOptions()
    options.page_load_strategy = "none"
    options.add_argument("--headless=new")
    options.add_argument("--incognito")
    options.add_argument(f"--user-data-dir={profile}")
    return options


def _wait_script(driver: webdriver.Chrome, script: str) -> bool:
    return bool(
        WebDriverWait(driver, 10).until(
            lambda browser: browser.execute_script(script)
        )
    )


def _wait_exact_context(
    driver: webdriver.Chrome,
    expected_origin: str,
    expected_path: str,
) -> bool:
    return bool(
        WebDriverWait(driver, 10).until(
            lambda browser: browser.execute_script(
                "return window.location.origin === arguments[0] && "
                "window.location.pathname === arguments[1];",
                expected_origin,
                expected_path,
            )
        )
    )


def run() -> dict[str, object]:
    result: dict[str, object] = {
        "edge_historical_only": True,
        "chrome_local_started": False,
        "chrome_binary_class": "not_started",
        "chrome_version": "unavailable",
        "chromedriver_version": "unavailable",
        "version_major_compatible": False,
        "strategy_none": False,
        "data_dom": False,
        "data_js": False,
        "data_cdp_document_start": False,
        "loopback_navigate": False,
        "loopback_nonempty_2xx": False,
        "callback_fragment": False,
        "callback_query": False,
        "callback_mixed": False,
        "callback_mixed_present": False,
        "callback_mixed_query_preserved": False,
        "callback_mixed_fragment_preserved": False,
        "callback_exact_path_reject": False,
        "callback_exact_origin_reject": False,
        "callback_read_once_delete": False,
        "callback_cleanup": False,
        "timing_hook_before_clear_script": False,
        "timing_clear_script_before_navigate": False,
        "timing_navigate_before_exact_context_wait": False,
        "timing_exact_context_before_capture_read": False,
        "local_driver_service_exit": False,
        "local_profile_removed": False,
        "full_login_result": "not_run",
        "full_login_stage": "",
        "full_login_substage": "",
        "full_login_category": "",
        "full_login_chrome_constructors": 0,
        "full_login_edge_constructors": 0,
        "full_login_callback_exact": False,
        "full_login_form_post_nonempty": False,
        "full_login_profile_removed": False,
        "full_login_driver_service_exit": False,
        "target_discovery_fresh": False,
        "target_page_navigate_calls": 0,
        "target_result_code": "not_run",
        "target_stage": "",
        "target_substage": "",
        "target_category": "",
        "target_zero_dom_form_credential_interaction": True,
        "target_driver_service_exit": False,
        "target_profile_removed": False,
        "loopback_servers_stopped": False,
    }
    local_profile = tempfile.mkdtemp(prefix="vse-chrome-local-runtime-")
    target_profile = tempfile.mkdtemp(prefix="vse-chrome-target-runtime-")
    local_driver: webdriver.Chrome | None = None
    target_driver: webdriver.Chrome | None = None
    local_service_process = None
    target_service_process = None
    server1 = thread1 = server2 = thread2 = None
    session: requests.Session | None = None
    authorize_url = ""
    state = ""
    metadata: dict[str, object] = {}
    trusted_origins: set[str] = set()
    target_base = str(sys.stdin.readline() or "").strip()
    try:
        server1, thread1 = _start_server()
        server2, thread2 = _start_server()
        port1 = server1.server_address[1]
        port2 = server2.server_address[1]
        origin1 = f"http://127.0.0.1:{port1}"
        origin2 = f"http://127.0.0.1:{port2}"
        callback_path = "/Client/OAuth/RedirectCallback"
        callback_target = origin1 + callback_path
        full_callback_target = (
            origin1 + "/innovatorserver/Client/OAuth/RedirectCallback"
        )
        server1.callback_location = full_callback_target  # type: ignore[attr-defined]

        local_service = Service(log_output=os.devnull)
        local_driver = webdriver.Chrome(
            service=local_service,
            options=_chrome_options(local_profile),
        )
        local_service_process = local_service.process
        result["chrome_local_started"] = True
        result["chrome_binary_class"] = "system_auto_discovered"
        browser_version = str(local_driver.capabilities.get("browserVersion", ""))
        driver_version = str(
            local_driver.capabilities.get("chrome", {}).get(
                "chromedriverVersion", ""
            )
        ).split(" ", 1)[0]
        version_pattern = r"\d+(?:\.\d+){1,3}"
        result["chrome_version"] = (
            browser_version
            if re.fullmatch(version_pattern, browser_version)
            else "classified"
        )
        result["chromedriver_version"] = (
            driver_version
            if re.fullmatch(version_pattern, driver_version)
            else "classified"
        )
        result["version_major_compatible"] = bool(
            browser_version
            and driver_version
            and browser_version.split(".", 1)[0]
            == driver_version.split(".", 1)[0]
        )
        result["strategy_none"] = (
            local_driver.capabilities.get("pageLoadStrategy") == "none"
        )

        local_driver.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument",
            {
                "source": (
                    "Object.defineProperty(window,'__vseDocStart',"
                    "{value:true,configurable:true});"
                )
            },
        )
        _navigate_authorize_with_cdp(
            local_driver,
            (
                "data:text/html,<body data-runtime-marker='ok'>"
                "<script>window.runtimeJs=2%2B3;</script></body>"
            ),
        )
        data_checks = WebDriverWait(local_driver, 10).until(
            lambda browser: browser.execute_script(
                "return document.body ? ["
                "document.body.dataset.runtimeMarker === 'ok',"
                "window.runtimeJs === 5,window.__vseDocStart === true] : null;"
            )
        )
        (
            result["data_dom"],
            result["data_js"],
            result["data_cdp_document_start"],
        ) = [bool(value) for value in data_checks]

        _install_callback_capture_hook(local_driver, callback_target)
        clear_script_result = local_driver.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument",
            {
                "source": (
                    "(() => { try {"
                    f"const expectedOrigin={json.dumps(origin1)};"
                    f"const expectedPath={json.dumps(callback_path)};"
                    "if (window.location.origin !== expectedOrigin || "
                    "window.location.pathname !== expectedPath) { return; }"
                    "const mode=new URLSearchParams(window.location.search).get('vse_clear');"
                    "if (!mode) { return; }"
                    "Object.defineProperty(window,'__vseClearScriptRan',"
                    "{value:true,configurable:true});"
                    "if (mode === 'both') { history.replaceState(null,'',window.location.pathname); }"
                    "else if (mode === 'hash') { history.replaceState(null,'',window.location.pathname+window.location.search); }"
                    "else if (mode === 'search') { history.replaceState(null,'',window.location.pathname+window.location.hash); }"
                    "} catch (_) {} })();"
                )
            },
        )
        result["timing_hook_before_clear_script"] = bool(
            isinstance(clear_script_result, dict)
            and clear_script_result.get("identifier")
        )
        result["timing_clear_script_before_navigate"] = True
        _navigate_authorize_with_cdp(local_driver, origin1 + "/control")
        result["loopback_navigate"] = _wait_script(
            local_driver,
            "return Boolean(document.body && "
            "document.body.dataset.loopbackMarker === 'ok' && "
            "window.loopbackJs === true);",
        )
        result["loopback_nonempty_2xx"] = bool(
            server1.request_count >= 1  # type: ignore[attr-defined]
            and server1.last_status == 200  # type: ignore[attr-defined]
            and server1.last_body_bytes > 0  # type: ignore[attr-defined]
        )

        cases = [
            ("fragment", "#marker=synthetic-fragment"),
            ("query", "?marker=synthetic-query"),
            ("mixed", "?marker=synthetic-query#marker=synthetic-fragment"),
        ]
        read_once_results = []
        for label, suffix in cases:
            # Force a new document for every callback case.  Navigating from a
            # query-only URL to the same query plus a fragment is a Chrome
            # same-document navigation and correctly does not rerun a
            # document-start hook.
            _navigate_authorize_with_cdp(
                local_driver,
                origin1 + f"/control-before-{label}",
            )
            _wait_exact_context(
                local_driver,
                origin1,
                f"/control-before-{label}",
            )
            _navigate_authorize_with_cdp(local_driver, callback_target + suffix)
            result["timing_navigate_before_exact_context_wait"] = True
            assert _wait_exact_context(local_driver, origin1, callback_path)
            result["timing_exact_context_before_capture_read"] = True
            captured = _read_callback_capture(local_driver, callback_target)
            result[f"callback_{label}"] = captured == callback_target + suffix
            if label == "mixed":
                captured_parts = urlsplit(captured or "")
                result["callback_mixed_present"] = bool(captured)
                result["callback_mixed_query_preserved"] = (
                    captured_parts.query == "marker=synthetic-query"
                )
                result["callback_mixed_fragment_preserved"] = (
                    captured_parts.fragment == "marker=synthetic-fragment"
                )
            read_once_results.append(
                _read_callback_capture(local_driver, callback_target) is None
            )
            captured = ""
        result["callback_read_once_delete"] = all(read_once_results)

        for mode in ("none", "hash", "search", "both"):
            diagnostic_suffix = (
                f"?vse_clear={mode}&marker=synthetic-query"
                "#marker=synthetic-fragment"
            )
            constructed = urlsplit(callback_target + diagnostic_suffix)
            result[f"diag_{mode}_constructed_search_present"] = bool(
                constructed.query
            )
            result[f"diag_{mode}_constructed_hash_present"] = bool(
                constructed.fragment
            )
            _navigate_authorize_with_cdp(
                local_driver,
                callback_target + diagnostic_suffix,
            )
            result[f"diag_{mode}_origin_path_match"] = _wait_exact_context(
                local_driver,
                origin1,
                callback_path,
            )
            location_state = local_driver.execute_script(
                "return ["
                "window.location.origin === arguments[0] && "
                "window.location.pathname === arguments[1],"
                "Boolean(window.location.search),Boolean(window.location.hash),"
                "window.__vseClearScriptRan === true];",
                origin1,
                callback_path,
            )
            result[f"diag_{mode}_script_origin_path_match"] = bool(
                location_state[0]
            )
            result[f"diag_{mode}_location_search_present"] = bool(
                location_state[1]
            )
            result[f"diag_{mode}_location_hash_present"] = bool(
                location_state[2]
            )
            result[f"diag_{mode}_clear_script_ran"] = bool(location_state[3])
            diagnostic_capture = _read_callback_capture(
                local_driver,
                callback_target,
            )
            diagnostic_parts = urlsplit(diagnostic_capture or "")
            result[f"diag_{mode}_captured_search_present"] = bool(
                diagnostic_parts.query
            )
            result[f"diag_{mode}_captured_hash_present"] = bool(
                diagnostic_parts.fragment
            )
            result[f"diag_{mode}_read_once_empty"] = (
                _read_callback_capture(local_driver, callback_target) is None
            )
            diagnostic_capture = ""

        _navigate_authorize_with_cdp(
            local_driver,
            origin1 + callback_path + "-wrong#marker=wrong-path",
        )
        _wait_exact_context(local_driver, origin1, callback_path + "-wrong")
        result["callback_exact_path_reject"] = (
            _read_callback_capture(local_driver, callback_target) is None
        )

        _navigate_authorize_with_cdp(
            local_driver,
            origin2 + callback_path + "#marker=wrong-origin",
        )
        _wait_exact_context(local_driver, origin2, callback_path)
        result["callback_exact_origin_reject"] = (
            _read_callback_capture(local_driver, callback_target) is None
        )

        _navigate_authorize_with_cdp(
            local_driver,
            callback_target + "#marker=cleanup",
        )
        _wait_exact_context(local_driver, origin1, callback_path)
        local_driver.execute_script(
            "window.localStorage.setItem('vse-runtime-marker','1');"
            "window.sessionStorage.setItem('vse-runtime-marker','1');"
        )
        local_driver.execute_script(
            "try { delete window[arguments[0]]; } catch (_) {} "
            "window.localStorage.clear(); window.sessionStorage.clear();",
            _CALLBACK_MEMORY_KEY,
        )
        local_driver.delete_all_cookies()
        result["callback_cleanup"] = bool(
            local_driver.execute_script(
                "return !Object.prototype.hasOwnProperty.call(window,arguments[0]) "
                "&& window.localStorage.length === 0 "
                "&& window.sessionStorage.length === 0;",
                _CALLBACK_MEMORY_KEY,
            )
        ) and len(local_driver.get_cookies()) == 0

        local_driver.quit()
        local_driver = None
        time.sleep(0.5)
        result["local_driver_service_exit"] = bool(
            local_service_process is not None
            and local_service_process.poll() is not None
        )
        shutil.rmtree(local_profile, ignore_errors=True)
        result["local_profile_removed"] = not os.path.exists(local_profile)

        real_chrome_constructor = webdriver.Chrome
        real_edge_constructor = webdriver.Edge
        full_login_profiles: list[Path] = []
        full_login_service_processes: list[object] = []

        def counted_chrome(*args, **kwargs):  # type: ignore[no-untyped-def]
            result["full_login_chrome_constructors"] = int(
                result["full_login_chrome_constructors"]
            ) + 1
            options = kwargs.get("options")
            for argument in getattr(options, "arguments", []):
                if str(argument).startswith("--user-data-dir="):
                    full_login_profiles.append(
                        Path(str(argument).split("=", 1)[1])
                    )
            chrome_driver = real_chrome_constructor(*args, **kwargs)
            if getattr(chrome_driver, "service", None) is not None:
                full_login_service_processes.append(chrome_driver.service.process)
            return chrome_driver

        def reject_edge(*_args, **_kwargs):  # type: ignore[no-untyped-def]
            result["full_login_edge_constructors"] = int(
                result["full_login_edge_constructors"]
            ) + 1
            raise AssertionError("Edge must not be constructed after Chrome success")

        webdriver.Chrome = counted_chrome  # type: ignore[assignment]
        webdriver.Edge = reject_edge  # type: ignore[assignment]
        try:
            full_client = ArasPasswordAuthClient(
                origin1 + "/innovatorserver/",
                allow_insecure_http=True,
                timeout=10,
            )
            full_callback = full_client._login_with_selenium(
                origin1 + "/authorize",
                {origin1},
                "synthetic-user",
                "synthetic-password",
            )
            result["full_login_result"] = "success"
            result["full_login_callback_exact"] = (
                full_callback
                == full_callback_target + "#marker=synthetic-callback"
            )
            full_callback = ""
        except ArasAuthError as error:
            result["full_login_result"] = error.code
            result["full_login_stage"] = error.stage
            result["full_login_substage"] = error.substage or ""
            result["full_login_category"] = error.category or ""
        finally:
            webdriver.Chrome = real_chrome_constructor  # type: ignore[assignment]
            webdriver.Edge = real_edge_constructor  # type: ignore[assignment]
        time.sleep(0.5)
        result["full_login_form_post_nonempty"] = bool(
            server1.post_count == 1  # type: ignore[attr-defined]
            and server1.last_post_nonempty  # type: ignore[attr-defined]
        )
        result["full_login_profile_removed"] = bool(
            len(full_login_profiles) == 1
            and not full_login_profiles[0].exists()
        )
        result["full_login_driver_service_exit"] = bool(
            len(full_login_service_processes) == 1
            and full_login_service_processes[0] is not None
            and full_login_service_processes[0].poll() is not None
        )
        full_login_profiles.clear()
        full_login_service_processes.clear()

        parsed_target = urlsplit(target_base)
        client = ArasPasswordAuthClient(
            target_base,
            allow_insecure_http=parsed_target.scheme.casefold() == "http",
            timeout=30,
        )
        session = requests.Session()
        session.trust_env = False
        prewarm = client._request(
            session,
            "GET",
            client._aras_url(CLIENT_ROUTE),
            stage="client",
        )
        prewarm = None
        metadata, trusted_origins = client._discover(session)
        authorize_url, state = client._authorize_url(metadata)
        result["target_discovery_fresh"] = bool(
            authorize_url and state and trusted_origins
        )

        target_service = Service(log_output=os.devnull)
        target_driver = webdriver.Chrome(
            service=target_service,
            options=_chrome_options(target_profile),
        )
        target_service_process = target_service.process
        _install_callback_capture_hook(
            target_driver,
            client._aras_url(CALLBACK_ROUTE),
        )
        result["target_page_navigate_calls"] = 1
        try:
            _navigate_authorize_with_cdp(target_driver, authorize_url)
            result["target_result_code"] = "NAVIGATE_RETURNED_WITHOUT_FIXED_ERROR"
            result["target_stage"] = "browser"
            result["target_substage"] = "navigate"
            result["target_category"] = "none"
        except ArasAuthError as error:
            result["target_result_code"] = error.code
            result["target_stage"] = error.stage
            result["target_substage"] = error.substage or ""
            result["target_category"] = error.category or ""
    except Exception as error:
        result["safe_failure_type"] = type(error).__name__
        if isinstance(error, ArasAuthError):
            result["safe_failure_code"] = error.code
            result["safe_failure_stage"] = error.stage
    finally:
        authorize_url = ""
        state = ""
        metadata = {}
        trusted_origins = set()
        target_base = ""
        if session is not None:
            session.headers.clear()
            session.cookies.clear()
            session.close()
        if target_driver is not None:
            try:
                target_driver.delete_all_cookies()
            except Exception:
                pass
            try:
                target_driver.quit()
            except Exception:
                pass
        time.sleep(0.5)
        result["target_driver_service_exit"] = bool(
            target_service_process is not None
            and target_service_process.poll() is not None
        )
        shutil.rmtree(target_profile, ignore_errors=True)
        result["target_profile_removed"] = not os.path.exists(target_profile)
        if local_driver is not None:
            try:
                local_driver.delete_all_cookies()
            except Exception:
                pass
            try:
                local_driver.quit()
            except Exception:
                pass
        shutil.rmtree(local_profile, ignore_errors=True)
        result["local_profile_removed"] = bool(
            result["local_profile_removed"] or not os.path.exists(local_profile)
        )
        for server, thread in ((server1, thread1), (server2, thread2)):
            if server is not None:
                server.shutdown()
                server.server_close()
            if thread is not None:
                thread.join(timeout=2)
        result["loopback_servers_stopped"] = all(
            thread is None or not thread.is_alive()
            for thread in (thread1, thread2)
        )
    return result


if __name__ == "__main__":
    print(json.dumps(run(), sort_keys=True))
