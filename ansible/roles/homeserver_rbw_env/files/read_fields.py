"""Resolve one host's environment mappings using rbw on the Ansible controller."""

import json
import subprocess
import sys
from functools import cache


def rbw_get(item, *options):
    return subprocess.run(
        ["rbw", "get", *options, "--", item],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=True,
    ).stdout.decode("utf-8")


@cache
def item_fields(item):
    entry = json.loads(rbw_get(item, "--raw"))
    # Cache custom fields and built-in names only, never the full vault record.
    return entry["fields"], set(entry["data"] or {}) | {"notes"}


def read_field(item, name):
    custom, builtin = item_fields(item)
    key = name.casefold()
    if key not in builtin:
        # rbw --field picks the first substring match for custom fields.
        matches = [f for f in custom if key in (f["name"] or "").casefold()]
        if matches:
            exact = [f for f in matches if key == f["name"].casefold()]
            if len(exact) != 1:
                raise ValueError("Missing or ambiguous custom field")
            return exact[0]["value"]

    # Let rbw interpret built-in fields and aliases, including generated TOTP.
    return rbw_get(item, "--field", name).removesuffix("\n")


def main():
    values = {}
    for key, mapping in json.load(sys.stdin).items():
        try:
            name = mapping.get("field", key)
            if not name:
                raise ValueError("Empty field name")
            value = read_field(mapping["item"], name)
            if not isinstance(value, str) or not value:
                raise ValueError("Empty field value")
        except (OSError, subprocess.CalledProcessError, KeyError, TypeError, ValueError):
            sys.exit(f"Could not read a unique, nonempty vault field for {key}.")
        values[key] = value
    json.dump(values, sys.stdout)


if __name__ == "__main__":
    main()
