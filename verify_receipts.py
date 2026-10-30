#!/usr/bin/env python3
"""Re-verify a ProofCrew receipt chain — Python standard library only.

Usage:
    python3 verify_receipts.py [path/to/receipts.jsonl]

Exit code 0 means every receipt's hash recomputes over its actual contents
and every link in the chain matches: nothing was altered after the run.
Exit code 1 means the chain is broken. This gives you the same guarantee
ProofCrew itself checks, with no ProofCrew dependencies beyond the stdlib
receipt module and no network access.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from proofcrew.receipts import load_receipts, verify_receipts


def main(argv: list[str]) -> int:
    path = argv[1] if len(argv) > 1 else "receipts.jsonl"
    receipts = load_receipts(path)
    stages = " -> ".join(f"{r.get('actor')}/{r.get('kind')}" for r in receipts)
    print(f"{len(receipts)} receipts: {stages}")
    for r in receipts:
        if r.get("kind") == "work" and r.get("actor") == "worker_b":
            print(f"worker_b grounded via Tavily: {r['payload'].get('grounded')}")
    problems = verify_receipts(receipts)
    if problems:
        print("CHAIN INVALID:")
        for p in problems:
            print(f" - {p}")
        return 1
    print("CHAIN VALID — every receipt hashes to the next; nothing was altered.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
