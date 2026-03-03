"""
Zoho payload hashing utilities.

Provides deterministic hashing of Zoho API payloads so we can detect
whether a record has actually changed and avoid redundant pushes /
webhook echo-loops.
"""
import hashlib
import json
from typing import Any


def generate_payload_hash(payload: dict[str, Any]) -> str:
    """
    Return a deterministic SHA-256 hex digest for *payload*.

    Keys are sorted recursively so that logically identical dicts always
    produce the same hash regardless of insertion order.
    """
    canonical = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
