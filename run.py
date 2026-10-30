#!/usr/bin/env python3
"""ProofCrew command-line entry point.

Usage:
    TOKENFACTORY_API_KEY=... python3 run.py "Your task here" [--out DIR]

Writes <out>/deliverable.md and <out>/receipts.jsonl, prints the deliverable,
and self-checks the receipt chain before exiting.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from proofcrew.config import Config
from proofcrew.crew import run_crew
from proofcrew.receipts import verify_receipts
from proofcrew.tavily import TavilyClient
from proofcrew.transport import TokenFactoryTransport


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the ProofCrew on a task.")
    parser.add_argument("task", help="The task for the crew.")
    parser.add_argument(
        "--out",
        default="proofcrew-out",
        help="Output directory for deliverable.md and receipts.jsonl.",
    )
    args = parser.parse_args(argv)

    config = Config.from_env()
    if not config.api_key:
        print(
            "error: TOKENFACTORY_API_KEY is not set. Get a key from Nebius "
            "Token Factory and export it (see .env.example).",
            file=sys.stderr,
        )
        return 2

    transport = TokenFactoryTransport(config.api_key, config.base_url)
    tavily = TavilyClient(config.tavily_api_key) if config.tavily_api_key else None

    result = run_crew(args.task, transport, config, tavily)

    os.makedirs(args.out, exist_ok=True)
    deliverable_path = os.path.join(args.out, "deliverable.md")
    receipts_path = os.path.join(args.out, "receipts.jsonl")
    with open(deliverable_path, "w", encoding="utf-8") as fh:
        fh.write(result.deliverable)
    result.chain.write(receipts_path)

    problems = verify_receipts(result.chain.receipts)
    print(result.deliverable)
    print("=" * 60)
    print(f"Deliverable: {deliverable_path}")
    print(f"Receipts:    {receipts_path} ({len(result.chain.receipts)} receipts)")
    print(f"Worker B grounded via Tavily: {result.grounded_worker_b}")
    print(f"Adjudicated by planner:       {result.adjudicated}")
    if problems:
        print("Receipt chain INVALID:", problems)
        return 1
    print("Receipt chain self-check: VALID")
    return 0


if __name__ == "__main__":
    sys.exit(main())
