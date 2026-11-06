import datetime

from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def test_create_and_list_habit():
    r = client.post("/habits", json={"name": "Read 20 minutes"})
    assert r.status_code == 200
    hid = r.json()["id"]
    r2 = client.get("/habits")
    assert r2.status_code == 200
    assert any(h["id"] == hid for h in r2.json())


def test_checkin_flow():
    hid = client.post("/habits", json={"name": "Stretch"}).json()["id"]
    r = client.post(f"/habits/{hid}/checkin", json={"day": "2026-09-22"})
    assert r.status_code == 200
    r2 = client.get(f"/habits/{hid}/checkins")
    assert r2.json() == ["2026-09-22"]


def test_checkin_unknown_habit_404():
    r = client.post("/habits/99999/checkin", json={"day": "2026-09-22"})
    assert r.status_code == 404


def test_streak_zero():
    hid = client.post("/habits", json={"name": "Meditate"}).json()["id"]
    r = client.get(f"/habits/{hid}/streak")
    assert r.status_code == 200
    assert r.json() == {"streak": 0}


def test_streak_today():
    hid = client.post("/habits", json={"name": "Read"}).json()["id"]
    today = datetime.date.today().isoformat()
    client.post(f"/habits/{hid}/checkin", json={"day": today})
    r = client.get(f"/habits/{hid}/streak")
    assert r.status_code == 200
    assert r.json() == {"streak": 1}


def test_streak_consecutive():
    hid = client.post("/habits", json={"name": "Exercise"}).json()["id"]
    today = datetime.date.today()
    yesterday = today - datetime.timedelta(days=1)

    client.post(f"/habits/{hid}/checkin", json={"day": yesterday.isoformat()})
    client.post(f"/habits/{hid}/checkin", json={"day": today.isoformat()})

    r = client.get(f"/habits/{hid}/streak")
    assert r.status_code == 200
    assert r.json() == {"streak": 2}


def test_streak_with_gap():
    hid = client.post("/habits", json={"name": "Code"}).json()["id"]
    today = datetime.date.today()
    old_day = today - datetime.timedelta(days=5)

    client.post(f"/habits/{hid}/checkin", json={"day": old_day.isoformat()})
    r = client.get(f"/habits/{hid}/streak")
    assert r.status_code == 200
    assert r.json() == {"streak": 0}


def test_streak_unknown_habit_404():
    r = client.get("/habits/99999/streak")
    assert r.status_code == 404
