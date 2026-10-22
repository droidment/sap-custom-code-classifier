"""Shared helpers for the SAP custom-code classification pipeline.

Standard library only. Every script in tools/ imports this module.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Tuple

# --------------------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------------------

DEFAULT_CONFIG = {
    "systems": [],
    "work_dir": "work",
    "output_dir": "output",
    "taxonomy": "tools/taxonomy.json",
    "classification": {
        "auto_min_score": 6.0,
        "auto_min_margin": 3.0,
        "sub_level_share": 0.3,
        "batch_size": 20,
        "excerpt_max_lines": 140,
        "excerpt_max_chars": 7000,
        "propagation_passes": 2,
        "propagation_cap": 4.0,
        "propagation_factor_users": 1.0,
        "propagation_factor_uses": 0.6,
    },
    "review": {"low_confidence": 0.6},
    "overlaps": {"similar_name_threshold": 0.82, "min_shared_tables": 2},
}


def _deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


@dataclass
class Config:
    raw: dict
    config_path: Path

    @property
    def base_dir(self) -> Path:
        return self.config_path.parent

    def resolve(self, p: str) -> Path:
        path = Path(p)
        return path if path.is_absolute() else (self.base_dir / path)

    @property
    def systems(self) -> List[dict]:
        return self.raw["systems"]

    def fmt(self, system: dict) -> str:
        """Export format of a system: 'abapgit' (default) or 'chunks'."""
        return str(system.get("format", "abapgit")).lower()

    def unchunked_dir(self, system: dict) -> Path:
        return self.work_dir / "unchunked" / system["id"]

    def system_root(self, system: dict) -> Path:
        """Folder the pipeline reads objects from. For chunked exports that is the rebuilt
        abapGit-style tree under work/unchunked/<SYS> (created by tools/unchunk.py)."""
        if self.fmt(system) == "chunks":
            return self.unchunked_dir(system)
        return self.resolve(system["root"])

    def roots(self) -> Dict[str, Path]:
        return {s["id"]: self.system_root(s) for s in self.systems}

    @property
    def work_dir(self) -> Path:
        return self.resolve(self.raw["work_dir"])

    @property
    def output_dir(self) -> Path:
        return self.resolve(self.raw["output_dir"])

    @property
    def taxonomy_path(self) -> Path:
        return self.resolve(self.raw["taxonomy"])

    @property
    def classification(self) -> dict:
        return self.raw["classification"]

    @property
    def review(self) -> dict:
        return self.raw["review"]

    @property
    def overlaps(self) -> dict:
        return self.raw["overlaps"]

    # Canonical file locations ------------------------------------------------------
    @property
    def inventory_file(self) -> Path:
        return self.work_dir / "inventory.jsonl"

    @property
    def evidence_file(self) -> Path:
        return self.work_dir / "evidence.jsonl"

    @property
    def auto_file(self) -> Path:
        return self.work_dir / "auto.json"

    @property
    def batches_dir(self) -> Path:
        return self.work_dir / "batches"

    @property
    def llm_dir(self) -> Path:
        return self.work_dir / "llm"

    @property
    def classification_file(self) -> Path:
        return self.work_dir / "classification.json"

    @property
    def overlaps_file(self) -> Path:
        return self.work_dir / "overlaps.json"

    @property
    def review_candidates_file(self) -> Path:
        return self.work_dir / "review_candidates.json"

    @property
    def review_patch_file(self) -> Path:
        return self.work_dir / "review_patch.json"

    @property
    def target_draft_file(self) -> Path:
        return self.work_dir / "target_draft.json"


def load_config(path: str | os.PathLike) -> Config:
    p = Path(path).resolve()
    with p.open("r", encoding="utf-8") as fh:
        raw = json.load(fh)
    merged = _deep_merge(DEFAULT_CONFIG, raw)
    if not merged["systems"]:
        raise SystemExit(f"config {p}: 'systems' is empty - add at least one system root")
    return Config(raw=merged, config_path=p)


def base_argparser(description: str) -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=description)
    ap.add_argument("--config", default="migration.config.json", help="path to migration.config.json")
    return ap


# --------------------------------------------------------------------------------------
# JSON / JSONL helpers
# --------------------------------------------------------------------------------------

def read_json(path: Path) -> Any:
    with Path(path).open("r", encoding="utf-8") as fh:
        return json.load(fh)


def write_json(path: Path, data: Any, indent: int = 2) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=indent, ensure_ascii=False)
        fh.write("\n")


def read_jsonl(path: Path) -> List[dict]:
    out: List[dict] = []
    with Path(path).open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def write_jsonl(path: Path, rows: Iterable[dict]) -> int:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False))
            fh.write("\n")
            n += 1
    return n


def read_text(path: Path) -> str:
    """Read a source file tolerating the encodings abapGit exports use."""
    data = Path(path).read_bytes()
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


# --------------------------------------------------------------------------------------
# Object keys and abapGit naming
# --------------------------------------------------------------------------------------

def make_key(system: str, obj_type: str, name: str) -> str:
    return f"{system}|{obj_type}|{name}"


def split_key(key: str) -> Tuple[str, str, str]:
    system, obj_type, name = key.split("|", 2)
    return system, obj_type, name


def decode_abapgit_name(raw: str) -> str:
    """abapGit encodes '/' (namespaces) as '#' and lowercases names."""
    return raw.replace("#", "/").upper()


def encode_for_match(name: str) -> str:
    return name.upper()


_FILENAME_RE = re.compile(r"^(?P<name>[^.]+)\.(?P<type>[a-z0-9]{4})(?:\.(?P<rest>.+))?$", re.IGNORECASE)


def parse_abapgit_filename(filename: str) -> Optional[Tuple[str, str, str]]:
    """Return (OBJECT_NAME, TYPE, rest) for an abapGit file name, or None.

    Examples:
        zcl_foo.clas.abap            -> ('ZCL_FOO', 'CLAS', 'abap')
        zcl_foo.clas.locals_imp.abap -> ('ZCL_FOO', 'CLAS', 'locals_imp.abap')
        zfg.fugr.z_fm_name.abap      -> ('ZFG', 'FUGR', 'z_fm_name.abap')
        package.devc.xml             -> ('PACKAGE', 'DEVC', 'xml')
        #ns#zcl_x.clas.abap          -> ('/NS/ZCL_X', 'CLAS', 'abap')
    """
    m = _FILENAME_RE.match(filename)
    if not m:
        return None
    return decode_abapgit_name(m.group("name")), m.group("type").upper(), (m.group("rest") or "")


# --------------------------------------------------------------------------------------
# ABAP source normalisation
# --------------------------------------------------------------------------------------

def strip_line_comment(line: str) -> str:
    """Remove a trailing '"' comment that is outside string literals."""
    in_str: Optional[str] = None
    for i, ch in enumerate(line):
        if in_str:
            if ch == in_str:
                in_str = None
        elif ch in ("'", "`", "|"):
            in_str = ch
        elif ch == '"':
            return line[:i]
    return line


def code_lines(text: str) -> Iterator[Tuple[int, str]]:
    """Yield (line_no, line) with full-line and trailing comments removed."""
    for i, raw in enumerate(text.splitlines(), start=1):
        s = raw.rstrip("\r\n")
        if s.startswith("*"):
            continue
        s = strip_line_comment(s)
        if s.strip():
            yield i, s


def comment_lines(text: str) -> Iterator[str]:
    """Yield the text of full-line comments (often the most informative header lines)."""
    for raw in text.splitlines():
        if raw.startswith("*"):
            body = raw.lstrip("*").strip()
            if body and not set(body) <= set("*-=_ "):
                yield body


def normalize_source(text: str) -> str:
    """Comment-free, whitespace-collapsed, upper-cased source for hashing and diffing."""
    parts = []
    for _, line in code_lines(text):
        parts.append(" ".join(line.split()).upper())
    return "\n".join(parts)


def source_hash(normalized: str) -> str:
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------------------
# Taxonomy
# --------------------------------------------------------------------------------------

@dataclass
class Taxonomy:
    nodes: Dict[str, dict]
    children: Dict[str, List[str]]
    weights: Dict[str, float]
    rules: List[dict]
    raw: dict = field(default_factory=dict)

    @property
    def top_level(self) -> List[str]:
        return [nid for nid, n in self.nodes.items() if not n.get("parent")]

    def parent(self, nid: str) -> Optional[str]:
        return self.nodes[nid].get("parent")

    def ancestors(self, nid: str) -> List[str]:
        """[module, submodule, area ...] path from root to nid inclusive."""
        path = []
        cur: Optional[str] = nid
        while cur:
            path.append(cur)
            cur = self.parent(cur)
        return list(reversed(path))

    def depth(self, nid: str) -> int:
        return len(self.ancestors(nid)) - 1

    def module_of(self, nid: str) -> str:
        return self.ancestors(nid)[0]

    def split(self, nid: Optional[str]) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        if not nid or nid not in self.nodes:
            return None, None, None
        path = self.ancestors(nid)
        return (path[0], path[1] if len(path) > 1 else None, path[2] if len(path) > 2 else None)

    def deepest(self, module: Optional[str], submodule: Optional[str], area: Optional[str]) -> Optional[str]:
        for cand in (area, submodule, module):
            if cand and cand in self.nodes:
                return cand
        return None

    def name(self, nid: str) -> str:
        return self.nodes.get(nid, {}).get("name", nid)

    def descendants(self, nid: str) -> List[str]:
        out = []
        stack = list(self.children.get(nid, []))
        while stack:
            c = stack.pop()
            out.append(c)
            stack.extend(self.children.get(c, []))
        return out

    def is_valid_path(self, module: Optional[str], submodule: Optional[str], area: Optional[str]) -> Tuple[bool, str]:
        if not module or module not in self.nodes or self.parent(module):
            return False, f"module '{module}' is not a top-level taxonomy node"
        if submodule:
            if submodule not in self.nodes or self.parent(submodule) != module:
                return False, f"submodule '{submodule}' is not a child of '{module}'"
        if area:
            if not submodule:
                return False, "area given without submodule"
            if area not in self.nodes or self.parent(area) != submodule:
                return False, f"area '{area}' is not a child of '{submodule}'"
        return True, ""


def load_taxonomy(path: Path) -> Taxonomy:
    """Load the taxonomy from a single json file OR a directory.

    Directory layout (recommended): nodes.json (+ weights) and any number of rules_*.json files,
    each holding {"rules": [...]}. All rule files are merged, so the team can add
    rules_custom.json without touching the shipped files.
    """
    path = Path(path)
    if path.is_dir():
        raw = read_json(path / "nodes.json")
        raw.setdefault("rules", [])
        for rf in sorted(path.glob("rules_*.json")):
            raw["rules"].extend(read_json(rf).get("rules", []))
    else:
        raw = read_json(path)
    nodes: Dict[str, dict] = {}
    children: Dict[str, List[str]] = {}
    for n in raw["nodes"]:
        nid = n["id"]
        if nid in nodes:
            raise SystemExit(f"taxonomy: duplicate node id {nid}")
        nodes[nid] = n
    for nid, n in nodes.items():
        p = n.get("parent")
        if p:
            if p not in nodes:
                raise SystemExit(f"taxonomy: node {nid} has unknown parent {p}")
            children.setdefault(p, []).append(nid)
    for r in raw.get("rules", []):
        if r["node"] not in nodes:
            raise SystemExit(f"taxonomy: rule refers to unknown node {r['node']}")
    return Taxonomy(nodes=nodes, children=children, weights=raw.get("weights", {}), rules=raw.get("rules", []), raw=raw)


# --------------------------------------------------------------------------------------
# Misc
# --------------------------------------------------------------------------------------

def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def pct(n: int, d: int) -> str:
    return f"{(100.0 * n / d):.1f}%" if d else "n/a"


def short(s: Optional[str], n: int = 80) -> str:
    s = (s or "").strip().replace("\n", " ")
    return s if len(s) <= n else s[: n - 1] + "…"
