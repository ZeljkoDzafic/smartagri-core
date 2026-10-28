"""Optional accounts of the research web app (open core). Off by default.

SMARTAGRI_ACCOUNTS
    off       (default) local single-user use, exactly as before: no accounts, no cookies, everyone sees every parcel.
    optional  accounts with e-mail and password; anonymous work is temporary:
              - without an account, parcels belong to the browser session (an anonymous httpOnly session cookie,
                ended when the browser closes; the server stores only its sha256 in `core_owners`). They are not
                saved: anonymous parcels with their conversations and runs are purged after
                SMARTAGRI_ANON_TTL_HOURS (default 24) without activity (lazily on requests, or
                `python -m smartagri.research_api --purge-anonymous`);
              - to save them, the user creates an account or signs in: that browser's parcels are claimed;
              - each user sees only their own parcels; conversations and runs follow their parcel.
              Parcels stored before accounts were turned on have no owner and are not shown to anyone; the operator
              can hand them to an account: `python -m smartagri.research_api --assign-unowned EMAIL`.

E-mail verification and password reset are enabled only when SMTP is configured (SMARTAGRI_SMTP_HOST,
SMARTAGRI_SMTP_FROM and SMARTAGRI_PUBLIC_URL, which builds the links). Without SMTP an account works immediately.

Protection: scrypt password hashes (PBKDF2-SHA256 where the Python build has no scrypt), a minimum password length,
rate limits on every authentication endpoint and login throttling (fixed windows in the shared `rate_counters`
table, so several processes agree), generic error messages, HttpOnly + SameSite=Lax cookies (Secure on https),
host-only cookies (no Domain attribute), session expiry and logout, and CSRF protection of every state-changing API
request (double-submit token in the X-CSRF-Token header, plus an Origin check). The blind rating endpoints
(/api/eval/) are outside all of this: their screen, requests and protocol do not depend on accounts.

This module imports nothing from the product; the product's own account system is separate.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
import re
import secrets
import smtplib
import time
from email.message import EmailMessage
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import urlsplit

from ..store import Store, new_id, now_iso

log = logging.getLogger("smartagri.research_api.auth")

ENV_MODE = "SMARTAGRI_ACCOUNTS"
MODES = ("off", "optional")

# Cookies (host-only: no Domain attribute, so they never reach other subdomains).
SESSION_COOKIE = "sa_session"
BROWSER_COOKIE = "sa_browser"
CSRF_COOKIE = "sa_csrf"
CSRF_HEADER = "x-csrf-token"
BROWSER_DAYS = 365                      # the CSRF cookie; the anonymous browser cookie is a session cookie
TOUCH_EVERY_S = 300                     # an anonymous browser's activity is recorded at most every 5 minutes
PURGE_EVERY_S = 600                     # lazy purge of stale anonymous work at most every 10 minutes per process
# Paths outside accounts, cookies and CSRF: the blind rating protocol.
EXEMPT_PATHS = ("/api/eval/",)
UNSAFE_METHODS = ("POST", "PUT", "PATCH", "DELETE")

# The web-settings administrator role (stored in `instance_roles`, one document per user, set by the operator CLI only).
ADMIN_ROLE = "settings_admin"
OPERATOR = "operator-cli"

MIN_PASSWORD = 10
MAX_PASSWORD = 256
COMMON_PASSWORDS = frozenset([
    "1234567890", "123456789a", "qwertyuiop", "password12", "password123", "1q2w3e4r5t", "iloveyou12",
    "qwerty1234", "abcdefghij", "0123456789", "1111111111", "passw0rd12",
])
VERIFY_HOURS = 48
RESET_HOURS = 1

# action: (attempts, window seconds) per key kind. Every attempt counts; over the limit the request gets 429.
LIMITS: Dict[str, Dict[str, Tuple[int, int]]] = {
    "signin": {"email": (10, 15 * 60), "ip": (50, 15 * 60)},
    "signup": {"ip": (20, 60 * 60)},
    "forgot": {"email": (3, 60 * 60), "ip": (10, 60 * 60)},
    "reset": {"ip": (20, 60 * 60)},
    "verify": {"ip": (30, 60 * 60)},
    "delete": {"ip": (10, 15 * 60)},
}
AUTH_IP_LIMIT = (100, 15 * 60)          # all authentication requests of one address together
# SMARTAGRI_AUTH_RATE_FACTOR (integer, default 1) multiplies the per-address limits, e.g. for many users behind one NAT.

EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[^@\s]+$")


# ---------------------------------------------------------------------------------------------------- settings
def mode() -> str:
    value = (os.environ.get(ENV_MODE) or "off").strip().lower()
    if value not in MODES:
        raise ValueError("%s must be one of %s, not %r" % (ENV_MODE, "|".join(MODES), value))
    return value


def enabled() -> bool:
    return mode() == "optional"


def public_url() -> str:
    return (os.environ.get("SMARTAGRI_PUBLIC_URL") or "").strip().rstrip("/")


def anon_ttl_hours() -> float:
    try:
        value = float(os.environ.get("SMARTAGRI_ANON_TTL_HOURS") or 24)
    except ValueError:
        return 24.0
    return value if value > 0 else 24.0


def session_days() -> int:
    try:
        return max(1, int(os.environ.get("SMARTAGRI_SESSION_DAYS") or 30))
    except ValueError:
        return 30


def rate_factor() -> int:
    try:
        return max(1, int(os.environ.get("SMARTAGRI_AUTH_RATE_FACTOR") or 1))
    except ValueError:
        return 1


def smtp_configured() -> bool:
    return bool(os.environ.get("SMARTAGRI_SMTP_HOST") and os.environ.get("SMARTAGRI_SMTP_FROM") and public_url())


def _utc(ts: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def normalize_email(value: Any) -> str:
    return value.strip().lower() if isinstance(value, str) else ""


def _admin_addresses() -> frozenset:
    """The addresses listed in SMARTAGRI_ADMINS (lower case). Listing an address grants nothing by itself."""
    from ..web_settings.service import admin_emails
    return admin_emails()


# ---------------------------------------------------------------------------------------------------- passwords
SCRYPT_N, SCRYPT_R, SCRYPT_P, DKLEN = 2 ** 14, 8, 1, 32
PBKDF2_ITERATIONS = 600_000


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _scrypt(password: str, salt: bytes, n: int, r: int, p: int) -> Optional[bytes]:
    if hasattr(hashlib, "scrypt"):
        return hashlib.scrypt(password.encode("utf-8"), salt=salt, n=n, r=r, p=p, dklen=DKLEN, maxmem=128 * r * n * 2)
    try:                                   # Python builds linked against LibreSSL (macOS system Python 3.9)
        from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
    except ImportError:
        return None
    return Scrypt(salt=salt, length=DKLEN, n=n, r=r, p=p).derive(password.encode("utf-8"))


def hash_password(password: str) -> str:
    """scrypt$<n>$<r>$<p>$<salt>$<hash>, or pbkdf2_sha256$<iterations>$<salt>$<hash> where scrypt is unavailable."""
    salt = os.urandom(16)
    digest = _scrypt(password, salt, SCRYPT_N, SCRYPT_R, SCRYPT_P)
    if digest is not None:
        return "$".join(["scrypt", str(SCRYPT_N), str(SCRYPT_R), str(SCRYPT_P), _b64(salt), _b64(digest)])
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS, DKLEN)
    return "$".join(["pbkdf2_sha256", str(PBKDF2_ITERATIONS), _b64(salt), _b64(digest)])


def verify_password(password: Any, stored: Optional[str]) -> bool:
    if not stored or not isinstance(password, str):
        return False
    try:
        parts = stored.split("$")
        if parts[0] == "scrypt":
            n, r, p, salt, digest = parts[1:]
            got = _scrypt(password, _unb64(salt), int(n), int(r), int(p))
            if got is None:
                raise RuntimeError("scrypt is unavailable: install the `cryptography` package")
        elif parts[0] == "pbkdf2_sha256":
            iterations, salt, digest = parts[1:]
            got = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), _unb64(salt), int(iterations), DKLEN)
        else:
            return False
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(got, _unb64(digest))


def password_problem(password: Any, email: str = "") -> Optional[str]:
    if not isinstance(password, str) or len(password) < MIN_PASSWORD:
        return "Use a password of at least %d characters." % MIN_PASSWORD
    if len(password) > MAX_PASSWORD:
        return "The password is too long (at most %d characters)." % MAX_PASSWORD
    if password.lower() in COMMON_PASSWORDS or (email and password.lower() == email):
        return "This password is too easy to guess. Choose another one."
    return None


# ---------------------------------------------------------------------------------------------------- e-mail
class SmtpMailer:
    """Plain-text e-mail through SMTP (SMARTAGRI_SMTP_*). TLS: starttls (default), ssl or none."""

    def send(self, to: str, subject: str, text: str) -> None:
        msg = EmailMessage()
        msg["From"] = os.environ["SMARTAGRI_SMTP_FROM"]
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(text)
        host = os.environ["SMARTAGRI_SMTP_HOST"]
        tls = (os.environ.get("SMARTAGRI_SMTP_TLS") or "starttls").lower()
        port = int(os.environ.get("SMARTAGRI_SMTP_PORT") or (465 if tls == "ssl" else 587))
        cls = smtplib.SMTP_SSL if tls == "ssl" else smtplib.SMTP
        with cls(host, port, timeout=20) as smtp:
            if tls == "starttls":
                smtp.starttls()
            user = os.environ.get("SMARTAGRI_SMTP_USER")
            if user:
                smtp.login(user, os.environ.get("SMARTAGRI_SMTP_PASSWORD") or "")
            smtp.send_message(msg)


# ---------------------------------------------------------------------------------------------------- errors
class AuthError(Exception):
    def __init__(self, status: int, message: str, retry_after: Optional[int] = None):
        super().__init__(message)
        self.status = status
        self.message = message
        self.retry_after = retry_after


INVALID_LOGIN = "The email or password is incorrect."
INVALID_LINK = "This link is invalid or has expired."
THROTTLED = "Too many attempts. Please wait and try again later."


# ---------------------------------------------------------------------------------------------------- accounts
class Accounts:
    """Users, sessions, one-time tokens and parcel ownership on the shared Store (tables core_*)."""

    def __init__(self, store: Store, mailer: Any = None, clock: Callable[[], float] = time.time):
        self.store = store
        self.clock = clock
        self.mailer = mailer if mailer is not None else (SmtpMailer() if smtp_configured() else None)
        self._dummy_hash: Optional[str] = None
        self._last_purge = 0.0

    @property
    def email_enabled(self) -> bool:
        return self.mailer not in (None, False) and bool(public_url())

    # ------------------------------------------------------------ rate limits
    def limit(self, action: str, ip: str, email: str = "") -> None:
        now = self.clock()
        factor = rate_factor()
        checks = [("auth", "ip", ip, (AUTH_IP_LIMIT[0] * factor, AUTH_IP_LIMIT[1]))]
        for kind, (attempts, window) in LIMITS.get(action, {}).items():
            value = ip if kind == "ip" else email
            if value:
                checks.append((action, kind, value, (attempts * factor if kind == "ip" else attempts, window)))
        refused: Optional[int] = None
        for name, kind, value, (attempts, window) in checks:
            slot = int(now // window)
            key = "core:%s:%s:%s" % (name, kind, _sha(value)[:32])
            id_ = _sha("%s:%d" % (key, slot))
            n = self.store.increment("rate_counters", id_, {"key": key, "expires_at": _utc((slot + 1) * window)})
            if n > attempts:
                refused = max(refused or 0, int((slot + 1) * window - now) + 1)
        if int(now) % 97 == 0:
            self.store.delete_before("rate_counters", "expires_at", _utc(now))
        if refused is not None:
            raise AuthError(429, THROTTLED, refused)

    # ------------------------------------------------------------ users and sessions
    def _user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        rows = self.store.find("core_users", email=email)
        return rows[0] if rows else None

    @staticmethod
    def public(user: Dict[str, Any]) -> Dict[str, Any]:
        return {"id": user["id"], "email": user["email"], "verified": bool(user.get("verified")),
                "created_at": user["created_at"]}

    def _new_session(self, user: Dict[str, Any]) -> str:
        token = secrets.token_urlsafe(32)
        now = self.clock()
        self.store.put("core_sessions", {"id": _sha(token), "created_at": _utc(now), "user_id": user["id"],
                                         "expires_at": _utc(now + session_days() * 86400)})
        if int(now) % 31 == 0:
            self.store.delete_before("core_sessions", "expires_at", _utc(now))
        return token

    def session_user(self, token: Optional[str]) -> Optional[Dict[str, Any]]:
        if not token:
            return None
        row = self.store.get("core_sessions", _sha(token))
        if not row:
            return None
        if row["expires_at"] <= _utc(self.clock()):
            self.store.delete("core_sessions", id=row["id"])
            return None
        return self.store.get("core_users", row["user_id"])

    def signout(self, token: Optional[str]) -> None:
        if token:
            self.store.delete("core_sessions", id=_sha(token))

    def _new_token(self, user: Dict[str, Any], purpose: str, hours: int) -> str:
        token = secrets.token_urlsafe(32)
        self.store.put("core_tokens", {"id": _sha(token), "created_at": now_iso(), "user_id": user["id"],
                                       "purpose": purpose, "expires_at": _utc(self.clock() + hours * 3600)})
        return token

    def _use_token(self, token: Any, purpose: str) -> Optional[Dict[str, Any]]:
        if not isinstance(token, str) or not token:
            return None
        row = self.store.get("core_tokens", _sha(token))
        if not row or row.get("purpose") != purpose:
            return None
        self.store.delete("core_tokens", id=row["id"])                    # one-time
        if row["expires_at"] <= _utc(self.clock()):
            return None
        return self.store.get("core_users", row["user_id"])

    def _mail(self, user: Dict[str, Any], purpose: str) -> None:
        if not self.email_enabled:
            return
        # An address listed as an administrator is not confirmed by a "confirm" link: whoever signed up first chose the
        # password, and the mailbox owner who clicks would confirm it. The owner gets a link that sets the password.
        admin_link = purpose == "verify" and user["email"] in _admin_addresses()
        for kind in (("verify", "reset") if admin_link else (purpose,)):
            self.store.delete("core_tokens", user_id=user["id"], purpose=kind)   # only the newest link works
        if admin_link:
            token = self._new_token(user, "reset", RESET_HOURS)
            subject = "Set the password of your SmartAgri administrator account"
            text = ("Someone asked for a SmartAgri account with this address, which is listed as an administrator. "
                    "If it was you, choose your password by opening this link:\n\n%s/#/reset/%s\n\n"
                    "The link is valid for %d hour. Opening it replaces any password that was set at sign-up. If it "
                    "was not you, ignore this message." % (public_url(), token, RESET_HOURS))
        elif purpose == "verify":
            token = self._new_token(user, "verify", VERIFY_HOURS)
            subject = "Confirm your SmartAgri account"
            text = ("Confirm the email address of your SmartAgri account by opening this link:\n\n%s/#/verify/%s\n\n"
                    "The link is valid for %d hours. If you did not create an account, ignore this message."
                    % (public_url(), token, VERIFY_HOURS))
        else:
            token = self._new_token(user, "reset", RESET_HOURS)
            subject = "Reset your SmartAgri password"
            text = ("Choose a new password for your SmartAgri account by opening this link:\n\n%s/#/reset/%s\n\n"
                    "The link is valid for %d hour. If you did not ask for it, ignore this message; your password "
                    "stays as it is." % (public_url(), token, RESET_HOURS))
        try:
            self.mailer.send(user["email"], subject, text)
        except Exception as exc:                                       # the request still answers generically
            log.warning("e-mail to a user could not be sent: %s", exc.__class__.__name__)

    def signup(self, email_in: Any, password: Any, ip: str, browser_owner: Optional[str]
               ) -> Tuple[Dict[str, Any], Optional[str]]:
        """A new account. Without e-mail: a session (and the browser's parcels) at once. With e-mail: a verification
        link and no session; the same answer whether the address was free or not."""
        self.limit("signup", ip)
        email = normalize_email(email_in)
        if len(email) > 254 or not EMAIL_RE.match(email):
            raise AuthError(400, "Enter a valid email address.")
        problem = password_problem(password, email)
        if problem:
            raise AuthError(400, problem)
        existing = self._user_by_email(email)
        if existing is None and not self.email_enabled and email in _admin_addresses():
            # An address that the operator listed as an administrator cannot be proven by anyone here (no email), so it
            # is not open to sign-up: the operator creates that account on the server (`--make-admin`). The answer is
            # the one for a taken address.
            raise AuthError(409, "An account with this email already exists. Sign in instead.")
        if existing is not None:
            if self.email_enabled:
                return {"email": email, "verified": False}, None
            raise AuthError(409, "An account with this email already exists. Sign in instead.")
        user = {"id": new_id(), "created_at": now_iso(), "email": email, "password_hash": hash_password(password),
                "verified": False}
        try:
            self.store.put("core_users", user)
        except Exception:                                              # a concurrent sign-up with the same address
            if self._user_by_email(email) is None:
                raise
            if self.email_enabled:
                return {"email": email, "verified": False}, None
            raise AuthError(409, "An account with this email already exists. Sign in instead.")
        if self.email_enabled:
            self._mail(user, "verify")
            return self.public(user), None
        self.claim(browser_owner, user)
        return self.public(user), self._new_session(user)

    def signin(self, email_in: Any, password: Any, ip: str, browser_owner: Optional[str]
               ) -> Tuple[Dict[str, Any], str]:
        email = normalize_email(email_in)
        self.limit("signin", ip, email)
        user = self._user_by_email(email) if email else None
        if user is None:
            if self._dummy_hash is None:
                self._dummy_hash = hash_password(secrets.token_hex(8))
            verify_password(password if isinstance(password, str) else "", self._dummy_hash)   # same timing
            raise AuthError(401, INVALID_LOGIN)
        if not verify_password(password, user.get("password_hash")):
            raise AuthError(401, INVALID_LOGIN)
        if self.email_enabled and not user.get("verified"):
            self._mail(user, "verify")
            raise AuthError(403, "Confirm your email address first. We have sent you a new link.")
        self.claim(browser_owner, user)
        return self.public(user), self._new_session(user)

    def verify(self, token: Any, ip: str) -> Dict[str, Any]:
        self.limit("verify", ip)
        user = self._use_token(token, "verify")
        if user is None or user["email"] in _admin_addresses():     # an administrator address is confirmed by a reset only
            raise AuthError(400, INVALID_LINK)
        user.update(verified=True, verified_at=now_iso())
        self.store.put("core_users", user)
        return self.public(user)

    def forgot(self, email_in: Any, ip: str) -> None:
        if not self.email_enabled:
            raise AuthError(404, "Password reset is not available on this server.")
        email = normalize_email(email_in)
        self.limit("forgot", ip, email)
        user = self._user_by_email(email) if email else None
        if user is not None:
            self._mail(user, "reset")

    def reset(self, token: Any, password: Any, ip: str, browser_owner: Optional[str]) -> Tuple[Dict[str, Any], str]:
        if not self.email_enabled:
            raise AuthError(404, "Password reset is not available on this server.")
        self.limit("reset", ip)
        if not isinstance(token, str) or not token:
            raise AuthError(400, INVALID_LINK)
        row = self.store.get("core_tokens", _sha(token))
        user = self.store.get("core_users", row["user_id"]) if row and row.get("purpose") == "reset" else None
        problem = password_problem(password, user["email"] if user else "")
        if problem and user is not None:
            raise AuthError(400, problem)                       # the link stays usable for a better password
        user = self._use_token(token, "reset")
        if user is None:
            raise AuthError(400, INVALID_LINK)
        user.update(password_hash=hash_password(password), verified=True,
                    verified_at=user.get("verified_at") or now_iso())
        self.store.put("core_users", user)
        self.store.delete("core_sessions", user_id=user["id"])         # every other session ends
        self.claim(browser_owner, user)
        return self.public(user), self._new_session(user)

    def delete_account(self, user: Dict[str, Any], password: Any, ip: str) -> int:
        """Delete the account and everything it owns: parcels with their profiles, conversations and runs, the
        ownership rows, sessions and one-time tokens. Returns the number of deleted parcels."""
        self.limit("delete", ip, user["email"])
        if not verify_password(password, user.get("password_hash")):
            raise AuthError(401, "The password is incorrect.")
        owner = user_owner(user)
        ids = self.parcel_ids(owner)
        for pid in ids:
            self.store.delete_parcel(pid)
        self.store.delete("core_owners", owner=owner)
        self.store.delete("settings_user", id=user["id"])                 # web settings: current overrides (history keeps the id)
        self.store.delete("core_tokens", user_id=user["id"])
        self.store.delete("core_sessions", user_id=user["id"])
        self.store.delete("core_users", id=user["id"])
        return len(ids)

    # ------------------------------------------------------------ administrators of the web settings
    def _role_doc(self, user_id: str) -> Dict[str, Any]:
        return self.store.get("instance_roles", user_id) or {"id": user_id, "created_at": now_iso(), "user_id": user_id,
                                                              "roles": [], "history": []}

    def has_admin_role(self, user_id: Optional[str]) -> bool:
        return bool(user_id) and ADMIN_ROLE in (self.store.get("instance_roles", user_id) or {}).get("roles", [])

    def is_admin(self, user: Optional[Dict[str, Any]]) -> bool:
        """The administrator role is held by (a) an account the operator promoted on the server (`--make-admin`), or
        (b) an account whose address is listed in SMARTAGRI_ADMINS AND was confirmed through the link sent to that
        mailbox (an account that nobody confirmed, which is every account when SMTP is off, never qualifies)."""
        if not user:
            return False
        if self.has_admin_role(user["id"]):
            return True
        return bool(user.get("verified")) and normalize_email(user.get("email")) in _admin_addresses()

    def _audit_role(self, user: Dict[str, Any], action: str, detail: str) -> None:
        now = now_iso()
        self.store.put("settings_audit", {"id": new_id(), "created_at": now, "at": now, "scope": "admin_role",
                                          "scope_id": user["id"], "actor": OPERATOR, "param": "admin_role",
                                          "old": action == "revoke", "new": action == "grant", "action": action,
                                          "version": 0, "reason": detail})

    def admin_needs_password(self, email_in: str, reset_password: bool = False) -> bool:
        """True when make_admin creates or takes over the account (a password must be given)."""
        user = self._user_by_email(normalize_email(email_in))
        return reset_password or user is None or not user.get("verified")

    def make_admin(self, email_in: str, password: Optional[str] = None, reset_password: bool = False) -> Dict[str, Any]:
        """Operator task (runs on the server, never over HTTP): give the account the administrator role.
        - no such account: it is created (a password is needed) and counts as confirmed by the operator;
        - an account that was never confirmed (every account when SMTP is off, so possibly someone else's, signed up
          with the owner's address first): the operator takes it over: a new password is required, the old one stops
          working, every session and pending link of the account ends;
        - an account confirmed through its mailbox: the role is added, nothing else changes (with `reset_password` the
          operator also replaces the password, for an administrator who lost it on a server without email).
        The change is written to the audit log (actor `operator-cli`)."""
        email = normalize_email(email_in)
        if len(email) > 254 or not EMAIL_RE.match(email):
            raise AuthError(400, "Enter a valid email address.")
        user = self._user_by_email(email)
        outcome = "role added to an account confirmed through its mailbox"
        if user is None or not user.get("verified") or reset_password:
            problem = password_problem(password, email) if password is not None else "A password is required."
            if problem:
                raise AuthError(400, problem)
            if user is None:
                user = {"id": new_id(), "created_at": now_iso(), "email": email, "verified": True}
                outcome = "account created by the operator"
            else:
                outcome = ("unconfirmed account taken over by the operator (password replaced, sessions ended)"
                           if not user.get("verified") else "password replaced by the operator (sessions ended)")
                self.store.delete("core_sessions", user_id=user["id"])
                self.store.delete("core_tokens", user_id=user["id"])
            user.update(password_hash=hash_password(password), verified=True, verified_at=now_iso(),
                        verified_by="operator")
            self.store.put("core_users", user)
        doc = self._role_doc(user["id"])
        if ADMIN_ROLE not in doc["roles"]:
            before = list(doc["roles"])
            doc["roles"] = sorted(set(before) | {ADMIN_ROLE})
            doc["history"] = list(doc.get("history", [])) + [{"at": now_iso(), "by": OPERATOR, "from": before,
                                                              "to": doc["roles"]}]
            self.store.put("instance_roles", doc)
            self._audit_role(user, "grant", outcome)
        elif reset_password:
            self._audit_role(user, "password_reset", outcome)
        return {"email": email, "outcome": outcome, "user_id": user["id"]}

    def revoke_admin(self, email_in: str) -> Dict[str, Any]:
        """Operator task: remove the administrator role (and end the account's sessions). An address that is still
        listed in SMARTAGRI_ADMINS and was confirmed through its mailbox stays an administrator until it is removed
        from the list; the result says so."""
        email = normalize_email(email_in)
        user = self._user_by_email(email)
        if user is None:
            raise AuthError(404, "No account with this email.")
        doc = self._role_doc(user["id"])
        had = ADMIN_ROLE in doc["roles"]
        if had:
            doc["roles"] = [r for r in doc["roles"] if r != ADMIN_ROLE]
            doc["history"] = list(doc.get("history", [])) + [{"at": now_iso(), "by": OPERATOR, "from": sorted(doc["roles"] + [ADMIN_ROLE]),
                                                              "to": doc["roles"]}]
            self.store.put("instance_roles", doc)
            self._audit_role(user, "revoke", "role removed by the operator")
        self.store.delete("core_sessions", user_id=user["id"])
        return {"email": email, "had_role": had, "still_listed": bool(user.get("verified")) and email in _admin_addresses()}

    # ------------------------------------------------------------ ownership
    def own(self, parcel_id: str, owner: str) -> None:
        row = {"id": parcel_id, "created_at": now_iso(), "owner": owner, "kind": "parcel"}
        if owner.startswith("b:"):
            row["touched_at"] = _utc(self.clock())
        self.store.put("core_owners", row)

    # ------------------------------------------------------------ temporary anonymous work
    def touch(self, owner: Optional[str]) -> None:
        """Record activity of an anonymous browser (at most every TOUCH_EVERY_S, one statement)."""
        if not owner or not owner.startswith("b:"):
            return
        now = self.clock()
        self.store._exec(self.store._q("UPDATE core_owners SET touched_at = ? WHERE owner = ? AND "
                                       "(touched_at IS NULL OR touched_at < ?)"),
                         (_utc(now), owner, _utc(now - TOUCH_EVERY_S)))

    def purge_anonymous(self, ttl_hours: Optional[float] = None) -> int:
        """Delete anonymous parcels (with profiles, conversations and runs) idle longer than the TTL. Account-owned
        parcels and parcels without an owner are never touched. Returns the number of deleted parcels."""
        now = self.clock()
        self._last_purge = now
        cutoff = _utc(now - (ttl_hours if ttl_hours is not None else anon_ttl_hours()) * 3600)
        # rows written before touched_at existed get a full TTL from now
        self.store._exec(self.store._q("UPDATE core_owners SET touched_at = ? WHERE owner LIKE ? AND "
                                       "touched_at IS NULL"), (_utc(now), "b:%"))
        stale = self.store._rows(self.store._q("SELECT id FROM core_owners WHERE owner LIKE ? AND kind = ? "
                                               "AND touched_at < ?"), ("b:%", "parcel", cutoff))
        for row in stale:
            self.store.delete_parcel(row["id"])
            self.store._exec(self.store._q("DELETE FROM core_owners WHERE id = ? AND owner LIKE ?"), (row["id"], "b:%"))
        return len(stale)

    def maybe_purge(self) -> None:
        if self.clock() - self._last_purge >= PURGE_EVERY_S:
            try:
                self.purge_anonymous()
            except Exception as exc:                                   # never fail a request because of cleanup
                log.warning("purge of anonymous parcels failed: %s", exc.__class__.__name__)

    def owns(self, owner: Optional[str], parcel_id: Optional[str]) -> bool:
        if not owner or not parcel_id:
            return False
        row = self.store.get("core_owners", parcel_id)
        return bool(row) and hmac.compare_digest(row["owner"], owner)

    def parcel_ids(self, owner: str) -> List[str]:
        return [r["id"] for r in self.store.find("core_owners", owner=owner, kind="parcel")]

    def parcels(self, owner: str) -> List[Dict[str, Any]]:
        ids = self.parcel_ids(owner)
        return self.store.find_in("parcels", "id", ids, "seq DESC") if ids else []

    def claim(self, browser_owner: Optional[str], user: Dict[str, Any]) -> int:
        """Move the parcels of an anonymous browser to the account (on sign-up and sign-in)."""
        if not browser_owner or not browser_owner.startswith("b:"):
            return 0
        rows = self.store.find("core_owners", owner=browser_owner)
        for row in rows:
            row["owner"] = user_owner(user)
            row.pop("touched_at", None)                                   # saved: no longer temporary
            self.store.put("core_owners", row)
        return len(rows)

    def assign_unowned(self, email_in: str) -> int:
        """Operator task: give every parcel without an owner (stored before accounts were turned on) to an account."""
        user = self._user_by_email(normalize_email(email_in))
        if user is None:
            raise AuthError(404, "No account with this email.")
        owned = {r["id"] for r in self.store.find("core_owners")}
        n = 0
        for parcel in self.store.list_parcels():
            if parcel["id"] not in owned:
                self.own(parcel["id"], user_owner(user))
                n += 1
        return n


def user_owner(user: Dict[str, Any]) -> str:
    return "u:" + user["id"]


def browser_owner(token: str) -> str:
    return "b:" + _sha(token)


# ---------------------------------------------------------------------------------------------------- HTTP helpers
def secure_request(scheme: str) -> bool:
    return scheme == "https" or os.environ.get("SMARTAGRI_COOKIE_SECURE") == "1" or public_url().startswith("https:")


def origin_allowed(origin: Optional[str], scheme: str, host: Optional[str]) -> bool:
    """No Origin header (non-browser clients, same-origin GETs) passes; a present Origin must be this server's."""
    if origin is None:
        return True
    allowed = set()
    if host:
        allowed.add("%s://%s" % (scheme, host.lower()))
    if public_url():
        u = urlsplit(public_url())
        allowed.add("%s://%s" % (u.scheme, u.netloc.lower()))
    return origin.strip().lower().rstrip("/") in allowed
