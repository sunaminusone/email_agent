from __future__ import annotations

from src.schemas import ResponseTopic

from .common import RendererUnavailableError
from .document_renderer import render_document
from .operational_renderer import render_operational
from .pricing_renderer import render_pricing
from .product_renderer import render_product
from .technical_renderer import render_technical
from .workflow_renderer import render_workflow


TOPIC_RENDERERS = {
    ResponseTopic.COMMERCIAL_QUOTE.value: render_pricing,
    ResponseTopic.PRODUCT_INFO.value: render_product,
    ResponseTopic.DOCUMENT_DELIVERY.value: render_document,
    ResponseTopic.OPERATIONAL_STATUS.value: render_operational,
    ResponseTopic.TECHNICAL_DOC.value: render_technical,
    ResponseTopic.WORKFLOW_STATUS.value: render_workflow,
}


def render_topic_response(payload: dict):
    renderer = TOPIC_RENDERERS.get(payload["topic_type"])
    if renderer is None:
        raise RendererUnavailableError(f"No renderer registered for topic {payload['topic_type']}.")
    return renderer(payload)


__all__ = [
    "RendererUnavailableError",
    "render_topic_response",
]
