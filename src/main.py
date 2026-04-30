import os
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from langchain_core.runnables import RunnableLambda # 把普通Python函数包装成 LangChain runnable
from langserve import add_routes # 自动生成 API（不用自己写 /chat）

from src.app.service import run_email_agent
from src.api_models import AgentPrototypeResponse, AgentRequest
from src.conversations import ConversationStore
from src.integrations import QuickBooksClient, QuickBooksConfigError

BASE_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = BASE_DIR / "frontend"

app = FastAPI(
    title="Email Agent Prototype",
    version="0.1.0",
    description="A LangServe-powered prototype for parsing email requests and preparing agent input.",
)


class RenameConversationPayload(BaseModel):
    title: str


# Module-level singleton — keeps _has_documents_table cache warm across requests.
# Recreated on process restart, which is fine for a CSR sidecar.
conversation_store = ConversationStore()


def require_csr_auth(authorization: str | None = Header(default=None)) -> None:
    """Bearer-token gate for /api/conversations/*.

    If CSR_API_TOKEN is unset (dev mode), the gate is open. In any environment
    that exports the var, requests must carry `Authorization: Bearer <token>`.
    """
    expected = os.getenv("CSR_API_TOKEN", "").strip()
    if not expected:
        return
    prefix = "Bearer "
    if not authorization or not authorization.startswith(prefix):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    if authorization[len(prefix):].strip() != expected:
        raise HTTPException(status_code=403, detail="Invalid bearer token")


email_agent_runnable = RunnableLambda(run_email_agent).with_types(
    input_type=AgentRequest,
    output_type=AgentPrototypeResponse,
)

add_routes(
    app,
    email_agent_runnable,
    path="/email-agent",
)

if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


@app.get("/", include_in_schema=False)
async def serve_frontend() -> HTMLResponse:
    index_path = FRONTEND_DIR / "index.html"
    asset_paths = [
        FRONTEND_DIR / "styles.css",
        FRONTEND_DIR / "app.js",
        index_path,
    ]
    asset_version = str(
        max(int(path.stat().st_mtime) for path in asset_paths if path.exists())
    )
    html = index_path.read_text(encoding="utf-8").replace("__ASSET_VERSION__", asset_version)
    return HTMLResponse(content=html)


@app.get("/health", tags=["system"])
async def health_check() -> dict:
    return {"status": "ok"}


@app.get("/api/conversations", tags=["conversations"])
async def list_conversations(
    limit: int = Query(default=100, ge=1, le=500),
    _auth: None = Depends(require_csr_auth),
) -> dict:
    return {"threads": conversation_store.list_threads(limit=limit)}


@app.get("/api/conversations/{thread_key}", tags=["conversations"])
async def get_conversation(
    thread_key: str,
    _auth: None = Depends(require_csr_auth),
) -> dict:
    return {"thread_id": thread_key, "messages": conversation_store.get_thread_messages(thread_key)}


@app.delete("/api/conversations/{thread_key}", tags=["conversations"])
async def delete_conversation(
    thread_key: str,
    _auth: None = Depends(require_csr_auth),
) -> dict:
    deleted = conversation_store.delete_thread(thread_key)
    if not deleted:
        raise HTTPException(status_code=404, detail="Thread not found")
    return {"thread_id": thread_key, "deleted": True}


@app.patch("/api/conversations/{thread_key}", tags=["conversations"])
async def rename_conversation(
    thread_key: str,
    payload: RenameConversationPayload,
    _auth: None = Depends(require_csr_auth),
) -> dict:
    renamed = conversation_store.rename_thread(thread_key, payload.title)
    if not renamed:
        raise HTTPException(status_code=404, detail="Thread not found")
    return {"thread_id": thread_key, "renamed": True, "title": payload.title}


@app.get("/qb/status", tags=["quickbooks"])
async def quickbooks_status() -> dict:
    client = QuickBooksClient()
    return client.get_connection_status()


@app.get("/qb/connect", tags=["quickbooks"])
async def quickbooks_connect() -> RedirectResponse:
    client = QuickBooksClient()
    try:
        auth = client.build_authorization_url()
    except QuickBooksConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return RedirectResponse(url=auth["authorization_url"])


@app.get("/qb/callback", tags=["quickbooks"])
async def quickbooks_callback(
    code: str = Query(...),
    realmId: str = Query(...),
    state: str | None = Query(default=None),
) -> dict:
    client = QuickBooksClient()
    try:
        token_data = client.exchange_code(code=code, realm_id=realmId)
    except QuickBooksConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"QuickBooks token exchange failed: {exc}") from exc

    return {
        "connected": True,
        "realm_id": token_data["realm_id"],
        "environment": client.get_connection_status()["environment"],
        "state": state,
    }
