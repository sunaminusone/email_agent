# Executor Package

This package turns routing decisions into runnable tool work.

## Public Boundary

- `__init__.py`
  - public entry points: `run_executor`, `empty_execution_run`
- `models.py`
  - contracts: `ExecutionResult`, `ExecutionContext`, `MergedResults`

## Internal Implementation

- `engine.py`
  - reasoning loop: select -> build -> dispatch -> evaluate -> repeat
- `tool_selector.py`
  - registry-based tool selection (replaces hardcoded planner_rules)
- `request_builder.py`
  - builds `ToolRequest` objects for each selected tool
- `merger.py`
  - merges tool results and derives aggregate execution status
- `completeness.py`
  - evaluates whether results are sufficient or need retry

## Layer Boundary

`run_executor(ingestion_bundle, resolved_object_state, route_decision, memory_snapshot)`
-> reasoning loop (select tools -> dispatch -> evaluate)
-> `ExecutionResult`

Execution does not:

- perform ingestion
- perform object resolution
- classify dialogue act
- generate the final user-facing response

Execution does:

- select tools from the registry based on context
- build and dispatch tool calls
- evaluate result completeness
- retry with fallback tools when results are insufficient
