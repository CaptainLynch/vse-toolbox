# B′ P1a TD-4（补充，独立于 p1a-impl-reference.md，后者未改动）
## 追加（19:37）：TD-4 本机才暴露的导入路径缺陷
- 本机证据：task-2 回执 7fb95689 失败，`tests/test_bprime_config_audit_fixture_trace.py:5` 的 `from conftest import trace` 抛 `ModuleNotFoundError: No module named 'conftest'`。
- 根因：本机 `tests/` 下有 `__init__.py`（内容只有一行注释 `# tests/__init__.py`），pytest 默认 prepend 导入模式把仓库根目录放进 sys.path，conftest 以 `tests.conftest` 身份加载；顶层名 `conftest` 不存在。云端副本最初缺这个 `__init__.py`，所以没暴露。
- 影响：6 个文件共 7 处 `from conftest import trace`，对应 12 个节点（只有 isolation_schema、fixture_state 两个节点不受影响）：
  - tests/test_bprime_config_audit_changes.py:9
  - tests/test_bprime_config_audit_failures.py:10
  - tests/test_bprime_config_audit_fixture_trace.py:5
  - tests/test_bprime_config_audit_isolation.py:3 和 :54
  - tests/test_bprime_config_audit_mixed.py:3
  - tests/test_bprime_config_audit_noarchive.py:3
- 最小修复：这 7 处逐字改为 `    from tests.conftest import trace`（缩进 4 个空格不变）。不改断言，不改 conftest.py，也不改 setup.cfg。
- 云端复验：补上 tests/__init__.py 后，修复前 12 failed / 2 passed；修复后，在实现补丁齐全的副本上扩大回归 498 passed。
- 建议拆成两张 tests-only 卡（每张不超过 3 个文件）：
  - TESTFIX-2A：fixture_trace、changes、failures
  - TESTFIX-2B：isolation、mixed、noarchive
- task-2（IMPL-1）的实现本身没有问题：同一回执里 isolation_schema、fixture_state 两个节点本机通过。fixture_trace 只需等 TESTFIX-2A 完成后重跑。
