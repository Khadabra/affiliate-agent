# Phase 3.3 — Specialist Agents & Pre-flight Security Verification

Status: `IMPLEMENTED_AND_TESTED` locally on Python 3.12, with the existing
Windows symlink privilege limitation documented below.

## Pre-flight findings

### Symlink protection

`exporter.py` checks the unresolved target with `raw_target_dir.is_symlink()`
before canonical resolution and then enforces containment with `relative_to()`.
The four filesystem tests were executed directly and each failed to create its
test link with Windows `WinError 1314` (required privilege is not held by the
client). `fsutil behavior query SymlinkEvaluation` reports local symlink
evaluation enabled. This is an environment limitation on symlink creation,
not an observed exporter defect. The tests remain active and were not replaced
with mocks.

### In-memory event sink recovery

SQLite default workflow/task state and event writes remain atomic per operation.
When an injected in-memory workflow event sink fails after SQLite state is
committed, the executor now propagates `WorkflowPersistenceError` rather than
misclassifying the step as an agent failure. The non-terminal execution can be
recovered, and persisted agent task IDs/results prevent duplicate task
execution. Cross-storage atomicity is intentionally not claimed.

## Specialist agents

`specialist_agents.py` implements deterministic/manual-first agents:

- **ResearchAgent:** curated product input, audience/problems, evidence
  provenance, unsupported facts, and missing information.
- **ContentWriterAgent:** original TikTok/Instagram copy from supported facts;
  no seller/creator media copying and no unsupported claims.
- **FactCheckerAgent:** supported, unsupported, contradicted, and manual
  verification classifications using supplied evidence only.
- **ComplianceAgent:** delegates to the existing fail-closed compliance engine.
- **HumanApprovalGateAgent:** creates an explicit approval pause and never
  approves automatically.
- **ExportAgent:** applies explicit human claim verification and existing
  `approve_draft`/safe exporter gates.
- **AnalyticsAgent:** delegates to existing performance aggregation and
  preserves missing metrics as unknown.

`build_content_workflow()` provides the sequence:

`Research → Content Writer → Fact Checker → Compliance → Human Approval → Export`

Analytics is registered separately and is not forced into content generation.

No external browsing, scraping, paid API, real LLM integration, social API, or
automatic publishing was added.
