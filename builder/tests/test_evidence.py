"""The page's field-evidence rule: when a place has no (or thin) public reports of a mushroom, the page says so.
Runs site/calcs.js in node with a stub `dash`; skipped when node is not installed."""
import os
import shutil
import subprocess
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
CALCS = os.path.abspath(os.path.join(HERE, "..", "..", "site", "calcs.js"))
NODE = shutil.which("node")


@unittest.skipUnless(NODE, "node is not installed; the evidence checks need it")
class FieldEvidence(unittest.TestCase):
    def test_rule(self):
        run = subprocess.run([NODE, os.path.join(HERE, "evidence_test.js"), CALCS], capture_output=True, text=True, timeout=60)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)


if __name__ == "__main__":
    unittest.main()
