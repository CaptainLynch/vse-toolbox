# Context Manifest — VSE Toolbox

Navigation map for the shared Codex + ZCode long-term memory. Any agent in a
new session, after compaction, or after a Codex/ZCode/model switch restores
state from here instead of re-investigating the repository. Memory is
navigation, not proof: the repository is always the source of truth.

## Read order (non-trivial tasks)

1. `AGENTS.md` — collaboration and runtime rules (who may do what).
2. `memory/CURRENT_STATE.md` — current objective, execution frontier,
   exact next action, completion criteria.
3. `memory/RECOVERY_NOTES.md` — required when debugging, or when touching the
   agent harness, crawlers, DPAPI/credentials, Excel COM, or packaging;
   otherwise skim the "do not retry" section.
4. `memory/DECISIONS.md` — when a choice touches something already decided.
5. Verify against the repository before working: `git status`, `git diff`,
   `git log --oneline -10`, relevant code and tests.

## Files and update rules

| File | Role | Update policy |
| --- | --- | --- |
| `CURRENT_STATE.md` | Execution frontier; the only file that must always answer "what now?" | Replace wholesale at every milestone checkpoint |
| `RECOVERY_NOTES.md` | Environment pitfalls, failed attempts (do-not-retry), verified root causes | Append + prune; wholesale rewrite allowed; never delete *why* an attempt failed |
| `DECISIONS.md` | Durable decisions that constrain future work | Append-only; supersede, never delete |
| `CONTEXT_MANIFEST.md` | This map: read order, doc freshness, fact priority | Edit only when memory layout or doc inventory changes |

Checkpoint triggers and mechanics are defined in `AGENTS.md` → "Persistent
Project Memory Protocol". A default milestone updates `CURRENT_STATE.md`
only; the other files gain entries only for their corresponding events.

## Local-only state (do not rely on it after a clone or machine change)

- `.superpowers/sdd/<date>-<plan>/progress.md` — SDD ledgers (rulings, task
  progress, AGY audit). Gitignored by design (`.superpowers/sdd/.gitignore`).
- `.agents/runs/TASK-*/` — AGY worker handoffs and evidence. Gitignored.
- `.runtime/` — logs, diagnostics, test output. Gitignored.

Consequence: anything from these that must survive a new clone, a machine
change, or a session loss has to be promoted into `memory/` (committed) at
the checkpoint that produces it.

## Document inventory (freshness)

Tracked documentation, grouped by status:

| Location | Status |
| --- | --- |
| `docs/superpowers/specs/` + `docs/superpowers/plans/` (dated) | Active convention: per-feature design spec + execution plan |
| `docs/*.md` (SCHEDULED_*, EXCEL_*, PRODUCTION_*, USER_GUIDE_*, PROD_DATA_MODEL_*) | Active architecture docs and runbooks |
| `docs/agents/research_notes.md`, `crawl_source_index.md`, `paa_har_snapshot.md`, `crawler_contract.md` | Active reference for crawler work |
| `DELIVERABLE_UPDATE_MODES_PILOT_ARCHITECTURE.md` | Active architecture reference for the implemented dual-mode (interactive/background) deliverable sync |
| `DELIVERABLE_UPDATE_MODES_IMPLEMENTATION_PLAN.md` | Consumed sprint plan; historical (kept because the PILOT_ARCHITECTURE doc references it) |
| `PROJECT_OVERVIEW_*.md`, `FRONTEND_REDESIGN_EXECUTION_PLAN.md`, `.codex.yaml`, `docs/agents/{project_state,task,review_feedback,role_*,SOP_worker_coding,implementation_plan}.md` | Deleted 2026-09-02: retired 2026-06 sprint artifacts + four-role agent subsystem (see DECISIONS). Recover via Git history if ever needed |
| `DESIGN.md` | Active UI design-token document (warm cream / coral system adopted by the current dashboard) |
| `GPT_WEB_PROJECT_CONTEXT.md` | External-LLM context snapshot (2026-08-20). Its §6 design constraints are durable (promoted into `DECISIONS.md`), but capability/branch claims are stale (Web Excel tasks and scheduled sync now exist; Python-version claim conflicts with `requirements.txt`). Refresh before reusing it for an external LLM session |
| `docs/PHASE0_*`, `docs/PHASE1_*` | Historical refactor baseline (2026-06) |
| `README.md` | Partially stale: claims CLI-only/"zero web framework" while the project now ships a full Flask WebUI; contains a stray `ACCEPTANCE_TEST` line; directory table incomplete. Do not rely on its structure description |

## Fact priority on conflict

1. Actual code / runtime behavior
2. Tests / logs
3. Git diff / git history
4. Current configuration (`setup.cfg`, `.agents/config.json`, requirements)
5. `memory/` files (this shared long-term memory)
6. ZCode native project memory (auxiliary)
7. Chat context
8. Model speculation

If memory says "done" but tests fail, tests win — fix the memory at the next
checkpoint, never the evidence.

## Hygiene

- Never store secrets in memory files (no API keys, tokens, passwords,
  cookies, DPAPI payloads). Record only env var names and config locations.
  Secrets live in the DPAPI vault (`core/credential_provider.py`,
  `data/domain-credential.dpapi`, both outside version control).
- Memory files are Markdown, git-tracked, agent-neutral: no session IDs, no
  runtime-private context, nothing only one model can interpret.
- Keep the memory layer lean (currently four files). Adding a file requires
  updating this manifest and the AGENTS.md protocol.
