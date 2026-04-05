from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from langchain_core.runnables import RunnableLambda # 把普通Python函数包装成 LangChain runnable
from langserve import add_routes # 自动生成 API（不用自己写 /chat）

from src.integrations import QuickBooksClient, QuickBooksConfigError
from src.schemas.chat_schema import AgentPrototypeResponse, AgentRequest
from src.orchestration.prototype_service import run_email_agent
from src.documents.service import DOCUMENT_ROOT

BASE_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = BASE_DIR / "frontend"

app = FastAPI(
    title="Email Agent Prototype",
    version="0.1.0",
    description="A LangServe-powered prototype for parsing email requests and preparing agent input.",
)

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
if DOCUMENT_ROOT.exists():
    app.mount("/documents", StaticFiles(directory=DOCUMENT_ROOT), name="documents")


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
