"""Stage 4b: Markdown tree + flat CSV + a copy of classification.json.

Reads  work/classification.json, work/overlaps.json
Writes output/tree.md, output/objects.csv, output/classification.json

Usage:  py tools/render_tree.py --config migration.config.json
"""
from __future__ import annotations

import csv
import shutil
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import base_argparser, load_config, load_taxonomy, log, read_json, short  # noqa: E402

CSV_COLUMNS = ["system", "company", "package", "package_desc", "type", "name", "description", "module", "module_name",
               "submodule", "submodule_name", "area", "area_name", "confidence", "source", "purpose", "flags",
               "secondary", "process_primary", "process_primary_name", "process_all", "process_basis",
               "outcome", "review_state", "reviewed_by", "model", "prompt_version", "taxonomy_version",
               "overlap_status", "overlap_systems", "loc", "function_modules", "files"]


def main(argv: Optional[List[str]] = None) -> int:
    ap = base_argparser(__doc__)
    ap.add_argument("--systems", default=None, help="comma-separated system ids to include (default all); outputs get a _<ids> suffix")
    args = ap.parse_args(argv)
    cfg = load_config(args.config)
    tax = load_taxonomy(cfg.taxonomy_path)
    cls = read_json(cfg.classification_file)
    only = {s.strip().upper() for s in args.systems.split(",") if s.strip()} if args.systems else None
    suffix = f"_{'_'.join(sorted(only))}" if only else ""
    if only:
        cls["objects"] = [o for o in cls["objects"] if o["system"].upper() in only]
        cls["systems"] = [s for s in cls["systems"] if s["id"].upper() in only]
    objs = cls["objects"]
    ov_index = read_json(cfg.overlaps_file).get("index", {}) if cfg.overlaps_file.exists() else {}
    cfg.output_dir.mkdir(parents=True, exist_ok=True)

    # ---- tree.md -------------------------------------------------------------------
    tree: Dict[str, Dict[str, Dict[str, List[dict]]]] = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    for o in objs:
        tree[o["module"]][o.get("submodule") or "_"][o.get("area") or "_"].append(o)

    lines = [f"# Custom code by SAP module", "", f"Generated {cls['generated']}. Systems: " +
             ", ".join(f"{s['id']} ({s['company']})" for s in cls["systems"]), "",
             f"Objects: {len(objs)}", ""]
    for module in sorted(tree, key=lambda m: (m == "UNKNOWN", m)):
        subs = tree[module]
        n_mod = sum(len(v) for s in subs.values() for v in s.values())
        lines.append(f"## {module} - {tax.name(module)}  ({n_mod})")
        for sub in sorted(subs, key=lambda s: (s == "_", s)):
            areas = subs[sub]
            n_sub = sum(len(v) for v in areas.values())
            indent = ""
            if sub != "_":
                lines.append(f"- **{sub} - {tax.name(sub)}** ({n_sub})")
                indent = "  "
            for area in sorted(areas, key=lambda a: (a == "_", a)):
                items = sorted(areas[area], key=lambda o: (o["type"], o["name"], o["system"]))
                a_indent = indent
                if area != "_":
                    lines.append(f"{indent}- *{area} - {tax.name(area)}* ({len(items)})")
                    a_indent = indent + "  "
                for o in items:
                    ov = ov_index.get(o["key"], {})
                    tag = f" [{ov['status']}: {','.join(ov.get('systems', []))}]" if ov.get("status") in ("identical", "diverged") else ""
                    fms = f" (FMs: {len(o['children'])})" if o.get("children") else ""
                    lines.append(f"{a_indent}- `{o['type']} {o['name']}` - {short(o.get('purpose') or o.get('description'), 90)} "
                                 f"| {o['system']} / {o['package']} | conf {o['confidence']:.2f}{fms}{tag}")
        lines.append("")

    # ---- process view -------------------------------------------------------------
    pcat = cls.get("process_catalog")
    if pcat:
        lines += ["", f"# Custom code by business process", "",
                  f"Catalog: {pcat['source']} {pcat['version']} (crosswalk {pcat.get('crosswalk_version', '')}). "
                  "An object appears under every process it is assigned to; the role is shown per line.", ""]
        mod_info = {m["id"]: m for m in pcat["modules"]}
        by_proc: Dict[str, List[tuple]] = defaultdict(list)
        for o in objs:
            for p in o.get("process", []):
                by_proc[p["process"]].append((p["role"], p.get("basis", ""), o))
        for group in pcat["groups"]:
            mods = [m for m in pcat["modules"] if m["group"] == group["name"] and by_proc.get(m["id"])]
            n_group = sum(len(by_proc[m["id"]]) for m in mods)
            if not n_group:
                continue
            lines.append(f"## {group['id']} - {group['name']}  ({n_group} assignments)")
            for m in mods:
                items = sorted(by_proc[m["id"]], key=lambda t: (t[0] != "direct", t[2]["type"], t[2]["name"], t[2]["system"]))
                lines.append(f"- **{m['id']} - {m['name']}** ({len(items)})")
                for role, basis, o in items:
                    lines.append(f"  - `{o['type']} {o['name']}` [{role}, {basis}] - {short(o.get('purpose') or o.get('description'), 80)} "
                                 f"| {o['system']} / {o['package']} | {o['module']}")
            lines.append("")
    (cfg.output_dir / f"tree{suffix}.md").write_text("\n".join(lines), encoding="utf-8")

    # ---- objects.csv ---------------------------------------------------------------
    with (cfg.output_dir / f"objects{suffix}.csv").open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
        w.writeheader()
        for o in sorted(objs, key=lambda o: (o["module"], o.get("submodule") or "", o.get("area") or "", o["type"], o["name"], o["system"])):
            ov = ov_index.get(o["key"], {})
            w.writerow({
                "system": o["system"], "company": o.get("company", ""), "package": o["package"], "package_desc": o.get("package_desc", ""),
                "type": o["type"], "name": o["name"], "description": o.get("description", ""),
                "module": o["module"], "module_name": tax.name(o["module"]),
                "submodule": o.get("submodule") or "", "submodule_name": tax.name(o["submodule"]) if o.get("submodule") else "",
                "area": o.get("area") or "", "area_name": tax.name(o["area"]) if o.get("area") else "",
                "confidence": o["confidence"], "source": o["source"], "purpose": o.get("purpose", ""),
                "flags": ";".join(o.get("flags", [])),
                "secondary": ";".join(f"{s.get('area') or s.get('submodule') or s['module']}({s['role']})" for s in o.get("secondary", [])),
                "process_primary": next((p["process"] for p in o.get("process", []) if p["role"] == "direct"), ""),
                "process_primary_name": next((p.get("label", "") for p in o.get("process", []) if p["role"] == "direct"), ""),
                "process_all": ";".join(f"{p['process']}({p['role']})" for p in o.get("process", [])),
                "process_basis": next((p.get("basis", "") for p in o.get("process", [])), ""),
                "outcome": o.get("outcome", ""), "review_state": o.get("review_state", ""), "reviewed_by": o.get("reviewed_by", ""),
                "model": (o.get("provenance") or {}).get("model", ""), "prompt_version": (o.get("provenance") or {}).get("prompt_version", ""),
                "taxonomy_version": (o.get("provenance") or {}).get("taxonomy_version", ""),
                "overlap_status": ov.get("status", ""), "overlap_systems": ";".join(ov.get("systems", [])),
                "loc": o.get("loc", 0), "function_modules": ";".join(c["name"] for c in o.get("children", [])),
                "files": ";".join(o.get("files", [])),
            })
    if not only:
        shutil.copyfile(cfg.classification_file, cfg.output_dir / "classification.json")
    log(f"tree: {cfg.output_dir / f'tree{suffix}.md'}, csv: {cfg.output_dir / f'objects{suffix}.csv'}")
    print(f"TREE_OK objects={len(objs)} tree={cfg.output_dir / f'tree{suffix}.md'} csv={cfg.output_dir / f'objects{suffix}.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
