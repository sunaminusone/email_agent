from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.ingestion.models import (
    EntitySpan,
    ParserContext,
    ParserRequestFlags,
    ParserSignals,
    ParserEntitySignals,
)
from src.ingestion.signal_refinement import (
    reconcile_intent_and_flags,
)


def _make_signals(
    *,
    intent: str = "unknown",
    flags: ParserRequestFlags | None = None,
    order_numbers: list[EntitySpan] | None = None,
    invoice_numbers: list[EntitySpan] | None = None,
) -> ParserSignals:
    entities_kwargs = {}
    if order_numbers is not None:
        entities_kwargs["order_numbers"] = order_numbers
    if invoice_numbers is not None:
        entities_kwargs["invoice_numbers"] = invoice_numbers
    return ParserSignals(
        context=ParserContext(primary_intent=intent),
        request_flags=flags or ParserRequestFlags(),
        entities=ParserEntitySignals(**entities_kwargs),
    )


def _span(text: str) -> EntitySpan:
    return EntitySpan(text=text, raw=text)


# -----------------------------------------------------------------------
# Gap fill: commercial family
# -----------------------------------------------------------------------

def test_gap_fill_pricing_question_no_flags():
    """intent=pricing_question with zero flags → supplement needs_price."""
    result = reconcile_intent_and_flags(
        _make_signals(intent="pricing_question"),
    )
    assert result.request_flags.needs_price is True


def test_gap_fill_pricing_question_has_quote_flag():
    """intent=pricing_question with needs_quote already set → no change."""
    result = reconcile_intent_and_flags(
        _make_signals(
            intent="pricing_question",
            flags=ParserRequestFlags(needs_quote=True),
        ),
    )
    assert result.request_flags.needs_price is False
    assert result.request_flags.needs_quote is True


def test_gap_fill_timeline_question_no_flags():
    result = reconcile_intent_and_flags(
        _make_signals(intent="timeline_question"),
    )
    assert result.request_flags.needs_timeline is True


def test_gap_fill_customization_request_no_flags():
    result = reconcile_intent_and_flags(
        _make_signals(intent="customization_request"),
    )
    assert result.request_flags.needs_customization is True


# -----------------------------------------------------------------------
# Gap fill: operational family
# -----------------------------------------------------------------------

def test_gap_fill_order_support_no_flags():
    result = reconcile_intent_and_flags(
        _make_signals(intent="order_support"),
    )
    assert result.request_flags.needs_order_status is True


def test_gap_fill_shipping_question_no_flags():
    result = reconcile_intent_and_flags(
        _make_signals(intent="shipping_question"),
    )
    assert result.request_flags.needs_shipping_info is True


def test_gap_fill_complaint_no_flags():
    result = reconcile_intent_and_flags(
        _make_signals(intent="complaint"),
    )
    assert result.request_flags.needs_refund_or_cancellation is True


def test_gap_fill_complaint_has_invoice_flag():
    """complaint with needs_invoice already set → no supplement."""
    result = reconcile_intent_and_flags(
        _make_signals(
            intent="complaint",
            flags=ParserRequestFlags(needs_invoice=True),
        ),
    )
    assert result.request_flags.needs_refund_or_cancellation is False
    assert result.request_flags.needs_invoice is True


# -----------------------------------------------------------------------
# Gap fill: technical family skipped
# -----------------------------------------------------------------------

def test_gap_fill_skips_technical_question():
    """Technical gap fill is NOT done here."""
    result = reconcile_intent_and_flags(
        _make_signals(intent="technical_question"),
    )
    assert result.request_flags.needs_protocol is False
    assert result.request_flags.needs_troubleshooting is False


# -----------------------------------------------------------------------
# Cross-family fix
# -----------------------------------------------------------------------

def test_cross_family_pricing_intent_technical_flags():
    """intent=pricing_question but only needs_protocol → gap fill adds
    needs_price first, then cross-family sees both families → no fix.
    This is correct: the result is multi-intent (price + protocol)."""
    result = reconcile_intent_and_flags(
        _make_signals(
            intent="pricing_question",
            flags=ParserRequestFlags(needs_protocol=True),
        ),
    )
    assert result.context.primary_intent == "pricing_question"
    assert result.request_flags.needs_protocol is True
    assert result.request_flags.needs_price is True  # gap-filled


def test_cross_family_technical_intent_commercial_flags():
    """intent=technical_question but only needs_price → fix intent."""
    result = reconcile_intent_and_flags(
        _make_signals(
            intent="technical_question",
            flags=ParserRequestFlags(needs_price=True),
        ),
    )
    assert result.context.primary_intent == "pricing_question"
    assert result.request_flags.needs_price is True


def test_cross_family_no_fix_when_family_matches():
    """intent=pricing_question + needs_price + needs_protocol → no fix."""
    result = reconcile_intent_and_flags(
        _make_signals(
            intent="pricing_question",
            flags=ParserRequestFlags(needs_price=True, needs_protocol=True),
        ),
    )
    # commercial is present in flag families, so no cross-family fix
    assert result.context.primary_intent == "pricing_question"


def test_cross_family_skips_vague_intent():
    """intent=unknown + needs_price → not a contradiction, skip."""
    result = reconcile_intent_and_flags(
        _make_signals(
            intent="unknown",
            flags=ParserRequestFlags(needs_price=True),
        ),
    )
    # validate_intent_and_flags handles vague→specific, not cross-family
    assert result.context.primary_intent == "unknown"


def test_cross_family_skips_no_flags():
    """intent=pricing_question + no flags → handled by gap fill, not cross-family."""
    signals = _make_signals(intent="pricing_question")
    result = reconcile_intent_and_flags(signals)
    # Gap fill adds needs_price; cross-family sees family match → no fix
    assert result.context.primary_intent == "pricing_question"
    assert result.request_flags.needs_price is True


def test_cross_family_operational_intent_technical_flags():
    """intent=order_support + only needs_troubleshooting → gap fill adds
    needs_order_status (operational family empty), so both families present.
    Result: multi-intent, intent stays order_support."""
    result = reconcile_intent_and_flags(
        _make_signals(
            intent="order_support",
            flags=ParserRequestFlags(needs_troubleshooting=True),
        ),
    )
    assert result.context.primary_intent == "order_support"
    assert result.request_flags.needs_order_status is True  # gap-filled
    assert result.request_flags.needs_troubleshooting is True


def test_cross_family_pure_documentation_intent_commercial_flags():
    """intent=documentation_request (technical, no gap fill) but only
    needs_price → cross-family fixes intent to pricing_question."""
    result = reconcile_intent_and_flags(
        _make_signals(
            intent="documentation_request",
            flags=ParserRequestFlags(needs_price=True),
        ),
    )
    assert result.context.primary_intent == "pricing_question"
    assert result.request_flags.needs_price is True


def test_cross_family_pure_troubleshooting_intent_operational_flags():
    """intent=troubleshooting (technical, no gap fill) but only
    needs_order_status → cross-family fixes intent to order_support."""
    result = reconcile_intent_and_flags(
        _make_signals(
            intent="troubleshooting",
            flags=ParserRequestFlags(needs_order_status=True),
        ),
    )
    assert result.context.primary_intent == "order_support"
    assert result.request_flags.needs_order_status is True
