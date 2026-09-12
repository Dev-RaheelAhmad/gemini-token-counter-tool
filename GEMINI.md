# AI Guidelines & Security Rules

These rules apply to all AI coding agents, assistants, and automated tools operating on this repository.

## 1. Mandatory Pre-Action Safety Snapshots & Local Git Commits (CRITICAL TOP PRIORITY)
- **Pre-Modification Local Git Commit**: Whenever performing complex refactoring, implementing a new feature, or making any changes that might risk breaking the app, you MUST always create a clean local git commit (snapshot) before taking any action.
- **Safe Rollback Assurance**: This ensures that if an unexpected error occurs, tests fail, or the application breaks during execution, the workspace can be safely and cleanly reverted back to the previous working commit state without data loss.

## 2. Zero-Leak Confidentiality & Secrets Policy
- **Never Hardcode Secrets**: Under NO circumstances should any API key, OAuth token, client secret, Bearer token, password, private key (`.pem`, `.key`, `.pfx`), or cloud service credential be added to source code, comments, documentation, or commit messages.
- **Never Commit User Transcripts or State**: Never track, commit, or stage user `.jsonl` transcripts, local database files (`account_usage.json`, `account_ledger.jsonl`), `.env` files, or local config files. All user state must strictly reside in user-specific `%APPDATA%` / `$HOME` locations ignored by git.
- **Generic Testing & Documentation Fixtures**: When writing unit tests, examples, or documentation, always use RFC standard placeholder domains (e.g. `user@example.com`, `developer@company.org`) and dummy session UUIDs. Never use real personal or customer email addresses or tokens.

## 3. Dynamic Portability & Path Handling
- **No Hardcoded Machine Paths**: Never hardcode developer-specific absolute paths (such as `C:\Users\<user>`, `Z:\home\<user>`, `/home/<user>`).
- **Dynamic Resolution**: Always resolve paths dynamically using OS environment variables (`%USERPROFILE%`, `%APPDATA%`, `Path.home()`, `os.environ`), dynamic UNC WSL2 queries, or drive enumeration.
- **WSL Command Execution on Mapped Drives**: When invoking `wsl.exe` from Windows mapped network drives (such as `Z:`), always supply the explicit target directory using the `--cd` flag (e.g. `wsl --cd <path> <cmd>`) to prevent WSL path translation warnings, or prefer native Windows tooling (`git`).

## 4. Git Staging & Pre-Commit Hygiene
- **Pre-Commit Inspection**: Before executing `git commit` or proposing changes, verify `git status` and ensure untracked caches (`__pycache__`, `.pytest_cache`), logs (`*.log`), temporary exports (`*.tmp`, `*.csv`), or user credentials are not staged.
- **Respect .gitignore**: Strictly adhere to `.gitignore` defense-in-depth patterns.

## 5. Codebase Architecture & Integrity
- **0% Idle CPU Overhead**: All background watchers and file polling loops must maintain smart stat-based change detection with zero unnecessary subprocess invocations or idle wakeups.
- **Test Integrity**: Every modification to core engine, ledger, session discovery, or GUI modules must maintain 100% passing test coverage (`python -m unittest tests/test_all.py`).

## 6. Architectural Discovery & Graphify Usage
- **Graph-First Architecture Queries**: When exploring codebase structure, caller/callee relationships, cross-module dependencies, or evaluating change blast radius, always utilize Graphify (`graphify-out/graph.json` and Graphify MCP tools such as `query_graph`, `god_nodes`, `get_neighbors`) as the primary fast-path before performing ad-hoc file scans.
- **Incremental Knowledge Graph Sync**: When introducing new modules, abstractions, or structural changes, keep the knowledge graph synchronized by running `/graphify <absolute-path> --update` to maintain up-to-date dependency tracking.
- **Preserve Graph Artifacts**: Ensure generated graph artifacts in `graphify-out/` (`graph.json`, `GRAPH_REPORT.md`, `graph.html`) are preserved and maintained alongside codebase evolutions.

## 7. Mandatory Workflow Protocol & Real-Time Task Tracking
- **Mandatory Pre-Action Plan**: Always generate a clear, upfront implementation plan before modifying codebase files or executing impactful operational actions.
- **`task.md` Initialization**: Create and maintain a `task.md` tracking file in the project root containing an actionable checklist derived directly from the implementation plan before initiating work.
- **Continuous Progress Tracking**: Update `task.md` in real-time after each step or code change, checking off completed items (`- [x]`), marking active items (`- [/]`), and maintaining clear visibility on pending tasks (`- [ ]`).
- **Strict Non-Negotiable Adherence**: These workflow planning and real-time tracking steps are non-negotiable rules for all AI assistants, automated coding agents, and subagents operating on this repository.

## 8. Critical Workflow Protocol — Strict Branch Isolation & Safety
- **Active Development Branch**: You must strictly perform all coding, refactoring, operational tasks, and test executions on the designated development branch (`development` or `develop`).
- **Protected Production Branch**: The production branch (`main` / `master`) is strictly reserved for verified, stable releases. NEVER modify files, generate code, or execute commits directly on `main` / `master`.
- **Pre-Flight Branch Check**: Before making any changes, always verify the active branch using `git branch --show-current`. If currently on `main` or `master`, switch to the development branch immediately (`git checkout development` or `git checkout develop`).
- **Pre-Action Safety Commit**: Before executing complex refactoring or risky changes, create a clean local git snapshot so work can be rolled back safely if tests fail.
- **Gated Merge Policy**: Propose or perform merges into the production branch ONLY after all automated test suites, linting, and CI validation pipelines pass 100% with zero regressions.

## 9. Multi-Agent Programming Instruction

This task is related to software development and programming.

Analyze the task and, based on its scope and complexity, decide whether sub-agents are needed.

When sub-agents are useful, automatically create the appropriate specialized coding sub-agents and assign each a clear responsibility.

### Possible Sub-Agent Roles
- **Architect Agent** — system architecture, technology choices, and project structure.
- **Frontend Agent** — UI, UX, components, and client-side functionality.
- **Backend Agent** — APIs, business logic, and server-side functionality.
- **Database Agent** — database design, schemas, queries, and migrations.
- **DevOps Agent** — deployment, infrastructure, CI/CD, and configuration.
- **Testing Agent** — unit, integration, and end-to-end testing.
- **Security Agent** — authentication, authorization, vulnerabilities, and secure coding.
- **Code Review Agent** — code quality, bugs, maintainability, and best practices.
- **Documentation Agent** — technical documentation, setup instructions, and API documentation.
- **Research Agent** — unfamiliar technologies, libraries, APIs, or implementation approaches.

### Rules
- Do **not** create unnecessary sub-agents.
- Use only the agents required for the specific task.
- Create more specialized sub-agents when the task is complex or has multiple independent areas.
- For simple tasks, use the minimum number of agents or no sub-agents.
- Sub-agents must have clearly separated responsibilities.
- Coordinate their work and integrate everything into one complete, working product.

### For Each Selected Sub-Agent, Provide
1. **Agent Type**
2. **Responsibility**
3. **Expected Output**

Choose the sub-agents dynamically based on the task requirements and complexity.

## 🔍 Autonomous Coding Standard: Defensive Error Handling & 1-Click Traceability (CRITICAL)

When generating code, creating services, writing controllers, defining domain models, implementing queue jobs, executing artisan commands, or handling UI mutations (Filament / Livewire / Blade), you must proactively apply defensive error handling and direct 1-click traceability across all architectural layers. Every module, service, and business logic execution must implement strict, granular error handling to guarantee that any failure is immediately identifiable, traceable, and resolvable.

### 1. Exception Architecture & Throwing Standards
- **Strict Ban on Raw Exceptions**: Never throw raw `\Exception`, `\RuntimeException`, or generic `\Error`. Every exception must communicate domain intent.
- **Typed Domain Exceptions**: Always throw or wrap into domain-specific exceptions extending the base `App\Exceptions\DomainException` (or relevant framework domain bases).
- **Static Factory Constructors**: Exclusively instantiate domain exceptions via descriptive static factory methods (e.g., `ClassNameException::invalidTransition(...)`, `::thresholdExceeded(...)`, `::recordNotFound(...)`). Static factories must encapsulate:
  - Failing entity / model context (IDs, states, types)
  - Attempted vs. expected / permitted values
  - Actionable remediation advice for callers, operators, or end users
- **Deterministic Context Tagging Pattern**:
  Format every exception message with an explicit caller context prefix:
  `"[<ClassName>:<methodName>] <Clear explanation of failure>. Attempted value: [<val>], Allowed/Expected: [<allowed>]."`
- **Mandatory Exception Metadata**:
  Always populate:
  - `error_code`: Unique uppercase snake_case identifier (e.g., `WORKFLOW_INVALID_TRANSITION`, `INSUFFICIENT_STOCK`).
  - `details`: Associative array of runtime parameters, entity IDs, attempted action, and violated constraints.
  - `remediation`: Concrete remediation guidance guiding operators or developers on how to resolve the error.
  - `http_status`: Accurate HTTP status code (e.g., 400, 403, 404, 409, 422).
- **Root-Cause Exception Chaining**:
  When catching lower-level exceptions (e.g., `QueryException`, `GuzzleException`, `JsonException`), always preserve the root cause via the `$previous` parameter (`?Throwable $previous = null`) so full telemetry is preserved.

### 2. Catch Blocks, Resilience & Observability Standards
- **Zero-Swallowing Policy**:
  Suppressing exceptions without diagnostics or silently returning `null`, `false`, or empty fallback collections on critical business mutations is strictly forbidden. Never write empty `catch` blocks.
- **Selective & Scope-Specific Catching**:
  Catch specific exception types rather than broad catch-all `\Throwable` or `\Exception` blocks. If an outer boundary (middleware, global exception handler, queue worker, console command) catches `\Throwable` as a safety net, it must capture full diagnostics and never swallow failures silently.
- **Correlation Trace Context & Structured Logging**:
  Always log failures at `ERROR` or `CRITICAL` severity using `TraceContext::buildContext(...)`. This automatically attaches the correlation `trace_id`, `actor_id`, `tenant_id`, and `timestamp`:
  ```php
  Log::error("[ClassName:methodName] Failed to execute action: {$e->getMessage()}", TraceContext::buildContext([
      'entity_id'   => $entity->id ?? null,
      'action'      => '<action_name>',
      'payload'     => $payload ?? [],
      'stack_trace' => $e->getTraceAsString(),
  ]));
  ```

