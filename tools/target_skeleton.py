"""Stage 5a: draft target package hierarchy and per-object move list from the classification.

Reads  work/classification.json, work/overlaps.json
Writes work/target_draft.json, output/object_moves.csv, output/target_packages_draft.md

Naming convention (default, change --prefix): Z_<MODULE>, Z_<MODULE>_<SUB>, Z_<MODULE>_<SUB>_<AREA>
e.g. HCM / HCM-PT / HCM-PT-TS  ->  Z_HCM / Z_HCM_PT / Z_HCM_PT_TS.
Technical objects (BC, CA) go under Z_BC / Z_CA; UNKNOWN goes to Z_UNASSIGNED for triage.

Actions
  move          single occurrence, classified -> move to target package
  dedupe        identical in several systems -> keep one copy
  resolve       diverged copies -> rename or merge decision needed
  triage        UNKNOWN / low confidence -> human decision needed

Usage:  py tools/target_skeleton.py --config migration.config.json [--prefix Z_]
"""
from __future__ import annotations

import csv
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import base_argparser, load_config, load_taxonomy, log, read_json, write_json  # noqa: E402


def pkg_name(prefix: str, node: Optional[str]) -> str:
    if not node or node == "UNKNOWN":
        return f"{prefix}UNASSIGNED"
    return prefix + node.replace("-", "_")


def main(argv: Optional[List[str]] = None) -> int:
    ap = base_argparser(__doc__)
    ap.add_argument("--prefix", default="Z_")
    ap.add_argument("--min-confidence", type=float, default=0.6)
    args = ap.parse_args(argv)
    cfg = load_config(args.config)
    tax = load_taxonomy(cfg.taxonomy_path)
    cls = read_json(cfg.classification_file)
    objs = cls["objects"]
    ov = read_json(cfg.overlaps_file) if cfg.overlaps_file.exists() else {"same_name": [], "index": {}}
    ov_index = ov.get("index", {})
    same_name = {k: e for e in ov.get("same_name", []) for k in e["keys"]}

    packages: Dict[str, dict] = {}

    def ensure(node: Optional[str]):
        name = pkg_name(args.prefix, node)
        if name not in packages:
            parent = tax.parent(node) if node and node in tax.nodes else None
            packages[name] = {"package": name, "node": node, "description": tax.name(node) if node else "Unassigned custom code (triage)",
                              "parent": pkg_name(args.prefix, parent) if parent else None, "objects": 0, "systems": Counter(), "types": Counter()}
            if parent:
                ensure(parent)
        return name

    moves = []
    seen_dedupe = set()
    for o in objs:
        node = o.get("area") or o.get("submodule") or o["module"]
        target = ensure(node if o["module"] != "UNKNOWN" else None)
        p = packages[target]
        p["objects"] += 1
        p["systems"][o["system"]] += 1
        p["types"][o["type"]] += 1
        action, note = "move", ""
        if o["module"] == "UNKNOWN" or o["confidence"] < args.min_confidence:
            action, note = "triage", f"confidence {o['confidence']:.2f}"
        sn = same_name.get(o["key"])
        if sn:
            if sn["status"] == "identical":
                action = "dedupe"
                note = "identical in " + ",".join(sn["systems"]) + ("; keep one copy" if o["key"] == sn["keys"][0] else "; drop, duplicate of " + sn["keys"][0])
            else:
                action = "resolve"
                note = f"diverged in {','.join(sn['systems'])} (similarity {sn['similarity']}); rename per system or merge logic"
        moves.append({"system": o["system"], "package": o["package"], "type": o["type"], "name": o["name"],
                      "module": o["module"], "submodule": o.get("submodule") or "", "area": o.get("area") or "",
                      "target_package": target, "action": action, "confidence": o["confidence"], "note": note,
                      "purpose": o.get("purpose", "")})

    pk_list = []
    for name, p in sorted(packages.items()):
        pk_list.append({**p, "systems": dict(p["systems"]), "types": dict(p["types"])})
    actions = Counter(m["action"] for m in moves)
    draft = {"prefix": args.prefix, "packages": pk_list, "actions": dict(actions), "moves": moves}
    write_json(cfg.target_draft_file, draft)

    cfg.output_dir.mkdir(parents=True, exist_ok=True)
    with (cfg.output_dir / "object_moves.csv").open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=list(moves[0].keys()) if moves else ["system"])
        w.writeheader()
        for m in sorted(moves, key=lambda m: (m["target_package"], m["type"], m["name"], m["system"])):
            w.writerow(m)

    md = ["# Target package design (draft)", "", f"Prefix: `{args.prefix}`  |  objects: {len(objs)}  |  actions: " +
          ", ".join(f"{k}={v}" for k, v in actions.most_common()), "", "## Hierarchy", ""]
    roots = [p for p in pk_list if not p["parent"]]

    def emit(p, depth):
        md.append(f"{'  ' * depth}- `{p['package']}` {p['description']} ({p['objects']} objects; " +
                  ", ".join(f"{s}={n}" for s, n in sorted(p['systems'].items())) + ")")
        for c in sorted((c for c in pk_list if c["parent"] == p["package"]), key=lambda c: c["package"]):
            emit(c, depth + 1)
    for r in sorted(roots, key=lambda r: r["package"]):
        emit(r, 0)
    md += ["", "## Open decisions", "",
           f"- {actions.get('resolve', 0)} objects exist in several systems with different code (see object_moves.csv action=resolve)",
           f"- {actions.get('dedupe', 0)} objects are identical copies across systems (keep one)",
           f"- {actions.get('triage', 0)} objects are unclassified or low confidence (triage before moving)", ""]
    (cfg.output_dir / "target_packages_draft.md").write_text("\n".join(md), encoding="utf-8")
    log(f"target draft: {len(pk_list)} packages, actions {dict(actions)}")
    print(f"TARGET_OK packages={len(pk_list)} moves={len(moves)} " + " ".join(f"{k}={v}" for k, v in actions.items()) +
          f" draft={cfg.target_draft_file} csv={cfg.output_dir / 'object_moves.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
