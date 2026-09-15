"""PreToolUse guard, active only for processes carrying VSE_ZCODE_CONTRACT."""
import json
import os
from pathlib import Path
import re
import sys

CONTROL = {'.git', '.zcode', '.codex', '.agents', '.claude', '.gemini', 'zcode.json', '.env', 'agents.md', 'claude.md', 'gemini.md'}


def tool_path(data, default=None):
    for key in ('file_path', 'filePath', 'path', 'directory', 'directoryPath'):
        value = data.get(key)
        if isinstance(value, str) and value:
            return value
    return default


def in_scope(root, scope, value):
    if not isinstance(value, str) or not value:
        return False
    root = Path(root).resolve()
    try:
        candidate = (root / value).resolve()
        relative = candidate.relative_to(root)
    except (ValueError, OSError):
        return False
    if any(part.lower() in CONTROL or part.lower().startswith('.env.') for part in relative.parts):
        return False
    # Windows alternate streams are not ordinary owned files.
    if any(':' in part for part in relative.parts):
        return False
    for item in scope:
        try:
            allowed = (root / item).resolve()
            allowed.relative_to(root)
            if candidate == allowed or allowed in candidate.parents:
                return True
        except (ValueError, OSError):
            continue
    return False


def tool_decision(tool, data, contract):
    """Return the shared allow/deny decision used by the hook and worker RPC."""
    if not isinstance(data, dict):
        return {'decision': 'deny', 'reason': 'Malformed tool input'}
    root = Path(contract['root'])
    read_scope = contract.get('read_scope') or contract.get('scope') or ['.']
    write_scope = contract.get('scope') or []
    if tool in ('Read', 'Grep', 'Glob'):
        path = tool_path(data, '.')
        allowed = in_scope(root, read_scope, path)
        return {'decision': 'allow' if allowed else 'deny',
                'reason': 'Owned native read' if allowed else 'Outside read scope'}
    if contract.get('readonly'):
        return {'decision': 'deny', 'reason': 'Readonly worker'}
    if tool in ('Write', 'Edit'):
        path = tool_path(data)
        allowed = in_scope(root, write_scope, path)
        return {'decision': 'allow' if allowed else 'deny',
                'reason': 'Owned native edit' if allowed else 'Outside worker contract'}
    if tool == 'ApplyPatch':
        patch = data.get('patch') or data.get('patch_text') or data.get('input')
        if not isinstance(patch, str):
            return {'decision': 'deny', 'reason': 'Malformed patch'}
        paths = re.findall(r'^\*\*\* (?:Add File|Update File|Delete File|Move to): (.+)$', patch, re.M)
        allowed = bool(paths) and all(in_scope(root, write_scope, path.strip()) for path in paths)
        return {'decision': 'allow' if allowed else 'deny',
                'reason': 'Owned native patch' if allowed else 'Outside worker contract'}
    return {'decision': 'deny', 'reason': 'Tool is not enabled'}


def check_tool(event, contract):
    tool = event.get('tool_name', event.get('toolName'))
    data = event.get('tool_input', event.get('input', {}))
    return tool_decision(tool, data, contract)['decision'] == 'allow'


def main():
    contract_path = os.environ.get('VSE_ZCODE_CONTRACT')
    if not contract_path:
        return 0
    try:
        contract = json.loads(Path(contract_path).read_text(encoding='utf-8-sig'))
        raw = sys.stdin.read(1_000_001)
        if len(raw) > 1_000_000:
            return 2
        event = json.loads(raw)
        allowed = check_tool(event, contract)
        with Path(contract['audit_path']).open('a', encoding='utf-8') as handle:
            handle.write(json.dumps({'tool': event.get('tool_name', event.get('toolName')),
                                     'allowed': allowed}) + '\n')
        if not allowed:
            print('Worker tool is outside the allowed scope.', file=sys.stderr)
        return 0 if allowed else 2
    except Exception:
        print('Worker scope guard cannot validate this request.', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
