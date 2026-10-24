"""Verify the hash chain in ledger.jsonl and that the current cards match the last entry.

    python scripts/verify_ledger.py            # exit 0 if the chain and cards verify
    python scripts/verify_ledger.py --chain    # chain only, do not compare card files

Standard library only.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def entry_hash(entry: dict) -> str:
    body = {k: v for k, v in entry.items() if k != "hash"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def verify(lines: list[str], cards_dir: Path | None) -> list[str]:
    """Return a list of problems. Empty list means the ledger verifies."""
    problems: list[str] = []
    prev = "0" * 64
    last = None
    for i, line in enumerate(lines, 1):
        if not line.strip():
            continue
        e = json.loads(line)
        if e.get("prev") != prev:
            problems.append(f"line {i}: prev does not match previous hash")
        if e.get("hash") != entry_hash(e):
            problems.append(f"line {i}: hash does not match content")
        if e.get("build") != (last["build"] + 1 if last else 1):
            problems.append(f"line {i}: build number out of sequence")
        # chain on the recomputed hash, so editing an entry breaks every entry after it
        prev = entry_hash(e)
        last = e
    if last is None:
        problems.append("ledger is empty")
    elif cards_dir is not None:
        for name, digest in last["cards"].items():
            p = cards_dir / name
            if not p.exists():
                problems.append(f"card missing: {name}")
            elif hashlib.sha256(p.read_bytes()).hexdigest() != digest:
                problems.append(f"card differs from ledger: {name}")
    return problems


def main() -> int:
    lines = (ROOT / "ledger.jsonl").read_text(encoding="utf-8").splitlines()
    problems = verify(lines, None if "--chain" in sys.argv else ROOT / "cards")
    for p in problems:
        print(f"  FAIL {p}")
    print("LEDGER OK" if not problems else "LEDGER FAIL")
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())
