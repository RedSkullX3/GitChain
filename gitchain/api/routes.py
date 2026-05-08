"""
GitChain REST API routes.

All endpoints are read-only except POST /transaction (used by the GitHub Action).

Endpoints:
  GET  /status                      — node status (height, peers, mempool)
  GET  /chain                       — full chain as JSON
  GET  /block/:index                — single block by index
  GET  /contributions/:author       — all txs for a developer (by pubkey hex)
  GET  /contributions/repo/:repo    — all txs for a repository
  GET  /verify/:commit_hash         — is this commit on-chain?
  GET  /mempool                     — pending transactions
  POST /transaction                 — submit a new signed transaction (GitHub Action)
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from gitchain.api.server import get_node
from gitchain.core.transaction import Transaction

router = APIRouter()


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class TransactionRequest(BaseModel):
    commit_hash: str
    owner_pubkey: str
    author: str = "unknown"   # optional for backward compat with older Action scripts
    repo: str
    branch: str
    timestamp: float
    diff_summary: str
    diff_hash: str = ""       # optional for backward compat; SHA-256 of full git diff
    payload_hash: str
    signature: str


class VerifyResponse(BaseModel):
    commit_hash: str
    on_chain: bool
    block_index: int | None = None
    transaction: dict | None = None
    message: str


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/status")
def status(node=Depends(get_node)):
    return node.status()


@router.get("/chain")
def get_chain(node=Depends(get_node)):
    """Return the full blockchain as a JSON list of blocks."""
    chain = node.blockchain.to_dict_list()
    # Ensure all transactions have author — old blocks predating this field default to "unknown"
    for block in chain:
        for tx in block.get("transactions", []):
            tx.setdefault("author", "unknown")
    return chain


@router.get("/block/{index}")
def get_block(index: int, node=Depends(get_node)):
    block = node.blockchain.get_block(index)
    if block is None:
        raise HTTPException(status_code=404, detail=f"Block {index} not found")
    return block.to_dict()


@router.get("/contributions/{owner_pubkey}")
def contributions_by_author(owner_pubkey: str, node=Depends(get_node)):
    """
    Return all on-chain transactions for a given developer public key.
    Each entry includes _block_index for dashboard block-explorer links.
    """
    txs = node.blockchain.get_transactions_by_author(owner_pubkey)
    return {"owner_pubkey": owner_pubkey, "count": len(txs), "transactions": txs}


@router.get("/contributions/repo/{org}/{repo}")
def contributions_by_repo(org: str, repo: str, node=Depends(get_node)):
    """Return all on-chain transactions for a repository (org/repo)."""
    full_repo = f"{org}/{repo}"
    txs = node.blockchain.get_transactions_by_repo(full_repo)
    return {"repo": full_repo, "count": len(txs), "transactions": txs}


@router.get("/verify/{commit_hash}", response_model=VerifyResponse)
def verify_commit(commit_hash: str, node=Depends(get_node)):
    """
    Check whether a git commit SHA is permanently recorded on-chain.

    Used by:
      
      - The CLI `gitchain verify <sha>` command
      - External auditors
    """
    tx = node.blockchain.has_transaction(commit_hash)
    if tx is None:
        return VerifyResponse(
            commit_hash=commit_hash,
            on_chain=False,
            message="Commit not found on-chain — may have been force-pushed or never submitted",
        )
    return VerifyResponse(
        commit_hash=commit_hash,
        on_chain=True,
        block_index=tx.get("_block_index"),
        transaction=tx,
        message="Commit is permanently recorded on-chain",
    )




@router.get("/mempool")
def get_mempool(node=Depends(get_node)):
    """Return all pending (unconfirmed) transactions."""
    return {
        "size": node.mempool.size(),
        "transactions": node.mempool.all_transactions(),
    }


@router.post("/transaction", status_code=201)
async def submit_transaction(req: TransactionRequest, node=Depends(get_node)):
    """
    Accept a signed transaction from the GitHub Action.

    The signature is verified before the transaction enters the mempool.
    Permissionless: any valid Ed25519 signature is accepted regardless of
    whether the pubkey is in gitchain-registry.json.
    """
    tx = Transaction(
        commit_hash=req.commit_hash,
        owner_pubkey=req.owner_pubkey,
        author=req.author,
        repo=req.repo,
        branch=req.branch,
        timestamp=req.timestamp,
        diff_summary=req.diff_summary,
        diff_hash=req.diff_hash,
        payload_hash=req.payload_hash,
        signature=req.signature,
    )

    # Reject if payload hash doesn't match fields (tampered in transit)
    if not tx.is_payload_hash_valid():
        raise HTTPException(status_code=400, detail="payload_hash does not match transaction fields")

    # Reject duplicates before touching the mempool
    if node.blockchain.has_transaction(req.commit_hash) or node.mempool.contains(req.commit_hash):
        raise HTTPException(status_code=409, detail="Transaction already recorded")

    accepted = await node.submit_transaction(tx)

    if not accepted:
        raise HTTPException(status_code=400, detail="Transaction rejected — invalid signature")

    return {"status": "accepted", "commit_hash": req.commit_hash}
