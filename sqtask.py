import json
import os
import sqlite3
import ssl
import urllib.request
from datetime import datetime

from textual import on, work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.reactive import reactive
from textual.screen import ModalScreen, Screen
from textual.widgets import DataTable, Footer, Static, Input, Select, Button, Label, TextArea

DB_FILE = "tasks.db"


# ---------------------------------------------------------------------------
# DATABASE LAYER
# ---------------------------------------------------------------------------

def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")   # safer concurrent writes
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    """Create tables if they don't exist yet."""
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS projects (
                name        TEXT PRIMARY KEY,
                color       TEXT NOT NULL DEFAULT '#00FFFF'
            );

            CREATE TABLE IF NOT EXISTS tasks (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                project     TEXT NOT NULL REFERENCES projects(name) ON UPDATE CASCADE ON DELETE CASCADE,
                task        TEXT NOT NULL,
                priority    TEXT NOT NULL DEFAULT '2. MEDIUM',
                status      TEXT NOT NULL DEFAULT 'TO DO',
                notes       TEXT,
                sort_order  INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS sub_tasks (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id     INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                task        TEXT NOT NULL,
                status      TEXT NOT NULL DEFAULT 'TO DO',
                notes       TEXT,
                sort_order  INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS view_settings (
                key         TEXT PRIMARY KEY,
                value       TEXT
            );
                           
            CREATE TABLE IF NOT EXISTS project_logs (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                project     TEXT NOT NULL REFERENCES projects(name) ON UPDATE CASCADE ON DELETE CASCADE,
                log_date    TEXT NOT NULL,
                title       TEXT NOT NULL DEFAULT 'Milestone',
                notes       TEXT NOT NULL
            );
        """)
        # Seed default view settings if missing
        defaults = {
            "sort_by": "priority",
            "filter_project": "",
            "filter_priority": "",
            "theme": "textual-dark",
            "hide_done": "0",
            "border_color": "#00FF00",
        }
        for k, v in defaults.items():
            conn.execute(
                "INSERT OR IGNORE INTO view_settings (key, value) VALUES (?, ?)", (k, v)
            )


def upgrade_project_logs_table() -> None:
    """Run this once on startup to ensure the title column exists for older DB versions."""
    with get_conn() as conn:
        try:
            conn.execute("ALTER TABLE project_logs ADD COLUMN title TEXT NOT NULL DEFAULT 'Milestone'")
        except sqlite3.OperationalError:
            pass # Column already exists


# --- Migration helper ---------------------------------------------------

def migrate_from_json(json_path: str = "tasks.json") -> None:
    """One-time import of an existing tasks.json into the SQLite DB."""
    if not os.path.exists(json_path):
        return

    with open(json_path) as f:
        data = json.load(f)

    with get_conn() as conn:
        # Check if DB is already populated
        row = conn.execute("SELECT COUNT(*) FROM projects").fetchone()
        if row[0] > 0:
            return   # already migrated

        colors = data.get("project_colors", {})
        for proj_name, tasks in data.get("projects", {}).items():
            color = colors.get(proj_name, "#00FFFF")
            conn.execute(
                "INSERT OR IGNORE INTO projects (name, color) VALUES (?, ?)",
                (proj_name, color),
            )
            for order, t in enumerate(tasks):
                cur = conn.execute(
                    """INSERT INTO tasks (project, task, priority, status, notes, sort_order)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        proj_name,
                        t.get("task", ""),
                        t.get("priority", "2. MEDIUM"),
                        t.get("status", "TO DO"),
                        t.get("notes") or None,
                        order,
                    ),
                )
                task_id = cur.lastrowid
                for sub_order, s in enumerate(t.get("sub_tasks", [])):
                    conn.execute(
                        """INSERT INTO sub_tasks (task_id, task, status, notes, sort_order)
                           VALUES (?, ?, ?, ?, ?)""",
                        (
                            task_id,
                            s.get("task", ""),
                            s.get("status", "TO DO"),
                            s.get("notes") or None,
                            sub_order,
                        ),
                    )

        vs = data.get("view_settings", {})
        mapping = {
            "sort_by": vs.get("sort_by", "priority"),
            "filter_project": vs.get("filter_project") or "",
            "filter_priority": vs.get("filter_priority") or "",
            "theme": vs.get("theme", "textual-dark"),
            "hide_done": "1" if vs.get("hide_done") else "0",
        }
        for k, v in mapping.items():
            conn.execute(
                "INSERT OR REPLACE INTO view_settings (key, value) VALUES (?, ?)", (k, v)
            )

    # Rename the old file so migration won't re-run
    os.rename(json_path, json_path + ".bak")
    print(f"[migration] tasks.json imported → {DB_FILE}  (backup: tasks.json.bak)")


# --- High-level DB helpers ----------------------------------------------

def db_load_data() -> dict:
    """Return the same dict shape the rest of the app expects."""
    with get_conn() as conn:
        # Projects + their color
        proj_rows = conn.execute("SELECT name, color FROM projects ORDER BY name").fetchall()
        project_colors = {r["name"]: r["color"] for r in proj_rows}

        # Tasks (with sub-tasks) per project
        projects: dict[str, list] = {r["name"]: [] for r in proj_rows}

        task_rows = conn.execute(
            "SELECT * FROM tasks ORDER BY project, sort_order, id"
        ).fetchall()

        task_ids = [r["id"] for r in task_rows]
        sub_map: dict[int, list] = {tid: [] for tid in task_ids}

        if task_ids:
            placeholders = ",".join("?" * len(task_ids))
            sub_rows = conn.execute(
                f"SELECT * FROM sub_tasks WHERE task_id IN ({placeholders}) "
                f"ORDER BY sort_order, id",
                task_ids,
            ).fetchall()
            for s in sub_rows:
                sub_map[s["task_id"]].append({
                    "task": s["task"],
                    "status": s["status"],
                    "notes": s["notes"],
                    "_id": s["id"],
                })

        for t in task_rows:
            projects[t["project"]].append({
                "task": t["task"],
                "priority": t["priority"],
                "status": t["status"],
                "notes": t["notes"],
                "sub_tasks": sub_map[t["id"]],
                "_id": t["id"],
            })

        # View settings
        vs_rows = conn.execute("SELECT key, value FROM view_settings").fetchall()
        vs = {r["key"]: r["value"] for r in vs_rows}

        view_settings = {
            "sort_by": vs.get("sort_by", "priority"),
            "filter_project": vs.get("filter_project") or None,
            "filter_priority": vs.get("filter_priority") or None,
            "theme": vs.get("theme", "textual-dark"),
            "hide_done": vs.get("hide_done", "0") == "1",
            "border_color": vs.get("border_color", "#00FF00"),
        }

    return {
        "projects": projects,
        "project_colors": project_colors,
        "view_settings": view_settings,
    }


def db_save_view_settings(vs: dict) -> None:
    mapping = {
        "sort_by": vs.get("sort_by", "priority"),
        "filter_project": vs.get("filter_project") or "",
        "filter_priority": vs.get("filter_priority") or "",
        "theme": vs.get("theme", "textual-dark"),
        "hide_done": "1" if vs.get("hide_done") else "0",
        "border_color": vs.get("border_color", "#00FF00"),
    }
    with get_conn() as conn:
        for k, v in mapping.items():
            conn.execute(
                "INSERT OR REPLACE INTO view_settings (key, value) VALUES (?, ?)", (k, v)
            )


def db_add_project(name: str, color: str) -> bool:
    try:
        with get_conn() as conn:
            conn.execute("INSERT INTO projects (name, color) VALUES (?, ?)", (name, color))
        return True
    except sqlite3.IntegrityError:
        return False


def db_edit_project(old_name: str, new_name: str | None, new_color: str | None) -> bool:
    try:
        with get_conn() as conn:
            if new_color:
                conn.execute("UPDATE projects SET color=? WHERE name=?", (new_color, old_name))
            if new_name and new_name != old_name:
                # Rename: tasks.project FK will cascade via ON UPDATE CASCADE
                conn.execute(
                    "UPDATE projects SET name=? WHERE name=?", (new_name, old_name)
                )
        return True
    except sqlite3.IntegrityError:
        return False


def db_delete_project(name: str) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM projects WHERE name=?", (name,))


def db_add_task(project: str, task: str, priority: str, status: str, notes: str | None) -> int:
    with get_conn() as conn:
        max_order = conn.execute(
            "SELECT COALESCE(MAX(sort_order),0) FROM tasks WHERE project=?", (project,)
        ).fetchone()[0]
        cur = conn.execute(
            "INSERT INTO tasks (project, task, priority, status, notes, sort_order) VALUES (?,?,?,?,?,?)",
            (project, task, priority, status, notes, max_order + 1),
        )
        return cur.lastrowid or 0


def db_update_task(task_id: int, task: str, priority: str, status: str, notes: str | None) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE tasks SET task=?, priority=?, status=?, notes=? WHERE id=?",
            (task, priority, status, notes, task_id),
        )


def db_delete_task(task_id: int) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM tasks WHERE id=?", (task_id,))


def db_add_subtask(task_id: int, task: str, status: str, notes: str | None) -> int:
    with get_conn() as conn:
        max_order = conn.execute(
            "SELECT COALESCE(MAX(sort_order),0) FROM sub_tasks WHERE task_id=?", (task_id,)
        ).fetchone()[0]
        cur = conn.execute(
            "INSERT INTO sub_tasks (task_id, task, status, notes, sort_order) VALUES (?,?,?,?,?)",
            (task_id, task, status, notes, max_order + 1),
        )
        return cur.lastrowid or 0


def db_update_subtask(sub_id: int, task: str, status: str, notes: str | None) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE sub_tasks SET task=?, status=?, notes=? WHERE id=?",
            (task, status, notes, sub_id),
        )


def db_delete_subtask(sub_id: int) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM sub_tasks WHERE id=?", (sub_id,))


def db_get_project_logs(project: str) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, log_date, title, notes FROM project_logs WHERE project=? ORDER BY log_date DESC, id DESC", 
            (project,)
        ).fetchall()
        return [{"id": r["id"], "log_date": r["log_date"], "title": r["title"], "notes": r["notes"]} for r in rows]


def db_add_project_log(project: str, log_date: str, title: str, notes: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO project_logs (project, log_date, title, notes) VALUES (?, ?, ?, ?)",
            (project, log_date, title, notes)
        )


def db_update_project_log(log_id: int, log_date: str, title: str, notes: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE project_logs SET log_date=?, title=?, notes=? WHERE id=?",
            (log_date, title, notes, log_id)
        )

def db_delete_project_log(log_id: int) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM project_logs WHERE id=?", (log_id,))

def db_get_log_by_id(log_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id, log_date, title, notes FROM project_logs WHERE id=?",
            (log_id,)
        ).fetchone()
        if row:
            return {"id": row["id"], "log_date": row["log_date"], "title": row["title"], "notes": row["notes"]}
        return None

# ---------------------------------------------------------------------------
# UI COMPONENTS  (unchanged from original)
# ---------------------------------------------------------------------------

class SystemStatus(Static):
    date_str = reactive("")
    time_str = reactive("")
    weather_str = reactive("--")

    def on_mount(self) -> None:
        self.update_time()
        self.set_interval(1, self.update_time)
        self.fetch_weather()
        self.set_interval(300, self.fetch_weather)

    def update_time(self) -> None:
        now = datetime.now()
        self.date_str = now.strftime("%Y-%m-%d")
        self.time_str = now.strftime("%H:%M:%S")
        self.render_status()

    @work(thread=True)
    def fetch_weather(self) -> None:
        try:
            url = "https://api.open-meteo.com/v1/forecast?latitude=-33.3667&longitude=-70.7333&current_weather=true"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            with urllib.request.urlopen(req, timeout=5, context=ctx) as response:
                api_data = json.loads(response.read().decode())
                self.weather_str = str(api_data["current_weather"]["temperature"])
        except Exception:
            pass
        self.app.call_from_thread(self.render_status)

    def render_status(self) -> None:
        color = getattr(self.app, "app_border", "#00ff00")
        content = (
            f"[{color}]DATE:[/] {self.date_str}  |  "
            f"[{color}]TIME:[/] {self.time_str}  |  "
            f"[{color}]TEMP:[/] {self.weather_str}°C"
        )
        self.update(content)


# --- MODAL SCREENS ------------------------------------------

class ConfirmScreen(ModalScreen[bool]):
    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, message: str):
        super().__init__()
        self.message = message

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label(f"[bold red]WARNING:[/bold red] {self.message}", id="dialog-title")
            with Horizontal(id="dialog-buttons"):
                yield Button("YES, PURGE", variant="error", id="btn-yes")
                yield Button("CANCEL", variant="success", id="btn-no")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "btn-yes")

    def on_mount(self) -> None:
        color = getattr(self.app, "app_border", "#00ff00")
        try:
            self.query_one("#dialog").styles.border = ("heavy", color)
        except Exception:
            pass

class TaskFormScreen(ModalScreen[dict]):
    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(
        self,
        projects: list,
        edit_proj: str | None = None,
        edit_task_id: int | None = None,
        edit_sub_id: int | None = None,
        task_data: dict | None = None,
        is_subtask: bool = False,
        parent_proj: str | None = None,
        parent_task_id: int | None = None,
    ) -> None:
        super().__init__()
        self.projects = projects
        self.edit_proj = edit_proj
        self.edit_task_id = edit_task_id
        self.edit_sub_id = edit_sub_id
        self.task_data = task_data or {}
        self.is_subtask = is_subtask
        self.parent_proj = parent_proj
        self.parent_task_id = parent_task_id

    def compose(self) -> ComposeResult:
        proj_options = [(p, p) for p in self.projects]
        prio_options = [
            ("1. HIGH", "1. HIGH"),
            ("2. MEDIUM", "2. MEDIUM"),
            ("3. LOW", "3. LOW"),
            ("4. ----", "4. ----"),
        ]
        stat_options = [
            ("TO DO", "TO DO"),
            ("IN PROGRESS", "IN PROGRESS"),
            ("ON HOLD", "ON HOLD"),
            ("DONE", "DONE"),
        ]

        if self.is_subtask:
            title = (
                "[bold yellow]EDITING SUB-TASK[/]"
                if self.edit_sub_id is not None
                else "[bold cyan]INITIALIZING SUB-TASK...[/]"
            )
        else:
            title = (
                "[bold yellow]EDITING TASK OVERRIDE[/]"
                if self.edit_task_id is not None
                else "[bold green]INITIALIZING NEW TASK SEQUENCE...[/]"
            )

        with Vertical(id="dialog"):
            yield Label(title, id="dialog-title")

            yield Label("Project Designation:")
            sel_proj = Select(proj_options, id="select-project", prompt="Select Project...")
            if self.edit_proj is not None or self.is_subtask:
                sel_proj.value = self.edit_proj or self.parent_proj  # type: ignore
                sel_proj.disabled = True
            yield sel_proj

            yield Label("Task Description:")
            yield Input(
                value=self.task_data.get("task", ""),
                placeholder="Enter task...",
                id="input-desc",
            )

            yield Label("Priority:")
            sel_prio = Select(
                prio_options,
                id="select-priority",
                value=self.task_data.get("priority", "2. MEDIUM"),
            )
            if self.is_subtask:
                sel_prio.disabled = True
            yield sel_prio

            yield Label("Status:")
            yield Select(
                stat_options,
                id="select-status",
                value=self.task_data.get("status", "TO DO"),
            )

            yield Label("Notes (Optional):")
            yield Input(
                value=self.task_data.get("notes", "") or "",
                placeholder="Enter notes...",
                id="input-notes",
            )

            with Horizontal(id="dialog-buttons"):
                yield Button("SAVE DATA", variant="success", id="btn-submit")
                yield Button("CANCEL", variant="error", id="btn-cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-submit":
            project = self.query_one("#select-project", Select).value
            desc = self.query_one("#input-desc", Input).value
            priority = self.query_one("#select-priority", Select).value
            status = self.query_one("#select-status", Select).value
            notes = self.query_one("#input-notes", Input).value

            if project == Select.BLANK or not desc.strip():
                self.app.notify("Project and Description are required.", severity="error")
                return

            if status == "DONE":
                priority = "4. ----"

            self.dismiss(
                {
                    "project": project,
                    "task": desc.strip(),
                    "priority": priority,
                    "status": status,
                    "notes": notes.strip() if notes.strip() else None,
                    "edit_task_id": self.edit_task_id,
                    "edit_sub_id": self.edit_sub_id,
                    "parent_task_id": self.parent_task_id,
                    "is_subtask": self.is_subtask,
                }
            )
        elif event.button.id == "btn-cancel":
            self.dismiss(None)

    def on_mount(self) -> None:
        color = getattr(self.app, "app_border", "#00ff00")
        try:
            self.query_one("#dialog").styles.border = ("heavy", color)
        except Exception:
            pass

class ViewFilterScreen(ModalScreen[dict]):
    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, projects: list, current_settings: dict):
        super().__init__()
        self.projects = projects
        self.settings = current_settings

    def compose(self) -> ComposeResult:
        sort_opts = [("PROJECT", "project"), ("PRIORITY", "priority")]
        proj_opts = [("NONE", "NONE")] + [(p, p) for p in self.projects]
        prio_opts = [
            ("NONE", "NONE"),
            ("1. HIGH", "1. HIGH"),
            ("2. MEDIUM", "2. MEDIUM"),
            ("3. LOW", "3. LOW"),
            ("4. ----", "4. ----"),
        ]

        with Vertical(id="dialog"):
            yield Label("[bold cyan]VIEW & FILTER CONFIGURATION[/bold cyan]", id="dialog-title")
            yield Label("Sort By:")
            yield Select(sort_opts, id="sort-by", value=self.settings.get("sort_by", "priority"))
            yield Label("Project Filter:")
            yield Select(
                proj_opts,
                id="filter-proj",
                value=self.settings.get("filter_project") or "NONE",
            )
            yield Label("Priority Filter:")
            yield Select(
                prio_opts,
                id="filter-prio",
                value=self.settings.get("filter_priority") or "NONE",
            )
            with Horizontal(id="dialog-buttons"):
                yield Button("APPLY", variant="success", id="btn-apply")
                yield Button("CLEAR FILTERS", variant="warning", id="btn-clear")
                yield Button("CANCEL", variant="error", id="btn-cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-apply":
            sb = self.query_one("#sort-by", Select).value
            fp = self.query_one("#filter-proj", Select).value
            fpr = self.query_one("#filter-prio", Select).value
            self.dismiss(
                {
                    "sort_by": "priority" if sb == Select.BLANK else sb,
                    "filter_project": None if fp in ("NONE", Select.BLANK) else fp,
                    "filter_priority": None if fpr in ("NONE", Select.BLANK) else fpr,
                }
            )
        elif event.button.id == "btn-clear":
            self.dismiss(
                {
                    "sort_by": self.settings.get("sort_by", "priority"),
                    "filter_project": None,
                    "filter_priority": None,
                }
            )
        elif event.button.id == "btn-cancel":
            self.dismiss(None)

    def on_mount(self) -> None:
        color = getattr(self.app, "app_border", "#00ff00")
        try:
            self.query_one("#dialog").styles.border = ("heavy", color)
        except Exception:
            pass

class ProjectManagerScreen(ModalScreen[dict]):
    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, projects: list):
        super().__init__()
        self.projects = projects

    def compose(self) -> ComposeResult:
        color_palette = {
            "CYAN": "#00FFFF",
            "MAGENTA": "#FF00FF",
            "GREEN": "#00FF00",
            "YELLOW": "#FFFF00",
            "RED": "#FF4444",
            "BLUE": "#3399FF",
            "WHITE": "#FFFFFF",
            "ORANGE": "#FFA500",
            "VIOLET": "#EE82EE",
        }
        color_opts = [
            (f"[{hex_code} bold]{name}[/]", hex_code)
            for name, hex_code in color_palette.items()
        ]
        proj_opts = [(p, p) for p in self.projects]

        with VerticalScroll(id="dialog"):
            yield Label("[bold magenta]PROJECT MANAGEMENT OVERRIDE[/bold magenta]", id="dialog-title")

            yield Label("[bold white]--- ADD NEW PROJECT ---[/]")
            yield Input(placeholder="New Project Designation...", id="new-proj-name")
            yield Select(color_opts, id="new-proj-color", prompt="Select Color...")
            yield Button("CREATE PROJECT", variant="success", id="btn-add")

            yield Label("\n[bold white]--- EDIT EXISTING PROJECT ---[/]")
            yield Select(proj_opts, id="edit-proj-name", prompt="Select Project...")
            yield Input(placeholder="New Designation (leave blank to keep)", id="edit-proj-new-name")
            yield Select(color_opts, id="edit-proj-color", prompt="Select New Color...")
            yield Button("UPDATE PROJECT", variant="primary", id="btn-edit")

            yield Label("\n[bold white]--- PURGE EXISTING PROJECT ---[/]")
            yield Select(proj_opts, id="del-proj-name", prompt="Select Project to Purge...")
            yield Button("PURGE PROJECT", variant="error", id="btn-del")

            with Horizontal(id="dialog-buttons"):
                yield Button("CLOSE MENU", id="btn-cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-add":
            name = self.query_one("#new-proj-name", Input).value.strip().upper()
            color = self.query_one("#new-proj-color", Select).value
            if not name or color == Select.BLANK:
                self.app.notify("Designation and Color required.", severity="error")
                return
            self.dismiss({"action": "add", "name": name, "color": color})

        elif event.button.id == "btn-edit":
            target = self.query_one("#edit-proj-name", Select).value
            new_name = self.query_one("#edit-proj-new-name", Input).value.strip().upper()
            new_color = self.query_one("#edit-proj-color", Select).value
            if target == Select.BLANK:
                self.app.notify("No project selected to edit.", severity="warning")
                return
            self.dismiss(
                {
                    "action": "edit",
                    "name": target,
                    "new_name": new_name,
                    "new_color": new_color,
                }
            )

        elif event.button.id == "btn-del":
            target = self.query_one("#del-proj-name", Select).value
            if target == Select.BLANK:
                self.app.notify("No project selected to purge.", severity="warning")
                return
            self.dismiss({"action": "delete", "name": target})

        elif event.button.id == "btn-cancel":
            self.dismiss(None)

    def on_mount(self) -> None:
        color = getattr(self.app, "app_border", "#00ff00")
        try:
            self.query_one("#dialog").styles.border = ("heavy", color)
        except Exception:
            pass

class PreferencesScreen(ModalScreen[str]):
    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, current_color: str):
        super().__init__()
        self.current_color = current_color

    def compose(self) -> ComposeResult:
        color_palette = {
            "GREEN (Default)": "#00FF00",
            "CYAN": "#00FFFF",
            "MAGENTA": "#FF00FF",
            "YELLOW": "#FFFF00",
            "RED": "#FF4444",
            "BLUE": "#3399FF",
            "WHITE": "#FFFFFF",
            "ORANGE": "#FFA500",
            "VIOLET": "#EE82EE",
        }
        
        color_opts = [
            (f"[{hex_code} bold]{name}[/]", hex_code)
            for name, hex_code in color_palette.items()
        ]

        with Vertical(id="dialog"):
            yield Label("[bold cyan]APP PREFERENCES[/bold cyan]", id="dialog-title")
            yield Label("Border Color:")
            yield Select(
                color_opts,
                id="select-border-color",
                value=self.current_color,
                prompt="Select border color...",
            )
            with Horizontal(id="dialog-buttons"):
                yield Button("APPLY", variant="success", id="btn-apply")
                yield Button("CANCEL", variant="error", id="btn-cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-apply":
            color = self.query_one("#select-border-color", Select).value
            if color == Select.BLANK:
                self.dismiss(None)
            else:
                self.dismiss(str(color)) 
        elif event.button.id == "btn-cancel":
            self.dismiss(None)

    def on_mount(self) -> None:
        color = getattr(self.app, "app_border", "#00ff00")
        try:
            self.query_one("#dialog").styles.border = ("heavy", color)
        except Exception:
            pass

class LogDetailScreen(ModalScreen[None]):
    BINDINGS = [
        ("escape", "close", "Close"), 
        ("enter", "close", "Close")
    ]

    def __init__(self, log_data: dict):
        super().__init__()
        self.log_data = log_data

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label(f"[bold cyan]{self.log_data['log_date']} - {self.log_data['title']}[/]", id="dialog-title")
            
            notes_area = TextArea(text=self.log_data.get("notes", ""), read_only=True)
            notes_area.styles.height = 25
            yield notes_area
            
            with Horizontal(id="dialog-buttons"):
                yield Button("CLOSE", variant="primary", id="btn-close")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-close":
            self.dismiss(None)
            
    def action_close(self) -> None:
        self.dismiss(None)

    def on_mount(self) -> None:
        color = getattr(self.app, "app_border", "#00ff00")
        try:
            self.query_one("#dialog").styles.border = ("heavy", color)
        except Exception:
            pass
# ---------------------------------------------------------------------------
# LOG SCREENS 
# ---------------------------------------------------------------------------

class LogProjectSelectScreen(ModalScreen[str]):
    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, projects: list):
        super().__init__()
        self.projects = projects

    def compose(self) -> ComposeResult:
        proj_opts = [(p, p) for p in self.projects]
        with Vertical(id="dialog"):
            yield Label("[bold cyan]SELECT PROJECT FOR LOG[/bold cyan]", id="dialog-title")
            yield Select(proj_opts, id="select-log-proj", prompt="Select Project...")
            
            with Horizontal(id="dialog-buttons"):
                yield Button("OPEN LOG", variant="success", id="btn-open")
                yield Button("CANCEL", variant="error", id="btn-cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-open":
            selection = self.query_one("#select-log-proj", Select).value
            if selection == Select.BLANK:
                self.app.notify("Please select a project.", severity="error")
                return
            self.dismiss(str(selection))
        elif event.button.id == "btn-cancel":
            self.dismiss(None)

    def on_mount(self) -> None:
        color = getattr(self.app, "app_border", "#00ff00")
        try:
            self.query_one("#dialog").styles.border = ("heavy", color)
        except Exception:
            pass

class LogFormScreen(ModalScreen[dict]):
    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, log_data: dict | None = None):
        super().__init__()
        self.log_data = log_data or {}
        self.is_edit = bool(self.log_data)

    def compose(self) -> ComposeResult:
        default_date = self.log_data.get("log_date", datetime.now().strftime("%Y-%m-%d"))
        title_val = self.log_data.get("title", "")
        notes_val = self.log_data.get("notes", "")
        
        form_title = "[bold yellow]EDIT MILESTONE LOG[/]" if self.is_edit else "[bold cyan]ADD MILESTONE LOG[/]"

        with Vertical(id="dialog"):
            yield Label(form_title, id="dialog-title")
            
            yield Label("Date:")
            yield Input(value=default_date, id="input-date")
            
            yield Label("Title:")
            yield Input(value=title_val, placeholder="e.g., Meeting with client...", id="input-title")
            
            yield Label("Notes:")
            notes_area = TextArea(text=notes_val, id="input-notes")
            notes_area.styles.height = 15 
            yield notes_area
            
            with Horizontal(id="dialog-buttons"):
                yield Button("SAVE", variant="success", id="btn-save")
                if self.is_edit:
                    yield Button("DELETE", variant="error", id="btn-delete")
                yield Button("CANCEL", variant="primary", id="btn-cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-save":
            date_val = self.query_one("#input-date", Input).value.strip()
            title_val = self.query_one("#input-title", Input).value.strip()
            notes_val = self.query_one("#input-notes", TextArea).text.strip()
            
            if not date_val or not title_val or not notes_val:
                self.app.notify("Date, Title, and Notes are required.", severity="error")
                return
            
            self.dismiss({
                "action": "save",
                "id": self.log_data.get("id"),
                "date": date_val, 
                "title": title_val, 
                "notes": notes_val
            })
            
        elif event.button.id == "btn-delete":
            self.dismiss({
                "action": "delete",
                "id": self.log_data.get("id")
            })
            
        elif event.button.id == "btn-cancel":
            self.dismiss(None)

    def on_mount(self) -> None:
        color = getattr(self.app, "app_border", "#00ff00")
        try:
            self.query_one("#dialog").styles.border = ("heavy", color)
        except Exception:
            pass

class ProjectLogScreen(Screen):
    BINDINGS = [
        ("escape", "app.pop_screen", "Back to Tasks"),
        ("a", "add_log", "Add Log Entry"),
        ("r", "edit_log", "Edit Entry"),
    ]

    def __init__(self, project_name: str):
        super().__init__()
        self.project_name = project_name
        self.expanded_logs: set[str] = set()

    def compose(self) -> ComposeResult:
        with Horizontal(id="top-bar"):
            status = SystemStatus()
            status.border_title = f" {self.project_name} LOG "
            yield status
        yield DataTable(id="log-table", cursor_type="row")
        yield Footer()

    def on_mount(self) -> None:
        color = getattr(self.app, "app_border", "#00FF00")
        
        status = self.query_one(SystemStatus)
        status.styles.border = ("round", color)
        status.styles.border_title_color = color
        
        dt = self.query_one(DataTable)
        dt.styles.border = ("round", color)
        
        self.populate_table()

    def populate_table(self) -> None:
        table = self.query_one(DataTable)
        
        cursor_key = None
        if table.row_count > 0:
            try:
                cursor_key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value
            except Exception:
                pass

        table.clear(columns=False)
        if not table.columns:
            table.add_columns("DATE", "TITLE")
        
        logs = db_get_project_logs(self.project_name)
        
        for log in logs:
            row_key = f"log::{log['id']}"
            indicator = "[bold cyan]▼[/] " if row_key in self.expanded_logs else "[bold white]▶[/] "
            
            table.add_row(
                f"{indicator}[bold cyan]{log['log_date']}[/]",
                f"[bold white]{log['title']}[/]",
                key=row_key
            )
            
            if row_key in self.expanded_logs:
                note_key = f"note::{log['id']}"
                table.add_row(
                    "", 
                    f"[gray]↳[/] {log['notes']}", 
                    key=note_key
                )

        if cursor_key:
            try:
                row_idx = table.get_row_index(cursor_key)
                table.move_cursor(row=row_idx)
            except Exception:
                pass

    @on(DataTable.RowSelected)
    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        row_key_str = str(event.row_key.value)
        
        # Parse the ID whether they pressed Enter on the primary row or the expanded note row
        log_id_str = row_key_str.split("::")[1] if "::" in row_key_str else None
        
        if not log_id_str:
            return
            
        log_id = int(log_id_str)
        log_data = db_get_log_by_id(log_id)
        
        if log_data:
            self.app.push_screen(LogDetailScreen(log_data))

    def action_add_log(self) -> None:
        self.app.push_screen(LogFormScreen(), self.handle_log_form)

    def action_edit_log(self) -> None:
        table = self.query_one(DataTable)
        if not table.row_count:
            self.app.notify("No logs to edit.", severity="warning")
            return
        
        try:
            row_key_value = table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value
        except Exception:
            return

        key = str(row_key_value)
        # Parse the ID whether they have selected the primary row or the expanded notes row
        log_id_str = key.split("::")[1] if "::" in key else None
        
        if not log_id_str:
            return
            
        log_id = int(log_id_str)
        log_data = db_get_log_by_id(log_id)
        if log_data:
            self.app.push_screen(LogFormScreen(log_data), self.handle_log_form)

    def handle_log_form(self, result: dict | None) -> None:
        if not result:
            return
        
        action = result.get("action")
        log_id = result.get("id")
        
        if action == "save":
            if log_id:
                db_update_project_log(log_id, result["date"], result["title"], result["notes"])
                self.app.notify("Log entry updated.", severity="information")
            else:
                db_add_project_log(self.project_name, result["date"], result["title"], result["notes"])
                self.app.notify("Log entry added.", severity="information")
                
        elif action == "delete":
            if log_id:
                db_delete_project_log(log_id)
                self.expanded_logs.discard(f"log::{log_id}")
                self.app.notify("Log entry deleted.", severity="warning")
        
        self.populate_table()

# ---------------------------------------------------------------------------
# MAIN APP
# ---------------------------------------------------------------------------

class TaskManagerApp(App):
    CSS = """
    Screen { background: $surface; }
    #top-bar { height: 3; margin-bottom: 0; }
    SystemStatus { width: 100%; height: 100%; border: round #00ff00; border-title-color: #00ff00; content-align: center middle; }
    DataTable { border: round #00ff00; height: 1fr; }

    ConfirmScreen, TaskFormScreen, ViewFilterScreen, ProjectManagerScreen, PreferencesScreen, LogProjectSelectScreen, LogFormScreen, LogDetailScreen {
        align: center middle;
        background: $background 50%;
    }
    
    LogFormScreen #dialog, LogDetailScreen #dialog {
        width: 150;
    }
    #dialog {
        width: 60;
        height: auto;
        max-height: 90vh;
        padding: 1 2;
        background: $surface;
        border: heavy #00ff00;
    }
    #dialog-title { content-align: center middle; width: 100%; margin-bottom: 1; }
    #dialog-buttons { margin-top: 1; align: center middle; height: auto; }
    #dialog-buttons Button { margin: 0 1; }
    """

    BINDINGS = [
        ("1", "manage_projects", "Projects"),
        ("2", "add_task", "Add Task"),
        ("s", "add_subtask", "Add Sub-task"),
        ("e", "edit_task", "Edit Task"),
        ("d", "delete_task", "Delete Task"),
        ("v", "view_filter", "View/Filter"),
        ("h", "toggle_hide_done", "Hide Done"),
        ("p", "open_preferences", "Preferences"),
        ("l", "open_project_log", "Project Log"),
        ("q", "app.quit", "Quit"),
    ]

    # Reactive variable for dynamic styling
    app_border = reactive("#00FF00")

    def watch_app_border(self, new_color: str) -> None:
        """Fires automatically whenever app_border changes."""
        # Update all active widgets that require the border color globally
        for status in self.query(SystemStatus):
            status.styles.border = ("round", new_color)
            status.styles.border_title_color = new_color
            
        for dt in self.query(DataTable):
            dt.styles.border = ("round", new_color)

        for dialog in self.query("#dialog"):
            dialog.styles.border = ("heavy", new_color)

        # Save to database
        if hasattr(self, "data") and "view_settings" in self.data:
            self.data["view_settings"]["border_color"] = new_color
            db_save_view_settings(self.data["view_settings"])


    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def on_mount(self) -> None:
        self.title = "TASKS_MANAGER"
        self.data = db_load_data()
        self.expanded_rows: set[str] = set()
        self.hide_done: bool = self.data["view_settings"].get("hide_done", False)

        if "theme" in self.data.get("view_settings", {}):
            self.theme = self.data["view_settings"]["theme"]
            
        # Load custom border color
        if "border_color" in self.data.get("view_settings", {}):
            self.app_border = self.data["view_settings"]["border_color"]

        self.populate_table()

    def watch_theme(self, new_theme: str) -> None:
        if hasattr(self, "data") and "view_settings" in self.data:
            self.data["view_settings"]["theme"] = new_theme
            db_save_view_settings(self.data["view_settings"])

    def compose(self) -> ComposeResult:
        with Horizontal(id="top-bar"):
            status = SystemStatus()
            status.border_title = " TASKS MANAGER "
            yield status
        yield DataTable(id="task-table", cursor_type="row")
        yield Footer()

    # ------------------------------------------------------------------
    # Table rendering
    # ------------------------------------------------------------------

    def populate_table(self) -> None:
        self.data = db_load_data()
        # Re-apply in-memory settings that may not be persisted yet
        self.data["view_settings"]["hide_done"] = self.hide_done

        table = self.query_one(DataTable)

        cursor_key = None
        if table.row_count > 0:
            try:
                cursor_key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value
            except Exception:
                pass

        table.clear(columns=False)
        if not table.columns:
            table.add_columns("PROJECT", "PRIORITY", "TASK", "STATUS", "NOTES")

        view = self.data["view_settings"]
        all_tasks = []

        for project, tasks in self.data.get("projects", {}).items():
            for t in tasks:
                all_tasks.append((project, t))

        if view.get("filter_project"):
            all_tasks = [x for x in all_tasks if x[0] == view["filter_project"]]
        if view.get("filter_priority"):
            all_tasks = [x for x in all_tasks if x[1]["priority"] == view["filter_priority"]]
        if self.hide_done:
            all_tasks = [x for x in all_tasks if x[1].get("status") != "DONE"]

        if view.get("sort_by", "priority") == "project":
            all_tasks.sort(key=lambda x: x[0])
        else:
            all_tasks.sort(key=lambda x: (x[1]["priority"], x[0]))

        for proj, t in all_tasks:
            p_col = self.data["project_colors"].get(proj, "cyan")
            proj_str = f"[{p_col} bold]{proj}[/]"

            prio = t["priority"]
            if "HIGH" in prio:
                prio_str = f"[bold red]{prio}[/]"
            elif "MEDIUM" in prio:
                prio_str = f"[bold yellow]{prio}[/]"
            elif "LOW" in prio:
                prio_str = f"[cyan]{prio}[/]"
            else:
                prio_str = f"[white]{prio}[/]"

            stat = t["status"]
            if "DONE" in stat:
                stat_str = f"[bold green]{stat}[/]"
            elif "IN PROGRESS" in stat:
                stat_str = f"[bold cyan]{stat}[/]"
            elif "ON HOLD" in stat:
                stat_str = f"[bold red]{stat}[/]"
            else:
                stat_str = f"[white]{stat}[/]"

            task_db_id = t["_id"]
            row_key = f"task::{task_db_id}"
            sub_tasks = t.get("sub_tasks", [])

            visible_subs = (
                [s for s in sub_tasks if s.get("status") != "DONE"]
                if self.hide_done
                else sub_tasks
            )

            if visible_subs:
                indicator = (
                    "[bold cyan]▼[/] "
                    if row_key in self.expanded_rows
                    else "[bold white]▶[/] "
                )
            else:
                indicator = "  "

            table.add_row(
                proj_str, prio_str, f"{indicator}{t['task']}", stat_str,
                t.get("notes", "") or "", key=row_key,
            )

            if row_key in self.expanded_rows:
                for sub in sub_tasks:
                    if self.hide_done and sub.get("status") == "DONE":
                        continue
                    sub_db_id = sub["_id"]
                    sub_key = f"sub::{sub_db_id}"
                    sub_stat = sub.get("status", "TO DO")

                    if "DONE" in sub_stat:
                        sub_stat_str = f"[bold green]{sub_stat}[/]"
                    elif "IN PROGRESS" in sub_stat:
                        sub_stat_str = f"[bold cyan]{sub_stat}[/]"
                    elif "ON HOLD" in sub_stat:
                        sub_stat_str = f"[bold red]{sub_stat}[/]"
                    else:
                        sub_stat_str = f"[white]{sub_stat}[/]"

                    table.add_row(
                        "", "", f"    [gray]↳[/] {sub['task']}",
                        sub_stat_str, sub.get("notes", "") or "", key=sub_key,
                    )

        if cursor_key:
            try:
                row_idx = table.get_row_index(cursor_key)
                table.move_cursor(row=row_idx)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Row selection (expand/collapse)
    # ------------------------------------------------------------------

    @on(DataTable.RowSelected)
    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        row_key = str(event.row_key.value)
        if row_key.startswith("sub::"):
            return
        if row_key in self.expanded_rows:
            self.expanded_rows.remove(row_key)
        else:
            self.expanded_rows.add(row_key)
        self.populate_table()

    # ------------------------------------------------------------------
    # Helper: parse selected row → (task_db_id, sub_db_id | None)
    # ------------------------------------------------------------------

    def get_selected_task(self) -> tuple[int, int | None] | None:
        table = self.query_one(DataTable)
        if not table.row_count:
            return None
        row_key_value = table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value
        if not row_key_value:
            return None
        key = str(row_key_value)
        if key.startswith("task::"):
            return int(key.split("::")[1]), None
        if key.startswith("sub::"):
            sub_id = int(key.split("::")[1])
            # Look up the parent task id from the DB
            with get_conn() as conn:
                row = conn.execute("SELECT task_id FROM sub_tasks WHERE id=?", (sub_id,)).fetchone()
            if row:
                return row["task_id"], sub_id
        return None

    def get_project_for_task(self, task_id: int) -> str | None:
        with get_conn() as conn:
            row = conn.execute("SELECT project FROM tasks WHERE id=?", (task_id,)).fetchone()
        return row["project"] if row else None

    # ------------------------------------------------------------------
    # ACTIONS
    # ------------------------------------------------------------------

    def action_toggle_hide_done(self) -> None:
        self.hide_done = not self.hide_done
        self.data["view_settings"]["hide_done"] = self.hide_done
        db_save_view_settings(self.data["view_settings"])
        status_msg = "HIDDEN" if self.hide_done else "VISIBLE"
        self.notify(f"'DONE' TASKS ARE NOW {status_msg}.", severity="information")
        self.populate_table()

    # --- Projects -------------------------------------------------------

    def action_manage_projects(self) -> None:
        projects = list(self.data["projects"].keys())
        self.push_screen(ProjectManagerScreen(projects), self.handle_project_manage)

    def handle_project_manage(self, result: dict | None) -> None:
        if not result:
            return
        name = result["name"]

        if result["action"] == "add":
            ok = db_add_project(name, result["color"])
            if not ok:
                self.notify("DESIGNATION ALREADY EXISTS.", severity="error")
                return
            self.notify(f"PROJECT '{name}' INITIALIZED.", severity="information")

        elif result["action"] == "edit":
            new_name = result["new_name"] or None
            new_color = result["new_color"]
            new_color = None if new_color == Select.BLANK else new_color
            ok = db_edit_project(name, new_name, new_color)
            if not ok:
                self.notify("NEW DESIGNATION ALREADY EXISTS.", severity="error")
                return
            self.notify(f"PROJECT '{name}' OVERRIDDEN.", severity="information")

        elif result["action"] == "delete":
            self.push_screen(
                ConfirmScreen(f"Purge {name} and ALL its tasks?"),
                lambda conf: self.finalize_project_purge(conf, name),
            )
            return

        self.populate_table()

    def finalize_project_purge(self, confirm: bool | None, name: str) -> None:
        if confirm:
            db_delete_project(name)
            self.notify(f"PROJECT '{name}' PURGED.", severity="warning")
            self.populate_table()

    # --- Tasks ----------------------------------------------------------

    def action_add_task(self) -> None:
        projects = list(self.data["projects"].keys())
        if not projects:
            self.notify("NO PROJECTS DETECTED. Create a project first.", severity="error")
            return
        self.push_screen(TaskFormScreen(projects), self.handle_task_save)

    def action_add_subtask(self) -> None:
        selected = self.get_selected_task()
        if not selected:
            self.notify("NO TASK SELECTED.", severity="warning")
            return
        task_id, sub_id = selected
        if sub_id is not None:
            self.notify("CANNOT NEST SUB-TASKS. Select a main parent task instead.", severity="error")
            return
        proj = self.get_project_for_task(task_id)
        projects = list(self.data["projects"].keys())
        self.push_screen(
            TaskFormScreen(projects, parent_proj=proj, parent_task_id=task_id, is_subtask=True),
            self.handle_task_save,
        )

    def action_edit_task(self) -> None:
        selected = self.get_selected_task()
        if not selected:
            self.notify("NO TASK SELECTED.", severity="warning")
            return
        task_id, sub_id = selected
        projects = list(self.data["projects"].keys())
        proj = self.get_project_for_task(task_id)

        if sub_id is not None:
            with get_conn() as conn:
                row = conn.execute("SELECT * FROM sub_tasks WHERE id=?", (sub_id,)).fetchone()
            if row:
                task_data = {"task": row["task"], "status": row["status"], "notes": row["notes"]}
                self.push_screen(
                    TaskFormScreen(
                        projects, edit_proj=proj, edit_task_id=task_id,
                        edit_sub_id=sub_id, task_data=task_data, is_subtask=True,
                    ),
                    self.handle_task_save,
                )
        else:
            with get_conn() as conn:
                row = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            if row:
                task_data = {
                    "task": row["task"], "priority": row["priority"],
                    "status": row["status"], "notes": row["notes"],
                }
                self.push_screen(
                    TaskFormScreen(projects, edit_proj=proj, edit_task_id=task_id, task_data=task_data),
                    self.handle_task_save,
                )

    def handle_task_save(self, result: dict | None) -> None:
        if not result:
            return

        proj        = result["project"]
        task_text   = result["task"]
        priority    = result["priority"]
        status      = result["status"]
        notes       = result["notes"]
        edit_task_id = result["edit_task_id"]
        edit_sub_id  = result["edit_sub_id"]
        parent_task_id = result["parent_task_id"]
        is_subtask  = result["is_subtask"]

        if is_subtask:
            if edit_sub_id is not None:
                db_update_subtask(edit_sub_id, task_text, status, notes)
                self.notify("SUB-TASK OVERRIDE SUCCESSFUL.", severity="information")
            else:
                db_add_subtask(parent_task_id, task_text, status, notes)
                self.expanded_rows.add(f"task::{parent_task_id}")
                self.notify("SUB-TASK UPLOADED.", severity="information")
        else:
            if edit_task_id is not None:
                db_update_task(edit_task_id, task_text, priority, status, notes)
                self.notify("TASK OVERRIDE SUCCESSFUL.", severity="information")
            else:
                db_add_task(proj, task_text, priority, status, notes)
                self.notify("TASK UPLOADED TO MAINFRAME.", severity="information")

        self.populate_table()

    def action_delete_task(self) -> None:
        selected = self.get_selected_task()
        if not selected:
            return
        task_id, sub_id = selected
        msg = (
            "Permanently delete this sub-task?"
            if sub_id is not None
            else "Permanently delete this task and ALL its sub-tasks?"
        )
        self.push_screen(
            ConfirmScreen(msg),
            lambda conf: self.finalize_delete_task(conf, task_id, sub_id),
        )

    def finalize_delete_task(self, confirm: bool | None, task_id: int, sub_id: int | None) -> None:
        if confirm:
            if sub_id is not None:
                db_delete_subtask(sub_id)
                self.notify("SUB-TASK PURGED.", severity="warning")
            else:
                db_delete_task(task_id)
                self.expanded_rows.discard(f"task::{task_id}")
                self.notify("TASK PURGED.", severity="warning")
            self.populate_table()

    # --- View / Filter --------------------------------------------------

    def action_view_filter(self) -> None:
        projects = list(self.data["projects"].keys())
        self.push_screen(
            ViewFilterScreen(projects, self.data["view_settings"]),
            self.handle_view_filter,
        )

    def handle_view_filter(self, result: dict | None) -> None:
        if result:
            # Preserve hide_done since ViewFilterScreen doesn't touch it
            result["hide_done"] = self.hide_done
            self.data["view_settings"].update(result)
            db_save_view_settings(self.data["view_settings"])
            self.populate_table()
            self.notify("VIEW PARAMETERS UPDATED.", severity="information")

    # --- Preferences ----------------------------------------------------

    def action_open_preferences(self) -> None:
        current_color = self.data["view_settings"].get("border_color", "#00FF00")
        self.push_screen(PreferencesScreen(current_color), self.handle_preferences)

    def handle_preferences(self, new_color: str | None) -> None:
        if new_color:
            self.app_border = new_color
            self.notify("UI PARAMETERS OVERRIDDEN.", severity="information")

    # --- Log Project ----------------------------------------------------

    def action_open_project_log(self) -> None:
        projects = list(self.data["projects"].keys())
        if not projects:
            self.notify("NO PROJECTS DETECTED.", severity="error")
            return
        self.push_screen(LogProjectSelectScreen(projects), self.handle_log_project_select)

    def handle_log_project_select(self, project: str | None) -> None:
        if project:
            self.push_screen(ProjectLogScreen(project))

# ---------------------------------------------------------------------------
# ENTRY POINT
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    init_db()
    upgrade_project_logs_table() # Safely ensure older DBs get the Title column
    migrate_from_json()   # no-op if tasks.json doesn't exist or already migrated
    app = TaskManagerApp()
    app.run()