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

    def test_01_inventory(self):
        out = run("inventory.py")
        self.assertIn("INVENTORY_OK", out)
        inv = {r["key"]: r for r in self.load_jsonl(self.work / "inventory.jsonl")}
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
        results = [{"key": k, "module": "FI", "submodule": "FI-GL", "confidence": 0.7, "purpose": "mock", "rationale": "mock"} for k in keys]
        results.append({"key": "SYSA|CLAS|NOPE", "module": "XX", "confidence": 2, "purpose": ""})
        (self.work / "llm" / f"{b['batch_id']}.json").write_text(json.dumps({"batch_id": b["batch_id"], "model": "mock", "results": results}), encoding="utf-8")
        out = run("prep_batches.py")
        self.assertIn("batches_done=1", out)
        out = run("merge.py")
        self.assertIn("MERGE_OK", out)
        self.assertIn("llm_invalid=1", out)
        cls = json.loads((self.work / "classification.json").read_text(encoding="utf-8"))
        by = {o["key"]: o for o in cls["objects"]}
        self.assertEqual(len(by), 11)
        self.assertEqual(by["SYSA|PROG|ZHR_TS_REPORT"]["source"], "heuristic")
        self.assertEqual(by[keys[0]]["source"], "llm")
        self.assertNotIn("missing", {o["source"] for o in cls["objects"] if o["key"] in keys})
        out = run("overlaps.py")
        self.assertIn("OVERLAPS_OK", out)
        ov = json.loads((self.work / "overlaps.json").read_text(encoding="utf-8"))
        same = {e["name"]: e for e in ov["same_name"]}
        self.assertEqual(same["ZCL_PO_CHECK"]["status"], "diverged")
        self.assertEqual(same["ZCL_UTIL_STRING"]["status"], "identical")
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
        self.assertTrue((self.out / "objects.csv").exists())
        out = run("target_skeleton.py")
        self.assertIn("TARGET_OK", out)
        self.assertIn("resolve=", out)
        out = run("status.py")
        self.assertIn("NEXT:", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
