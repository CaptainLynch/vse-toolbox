from tests.p1d_frontend_fixture import Scenario, load_policy_panel

DIGEST = 'cfgd1:' + 'a' * 64


def _policy(**extra):
    return {'enabled': True, 'credentialAvailable': True, 'mode': 'auto', 'intervalMinutes': 30, 'matchRule': {}, **extra}


def _panel(policy, fields=None):
    body = {'ok': True, 'data': {**policy, 'configDigest': 'cfgd1:' + 'b' * 64}}
    if fields is not None:
        body = {'ok': False, 'error': {'message': 'rejected', 'fields': fields}}
    panel = load_policy_panel(Scenario(
        policy=policy, settings={'credentialVaultConfigured': True}, discovery={},
        inputs={'mode': 'auto', 'intervalMinutes': 47},
        responses=[{'method': 'PATCH', 'path': '/update-policy',
                    'status': 200 if fields is None else 422, 'body': body}],
    ))
    panel.result.assert_ok()
    assert [r.method for r in panel.requests] == ['GET', 'GET', 'GET', 'PATCH']
    return panel


def test_editor_save_uses_loaded_digest_and_inputs():
    for digest in (DIGEST, ' ' + DIGEST.upper() + ' '):
        panel = _panel(_policy(configDigest=digest))
        assert panel.patches[-1].body == {
            'enabled': True, 'mode': 'auto', 'intervalMinutes': 47,
            'credentialRef': '', 'externalKey': '', 'matchRule': {}, 'expectedConfigDigest': digest,
        }


def test_editor_absent_digest_is_omitted():
    for extra in ({}, {'configDigest': None}, {'configDigest': ''}):
        panel = _panel(_policy(**extra))
        assert 'expectedConfigDigest' not in panel.patches[-1].body


def test_editor_success_has_one_patch_and_no_extra_get():
    panel = _panel(_policy(configDigest=DIGEST))
    assert panel.patches[-1].status == 200
    assert panel.patches[-1].body['expectedConfigDigest'] == DIGEST


def test_editor_rejections_have_one_patch_and_no_extra_get():
    for fields in ({'expectedConfigDigest': '过期'}, {'request': '绑定已发生变化，请刷新配置后重试'}, {'request': '包含不允许修改的字段'}):
        panel = _panel(_policy(configDigest=DIGEST), fields)
        assert panel.patches[-1].status == 422
        assert panel.patches[-1].body['expectedConfigDigest'] == DIGEST
