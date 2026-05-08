
import time
from typing import List, Optional, Callable

from gitchain.core.block import Block


def mine_block(
    transactions: List[dict],
    previous_hash: str,
    index: int,
    difficulty: int = 3,
    stop_flag: Optional[Callable[[], bool]] = None,
) -> Block:
    
    target = "0" * difficulty
    timestamp = time.time()

    block = Block(
        index=index,
        timestamp=timestamp,
        transactions=transactions,
        previous_hash=previous_hash,
        nonce=0,
    )

    while True:
        if stop_flag and stop_flag():
            return None

        block.hash = block.calculate_hash()
        if block.hash.startswith(target):
            return block

        block.nonce += 1


def meets_difficulty(hash_str: str, difficulty: int) -> bool:
    """Check whether a given hash satisfies the PoW difficulty target."""
    return hash_str.startswith("0" * difficulty)
