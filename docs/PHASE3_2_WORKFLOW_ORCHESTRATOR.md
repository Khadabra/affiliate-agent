# Phase 3.2 — Workflow Orchestrator & Multi-Agent Coordination

Status: `IMPLEMENTED_AND_TESTED` locally on Python 3.12.

## Architecture

- `WorkflowDefinition` validates workflow metadata, unique steps, selectors,
  dependencies, mappings, retry settings, and acyclic dependency graphs.
- `WorkflowExecutor` coordinates the existing `AgentOrchestrator` sequentially;
  `src/affiliate_factory/orchestrator.py` remains the legacy affiliate
  workflow and is not replaced.
- Agents can be selected by stable `agent_id` or one unambiguous capability.
- Step input mappings use paths such as `input.text` and
  `steps.previous.output.text`. Output mappings write into structured workflow
  output paths.

## Lifecycle and failure behavior

Workflow statuses are `queued`, `running`, `paused`, `completed`, `failed`, and
`rejected`. Step dependencies must be completed before a step runs. A failed
step records its error and leaves downstream steps idle.

Retries are deterministic and step-configured. Only error types listed in
`retryable_errors` are retried; validation errors are not retried. Retry task
IDs are deterministic per execution/step/attempt, so recovery reuses a
completed persisted attempt instead of creating a duplicate task.

## Human approval

A step marked `requires_approval=True` completes its own agent task, then pauses
the workflow. The executor never approves automatically. `resume(...,
APPROVE)` continues downstream steps; `resume(..., REJECT)` terminates with
`rejected` and does not execute downstream steps.

## Persistence guarantee

SQLite default sinks use explicit transaction boundaries:

- agent task creation/update and its lifecycle event are committed atomically;
- workflow execution/step state and the corresponding workflow event are
  committed atomically;
- foreign keys remain enabled and stale workflow transitions are rejected;
- workflow definitions are stored with executions so resume/recovery can verify
  the same version.

Injected in-memory event sinks are intentionally separate from SQLite. They are
supported for isolated tests/local observers, but they do not provide
cross-storage atomicity. If persistence fails before a workflow state change,
the execution remains `queued` or `running` and `recover()` resumes it using
persisted task results where available.

## Scope boundary

This phase adds coordination infrastructure only. It does not implement real
research, writing, compliance, analytics, dashboard, Agent Office UI, paid AI
providers, social APIs, auto-posting, or specialist production agents.
