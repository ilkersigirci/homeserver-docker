import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "files"))
import read_fields


class VaultFieldSelection(unittest.TestCase):
    def setUp(self):
        read_fields.item_fields.cache_clear()

    @patch.object(read_fields, "rbw_get")
    def test_overlapping_custom_field_names(self, get):
        get.return_value = json.dumps({
            "data": None,
            "fields": [
                {"name": "LANGFUSE_SALT_NEXTAUTH_SECRET", "value": "long"},
                {"name": "LANGFUSE_SALT", "value": "short"},
            ],
        })
        self.assertEqual(read_fields.read_field("stack", "langfuse_salt"), "short")
        self.assertEqual(read_fields.read_field("stack", "LANGFUSE_SALT_NEXTAUTH_SECRET"), "long")
        with self.assertRaises(ValueError):
            read_fields.read_field("stack", "LANGFUSE")
        get.assert_called_once_with("stack", "--raw")

    @patch.object(read_fields, "rbw_get")
    def test_duplicate_custom_field_names_fail_closed(self, get):
        get.return_value = json.dumps({
            "data": {},
            "fields": [{"name": "Token", "value": "one"}, {"name": "TOKEN", "value": "two"}],
        })
        with self.assertRaises(ValueError):
            read_fields.read_field("stack", "TOKEN")

    @patch.object(read_fields, "rbw_get")
    def test_builtin_uses_rbw_and_preserves_stored_newline(self, get):
        get.side_effect = [
            json.dumps({"data": {"password": "value"}, "fields": []}),
            "value\n\n",
        ]
        self.assertEqual(read_fields.read_field("login", "password"), "value\n")
        get.assert_called_with("login", "--field", "password")
