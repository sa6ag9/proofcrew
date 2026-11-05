"""Multi-operator independent attestation quorum for a ProofCrew artifact.

Each signer must be independently trusted. A quorum only establishes that
distinct pinned operators signed identical evidence, not that claims are true.
"""
from __future__ import annotations
import hashlib
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from .attestation import sign_attestation, verify_attestation


def sign_quorum(receipts, deliverable: bytes, private_keys: dict[str, bytes]) -> dict:
    if not private_keys:
        raise ValueError("at least one signing operator required")
    signatures = {}
    for operator, pem in sorted(private_keys.items()):
        if not isinstance(operator, str) or not operator.strip():
            raise ValueError("invalid operator identifier")
        signatures[operator] = sign_attestation(receipts, deliverable, pem)
    return {"version": 1, "attestations": signatures}


def verify_quorum(receipts, deliverable: bytes, bundle: dict,
                  trusted_keys: dict[str, bytes], threshold: int) -> dict:
    if not isinstance(threshold, int) or isinstance(threshold, bool) or threshold < 1:
        raise ValueError("threshold must be a positive integer")
    if not isinstance(bundle, dict) or bundle.get("version") != 1 or not isinstance(bundle.get("attestations"), dict):
        return {"accepted": False, "valid": 0, "threshold": threshold, "reason": "invalid bundle"}
    seen_keys = set()
    accepted = []
    rejected = []
    for operator, attestation in sorted(bundle["attestations"].items()):
        pem = trusted_keys.get(operator)
        if pem is None:
            rejected.append(operator)
            continue
        try:
            key = serialization.load_pem_public_key(pem)
            if not isinstance(key, Ed25519PublicKey):
                rejected.append(operator)
                continue
            fingerprint = hashlib.sha256(key.public_bytes(
                encoding=serialization.Encoding.DER,
                format=serialization.PublicFormat.SubjectPublicKeyInfo)).hexdigest()
            if fingerprint in seen_keys:
                rejected.append(operator)
                continue
            if verify_attestation(receipts, deliverable, attestation, pem):
                rejected.append(operator)
                continue
            seen_keys.add(fingerprint)
            accepted.append(operator)
        except (TypeError, ValueError):
            rejected.append(operator)
    return {"accepted": len(accepted) >= threshold, "valid": len(accepted),
            "threshold": threshold, "operators": accepted, "rejected": rejected}
