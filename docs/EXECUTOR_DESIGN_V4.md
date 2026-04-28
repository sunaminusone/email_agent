# Executor Design v4

## Purpose

The executor is the core "agent behavior" module of the v4 CSR co-pilot.
It receives a resolved inquiry (ingestion done, entities resolved, route
classified — and in v4, always coerced to "execute") and autonomously
selects tools, dispatches calls, evaluates results, and iterates when
results are insufficient.

The executor answers questions like:
- Which backend sources do I need to query to give the rep useful context?
- Did I get enough information, or should I try another source?
- The catalog returned nothing — should I fall back to RAG for a fuzzy match?

The executor does **not** understand the inquiry (ingestion), resolve
entities (objects), classify the route (routing), or compose the final
draft (responser). It executes.

## v4 invariant — both retrieval tools always run

Beyond the v3 self-describing tool framework documented below, v4 adds
one CSR-mode invariant in `select_tools` (`src/executor/tool_selector.py`):

```python
CSR_ALWAYS_INCLUDE = ("historical_thread_tool", "technical_rag_tool")
```

Regardless of which tool the demand classifier picks as primary, both
retrieval tools are added as **supporting** selections. Their values are
**complementary, not substitutional**:

- `historical_thread_tool` surfaces past similar inquiries with how sales
  actually replied
- `technical_rag_tool` surfaces relevant authoritative KB chunks (service
  flyers, workflow docs)

The CSR sees both and decides what to use in their reply. Letting the
demand classifier pick only one would make the v4 product (a search engine
+ case library for the rep) artificially narrow.

## Why This Makes the System an Agent

### Pipeline vs Agent

A pipeline executes a fixed sequence of steps. Each step does not observe the previous step's output to change its own behavior:

```
Input -> Step 1 -> Step 2 -> Step 3 -> Output
```

An agent has an **observe → decide → act** loop. It looks at what happened, decides what to do next, and acts -- potentially multiple times:

```
Input -> What should I do? -> Do it -> Enough? -> No -> What else? -> Do it -> Enough? -> Yes -> Output
```

Think of a human customer support agent. When a customer asks "Tell me about CD19 CAR-T", the agent:

1. Checks the product catalog -- nothing found
2. **Observes** the empty result, **decides** to try the technical knowledge base instead
3. Finds technical documentation about CD19 CAR-T constructs
4. **Evaluates** that the answer is now sufficient, responds to the customer

A human agent would never say "I checked the product catalog and found nothing, goodbye." They adapt. The v3 executor does the same.

### What v2 does wrong

The current executor is a **blind hand** -- it does what it's told, without looking at the results:

```python
# Current executor.py -- the entire execution logic
def execute_plan(plan: ExecutionPlan) -> ExecutionRun:
    for planned_call in plan.planned_calls:       # Run whatever routing told me to
        result = safe_dispatch_tool(planned_call.request)
        executed_calls.append(...)                 # Record result, but never inspect it
    # Loop ends. No observation. No decision. No retry.
```

And the tools to run were decided by a hardcoded mapping table, not by the executor:

```python
# Current planner_rules.py -- tool selection is a static dict
PRIMARY_TOOL_BY_OBJECT_TYPE = {
    "product": "catalog_lookup_tool",     # Always this, no matter what
    "service": "technical_rag_tool",      # Always this, no exceptions
    "order":   "order_lookup_tool",       # No room for judgment
    ...
}
```

This is a pipeline, not an agent. The executor has no eyes (cannot observe results), no brain (cannot decide what to do next), and no autonomy (tools are pre-selected by someone else).

### What v3 changes

The v3 executor is an **agent with eyes and a brain**:

1. **Eyes**: after each tool dispatch, the executor inspects the results (`evaluate_completeness`)
2. **Brain**: based on the results, it decides what to do next -- stop, retry, or try a different tool (`select_tools` with `already_called` awareness)
3. **Autonomy**: the executor reads the tool registry and selects tools itself, based on what each tool declares it can do (`ToolCapability`), not based on a hardcoded table

### Adding a new tool: the cost difference

**v2** -- adding an `inventory_tool` requires editing 4 files across 3 modules:

1. `routing/stages/tool_routing.py` -- add selection rule
2. `execution/planner_rules.py` -- add to `PRIMARY_TOOL_BY_OBJECT_TYPE`
3. `execution/requests.py` -- add `_inventory_constraints()`
4. `tools/inventory/` -- implement the tool itself

**v3** -- adding an `inventory_tool` requires 1 file in 1 module:

1. `tools/inventory/` -- implement the tool and declare its `ToolCapability`

The executor discovers the new tool through the registry. No other module needs to know it exists. This is what "self-describing tools" means: the tool tells the system what it can do, and the system figures out when to use it.

## Current State Analysis

### What exists (`src/execution/`)

| File | Role | Limitation |
| --- | --- | --- |
| `planner.py` | Builds ExecutionPlan from ExecutionIntent | Entirely deterministic; reads `intent.selected_tools` set by routing -- zero autonomy |
| `planner_rules.py` | Hardcoded mapping tables (`PRIMARY_TOOL_BY_OBJECT_TYPE`, `PARALLEL_SAFE_TOOLS`, `SEQUENTIAL_DEPENDENCIES`) | Adding a new tool requires editing this file. Opposite of self-describing tools |
| `executor.py` | Sequential `for` loop over `plan.planned_calls` | No reasoning, no parallelism, no completeness check, no iteration |
| `merger.py` | Aggregates primary_facts + supporting_facts | Reusable as-is |
| `requests.py` | Builds `ToolRequest` with enriched constraints per tool family | Reusable as-is; well-structured constraint hydration |
| `runtime.py` | Public API: `build_execution_plan()`, `run_execution_plan()` | Thin wrappers; will be replaced by new entry point |
| `models.py` | `ExecutionPlan`, `PlannedToolCall`, `ExecutedToolCall`, `ExecutionRun` | `ExecutionRun` couples to routing's `ExecutionIntent`; needs decoupling |

### Core problems

1. **No tool selection autonomy.** The executor receives `intent.selected_tools` pre-chosen by `routing/stages/tool_routing.py`. Adding a tool means editing routing + planner_rules + requests -- three modules that should not care.

2. **No reasoning loop.** `executor.py` is a single-pass `for` loop. If catalog returns empty, it cannot try RAG as a fallback. If a tool errors, it records the error and moves on.

3. **No completeness evaluation.** The executor has no concept of "did I answer the customer's question?" It always runs exactly the tools routing selected, even if they return nothing useful.

4. **Hardcoded dependency knowledge.** `SEQUENTIAL_DEPENDENCIES` knows that `catalog_lookup_tool` must run before `technical_rag_tool`. This knowledge should live in tool capabilities or be inferred from results.

### What to keep

- **`requests.py`** -- the constraint-building logic (`_catalog_constraints`, `_rag_constraints`, `_quickbooks_constraints`, etc.) is well-tested and domain-correct. Rename to `request_builder.py` and reuse.
- **`merger.py`** -- the fact-aggregation logic is clean and reusable.
- **`models.py`** -- `ExecutedToolCall` and `PlannedToolCall` are solid. `ExecutionRun` needs evolution into `ExecutionResult`.

## v3 Design

### Module Boundary

```
Input:
  - IngestionBundle         (what the customer said)
  - ResolvedObjectState     (which entities they mean)
  - RouteDecision           (dialogue_act, action=execute)
  - MemorySnapshot          (session context)

Output:
  - ExecutionResult         (tool calls, merged results, iteration count)
```

The executor does **not** receive pre-selected tools. It reads tool capabilities from the registry at runtime.

### Entry Point

```python
def run_executor(
    ingestion_bundle: IngestionBundle,
    resolved_object_state: ResolvedObjectState,
    route_decision: RouteDecision,
    memory_snapshot: MemorySnapshot,
) -> ExecutionResult:
```

This replaces `run_execution(intent)` and `run_execution_plan(plan)`.

### Building ExecutionContext From Upstream Inputs

The entry point receives four upstream objects. `build_execution_context()` maps them into the executor's internal state:

```python
def build_execution_context(
    ingestion_bundle: IngestionBundle,
    resolved_object_state: ResolvedObjectState,
    route_decision: RouteDecision,
    memory_snapshot: MemorySnapshot,
) -> ExecutionContext:
    return ExecutionContext(
        # Query
        query=ingestion_bundle.turn_core.normalized_query
              or ingestion_bundle.turn_core.raw_query,

        # Resolved entities (from objects module)
        primary_object=resolved_object_state.primary_object,
        secondary_objects=resolved_object_state.secondary_objects,
        resolved_object_constraints=_extract_object_constraints(
            resolved_object_state),

        # Routing decision (from routing module)
        dialogue_act=route_decision.dialogue_act,

        # Ingestion signals (for tool selection and retrieval needs derivation)
        request_flags=ingestion_bundle.turn_signals.parser_signals.request_flags,
        retrieval_hints=ingestion_bundle.turn_signals.parser_signals.retrieval_hints,

        # Session context
        memory_snapshot=memory_snapshot,
    )
```

**Why this mapping matters**: the executor is decoupled from both routing and ingestion internals. It reads what it needs during construction, then operates on its own `ExecutionContext` throughout the reasoning loop. If routing or ingestion models change, only `build_execution_context()` needs updating.

### Reasoning Loop

```
     ┌─────────────────────────────────────────────┐
     │                                             │
     ▼                                             │
  ┌──────────────┐                                 │
  │  1. SELECT   │  Read registry, match           │
  │     TOOLS    │  capabilities to context        │
  └──────┬───────┘                                 │
         │ list[ToolName]                          │
         ▼                                         │
  ┌──────────────┐                                 │
  │  2. BUILD    │  Build ToolRequest              │
  │     REQUESTS │  per tool (constraints)         │
  └──────┬───────┘                                 │
         │ list[PlannedToolCall]                   │
         ▼                                         │
  ┌──────────────┐                                 │
  │  3. DISPATCH │  Call tools                     │
  │              │  (parallel when safe)           │
  └──────┬───────┘                                 │
         │ list[ExecutedToolCall]                   │
         ▼                                         │
  ┌──────────────┐         yes                     │
  │  4. EVALUATE │  ──────────▶ done               │
  │   COMPLETE?  │  sufficient                     │
  │              │  ──────────▶ loop (if < max)  ──┘
  └──────────────┘  insufficient
```

#### Step 1: Select Tools

The tool selector scans the registry and matches tool capabilities against the current execution context:

```python
def select_tools(
    context: ExecutionContext,
    registry: list[ToolCapability],
    already_called: set[str],
) -> list[ToolSelection]:
```

Matching criteria (all deterministic):

| Signal | Matches Against | Weight |
| --- | --- | --- |
| `primary_object.object_type` | `capability.supported_object_types` | 0.4 (strongest) |
| `dialogue_act.act` | `capability.supported_dialogue_acts` | 0.3 |
| `secondary_objects[*].object_type` | `capability.supported_object_types` | 0.1 each |
| Derived retrieval needs | `capability.supported_modalities` | 0.15 each |

**Retrieval needs derivation**: instead of receiving a pre-classified modality from routing, the executor derives retrieval needs from ingestion `request_flags` and object type:

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
    if not needs and primary_object:
        _DEFAULTS = {"product": {"structured_lookup"}, "order": {"external_api"},
                     "invoice": {"external_api"}, "service": {"unstructured_retrieval"},
                     "document": {"unstructured_retrieval"}}
        needs = _DEFAULTS.get(primary_object.object_type, {"structured_lookup"})
    return needs or {"structured_lookup"}
```

This replaces v2's modality classification from routing. `request_flags` are more specific than modality — `needs_price=True` directly maps to a tool, while `structured_lookup` is a lossy category.

**Ingestion signal boosting**: the tool selector also checks specific `request_flags` and `retrieval_hints` for direct tool bonuses:

| Ingestion Signal | Boost |
| --- | --- |
| `request_flags.needs_price == True` | +0.2 for `pricing_lookup_tool` |
| `request_flags.needs_shipping_info == True` | +0.2 for `shipping_lookup_tool` |
| `request_flags.needs_documentation == True` | +0.2 for `document_lookup_tool` |
| `request_flags.needs_protocol == True` | +0.2 for `technical_rag_tool` |
| `retrieval_hints.suggested_tools` contains tool_name | +0.15 for that tool |

This means if a customer says "Check order 12345 and send me the shipping info", the ingestion parser sets `needs_shipping_info=True`, which boosts `shipping_lookup_tool` alongside `order_lookup_tool` -- without the executor having to guess from the object type alone.

Scoring: a tool that matches on all signals scores higher than one matching on two. Tools already called in a previous iteration are deprioritized unless the retry strategy explicitly requests them with refined constraints.

**Customer support example:**

User asks: "What is the recommended protocol for Anti-CD3 antibody in IHC?"

Context: `object_type=product`, `act=inquiry`, `request_flags.needs_protocol=True`

Registry scan:
- `catalog_lookup_tool`: supports product + inquiry + structured_lookup --> object + act match
- `technical_rag_tool`: supports product + inquiry + unstructured_retrieval --> object + act + retrieval needs match (needs_protocol)
- `order_lookup_tool`: supports order + inquiry + external_api --> no match (wrong object_type)

Selected: `[catalog_lookup_tool, technical_rag_tool]`

#### Step 2: Build Requests

Builds a `ToolRequest` for each selected tool. The constraint-enrichment logic from `requests.py` is reused (renamed to `request_builder.py`), but the interface changes: it now reads from `ExecutionContext` instead of `ExecutionIntent`.

Each selected tool gets a `ToolRequest` with:
- The customer's query
- Resolved object constraints (catalog number, product name, business line)
- Retrieval hints (dialogue act, request_flags)
- Tool-specific enrichment (catalog constraints, RAG constraints, QuickBooks constraints)

**What changes from v2**: the current `build_tool_request(intent, tool_name)` takes `ExecutionIntent` (a routing contract). In v3, it takes `ExecutionContext` (an executor-internal contract). The internal enrichment functions (`_catalog_constraints`, `_rag_constraints`, `_quickbooks_constraints`) are reusable -- only the top-level function signature changes to read from `ExecutionContext` fields instead of `ExecutionIntent` fields.

#### Step 3: Dispatch

Calls tools through the existing `safe_dispatch_tool()` from `src/tools/dispatcher.py`.

Dispatch strategy:
- **Single tool**: call directly
- **Multiple tools, all `can_run_in_parallel=True`**: dispatch concurrently
- **Multiple tools, some sequential**: respect ordering. If tool A returns information that tool B needs, run A first.

Sequencing is determined by:
1. Tool capability flags (`can_run_in_parallel`)
2. Whether a tool's constraints reference another tool's output type (e.g., RAG may benefit from catalog results for product context)

#### Step 4: Evaluate Completeness

After each dispatch round, the executor evaluates whether the results are sufficient to answer the customer's question.

```python
def evaluate_completeness(
    context: ExecutionContext,
    executed_calls: list[ExecutedToolCall],
) -> CompletenessResult:
```

Completeness criteria (deterministic rules, evaluated in order):

| # | Condition | Assessment | Rationale |
| --- | --- | --- | --- |
| 1 | Max iterations reached | `done` | Hard stop. Return whatever we have. |
| 2 | All tools returned `status=error` | `failed` | Nothing worked. Responser will explain the failure. |
| 3 | All tools returned `status=empty` and no retries remain | `done` | Exhausted options. |
| 4 | All tools returned `status=empty` and retries remain, but primary_object is None | `escalate_to_llm` | No resolved object means deterministic retry cannot pick better keywords. Needs LLM reasoning. |
| 5 | All tools returned `status=empty` and retries remain, primary_object exists | `retry_with_fallback` | Try different retrieval type tools (e.g., structured failed -> try unstructured). |
| 6 | Retrieval needs include `unstructured_retrieval`, got structured facts but zero unstructured snippets, RAG not yet called | `retry_add_rag` | Customer's question likely needs technical context beyond catalog data. |
| 7 | Some tools `ok`, some tools `error` | `done` | Partial success. Return what we have; responser handles partial results. |
| 8 | Primary tool `ok` with non-empty primary_records or structured_facts | `done` | Core question answered. |
| 9 | `request_flags.needs_shipping_info=True` but `shipping_lookup_tool` not called and order data available | `retry_add_tool` | Ingestion explicitly flagged shipping need. |
| 10 | None of the above matched | `escalate_to_llm` | Rules cannot determine sufficiency. Let LLM evaluate semantically. |

**Customer support scenario -- fallback:**

User: "Tell me about the CD19 CAR construct"

- Iteration 1: `catalog_lookup_tool` returns `status=empty` (no exact product match)
- Evaluate: all tools empty, retries remain --> `retry_with_fallback`
- Iteration 2: `technical_rag_tool` selected (different retrieval type, not yet called)
- Result: RAG returns technical snippets about CD19 CAR constructs --> `sufficient`

This fallback behavior is impossible in v2, where routing pre-selects tools and the executor blindly runs them.

## Reasoning Strategy: Two Levels

The executor uses a **two-level reasoning strategy**. Most customer queries are handled by fast deterministic rules (Level 1). Complex or ambiguous scenarios escalate to LLM-backed reasoning (Level 2).

```
                ┌─────────────────────────────────────────────┐
  Level 1       │  Deterministic reasoning (~80% of queries)  │
  (fast)        │  Rule-based tool scoring + rule-based       │
                │  completeness evaluation                    │
                │                                             │
                │  Latency: 0ms reasoning overhead            │
                │  Cost: zero LLM calls for reasoning         │
                └─────────────────────────────────────────────┘

                ┌─────────────────────────────────────────────┐
  Level 2       │  LLM reasoning (~20% of queries)            │
  (smart)       │  LLM selects tools + LLM evaluates          │
                │  completeness + LLM refines queries          │
                │                                             │
                │  Latency: 1-2 LLM calls per iteration       │
                │  Cost: justified only for complex scenarios  │
                └─────────────────────────────────────────────┘
```

### Level 1: Deterministic Reasoning

Level 1 handles routine customer support queries where the correct tools are predictable from the object type and request_flags.

**Tool selection**: score-based matching against ToolCapability fields (described in Tool Selection Algorithm below).

**Completeness evaluation**: rule-based checks (at least one `status=ok`, retry on all-empty, etc.).

**When Level 1 is sufficient:**

| Scenario | Why deterministic works |
| --- | --- |
| "What is PM-AB0001?" | object_type=product -> catalog_lookup_tool. Obvious. |
| "Check order 12345" | object_type=order -> order_lookup_tool. Obvious. |
| "Send me the datasheet" | object_type=document -> document_lookup_tool. Obvious. |
| Catalog returns empty, RAG available | Rule: all-empty + retries remain -> try different retrieval type. Predictable. |

Level 1 is fast, predictable, testable, and covers the majority of customer interactions.

### Level 2: LLM Reasoning (ReAct)

Level 2 activates when Level 1 cannot make a confident decision. It follows the **ReAct** (Reasoning + Acting) pattern: the LLM explicitly writes out its thinking before each action.

**When Level 2 activates:**

| Trigger | Example |
| --- | --- |
| Deterministic tool selector returns no tools above threshold | User asks something novel that doesn't match any object type cleanly |
| Multiple tools score equally and the intent is ambiguous | "Tell me everything about this antibody" -- catalog? RAG? documents? all? |
| First iteration returned partial results and the evaluator cannot determine if it's enough | Got product specs but user asked about "recommended protocol" -- is the storage temp line sufficient, or do they need a full protocol? |
| Query needs refinement before retry | Catalog returned empty for "lipofectamine alternative" -- what keywords should we try in RAG? |
| Mixed intent with multiple objects | "Check my order for PM-CAR0001 and explain the CAR-T mechanism" -- two objects, two tool types, need to plan the combination |

**ReAct trace format:**

The LLM reasoning follows a strict Thought / Action / Observation cycle:

```
Thought: [What the LLM thinks about the current state and what to do next]
Action:  [Which tool(s) to call and with what parameters]
Observation: [What the tool returned -- injected by the system, not generated by LLM]
Thought: [Assessment of the result and next step]
...
Final:   [Conclusion -- sufficient or give up]
```

**Full ReAct example -- technical consultation:**

```
Customer: "What is the recommended protocol for using Anti-CD3 antibody in IHC?"

Context:
  object_type: product
  dialogue_act: inquiry
  request_flags: needs_protocol=True
  resolved_object: Anti-CD3 Antibody (PM-AB0042)

--- Iteration 1 ---

Thought: The customer is asking about a specific product (Anti-CD3, PM-AB0042)
         AND a usage protocol for IHC. I need two types of information:
         1. Product specifications (from catalog) to confirm the product identity
         2. IHC protocol details (from technical knowledge base) for the procedure
         I should call both catalog_lookup_tool and technical_rag_tool.

Action:  catalog_lookup_tool(catalog_number="PM-AB0042")
         technical_rag_tool(query="Anti-CD3 antibody IHC protocol")

Observation:
  catalog_lookup_tool -> ok
    product: Anti-CD3 Antibody, PM-AB0042, monoclonal mouse anti-human
    storage: -20°C, applications: IHC, WB, FC
  technical_rag_tool -> ok
    snippet 1: "IHC Protocol for Anti-CD3: 1) Deparaffinize sections...
                2) Antigen retrieval in citrate buffer pH 6.0...
                3) Block with 5% BSA... 4) Dilute antibody 1:100..."
    snippet 2: "Recommended positive control: human tonsil tissue..."

Thought: I have both the product specs (confirms this is an IHC-compatible antibody)
         and a detailed IHC protocol with dilution, antigen retrieval, and controls.
         This fully answers the customer's question about recommended protocol.

Final: sufficient (2 tools, 1 iteration)
```

**Full ReAct example -- empty result with fallback:**

```
Customer: "Do you have anything similar to Lipofectamine for mRNA delivery?"

Context:
  object_type: product
  dialogue_act: inquiry
  request_flags: needs_recommendation=True
  resolved_object: None (no exact product match -- "Lipofectamine" is a competitor product)

--- Iteration 1 (Level 1 attempt) ---

Deterministic selection: catalog_lookup_tool (product + inquiry)
catalog_lookup_tool -> empty (no product named "Lipofectamine" in our catalog)

Deterministic evaluation: all-empty, retries remain.
  But the query is about a competitor product with no resolved object.
  Level 1 cannot determine what keyword to use for retry.
  -> Escalate to Level 2.

--- Iteration 2 (Level 2 kicks in) ---

Thought: The catalog returned nothing because "Lipofectamine" is a Thermo Fisher
         product, not ours. The customer is asking for alternatives in our catalog.
         "Lipofectamine" is a cationic lipid transfection reagent used for mRNA
         delivery. Our equivalent category is mRNA-LNP (lipid nanoparticle)
         products. I should search RAG for our mRNA delivery solutions and also
         try the catalog with "mRNA-LNP" as the product category.

Action:  catalog_lookup_tool(product_name="mRNA-LNP", business_line="mrna_lnp")
         technical_rag_tool(query="mRNA lipid nanoparticle delivery transfection reagent")

Observation:
  catalog_lookup_tool -> ok
    3 products found: PM-LNP-0001 (mRNA-LNP Kit), PM-LNP-0002, PM-LNP-0003
  technical_rag_tool -> ok
    snippet: "ProMab's mRNA-LNP delivery platform provides ready-to-use
             lipid nanoparticle formulations optimized for mRNA encapsulation..."

Thought: Found our mRNA-LNP product line as alternatives to Lipofectamine,
         plus technical context about the platform. This answers the customer's
         question about alternatives.

Final: sufficient (3 tool calls across 2 iterations)
```

This second example shows something Level 1 **cannot do**: understanding that "Lipofectamine" is a competitor product and reformulating the query as "mRNA-LNP" for our catalog. Only LLM reasoning can make that domain knowledge connection.

### How the Two Levels Interact

```python
# In engine.py -- simplified pseudocode

def run_executor(ingestion_bundle, resolved_object_state, route_decision, memory_snapshot):
    context = build_execution_context(...)

    while context.iteration < context.max_iterations:
        context.iteration += 1

        # --- LEVEL 1: Deterministic ---
        selections = deterministic_select_tools(context, registry)

        if not selections or context.escalate_to_llm:
            # --- LEVEL 2: LLM ReAct ---
            selections = llm_select_tools(context, registry)
            context.reasoning_level = "llm"

        requests = build_requests(context, selections)
        results = dispatch(requests)
        context.all_executed_calls.extend(results)

        # --- Evaluate ---
        if context.reasoning_level == "llm":
            completeness = llm_evaluate_completeness(context, results)
        else:
            completeness = deterministic_evaluate_completeness(context, results)

        if completeness.is_sufficient:
            break

        # Prepare next iteration
        if completeness.action == "escalate_to_llm":
            context.escalate_to_llm = True
        context.tools_called.extend([r.tool_name for r in results])

    return build_execution_result(context)
```

### Level 2 Escalation Triggers

The executor starts at Level 1 and escalates to Level 2 only when the completeness evaluator returns `action="escalate_to_llm"`. This happens in two cases (see completeness rules #4 and #10 above):

1. **All tools empty + no resolved object**: the query references something not in our catalog (e.g., a competitor product). Deterministic retry would just call the same tools with the same keywords. LLM reasoning can reformulate the query.

2. **Rules cannot determine sufficiency**: got some data, but unclear if it answers the customer's specific question. LLM reasoning evaluates semantically.

The escalation is a one-way door within a single execution: once escalated, all remaining iterations use Level 2.

### LLM Reasoning Prompt Design

The Level 2 prompt gives the LLM structured context and asks for a specific output format:

```
You are the reasoning engine of a biotech customer support agent.

Current customer query: {query}
Resolved entity: {primary_object or "none"}
Dialogue act: {dialogue_act}
Retrieval needs: {derived_retrieval_needs}
Request flags: {active_request_flags}

Tools already called and their results:
{previous_tool_calls_and_results}

Available tools (from registry):
{tool_capabilities_summary}

Based on the above, decide what to do next.

Output format:
Thought: <your reasoning about what information is still needed>
Action: <tool_name(param=value)> or "sufficient" or "failed"
```

The system injects the Observation after each Action, then re-prompts with the updated state.

**Key constraints on the LLM reasoning:**
- The LLM can only select tools from the registry -- it cannot invent tools
- The LLM can refine query parameters but cannot change the resolved entity
- Maximum 2 LLM reasoning calls per execution (to bound latency and cost)
- The LLM's Thought is logged for observability but not shown to the customer

### Configuration

```python
EXECUTOR_CONFIG = {
    "max_iterations": 3,             # Maximum reasoning loops
    "parallel_dispatch": True,       # Enable concurrent tool calls
    "fallback_on_empty": True,       # Try alternative tools if primary returns empty
    "enable_llm_reasoning": True,    # Allow Level 2 escalation
    "max_llm_reasoning_calls": 2,    # Maximum LLM reasoning calls per execution
    "llm_reasoning_model": "default", # Model for Level 2 reasoning
}
```

For a customer support agent, 3 iterations is the practical maximum. Most queries resolve in 1 iteration with Level 1. Mixed queries (product + technical) may take 2. Only edge cases with empty primary results or ambiguous queries hit Level 2.

### Implementation Order

The two levels can be built sequentially:

1. **Phase A**: Build Level 1 only (deterministic). This already provides the reasoning loop, fallback behavior, and covers ~80% of customer queries. Deploy and validate.

2. **Phase B**: Add Level 2 (LLM reasoning). Wire in escalation triggers, prompt design, and the ReAct cycle. The architecture does not change -- only `engine.py` gains an additional code path at the SELECT and EVALUATE steps.

This means the system is useful after Phase A. Phase B adds intelligence for edge cases without disrupting the deterministic core.

## Data Contracts

### ReasoningStep (trace record)

Each iteration of the reasoning loop produces one `ReasoningStep` for observability and debugging.

```python
class ReasoningStep(BaseModel):
    """One step in the executor's reasoning trace."""
    iteration: int
    level: Literal["deterministic", "llm"]  # Which reasoning level made this decision
    thought: str = ""                       # LLM reasoning text (empty for deterministic)
    selected_tools: list[str] = Field(default_factory=list)
    dispatch_results: list[str] = Field(default_factory=list)  # "tool_name:status" pairs
    completeness_action: str = ""           # "done", "retry_with_fallback", "escalate_to_llm", etc.
    completeness_reason: str = ""           # Human-readable explanation
```

### ExecutionContext (internal state)

Carries the full context through the reasoning loop. Not exposed outside the executor. Built by `build_execution_context()` from upstream inputs.

```python
class ExecutionContext(BaseModel):
    """Internal state for the executor reasoning loop."""
    # From upstream modules
    query: str
    primary_object: ObjectCandidate | None
    secondary_objects: list[ObjectCandidate]
    dialogue_act: DialogueActResult
    resolved_object_constraints: dict[str, str]
    memory_snapshot: MemorySnapshot | None

    # Ingestion signals (used for tool selection and retrieval needs derivation)
    request_flags: ParserRequestFlags | None = None
    retrieval_hints: ParserRetrievalHints | None = None

    # Loop state
    iteration: int = 0
    max_iterations: int = 3
    tools_called: list[str] = Field(default_factory=list)
    all_executed_calls: list[ExecutedToolCall] = Field(default_factory=list)

    # Reasoning state
    reasoning_trace: list[ReasoningStep] = Field(default_factory=list)
    reasoning_level: Literal["deterministic", "llm"] = "deterministic"
    escalate_to_llm: bool = False
```

### ExecutionResult (output contract)

Replaces `ExecutionRun`. This is the executor's output to the responser.

```python
class ExecutionResult(BaseModel):
    """Output of the executor module."""
    executed_calls: list[ExecutedToolCall] = Field(default_factory=list)
    merged_results: MergedResults = Field(default_factory=MergedResults)
    iterations: int = 1
    final_status: ExecutionStatus = "empty"
    reason: str = ""
    reasoning_trace: list[ReasoningStep] = Field(default_factory=list)
```

Key difference from `ExecutionRun`:
- No `intent: ExecutionIntent` field -- the executor does not pass routing internals downstream
- No `plan: ExecutionPlan` field -- planning is internal to the executor
- Adds `iterations` field to track how many loops ran
- Adds `reasoning_trace` for observability -- each step records level, thought, tools, and result
- Uses typed `MergedResults` instead of raw `dict[str, object]`

### MergedResults (typed result container)

Replaces the current `dict[str, object]` in `merged_results`.

```python
class MergedResults(BaseModel):
    """Typed container for aggregated tool results."""
    primary_facts: dict[str, Any] = Field(default_factory=dict)
    supporting_facts: dict[str, Any] = Field(default_factory=dict)
    snippets: list[dict[str, Any]] = Field(default_factory=list)
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
```

### ToolSelection (internal)

Result of the tool selector for one tool.

```python
class ToolSelection(BaseModel):
    """A tool selected by the executor for dispatch."""
    tool_name: str
    match_score: float        # How well this tool matches the context
    match_reasons: list[str]  # Which criteria matched
    role: ToolCallRole        # "primary" or "supporting"
    can_run_in_parallel: bool
    sequencing_hint: str = "" # e.g., "run_after:catalog_lookup_tool"
```

### CompletenessResult (internal)

Result of the completeness evaluator.

```python
class CompletenessResult(BaseModel):
    """Assessment of whether execution results are sufficient."""
    is_sufficient: bool
    action: Literal[
        "done",                  # Results sufficient, or max iterations reached
        "failed",                # All tools errored, cannot recover
        "retry_with_fallback",   # Try different retrieval type tools (deterministic)
        "retry_add_rag",         # Specifically add RAG for hybrid completeness
        "retry_add_tool",        # Add a specific tool flagged by ingestion signals
        "escalate_to_llm",       # Deterministic rules cannot decide; use Level 2
    ]
    reason: str
    suggested_tools: list[str] = Field(default_factory=list)
```

### Reused contracts

These contracts are unchanged from v2:

- `PlannedToolCall` -- from current `models.py`
- `ExecutedToolCall` -- from current `models.py`
- `ToolRequest` -- from `src/tools/models.py`
- `ToolResult` -- from `src/tools/models.py`

## Target File Structure

```
src/executor/                      # Renamed from src/execution/
├── __init__.py                    # Public exports: run_executor, ExecutionResult
├── models.py                      # ExecutionResult, ExecutionContext, MergedResults, etc.
├── engine.py                      # Reasoning loop orchestration (new)
├── tool_selector.py               # Registry-based tool selection (replaces planner.py + planner_rules.py)
├── request_builder.py             # Build ToolRequest per tool (migrated from requests.py)
├── completeness.py                # Evaluate result sufficiency (new)
├── merger.py                      # Merge multi-tool results (migrated from merger.py)
└── dispatcher.py                  # Dispatch tool calls, handle parallel (migrated from executor.py)
```

### File mapping from current code

| v2 file | v3 file | Action |
| --- | --- | --- |
| `execution/planner.py` | `executor/tool_selector.py` | **Replace** -- reads registry instead of hardcoded rules |
| `execution/planner_rules.py` | (deleted) | **Delete** -- all rules absorbed into registry-based selection |
| `execution/executor.py` | `executor/dispatcher.py` | **Evolve** -- add parallel dispatch, keep safe_dispatch pattern |
| `execution/requests.py` | `executor/request_builder.py` | **Adapt** -- change input from `ExecutionIntent` to `ExecutionContext`; reuse internal `_catalog_constraints`, `_rag_constraints`, etc. |
| `execution/merger.py` | `executor/merger.py` | **Move** -- reuse as-is |
| `execution/models.py` | `executor/models.py` | **Evolve** -- add ExecutionResult, ExecutionContext; keep ExecutedToolCall |
| `execution/runtime.py` | `executor/__init__.py` | **Replace** -- new public API |
| `execution/status.py` | `executor/merger.py` | **Merge** -- small utility, absorb into merger |
| (new) | `executor/engine.py` | **Create** -- reasoning loop |
| (new) | `executor/completeness.py` | **Create** -- result evaluation |

## Customer Support Scenarios

### Scenario 1: Simple product inquiry (1 iteration)

```
Customer: "What is PM-AB0001?"
Context:  object_type=product, act=inquiry

Iteration 1:
  Select:   catalog_lookup_tool (product + inquiry)
  Dispatch: catalog_lookup_tool -> ok, returns product record
  Evaluate: status=ok, primary_records non-empty -> sufficient

Result: 1 iteration, 1 tool call
```

### Scenario 2: Technical consultation (1 iteration, 2 tools)

```
Customer: "What is the recommended storage condition for Anti-CD3 antibody?"
Context:  object_type=product, act=inquiry, request_flags: needs_protocol=True

Iteration 1:
  Select:   catalog_lookup_tool (product + inquiry)
            technical_rag_tool (product + inquiry + needs_protocol boost)
  Dispatch: catalog_lookup_tool -> ok (product specs)
            technical_rag_tool -> ok (storage protocol snippets)
  Evaluate: structured + unstructured content --> sufficient

Result: 1 iteration, 2 tool calls
```

### Scenario 3: Order + shipping (1 iteration, parallel)

```
Customer: "What's the status of order 12345 and when will it arrive?"
Context:  object_type=order, act=inquiry, request_flags: needs_order_status=True, needs_shipping_info=True

Iteration 1:
  Select:   order_lookup_tool (order + inquiry + needs_order_status boost)
            shipping_lookup_tool (needs_shipping_info boost, can_run_in_parallel)
  Dispatch: both in parallel
  Evaluate: both ok -> sufficient

Result: 1 iteration, 2 tool calls (parallel)
```

### Scenario 4: Empty result fallback (2 iterations)

```
Customer: "Tell me about the CD19 CAR-T construct"
Context:  object_type=product, act=inquiry

Iteration 1:
  Select:   catalog_lookup_tool (product + inquiry)
  Dispatch: catalog_lookup_tool -> empty (no exact match for "CD19 CAR-T construct")
  Evaluate: all empty, retries remain -> retry_with_fallback

Iteration 2:
  Select:   technical_rag_tool (product + unstructured_retrieval, not yet called)
  Dispatch: technical_rag_tool -> ok (technical content about CD19 CAR-T)
  Evaluate: snippets found -> sufficient

Result: 2 iterations, 2 tool calls
```

### Scenario 5: Mixed business + technical (1 iteration, 2 tools)

```
Customer: "I ordered PM-CAR0001 last month, can you check the order
           and also explain the CAR-T construct?"
Context:  object_type=order, act=inquiry
          secondary_object: product (PM-CAR0001)
          request_flags: needs_order_status=True, needs_documentation=True

Iteration 1:
  Select:   order_lookup_tool (order + inquiry + needs_order_status boost)
            technical_rag_tool (product + inquiry + needs_documentation boost)
  Dispatch: order_lookup_tool -> ok (order record)
            technical_rag_tool -> ok (CAR-T technical content)
  Evaluate: both ok -> sufficient

Result: 1 iteration, 2 tool calls
```

### Scenario 6: Document request with product context (1 iteration)

```
Customer: "Can you send me the datasheet for PM-AB0001?"
Context:  object_type=document, act=inquiry, request_flags: needs_documentation=True

Iteration 1:
  Select:   document_lookup_tool (document + inquiry + needs_documentation boost)
  Dispatch: document_lookup_tool -> ok (datasheet reference)
  Evaluate: artifact found -> sufficient

Result: 1 iteration, 1 tool call
```

### Scenario 7: QuickBooks not configured (1 iteration, partial)

```
Customer: "What's my latest invoice?"
Context:  object_type=invoice, act=inquiry, request_flags: needs_invoice=True

Iteration 1:
  Select:   invoice_lookup_tool (invoice + inquiry + needs_invoice boost)
  Dispatch: invoice_lookup_tool -> partial (QuickBooks not configured)
  Evaluate: partial with "not_configured" -> sufficient (cannot retry, system limitation)

Result: 1 iteration, 1 tool call, status=partial
```

### Scenario 8: Level 2 -- competitor product translation (2 iterations)

This scenario is impossible with Level 1 alone. The customer references a competitor's product name that does not exist in our catalog. Level 2 LLM reasoning translates the competitor reference into our product category.

```
Customer: "Do you have anything similar to Lipofectamine for mRNA delivery?"
Context:  object_type=product, act=inquiry, request_flags: needs_recommendation=True
          resolved_object: None (Lipofectamine is not in our catalog)

Iteration 1 (Level 1):
  Select:   catalog_lookup_tool (product + inquiry)
  Dispatch: catalog_lookup_tool -> empty (no "Lipofectamine" in catalog)
  Evaluate: all empty, no resolved object -> cannot determine retry keyword
            -> escalate to Level 2

Iteration 2 (Level 2 -- ReAct):
  Thought:  "Lipofectamine is a Thermo Fisher cationic lipid reagent for
            nucleic acid delivery. The customer wants our alternative.
            Our equivalent is the mRNA-LNP product line. I should search
            our catalog for mRNA-LNP products and query RAG for our
            mRNA delivery platform information."
  Action:   catalog_lookup_tool(product_name="mRNA-LNP", business_line="mrna_lnp")
            technical_rag_tool(query="mRNA lipid nanoparticle delivery")
  Dispatch: catalog -> ok (3 mRNA-LNP products found)
            rag -> ok (platform overview snippets)
  Evaluate: product alternatives found + technical context -> sufficient

Result: 2 iterations, 3 tool calls, Level 2 used
```

### Scenario 9: Level 2 -- ambiguous sufficiency (2 iterations)

The first tool returns data, but Level 1 cannot tell whether it actually answers the customer's specific question. Level 2 evaluates semantically.

```
Customer: "What concentration should I use for Western Blot with PM-AB0001?"
Context:  object_type=product, act=inquiry, request_flags: needs_protocol=True

Iteration 1 (Level 1):
  Select:   catalog_lookup_tool (product + inquiry)
            technical_rag_tool (product + needs_protocol boost)
  Dispatch: catalog -> ok (product specs: 1mg/mL stock, applications: WB, IHC, FC)
            rag -> empty (no specific WB protocol found for this antibody)
  Evaluate: catalog returned ok but only lists "WB" as supported application,
            no dilution information. RAG returned empty.
            Level 1 rule: status=ok -> sufficient?
            But needs_protocol=True and no unstructured content found -> retry_add_rag?
            RAG already called and returned empty -> ambiguous.
            -> escalate to Level 2

Iteration 2 (Level 2 -- ReAct):
  Thought:  "The customer specifically asked about Western Blot concentration.
            The catalog only confirms WB is a supported application but has no
            dilution data. RAG returned nothing for this specific antibody.
            I should try RAG with a broader query -- general WB protocols for
            monoclonal antibodies, which typically recommend 1:500 to 1:2000."
  Action:   technical_rag_tool(query="monoclonal antibody Western Blot dilution protocol")
  Dispatch: rag -> ok (general WB protocol: "Typical dilution 1:1000,
            optimize between 1:500-1:2000")
  Evaluate: now have product identity + general WB protocol -> sufficient
            (responser will note this is a general recommendation,
             not product-specific)

Result: 2 iterations, 3 tool calls, Level 2 used
```

## Tool Selection Algorithm

### Matching

For each registered tool capability, compute a match score:

```python
def _score_tool(capability: ToolCapability, context: ExecutionContext) -> float:
    score = 0.0

    # Object type match (strongest signal)
    if context.primary_object and context.primary_object.object_type in capability.supported_object_types:
        score += 0.4

    # Secondary objects (weaker signal, enables multi-tool selection)
    for obj in context.secondary_objects:
        if obj.object_type in capability.supported_object_types:
            score += 0.1

    # Dialogue act match
    if context.dialogue_act.act in capability.supported_dialogue_acts:
        score += 0.3

    # Retrieval needs match (replaces v2 modality matching)
    retrieval_needs = _derive_retrieval_needs(context.request_flags, context.primary_object)
    for need in retrieval_needs:
        if need in capability.supported_modalities:
            score += 0.15

    # Ingestion signal boosting (specific flag -> specific tool)
    score += _ingestion_boost(capability.tool_name, context)

    return score


# Ingestion request_flags -> tool boost mapping
_FLAG_BOOST = {
    "needs_price":         "pricing_lookup_tool",
    "needs_shipping_info": "shipping_lookup_tool",
    "needs_documentation": "document_lookup_tool",
    "needs_protocol":      "technical_rag_tool",
}

def _ingestion_boost(tool_name: str, context: ExecutionContext) -> float:
    boost = 0.0
    if context.request_flags:
        for flag_name, boosted_tool in _FLAG_BOOST.items():
            if getattr(context.request_flags, flag_name, False) and tool_name == boosted_tool:
                boost += 0.2

    if context.retrieval_hints and tool_name in (context.retrieval_hints.suggested_tools or []):
        boost += 0.15

    return boost
```

### Selection threshold

- Score >= 0.6: select as primary tool
- Score >= 0.3 and retrieval needs match: select as supporting tool
- Score < 0.3: skip

### Deprioritization

Tools already called in previous iterations get a -0.5 penalty unless `retry_refine` is the action.

### Sequencing

When multiple tools are selected:
1. Check `can_run_in_parallel` on each capability
2. If all selected tools are parallel-safe: dispatch concurrently
3. If any tool requires external system AND another returns structured facts the first might need: run the structured-fact tool first
4. Default: sequential in score order (highest first)

## LangGraph Integration

The reasoning loop maps naturally to a LangGraph state graph. LangGraph is not required for the initial implementation (a plain `while` loop works), but it becomes valuable when Level 2 LLM reasoning is added.

### State Graph

```
                    ┌──────────┐
                    │  START   │
                    └────┬─────┘
                         │
                    ┌────▼──────┐
                    │  SELECT   │─── Level 1: deterministic scoring
                    │  (tools)  │─── Level 2: LLM ReAct reasoning
                    └────┬──────┘
                         │
                    ┌────▼─────┐
                    │  BUILD   │
                    └────┬─────┘
                         │
                    ┌────▼─────┐
                    │ DISPATCH │
                    └────┬─────┘
                         │
                    ┌────▼──────┐     sufficient
                    │ EVALUATE  │────────────▶ MERGE ──▶ END
                    │           │─── Level 1: rule check
                    │           │─── Level 2: LLM assessment
                    └────┬──────┘
                         │ insufficient
                         │ (iteration < max)
                         │
                    ┌────▼──────┐
                    │  SELECT   │  (next iteration, possibly escalated to Level 2)
                    └───────────┘
```

State graph nodes:
- `select`: reads registry, outputs tool list (Level 1 or Level 2)
- `build`: constructs ToolRequest objects
- `dispatch`: calls tools (parallel/sequential)
- `evaluate`: checks completeness (Level 1 or Level 2)
- `merge`: aggregates results

State: `ExecutionContext` (the typed state object passed between nodes).

### Why LangGraph helps

| Benefit | Without LangGraph | With LangGraph |
| --- | --- | --- |
| Reasoning loop | Manual `while` loop in `engine.py` | Declarative state graph with explicit transitions |
| Level escalation | `if/else` in loop body | Conditional edges: `select_l1 -> evaluate -> select_l2` |
| State checkpointing | Manual serialization | Built-in state snapshots at each node |
| Trace visualization | Custom logging | LangSmith integration for visual trace |
| Parallel dispatch | Manual `asyncio.gather` | LangGraph `Send` API for fan-out |

### Implementation plan

**Phase A (no LangGraph)**: plain `while` loop with Level 1 only. The same `tool_selector`, `request_builder`, `completeness`, `merger` modules.

**Phase B (LangGraph)**: replace the `while` loop with a LangGraph `StateGraph`. The same modules plug in as node functions. Level 2 LLM reasoning is added as an alternative path in the SELECT and EVALUATE nodes.

The architecture does not change between phases. Only `engine.py` changes.

## Integration with `app/service.py`

### Current (v2)

```python
execution_plan = build_execution_plan(route.execution_intent)
execution_run = run_execution_plan(execution_plan)

# responser uses execution_run.intent, execution_run.plan, etc.
response_bundle = build_response_bundle(ResponseInput(
    execution_run=execution_run,
    ...
))
```

### Target (v3)

```python
execution_result = None
if route.action == "execute":
    execution_result = run_executor(
        ingestion_bundle=ingestion_bundle,
        resolved_object_state=resolved_object_state,
        route_decision=route,
        memory_snapshot=memory_snapshot,
    )

# responser uses execution_result (no routing internals)
response_bundle = build_response_bundle(ResponseInput(
    execution_result=execution_result,
    ...
))
```

The responser's `ResponseInput` changes from `execution_run: ExecutionRun` to `execution_result: ExecutionResult | None`. This is a breaking change, handled in the Responser migration.

## Migration Steps

### Step 1: File restructure (safe, no behavior change)

1. Create `src/executor/` directory
2. Copy files with rename:
   - `execution/requests.py` --> `executor/request_builder.py`
   - `execution/merger.py` --> `executor/merger.py`
   - `execution/models.py` --> `executor/models.py`
   - `execution/executor.py` --> `executor/dispatcher.py`
3. Update all internal imports
4. Create `executor/__init__.py` that re-exports old API for backward compatibility
5. Verify tests pass

### Step 2: Add new contracts (additive, no breakage)

1. Add `ExecutionResult`, `ExecutionContext`, `MergedResults` to `executor/models.py`
2. Keep `ExecutionRun` temporarily for backward compatibility
3. Add conversion function: `ExecutionResult.from_execution_run(run: ExecutionRun) -> ExecutionResult`

### Step 3: Implement tool selector (replaces planner)

1. Create `executor/tool_selector.py` with registry-based selection
2. Write tests comparing tool_selector output vs. planner_rules output for known scenarios
3. In `engine.py`, start with `tool_selector` but fall back to planner for any edge case

### Step 4: Implement reasoning loop

1. Create `executor/engine.py` with `while iteration < max_iterations` loop
2. Create `executor/completeness.py` with deterministic evaluation rules
3. Wire into `run_executor()` entry point
4. Initially limit to max_iterations=1 to match v2 behavior, then increase

### Step 5: Update service.py integration

1. Change `service.py` to call `run_executor()` instead of `build_execution_plan()` + `run_execution_plan()`
2. Update `ResponseInput` to accept `ExecutionResult`
3. Remove old `execution/` directory
4. Delete `planner_rules.py`

## Anti-Patterns

1. **LLM reasoning on every call.** When a customer asks "What is PM-AB0001?", the answer is obvious: call `catalog_lookup_tool`. Using an LLM to reason about this wastes time and money. Level 1 deterministic matching handles this in zero milliseconds. Reserve Level 2 for the cases that actually need it -- competitor product translation, ambiguous multi-tool scenarios, or results that need semantic evaluation.

2. **Skipping Level 1 entirely.** The opposite mistake: routing everything through LLM reasoning "because it's smarter." For a production customer support agent, 80% of queries are routine. Deterministic reasoning is faster, cheaper, and more predictable. Level 2 exists for the 20% where deterministic rules genuinely cannot decide.

3. **Unbounded iteration.** A customer support agent should not loop 10 times trying different tools. If 3 iterations cannot answer the question, the responser should explain what was found and what was not. Similarly, Level 2 LLM reasoning is capped at 2 LLM calls per execution.

4. **Re-resolving entities inside the executor.** The executor receives already-resolved objects from the objects module. It should not re-parse the user's message or re-resolve product names. Even Level 2 LLM reasoning should refine tool _parameters_, not re-resolve the entity itself.

5. **Coupling to routing internals.** The executor should not read `intent.selected_tools` or `intent.needs_clarification`. If routing decided to execute, the executor executes. It does not second-guess routing.

6. **Tools that decide what other tools to call.** Each tool returns data, not instructions. The executor alone decides the next action based on tool results. This applies to both Level 1 and Level 2.

7. **Leaking LLM reasoning to the customer.** Level 2's Thought traces are for internal observability. The customer never sees "I decided to try RAG because catalog was empty." The responser composes the customer-facing reply from tool results only.

## Dependencies

### Modules the executor calls

- `src/tools/registry.py` -- read `ToolCapability` list
- `src/tools/dispatcher.py` -- dispatch `ToolRequest`, receive `ToolResult`

### Modules that call the executor

- `src/app/service.py` -- the agent loop

### Modules the executor does not call

- `src/ingestion/` -- understanding is complete before executor runs
- `src/objects/` -- entity resolution is complete
- `src/routing/` -- route decision is made
- `src/responser/` -- response synthesis happens after executor
- `src/memory/` -- memory is read before executor, written after responser
