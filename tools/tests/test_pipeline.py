"""End-to-end test of the deterministic pipeline on the synthetic fixtures.

Runs: make_fixtures -> inventory -> evidence -> prep_batches -> (mock llm result) -> merge -> overlaps
      -> review_candidates -> render_html -> render_tree -> target_skeleton -> status

Usage:  py tools/tests/test_pipeline.py
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent
CFG = HERE / "fixtures" / "migration.config.json"
TMP = HERE / "_tmp"


def run(script: str, *args: str) -> str:
    cmd = [sys.executable, "-I", str(TOOLS / script), "--config", str(CFG), *args]
    res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    if res.returncode != 0:
        raise AssertionError(f"{script} failed:\nSTDOUT {res.stdout}\nSTDERR {res.stderr}")
    return res.stdout


class PipelineTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if TMP.exists():
            shutil.rmtree(TMP)
        subprocess.run([sys.executable, "-I", str(HERE / "make_fixtures.py")], check=True)
        cls.work = TMP / "work"
        cls.out = TMP / "output"

    def load_jsonl(self, p):
        return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]

    def test_00_unchunk(self):
        out = run("unchunk.py", "--inspect", "SYSC")
        self.assertIn("object_comment", out)
        out = run("unchunk.py")
        self.assertIn("UNCHUNK_OK", out)
        self.assertIn("unresolved=1", out)
        rows = self.load_jsonl(self.work / "unchunked" / "SYSC" / "_manifest.jsonl")
        got = {(r["type"], r["name"]) for r in rows}
        self.assertEqual(got, {("PROG", "ZHR_TS_REPORT"), ("CLAS", "ZCL_UTIL_STRING"), ("CLAS", "ZCL_PO_CHECK"),
                               ("CLAS", "ZCL_DOC_HELPER"), ("FUGR", "ZWF_HR")})
        fugr = next(r for r in rows if r["type"] == "FUGR")
        self.assertEqual(fugr["fms"], ["Z_WF_HR_START"])
        # the class cut into DEFINITION + IMPLEMENTATION segments must come back as one file
        src = (self.work / "unchunked" / "SYSC" / "zchunked" / "zcl_po_check.clas.abap").read_text(encoding="utf-8")
        self.assertIn("DEFINITION", src)
        self.assertIn("IMPLEMENTATION", src)
        # second run: nothing changed -> packages_unchanged
        out = run("unchunk.py")
        self.assertIn("unchanged_packages=1", out)
        # resolve the leftover segment via a mocked splitter answer
        unres = json.loads((self.work / "unchunk_unresolved.json").read_text(encoding="utf-8"))["segments"]
        self.assertEqual(len(unres), 1)
        (self.work / "unchunk_resolution.json").write_text(json.dumps({"results": [
            {"segment": unres[0]["id"], "type": "PROG", "name": "ZFRAGMENT"}]}), encoding="utf-8")
        out = run("unchunk.py", "--apply-resolution")
        self.assertIn("applied=1", out)
        self.assertTrue((self.work / "unchunked" / "SYSC" / "zchunked" / "zfragment.prog.abap").exists())
        self.assertEqual(json.loads((self.work / "unchunk_unresolved.json").read_text(encoding="utf-8"))["segments"], [])

    def test_01_inventory(self):
        run("unchunk.py")
        out = run("inventory.py")
        self.assertIn("INVENTORY_OK", out)
        inv = {r["key"]: r for r in self.load_jsonl(self.work / "inventory.jsonl")}
        self.assertIn("SYSC|PROG|ZHR_TS_REPORT", inv)
        self.assertEqual(inv["SYSC|PROG|ZHR_TS_REPORT"]["source_hash"], inv["SYSA|PROG|ZHR_TS_REPORT"]["source_hash"])
        self.assertEqual([c["name"] for c in inv["SYSC|FUGR|ZWF_HR"]["children"]], ["Z_WF_HR_START"])
        inv = {k: v for k, v in inv.items() if not k.startswith("SYSC|")}
        self.assertIn("SYSA|PROG|ZHR_TS_REPORT", inv)
        self.assertEqual(inv["SYSA|PROG|ZHR_TS_REPORT"]["description"], "Timesheet hours per employee")
        self.assertEqual(inv["SYSA|PROG|ZHR_TS_REPORT"]["extra"]["ldb"], "PNP")
        self.assertEqual(inv["SYSA|PROG|ZHR_TS_REPORT"]["package"], "ZMISC")
        self.assertEqual(inv["SYSA|PROG|ZHR_TS_REPORT"]["package_desc"], "Miscellaneous developments")
        fugr = inv["SYSA|FUGR|ZWF_HR"]
        self.assertEqual([c["name"] for c in fugr["children"]], ["Z_WF_HR_START"])
        self.assertIn("Z_WF_HR_START", fugr["fm_sources"])
        self.assertEqual(len(inv), 11)

    def test_02_evidence(self):
        run("unchunk.py")
        run("inventory.py")
        out = run("evidence.py")
        self.assertIn("EVIDENCE_OK", out)
        ev = {r["key"]: r for r in self.load_jsonl(self.work / "evidence.jsonl")}
        ts = ev["SYSA|PROG|ZHR_TS_REPORT"]
        self.assertEqual(ts["module"], "HCM", ts["top"])
        self.assertEqual(ts["submodule"], "HCM-PT", ts["signals"][:5])
        self.assertEqual(ts["area"], "HCM-PT-TS")
        self.assertEqual(ts["decision"], "auto")
        self.assertIn("SYSA|TABL|ZHRTS_LOG", ts["uses"])
        self.assertIn("SYSA|CLAS|ZCL_UTIL_STRING", ts["uses"])
        # propagation: the Z table and the helper class inherit HCM from the report
        self.assertEqual(ev["SYSA|TABL|ZHRTS_LOG"]["module"], "HCM")
        self.assertTrue(ev["SYSA|TABL|ZHRTS_LOG"]["via_propagation"])
        self.assertEqual(ev["SYSA|CLAS|ZCL_UTIL_STRING"]["module"], "HCM")
        self.assertEqual(ev["SYSA|CLAS|ZCL_PO_CHECK"]["module"], "MM")
        self.assertEqual(ev["SYSA|CLAS|ZCL_PO_CHECK"]["submodule"], "MM-PUR")
        self.assertEqual(ev["SYSA|FUGR|ZWF_HR"]["module"], "HCM", ev["SYSA|FUGR|ZWF_HR"]["top"])
        self.assertIn(ev["SYSA|FUGR|ZWF_HR"]["submodule"], ("HCM-WF", "HCM-PA", None))
        self.assertEqual(ev["SYSB|PROG|ZFI_POST"]["module"], "FI")
        self.assertEqual(ev["SYSA|CLAS|ZCL_DOC_HELPER"]["decision"], "needs_llm", ev["SYSA|CLAS|ZCL_DOC_HELPER"]["top"])

    def test_03_batches_merge_overlaps_render(self):
        run("unchunk.py")
        run("inventory.py")
        run("evidence.py")
        out = run("prep_batches.py")
        self.assertIn("PREP_OK", out)
        batches = sorted((self.work / "batches").glob("*.json"))
        self.assertGreaterEqual(len(batches), 1)
        b = json.loads(batches[0].read_text(encoding="utf-8"))
        keys = [o["key"] for o in b["objects"]]
        self.assertIn("SYSA|CLAS|ZCL_DOC_HELPER", [k for bb in batches for k in [o["key"] for o in json.loads(bb.read_text(encoding="utf-8"))["objects"]]])
        self.assertTrue(all("excerpt" in o and o["excerpt"] for o in b["objects"]))
        # mock LLM result incl. one invalid record
        (self.work / "llm").mkdir(exist_ok=True)
        results = [{"key": k, "module": "FI", "submodule": "FI-GL", "confidence": 0.7, "purpose": "mock", "rationale": "mock",
                    "secondary": [{"module": "MM", "submodule": "MM-PUR", "role": "context", "rationale": "reads EKKO"},
                                  {"module": "XX", "role": "supporting"}]} for k in keys]
        results[0]["process"] = [{"process": "R2R.CLOSE", "role": "direct", "rationale": "closing report"},
                                 {"process": "NOPE.X", "role": "direct"}]
        results.append({"key": "SYSA|CLAS|NOPE", "module": "XX", "confidence": 2, "purpose": ""})
        (self.work / "llm" / f"{b['batch_id']}.json").write_text(json.dumps({"batch_id": b["batch_id"], "model": "mock", "results": results}), encoding="utf-8")
        out = run("prep_batches.py")
        self.assertIn("batches_done=1", out)
        out = run("merge.py")
        self.assertIn("MERGE_OK", out)
        self.assertIn("llm_invalid=1", out)
        cls = json.loads((self.work / "classification.json").read_text(encoding="utf-8"))
        by = {o["key"]: o for o in cls["objects"]}
        self.assertEqual(len([k for k in by if not k.startswith("SYSC|")]), 11)
        self.assertEqual(by["SYSA|PROG|ZHR_TS_REPORT"]["source"], "heuristic")
        self.assertEqual(by[keys[0]]["source"], "llm")
        # contract fields: secondary (invalid entry dropped, valid one kept), outcome, review_state, provenance
        self.assertEqual(by[keys[0]]["secondary"], [{"module": "MM", "submodule": "MM-PUR", "area": None, "role": "context", "rationale": "reads EKKO"}])
        self.assertEqual(by[keys[0]]["outcome"], "classified")
        self.assertEqual(by[keys[0]]["review_state"], "proposed")
        self.assertEqual(by[keys[0]]["provenance"]["model"], "mock")
        self.assertEqual(by[keys[0]]["provenance"]["prompt_version"], "classifier-1.1")
        nodes_version = json.loads((TOOLS / "taxonomy" / "nodes.json").read_text(encoding="utf-8"))["version"]
        self.assertEqual(by[keys[0]]["provenance"]["taxonomy_version"], nodes_version)
        self.assertTrue(all(o["outcome"] in cls["outcomes"] for o in cls["objects"]))
        # business process: explicit LLM list wins (invalid id dropped), otherwise crosswalk from module + secondary
        self.assertEqual([(p["process"], p["role"], p["basis"]) for p in by[keys[0]]["process"]], [("R2R.CLOSE", "direct", "llm")])
        self.assertEqual(by["SYSA|PROG|ZHR_TS_REPORT"]["process"][0]["process"], "H2R.TIME")
        self.assertEqual(by["SYSA|PROG|ZHR_TS_REPORT"]["process"][0]["basis"], "crosswalk")
        self.assertEqual(by["SYSA|CLAS|ZCL_PO_CHECK"]["process"][0]["process"], "S2P.PROCURE")
        self.assertEqual([p["process"] for p in by["SYSB|PROG|ZFI_POST"]["process"]], ["R2R.LEDGER"])
        if len(keys) > 1:   # second llm object: crosswalk FI-GL -> R2R.LEDGER plus MM-PUR secondary -> S2P.PROCURE (context)
            self.assertEqual([(p["process"], p["role"]) for p in by[keys[1]]["process"]], [("R2R.LEDGER", "direct"), ("S2P.PROCURE", "context")])
        self.assertEqual(cls["process_catalog"]["source"], "local")
        # fallback: an object with no derivable process lands in the explicit revisit bucket
        sys.path.insert(0, str(TOOLS))
        import merge as merge_mod  # noqa: E402
        from common import load_processes, load_taxonomy  # noqa: E402
        cat = load_processes(TOOLS / "taxonomy")
        tax = load_taxonomy(TOOLS / "taxonomy")
        fb = merge_mod.derive_process({"module": "UNKNOWN", "submodule": None, "area": None, "secondary": [], "source": "llm"}, cat, tax)
        self.assertEqual([(p["process"], p["basis"]) for p in fb], [("OTH.UNMAPPED", "default")])
        # review patch sets review_state
        (self.work / "review_patch.json").write_text(json.dumps([
            {"key": keys[0], "module": "FI", "submodule": "FI-GL", "confidence": 0.9, "purpose": "reviewed purpose", "rationale": "review: confirmed"}]), encoding="utf-8")
        out = run("merge.py", "--apply-review")
        self.assertIn("MERGE_OK", out)
        by = {o["key"]: o for o in json.loads((self.work / "classification.json").read_text(encoding="utf-8"))["objects"]}
        self.assertEqual(by[keys[0]]["review_state"], "reviewed")
        self.assertEqual(by[keys[0]]["reviewed_by"], "abap-reviewer")
        self.assertEqual(by[keys[0]]["provenance"]["model"], "mock")   # provenance of the underlying llm result is kept
        self.assertNotIn("missing", {o["source"] for o in cls["objects"] if o["key"] in keys})
        out = run("overlaps.py")
        self.assertIn("OVERLAPS_OK", out)
        ov = json.loads((self.work / "overlaps.json").read_text(encoding="utf-8"))
        same = {e["name"]: e for e in ov["same_name"]}
        self.assertEqual(same["ZCL_PO_CHECK"]["status"], "diverged")
        self.assertEqual(same["ZCL_UTIL_STRING"]["status"], "identical")
        self.assertEqual(same["ZHR_TS_REPORT"]["status"], "identical", same["ZHR_TS_REPORT"])  # SYSA vs rebuilt SYSC
        self.assertTrue(any({s["a"], s["b"]} == {"SYSA|PROG|ZHR_TS_REPORT", "SYSB|PROG|ZHR_TS_REPORT_B"} for s in ov["similar"]), ov["similar"])
        run("review_candidates.py")
        self.assertTrue((self.work / "review_candidates.json").exists())
        out = run("render_html.py")
        self.assertIn("EXPLORER_OK", out)
        html = (self.out / "explorer.html").read_text(encoding="utf-8")
        self.assertIn("ZHR_TS_REPORT", html)
        self.assertNotIn("</script>\"", html.split('id="data"')[1].split("</script>")[0])
        out = run("render_tree.py")
        self.assertIn("TREE_OK", out)
        tree = (self.out / "tree.md").read_text(encoding="utf-8")
        self.assertIn("## HCM", tree)
        self.assertIn("HCM-PT-TS", tree)
        self.assertIn("# Custom code by business process", tree)
        self.assertIn("H2R.TIME", tree)
        csv_head = (self.out / "objects.csv").read_text(encoding="utf-8-sig").splitlines()[0]
        for col in ("secondary", "process_primary", "process_all", "outcome", "review_state", "prompt_version", "taxonomy_version"):
            self.assertIn(col, csv_head)
        # per-system outputs and per-system batch ids
        self.assertTrue(b["batch_id"].startswith(("SYSA-", "SYSB-", "SYSC-")), b["batch_id"])
        out = run("render_html.py", "--systems", "SYSA")
        self.assertIn("explorer_SYSA.html", out)
        html_a = (self.out / "explorer_SYSA.html").read_text(encoding="utf-8")
        self.assertIn("ZHR_TS_REPORT", html_a)
        self.assertNotIn("ZFI_POST", html_a)
        out = run("render_tree.py", "--systems", "SYSB")
        self.assertIn("objects_SYSB.csv", out)
        self.assertIn("ZFI_POST", (self.out / "tree_SYSB.md").read_text(encoding="utf-8"))
        out = run("target_skeleton.py")
        self.assertIn("TARGET_OK", out)
        self.assertIn("resolve=", out)
        out = run("status.py")
        self.assertIn("NEXT:", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
