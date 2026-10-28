"""Security of the public web app (S1 admin bootstrap, S3 forwarded addresses, S4-S6 input limits, S10 headers).
Each test states the attack and the expected outcome; they run offline."""
import io
import json
import math
import socket
import sys
import threading
import time
import urllib.request

import pytest
from fastapi.testclient import TestClient

from smartagri.research_api import auth, guards, proxy
from smartagri.research_api.app import create_app
from smartagri.research_api.service import ResearchService

from test_web_settings import CAP, PW, Outbox, _accounts_app, _browser, _send, _signup  # noqa: F401
from test_web_settings import env  # noqa: F401  (fixture)

OWNER = "owner@farm.example"
PW_ATTACKER = "attacker-field-2026"
PW_OWNER = "owner-field-2026-ok"
GLOBAL = {"values": {CAP: 30}, "reason": "x"}


def _is_admin(c):
    return c.get("/api/settings").json()["capabilities"]["is_admin"]


def _signin(app, email, password):
    c = _browser(app)
    return c, _send(c, "POST", "/api/auth/signin", {"email": email, "password": password})


# ------------------------------------------------------------------------------------------------ S1, SMTP off
def test_s1_an_attacker_who_registers_the_admin_address_first_gets_no_admin_rights(env, monkeypatch):
    """Accounts optional, SMTP off, the owner's address is in SMARTAGRI_ADMINS. The attacker signs up with it first
    (before the fix: 201, is_admin true, PUT /api/settings/global 200, the real owner got 409)."""
    app, _ = _accounts_app(env, monkeypatch, admins=OWNER)
    attacker = _browser(app)
    r = _send(attacker, "POST", "/api/auth/signup", {"email": OWNER.upper(), "password": PW_ATTACKER})
    assert r.status_code == 409 and env.find("core_users") == []                 # the address is reserved: no account
    assert _is_admin(attacker) is False
    assert _send(attacker, "PUT", "/api/settings/global", GLOBAL).status_code == 403
    assert _send(attacker, "PUT", "/api/settings/limits", {"limits": {CAP: {"max": 60}}, "reason": "x"}).status_code == 403


def test_s1_the_owner_is_not_locked_out_the_operator_creates_the_account(env, monkeypatch):
    app, _ = _accounts_app(env, monkeypatch, admins=OWNER)
    _send(_browser(app), "POST", "/api/auth/signup", {"email": OWNER, "password": PW_ATTACKER})      # refused
    accounts = auth.Accounts(env, mailer=False)
    assert accounts.admin_needs_password(OWNER) is True
    res = accounts.make_admin(OWNER, PW_OWNER)
    assert "created" in res["outcome"]
    c, r = _signin(app, OWNER, PW_OWNER)
    assert r.status_code == 200 and _is_admin(c) is True
    assert _send(c, "PUT", "/api/settings/global", GLOBAL).status_code == 200
    assert _signin(app, OWNER, PW_ATTACKER)[1].status_code == 401


def test_s1_an_account_taken_before_the_address_was_listed_is_taken_over_by_the_operator(env, monkeypatch):
    """The attacker's account exists (made before SMARTAGRI_ADMINS listed the address, or on a server that did not
    reserve it). Listing it does not promote it, and the operator's command replaces the password and ends sessions."""
    app, _ = _accounts_app(env, monkeypatch, admins="")
    attacker = _signup(app, OWNER)
    monkeypatch.setenv("SMARTAGRI_ADMINS", OWNER)
    assert _is_admin(attacker) is False and _send(attacker, "PUT", "/api/settings/global", GLOBAL).status_code == 403
    accounts = auth.Accounts(env, mailer=False)
    with pytest.raises(auth.AuthError):
        accounts.make_admin(OWNER)                                       # no password given: nothing changes
    assert _is_admin(attacker) is False
    res = accounts.make_admin(OWNER, PW_OWNER)
    assert "taken over" in res["outcome"]
    assert attacker.get("/api/auth/me").json()["user"] is None           # the attacker's session ended
    assert _signin(app, OWNER, PW)[1].status_code == 401                 # and so did the password
    owner, r = _signin(app, OWNER, PW_OWNER)
    assert r.status_code == 200 and _is_admin(owner) is True and len(env.find("core_users")) == 1


def test_s1_an_administrator_who_lost_the_password_is_reset_by_the_operator(env, monkeypatch):
    app, _ = _accounts_app(env, monkeypatch, admins="")
    accounts = auth.Accounts(env, mailer=False)
    accounts.make_admin(OWNER, PW_OWNER)
    owner, r = _signin(app, OWNER, PW_OWNER)
    assert r.status_code == 200
    assert accounts.admin_needs_password(OWNER) is False and accounts.admin_needs_password(OWNER, True) is True
    accounts.make_admin(OWNER)                                           # the role is there: nothing changes
    assert _signin(app, OWNER, PW_OWNER)[1].status_code == 200
    with pytest.raises(auth.AuthError):
        accounts.make_admin(OWNER, None, reset_password=True)            # a reset needs a new password
    res = accounts.make_admin(OWNER, PW_ATTACKER, reset_password=True)
    assert "password replaced" in res["outcome"]
    assert owner.get("/api/auth/me").json()["user"] is None              # sessions ended
    assert _signin(app, OWNER, PW_OWNER)[1].status_code == 401
    assert _is_admin(_signin(app, OWNER, PW_ATTACKER)[0]) is True and len(env.find("core_users")) == 1
    assert [a["action"] for a in env.find("settings_audit", scope="admin_role")] == ["grant", "password_reset"]   # both logged


def test_s1_listing_an_address_alone_never_makes_an_unconfirmed_account_an_administrator(env, monkeypatch):
    app, _ = _accounts_app(env, monkeypatch, admins="")
    c = _signup(app, OWNER)
    monkeypatch.setenv("SMARTAGRI_ADMINS", OWNER + ", other@farm.example")
    assert _is_admin(c) is False
    assert auth.Accounts(env, mailer=False).is_admin(env.find("core_users")[0]) is False


def test_s1_operator_grant_and_revoke_are_in_the_audit_log(env, monkeypatch):
    app, _ = _accounts_app(env, monkeypatch, admins="")
    _signup(app, "someone@farm.example")
    accounts = auth.Accounts(env, mailer=False)
    accounts.make_admin("someone@farm.example", PW_OWNER)
    admin, r = _signin(app, "someone@farm.example", PW_OWNER)
    assert r.status_code == 200 and _is_admin(admin) is True
    rows = admin.get("/api/settings/audit?scope=admin_role").json()["items"]
    assert [(i["action"], i["param"], i["actor"], i["new"]) for i in rows] == [("grant", "admin_role", "operator (server command)", True)]
    assert "taken over" in rows[0]["reason"]
    res = accounts.revoke_admin("someone@farm.example")
    assert res == {"email": "someone@farm.example", "had_role": True, "still_listed": False}
    assert _send(admin, "PUT", "/api/settings/global", GLOBAL).status_code in (401, 403)   # its sessions ended with the role
    again, _ = _signin(app, "someone@farm.example", PW_OWNER)
    assert _is_admin(again) is False
    _signup(app, "plain@farm.example")
    assert accounts.revoke_admin("plain@farm.example")["had_role"] is False        # idempotent, nothing logged
    with pytest.raises(auth.AuthError):
        accounts.revoke_admin("nobody@farm.example")
    audit = env.find("settings_audit", scope="admin_role")
    assert [a["action"] for a in audit] == ["grant", "revoke"] and all(a["actor"] == auth.OPERATOR for a in audit)


def test_s1_the_role_does_not_leak_to_other_accounts(env, monkeypatch):
    app, _ = _accounts_app(env, monkeypatch, admins="")
    auth.Accounts(env, mailer=False).make_admin("boss@farm.example", PW_OWNER)
    user = _signup(app, "user@farm.example")
    assert _is_admin(user) is False and _send(user, "PUT", "/api/settings/global", GLOBAL).status_code == 403


def test_s1_the_command_line(env, monkeypatch, capsys):
    from smartagri.research_api import __main__ as cli
    monkeypatch.setattr("smartagri.store.make_store", lambda *a, **k: env)
    monkeypatch.setattr(sys, "argv", ["x", "--make-admin", OWNER, "--password-stdin"])
    monkeypatch.setattr(sys, "stdin", io.StringIO(PW_OWNER + "\n"))
    with pytest.raises(SystemExit) as e:
        cli.main()
    assert e.value.code == 0 and "administrator (account created by the operator)" in capsys.readouterr().out
    assert auth.Accounts(env, mailer=False).is_admin(env.find("core_users")[0]) is True
    monkeypatch.setattr(sys, "argv", ["x", "--make-admin", OWNER])           # confirmed by the operator: no password asked
    with pytest.raises(SystemExit) as e:
        cli.main()
    assert e.value.code == 0
    monkeypatch.setenv("SMARTAGRI_ADMINS", OWNER)
    monkeypatch.setattr(sys, "argv", ["x", "--revoke-admin", OWNER])
    with pytest.raises(SystemExit) as e:
        cli.main()
    out = capsys.readouterr().out
    assert e.value.code == 0 and "administrator role removed" in out and "still listed" in out
    monkeypatch.setattr(sys, "argv", ["x", "--revoke-admin", "nobody@farm.example"])
    with pytest.raises(SystemExit) as e:
        cli.main()
    assert e.value.code == 1


# ------------------------------------------------------------------------------------------------ S1, SMTP on
def test_s1_with_smtp_the_address_is_confirmed_by_setting_the_password_through_the_mailbox(env, monkeypatch):
    monkeypatch.setenv("SMARTAGRI_PUBLIC_URL", "https://app.example.org")
    outbox = Outbox()
    monkeypatch.setenv("SMARTAGRI_ACCOUNTS", "optional")
    monkeypatch.setenv("SMARTAGRI_ADMINS", OWNER)
    app = create_app(ResearchService(env), auth.Accounts(env, mailer=outbox))
    https = "https://app.example.org"

    def browser():
        c = TestClient(app, base_url=https)
        c.get("/api/auth/me")
        return c
    attacker = browser()
    r = _send(attacker, "POST", "/api/auth/signup", {"email": OWNER, "password": PW_ATTACKER})
    assert r.status_code == 201 and r.json()["verify_sent"] is True
    assert _send(attacker, "POST", "/api/auth/signin", {"email": OWNER, "password": PW_ATTACKER}).status_code == 403
    assert _is_admin(attacker) is False
    # the mail goes to the real mailbox and carries a set-password link, not a confirm link
    assert outbox.sent[-1]["to"] == OWNER and "/#/reset/" in outbox.sent[-1]["text"] and "/#/verify/" not in outbox.sent[-1]["text"]
    token = outbox.token("reset")
    assert _send(attacker, "POST", "/api/auth/verify", {"token": token}).status_code == 400    # not usable to confirm
    owner = browser()
    assert _send(owner, "POST", "/api/auth/password/reset", {"token": token, "password": PW_OWNER}).status_code == 200
    assert _is_admin(owner) is True
    assert _send(owner, "PUT", "/api/settings/global", GLOBAL).status_code == 200
    assert _send(browser(), "POST", "/api/auth/signin", {"email": OWNER, "password": PW_ATTACKER}).status_code == 401
    assert _send(browser(), "POST", "/api/auth/signin", {"email": OWNER, "password": PW_OWNER}).status_code == 200


def test_s1_with_smtp_an_attacker_who_signed_up_first_does_not_keep_the_account_after_a_password_reset(env, monkeypatch):
    """The owner who never saw the sign-up mail uses 'forgot password': the link sets the password and confirms."""
    monkeypatch.setenv("SMARTAGRI_PUBLIC_URL", "https://app.example.org")
    outbox = Outbox()
    monkeypatch.setenv("SMARTAGRI_ACCOUNTS", "optional")
    monkeypatch.setenv("SMARTAGRI_ADMINS", OWNER)
    app = create_app(ResearchService(env), auth.Accounts(env, mailer=outbox))
    c = TestClient(app, base_url="https://app.example.org")
    c.get("/api/auth/me")
    _send(c, "POST", "/api/auth/signup", {"email": OWNER, "password": PW_ATTACKER})
    assert _send(c, "POST", "/api/auth/signup", {"email": OWNER, "password": PW_OWNER}).status_code == 201     # same answer
    _send(c, "POST", "/api/auth/password/forgot", {"email": OWNER})
    owner = TestClient(app, base_url="https://app.example.org")
    owner.get("/api/auth/me")
    assert _send(owner, "POST", "/api/auth/password/reset", {"token": outbox.token("reset"), "password": PW_OWNER}).status_code == 200
    assert _is_admin(owner) is True and len(env.find("core_users")) == 1


# ------------------------------------------------------------------------------------------------ S3 forwarded addresses
def test_s3_the_client_address_is_the_rightmost_address_that_is_not_a_trusted_proxy():
    nets = proxy.trusted_proxies("127.0.0.1, 10.0.0.0/8")
    spoof = ["203.0.113.77, 198.51.100.9"]                       # the client wrote the first, nginx appended the second
    assert proxy.client_address("127.0.0.1", spoof, nets) == ("198.51.100.9", True)
    assert proxy.client_address("127.0.0.1", ["203.0.113.77", "198.51.100.9, 10.1.2.3"], nets) == ("198.51.100.9", True)
    assert proxy.client_address("127.0.0.1", [], nets) == ("127.0.0.1", True)                  # no header: the proxy itself
    assert proxy.client_address("127.0.0.1", ["garbage"], nets) == ("127.0.0.1", True)         # not an address: keep the peer
    assert proxy.client_address("::ffff:127.0.0.1", spoof, nets) == ("198.51.100.9", True)
    # a peer that is not a trusted proxy cannot say who the client is
    assert proxy.client_address("198.51.100.9", ["203.0.113.77"], nets) == ("198.51.100.9", False)
    assert proxy.client_address("198.51.100.9", ["203.0.113.77"], []) == ("198.51.100.9", False)   # the default: trust nobody
    assert proxy.client_address("testclient", ["203.0.113.77"], nets) == ("testclient", False)
    with pytest.raises(ValueError):
        proxy.trusted_proxies("*")                                                              # never "every peer"
    with pytest.raises(ValueError):
        proxy.trusted_proxies("localhost")


def _post_json(url, body, headers):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=dict({"Content-Type": "application/json"}, **headers))
    try:
        return urllib.request.urlopen(req).status
    except urllib.error.HTTPError as exc:
        return exc.code


def _serve(app, **uvicorn_options):
    import uvicorn
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error", **uvicorn_options))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            return server, thread, port
        time.sleep(0.05)
    raise RuntimeError("the test server did not start")


def test_s3_a_client_cannot_spoof_its_address_past_the_per_address_limits_over_real_http(env, monkeypatch):
    """The audit's attack through a real server: a proxy on the same host appends the real address to the client's own
    X-Forwarded-For. With uvicorn's FORWARDED_ALLOW_IPS=* the client chose the address (203.0.113.n) and the limit of
    20 sign-ups per address per hour never applied; now the address is the one the proxy saw."""
    monkeypatch.setenv(proxy.ENV_TRUSTED, "127.0.0.1")
    app, _ = _accounts_app(env, monkeypatch, admins="")
    server, thread, port = _serve(app, proxy_headers=False)          # exactly what `python -m smartagri.research_api` does
    try:
        url = "http://127.0.0.1:%d/api/auth/signup" % port
        codes = []
        for i in range(24):
            spoof = {"X-Forwarded-For": "203.0.113.%d, 198.51.100.9" % (i + 1), "Origin": "http://127.0.0.1:%d" % port,
                     "Cookie": "sa_csrf=t", "X-CSRF-Token": "t"}
            codes.append(_post_json(url, {"email": "not-an-email", "password": "x"}, spoof))
        assert codes[:20] == [400] * 20 and set(codes[20:]) == {429}, codes
        # another real client is counted on its own
        other = {"X-Forwarded-For": "203.0.113.1, 198.51.100.10", "Origin": "http://127.0.0.1:%d" % port,
                 "Cookie": "sa_csrf=t", "X-CSRF-Token": "t"}
        assert _post_json(url, {"email": "not-an-email", "password": "x"}, other) == 400
    finally:
        server.should_exit = True
        thread.join(5)


def _scope_through(middleware_nets, peer, headers):
    """The scope that the app behind TrustedProxyMiddleware sees for a request from `peer` with these headers."""
    import asyncio
    got = {}

    async def inner(scope, receive, send):
        got.update(client=scope["client"][0], scheme=scope["scheme"])
    scope = {"type": "http", "client": (peer, 5000), "scheme": "http",
             "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()]}
    asyncio.run(proxy.TrustedProxyMiddleware(inner, middleware_nets)(scope, None, None))
    return got


def test_s3_nothing_is_trusted_by_default_and_the_scheme_follows_a_trusted_proxy_only(monkeypatch):
    monkeypatch.delenv(proxy.ENV_TRUSTED, raising=False)
    headers = {"X-Forwarded-For": "203.0.113.77", "X-Forwarded-Proto": "https"}
    assert _scope_through(proxy.trusted_proxies(), "198.51.100.9", headers) == {"client": "198.51.100.9", "scheme": "http"}
    nets = proxy.trusted_proxies("198.51.100.9")
    assert _scope_through(nets, "198.51.100.9", headers) == {"client": "203.0.113.77", "scheme": "https"}
    assert _scope_through(nets, "198.51.100.8", headers) == {"client": "198.51.100.8", "scheme": "http"}   # another peer
    assert _scope_through(nets, "198.51.100.9", dict(headers, **{"X-Forwarded-Proto": "javascript"}))["scheme"] == "http"


def test_s3_the_server_command_hands_the_address_decision_to_the_app(monkeypatch):
    from smartagri.research_api import __main__ as cli
    import uvicorn
    called = {}
    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: called.update(kw))
    monkeypatch.setattr(sys, "argv", ["x"])
    cli.main()
    assert called["proxy_headers"] is False


# ------------------------------------------------------------------------------------------------ S4 request limits
def _circle(n, lat=44.9, lon=17.3, r=0.001):
    ring = [[lon + r * math.cos(2 * math.pi * k / n), lat + r * math.sin(2 * math.pi * k / n)] for k in range(n)]
    return {"type": "Polygon", "coordinates": [ring + [ring[0]]]}


def _user(app):
    return _signup(app, "grower@farm.example")


def test_s4_a_body_over_the_limit_is_refused_before_it_is_read(env, monkeypatch):
    app, _ = _accounts_app(env, monkeypatch, admins="")
    c = _user(app)
    huge = {"name": "x" * (guards.DEFAULT_MAX_BODY + 10), "geometry": _circle(8)}
    r = _send(c, "POST", "/api/parcels", huge)
    assert r.status_code == 413 and env.list_parcels() == []
    # no declared length (chunked): counted while it arrives
    def chunks():
        yield b'{"name": "'
        for _ in range(40):
            yield b"x" * 10000
        yield b'"}'
    r = c.post("/api/parcels", content=chunks(), headers={"X-CSRF-Token": c.cookies.get("sa_csrf"), "Content-Type": "application/json"})
    assert r.status_code == 413
    monkeypatch.setenv("SMARTAGRI_MAX_BODY_BYTES", "100")
    assert guards.max_body_bytes() == 100
    monkeypatch.setenv("SMARTAGRI_MAX_BODY_BYTES", "garbage")
    assert guards.max_body_bytes() == guards.DEFAULT_MAX_BODY


def test_s4_json_that_is_too_deep_or_not_json_at_all_is_a_400(env, monkeypatch):
    app, _ = _accounts_app(env, monkeypatch, admins="")
    c = _user(app)
    deep = "[" * 200 + "]" * 200
    for body in ('{"name": %s}' % deep, '{"name": NaN}', '{"name": -Infinity}', '{"name": [Infinity]}'):
        r = c.post("/api/parcels", content=body, headers={"X-CSRF-Token": c.cookies.get("sa_csrf"), "Content-Type": "application/json"})
        assert r.status_code == 400, body
    # brackets and the word NaN inside a text are only text
    assert guards.json_problem(b'{"a": "[[[[[[ NaN ]]]]]]", "b": "quote \\" ] NaN"}', max_depth=2) is None
    assert guards.json_problem(b'{"a": {"b": {"c": 1}}}', max_depth=2) is not None
    r = _send(c, "POST", "/api/parcels", {"name": "Njiva", "geometry": _circle(12)})
    assert r.status_code == 201                                                        # a normal request is untouched


def test_s4_a_polygon_with_too_many_vertices_is_refused_fast(env, monkeypatch):
    app, _ = _accounts_app(env, monkeypatch, admins="")
    c = _user(app)
    started = time.time()
    r = _send(c, "POST", "/api/parcels", {"name": "Njiva", "geometry": _circle(8000)})
    assert r.status_code in (400, 413) and time.time() - started < 2
    r = _send(c, "POST", "/api/parcels", {"name": "Njiva", "geometry": _circle(600)})
    assert r.status_code == 400 and "vertices" in r.json()["detail"]
    assert _send(c, "POST", "/api/parcels", {"name": "Njiva", "geometry": _circle(499)}).status_code == 201     # 500 positions
    assert _send(c, "POST", "/api/parcels", {"name": "Njiva", "geometry": {"type": "Polygon", "coordinates": [5]}}).status_code == 400


# ------------------------------------------------------------------------------------------------ S6 malformed input
GOOD_PARCEL = {"name": "Njiva", "geometry": None}


@pytest.mark.parametrize("patch", [
    {"name": 5}, {"name": ["a"]}, {"name": "x" * 500}, {"name": "   "}, {"notes": 5}, {"notes": "n" * 5000},
    {"pinned_as_of": "yesterday"}, {"pinned_as_of": 20260101}, {"sowing_date": "garbage"}, {"sowing_date": 5},
    {"sowing_date": "2026-13-45"}, {"bbch": "x"}, {"bbch": 9999}, {"bbch": -5}, {"bbch": 1.5}, {"bbch": True},
    {"bbch": [1]}, {"irrigation_available": {"a": 1}}, {"soil_texture": ["loam"]}, {"geometry": "text"},
])
def test_s6_malformed_parcel_input_is_a_400_and_stores_nothing(env, monkeypatch, patch):
    app, _ = _accounts_app(env, monkeypatch, admins="")
    c = _user(app)
    body = dict(GOOD_PARCEL, geometry=_circle(12))
    body.update(patch)
    r = _send(c, "POST", "/api/parcels", body)
    assert r.status_code == 400, (patch, r.status_code, r.text[:200])
    assert env.list_parcels() == []


def test_s6_a_valid_parcel_still_works_and_malformed_chat_input_is_a_400(env, monkeypatch):
    app, _ = _accounts_app(env, monkeypatch, admins="")
    c = _user(app)
    body = dict(GOOD_PARCEL, geometry=_circle(12), sowing_date="2026-5-3", bbch=12, pinned_as_of="2026-06-01")
    r = _send(c, "POST", "/api/parcels", body)
    assert r.status_code == 201 and r.json()["agronomic"]["sowing_date"] == "2026-05-03"
    pid = r.json()["id"]
    for path, patch in (("chat", {"text": 5}), ("chat", {"text": ["a"]}), ("chat", {"text": "x" * 3000}),
                        ("chat", {"text": "irrigate?", "variant": ["V5"]}), ("chat", {"text": "irrigate?", "variant": "V99"}),
                        ("chat", {"text": "irrigate?", "conversation_id": ["a"]}), ("chat", {"text": "x", "reply": "yes"}),
                        ("chat", {"text": "irrigate?", "advice_type": ["a"]}),
                        ("ai-chat", {"message": 5}), ("ai-chat", {"message": "hi", "mode": ["x"]}),
                        ("ai-chat", {"message": "hi", "conversation_id": {"a": 1}})):
        r = _send(c, "POST", "/api/parcels/%s/%s" % (pid, path), patch)
        assert r.status_code in (400, 404, 503), (path, patch, r.status_code, r.text[:200])
    assert _send(c, "POST", "/api/parcels", [1, 2]).status_code == 422                 # not an object: the framework refuses it


def test_s6_the_old_attack_a_garbage_sowing_date_no_longer_breaks_a_parcel_for_good(env, monkeypatch):
    app, _ = _accounts_app(env, monkeypatch, admins="")
    c = _user(app)
    r = _send(c, "POST", "/api/parcels", dict(GOOD_PARCEL, geometry=_circle(12), sowing_date="garbage"))
    assert r.status_code == 400 and env.list_parcels() == []


# ------------------------------------------------------------------------------------------------ S10 headers
def test_s10_security_headers_on_every_response(env, monkeypatch):
    monkeypatch.delenv("SMARTAGRI_TILE_URL", raising=False)
    app, _ = _accounts_app(env, monkeypatch, admins="")
    c = _browser(app)
    for path, status in (("/", 200), ("/api/health", 200), ("/static/app.js", 200), ("/static/nope.js", 404), ("/api/nothing", 404)):
        r = c.get(path)
        assert r.status_code == status, path
        assert r.headers["x-content-type-options"] == "nosniff", path
        assert r.headers["referrer-policy"] == "strict-origin-when-cross-origin", path
        assert r.headers["x-frame-options"] == "DENY", path
        csp = r.headers["content-security-policy"]
        assert "frame-ancestors 'none'" in csp and "default-src 'self'" in csp and "object-src 'none'" in csp, path
        assert "unsafe-inline" not in csp and "unsafe-eval" not in csp and "*" not in csp.replace("https://*.", ""), path
        assert "img-src 'self' data: https://tile.openstreetmap.org" in csp, path
    refused = c.post("/api/parcels", content=b"x" * (guards.DEFAULT_MAX_BODY + 1), headers={"Content-Type": "application/json"})
    assert refused.status_code == 413 and refused.headers["x-content-type-options"] == "nosniff"      # also on the guard's refusals
    assert "content-security-policy" not in c.get("/docs").headers                                  # the interactive docs use a CDN


def test_s10_the_tile_host_of_this_server_is_the_only_extra_image_source(env, monkeypatch):
    monkeypatch.setenv("SMARTAGRI_TILE_URL", "https://{s}.tiles.example.org/{z}/{x}/{y}.png")
    app, _ = _accounts_app(env, monkeypatch, admins="")
    csp = _browser(app).get("/").headers["content-security-policy"]
    assert "img-src 'self' data: https://*.tiles.example.org;" in csp and "openstreetmap" not in csp
    monkeypatch.setenv("SMARTAGRI_TILE_URL", "none")
    app, _ = _accounts_app(env, monkeypatch, admins="")
    assert "img-src 'self' data:;" in _browser(app).get("/").headers["content-security-policy"]
    assert guards.tile_sources("javascript:alert(1)") == [] and guards.tile_sources("https://a.example/{z}") == ["https://a.example"]


def test_s10_the_client_loads_nothing_that_the_policy_forbids():
    """The page has no inline script, inline style, event-handler attribute or external resource but the tile host."""
    import re
    from pathlib import Path
    static = Path(__file__).resolve().parents[1] / "src" / "smartagri" / "research_api" / "static"
    page = (static / "index.html").read_text(encoding="utf-8")
    assert not re.search(r"<script(?![^>]*\bsrc=)", page) and "<style" not in page
    assert not re.search(r"\son[a-z]+=\"", page) and " style=\"" not in page
    for name in ("app.js", "settings.js", "charts.js", "map.js"):
        text = (static / name).read_text(encoding="utf-8")
        assert not re.search(r"""\s(style|on[a-z]+)=["'$]""", text), name          # no markup built with style or handler attributes
        assert "javascript:" not in text, name
