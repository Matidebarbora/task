from datetime import datetime

from textual import on, work
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen, Screen
from textual.widgets import Button, DataTable, Footer, Input, Label, Select, Static, TextArea

from db import (
    db_add_project_log,
    db_delete_project_log,
    db_ensure_user,
    db_get_log_by_id,
    db_get_project_logs,
    db_update_project_log,
)


# ---------------------------------------------------------------------------
# SETUP WIZARD  (shown on first run)
# ---------------------------------------------------------------------------

class SetupWizardScreen(Screen):

    def compose(self):
        with Vertical(id="wizard"):
            yield Label("[bold cyan]TASKY — FIRST TIME SETUP[/bold cyan]", id="dialog-title")
            yield Label("Supabase URL:")
            yield Input(placeholder="https://xxxx.supabase.co", id="input-url")
            yield Label("Supabase Anon Key:")
            yield Input(placeholder="eyJ...", password=True, id="input-key")
            yield Label("Your username (lowercase, no spaces):")
            yield Input(placeholder="e.g. matias", id="input-username")
            yield Label("Your display name:")
            yield Input(placeholder="e.g. Matías De Barbora", id="input-display")
            yield Label("", id="status-msg")
            with Horizontal(id="dialog-buttons"):
                yield Button("CONNECT & SAVE", variant="success", id="btn-save")

    def on_mount(self) -> None:
        color = "#00FF00"
        try:
            self.query_one("#wizard").styles.border = ("heavy", color)
        except Exception:
            pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id != "btn-save":
            return

        url = self.query_one("#input-url", Input).value.strip().rstrip("/")
        key = self.query_one("#input-key", Input).value.strip()
        username = self.query_one("#input-username", Input).value.strip().lower()
        display_name = self.query_one("#input-display", Input).value.strip()

        if not url or not key or not username or not display_name:
            self.app.notify("All fields are required.", severity="error")
            return

        event.button.disabled = True
        self.query_one("#status-msg", Label).update("[yellow]Testing connection...[/]")
        self._connect(url, key, username, display_name)

    @work(thread=True)
    def _connect(self, url: str, key: str, username: str, display_name: str) -> None:
        try:
            from supabase import create_client
            client = create_client(url, key)
            client.table("projects").select("name").limit(1).execute()

            existing = client.table("users").select("username").eq("username", username).execute()
            if not existing.data:
                client.table("users").insert({
                    "username": username,
                    "display_name": display_name,
                }).execute()

            from config import save_config, DEFAULT_VIEW_SETTINGS
            save_config({
                "supabase_url": url,
                "supabase_key": key,
                "username": username,
                "display_name": display_name,
                "view_settings": DEFAULT_VIEW_SETTINGS.copy(),
            })
            self.app.call_from_thread(self._on_success)
        except Exception as e:
            self.app.call_from_thread(self._on_error, str(e))

    def _on_success(self) -> None:
        self.dismiss(True)

    def _on_error(self, error: str) -> None:
        try:
            self.query_one("#status-msg", Label).update(f"[bold red]{error}[/]")
            self.query_one("#btn-save", Button).disabled = False
        except Exception:
            pass


# ---------------------------------------------------------------------------
# GENERIC MODALS
# ---------------------------------------------------------------------------

class ConfirmScreen(ModalScreen[bool]):
    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, message: str):
        super().__init__()
        self.message = message

    def compose(self):
        with Vertical(id="dialog"):
            yield Label(f"[bold red]WARNING:[/bold red] {self.message}", id="dialog-title")
            with Horizontal(id="dialog-buttons"):
                yield Button("YES, PURGE", variant="error", id="btn-yes")
                yield Button("CANCEL", variant="success", id="btn-no")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "btn-yes")

    def on_mount(self) -> None:
        _apply_dialog_style(self)


class HelpScreen(ModalScreen[None]):
    BINDINGS = [
        ("escape", "close", "Close"),
        ("?", "close", "Close"),
    ]

    def __init__(self, bindings_list: list[tuple[str, str]]):
        super().__init__()
        self.bindings_list = bindings_list

    def compose(self):
        with Vertical(id="help-dialog"):
            yield Label("[bold cyan]KEYBOARD SHORTCUTS[/]", id="dialog-title")
            dt = DataTable(id="help-table")
            dt.show_header = False
            yield dt
            with Horizontal(id="dialog-buttons"):
                yield Button("CLOSE", variant="primary", id="btn-close")

    def on_mount(self) -> None:
        color = getattr(self.app, "app_border", "#00ff00")
        bg_color = getattr(self.app, "app_bg", "")
        try:
            dialog = self.query_one("#help-dialog")
            dialog.styles.border = ("heavy", color)
            if bg_color:
                dialog.styles.background = bg_color
            self.query_one("#help-table").styles.border = ("round", color)
        except Exception:
            pass

        table = self.query_one(DataTable)
        table.add_columns("KEY", "ACTION")
        for key, desc in self.bindings_list:
            table.add_row(f"[bold cyan]{key.upper()}[/]", desc)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-close":
            self.dismiss(None)

    def action_close(self) -> None:
        self.dismiss(None)


# ---------------------------------------------------------------------------
# TASK / PROJECT MODALS
# ---------------------------------------------------------------------------

class TaskFormScreen(ModalScreen[dict]):
    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(
        self,
        projects: list,
        users: list[str],
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
        self.users = users
        self.edit_proj = edit_proj
        self.edit_task_id = edit_task_id
        self.edit_sub_id = edit_sub_id
        self.task_data = task_data or {}
        self.is_subtask = is_subtask
        self.parent_proj = parent_proj
        self.parent_task_id = parent_task_id

    def compose(self):
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
        user_options = [("— UNASSIGNED —", "")] + [(u, u) for u in self.users]

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
            if not self.is_subtask:
                yield Label("Assigned To:")
                yield Select(
                    user_options,
                    id="select-assigned",
                    value=self.task_data.get("assigned_to") or "",
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

            if priority == Select.BLANK:
                priority = "2. MEDIUM"
            if status == Select.BLANK:
                status = "TO DO"
            if status == "DONE":
                priority = "4. ----"

            assigned_to: str | None = None
            if not self.is_subtask:
                raw = self.query_one("#select-assigned", Select).value
                assigned_to = str(raw) if raw and raw != Select.BLANK else None

            self.dismiss({
                "project": project,
                "task": desc.strip(),
                "priority": priority,
                "status": status,
                "notes": notes.strip() if notes.strip() else None,
                "assigned_to": assigned_to,
                "edit_task_id": self.edit_task_id,
                "edit_sub_id": self.edit_sub_id,
                "parent_task_id": self.parent_task_id,
                "is_subtask": self.is_subtask,
            })
        elif event.button.id == "btn-cancel":
            self.dismiss(None)

    def on_mount(self) -> None:
        _apply_dialog_style(self)


class ViewFilterScreen(ModalScreen[dict]):
    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, projects: list, current_settings: dict):
        super().__init__()
        self.projects = projects
        self.settings = current_settings

    def compose(self):
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
            self.dismiss({
                "sort_by": "priority" if sb == Select.BLANK else sb,
                "filter_project": None if fp in ("NONE", Select.BLANK) else fp,
                "filter_priority": None if fpr in ("NONE", Select.BLANK) else fpr,
            })
        elif event.button.id == "btn-clear":
            self.dismiss({
                "sort_by": self.settings.get("sort_by", "priority"),
                "filter_project": None,
                "filter_priority": None,
            })
        elif event.button.id == "btn-cancel":
            self.dismiss(None)

    def on_mount(self) -> None:
        _apply_dialog_style(self)


class ProjectManagerScreen(ModalScreen[dict]):
    BINDINGS = [("escape", "cancel", "Cancel")]

    COLOR_PALETTE = {
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

    def __init__(self, projects: list):
        super().__init__()
        self.projects = projects

    def compose(self):
        color_opts = [
            (f"[{hex_code} bold]{name}[/]", hex_code)
            for name, hex_code in self.COLOR_PALETTE.items()
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
            self.dismiss({
                "action": "edit",
                "name": target,
                "new_name": new_name,
                "new_color": new_color,
            })
        elif event.button.id == "btn-del":
            target = self.query_one("#del-proj-name", Select).value
            if target == Select.BLANK:
                self.app.notify("No project selected to purge.", severity="warning")
                return
            self.dismiss({"action": "delete", "name": target})
        elif event.button.id == "btn-cancel":
            self.dismiss(None)

    def on_mount(self) -> None:
        _apply_dialog_style(self)


class PreferencesScreen(ModalScreen[dict]):
    BINDINGS = [("escape", "cancel", "Cancel")]

    BORDER_PALETTE = {
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

    BG_PALETTE = {
        "DEFAULT (Theme)": "",
        "TRANSPARENT": "transparent",
        "LAZYGIT DARK": "#242424",
        "LAZYGIT BLUE": "#1e252c",
        "PURE BLACK": "#000000",
        "DEEP NAVY": "#000040",
        "UBUNTU PLUM": "#300a24",
    }

    def __init__(self, current_border: str, current_bg: str):
        super().__init__()
        self.current_border = current_border
        self.current_bg = current_bg

    def compose(self):
        border_opts = [
            (f"[{hex_code} bold]{name}[/]", hex_code)
            for name, hex_code in self.BORDER_PALETTE.items()
        ]
        bg_opts = []
        for name, hex_code in self.BG_PALETTE.items():
            if hex_code == "transparent":
                bg_opts.append((f"[#ffffff on transparent] {name} [/]", hex_code))
            else:
                bg_opts.append((f"[{hex_code or '#ffffff'} on {hex_code or 'transparent'}] {name} [/]", hex_code))

        with Vertical(id="dialog"):
            yield Label("[bold cyan]APP PREFERENCES[/bold cyan]", id="dialog-title")
            yield Label("Border Color:")
            yield Select(border_opts, id="select-border-color", value=self.current_border, prompt="Select border color...")
            yield Label("Background Color:")
            yield Select(bg_opts, id="select-bg-color", value=self.current_bg, prompt="Select background color...")
            with Horizontal(id="dialog-buttons"):
                yield Button("APPLY", variant="success", id="btn-apply")
                yield Button("CANCEL", variant="error", id="btn-cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-apply":
            b_color = self.query_one("#select-border-color", Select).value
            bg_color = self.query_one("#select-bg-color", Select).value
            self.dismiss({
                "border": str(b_color) if b_color != Select.BLANK else self.current_border,
                "bg": str(bg_color) if bg_color != Select.BLANK else "",
            })
        elif event.button.id == "btn-cancel":
            self.dismiss(None)

    def on_mount(self) -> None:
        _apply_dialog_style(self)


# ---------------------------------------------------------------------------
# LOG SCREENS
# ---------------------------------------------------------------------------

class LogDetailScreen(ModalScreen[None]):
    BINDINGS = [
        ("escape", "close", "Close"),
        ("enter", "close", "Close"),
    ]

    def __init__(self, log_data: dict):
        super().__init__()
        self.log_data = log_data

    def compose(self):
        with Vertical(id="dialog"):
            yield Label(
                f"[bold cyan]{self.log_data['log_date']} - {self.log_data['title']}[/]",
                id="dialog-title",
            )
            notes_area = TextArea(text=self.log_data.get("notes", ""), read_only=True)
            notes_area.styles.height = "1fr"
            yield notes_area
            with Horizontal(id="dialog-buttons"):
                yield Button("CLOSE", variant="primary", id="btn-close")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-close":
            self.dismiss(None)

    def action_close(self) -> None:
        self.dismiss(None)

    def on_mount(self) -> None:
        _apply_dialog_style(self)


class LogFormScreen(ModalScreen[dict]):
    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, log_data: dict | None = None):
        super().__init__()
        self.log_data = log_data or {}
        self.is_edit = bool(self.log_data)

    def compose(self):
        default_date = self.log_data.get("log_date", datetime.now().strftime("%Y-%m-%d"))
        form_title = "[bold yellow]EDIT MILESTONE LOG[/]" if self.is_edit else "[bold cyan]ADD MILESTONE LOG[/]"

        with Vertical(id="dialog"):
            yield Label(form_title, id="dialog-title")
            yield Label("Date (YYYY-MM-DD):")
            yield Input(value=default_date, id="input-date")
            yield Label("Title:")
            yield Input(value=self.log_data.get("title", ""), placeholder="e.g., Meeting with client...", id="input-title")
            yield Label("Notes:")
            notes_area = TextArea(text=self.log_data.get("notes", ""), id="input-notes")
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

            try:
                datetime.strptime(date_val, "%Y-%m-%d")
            except ValueError:
                self.app.notify("Date must be YYYY-MM-DD format.", severity="error")
                return

            self.dismiss({
                "action": "save",
                "id": self.log_data.get("id"),
                "date": date_val,
                "title": title_val,
                "notes": notes_val,
            })
        elif event.button.id == "btn-delete":
            self.dismiss({"action": "delete", "id": self.log_data.get("id")})
        elif event.button.id == "btn-cancel":
            self.dismiss(None)

    def on_mount(self) -> None:
        _apply_dialog_style(self)


class ProjectLogScreen(Screen):
    BINDINGS = [
        Binding("escape", "app.pop_screen", "Back to Tasks", show=False),
        Binding("ctrl+a", "add_log", "Add Log Entry", show=False),
        Binding("ctrl+r", "edit_log", "Edit Entry", show=False),
        Binding("?", "show_help", "Shortcuts"),
    ]

    def __init__(self, project_name: str):
        super().__init__()
        self.project_name = project_name
        self.expanded_logs: set[str] = set()

    def compose(self):
        with Horizontal(id="top-bar"):
            yield Static(f"TASKY  —  {self.project_name} LOG", id="app-title")
        yield DataTable(id="log-table", cursor_type="row")
        yield Footer()

    def on_mount(self) -> None:
        color = getattr(self.app, "app_border", "#00FF00")
        self.query_one("#app-title").styles.border = ("round", color)
        self.query_one(DataTable).styles.border = ("round", color)
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

        for log in db_get_project_logs(self.project_name):
            row_key = f"log::{log['id']}"
            indicator = "[bold cyan]▼[/] " if row_key in self.expanded_logs else "[bold white]▶[/] "
            table.add_row(
                f"{indicator}[bold cyan]{log['log_date']}[/]",
                f"[bold white]{log['title']}[/]",
                key=row_key,
            )
            if row_key in self.expanded_logs:
                table.add_row("", f"[gray]↳[/] {log['notes']}", key=f"note::{log['id']}")

        if cursor_key:
            try:
                table.move_cursor(row=table.get_row_index(cursor_key))
            except Exception:
                pass

    @on(DataTable.RowSelected)
    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        log_id = _parse_log_key(event.row_key.value)
        if log_id is None:
            return
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
        log_id = _parse_log_key(row_key_value)
        if log_id is None:
            return
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
        elif action == "delete" and log_id:
            db_delete_project_log(log_id)
            self.expanded_logs.discard(f"log::{log_id}")
            self.app.notify("Log entry deleted.", severity="warning")

        self.populate_table()

    def action_show_help(self) -> None:
        screen_binds = []
        for b in self.BINDINGS:
            if isinstance(b, tuple):
                screen_binds.append((b[0], b[2] if len(b) == 3 else str(b[1])))
            else:
                screen_binds.append((b.key, b.description))
        self.app.push_screen(HelpScreen(screen_binds + [("ctrl+q", "Quit"), ("ctrl+p", "Preferences"), ("ctrl+l", "Project Log")]))


# ---------------------------------------------------------------------------
# INTERNAL HELPERS
# ---------------------------------------------------------------------------

def _parse_log_key(row_key_value) -> int | None:
    key = str(row_key_value) if row_key_value is not None else ""
    if not key.startswith("log::"):
        return None
    try:
        return int(key.split("::")[1])
    except (IndexError, ValueError):
        return None


def _apply_dialog_style(screen: ModalScreen) -> None:
    color = getattr(screen.app, "app_border", "#00ff00")
    bg_color = getattr(screen.app, "app_bg", "")
    try:
        dialog = screen.query_one("#dialog")
        dialog.styles.border = ("heavy", color)
        if bg_color:
            dialog.styles.background = bg_color
    except Exception:
        pass
