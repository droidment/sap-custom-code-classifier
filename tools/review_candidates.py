"""Stage 3a: pick the objects worth a reviewer's attention and write them in a compact file.

Reads  work/classification.json, work/overlaps.json
Writes work/review_candidates.json

Candidate groups
  low_confidence          confidence < review.low_confidence
  unknown                 module UNKNOWN or source 'missing'
  disagree_heuristic      LLM module differs from heuristic module when the heuristic was strong
  mixed_fugr              function groups whose FM descriptions/names point to several modules
  cross_system_mismatch   same TYPE+NAME classified differently in different systems
  package_outliers        objects whose module differs from >= 80% of their package
  llm_flags               objects the LLM flagged needs-human / cross-module / mixed-fugr

Usage:  py tools/review_candidates.py --config migration.config.json
"""
from __future__ import annotations

import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import base_argparser, load_config, log, read_json, write_json  # noqa: E402


def brief(o: dict) -> dict:
    return {"key": o["key"], "type": o["type"], "name": o["name"], "package": o["package"], "description": o.get("description", ""),
            "module": o["module"], "submodule": o.get("submodule"), "area": o.get("area"), "confidence": o.get("confidence"),
            "source": o.get("source"), "purpose": o.get("purpose", ""), "rationale": o.get("rationale", ""),
            "heuristic": o.get("heuristic", {}), "evidence": o.get("evidence", [])[:8], "flags": o.get("flags", []),
            "children": [c["name"] for c in o.get("children", [])][:15]}


def main(argv: Optional[List[str]] = None) -> int:
    ap = base_argparser(__doc__)
    ap.add_argument("--max-per-group", type=int, default=150)
    args = ap.parse_args(argv)
    cfg = load_config(args.config)
    low = float(cfg.review.get("low_confidence", 0.6))
    cls = read_json(cfg.classification_file)
    objs = cls["objects"]
    overlaps = read_json(cfg.overlaps_file) if cfg.overlaps_file.exists() else {"same_name": []}

    groups: Dict[str, List[dict]] = defaultdict(list)
    for o in objs:
        if o["module"] == "UNKNOWN" or o.get("source") == "missing":
            groups["unknown"].append(brief(o))
        elif (o.get("confidence") or 0) < low:
            groups["low_confidence"].append(brief(o))
        h = o.get("heuristic") or {}
        if o.get("source") == "llm" and h.get("module") and h.get("module") not in ("UNKNOWN", o["module"]):
            top = h.get("top") or []
            if top and top[0][1] >= 5:
                groups["disagree_heuristic"].append(brief(o))
        if any(f in ("needs-human", "cross-module", "mixed-fugr") for f in o.get("flags", [])):
            groups["llm_flags"].append(brief(o))

    for e in overlaps.get("same_name", []):
        mods = {m for m in e.get("modules", {}).values() if m}
        if len(mods) > 1:
            groups["cross_system_mismatch"].append({"type": e["type"], "name": e["name"], "modules": e["modules"],
                                                    "keys": e["keys"], "status": e["status"]})

    by_pkg: Dict[str, List[dict]] = defaultdict(list)
    for o in objs:
        by_pkg[f"{o['system']}|{o['package']}"].append(o)
    for pkg, members in by_pkg.items():
        if len(members) < 5:
            continue
        cnt = Counter(m["module"] for m in members if m["module"] != "UNKNOWN")
        if not cnt:
            continue
        dominant, n = cnt.most_common(1)[0]
        if n / len(members) >= 0.8:
            for m in members:
                if m["module"] not in (dominant, "UNKNOWN", "BC", "CA"):
                    b = brief(m)
                    b["package_dominant_module"] = dominant
                    groups["package_outliers"].append(b)

    out = {"low_confidence_threshold": low, "counts": {g: len(v) for g, v in groups.items()},
           "groups": {g: v[: args.max_per_group] for g, v in groups.items()},
           "taxonomy": [{"id": n["id"], "name": n["name"], "parent": n.get("parent")} for n in cls["taxonomy"]]}
    write_json(cfg.review_candidates_file, out)
    log(f"review candidates: {out['counts']}")
    print("REVIEW_CANDIDATES_OK " + " ".join(f"{g}={len(v)}" for g, v in groups.items()) + f" file={cfg.review_candidates_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
