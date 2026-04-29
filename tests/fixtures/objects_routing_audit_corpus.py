"""Fixture corpus for #11 objects→routing→executor end-to-end plumbing audit.

Purpose
-------
Backlog item #11 (`project_rag_architecture_backlog.md`) calls for an audit
that observes whether the production entry path (`run_email_agent` →
`resolve_objects` → `decide_clarification` → `request_builder`) actually
behaves as designed on queries that *should* trigger object ambiguity,
clarification, or selection follow-up.

The two existing observation harnesses both bypass this slice:

  - `tests/observe_rag_accuracy.py`     skips ingestion AND objects/routing.
  - `tests/observe_rag_confidence_e2e.py` runs ingestion but still calls
    `retrieve_technical_knowledge` directly — no `resolve_objects`, no
    `decide_clarification`, no `request_builder`.

This fixture provides 8 hand-written queries split across 4 buckets so an
audit script can drive the real entry point and dump the four observation
points that #11 specifies:

  (1) `resolved_object_state.ambiguous_sets` — non-empty on real ambiguity?
  (2) `route_decision.action` / `route_decision.clarification.kind` — does
      routing block execution and emit the right clarification kind?
  (3) `resolved_object_state.primary_object` after a selection follow-up —
      does the next turn lock onto the candidate the user picked?
  (4) `scope_context["business_line"]` from `request_builder._build_scope_context`
      — does the executor-built scope match what the bypassing harnesses
      hand-fabricate?

Hypothesis vs. ground truth
---------------------------
Each row records the *expected* behavior under the design described in
`project_rag_gamma_clarification_strategy.md` and `project_rag_active_service_data_flow.md`.
These are predictions, not ground truth. The audit's value is precisely
the diff between hypothesis and observed behavior — disagreements either
falsify the design assumption or surface a silent regression.

In particular: alias-collision-driven ambiguity (the strong-ambig bucket)
depends on what aliases the live `service_registry` / `product_registry`
return, which can drift as registry data evolves. A fixture row that no
longer triggers `ambiguous_sets` is a finding, not a bug in the fixture.

Note on multi-candidate resolution
----------------------------------
`resolve_objects()` picks `primary_object` by candidate score, not by
mention order or first-listed-in-registry. When a query naturally
surfaces several services in the same biz_line (e.g. "compare mouse vs
human monoclonal"), which candidate becomes primary is score-driven and
can flip between runs without indicating a bug. For these rows, use
`expected_primary_object_one_of` (list) instead of
`expected_primary_object` (single value) so the audit records the
chosen candidate without raising a false positive. Reserve the singular
field for cases where exactly one canonical entry is acceptable.

Note on selection follow-up state
---------------------------------
Selection resolution does NOT come from `conversation_history` alone.
`src/objects/extractors/context_extractor.py:64-94` rebuilds the live
`ambiguous_sets` ONLY when
`memory_context.snapshot.clarification_memory` carries a non-empty
`pending_clarification_type` and populated `pending_candidate_options`.
Then in `src/objects/resolution.py:84-95`, `resolve_objects()` applies
the parser's `selection_resolution` to those rebuilt ambiguous sets —
but only if `pending_clarification` is true AND `ambiguous_sets` is
non-empty AND `selection.selection_confidence >= 0.5`.

Consequence: a fixture that only carries prior turns as natural-language
text is under-specified — the production code path needs the structured
pending state too. Each `selection_followup` row therefore carries a
`prior_clarification_state` dict that an audit harness must wrap in a
minimal `MemoryContext` and pass into
`build_ingestion_bundle(..., memory_context=...)`. Without this, a
follow-up may fail to resolve even when the plumbing is correct,
producing a misleading audit signal.

Additional constraint: `_infer_pending_object_type` keys off whether
`pending_clarification_type` contains "service" / "product" / "order"
/ etc. Use a value that contains the right keyword (e.g.
"service_selection") so the rebuilt ambiguous set has the correct
`object_type`.

Note on executor-side fields when route=clarify
-----------------------------------------------
`request_builder._build_scope_context` is only invoked on the execute
path. When `actual_route_action == "clarify"`, `scope_context` is never
constructed — there is no `business_line` to compare, no
`primary_object` threaded into a tool request. Therefore: for any row
whose `expected_route_action == "clarify"`, the executor-comparable
fields (`expected_primary_object` / `expected_primary_object_one_of` /
`expected_business_line`) MUST be set to None. The observe script may
still record actuals as artifacts, but must not flag mismatches on
those fields when the route is clarify.

Note on parser-dependent route (soft expectations)
--------------------------------------------------
A few rows are probes rather than assertions: their
`expected_route_action` depends on a parser judgment we cannot reliably
predict (e.g. whether `dialogue_act` is tagged "selection" vs "inquiry"
on a vague reference query). For those rows, set
`route_is_soft_expectation: True`. The observe script should still
record `actual_route_action` and `actual_clarification_kind` for the
audit artifact, but must not raise a mismatch finding when those differ
from the soft expectation. Use sparingly — most rows should be hard
assertions so the audit retains its diagnostic value.

Schema
------
Each row is a `dict` with the keys below. All `expected_*` fields are
hypothesis annotations — the audit script compares them against observed
values and flags mismatches.

  id                       : stable identifier for CSV joins
  bucket                   : one of {strong_ambig, referential, weak_ambig,
                                     selection_followup}
  query                    : raw user message text
  conversation_history     : list of prior turns (only used for
                             selection_followup); each entry is a dict with
                             {"role": "user"|"assistant", "content": str}
                             matching `ConversationMessage`
  expected_route_action    : "execute" | "clarify"
  expected_clarification_kind: ""        — when route is execute
                              "object_disambiguation" — strong ambig
                              "selection_context_missing" — selection w/o
                              prior context
  expected_primary_object  : canonical service/product name, or None when
                             nothing should resolve. Mutually exclusive
                             with expected_primary_object_one_of.
  expected_primary_object_one_of:
                             optional list of canonical names — use when
                             score-tiebreak between candidates makes any
                             of them acceptable (see "Note on
                             multi-candidate resolution"). Mutually
                             exclusive with expected_primary_object.
  expected_business_line   : value from `KNOWN_BUSINESS_LINES`, or None
                             when no biz_line should propagate to scope
  route_is_soft_expectation: bool, default False. Set True when
                             `expected_route_action` depends on a parser
                             judgment we cannot reliably predict (see
                             "Note on parser-dependent route"). Observe
                             script records actuals but does not flag
                             mismatches.
  prior_clarification_state   : optional dict — only required for
                             selection_followup rows. Keys mirror the
                             clarification-memory fields carried inside
                             `src.memory.models.MemoryContext.snapshot`:
                                 pending_clarification_type  (str)
                                 pending_candidate_options    (list[str])
                                 pending_identifier           (str)
                             The audit harness MUST construct a minimal
                             `MemoryContext(snapshot=MemorySnapshot(
                             clarification_memory=ClarificationMemory(...)))`
                             and pass it to
                             `build_ingestion_bundle(...,
                             memory_context=...)`. None / absent for
                             non-selection rows.
  hypothesis_notes         : short rationale — what behavior we expect and
                             why (parser→objects→routing path-specific)
"""
from __future__ import annotations

from typing import Any

# Static list — fixture authoring is a deliberate, slow process. Do not
# auto-generate.
AUDIT_CORPUS: list[dict[str, Any]] = [
    # ------------------------------------------------------------------
    # A. Strong ambiguity — same surface form maps to multiple registry
    #    entries across or within business_lines. Expected: routing
    #    should block execution and emit object_disambiguation clarify.
    # ------------------------------------------------------------------
    {
        "id": "audit_strong_ambig_cho_cross_biz_line",
        "bucket": "strong_ambig",
        "query": "Can you do CHO work for me? I need to discuss what's possible.",
        "conversation_history": [],
        "expected_route_action": "clarify",
        "expected_clarification_kind": "object_disambiguation",
        "expected_primary_object": None,
        "expected_business_line": None,
        "hypothesis_notes": (
            "CHO appears in stable cell line (protein_expression biz_line) and "
            "in mammalian protein expression hosts. If product_registry surfaces "
            "both as candidates with the same alias 'CHO', "
            "product_extractor should yield AmbiguousObjectSet with "
            "ambiguity_kind=cross_business_line. If it does not — finding."
        ),
    },
    {
        "id": "audit_strong_ambig_monoclonal_unscoped",
        "bucket": "strong_ambig",
        "query": "We're looking into monoclonal antibody development — what options do you have?",
        "conversation_history": [],
        "expected_route_action": "clarify",
        "expected_clarification_kind": "object_disambiguation",
        "expected_primary_object": None,
        "expected_business_line": None,
        "hypothesis_notes": (
            "'monoclonal antibody' (without species) could route to mouse / "
            "rabbit / human mAb services. Service alias map currently lists "
            "species-prefixed aliases only ('mouse monoclonal', 'rabbit "
            "monoclonal', 'human monoclonal') — bare 'monoclonal antibody' may "
            "fall through and produce no candidate at all. If primary_object "
            "is None and route is 'execute' (not 'clarify'), the design "
            "assumption that strong ambiguity always blocks execution is "
            "incomplete — finding. expected_business_line is None per the "
            "executor-fields-when-clarify rule (no scope built on clarify)."
        ),
    },

    # ------------------------------------------------------------------
    # B. Referential / no-hit — vague reference resolves to no registry
    #    entry. Expected: primary_object=None, route=execute, RAG runs
    #    on raw query relying on bucket+section_boost only.
    # ------------------------------------------------------------------
    {
        "id": "audit_referential_the_protein",
        "bucket": "referential",
        "query": "How long does it take for the protein to express? I want a rough timeline.",
        "conversation_history": [],
        "expected_route_action": "execute",
        "expected_clarification_kind": "",
        "expected_primary_object": None,
        "expected_business_line": None,
        "hypothesis_notes": (
            "'the protein' is a bare definite reference with no antecedent "
            "(no conversation_history). Object extractors should not "
            "fabricate a candidate. Route is execute because dialogue_act is "
            "inquiry, not selection. RAG should still run — the audit "
            "checks that scope_context.business_line is empty rather than "
            "incorrectly populated from a hallucinated candidate."
        ),
    },
    {
        "id": "audit_referential_that_thing_no_history",
        "bucket": "referential",
        "query": "What's the timeline for that thing we discussed?",
        "conversation_history": [],
        "expected_route_action": "clarify",
        "expected_clarification_kind": "selection_context_missing",
        "expected_primary_object": None,
        "expected_business_line": None,
        "route_is_soft_expectation": True,
        "hypothesis_notes": (
            "PROBE, not assertion. Whether route lands on clarify "
            "(selection_context_missing) or execute depends on whether "
            "the parser tags this as dialogue_act=selection vs inquiry "
            "for a bare referential without prior context. The audit "
            "should record actual route + dialogue_act as artifacts and "
            "leave the inquiry-vs-selection judgment to dedicated parser "
            "evaluation. If the parser consistently tags one way across "
            "runs, future fixture revisions can promote this to a hard "
            "expectation."
        ),
    },

    # ------------------------------------------------------------------
    # C. Weak ambiguity (within one biz_line) — design says active_service
    #    leverage_3 + biz_line soft boost should resolve without
    #    clarification. Expected: route=execute, primary_object resolves
    #    to a single canonical entry, biz_line propagates to scope.
    # ------------------------------------------------------------------
    {
        "id": "audit_weak_ambig_rabbit_polyclonal_specific",
        "bucket": "weak_ambig",
        "query": "I'd like to set up a rabbit polyclonal antibody project against a custom peptide.",
        "conversation_history": [],
        "expected_route_action": "execute",
        "expected_clarification_kind": "",
        "expected_primary_object": "Rabbit Polyclonal Antibody Production",
        "expected_business_line": "antibody",
        "hypothesis_notes": (
            "'rabbit polyclonal' is in MANUAL_SERVICE_ALIASES under exactly "
            "one canonical service. Should resolve unambiguously, no "
            "clarify, scope_context.business_line='antibody'."
        ),
    },
    {
        "id": "audit_weak_ambig_compare_mouse_human_mab",
        "bucket": "weak_ambig",
        "query": "What's the difference between your mouse monoclonal and human monoclonal antibody services?",
        "conversation_history": [],
        "expected_route_action": "execute",
        "expected_clarification_kind": "",
        "expected_primary_object": None,
        "expected_primary_object_one_of": [
            "Mouse Monoclonal Antibodies",
            "Human Monoclonal Antibodies",
        ],
        "expected_business_line": "antibody",
        "hypothesis_notes": (
            "Two services in the same biz_line are explicitly named for "
            "comparison. Audit focus: (a) route=execute, NOT clarify "
            "(comparison is not ambiguity); (b) BOTH services appear in "
            "candidates — one as primary_object, the other as a member of "
            "secondary_objects. Which becomes primary is score-driven by "
            "resolve_objects(); record the choice but do not assert. "
            "Fixture uses expected_primary_object_one_of so a flip "
            "between mouse and human does not raise a false positive. "
            "What WOULD be a finding: routing emits clarify, OR only one "
            "of the two surfaces in candidates."
        ),
    },

    # ------------------------------------------------------------------
    # D. Selection follow-up — prior turn offered options, current turn
    #    picks one. Expected: selection extractor locks the chosen
    #    candidate, route=execute, executor builds scope_context with
    #    that candidate's business_line.
    # ------------------------------------------------------------------
    {
        "id": "audit_selection_named_rabbit_after_clarify",
        "bucket": "selection_followup",
        "query": "Let's go with the rabbit one.",
        "conversation_history": [
            {
                "role": "user",
                "content": "I'm interested in monoclonal antibody development.",
            },
            {
                "role": "assistant",
                "content": (
                    "We offer monoclonal antibody services with three host "
                    "species. Which would you like? "
                    "1) Mouse Monoclonal Antibodies "
                    "2) Rabbit Monoclonal Antibody Development "
                    "3) Human Monoclonal Antibodies"
                ),
            },
        ],
        "prior_clarification_state": {
            "pending_clarification_type": "service_selection",
            "pending_candidate_options": [
                "Mouse Monoclonal Antibodies",
                "Rabbit Monoclonal Antibody Development",
                "Human Monoclonal Antibodies",
            ],
            "pending_identifier": "monoclonal antibody",
        },
        "expected_route_action": "execute",
        "expected_clarification_kind": "",
        # Canonical "Rabbit Monoclonal Antibodies" — even though the
        # assistant turn / pending_candidate_options surface the alias
        # form "Rabbit Monoclonal Antibody Development", registry
        # canonicalization rightly returns the canonical name.
        "expected_primary_object": "Rabbit Monoclonal Antibodies",
        "expected_business_line": "antibody",
        "hypothesis_notes": (
            "Named selection ('the rabbit one'). Required state path: "
            "(1) context_extractor reads pending_clarification_type + "
            "pending_candidate_options and rebuilds an AmbiguousObjectSet "
            "with three candidates; (2) parser sees pending clarification "
            "in its prompt and emits SelectionResolution with "
            "selected_value matching 'Rabbit...' and confidence >= 0.5; "
            "(3) resolve_objects applies that selection against the "
            "rebuilt ambiguous_sets and the registry canonicalizes the "
            "alias 'Rabbit Monoclonal Antibody Development' to its "
            "canonical 'Rabbit Monoclonal Antibodies'. Any of those "
            "three breaking is a finding. conversation_history alone is "
            "INSUFFICIENT — harness must wrap prior_clarification_state in a "
            "minimal MemoryContext so build_ingestion_bundle() sees the "
            "derived anchor view."
        ),
    },
    {
        "id": "audit_selection_ordinal_option_two_car",
        "bucket": "selection_followup",
        "query": "I'll go with option 2.",
        "conversation_history": [
            {
                "role": "user",
                "content": "We're scoping out a CAR-based therapy project. What service options do you have?",
            },
            {
                "role": "assistant",
                "content": (
                    "We have three CAR-based service lines. Which fits your project? "
                    "1) CAR-T Cell Design and Development "
                    "2) Custom CAR-NK Manufacturing "
                    "3) Custom CAR-Macrophage Cell Development"
                ),
            },
        ],
        "prior_clarification_state": {
            "pending_clarification_type": "service_selection",
            "pending_candidate_options": [
                "CAR-T Cell Design and Development",
                "Custom CAR-NK Manufacturing",
                "Custom CAR-Macrophage Cell Development",
            ],
            "pending_identifier": "CAR-based service",
        },
        "expected_route_action": "execute",
        "expected_clarification_kind": "",
        "expected_primary_object": "Custom CAR-NK Manufacturing",
        "expected_business_line": "car_t_car_nk",
        "hypothesis_notes": (
            "Ordinal selection ('option 2'). Same three-step state path "
            "as the named-selection row, but parser should emit "
            "SelectionResolution with selected_index=1 (zero-based — "
            "verify against parser_prompt) or selected_value matching "
            "the second candidate. Service-level selection chosen "
            "deliberately so pending_clarification_type='service_selection' "
            "produces object_type='service' via "
            "_infer_pending_object_type. (Selection at attribute level, "
            "e.g. host-cell-line as a property of stable-cell-line "
            "service, is a separate boundary case worth a future fixture "
            "but not encoded here.)"
        ),
    },
]


def by_bucket(bucket: str) -> list[dict[str, Any]]:
    """Convenience accessor used by the audit script."""
    return [row for row in AUDIT_CORPUS if row["bucket"] == bucket]


_EXPECTED_BUCKET_COUNTS = {
    "strong_ambig": 2,
    "referential": 2,
    "weak_ambig": 2,
    "selection_followup": 2,
}


_REQUIRED_PENDING_KEYS = {
    "pending_clarification_type",
    "pending_candidate_options",
    "pending_identifier",
}


def _validate_corpus() -> None:
    """Sanity-check at import time so a structural typo fails loud."""
    seen_ids: set[str] = set()
    for row in AUDIT_CORPUS:
        if row["id"] in seen_ids:
            raise ValueError(f"Duplicate audit row id: {row['id']}")
        seen_ids.add(row["id"])
        if (
            row.get("expected_primary_object") is not None
            and row.get("expected_primary_object_one_of")
        ):
            raise ValueError(
                f"Row {row['id']}: expected_primary_object and "
                "expected_primary_object_one_of are mutually exclusive."
            )
        if row["expected_route_action"] == "clarify":
            for executor_field in (
                "expected_primary_object",
                "expected_primary_object_one_of",
                "expected_business_line",
            ):
                value = row.get(executor_field)
                if value not in (None, []):
                    raise ValueError(
                        f"Row {row['id']}: {executor_field}={value!r} but "
                        "expected_route_action='clarify'. Executor scope is "
                        "not built on the clarify path; this field must be "
                        "None (see 'Note on executor-side fields when "
                        "route=clarify')."
                    )
        if row["bucket"] == "selection_followup":
            anchors = row.get("prior_clarification_state")
            if not isinstance(anchors, dict):
                raise ValueError(
                    f"Row {row['id']}: selection_followup rows require a "
                    "prior_clarification_state dict (see schema docstring)."
                )
            missing = _REQUIRED_PENDING_KEYS - anchors.keys()
            if missing:
                raise ValueError(
                    f"Row {row['id']}: prior_clarification_state missing keys "
                    f"{sorted(missing)}."
                )
            if not anchors["pending_candidate_options"]:
                raise ValueError(
                    f"Row {row['id']}: pending_candidate_options must be "
                    "non-empty for selection_followup."
                )
            if not anchors["pending_clarification_type"]:
                raise ValueError(
                    f"Row {row['id']}: pending_clarification_type must be "
                    "non-empty so context_extractor rebuilds ambiguous_sets."
                )
    for bucket, expected_n in _EXPECTED_BUCKET_COUNTS.items():
        actual_n = len(by_bucket(bucket))
        if actual_n != expected_n:
            raise ValueError(
                f"Bucket '{bucket}' has {actual_n} rows, expected {expected_n}. "
                "Update _EXPECTED_BUCKET_COUNTS if intentional."
            )


_validate_corpus()
