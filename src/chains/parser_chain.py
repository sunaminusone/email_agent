from src.config.settings import get_llm
from src.prompts import get_parser_prompt
from src.schemas import ParsedResult

def build_parser_chain():
    llm = get_llm()
    structured_llm = llm.with_structured_output(ParsedResult)
    parser_prompt = get_parser_prompt()
    parser_chain = parser_prompt | structured_llm
    return parser_chain