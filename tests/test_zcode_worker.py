import importlib
import json

import pytest


def module():
    return importlib.import_module('tools.agents.zcode_worker')


def test_rejects_unapproved_model_before_reading_credentials(tmp_path):
    with pytest.raises(ValueError, match='allowlist'):
        module().load_runtime({'model': 'wrong', 'allowed_models': ['good'],
                               'provider_config': str(tmp_path / 'absent')})


def test_load_runtime_caps_provider_context_to_one_million_tokens(tmp_path):
    provider_file = tmp_path / 'provider.json'
    provider_file.write_text(json.dumps({
        'provider': {
            'p': {
                'enabled': True,
                'kind': 'openai-compatible',
                'models': {
                    'gemini-test': {
                        'limit': {'context': 1_000_000, 'output': 128_000},
                        'reasoning': {'enabled': True, 'variants': ['high'], 'defaultVariant': 'high'},
                    },
                },
                'options': {'apiKey': 'test-key', 'baseURL': 'http://example.invalid'},
            },
        },
    }), encoding='utf-8')
    runtime = module().load_runtime({
        'model': 'gemini-test',
        'allowed_models': ['gemini-test'],
        'provider_id': 'p',
        'provider_config': str(provider_file),
        'max_output_tokens': 32_768,
        'safety_reserve_tokens': 16_384,
    })
    selected = runtime['provider']['models'][0]
    assert selected['contextWindow'] == 1_000_000
    assert selected['maxOutputTokens'] == 32_768
    assert selected['contextBudget']['max_input_tokens'] == 950_848


def test_load_runtime_supports_explicit_anthropic_messages_provider(tmp_path):
    provider_file = tmp_path / 'provider.json'
    provider_file.write_text(json.dumps({
        'provider': {
            'p': {
                'enabled': True,
                'kind': 'anthropic',
                'models': {
                    'GLM-5.3-Flash': {
                        'limit': {'context': 1_000_000, 'output': 128_000},
                        'reasoning': {'enabled': True, 'variants': ['high'], 'defaultVariant': 'high'},
                    },
                },
                'options': {'apiKey': 'test-key', 'baseURL': 'https://example.invalid/anthropic'},
            },
        },
    }), encoding='utf-8')

    runtime = module().load_runtime({
        'model': 'GLM-5.3-Flash',
        'allowed_models': ['GLM-5.3-Flash'],
        'provider_id': 'p',
        'provider_config': str(provider_file),
        'max_output_tokens': 32_768,
        'safety_reserve_tokens': 16_384,
    })

    assert runtime['provider']['kind'] == 'anthropic'
    assert runtime['provider']['apiFormat'] == 'anthropic-messages'
    assert runtime['provider']['models'][0]['contextWindow'] == 1_000_000


def test_load_runtime_honors_requested_thinking_level_when_provider_supports_it(tmp_path):
    provider_file = tmp_path / 'provider.json'
    provider_file.write_text(json.dumps({
        'provider': {
            'p': {
                'enabled': True,
                'kind': 'openai-compatible',
                'models': {
                    'gemini-test': {
                        'limit': {'context': 272_000},
                        'reasoning': {
                            'enabled': True,
                            'variants': ['low', 'medium', 'high'],
                            'defaultVariant': 'high',
                        },
                    },
                },
                'options': {'apiKey': 'test-key', 'baseURL': 'http://example.invalid'},
            },
        },
    }), encoding='utf-8')
    runtime = module().load_runtime({
        'model': 'gemini-test',
        'allowed_models': ['gemini-test'],
        'provider_id': 'p',
        'provider_config': str(provider_file),
        'thinking_level': 'medium',
    })
    assert runtime['thoughtLevel'] == 'medium'
    assert runtime['provider']['models'][0]['reasoning']['defaultLevel'] == 'medium'


def test_worker_limits_allow_one_million_token_gemini_context_without_quota_budget():
    limits = module().resolve_worker_limits({
        'context_window_tokens': 1_000_000,
        'max_output_tokens': 32_768,
        'safety_reserve_tokens': 16_384,
        'max_model_turns': 64,
        'max_tool_calls': 256,
    })
    assert limits['context_budget']['context_window_tokens'] == 1_000_000
    assert limits['context_budget']['max_input_tokens'] == 950_848
    assert limits['max_model_turns'] == 64
    assert limits['max_tool_calls'] == 256


def test_preflight_runtime_returns_safe_model_and_context_summary(tmp_path):
    provider_file = tmp_path / 'provider.json'
    provider_file.write_text(json.dumps({
        'provider': {
            'p': {
                'enabled': True,
                'kind': 'openai-compatible',
                'models': {'gemini-test': {'limit': {'context': 1_000_000}}},
                'options': {'apiKey': 'test-key', 'baseURL': 'http://example.invalid'},
            },
        },
    }), encoding='utf-8')
    result = module().preflight_runtime({
        'model': 'gemini-test',
        'allowed_models': ['gemini-test'],
        'provider_id': 'p',
        'provider_config': str(provider_file),
    })
    assert result['status'] == 'passed'
    assert result['model_id'] == 'gemini-test'
    assert result['context_budget']['context_window_tokens'] == 1_000_000
    assert result['permission_checks'] == {
        'Read': True,
        'Grep': True,
        'Glob': True,
    }
    assert 'apiKey' not in json.dumps(result)


def test_preflight_runtime_rejects_provider_window_below_one_million_tokens(tmp_path):
    provider_file = tmp_path / 'provider.json'
    provider_file.write_text(json.dumps({
        'provider': {
            'p': {
                'enabled': True,
                'kind': 'openai-compatible',
                'models': {'gemini-test': {'limit': {'context': 200_000}}},
                'options': {'apiKey': 'test-key', 'baseURL': 'http://example.invalid'},
            },
        },
    }), encoding='utf-8')
    with pytest.raises(ValueError, match='1000000'):
        module().preflight_runtime({
            'model': 'gemini-test',
            'allowed_models': ['gemini-test'],
            'provider_id': 'p',
            'provider_config': str(provider_file),
        })


def test_build_worker_prompt_explains_context_guard_without_gemini_quota_cap():
    prompt = module().build_worker_prompt(
        {
            'task_id': 'TASK-PROMPT',
            'objective': 'Implement the bounded change',
            'scope': ['src/example.py'],
        },
        {
            'context_budget': {
                'context_window_tokens': 1_000_000,
                'max_input_tokens': 950_848,
            },
            'max_model_turns': 64,
            'max_tool_calls': 256,
        },
    )
    assert '1000000' in prompt
    assert '950848' in prompt
    assert '64' in prompt
    assert '256' in prompt
    assert 'Do not claim you ran verification_commands' in prompt
    assert 'Gemini quota' not in prompt


def test_worker_budget_exceeded_only_after_operational_limit_is_crossed():
    limits = {'max_model_turns': 64, 'max_tool_calls': 256}
    assert module().worker_budget_exceeded({'model_turns': 64, 'tool_calls': 256}, limits) is False
    assert module().worker_budget_exceeded({'model_turns': 65, 'tool_calls': 256}, limits) is True
    assert module().worker_budget_exceeded({'model_turns': 64, 'tool_calls': 257}, limits) is True


def test_build_preflight_params_disable_all_tools_and_use_plan_mode(tmp_path):
    runtime = {
        'model': {'providerId': 'provider', 'modelId': 'gemini-test'},
    }
    params = module().build_preflight_params(runtime, tmp_path)
    assert params['mode'] == 'plan'
    assert params['toolAllowlist'] == []
    assert set(params['toolDenylist']) >= {'Read', 'Grep', 'Glob', 'Edit', 'Write', 'Bash', 'Agent'}
    assert params['workspace']['workspacePath'] == str(tmp_path.resolve())
    assert params['runtimeModel']['model'] == runtime['model']
    assert 'contextBudget' not in params['runtimeModel']


def test_protocol_runtime_strips_internal_budget_metadata():
    runtime = {
        'model': {'providerId': 'provider', 'modelId': 'gemini-test'},
        'contextBudget': {'context_window_tokens': 1_000_000},
        'provider': {
            'models': [{'modelId': 'gemini-test', 'contextWindow': 1_000_000,
                        'contextBudget': {'max_input_tokens': 950_848},
                        'thinkingLevel': 'low'}],
        },
    }
    protocol = module().protocol_runtime(runtime)
    assert 'contextBudget' not in protocol
    assert 'contextBudget' not in protocol['provider']['models'][0]
    assert 'thinkingLevel' not in protocol['provider']['models'][0]
    assert protocol['provider']['models'][0]['contextWindow'] == 1_000_000
    assert runtime['contextBudget']['context_window_tokens'] == 1_000_000


def test_host_rpc_response_completes_runtime_and_provider_handshakes():
    worker = module()
    runtime = {
        'revision': 'runtime-revision',
        'model': {'providerId': 'provider', 'modelId': 'GLM-5.3-Flash'},
    }

    preferences = worker.host_rpc_response(
        'session/requestRuntimePreferences',
        {'scope': 'runtime-materialization'},
        runtime=runtime,
    )
    assert preferences == {
        'nativeSearchEnhancementsEnabled': True,
        'memoryEnabled': False,
        'askUserQuestionAutoResolutionEnabled': True,
        'modelContextBudgetStrategy': 'preflight-v1',
    }

    headers = worker.host_rpc_response(
        'interaction/requestProviderRuntimeHeaders',
        {
            'providerId': 'provider',
            'modelRef': {'providerId': 'provider', 'modelId': 'GLM-5.3-Flash'},
        },
        runtime=runtime,
    )
    assert headers == {
        'headersApplied': False,
        'errorMessage': 'Provider runtime headers require an interactive host and are unavailable in the bounded worker',
    }
    assert worker.host_rpc_response('unknown/method', {}, runtime=runtime) is None


def test_host_rpc_response_rejects_headers_for_a_different_model():
    result = module().host_rpc_response(
        'interaction/requestProviderRuntimeHeaders',
        {
            'providerId': 'other-provider',
            'modelRef': {'providerId': 'other-provider', 'modelId': 'other-model'},
        },
        runtime={'model': {'providerId': 'provider', 'modelId': 'model'}},
    )

    assert result['headersApplied'] is False
    assert 'does not match' in result['errorMessage']


@pytest.mark.parametrize('stall', [False, True])
def test_network_preflight_completes_one_no_tool_session(monkeypatch, tmp_path, stall):
    worker = module()
    runtime = {
        'model': {'providerId': 'provider', 'modelId': 'gemini-test'},
        'provider': {'apiKey': {'value': 'test-key'}},
    }
    calls = []

    class FakeRpc:
        cleanup_complete = True

        def __init__(self, command, cwd, env, timeout):
            calls.append(('init', command, cwd, timeout))

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def request(self, method, params, handler, timeout=40):
            calls.append((method, params))
            if method == 'session/create':
                return {
                    'session': {'sessionId': 'probe-session'},
                    'settings': {
                        'model': {'current': runtime['model']},
                        'permission': {'mode': 'plan'},
                    },
                }
            if method == 'session/send':
                if stall:
                    raise TimeoutError('Worker deadline exceeded')
                handler({
                    'method': 'session/event',
                    'params': {
                        'sessionId': 'probe-session',
                        'type': 'turn.completed',
                        'payload': {'resultType': 'success', 'usage': {'input_tokens': 4}},
                    },
                })
            return {}

    monkeypatch.setattr(worker, 'load_runtime', lambda config: runtime)
    monkeypatch.setattr(worker, 'build_command', lambda config: ['fake-node', 'zcode.cjs', 'app-server'])
    monkeypatch.setattr(worker, 'RpcProcess', FakeRpc)
    if stall:
        with pytest.raises(TimeoutError, match='stage=session/send.*timeout_seconds=60'):
            worker.network_preflight({'preflight_retries': 0}, tmp_path)
        return
    result = worker.network_preflight(
        {'node_executable': 'fake-node', 'cli_entry': 'zcode.cjs', 'model': 'gemini-test'},
        tmp_path,
    )
    assert result['status'] == 'passed'
    assert result['model_id'] == 'gemini-test'
    assert result['tool_call_count'] == 0
    assert result['usage'] == {'input_tokens': 4}
    assert calls[0][3] == 60
    assert result['timings_seconds']['session/create'] >= 0
    assert result['timeout_seconds'] == 60
    create = next(item for item in calls if item[0] == 'session/create')
    assert create[1]['toolAllowlist'] == []
    assert sum(1 for item in calls if item[0] == 'session/send') == 1


def test_invoke_passes_one_million_token_runtime_and_records_usage(monkeypatch, tmp_path):
    worker = module()
    runtime = {
        'model': {'providerId': 'provider', 'modelId': 'gemini-test'},
        'provider': {
            'apiKey': {'value': 'test-key'},
            'models': [{
                'contextWindow': 1_000_000,
                'maxOutputTokens': 32_768,
                'contextBudget': {
                    'context_window_tokens': 1_000_000,
                    'max_output_tokens': 32_768,
                    'safety_reserve_tokens': 16_384,
                    'max_input_tokens': 950_848,
                },
            }],
        },
        'contextBudget': {
            'context_window_tokens': 1_000_000,
            'max_output_tokens': 32_768,
            'safety_reserve_tokens': 16_384,
            'max_input_tokens': 950_848,
        },
    }
    captured = []

    class FakeRpc:
        cleanup_complete = True

        def __init__(self, command, cwd, env, timeout):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def send(self, value):
            pass

        def request(self, method, params, handler, timeout=40):
            captured.append((method, params))
            if method == 'session/create':
                return {
                    'session': {'sessionId': 'worker-session'},
                    'settings': {
                        'model': {'current': runtime['model']},
                        'permission': {'mode': 'build'},
                    },
                }
            if method == 'session/send':
                handler({
                    'method': 'session/event',
                    'params': {
                        'sessionId': 'worker-session',
                        'type': 'turn.completed',
                        'payload': {
                            'resultType': 'success',
                            'response': json.dumps({
                                'task_id': 'TASK-INVOKE-BUDGET', 'status': 'completed',
                                'summary': 'done', 'changed_files': [], 'tests': [],
                                'commands_executed': [], 'risks': [], 'unresolved': [],
                                'needs_review': True,
                            }),
                            'usage': {'input_tokens': 10, 'output_tokens': 2},
                            'toolCallCount': 0,
                        },
                    },
                })
            return {}

    monkeypatch.setattr(worker, 'verify_guard', lambda worktree: None)
    monkeypatch.setattr(worker, 'load_runtime', lambda config: runtime)
    monkeypatch.setattr(worker, 'build_command', lambda config: ['fake-node', 'zcode.cjs', 'app-server'])
    monkeypatch.setattr(worker, 'RpcProcess', FakeRpc)
    result = worker.invoke(
        {
            'task_id': 'TASK-INVOKE-BUDGET',
            'scope': [],
            'objective': 'bounded task',
        },
        tmp_path,
        tmp_path / 'run',
        {
            'model': 'gemini-test',
            'provider_id': 'provider',
            'allowed_models': ['gemini-test'],
            'max_output_tokens': 32_768,
            'safety_reserve_tokens': 16_384,
        },
    )
    assert result['status'] == 'completed'
    assert result['process']['usage'] == {'input_tokens': 10, 'output_tokens': 2}
    assert result['process']['context_waterline'] == 'green'
    create = next(item for item in captured if item[0] == 'session/create')
    assert create[1]['runtimeModel']['provider']['models'][0]['contextWindow'] == 1_000_000
    send = next(item for item in captured if item[0] == 'session/send')
    assert '1000000' in send[1]['content']


def test_usage_budget_detects_input_overflow_but_allows_cached_tokens():
    budget = {'max_input_tokens': 222_848}
    assert module().usage_budget_exceeded({'input_tokens': 222_848}, budget) is False
    assert module().usage_budget_exceeded({'prompt_tokens': 222_849}, budget) is True
    assert module().usage_budget_exceeded({'cached_input_tokens': 999_999}, budget) is False


def test_scope_rejects_escape_and_control_paths(tmp_path):
    check = module().in_scope
    assert check(tmp_path, ['src'], 'src/good.py')
    assert not check(tmp_path, ['src'], '../outside.py')
    assert not check(tmp_path, ['src'], 'src/../../outside.py')
    assert not check(tmp_path, ['.'], '.git/config')
    assert not check(tmp_path, ['.'], '.zcode/config.json')
    assert not check(tmp_path, ['.'], 'AGENTS.md')


def test_scope_rejects_symlink_outside(tmp_path):
    outside = tmp_path.parent / (tmp_path.name + '-outside')
    outside.mkdir()
    try:
        (tmp_path / 'link').symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip('symlink unavailable')
    assert not module().in_scope(tmp_path, ['link'], 'link/file.py')


def test_permission_only_allows_owned_native_edits(tmp_path):
    decide = module().permission_decision
    assert decide('Write', {'file_path': str(tmp_path / 'ok.py')}, tmp_path, ['ok.py'], False)['decision'] == 'allow'
    assert decide('Write', {'file_path': str(tmp_path / 'other.py')}, tmp_path, ['ok.py'], False)['decision'] == 'deny'
    assert decide('Bash', {'command': 'echo test'}, tmp_path, ['.'], False)['decision'] == 'deny'
    assert decide('Write', {'file_path': str(tmp_path / 'ok.py')}, tmp_path, ['ok.py'], True)['decision'] == 'deny'


@pytest.mark.parametrize('tool', ['Read', 'Grep', 'Glob'])
def test_permission_allows_in_scope_native_reads(tool, tmp_path):
    decision = module().permission_decision(
        tool,
        {'file_path': str(tmp_path / 'src' / 'good.py')},
        tmp_path,
        ['src'],
        False,
    )
    assert decision['decision'] == 'allow'


def test_permission_allows_camel_case_file_path_from_app_server(tmp_path):
    # The app-server may encode native tool input with camelCase keys.
    decision = module().permission_decision(
        'Read',
        {'filePath': str(tmp_path / 'src' / 'good.py')},
        tmp_path,
        ['src'],
        False,
    )
    assert decision['decision'] == 'allow'


def test_permission_denies_read_outside_declared_read_scope(tmp_path):
    decision = module().permission_decision(
        'Read',
        {'file_path': str(tmp_path / 'secret.txt')},
        tmp_path,
        ['src'],
        False,
    )
    assert decision['decision'] == 'deny'


def test_context_budget_allows_one_million_provider_window_and_reserves_output():
    budget = module().resolve_context_budget({
        'context_window_tokens': 1_000_000,
        'max_output_tokens': 32_768,
        'safety_reserve_tokens': 16_384,
    })
    assert budget == {
        'context_window_tokens': 1_000_000,
        'max_output_tokens': 32_768,
        'safety_reserve_tokens': 16_384,
        'max_input_tokens': 950_848,
    }


@pytest.mark.parametrize('tokens,expected', [
    (760_678, 'green'),
    (760_679, 'yellow'),
    (903_305, 'yellow'),
    (903_306, 'red'),
    (950_848, 'red'),
    (950_849, 'hard-stop'),
])
def test_one_million_token_worker_waterline_boundaries(tokens, expected):
    assert module().context_waterline(tokens, {'max_input_tokens': 950_848}) == expected


@pytest.mark.parametrize('tokens,expected', [
    (178_278, 'green'),
    (178_279, 'yellow'),
    (211_705, 'yellow'),
    (211_706, 'red'),
    (222_848, 'red'),
    (222_849, 'hard-stop'),
])
def test_context_waterline_is_deterministic(tokens, expected):
    assert module().context_waterline(tokens, {'max_input_tokens': 222_848}) == expected


def test_bound_text_keeps_head_and_tail_with_omission_marker():
    value = module().bound_text('HEAD-' + ('x' * 100) + '-TAIL', 32)
    assert value.startswith('HEAD-')
    assert value.endswith('-TAIL')
    assert '[... omitted ...]' in value


def test_make_handoff_is_compact_and_does_not_include_raw_diagnostics():
    result = {
        'task_id': 'TASK-handoff',
        'status': 'completed',
        'summary': 'done ' + ('summary ' * 1000),
        'changed_files': [f'src/file-{n}.py' for n in range(100)],
        'tests': [],
        'commands_executed': [],
        'risks': ['risk ' + ('x' * 2000)],
        'unresolved': ['unresolved ' + ('y' * 2000)],
        'needs_review': True,
        'process': {
            'usage': {'input_tokens': 217_601, 'cached_input_tokens': 100_000, 'output_tokens': 12},
            'context_budget': {'max_input_tokens': 222_848},
        },
    }
    handoff = module().make_handoff(
        {'task_id': 'TASK-handoff'},
        result,
        model_id='gemini-3.8-flash-high',
        base_commit='abc123',
        diff_stat={'files': 1, 'insertions': 2, 'deletions': 0},
        checks=[{'command': ['python', '-m', 'pytest'], 'exit_code': 0, 'duration_seconds': 1.2,
                 'stdout': 'secret raw output ' + ('z' * 5000), 'stderr': ''}],
    )
    assert handoff['schema_version'] == 'handoff.v1'
    assert handoff['task_id'] == 'TASK-handoff'
    assert len(handoff['changed_files']) == 50
    assert len(handoff['risks'][0]) <= 400
    assert len(handoff['unresolved'][0]) <= 400
    assert handoff['runtime']['context_waterline'] == 'red'
    assert handoff['usage']['input_tokens'] == 217_601
    assert 'secret raw output' not in json.dumps(handoff)
    assert len(json.dumps(handoff, ensure_ascii=False)) <= 16_384


def test_validate_handoff_enforces_v1_shape_and_one_million_token_limit():
    handoff = module().make_handoff(
        {'task_id': 'TASK-HANDOFF-VALIDATE'},
        {
            'task_id': 'TASK-HANDOFF-VALIDATE', 'status': 'completed', 'summary': 'done',
            'changed_files': [], 'risks': [], 'unresolved': [],
        },
        model_id='gemini-3.8-flash-high',
    )
    assert module().validate_handoff(handoff) is True
    handoff['runtime']['context_limit_tokens'] = 272_000
    with pytest.raises(ValueError, match='1000000'):
        module().validate_handoff(handoff)


@pytest.mark.parametrize('message,write_seen,expected', [
    ('429 too_many_requests', False, (True, 'rate-limit')),
    ('503 service unavailable', False, (True, 'transport')),
    ('504 gateway timeout', False, (True, 'transport')),
    ('Worker deadline exceeded', False, (True, 'transport')),
    ('429 quota_exceeded', False, (False, 'quota')),
    ('401 unauthorized', False, (False, 'authentication')),
    ('504 gateway timeout', True, (False, 'uncertain-write')),
])
def test_retry_policy_respects_error_class_and_write_side_effects(message, write_seen, expected):
    decision = module().retry_decision(message, write_seen=write_seen)
    assert (decision['retryable'], decision['failure_code']) == expected


def test_retry_delay_uses_full_jitter_and_retry_after_floor():
    assert module().calculate_retry_delay(0, random_value=0.5) == 0.5
    assert module().calculate_retry_delay(1, random_value=0.5) == 1.0
    assert module().calculate_retry_delay(1, retry_after=3.0, random_value=0.0) == 3.0


def test_retry_operation_retries_transient_failures_with_a_bounded_budget():
    attempts = []
    sleeps = []

    def operation():
        attempts.append(len(attempts) + 1)
        if len(attempts) < 3:
            raise RuntimeError('503 service unavailable')
        return 'ok'

    assert module().retry_operation(
        operation,
        max_retries=3,
        sleep_func=sleeps.append,
        random_source=lambda: 0.0,
    ) == 'ok'
    assert attempts == [1, 2, 3]
    assert sleeps == [0.0, 0.0]


def test_retry_operation_does_not_repeat_an_uncertain_write():
    attempts = []

    def operation():
        attempts.append(1)
        raise RuntimeError('504 gateway timeout')

    with pytest.raises(RuntimeError, match='504'):
        module().retry_operation(operation, write_seen=True, sleep_func=lambda _: None)
    assert len(attempts) == 1


def test_retry_operation_stops_when_total_backoff_budget_is_exhausted():
    attempts = []
    sleeps = []

    def operation():
        attempts.append(1)
        raise RuntimeError('503 service unavailable Retry-After: 1')

    with pytest.raises(RuntimeError, match='503'):
        module().retry_operation(
            operation,
            max_retries=3,
            total_delay_budget=1.0,
            sleep_func=sleeps.append,
            random_source=lambda: 0.0,
        )
    assert len(attempts) == 2
    assert sleeps == [1.0]


def test_early_protocol_completion_is_not_model_completion():
    event = {'method': 'state.updated', 'params': {'reason': 'prompt_completed'}}
    assert module().terminal_event(event, 's') is None
    real = {'method': 'session/event', 'params': {'sessionId': 's', 'type': 'turn.completed', 'payload': {'response': 'ok'}}}
    assert module().terminal_event(real, 's') == ('turn.completed', {'response': 'ok'})
    assert module().terminal_event(real, 'other') is None


def test_result_validates_all_field_types():
    result = {'task_id': 'TASK-t', 'status': 'completed', 'summary': 'ok',
              'changed_files': [], 'tests': [], 'commands_executed': [],
              'risks': [], 'unresolved': [], 'needs_review': True}
    assert module().parse_result(json.dumps(result), 'TASK-t')['status'] == 'completed'
    result['changed_files'] = 'wrong'
    with pytest.raises(ValueError):
        module().parse_result(json.dumps(result), 'TASK-t')
    with pytest.raises(ValueError):
        module().parse_result('looks successful', 'TASK-t')


@pytest.mark.parametrize('message,expected', [
    ('HTTP 429 quota exhausted', 'quota'), ('401 unauthorized', 'authentication'),
    ('HTTP 429 too_many_requests', 'rate-limit'),
    ('403 forbidden', 'authentication'), ('model unavailable', 'model'),
    ('connection reset', 'transport'),
])
def test_failure_classification(message, expected):
    assert module().classify_error(message) == expected


def test_process_timeout_stops_descendant(tmp_path):
    import os
    import sys
    import time
    from tools.agents.zcode_process import RpcProcess
    child = "import time; from pathlib import Path; time.sleep(2); Path('escaped.txt').write_text('bad')"
    parent = "import subprocess,sys,time,json; subprocess.Popen([sys.executable,'-c',sys.argv[1]]); print(json.dumps({'ready':True}),flush=True); time.sleep(30)"
    with RpcProcess([sys.executable, '-c', parent, child], tmp_path, os.environ.copy(), 0.7) as rpc:
        assert rpc.receive()['ready'] is True
        with pytest.raises(TimeoutError):
            rpc.receive()
    time.sleep(2.2)
    assert not (tmp_path / 'escaped.txt').exists()
    assert rpc.process.poll() is not None


def test_rpc_rejects_error_without_silent_retry(tmp_path):
    import os
    import sys
    from tools.agents.zcode_process import RpcProcess, ProtocolError
    code = "import sys,json; x=json.loads(sys.stdin.readline()); print(json.dumps({'id':x['id'],'error':{'message':'model unavailable'}}),flush=True); sys.stdin.readline()"
    with RpcProcess([sys.executable, '-c', code], tmp_path, os.environ.copy(), 5) as rpc:
        with pytest.raises(ProtocolError, match='model unavailable'):
            rpc.request('session/create', {}, lambda _: None)
        assert rpc.sequence == 1


def test_guard_rejects_outside_edit_and_shell(tmp_path):
    from tools.agents.zcode_guard import check_tool
    contract = {'root': str(tmp_path), 'scope': ['ok.py'], 'readonly': False}
    assert check_tool({'tool_name': 'Write', 'tool_input': {'file_path': str(tmp_path / 'ok.py')}}, contract)
    assert not check_tool({'tool_name': 'Edit', 'tool_input': {'file_path': str(tmp_path / 'other.py')}}, contract)
    assert not check_tool({'tool_name': 'Bash', 'tool_input': {'command': 'pwd'}}, contract)
    assert not check_tool({'tool_name': 'Read', 'tool_input': {'file_path': '../secret'}}, contract)
    assert not check_tool({'tool_name': 'Write', 'tool_input': {'file_path': 'ok.py:stream'}}, contract)


def test_guard_blocks_renamed_patch_outside_scope(tmp_path):
    from tools.agents.zcode_guard import check_tool
    contract = {'root': str(tmp_path), 'scope': ['ok.py'], 'readonly': False}
    event = {'tool_name': 'ApplyPatch', 'tool_input': {'patch': '*** Update File: ok.py\n*** Move to: ../bad.py\n'}}
    assert not check_tool(event, contract)


def test_control_aliases_are_blocked(tmp_path):
    for name in ('zcode.json', '.env.local', '.env.production', '.claude/settings.json', '.gemini/settings.json'):
        assert not module().in_scope(tmp_path, ['.'], name)


def test_one_line_fence_is_a_structured_parse_error():
    with pytest.raises(ValueError):
        module().parse_result('```{"task_id":"TASK-t"}```', 'TASK-t')


def test_model_change_is_classified_as_blocked_model():
    assert module().classify_error('Model changed during worker turn') == 'model'
    assert module().failure('TASK-t', 'model')['status'] == 'blocked'


def test_worker_worktree_uses_codex_branch_prefix(tmp_path):
    import subprocess
    from tools.agents import git_worktree
    subprocess.run(['git', 'init', str(tmp_path)], check=True, capture_output=True)
    subprocess.run(['git', '-c', 'user.name=Test', '-c', 'user.email=test@localhost',
                    'commit', '--allow-empty', '-m', 'baseline'], cwd=tmp_path, check=True, capture_output=True)
    tree = git_worktree.create(tmp_path, 'TASK-prefix')
    branch = subprocess.run(['git', 'branch', '--show-current'], cwd=tree, check=True,
                            capture_output=True, text=True).stdout.strip()
    assert branch == 'codex/TASK-prefix'
