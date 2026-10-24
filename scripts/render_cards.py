"""Render the profile README cards as self-hosted SVGs and append to the ledger.

Cards:
  cards/route.svg    the seven-hop traceroute strip with the growing AI thread (static, from data/hops.json)
  cards/now.svg      repos pushed in the last 30 days (GitHub API)
  cards/posture.svg  SECURITY.md / tests / CI / last push for featured repos (GitHub API)

Then, only if a card changed, append a hash-chained entry to ledger.jsonl and refresh the
ledger line in README.md between <!-- ledger:start --> and <!-- ledger:end -->.

Standard library only. Python 3.11+. Reads GITHUB_TOKEN or GH_TOKEN if present.
All security-relevant decisions here are deterministic string and HTTP checks; no model is involved.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.request
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CARDS = ROOT / "cards"
API = "https://api.github.com"
UA = "mwill20-profile-cards (+https://github.com/mwill20/mwill20)"

# palette, matching mwill20.github.io
BG, PANEL, LINE = "#05070c", "#0b1119", "#1b2433"
FG, DIM, TEAL, VIOLET, AMBER, GREEN, RED, GREY = "#eef2f7", "#8a97a8", "#5eead4", "#c4b5fd", "#fcd34d", "#34d399", "#f87171", "#3b4a66"
MONO = "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace"
SANS = "-apple-system, 'Segoe UI', Inter, Roboto, sans-serif"
W = 880


# ----------------------------------------------------------------------------- helpers

def svg_open(height: int, title: str) -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{height}" viewBox="0 0 {W} {height}" '
            f'role="img" aria-labelledby="t"><title id="t">{escape(title)}</title>'
            f'<rect width="{W}" height="{height}" rx="12" fill="{BG}"/>'
            f'<rect x="0.5" y="0.5" width="{W-1}" height="{height-1}" rx="12" fill="none" stroke="{LINE}"/>')


def text(x: float, y: float, s: str, *, size=12, fill=FG, font=MONO, anchor="start", weight="normal", extra="") -> str:
    return (f'<text x="{x:.1f}" y="{y:.1f}" font-family="{font}" font-size="{size}" fill="{fill}" '
            f'text-anchor="{anchor}" font-weight="{weight}" {extra}>{escape(s)}</text>')


def header(title: str, right: str) -> str:
    return (text(24, 30, title.upper(), size=11, fill=DIM, extra='letter-spacing="1.6"')
            + text(W - 24, 30, right, size=11, fill=DIM, anchor="end"))


def truncate(s: str, n: int) -> str:
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def meter(cx: float, y: float, value: float) -> str:
    """Five 9x5 segments centred on cx; filled, half-filled, or empty."""
    segs, gap, bw = 5, 3, 9
    x = cx - (segs * bw + (segs - 1) * gap) / 2
    out = []
    for k in range(segs):
        sx = x + k * (bw + gap)
        out.append(f'<rect x="{sx:.1f}" y="{y}" width="{bw}" height="5" rx="1" fill="{GREY}"/>')
        fill_w = bw if k + 1 <= value else (bw / 2 if k < value else 0)
        if fill_w:
            out.append(f'<rect x="{sx:.1f}" y="{y}" width="{fill_w:.1f}" height="5" rx="1" fill="{VIOLET}"/>')
    return "".join(out)


# ----------------------------------------------------------------------------- GitHub API

class ApiError(Exception):
    pass


def api_get(path: str, token: str | None):
    """GET api.github.com{path}. Returns (status, json_or_None). Raises ApiError on transport failure."""
    req = urllib.request.Request(API + path, headers={
        "User-Agent": UA,
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        **({"Authorization": f"Bearer {token}"} if token else {}),
    })
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return 404, None
        raise ApiError(f"{path}: HTTP {e.code}") from e
    except Exception as e:
        raise ApiError(f"{path}: {e.__class__.__name__}") from e


def fetch_recent_repos(owner: str, token: str | None, days: int = 30, limit: int = 5, exclude: tuple[str, ...] = ()) -> list[dict]:
    status, repos = api_get(f"/users/{owner}/repos?sort=pushed&direction=desc&per_page=30&type=owner", token)
    if status != 200 or not isinstance(repos, list):
        raise ApiError("repo listing failed")
    cutoff = utcnow() - dt.timedelta(days=days)
    out = []
    for r in repos:
        if r.get("fork") or r["name"] in exclude:
            continue
        pushed = dt.datetime.fromisoformat(r["pushed_at"].replace("Z", "+00:00"))
        if pushed < cutoff:
            continue
        out.append({"name": r["name"], "description": r.get("description") or "", "pushed": pushed.date().isoformat(),
                    "language": r.get("language") or ""})
    return out[:limit]


def fetch_posture(owner: str, repos: list[str], token: str | None) -> list[dict]:
    """One row per repo. Values: True / False / None (None = could not determine)."""
    rows = []
    for name in repos:
        row = {"name": name, "security": None, "tests": None, "ci": None, "pushed": ""}
        try:
            s, meta = api_get(f"/repos/{owner}/{name}", token)
            if s == 200 and meta:
                row["pushed"] = meta["pushed_at"][:10]
            s, _ = api_get(f"/repos/{owner}/{name}/contents/SECURITY.md", token)
            row["security"] = s == 200
            s, listing = api_get(f"/repos/{owner}/{name}/contents", token)
            if s == 200 and isinstance(listing, list):
                row["tests"] = any(i.get("type") == "dir" and i.get("name", "").lower() in ("test", "tests") for i in listing)
            s, wf = api_get(f"/repos/{owner}/{name}/contents/.github/workflows", token)
            row["ci"] = s == 200 and isinstance(wf, list) and len(wf) > 0
        except ApiError as e:
            print(f"  warn {e}", file=sys.stderr)
        rows.append(row)
    return rows


# ----------------------------------------------------------------------------- renderers

def render_route(hops: list[dict], loop_at: int) -> str:
    h = 192
    out = [svg_open(h, "Traceroute: seven hops from 2020 to now, with the AI thread growing per hop")]
    out.append(header("traceroute mwill20 --from 2020 --to now", "cyber route · AI thread"))
    n = len(hops)
    x0, x1, y = 70, W - 70, 96
    xs = [x0 + i * (x1 - x0) / (n - 1) for i in range(n)]
    # cyber route
    out.append(f'<path d="M {x0} {y} L {x1} {y}" stroke="{TEAL}" stroke-width="2" fill="none"/>')
    # loop at the Director hop
    if 0 <= loop_at < n:
        lx = xs[loop_at]
        out.append(f'<path d="M {lx} {y} c 18 -26, 44 -26, 44 0 c 0 20, -26 24, -44 0" stroke="{TEAL}" stroke-width="1.5" fill="none" opacity=".8"/>')
        out.append(text(lx + 50, y - 18, "loop · fill the gaps", size=9, fill=TEAL))
    # AI thread: segments thicken with the meter
    for i in range(1, n):
        m = float(hops[i]["meter"])
        if m <= 0:
            continue
        width = 0.6 + m * 0.8
        op = 0.25 + m * 0.15
        dash = ' stroke-dasharray="2 7"' if m < 1.5 else (' stroke-dasharray="6 5"' if m < 3 else "")
        out.append(f'<path d="M {xs[i-1]:.1f} {y+14} L {xs[i]:.1f} {y+14}" stroke="{VIOLET}" stroke-width="{width:.1f}" '
                   f'opacity="{min(op,1):.2f}" stroke-linecap="round"{dash} fill="none"/>')
    # nodes and labels
    for i, hop in enumerate(hops):
        x = xs[i]
        out.append(f'<circle cx="{x:.1f}" cy="{y}" r="5" fill="{BG}" stroke="{TEAL}" stroke-width="2"/>')
        out.append(text(x, y - 34, str(hop["year"]), size=10, fill=DIM, anchor="middle"))
        out.append(text(x, y + 40, truncate(str(hop["title"]), 24), size=11, fill=FG, font=SANS, anchor="middle"))
        out.append(meter(x, y + 50, float(hop["meter"])))
    out.append(text(24, h - 14, "hop", size=9, fill=DIM) + text(W - 24, h - 14, "AI meter: none → curiosity → study → adversarial → production", size=9, fill=DIM, anchor="end"))
    out.append("</svg>")
    return "".join(out)


def render_now(repos: list[dict], generated: str) -> str:
    rows = repos or [{"name": "quiet", "description": "no public pushes in the last 30 days", "pushed": "", "language": ""}]
    h = 58 + 34 * len(rows)
    out = [svg_open(h, "Now: repositories pushed in the last 30 days"), header("now · last 30 days", f"auto-generated {generated}")]
    for i, r in enumerate(rows):
        y = 64 + i * 34
        out.append(f'<line x1="24" y1="{y-20}" x2="{W-24}" y2="{y-20}" stroke="{LINE}"/>')
        out.append(text(24, y, truncate(r["name"], 30), size=12.5, fill=TEAL))
        out.append(text(300, y, truncate(r.get("description") or "", 62), size=12, fill=DIM, font=SANS))
        out.append(text(W - 24, y, r.get("pushed", ""), size=11, fill=DIM, anchor="end"))
    out.append("</svg>")
    return "".join(out)


def dot(x: float, y: float, v) -> str:
    fill = GREEN if v is True else (RED if v is False else GREY)
    label = "yes" if v is True else ("no" if v is False else "unknown")
    return f'<circle cx="{x:.1f}" cy="{y:.1f}" r="5" fill="{fill}"><title>{label}</title></circle>'


def render_posture(rows: list[dict], generated: str) -> str:
    h = 86 + 30 * len(rows)
    out = [svg_open(h, "Repo security posture: SECURITY.md, tests, CI, last push for featured repositories"),
           header("repo security posture · checked nightly", f"auto-generated {generated}")]
    cols = {"SECURITY.md": 470, "tests": 570, "CI": 650, "last push": W - 24}
    for label, x in cols.items():
        out.append(text(x, 54, label, size=10, fill=DIM, anchor="middle" if label != "last push" else "end"))
    out.append(f'<line x1="24" y1="62" x2="{W-24}" y2="62" stroke="{LINE}"/>')
    for i, r in enumerate(rows):
        y = 86 + i * 30
        out.append(text(24, y, truncate(r["name"], 40), size=12.5, fill=FG))
        out.append(dot(cols["SECURITY.md"], y - 4, r["security"]))
        out.append(dot(cols["tests"], y - 4, r["tests"]))
        out.append(dot(cols["CI"], y - 4, r["ci"]))
        out.append(text(cols["last push"], y, r.get("pushed", ""), size=11, fill=DIM, anchor="end"))
    out.append(text(24, h - 12, "gaps are shown on purpose; the scorecard is the backlog", size=9, fill=DIM))
    out.append("</svg>")
    return "".join(out)


# ----------------------------------------------------------------------------- ledger

def ledger_entries(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def entry_hash(entry: dict) -> str:
    body = {k: v for k, v in entry.items() if k != "hash"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def append_ledger(path: Path, cards: dict[str, str], ts: str) -> dict:
    entries = ledger_entries(path)
    prev = entries[-1]["hash"] if entries else "0" * 64
    entry = {"build": len(entries) + 1, "ts": ts, "cards": cards, "prev": prev}
    entry["hash"] = entry_hash(entry)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, sort_keys=True, separators=(",", ":")) + "\n")
    return entry


def update_readme_ledger(readme: Path, entry: dict) -> None:
    s = readme.read_text(encoding="utf-8")
    line = (f"`profile build #{entry['build']}` · `{entry['ts'][:10]}` · prev `sha256:{entry['prev'][:4]}…{entry['prev'][-4:]}` "
            f"· this `sha256:{entry['hash'][:4]}…{entry['hash'][-4:]}` · verify with `python scripts/verify_ledger.py`")
    new = re.sub(r"(<!-- ledger:start -->).*?(<!-- ledger:end -->)", rf"\1\n{line}\n\2", s, flags=re.S)
    if new == s and "<!-- ledger:start -->" not in s:
        print("  warn README has no ledger markers", file=sys.stderr)
    readme.write_text(new, encoding="utf-8")


# ----------------------------------------------------------------------------- main

def write_if_changed(path: Path, content: str) -> bool:
    if path.exists() and path.read_text(encoding="utf-8") == content:
        return False
    path.write_text(content, encoding="utf-8")
    return True


def main() -> int:
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    CARDS.mkdir(exist_ok=True)
    hops_cfg = json.loads((ROOT / "data" / "hops.json").read_text(encoding="utf-8"))
    feat = json.loads((ROOT / "data" / "featured.json").read_text(encoding="utf-8"))
    today = utcnow().date().isoformat()
    changed = []

    if write_if_changed(CARDS / "route.svg", render_route(hops_cfg["hops"], hops_cfg["loop_at"])):
        changed.append("route.svg")
    print("  route.svg rendered")

    try:
        recent = fetch_recent_repos(feat["owner"], token, exclude=tuple(feat.get("now_exclude", ())))
        # keep the card stable day to day: only the data, not the date, decides a change
        now_svg = render_now(recent, today)
        prev = (CARDS / "now.svg").read_text(encoding="utf-8") if (CARDS / "now.svg").exists() else ""
        if re.sub(r"auto-generated \d{4}-\d{2}-\d{2}", "", prev) != re.sub(r"auto-generated \d{4}-\d{2}-\d{2}", "", now_svg):
            (CARDS / "now.svg").write_text(now_svg, encoding="utf-8")
            changed.append("now.svg")
        print(f"  now.svg: {len(recent)} repos in the last 30 days")
    except ApiError as e:
        print(f"  warn now.svg left unchanged: {e}", file=sys.stderr)

    rows = fetch_posture(feat["owner"], feat["repos"], token)
    post_svg = render_posture(rows, today)
    prev = (CARDS / "posture.svg").read_text(encoding="utf-8") if (CARDS / "posture.svg").exists() else ""
    if re.sub(r"auto-generated \d{4}-\d{2}-\d{2}", "", prev) != re.sub(r"auto-generated \d{4}-\d{2}-\d{2}", "", post_svg):
        (CARDS / "posture.svg").write_text(post_svg, encoding="utf-8")
        changed.append("posture.svg")
    print(f"  posture.svg: {len(rows)} repos checked")

    if changed:
        cards = {p.name: sha256_file(p) for p in sorted(CARDS.glob("*.svg"))}
        entry = append_ledger(ROOT / "ledger.jsonl", cards, utcnow().isoformat(timespec="seconds"))
        update_readme_ledger(ROOT / "README.md", entry)
        print(f"  ledger: build #{entry['build']} appended ({', '.join(changed)} changed)")
    else:
        print("  no card changed; ledger untouched")
    return 0


if __name__ == "__main__":
    sys.exit(main())
