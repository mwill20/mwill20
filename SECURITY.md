# Security

## Scope

This repository is the GitHub profile README for mwill20 plus a nightly GitHub Action that
renders three SVG cards and appends to a hash-chained ledger.

## What runs, with what

- `scripts/render_cards.py` runs in GitHub Actions on a daily schedule, on manual dispatch,
  and on pushes that change `data/`, `scripts/`, `tests/`, or the workflow.
- It uses the workflow's default `GITHUB_TOKEN` with `contents: write` on **this repository
  only**. No other secrets exist. The token is sent only to `api.github.com`.
- Outbound calls: GitHub REST API (public repository metadata and contents listings) and,
  in tests, one raw file fetch from `mwill20.github.io` for the drift check.
- Python 3.11 standard library only. No third-party packages.
- Actions are pinned to exact release tags (`actions/checkout@v4.2.2`,
  `actions/setup-python@v5.3.0`).

## Trust boundary

Everything read from the API is untrusted data. Descriptions and names are HTML-escaped
before they are written into SVG. An API failure renders as grey ("unknown"), never as a
pass. No model or heuristic makes any decision in this pipeline; every check is a
deterministic string or HTTP status comparison.

## Ledger

`ledger.jsonl` is append-only. Each entry carries SHA-256 digests of the cards, the
previous entry's hash, and its own hash over the entry body. `scripts/verify_ledger.py`
recomputes the chain and compares the digests to the files on disk. It makes tampering
*evident*, not impossible: anyone with write access can rewrite history. Git history is the
second witness.

## Reporting

Open an issue in this repository or email mwill.itmission@gmail.com.
