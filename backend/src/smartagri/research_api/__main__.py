"""python -m smartagri.research_api [--host 127.0.0.1] [--port 8100] [--assign-unowned EMAIL] [--purge-anonymous]"""
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
    p.add_argument("--purge-anonymous", action="store_true",
                   help="delete anonymous (not saved) parcels idle longer than SMARTAGRI_ANON_TTL_HOURS (default 24), "
                        "with their conversations and runs, then exit")
    a = p.parse_args()
    if a.purge_anonymous:
        from ..store import make_store
        from .auth import Accounts, anon_ttl_hours
        n = Accounts(make_store(), mailer=False).purge_anonymous()
        print("%d anonymous parcel(s) idle for more than %g h deleted" % (n, anon_ttl_hours()))
        return
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
