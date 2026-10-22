"""Show pipeline state and the next command to run.

Usage:  py tools/status.py --config migration.config.json
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path
from typing import List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import base_argparser, load_config, read_json, read_jsonl  # noqa: E402


def main(argv: Optional[List[str]] = None) -> int:
    ap = base_argparser(__doc__)
    args = ap.parse_args(argv)
    cfg = load_config(args.config)
    lines = []
    nxt = None
    for s in cfg.systems:
        root = cfg.resolve(s["root"])
        lines.append(f"system {s['id']} ({s.get('company','')}): root {'OK' if root.exists() else 'MISSING'} {root}")
    if cfg.inventory_file.exists():
        inv = read_jsonl(cfg.inventory_file)
        lines.append(f"inventory: {len(inv)} objects, " + ", ".join(f"{k}={v}" for k, v in Counter(r['system'] for r in inv).items()))
    else:
        lines.append("inventory: not run")
        nxt = nxt or "/inventory"
    if cfg.evidence_file.exists():
        ev = read_jsonl(cfg.evidence_file)
        c = Counter(e["decision"] for e in ev)
        lines.append(f"evidence: {len(ev)} objects, auto={c['auto']} needs_llm={c['needs_llm']}")
    else:
        lines.append("evidence: not run")
        nxt = nxt or "/classify"
    if cfg.batches_dir.exists():
        batches = sorted(p.stem for p in cfg.batches_dir.glob("*.json"))
        done = {p.stem for p in cfg.llm_dir.glob("*.json")} if cfg.llm_dir.exists() else set()
        pending = [b for b in batches if b not in done]
        lines.append(f"llm batches: {len(batches)} prepared, {len(done)} with results, {len(pending)} pending" +
                     (f" (next: {', '.join(pending[:5])})" if pending else ""))
        if pending:
            nxt = nxt or "/classify (processes the pending batches)"
    if cfg.classification_file.exists():
        cls = read_json(cfg.classification_file)
        st = cls.get("stats", {})
        mods = ", ".join(f"{k[7:]}={v}" for k, v in sorted(st.items()) if k.startswith("module:"))
        lines.append(f"classification: {len(cls['objects'])} objects ({cls['generated']}); unclassified={st.get('unclassified', 0)}; {mods}")
        if st.get("unclassified", 0):
            nxt = nxt or "/classify"
    else:
        lines.append("classification: not merged")
    if cfg.overlaps_file.exists():
        lines.append(f"overlaps: {read_json(cfg.overlaps_file)['summary']}")
    if cfg.review_patch_file.exists():
        lines.append("review: patch present (apply with /review or merge --apply-review)")
    for name in ("explorer.html", "tree.md", "objects.csv", "target_packages.md", "target_packages_draft.md", "object_moves.csv"):
        p = cfg.output_dir / name
        if p.exists():
            lines.append(f"output: {name} ({p.stat().st_size // 1024} KB)")
    if not nxt and cfg.classification_file.exists():
        nxt = "/explorer, then /tree and /target-packages"
    print("\n".join(lines))
    print(f"NEXT: {nxt or '/inventory'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
