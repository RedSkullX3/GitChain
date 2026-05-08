"""
Sign and verify GitChain transaction payloads using Ed25519 (PyNaCl).

The GitHub Action uses this (via tweetnacl in JS) to sign each commit payload.
Any GitChain node uses verify_signature() to authenticate incoming transactions.
"""

import nacl.signing
import nacl.encoding
import nacl.exceptions


def sign_payload(payload_hash: str, private_key_hex: str) -> str:
    """
    Sign a payload hash with the developer's Ed25519 private key.

    Args:
        payload_hash:    SHA-256 hex digest of the transaction fields
        private_key_hex: 64-char hex private key (from GitHub Secrets)

    Returns:
        Signature as a hex string.
    """
    signing_key = nacl.signing.SigningKey(
        private_key_hex,
        encoder=nacl.encoding.HexEncoder,
    )
    signed = signing_key.sign(payload_hash.encode())
    # signed.signature is the 64-byte raw signature
    return signed.signature.hex()


def verify_signature(payload_hash: str, signature_hex: str, public_key_hex: str) -> bool:
    """
    Verify a signature against a payload hash using an Ed25519 public key.

    Permissionless: the public key is taken directly from the transaction —
    no central registry lookup required for validation. The registry is only
    used for human-readable name display in the dashboard.

    Returns:
        True if signature is valid, False otherwise.
    """
    try:
        vk = nacl.signing.VerifyKey(
            public_key_hex,
            encoder=nacl.encoding.HexEncoder,
        )
        vk.verify(payload_hash.encode(), bytes.fromhex(signature_hex))
        return True
    except (nacl.exceptions.BadSignatureError, Exception):
        return False


def pubkey_from_private(private_key_hex: str) -> str:
    """Derive the public key hex from a private key hex."""
    signing_key = nacl.signing.SigningKey(
        private_key_hex,
        encoder=nacl.encoding.HexEncoder,
    )
    return signing_key.verify_key.encode(encoder=nacl.encoding.HexEncoder).decode()
