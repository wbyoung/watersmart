"""Update the manifest file."""

import json
import sys


def validate_coverage():
    coverage = json.loads(sys.stdin.read())
    totals = coverage["totals"]

    def exit_unless(key, value):
        if totals[key] != value:
            print(f"Coverage check: totals.{key} is expected to be {value}")
            sys.exit(1)

    exit_unless("percent_covered", 100.0)
    exit_unless("missing_lines", 0)
    exit_unless("num_partial_branches", 0)
    exit_unless("missing_branches", 0)

    print("Coverage check completed")


validate_coverage()
