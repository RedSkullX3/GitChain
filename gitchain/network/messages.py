import json
from enum import Enum
from typing import Any


class MessageType(str, Enum):
    # A new unconfirmed commit transaction — broadcast to all peers
    NEW_TRANSACTION = "NEW_TRANSACTION"

    # A freshly mined block — broadcast to all peers
    NEW_BLOCK = "NEW_BLOCK"

    # Request a peer's full chain (sent on first connect / re-sync)
    GET_CHAIN = "GET_CHAIN"

    # Response to GET_CHAIN — carries the full chain as a list of block dicts
    CHAIN_RESPONSE = "CHAIN_RESPONSE"

    # Heartbeat — sent every PING_INTERVAL seconds to detect stale peers
    PING = "PING"

    # Response to PING
    PONG = "PONG"


def encode(msg_type: MessageType, payload: Any = None) -> bytes:
    
    envelope = {
        "type": msg_type.value,
        "payload": payload if payload is not None else {},
    }
    return (json.dumps(envelope, separators=(",", ":")) + "\n").encode()


def decode(raw: str) -> tuple[MessageType, Any]:
    
    try:
        envelope = json.loads(raw.strip())
    except json.JSONDecodeError as e:
        raise ValueError(f"malformed JSON: {e}") from e

    try:
        msg_type = MessageType(envelope["type"])
    except (KeyError, ValueError) as e:
        raise ValueError(f"unknown message type: {envelope.get('type')!r}") from e

    return msg_type, envelope.get("payload", {})
