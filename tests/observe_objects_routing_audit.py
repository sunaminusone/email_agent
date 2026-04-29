"""Drive the production objects→routing slice on AUDIT_CORPUS and dump
observations for backlog item #11.

This harness is the missing observation lens — `tests/observe_rag_accuracy.py`
and `tests/observe_rag_confidence_e2e.py` both bypass `resolve_objects` and
the routing policies, so neither can falsify the v3 closed-loop assumption
that ambiguity → clarify and selection → primary_object actually fires on
real queries.

Per the fixture's docstring, four observation points per row:
  (1) ambiguous_sets non-empty?  (resolve_objects)
  (2) route_decision.action / clarification.kind   (routing.orchestrator.route)
  (3) primary_object after selection follow-up      (resolved_object_state)
  (4) scope_context["business_line"] when route=execute (request_builder)

Notes on what this script DOES NOT do:
  - It does not run the executor or any tools (no LLM-driven retrieval). The
    audit's purpose is upstream of execution.
  - It does not rebuild a full MemorySnapshot. `prior_clarification_state` is
    converted into a minimal `MemoryContext` / `MemorySnapshot`
    clarification state, which is sufficient for the
    production-equivalent path that context_extractor → resolve_objects
    relies on.

Usage:
    python tests/observe_objects_routing_audit.py
    python tests/observe_objects_routing_audit.py --csv outputs/observe_objects_routing_audit.csv
"""
from __future__ import annotations

import argparse
import csv
import sys
import traceback
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.executor.request_builder import _build_scope_context  # noqa: E402
from src.ingestion import build_demand_profile  # noqa: E402
from src.ingestion.demand_profile import narrow_demand_profile  # noqa: E402
from src.ingestion.pipeline import build_ingestion_bundle  # noqa: E402
from src.memory.models import ClarificationMemory, MemoryContext, MemorySnapshot  # noqa: E402
from src.objects.extraction import extract_object_bundle  # noqa: E402
from src.objects.resolution import resolve_objects  # noqa: E402
from src.routing.intent_assembly import assemble_intent_groups  # noqa: E402
from src.routing.orchestrator import route  # noqa: E402
from tests.fixtures.objects_routing_audit_corpus import AUDIT_CORPUS  # noqa: E402


# ---------------------------------------------------------------------------
# Per-row driver
# ---------------------------------------------------------------------------

def _observe_row(row: dict[str, Any]) -> dict[str, Any]:
    """Drive one audit row through ingestion → objects → routing → scope."""
    row_id = row["id"]
    bucket = row["bucket"]
    query = row["query"]
    history = row.get("conversation_history") or []
    prior_clarification_state = row.get("prior_clarification_state")

    out: dict[str, Any] = {
        "id": row_id,
        "bucket": bucket,
        "query": query[:80],
        "expected_route_action": row["expected_route_action"],
        "expected_clarification_kind": row.get("expected_clarification_kind", ""),
        "expected_primary_object": row.get("expected_primary_object") or "",
        "expected_primary_object_one_of": " | ".join(
            row.get("expected_primary_object_one_of") or []
        ),
        "expected_business_line": row.get("expected_business_line") or "",
        "route_is_soft_expectation": "Y" if row.get("route_is_soft_expectation") else "",
        # Observations populated below
        "actual_dialogue_act": "",
        # Pre-resolution view: what context_extractor / object extractors
        # built BEFORE selection consumed any matching set. This is the only
        # signal that tells us whether `pending_clarification_type` →
        # ambiguous_set rebuild actually fired on selection_followup rows.
        "pre_resolution_ambiguous_sets_count": "",
        "pre_resolution_ambiguity_kinds": "",
        # Post-resolution view: useful for diffing — drop from non-zero pre
        # to zero post means selection_resolution consumed the set.
        "post_resolution_ambiguous_sets_count": "",
        "post_resolution_ambiguity_kinds": "",
        "actual_route_action": "",
        "actual_clarification_kind": "",
        "actual_primary_object": "",
        "actual_primary_object_type": "",
        "actual_secondary_objects": "",
        "actual_business_line_on_primary": "",
        "actual_scope_business_line": "",
        # Mismatch flags populated by _flag_mismatches
        "route_mismatch": "",
        "clarification_kind_mismatch": "",
        "primary_object_mismatch": "",
        "business_line_mismatch": "",
        "ambiguous_sets_mismatch": "",
        "error": "",
    }

    # Build a minimal MemoryContext if present (only selection_followup rows
    # have it, but the schema permits it elsewhere too).
    memory_context: MemoryContext | None = None
    if prior_clarification_state is not None:
        memory_context = MemoryContext(
            snapshot=MemorySnapshot(
                clarification_memory=ClarificationMemory(
                    pending_clarification_type=prior_clarification_state.get(
                        "pending_clarification_type", ""
                    ),
                    pending_candidate_options=list(
                        prior_clarification_state.get("pending_candidate_options", [])
                        or []
                    ),
                    pending_identifier=prior_clarification_state.get(
                        "pending_identifier", ""
                    ),
                )
            )
        )

    try:
        bundle = build_ingestion_bundle(
            thread_id=f"audit::{row_id}",
            user_query=query,
            conversation_history=history,
            memory_context=memory_context,
        )
        # Capture the pre-resolution ambiguous_sets explicitly. resolve_objects
        # internally calls extract_object_bundle and then may consume matching
        # sets via selection_resolution — observing only post-resolution
        # cannot distinguish "set rebuilt and consumed" from "never rebuilt".
        pre_bundle = extract_object_bundle(bundle, recent_objects=None)
        resolved = resolve_objects(bundle)
        intent_groups = assemble_intent_groups(
            request_flags=bundle.turn_signals.parser_signals.request_flags,
            resolved_objects=[
                resolved.primary_object,
                *resolved.secondary_objects,
            ],
            semantic_intent=bundle.turn_signals.parser_signals.context.semantic_intent,
        )
        demand_profile = build_demand_profile(
            bundle.turn_signals.parser_signals,
            intent_groups,
        )
        # Match production: route per group. Audit on the first group (the
        # "primary" intent for this query). Multi-group queries are out of
        # scope for #11 — single-intent fixture by design.
        focus_group = intent_groups[0] if intent_groups else None
        scoped_demand = narrow_demand_profile(demand_profile, focus_group)
        route_decision = route(
            bundle,
            resolved,
            focus_group=focus_group,
            scoped_demand=scoped_demand,
        )
    except Exception as exc:  # noqa: BLE001 — record and continue
        out["error"] = f"{type(exc).__name__}: {exc}"
        traceback.print_exc(file=sys.stderr)
        return out

    # --- Observation 1: ambiguous_sets (pre + post)
    out["pre_resolution_ambiguous_sets_count"] = str(len(pre_bundle.ambiguous_sets))
    out["pre_resolution_ambiguity_kinds"] = " | ".join(
        s.ambiguity_kind for s in pre_bundle.ambiguous_sets if s.ambiguity_kind
    )
    out["post_resolution_ambiguous_sets_count"] = str(len(resolved.ambiguous_sets))
    out["post_resolution_ambiguity_kinds"] = " | ".join(
        s.ambiguity_kind for s in resolved.ambiguous_sets if s.ambiguity_kind
    )

    # --- Observation 2: route action + clarification
    out["actual_dialogue_act"] = route_decision.dialogue_act.act
    out["actual_route_action"] = route_decision.action
    out["actual_clarification_kind"] = (
        route_decision.clarification.kind
        if route_decision.clarification is not None
        else ""
    )

    # --- Observation 3: primary_object after resolution
    primary = resolved.primary_object
    if primary is not None:
        out["actual_primary_object"] = primary.canonical_value or primary.display_name or primary.identifier
        out["actual_primary_object_type"] = primary.object_type
        out["actual_business_line_on_primary"] = primary.business_line or ""
    out["actual_secondary_objects"] = " | ".join(
        (s.canonical_value or s.display_name or s.identifier)
        for s in resolved.secondary_objects
    )

    # --- Observation 4: scope_context.business_line (only meaningful on execute)
    if route_decision.action == "execute":
        scope = _build_scope_context(
            query=bundle.turn_core.normalized_query or query,
            primary_object=primary,
            secondary_objects=list(resolved.secondary_objects),
            dialogue_act=route_decision.dialogue_act,
            semantic_intent=bundle.turn_signals.parser_signals.context.semantic_intent,
        )
        # _build_scope_context doesn't store business_line at top-level; it's
        # carried by primary_object. Mirror what request_builder threads via
        # retrieval_hints.business_line — which is primary.business_line.
        out["actual_scope_business_line"] = (
            primary.business_line if primary is not None else ""
        )
        # Keep scope dict around for debugging if needed (not exported).
        _ = scope

    _flag_mismatches(row, out)
    return out


# ---------------------------------------------------------------------------
# Mismatch detection
# ---------------------------------------------------------------------------

def _flag_mismatches(row: dict[str, Any], out: dict[str, Any]) -> None:
    """Populate *_mismatch fields on `out`.

    Three rules govern severity:

    (a) `route_is_soft_expectation=True` demotes ALL route-dependent
        mismatches (route, clarification kind, primary_object, business_line)
        to "note". Without this, a soft row that lands on a different
        branch still pollutes the rollup via downstream comparisons
        derived from the actual route.

    (b) When the fixture-declared route is "clarify", executor-side fields
        are forbidden (the fixture validator enforces them None) — no
        comparison runs.

    (c) Bucket-level ambiguous_sets sanity uses the PRE-resolution count
        (`extract_object_bundle` output before `resolve_objects` may
        consume a matching set via selection_resolution). For
        selection_followup the post-resolution count is 0 on success and
        N>0 on failure — exactly inverted from intuition — so only the
        pre-resolution snapshot can falsify the rebuild step.
    """
    expected_route = row["expected_route_action"]
    actual_route = out["actual_route_action"]
    soft = bool(row.get("route_is_soft_expectation"))
    # Tag value used for soft demotion / non-binding observations.
    demoted = "note"

    def _flag(key: str, condition: bool) -> None:
        if not condition:
            return
        out[key] = demoted if soft else "Y"

    # Route mismatch
    _flag("route_mismatch", actual_route != expected_route)

    # Clarification kind — only meaningful when both rows agree route is clarify
    _flag(
        "clarification_kind_mismatch",
        (
            expected_route == "clarify"
            and actual_route == "clarify"
            and bool(row.get("expected_clarification_kind", ""))
            and out["actual_clarification_kind"] != row["expected_clarification_kind"]
        ),
    )

    # Executor-side fields are only valid on actual execute path. Per fixture
    # rule, if expected route is clarify they're already None — skip.
    if actual_route == "execute":
        # primary_object: strict if expected_primary_object set; one_of if list.
        expected_primary_single = row.get("expected_primary_object")
        expected_primary_one_of = row.get("expected_primary_object_one_of") or []
        actual_primary = out["actual_primary_object"]

        if expected_primary_single is not None:
            _flag("primary_object_mismatch", actual_primary != expected_primary_single)
        elif expected_primary_one_of:
            _flag("primary_object_mismatch", actual_primary not in expected_primary_one_of)
        else:
            # expected is None — only flag if hypothesis was that no candidate
            # should resolve and one did.
            _flag("primary_object_mismatch", bool(actual_primary))

        # business_line
        expected_bl = row.get("expected_business_line")
        actual_bl = out["actual_scope_business_line"]
        if expected_bl is None:
            _flag("business_line_mismatch", bool(actual_bl))
        else:
            _flag("business_line_mismatch", actual_bl != expected_bl)

    # Ambiguous_sets sanity uses PRE-resolution count.
    #   strong_ambig         : extractor must have produced >=1 set.
    #   selection_followup   : context_extractor must have rebuilt >=1 set
    #                          from the derived memory anchor view before
    #                          selection_resolution could consume it.
    #   weak_ambig / referential: pre==0 expected; pre>0 is a soft note,
    #                             not a hard fail (extractor may legitimately
    #                             surface incidental ambiguity).
    pre_n = int(out["pre_resolution_ambiguous_sets_count"] or 0)
    bucket = row["bucket"]
    if bucket in ("strong_ambig", "selection_followup") and pre_n == 0:
        out["ambiguous_sets_mismatch"] = "Y"
    elif bucket in ("weak_ambig", "referential") and pre_n > 0:
        out["ambiguous_sets_mismatch"] = "note"


# ---------------------------------------------------------------------------
# Rollup + IO
# ---------------------------------------------------------------------------

def _rollup(rows: list[dict[str, Any]]) -> None:
    print("\n=== OBJECTS→ROUTING AUDIT ROLLUP ===")
    n = len(rows)
    errors = [r for r in rows if r["error"]]
    if errors:
        print(f"\n[ERRORS]  {len(errors)}/{n}")
        for r in errors:
            print(f"  {r['id']}: {r['error']}")

    print(f"\n[ROW SUMMARY]  n={n}")
    for r in rows:
        soft_tag = " [SOFT]" if r["route_is_soft_expectation"] == "Y" else ""
        flags = []
        for key, label in (
            ("route_mismatch", "route"),
            ("clarification_kind_mismatch", "clar_kind"),
            ("primary_object_mismatch", "primary"),
            ("business_line_mismatch", "biz_line"),
            ("ambiguous_sets_mismatch", "ambig_sets"),
        ):
            if r[key] == "Y":
                flags.append(f"⚠{label}")
            elif r[key] == "note":
                flags.append(f"·{label}")
        flag_str = (" " + " ".join(flags)) if flags else ""
        print(
            f"  {r['id']}{soft_tag}\n"
            f"    route: expected={r['expected_route_action']} "
            f"actual={r['actual_route_action']} ({r['actual_clarification_kind'] or '-'})\n"
            f"    primary: expected="
            f"{r['expected_primary_object'] or r['expected_primary_object_one_of'] or '-'} "
            f"actual={r['actual_primary_object'] or '-'} "
            f"(type={r['actual_primary_object_type'] or '-'})\n"
            f"    biz_line: expected={r['expected_business_line'] or '-'} "
            f"actual={r['actual_scope_business_line'] or '-'}\n"
            f"    ambig_sets: pre={r['pre_resolution_ambiguous_sets_count'] or '0'} "
            f"post={r['post_resolution_ambiguous_sets_count'] or '0'} "
            f"({r['pre_resolution_ambiguity_kinds'] or '-'}){flag_str}"
        )

    # Bucket-level pass/fail
    print("\n[BUCKET ROLLUP]")
    for bucket in ("strong_ambig", "referential", "weak_ambig", "selection_followup"):
        rows_b = [r for r in rows if r["bucket"] == bucket]
        if not rows_b:
            continue
        # A row "passes" if no hard mismatch flags and no error.
        def is_pass(r: dict[str, Any]) -> bool:
            if r["error"]:
                return False
            for key in (
                "route_mismatch",
                "clarification_kind_mismatch",
                "primary_object_mismatch",
                "business_line_mismatch",
                "ambiguous_sets_mismatch",
            ):
                if r[key] == "Y":
                    return False
            return True

        passed = sum(1 for r in rows_b if is_pass(r))
        print(f"  {bucket:22s}: {passed}/{len(rows_b)}")


def _export_csv(rows: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"\nexported {path}", file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--csv",
        type=str,
        default="outputs/observe_objects_routing_audit.csv",
    )
    parser.add_argument(
        "--row",
        type=str,
        default=None,
        help="Run a single row by id (for quick debugging).",
    )
    args = parser.parse_args()

    corpus = AUDIT_CORPUS
    if args.row:
        corpus = [r for r in AUDIT_CORPUS if r["id"] == args.row]
        if not corpus:
            sys.stderr.write(f"no row matches id={args.row}\n")
            sys.exit(2)

    rows: list[dict[str, Any]] = []
    total = len(corpus)
    for idx, row in enumerate(corpus, start=1):
        print(f"[{idx}/{total}] ({row['bucket']}) {row['id']}", file=sys.stderr)
        rows.append(_observe_row(row))

    _rollup(rows)
    if args.csv:
        _export_csv(rows, PROJECT_ROOT / args.csv)


if __name__ == "__main__":
    main()
