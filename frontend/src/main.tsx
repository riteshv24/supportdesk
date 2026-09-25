import React, { useEffect, useState, type FormEvent } from "react";
import { createRoot } from "react-dom/client";
import {
  Inbox,
  Activity,
  Users,
  Plus,
  Search,
  ArrowUpRight,
  X,
  LogOut,
  CheckCircle2,
  Circle,
  Clock3,
  ChevronLeft,
  ChevronRight,
  MessageSquare,
  RefreshCw,
  ArrowRight,
  LifeBuoy,
  ShieldCheck,
} from "lucide-react";
import "./styles.css";

type User = { id: number; name: string; email: string };
type Workspace = { id: number; name: string; role: string };
type Ticket = {
  id: number;
  title: string;
  description: string;
  status: string;
  priority: string;
  assignee_id: number | null;
  creator_id: number;
  version: number;
  updated_at: string;
  comments?: {
    id: number;
    body: string;
    author_id: number;
    created_at: string;
  }[];
};
type Event = {
  id: number;
  actor_id: number;
  ticket_id: number | null;
  action: string;
  created_at: string;
  details: Record<string, unknown>;
};
type Stats = {
  total: number;
  open: number;
  in_progress: number;
  resolved: number;
};
let token = sessionStorage.getItem("supportdesk-token") || "";
class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
  }
}
async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch("/api" + path, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...init.headers,
    },
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new ApiError(
      typeof data.detail === "string"
        ? data.detail
        : "Please check the form and try again.",
      response.status,
    );
  }
  return response.status === 204 ? (undefined as T) : response.json();
}
const label = (value: string) =>
  value.replaceAll("_", " ").replace(/^./, (s) => s.toUpperCase());
const initials = (name: string) =>
  name
    .split(" ")
    .slice(0, 2)
    .map((s) => s[0])
    .join("");
const date = (value: string) =>
  new Date(
    value.endsWith("Z") || /[+-]\d\d:\d\d$/.test(value) ? value : value + "Z",
  ).toLocaleDateString(undefined, { month: "short", day: "numeric" });
const errorText = (e: unknown) =>
  e instanceof Error ? e.message : "Something went wrong. Please try again.";
function App() {
  const [user, setUser] = useState<User | null>(null),
    [boot, setBoot] = useState(true),
    [register, setRegister] = useState(false),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]),
    [workspaceId, setWorkspaceId] = useState(0),
    [members, setMembers] = useState<User[]>([]),
    [tab, setTab] = useState("tickets");
  const [tickets, setTickets] = useState<Ticket[]>([]),
    [total, setTotal] = useState(0),
    [stats, setStats] = useState<Stats>({
      total: 0,
      open: 0,
      in_progress: 0,
      resolved: 0,
    }),
    [events, setEvents] = useState<Event[]>([]);
  const [q, setQ] = useState(""),
    [status, setStatus] = useState(""),
    [priority, setPriority] = useState(""),
    [page, setPage] = useState(1),
    [loading, setLoading] = useState(false),
    [reload, setReload] = useState(0);
  const [selected, setSelected] = useState<Ticket | null>(null),
    [create, setCreate] = useState(false),
    [modalError, setModalError] = useState(""),
    [notice, setNotice] = useState("");
  const current = workspaces.find((w) => w.id === workspaceId),
    base = `/workspaces/${workspaceId}`;
  const name = (id: number | null) =>
    members.find((m) => m.id === id)?.name ||
    (id ? "Team member" : "Unassigned");
  useEffect(() => {
    if (!token) {
      setBoot(false);
      return;
    }
    api<User>("/auth/me")
      .then(setUser)
      .catch(() => {
        token = "";
        sessionStorage.removeItem("supportdesk-token");
      })
      .finally(() => setBoot(false));
  }, []);
  useEffect(() => {
    if (user)
      api<Workspace[]>("/workspaces")
        .then((data) => {
          setWorkspaces(data);
          setWorkspaceId(data[0]?.id || 0);
        })
        .catch((e) => setError(errorText(e)));
  }, [user]);
  useEffect(() => {
    if (!workspaceId) return;
    let active = true;
    setLoading(true);
    setError("");
    const params = new URLSearchParams({
      q,
      page: String(page),
      page_size: "8",
      ...(status ? { status } : {}),
      ...(priority ? { priority } : {}),
    });
    Promise.all([
      api<{ items: Ticket[]; total: number }>(`${base}/tickets?${params}`),
      api<User[]>(`${base}/members`),
      api<Stats>(`${base}/stats`),
      api<Event[]>(`${base}/activity`),
    ])
      .then(([list, people, counts, activity]) => {
        if (active) {
          setTickets(list.items);
          setTotal(list.total);
          setMembers(people);
          setStats(counts);
          setEvents(activity);
        }
      })
      .catch((e) => {
        if (active) {
          setError(errorText(e));
          if (e instanceof ApiError && e.status === 401) {
            token = "";
            sessionStorage.removeItem("supportdesk-token");
            setUser(null);
          }
        }
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [workspaceId, q, status, priority, page, reload]);
  async function authenticate(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setBusy(true);
    setError("");
    const f = new FormData(e.currentTarget);
    const body = {
      email: f.get("email"),
      password: f.get("password"),
      ...(register
        ? { name: f.get("name"), workspace_name: f.get("workspace") }
        : {}),
    };
    try {
      const result = await api<{ token: string; user: User }>(
        `/auth/${register ? "register" : "login"}`,
        { method: "POST", body: JSON.stringify(body) },
      );
      token = result.token;
      sessionStorage.setItem("supportdesk-token", token);
      setUser(result.user);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }
  async function logout() {
    try {
      await api("/auth/logout", { method: "POST" });
    } catch {
      /* Expired sessions still permit local sign-out. */
    }
    token = "";
    sessionStorage.removeItem("supportdesk-token");
    setUser(null);
    setWorkspaceId(0);
    setSelected(null);
    setError("");
  }
  async function openTicket(id: number) {
    setModalError("");
    try {
      setSelected(await api<Ticket>(`${base}/tickets/${id}`));
    } catch (e) {
      setError(errorText(e));
    }
  }
  async function saveTicket(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setBusy(true);
    setModalError("");
    const f = new FormData(e.currentTarget);
    const assignee = f.get("assignee");
    const body = {
      title: f.get("title"),
      description: f.get("description"),
      priority: f.get("priority"),
      assignee_id: assignee ? Number(assignee) : null,
      ...(selected
        ? { version: selected.version, status: f.get("status") }
        : {}),
    };
    try {
      await api(`${base}/tickets${selected ? "/" + selected.id : ""}`, {
        method: selected ? "PATCH" : "POST",
        body: JSON.stringify(body),
      });
      setSelected(null);
      setCreate(false);
      setReload((n) => n + 1);
      setNotice(selected ? "Ticket updated." : "Ticket created.");
    } catch (e) {
      setModalError(errorText(e));
    } finally {
      setBusy(false);
    }
  }
  async function addComment(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!selected) return;
    setBusy(true);
    setModalError("");
    const form = e.currentTarget;
    try {
      await api(`${base}/tickets/${selected.id}/comments`, {
        method: "POST",
        body: JSON.stringify({ body: new FormData(form).get("body") }),
      });
      form.reset();
      await openTicket(selected.id);
      setReload((n) => n + 1);
    } catch (e) {
      setModalError(errorText(e));
    } finally {
      setBusy(false);
    }
  }
  async function archive() {
    if (
      !selected ||
      !window.confirm(
        "Archive this ticket? Its activity history will be retained.",
      )
    )
      return;
    setBusy(true);
    try {
      await api(`${base}/tickets/${selected.id}?version=${selected.version}`, {
        method: "DELETE",
      });
      setSelected(null);
      setReload((n) => n + 1);
      setNotice("Ticket archived.");
    } catch (e) {
      setModalError(errorText(e));
    } finally {
      setBusy(false);
    }
  }
  async function addMember(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setBusy(true);
    setError("");
    const form = e.currentTarget;
    try {
      await api(`${base}/members`, {
        method: "POST",
        body: JSON.stringify({ email: new FormData(form).get("email") }),
      });
      form.reset();
      setReload((n) => n + 1);
      setNotice("Member added.");
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }
  if (boot) return <div className="boot">Opening your workspace…</div>;
  if (!user)
    return (
      <main className="auth-layout">
        <section className="auth-story">
          <div className="brand">
            <LifeBuoy size={27} />
            <span>
              supportdesk<span className="brand-dot">.</span>
            </span>
          </div>
          <div>
            <div className="eyebrow">A CALMER WAY TO SUPPORT YOUR TEAM</div>
            <h1>
              Less chasing.
              <br />
              More resolving.
            </h1>
            <p>
              One shared place for requests, clear ownership, and the next step
              forward.
            </p>
            <div className="story-line">
              <ShieldCheck size={19} /> Workspace access, built in.
            </div>
          </div>
          <span className="auth-foot">
            Built for the people behind the work.
          </span>
        </section>
        <section className="auth-form">
          <div className="auth-form-inner">
            <span className="eyebrow">YOUR TEAM, IN SYNC</span>
            <h2>{register ? "Create your workspace" : "Welcome back"}</h2>
            <p>
              {register
                ? "Start with your own team. Invite registered colleagues when you’re ready."
                : "Sign in to see what needs your attention."}
            </p>
            {error && (
              <div className="error" role="alert">
                {error}
              </div>
            )}
            <form onSubmit={authenticate}>
              {register && (
                <>
                  <label>
                    Your name
                    <input
                      name="name"
                      autoComplete="name"
                      required
                      maxLength={80}
                      placeholder="Alex Morgan"
                    />
                  </label>
                  <label>
                    Workspace name
                    <input
                      name="workspace"
                      required
                      maxLength={80}
                      placeholder="Acme Engineering"
                    />
                  </label>
                </>
              )}
              <label>
                Email address
                <input
                  name="email"
                  type="email"
                  autoComplete="email"
                  required
                  placeholder="you@company.com"
                />
              </label>
              <label>
                Password
                <input
                  name="password"
                  type="password"
                  autoComplete={register ? "new-password" : "current-password"}
                  minLength={12}
                  maxLength={128}
                  required
                  placeholder="At least 12 characters"
                />
              </label>
              <button className="primary wide" disabled={busy}>
                {busy
                  ? "Please wait…"
                  : register
                    ? "Create workspace"
                    : "Sign in"}
                <ArrowRight size={17} />
              </button>
            </form>
            <p className="auth-switch">
              {register ? "Already have an account?" : "New to SupportDesk?"}{" "}
              <button
                className="text-button"
                onClick={() => {
                  setRegister(!register);
                  setError("");
                }}
              >
                {register ? "Sign in" : "Create a workspace"}
              </button>
            </p>
            <div className="demo-note">
              <strong>Exploring locally?</strong>
              <br />
              Run the demo seed command in the README, then sign in as{" "}
              <code>demo@supportdesk.local</code> with your supplied password.
            </div>
          </div>
        </section>
      </main>
    );
  return (
    <div className="app-layout">
      <aside className="sidebar">
        <div className="brand">
          <LifeBuoy size={24} />
          <span>
            supportdesk<span className="brand-dot">.</span>
          </span>
        </div>
        <label className="workspace-label">
          WORKSPACE
          <select
            aria-label="Select workspace"
            value={workspaceId}
            onChange={(e) => {
              setWorkspaceId(Number(e.target.value));
              setPage(1);
              setSelected(null);
            }}
          >
            {workspaces.map((w) => (
              <option value={w.id} key={w.id}>
                {w.name}
              </option>
            ))}
          </select>
        </label>
        <nav aria-label="Main navigation">
          {[
            ["tickets", Inbox, "Team inbox"],
            ["activity", Activity, "Activity log"],
            ["team", Users, "Team members"],
          ].map(([key, Icon, title]) => {
            const I = Icon as typeof Inbox;
            return (
              <button
                key={key as string}
                className={tab === key ? "nav-active" : ""}
                onClick={() => setTab(key as string)}
              >
                <I size={19} />
                {title as string}
                {key === "tickets" && (
                  <span className="nav-count">{stats.total}</span>
                )}
              </button>
            );
          })}
        </nav>
        <div className="sidebar-note">
          <span className="small-dot" /> A little clarity goes a long way.
          <p>Keep ownership visible and updates in one place.</p>
        </div>
        <div className="user-area">
          <span className="avatar">{initials(user.name)}</span>
          <div>
            <strong>{user.name}</strong>
            <small>
              {current?.role === "owner" ? "Workspace owner" : "Team member"}
            </small>
          </div>
          <button aria-label="Sign out" onClick={logout}>
            <LogOut size={17} />
          </button>
        </div>
      </aside>
      <div className="main-shell">
        <header className="topbar">
          <span>
            {current?.name}
            <span className="slash">/</span>
            <strong>
              {tab === "tickets"
                ? "Team inbox"
                : tab === "activity"
                  ? "Activity log"
                  : "Team members"}
            </strong>
          </span>
          <span className="top-right">
            <span className="small-dot" /> Shared workspace
          </span>
        </header>
        <main className="content">
          <div className="page-heading">
            <div className="eyebrow">MAKE ROOM FOR BETTER WORK</div>
            <div className="heading-row">
              <div>
                <h1>
                  {tab === "tickets"
                    ? "Every request. One clear view."
                    : tab === "activity"
                      ? "The story behind the work."
                      : "Good work takes a team."}
                </h1>
                <p>
                  {tab === "tickets"
                    ? "Triage requests, share updates, and keep things moving."
                    : tab === "activity"
                      ? "A record of changes across your workspace."
                      : "Give your colleagues a shared place to get things done."}
                </p>
              </div>
              {tab === "tickets" && (
                <button
                  className="primary"
                  onClick={() => {
                    setCreate(true);
                    setModalError("");
                  }}
                >
                  <Plus size={18} /> New ticket
                </button>
              )}
            </div>
          </div>
          {error && (
            <div className="error" role="alert">
              {error}
            </div>
          )}
          {notice && (
            <div className="notice" role="status">
              {notice}
              <button
                aria-label="Dismiss notification"
                onClick={() => setNotice("")}
              >
                <X size={16} />
              </button>
            </div>
          )}
          {tab === "tickets" && (
            <>
              <div className="stats-grid">
                {[
                  ["All tickets", stats.total, Inbox, "neutral"],
                  ["Open", stats.open, Circle, "blue"],
                  ["In progress", stats.in_progress, Clock3, "amber"],
                  ["Resolved", stats.resolved, CheckCircle2, "green"],
                ].map(([title, value, Icon, color]) => {
                  const I = Icon as typeof Inbox;
                  return (
                    <article className="stat-card" key={title as string}>
                      <span>
                        {title as string}
                        <I className={`stat-icon ${color}`} size={18} />
                      </span>
                      <strong>{value as number}</strong>
                      <small>
                        {title === "All tickets"
                          ? "Across your workspace"
                          : title === "Open"
                            ? "Ready for a first look"
                            : title === "In progress"
                              ? "Moving toward a solution"
                              : "A little less on your plate"}
                      </small>
                    </article>
                  );
                })}
              </div>
              <section className="ticket-section">
                <div className="list-heading">
                  <div>
                    <h2>
                      Team inbox <span>{total}</span>
                    </h2>
                    <p>The latest requests from your workspace.</p>
                  </div>
                  <button
                    className="icon-button"
                    title="Refresh tickets"
                    aria-label="Refresh tickets"
                    onClick={() => setReload((n) => n + 1)}
                  >
                    <RefreshCw size={17} />
                  </button>
                </div>
                <div className="filters">
                  <div className="search">
                    <Search size={17} />
                    <input
                      aria-label="Search tickets"
                      placeholder="Search by ticket title…"
                      value={q}
                      onChange={(e) => {
                        setQ(e.target.value);
                        setPage(1);
                      }}
                    />
                  </div>
                  <select
                    aria-label="Filter by status"
                    value={status}
                    onChange={(e) => {
                      setStatus(e.target.value);
                      setPage(1);
                    }}
                  >
                    <option value="">All statuses</option>
                    {["open", "in_progress", "resolved"].map((s) => (
                      <option value={s} key={s}>
                        {label(s)}
                      </option>
                    ))}
                  </select>
                  <select
                    aria-label="Filter by priority"
                    value={priority}
                    onChange={(e) => {
                      setPriority(e.target.value);
                      setPage(1);
                    }}
                  >
                    <option value="">All priorities</option>
                    {["urgent", "high", "medium", "low"].map((s) => (
                      <option key={s}>{s}</option>
                    ))}
                  </select>
                </div>
                <div className="table-scroll">
                  <table>
                    <thead>
                      <tr>
                        <th>Ticket</th>
                        <th>Status</th>
                        <th>Priority</th>
                        <th>Assignee</th>
                        <th>Updated</th>
                        <th>
                          <span className="sr-only">Open ticket</span>
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {tickets.map((t) => (
                        <tr key={t.id}>
                          <td>
                            <button
                              className="ticket-title"
                              onClick={() => openTicket(t.id)}
                            >
                              <small>SD-{String(t.id).padStart(3, "0")}</small>
                              <strong>{t.title}</strong>
                            </button>
                          </td>
                          <td>
                            <span className={`badge ${t.status}`}>
                              <span />
                              {label(t.status)}
                            </span>
                          </td>
                          <td>
                            <span className={`priority ${t.priority}`}>
                              <i />
                              {label(t.priority)}
                            </span>
                          </td>
                          <td>
                            <span className="assignee">
                              {t.assignee_id && (
                                <span className="avatar tiny">
                                  {initials(name(t.assignee_id))}
                                </span>
                              )}
                              {name(t.assignee_id)}
                            </span>
                          </td>
                          <td className="date-cell">{date(t.updated_at)}</td>
                          <td>
                            <button
                              className="row-open"
                              aria-label={`Open ${t.title}`}
                              onClick={() => openTicket(t.id)}
                            >
                              <ArrowUpRight size={17} />
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                {tickets.length === 0 && (
                  <div className="empty">
                    <Inbox size={30} />
                    <h3>
                      {loading ? "Loading your inbox…" : "Nothing here yet"}
                    </h3>
                    <p>
                      {q || status || priority
                        ? "Try another search or clear your filters."
                        : "Create your first ticket to get things moving."}
                    </p>
                  </div>
                )}
                <footer className="pagination">
                  <span>
                    {loading
                      ? "Refreshing…"
                      : `${total === 0 ? 0 : (page - 1) * 8 + 1}–${Math.min(page * 8, total)} of ${total} tickets`}
                  </span>
                  <div>
                    <button
                      aria-label="Previous page"
                      disabled={page === 1}
                      onClick={() => setPage((n) => n - 1)}
                    >
                      <ChevronLeft size={16} />
                    </button>
                    <span>Page {page}</span>
                    <button
                      aria-label="Next page"
                      disabled={page * 8 >= total}
                      onClick={() => setPage((n) => n + 1)}
                    >
                      <ChevronRight size={16} />
                    </button>
                  </div>
                </footer>
              </section>
              <div className="bottom-note">
                <ShieldCheck size={15} /> Every change leaves a trail. Your team
                stays in the loop.
              </div>
            </>
          )}
          {tab === "activity" && (
            <section className="panel">
              <h2>Workspace activity</h2>
              <p className="muted">
                Most recent 50 events. Ticket archives retain their history.
              </p>
              <div className="activity-list">
                {events.map((ev) => (
                  <article key={ev.id}>
                    <div className="activity-symbol">
                      <Activity size={17} />
                    </div>
                    <div>
                      <strong>{name(ev.actor_id)}</strong>{" "}
                      <span>
                        {ev.action
                          .replaceAll(".", " ")
                          .replace("ticket ", "a ticket was ")
                          .replace("comment added", "added a comment")}
                      </span>
                      <small>
                        {ev.ticket_id
                          ? `SD-${String(ev.ticket_id).padStart(3, "0")} · `
                          : ""}
                        {date(ev.created_at)}
                      </small>
                    </div>
                  </article>
                ))}
                {!events.length && (
                  <p className="muted">
                    Activity will appear when your team creates or updates work.
                  </p>
                )}
              </div>
            </section>
          )}
          {tab === "team" && (
            <section className="panel">
              <h2>People in {current?.name}</h2>
              <p className="muted">
                Members can read, comment on, assign, and update workspace
                tickets.
              </p>
              <div className="members-list">
                {members.map((m) => (
                  <article key={m.id}>
                    <span className="avatar">{initials(m.name)}</span>
                    <div>
                      <strong>{m.name}</strong>
                      <small>{m.email}</small>
                    </div>
                    {m.id === user.id && <span className="you-label">You</span>}
                  </article>
                ))}
              </div>
              {current?.role === "owner" && (
                <form className="invite-form" onSubmit={addMember}>
                  <h3>Add a colleague</h3>
                  <p>
                    Ask them to register first, then enter their account email.
                  </p>
                  <div>
                    <input
                      name="email"
                      aria-label="Colleague email"
                      type="email"
                      required
                      placeholder="colleague@company.com"
                    />
                    <button className="primary" disabled={busy}>
                      Add member
                    </button>
                  </div>
                </form>
              )}
            </section>
          )}
        </main>
      </div>
      {(selected || create) && (
        <div
          className="modal-backdrop"
          onClick={(e) => {
            if (e.target === e.currentTarget) {
              setSelected(null);
              setCreate(false);
            }
          }}
        >
          <section
            className="modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="ticket-dialog-title"
          >
            <header>
              <div>
                <span className="eyebrow">
                  {selected
                    ? `SD-${String(selected.id).padStart(3, "0")} · VERSION ${selected.version}`
                    : "A NEW REQUEST"}
                </span>
                <h2 id="ticket-dialog-title">
                  {selected ? "Ticket details" : "Create a ticket"}
                </h2>
              </div>
              <button
                className="icon-button"
                aria-label="Close ticket"
                onClick={() => {
                  setSelected(null);
                  setCreate(false);
                }}
              >
                <X size={20} />
              </button>
            </header>
            {modalError && (
              <div className="error" role="alert">
                {modalError}
                {selected && (
                  <button
                    type="button"
                    className="text-button"
                    onClick={() => openTicket(selected.id)}
                  >
                    {" "}
                    Reload latest version
                  </button>
                )}
              </div>
            )}
            <form
              key={`${selected?.id || "new"}-${selected?.version || 0}`}
              onSubmit={saveTicket}
            >
              <label>
                Title
                <input
                  name="title"
                  defaultValue={selected?.title}
                  required
                  maxLength={160}
                  placeholder="What can we help with?"
                  autoFocus
                />
              </label>
              <label>
                Description
                <textarea
                  name="description"
                  defaultValue={selected?.description}
                  maxLength={10000}
                  rows={4}
                  placeholder="Add context, steps to reproduce, or the outcome you need."
                />
              </label>
              <div className="form-grid">
                <label>
                  Priority
                  <select
                    aria-label="Priority"
                    name="priority"
                    defaultValue={selected?.priority || "medium"}
                  >
                    {["low", "medium", "high", "urgent"].map((s) => (
                      <option key={s} value={s}>
                        {label(s)}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Assignee
                  <select
                    aria-label="Assignee"
                    name="assignee"
                    defaultValue={selected?.assignee_id || ""}
                  >
                    <option value="">Unassigned</option>
                    {members.map((m) => (
                      <option key={m.id} value={m.id}>
                        {m.name}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
              {selected && (
                <label>
                  Status
                  <select
                    aria-label="Status"
                    name="status"
                    defaultValue={selected.status}
                  >
                    {(selected.status === "resolved"
                      ? ["resolved", "open"]
                      : ["open", "in_progress", "resolved"]
                    ).map((s) => (
                      <option key={s} value={s}>
                        {label(s)}
                      </option>
                    ))}
                  </select>
                </label>
              )}
              <div className="modal-actions">
                {selected &&
                  (current?.role === "owner" ||
                    selected.creator_id === user.id) && (
                    <button
                      type="button"
                      className="danger-link"
                      disabled={busy}
                      onClick={archive}
                    >
                      Archive ticket
                    </button>
                  )}
                <button className="primary" disabled={busy}>
                  {busy
                    ? "Saving…"
                    : selected
                      ? "Save changes"
                      : "Create ticket"}
                </button>
              </div>
            </form>
            {selected && (
              <section className="comments">
                <h3>
                  <MessageSquare size={17} /> Conversation{" "}
                  <span>{selected.comments?.length || 0}</span>
                </h3>
                {selected.comments?.map((c) => (
                  <article key={c.id}>
                    <span className="avatar tiny">
                      {initials(name(c.author_id))}
                    </span>
                    <div>
                      <strong>
                        {name(c.author_id)} <small>{date(c.created_at)}</small>
                      </strong>
                      <p>{c.body}</p>
                    </div>
                  </article>
                ))}
                {!selected.comments?.length && (
                  <p className="muted">
                    Keep context together. Add the first update.
                  </p>
                )}
                <form onSubmit={addComment}>
                  <textarea
                    name="body"
                    aria-label="Add an update"
                    placeholder="Share an update with your team…"
                    required
                    maxLength={5000}
                    rows={3}
                  />
                  <button className="secondary" disabled={busy}>
                    Post update
                  </button>
                </form>
              </section>
            )}
          </section>
        </div>
      )}
    </div>
  );
}
createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
