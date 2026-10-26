"""Optional accounts of the research web app (research_api/auth.py): SMARTAGRI_ACCOUNTS=off|optional."""
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from smartagri.providers import weather
from smartagri.research_api import auth
from smartagri.research_api.app import create_app
from smartagri.research_api.service import ResearchService

SQUARE = {"type": "Polygon", "coordinates": [[[17.300, 44.900], [17.302, 44.900], [17.302, 44.902], [17.300, 44.902],
                                              [17.300, 44.900]]]}
PW = "maize-field-2026"
PW2 = "another-maize-2027"


def _fake_weather(store, lat, lon, as_of, refresh=False):
    days = [(as_of + timedelta(days=o)).date().isoformat() for o in range(-92, 7)]
    n = len(days)
    return {"raw": {"daily": {"time": days, "precipitation_sum": [0.5] * n, "et0_fao_evapotranspiration": [5.0] * n,
                              "temperature_2m_min": [15.0] * n, "temperature_2m_max": [29.0] * n,
                              "wind_speed_10m_max": [3.0] * n}},
            "fetched_at": as_of.isoformat(), "request_hash": "test"}


class Clock:
    def __init__(self):
        self.t = 1_800_000_000.0

    def __call__(self):
        return self.t


class Outbox:
    def __init__(self):
        self.sent = []

    def send(self, to, subject, text):
        self.sent.append({"to": to, "subject": subject, "text": text})

    def token(self, kind):
        text = self.sent[-1]["text"]
        start = text.index("/#/%s/" % kind) + len("/#/%s/" % kind)
        return text[start:].split()[0]


@pytest.fixture
def env(monkeypatch, store):
    monkeypatch.delenv("CDSE_CLIENT_ID", raising=False)
    for name in ("SMARTAGRI_SMTP_HOST", "SMARTAGRI_SMTP_FROM", "SMARTAGRI_PUBLIC_URL", "SMARTAGRI_COOKIE_SECURE",
                 "SMARTAGRI_SESSION_DAYS"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LLM_PROVIDER", "template")
    monkeypatch.setenv("EMBEDDINGS_PROVIDER", "none")
    monkeypatch.setattr(weather, "fetch", _fake_weather)
    return store


def _app(store, monkeypatch, mode="optional", **kw):
    monkeypatch.setenv("SMARTAGRI_ACCOUNTS", mode)
    svc = ResearchService(store)
    accounts = auth.Accounts(store, **kw) if kw else None
    return create_app(svc, accounts), svc


def browser(app, base_url="http://testserver"):
    c = TestClient(app, base_url=base_url)
    c.get("/api/auth/me")                       # receives the anonymous browser and CSRF cookies
    return c


def post(c, path, body=None, **kw):
    headers = {"X-CSRF-Token": c.cookies.get("sa_csrf") or ""}
    headers.update(kw.pop("headers", {}))
    return c.post(path, json=body if body is not None else {}, headers=headers, **kw)


def new_parcel(c, name="Njiva"):
    sowing = (datetime.now() - timedelta(days=78)).date().isoformat()
    r = post(c, "/api/parcels", {"name": name, "geometry": SQUARE, "sowing_date": sowing,
                                 "irrigation_available": "yes", "irrigation_system_type": "sprinkler"})
    assert r.status_code == 201, r.text
    return r.json()


def ids(c):
    r = c.get("/api/parcels")
    assert r.status_code == 200, r.text
    return [p["id"] for p in r.json()]


# ------------------------------------------------------------------------------------------------ mode off (default)
def test_off_is_the_default_and_keeps_the_old_behaviour(env, monkeypatch):
    monkeypatch.delenv("SMARTAGRI_ACCOUNTS", raising=False)
    assert auth.mode() == "off"
    app = create_app(ResearchService(env))
    a, b = TestClient(app), TestClient(app)
    assert a.get("/api/meta").json()["accounts"] == {"enabled": False, "email": False}
    assert a.get("/api/auth/me").status_code == 404
    assert post(a, "/api/auth/signup", {"email": "a@example.org", "password": PW}).status_code in (404, 405)
    r = a.post("/api/parcels", json={"name": "Njiva", "geometry": SQUARE})      # no CSRF token needed
    assert r.status_code == 201 and "set-cookie" not in r.headers
    pid = r.json()["id"]
    assert ids(b) == [pid] and b.get("/api/parcels/" + pid).status_code == 200    # everyone sees everything
    assert not env.find("core_owners")


def test_bad_mode_is_refused(monkeypatch):
    monkeypatch.setenv("SMARTAGRI_ACCOUNTS", "required")
    with pytest.raises(ValueError):
        auth.mode()


# ------------------------------------------------------------------------------------------------ sign-up and sign-in
def test_signup_signin_wrong_password_and_meta(env, monkeypatch):
    app, _ = _app(env, monkeypatch)
    c = browser(app)
    assert c.get("/api/meta").json()["accounts"] == {"enabled": True, "email": False}
    assert c.get("/api/auth/me").json() == {"user": None, "email": False}
    short = post(c, "/api/auth/signup", {"email": "a@example.org", "password": "short"})
    assert short.status_code == 400 and "at least 10" in short.json()["detail"]
    assert post(c, "/api/auth/signup", {"email": "not-an-email", "password": PW}).status_code == 400
    r = post(c, "/api/auth/signup", {"email": " A@Example.org ", "password": PW})
    assert r.status_code == 201 and r.json()["user"]["email"] == "a@example.org"
    cookie = r.headers.get("set-cookie", "")
    assert "sa_session=" in cookie and "HttpOnly" in cookie and "SameSite=lax" in cookie.replace("Lax", "lax")
    assert "Domain" not in cookie and "Secure" not in cookie                         # http: no Secure; host-only
    assert c.get("/api/auth/me").json()["user"]["email"] == "a@example.org"
    assert post(c, "/api/auth/signup", {"email": "a@example.org", "password": PW}).status_code == 409
    stored = env.find("core_users", email="a@example.org")[0]
    assert stored["password_hash"].split("$")[0] in ("scrypt", "pbkdf2_sha256") and PW not in str(stored)

    d = browser(app)
    wrong = post(d, "/api/auth/signin", {"email": "a@example.org", "password": "wrong-password-1"})
    unknown = post(d, "/api/auth/signin", {"email": "nobody@example.org", "password": PW})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["detail"] == unknown.json()["detail"] == auth.INVALID_LOGIN    # generic message
    ok = post(d, "/api/auth/signin", {"email": "A@EXAMPLE.ORG", "password": PW})
    assert ok.status_code == 200 and d.get("/api/auth/me").json()["user"]["email"] == "a@example.org"


def test_secure_cookie_on_https(env, monkeypatch):
    app, _ = _app(env, monkeypatch)
    c = TestClient(app, base_url="https://app.example.org")
    r = c.get("/api/auth/me")
    for part in r.headers.get_list("set-cookie"):
        assert "Secure" in part and "Domain" not in part
    assert any(p.startswith("sa_browser=") and "HttpOnly" in p and "Max-Age" not in p
               for p in r.headers.get_list("set-cookie"))
    assert any(p.startswith("sa_csrf=") and "HttpOnly" not in p for p in r.headers.get_list("set-cookie"))


# ------------------------------------------------------------------------------------------------ protection
def test_csrf_is_required_for_state_changes(env, monkeypatch):
    app, _ = _app(env, monkeypatch)
    c = browser(app)
    body = {"name": "Njiva", "geometry": SQUARE}
    assert c.post("/api/parcels", json=body).status_code == 403                       # no token
    assert c.post("/api/parcels", json=body, headers={"X-CSRF-Token": "forged"}).status_code == 403
    assert post(c, "/api/parcels", body, headers={"Origin": "https://evil.example"}).status_code == 403
    assert post(c, "/api/auth/signin", {"email": "a@example.org", "password": PW},
                headers={"Origin": "null"}).status_code == 403
    assert post(c, "/api/parcels", body, headers={"Origin": "http://testserver"}).status_code == 201
    assert c.get("/api/parcels").status_code == 200                                    # reads need no token


def test_signin_is_throttled(env, monkeypatch):
    clock = Clock()
    app, _ = _app(env, monkeypatch, clock=clock)
    c = browser(app)
    assert post(c, "/api/auth/signup", {"email": "t@example.org", "password": PW}).status_code == 201
    d = browser(app)
    limit = auth.LIMITS["signin"]["email"][0]
    for _ in range(limit):
        assert post(d, "/api/auth/signin", {"email": "t@example.org", "password": "wrong-password-1"}).status_code == 401
    r = post(d, "/api/auth/signin", {"email": "t@example.org", "password": PW})
    assert r.status_code == 429 and int(r.headers["Retry-After"]) > 0                  # even the right password
    clock.t += auth.LIMITS["signin"]["email"][1] + 1
    assert post(d, "/api/auth/signin", {"email": "t@example.org", "password": PW}).status_code == 200


def test_signup_is_rate_limited_per_address(env, monkeypatch):
    app, _ = _app(env, monkeypatch, clock=Clock())
    c = browser(app)
    limit = auth.LIMITS["signup"]["ip"][0]
    codes = [post(c, "/api/auth/signup", {"email": "x@example.org", "password": "short"}).status_code
             for _ in range(limit + 1)]
    assert codes[:limit] == [400] * limit and codes[-1] == 429


# ------------------------------------------------------------------------------------------------ isolation
def test_users_and_browsers_see_only_their_own_parcels(env, monkeypatch):
    app, svc = _app(env, monkeypatch)
    anon_a, anon_b = browser(app), browser(app)
    pa = new_parcel(anon_a, "A")
    assert ids(anon_a) == [pa["id"]] and ids(anon_b) == []
    for path in ("/api/parcels/%s", "/api/parcels/%s/profile"):
        assert anon_b.get(path % pa["id"]).status_code == 404
    assert post(anon_b, "/api/parcels/%s/profile/refresh" % pa["id"]).status_code == 404
    assert post(anon_b, "/api/parcels/%s/chat" % pa["id"], {"text": "Kada da navodnjavam?"}).status_code == 404
    run = post(anon_a, "/api/parcels/%s/chat" % pa["id"],
               {"text": "Da li da navodnjavam kukuruz?", "advice_type": "irrigation_timing"})
    assert run.status_code == 200, run.text
    run = run.json()
    assert anon_a.get("/api/runs/" + run["id"]).status_code == 200
    assert anon_b.get("/api/runs/" + run["id"]).status_code == 404
    assert anon_b.get("/api/conversations/" + run["conversation_id"]).status_code == 404
    # a conversation of A cannot be continued through a parcel of B
    pb = new_parcel(anon_b, "B")
    assert post(anon_b, "/api/parcels/%s/chat" % pb["id"],
                {"text": "x", "conversation_id": run["conversation_id"]}).status_code == 404

    user_a, user_b = browser(app), browser(app)
    post(user_a, "/api/auth/signup", {"email": "ua@example.org", "password": PW})
    post(user_b, "/api/auth/signup", {"email": "ub@example.org", "password": PW})
    pua = new_parcel(user_a, "UA")
    assert ids(user_a) == [pua["id"]] and ids(user_b) == []
    assert user_b.get("/api/parcels/" + pua["id"]).status_code == 404
    assert user_b.get("/api/parcels/" + pua["id"]).json() == anon_b.get("/api/parcels/nope").json()   # no hint
    assert set(p["id"] for p in svc.list_parcels()) == {pa["id"], pb["id"], pua["id"]}


def test_parcels_from_before_accounts_are_hidden_until_assigned(env, monkeypatch):
    svc = ResearchService(env)
    old = svc.create_parcel({"name": "Stara", "geometry": SQUARE})                   # stored with accounts off
    app, _ = _app(env, monkeypatch)
    c = browser(app)
    post(c, "/api/auth/signup", {"email": "owner@example.org", "password": PW})
    assert ids(c) == [] and c.get("/api/parcels/" + old["id"]).status_code == 404
    assert auth.Accounts(env, mailer=False).assign_unowned("Owner@example.org") == 1
    assert ids(c) == [old["id"]]


# ------------------------------------------------------------------------------------------------ claim, logout, delete
def test_anonymous_parcels_are_claimed_on_signup_and_signin(env, monkeypatch):
    app, _ = _app(env, monkeypatch)
    c = browser(app)
    p1 = new_parcel(c, "Before sign-up")
    assert post(c, "/api/auth/signup", {"email": "claim@example.org", "password": PW}).status_code == 201
    assert ids(c) == [p1["id"]]
    assert env.get("core_owners", p1["id"])["owner"].startswith("u:")
    assert post(c, "/api/auth/signout").json()["user"] is None
    assert ids(c) == []                                                                # a fresh, empty browser
    p2 = new_parcel(c, "Anonymous again")
    assert post(c, "/api/auth/signin", {"email": "claim@example.org", "password": PW}).status_code == 200
    assert sorted(ids(c)) == sorted([p1["id"], p2["id"]])
    other = browser(app)                                                               # another device
    post(other, "/api/auth/signin", {"email": "claim@example.org", "password": PW})
    assert sorted(ids(other)) == sorted([p1["id"], p2["id"]])


def test_logout_ends_the_session_on_the_server(env, monkeypatch):
    app, _ = _app(env, monkeypatch)
    c = browser(app)
    post(c, "/api/auth/signup", {"email": "out@example.org", "password": PW})
    token = c.cookies.get("sa_session")
    assert token and c.get("/api/auth/me").json()["user"]
    r = post(c, "/api/auth/signout")
    assert r.status_code == 200
    assert any(h.startswith("sa_session=") and "Max-Age=0" in h for h in r.headers.get_list("set-cookie"))
    assert c.get("/api/auth/me").json()["user"] is None
    replay = TestClient(app)
    replay.cookies.set("sa_session", token)
    assert replay.get("/api/auth/me").json()["user"] is None                         # the old token is dead


def test_sessions_expire(env, monkeypatch):
    clock = Clock()
    monkeypatch.setenv("SMARTAGRI_SESSION_DAYS", "2")
    app, _ = _app(env, monkeypatch, clock=clock)
    c = browser(app)
    post(c, "/api/auth/signup", {"email": "exp@example.org", "password": PW})
    clock.t += 86400
    assert c.get("/api/auth/me").json()["user"]
    clock.t += 86400 + 1
    assert c.get("/api/auth/me").json()["user"] is None


def test_delete_account_deletes_the_users_data(env, monkeypatch):
    app, _ = _app(env, monkeypatch)
    c = browser(app)
    keep = new_parcel(browser(app), "Someone else's")
    post(c, "/api/auth/signup", {"email": "gone@example.org", "password": PW})
    p = new_parcel(c)
    post(c, "/api/parcels/%s/profile/refresh" % p["id"])
    run = post(c, "/api/parcels/%s/chat" % p["id"], {"text": "Da li da navodnjavam kukuruz?",
                                                     "advice_type": "irrigation_timing"}).json()
    assert env.latest_profile(p["id"]) and env.get_run(run["id"])
    assert post(c, "/api/auth/account/delete", {"password": "wrong-password-1"}).status_code == 401
    r = post(c, "/api/auth/account/delete", {"password": PW})
    assert r.status_code == 200 and r.json() == {"deleted": True, "parcels": 1}
    assert env.get_parcel(p["id"]) is None and env.latest_profile(p["id"]) is None
    assert env.get_run(run["id"]) is None and env.get_conversation(run["conversation_id"]) is None
    assert not env.find("core_users", email="gone@example.org") and not env.find("core_sessions")
    assert env.get("core_owners", p["id"]) is None and env.get_parcel(keep["id"])
    assert c.get("/api/auth/me").json()["user"] is None and ids(c) == []
    d = browser(app)
    assert post(d, "/api/auth/signin", {"email": "gone@example.org", "password": PW}).status_code == 401
    assert post(TestClient(app), "/api/auth/account/delete", {"password": PW}).status_code == 403   # no CSRF cookie


# ------------------------------------------------------------------------------------------------ e-mail on and off
def test_without_smtp_there_is_no_email_flow(env, monkeypatch):
    monkeypatch.setenv("SMARTAGRI_SMTP_HOST", "smtp.example.org")                    # incomplete: no FROM, no URL
    assert auth.smtp_configured() is False
    app, _ = _app(env, monkeypatch)
    c = browser(app)
    assert c.get("/api/meta").json()["accounts"]["email"] is False
    assert post(c, "/api/auth/password/forgot", {"email": "a@example.org"}).status_code == 404
    assert post(c, "/api/auth/password/reset", {"token": "x", "password": PW}).status_code == 404
    r = post(c, "/api/auth/signup", {"email": "now@example.org", "password": PW})
    assert r.status_code == 201 and r.json()["user"]["verified"] is False                # works immediately
    assert c.get("/api/auth/me").json()["user"]["email"] == "now@example.org"


def test_with_smtp_verification_and_password_reset(env, monkeypatch):
    monkeypatch.setenv("SMARTAGRI_PUBLIC_URL", "https://app.example.org/")
    outbox = Outbox()
    app, _ = _app(env, monkeypatch, mailer=outbox)
    https = "https://app.example.org"                                    # Secure cookies: the client must use https
    c = browser(app, https)
    assert c.get("/api/meta").json()["accounts"] == {"enabled": True, "email": True}
    anon = new_parcel(c, "Mine")
    r = post(c, "/api/auth/signup", {"email": "v@example.org", "password": PW})
    assert r.status_code == 201 and r.json() == {"user": None, "email": True, "verify_sent": True}
    assert outbox.sent[-1]["to"] == "v@example.org" and "https://app.example.org/#/verify/" in outbox.sent[-1]["text"]
    assert c.get("/api/auth/me").json()["user"] is None and ids(c) == [anon["id"]]
    # the same answer for an address that is already registered, and no second account
    again = post(browser(app, https), "/api/auth/signup", {"email": "v@example.org", "password": PW2})
    assert again.status_code == 201 and again.json() == r.json() and len(env.find("core_users")) == 1
    blocked = post(c, "/api/auth/signin", {"email": "v@example.org", "password": PW})
    assert blocked.status_code == 403                                                 # a new link was sent
    token = outbox.token("verify")
    assert post(c, "/api/auth/verify", {"token": "bad"}).status_code == 400
    assert post(c, "/api/auth/verify", {"token": token}).json()["user"]["verified"] is True
    assert post(c, "/api/auth/verify", {"token": token}).status_code == 400            # one-time
    assert post(c, "/api/auth/signin", {"email": "v@example.org", "password": PW}).status_code == 200
    assert ids(c) == [anon["id"]]                                                       # claimed at sign-in

    n = len(outbox.sent)
    assert post(c, "/api/auth/password/forgot", {"email": "nobody@example.org"}).status_code == 202
    assert len(outbox.sent) == n                                                        # same answer, no mail
    assert post(c, "/api/auth/password/forgot", {"email": "V@example.org"}).status_code == 202
    reset = outbox.token("reset")
    other = browser(app, https)
    assert post(other, "/api/auth/password/reset", {"token": reset, "password": "short"}).status_code == 400
    r = post(other, "/api/auth/password/reset", {"token": reset, "password": PW2})
    assert r.status_code == 200 and r.json()["user"]["email"] == "v@example.org"
    assert c.get("/api/auth/me").json()["user"] is None                                 # other sessions ended
    assert post(other, "/api/auth/password/reset", {"token": reset, "password": PW2}).status_code == 400
    assert post(c, "/api/auth/signin", {"email": "v@example.org", "password": PW}).status_code == 401
    assert post(c, "/api/auth/signin", {"email": "v@example.org", "password": PW2}).status_code == 200


def test_expired_links_are_refused(env, monkeypatch):
    monkeypatch.setenv("SMARTAGRI_PUBLIC_URL", "https://app.example.org")
    clock, outbox = Clock(), Outbox()
    app, _ = _app(env, monkeypatch, mailer=outbox, clock=clock)
    c = browser(app, "https://app.example.org")
    post(c, "/api/auth/signup", {"email": "late@example.org", "password": PW})
    clock.t += auth.VERIFY_HOURS * 3600 + 1
    assert post(c, "/api/auth/verify", {"token": outbox.token("verify")}).status_code == 400


# ------------------------------------------------------------------------------------------------ blind rating unchanged
def test_rating_endpoints_do_not_depend_on_accounts(env, monkeypatch):
    app, _ = _app(env, monkeypatch)
    c = TestClient(app)                                       # no cookies, no CSRF token, no account
    nxt = c.get("/api/eval/rating/next", params={"rater": "r1"})
    assert nxt.json() == {"item_id": None, "remaining": 0} and "set-cookie" not in nxt.headers
    assert c.get("/api/eval/rubric").status_code == 200 and c.get("/api/eval/runs").status_code == 200
    bad = {"item_id": "nope", "rater": "r1", "r1": 1, "r2": 1, "r3": 1, "r4": 1, "r5": 1}
    r = c.post("/api/eval/rating", json=bad)
    assert r.status_code == 404 and "set-cookie" not in r.headers
    assert c.post("/api/eval/rating", json=dict(bad, r1=3)).status_code == 422
    assert r.headers["content-language"] == "sr-Latn"


def test_accounts_tables_come_from_migration_0014(env):
    from smartagri import migrate
    assert any(v[0] == "0014" for v in migrate.VERSIONS)
    for table in ("core_users", "core_sessions", "core_tokens", "core_owners"):
        assert env.find(table) == []


def test_password_hash_round_trip_and_fallback(monkeypatch):
    h = auth.hash_password(PW)
    assert auth.verify_password(PW, h) and not auth.verify_password(PW2, h) and not auth.verify_password(PW, "x$y")
    monkeypatch.setattr(auth, "_scrypt", lambda *a: None)                            # no scrypt in this build
    monkeypatch.setattr(auth, "PBKDF2_ITERATIONS", 1000)
    h2 = auth.hash_password(PW)
    assert h2.startswith("pbkdf2_sha256$1000$") and auth.verify_password(PW, h2)


def test_account_ui_is_hidden_unless_the_server_turns_it_on():
    from pathlib import Path
    static = Path(auth.__file__).resolve().parent / "static"
    page = (static / "index.html").read_text(encoding="utf-8")
    for start in ('<div id="account" class="account" hidden>', 'id="account-icon"', '<div id="anon-banner"'):
        tag = page[page.index(start):page.index(">", page.index(start))]
        assert " hidden" in tag, start
    assert "Temporary — this parcel is kept only for this browser session. Create an account to save it." in page
    assert 'id="p-save">Save parcel</button>' in page and 'class="pill unsaved">Not saved</span>' in page
    script = (static / "app.js").read_text(encoding="utf-8")
    assert "if (meta.accounts && meta.accounts.enabled) await initAccount();" in script


# ------------------------------------------------------------------------------------------------ temporary anonymous work
def test_anonymous_browser_cookie_is_a_session_cookie(env, monkeypatch):
    app, _ = _app(env, monkeypatch)
    r = TestClient(app).get("/api/auth/me")
    browser_cookie = [h for h in r.headers.get_list("set-cookie") if h.startswith("sa_browser=")]
    assert browser_cookie and "Max-Age" not in browser_cookie[0] and "expires" not in browser_cookie[0].lower()
    assert "HttpOnly" in browser_cookie[0]


def _stale_setup(env, monkeypatch, clock):
    app, svc = _app(env, monkeypatch, clock=clock)
    unowned = svc.create_parcel({"name": "Before accounts", "geometry": SQUARE})
    user = browser(app)
    post(user, "/api/auth/signup", {"email": "keep@example.org", "password": PW})
    saved = new_parcel(user, "Saved")
    anon = browser(app)
    temp = new_parcel(anon, "Temporary")
    run = post(anon, "/api/parcels/%s/chat" % temp["id"], {"text": "Da li da navodnjavam kukuruz?",
                                                           "advice_type": "irrigation_timing"}).json()
    return app, user, anon, unowned, saved, temp, run


def test_purge_removes_only_stale_anonymous_work(env, monkeypatch):
    clock = Clock()
    app, user, anon, unowned, saved, temp, run = _stale_setup(env, monkeypatch, clock)
    accounts = auth.Accounts(env, mailer=False, clock=clock)
    assert accounts.purge_anonymous() == 0                                     # fresh: kept
    clock.t += 23 * 3600
    assert ids(anon) == [temp["id"]]                                           # activity keeps it alive
    clock.t += 23 * 3600
    assert accounts.purge_anonymous() == 0
    clock.t += 24 * 3600 + 1
    assert accounts.purge_anonymous() == 1
    assert env.get_parcel(temp["id"]) is None and env.get_run(run["id"]) is None
    assert env.get_conversation(run["conversation_id"]) is None and env.get("core_owners", temp["id"]) is None
    assert env.get_parcel(saved["id"]) and env.get_parcel(unowned["id"])          # account and unowned data stay
    assert env.get("core_owners", saved["id"])["owner"].startswith("u:")
    assert anon.get("/api/parcels/" + temp["id"]).status_code == 404            # a purged parcel is gone
    assert ids(anon) == [] and ids(user) == [saved["id"]]


def test_purge_runs_lazily_on_requests(env, monkeypatch):
    clock = Clock()
    app, user, anon, unowned, saved, temp, run = _stale_setup(env, monkeypatch, clock)
    clock.t += 25 * 3600
    assert user.get("/api/parcels").status_code == 200                         # any API request may purge
    assert env.get_parcel(temp["id"]) is None and env.get_parcel(saved["id"]) and env.get_parcel(unowned["id"])


def test_anonymous_ttl_comes_from_the_environment(env, monkeypatch):
    monkeypatch.setenv("SMARTAGRI_ANON_TTL_HOURS", "2")
    assert auth.anon_ttl_hours() == 2
    clock = Clock()
    app, user, anon, unowned, saved, temp, run = _stale_setup(env, monkeypatch, clock)
    accounts = auth.Accounts(env, mailer=False, clock=clock)
    clock.t += 3600
    assert accounts.purge_anonymous() == 0
    clock.t += 3601
    assert accounts.purge_anonymous() == 1 and env.get_parcel(temp["id"]) is None
    for bad in ("0", "-1", "x"):
        monkeypatch.setenv("SMARTAGRI_ANON_TTL_HOURS", bad)
        assert auth.anon_ttl_hours() == 24


def test_claimed_parcels_are_saved_and_never_purged(env, monkeypatch):
    clock = Clock()
    app, _ = _app(env, monkeypatch, clock=clock)
    c = browser(app)
    p = new_parcel(c, "Save me")
    assert env.get("core_owners", p["id"])["touched_at"]
    assert post(c, "/api/auth/signup", {"email": "saver@example.org", "password": PW}).status_code == 201
    assert ids(c) == [p["id"]] and not env.get("core_owners", p["id"]).get("touched_at")
    clock.t += 1000 * 3600
    assert auth.Accounts(env, mailer=False, clock=clock).purge_anonymous() == 0 and env.get_parcel(p["id"])
