import json
import re
import shutil
import subprocess
from pathlib import Path

def _node_major() -> int:
    node = shutil.which("node")
    if node is None:
        return 0
    out = subprocess.run([node, "--version"], capture_output=True, text=True, check=False).stdout
    match = re.match(r"v(\d+)", out.strip())
    return int(match.group(1)) if match else 0

def _run(script: str) -> dict:
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script, MODULE.as_uri()],
        capture_output=True, text=True, encoding="utf-8", check=False,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    return json.loads(result.stdout.strip().splitlines()[-1])

REQUIRE_MAJOR = _node_major
MODULE = Path(__file__).resolve().parents[1] / 'plugins/project_overview/static/deliverable/policy-digest-logic.js'
PREFIX = '''
const {attachPolicyDigest: attach, isPolicyDigestConflict: classify} = await import(process.argv[1]);
const conflict = '绑定已发生变化，请刷新配置后重试';
const fail = message => { throw new Error(message); };
const assert = {
  equal: (a, b) => Object.is(a, b) || fail('equal'),
  notEqual: (a, b) => !Object.is(a, b) || fail('notEqual'),
  deepEqual(a, b) { if (Object.is(a, b)) return;
    if (a === null || b === null || typeof a !== 'object' || typeof b !== 'object' || Array.isArray(a) !== Array.isArray(b)) fail('deepEqual'); const keys = Reflect.ownKeys(a); if (keys.length !== Reflect.ownKeys(b).length) fail('deepEqual keys');
    for (const key of keys) { if (!Object.prototype.hasOwnProperty.call(b, key)) fail('deepEqual key'); this.deepEqual(a[key], b[key]); } },
  async throws(fn, Type) { const error = await Promise.resolve().then(fn).then(() => null, value => value); if (!(error instanceof Type)) fail('throws'); },
  fail
};
'''
SUFFIX = '\nconsole.log(JSON.stringify({ok: true}));'

def test_attach_digest_verbatim():
    assert REQUIRE_MAJOR() >= 22
    assert _run(PREFIX + r'''
const payload = Object.freeze({enabled: true});
for (const digest of ['cfgd1:AbCdEF', ' cfgd1:AbC ' + String.fromCharCode(9, 10),
                      ' ', String.fromCharCode(9), String.fromCharCode(10)]) {
  const result = attach(payload, digest);
  assert.deepEqual(result, {enabled: true, expectedConfigDigest: digest});
  assert.notEqual(result, payload);
}
''' + SUFFIX) == {'ok': True}

def test_omit_absent_digest():
    assert REQUIRE_MAJOR() >= 22
    assert _run(PREFIX + r'''
const payload = Object.freeze({enabled: true});
for (const digest of [undefined, null, '', false, true, 0, 42, {}, [], new String('token')]) {
  const result = attach(payload, digest);
  assert.deepEqual(result, {enabled: true});
  assert.equal(Object.prototype.hasOwnProperty.call(result, 'expectedConfigDigest'), false);
}
assert.deepEqual(payload, {enabled: true});
''' + SUFFIX) == {'ok': True}

def test_preserve_payload():
    assert REQUIRE_MAJOR() >= 22
    assert _run(PREFIX + r'''
const matchRule = Object.freeze({source: 'synthetic'});
const payload = Object.freeze({enabled: false, intervalMinutes: 47, matchRule});
const result = attach(payload, 'Token');
assert.deepEqual(result, {...payload, expectedConfigDigest: 'Token'});
assert.equal(result.matchRule, matchRule);
assert.notEqual(result, payload);
assert.deepEqual(payload, {enabled: false, intervalMinutes: 47, matchRule});
const inherited = Object.assign(Object.create({expectedConfigDigest: 'old'}), {enabled: true});
assert.deepEqual(attach(inherited, 'new'), {enabled: true, expectedConfigDigest: 'new'});
''' + SUFFIX) == {'ok': True}

def test_reject_existing_digest_key():
    assert REQUIRE_MAJOR() >= 22
    assert _run(PREFIX + r'''
for (const value of [undefined, null, '', 'old']) {
  for (const digest of [undefined, '', 'new']) {
    const payload = Object.create(null);
    Object.defineProperty(payload, 'expectedConfigDigest', {value});
    Object.freeze(payload);
    await assert.throws(() => attach(payload, digest), TypeError);
    assert.equal(payload.expectedConfigDigest, value);
  }
}
''' + SUFFIX) == {'ok': True}

def test_classify_digest_errors():
    assert REQUIRE_MAJOR() >= 22
    assert _run(PREFIX + r'''
for (const value of [undefined, null, '', 'x', false]) {
  assert.equal(classify({status: 422, fields: {expectedConfigDigest: value, other: 'x'}}), true);
}
const fields = Object.create(null);
Object.defineProperty(fields, 'expectedConfigDigest', {get() { assert.fail('unexpected value read'); }});
assert.equal(classify({status: 422, fields}), true);
for (const status of [200, 400, 409, 500, undefined, null, '422']) {
  assert.equal(classify({status, fields: {expectedConfigDigest: 'x'}}), false);
}
for (const fields of [undefined, null, [], Object.assign([], {expectedConfigDigest: 'x'}), {},
                      'x', 42, true, () => {}, Object.create({expectedConfigDigest: 'x'})]) {
  assert.equal(classify({status: 422, fields}), false);
}
for (const error of [null, undefined, false, 42, 'x', () => {}, {},
                     Object.assign(() => {}, {status: 422, fields: {expectedConfigDigest: 'x'}})]) {
  assert.equal(classify(error), false);
}
''' + SUFFIX) == {'ok': True}

def test_classify_request_errors():
    assert REQUIRE_MAJOR() >= 22
    assert _run(PREFIX + r'''
const fields = Object.assign(Object.create(null), {request: conflict});
assert.equal(classify({status: 422, fields}), true);
assert.equal(classify(Object.assign(new Error('unrelated'), {status: 422, fields})), true);
for (const fields of [
  {request: '包含不允许修改的字段'},
  {request: conflict, other: 'x'},
  {request: conflict + ' '}, {request: ' ' + conflict},
  {request: conflict.slice(0, -1)}, {request: [conflict]}, {request: new String(conflict)},
  Object.create({request: conflict}), Object.assign(Object.create({request: conflict}), {other: 'x'}),
  Object.assign([], {request: conflict}),
]) assert.equal(classify({status: 422, fields}), false);
for (const status of [200, 400, 409, 500, undefined, null, '422']) {
  assert.equal(classify({status, fields: {request: conflict}}), false);
}
''' + SUFFIX) == {'ok': True}
