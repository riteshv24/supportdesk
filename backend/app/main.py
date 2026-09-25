import os
import secrets
from contextlib import asynccontextmanager
from datetime import timedelta
from fastapi import FastAPI, Depends, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import create_engine, select, func, update, event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker, Session as DBSession
from .models import (
    Base,
    User,
    Session,
    Workspace,
    Membership,
    Ticket,
    Comment,
    AuditEvent,
    now,
)
from .schemas import (
    Register,
    Credentials,
    TicketCreate,
    TicketPatch,
    CommentCreate,
    MemberCreate,
    Status,
    Priority,
)
from .security import hash_password, verify_password, token_digest

TRANSITIONS = {
    "open": {"in_progress", "resolved"},
    "in_progress": {"open", "resolved"},
    "resolved": {"open"},
}


def create_app(database_url: str | None = None):
    url = database_url or os.getenv("DATABASE_URL", "sqlite:///./supportdesk.db")
    engine = create_engine(
        url,
        connect_args={"check_same_thread": False} if url.startswith("sqlite") else {},
        pool_pre_ping=True,
    )
    if url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def sqlite_setup(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA busy_timeout=5000")

    factory = sessionmaker(engine, expire_on_commit=False)

    @asynccontextmanager
    async def lifespan(app):
        Base.metadata.create_all(engine)
        yield
        engine.dispose()

    app = FastAPI(title="SupportDesk API", version="1.0.0", lifespan=lifespan)
    app.state.session_factory = factory
    app.state.engine = engine
    app.add_middleware(
        CORSMiddleware,
        allow_origins=os.getenv(
            "CORS_ORIGINS", "http://localhost:5173,http://localhost:8080"
        ).split(","),
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )
    bearer = HTTPBearer(auto_error=False)
    # Equal-cost password check reduces email enumeration through login timing.
    dummy_hash = hash_password(secrets.token_urlsafe(24))

    def db():
        with factory() as session:
            yield session

    def current_user(
        credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
        session: DBSession = Depends(db),
    ):
        if not credentials:
            raise HTTPException(401, "Sign in to continue")
        user = session.scalar(
            select(User)
            .join(Session, Session.user_id == User.id)
            .where(
                Session.token_hash == token_digest(credentials.credentials),
                Session.expires_at > now(),
            )
        )
        if user is None:
            raise HTTPException(401, "Session expired or invalid")
        return user

    def member(
        workspace_id: int,
        user: User = Depends(current_user),
        session: DBSession = Depends(db),
    ):
        membership = session.scalar(
            select(Membership).where(
                Membership.workspace_id == workspace_id, Membership.user_id == user.id
            )
        )
        if membership is None:
            raise HTTPException(404, "Workspace not found")
        return membership

    def public_user(user):
        return {"id": user.id, "name": user.name, "email": user.email}

    def new_session(user, session):
        token = secrets.token_urlsafe(48)
        expires = now() + timedelta(hours=12)
        session.add(
            Session(user_id=user.id, token_hash=token_digest(token), expires_at=expires)
        )
        session.commit()
        return {"token": token, "expires_at": expires, "user": public_user(user)}

    def get_ticket(session, workspace_id, ticket_id):
        ticket = session.scalar(
            select(Ticket).where(
                Ticket.id == ticket_id,
                Ticket.workspace_id == workspace_id,
                Ticket.deleted.is_(False),
            )
        )
        if ticket is None:
            raise HTTPException(404, "Ticket not found")
        return ticket

    def assignment_valid(session, workspace_id, assignee_id):
        if (
            assignee_id is not None
            and session.scalar(
                select(Membership.id).where(
                    Membership.workspace_id == workspace_id,
                    Membership.user_id == assignee_id,
                )
            )
            is None
        ):
            raise HTTPException(422, "Assignee must belong to this workspace")

    def audit(session, workspace_id, actor_id, action, ticket_id=None, details=None):
        session.add(
            AuditEvent(
                workspace_id=workspace_id,
                actor_id=actor_id,
                action=action,
                ticket_id=ticket_id,
                details=details or {},
            )
        )

    def ticket_dict(t):
        return {
            key: getattr(t, key)
            for key in (
                "id",
                "workspace_id",
                "title",
                "description",
                "status",
                "priority",
                "creator_id",
                "assignee_id",
                "version",
                "created_at",
                "updated_at",
            )
        }

    @app.get("/api/health")
    def health(session: DBSession = Depends(db)):
        session.execute(select(1))
        return {"status": "ok"}

    @app.post("/api/auth/register", status_code=201)
    def register(body: Register, session: DBSession = Depends(db)):
        user = User(
            email=body.email, name=body.name, password_hash=hash_password(body.password)
        )
        workspace = Workspace(name=body.workspace_name)
        try:
            session.add_all([user, workspace])
            session.flush()
            session.add(
                Membership(workspace_id=workspace.id, user_id=user.id, role="owner")
            )
            return new_session(user, session)
        except IntegrityError:
            session.rollback()
            raise HTTPException(409, "An account with that email already exists")

    @app.post("/api/auth/login")
    def login(body: Credentials, session: DBSession = Depends(db)):
        user = session.scalar(select(User).where(User.email == body.email))
        valid = verify_password(
            body.password, user.password_hash if user else dummy_hash
        )
        if user is None or not valid:
            raise HTTPException(401, "Email or password is incorrect")
        return new_session(user, session)

    @app.get("/api/auth/me")
    def me(user: User = Depends(current_user)):
        return public_user(user)

    @app.post("/api/auth/logout", status_code=204)
    def logout(
        user: User = Depends(current_user),
        credentials: HTTPAuthorizationCredentials = Depends(bearer),
        session: DBSession = Depends(db),
    ):
        saved = session.scalar(
            select(Session).where(
                Session.token_hash == token_digest(credentials.credentials)
            )
        )
        session.delete(saved)
        session.commit()
        return Response(status_code=204)

    @app.get("/api/workspaces")
    def workspaces(
        user: User = Depends(current_user), session: DBSession = Depends(db)
    ):
        rows = session.execute(
            select(Workspace, Membership.role)
            .join(Membership)
            .where(Membership.user_id == user.id)
        ).all()
        return [{"id": w.id, "name": w.name, "role": role} for w, role in rows]

    @app.get("/api/workspaces/{workspace_id}/members")
    def members(
        workspace_id: int, membership=Depends(member), session: DBSession = Depends(db)
    ):
        return [
            public_user(u)
            for u in session.scalars(
                select(User)
                .join(Membership)
                .where(Membership.workspace_id == workspace_id)
            ).all()
        ]

    @app.post("/api/workspaces/{workspace_id}/members", status_code=201)
    def add_member(
        workspace_id: int,
        body: MemberCreate,
        membership=Depends(member),
        session: DBSession = Depends(db),
    ):
        if membership.role != "owner":
            raise HTTPException(403, "Only the workspace owner can add members")
        user = session.scalar(select(User).where(User.email == body.email.lower()))
        if user is None:
            raise HTTPException(
                404, "Account not found. Ask this person to register first."
            )
        try:
            session.add(
                Membership(workspace_id=workspace_id, user_id=user.id, role="member")
            )
            audit(
                session,
                workspace_id,
                membership.user_id,
                "member.added",
                details={"user_id": user.id},
            )
            session.commit()
        except IntegrityError:
            session.rollback()
            raise HTTPException(409, "User is already a workspace member")
        return public_user(user)

    @app.get("/api/workspaces/{workspace_id}/stats")
    def stats(
        workspace_id: int, membership=Depends(member), session: DBSession = Depends(db)
    ):
        result = {"open": 0, "in_progress": 0, "resolved": 0}
        for status, count in session.execute(
            select(Ticket.status, func.count())
            .where(Ticket.workspace_id == workspace_id, Ticket.deleted.is_(False))
            .group_by(Ticket.status)
        ):
            result[status] = count
        result["total"] = sum(result.values())
        return result

    @app.get("/api/workspaces/{workspace_id}/tickets")
    def tickets(
        workspace_id: int,
        q: str = Query("", max_length=160),
        status: Status | None = None,
        priority: Priority | None = None,
        page: int = Query(1, ge=1),
        page_size: int = Query(10, ge=1, le=50),
        membership=Depends(member),
        session: DBSession = Depends(db),
    ):
        filters = [Ticket.workspace_id == workspace_id, Ticket.deleted.is_(False)]
        if q:
            filters.append(Ticket.title.icontains(q, autoescape=True))
        if status:
            filters.append(Ticket.status == status)
        if priority:
            filters.append(Ticket.priority == priority)
        total = session.scalar(select(func.count()).select_from(Ticket).where(*filters))
        rows = session.scalars(
            select(Ticket)
            .where(*filters)
            .order_by(Ticket.updated_at.desc(), Ticket.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return {
            "items": [ticket_dict(t) for t in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    @app.post("/api/workspaces/{workspace_id}/tickets", status_code=201)
    def create_ticket(
        workspace_id: int,
        body: TicketCreate,
        membership=Depends(member),
        session: DBSession = Depends(db),
    ):
        assignment_valid(session, workspace_id, body.assignee_id)
        t = Ticket(
            workspace_id=workspace_id,
            creator_id=membership.user_id,
            **body.model_dump()
        )
        session.add(t)
        session.flush()
        audit(
            session,
            workspace_id,
            membership.user_id,
            "ticket.created",
            t.id,
            {"title": t.title},
        )
        session.commit()
        return ticket_dict(t)

    @app.get("/api/workspaces/{workspace_id}/tickets/{ticket_id}")
    def detail(
        workspace_id: int,
        ticket_id: int,
        membership=Depends(member),
        session: DBSession = Depends(db),
    ):
        t = get_ticket(session, workspace_id, ticket_id)
        comments = session.scalars(
            select(Comment)
            .where(Comment.ticket_id == ticket_id)
            .order_by(Comment.created_at, Comment.id)
        )
        return {
            **ticket_dict(t),
            "comments": [
                {
                    "id": c.id,
                    "body": c.body,
                    "author_id": c.author_id,
                    "created_at": c.created_at,
                }
                for c in comments
            ],
        }

    @app.patch("/api/workspaces/{workspace_id}/tickets/{ticket_id}")
    def patch_ticket(
        workspace_id: int,
        ticket_id: int,
        body: TicketPatch,
        membership=Depends(member),
        session: DBSession = Depends(db),
    ):
        t = get_ticket(session, workspace_id, ticket_id)
        if t.version != body.version:
            raise HTTPException(409, "This ticket changed. Reload it before saving.")
        changes = body.model_dump(exclude_unset=True, exclude={"version"})
        if any(value is None for key, value in changes.items() if key != "assignee_id"):
            raise HTTPException(422, "Only assignee_id can be null")
        if not changes:
            raise HTTPException(422, "Provide at least one changed field")
        if "assignee_id" in changes:
            assignment_valid(session, workspace_id, changes["assignee_id"])
        if (
            "status" in changes
            and changes["status"] != t.status
            and changes["status"] not in TRANSITIONS[t.status]
        ):
            raise HTTPException(
                422, "Reopen a resolved ticket before starting work again"
            )
        changes.update(version=body.version + 1, updated_at=now())
        result = session.execute(
            update(Ticket)
            .where(
                Ticket.id == ticket_id,
                Ticket.workspace_id == workspace_id,
                Ticket.version == body.version,
                Ticket.deleted.is_(False),
            )
            .values(**changes)
        )
        if result.rowcount != 1:
            session.rollback()
            raise HTTPException(409, "This ticket changed. Reload it before saving.")
        audit(
            session,
            workspace_id,
            membership.user_id,
            "ticket.updated",
            ticket_id,
            {
                k: v
                for k, v in changes.items()
                if k not in {"updated_at", "description"}
            },
        )
        session.commit()
        session.refresh(t)
        return ticket_dict(t)

    @app.delete("/api/workspaces/{workspace_id}/tickets/{ticket_id}", status_code=204)
    def delete_ticket(
        workspace_id: int,
        ticket_id: int,
        version: int = Query(..., ge=1),
        membership=Depends(member),
        session: DBSession = Depends(db),
    ):
        t = get_ticket(session, workspace_id, ticket_id)
        if membership.role != "owner" and t.creator_id != membership.user_id:
            raise HTTPException(
                403, "Only the creator or workspace owner can archive this ticket"
            )
        result = session.execute(
            update(Ticket)
            .where(
                Ticket.id == ticket_id,
                Ticket.workspace_id == workspace_id,
                Ticket.version == version,
                Ticket.deleted.is_(False),
            )
            .values(deleted=True, version=version + 1, updated_at=now())
        )
        if result.rowcount != 1:
            session.rollback()
            raise HTTPException(409, "This ticket changed. Reload it before archiving.")
        audit(session, workspace_id, membership.user_id, "ticket.archived", ticket_id)
        session.commit()
        return Response(status_code=204)

    @app.post(
        "/api/workspaces/{workspace_id}/tickets/{ticket_id}/comments", status_code=201
    )
    def comment(
        workspace_id: int,
        ticket_id: int,
        body: CommentCreate,
        membership=Depends(member),
        session: DBSession = Depends(db),
    ):
        get_ticket(session, workspace_id, ticket_id)
        c = Comment(ticket_id=ticket_id, author_id=membership.user_id, body=body.body)
        session.add(c)
        session.flush()
        audit(
            session,
            workspace_id,
            membership.user_id,
            "comment.added",
            ticket_id,
            {"comment_id": c.id},
        )
        session.commit()
        return {
            "id": c.id,
            "body": c.body,
            "author_id": c.author_id,
            "created_at": c.created_at,
        }

    @app.get("/api/workspaces/{workspace_id}/activity")
    def activity(
        workspace_id: int,
        ticket_id: int | None = None,
        membership=Depends(member),
        session: DBSession = Depends(db),
    ):
        query = select(AuditEvent).where(AuditEvent.workspace_id == workspace_id)
        if ticket_id is not None:
            query = query.where(AuditEvent.ticket_id == ticket_id)
        events = session.scalars(
            query.order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc()).limit(50)
        )
        return [
            {
                "id": a.id,
                "actor_id": a.actor_id,
                "ticket_id": a.ticket_id,
                "action": a.action,
                "details": a.details,
                "created_at": a.created_at,
            }
            for a in events
        ]

    return app


app = create_app()
