"""
RSVP persistence tests — written against the 2026-09-03 data-loss postmortem.

The GitHub token died 2026-08-21 (401). The old code did:

    read_data()      GitHub 401 -> returns []          (silently "no guests")
    submit()         [].append(guest) -> write_data([guest])
    _write_internal  PUT that 1-element array over the 14-record file

Only the token being dead for WRITES too kept the 14 records alive. Dropping a
fresh token into the old code would have destroyed them on the very next RSVP.

These tests encode the invariants that were missing:

    1. A failed read RAISES. It never degrades into an empty list.
    2. A write MERGES into a fresh remote read, so a stale or empty in-memory
       list can only ADD, never remove.
    3. A write that shrinks the file is refused unless it is an explicit delete.
    4. A guest is told "confirmed" only when the RSVP is really stored.

Run: python -m pytest backend/test_persist.py -q
"""
import base64
import json

import pytest

import app as A


REMOTE_14 = [{"_id": f"id{i:02d}", "name": f"Guest {i}", "guests": 1,
              "date": f"2026-08-{10 + i:02d}T00:00:00+00:00"} for i in range(14)]


class FakeResp:
    def __init__(self, status, payload=None):
        self.status_code = status
        self._payload = payload or {}

    def json(self):
        return self._payload


def _contents(rows, sha="abc123"):
    blob = base64.b64encode(json.dumps(rows).encode()).decode()
    return FakeResp(200, {"content": blob, "sha": sha})


class FakeGH:
    """Stands in for the GitHub contents API."""

    def __init__(self, rows, get_status=200):
        self.rows = list(rows)
        self.get_status = get_status
        self.puts = []

    def get(self, url, headers=None, timeout=None):
        if self.get_status != 200:
            return FakeResp(self.get_status)
        return _contents(self.rows)

    def put(self, url, headers=None, json=None, timeout=None):
        decoded = base64.b64decode(json["content"]).decode()
        self.puts.append(__import__("json").loads(decoded))
        self.rows = self.puts[-1]
        return FakeResp(200, {})


@pytest.fixture(autouse=True)
def _token(monkeypatch):
    monkeypatch.setattr(A, "GH_TOKEN", "fake-token")
    monkeypatch.setattr(A, "DATA_FILE", "/nonexistent/rsvp_data.json")


def test_failed_read_raises_instead_of_returning_empty():
    """The bug's first domino: 401 became 'no guests'."""
    gh = FakeGH(REMOTE_14, get_status=401)
    A.req = gh
    with pytest.raises(A.PersistError):
        A.read_data()


def test_stale_empty_list_cannot_wipe_the_file():
    """THE regression. Old code PUT a 1-element array over 14 records."""
    gh = FakeGH(REMOTE_14)
    A.req = gh
    newcomer = {"_id": "new001", "name": "Late Guest", "guests": 2,
                "date": "2026-09-03T00:00:00+00:00"}
    A.write_data([newcomer])                    # caller's view is empty + 1
    assert len(gh.puts) == 1
    written = gh.puts[0]
    assert len(written) == 15, f"expected 14 merged + 1 new, got {len(written)}"
    names = {g["name"] for g in written}
    assert "Late Guest" in names
    for g in REMOTE_14:
        assert g["name"] in names, f"{g['name']} was destroyed by the write"


def test_empty_write_is_a_no_op_not_a_wipe():
    """An empty in-memory list merges to the same 14 — it cannot delete."""
    gh = FakeGH(REMOTE_14)
    A.req = gh
    A._write_internal([], allow_shrink=False)
    assert len(gh.rows) == 14, f"empty write changed the file to {len(gh.rows)}"
    assert {g["name"] for g in gh.rows} == {g["name"] for g in REMOTE_14}


def test_legacy_row_without_id_survives_a_merge():
    """The merge keys on _id. A legacy row without one used to fall out, and
    because the newcomer kept the count equal the length guard missed it."""
    legacy = [dict(g) for g in REMOTE_14] + [{"name": "No Id Guest", "guests": 1}]
    gh = FakeGH(legacy)
    A.req = gh
    A._write_internal([{"_id": "new001", "name": "Late"}], allow_shrink=False)
    names = {g["name"] for g in gh.rows}
    assert "No Id Guest" in names, "legacy row was silently dropped"
    assert "Late" in names
    assert len(gh.rows) == 16


def test_explicit_delete_may_shrink():
    gh = FakeGH(REMOTE_14)
    A.req = gh
    keep = [g for g in REMOTE_14 if g["_id"] != "id03"]
    A.write_data(keep, allow_shrink=True)
    assert len(gh.puts[0]) == 13


def test_update_in_place_does_not_duplicate():
    """Flipping confirmation_sent must not append a second copy."""
    gh = FakeGH(REMOTE_14)
    A.req = gh
    same = dict(REMOTE_14[0])
    same["confirmation_sent"] = True
    A.write_data([same])
    written = gh.puts[0]
    assert len(written) == 14
    assert sum(1 for g in written if g["_id"] == "id00") == 1
    assert [g for g in written if g["_id"] == "id00"][0]["confirmation_sent"] is True


def test_submit_returns_503_when_storage_is_down():
    """A guest must never see the thank-you screen for an unstored RSVP."""
    gh = FakeGH(REMOTE_14, get_status=401)
    A.req = gh
    client = A.app.test_client()
    r = client.post("/rsvp", json={"name": "Ana", "guests": 1})
    assert r.status_code == 503, f"got {r.status_code}: silent loss is back"
    assert r.get_json()["ok"] is False


def test_submit_succeeds_and_preserves_everyone():
    gh = FakeGH(REMOTE_14)
    A.req = gh
    client = A.app.test_client()
    r = client.post("/rsvp", json={"name": "Ana", "guests": 2})
    assert r.status_code == 200 and r.get_json()["ok"] is True
    assert len(gh.rows) == 15
    assert "Ana" in {g["name"] for g in gh.rows}


def test_list_reports_unavailable_rather_than_zero_guests():
    gh = FakeGH(REMOTE_14, get_status=500)
    A.req = gh
    client = A.app.test_client()
    r = client.get("/rsvp")
    assert r.status_code == 503
    assert r.get_json()["error"] == "storage_unavailable"


def test_missing_token_is_an_error_not_an_empty_list(monkeypatch):
    monkeypatch.setattr(A, "GH_TOKEN", "")
    with pytest.raises(A.PersistError):
        A.read_data()
