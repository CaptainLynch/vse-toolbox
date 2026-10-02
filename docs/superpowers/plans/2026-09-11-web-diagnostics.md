# WebUI safe full-chain diagnostics implementation plan

> Execute with superpowers:executing-plans. User approved implementation, excluding Office/Excel worker.

**Goal:** Record the observable non-Office execution chain for offline diagnosis.

**Architecture:** A separate bounded SQLite recording store shares the active recording across WebUI and scheduler processes using the same application data directory. Context variables carry trace/span identities; explicit context copying covers the archive heartbeat thread. Ingestion projects events onto safe metadata before persistence. Existing diagnostic outputs remain compatible.

**Tech Stack:** Python stdlib, Flask, existing browser JavaScript; no telemetry service.

**Spec:** User-approved conversation design: safe recording, all non-Office chains; no raw credentials, business files or arbitrary response bodies. Default 30 minutes, 100 MiB/recording, 7 days/500 MiB logical retention. Cross-process writers serialize quota enforcement. Capture failures never replace business results. Flask debugger stays disabled.

## Tasks

- [x] Core: tests/test_diagnostic_recording.py tests start/stop/expiry, second recorder instance, rejected secrets, frame-only exceptions, quotas, invalid IDs and ZIP contents. Implement core/diagnostic_recording.py with Recorder.start/status/stop/emit/export and recording_scope/operation decorators. Run `python -m pytest tests/test_diagnostic_recording.py -q`.
- [x] Web: tests/test_web_diagnostics.py tests loopback and Origin restrictions on all diagnostic endpoints, request IDs, business-error metadata, bounded frontend ingestion and export. Implement web/diagnostics.py registration and attach in web/app.py; launch flag in both actual entrypoints. Run focused tests with temporary DB/recorder only.
- [x] Chain: instrument auth/crawler emitters and operation boundaries, DB transactions, cache, archive storage, sync and archive runners. Test synthetic chain correlation, exception handling and background process discovery. Preserve existing HTTP hooks and business semantics. Run crawler/auth/sync/archive/db regressions.
- [x] Browser: standalone web/static/diagnostics.js controls, fetch correlation and safe action/error metadata; dashboard includes script. Node synthetic tests verify original fetch semantics, no request body capture and no recursion. Add operator instructions.
- [x] Final: focused tests, complete application regression, scoped lint/JS syntax, generated maps, packaged WebUI smoke and ZIP inspection. Integrate only reviewed diagnostics changes over the preserved checkout. No commit/push or production request.

## Security contract

Record fixed operation names, bounded counters, HTTP status and known media types. Input and output business strings become keyed fingerprints; never record authentication values even as fingerprints. Exception frames contain module basename/function/line only, no source lines, messages or locals. HTTP events omit headers and bodies. Frontend accepts fixed event kinds and validated generated UUIDs only, not arbitrary prose/DOM text. Download takes a generated recording ID, never a filesystem path. Known omissions and capacity/drop counters are exported. Optional response sample is structural metadata only: raw business samples remain excluded.

## Verification fixtures

Synthetic strings such as `SYNTHETIC_SECRET` appear in credentials, messages, URLs, nested inputs and response headers; assertions search persisted/exported bytes for absence. Two recorder objects and a subprocess use a temporary root to prove shared session discovery. Failing business functions must raise their original exception while recording a safe frame event. Retention and deadline tests use injected clock/caps. Source/frozen integration includes static assets and diagnostics store export.
