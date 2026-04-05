from langchain_core.runnables import RunnableLambda, RunnablePassthrough

from src.config.settings import get_llm
from src.parser.prompt import get_parser_prompt
from src.parser.postprocess import postprocess_parsed_result
from src.parser.preprocess import preprocess_parser_input
from src.schemas import ParsedResult


def _postprocess_payload(payload: dict) -> ParsedResult:
    meta = payload.get("_meta") or {}
    parsed = payload["parsed"]
    return postprocess_parsed_result(
        parsed,
        user_query=meta.get("raw_user_query", ""),
        conversation_history=meta.get("conversation_history_raw", []),
        attachments=meta.get("attachments_raw", []),
    )


def build_parser_pipeline():
    llm = get_llm()
    structured_llm = llm.with_structured_output(ParsedResult)
    parser_prompt = get_parser_prompt()
    parser_chain = parser_prompt | structured_llm

    preprocess = RunnableLambda(preprocess_parser_input)
    parse_step = RunnablePassthrough.assign(parsed=parser_chain)
    postprocess = RunnableLambda(_postprocess_payload)
    return preprocess | parse_step | postprocess


def build_parser_chain():
    return build_parser_pipeline()
