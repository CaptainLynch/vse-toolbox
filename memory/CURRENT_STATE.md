# Current State

Last checkpoint: 2026-09-02 (Codex production WebUI packaging after NCR
progress response adaptation and real WebUI verification).

## Current objective

Complete and safely hand off the unified deliverable-form analysis work on
branch `feature/scheduled-deliverables-overview-excel`, preserving the existing
CLI/WebUI, ARAS/TDC connector boundaries, scheduled archive safety, and additive
public APIs. A production WebUI ZIP is prepared locally for distribution;
email delivery remains pending because no usable mail sending connector is
available on this host.

The working tree contains related feature, repair, and agent-harness changes.
The form tracks share `services/deliverable_form_analysis.py`; review them
together rather than reverting individual files.

## Completed repair frontier

- NCR blank identifiers remain separate metric entities; legacy positional
  snapshots recover NCR identity and legacy completion state read-side.
- Current form schemas are served over old snapshots; NCR historical trends use
  the current entity grain when the stored schema predates it.
- NCR `完成` and TDC status code `4` normalize to completion. Contacts are
  masked before stored table values and search text. Filter options remain
  discoverable under active filters.
- Official workbook truncation, fallback API record caps, unreadable/invalid
  NCR workbooks, and form projection failures become `needs_attention` while
  retaining artifacts and the last good form snapshot.

## NCR progress response adaptation

The live ARAS progress response was HTTP 200 and contained a `Result` subtree
with an `Item` carrying a non-empty `_file` relation, but its server-side Item
type spelling did not match the hard-coded `sgmw_outputFileRecord` value. The
parser now restricts discovery to `Result` descendants and identifies the
export by the `_file` relation, retaining the file name and outer record ID.
`Message` nodes and arbitrary XML nodes are not accepted as fallbacks.

## Production WebUI package

- `VSE-WebUI.spec` now excludes only CLI-only integrations and their optional
  dependency trees (Selenium, IMAP, Rich, xlwings, PythonWin helpers, and
  test/debug-only modules), while retaining the explicit WinHTTP/pywin32
  hidden imports required by the existing packaging contract.
- The final local build used the isolated `.runtime/py311-webui-venv-20260902`
  environment (Python 3.11, PyInstaller 6.22.2) and UPX 5.2.1. The EXE is
  `15220786` bytes; the ZIP contains only `VSE-WebUI.exe` and is
  `14942697` bytes, below the strict 15,000,000-byte limit.
- Final local artifact: `.runtime/VSE-WebUI-production-20260902-r2.zip`.
  ZIP test passed; ZIP SHA256 is
  `057deaf252d6457ffa1e5ca2a9789102cc3ceaabf964156d89b6ee3341e89384`.
  EXE SHA256 is
  `88249037b78a2c16773faba6d39f45e56533907bac6037d8467ac1ee3452101c`.
- Final EXE smoke on isolated port 55128 returned HTTP 200 for `/`,
  `/static/app.js`, and `/api/overview`; the test process was stopped.
- Email delivery was not performed: the user reports Gmail connected, and the
  workspace app list discovers Gmail, but this task still exposes no Gmail
  `send_email`/attachment action. Classic Outlook COM activation also failed;
  no credential or mail secret was stored.

## Validation

- ARAS parser/Web route tests: `126 passed` — `.runtime/ncr-adaptation-web-tests.log`.
- Full pytest after adaptation: `1673 passed, 2 skipped` —
  `.runtime/ncr-adaptation-full-final.log`.
- flake8, compileall, Node check, and git diff check passed —
  `.runtime/ncr-adaptation-static.log`.
- Fresh dual PyInstaller build passed; WebUI SHA256 is recorded in
  `.runtime/ncr-adaptation-build-output-final2/SHA256SUMS.txt`.
- Fresh build WebUI real smoke on isolated port 55125: login succeeded; NCR
  progress returned 500 rows, the query button re-enabled, and browser console
  error count was zero. Password field was empty after submit and saving the
  credential option remained disabled.
- No raw ARAS XML, credential, cookie, token, or business row was written to
  memory or diagnostics.
- Final packaging regression: `1672 passed, 2 skipped` after the spec
  exclusions were reconciled with `tests/test_webui_winhttp_packaging.py`.
  `compileall`, Node syntax check, and `git diff --check` also passed.

## ZCode / AGY cross-audit

- ZCode session `sess_8471cad2-b3f8-49d9-a956-7f9f22546a1c` used the configured
  custom provider with model `gemini-3.7-flash-high`. It completed the
  read-only cross-audit and then executed the two required verification
  commands: `151 passed in 6.43s` and
  `python -m compileall -q services core web` exit 0. Findings were compliant;
  custom NCR node aliases remain intentionally unresolved pending domain
  confirmation.
- AGY model-only calls work, but headless command calls remain blocked on
  Windows. AGY 1.1.23 and 1.1.24 soft-denied `Bash`/`RunCommand` and attempted
  `escalate_admin`; a precise command allow rule had no effect. Do not use
  global `command(*)`, `always-proceed`, or `--dangerously-skip-permissions`.
- AGY TUI launches but requires first-run terms/login interaction; no terms
  were accepted automatically. A custom-agent experiment was removed because
  it did not prove Bash execution and its real agent path hit a location
  precondition error.

## Git state and remaining acceptance

- HEAD remains `f700cbb`; no files are staged and no commit was made by Codex.
- `VSE-WebUI.spec` is an intentional uncommitted packaging change; the other
  pre-existing feature/repair and agent-harness working-tree changes remain
  untouched.
- The existing feature/repair and agent-harness working-tree changes remain
  intentionally available for review; no unrelated changes were reverted.
- Production credentialed acceptance was performed only as the requested
  read-only ARAS smoke. No archive sync, export download, or write operation
  was executed.
- The UI's unified login endpoint also attempted TDC authentication as part of
  the approved flow, but this run did not separately validate a TDC operation;
  the ARAS result above is the verified contract.

## Next action

If the Gmail send action becomes exposed or the user sends the prepared ZIP
manually, use the recorded local artifact and verify the attachment remains
under 15,000,000 bytes. If future ARAS changes produce another response
variant, add a sanitized parser fixture first; do not log or persist the raw
response. Do not rebuild the strict-size package with the default Python 3.14
environment without rechecking the attachment size.
