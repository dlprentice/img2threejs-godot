#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

import jsonschema


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a JSON document against a Draft 2020-12 schema.")
    parser.add_argument("schema", type=Path)
    parser.add_argument("document", type=Path)
    args = parser.parse_args()
    schema = json.loads(args.schema.read_text(encoding="utf-8"))
    document = json.loads(args.document.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator.check_schema(schema)
    validator = jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker())
    errors = sorted(validator.iter_errors(document), key=lambda error: list(error.absolute_path))
    result = {
        "status": "pass" if not errors else "fail",
        "schema": str(args.schema.resolve()),
        "document": str(args.document.resolve()),
        "errorCount": len(errors),
        "errors": [
            {"path": "/" + "/".join(str(value) for value in error.absolute_path), "message": error.message}
            for error in errors
        ],
    }
    print(json.dumps(result, indent=2))
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
