# ADR-003: Scenario Engine Design

**Status:** Accepted
**Date:** 2026-05-31

## Context

Phase 4 adds "what-if / scenario" MCP tools so an LLM can explore mutations of a model's
data without touching live instances. The brief says scenarios are sandboxed and must never
mutate live data, and that `metrics_config` must be declarative (§15 forbids a code-execution engine).

Two snapshot strategies were considered:

- **Snapshot-copy** — at `create_scenario`, copy the live instance data into the scenario row.
  The scenario is self-contained and reproducible, immune to later live edits.
- **Reference-and-recompute** — store only deltas; recompute against live instances on demand.
  The `base_snapshot_ref` name in the brief hints at this, but it complicates isolation.

## Decisions

### 1. Snapshot-copy (over reference-and-recompute)

`create_scenario` reads all alive instances (`deleted_at IS NULL`) for the model and stores
`[{"id": ..., "data": ...}, ...]` as `base_snapshot` in the `scenarios` row. Subsequent ops
(`apply_change`, `compute_metrics`, `compare_to_baseline`, `reset_scenario`) operate only on
`base_snapshot + changes` in memory, and write only to the `scenarios` table.

**Why:** Makes the sandbox invariant *structural* — live instances are never referenced after
snapshot time. No possibility of a scenario "accidentally" seeing live edits. The acceptance
test can verify this by running the full scenario lifecycle and then asserting that
`list_instances` on the live model is unchanged.

**Trade-off:** The snapshot grows with instance count. Acceptable at Phase 4 scale; a reference
strategy can be added later if needed.

### 2. Declarative aggregates only (no expression evaluator)

`metrics_config` format:
```json
{
  "metric_name": {"agg": "count|sum|avg|min|max", "field": "top_level_field_name"}
}
```

`count` needs no `field`. All other agg functions extract a top-level numeric field from each
instance's `data`. Non-numeric or missing values are skipped. `avg`/`min`/`max` over an empty
set return `null` (no ZeroDivisionError).

**Why:** §15 explicitly forbids arbitrary code execution in the scenario engine. This covers
the entire analytics use-case of the brief (aggregate metrics for what-if analysis) without
needing `eval()` or a DSL. Extension to computed columns or cross-field expressions is an
explicit non-goal for Phase 4.

### 3. `changes` as an append-only log

Each `apply_change` call appends one entry to `changes` JSONB. The working set is recomputed
by replaying the log against the snapshot. This makes `reset_scenario` trivial (clear the log)
and `compare_to_baseline` exact (replay zero changes for baseline, all changes for current).

### 4. `scenarios.status` is VARCHAR, not a PG enum

Avoids the asyncpg `CREATE TYPE` DDL collision documented in ADR-001 / feedback notes. Status
values (`"active"`, `"done"`) are validated in application code only.

## Rejected alternatives

- **User-supplied formulas / expression language**: would violate §15 and introduce a code
  execution surface. Ruled out regardless of demand.
- **Reference-and-recompute**: correct but complicates isolation and makes the sandbox harder
  to prove by test.
