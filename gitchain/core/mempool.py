import threading
from typing import List, Dict, Optional

from gitchain.core.transaction import Transaction


class Mempool:
    def __init__(self, max_size: int = 1000):
        self._pool: Dict[str, dict] = {}   # commit_hash → tx dict
        self._lock = threading.Lock()
        self.max_size = max_size

    def add(self, tx: Transaction, verify: bool = True) -> bool:
        
        with self._lock:
            if tx.commit_hash in self._pool:
                return False  # duplicate

            if len(self._pool) >= self.max_size:
                return False  # full

            if verify and not tx.verify_signature():
                return False  # bad signature — permissionless but not trustless

            self._pool[tx.commit_hash] = tx.to_dict()
            return True

    def get_pending(self, limit: int = 10) -> List[dict]:
        
        with self._lock:
            return list(self._pool.values())[:limit]

    def remove(self, commit_hashes: List[str]) -> None:
        
        with self._lock:
            for h in commit_hashes:
                self._pool.pop(h, None)

    def contains(self, commit_hash: str) -> bool:
        with self._lock:
            return commit_hash in self._pool

    def size(self) -> int:
        with self._lock:
            return len(self._pool)

    def clear(self) -> None:
        with self._lock:
            self._pool.clear()

    def all_transactions(self) -> List[dict]:
        with self._lock:
            return list(self._pool.values())
