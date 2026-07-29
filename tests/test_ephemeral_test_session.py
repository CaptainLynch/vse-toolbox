from __future__ import annotations

import pytest

import services.ephemeral_test_session as ephemeral


BASE_URL = "https://aras.example/innovatorserver/"
USERNAME = "unit-test-user"
PASSWORD = "unit-test-password"


class OwnedSession:
    def __init__(self) -> None:
        self.headers = {"Authorization": "Bearer unit-test-token"}
        self.cookies = {"sid": "unit-test-cookie"}
        self.closed = False

    def close(self) -> None:
        self.closed = True


def _seed(vault: ephemeral.EphemeralTestSessionVault):
    sid, csrf = vault.bootstrap()
    new_sid, new_csrf, status = vault.seed(
        sid,
        csrf,
        base_url=BASE_URL,
        username=USERNAME,
        password=PASSWORD,
        allow_insecure_http=False,
        module="ewo",
        filters={"ewo_no": "EWO-1"},
    )
    return sid, csrf, new_sid, new_csrf, status


def _assert_error(code: str, callback) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(ephemeral.EphemeralTestSessionError) as excinfo:
        callback()
    assert excinfo.value.code == code


def test_bootstrap_and_seed_rotate_tokens_never_echo_password_and_keep_ram_only() -> None:
    vault = ephemeral.EphemeralTestSessionVault()
    try:
        old_sid, old_csrf, sid, csrf, status = _seed(vault)

        assert sid != old_sid
        assert csrf != old_csrf
        assert PASSWORD not in repr(status)
        assert "password" not in status
        assert status["password_cached"] is True
        assert status["base_url"] == BASE_URL
        assert status["username"] == USERNAME
        assert status["filters"] == {"ewo_no": "EWO-1"}
        assert status["operations_remaining"] == ephemeral.MAX_OPERATIONS
        _assert_error(
            "TEST_SESSION_FORBIDDEN", lambda: vault.status(old_sid, old_csrf)
        )
        assert vault.status(sid, csrf)["password_cached"] is True
    finally:
        vault.close()


def test_secret_buffer_is_overwritten_on_clear_and_close() -> None:
    secret = ephemeral.SecretBuffer(PASSWORD)
    original_storage = secret._data
    secret.clear()
    assert secret.reveal() == ""
    assert original_storage == bytearray()

    vault = ephemeral.EphemeralTestSessionVault()
    _old_sid, _old_csrf, sid, csrf, _status = _seed(vault)
    password_buffer = vault._record.password
    assert password_buffer is not None
    storage = password_buffer._data
    vault.clear(sid, csrf)
    assert storage == bytearray()
    assert password_buffer.reveal() == ""
    vault.close()


def test_idle_and_hard_ttl_expiry_destroy_password_and_session(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    clock = [1000.0]
    monkeypatch.setattr(ephemeral.time, "monotonic", lambda: clock[0])
    vault = ephemeral.EphemeralTestSessionVault()
    try:
        _old_sid, _old_csrf, sid, csrf, _status = _seed(vault)
        password_buffer = vault._record.password
        assert password_buffer is not None
        clock[0] += ephemeral.IDLE_TTL_SECONDS + 1
        _assert_error("TEST_SESSION_NOT_FOUND", lambda: vault.status(sid, csrf))
        assert password_buffer.reveal() == ""

        _old_sid, _old_csrf, sid, csrf, _status = _seed(vault)
        lease = vault.begin_operation(sid, csrf, module="ewo", filters=None)
        session = OwnedSession()
        vault.promote_authenticated(lease, session, validated_module="ewo")
        vault.finish_success(lease)
        clock[0] += ephemeral.HARD_TTL_SECONDS + 1
        _assert_error("TEST_SESSION_NOT_FOUND", lambda: vault.status(sid, csrf))
        assert session.headers == {}
        assert session.cookies == {}
        assert session.closed is True
    finally:
        vault.close()


def test_single_flight_and_four_operation_limit() -> None:
    vault = ephemeral.EphemeralTestSessionVault()
    try:
        _old_sid, _old_csrf, sid, csrf, _status = _seed(vault)
        lease = vault.begin_operation(sid, csrf, module="ewo", filters=None)
        _assert_error(
            "TEST_SESSION_BUSY",
            lambda: vault.begin_operation(sid, csrf, module="paa", filters=None),
        )
        assert vault.finish_success(lease) is False

        for expected_remaining in (2, 1):
            lease = vault.begin_operation(sid, csrf, module="ewo", filters=None)
            assert vault.finish_success(lease) is False
            assert vault.status(sid, csrf)["operations_remaining"] == expected_remaining

        lease = vault.begin_operation(sid, csrf, module="ewo", filters=None)
        assert vault.finish_success(lease) is True
        _assert_error("TEST_SESSION_NOT_FOUND", lambda: vault.status(sid, csrf))
    finally:
        vault.close()


def test_any_scheme_a_failure_destroys_password_without_retry() -> None:
    vault = ephemeral.EphemeralTestSessionVault()
    try:
        _old_sid, _old_csrf, sid, csrf, _status = _seed(vault)
        password_buffer = vault._record.password
        assert password_buffer is not None

        lease = vault.begin_operation(sid, csrf, module="ewo", filters=None)
        assert vault.finish_failure(lease, preserve_pre_touch_password=True) is True
        assert password_buffer.reveal() == ""
        _assert_error("TEST_SESSION_NOT_FOUND", lambda: vault.status(sid, csrf))
    finally:
        vault.close()


def test_posttouch_failure_always_destroys_password() -> None:
    vault = ephemeral.EphemeralTestSessionVault()
    try:
        _old_sid, _old_csrf, sid, csrf, _status = _seed(vault)
        password_buffer = vault._record.password
        assert password_buffer is not None
        lease = vault.begin_operation(sid, csrf, module="ewo", filters=None)

        assert vault.finish_failure(lease, preserve_pre_touch_password=False) is True

        assert password_buffer.reveal() == ""
        _assert_error("TEST_SESSION_NOT_FOUND", lambda: vault.status(sid, csrf))
    finally:
        vault.close()


def test_running_clear_only_requests_cancel_and_operation_finally_closes() -> None:
    class OwnedSession:
        def __init__(self) -> None:
            self.headers = {}
            self.cookies = {}
            self.cancel_count = 0
            self.close_count = 0

        def request_cancel(self) -> None:
            self.cancel_count += 1

        def close(self) -> None:
            self.close_count += 1

    vault = ephemeral.EphemeralTestSessionVault()
    try:
        _old_sid, _old_csrf, sid, csrf, _status = _seed(vault)
        lease = vault.begin_operation(sid, csrf, module="ewo", filters=None)
        session = OwnedSession()
        vault.promote_authenticated(lease, session, validated_module="ewo")

        vault.clear(sid, csrf)

        assert lease.cancel_requested is True
        assert session.cancel_count == 1
        assert session.close_count == 0
        assert vault.finish_failure(
            lease, preserve_pre_touch_password=False
        ) is True
        assert session.close_count == 1
    finally:
        vault.close()


def test_ewo_then_paa_reuses_one_owned_login_and_terminally_destroys() -> None:
    vault = ephemeral.EphemeralTestSessionVault()
    try:
        _old_sid, _old_csrf, sid, csrf, _status = _seed(vault)
        password_buffer = vault._record.password
        assert password_buffer is not None
        ewo = vault.begin_operation(
            sid, csrf, module="ewo", filters={"ewo_no": "EWO-2"}
        )
        assert ewo.reveal_password() == PASSWORD
        session = OwnedSession()
        vault.promote_authenticated(ewo, session, validated_module="ewo")
        assert password_buffer.reveal() == ""
        assert vault.finish_success(ewo) is False

        paa = vault.begin_operation(
            sid, csrf, module="paa", filters={"project_code": "P100"}
        )
        assert paa.authenticated_session is session
        assert paa.reveal_password() == ""
        assert vault.module_is_validated(paa, "paa") is False
        vault.mark_validated(paa, "paa")
        assert vault.finish_success(paa) is True

        assert session.headers == {}
        assert session.cookies == {}
        assert session.closed is True
        _assert_error("TEST_SESSION_NOT_FOUND", lambda: vault.status(sid, csrf))
    finally:
        vault.close()


def test_close_is_idempotent_and_disables_future_bootstrap() -> None:
    vault = ephemeral.EphemeralTestSessionVault()
    _seed(vault)
    password_buffer = vault._record.password
    assert password_buffer is not None

    vault.close()
    vault.close()

    assert password_buffer.reveal() == ""
    _assert_error("TEST_SESSION_DISABLED", vault.bootstrap)
