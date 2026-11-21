"""Admin CLI for hosted mode: users, tokens, export, deletion, backups.

    career-hub-admin create-user "Ada"        # prints the token ONCE; only its hash is stored
    career-hub-admin list-users
    career-hub-admin rotate-token 2
    career-hub-admin export 2 --out ada.json
    career-hub-admin delete-user 2 --yes
    career-hub-admin backup /backups/career-2026-11-18.db
"""

from __future__ import annotations

import argparse
import json
import sys

from . import db


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="career-hub-admin", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--db", help="database path (default: $CAREER_HUB_DB or ~/.career-hub/career.db)")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list-users")
    c = sub.add_parser("create-user")
    c.add_argument("name")
    r = sub.add_parser("rotate-token")
    r.add_argument("user_id", type=int)
    e = sub.add_parser("export")
    e.add_argument("user_id", type=int)
    e.add_argument("--out", help="write JSON here instead of stdout")
    d = sub.add_parser("delete-user")
    d.add_argument("user_id", type=int)
    d.add_argument("--yes", action="store_true", help="confirm permanent deletion")
    b = sub.add_parser("backup")
    b.add_argument("dest")
    a = p.parse_args(argv)

    con = db.connect(a.db)
    try:
        if a.cmd == "list-users":
            for u in db.list_users(con):
                print(f"{u['id']}\t{u['name']}\ttoken={'yes' if u['has_token'] else 'no'}")
        elif a.cmd == "create-user":
            uid, token = db.create_user(con, a.name)
            print(f"user {uid} created. Token (shown once, store it safely):\n{token}")
        elif a.cmd == "rotate-token":
            print(f"New token for user {a.user_id} (old one is now invalid):\n{db.rotate_token(con, a.user_id)}")
        elif a.cmd == "export":
            text = json.dumps(db.export_user(con, a.user_id), indent=2)
            if a.out:
                with open(a.out, "w", encoding="utf-8") as f:
                    f.write(text)
                print(f"wrote {a.out}")
            else:
                print(text)
        elif a.cmd == "delete-user":
            if not a.yes:
                print("refusing: this permanently deletes the user and all their data. Re-run with --yes.", file=sys.stderr)
                return 2
            print(json.dumps(db.delete_user(con, a.user_id)))
        elif a.cmd == "backup":
            print(f"backup written to {db.backup(con, a.dest)}")
    except ValueError as err:
        print(f"error: {err}", file=sys.stderr)
        return 1
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
