import os
from datetime import timedelta
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from app.main import create_app
from app.models import Base, Session, Ticket, AuditEvent, now

PASSWORD = "TestPassword-42!"


@pytest.fixture
def client(tmp_path):
    url = os.getenv("TEST_DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    app = create_app(url)
    # TEST_DATABASE_URL must point to a disposable database, never development data.
    if os.getenv("TEST_DATABASE_URL"):
        Base.metadata.drop_all(app.state.engine)
    with TestClient(app) as c:
        yield c


def register(client, email="owner@example.test"):
    result = client.post(
        "/api/auth/register",
        json={
            "email": email,
            "password": PASSWORD,
            "name": email.split("@")[0],
            "workspace_name": "Test workspace",
        },
    )
    assert result.status_code == 201, result.text
    headers = {"Authorization": "Bearer " + result.json()["token"]}
    workspace = client.get("/api/workspaces", headers=headers).json()[0]["id"]
    return headers, workspace, result.json()


def ticket(client, headers, workspace, **kwargs):
    result = client.post(
        f"/api/workspaces/{workspace}/tickets",
        headers=headers,
        json={"title": "Fix the build runner", **kwargs},
    )
    assert result.status_code == 201, result.text
    return result.json()


def test_registration_login_and_revocation(client):
    headers, workspace, account = register(client)
    assert (
        client.get("/api/auth/me", headers=headers).json()["email"]
        == "owner@example.test"
    )
    assert client.get(f"/api/workspaces/{workspace}/tickets").status_code == 401
    assert (
        client.post(
            "/api/auth/login",
            json={"email": "owner@example.test", "password": "IncorrectPassword"},
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/api/auth/login",
            json={"email": "owner@example.test", "password": PASSWORD},
        ).status_code
        == 200
    )
    with client.app.state.session_factory() as db:
        tokens = list(db.scalars(select(Session.token_hash)))
        assert account["token"] not in tokens
        assert all(len(value) == 64 for value in tokens)
    assert client.post("/api/auth/logout", headers=headers).status_code == 204
    assert client.get("/api/auth/me", headers=headers).status_code == 401


def test_expired_token_cannot_access_data(client):
    headers, _, _ = register(client)
    with client.app.state.session_factory() as db:
        session = db.scalar(select(Session))
        session.expires_at = now() - timedelta(seconds=1)
        db.commit()
    assert client.get("/api/workspaces", headers=headers).status_code == 401


def test_workspace_isolation_all_ticket_routes(client):
    owner, a, _ = register(client)
    other, b, _ = register(client, "other@example.test")
    t = ticket(client, owner, a)
    root = f"/api/workspaces/{a}"
    assert client.get(root + "/tickets", headers=other).status_code == 404
    assert client.get(root + "/members", headers=other).status_code == 404
    assert client.get(root + "/activity", headers=other).status_code == 404
    assert client.get(root + "/stats", headers=other).status_code == 404
    assert (
        client.post(
            root + "/tickets", headers=other, json={"title": "attack"}
        ).status_code
        == 404
    )
    # Membership in another workspace must not authorize a ticket ID from this one.
    wrong = f"/api/workspaces/{b}/tickets/{t['id']}"
    assert client.get(wrong, headers=other).status_code == 404
    assert (
        client.patch(
            wrong, headers=other, json={"version": 1, "title": "attack"}
        ).status_code
        == 404
    )
    assert client.delete(wrong + "?version=1", headers=other).status_code == 404
    assert (
        client.post(
            wrong + "/comments", headers=other, json={"body": "attack"}
        ).status_code
        == 404
    )


def test_assignment_and_membership_permissions(client):
    owner, a, _ = register(client)
    other, _, account = register(client, "other@example.test")
    base = f"/api/workspaces/{a}"
    assert (
        client.post(
            base + "/tickets",
            headers=owner,
            json={"title": "Unsafe assign", "assignee_id": account["user"]["id"]},
        ).status_code
        == 422
    )
    assert (
        client.post(
            base + "/members", headers=owner, json={"email": "other@example.test"}
        ).status_code
        == 201
    )
    t = ticket(client, owner, a, assignee_id=account["user"]["id"])
    assert client.get(base + f"/tickets/{t['id']}", headers=other).status_code == 200
    assert (
        client.post(
            base + "/members", headers=other, json={"email": "owner@example.test"}
        ).status_code
        == 403
    )
    assert (
        client.delete(base + f"/tickets/{t['id']}?version=1", headers=other).status_code
        == 403
    )


def test_stale_writes_do_not_overwrite_ticket(client):
    headers, wid, _ = register(client)
    t = ticket(client, headers, wid)
    path = f"/api/workspaces/{wid}/tickets/{t['id']}"
    saved = client.patch(
        path, headers=headers, json={"version": 1, "title": "First editor saved"}
    )
    assert saved.status_code == 200 and saved.json()["version"] == 2
    assert (
        client.patch(
            path, headers=headers, json={"version": 1, "title": "Stale editor"}
        ).status_code
        == 409
    )
    assert client.delete(path + "?version=1", headers=headers).status_code == 409
    assert client.get(path, headers=headers).json()["title"] == "First editor saved"
    events = client.get(f"/api/workspaces/{wid}/activity", headers=headers).json()
    assert sum(e["action"] == "ticket.updated" for e in events) == 1


def test_status_rules_comments_and_archive_retention(client):
    headers, wid, account = register(client)
    t = ticket(client, headers, wid)
    path = f"/api/workspaces/{wid}/tickets/{t['id']}"
    assert (
        client.patch(
            path, headers=headers, json={"version": 1, "status": "resolved"}
        ).status_code
        == 200
    )
    assert (
        client.patch(
            path, headers=headers, json={"version": 2, "status": "in_progress"}
        ).status_code
        == 422
    )
    assert (
        client.patch(
            path, headers=headers, json={"version": 2, "status": "open"}
        ).status_code
        == 200
    )
    comment = client.post(
        path + "/comments", headers=headers, json={"body": "A reproducible update"}
    )
    assert comment.status_code == 201
    detail = client.get(path, headers=headers).json()
    assert detail["comments"][0]["author_id"] == account["user"]["id"]
    assert detail["version"] == 3  # Comments do not mutate ticket-edit versions.
    assert client.delete(path + "?version=3", headers=headers).status_code == 204
    assert client.get(path, headers=headers).status_code == 404
    assert (
        client.get(f"/api/workspaces/{wid}/stats", headers=headers).json()["total"] == 0
    )
    events = client.get(f"/api/workspaces/{wid}/activity", headers=headers).json()
    assert events[0]["action"] == "ticket.archived"
    with client.app.state.session_factory() as db:
        assert db.get(Ticket, t["id"]).deleted
        assert (
            db.scalar(select(AuditEvent).where(AuditEvent.action == "comment.added"))
            is not None
        )


def test_search_filters_and_pagination(client):
    headers, wid, _ = register(client)
    ticket(client, headers, wid, title="100% disk full", priority="urgent")
    ticket(client, headers, wid, title="VPN access", priority="low")
    root = f"/api/workspaces/{wid}/tickets"
    result = client.get(root + "?q=%25", headers=headers).json()
    assert result["total"] == 1 and result["items"][0]["title"] == "100% disk full"
    assert client.get(root + "?priority=urgent", headers=headers).json()["total"] == 1
    first = client.get(root + "?page_size=1&page=1", headers=headers).json()
    second = client.get(root + "?page_size=1&page=2", headers=headers).json()
    assert first["total"] == 2 and first["items"][0]["id"] != second["items"][0]["id"]
    assert client.get(root + "?page_size=1000", headers=headers).status_code == 422


def test_validation_and_duplicate_account(client):
    headers, wid, _ = register(client)
    assert (
        client.post(
            "/api/auth/register",
            json={
                "email": "owner@example.test",
                "password": PASSWORD,
                "name": "Owner",
                "workspace_name": "Other",
            },
        ).status_code
        == 409
    )
    assert (
        client.post(
            "/api/auth/register",
            json={
                "email": "bad",
                "password": "short",
                "name": "",
                "workspace_name": "",
            },
        ).status_code
        == 422
    )
    assert (
        client.post(
            f"/api/workspaces/{wid}/tickets", headers=headers, json={"title": "   "}
        ).status_code
        == 422
    )
    t = ticket(client, headers, wid)
    assert (
        client.patch(
            f"/api/workspaces/{wid}/tickets/{t['id']}",
            headers=headers,
            json={"version": 1, "title": None},
        ).status_code
        == 422
    )
    assert (
        client.patch(
            f"/api/workspaces/{wid}/tickets/{t['id']}",
            headers=headers,
            json={"version": 1, "workspace_id": 500},
        ).status_code
        == 422
    )
