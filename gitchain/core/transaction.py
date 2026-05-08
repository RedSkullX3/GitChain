import hashlib
import json
from dataclasses import dataclass
from typing import Optional


@dataclass
class Transaction:
    commit_hash: str        # git SHA (40-char hex)
    owner_pubkey: str       # CI bot's Ed25519 public key (hex); verifies the signature
    author: str             # GitHub username of the developer who pushed
    repo: str               # org/repo
    branch: str             # e.g. main
    timestamp: float        # unix time of the commit
    diff_summary: str       # "3 files changed, +120 -40"
    diff_hash: str          # SHA-256 of full git diff (git show -p HEAD); proves exact line changes
    payload_hash: str       # SHA-256 of the above fields
    signature: str          # Ed25519 signature of payload_hash (hex)

    def compute_payload_hash(self) -> str:
        
        payload = {
            "author": self.author,
            "branch": self.branch,
            "commit_hash": self.commit_hash,
            "diff_hash": self.diff_hash,
            "diff_summary": self.diff_summary,
            "owner_pubkey": self.owner_pubkey,
            "repo": self.repo,
            # Serialize as int so Python (float) matches JS (Math.floor → int).
            # Git timestamps are always whole seconds; fractional precision is never needed.
            "timestamp": int(self.timestamp),
        }
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode()).hexdigest()

    def is_payload_hash_valid(self) -> bool:
        
        return self.payload_hash == self.compute_payload_hash()

    def verify_signature(self) -> bool:
        
        try:
            import nacl.signing
            import nacl.encoding
            import nacl.exceptions

            if not self.is_payload_hash_valid():
                return False

            vk = nacl.signing.VerifyKey(
                self.owner_pubkey,
                encoder=nacl.encoding.HexEncoder,
            )
            vk.verify(
                self.payload_hash.encode(),
                bytes.fromhex(self.signature),
            )
            return True
        except (nacl.exceptions.BadSignatureError, Exception):
            return False

    def to_dict(self) -> dict:
        return {
            "commit_hash": self.commit_hash,
            "owner_pubkey": self.owner_pubkey,
            "author": self.author,
            "repo": self.repo,
            "branch": self.branch,
            "timestamp": self.timestamp,
            "diff_summary": self.diff_summary,
            "diff_hash": self.diff_hash,
            "payload_hash": self.payload_hash,
            "signature": self.signature,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Transaction":
        return cls(
            commit_hash=data["commit_hash"],
            owner_pubkey=data["owner_pubkey"],
            author=data.get("author", "unknown"),
            repo=data["repo"],
            branch=data["branch"],
            timestamp=data["timestamp"],
            diff_summary=data["diff_summary"],
            diff_hash=data.get("diff_hash", ""),    # .get() for chain data predating this field
            payload_hash=data["payload_hash"],
            signature=data["signature"],
        )
