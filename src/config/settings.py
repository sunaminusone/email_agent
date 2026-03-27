# src/config/settings.py
import os
from pathlib import Path
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

# 找 .env
BASE_DIR = Path(__file__).resolve().parent.parent.parent

env_path = BASE_DIR / ".env"
load_dotenv(env_path)

# API KEY
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# LLM
def get_llm() -> ChatOpenAI:
    if not OPENAI_API_KEY:
        raise ValueError("OPENAI_API_KEY is not set in .env")

    return ChatOpenAI(
        model="gpt-4o-mini",
        temperature=0,
        api_key=OPENAI_API_KEY,
    )