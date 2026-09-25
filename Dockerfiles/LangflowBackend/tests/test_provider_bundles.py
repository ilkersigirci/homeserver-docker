"""Tests that the stock provider bundles used to reach LiteLLM are installed."""

import unittest
from importlib.metadata import entry_points


class ProviderBundleTests(unittest.TestCase):
    def test_openai_compatible_bundles_are_installed(self):
        extensions = {point.name for point in entry_points(group="langflow.extensions")}
        self.assertIn("lfx-openai", extensions)
        self.assertIn("lfx-openai-compatible", extensions)


if __name__ == "__main__":
    unittest.main()
