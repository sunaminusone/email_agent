# Ingestion Design v4

## Purpose

The ingestion layer is the structured entrypoint for every incoming
inquiry. Its job is to emit one clean, trustworthy signal bundle that
answers:

> What evidence do we have about this turn before object resolution begins?

**v4 framing**: ingestion is reused unchanged from v3. The agent's
consumer changed (CSR / sales rep, not the customer), but the signal
extraction problem is identical — we still need to understand what an
incoming customer message says so the downstream retrieval / drafting
modules can use that understanding. Parser intent / flags now drive
retrieval scoping, not customer-facing routing decisions, but the
extraction itself is the same.

In v3 (and still in v4), ingestion's core responsibility is **flat
extraction of entities, flags, and intent**. Multi-intent handling is
achieved through a **deterministic assembly** step that runs _after_
object resolution, not inside ingestion.

### What changed in v3 (still applies in v4)

1. **`secondary_intents` removed** — dead field, never consumed downstream
2. **`resolve_corrected_intent_values()` rewritten** — destructive if/elif chain replaced by non-destructive per-flag validation
3. **`ParserToolHints` deprecated** — replaced by `ToolCapability.supported_request_flags` in tools module
4. **`IntentGroup` introduced** — but assembled deterministically _after_ object resolution, not by the parser

### What does NOT change

- Pipeline structure (`build_ingestion_bundle` orchestration order)
- Parser LLM schema and prompt (no `intent_groups` in parser output)
- Normalizers (query cleanup, conversation history, attachments)
- Deterministic signals (regex-based identifier extraction)
- Reference signals (referential language detection)
- Stateful anchors (prior-state constraint exposure)
- EntitySpan model (text + raw + normalized_value + attribution)
- Attachment signals
- IngestionBundle top-level structure (turn_core / turn_signals / stateful_anchors)

### Key design decision: why the parser does NOT output IntentGroup

LLMs are strong at flat extraction (entities, flags, single intent classification). They are weak at structural binding (which flag belongs to which entity). A parser that outputs `intent_groups` directly would:

1. Increase schema complexity → degrade extraction accuracy on edge fields
2. Produce wrong bindings confidently → worse than no binding (executor acts on wrong data)
3. Be untestable → LLM grouping behavior varies across model versions

Instead, `IntentGroup` assembly uses deterministic rules that are explicit, testable, and stable. The rules derive from `ToolCapability.supported_request_flags` and `ObjectType`, so adding a new tool automatically updates the binding logic.

## Current State Analysis

### What exists (`src/ingestion/`)

| File | Role | v3 status |
| --- | --- | --- |
| `models.py` | All ingestion data models | **Minor** — remove `secondary_intents` |
| `pipeline.py` | `build_ingestion_bundle()` orchestrator | Unchanged |
| `parser_adapter.py` | Parser LLM invocation + result mapping | **Minor** — stop mapping `secondary_intents` |
| `parser_prompt.py` | System prompt for LLM parser | **Minor** — update intent guidance wording |
| `signal_refinement.py` | Dedupe, canonicalize, correct intent/flags | **Rewrite** — non-destructive validation |
| `normalizers.py` | Turn normalization | Unchanged |
| `deterministic_signals.py` | Regex identifier + context extraction | Unchanged |
| `reference_signals.py` | Referential language detection | Unchanged |
| `stateful_anchors.py` | Prior-state anchor extraction | Unchanged |

### What works well

1. **Pipeline structure** — `build_ingestion_bundle()` orchestrates normalize → parse → refine → deterministic → reference → anchor → assemble. The order is correct and should not change.

2. **EntitySpan with provenance** — entities carry `text`, `raw`, `normalized_value`, and `SourceAttribution`. This is the right level of detail for grounded processing.

3. **ParserRequestFlags** — 16 boolean flags cover the biotech domain comprehensively. Multiple flags can be true simultaneously, naturally representing multi-intent queries at the signal level.

4. **Deterministic signals** — regex-based extraction of catalog/order/invoice numbers provides reliable non-LLM signals that correct parser mistakes.

5. **Stateful anchors** — clean separation of prior-state constraints from current-turn evidence.

### What's insufficient for v3

1. **`secondary_intents` is dead data.** `ParserContext.secondary_intents: list[str]` is extracted by the parser but never consumed by routing, executor, or response.

2. **`resolve_corrected_intent_values()` is destructive.** The if/elif chain in `signal_refinement.py:51-72` picks ONE winner:

    ```python
    if needs_invoice or needs_order_status:      # ← wins
        corrected_intent = "order_support"
    elif needs_documentation:                     # ← dead if order flags also set
        corrected_intent = "documentation_request"
    ```

    For "check my order and send me a datasheet": `needs_order_status=True` + `needs_documentation=True`, but `primary_intent` becomes `"order_support"` only. The documentation need vanishes from intent classification, even though `request_flags.needs_documentation` remains True.

3. **request_flags are unbound.** `needs_order_status=True` + `needs_protocol=True` exist as flat booleans. No structure tells the executor that `needs_order_status` relates to the order and `needs_protocol` relates to the product.

4. **ParserToolHints overlaps with v3 tools.** `suggested_tools`, `requires_database_lookup`, `requires_file_lookup`, `requires_order_system` duplicate information now available via `ToolCapability.supported_request_flags`. The parser guessing tool names couples ingestion to tool implementation.

## v3 Design

### Overview: two-phase intent handling

```
Phase 1 (Ingestion): Flat extraction — entities + request_flags + primary_intent
    ↓ IngestionBundle (unchanged contract)
Phase 2 (Objects): Resolve entities → ResolvedObjectState
    ↓
Phase 3 (Assembly): Deterministic rules bind flags to resolved objects → IntentGroup[]
    ↓
Phase 4 (Executor): Per-group tool selection and execution
```

Phase 1 is what ingestion already does. Phase 2 is what objects already does. Phase 3 is new — a deterministic function, not an LLM call. Phase 4 is the v3 executor.

### Phase 1: Ingestion changes (minimal)

#### Remove `secondary_intents`

```python
class ParserContext(_IngestionModel):
    language: str = "other"
    channel: str = "internal_qa"
    primary_intent: str = "unknown"
    # secondary_intents: REMOVED — dead field, replaced by intent assembly
    intent_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    query_type: str = "question"
    urgency: str = "low"
    risk_level: str = "low"
    needs_human_review: bool = False
    reasoning_note: str = ""
```

#### Rewrite signal refinement: non-destructive validation

Current `resolve_corrected_intent_values()` uses if/elif to pick one winner. Replace with validation that checks consistency but does not destroy multi-intent information:

```python
def validate_intent_and_flags(
    parser_signals: ParserSignals,
    normalized_query: str,
) -> ParserSignals:
    """Validate primary_intent against request_flags. Non-destructive."""
    context = parser_signals.context
    flags = parser_signals.request_flags
    primary_intent = context.primary_intent
    confidence = context.intent_confidence or 0.0

    # Only correct when primary_intent contradicts the dominant flags
    dominant_intent = _dominant_intent_from_flags(flags, normalized_query)
    if dominant_intent and primary_intent in {"unknown", "general_info", "follow_up"}:
        primary_intent = dominant_intent
        confidence = max(confidence, 0.80)

    if primary_intent == context.primary_intent and confidence == context.intent_confidence:
        return parser_signals

    return parser_signals.model_copy(update={
        "context": context.model_copy(update={
            "primary_intent": primary_intent,
            "intent_confidence": confidence,
        }),
    })


def _dominant_intent_from_flags(flags: ParserRequestFlags, query: str) -> str | None:
    """Determine the single most dominant intent from flags. Used only when
    primary_intent is too vague ('unknown'/'general_info'). Does NOT override
    a specific intent the parser already classified."""
    flag_intent_map = [
        (flags.needs_invoice or flags.needs_order_status, "order_support"),
        (flags.needs_shipping_info, "shipping_question"),
        (flags.needs_documentation, "documentation_request"),
        (flags.needs_price or flags.needs_quote, "pricing_question"),
        (flags.needs_timeline, "timeline_question"),
        (flags.needs_customization, "customization_request"),
        (flags.needs_troubleshooting, "troubleshooting"),
        (flags.needs_protocol, "technical_question"),
    ]
    for is_active, intent in flag_intent_map:
        if is_active:
            return intent
    return None
```

Key differences from the current implementation:
1. **Only corrects vague intents** (`unknown`, `general_info`, `follow_up`) — if the parser said `"order_support"` but `needs_documentation=True` is also set, the correction does NOT overwrite to `"documentation_request"`. The documentation need is preserved in `request_flags`.
2. **`request_flags` are never modified** — they reflect what the user asked for, regardless of which intent wins.
3. **Multi-intent information survives** — both `needs_order_status=True` and `needs_documentation=True` remain. The assembly phase (Phase 3) uses the flags, not `primary_intent`.

#### Deprecate ParserToolHints

`ParserToolHints` fields are no longer consumed in v3:
- `suggested_tools` → executor reads `ToolCapability.supported_request_flags` via registry
- `requires_database_lookup` → implied by `needs_availability`, `needs_comparison`, etc.
- `requires_file_lookup` → implied by `needs_documentation`
- `requires_order_system` → implied by `needs_order_status`, `needs_invoice`, etc.

Keep the model with default values for v2 compatibility. Remove when v2 code paths are deleted.

#### Parser prompt: minor update

Remove:
```
5. Choose one primary intent and optionally multiple secondary intents.
```

Replace with:
```
5. Choose one primary intent that best describes the user's dominant need.
   Set all applicable request_flags — multiple flags can be true simultaneously.
   Do not output secondary_intents (deprecated).
```

No structural change to the parser schema. The LLM continues to output flat entities + flat flags + single primary_intent. This is what LLMs do reliably.

### Phase 3: Deterministic intent assembly (new)

This is the core of the v3 multi-intent design. It runs _after_ object resolution, as a standalone function.

#### Location

New file: `src/ingestion/intent_assembly.py`

Although the function runs after objects, it lives in `src/ingestion/` because:
- It reads ingestion signals (`request_flags`)
- It reads tool capability metadata (`supported_request_flags`, `supported_object_types`)
- It produces an `IntentGroup` list that enriches the ingestion signal contract
- Objects module should not know about request_flags or tools

#### Data contracts

```python
class IntentGroup(BaseModel):
    """One coherent user need, bound to a resolved object."""
    model_config = ConfigDict(extra="forbid")

    intent: str = "unknown"
    request_flags: list[str] = Field(default_factory=list)
    object_type: str = ""
    object_identifier: str = ""
    object_display_name: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
```

IntentGroup references a resolved object by its type + identifier (not the full ObjectCandidate). This is a lightweight pointer, not a copy. The executor can look up the full object from `ResolvedObjectState` when needed.

#### Assembly rules

```python
# Flag → object_type affinity. Derived from ToolCapability.supported_request_flags
# + ToolCapability.supported_object_types. When a new tool is added, this mapping
# updates automatically (or can be computed at startup from the registry).
_FLAG_OBJECT_AFFINITY: dict[str, set[str]] = {
    "needs_order_status":         {"order"},
    "needs_shipping_info":        {"shipment", "order"},
    "needs_invoice":              {"invoice", "order", "customer"},
    "needs_price":                {"product", "service"},
    "needs_quote":                {"product", "service"},
    "needs_availability":         {"product", "service"},
    "needs_comparison":           {"product", "service"},
    "needs_sample":               {"product", "service"},
    "needs_protocol":             {"product", "service", "scientific_target"},
    "needs_troubleshooting":      {"product", "service"},
    "needs_documentation":        {"product", "service", "document"},
    "needs_customization":        {"product", "service"},
    "needs_timeline":             {"product", "service", "order"},
    "needs_recommendation":       {"product", "service", "scientific_target"},
    "needs_regulatory_info":      {"product", "service"},
    "needs_refund_or_cancellation": {"order", "invoice"},
}

# Flag → intent classification (for per-group intent labeling)
_FLAG_INTENT: dict[str, str] = {
    "needs_order_status":         "order_support",
    "needs_shipping_info":        "shipping_question",
    "needs_invoice":              "order_support",
    "needs_price":                "pricing_question",
    "needs_quote":                "pricing_question",
    "needs_availability":         "product_inquiry",
    "needs_comparison":           "product_inquiry",
    "needs_sample":               "product_inquiry",
    "needs_protocol":             "technical_question",
    "needs_troubleshooting":      "troubleshooting",
    "needs_documentation":        "documentation_request",
    "needs_customization":        "customization_request",
    "needs_timeline":             "timeline_question",
    "needs_recommendation":       "technical_question",
    "needs_regulatory_info":      "technical_question",
    "needs_refund_or_cancellation": "order_support",
}
```

#### Assembly algorithm

```python
def assemble_intent_groups(
    request_flags: ParserRequestFlags,
    resolved_objects: list[ObjectCandidate],
    primary_intent: str = "unknown",
) -> list[IntentGroup]:
    """Deterministically bind active request_flags to resolved objects."""
    active_flags = _get_active_flags(request_flags)
    if not active_flags:
        # No flags → single group from primary_intent (simple query)
        return _single_group_from_intent(primary_intent, resolved_objects)

    # Step 1: For each flag, find objects whose type matches the flag's affinity
    flag_bindings: dict[str, list[ObjectCandidate]] = {}
    for flag in active_flags:
        affinity = _FLAG_OBJECT_AFFINITY.get(flag, set())
        matched = [obj for obj in resolved_objects if obj.object_type in affinity]
        flag_bindings[flag] = matched

    # Step 2: Group flags by their matched object
    # Key insight: flags that match the SAME object belong to the SAME group
    object_groups: dict[str, list[str]] = {}  # object_identifier → [flag_names]
    unbound_flags: list[str] = []

    for flag, matched_objects in flag_bindings.items():
        if len(matched_objects) == 1:
            # Unambiguous: exactly one object matches
            key = matched_objects[0].identifier or matched_objects[0].display_name
            object_groups.setdefault(key, []).append(flag)
        elif len(matched_objects) == 0:
            # No object matches this flag → unbound group
            unbound_flags.append(flag)
        else:
            # Multiple objects match → bind to all (executor disambiguates via tool scoring)
            for obj in matched_objects:
                key = obj.identifier or obj.display_name
                object_groups.setdefault(key, []).append(flag)

    # Step 3: Build IntentGroup per object
    groups: list[IntentGroup] = []
    for obj_key, flags in object_groups.items():
        obj = _find_object(obj_key, resolved_objects)
        deduped_flags = list(dict.fromkeys(flags))
        groups.append(IntentGroup(
            intent=_infer_group_intent(deduped_flags, primary_intent),
            request_flags=deduped_flags,
            object_type=obj.object_type if obj else "",
            object_identifier=obj.identifier if obj else "",
            object_display_name=obj.display_name if obj else "",
            confidence=0.85,
        ))

    # Step 4: Unbound flags → general group (no specific object)
    if unbound_flags:
        groups.append(IntentGroup(
            intent=_infer_group_intent(unbound_flags, primary_intent),
            request_flags=unbound_flags,
            confidence=0.60,
        ))

    return groups or _single_group_from_intent(primary_intent, resolved_objects)


def _get_active_flags(request_flags: ParserRequestFlags) -> list[str]:
    return [
        field_name
        for field_name in request_flags.model_fields
        if getattr(request_flags, field_name, False)
    ]


def _infer_group_intent(flags: list[str], fallback_intent: str) -> str:
    """Pick the most specific intent from a set of flags."""
    for flag in flags:
        intent = _FLAG_INTENT.get(flag)
        if intent:
            return intent
    return fallback_intent
```

#### Walkthrough: multi-intent query

```
User: "Check my order #12345 and explain the CAR-T construct mechanism"
```

After ingestion:
- `request_flags.needs_order_status = True`
- `request_flags.needs_protocol = True`
- `entities.order_numbers = [EntitySpan(text="12345")]`
- `entities.product_names = [EntitySpan(text="CAR-T")]`

After object resolution:
- `primary_object = ObjectCandidate(object_type="order", identifier="12345")`
- `secondary_objects = [ObjectCandidate(object_type="product", display_name="CAR-T")]`

Assembly:
1. `needs_order_status` affinity = `{"order"}` → matches `order(12345)` ✓
2. `needs_protocol` affinity = `{"product", "service", "scientific_target"}` → matches `product(CAR-T)` ✓
3. Result:

```python
[
    IntentGroup(
        intent="order_support",
        request_flags=["needs_order_status"],
        object_type="order",
        object_identifier="12345",
        confidence=0.85,
    ),
    IntentGroup(
        intent="technical_question",
        request_flags=["needs_protocol"],
        object_type="product",
        object_display_name="CAR-T",
        confidence=0.85,
    ),
]
```

Executor selects tools per group:
- Group 1 → `order_lookup_tool` (supports `needs_order_status` + object_type `order`)
- Group 2 → `technical_rag_tool` (supports `needs_protocol` + object_type `product`)

#### Walkthrough: same-entity multi-flag query

```
User: "How much does product 20001 cost and can you send the datasheet?"
```

After object resolution:
- `primary_object = ObjectCandidate(object_type="product", identifier="20001")`
- `request_flags.needs_price = True, needs_documentation = True`

Assembly:
1. `needs_price` affinity = `{"product", "service"}` → matches `product(20001)` ✓
2. `needs_documentation` affinity = `{"product", "service", "document"}` → matches `product(20001)` ✓
3. Both flags bind to the same object → **one group with two flags**:

```python
[
    IntentGroup(
        intent="pricing_question",
        request_flags=["needs_price", "needs_documentation"],
        object_type="product",
        object_identifier="20001",
        confidence=0.85,
    ),
]
```

Executor selects multiple tools for one group:
- `pricing_lookup_tool` (supports `needs_price`)
- `document_lookup_tool` (supports `needs_documentation`)

#### Walkthrough: no entities

```
User: "Do you offer custom antibody services?"
```

After object resolution:
- `primary_object = None` (no specific entity resolved)
- `request_flags.needs_availability = True, needs_customization = True`

Assembly:
1. `needs_availability` affinity = `{"product", "service"}` → no resolved objects match → unbound
2. `needs_customization` affinity = `{"product", "service"}` → no resolved objects match → unbound
3. Result: one unbound group

```python
[
    IntentGroup(
        intent="product_inquiry",
        request_flags=["needs_availability", "needs_customization"],
        confidence=0.60,
    ),
]
```

Lower confidence because no object binding exists. Executor falls back to broad tool scoring.

#### Walkthrough: closing query

```
User: "thanks"
```

After ingestion: no active flags. After assembly: `_single_group_from_intent("unknown", [])` → one generic group or empty list. Routing classifies `dialogue_act="closing"`, action=`"respond"`. Executor is not invoked.

### Auto-deriving affinity from the tool registry

`_FLAG_OBJECT_AFFINITY` can be computed at startup instead of hardcoded:

```python
def build_flag_object_affinity() -> dict[str, set[str]]:
    """Derive flag-to-object-type mapping from tool capabilities in the registry."""
    affinity: dict[str, set[str]] = {}
    for entry in list_registry_entries():
        cap = entry.capability
        if cap is None:
            continue
        for flag in cap.supported_request_flags:
            affinity.setdefault(flag, set()).update(cap.supported_object_types)
    return affinity
```

This means adding a new tool with `supported_request_flags=["needs_X"]` and `supported_object_types=["Y"]` automatically teaches the assembly that `needs_X` has affinity with object_type `Y`. No manual mapping maintenance.

## Pipeline Integration

### Where assembly fits

```
service.py (or orchestration layer):

    ingestion_bundle = build_ingestion_bundle(...)         # Phase 1
    resolved_object_state = resolve_objects(...)            # Phase 2
    intent_groups = assemble_intent_groups(                 # Phase 3 (NEW)
        request_flags=ingestion_bundle.turn_signals.parser_signals.request_flags,
        resolved_objects=_all_resolved(resolved_object_state),
        primary_intent=ingestion_bundle.turn_signals.parser_signals.context.primary_intent,
    )
    route = route_v3(...)                                   # Phase 4
    # executor receives intent_groups                       # Phase 5
```

Assembly runs between objects and routing. It does not modify the IngestionBundle or ResolvedObjectState — it produces a separate `list[IntentGroup]` that is passed to the executor.

### LangChain integration

The assembly step is deterministic — it does not need an LLM. In a LangChain pipeline, it's a `RunnableLambda`:

```python
from langchain_core.runnables import RunnableLambda, RunnableParallel, RunnablePassthrough

def build_core_pipeline():
    """The full ingestion → objects → assembly → routing pipeline."""

    ingest = RunnableLambda(
        lambda state: {
            **state,
            "ingestion_bundle": build_ingestion_bundle(
                thread_id=state["thread_id"],
                user_query=state["user_query"],
                conversation_history=state.get("conversation_history"),
                attachments=state.get("attachments"),
                prior_state=state.get("prior_state"),
            ),
        }
    )

    resolve = RunnableLambda(
        lambda state: {
            **state,
            "resolved_object_state": resolve_objects(state["ingestion_bundle"]),
        }
    )

    assemble = RunnableLambda(
        lambda state: {
            **state,
            "intent_groups": assemble_intent_groups(
                request_flags=state["ingestion_bundle"].turn_signals.parser_signals.request_flags,
                resolved_objects=_all_resolved(state["resolved_object_state"]),
                primary_intent=state["ingestion_bundle"].turn_signals.parser_signals.context.primary_intent,
            ),
        }
    )

    route = RunnableLambda(
        lambda state: {
            **state,
            "route_decision": route_v3(
                build_routing_input(state["ingestion_bundle"], state["resolved_object_state"]),
                stateful_anchors=state["ingestion_bundle"].stateful_anchors,
            ),
        }
    )

    return ingest | resolve | assemble | route
```

Each step is a `RunnableLambda` that enriches the state dict. This is transparent, debuggable (each step's output is inspectable), and composable with other LangChain primitives.

#### Optional: LLM disambiguation for ambiguous bindings

When a flag matches multiple resolved objects of the same type, the deterministic rules cannot decide. For this case, an optional LLM disambiguation chain can be added:

```python
from langchain_core.runnables import RunnableBranch

DISAMBIGUATION_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """Given these resolved entities and request flags, determine which
    flag belongs to which entity. Return a list of bindings."""),
    ("human", "Query: {query}\nEntities: {entities}\nAmbiguous flags: {flags}"),
])

class FlagBinding(BaseModel):
    flag: str
    entity_identifier: str

class DisambiguationOutput(BaseModel):
    bindings: list[FlagBinding]

def get_disambiguation_chain():
    llm = get_llm(model="haiku")  # lightweight model suffices
    return DISAMBIGUATION_PROMPT | llm.with_structured_output(DisambiguationOutput)

def build_assembly_with_disambiguation():
    """Assembly pipeline: deterministic first, LLM only for ambiguous cases."""
    assemble = RunnableLambda(assemble_intent_groups_with_ambiguity_tracking)
    disambiguate = RunnableBranch(
        (lambda state: state.get("has_ambiguous_bindings", False), get_disambiguation_chain()),
        RunnableLambda(lambda state: state),  # no ambiguity → pass through
    )
    return assemble | disambiguate
```

This is optional. The base assembly works without it — ambiguous flags are bound to all matching objects, and the executor's tool scoring handles the rest. The LLM disambiguation improves precision for complex multi-entity queries.

## Data Contracts

### IntentGroup (new — lives in `src/ingestion/intent_assembly.py`)

```python
class IntentGroup(BaseModel):
    model_config = ConfigDict(extra="forbid")
    intent: str = "unknown"
    request_flags: list[str] = Field(default_factory=list)
    object_type: str = ""
    object_identifier: str = ""
    object_display_name: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
```

### ParserContext (updated)

```python
class ParserContext(_IngestionModel):
    language: str = "other"
    channel: str = "internal_qa"
    primary_intent: str = "unknown"
    # secondary_intents: REMOVED
    intent_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    query_type: str = "question"
    urgency: str = "low"
    risk_level: str = "low"
    needs_human_review: bool = False
    reasoning_note: str = ""
```

### Unchanged models

All other ingestion models remain unchanged:
- `ParserSignals`, `ParserOutput`, `ParserRequestFlags`
- `ParserConstraints`, `ParserOpenSlots`, `ParserRetrievalHints`
- `ParserEntitySignals`, `ParserOutputEntities`
- `TurnCore`, `TurnSignals`, `IngestionBundle`
- `EntitySpan`, `SourceAttribution`, `ValueSignal`
- `DeterministicSignals`, `ReferenceSignals`, `AttachmentSignals`
- `StatefulAnchors`

## Integration With Downstream Modules

### Objects (unchanged)

Object resolution stays flat. It resolves all entities into `ResolvedObjectState` with `primary_object`, `secondary_objects`, and `ambiguous_sets`. Objects does not know about intent groups.

### Routing (unchanged)

v3 routing classifies `dialogue_act` and determines `action` (execute/respond/clarify/handoff). It does not read intent groups. Multi-intent decomposition is the executor's responsibility.

### Executor (new consumer)

The v3 executor receives `list[IntentGroup]` and does per-group tool selection:

```python
def select_tools_for_execution(
    intent_groups: list[IntentGroup],
    registry_entries: list[RegistryEntry],
    dialogue_act: DialogueActResult,
) -> list[PlannedToolCall]:
    all_calls = []
    for group in intent_groups:
        scored = _score_tools_for_group(group, registry_entries, dialogue_act)
        selected = [entry for entry, score in scored if score >= SELECTION_THRESHOLD]
        all_calls.extend(_plan_calls_for_group(selected, group))
    return _dedupe_and_order(all_calls)
```

Details are in EXECUTOR_DESIGN_V3.md.

### Response (minor enhancement)

The executor can tag tool results with group metadata (intent, object). The response layer uses this to organize the reply by user need:

```
Your order #12345 is currently being processed and is expected to ship on April 15.

Regarding the CAR-T construct mechanism: [technical explanation from RAG]
```

Instead of mixing results from different needs into one flat paragraph.

## Migration Steps

### Step 1: Remove secondary_intents (zero risk)

1. Remove `secondary_intents` from `ParserContext`
2. Remove mapping in `parser_adapter.py` (`_map_parser_context`)
3. Update parser prompt wording
4. No downstream code reads this field — zero breakage

### Step 2: Rewrite signal refinement (behavioral change, low risk)

1. Replace `resolve_corrected_intent_values()` with `validate_intent_and_flags()`
2. New function only corrects vague intents (`unknown`, `general_info`) — does not overwrite specific intents
3. `request_flags` are never modified by refinement
4. Run existing tests to verify no regression

### Step 3: Add intent_assembly.py (zero risk, additive)

1. Create `src/ingestion/intent_assembly.py` with `IntentGroup` model and `assemble_intent_groups()`
2. Wire into `service.py` between object resolution and routing
3. v2 executor ignores intent_groups — no behavioral change until executor migrates

### Step 4: Deprecate ParserToolHints (cleanup)

1. Stop populating `suggested_tools`, `requires_database_lookup`, etc. in signal refinement
2. Keep the model with default values for v2 compatibility
3. Remove when v2 code paths are deleted

### Step 5: Executor consumes intent_groups (when executor migrates)

1. Executor reads intent_groups for per-group tool selection
2. Results tagged with group metadata for response assembly
3. Old flat tool selection removed

### Step 6: Optional LLM disambiguation (future)

1. Add disambiguation chain for ambiguous flag-to-object bindings
2. Only triggers when multiple objects of the same type match the same flag
3. Uses lightweight model (haiku) with minimal prompt

## Known Limitations

### Conditional intents not supported

```
"If it hasn't shipped yet, cancel it; otherwise give me the tracking number"
```

IntentGroup has no conditional structure. Both needs would be assembled as parallel groups. The executor would execute both tools, and the response layer would need to handle the conditional logic. This is acceptable for the current use case (customer support emails rarely contain true conditionals).

### Per-group constraints not supported

```
"100 units of product A, 200 units of product B, quote for both"
```

`ParserConstraints.quantity` is global. Per-group constraints are deferred until there's evidence of frequent occurrence in production traffic.

### Multi-turn group continuity

```
Turn 1: "Check order #12345 and explain CAR-T mechanism"
Turn 2: "Tell me more about the second thing"
```

Stateful anchors don't preserve group structure across turns. The reference "second thing" would be handled by reference signals + stateful anchors at the object level, not the group level. This is a known gap.

## Anti-Patterns

1. **Parser outputs intent_groups.** The parser extracts flat signals. Group assembly is deterministic and happens after object resolution.

2. **Assembly in ingestion pipeline.** `assemble_intent_groups()` runs after `resolve_objects()`, not inside `build_ingestion_bundle()`. The function needs resolved object types, which don't exist during ingestion.

3. **One IntentGroup per request_flag.** "Price and documentation for product X" is ONE group with two flags, not two groups. Groups are per-object, not per-flag.

4. **Hardcoded `_FLAG_OBJECT_AFFINITY`.** Prefer deriving it from `ToolCapability.supported_request_flags` + `supported_object_types` at startup. Adding a new tool should automatically update the affinity mapping.

5. **IntentGroup modifying IngestionBundle.** Assembly produces a _separate_ `list[IntentGroup]`. It does not modify the ingestion bundle or resolved object state. These are read-only inputs.

6. **Routing consuming intent_groups.** Routing classifies the dialogue act and macro action. Per-group decomposition is the executor's job.
