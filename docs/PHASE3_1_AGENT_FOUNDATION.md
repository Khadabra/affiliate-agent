# Phase 3.1 — Agent Foundation

Status: `IMPLEMENTED_AND_TESTED` locally on Python 3.12. The foundation is
provider-neutral and does not implement specialist affiliate agents yet.

## Boundaries

- `orchestrator.py` remains the existing affiliate content workflow.
- `agent_orchestrator.py` owns generic, sequential execution of one registered
  agent task at a time.
- All task input/output and lifecycle events use Pydantic contracts.
- SQLite persistence is additive through `agent_tasks` and `agent_events`.
- Human approval and manual export remain in the existing workflow; agent
  execution cannot approve or publish content.

## Components

| Component | Module | Responsibility |
|---|---|---|
| Contracts | `agent_contracts.py` | `AgentTask`, `AgentResult`, `AgentEvent`, metadata, errors, statuses |
| Base interface | `agent.py` | Declares metadata, input/output models, and validation boundary |
| Context | `agent_context.py` | Injects SQLite, configuration, logger, provider, task context, and event sink |
| Event sinks | `agent_events.py` | In-memory or SQLite event publication |
| Registry | `agent_registry.py` | Explicit registration, lookup, duplicate protection, metadata listing |
| Provider boundary | `agent_provider.py` | Future local/external provider contract and typed unavailable/error/timeout failures |
| Execution | `agent_orchestrator.py` | Sequential lifecycle, validation, result/error capture, and event publication |

## Lifecycle

`idle → queued → running → completed|failed`

Invalid transitions, including terminal-state reuse, are rejected. A normal
execution emits `task_created`, `task_queued`, `agent_started`, and either
`agent_completed` or `agent_failed`. Events carry task, agent, and correlation
identifiers and are ordered by SQLite insertion sequence.

## Provider status

The existing `LLMAdapter` is reusable through `LLMAdapterProvider`. No paid API,
network client, credential loader, or fake production provider was added. A
missing provider raises `ProviderUnavailableError`; adapter timeout and other
exceptions are mapped to typed provider errors.

## Persistence safety

Schema initialization is backward-compatible and additive. `agent_events.task_id`
references `agent_tasks.task_id`, and the existing per-connection
`PRAGMA foreign_keys = ON` remains active. Tests use temporary SQLite databases.
