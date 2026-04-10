# Execution Package

This package turns routing decisions into runnable tool work.

## Public Boundary

- `models.py`
  - stable execution contracts
- `runtime.py`
  - public entry points into execution

## Internal Implementation

- `planner.py`
  - converts `ExecutionIntent` into `ExecutionPlan`
- `planner_rules.py`
  - rule tables and helpers for planning
- `requests.py`
  - builds `ToolRequest` objects for each planned tool call
- `executor.py`
  - runs planned tool calls
- `merger.py`
  - merges tool results into one `ExecutionRun`
- `status.py`
  - derives per-call and aggregate execution status

## Layer Boundary

`ExecutionIntent`
-> `ExecutionPlan`
-> tool calls
-> `ExecutionRun`

Execution does not:

- perform ingestion
- perform object resolution
- classify dialogue act
- choose tools from scratch
- generate the final user-facing response

Execution does:

- plan tool calls
- run tool calls
- record execution metadata
- merge tool outputs into one structured run result
