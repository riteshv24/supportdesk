"""Create an explicit local demo. Run with DEMO_PASSWORD set; safe to rerun."""

import os
from sqlalchemy import select
from .main import app
from .models import Base, User, Workspace, Membership, Ticket, Comment, AuditEvent
from .security import hash_password


def main():
    password = os.getenv("DEMO_PASSWORD", "")
    if not 12 <= len(password) <= 128:
        raise SystemExit(
            "Set DEMO_PASSWORD to a password between 12 and 128 characters."
        )
    Base.metadata.create_all(app.state.engine)
    with app.state.session_factory() as db:
        if db.scalar(select(User).where(User.email == "demo@supportdesk.local")):
            print(
                "Demo account already exists; existing data and password were preserved."
            )
            return
        owner = User(
            name="Alex Morgan",
            email="demo@supportdesk.local",
            password_hash=hash_password(password),
        )
        workspace = Workspace(name="Acme Engineering")
        db.add_all([owner, workspace])
        db.flush()
        db.add(Membership(workspace_id=workspace.id, user_id=owner.id, role="owner"))
        examples = [
            (
                "VPN connection drops during video calls",
                "Connection drops after 10–15 minutes on the office VPN. Reproduced on two laptops. Check gateway logs and client versions.",
                "high",
                "in_progress",
            ),
            (
                "Set up access for the new design team",
                "Provision the design workspace and confirm least-privilege access for the incoming team.",
                "medium",
                "open",
            ),
            (
                "Build runner is running out of disk space",
                "The CI runner reports 92% disk usage. Review retained artifacts before the next scheduled deployment.",
                "urgent",
                "open",
            ),
            (
                "Update onboarding documentation",
                "Add the new SSO sign-in flow and test the instructions with a fresh account.",
                "low",
                "open",
            ),
            (
                "Fix duplicate alert notifications",
                "The same monitoring event was routed to two channels. Removed the overlapping notification policy.",
                "medium",
                "resolved",
            ),
            (
                "Database dashboard needs read-only access",
                "Give the analytics team access to the service dashboard without write permissions.",
                "medium",
                "in_progress",
            ),
            (
                "Printer unavailable on the guest network",
                "Validated network isolation. Documented the supported staff-network printing flow.",
                "low",
                "resolved",
            ),
        ]
        for title, description, priority, status in examples:
            ticket = Ticket(
                workspace_id=workspace.id,
                creator_id=owner.id,
                assignee_id=owner.id if status != "open" else None,
                title=title,
                description=description,
                priority=priority,
                status=status,
            )
            db.add(ticket)
            db.flush()
            db.add(
                AuditEvent(
                    workspace_id=workspace.id,
                    actor_id=owner.id,
                    ticket_id=ticket.id,
                    action="ticket.created",
                    details={"title": title, "source": "demo seed"},
                )
            )
            if status == "in_progress":
                db.add(
                    Comment(
                        ticket_id=ticket.id,
                        author_id=owner.id,
                        body="Reproduced the issue. Investigation is in progress; I will post the next update here.",
                    )
                )
        db.commit()
    print(
        "Demo created: demo@supportdesk.local (use the password supplied in DEMO_PASSWORD)"
    )


if __name__ == "__main__":
    main()
