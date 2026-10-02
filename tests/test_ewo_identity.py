from datetime import timedelta

import pytest

from core.domain_identity import DomainSessionRegistry


ROOT = 'https://example.test/innovatorserver'


def test_scope_stable_for_same_account_and_source_but_isolated():
    registry = DomainSessionRegistry()
    first = object()
    registry.mark_authenticated('aras', first, principal='alice', source_root=ROOT)
    session, scope = registry.bound_session('aras', ROOT + '/')
    assert session is first
    registry.mark_authenticated('aras', object(), principal='alice', source_root=ROOT)
    assert registry.bound_session('aras', ROOT)[1] == scope
    registry.mark_authenticated('aras', object(), principal='bob', source_root=ROOT)
    assert registry.bound_session('aras', ROOT)[1] != scope
    assert registry.bound_session('aras', ROOT.replace('https:', 'http:')) is None
    assert registry.bound_session('aras', ROOT + '/other') is None
    assert 'bob' not in str(registry.payload())


def test_legacy_status_cannot_inherit_prior_bound_session():
    registry = DomainSessionRegistry()
    registry.mark_authenticated('aras', object(), principal='alice', source_root=ROOT)
    registry.mark_authenticated('aras')
    assert registry.bound_session('aras', ROOT) is None
    assert registry.session('aras') is None


def test_expired_and_cleared_sessions_cannot_resume():
    registry = DomainSessionRegistry(ttl=timedelta(seconds=-1))
    registry.mark_authenticated('aras', object(), principal='alice', source_root=ROOT)
    assert registry.bound_session('aras', ROOT) is None
    registry = DomainSessionRegistry()
    registry.mark_authenticated('aras', object(), principal='alice', source_root=ROOT)
    registry.clear('aras')
    assert registry.bound_session('aras', ROOT) is None


@pytest.mark.parametrize('root', ['https://user:pass@example.test/app',
                                  'https://example.test/app?token=secret', 'relative'])
def test_invalid_binding_not_published(root):
    registry = DomainSessionRegistry()
    with pytest.raises(ValueError):
        registry.mark_authenticated('aras', object(), principal='alice', source_root=root)
    assert registry.session('aras') is None
