# Routing Design v4

## Purpose

Routing is the **classification** layer of the v4 CSR co-pilot. It answers
one question: **what kind of posture does this incoming inquiry have?**

Four possible classifications:
- **execute** — the inquiry is straightforward, retrieve & draft directly
- **respond** — pure acknowledgement, no retrieval needed (e.g., "thanks", "bye")
- **clarify** — the agent thinks the inquiry is ambiguous; the rep should
  consider asking the customer for more detail
- **handoff** — the agent thinks this needs expert / AE input; the rep
  should consider escalating

**v4 critical change**: `clarify` and `handoff` classifications are
**advisory metadata**, not gates. The dispatch in
`src/app/service.py::_run_agent_loop` coerces every group to the `execute`
path regardless of original classification, and the original judgment is
preserved on `route_decision.reason` as an `AI_ROUTING_NOTE` string that
the CSR renderer surfaces in a ⚠️ section of the draft. The rep sees
the agent's judgment without losing the retrieval value of running
through to execute.

The classification logic in this document is still correct (and is useful
both as documentation of the agent's reasoning and as future-proofing if
gating ever needs to come back). What changed is purely the dispatch.

Routing also classifies one supporting signal:
- **dialogue act** — what the customer is trying to do (inquiry, selection, closing)

### What routing does NOT do (v3 changes)

1. **Routing does not select tools.** In v2, `routing/stages/tool_routing.py` picked specific tools. In v3, tool selection moves to the executor, which reads tool capabilities from the registry.

2. **Routing does not classify modality.** In v2, `routing/stages/modality.py` determined the information retrieval type (structured/unstructured/external/hybrid). In v3, the executor derives this from ingestion `request_flags` and the tool registry. Modality was a lossy compression of request_flags — `needs_price` is more actionable than `structured_lookup`.

## Contract With the Executor

### What routing sends

```python
class RouteDecision(BaseModel):
    """Output of the routing module."""
    action: Literal["execute", "respond", "clarify", "handoff"]
    dialogue_act: DialogueActResult
    clarification: ClarificationPayload | None = None
    reason: str = ""
```

### What the executor reads from RouteDecision

The executor reads exactly one field:

```python
# In executor/engine.py
context = ExecutionContext(
    dialogue_act=route_decision.dialogue_act,     # <-- from routing
    query=...,                                     # from ingestion
    primary_object=...,                            # from objects
    request_flags=...,                             # from ingestion
    ...
)
```

The executor does **not** read:
- `action` — `service.py` checks this; executor is only called when `action == "execute"`
- `clarification` — the responser reads this for composing clarification replies
- `reason` — for observability only

### What routing does NOT send

| v2 field | v3 status | Why |
| --- | --- | --- |
| `selected_tools` | **removed** | Executor selects tools from registry |
| `modality_decision` | **removed** | Executor derives retrieval needs from `request_flags` |
| `primary_object` | **removed** | Executor reads `ResolvedObjectState` directly |
| `secondary_objects` | **removed** | Same |
| `resolved_object_constraints` | **removed** | Same |
| `needs_clarification` | **replaced by** `action == "clarify"` | Simpler |
| `handoff_required` | **replaced by** `action == "handoff"` | Simpler |

### Why modality was removed

In v2, modality told the executor what type of information retrieval to use. In v3, this is redundant because:

1. **request_flags are more specific.** `needs_price=True` directly maps to `pricing_lookup_tool`. `structured_lookup` loses this specificity.

2. **Multi-intent breaks modality.** "Check my order and explain CAR-T mechanism" needs both `external_api` and `unstructured_retrieval`. Modality can only return one `primary_modality` — setting `hybrid` is too vague for the executor to act on.

3. **The executor has the tool registry.** Each tool declares `supported_modalities` in its `ToolCapability`. The executor matches tools against `object_type + request_flags + dialogue_act` directly, without needing a pre-classified modality.

The executor derives retrieval needs internally:

```python
def _derive_retrieval_needs(request_flags, primary_object) -> set[str]:
    needs = set()
    if request_flags:
        if any([request_flags.needs_price, request_flags.needs_availability,
                request_flags.needs_comparison]):
            needs.add("structured_lookup")
        if any([request_flags.needs_protocol, request_flags.needs_documentation,
                request_flags.needs_troubleshooting]):
            needs.add("unstructured_retrieval")
        if any([request_flags.needs_order_status, request_flags.needs_shipping_info,
                request_flags.needs_invoice]):
            needs.add("external_api")

    # Object type fallback when no request_flags match
    if not needs and primary_object:
        _OBJECT_TYPE_DEFAULTS = {
            "product": {"structured_lookup"},
            "order": {"external_api"}, "invoice": {"external_api"},
            "shipment": {"external_api"}, "customer": {"external_api"},
            "service": {"unstructured_retrieval"},
            "document": {"unstructured_retrieval"},
            "scientific_target": {"unstructured_retrieval"},
        }
        needs = _OBJECT_TYPE_DEFAULTS.get(
            primary_object.object_type, {"structured_lookup"}
        )

    return needs or {"structured_lookup"}
```

### Flow through service.py (v4 CSR mode)

In v4 the routing decision never short-circuits the executor. Whatever the
classifier returns (`execute` / `clarify` / `handoff` / `respond`) is coerced
to `execute`; the original judgment is preserved on `route_decision.reason`
as an `AI_ROUTING_NOTE` so the renderer can surface it to the rep.

```python
# In app/service.py::_run_agent_loop

route = routing.route(ingestion_bundle, resolved_object_state)

# CSR-mode invariant: every route runs the executor; original judgment
# becomes advisory metadata, not a gate.
if route.action != "execute":
    route = route.model_copy(update={
        "action": "execute",
        "reason": f"AI_ROUTING_NOTE original_action={route.action} | {route.reason or ''}",
    })

execution_result = executor.run(
    ingestion_bundle, resolved_object_state, route, memory_snapshot
)

# csr_draft renderer reads execution results AND the AI_ROUTING_NOTE on
# route.reason; it shows historical threads + KB chunks + ⚠️ routing notes.
response = responser.respond(ingestion_bundle, route, execution_result)
```

Three modules read the RouteDecision:
1. **service.py** coerces `route.action` to `execute` and preserves the
   original action as an `AI_ROUTING_NOTE` on `route.reason`.
2. **executor** reads `route.dialogue_act` to build execution context.
3. **csr_draft renderer** reads `route.reason` for `AI_ROUTING_NOTE`
   entries and surfaces them as advisory notes in the rep-facing draft.

## Current State Analysis

### What exists (`src/routing/`)

| File | Role | v3 status |
| --- | --- | --- |
| `orchestrator.py` | Coordinates all routing stages | **Simplify** — remove tool selection + modality stages, add action determination |
| `runtime.py` | Bridges ingestion data to routing functions | **Keep** — adapter pattern still valid |
| `models.py` | Data models (RoutingDecision, ExecutionIntent, etc.) | **Simplify** — flatten into RouteDecision, remove ModalityDecision |
| `vocabulary.py` | Term sets and type literals | **Keep** — remove ToolName, remove ModalityType, update DialogueActType |
| `utils.py` | Text normalization helpers | **Keep** as-is |
| `stages/dialogue_act.py` | Classify intent type | **Enhance** — simplify to 3 acts, add stateful_anchors awareness, add Level 2 |
| `stages/modality.py` | Determine information modality | **Delete** — executor derives retrieval needs from request_flags |
| `stages/object_routing.py` | Validate object state for routing | **Keep** as-is |
| `stages/tool_routing.py` | Select specific tools | **Delete** — moved to executor |
| `policies/clarification.py` | Decide when to clarify | **Enhance** — add ingestion signal awareness |
| `policies/handoff.py` | Decide when to escalate | **Keep** as-is |
| `policies/assembly.py` | Result assembly metadata | **Delete** — executor handles assembly |

### Core problems in v2

1. **Tool selection in routing.** `tool_routing.py` hardcodes object_type to tool mappings. This is the executor's job.

2. **Modality is redundant.** `modality.py` classifies retrieval type from object_type + keywords. The executor can derive this from `request_flags` (more specific) + tool registry (self-describing). Modality is a lossy intermediate step.

3. **ExecutionIntent is overloaded.** Carries routing decisions, object data, and execution data — three responsibilities in one model.

4. **Dialogue act classification is keyword-only.** Falls to UNKNOWN (0.35 confidence) when no pattern matches. No LLM fallback for ambiguous cases.

5. **No action: respond.** ACKNOWLEDGE and TERMINATE still route to executor, which runs a full reasoning loop only to do nothing.

### What to keep

- **`stages/dialogue_act.py`** — pattern-matching logic is solid for ~85% of queries. Simplify acts and add Level 2.
- **`stages/object_routing.py`** — clean conversion from `ResolvedObjectState` to routing's internal representation.
- **`policies/clarification.py`** — solid clarification logic. Minor enhancement for ingestion signals.
- **`policies/handoff.py`** — simple and correct.
- **`runtime.py`** — adapter pattern from ingestion to routing input.
- **`vocabulary.py`** — term sets are reusable. Remove ToolName and ModalityType.

## v3 Design

### Module Boundary

```
Input:
  - IngestionBundle         (parsed customer message)
  - ResolvedObjectState     (resolved entities)

Output:
  - RouteDecision           (action + dialogue_act + clarification)
```

Routing reads ingestion signals and object state, but does **not** read tool capabilities, session memory, or modality. It focuses on two decisions: what kind of action is needed, and what is the customer trying to do.

Note on session awareness: routing accesses limited session state through `IngestionBundle.stateful_anchors`, which carries `pending_clarification_field`, `active_route`, and active entity info. This is populated by the ingestion module from memory, so routing does not import or read memory directly.

### Entry Point

```python
def route(
    ingestion_bundle: IngestionBundle,
    resolved_object_state: ResolvedObjectState,
) -> RouteDecision:
```

This replaces `route(routing_input: RoutingInput)`. The new signature takes upstream contracts directly instead of wrapping them in `RoutingInput`.

### Routing Pipeline

```
IngestionBundle + ResolvedObjectState
          |
          v
  +----------------+
  | Object Routing  |  Validate objects, detect ambiguity
  +-------+--------+
          | RoutedObjectState (internal)
          v
  +----------------+
  | Dialogue Act    |  What is the customer trying to do?
  |                 |  Level 1: patterns + stateful_anchors
  |                 |  Level 2: LLM classifier (if no match)
  +-------+--------+
          | DialogueActResult
          v
  +----------------+
  | Policies        |  Should we clarify? Handoff?
  |  - clarification|  + action determination
  |  - handoff      |
  |  - action       |
  +-------+--------+
          |
          v
      RouteDecision    (assembled in orchestrator.py)
```

Compared to v2, the pipeline is shorter: no `modality` stage, no `tool_routing` stage, no `assembly_policy` stage. The final RouteDecision is assembled directly in `orchestrator.py` after all stages complete.

### Stage 1: Object Routing (unchanged)

Converts `ResolvedObjectState` into routing's internal `RoutedObjectState`. This stage:
- Detects ambiguity (`ambiguous_sets` non-empty -> `should_block_execution`)
- Resolves primary object vs. active object
- Sets routing status (`resolved`, `contextual_reuse`, `unresolved`, `ambiguous`)

**No changes from v2.** The existing `object_routing.py` is clean and correct.

### Stage 2: Dialogue Act Classification (simplified + two-level)

Classifies what the customer is trying to do. Simplified from 6 acts to 3:

| Act | Meaning | Example | v2 equivalent |
| --- | --- | --- | --- |
| `inquiry` | Asking for information or action | "What is PM-AB0001?" | INQUIRY + ELABORATE |
| `selection` | Choosing from prior options | "The first one" | SELECTION |
| `closing` | Thanking, confirming, or ending | "Thanks, bye" | ACKNOWLEDGE + TERMINATE |

The old `ELABORATE` is replaced by `inquiry` with `is_continuation=True`. The old `UNKNOWN` is eliminated — Level 2 resolves ambiguous cases instead of returning a useless label.

**Level 1 (deterministic + stateful_anchors awareness):**

```python
def resolve_dialogue_act(query, object_routing, *, stateful_anchors=None):
    text = normalize_routing_text(query or "").strip()
    if not text:
        return DialogueActResult(act="closing", reason="Empty turn")

    # Stateful anchors awareness: pending clarification biases toward selection
    if stateful_anchors and stateful_anchors.pending_clarification_field:
        if _looks_like_selection(text, object_routing):
            return DialogueActResult(
                act="selection", confidence=0.90,
                reason="Selection in response to pending clarification",
                matched_signals=["pending_clarification", "selection_pattern"],
                requires_active_object=True,
                selection_value=query.strip(),
            )

    # Pattern matching (same patterns as v2, mapped to 3 acts)
    if any(p in text for p in TERMINATE_PATTERNS):
        return DialogueActResult(
            act="closing", confidence=0.92,
            reason="Explicit stop or closure signal.",
            matched_signals=["terminate_pattern"],
        )

    if _looks_like_selection(text, object_routing):
        return DialogueActResult(
            act="selection", confidence=0.88,
            reason="Selects one candidate from prior context.",
            matched_signals=["selection_pattern"],
            requires_active_object=True,
            selection_value=query.strip(),
        )

    if any(p in text for p in ELABORATE_PATTERNS):
        return DialogueActResult(
            act="inquiry", is_continuation=True, confidence=0.82,
            reason="Asks for expansion on a prior topic.",
            matched_signals=["elaboration_pattern"],
            requires_active_object=object_routing.active_object is not None,
        )

    if _looks_like_acknowledgement(text):
        return DialogueActResult(
            act="closing", confidence=0.81,
            reason="Acknowledges the prior response.",
            matched_signals=["acknowledgement_pattern"],
        )

    if _looks_like_inquiry(text):
        return DialogueActResult(
            act="inquiry", confidence=0.84,
            reason="Asks for information or action-oriented detail.",
            matched_signals=["inquiry_pattern"],
        )

    # No pattern matched -> Level 2
    return _llm_classify_dialogue_act(query, object_routing, stateful_anchors)
```

Key changes from v2:
- Instead of returning `UNKNOWN (0.35)` when no pattern matches, Level 1 directly calls Level 2. No confidence threshold — Level 2 activates when Level 1 has no answer.
- `stateful_anchors` provides pending clarification state, allowing Level 1 to correctly handle "sure" after a disambiguation prompt.

**Level 2 (LLM classifier):**

Activates only when Level 1 finds no matching pattern (~15% of messages).

```python
def _llm_classify_dialogue_act(query, object_routing, stateful_anchors=None):
    """LLM fallback for dialogue act classification."""
    ...
```

LLM prompt (uses stateful_anchors, not memory):

```
You are classifying a customer support message for a biotech company.

Customer message: "{query}"
Resolved entity: {primary_object or "none"}
Conversation state: {stateful_anchors.active_route or "new"}
Pending clarification: {stateful_anchors.pending_clarification_field or "none"}

Classify the customer's intent:
- inquiry: asking for information or requesting an action
- selection: choosing from previously offered options
- closing: confirming, thanking, or ending the conversation

Also determine:
- is_continuation: true if this continues a prior topic, false if new question

Output: {"act": "...", "is_continuation": true/false, "confidence": 0.0-1.0, "reason": "..."}
```

**When Level 2 makes a difference:**

| Message | Level 1 | Level 2 |
| --- | --- | --- |
| "sure" (no pending clarification) | No pattern -> Level 2 | closing (0.82) — casual confirmation |
| "sure" (pending clarification) | selection (0.90) — stateful anchors | N/A — Level 1 handles it |
| "and the pricing?" | inquiry (0.84) | inquiry, is_continuation=True (0.88) |
| "I'll take that" | No pattern -> Level 2 | selection (0.90) — purchase intent |
| "这个抗体多少钱？" | No pattern -> Level 2 | inquiry (0.91) — non-English |

### Stage 3: Policies + Action Determination

**Action determination** — maps dialogue_act + policy results to action:

```python
def determine_action(dialogue_act, clarification, handoff_required):
    if handoff_required:
        return "handoff"
    if clarification is not None:
        return "clarify"
    if dialogue_act.act == "closing":
        return "respond"
    return "execute"
```

Rules (evaluated in order):
1. **Handoff** takes highest priority (safety concern)
2. **Clarification** takes second priority (can't execute without information)
3. **Closing** acts skip executor — no tools needed, responser composes farewell/acknowledgment directly
4. Everything else **executes**

**Clarification policy** — decides when to ask for more information:

```python
def decide_clarification(object_routing, dialogue_act, *, ingestion_signals=None):
    # Existing: object ambiguity
    if object_routing.ambiguous_objects:
        return _build_disambiguation_clarification(object_routing)

    # Existing: selection without context
    if dialogue_act.act == "selection" and not object_routing.primary_object:
        return _build_selection_context_clarification()

    # New: ingestion flagged missing critical info
    if ingestion_signals and ingestion_signals.missing_information:
        critical = _filter_critical_missing(
            ingestion_signals.missing_information, object_routing
        )
        if critical:
            return _build_missing_info_clarification(critical)

    return None
```

**Critical missing information** — defined per object type. Only information that prevents the executor's primary tool from running is considered critical:

```python
# Information without which the primary tool cannot execute
_CRITICAL_FIELDS = {
    "order":    {"order_number", "customer_identifier"},
    "invoice":  {"invoice_number", "customer_identifier"},
    "shipment": {"order_number", "tracking_number"},
}

def _filter_critical_missing(missing_info, object_routing):
    obj_type = _get_primary_object_type(object_routing)
    required = _CRITICAL_FIELDS.get(obj_type, set())
    return [info for info in missing_info if info in required]
```

Products and services have no critical fields — the executor can always attempt a fuzzy search.

**Handoff policy** — unchanged. Triggers on `needs_human_review` or `risk_level in {"high", "critical"}`.

### Multi-Intent Awareness

Customer messages often contain multiple intents:

> "Check my order for PM-CAR0001 and also explain the CAR-T construct mechanism"

Routing does not decompose multi-intent messages. It classifies the primary dialogue act (`inquiry`) and lets the executor handle tool decomposition. The executor has access to:
- `request_flags` — `needs_order_status=True` and `needs_documentation=True` (both set by ingestion)
- `ResolvedObjectState` — `primary_object=order`, `secondary_objects=[product]`
- Tool registry — knows which tools handle orders vs. technical queries

This is a cleaner boundary than v2's `modality=hybrid`, which told the executor "you need multiple retrieval types" without specifying which ones. With request_flags, the executor knows *exactly* what is needed.

## Data Contracts

### RouteDecision (output contract)

Replaces v2's `RoutingDecision` + `ExecutionIntent`. Much simpler.

```python
class RouteDecision(BaseModel):
    """The routing module's output."""
    action: Literal["execute", "respond", "clarify", "handoff"]
    dialogue_act: DialogueActResult
    clarification: ClarificationPayload | None = None
    reason: str = ""
```

### DialogueActResult (simplified)

Reduced from 6 acts to 3. `is_continuation` replaces the old `ELABORATE` act.

```python
class DialogueActResult(BaseModel):
    act: Literal["inquiry", "selection", "closing"]
    is_continuation: bool = False       # True when continuing a prior topic
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reason: str = ""
    matched_signals: list[str] = Field(default_factory=list)
    requires_active_object: bool = False
    selection_value: str = ""
```

### ClarificationPayload (enhanced)

```python
class ClarificationPayload(BaseModel):
    kind: str = "generic"
    # kinds: object_disambiguation | selection_context_missing | missing_information
    reason: str = ""
    prompt: str = ""
    missing_information: list[str] = Field(default_factory=list)
    options: list[ClarificationOption] = Field(default_factory=list)
```

### Removed contracts

| v2 contract | v3 status |
| --- | --- |
| `ExecutionIntent` | **Removed.** Routing decisions are flat fields in `RouteDecision`. |
| `ModalityDecision` | **Removed.** Executor derives retrieval needs from `request_flags`. |
| `RoutedObjectState` | **Internal only.** Still used inside routing stages but not exposed in output. |
| `ExecutionObjectRef` | **Internal only.** Not part of the output contract. |
| `RoutingInput` | **Removed.** Entry point takes upstream contracts directly. |

## Two-Level Reasoning (Consistent With Executor)

```
                +----------------------------------------------+
  Level 1       |  Deterministic rules (~85%)                   |
  (fast)        |  Pattern matching + stateful_anchors          |
                |  for dialogue act classification              |
                |                                              |
                |  Latency: 0ms                                |
                +----------------------------------------------+

                +----------------------------------------------+
  Level 2       |  LLM classifier (~15%)                        |
  (smart)       |  Structured output LLM call                   |
                |  Handles: no-match, non-English, edge cases   |
                |                                              |
                |  Latency: 1 LLM call (~500ms)                |
                +----------------------------------------------+
```

### When Level 2 activates

Level 2 activates when Level 1 returns no match — not based on a confidence threshold. This is simpler and more robust than v2's approach of returning `UNKNOWN (0.35)` and checking `confidence < 0.5`.

| Trigger | Example |
| --- | --- |
| No pattern matches query text | "I'll take that" — not in any pattern set |
| Non-English message | "这个抗体多少钱？" — Chinese text, no English patterns |
| Ambiguous between acts | "ok and what about the price?" — closing + inquiry |

Note: when `stateful_anchors.pending_clarification_field` is set, Level 1 handles common post-clarification replies ("sure", "the first one") directly, avoiding unnecessary LLM calls.

### Contrast with executor Level 2

| Aspect | Routing Level 2 | Executor Level 2 |
| --- | --- | --- |
| Purpose | Classify dialogue act | Select tools and evaluate sufficiency |
| LLM task | Single classification (structured output) | ReAct reasoning loop (Thought/Action/Observation) |
| Complexity | One LLM call, returns a label | Multiple LLM calls, iterative |
| When | Before execution starts | During execution, after tools return results |

Routing's Level 2 is simpler — it's a classifier, not a reasoning loop.

## Target File Structure

```
src/routing/                          # Same directory, simplified contents
+-- __init__.py                       # Public exports: route, RouteDecision
+-- models.py                         # RouteDecision, DialogueActResult, ClarificationPayload
+-- orchestrator.py                   # Stage pipeline + action determination
+-- runtime.py                        # Adapter from IngestionBundle to routing
+-- vocabulary.py                     # Term sets (no ToolName, no ModalityType)
+-- utils.py                          # Text normalization helpers
+-- stages/
|   +-- __init__.py
|   +-- dialogue_act.py               # Dialogue act classification (Level 1 + Level 2)
|   +-- object_routing.py             # Object state validation (unchanged)
+-- policies/
    +-- __init__.py
    +-- clarification.py              # Clarification decision (enhanced)
    +-- handoff.py                    # Handoff decision (unchanged)
```

### File changes from v2

| File | Action |
| --- | --- |
| `stages/tool_routing.py` | **Delete** — tool selection moved to executor |
| `stages/modality.py` | **Delete** — executor derives retrieval needs from request_flags |
| `policies/assembly.py` | **Delete** — executor handles assembly |
| `models.py` | **Simplify** — remove ExecutionIntent, RoutingInput, ModalityDecision; add RouteDecision |
| `orchestrator.py` | **Simplify** — remove tool selection + modality stages, add action determination |
| `vocabulary.py` | **Simplify** — remove ToolName, ModalityType; update DialogueActType |
| `runtime.py` | **Adapt** — update return type from RoutingDecision to RouteDecision |
| `stages/dialogue_act.py` | **Enhance** — simplify to 3 acts, add stateful_anchors, add Level 2 |
| `policies/clarification.py` | **Enhance** — add ingestion signal awareness |
| Other files | **Unchanged** |

## Customer Support Scenarios

### Scenario 1: Simple product inquiry

```
Customer: "What is PM-AB0001?"

Object routing: primary_object = product (PM-AB0001), status = resolved
Dialogue act:   Level 1 -> inquiry (0.84, "?" detected)
Policies:       no clarification, no handoff
Action:         execute (inquiry -> execute)

RouteDecision:
  action: execute
  dialogue_act: inquiry (0.84)
```

### Scenario 2: Technical consultation

```
Customer: "What is the recommended IHC protocol for Anti-CD3 antibody?"

Object routing: primary_object = product (Anti-CD3), status = resolved
Dialogue act:   Level 1 -> inquiry (0.84)
Policies:       no clarification, no handoff
Action:         execute

RouteDecision:
  action: execute
  dialogue_act: inquiry (0.84)
```

Note: in v2, routing would also classify `modality=hybrid`. In v3, the executor sees `request_flags.needs_protocol=True` from ingestion and selects both `catalog_lookup_tool` and `technical_rag_tool` accordingly.

### Scenario 3: Ambiguous entity

```
Customer: "Tell me about the CD3 antibody"

Object routing: ambiguous_objects = [3 candidates], status = ambiguous
Dialogue act:   Level 1 -> inquiry (0.84)
Policies:       clarification triggered (object disambiguation)
Action:         clarify (clarification takes priority over execute)

RouteDecision:
  action: clarify
  dialogue_act: inquiry (0.84)
  clarification:
    kind: object_disambiguation
    prompt: "Please clarify which product you mean."
    options: [Anti-CD3 (PM-AB0042), Anti-CD3 (PM-AB0051), Anti-CD3 (PM-AB0063)]
```

### Scenario 4: Acknowledgment (no execution needed)

```
Customer: "Thanks, got it"

Object routing: no change
Dialogue act:   Level 1 -> closing (0.81, acknowledgement pattern)
Policies:       no clarification, no handoff
Action:         respond (closing -> respond, skip executor entirely)

RouteDecision:
  action: respond
  dialogue_act: closing (0.81)
```

### Scenario 5: Post-clarification selection (stateful anchors)

```
Customer: "sure" (after system asked "which antibody do you mean?")

Stateful anchors: pending_clarification_field = "object_disambiguation"
                  pending_candidate_options = ["PM-AB0042", "PM-AB0051"]

Object routing: active_object from memory
Dialogue act:   Level 1 -> selection (0.90, stateful anchors detect pending state)
Policies:       no clarification, no handoff
Action:         execute (selection -> execute)

RouteDecision:
  action: execute
  dialogue_act: selection (0.90)
```

### Scenario 6: Non-English query (Level 2)

```
Customer: "这个抗体多少钱？"

Object routing: active_object = product (PM-AB0001), status = contextual_reuse
Dialogue act:   Level 1 -> no pattern matched (Chinese text)
                Level 2 -> inquiry (0.91, LLM: "customer asking about antibody pricing")
Policies:       no clarification, no handoff
Action:         execute

RouteDecision:
  action: execute
  dialogue_act: inquiry (0.91)
```

### Scenario 7: Handoff

```
Customer: "I need to report a serious quality issue with batch #2024-0312"

Ingestion: risk_level = "high", needs_human_review = true
Object routing: primary_object = None
Dialogue act:   Level 1 -> inquiry (0.84)
Policies:       handoff triggered (risk_level = high)
Action:         handoff (handoff takes highest priority)

RouteDecision:
  action: handoff
  dialogue_act: inquiry (0.84)
  reason: "Handoff: request risk exceeds automated routing path"
```

## Migration Steps

### Step 1: Simplify models (medium risk)

1. Define new `RouteDecision` and simplified `DialogueActResult` in `models.py`
2. Keep old contracts (`RoutingDecision`, `ExecutionIntent`, `ModalityDecision`) temporarily
3. Add conversion: `RouteDecision.from_routing_decision(old) -> RouteDecision`
4. Update `orchestrator.py` to return both formats during transition

### Step 2: Remove modality + tool selection (medium risk)

1. Delete `stages/tool_routing.py`
2. Delete `stages/modality.py`
3. Delete `policies/assembly.py`
4. Remove their calls from `orchestrator.py`
5. Remove `ToolName`, `ModalityType` from `vocabulary.py`

### Step 3: Simplify dialogue act + add stateful_anchors (low risk)

1. Update `dialogue_act.py` to use 3 acts (`inquiry`, `selection`, `closing`)
2. Add `stateful_anchors` parameter to `resolve_dialogue_act()`
3. Add Level 2 LLM fallback (called when no pattern matches, replacing UNKNOWN)

### Step 4: Add action determination + enhance clarification (low risk)

1. Add `determine_action()` to orchestrator
2. Add ingestion signal awareness to `clarification.py`
3. Build `RouteDecision` with `action` field in orchestrator

### Step 5: Update entry point and service.py (low risk)

1. Change `route()` signature to take `IngestionBundle + ResolvedObjectState` directly
2. Update `runtime.py` adapter
3. Update `service.py` to use new signature and handle `action: respond`

## Integration With Other Modules

### Routing reads from

| Module | What routing reads | Why |
| --- | --- | --- |
| **Ingestion** | `parser_signals.context.risk_level`, `needs_human_review`, `normalized_query`, `missing_information` | Risk assessment, handoff, query text, clarification signals |
| **Ingestion** | `stateful_anchors.pending_clarification_field`, `active_route` | Session awareness for dialogue act classification |
| **Objects** | `ResolvedObjectState` (primary_object, ambiguous_sets) | Object validation, clarification decision |

### Routing does NOT read from

| Module | Why not |
| --- | --- |
| **Tools** | Tool selection is the executor's job |
| **Memory** | Session state flows through `IngestionBundle.stateful_anchors` and `ResolvedObjectState` |
| **Executor** | Routing runs before execution |
| **Responser** | Routing runs before response synthesis |

### Modules that read from routing

| Module | What it reads from RouteDecision |
| --- | --- |
| **service.py** | `action` — decides whether to call executor or skip to responser |
| **Executor** | `dialogue_act` — builds execution context |
| **Responser** | `action`, `clarification` — selects response mode |
| **Memory** | `action` — persists route state for next turn |

## Anti-Patterns

1. **Routing selects tools.** That's the executor's job. If you find yourself adding tool names in routing, stop — you're re-creating v2's problem.

2. **Routing classifies modality.** The executor derives retrieval needs from `request_flags` and tool registry. If routing needs to know what type of data retrieval is needed, the architecture is wrong — move that logic to the executor.

3. **Routing decomposes multi-intent.** "Check order and explain CAR-T" should not be split into separate route decisions. Routing classifies `dialogue_act=inquiry`, the executor uses `request_flags` + `secondary_objects` to select multiple tools.

4. **Routing reads tool capabilities.** Routing should not import from `src/tools/`. If routing needs to know what tools exist, the architecture is wrong.

5. **LLM routing on every call.** Level 2 is for the ~15% of messages where no pattern matches. "What is PM-AB0001?" should never touch an LLM for dialogue act classification.

6. **Passing object data through routing.** In v2, `ExecutionIntent` carried objects duplicated from `ResolvedObjectState`. In v3, objects flow directly from objects module to executor.

7. **Returning UNKNOWN.** If Level 1 can't classify, call Level 2 immediately. Don't return a useless label with low confidence and hope downstream handles it.
