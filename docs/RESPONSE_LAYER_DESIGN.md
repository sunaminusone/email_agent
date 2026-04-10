# Response Layer Design

## Goal

The response layer should turn execution output into a grounded, natural, and
policy-safe final reply.

Its purpose is to answer one question:

> Given an `ExecutionRun`, how should the system express the result to the user without inventing facts or redoing upstream decisions?

In short:

- `execution` determines what happened
- `response` determines how to say it
- `memory` helps prevent repetition and supports layered follow-up behavior

## Position In The Stack

The intended architecture order is:

1. `ingestion`
2. `objects`
3. `routing`
4. `tools`
5. `execution`
6. `response`

More concretely:

1. `routing` emits `ExecutionIntent`
2. `execution` emits `ExecutionRun`
3. `response` consumes `ExecutionRun` and produces the final reply

## Boundary

### In Scope

The response layer should:

1. consume `ExecutionRun`
2. organize grounded content blocks
3. choose a response mode
4. render deterministic grounded drafts
5. optionally apply constrained LLM rewriting
6. emit one structured final response

### Out Of Scope

The response layer should not:

- re-run object resolution
- re-run routing
- re-select tools
- retrieve new evidence on its own
- invent facts not present in execution results

## Core Design Principle

The response layer is an expression layer, not a decision layer.

That means:

- routing decides what should be done
- execution determines what was found
- response decides how to present that result

The response layer may:

- organize
- summarize
- lightly rewrite

but it may not:

- silently change business meaning
- override a clarification requirement
- fabricate missing facts

## Canonical Naming

The response design should align to the current architecture vocabulary:

- `ExecutionRun`
- `ResponseInput`
- `ResponsePlan`
- `ComposedResponse`
- `content_blocks`
- `revealed_attributes`
- `resolved object`
- `grounded snippets`

Avoid older mixed terms when the document really means:

- expression mode
- grounded content assembly
- constrained rewrite

## Core Contracts

### `ResponseInput`

Suggested shape:

```python
{
    "query": str,
    "execution_run": ExecutionRun,
    "resolved_object_state": ResolvedObjectState,
    "dialogue_act": DialogueActResult,
    "response_memory": dict,
}
```

Recommended interpretation:

- `execution_run`
  - the primary source of truth for grounded result material
- `resolved_object_state`
  - optional object metadata helpful for acknowledgements and continuity phrasing
- `dialogue_act`
  - interaction context such as `ACKNOWLEDGE`, `ELABORATE`, or `TERMINATE`
- `response_memory`
  - state such as `revealed_attributes` and `last_response_topics`

### `ResponsePlan`

Suggested shape:

```python
{
    "response_mode": "clarification" | "direct_answer" | "hybrid_answer" | "acknowledgement" | "termination" | "handoff",
    "primary_content_blocks": list[dict],
    "supporting_content_blocks": list[dict],
    "should_use_llm_rewrite": bool,
    "should_acknowledge_object": bool,
    "memory_updates": dict,
    "reason": str,
}
```

Recommended interpretation:

- `response_mode`
  - the high-level reply type
- `primary_content_blocks`
  - the grounded answer spine
- `supporting_content_blocks`
  - additional supporting content
- `should_use_llm_rewrite`
  - whether the final message should go through constrained natural-language polishing
- `should_acknowledge_object`
  - whether the object should be lightly surfaced in the reply
- `memory_updates`
  - response-driven state updates such as revealed attributes or soft reset

### `ComposedResponse`

Suggested shape:

```python
{
    "message": str,
    "response_type": str,
    "content_blocks": list[dict],
    "citations": list[dict],
    "debug_info": dict,
}
```

Recommended interpretation:

- `message`
  - the final user-facing response text
- `response_type`
  - the normalized reply category
- `content_blocks`
  - the grounded blocks used to assemble the response
- `citations`
  - optional evidence references for debugging or structured trace output

## Response Modes

The first implementation should support six response modes.

### 1. `clarification`

Used when execution cannot proceed safely because ambiguity or missing
identifiers remain.

Examples:

- multiple matching products
- missing referential target
- unresolved identifier type

### 2. `direct_answer`

Used when one tool or one merged result can answer the question directly.

Examples:

- product facts from catalog lookup
- order status
- invoice detail

### 3. `hybrid_answer`

Used when the final answer combines more than one result type.

Examples:

- structured product facts plus technical RAG snippets
- service RAG plus supporting document artifacts

### 4. `acknowledgement`

Used for short non-informational confirmations.

Examples:

- `ok`
- `thanks`
- `got it`

### 5. `termination`

Used when the user wants to stop the current topic.

Examples:

- `stop`
- `that's all`
- `别说了`

### 6. `handoff`

Used when the system should not continue automatically.

Examples:

- policy-required escalation
- unresolved high-risk ambiguity
- unsupported operational case

## Content Blocks

The response layer should not consume raw tool outputs directly in renderers.

It should first normalize them into grounded content blocks.

Recommended block families:

- `object_summary`
- `structured_facts`
- `technical_snippets`
- `document_artifacts`
- `clarification_options`
- `handoff_notice`

### Why Content Blocks Matter

They make it possible to:

- keep renderers simpler
- standardize grounded input across product, service, and operational answers
- support deterministic fallback even when LLM rewrite is disabled or fails

## Content Assembly

This is the first major step in the response layer.

It should transform `ExecutionRun` into normalized content blocks.

Examples:

### Product Hybrid Result

- `object_summary`
  - product name, catalog number, business line
- `structured_facts`
  - applications, species, lead time, pricing if applicable
- `technical_snippets`
  - validation or protocol text

### Service Technical Result

- `object_summary`
  - service name
- `technical_snippets`
  - service plan, workflow, model support, validation
- `document_artifacts`
  - optional related files or references

### Clarification Result

- `clarification_options`
  - candidate items
  - guidance for what the user should reply with

## Response Planning

After content assembly, the response layer should choose a `ResponsePlan`.

The planner should consider:

- `ExecutionRun.final_status`
- `DialogueActResult`
- whether the result is clarification, direct, or hybrid
- response-memory state such as `revealed_attributes`

This planner should not inspect raw storage or raw parser output.

## Renderer vs Composer

The response layer should be split into two responsibilities:

### 1. Renderer

The renderer should:

- use deterministic logic
- turn content blocks into a grounded draft
- apply response-mode specific structure

Examples:

- clarification renderer
- product renderer
- technical renderer
- document renderer
- handoff renderer

### 2. Composer

The composer should:

- optionally apply constrained LLM rewriting
- preserve all grounded facts
- improve fluency and customer-facing tone

This should remain a narrow rewrite layer, not a free-form generation layer.

## Grounded Rewrite Rule

If an LLM rewrite is used, it must obey these rules:

- use only grounded content blocks
- do not invent facts
- do not change identifiers or technical values
- keep the response concise and customer-safe
- fall back to deterministic rendering on failure

This preserves the advantages of:

- deterministic structure
- grounded evidence
- more natural language when helpful

## Memory Interaction

The response layer should read and update response-specific memory carefully.

### Read From Memory

Useful inputs:

- `revealed_attributes`
- `last_response_topics`
- `last_tool_results`

### Write To Memory

Useful updates:

- mark newly revealed attributes
- record response topics
- clear topic-specific state on termination

### Example: `ELABORATE`

If the user asks:

- `tell me more`
- `do you have more information?`

the response layer should:

1. inspect `revealed_attributes`
2. avoid repeating the same exact information block
3. prefer the next grounded layer of detail when available

## Soft Reset

The response layer should support `termination` without full amnesia.

When a termination response is emitted, the response plan should request
topic-level memory cleanup such as:

- clear `active_object`
- clear pending clarification
- clear `revealed_attributes`
- clear current-topic `last_tool_results`

It should not erase the entire thread history.

## Ideal Directory Shape

Ignoring the current repo layout, the ideal shape would be:

```text
src/response/
  __init__.py
  contracts.py
  blocks.py
  policy.py
  planner.py
  composer.py
  prompts.py
  renderers/
    clarification_renderer.py
    product_renderer.py
    technical_renderer.py
    document_renderer.py
    handoff_renderer.py
```

## Module Responsibilities

### `contracts.py`

Defines:

- `ResponseInput`
- `ResponsePlan`
- `ComposedResponse`

### `blocks.py`

Responsible for grounded content assembly.

### `policy.py`

Defines response-mode selection rules.

### `planner.py`

Builds `ResponsePlan` from `ResponseInput`.

### `composer.py`

Handles optional constrained LLM rewriting.

### `prompts.py`

Holds bounded rewrite prompts for grounded response composition.

### `renderers/`

Contain mode-specific deterministic rendering logic.

## Current Codebase Mapping

The current codebase already contains response-like behavior in:

- [response/chain.py](/Users/promab/anaconda_projects/email_agent/src/response/chain.py)
- [response/content/blocks.py](/Users/promab/anaconda_projects/email_agent/src/response/content/blocks.py)
- [responders/renderers/product_renderer.py](/Users/promab/anaconda_projects/email_agent/src/responders/renderers/product_renderer.py)
- [responders/renderers/technical_renderer.py](/Users/promab/anaconda_projects/email_agent/src/responders/renderers/technical_renderer.py)
- [responders/renderers/document_renderer.py](/Users/promab/anaconda_projects/email_agent/src/responders/renderers/document_renderer.py)

The current strengths are:

- grounded block-like structure already exists
- deterministic renderers already exist
- constrained rewrite has already begun in some renderers

The current gap is:

- response policy is still partially distributed
- execution results are not yet the single canonical input
- mode selection is not yet fully explicit

## Migration Strategy

### Phase 1: Define Response Contracts

- define `ResponseInput`
- define `ResponsePlan`
- define `ComposedResponse`

### Phase 2: Standardize Content Blocks

- normalize product, service, and operational outputs into shared block families

### Phase 3: Make Response Consume `ExecutionRun`

- stop letting individual renderers infer too much from scattered upstream state
- use merged execution output as the primary response input

### Phase 4: Narrow LLM Rewrite To A Constrained Composer

- preserve deterministic fallback
- move free-form naturalization into one bounded place

### Phase 5: Connect Response Memory

- formalize `revealed_attributes`
- formalize soft reset
- formalize response-topic continuity

## Testing Strategy

The response layer should be validated at four levels:

### 1. Content Block Tests

Test whether `ExecutionRun` is transformed into the correct block families.

### 2. Response Mode Tests

Test whether the planner selects:

- clarification
- direct answer
- hybrid answer
- acknowledgement
- termination
- handoff

correctly.

### 3. Renderer and Composer Tests

Test whether:

- deterministic renderers stay grounded
- constrained rewrite preserves facts
- fallback behavior works when rewrite fails

### 4. Multi-Turn Response Memory Tests

Test whether:

- `ELABORATE`
- `ACKNOWLEDGE`
- `TERMINATE`

interact correctly with `revealed_attributes` and soft reset behavior.

## Summary

The response layer should be the grounded expression layer of the agent.

Its job is simple:

1. consume `ExecutionRun`
2. organize grounded content
3. choose a response mode
4. render a deterministic draft
5. optionally apply constrained natural-language composition
6. emit one final grounded reply

That separation is what will make:

- replies more natural
- clarification behavior cleaner
- hybrid results easier to explain
- memory-driven elaboration less repetitive
