# Service-Page RAG Standard

This document defines the current gold standard for ProMab service-page RAG files.

It is the source-of-truth for:
- service-page `rag_ready` authoring
- explicit section and subchunk design
- optional phase vs optional branch semantics
- workflow-step ordering fields
- service-page ingestion expectations
- current retrieval assumptions

## Scope

This standard is for service pages such as:
- CAR-T
- CAR-NK
- CAR-Macrophage
- Gamma Delta T
- Lentivirus Production
- Licensing CAR Technology

It is not the standard for:
- structured product catalog rows
- operational QuickBooks data
- generic company pages

## Design Goals

The service-page RAG layer should:
- preserve real service knowledge, not site chrome
- expose plan, phase, and workflow structure explicitly
- support both broad overview questions and narrow phase-level questions
- make deterministic metadata available for retrieval
- keep source files readable enough to maintain by hand

## File Location

Current service-page sources live under:

- [/Users/promab/anaconda_projects/email_agent/data/processed/rag_ready_files/car-t:car-nk](/Users/promab/anaconda_projects/email_agent/data/processed/rag_ready_files/car-t:car-nk)

The current ingestion entrypoint is:

- [/Users/promab/anaconda_projects/email_agent/src/rag/service_page_ingestion.py](/Users/promab/anaconda_projects/email_agent/src/rag/service_page_ingestion.py)

## Required File Shape

Each file should use:
- one `[DOCUMENT] ... [END_DOCUMENT]` block
- multiple `[SECTION] ... [END_SECTION]` blocks

Every section is ingestion-ready. We do not rely on HTML parsing at retrieval time.

## Document-Level Metadata

Each `[DOCUMENT]` block should include at least:

- `company`
- `entity_type: service`
- `business_line`
- `subcategory`
- `service_name`
- `document_type: service_page`
- `page_title`
- `source_url`
- `document_summary`

Recommended fields:
- `service_line`
- `notes_for_rag`
- `version`

## Section Authoring Principles

Each section should:
- answer one coherent question
- remain understandable when retrieved alone
- repeat the most important service metadata
- avoid mixing overview, pricing, workflow, and branch logic in one chunk

We prefer explicit source authoring over parser-side guessing.

## Core Section Types

Common top-level section types:
- `service_overview`
- `scientific_rationale`
- `why_us`
- `development_capabilities`
- `timeline_overview`
- `model_support`
- `validation_models`
- `licensing_scope`
- `platform_advantage_overview`
- `technical_advantage`
- `workflow_overview`
- `workflow_highlights`
- `pricing_overview`
- `related_reference`
- `faq`
- `related_services`

Common explicit subchunk section types:
- `plan_comparison`
- `plan_summary`
- `service_plan`
- `service_phase`
- `workflow_step`

Optional additional subchunk types when justified:
- `workflow_overview`
- `timeline_group`
- `service_component`
- `benchmark`

## What To Exclude

The following site-wide blocks should not be kept unless they are truly page-specific:

- `contact`
- `call_to_action`
- `featured_publications`
- `company_metrics_on_page`

These create retrieval noise because they repeat across pages.

## Plan and Phase Structure

### Plan Layer

Use:
- `pricing_overview`
- `plan_comparison`
- `plan_summary`
- `service_plan`

`pricing_overview` should explain:
- whether the service has one or more plans
- the high-level entry point for each plan
- timeline interpretation
- total duration or pricing summary when present

For dual-plan pages, add:
- `plan_comparison`

`plan_comparison` should directly answer:
- how Plan A and Plan B differ
- where each plan starts
- which path is longer or shorter
- which phases or optional stages differ
- when each plan is the better fit

`plan_summary` should be a short per-plan chunk, not the primary comparison chunk.

`service_plan` should hold the full structured plan:
- `plan_entry_point`
- `timeline_summary`
- `timeline_note` if needed
- `total_duration_weeks`
- `total_price_usd` when present
- `timeline_groups`
- `stages`

When users often ask broad duration questions such as `What is the project timeline?`, add:
- `timeline_overview`

`timeline_overview` should summarize:
- how many plans exist
- which route is longer or shorter
- the major phase groups
- which phases are optional main phases or optional branches

### Phase Layer

Each phase that may need to be answered independently should also exist as its own `[SECTION]` with:
- `section_type: service_phase`
- `parent_section`
- `parent_section_type: service_plan`
- `plan_name`
- `phase_name`
- `stage_type`
- `optional`
- `duration_weeks` when known
- `price_usd` or related price fields when known
- `summary`
- `description`

## Optional Semantics

There are two different kinds of `optional` and they must not be conflated.

### 1. Optional Main Phase

This is a linear stage in the main plan that may or may not be included.

Examples:
- `Plan A - Optional Phase I`
- `Plan A - Optional Phase II`
- `Plan B - Optional Phase VI`

Required metadata:
- `optional: yes`
- `phase_role: optional_main_phase`

Recommended wording:
- `This is an optional phase in Plan A.`
- `This is an optional phase in Plan B.`

### 2. Optional Branch

This is not a normal mainline phase. It is a branch under a parent phase.

Examples:
- `Plan A - Phase IV Optional Assay Branch A`
- `Plan A - Phase IV Optional Assay Branch B`
- `Plan B - Phase IV Optional Assay Branch A`
- `Plan B - Phase IV Optional Assay Branch B`

Required metadata:
- `optional: yes`
- `phase_role: optional_branch`
- `parent_phase: Phase IV`

Recommended wording:
- `This is an optional branch derived from the main Phase IV stage.`

### 3. Main Phase

Normal backbone stages should use:
- `phase_role: main_phase`

This matters especially when:
- `Phase IV`
- `Phase IV-A`
- `Phase IV-B`

coexist in the same file.

## Workflow Structure

For workflow-heavy pages, use two layers:

### Workflow Overview

Use:
- `workflow_overview`
- or `workflow_highlights`

This should summarize the full flow in one chunk.

### Workflow Steps

Any workflow that users may ask about step-by-step should have explicit `workflow_step` sections.

Each `workflow_step` should include:
- `step_name`
- `step`
- `previous_step`
- `next_step`
- `stage_type` when useful
- `summary`

This supports queries such as:
- `What happens after Hybridoma Sequencing?`
- `What comes after Lentivirus Production?`

## Example Section Patterns

### Optional Main Phase

```text
[SECTION]
section_type: service_phase
section_title: Plan A - Optional Phase II
parent_section: Plan A
parent_section_type: service_plan
plan_name: Plan A
phase_name: Phase II
phase_role: optional_main_phase
optional: yes
stage_type: sequence_characterization
summary: This is an optional phase in Plan A for antibody heavy- and light-chain sequencing.
description: This is an optional phase in Plan A. It covers sequencing of the antibody's heavy and light chains.
[END_SECTION]
```

### Optional Branch

```text
[SECTION]
section_type: service_phase
section_title: Plan A - Phase IV Optional Assay Branch A
parent_section: Plan A
parent_section_type: service_plan
plan_name: Plan A
phase_name: Phase IV-A
phase_role: optional_branch
parent_phase: Phase IV
optional: yes
stage_type: functional_assay_flow_cytometry
summary: This is an optional branch derived from the main Phase IV stage, using flow cytometry for phagocytosis analysis.
description: Phase IV optional assay branch A by flow cytometry to determine the percentage of CAR-macrophage cells.
[END_SECTION]
```

### Workflow Step

```text
[SECTION]
section_type: workflow_step
section_title: Lentivirus Production
step_name: Lentivirus Production
step: 4
previous_step: Hybridoma Sequencing
next_step: mRNA Transfection
summary: Produce lentiviral particles for CAR delivery.
[END_SECTION]
```

## Retrieval Expectations

The current retrieval design is:

1. Chroma embedding recall
2. BGE reranker
3. thin deterministic post-processing

Current implementation files:
- [/Users/promab/anaconda_projects/email_agent/src/rag/retriever.py](/Users/promab/anaconda_projects/email_agent/src/rag/retriever.py)
- [/Users/promab/anaconda_projects/email_agent/src/rag/reranker.py](/Users/promab/anaconda_projects/email_agent/src/rag/reranker.py)
- [/Users/promab/anaconda_projects/email_agent/src/rag/vectorstore.py](/Users/promab/anaconda_projects/email_agent/src/rag/vectorstore.py)

The deterministic logic should stay small.

Keep:
- `business_line_hint`
- `after X -> next_step`
- exact `service_phase` fallback for precise phase queries

Avoid re-growing:
- broad section-type weighting
- token-overlap scoring as a main ranking strategy
- large if/else trees for every query shape

## Current Authoring Rules

When creating or editing a new service-page RAG file:

1. Add the document block first.
2. Keep only page-specific service knowledge.
3. Add top-level overview sections.
4. Add explicit `plan_summary`, `service_plan`, and `service_phase` sections when plans exist.
5. Add explicit `workflow_step` sections when step-level workflow exists.
6. Distinguish:
   - `main_phase`
   - `optional_main_phase`
   - `optional_branch`
7. Add `previous_step` and `next_step` for workflow steps.
8. Prefer explicit source metadata over parser inference.

## Current Known Good Patterns

These files currently represent the strongest reference patterns:

- [promab_custom_gamma_delta_t_cell_development_rag_ready_v4.txt](/Users/promab/anaconda_projects/email_agent/data/processed/rag_ready_files/car-t:car-nk/promab_custom_gamma_delta_t_cell_development_rag_ready_v4.txt)
- [promab_custom_car_t_cell_development_rag_ready_v1.txt](/Users/promab/anaconda_projects/email_agent/data/processed/rag_ready_files/car-t:car-nk/promab_custom_car_t_cell_development_rag_ready_v1.txt)
- [promab_custom_car_nk_cell_development_rag_ready_v1.txt](/Users/promab/anaconda_projects/email_agent/data/processed/rag_ready_files/car-t:car-nk/promab_custom_car_nk_cell_development_rag_ready_v1.txt)
- [promab_custom_car_macrophage_cell_development_rag_ready_v2.txt](/Users/promab/anaconda_projects/email_agent/data/processed/rag_ready_files/car-t:car-nk/promab_custom_car_macrophage_cell_development_rag_ready_v2.txt)
- [promab_lentivirus_production_rag_ready_v1.txt](/Users/promab/anaconda_projects/email_agent/data/processed/rag_ready_files/car-t:car-nk/promab_lentivirus_production_rag_ready_v1.txt)
- [promab_licensing_car_technology_rag_ready_v1.txt](/Users/promab/anaconda_projects/email_agent/data/processed/rag_ready_files/car-t:car-nk/promab_licensing_car_technology_rag_ready_v1.txt)

## Validation Checklist

Before ingesting a new file, verify:

- the page-specific knowledge is preserved
- generic site chrome is removed
- every plan has a clear summary
- every answerable phase has its own `service_phase`
- optional main phases use `optional_main_phase`
- optional branches use `optional_branch` plus `parent_phase`
- workflow steps have `step`, `previous_step`, and `next_step`
- terminology is consistent across similar files

## Ingestion and Rebuild

When source files change:

1. rebuild the service-page vector store
2. rerun service-page ingestion tests
3. smoke-test representative queries

Typical checks:

```bash
python - <<'PY'
from src.rag.vectorstore import rebuild_vectorstore
vs = rebuild_vectorstore()
print(vs._collection.count())
PY

pytest -q tests/test_service_page_ingestion.py
```

## Current Open Risk

The biggest retrieval risks are no longer file-shape problems.

They are usually:
- exact phase matching across similarly named phases
- comparison-style plan questions
- making sure broad timeline questions do not crowd out exact phase chunks

This standard is meant to reduce those risks at the source-file level first.
