"""Unit tests for the receipt hash chain and the shipped verifier.

The core guarantee: alter any receipt after the fact and verification fails.
"""
import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from proofcrew.receipts import ReceiptChain, verify_receipts

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def sample_chain() -> ReceiptChain:
    chain = ReceiptChain()
    chain.append("planner", "plan", {"model": "ultra", "task": "write a haiku"})
    chain.append("worker_a", "work", {"model": "super", "grounded": False, "output": "A"})
    chain.append("worker_b", "work", {"model": "super", "grounded": False, "output": "B"})
    chain.append("crew", "final", {"deliverable_sha256": "abc"})
    return chain


class TestReceiptChain(unittest.TestCase):
    def test_valid_chain_passes(self):
        self.assertEqual(verify_receipts(sample_chain().receipts), [])

    def test_tampered_payload_fails(self):
        receipts = copy.deepcopy(sample_chain().receipts)
        receipts[1]["payload"]["output"] = "forged output"
        problems = verify_receipts(receipts)
        self.assertTrue(problems, "tampered payload must fail verification")
        self.assertTrue(any("hash mismatch" in p for p in problems))

    def test_tampered_hash_fails(self):
        receipts = copy.deepcopy(sample_chain().receipts)
        receipts[2]["hash"] = "f" * 64
        self.assertTrue(verify_receipts(receipts))

    def test_rehashed_tamper_breaks_the_link(self):
        # Even an attacker who recomputes the tampered receipt's own hash
        # breaks the next receipt's prev_hash link.
        from proofcrew.receipts import receipt_hash

        receipts = copy.deepcopy(sample_chain().receipts)
        receipts[1]["payload"]["output"] = "forged output"
        receipts[1]["hash"] = receipt_hash(receipts[1])
        problems = verify_receipts(receipts)
        self.assertTrue(any("prev_hash" in p for p in problems))

    def test_dropped_receipt_fails(self):
        receipts = copy.deepcopy(sample_chain().receipts)
        del receipts[1]
        self.assertTrue(verify_receipts(receipts))

    def test_genesis_link(self):
        chain = sample_chain()
        self.assertEqual(chain.receipts[0]["prev_hash"], "0" * 64)
        self.assertEqual(chain.receipts[1]["prev_hash"], chain.receipts[0]["hash"])


class TestShippedVerifierScript(unittest.TestCase):
    """verify_receipts.py — the stdlib-only script anyone can run."""

    def _write(self, chain: ReceiptChain) -> str:
        fh = tempfile.NamedTemporaryFile(
            "w", suffix=".jsonl", delete=False, encoding="utf-8"
        )
        fh.write(chain.to_jsonl())
        fh.close()
        return fh.name

    def _run_verifier(self, path: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, os.path.join(REPO_ROOT, "verify_receipts.py"), path],
            capture_output=True,
            text=True,
        )

    def test_verifier_accepts_valid_chain(self):
        path = self._write(sample_chain())
        proc = self._run_verifier(path)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("CHAIN VALID", proc.stdout)

    def test_verifier_rejects_tampered_file(self):
        path = self._write(sample_chain())
        with open(path, encoding="utf-8") as fh:
            lines = fh.readlines()
        row = json.loads(lines[1])
        row["payload"]["output"] = "tampered after the fact"
        lines[1] = json.dumps(row) + "\n"
        with open(path, "w", encoding="utf-8") as fh:
            fh.writelines(lines)
        proc = self._run_verifier(path)
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertIn("CHAIN INVALID", proc.stdout)


if __name__ == "__main__":
    unittest.main()
