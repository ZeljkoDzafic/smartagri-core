from datetime import datetime

import pytest

from smartagri.config import load_variants
from smartagri.core.types import (AdviceType, Agronomic, Context, NdviObservation, ParcelInfo, Question,
                                  SatelliteSummary, WeatherSummary)

AS_OF = datetime.fromisoformat("2026-07-12T06:00:00")


def make_context(advice_type=AdviceType.IRRIGATION_TIMING, agronomic=None, weather=None, ndvi=None,
                 questions_asked=0, stated=None):
    a = dict(sowing_date="2026-04-25", bbch=61, bbch_reported_on="2026-07-11", irrigation_available="yes",
             irrigation_system_type="sprinkler", soil_texture="loam", soil_water_status="dry",
             soil_water_reported_on="2026-07-12")
    a.update(agronomic or {})
    w = dict(precip_past_7d_mm=2.0, et0_past_7d_mm=38.0, precip_forecast_3d_mm=0.0, precip_forecast_7d_mm=4.0,
             tmin_forecast_7d_c=17.0, tmax_forecast_7d_c=33.0, wind_forecast_max_ms=3.0,
             forecast_issued_at="2026-07-12T04:00:00", horizon_days=7)
    w.update(weather or {})
    series = [NdviObservation(**o) for o in (ndvi or [])]
    return Context(P=ParcelInfo("t", 2.1, 44.9, 17.3, "pannonian"), A=Agronomic(**a), W=WeatherSummary(**w),
                   S=SatelliteSummary(ndvi_series=series),
                   Q=Question("pitanje", advice_type, stated or {}), as_of=AS_OF, questions_asked=questions_asked)


@pytest.fixture
def variants():
    return load_variants()


@pytest.fixture(autouse=True)
def _lock_sees_a_clean_checkout(monkeypatch):
    """The protocol lock refuses a checkout with uncommitted source or config changes (lock.git_state). Tests run in
    working copies that are dirty while being developed, so they see a fixed clean state; the refusal itself is tested
    through lock.environment_differences."""
    from smartagri.evalkit import lock
    monkeypatch.setattr(lock, "git_state", lambda: {"git": True, "commit": "0" * 40, "dirty": []})


# ---------------------------------------------------------------- git-ignored test scenarios
from pathlib import Path

TEST_SCENARIOS_DIR = Path(__file__).resolve().parents[1] / "eval" / "scenarios" / "test"
TEST_SCENARIOS_ABSENT = ("the test scenarios (backend/eval/scenarios/test/) are git-ignored and absent in this checkout "
                         "(CI, fresh clone); the protocol-lock fingerprint over them is checked only where they exist")


# ---------------------------------------------------------------- fake providers under SMARTAGRI_OFFLINE=1
# CI runs the suite with SMARTAGRI_OFFLINE=1 so that no request can leave the runner. Offline mode refuses every provider
# fetch that is not in the cache, including fetches answered by a fake. Tests whose provider calls are answered by an
# httpx.MockTransport or by a fake fetch callable switch offline mode off for themselves only: the fake answers, nothing
# reaches the network, and the assertions stay exactly as written.

def use_mock_transport(monkeypatch, transport):
    """Install a fake HTTP transport for every provider (providers.base.TRANSPORT) and leave offline mode."""
    from smartagri.providers import base
    monkeypatch.setattr(base, "TRANSPORT", transport)
    monkeypatch.delenv("SMARTAGRI_OFFLINE", raising=False)
    return transport


@pytest.fixture
def online_fakes(monkeypatch):
    """For tests that pass their own fake fetch callables to the provider cache (no HTTP at all)."""
    monkeypatch.delenv("SMARTAGRI_OFFLINE", raising=False)


def skip_without_test_scenarios():
    """Skip the rest of a test that hashes or scans the test scenarios (never runs them) when the folder is absent.

    Assertions placed before the call (config hashes, prompt hashes, file lists) still run everywhere."""
    if not TEST_SCENARIOS_DIR.is_dir():
        pytest.skip(TEST_SCENARIOS_ABSENT)


# ---------------------------------------------------------------- storage backends
import os

from smartagri.store import TABLES, PostgresStore, SqliteStore

# TEST_DATABASE_URL names a maintenance database whose name ends in `_test`; every test
# process (each pytest run, each xdist worker) creates its own database `<name>_<pid>_<random>` from it, uses only
# that one and drops it at the end, so parallel runs never TRUNCATE each other's tables (or a dev database).
BASE_PG_URL = os.environ.get("TEST_DATABASE_URL", "")
PG_URL = ""
_PG_DB = ""


def _split_db(url):
    from urllib.parse import urlsplit, urlunsplit
    parts = urlsplit(url)
    return parts, parts.path.lstrip("/"), urlunsplit


def _create_run_db():
    global PG_URL, _PG_DB
    import secrets

    import psycopg
    parts, name, unsplit = _split_db(BASE_PG_URL)
    if not name.endswith("_test"):
        raise RuntimeError("TEST_DATABASE_URL must name a database ending in _test (got %r); the PostgreSQL tests "
                           "create and drop their own databases next to it" % name)
    _PG_DB = "%s_%d_%s" % (name, os.getpid(), secrets.token_hex(3))
    with psycopg.connect(BASE_PG_URL, autocommit=True) as conn:
        conn.execute('CREATE DATABASE "%s"' % _PG_DB)
    PG_URL = unsplit(parts._replace(path="/" + _PG_DB))


def _drop_run_db():
    if not _PG_DB:
        return
    import psycopg
    for s in list(_OPEN_PG):
        s.close()
    with psycopg.connect(BASE_PG_URL, autocommit=True) as conn:
        conn.execute('DROP DATABASE IF EXISTS "%s" WITH (FORCE)' % _PG_DB)


if BASE_PG_URL:
    _create_run_db()


def pytest_unconfigure(config):
    _drop_run_db()


# Every PostgresStore opened by a test is closed after it (each holds a connection pool with its own threads).
import weakref

_OPEN_PG = weakref.WeakSet()
_pg_init = PostgresStore.__init__


def _tracked_init(self, *args, **kwargs):
    _pg_init(self, *args, **kwargs)
    _OPEN_PG.add(self)


PostgresStore.__init__ = _tracked_init


@pytest.fixture(autouse=True)
def _close_pg_stores():
    yield
    for s in list(_OPEN_PG):
        try:
            s.close()
        except Exception:
            pass
        _OPEN_PG.discard(s)


def _fresh_pg():
    store = PostgresStore(PG_URL)
    for table in list(TABLES) + ["external_cache", "chunks"]:
        store._exec("TRUNCATE %s RESTART IDENTITY" % table)
    return store


@pytest.fixture(params=["sqlite", "postgresql"])
def store(request):
    """Every storage test runs on SQLite and, when TEST_DATABASE_URL is set, on PostgreSQL (own database per run)."""
    if request.param == "sqlite":
        return SqliteStore(":memory:")
    if not PG_URL:
        pytest.skip("TEST_DATABASE_URL is not set")
    return _fresh_pg()


# ---------------------------------------------------------------- accounts
import uuid

TEST_PASSWORD = "dobra-lozinka-2026"
CSRF = {"X-Requested-With": "smartagri"}


def login_as(client, role="owner", email=None, org_id=None, researcher=True, org_name="Gazdinstvo Test",
             password=TEST_PASSWORD):
    """Create a verified user with `role` in organisation `org_id` (a new one when None), log the
    TestClient in with the session cookie and send the CSRF header on every request. Returns /auth/me."""
    accounts = client.app.state.accounts
    email = email or "%s-%s@example.org" % (role, uuid.uuid4().hex[:8])
    user = accounts.create_user(email, "Test " + role, password, verified=True, researcher=researcher)
    if org_id is None:
        org_id = accounts.create_org(org_name)["id"]
    accounts.add_member(user["id"], org_id, role)
    client.headers.update(CSRF)
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()
