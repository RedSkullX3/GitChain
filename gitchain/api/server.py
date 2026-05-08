"""
GitChain REST API server.

Runs alongside the node daemon. Exposes the chain and mempool for:
  - The dashboard (read-only queries)
  - The GitHub Action (POST /transaction)
  - The CLI verify command
  - External auditors (read full chain as JSON)

The FastAPI app is created here; routes are registered in routes.py.
The node instance is injected at startup so routes can read the live chain.
"""

import logging
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path

log = logging.getLogger(__name__)

app = FastAPI(
    title="GitChain Node API",
    description="Decentralized contribution verifier — REST interface",
    version="1.0.0",
)

# Allow any origin so the plain-HTML dashboard can query from file:// or any port
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# Node is injected here at startup by the CLI / node daemon
_node = None


def set_node(node) -> None:
    """Inject the running GitChainNode into the API."""
    global _node
    _node = node


def get_node():
    """Dependency: retrieve the injected node (raises if not set)."""
    if _node is None:
        raise RuntimeError("Node not initialised — call set_node() before serving")
    return _node


def create_app(node) -> FastAPI:
    """
    Wire up the app with a live node instance and register all routes.
    Call this once at startup.
    """
    set_node(node)

    from gitchain.api import routes  # noqa: F401 — registers routes on import
    app.include_router(routes.router)

    # Serve the dashboard from the dashboard/ directory
    dashboard_path = Path(__file__).parent.parent / "dashboard"
    if dashboard_path.exists():
        app.mount("/dashboard", StaticFiles(directory=str(dashboard_path), html=True), name="dashboard")

    return app


def run(node, host: str = "0.0.0.0", api_port: int = 8000) -> None:
    """Start the uvicorn server (blocking). Called from the node daemon."""
    application = create_app(node)
    uvicorn.run(application, host=host, port=api_port, log_level="warning")
