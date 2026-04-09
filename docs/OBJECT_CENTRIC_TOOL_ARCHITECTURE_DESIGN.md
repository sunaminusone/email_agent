# Object-Centric Tool Architecture Design

## Goal

Restructure the system around one primary question:

> What objects are present in this turn, and what tools should be used to answer questions about them?

This design replaces the current tendency to treat:

- catalog lookup
- technical RAG
- document lookup
- pricing
- order/shipping lookup

as parallel system paths.

Instead, the system should:

1. ingest and normalize the turn
2. extract and resolve objects
3. decide the user interaction act
4. choose one or more tools for those objects
5. synthesize a grounded response

## Why This Redesign Is Needed

Today, some modules are carrying too much responsibility.

The clearest example is `selection.py`, which currently mixes:

- alias normalization
- candidate generation
- exact lookup
- fuzzy recovery
- ambiguity handling
- partial orchestration decisions

This creates an architectural smell:

- catalog lookup no longer feels like a tool
- RAG feels like a parallel state machine instead of another tool
- object resolution, tool choice, and response behavior are coupled too tightly

The result is a system that can work, but is harder to scale cleanly.

## Core Design Principle

Use:

- **object-first**

before:

- **tool selection**

and before:

- **response generation**

The system should not begin by asking:

- "Should I go to catalog or RAG?"

It should begin by asking:

- "What product, service, document, order, invoice, or target is the user talking about?"

## Object x Modality Matrix

The architecture should explicitly model two separate dimensions:

### Dimension 1: Object

First determine what object is currently in play:

- `product`
- `service`
- `order`
- `invoice`
- `shipment`
- `document`
- `customer`
- `scientific_target`

### Dimension 2: Information Modality

Then determine what kind of information is needed for that object:

- `structured_lookup`
- `unstructured_retrieval`
- `external_api`
- `hybrid`

### Why This Separation Matters

The system should not confuse:

- object type

with:

- retrieval or execution modality

Examples:

- `product` does not mean structured lookup only
- `service` does not mean RAG only
- `order` does not always mean one external API call and nothing else

Instead, the system should always ask these questions in order:

1. what object is the user talking about?
2. what modality is needed to answer this turn?
3. which tools implement that modality?

### Examples

#### Product

- `product + structured_lookup`
  - catalog identity
  - applications
  - species reactivity
  - lead time
- `product + unstructured_retrieval`
  - datasheet text
  - protocol guidance
  - validation narrative
- `product + hybrid`
  - structured catalog facts plus unstructured technical/doc detail

#### Service

- `service + unstructured_retrieval`
  - service plan
  - workflow
  - models
  - validation
  - timeline
- `service + hybrid`
  - service-page RAG plus linked documents or pricing guidance

#### Order / Invoice

- `order + external_api`
  - order lookup
  - fulfillment or shipping status
- `invoice + external_api`
  - invoice details
  - balance
  - due date

### Design Rule

Object resolution must happen before modality selection.

This means:

- first resolve the object
- then select the modality
- then select the tools

That separation is what will keep:

- `selection.py`
- RAG
- catalog lookup
- API calls

from collapsing into one oversized decision layer.

## Top-Level Flow

The new architecture should follow this order:

1. ingest and normalize the user turn
2. extract all candidate objects
3. resolve active + current object state
4. classify dialogue act
5. choose tools
6. execute tools
7. synthesize a grounded answer

## Layer 1: Object Extraction

This layer should extract **all object candidates**, not just the first winning one.

Recommended object families:

- `product`
- `service`
- `scientific_target`
- `document`
- `order`
- `invoice`
- `shipment`
- `customer`

### Required Output Shape

Return a normalized object list, for example:

```python
[
    {
        "object_type": "product",
        "raw_value": "MSH2",
        "canonical_value": "",
        "identifier": "",
        "identifier_type": "",
        "confidence": 0.82,
        "source": "parser",
        "is_ambiguous": True,
    },
    {
        "object_type": "service",
        "raw_value": "mRNA-LNP delivery",
        "canonical_value": "mRNA-LNP Gene Delivery",
        "identifier": "",
        "identifier_type": "",
        "confidence": 0.94,
        "source": "service_registry",
        "is_ambiguous": False,
    },
]
```

### Design Rule

This layer should be additive, not destructive.

That means:

- keep multiple object candidates when they are real
- do not collapse a turn to one object too early
- preserve ambiguity explicitly

## Layer 2: Object Resolution

This layer answers:

> Which object is primary right now, and which objects remain secondary or ambiguous?

It should merge:

- current-turn extracted objects
- active session objects
- pending clarification objects
- selected candidates from prior turns

### Resolution Output

Recommended shape:

```python
{
    "primary_object": {...} | None,
    "secondary_objects": [...],
    "ambiguous_objects": [...],
    "active_object": {...} | None,
    "reason": "...",
}
```

### Resolution Rules

#### 1. Current explicit object beats old context

If the current turn explicitly names a new product or service:

- prefer the current-turn object
- do not let stale active context override it

#### 2. Ambiguity must remain visible

If one alias maps to multiple products:

- do not auto-pick one
- keep it in `ambiguous_objects`
- let later clarification or candidate selection resolve it

#### 3. Active context is a fallback, not a guess engine

If current-turn extraction is empty and the turn is clearly context-dependent:

- reuse active object only when the state supports it
- otherwise require clarification

## Layer 3: Dialogue Act Resolution

This layer is already being introduced in:

- [DIALOGUE_ACT_ROUTING_DESIGN.md](/Users/promab/anaconda_projects/email_agent/docs/DIALOGUE_ACT_ROUTING_DESIGN.md)

Its job is different from object resolution.

It answers:

> What is the user trying to do with the current object?

MVP acts:

- `ACKNOWLEDGE`
- `TERMINATE`
- `ELABORATE`
- `SELECTION`
- `INQUIRY`
- `UNKNOWN`

### Important Separation

- object resolution decides **what the user is talking about**
- dialogue act decides **what the user is doing with that object**

These two layers are complementary and must remain separate.

## Layer 4: Tool Selection

Once objects and dialogue act are known, tool selection becomes much simpler.

### Design Rule

Tools should be chosen from object + act, not from route slogans like:

- "catalog path"
- "RAG path"

### Canonical Tool Set

Recommended first-class tools:

- `catalog_lookup_tool`
- `technical_rag_tool`
- `document_lookup_tool`
- `pricing_lookup_tool`
- `order_lookup_tool`
- `shipping_lookup_tool`
- `invoice_lookup_tool`

### Example Mapping

#### Product + INQUIRY

Possible tools:

- `catalog_lookup_tool`
- `technical_rag_tool`
- `document_lookup_tool`

#### Service + INQUIRY

Possible tools:

- `technical_rag_tool`
- optionally `document_lookup_tool`

#### Product + SELECTION

Possible tools:

- no business answer tool yet
- first update active object from the chosen candidate
- then continue normal inquiry flow

#### Product + TERMINATE

Possible tools:

- none
- update session state only

## Retrieval Modality Is Not Object Type

This is a hard rule:

- `product` does **not** mean structured lookup only
- `service` does **not** mean RAG only

The correct decision order is:

1. determine the object
2. determine the needed modality

### Structured Sources Are Good For

- identifiers
- titles
- business line
- applications
- species
- pricing
- lead time

### Unstructured Sources Are Good For

- protocol detail
- validation narrative
- workflow explanation
- service plan explanation
- technical caveats
- brochure or datasheet text

### Hybrid Retrieval Must Be Allowed

Examples:

- `What applications is this antibody validated for?`
  - product object
  - structured lookup for product identity/application/species
  - technical/doc retrieval for validation language

- `Do you have more information on this service plan?`
  - service object
  - RAG for plan/workflow/timeline details

## The New Role of `selection.py`

After this redesign, `selection.py` should become much narrower.

It should primarily do:

- object candidate retrieval
- object candidate scoring
- ambiguity grouping

It should not be responsible for:

- broad response strategy
- deciding the whole answer modality
- carrying business-level orchestration

### Target Responsibility

`selection.py` should answer:

> Given an object query signal, what are the best candidate objects?

It should not answer:

> What should the system ultimately do next?

## Multi-Object Handling

The new design must support turns containing more than one object.

Example:

- `I want to know about mRNA-LNP delivery, and also send me the brochure for the matching kit.`

Expected representation:

- primary service object
- secondary product object request
- document intent attached to the product branch

This should not be flattened into one winning object too early.

## One Alias -> Many Products vs One Product -> Many Documents

These must remain separate cases.

### A. One Alias -> Many Products

Example:

- `MSH2`

Behavior:

- product ambiguity
- clarification required

### B. One Product -> Many Supporting Documents

Example:

- one `catalog_no`
- multiple protocol/doc/datasheet chunks

Behavior:

- no clarification
- aggregate by `catalog_no`
- synthesize across documents

## Session State Design

The session should store object-centric state, not route-centric state only.

Recommended session fields:

- `active_object`
- `secondary_active_objects`
- `pending_clarification`
- `candidate_object_sets`
- `revealed_attributes`
- `last_tool_results`

### Important Rule

Pending clarification should be typed.

Examples:

- `product_selection`
- `service_selection`
- `referential_scope`
- `identifier_type`

This allows later turns like `32122` to be interpreted in context.

## Suggested Module Split

Recommended future structure:

- `src/conversation/object_extraction.py`
  - gathers raw object candidates
- `src/conversation/object_resolution.py`
  - resolves primary/secondary/ambiguous objects
- `src/catalog/selection.py`
  - retrieves candidate products only
- `src/decision/dialogue_act.py`
  - interaction act classification
- `src/decision/tool_selection.py`
  - decides which tools to call
- `src/decision/execution_planner.py`
  - builds execution plan from objects + act + tools

This does not need to be rewritten all at once.

## Migration Plan

### Phase 1

Define object-centric interfaces without deleting current behavior.

- introduce explicit object result structures
- keep current catalog and RAG code alive
- adapt them behind a cleaner interface

### Phase 2

Shrink `selection.py` responsibilities.

- move response decisions out
- move modality decisions out
- keep candidate retrieval only

### Phase 3

Move execution planning to object + tool orchestration.

- `product + inquiry -> catalog + maybe rag`
- `service + inquiry -> rag`
- `product + selection -> state update`

### Phase 4

Unify response synthesis across tools.

- grounded structured facts
- grounded RAG snippets
- one renderer/composer layer

## Testing Strategy

This redesign should be validated at four levels:

### 1. Object Extraction Eval

Test whether the system extracts:

- products
- services
- targets
- orders
- documents

correctly from raw turns

### 2. Object Resolution Eval

Test whether the system resolves:

- current object
- active object
- ambiguity
- multi-object turns

correctly

### 3. Tool Selection Eval

Test whether the chosen tools match:

- object type
- dialogue act
- modality needs

### 4. Response Eval

Test whether final answers:

- remain grounded
- avoid repetition
- respect clarification boundaries
- sound natural

## Summary

The system should stop thinking in terms of:

- "catalog branch"
- "RAG branch"

and start thinking in terms of:

1. extract all objects
2. resolve object state
3. classify interaction act
4. choose tools
5. synthesize one grounded answer

That is the cleanest way to make:

- catalog lookup feel like a tool
- RAG feel like a tool
- `selection.py` smaller
- multi-turn behavior more coherent
- hybrid product/service answers easier to support
