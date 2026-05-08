"""
Keypair generation for GitChain contributors.

Each developer runs this once to produce:
  - A private key (hex) → stored in GitHub Secrets as GITCHAIN_PRIVATE_KEY
  - A public key (hex)  → added to gitchain-registry.json in the repo

Ed25519 via PyNaCl: fast, small keys (32 bytes each), battle-tested.
"""

import json
import os
from pathlib import Path
from typing import Tuple

import nacl.signing
import nacl.encoding


def generate_keypair() -> Tuple[str, str]:
    """
    Generate a new Ed25519 keypair.

    Returns:
        (private_key_hex, public_key_hex)
    """
    signing_key = nacl.signing.SigningKey.generate()
    verify_key = signing_key.verify_key

    private_hex = signing_key.encode(encoder=nacl.encoding.HexEncoder).decode()
    public_hex = verify_key.encode(encoder=nacl.encoding.HexEncoder).decode()

    return private_hex, public_hex


def save_keypair(
    name: str,
    email: str,
    output_dir: str = ".",
) -> Tuple[str, str]:
    """
    Generate and persist a keypair to disk.

    Writes:
      <output_dir>/<email>.private.key  — private key (hex), keep secret
      <output_dir>/<email>.public.key   — public key (hex), safe to share

    Returns:
        (private_key_hex, public_key_hex)
    """
    private_hex, public_hex = generate_keypair()

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    private_path = out / f"{email}.private.key"
    public_path = out / f"{email}.public.key"

    private_path.write_text(private_hex)
    public_path.write_text(public_hex)

    # Set restrictive permissions on private key
    os.chmod(private_path, 0o600)

    return private_hex, public_hex


def load_registry(registry_path: str = "gitchain-registry.json") -> dict:
    """Load the public key registry (email → pubkey hex)."""
    path = Path(registry_path)
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def register_public_key(
    name: str,
    email: str,
    public_hex: str,
    registry_path: str = "gitchain-registry.json",
) -> None:
    """
    Add or update a developer's public key in gitchain-registry.json.

    The registry is a public file committed to the repo.
    It is used for identity display only — NOT for gating transactions
    (the blockchain is permissionless; any valid signature is accepted).
    """
    registry = load_registry(registry_path)
    registry[email] = {
        "name": name,
        "pubkey": public_hex,
    }
    Path(registry_path).write_text(
        json.dumps(registry, indent=2, sort_keys=True)
    )
