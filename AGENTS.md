# Agent Collaboration Rules

## Shared Engineering Rules

- Keep architecture, module boundaries, interfaces, data flow, security,
  authentication, authorization, privacy, and public contracts under the
  Main Agent's direct judgment.
- Delegate only bounded work with a concrete objective, owned files or a
  read-only scope, acceptance criteria, and focused verification commands.
- Do not repeat the same broad exploration in multiple agents. Give each
  agent the smallest useful evidence set and require compact, structured
  reports rather than full files, diffs, or logs.
- Do not trade correctness for token savings. Escalate when the evidence
  contradicts the settled design, a public interface or data model must change,
  a security assumption is uncertain, unrelated edits prevent a safe change,
  or two bounded repair attempts fail for the same cause.
- Preserve unrelated workspace changes. Never revert them unless the user
  explicitly requests it.
- Redirect verbose test, build, and log output to `.runtime/` where practical.
  Report failures, root causes, evidence locations, and material warnings.
- Verify the implemented contract with focused tests, then perform the final
  regression, packaging, or smoke checks warranted by the change.
- Treat secrets, credentials, tokens, cookies, and environment values as
  sensitive. Do not place them in instructions, source control, routine agent
  handoffs, or reports. Expose the minimum necessary exact value only when the
  Main Agent explicitly judges it essential for reproduction or verification.

## Runtime Selection

Use exactly one runtime section.

- In OpenAI Codex, when `use-v4-flash-worker` and `v4_flash_worker` are
  actually available, follow **Codex Runtime Rules** only.
- In ZCode, follow **ZCode Runtime Rules** only.
- Do not invoke, request, or emulate another runtime's agents, skills, or
  orchestration merely because both sections appear in this file. Determine the
  runtime from the available tools, skills, and agent names; never start both
  worker systems for one task.

## Codex Runtime Rules

Use Codex for high-value architectural reasoning and final accountability. Use
`v4_flash_worker` for bounded, high-volume exploration, implementation, and
log processing whenever doing so does not weaken security or design quality.

The target split for suitable tasks is approximately:

- Codex: 20-35% of the work, focused on decisions and verification.
- v4 Flash: 65-80% of the work, focused on execution and reduction.

These percentages are guidance, not a reason to delegate tightly coupled or
high-risk decisions.

### Codex Responsibilities

Codex retains ownership of:

- architecture, module boundaries, interfaces, and data flow;
- security, authentication, authorization, privacy, and secret handling;
- root-cause judgment and decisions between meaningful alternatives;
- cross-module changes, migrations, and compatibility policy;
- implementation contracts and acceptance criteria;
- final code review, regression assessment, release verification, and user
  communication.

Use higher reasoning effort only when architecture, security, difficult root
cause analysis, or consequential tradeoffs show a measured need for it.
Routine coordination and verification should use the normal reasoning level.

### v4 Flash Responsibilities

Prefer `v4_flash_worker` for bounded tasks such as:

- repository searches, file enumeration, and call-chain tracing;
- reading and reducing large HAR files, logs, test output, and build output;
- implementing a defined design in explicitly owned files;
- focused tests, repetitive edits, mechanical migrations, and documentation;
- extracting evidence, comparing contracts, and reporting concise findings.

Do not delegate work when it requires continuous architectural judgment,
changes public contracts without a settled design, performs irreversible
operations, or handles unresolved security decisions.

### Required Workflow

For substantial work, use this sequence when applicable:

1. v4 Flash explores the relevant code or evidence and returns a compact,
   structured report.
2. Codex decides the architecture, invariants, security constraints, file
   ownership, and acceptance criteria.
3. v4 Flash implements the bounded contract directly in the assigned files and
   runs focused tests.
4. Codex reviews the relevant diff, contract boundaries, test summary, and
   material risks.
5. v4 Flash performs narrowly specified follow-up fixes when needed.
6. Codex runs or confirms final regression tests, packaging, and smoke checks.

Before spawning or continuing `v4_flash_worker`, use the installed
`use-v4-flash-worker` skill and its plaintext Hook workflow. Spawn it with
`fork_turns="none"`. Workers must not revert unrelated edits.

### Worker Output

The normal worker report is limited to:

1. changed files;
2. one concise explanation per file;
3. test commands and summarized results;
4. no more than five remaining risks;
5. questions requiring Codex architectural judgment.

## Local AGY CLI Delegation

Codex is the Lead Engineer: it owns architecture, security-sensitive changes,
complex debugging, cross-module reasoning, task routing, final review, and
integration decisions. The locally installed `agy` CLI is the implementation
worker runtime for bounded repository exploration, mechanical implementation,
frontend work, tests, lint/type fixes, documentation, and repetitive
refactoring. Invoke it as a local subprocess; do not represent it as a Codex
subagent or call a remote model API directly.

The local harness uses structured JSON handoffs in `.agents/runs/` and isolated
Git worktrees. Codex must inspect the worker diff, run configured checks,
validate acceptance criteria, and return `PASS`, `FIX`, or `REJECT`; it must
not blindly trust a worker result. Never let both agents edit the same
worktree. Tasks involving architecture, authentication, authorization,
security, destructive migrations, irreversible operations, or unclear
acceptance criteria are routed to Codex or `manual` by default.

The AGY CLI invocation must use the configured local executable and model,
`--sandbox`, bounded timeouts, and a JSON output schema. Never use
`--dangerously-skip-permissions`. A headless permission denial is a blocked
worker result, not permission to weaken the sandbox.

## ZCode Runtime Rules

### Main Agent

The Main Agent is responsible for the final implementation and judgment.
Normally use `glm-5.2` at `high` effort; use `max` only for difficult root
cause analysis, cross-module bugs, concurrency or consistency problems,
complex architecture, major refactors, high-risk data flow, or repeated failed
attempts.

The Main Agent understands the request, decides the implementation, modifies
code, judges architecture and invariants, handles security and high-risk logic,
integrates subagent evidence, fixes review findings, and completes final
verification.

### readonly-explorer

Prefer `readonly-explorer` for broad repository search, implementation
location, call-chain investigation, module or dependency mapping, architecture
research, and pre-change evidence collection.

`readonly-explorer` is strictly read-only. Its tool whitelist must not include
Bash, Edit, Write, shell execution, or any other workspace-mutating capability.

Do not make Main and `readonly-explorer` repeat the same broad search. The
agent should return concise files, symbols, call chains, evidence, risks, and
unanswered questions.

The built-in `Explore` agent must not be used for normal repository exploration
because its runtime tool set may expose Bash and therefore does not provide the
required hard read-only boundary.

Do not invoke the built-in `Explore` merely as a fallback. If
`readonly-explorer` is unavailable, Main should perform the minimum necessary
read-only investigation itself or report the configuration problem.

### general-purpose

Use built-in general-purpose only for clearly bounded, independent work such as
a small feature, bounded bug fix, isolated test, or safely parallel code task.
It must not decide unresolved architecture, security, public APIs, data models,
or unclear cross-module changes.

Prefer `general-purpose` (Flash) for the following mechanical,
high-volume work types to conserve Main Agent tokens. In each case Main must
first define the contract (fixture template, method signature, return shape,
assertion checklist, or input-output spec) before delegating; Flash fills in
the concrete implementation under that contract.

1. **Test writing.** Once Main defines the fixture template, the service/data
   contract under test, and the per-scenario assertion checklist, delegate the
   actual test function bodies to Flash. Main should not hand-write every
   scenario. This is the single largest recoverable token saving.
2. **Call-site updates after signature changes.** When Main changes a method
   signature or return type, delegate the mechanical sweep of all call sites
   to Flash with the old/new contract and a list of affected files.
3. **Small utility functions.** When Main specifies the input-output contract
   (types, limits, edge cases), delegate the 5-15 line implementation to Flash.
4. **Simple read-only query methods.** When Main defines the field list, filter
   conditions, and ordering, delegate the SQL/query method body to Flash.
5. **Mechanical fixes identified by review.** When a review finding is a
   mechanical edit (renaming, adding a parameter, updating a repr) with no
   architectural judgment required, delegate the fix to Flash. Main retains
   complex fixes requiring root-cause reasoning.

Main retains: lease/concurrency design, redaction boundary decisions, exception
flow analysis, security/compatibility tradeoffs, architecture and data model
decisions, review finding triage, and final verification.

### code-reviewer

After meaningful or risky changes, invoke `code-reviewer` for core logic,
multiple files, cross-module behavior, authentication or permissions, data
handling, concurrency, state machines, error handling, public behavior, or
non-trivial regression risk. Do not invoke it mechanically for tiny,
unambiguous, low-risk edits.

### Recommended Workflow

Simple task: Main -> modify -> focused verification -> done.

Exploration task: readonly-explorer -> Main decision -> Main implementation ->
focused verification.

Important change: readonly-explorer when needed -> Main decision -> Main
implementation -> code-reviewer -> Main fixes -> regression verification.

For clearly bounded parallel work: readonly-explorer or general-purpose -> Main
integration and final judgment -> code-reviewer when needed -> final
verification. Do not delegate merely to consume model quota.

Test-heavy change: Main defines contracts and fixture templates -> general-purpose
(Flash) writes test scenario bodies -> Main reviews test diff and runs verification.
Main should not hand-write every test scenario; the target is for Flash to produce
60-80% of test code lines once the contract is settled.

Mechanical follow-up: Main changes a signature or return type -> general-purpose
(Flash) sweeps all call sites -> Main verifies compilation and runs focused tests.
