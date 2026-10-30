"""Hash-chained receipts for ProofCrew runs.

Every stage of a run appends one receipt (a JSON object) to an append-only
chain. Each receipt carries the SHA-256 hash of the previous receipt, so any
later edit to any receipt breaks the chain — and anyone can detect it with
``verify_receipts.py``, which uses only the Python standard library.

This module is deliberately dependency-free (hashlib/json/time only) so the
verifier stays stdlib-only.
"""
from __future__ import annotations

import hashlib
import json
import time

GENESIS_HASH = "0" * 64


def _canonical(obj) -> bytes:
    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def receipt_hash(receipt: dict) -> str:
    """SHA-256 over the canonical form of the receipt, excluding its own
    ``hash`` field."""
    body = {k: v for k, v in receipt.items() if k != "hash"}
    return hashlib.sha256(_canonical(body)).hexdigest()


class ReceiptChain:
    def __init__(self) -> None:
        self.receipts: list[dict] = []
        self._prev = GENESIS_HASH

    def append(self, actor: str, kind: str, payload: dict) -> dict:
        receipt = {
            "seq": len(self.receipts),
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "actor": actor,
            "kind": kind,
            "payload": payload,
            "prev_hash": self._prev,
        }
        receipt["hash"] = receipt_hash(receipt)
        self._prev = receipt["hash"]
        self.receipts.append(receipt)
        return receipt

    def to_jsonl(self) -> str:
        return "".join(json.dumps(r, sort_keys=True) + "\n" for r in self.receipts)

    def write(self, path) -> None:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(self.to_jsonl())


def verify_receipts(receipts: list[dict]) -> list[str]:
    """Return a list of problems found; an empty list means the chain is
    intact: sequence is continuous, every link matches, and every hash
    recomputes over the receipt's actual contents."""
    problems: list[str] = []
    prev = GENESIS_HASH
    for i, r in enumerate(receipts):
        if r.get("seq") != i:
            problems.append(f"receipt {i}: seq is {r.get('seq')!r}, expected {i}")
        if r.get("prev_hash") != prev:
            problems.append(
                f"receipt {i}: prev_hash does not match the previous receipt's "
                "hash (chain broken)"
            )
        if r.get("hash") != receipt_hash(r):
            problems.append(
                f"receipt {i}: hash mismatch — contents were altered after "
                "the fact"
            )
        prev = r.get("hash", prev)
    return problems


def load_receipts(path) -> list[dict]:
    out: list[dict] = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out
