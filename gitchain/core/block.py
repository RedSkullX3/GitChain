
import hashlib
import json
import time
from dataclasses import dataclass, field, asdict
from typing import List, TYPE_CHECKING

if TYPE_CHECKING:
    from gitchain.core.transaction import Transaction


@dataclass
class Block:
    index: int
    timestamp: float
    transactions: List[dict]       # serialized Transaction dicts
    previous_hash: str
    nonce: int = 0
    hash: str = ""

    def calculate_hash(self) -> str:
        #SHA-256 of all block fields in JSON order.
        block_data = {
            "index": self.index,
            "timestamp": self.timestamp,
            "transactions": self.transactions,
            "previous_hash": self.previous_hash,
            "nonce": self.nonce,
        }
        raw = json.dumps(block_data, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode()).hexdigest()

    def seal(self) -> None:
        
        self.hash = self.calculate_hash()

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "timestamp": self.timestamp,
            "transactions": self.transactions,
            "previous_hash": self.previous_hash,
            "nonce": self.nonce,
            "hash": self.hash,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Block":
        return cls(
            index=data["index"],
            timestamp=data["timestamp"],
            transactions=data["transactions"],
            previous_hash=data["previous_hash"],
            nonce=data["nonce"],
            hash=data["hash"],
        )


def create_genesis_block() -> Block:
    
    genesis = Block(
        index=0,
        timestamp=0.0,
        transactions=[],
        previous_hash="0" * 64,
        nonce=0,
    )
    genesis.seal()
    return genesis
