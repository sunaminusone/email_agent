from src.schemas.enums import ActionType, PrimaryIntent, RouteName


INTENT_TO_ROUTE = {
    PrimaryIntent.PRICING_QUESTION: RouteName.COMMERCIAL_AGENT,
    PrimaryIntent.DOCUMENTATION_REQUEST: RouteName.COMMERCIAL_AGENT,
    PrimaryIntent.PRODUCT_INQUIRY: RouteName.COMMERCIAL_AGENT,
    PrimaryIntent.ORDER_SUPPORT: RouteName.OPERATIONAL_AGENT,
    PrimaryIntent.SHIPPING_QUESTION: RouteName.OPERATIONAL_AGENT,
    PrimaryIntent.TECHNICAL_QUESTION: RouteName.COMMERCIAL_AGENT,
    PrimaryIntent.TROUBLESHOOTING: RouteName.COMMERCIAL_AGENT,
    PrimaryIntent.CUSTOMIZATION_REQUEST: RouteName.WORKFLOW_AGENT,
    PrimaryIntent.COMPLAINT: RouteName.COMPLAINT_REVIEW,
    PrimaryIntent.PARTNERSHIP_REQUEST: RouteName.PARTNERSHIP_REVIEW,
}


BLOCKING_ROUTES = {
    RouteName.HUMAN_REVIEW,
    RouteName.COMPLAINT_REVIEW,
    RouteName.CLARIFICATION_REQUEST,
}


ROUTE_DEFAULT_ACTIONS = {
    RouteName.CLARIFICATION_REQUEST: [
        {
            "action_id": "primary-clarify",
            "action_type": ActionType.CLARIFICATION_REQUEST,
            "title": "Collect missing details",
            "description": "Ask the user for the minimum missing details required to continue the workflow.",
            "metadata": {"include_missing_information": True},
        },
        {
            "action_id": "primary-draft",
            "action_type": ActionType.DRAFT_REPLY,
            "title": "Draft clarification message",
            "description": "Prepare the outward-facing clarification request for the user.",
            "depends_on": ["primary-clarify"],
        },
    ],
    RouteName.TECHNICAL_RAG: [
        {
            "action_id": "primary-tech-retrieval",
            "action_type": ActionType.RETRIEVE_TECHNICAL_KNOWLEDGE,
            "title": "Retrieve technical evidence",
            "description": "Search the technical knowledge base for the most relevant scientific support.",
        },
        {
            "action_id": "primary-draft",
            "action_type": ActionType.DRAFT_REPLY,
            "title": "Draft technical response",
            "description": "Prepare a technical response grounded in retrieved evidence.",
            "depends_on": ["primary-tech-retrieval"],
        },
    ],
    RouteName.COMMERCIAL_AGENT: [
        {
            "action_id": "primary-commercial-draft",
            "action_type": ActionType.DRAFT_REPLY,
            "title": "Draft commercial response",
            "description": "Prepare the commercial-domain response after running the selected supporting tools.",
        },
    ],
    RouteName.PRICING_LOOKUP: [
        {
            "action_id": "primary-price-lookup",
            "action_type": ActionType.LOOKUP_PRICE,
            "title": "Look up price and lead time",
            "description": "Match the product and retrieve price, availability, and timing details.",
        },
        {
            "action_id": "primary-draft",
            "action_type": ActionType.DRAFT_REPLY,
            "title": "Draft quote response",
            "description": "Prepare the commercial response using the retrieved quote details.",
            "depends_on": ["primary-price-lookup"],
        },
    ],
    RouteName.OPERATIONAL_AGENT: [
        {
            "action_id": "primary-operational-draft",
            "action_type": ActionType.DRAFT_REPLY,
            "title": "Draft operational response",
            "description": "Prepare the operational-domain response after running the selected supporting tools.",
        },
    ],
    RouteName.WORKFLOW_AGENT: [
        {
            "action_id": "primary-workflow-intake",
            "action_type": ActionType.PREPARE_CUSTOMIZATION_INTAKE,
            "title": "Prepare workflow intake",
            "description": "Summarize the workflow requirements and collect missing structured details.",
        },
        {
            "action_id": "primary-workflow-draft",
            "action_type": ActionType.DRAFT_REPLY,
            "title": "Draft workflow response",
            "description": "Prepare the workflow-domain response after processing the intake details.",
            "depends_on": ["primary-workflow-intake"],
        },
    ],
    RouteName.PRODUCT_LOOKUP: [
        {
            "action_id": "primary-product-lookup",
            "action_type": ActionType.LOOKUP_CATALOG_PRODUCT,
            "title": "Match catalog product",
            "description": "Find the best-fit standard catalog product from the unified catalog data.",
        },
        {
            "action_id": "primary-draft",
            "action_type": ActionType.DRAFT_REPLY,
            "title": "Draft product response",
            "description": "Prepare the response based on matched product information.",
            "depends_on": ["primary-product-lookup"],
        },
    ],
    RouteName.CUSTOMER_LOOKUP: [
        {
            "action_id": "primary-customer-lookup",
            "action_type": ActionType.LOOKUP_CUSTOMER,
            "title": "Look up customer or lead",
            "description": "Retrieve the customer or lead profile from QuickBooks using the provided name.",
        },
        {
            "action_id": "primary-draft",
            "action_type": ActionType.DRAFT_REPLY,
            "title": "Draft customer response",
            "description": "Prepare the response using the retrieved customer profile.",
            "depends_on": ["primary-customer-lookup"],
        },
    ],
    RouteName.INVOICE_LOOKUP: [
        {
            "action_id": "primary-invoice-lookup",
            "action_type": ActionType.LOOKUP_INVOICE,
            "title": "Look up invoice details",
            "description": "Retrieve invoice-specific billing details from QuickBooks using the provided invoice number or customer name.",
        },
        {
            "action_id": "primary-draft",
            "action_type": ActionType.DRAFT_REPLY,
            "title": "Draft invoice response",
            "description": "Prepare the response using the retrieved invoice details.",
            "depends_on": ["primary-invoice-lookup"],
        },
    ],
    RouteName.DOCUMENTATION_LOOKUP: [
        {
            "action_id": "primary-document-lookup",
            "action_type": ActionType.LOOKUP_DOCUMENT,
            "title": "Retrieve requested documents",
            "description": "Locate datasheets, protocols, COA, SDS, or related documentation.",
        },
        {
            "action_id": "primary-draft",
            "action_type": ActionType.DRAFT_REPLY,
            "title": "Draft document response",
            "description": "Prepare the response referencing the located documentation.",
            "depends_on": ["primary-document-lookup"],
        },
    ],
    RouteName.ORDER_SUPPORT: [
        {
            "action_id": "primary-order-lookup",
            "action_type": ActionType.LOOKUP_ORDER,
            "title": "Look up order details",
            "description": "Retrieve the operational details needed to answer the order-related request.",
        },
        {
            "action_id": "primary-draft",
            "action_type": ActionType.DRAFT_REPLY,
            "title": "Draft order response",
            "description": "Prepare the response using the operational order details.",
            "depends_on": ["primary-order-lookup"],
        },
    ],
    RouteName.SHIPPING_SUPPORT: [
        {
            "action_id": "primary-shipping-lookup",
            "action_type": ActionType.LOOKUP_SHIPPING,
            "title": "Look up shipping constraints",
            "description": "Retrieve destination-specific shipping constraints, ETA, or logistics details.",
        },
        {
            "action_id": "primary-draft",
            "action_type": ActionType.DRAFT_REPLY,
            "title": "Draft shipping response",
            "description": "Prepare the shipping-focused response using the logistics details.",
            "depends_on": ["primary-shipping-lookup"],
        },
    ],
    RouteName.COMPLAINT_REVIEW: [
        {
            "action_id": "primary-summary",
            "action_type": ActionType.SUMMARIZE_CASE,
            "title": "Summarize case for review",
            "description": "Prepare a concise internal summary of the complaint or risky request.",
        },
        {
            "action_id": "primary-escalate",
            "action_type": ActionType.ESCALATE_TO_HUMAN,
            "title": "Escalate to human reviewer",
            "description": "Route the case to manual review before any further automated handling.",
            "depends_on": ["primary-summary"],
        },
        {
            "action_id": "primary-internal-draft",
            "action_type": ActionType.DRAFT_INTERNAL_SUMMARY,
            "title": "Draft internal note",
            "description": "Prepare an internal review note rather than an immediate customer-facing reply.",
            "depends_on": ["primary-escalate"],
        },
    ],
    RouteName.HUMAN_REVIEW: [
        {
            "action_id": "primary-summary",
            "action_type": ActionType.SUMMARIZE_CASE,
            "title": "Summarize case for review",
            "description": "Prepare a concise internal summary of the risky request.",
        },
        {
            "action_id": "primary-escalate",
            "action_type": ActionType.ESCALATE_TO_HUMAN,
            "title": "Escalate to human reviewer",
            "description": "Route the case to manual review before any further automated handling.",
            "depends_on": ["primary-summary"],
        },
    ],
    RouteName.PARTNERSHIP_REVIEW: [
        {
            "action_id": "primary-summary",
            "action_type": ActionType.SUMMARIZE_CASE,
            "title": "Summarize partnership request",
            "description": "Prepare an internal summary for business review.",
        },
        {
            "action_id": "primary-escalate",
            "action_type": ActionType.ESCALATE_TO_HUMAN,
            "title": "Escalate to business owner",
            "description": "Route the partnership inquiry to the responsible business owner.",
            "depends_on": ["primary-summary"],
        },
    ],
}
