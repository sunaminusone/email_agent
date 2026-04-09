# RAG Retrieval Enhancement Design

This document defines the proposed retrieval-enhancement design for the technical RAG stack.

It focuses on one concrete problem:

- follow-up queries often omit the subject
- the system may already know the subject from active context
- retrieval still misses the best chunk because the query is too short, too vague, or not aligned with the section vocabulary in the service-page corpus

Example:

- user query: `What is the service plan?`
- resolved scope: `mRNA-LNP Gene Delivery`
- desired retrieval target: `service_plan`, `plan_summary`, `service_phase`, or `timeline_overview`

Today the system can often resolve the scope correctly, but retrieval may still rank generic sections such as `service_overview` or `faq` above the intended plan chunk.

## Goals

- improve retrieval quality for short multi-turn follow-up questions
- preserve the current route and scope resolution behavior
- keep retrieval enhancement deterministic by default
- add optional LLM-based contextualization only for cases that need it
- make rewritten and expanded retrieval queries observable in logs and tests

## Non-Goals

- replacing the existing routing pipeline
- moving scope resolution into the retriever
- rewriting every query with an LLM
- broad semantic paraphrasing with no guardrails
- changing the service-page authoring standard in this phase

## Current State

Relevant modules:

- [context_scope.py](/Users/promab/anaconda_projects/email_agent/src/conversation/context_scope.py)
- [route_preconditions.py](/Users/promab/anaconda_projects/email_agent/src/decision/route_preconditions.py)
- [selector.py](/Users/promab/anaconda_projects/email_agent/src/agents/selector.py)
- [rag_tools.py](/Users/promab/anaconda_projects/email_agent/src/tools/rag_tools.py)
- [service.py](/Users/promab/anaconda_projects/email_agent/src/rag/service.py)
- [retriever.py](/Users/promab/anaconda_projects/email_agent/src/rag/retriever.py)

Current behavior:

- `resolve_effective_scope(...)` determines whether the current turn is scoped to a `service`, `product`, or `scientific_target`
- route preconditions use that result to decide whether clarification is needed
- commercial tool selection can choose `technical_rag` when active service scope is valid
- `retrieve_chunks(...)` builds query variants from the raw query plus active names and entity lists
- reranking uses `BAAI/bge-reranker-base`

Current gap:

- scope resolution may succeed, but retrieval still does not always retrieve the best section for broad follow-ups such as `What is your service plan?`

## Design Summary

The enhancement is a hybrid approach:

1. use existing scope resolution as the source of truth
2. deterministically rewrite short follow-up queries into standalone retrieval queries
3. optionally add intent-specific keyword expansion
4. optionally run a small LLM contextualizer only for hard follow-up cases
5. preserve the original query and perform multi-query retrieval

This keeps the system production-friendly:

- cheap path first
- LLM only when needed
- easy to debug
- easy to test

## Parser-First Retrieval Tiers

The retrieval stack should not treat parser output and raw query text as equally strong signals.

Instead, retrieval should follow a strict three-tier policy:

### Tier 1: Structured Exact Scope

Use this tier when the parser or registry has already produced a high-confidence structured object:

- `catalog_numbers`
- uniquely resolvable `product_names`
- uniquely resolvable `targets`
- uniquely resolvable `service_names`

Expected behavior:

- seed exact identifiers as early as possible
- prefer exact lookup over alias lookup
- do not let raw query terms compete with the structured scope

Example:

- user query: `Tell me about NPM1`
- parser output: `product_names = ["Mouse Monoclonal antibody to Nucleophosmin"]`
- registry output: unique catalog resolution to `20001`
- retrieval behavior: exact lookup for `20001`

### Tier 2: Structured but Non-Unique Scope

Use this tier when the parser has produced a meaningful object, but the object is not unique.

Examples:

- `product_names = ["MSH2"]`
- `product_names = ["TP53"]`

Expected behavior:

- use alias lookup and direct alias lookup
- preserve ambiguity
- prefer clarification over fuzzy expansion when multiple grounded candidates exist

This tier should not fall back to broad raw-query fuzzy retrieval just because multiple matches were found.

### Tier 3: Raw-Query Recovery

Use this tier only when parser output does not provide a stable product or service scope.

Examples:

- `Do you have something for nucleophosmin?`
- `I need an antibody against p53`

Expected behavior:

- allow raw query terms to drive fuzzy retrieval
- use retrieval heuristics to recover likely candidates
- apply ambiguity handling after retrieval if multiple plausible products remain

This tier exists to recover from parser misses, not to compete with high-confidence parser hits.

## Retrieval Signal Priority

The governing rule is:

> Use parsed entities first; use raw query only as recovery, never as a competing primary signal.

This means:

- if Tier 1 applies, raw query terms should not inject additional alias tokens
- if Tier 2 applies, raw query terms should not bypass ambiguity handling
- only Tier 3 may use raw query as the dominant retrieval basis

## Object Type Is Not Retrieval Modality

The system must not equate:

- `product` -> structured lookup only
- `service` -> RAG only

That shortcut is too strong for production behavior.

In practice, structured and unstructured sources are complementary.

### Structured Product Data Is Good For

- catalog number
- canonical title
- price
- lead time
- species reactivity
- applications
- basic metadata

### Unstructured Product Retrieval Is Good For

- datasheet text
- brochure text
- protocol guidance
- validation narrative
- technical caveats
- FAQ-style usage detail

### Design Rule

Treat these as two separate decisions:

1. determine the object type
   - `product`
   - `service`
   - `scientific_target`

2. determine the retrieval modality
   - structured lookup
   - unstructured retrieval
   - hybrid retrieval

This means a turn may be:

- product + structured only
- product + unstructured only
- product + hybrid
- service + RAG
- service + hybrid

### Example

Query:

- `What applications is this antibody validated for?`

Possible retrieval plan:

- structured product lookup for:
  - product identity
  - known application/species metadata
- unstructured retrieval for:
  - validation language
  - protocol or datasheet detail

### Architectural Principle

Use:

- **object-first**

to determine what the user is talking about

and then use:

- **modality-second**

to determine where the answer should come from.

Do not skip RAG just because the resolved object is a product.

## One Product, Many Documents

The system should distinguish between:

1. one alias mapping to many products
2. one product mapping to many supporting documents or chunks

These are not the same problem.

### Case A: One Alias -> Many Products

Example:

- `MSH2`

If the lookup returns multiple distinct `catalog_no` values, the system is facing product ambiguity.

Expected behavior:

- do not guess
- ask the user to choose one product
- keep the clarification flow explicit

### Case B: One Product -> Many Documents

Example:

- one `catalog_no`
- multiple matched documents such as:
  - protocol variants
  - datasheets
  - brochures
  - validation notes

This is not ambiguity.

This is a retrieval aggregation problem.

Expected behavior:

- group matches by `catalog_no`
- if the top matched records all belong to the same `catalog_no`, treat them as one object with multiple evidence sources
- aggregate those sources before final response generation

### Recommended Aggregation Flow

Step 1:

- group `matches` by `catalog_no`

Step 2:

- if the highest-confidence group has a single dominant `catalog_no`, keep the product locked

Step 3:

- collect all matched document snippets for that product

Step 4:

- pass the grouped evidence into response generation as a structured bundle

Suggested shape:

```python
{
    "catalog_no": "P06329",
    "product_name": "Rabbit Polyclonal antibody to MSH2",
    "documents": [...],
    "protocols": [...],
    "datasheets": [...],
    "content_snippets": [...],
}
```

### Response Strategy

Do not send raw independent matches directly to the user when they all refer to the same product.

Instead:

- summarize them as one product-level answer
- merge complementary details
- let the LLM or renderer produce a cross-document summary when needed

### When To Use Cross-Document Summarization

This is most useful when the user asks for:

- protocol guidance
- validation detail
- technical usage detail
- broader "more information" about the same product

It is less necessary for:

- price
- lead time
- simple product identity
- pure catalog metadata

### Design Rule

If multiple top matches share the same `catalog_no`, prefer:

- aggregation

over:

- clarification

If multiple top matches point to different `catalog_no` values, prefer:

- clarification

over:

- aggregation

## Proposed Retrieval Layer

Introduce a retrieval-prep layer before technical retrieval execution.

Suggested entrypoint:

- `build_retrieval_queries(agent_input) -> RetrievalQueryPlan`

Suggested location:

- [service.py](/Users/promab/anaconda_projects/email_agent/src/rag/service.py)
- or [rag_tools.py](/Users/promab/anaconda_projects/email_agent/src/tools/rag_tools.py)

The preferred choice is `src/rag/service.py` because it keeps retrieval-specific logic inside the RAG boundary and avoids spreading query-prep behavior across tool adapters.

## RetrievalQueryPlan

Suggested shape:

```python
{
    "primary_query": str,
    "expanded_queries": list[str],
    "rewritten_query": str,
    "rewrite_reason": str,
    "intent_bucket": str,
    "used_llm_contextualizer": bool,
}
```

Rules:

- `primary_query` is always the original user retrieval query
- `rewritten_query` is empty when no rewrite is applied
- `expanded_queries` are additional variants for recall, not replacements
- `rewrite_reason` is for debugging and tests
- `intent_bucket` is a small controlled label such as `service_plan` or `workflow`

## Non-Linear Token Weighting For Fuzzy Retrieval

This applies to fuzzy retrieval only and should be treated as a Tier 3 optimization.

It should not override:

- Tier 1 exact lookup
- Tier 2 alias clarification

### Problem

A linear token bonus such as:

```python
score += len(matched_tokens) * k
```

over-values common catalog vocabulary.

That causes broad product words such as:

- `antibody`
- `kit`
- `protocol`

to contribute too much relative to high-information biological terms such as:

- `p53`
- `MSH2`
- `NPM1`
- `nucleophosmin`

This can pollute ranking when many irrelevant products share generic words.

### Design Goal

Move from:

- token-count scoring

to:

- token-importance scoring

The system should reward:

- rare, high-information tokens

and down-weight:

- frequent, generic catalog terms

### Recommended First-Version Formula

Do not introduce full BM25 immediately.

Instead, use a lightweight IDF-style token-weight table:

```python
score += sum(token_weight[token] for token in matched_tokens)
```

where:

- `token_weight[token]` is higher for rare tokens
- `token_weight[token]` is lower for generic tokens

Recommended intuition:

- `NPM1` > `nucleophosmin` > `rabbit` > `antibody`

### Token Classes

The weighting model should distinguish at least these buckets:

1. High-information biological terms
- targets
- genes
- epitope names
- construct-specific identifiers

2. Medium-information commercial descriptors
- host species
- clonality
- format-related terms

3. Low-information generic catalog vocabulary
- `antibody`
- `kit`
- `protein`
- `protocol`
- `mouse`
- `rabbit`

### Scope Boundary

This scoring policy should only influence:

- Tier 3 fuzzy retrieval ranking

It should not be used to reinterpret:

- exact catalog matches
- unique alias resolutions
- ambiguous alias clarification flows

### Expected Benefit

This reduces cases where:

- many irrelevant products rise because they share common vocabulary

and improves cases where:

- a small number of biologically precise terms should dominate ranking

Example:

- query: `p53 antibody`

Desired behavior:

- `p53` should dominate scoring
- `antibody` should contribute very little

### Rollout Recommendation

Implement this after the parser-first retrieval tiers are stable.

Suggested rollout:

1. introduce token frequency statistics from the product catalog
2. compute a lightweight `token_weight` map
3. apply weighted token scoring in Tier 3 only
4. compare rank shifts on a golden retrieval set before wider rollout

## Step 1: Scope-Gated Deterministic Rewrite

This is the default path.

### Trigger Conditions

Apply deterministic rewrite only when all are true:

- `resolve_effective_scope(...)` returns a non-empty scope
- current query is short or context-dependent
- current query does not already contain the resolved entity name
- current query is in a technical or technical-adjacent path

Context-dependent signals:

- pronouns such as `it`, `its`, `this`, `that`, `the service`, `the platform`
- short broad follow-ups such as:
  - `What is the service plan?`
  - `What models do you support?`
  - `How does it work?`
  - `What happens next?`

### Rewrite Behavior

Inject the resolved subject into the query without changing user intent.

Examples:

- `What is the service plan?`
  -> `What is the service plan for mRNA-LNP Gene Delivery?`
- `What models do you support?`
  -> `What models does mRNA-LNP Gene Delivery support?`
- `How does it work?`
  -> `How does mRNA-LNP Gene Delivery work?`

Rules:

- only inject the resolved scope name
- do not invent new details
- do not convert service questions into product questions
- keep the rewrite to a single standalone sentence

## Step 2: Intent Bucket Detection

After scope resolution, classify the retrieval query into a small controlled intent bucket.

Initial buckets:

- `service_plan`
- `model_support`
- `workflow`
- `validation`
- `pricing_detail`
- `general_technical`

This is not the same as parser intent. It is a retrieval-oriented label used only for query expansion and section boosting.

Example mappings:

- `service plan`, `phases`, `timeline`, `stages`
  -> `service_plan`
- `models`, `cell types`, `support`
  -> `model_support`
- `workflow`, `next step`, `after`
  -> `workflow`
- `validate`, `validation`, `assay`, `quality evidence`
  -> `validation`

## Step 3: Controlled Keyword Expansion

When the scope is known and an intent bucket is detected, generate a small set of expansion queries.

### `service_plan`

Recommended expansion terms:

- `service plan`
- `discovery services plan`
- `phases`
- `project timeline`
- `timeline overview`
- `workflow summary`
- `deliverables`

Example generated variants:

- `mRNA-LNP Gene Delivery service plan`
- `mRNA-LNP Gene Delivery discovery services plan`
- `mRNA-LNP Gene Delivery phases`
- `mRNA-LNP Gene Delivery project timeline`

### `model_support`

Recommended expansion terms:

- `supported models`
- `model support`
- `cell types`
- `application models`
- `validation models`

### `workflow`

Recommended expansion terms:

- `workflow`
- `workflow overview`
- `workflow step`
- `next step`
- `process`

### `validation`

Recommended expansion terms:

- `validation`
- `validation models`
- `quality evidence`
- `assay`
- `benchmark`

Rules:

- keep expansion lists small
- expand only when scope is already resolved
- preserve the original query
- do not expand operational or support-routing questions such as `contact support`

## Phase 2 Design: Intent Keyword Expansion

Phase 2 turns the existing retrieval rewrite layer into a small, controlled query-expansion system.

The goal is not to paraphrase broadly. The goal is to increase the odds that retrieval hits the exact section vocabulary used in the service-page corpus.

Example:

- user query: `What is your service plan?`
- resolved scope: `mRNA-LNP Gene Delivery`
- rewritten query from Phase 1: `What is the service plan for mRNA-LNP Gene Delivery?`
- desired Phase 2 variants:
  - `mRNA-LNP Gene Delivery discovery services plan`
  - `mRNA-LNP Gene Delivery phases`
  - `mRNA-LNP Gene Delivery project timeline`

This is especially useful when user wording is natural but the indexed documents use denser technical or structural labels.

### Problem Statement

The current retriever performs better once scope is resolved, but it can still miss the most relevant chunk when:

- the user uses broad language such as `plan`, `models`, or `what happens next`
- the corpus uses richer labels such as `Discovery Services Plan`, `workflow overview`, or `model support`
- the desired chunk is structurally specific while the raw query remains semantically broad

Phase 2 addresses this by generating a few high-signal retrieval variants derived from:

- resolved scope
- retrieval intent bucket
- small curated keyword packs

### Principles

- preserve the original query
- keep all expansion deterministic
- expand only after effective scope is resolved
- keep the number of variants intentionally small
- prefer section vocabulary already present in the corpus
- never use expansion to override routing or clarification logic

### Scope Guardrails

Keyword expansion should run only when all of the following are true:

- `resolve_effective_scope(...)` returns a non-empty scope
- the retrieval path is technical or technical-adjacent
- the query is not clearly operational, sales-contact, or support-routing language
- the expansion bucket is one of the explicitly supported buckets

Keyword expansion should not run when the query contains obvious non-technical routing intent, including:

- `contact`
- `representative`
- `sales rep`
- `support team`
- `customer support`
- `technical support`
- `connect me`
- `put me in touch`

### Supported Buckets For Phase 2

The first implementation should support only a narrow set:

- `service_plan`
- `workflow`
- `model_support`

Other buckets such as `validation` can remain defined in the design but should be deferred until after the first eval pass.

### Expansion Packs

The expansion packs should live in code as a small constant map, ideally in [service.py](/Users/promab/anaconda_projects/email_agent/src/rag/service.py) near `build_retrieval_queries(...)`.

Suggested shape:

```python
INTENT_EXPANSION_PACKS = {
    "service_plan": [
        "service plan",
        "discovery services plan",
        "phases",
        "project timeline",
        "timeline overview",
        "workflow summary",
        "deliverables",
    ],
    "workflow": [
        "workflow",
        "workflow overview",
        "workflow step",
        "next step",
        "process",
    ],
    "model_support": [
        "supported models",
        "model support",
        "cell types",
        "application models",
        "validation models",
    ],
}
```

The words should be taken from existing indexed section labels and chunk tags wherever possible.

### Query Construction Strategy

For each supported bucket, expansion queries should be generated from the resolved scope name plus each term in the pack.

Example for `service_plan`:

- original query:
  - `What is your service plan?`
- rewritten query:
  - `What is the service plan for mRNA-LNP Gene Delivery?`
- expanded queries:
  - `mRNA-LNP Gene Delivery service plan`
  - `mRNA-LNP Gene Delivery discovery services plan`
  - `mRNA-LNP Gene Delivery phases`
  - `mRNA-LNP Gene Delivery project timeline`

The construction rule should be simple:

- use `"{scope_name} {expansion_term}"` for most variants
- dedupe against the original query and rewritten query
- cap the total number of expansion variants per request

### Recommended Limits

To keep retrieval stable and cheap:

- maximum supported expansion queries per request: `4`
- maximum total query variants entering vector retrieval:
  - original query
  - rewritten query when present
  - up to `4` expanded queries

This keeps the candidate-recall space broad enough to help, but not so broad that recall becomes noisy.

### Data Contract Changes

`RetrievalQueryPlan` should continue to expose:

```python
{
    "primary_query": str,
    "rewritten_query": str,
    "expanded_queries": list[str],
    "rewrite_reason": str,
    "intent_bucket": str,
    "used_llm_contextualizer": bool,
}
```

For Phase 2, the meaning becomes:

- `rewritten_query`: deterministic standalone query from Phase 1
- `intent_bucket`: retrieval-specific bucket used to choose an expansion pack
- `expanded_queries`: the final capped keyword-expansion variants

No schema expansion is required for the first implementation.

### Implementation Plan

#### 1. Add a Controlled Expansion Map

In [service.py](/Users/promab/anaconda_projects/email_agent/src/rag/service.py):

- add a constant such as `INTENT_EXPANSION_PACKS`
- include only `service_plan`, `workflow`, and `model_support`

#### 2. Add an Expansion Builder

Add a helper such as:

```python
def _build_expanded_queries(scope: Mapping[str, str], intent_bucket: str) -> list[str]:
    ...
```

Responsibilities:

- return an empty list when no scope is available
- return an empty list when the bucket is unsupported
- combine scope name with expansion terms
- dedupe and cap the final result

#### 3. Integrate It Into `build_retrieval_queries(...)`

Flow:

1. resolve effective scope
2. detect intent bucket
3. perform deterministic rewrite
4. build expanded queries from scope + bucket
5. return the plan

This keeps all retrieval-prep logic in one place.

#### 4. Pass Expanded Queries Through The Existing Retriever

No new retriever interface is needed because [retriever.py](/Users/promab/anaconda_projects/email_agent/src/rag/retriever.py) already accepts `expanded_queries`.

The only behavioral change should be that the expanded variants are now more structured and bucket-driven.

### Debugging And Observability

`retrieval_debug` should continue to include:

- `rewritten_query`
- `rewrite_reason`
- `intent_bucket`
- `expanded_queries`

This makes Phase 2 easy to inspect in tests and logs.

Recommended additional debug convention:

- if no keyword expansion ran, leave `expanded_queries=[]`
- keep `intent_bucket` populated even when no expansion pack is applied

That makes it easier to tell the difference between:

- bucket detected, but expansion intentionally skipped
- no bucket detected at all

### Test Plan

The first Phase 2 test set should cover:

#### Unit tests

In a dedicated test file or in [test_rag_retrieval_enhancement.py](/Users/promab/anaconda_projects/email_agent/tests/test_rag_retrieval_enhancement.py):

- `service_plan` builds expected expansion queries
- `workflow` builds expected expansion queries
- `model_support` builds expected expansion queries
- unsupported buckets return no expansion queries
- no scope returns no expansion queries
- contact/support queries do not receive keyword expansion

#### Retrieval regression tests

Add targeted regression checks for:

- `What is your service plan?`
  - expected expanded query includes `discovery services plan`
  - top retrieval should prefer plan-related chunks
- `What models do you support?`
  - expected expanded query includes `supported models`
  - top retrieval should prefer model-support chunks
- `What happens next?`
  - expected expanded query includes `workflow` or `next step`
  - top retrieval should prefer workflow-related chunks

### Rollout Strategy

Phase 2 should be rolled out in this order:

1. implement expansion packs for `service_plan`
2. verify the `service plan` eval case improves
3. add `workflow`
4. add `model_support`
5. compare retrieval quality before enabling any further buckets

This avoids adding too many retrieval heuristics at once.

### Risks

- too many expansion terms can broaden recall and hurt reranking
- expansion terms that do not reflect real corpus vocabulary can add noise
- unsupported non-technical intents may accidentally receive technical expansions if guards are too loose

Mitigations:

- small fixed packs
- hard cap on variant count
- scope gating
- explicit support-intent denylist
- regression tests built around expected section families

### Success Criteria

Phase 2 should be considered successful when:

- `service_plan` follow-up queries retrieve plan-related chunks more consistently
- `workflow` follow-up queries retrieve workflow-related chunks more consistently
- `model_support` follow-up queries retrieve model-support chunks more consistently
- no increase is observed in false positive technical retrieval for support/contact style questions

## Step 4: Optional LLM Contextualizer

This is the fallback path, not the default.

### When To Use

Use the LLM contextualizer only when deterministic rewrite is insufficient.

Suggested triggers:

- query contains pronouns or nominal references
- query is short and ambiguous
- scope is known but deterministic rewrite would still be awkward
- no explicit entity appears in the current turn

### Prompt Contract

The LLM should:

- rewrite only when needed
- preserve original intent
- inject only resolved context already known to the system
- return one standalone retrieval query
- never answer the question

Example prompt shape:

```text
You are rewriting a follow-up user question into a standalone retrieval query.

Rules:
- Preserve the user's original intent.
- Inject the resolved subject only when needed.
- Do not add facts not present in the current turn or resolved context.
- Return one standalone search query only.

Resolved scope:
- scope_type: service
- name: mRNA-LNP Gene Delivery

Current user query:
What is the service plan?
```

Expected output:

- `What is the service plan for mRNA-LNP Gene Delivery?`

### Model Recommendation

Use a smaller LLM first for cost and latency control.

The contextualizer should be treated as a retrieval helper, not as a knowledge source.

## Step 5: Multi-Query Retrieval

The retriever should search with multiple variants, not a single rewritten query.

Recommended order:

1. original query
2. deterministic rewritten query
3. optional LLM rewritten query
4. intent expansion variants

This preserves recall and reduces the risk of overfitting to one rewrite.

`retrieve_chunks(...)` already supports multiple query variants through:

- [retriever.py](/Users/promab/anaconda_projects/email_agent/src/rag/retriever.py)

The enhancement should feed cleaner and more informative variants into that existing mechanism rather than replacing it.

## Section-Type Boosting

Query rewriting improves recall. It does not fully solve ranking.

Add lightweight metadata-aware boosting after initial candidate retrieval.

Recommended initial mapping:

- `service_plan`
  - boost `service_plan`
  - boost `plan_summary`
  - boost `service_phase`
  - boost `timeline_overview`
- `model_support`
  - boost `model_support`
  - boost `development_capabilities`
- `workflow`
  - boost `workflow_overview`
  - boost `workflow_step`
- `validation`
  - boost `validation_models`
  - boost `quality_benchmarks`
  - boost `benchmark`

This should remain a small deterministic boost, not a full second ranking system.

## Debug and Observability

Every retrieval run should expose enough metadata to explain what happened.

Recommended debug fields:

- `effective_scope_type`
- `effective_scope_name`
- `effective_scope_source`
- `rewrite_reason`
- `intent_bucket`
- `rewritten_query`
- `expanded_queries`
- `used_llm_contextualizer`

These fields should be easy to surface in:

- action output from [rag_tools.py](/Users/promab/anaconda_projects/email_agent/src/tools/rag_tools.py)
- test snapshots
- future routing or retrieval debug traces

## Response-Level Scope Acknowledgement

The retrieval layer should remain structured and machine-oriented, but the final user-facing response may lightly acknowledge the resolved object type when doing so improves clarity.

This is especially useful when:

- the current turn is a short follow-up
- the system resolved the object from active context
- the conversation switched from one object type to another
- the user would benefit from seeing that the system recognized the intended scope correctly

### Design Principle

Do not put user-facing phrasing into `RetrievalQueryPlan`.

`RetrievalQueryPlan` should only carry structured fields such as:

- `effective_scope`
- `rewritten_query`
- `rewrite_reason`
- `intent_bucket`

The final response layer may consume those fields and decide whether to briefly acknowledge the resolved scope.

### Example Phrasing

For product scope:

- `Regarding the product you mentioned, Mouse Monoclonal antibody to Nucleophosmin (Catalog #20001), here is the relevant information.`

For service scope:

- `Regarding the service you mentioned, mRNA-LNP Gene Delivery, here is the relevant information.`

For active-context fallback when the current turn is still somewhat implicit:

- `Assuming you mean the previously discussed service, mRNA-LNP Gene Delivery, here is the relevant information.`

### Guardrails

- keep the acknowledgement to one short clause
- do not repeat the object name in every reply
- do not sound overly certain when the scope came from fallback rather than an explicit current-turn mention
- do not expose internal labels such as `effective_scope` or `intent_bucket`
- prefer this acknowledgement when the system resolved a non-obvious type switch such as `service -> product` or `product -> service`

### Recommended Data Contract

The response layer should have access to:

- `effective_scope_type`
- `effective_scope_name`
- `effective_scope_source`
- optional product identifier details when available, such as catalog number

This allows the renderer to express the resolved scope naturally without coupling response wording to retrieval internals.

## MVP Stability Notes

The first production-safe version should optimize for correctness and traceability before it optimizes for breadth.

The following risks and mitigations should be treated as part of the design.

### 1. Silent Type Switches

Risk:

- the system may correctly switch from `service` to `product` or from `product` to `service`
- retrieval quality may improve
- but the user may perceive the response as a topic jump if the type switch is not surfaced at all

Mitigation:

- keep the internal type switch deterministic and structured
- optionally add one short user-facing acknowledgement in the response layer
- prefer this acknowledgement when the resolved scope came from active context or when the type changed relative to the prior turn

This is why response-level scope acknowledgement is included in this design.

### 2. Multi-Entity Turns

Risk:

- one user turn may mention more than one object, such as a service plus a related product or document
- the current architecture uses a single `active_entity` as the main remembered object
- forcing `active_entity` to become a list in the first implementation would ripple through routing, query resolution, payload persistence, and retrieval

MVP decision:

- keep `active_entity` as a single main object in phase 1
- preserve additional objects in `recent_entities`
- handle mixed-intent or dual-entity turns later through routing or execution-level expansion, not by changing the core `active_entity` schema immediately

Future extension options:

- support parallel retrieval for primary and secondary entities
- explicitly model primary vs secondary active objects
- route mixed turns into one primary route plus supplemental secondary actions

### 3. Identifier Robustness

Risk:

- product identifiers in biotech workflows may contain case differences, spaces, and separators
- lightly malformed identifiers can degrade lookup quality and cause false misses

Mitigation:

- normalize identifiers before storing or comparing them in active payload construction
- keep display-oriented values separate from normalized matching values when possible

Recommended minimum normalization:

- `strip()`
- collapse repeated whitespace
- normalize case for matching

Guardrail:

- avoid aggressive normalization that could destroy meaningful catalog formatting
- prefer conservative normalization first, then expand only if real catalog data requires it

### 4. Reference Resolution Failure Protection

Risk:

- the user may ask a referential follow-up such as `that one`, `what about this`, or `那这个呢`
- the prior active entity may already be gone, expired, or no longer valid
- naive retrieval enhancement may inject an unrelated old entity or force a misleading rewrite

Mitigation:

- if there is no valid effective scope, do not inject any entity into the retrieval query
- if the active context is unavailable or unusable, do not generate contextual rewrites
- fall back to the original query only
- allow route-level clarification to ask the user which product or service they mean

Required behavior:

- no valid active scope
  - `rewritten_query = ""`
  - no scope-based expansion
  - `rewrite_reason` should explain that no valid scope was available
- referential query with no usable scope
  - do not guess
  - do not revive stale entities
  - prefer clarification over speculative retrieval

This is a deliberate safe-failure policy:

- wrong entity injection is worse than no entity injection
- clarification is preferred over silent semantic drift

### MVP Implementation Priority

Recommended order:

1. stop service/product type pollution in active context
2. add response-level scope acknowledgement for non-obvious type continuity or type switches
3. add conservative identifier normalization
4. add safe failure behavior when referential queries have no valid active scope
5. defer multi-entity active-state redesign until after the first production evaluation

This keeps the first implementation small, testable, and easy to reason about.

## Guardrails

### Avoid Over-Rewrite

Skip rewrite when:

- query already includes a specific service or product name
- query is already long and self-contained
- current turn contains a new explicit entity that overrides active context

### Avoid Context Leakage

Do not inject old entities when:

- current turn has a new scope
- continuity gates fail
- active entity type conflicts with the current turn
- no valid active scope is available for a referential follow-up
- active context appears stale, expired, or otherwise unusable

### Avoid Hallucinated Context

The rewrite layer may only use:

- original retrieval query
- resolved effective scope
- bounded retrieval intent heuristics

It may not invent:

- durations
- prices
- phase counts
- model names
- fallback entities when no valid scope exists

## Evaluation Plan

Before rollout, define a compact eval set with:

- original query
- active scope
- expected scope type
- expected top service
- expected top section types

Minimum target set:

- `What is the service plan?`
  - active service: `mRNA-LNP Gene Delivery`
  - expected section types: `service_plan`, `plan_summary`, `service_phase`, `timeline_overview`
- `What models do you support?`
  - active service: `mRNA-LNP Gene Delivery`
  - expected section types: `model_support`, `development_capabilities`
- `What happens after Hybridoma Sequencing in the CAR-T workflow?`
  - expected section types: `workflow_step`
- `How do you validate the platform?`
  - active service: `mRNA-LNP Gene Delivery`
  - expected section types: `validation_models`, `quality_benchmarks`

Metrics:

- top-1 section type hit
- top-3 section type hit
- top-1 service match
- latency before and after enhancement

## Rollout Plan

### Phase 1

- add `RetrievalQueryPlan`
- deterministic scope-based rewrite only
- preserve original query
- add debug fields
- add eval cases

### Phase 2

- add intent bucket detection
- add controlled keyword expansion
- add section-type boosting

### Phase 3

- add optional LLM contextualizer
- gate it behind narrow conditions
- compare latency and retrieval quality

### Phase 4

- expand the eval set
- tune thresholds and bucket mappings
- document stable authoring/retrieval conventions

## Suggested Implementation Order

1. add retrieval query planning in [service.py](/Users/promab/anaconda_projects/email_agent/src/rag/service.py)
2. plumb `expanded_queries` and debug metadata into [rag_tools.py](/Users/promab/anaconda_projects/email_agent/src/tools/rag_tools.py)
3. extend [retriever.py](/Users/promab/anaconda_projects/email_agent/src/rag/retriever.py) to consume stronger variants and optional section boosting
4. add targeted tests for `service_plan` and other broad scoped follow-ups
5. add optional LLM contextualization only after deterministic retrieval quality has been measured

## Open Questions

- should `scientific_target` generate its own retrieval rewrite strategy, or only block service clarification?
- should keyword expansion live in `src/rag/` or in `src/conversation/` as a retrieval-focused helper?
- should the LLM contextualizer output only one rewrite, or a primary rewrite plus alternates?
- should reranker input include the rewritten query, the original query, or both?

## Recommendation

Start with the smallest production-safe change:

- deterministic scope-based rewrite
- `service_plan` intent expansion
- debug trace output
- eval set for top section-type hit rate

This will improve the known failure mode without making the retrieval stack opaque or expensive.
