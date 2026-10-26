"""python -m smartagri.research_api [--host 127.0.0.1] [--port 8100] [--assign-unowned EMAIL]"""
from __future__ import annotations

import argparse
import sys


def main() -> None:
    p = argparse.ArgumentParser(prog="smartagri.research_api")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8100)
    p.add_argument("--assign-unowned", metavar="EMAIL",
                   help="accounts on (SMARTAGRI_ACCOUNTS=optional): give every parcel stored before accounts were "
                        "turned on to the account with this email, then exit")
    a = p.parse_args()
    if a.assign_unowned:
        from ..store import make_store
        from .auth import Accounts, AuthError
        try:
            n = Accounts(make_store(), mailer=False).assign_unowned(a.assign_unowned)
        except AuthError as exc:
            sys.exit(exc.message)
        print("%d parcel(s) assigned to %s" % (n, a.assign_unowned.strip().lower()))
        return
    import uvicorn

    from .app import create_app
    uvicorn.run(create_app(), host=a.host, port=a.port)


if __name__ == "__main__":
    main()
