#!/usr/bin/env python3
"""
issue_license.py - Manually grant a licence key, until a payment provider's
webhook does this automatically.

STATUS.md item 10 ("Build /license/verify") is the read side, and it is
done — server/app.py's endpoint checks a key against exactly what this
script writes. What is not done, and cannot be built without the account
this needs, is the *write* side: automatically issuing a key the moment
someone pays. STATUS.md item 11 is signing up with Paddle for that reason;
once that account exists, its webhook payload format decides what a real
`server/paddle_webhook.py` looks like, and this script's job — INSERT a row
into license_keys — is exactly what that webhook handler would do on a
successful-payment event instead of a human typing a command.

Until then, this is how to grant a key by hand: to yourself for testing, or
to someone who paid you some other way in the meantime.

Usage:
    python -m server.issue_license KEY --plan premium --days 365
    python -m server.issue_license KEY --plan free
    python -m server.issue_license --check KEY
"""

import argparse
import os
import sys
import time

from server.db import ServerDatabase


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("key", help="The licence key to issue or check.")
    parser.add_argument("--plan", choices=("free", "premium"),
                         help="Plan to grant. Required unless --check.")
    parser.add_argument("--days", type=int, default=365,
                         help="Days until this key expires (default 365). "
                              "0 means it never expires.")
    parser.add_argument("--check", action="store_true",
                         help="Look the key up instead of issuing it.")
    parser.add_argument("--data-dir",
                         default=os.environ.get("PROTBOT_SERVER_DATA_DIR", "."),
                         help="Where protbot_server.db lives (same as the "
                              "running server's PROTBOT_SERVER_DATA_DIR).")
    args = parser.parse_args(argv)

    db = ServerDatabase(args.data_dir)

    if args.check:
        row = db.license_lookup(args.key)
        if not row:
            print(f"{args.key}: not found")
            return 1
        print(f"{args.key}: plan={row['plan']} expires_at={row['expires_at']}")
        return 0

    if not args.plan:
        parser.error("--plan is required unless --check is given.")

    expires_at = 0.0 if args.days <= 0 else time.time() + args.days * 86400
    db.license_issue(args.key, args.plan, expires_at)
    print(f"Issued {args.key}: plan={args.plan} "
          f"expires_at={'never' if not expires_at else expires_at}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
