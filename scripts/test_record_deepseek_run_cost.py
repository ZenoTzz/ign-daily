import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

import record_deepseek_run_cost


class RecordRunCostTests(unittest.TestCase):
    def test_missing_balance_snapshots_do_not_aggregate_unbounded_history(self):
        output = io.StringIO()
        with patch.object(record_deepseek_run_cost, "read_json", return_value={}), \
             patch("sys.argv", ["record_deepseek_run_cost.py", "test-run"]), \
             redirect_stdout(output):
            self.assertEqual(0, record_deepseek_run_cost.main())
        self.assertIn("RUN_COST_SKIP", output.getvalue())


if __name__ == "__main__":
    unittest.main()
