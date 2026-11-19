"""The page's shared ranking: one tie-break for the headline, "Best days this week" and "Right now".
Runs site/calcs.js in node with a stub `dash`; skipped when node is not installed."""
import os
import shutil
import subprocess
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
CALCS = os.path.abspath(os.path.join(HERE, "..", "..", "site", "calcs.js"))
NODE = shutil.which("node")


@unittest.skipUnless(NODE, "node is not installed; the ranking checks need it")
class SharedRanking(unittest.TestCase):
    def test_tied_fixtures(self):
        run = subprocess.run([NODE, os.path.join(HERE, "rank_test.js"), CALCS], capture_output=True, text=True, timeout=60)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)


if __name__ == "__main__":
    unittest.main()
