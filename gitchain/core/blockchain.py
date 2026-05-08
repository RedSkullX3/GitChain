"""
Blockchain — chain management, validation, and Nakamoto consensus.

Every GitChain node holds a full copy of the chain in memory (and persists
it to disk). This file contains:

  - Blockchain class: append, validate, persist, load
  - validate_block()  — single block integrity check
  - validate_chain()  — full chain from genesis
  - resolve_conflict() — longest-chain rule (Nakamoto consensus)
"""

import json
import threading
from pathlib import Path
from typing import List, Optional, Tuple

from gitchain.core.block import Block, create_genesis_block
from gitchain.core.miner import meets_difficulty
from gitchain.core.transaction import Transaction


def validate_block(block: Block, previous_block: Block, difficulty: int) -> Tuple[bool, str]:
    
    if block.index != previous_block.index + 1:
        return False, f"index mismatch: expected {previous_block.index + 1}, got {block.index}"

    if block.previous_hash != previous_block.hash:
        return False, (
            f"previous_hash mismatch: block claims {block.previous_hash!r}, "
            f"actual previous hash {previous_block.hash!r}"
        )

    computed = block.calculate_hash()
    if block.hash != computed:
        return False, f"hash tampered: stored {block.hash!r} != computed {computed!r}"

    if not meets_difficulty(block.hash, difficulty):
        return False, f"PoW not met: hash {block.hash!r} does not start with {'0'*difficulty!r}"

    return True, "ok"


def validate_chain(chain: List[Block], difficulty: int) -> Tuple[bool, str]:
    
    if not chain:
        return False, "empty chain"

    # Validate genesis
    genesis = chain[0]
    if genesis.previous_hash != "0" * 64:
        return False, "genesis block has wrong previous_hash"
    if genesis.hash != genesis.calculate_hash():
        return False, "genesis block hash is invalid"

    for i in range(1, len(chain)):
        ok, reason = validate_block(chain[i], chain[i - 1], difficulty)
        if not ok:
            return False, f"block {i}: {reason}"

    return True, "ok"


def resolve_conflict(chain_a: List[Block], chain_b: List[Block], difficulty: int) -> List[Block]:
    
    a_valid, _ = validate_chain(chain_a, difficulty)
    b_valid, _ = validate_chain(chain_b, difficulty)

    if b_valid and len(chain_b) > len(chain_a):
        return chain_b
    if a_valid:
        return chain_a
    if b_valid:
        return chain_b
    # Both invalid — return empty; caller should re-sync from scratch
    return []


class Blockchain:
    

    def __init__(self, difficulty: int = 3, data_path: str = "chain.json"):
        self.difficulty = difficulty
        self.data_path = Path(data_path)
        self._lock = threading.RLock()
        self._chain: List[Block] = []

        if self.data_path.exists():
            self._load()
        else:
            self._chain = [create_genesis_block()]
            self._save()

    @property
    def chain(self) -> List[Block]:
        with self._lock:
            return list(self._chain)

    @property
    def tip(self) -> Block:
        with self._lock:
            return self._chain[-1]

    def height(self) -> int:
        with self._lock:
            return len(self._chain)

    def get_block(self, index: int) -> Optional[Block]:
        with self._lock:
            if 0 <= index < len(self._chain):
                return self._chain[index]
            return None

    def has_transaction(self, commit_hash: str) -> Optional[dict]:
        
        with self._lock:
            for block in self._chain:
                for tx in block.transactions:
                    if tx.get("commit_hash") == commit_hash:
                        return {**tx, "_block_index": block.index}
        return None

    def get_transactions_by_author(self, owner_pubkey: str) -> List[dict]:
        result = []
        with self._lock:
            for block in self._chain:
                for tx in block.transactions:
                    if tx.get("owner_pubkey") == owner_pubkey:
                        result.append({**tx, "_block_index": block.index})
        return result

    def get_transactions_by_repo(self, repo: str) -> List[dict]:
        result = []
        with self._lock:
            for block in self._chain:
                for tx in block.transactions:
                    if tx.get("repo") == repo:
                        result.append({**tx, "_block_index": block.index})
        return result



    def append_block(self, block: Block) -> Tuple[bool, str]:
        
        with self._lock:
            ok, reason = validate_block(block, self._chain[-1], self.difficulty)
            if not ok:
                return False, reason
            self._chain.append(block)
            self._save()
            return True, "ok"

    def replace_chain(self, new_chain: List[Block]) -> Tuple[bool, str]:
        
        with self._lock:
            resolved = resolve_conflict(self._chain, new_chain, self.difficulty)
            if resolved is self._chain or resolved == self._chain:
                return False, "local chain is already longest"
            self._chain = resolved
            self._save()
            return True, "chain replaced"


    def to_dict_list(self) -> List[dict]:
        with self._lock:
            return [b.to_dict() for b in self._chain]

    def _save(self) -> None:
        self.data_path.write_text(
            json.dumps([b.to_dict() for b in self._chain], indent=2)
        )

    def _load(self) -> None:
        raw = json.loads(self.data_path.read_text())
        self._chain = [Block.from_dict(b) for b in raw]
