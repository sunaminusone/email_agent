# Eval And Observability Design

## Goal

The eval and observability layer should make one question answerable:

> Is the architecture behaving correctly at each layer, and if not, where did it drift?

In short:

- `eval` verifies architectural behavior against expected outcomes
- `observability` records how one turn actually flowed through the stack
- together they prevent silent contract drift during refactors

This layer is not only about model quality.

It is about:

- contract integrity
- layer-by-layer correctness
- regression safety
- debug visibility

## Position In The Stack

Eval and observability are cross-cutting concerns.

They do not sit as one runtime layer between `response` and the user.

Instead, they attach to the architecture like this:

```text
memory
  -> ingestion
  -> objects
  -> routing
  -> tools
  -> execution
  -> response

eval / observability
  -> validates and traces each step above
```

That means:

- eval consumes layer inputs and outputs
- observability records layer decisions and artifacts
- neither should replace the typed runtime contracts

## Boundary

### In Scope

The eval and observability design should:

1. define what to test at each layer
2. define what to trace at each layer
3. define how regressions should be detected
4. define the minimum debug fields needed for production investigation
5. define how offline evaluation and online traces connect

### Out Of Scope

The eval and observability design should not:

- redefine runtime business logic
- act as a second routing layer
- invent new contracts that bypass runtime contracts
- require human inspection for every routine regression

## Core Design Principle

Every major runtime contract should have:

1. an offline evaluation surface
2. an online trace surface

That means the system should be able to answer both:

- "did this layer produce the expected output on a golden case?"
- "what exactly did this layer do on a real production turn?"

## Canonical Naming

The eval and observability design should align to the current architecture vocabulary:

- `IngestionBundle`
- `ResolvedObjectState`
- `ExecutionIntent`
- `ToolRequest`
- `ToolResult`
- `ExecutionPlan`
- `ExecutionRun`
- `ComposedResponse`
- `stateful_anchors`
- `resolved object constraint`

When routing subcontracts are evaluated or traced:

- `DialogueActResult`
- `ModalityDecision`

should be treated as routing-internal artifacts that are surfaced for testing and traceability.

## Why This Layer Is Necessary

Without this layer, the refactor can fail in subtle ways:

- ingestion may silently change signal provenance semantics
- objects may over-trust `stateful_anchors`
- routing may regress into world-selection
- tools may start rediscovering state instead of consuming injected constraints
- execution may merge results inconsistently
- response may become fluent but less grounded

A typed architecture without typed evaluation will drift.

## Evaluation Families

The design should support seven evaluation families.

### 1. Ingestion Eval

Question:

> Did the current turn produce the right normalized signals?

Recommended checks:

- `normalized_query`
- entity span extraction
- `normalized_value`
- signal `recency`
- signal `source_type`
- `reference_signals.attribute_constraints`
- `stateful_anchors` separation from current-turn evidence

Representative cases:

- explicit catalog number
- explicit service name
- implicit referential follow-up
- attribute-constrained referential follow-up
- attachment-bearing email turn

Primary failure mode:

- stale context being treated like fresh user evidence

### 2. Objects Eval

Question:

> Did the system resolve the right objects from the ingestion evidence?

Recommended checks:

- primary object
- secondary objects
- ambiguous object sets
- identifier binding
- `used_stateful_anchor`
- object provenance preservation through `evidence_spans`

Representative cases:

- unique product alias
- ambiguous product alias
- service alias
- operational identifier
- follow-up selection from candidate set

Primary failure mode:

- collapsing ambiguity too early or choosing the wrong active object

### 3. Routing Eval

Question:

> Given resolved objects, did routing make the right internal decisions and emit the right execution intent?

Recommended checks:

- `DialogueActResult`
- `ModalityDecision`
- selected tools
- clarification vs execution vs handoff
- `ExecutionIntent` completeness

Representative cases:

- `SELECTION`
- `ACKNOWLEDGE`
- `TERMINATE`
- `ELABORATE`
- product hybrid inquiry
- service technical inquiry
- operational status inquiry

Primary failure mode:

- routing regressing into ad hoc branch logic

### 4. Tool Eval

Question:

> Does each tool honor the injected contract and return the expected result family?

Recommended checks:

- `ToolRequest` contract compliance
- result status
- `structured_facts`
- `unstructured_snippets`
- artifact pointers
- no hidden session re-discovery

Representative cases:

- exact catalog lookup
- service technical RAG retrieval
- document lookup
- order lookup
- shipping lookup

Primary failure mode:

- tools bypassing constraints or returning unstructured ad hoc payloads

### 5. Execution Eval

Question:

> Did execution build the right plan, call tools in the right order, and merge results correctly?

Recommended checks:

- `ExecutionPlan.execution_mode`
- `PlannedToolCall.role`
- dependency ordering
- sequential vs parallel behavior
- `ExecutionRun.final_status`
- merged result shape

Representative cases:

- single-tool product lookup
- sequential product hybrid answer
- parallel hybrid answer
- partial tool failure fallback

Primary failure mode:

- execution hiding failed tool runs or merging results inconsistently

### 6. Response Eval

Question:

> Did the system produce a grounded, correct, and policy-safe final answer?

Recommended checks:

- response mode
- groundedness to execution results
- clarification quality
- no repeated detail on `ACKNOWLEDGE`
- soft reset behavior on `TERMINATE`
- `ELABORATE` progression based on `revealed_attributes`

Representative cases:

- direct answer
- hybrid answer
- clarification request
- handoff
- acknowledgement
- termination

Primary failure mode:

- fluent answers that no longer match execution output

### 7. End-To-End Thread Eval

Question:

> Does a real multi-turn conversation behave correctly across layers?

Recommended checks:

- clarification loop completion
- active object continuity
- topic shift handling
- thread memory updates
- final answer appropriateness

Representative cases:

- ambiguous alias -> selection -> product follow-up
- service question -> short follow-up -> elaboration
- stop current topic -> new question
- referential follow-up with no valid object -> clarification

Primary failure mode:

- individually correct layers that still compose badly across turns

## Evaluation Contracts

### `EvalCase`

Suggested shape:

```python
{
    "case_id": str,
    "layer": "ingestion" | "objects" | "routing" | "tools" | "execution" | "response" | "thread",
    "input": dict,
    "expected": dict,
    "tags": list[str],
}
```

### `EvalRun`

Suggested shape:

```python
{
    "run_id": str,
    "layer": str,
    "cases_run": int,
    "cases_passed": int,
    "failures": list[dict],
    "summary_metrics": dict,
}
```

### `EvalFinding`

Suggested shape:

```python
{
    "case_id": str,
    "layer": str,
    "severity": "low" | "medium" | "high",
    "expected": dict,
    "actual": dict,
    "reason": str,
}
```

These contracts should stay simple.

The runtime system does not need to consume them.

They exist so evaluation outputs are structured and comparable over time.

## Observability Contracts

Observability should mirror the architecture contracts rather than inventing a second telemetry language.

### `TurnTrace`

Suggested shape:

```python
{
    "thread_id": str,
    "turn_id": str,
    "query": str,
    "layer_traces": {
        "ingestion": dict,
        "objects": dict,
        "routing": dict,
        "tools": list[dict],
        "execution": dict,
        "response": dict,
    },
    "final_status": str,
}
```

### Layer-Level Trace Guidance

#### Ingestion Trace

Should include:

- normalized query
- extracted identifiers
- reference signals
- attachment summary
- `stateful_anchors` summary

Should not include:

- the entire raw parser blob if only a few fields matter

#### Objects Trace

Should include:

- object candidates
- primary object
- ambiguous sets
- whether a stateful anchor was used

#### Routing Trace

Should include:

- `DialogueActResult`
- `ModalityDecision`
- selected tools
- clarification or handoff flags
- reason string

#### Tool Trace

Should include:

- tool name
- request summary
- status
- latency
- compact result summary

#### Execution Trace

Should include:

- `ExecutionPlan`
- execution mode
- merge policy
- final status

#### Response Trace

Should include:

- response mode
- content block families used
- whether LLM rewrite ran
- memory updates emitted

## Metrics

The minimum useful metrics should be split by layer.

### Ingestion Metrics

- entity extraction accuracy
- reference-signal accuracy
- provenance correctness

### Objects Metrics

- primary object accuracy
- ambiguity preservation rate
- wrong-anchor reuse rate

### Routing Metrics

- dialogue-act accuracy
- modality accuracy
- execution-intent accuracy
- clarification precision

### Tool Metrics

- tool success rate
- empty-result rate
- latency
- constraint-compliance failures

### Execution Metrics

- plan correctness
- merge correctness
- partial-failure recovery rate

### Response Metrics

- groundedness
- repetition rate
- clarification helpfulness
- handoff appropriateness

### End-To-End Metrics

- task completion rate
- clarification resolution rate
- multi-turn success rate
- user-visible failure rate

## Golden Sets And Regression Suites

The design should encourage a layered golden-set strategy rather than one giant end-to-end suite only.

Recommended suite families:

- ingestion golden set
- object resolution golden set
- routing golden set
- tool smoke and contract tests
- execution merge regressions
- response rendering regressions
- end-to-end thread scenarios

This prevents one failing layer from being invisible inside a huge integrated test.

## Offline Eval vs Online Trace

Both are needed.

### Offline Eval

Use for:

- contract correctness
- release gating
- regression detection
- targeted architecture testing

### Online Trace

Use for:

- production debugging
- unknown failure investigation
- real-world latency and empty-result monitoring
- identifying missing eval cases

The rule should be:

- offline eval protects known expectations
- online traces reveal unknown failure modes

## Minimal Production Trace Policy

Even if the system does not ship a full observability stack at first, each turn should still record enough to debug architecture behavior.

Recommended minimum trace:

- query
- primary object summary
- routing summary
- selected tools
- tool statuses
- execution mode
- response mode

This is the minimum viable audit trail.

## Integration With Existing Tests

This design should absorb and extend current work such as:

- parser eval
- retrieval regression tests
- response generation regression tests
- turn resolution regressions

The goal is not to throw those away.

The goal is to regroup them under the new architecture.

## Migration Strategy

Recommended order:

1. define eval contracts
2. formalize trace payload shape
3. map current parser and retrieval tests into the new layer model
4. add object and routing golden sets
5. add execution merge regressions
6. add end-to-end thread scenarios

This keeps observability useful from the start instead of postponing it until after the refactor.

## Testing Strategy

The first implementation should aim to prove three things:

1. each layer emits the correct contract
2. each contract can be traced without ambiguity
3. end-to-end behavior improves rather than merely becoming more complicated

## Summary

The eval and observability layer should ensure that the new architecture is:

- testable
- debuggable
- regression-resistant
- explainable at the layer level

Without this layer, the architecture may still be elegant on paper while drifting in real usage.
