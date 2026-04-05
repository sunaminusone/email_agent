from enum import Enum


class StrEnum(str, Enum):
    pass


class PrimaryIntent(StrEnum):
    PRODUCT_INQUIRY = "product_inquiry"
    TECHNICAL_QUESTION = "technical_question"
    PRICING_QUESTION = "pricing_question"
    TIMELINE_QUESTION = "timeline_question"
    CUSTOMIZATION_REQUEST = "customization_request"
    DOCUMENTATION_REQUEST = "documentation_request"
    SHIPPING_QUESTION = "shipping_question"
    TROUBLESHOOTING = "troubleshooting"
    ORDER_SUPPORT = "order_support"
    COMPLAINT = "complaint"
    FOLLOW_UP = "follow_up"
    PARTNERSHIP_REQUEST = "partnership_request"
    GENERAL_INFO = "general_info"
    UNKNOWN = "unknown"


class LanguageType(StrEnum):
    ZH = "zh"
    EN = "en"
    OTHER = "other"


class ChannelType(StrEnum):
    INTERNAL_QA = "internal_qa"
    EMAIL = "email"
    CHAT = "chat"
    UNKNOWN = "unknown"


class QueryType(StrEnum):
    QUESTION = "question"
    REQUEST = "request"
    UNCLEAR = "unclear"


class UrgencyType(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class RiskLevelType(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class RouteName(StrEnum):
    CLARIFICATION_REQUEST = "clarification_request"
    COMMERCIAL_AGENT = "commercial_agent"
    OPERATIONAL_AGENT = "operational_agent"
    WORKFLOW_AGENT = "workflow_agent"
    PRICING_LOOKUP = "pricing_lookup"
    PRODUCT_LOOKUP = "product_lookup"
    CUSTOMER_LOOKUP = "customer_lookup"
    TECHNICAL_RAG = "technical_rag"
    DOCUMENTATION_LOOKUP = "documentation_lookup"
    INVOICE_LOOKUP = "invoice_lookup"
    SHIPPING_SUPPORT = "shipping_support"
    ORDER_SUPPORT = "order_support"
    COMPLAINT_REVIEW = "complaint_review"
    PARTNERSHIP_REVIEW = "partnership_review"
    GENERAL_RESPONSE = "general_response"
    HUMAN_REVIEW = "human_review"


class BusinessLine(StrEnum):
    CAR_T = "car_t"
    MRNA_LNP = "mrna_lnp"
    ANTIBODY = "antibody"
    CROSS_LINE = "cross_line"
    UNKNOWN = "unknown"


class EngagementType(StrEnum):
    CATALOG_PRODUCT = "catalog_product"
    CUSTOM_SERVICE = "custom_service"
    PLATFORM_SERVICE = "platform_service"
    GENERAL_INQUIRY = "general_inquiry"
    UNKNOWN = "unknown"


class RoutePhase(StrEnum):
    NEW_REQUEST = "new_request"
    WAITING_FOR_USER = "waiting_for_user"
    READY_TO_RESUME = "ready_to_resume"
    ACTIVE = "active"
    RESOLVED = "resolved"
    UNKNOWN = "unknown"


class ContinuityMode(StrEnum):
    FRESH_REQUEST = "fresh_request"
    ROUTE_CONTINUATION = "route_continuation"
    CLARIFICATION_REPLY = "clarification_reply"
    FOLLOW_UP = "follow_up"
    UNKNOWN = "unknown"


class ActionType(StrEnum):
    CLARIFICATION_REQUEST = "clarification_request"
    RETRIEVE_TECHNICAL_KNOWLEDGE = "retrieve_technical_knowledge"
    LOOKUP_CATALOG_PRODUCT = "lookup_catalog_product"
    LOOKUP_PRICE = "lookup_price"
    LOOKUP_CUSTOMER = "lookup_customer"
    LOOKUP_DOCUMENT = "lookup_document"
    LOOKUP_INVOICE = "lookup_invoice"
    LOOKUP_ORDER = "lookup_order"
    LOOKUP_SHIPPING = "lookup_shipping"
    PREPARE_CUSTOMIZATION_INTAKE = "prepare_customization_intake"
    ESCALATE_TO_HUMAN = "escalate_to_human"
    SUMMARIZE_CASE = "summarize_case"
    DRAFT_REPLY = "draft_reply"
    DRAFT_INTERNAL_SUMMARY = "draft_internal_summary"
    RECORD_SECONDARY_FOLLOWUP = "record_secondary_followup"


class ActionMode(StrEnum):
    PRIMARY = "primary"
    SECONDARY = "secondary"
