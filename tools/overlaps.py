"""Stage 2d: find overlaps between the systems.

- same_name : same TYPE+NAME in 2+ systems -> identical (same normalised source hash) or diverged
- similar   : different names, same submodule, similar name or same set of standard tables
- collisions: same_name entries that are diverged (must be resolved before the merge)

Reads  work/inventory.jsonl, work/classification.json
Writes work/overlaps.json

Usage:  py tools/overlaps.py --config migration.config.json
"""
from __future__ import annotations

import difflib
import re
import sys
from collections import defaultdict
from itertools import combinations
from pathlib import Path
from typing import Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import base_argparser, load_config, log, normalize_source, read_json, read_jsonl, read_text, write_json  # noqa: E402

SYSTEM_PREFIX = re.compile(r"^(Z|Y)[A-Z0-9]{0,3}_")


def canon_name(name: str) -> str:
    """Strip a leading company/system prefix (ZA_, ZB_, ZCOM_) so ZA_PO_PRINT ~ ZB_PO_PRINT."""
    return SYSTEM_PREFIX.sub("Z_", name)


def source_similarity(root_a: Path, rec_a: dict, root_b: Path, rec_b: dict) -> float:
    def blob(root, rec):
        parts = []
        for f in rec.get("source_files", []):
            try:
                parts.append(normalize_source(read_text(root / f)))
            except OSError:
                pass
        return "\n".join(parts)
    a, b = blob(root_a, rec_a), blob(root_b, rec_b)
    if not a and not b:
        return 1.0
    return round(difflib.SequenceMatcher(None, a, b, autojunk=True).ratio(), 3)


def main(argv: Optional[List[str]] = None) -> int:
    ap = base_argparser(__doc__)
    args = ap.parse_args(argv)
    cfg = load_config(args.config)
    ocfg = cfg.overlaps
    inv = read_jsonl(cfg.inventory_file)
    cls = read_json(cfg.classification_file)["objects"] if cfg.classification_file.exists() else []
    cls_by_key = {o["key"]: o for o in cls}
    roots = cfg.roots()
    n_systems = len(cfg.systems)

    by_typename: Dict[str, List[dict]] = defaultdict(list)
    for r in inv:
        by_typename[f"{r['type']}|{r['name']}"].append(r)

    same_name = []
    collisions = []
    for tn, recs in by_typename.items():
        if len(recs) < 2:
            continue
        hashes = {r["source_hash"] for r in recs}
        status = "identical" if len(hashes) == 1 else "diverged"
        sim = None
        if status == "diverged":
            sims = [source_similarity(roots[a["system"]], a, roots[b["system"]], b) for a, b in combinations(recs, 2)]
            sim = round(min(sims), 3) if sims else None
        entry = {"type": recs[0]["type"], "name": recs[0]["name"], "status": status, "similarity": sim,
                 "systems": sorted(r["system"] for r in recs), "in_all_systems": len(recs) == n_systems,
                 "keys": [r["key"] for r in recs],
                 "loc": {r["system"]: r.get("loc", 0) for r in recs},
                 "packages": {r["system"]: r["package"] for r in recs},
                 "modules": {r["system"]: cls_by_key.get(r["key"], {}).get("module") for r in recs}}
        same_name.append(entry)
        if status == "diverged":
            collisions.append(entry)

    # similar: same submodule across systems, name similarity or shared standard tables
    thresh = float(ocfg.get("similar_name_threshold", 0.82))
    min_tables = int(ocfg.get("min_shared_tables", 2))
    by_sub: Dict[str, List[dict]] = defaultdict(list)
    for o in cls:
        if o["module"] in ("UNKNOWN", "BC") or o["type"] not in ("PROG", "CLAS", "FUGR", "INTF", "ENHO", "SXCI", "DDLS"):
            continue
        by_sub[o.get("submodule") or o["module"]].append(o)
    similar = []
    for sub, objs in by_sub.items():
        if len(objs) > 1500:
            log(f"  skip similarity for {sub}: {len(objs)} objects (too many pairs)")
            continue
        for a, b in combinations(objs, 2):
            if a["system"] == b["system"] or a["name"] == b["name"]:
                continue
            ca, cb = canon_name(a["name"]), canon_name(b["name"])
            name_sim = difflib.SequenceMatcher(None, ca, cb).ratio()
            ta = {t for t in a.get("refs", {}).get("tables", {}) if not t.startswith(("Z", "Y"))}
            tb = {t for t in b.get("refs", {}).get("tables", {}) if not t.startswith(("Z", "Y"))}
            shared = ta & tb
            reason = []
            if name_sim >= thresh:
                reason.append(f"name similarity {name_sim:.2f}")
            if len(shared) >= min_tables and a["type"] == b["type"] and len(shared) >= 0.6 * max(len(ta), len(tb), 1):
                reason.append(f"same tables {sorted(shared)[:6]}")
            if reason:
                similar.append({"a": a["key"], "b": b["key"], "submodule": sub, "name_similarity": round(name_sim, 2),
                                "shared_tables": sorted(shared)[:12], "reason": "; ".join(reason)})
    similar.sort(key=lambda s: -s["name_similarity"])

    index: Dict[str, dict] = {}
    for e in same_name:
        for k in e["keys"]:
            index[k] = {"status": e["status"], "systems": e["systems"], "similarity": e["similarity"]}
    for s in similar:
        for k in (s["a"], s["b"]):
            index.setdefault(k, {"status": "similar", "systems": [], "similarity": None})
            index[k].setdefault("similar_to", []).append(s["b"] if k == s["a"] else s["a"])

    out = {"summary": {"same_name": len(same_name), "identical": sum(1 for e in same_name if e["status"] == "identical"),
                       "diverged": len(collisions), "similar_pairs": len(similar)},
           "same_name": same_name, "collisions": collisions, "similar": similar[:5000], "index": index}
    write_json(cfg.overlaps_file, out)
    log(f"overlaps: {out['summary']}")
    print(f"OVERLAPS_OK same_name={len(same_name)} identical={out['summary']['identical']} diverged={len(collisions)} "
          f"similar_pairs={len(similar)} file={cfg.overlaps_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
