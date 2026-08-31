import io
import os
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

import deepseek_balance


class DeepSeekBalanceTests(unittest.TestCase):
    def test_generic_provider_skips_deepseek_balance_endpoint(self):
        env = {
            "TRANSLATOR_API_KEY": "test-key",
            "TRANSLATOR_BASE_URL": "https://api.apikey.fun/v1",
        }
        output = io.StringIO()
        with patch.dict(os.environ, env, clear=False), redirect_stdout(output):
            self.assertEqual(0, deepseek_balance.main())
        self.assertIn("API_BALANCE_SKIP", output.getvalue())


if __name__ == "__main__":
    unittest.main()
