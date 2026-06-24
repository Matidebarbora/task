from __future__ import annotations

import sqlite3
from pathlib import Path

DB_PATH = Path.home() / ".tasky" / "tasky.db"


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _conn() as c:
        c.executescript("""
            CREATE TABLE IF NOT EXISTS projects (
                name  TEXT PRIMARY KEY,
                color TEXT NOT NULL DEFAULT 'cyan'
            );
            CREATE TABLE IF NOT EXISTS users (
                username     TEXT PRIMARY KEY,
                display_name TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS tasks (
                id          INTEGER PRIMARY KEY,
                project     TEXT NOT NULL,
                task        TEXT NOT NULL,
                priority    TEXT NOT NULL DEFAULT '2. MEDIUM',
                status      TEXT NOT NULL DEFAULT 'TO DO',
                notes       TEXT,
                sort_order  INTEGER NOT NULL DEFAULT 0,
                assigned_to TEXT
            );
            CREATE TABLE IF NOT EXISTS sub_tasks (
                id         INTEGER PRIMARY KEY,
                task_id    INTEGER NOT NULL,
                task       TEXT NOT NULL,
                status     TEXT NOT NULL DEFAULT 'TO DO',
                notes      TEXT,
                sort_order INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS project_logs (
                id       INTEGER PRIMARY KEY,
                project  TEXT NOT NULL,
                log_date TEXT NOT NULL,
                title    TEXT NOT NULL,
                notes    TEXT NOT NULL DEFAULT ''
            );
        """)


def has_local_data() -> bool:
    try:
        with _conn() as c:
            return c.execute("SELECT 1 FROM projects LIMIT 1").fetchone() is not None
    except Exception:
        return False


def local_replace_all(
    projects: list[dict],
    users: list[dict],
    tasks: list[dict],
    sub_tasks: list[dict],
    project_logs: list[dict],
) -> None:
    with _conn() as c:
        c.execute("DELETE FROM project_logs")
        c.execute("DELETE FROM sub_tasks")
        c.execute("DELETE FROM tasks")
        c.execute("DELETE FROM users")
        c.execute("DELETE FROM projects")
        for r in projects:
            c.execute("INSERT INTO projects VALUES (?,?)", (r["name"], r["color"]))
        for r in users:
            c.execute("INSERT INTO users VALUES (?,?)", (r["username"], r["display_name"]))
        for r in tasks:
            c.execute(
                "INSERT INTO tasks VALUES (?,?,?,?,?,?,?,?)",
                (r["id"], r["project"], r["task"], r["priority"],
                 r["status"], r.get("notes"), r.get("sort_order", 0), r.get("assigned_to")),
            )
        for r in sub_tasks:
            c.execute(
                "INSERT INTO sub_tasks VALUES (?,?,?,?,?,?)",
                (r["id"], r["task_id"], r["task"], r["status"],
                 r.get("notes"), r.get("sort_order", 0)),
            )
        for r in project_logs:
            c.execute(
                "INSERT INTO project_logs VALUES (?,?,?,?,?)",
                (r["id"], r["project"], r["log_date"], r["title"], r.get("notes", "")),
            )


# ---------------------------------------------------------------------------
# READ
# ---------------------------------------------------------------------------

def local_load_data() -> dict:
    with _conn() as c:
        proj_rows = c.execute("SELECT name, color FROM projects ORDER BY name").fetchall()
        project_colors = {r["name"]: r["color"] for r in proj_rows}
        projects: dict[str, list] = {r["name"]: [] for r in proj_rows}

        task_rows = c.execute(
            "SELECT * FROM tasks ORDER BY project, sort_order, id"
        ).fetchall()
        task_ids = [r["id"] for r in task_rows]

        sub_map: dict[int, list] = {tid: [] for tid in task_ids}
        if task_ids:
            ph = ",".join("?" * len(task_ids))
            sub_rows = c.execute(
                f"SELECT * FROM sub_tasks WHERE task_id IN ({ph}) ORDER BY sort_order, id",
                task_ids,
            ).fetchall()
            for s in sub_rows:
                sub_map[s["task_id"]].append({
                    "task": s["task"], "status": s["status"],
                    "notes": s["notes"], "_id": s["id"],
                })

        for t in task_rows:
            projects[t["project"]].append({
                "task": t["task"], "priority": t["priority"],
                "status": t["status"], "notes": t["notes"],
                "assigned_to": t["assigned_to"],
                "sub_tasks": sub_map[t["id"]],
                "_id": t["id"],
            })

    return {"projects": projects, "project_colors": project_colors}


def local_get_users() -> list[str]:
    with _conn() as c:
        return [r["username"] for r in c.execute("SELECT username FROM users ORDER BY username").fetchall()]


def local_get_task(task_id: int) -> dict | None:
    with _conn() as c:
        r = c.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        return dict(r) if r else None


def local_get_subtask(sub_id: int) -> dict | None:
    with _conn() as c:
        r = c.execute("SELECT * FROM sub_tasks WHERE id=?", (sub_id,)).fetchone()
        return dict(r) if r else None


def local_get_subtask_parent(sub_id: int) -> int | None:
    with _conn() as c:
        r = c.execute("SELECT task_id FROM sub_tasks WHERE id=?", (sub_id,)).fetchone()
        return r["task_id"] if r else None


def local_get_project_for_task(task_id: int) -> str | None:
    with _conn() as c:
        r = c.execute("SELECT project FROM tasks WHERE id=?", (task_id,)).fetchone()
        return r["project"] if r else None


def local_get_project_logs(project: str) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT id, log_date, title, notes FROM project_logs "
            "WHERE project=? ORDER BY log_date DESC, id DESC",
            (project,),
        ).fetchall()
        return [dict(r) for r in rows]


def local_get_log_by_id(log_id: int) -> dict | None:
    with _conn() as c:
        r = c.execute(
            "SELECT id, log_date, title, notes FROM project_logs WHERE id=?", (log_id,)
        ).fetchone()
        return dict(r) if r else None


# ---------------------------------------------------------------------------
# PROJECTS
# ---------------------------------------------------------------------------

def local_add_project(name: str, color: str) -> None:
    with _conn() as c:
        c.execute("INSERT OR IGNORE INTO projects VALUES (?,?)", (name, color))


def local_update_project(old_name: str, new_name: str | None, new_color: str | None) -> None:
    with _conn() as c:
        if new_color:
            c.execute("UPDATE projects SET color=? WHERE name=?", (new_color, old_name))
        if new_name and new_name != old_name:
            c.execute("UPDATE tasks SET project=? WHERE project=?", (new_name, old_name))
            c.execute("UPDATE project_logs SET project=? WHERE project=?", (new_name, old_name))
            c.execute("UPDATE projects SET name=? WHERE name=?", (new_name, old_name))


def local_delete_project(name: str) -> None:
    with _conn() as c:
        task_ids = [r[0] for r in c.execute("SELECT id FROM tasks WHERE project=?", (name,)).fetchall()]
        if task_ids:
            ph = ",".join("?" * len(task_ids))
            c.execute(f"DELETE FROM sub_tasks WHERE task_id IN ({ph})", task_ids)
        c.execute("DELETE FROM tasks WHERE project=?", (name,))
        c.execute("DELETE FROM project_logs WHERE project=?", (name,))
        c.execute("DELETE FROM projects WHERE name=?", (name,))


# ---------------------------------------------------------------------------
# TASKS
# ---------------------------------------------------------------------------

def local_add_task(
    task_id: int, project: str, task: str, priority: str,
    status: str, notes: str | None, sort_order: int, assigned_to: str | None = None,
) -> None:
    with _conn() as c:
        c.execute(
            "INSERT OR REPLACE INTO tasks VALUES (?,?,?,?,?,?,?,?)",
            (task_id, project, task, priority, status, notes, sort_order, assigned_to),
        )


def local_update_task(
    task_id: int, task: str, priority: str, status: str,
    notes: str | None, assigned_to: str | None = None,
) -> None:
    with _conn() as c:
        c.execute(
            "UPDATE tasks SET task=?, priority=?, status=?, notes=?, assigned_to=? WHERE id=?",
            (task, priority, status, notes, assigned_to, task_id),
        )


def local_delete_task(task_id: int) -> None:
    with _conn() as c:
        c.execute("DELETE FROM sub_tasks WHERE task_id=?", (task_id,))
        c.execute("DELETE FROM tasks WHERE id=?", (task_id,))


# ---------------------------------------------------------------------------
# SUB-TASKS
# ---------------------------------------------------------------------------

def local_add_subtask(
    sub_id: int, task_id: int, task: str,
    status: str, notes: str | None, sort_order: int,
) -> None:
    with _conn() as c:
        c.execute(
            "INSERT OR REPLACE INTO sub_tasks VALUES (?,?,?,?,?,?)",
            (sub_id, task_id, task, status, notes, sort_order),
        )


def local_update_subtask(sub_id: int, task: str, status: str, notes: str | None) -> None:
    with _conn() as c:
        c.execute(
            "UPDATE sub_tasks SET task=?, status=?, notes=? WHERE id=?",
            (task, status, notes, sub_id),
        )


def local_delete_subtask(sub_id: int) -> None:
    with _conn() as c:
        c.execute("DELETE FROM sub_tasks WHERE id=?", (sub_id,))


# ---------------------------------------------------------------------------
# PROJECT LOGS
# ---------------------------------------------------------------------------

def local_add_project_log(log_id: int, project: str, log_date: str, title: str, notes: str) -> None:
    with _conn() as c:
        c.execute(
            "INSERT OR REPLACE INTO project_logs VALUES (?,?,?,?,?)",
            (log_id, project, log_date, title, notes),
        )


def local_update_project_log(log_id: int, log_date: str, title: str, notes: str) -> None:
    with _conn() as c:
        c.execute(
            "UPDATE project_logs SET log_date=?, title=?, notes=? WHERE id=?",
            (log_date, title, notes, log_id),
        )


def local_delete_project_log(log_id: int) -> None:
    with _conn() as c:
        c.execute("DELETE FROM project_logs WHERE id=?", (log_id,))


# ---------------------------------------------------------------------------
# USERS
# ---------------------------------------------------------------------------

def local_ensure_user(username: str, display_name: str) -> None:
    with _conn() as c:
        c.execute("INSERT OR IGNORE INTO users VALUES (?,?)", (username, display_name))


def local_get_all_users() -> list[dict]:
    with _conn() as c:
        rows = c.execute("SELECT username, display_name FROM users ORDER BY username").fetchall()
        return [dict(r) for r in rows]


def local_update_user(username: str, display_name: str) -> None:
    with _conn() as c:
        c.execute("UPDATE users SET display_name=? WHERE username=?", (display_name, username))


def local_delete_user(username: str) -> None:
    with _conn() as c:
        c.execute("UPDATE tasks SET assigned_to=NULL WHERE assigned_to=?", (username,))
        c.execute("DELETE FROM users WHERE username=?", (username,))
