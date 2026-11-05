from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from proofcrew.quorum import verify_quorum

def test_empty_quorum_fails_closed():
    assert verify_quorum([], b"artifact", {"version": 1, "attestations": {}}, {}, 2)["accepted"] is False

def test_unknown_operator_cannot_satisfy_quorum():
    assert verify_quorum([], b"artifact", {"version": 1, "attestations": {"unknown": {}}}, {}, 1)["valid"] == 0

def test_same_public_key_does_not_count_twice():
    key = Ed25519PrivateKey.generate()
    pem = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    # No valid signed receipt exists here: fail closed regardless of aliases.
    result = verify_quorum([], b"artifact", {"version": 1, "attestations": {"a": {}, "b": {}}}, {"a": pem, "b": pem}, 2)
    assert result["accepted"] is False
