"""ZCode app-server worker. Explicit model, bounded native tools, no paid fallback."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import random
import re
import time
import uuid
from pathlib import Path
from typing import Any

try:
    from .zcode_process import ProtocolError, RpcProcess
    from .zcode_guard import in_scope, tool_decision
except ImportError:
    from zcode_process import ProtocolError, RpcProcess
    from zcode_guard import in_scope, tool_decision

READ_TOOLS = ['Read', 'Grep', 'Glob']
WRITE_TOOLS = ['Edit', 'Write']
MAX_CONTEXT_TOKENS = 1_000_000
DEFAULT_MAX_OUTPUT_TOKENS = 32_768
DEFAULT_SAFETY_RESERVE_TOKENS = 16_384
GREEN_WATERLINE_RATIO = 0.80
YELLOW_WATERLINE_RATIO = 0.95
DEFAULT_MAX_MODEL_TURNS = 64
DEFAULT_MAX_TOOL_CALLS = 256
DEFAULT_MAX_TOOL_OUTPUT_CHARS = 32_768
SUPPORTED_PROVIDER_API_FORMATS = {
    'anthropic': 'anthropic-messages',
    'openai-compatible': 'openai-chat-completions',
}
RUNTIME_PREFERENCES_METHOD = 'session/requestRuntimePreferences'
PROVIDER_RUNTIME_HEADERS_METHOD = 'interaction/requestProviderRuntimeHeaders'


def resolve_context_budget(config: dict[str, Any]) -> dict[str, int]:
    """Return a conservative effective budget for every non-Codex worker."""
    provider_window = int(config.get('context_window_tokens', MAX_CONTEXT_TOKENS))
    max_output = int(config.get('max_output_tokens', DEFAULT_MAX_OUTPUT_TOKENS))
    safety_reserve = int(config.get('safety_reserve_tokens', DEFAULT_SAFETY_RESERVE_TOKENS))
    context_window = min(provider_window, MAX_CONTEXT_TOKENS)
    if context_window <= 0 or max_output <= 0 or safety_reserve < 0:
        raise ValueError('Context budget values must be positive')
    max_input = context_window - max_output - safety_reserve
    if max_input <= 0:
        raise ValueError('Context budget leaves no input capacity')
    return {
        'context_window_tokens': context_window,
        'max_output_tokens': max_output,
        'safety_reserve_tokens': safety_reserve,
        'max_input_tokens': max_input,
    }


def resolve_worker_limits(config: dict[str, Any]) -> dict[str, Any]:
    """Resolve operational guards without imposing a total Gemini token quota."""
    context_budget = resolve_context_budget(config)
    max_turns = int(config.get('max_model_turns', DEFAULT_MAX_MODEL_TURNS))
    max_tool_calls = int(config.get('max_tool_calls', DEFAULT_MAX_TOOL_CALLS))
    max_tool_output = int(config.get('max_tool_output_chars', DEFAULT_MAX_TOOL_OUTPUT_CHARS))
    if max_turns <= 0 or max_tool_calls <= 0 or max_tool_output <= 0:
        raise ValueError('Worker operational limits must be positive')
    return {
        'context_budget': context_budget,
        'max_model_turns': min(max_turns, 256),
        'max_tool_calls': min(max_tool_calls, 1024),
        'max_tool_output_chars': min(max_tool_output, 131_072),
    }


def worker_budget_exceeded(counters: dict[str, Any], limits: dict[str, Any]) -> bool:
    """Return whether a worker crossed a loop-safety limit."""
    return (
        int(counters.get('model_turns', 0)) > int(limits['max_model_turns'])
        or int(counters.get('tool_calls', 0)) > int(limits['max_tool_calls'])
    )


def usage_budget_exceeded(usage: dict[str, Any], budget: dict[str, Any]) -> bool:
    """Check total input usage; cached input alone is not an overflow signal."""
    for key in ('input_tokens', 'prompt_tokens', 'raw_input_tokens'):
        value = usage.get(key)
        if value is not None:
            return int(value) > int(budget['max_input_tokens'])
    return False


def context_waterline(tokens: int, budget: dict[str, int]) -> str:
    """Classify input usage before the next worker request is sent."""
    limit = int(budget['max_input_tokens'])
    if tokens < 0:
        raise ValueError('Context usage cannot be negative')
    green_limit = min(int(limit * GREEN_WATERLINE_RATIO), limit)
    yellow_limit = min(int(limit * YELLOW_WATERLINE_RATIO), limit)
    if tokens <= green_limit:
        return 'green'
    if tokens <= yellow_limit:
        return 'yellow'
    if tokens <= limit:
        return 'red'
    return 'hard-stop'


def bound_text(value: str, max_chars: int) -> str:
    """Keep both ends of a diagnostic while making omission explicit."""
    if max_chars <= 0:
        raise ValueError('Text bound must be positive')
    if len(value) <= max_chars:
        return value
    marker = '[... omitted ...]'
    if max_chars <= len(marker):
        return marker[:max_chars]
    available = max_chars - len(marker)
    head = (available + 1) // 2
    tail = available - head
    return value[:head] + marker + value[-tail:]


def _handoff_text(value: Any, limit: int = 400) -> str:
    text = str(value)
    text = re.sub(r'(?i)(api[_-]?key|authorization|password|secret|token)\s*[:=]\s*[^\s,;]+',
                  r'\1=[REDACTED]', text)
    text = re.sub(r'https?://[^\s"\']+', '[endpoint]', text)
    return bound_text(text, limit)


def make_handoff(task: dict[str, Any], result: dict[str, Any], *, model_id: str,
                 base_commit: str | None = None, diff_stat: dict[str, Any] | None = None,
                 checks: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Build a bounded, evidence-oriented handoff without raw tool output."""
    changed_files = []
    for path in result.get('changed_files', []):
        value = _handoff_text(path, 512)
        if value not in changed_files:
            changed_files.append(value)
        if len(changed_files) == 50:
            break
    verification = []
    for check in checks or []:
        command = check.get('command', [])
        if not isinstance(command, list):
            command = []
        verification.append({
            'command': [_handoff_text(part, 256) for part in command[:32]],
            'exit_code': check.get('exit_code'),
            'duration_seconds': check.get('duration_seconds'),
        })
    process = result.get('process', {})
    process = process if isinstance(process, dict) else {}
    raw_usage = process.get('usage', {})
    safe_usage = {
        key: int(value) for key, value in raw_usage.items()
        if key in {'input_tokens', 'cached_input_tokens', 'output_tokens', 'reasoning_tokens'}
        and isinstance(value, (int, float))
    } if isinstance(raw_usage, dict) else {}
    runtime_meta: dict[str, Any] = {
        'worker': 'zcode-app-server',
        'model_id': _handoff_text(model_id, 160),
        'context_limit_tokens': MAX_CONTEXT_TOKENS,
    }
    input_tokens = next((safe_usage[key] for key in ('input_tokens', 'prompt_tokens', 'raw_input_tokens') if key in safe_usage), None)
    if input_tokens is not None:
        process_budget = process.get('context_budget')
        budget = process_budget if isinstance(process_budget, dict) and process_budget.get('max_input_tokens') else resolve_context_budget({})
        runtime_meta['context_waterline'] = context_waterline(input_tokens, budget)
    handoff = {
        'schema_version': 'handoff.v1',
        'task_id': task.get('task_id'),
        'status': result.get('status'),
        'summary': _handoff_text(result.get('summary', ''), 800),
        'runtime': runtime_meta,
        'base_commit': _handoff_text(base_commit, 80) if base_commit else None,
        'changed_files': changed_files,
        'diff_stat': {
            'files': int((diff_stat or {}).get('files', len(changed_files)) or 0),
            'insertions': int((diff_stat or {}).get('insertions', 0) or 0),
            'deletions': int((diff_stat or {}).get('deletions', 0) or 0),
        },
        'verification': verification,
        'risks': [_handoff_text(item) for item in result.get('risks', [])[:5]],
        'unresolved': [_handoff_text(item) for item in result.get('unresolved', [])[:5]],
        'next_action': 'Inspect scoped diff and integrate' if result.get('status') == 'completed'
        else 'Resolve the reported worker condition before retrying',
    }
    if safe_usage:
        handoff['usage'] = safe_usage
    serialized = json.dumps(handoff, ensure_ascii=False)
    if len(serialized) > 16_384:
        handoff['summary'] = bound_text(handoff['summary'], 240)
        handoff['risks'] = handoff['risks'][:3]
        handoff['unresolved'] = handoff['unresolved'][:3]
        handoff['verification'] = handoff['verification'][:10]
    return handoff


def validate_handoff(value: dict[str, Any]) -> bool:
    """Validate the bounded handoff contract without third-party dependencies."""
    required = {
        'schema_version', 'task_id', 'status', 'runtime', 'changed_files',
        'diff_stat', 'verification', 'risks', 'unresolved', 'next_action',
    }
    if not isinstance(value, dict) or not required.issubset(value):
        raise ValueError('Invalid handoff fields')
    if value['schema_version'] != 'handoff.v1' or not isinstance(value['task_id'], str):
        raise ValueError('Invalid handoff version or task id')
    if value['status'] not in ('completed', 'partial', 'failed', 'blocked'):
        raise ValueError('Invalid handoff status')
    runtime = value['runtime']
    if not isinstance(runtime, dict) or runtime.get('context_limit_tokens') != MAX_CONTEXT_TOKENS:
        raise ValueError(f'Handoff context limit must be {MAX_CONTEXT_TOKENS}')
    changed_files = value['changed_files']
    if not isinstance(changed_files, list) or len(changed_files) > 50 or not all(
        isinstance(item, str) and len(item) <= 512 for item in changed_files
    ):
        raise ValueError('Invalid handoff changed_files')
    for key, limit in (('risks', 5), ('unresolved', 5), ('verification', 10)):
        items = value[key]
        if not isinstance(items, list) or len(items) > limit:
            raise ValueError(f'Invalid handoff {key}')
    if not isinstance(value['next_action'], str) or len(value['next_action']) > 400:
        raise ValueError('Invalid handoff next_action')
    if len(json.dumps(value, ensure_ascii=False)) > 16_384:
        raise ValueError('Handoff exceeds size limit')
    return True


def permission_decision(tool: str, data: dict, root: Path, scope: list[str],
                        readonly: bool, read_scope: list[str] | None = None) -> dict:
    contract = {'root': str(root), 'scope': scope, 'read_scope': read_scope or scope,
                'readonly': readonly}
    return tool_decision(tool, data, contract)


def terminal_event(message: dict, session_id: str):
    params = message.get('params', {})
    if message.get('method') != 'session/event' or params.get('sessionId') != session_id:
        return None
    if params.get('type') in ('turn.completed', 'turn.failed'):
        return params['type'], params.get('payload', {})
    return None


def host_rpc_response(
    method: str,
    params: dict[str, Any] | None = None,
    *,
    runtime: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Answer the two host callbacks required by the ZCode app-server."""
    params = params if isinstance(params, dict) else {}
    if method == RUNTIME_PREFERENCES_METHOD:
        if params.get('scope') not in {'runtime-materialization', 'user-execution'}:
            return None
        return {
            'nativeSearchEnhancementsEnabled': True,
            'memoryEnabled': False,
            'askUserQuestionAutoResolutionEnabled': True,
            'modelContextBudgetStrategy': 'preflight-v1',
        }
    if method != PROVIDER_RUNTIME_HEADERS_METHOD:
        return None

    selected = runtime.get('model') if isinstance(runtime, dict) else None
    model_ref = params.get('modelRef')
    provider_id = params.get('providerId')
    if (
        not isinstance(selected, dict)
        or not isinstance(model_ref, dict)
        or provider_id != selected.get('providerId')
        or model_ref.get('providerId') != selected.get('providerId')
        or model_ref.get('modelId') != selected.get('modelId')
    ):
        return {
            'headersApplied': False,
            'errorMessage': 'Provider runtime header request does not match the selected model',
        }
    return {
        'headersApplied': False,
        'errorMessage': (
            'Provider runtime headers require an interactive host and are '
            'unavailable in the bounded worker'
        ),
    }


def classify_error(message: str) -> str:
    lower = message.lower()
    if '429' in lower and ('too_many' in lower or 'rate limit' in lower):
        return 'rate-limit'
    if any(word in lower for word in ('429', 'quota', 'rate limit', 'credit', 'exhausted')):
        return 'quota'
    if any(word in lower for word in ('401', '403', 'unauthorized', 'authentication', 'forbidden')):
        return 'authentication'
    if 'model' in lower and any(word in lower for word in ('unavailable', 'not found', 'unsupported', 'allowlist', 'changed', 'mismatch')):
        return 'model'
    return 'transport'


def retry_decision(message: str, *, write_seen: bool = False) -> dict[str, Any]:
    """Classify whether a transport error can be safely retried."""
    lower = message.lower()
    if write_seen and any(marker in lower for marker in (
        '504', 'timeout', 'timed out', 'deadline exceeded', 'connection reset', 'broken pipe',
    )):
        return {'retryable': False, 'failure_code': 'uncertain-write'}
    if 'quota_exceeded' in lower or ('quota' in lower and 'exhaust' in lower):
        return {'retryable': False, 'failure_code': 'quota'}
    if any(marker in lower for marker in ('401', '403', 'unauthorized', 'authentication', 'forbidden')):
        return {'retryable': False, 'failure_code': 'authentication'}
    if '429' in lower and 'quota' not in lower:
        return {'retryable': True, 'failure_code': 'rate-limit'}
    if any(marker in lower for marker in (
        '500', '502', '503', '504', 'timeout', 'timed out', 'deadline exceeded',
        'connection reset', 'broken pipe',
    )):
        return {'retryable': True, 'failure_code': 'transport'}
    return {'retryable': False, 'failure_code': classify_error(message)}


def calculate_retry_delay(attempt: int, *, retry_after: float | None = None,
                          random_value: float = 0.0, base: float = 1.0,
                          cap: float = 20.0) -> float:
    """Calculate capped full-jitter delay, honoring Retry-After as a floor."""
    if attempt < 0 or base <= 0 or cap <= 0:
        raise ValueError('Invalid retry delay parameters')
    random_value = min(1.0, max(0.0, random_value))
    upper = min(cap, base * (2 ** attempt))
    delay = upper * random_value
    if retry_after is not None:
        delay = max(delay, max(0.0, retry_after))
    return min(cap, delay)


def retry_operation(operation, *, max_retries: int = 3, write_seen: bool = False,
                    total_delay_budget: float = 45.0, sleep_func=time.sleep, random_source=None):
    """Retry only safe transient operations with capped full-jitter backoff."""
    if max_retries < 0 or total_delay_budget < 0:
        raise ValueError('Invalid retry budget')
    random_source = random_source or random.random
    attempt = 0
    total_delay = 0.0
    while True:
        try:
            return operation()
        except Exception as exc:
            decision = retry_decision(str(exc), write_seen=write_seen)
            if not decision['retryable'] or attempt >= min(max_retries, 3):
                raise
            retry_after_match = re.search(r'(?i)retry[- ]after\s*[:=]\s*(\d+(?:\.\d+)?)', str(exc))
            retry_after = float(retry_after_match.group(1)) if retry_after_match else None
            delay = calculate_retry_delay(
                attempt,
                retry_after=retry_after,
                random_value=float(random_source()),
            )
            if total_delay + delay > total_delay_budget:
                raise
            sleep_func(delay)
            total_delay += delay
            attempt += 1


def load_runtime(config: dict) -> dict:
    model = config.get('model')
    if not model or model not in config.get('allowed_models', []):
        raise ValueError('Model is not in the explicit allowlist')
    path = Path(config.get('provider_config', str(Path.home() / '.zcode/v2/config.json')))
    providers = json.loads(path.read_text(encoding='utf-8-sig'))['provider']
    provider_id = config['provider_id']
    provider = providers[provider_id]
    provider_kind = str(provider.get('kind', '')).strip().lower()
    if provider.get('enabled') is False or provider_kind not in SUPPORTED_PROVIDER_API_FORMATS:
        raise ValueError('Configured provider is disabled or unsupported')
    if model not in provider.get('models', {}):
        raise ValueError('Model is unavailable in the configured provider')
    options = provider['options']
    if not options.get('apiKey') or not options.get('baseURL'):
        raise ValueError('Provider authentication configuration is incomplete')
    spec = provider['models'][model]
    provider_context = int(spec.get('limit', {}).get('context', 200000))
    budget_config = dict(config)
    budget_config['context_window_tokens'] = min(
        provider_context,
        int(config.get('context_window_tokens', MAX_CONTEXT_TOKENS)),
    )
    budget = resolve_context_budget(budget_config)
    selected = {'modelId': model, 'contextWindow': budget['context_window_tokens'],
                'maxOutputTokens': budget['max_output_tokens'], 'contextBudget': budget,
                'supportsTools': True}
    reasoning = spec.get('reasoning', {})
    requested_thinking = str(config.get('thinking_level', '')).strip().lower()
    if reasoning.get('enabled') and reasoning.get('variants'):
        variants = [str(value).strip().lower() for value in reasoning['variants'] if str(value).strip()]
        default_level = requested_thinking or str(reasoning.get('defaultVariant', variants[0])).strip().lower()
        if default_level not in variants:
            raise ValueError(f'Requested thinking level is unavailable for model: {default_level}')
        selected['reasoning'] = {'enabled': True, 'levels': [
            {'value': value, 'label': value} for value in variants],
            'defaultLevel': default_level}
    elif requested_thinking:
        selected['thinkingLevel'] = requested_thinking
    ref = {'providerId': provider_id, 'modelId': model}
    api_format = str(provider.get('apiFormat') or SUPPORTED_PROVIDER_API_FORMATS[provider_kind])
    if api_format not in set(SUPPORTED_PROVIDER_API_FORMATS.values()):
        raise ValueError('Configured provider API format is unsupported')
    runtime = {'revision': str(uuid.uuid4()), 'generatedAt': int(time.time() * 1000), 'model': ref,
               'provider': {'providerId': provider_id, 'kind': provider_kind,
                            'apiFormat': api_format, 'source': 'ephemeral',
                            'baseURL': options['baseURL'],
                            'apiKey': {'source': 'inline', 'value': options['apiKey']},
                            'models': [selected]}, 'contextBudget': budget}
    if selected.get('reasoning'):
        runtime['thoughtLevel'] = selected['reasoning']['defaultLevel']
    elif selected.get('thinkingLevel'):
        runtime['thoughtLevel'] = selected['thinkingLevel']
    return runtime


def preflight_runtime(config: dict, *, root: Path | None = None,
                      task: dict[str, Any] | None = None) -> dict[str, Any]:
    """Validate provider, context and native tool policy without inference."""
    runtime = load_runtime(config)
    selected = runtime['provider']['models'][0]
    budget = runtime['contextBudget']
    if budget['context_window_tokens'] < MAX_CONTEXT_TOKENS:
        raise ValueError(f'Provider context window must be at least {MAX_CONTEXT_TOKENS}')
    result: dict[str, Any] = {
        'status': 'passed',
        'provider_id': runtime['provider']['providerId'],
        'model_id': runtime['model']['modelId'],
        'context_budget': budget,
        'supports_tools': bool(selected.get('supportsTools')),
    }
    read_scope = (task or {}).get('read_scope') or ['.']
    write_scope = (task or {}).get('scope') or []
    root_path = root or Path.cwd()
    contract = {
        'root': str(root_path),
        'scope': write_scope,
        'read_scope': read_scope,
        'readonly': bool((task or {}).get('context', {}).get('read_only')),
    }
    read_probe = read_scope[0] if read_scope else '.'
    result['permission_checks'] = {
        tool: tool_decision(tool, {'path': read_probe}, contract)['decision'] == 'allow'
        for tool in READ_TOOLS
    }
    if not all(result['permission_checks'].values()):
        raise ValueError('Native read permission preflight failed')
    if root is not None:
        verify_guard(root)
        for key in ('node_executable', 'cli_entry'):
            if not Path(config[key]).is_file():
                raise OSError(f'Configured ZCode executable is missing: {key}')
    if selected.get('reasoning'):
        result['thinking_levels'] = [item['value'] for item in selected['reasoning']['levels']]
        result['thinking_level'] = selected['reasoning']['defaultLevel']
    elif runtime.get('thoughtLevel'):
        result['thinking_levels'] = [runtime['thoughtLevel']]
        result['thinking_level'] = runtime['thoughtLevel']
    return result


def parse_result(text: str, task_id: str) -> dict:
    text = text.strip()
    if text.startswith('```') and text.endswith('```'):
        if '\n' not in text:
            raise ValueError('Invalid single-line code fence')
        text = text.split('\n', 1)[1].rsplit('```', 1)[0].strip()
    result = json.loads(text)
    if not isinstance(result, dict) or result.get('task_id') != task_id:
        raise ValueError('Worker task id mismatch')
    if result.get('status') not in ('completed', 'partial', 'failed', 'blocked'):
        raise ValueError('Invalid worker status')
    if not isinstance(result.get('summary'), str) or type(result.get('needs_review')) is not bool:
        raise ValueError('Invalid worker summary/review field')
    for field in ('changed_files', 'tests', 'commands_executed', 'risks', 'unresolved'):
        if not isinstance(result.get(field), list):
            raise ValueError('Invalid worker list field')
        if field != 'tests' and not all(isinstance(item, str) for item in result[field]):
            raise ValueError('Invalid worker list item')
    return result


def failure(task_id: str, code: str) -> dict:
    return {'task_id': task_id, 'status': 'blocked' if code in ('quota', 'authentication', 'model', 'permission', 'config') else 'failed',
            'summary': f'ZCode worker stopped: {code}. No provider fallback was attempted.',
            'changed_files': [], 'tests': [], 'commands_executed': [], 'risks': [],
            'unresolved': [code], 'needs_review': True, 'failure_code': code}


def build_command(config: dict, *_args, **_kwargs) -> list[str]:
    return [config['node_executable'], config['cli_entry'], 'app-server']


def build_preflight_params(runtime: dict[str, Any], workspace: Path) -> dict[str, Any]:
    """Build a no-tool app-server session used only for connectivity probing."""
    return {
        'workspace': {
            'workspacePath': str(workspace.resolve()),
            'workspaceKey': str(workspace.resolve()),
        },
        'mode': 'plan',
        'model': runtime['model'],
        'runtimeModel': protocol_runtime(runtime),
        'persistence': 'deferred',
        'titleGenerationEnabled': False,
        'toolAllowlist': [],
        'toolDenylist': ['Read', 'Grep', 'Glob', 'Edit', 'Write', 'ApplyPatch', 'Bash', 'Agent'],
        'mcpServers': [],
    }


def protocol_runtime(runtime: dict[str, Any]) -> dict[str, Any]:
    """Remove local-only metadata before sending a runtime model to ZCode."""
    protocol = copy.deepcopy(runtime)
    protocol.pop('contextBudget', None)
    provider = protocol.get('provider', {})
    for model in provider.get('models', []) if isinstance(provider, dict) else []:
        if isinstance(model, dict):
            model.pop('contextBudget', None)
            model.pop('thinkingLevel', None)
    return protocol


def network_preflight(config: dict[str, Any], workspace: Path) -> dict[str, Any]:
    """Run the safe no-tool probe with a bounded transport retry policy."""
    return retry_operation(
        lambda: _network_preflight_once(config, workspace),
        max_retries=int(config.get('preflight_retries', 3)),
    )


def _network_preflight_once(config: dict[str, Any], workspace: Path) -> dict[str, Any]:
    """Keep one bounded deadline and expose safe stage timing on timeout."""
    progress = {'stage': 'runtime', 'started': time.monotonic(), 'timings': {}}
    try:
        return _run_network_preflight(config, workspace, progress)
    except TimeoutError as exc:
        elapsed = time.monotonic() - progress['started']
        timeout = float(config.get('preflight_timeout_seconds', 60))
        raise TimeoutError(
            f"Preflight deadline exceeded: stage={progress['stage']}, "
            f"elapsed_seconds={elapsed:.2f}, timeout_seconds={timeout:g}"
        ) from exc


def _run_network_preflight(config: dict[str, Any], workspace: Path,
                           progress: dict[str, Any]) -> dict[str, Any]:
    """Run one no-tool model request to verify the local relay path."""
    workspace = workspace.resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    probe_config = dict(config)
    probe_config['max_output_tokens'] = min(int(config.get('preflight_output_tokens', 32)), 128)
    runtime = load_runtime(probe_config)
    environment = os.environ.copy()
    environment['ZCODE_STORAGE_DIR'] = str(workspace / '.preflight-zcode-storage')
    contract_path = (workspace / '.preflight-scope-contract.json').resolve()
    audit_path = (workspace / '.preflight-scope-audit.jsonl').resolve()
    contract_path.write_text(json.dumps({
        'root': str(workspace),
        'scope': [],
        'read_scope': [],
        'readonly': True,
        'audit_path': str(audit_path),
    }), encoding='utf-8')
    environment['VSE_ZCODE_CONTRACT'] = str(contract_path)
    terminal = None
    session_id = None
    timeout = float(config.get('preflight_timeout_seconds', 60))

    progress['stage'] = 'process/start'
    with RpcProcess(build_command(config), workspace, environment, timeout) as rpc:
        def handle(message):
            nonlocal terminal
            if 'id' in message and 'method' in message:
                result = host_rpc_response(
                    message['method'], message.get('params'), runtime=runtime
                )
                if result is None:
                    rpc.send({'id': message['id'], 'error': {
                        'code': -32601, 'message': 'Unsupported worker host request'
                    }})
                else:
                    rpc.send({'id': message['id'], 'result': result})
                return
            event = message.get('params', {})
            payload = event.get('payload', {})
            if message.get('method') == 'session/event' and event.get('sessionId') == session_id:
                ref = payload.get('modelRef')
                if ref and any(ref.get(k) != runtime['model'][k] for k in ('providerId', 'modelId')):
                    raise ValueError('Preflight model mismatch')
                terminal = terminal_event(message, session_id) or terminal

        def request(method, params, handler, timeout):
            progress['stage'] = method
            started = time.monotonic()
            try:
                return rpc.request(method, params, handler, timeout=timeout)
            finally:
                progress['timings'][method] = round(time.monotonic() - started, 3)

        snapshot = request('session/create', build_preflight_params(runtime, workspace), handle, timeout=timeout)
        session_id = snapshot['session']['sessionId']
        settings = snapshot['settings']
        if settings['model']['current'] != runtime['model'] or settings['permission']['mode'] != 'plan':
            raise ValueError('Preflight model/permission mismatch')
        request('session/subscribe', {'sessionId': session_id, 'deliveryKind': 'desktop-continuous'}, handle,
                    timeout=timeout)
        request('session/send', {
            'sessionId': session_id,
            'inputId': 'PREFLIGHT-' + uuid.uuid4().hex,
            'content': 'Return exactly PING. Do not call tools.',
        }, handle, timeout=timeout)
        progress['stage'] = 'model/response'
        started = time.monotonic()
        while terminal is None:
            handle(rpc.receive())
        progress['timings']['model/response'] = round(time.monotonic() - started, 3)
        kind, payload = terminal
        if kind != 'turn.completed' or payload.get('resultType') not in ('success', None):
            details = json.dumps(payload, ensure_ascii=False)
            raise ProtocolError('Network preflight failed: ' + bound_text(details, 800))
        audit = []
        if audit_path.exists():
            audit = [json.loads(line) for line in audit_path.read_text(encoding='utf-8').splitlines() if line]
        if any(not item.get('allowed', False) for item in audit) or payload.get('toolCallCount', 0):
            raise ProtocolError('Network preflight attempted a tool call')
        usage = payload.get('usage', {})
        safe_usage = {
            key: int(value) for key, value in usage.items()
            if key in {'input_tokens', 'cached_input_tokens', 'output_tokens', 'reasoning_tokens'}
            and isinstance(value, (int, float))
        } if isinstance(usage, dict) else {}
        return {
            'status': 'passed',
            'timeout_seconds': timeout,
            'timings_seconds': progress['timings'],
            'elapsed_seconds': round(time.monotonic() - progress['started'], 3),
            'model_id': runtime['model']['modelId'],
            'session_id': session_id,
            'tool_call_count': int(payload.get('toolCallCount', 0) or 0),
            'usage': safe_usage,
        }


def verify_guard(worktree: Path):
    guard = Path.home() / '.zcode/tools/vse-worker-guard.py'
    source = Path(__file__).with_name('zcode_guard.py')
    if hashlib.sha256(guard.read_bytes()).digest() != hashlib.sha256(source.read_bytes()).digest():
        raise ValueError('Installed scope guard mismatch')
    global_config = json.loads((Path.home() / '.zcode/cli/config.json').read_text(encoding='utf-8-sig'))
    hooks = global_config.get('hooks', {})
    entries = hooks.get('events', {}).get('PreToolUse', [])
    if not hooks.get('enabled') or not any(str(guard) in h.get('args', []) for e in entries for h in e.get('hooks', [])):
        raise ValueError('Scope guard is not enabled')
    for root in (worktree, *worktree.parents):
        if any((root / name).exists() for name in ('.zcode/config.json', 'zcode.json')):
            raise ValueError('Project runtime overrides require manual review')
        if (root / '.git').exists():
            break


def build_worker_prompt(task: dict[str, Any], limits: dict[str, Any]) -> str:
    """Build a bounded worker instruction with operational, not cost, limits."""
    example = {'task_id': task['task_id'], 'status': 'completed', 'summary': 'concise result',
               'changed_files': [], 'tests': [], 'commands_executed': [], 'risks': [],
               'unresolved': [], 'needs_review': True}
    budget = limits['context_budget']
    return (
        'Complete this bounded task. You are the implementation worker, not the lead. '
        'Do not delegate or read global configuration, credentials, or memory directories. '
        'Use native Read/Grep/Glob and, if available, Edit/Write. Modify only scope paths. '
        'Do not modify instruction files or runtime settings. No shell is available. '
        'Do not claim you ran verification_commands; the supervisor runs them externally. '
        'Stop if architecture/security/public contracts require a new decision. '
        f'Keep the effective context at or below {budget["context_window_tokens"]} tokens, '
        f'with at most {budget["max_input_tokens"]} input tokens per request. '
        f'Use no more than {limits["max_model_turns"]} model turns and '
        f'{limits["max_tool_calls"]} tool calls; these are loop-safety limits, not a task token budget. '
        'Return only JSON with the following shape (do not invent completed tests):\n'
        + json.dumps(example) + '\nTask:\n' + json.dumps(task, ensure_ascii=False)
    )


def invoke(task: dict, worktree: Path, run_dir: Path, config: dict,
           effort: str | None = None, max_repair_attempts: int | None = None) -> dict[str, Any]:
    del effort, max_repair_attempts  # One bounded turn; caller owns repair rounds.
    started = time.monotonic()
    run_dir.mkdir(parents=True, exist_ok=True)
    summary: dict[str, Any] = {'model': config.get('model'), 'provider_id': config.get('provider_id'),
                               'permissions': [], 'tools': [], 'usage': {}, 'stopped': False}
    result = failure(task['task_id'], 'transport')
    secret = ''
    rpc = None
    try:
        verify_guard(worktree)
        runtime = load_runtime(config)
        limits = resolve_worker_limits(config)
        summary['context_budget'] = limits['context_budget']
        summary['max_model_turns'] = limits['max_model_turns']
        summary['max_tool_calls'] = limits['max_tool_calls']
        secret = runtime['provider']['apiKey']['value']
        readonly = config.get('readonly', False)
        if type(readonly) is not bool:
            raise ValueError('readonly must be boolean')
        mode = 'plan' if readonly else 'build'
        allowlist = READ_TOOLS + ([] if readonly else WRITE_TOOLS)
        env = os.environ.copy()
        env['ZCODE_STORAGE_DIR'] = str(run_dir / 'zcode-storage')
        contract_path = (run_dir / 'scope-contract.json').resolve()
        audit_path = (run_dir / 'scope-audit.jsonl').resolve()
        if audit_path.exists():
            raise ValueError('Run directory has already been used')
        read_scope = task.get('read_scope') or ['.']
        contract_path.write_text(json.dumps({'root': str(worktree.resolve()), 'scope': task['scope'],
                                             'read_scope': read_scope, 'readonly': readonly,
                                             'audit_path': str(audit_path)}), encoding='utf-8')
        env['VSE_ZCODE_CONTRACT'] = str(contract_path)
        # Never grant shells, nested agents, MCP, browsing or global settings tools.
        params = {'workspace': {'workspacePath': str(worktree.resolve()), 'workspaceKey': str(worktree.resolve())},
                  'mode': mode, 'model': runtime['model'], 'runtimeModel': protocol_runtime(runtime),
                  'persistence': 'deferred', 'titleGenerationEnabled': False,
                  'toolAllowlist': allowlist, 'toolDenylist': ['Bash', 'Agent'], 'mcpServers': []}
        if runtime.get('thoughtLevel'):
            params['thoughtLevel'] = runtime['thoughtLevel']
        terminal = None
        session_id = None
        with RpcProcess(build_command(config), worktree, env, float(config.get('timeout_seconds', 900))) as rpc:
            def handle(message):
                nonlocal terminal
                if 'id' in message and 'method' in message:
                    method = message['method']
                    request = message.get('params', {})
                    if method == 'interaction/requestPermission':
                        decision = permission_decision(request.get('toolName', ''), request.get('input') or {},
                                                       worktree, task['scope'], readonly, read_scope)
                        summary['permissions'].append({'tool': request.get('toolName'), 'decision': decision['decision']})
                        rpc.send({'id': message['id'], 'result': decision})
                        if decision['decision'] == 'deny':
                            raise PermissionError('Worker permission denied')
                    else:
                        result = host_rpc_response(
                            method, request, runtime=runtime
                        )
                        if result is None:
                            rpc.send({'id': message['id'], 'error': {
                                'code': -32601, 'message': 'Capability not enabled for worker'
                            }})
                        else:
                            rpc.send({'id': message['id'], 'result': result})
                    return
                event = message.get('params', {})
                payload = event.get('payload', {})
                if message.get('method') == 'session/event' and event.get('sessionId') == session_id:
                    ref = payload.get('modelRef')
                    if ref and any(ref.get(k) != runtime['model'][k] for k in ('providerId', 'modelId')):
                        raise ValueError('Model changed during worker turn')
                    if event.get('type') == 'tool.updated' and payload.get('toolName'):
                        summary['tools'].append({'name': payload.get('toolName'), 'status': payload.get('status')})
                    terminal = terminal_event(message, session_id) or terminal
            snapshot = rpc.request('session/create', params, handle)
            session_id = snapshot['session']['sessionId']
            settings = snapshot['settings']
            if settings['model']['current'] != runtime['model'] or settings['permission']['mode'] != mode:
                raise ValueError('Model/permission preflight mismatch')
            summary['session_id'] = session_id
            summary['tool_allowlist'] = allowlist
            rpc.request('session/subscribe', {'sessionId': session_id, 'deliveryKind': 'desktop-continuous'}, handle)
            prompt = build_worker_prompt(task, limits)
            rpc.request('session/send', {'sessionId': session_id, 'inputId': task['task_id'], 'content': prompt}, handle)
            while terminal is None:
                handle(rpc.receive())
            kind, payload = terminal
            summary['usage'] = payload.get('usage', {})
            summary['tool_call_count'] = payload.get('toolCallCount', 0)
            summary['model_turn_count'] = payload.get('modelTurnCount', payload.get('turnCount', 0))
            if isinstance(summary['usage'], dict):
                input_tokens = next(
                    (summary['usage'][key] for key in ('input_tokens', 'prompt_tokens', 'raw_input_tokens')
                     if key in summary['usage']),
                    None,
                )
                if input_tokens is not None:
                    summary['context_waterline'] = context_waterline(
                        int(input_tokens), limits['context_budget']
                    )
            counters = {
                'model_turns': summary['model_turn_count'],
                'tool_calls': summary['tool_call_count'],
            }
            if worker_budget_exceeded(counters, limits) or usage_budget_exceeded(
                summary['usage'], limits['context_budget']
            ):
                summary['budget_exceeded'] = True
                result = failure(task['task_id'], 'budget')
            elif kind != 'turn.completed' or payload.get('resultType') not in ('success', None):
                details = json.dumps(payload, ensure_ascii=False).replace(secret, '[REDACTED]')
                details = re.sub(r'https?://[^\s\"]+', '[endpoint]', details)
                summary['error_detail'] = details[:1200]
                result = failure(task['task_id'], classify_error(details))
            else:
                result = parse_result(payload.get('response', ''), task['task_id'])
                if any(not in_scope(worktree, task['scope'], path) for path in result['changed_files']):
                    result = failure(task['task_id'], 'scope')
            # Closing the owned job also stops any MCP/helper descendants.
        summary['stopped'] = True
        audited = [json.loads(line) for line in audit_path.read_text(encoding='utf-8').splitlines()] if audit_path.exists() else []
        summary['guard_calls'] = len(audited)
        if summary.get('tool_call_count', 0) and not audited:
            result = failure(task['task_id'], 'guard')
        elif any(not event['allowed'] for event in audited):
            result = failure(task['task_id'], 'permission')
        result['needs_review'] = True
    except PermissionError:
        result = failure(task['task_id'], 'permission')
        summary['stopped'] = True
    except TimeoutError:
        result = failure(task['task_id'], 'timeout')
        summary['stopped'] = True
    except (ValueError, KeyError, OSError, ProtocolError) as exc:
        classified = classify_error(str(exc))
        code = classified if isinstance(exc, ProtocolError) or classified != 'transport' else 'config' if not secret else 'result'
        result = failure(task['task_id'], code)
        summary['stopped'] = True
    summary['stopped'] = rpc.cleanup_complete if rpc is not None else True
    if not summary['stopped']:
        result = failure(task['task_id'], 'cleanup')
    summary['duration_seconds'] = round(time.monotonic() - started, 3)
    result['process'] = summary
    # No protocol request, raw provider error, credentials, or stderr is persisted.
    serialized = json.dumps(summary, ensure_ascii=False, indent=2)
    if secret:
        serialized = serialized.replace(secret, '[REDACTED]')
        result = json.loads(json.dumps(result).replace(secret, '[REDACTED]'))
    (run_dir / 'zcode-summary.json').write_text(serialized, encoding='utf-8')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--task', type=Path, required=True)
    parser.add_argument('--worktree', type=Path, required=True)
    parser.add_argument('--run-dir', type=Path, required=True)
    args = parser.parse_args()
    task = json.loads(args.task.read_text(encoding='utf-8-sig'))
    config = json.loads(args.config.read_text(encoding='utf-8-sig'))
    result = invoke(task, args.worktree, args.run_dir, config.get('zcode', config))
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result['status'] == 'completed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
