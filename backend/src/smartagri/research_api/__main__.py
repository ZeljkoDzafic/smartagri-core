"""python -m smartagri.research_api [--host 127.0.0.1] [--port 8100] [--assign-unowned EMAIL] [--purge-anonymous]
[--make-admin EMAIL [--password-stdin] [--reset-password]] [--revoke-admin EMAIL]"""
from __future__ import annotations

import argparse
import sys


def _admin_command(a: argparse.Namespace) -> int:
    from ..store import make_store
    from .auth import Accounts, AuthError
    accounts = Accounts(make_store(), mailer=False)
    try:
        if a.revoke_admin:
            res = accounts.revoke_admin(a.revoke_admin)
            print("%s: %s" % (res["email"], "administrator role removed" if res["had_role"] else "had no administrator role"))
            if res["still_listed"]:
                print("Note: this address is still listed in SMARTAGRI_ADMINS and confirmed, so it stays an administrator "
                      "until you remove it from the list.")
            return 0
        password = None
        if accounts.admin_needs_password(a.make_admin, a.reset_password):
            if a.password_stdin:
                password = sys.stdin.readline().rstrip("\r\n")
            else:
                import getpass
                print("The account does not exist or was never confirmed by email: choose its password (it replaces any "
                      "password set before).")
                password = getpass.getpass("Password: ")
                if getpass.getpass("Repeat: ") != password:
                    print("The passwords differ.")
                    return 1
        res = accounts.make_admin(a.make_admin, password, a.reset_password)
    except AuthError as exc:
        print(exc.message)
        return 1
    print("%s: administrator (%s)" % (res["email"], res["outcome"]))
    return 0


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
    p.add_argument("--make-admin", metavar="EMAIL",
                   help="accounts on: give the account this email the administrator role of the web settings, then "
                        "exit. Run on the server. An account that does not exist is created, and one that was never "
                        "confirmed by email is taken over: both ask for a (new) password. Written to the audit log")
    p.add_argument("--revoke-admin", metavar="EMAIL",
                   help="accounts on: remove the administrator role of this account and end its sessions, then exit")
    p.add_argument("--password-stdin", action="store_true",
                   help="with --make-admin: read the password from standard input instead of asking for it")
    p.add_argument("--reset-password", action="store_true",
                   help="with --make-admin: also replace the password of an existing account (an administrator who lost "
                        "it, on a server without email) and end its sessions")
    a = p.parse_args()
    if a.make_admin or a.revoke_admin:
        sys.exit(_admin_command(a))
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
    # The client address behind a proxy is decided by the app (SMARTAGRI_TRUSTED_PROXIES), not by uvicorn, which with
    # FORWARDED_ALLOW_IPS=* takes the leftmost X-Forwarded-For entry, an address the client chose.
    uvicorn.run(create_app(), host=a.host, port=a.port, proxy_headers=False)


if __name__ == "__main__":
    main()
