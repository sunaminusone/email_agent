# src/config/settings.py
import os
from pathlib import Path
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI, OpenAIEmbeddings

# 找 .env
BASE_DIR = Path(__file__).resolve().parent.parent.parent

env_path = BASE_DIR / ".env"
load_dotenv(env_path)

# API KEY
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# QuickBooks
QB_CLIENT_ID = os.getenv("QB_CLIENT_ID")
QB_CLIENT_SECRET = os.getenv("QB_CLIENT_SECRET")
QB_REDIRECT_URI = os.getenv("QB_REDIRECT_URI") or os.getenv("QB_REDIRECT_URL")
QB_ENVIRONMENT = (os.getenv("QB_ENVIRONMENT") or os.getenv("environment") or "sandbox").strip().lower()
QB_SCOPE = os.getenv("QB_SCOPE", "com.intuit.quickbooks.accounting")
QB_TOKEN_STORE = os.getenv("QB_TOKEN_STORE", str(BASE_DIR / "data" / "quickbooks_tokens.json"))

# Redis session memory
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = os.getenv("REDIS_PORT", "6379")
REDIS_DB = os.getenv("REDIS_DB", "0")
REDIS_URL = os.getenv("REDIS_URL", "")
MEMORY_TTL_SECONDS = os.getenv("MEMORY_TTL_SECONDS", "7200")
MEMORY_MAX_TURNS = os.getenv("MEMORY_MAX_TURNS", "10")
MEMORY_KEY_PREFIX = os.getenv("MEMORY_KEY_PREFIX", "email_agent:session")

# PostgreSQL catalog
DATABASE_URL = os.getenv("DATABASE_URL")
PGHOST = os.getenv("PGHOST", "localhost")
PGPORT = os.getenv("PGPORT", "5432")
PGUSER = os.getenv("PGUSER", "postgres")
PGPASSWORD = os.getenv("PGPASSWORD", "")
PGDATABASE = os.getenv("PGDATABASE", "promab")

# LLM
def get_llm() -> ChatOpenAI:
    if not OPENAI_API_KEY:
        raise ValueError("OPENAI_API_KEY is not set in .env")

    return ChatOpenAI(
        model="gpt-4o-mini",
        temperature=0,
        api_key=OPENAI_API_KEY,
    )


def get_vision_llm() -> ChatOpenAI:
    if not OPENAI_API_KEY:
        raise ValueError("OPENAI_API_KEY is not set in .env")

    return ChatOpenAI(
        model="gpt-4o-mini",
        temperature=0,
        api_key=OPENAI_API_KEY,
    )


def get_embeddings() -> OpenAIEmbeddings:
    if not OPENAI_API_KEY:
        raise ValueError("OPENAI_API_KEY is not set in .env")

    return OpenAIEmbeddings(
        model="text-embedding-3-small",
        api_key=OPENAI_API_KEY,
    )


def get_quickbooks_settings() -> dict:
    return {
        "client_id": QB_CLIENT_ID,
        "client_secret": QB_CLIENT_SECRET,
        "redirect_uri": QB_REDIRECT_URI,
        "environment": QB_ENVIRONMENT,
        "scope": QB_SCOPE,
        "token_store": QB_TOKEN_STORE,
        "is_configured": all([QB_CLIENT_ID, QB_CLIENT_SECRET, QB_REDIRECT_URI]),
    }


def get_catalog_db_settings() -> dict:
    return {
        "database_url": DATABASE_URL,
        "host": PGHOST,
        "port": PGPORT,
        "user": PGUSER,
        "password": PGPASSWORD,
        "database": PGDATABASE,
        "is_configured": bool(DATABASE_URL or PGDATABASE),
    }


def get_memory_settings() -> dict:
    redis_url = REDIS_URL or f"redis://{REDIS_HOST}:{REDIS_PORT}/{REDIS_DB}"
    return {
        "redis_host": REDIS_HOST,
        "redis_port": int(REDIS_PORT),
        "redis_db": int(REDIS_DB),
        "redis_url": redis_url,
        "ttl_seconds": int(MEMORY_TTL_SECONDS),
        "max_turns": int(MEMORY_MAX_TURNS),
        "key_prefix": MEMORY_KEY_PREFIX,
        "is_configured": bool(redis_url),
    }
