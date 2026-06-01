#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import sys

from app.admin import AdminActionError, run_admin_action, token_record_id_from_google_sub
from app.persistence import get_store


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Manage persisted OAuth token records for BigQuery Readonly MCP.")
    parser.add_argument("action", choices=["disable", "force_reauth", "delete"], help="Admin action to apply.")
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--token-record-id", help="OAuth token record document ID.")
    target.add_argument("--google-sub", help="Google user subject. The script hashes this into the token record ID.")
    parser.add_argument("--reason", required=True, help="Human-readable reason for the action.")
    parser.add_argument("--actor-email", help="Operator email to include in audit logs.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    token_record_id = args.token_record_id or token_record_id_from_google_sub(args.google_sub)
    try:
        result = run_admin_action(
            action=args.action,
            store=get_store(),
            token_record_id=token_record_id,
            reason=args.reason,
            actor_email=args.actor_email,
        )
    except AdminActionError as exc:
        print(json.dumps({"success": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1

    print(json.dumps({"success": True, **result}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
