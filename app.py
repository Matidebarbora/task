import sys

from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.reactive import reactive
from textual.widgets import DataTable, Footer, Select, Static

from config import config_exists, load_config
from db import (
    db_add_project,
    db_add_subtask,
    db_add_task,
    db_delete_project,
    db_delete_subtask,
    db_delete_task,
    db_edit_project,
    db_get_project_for_task,
    db_get_subtask,
    db_get_subtask_parent,
    db_get_task,
    db_get_users,
    db_load_data,
    db_save_view_settings,
    db_update_subtask,
    db_update_task,
)
from screens import (
    ConfirmScreen,
    HelpScreen,
    PreferencesScreen,
    ProjectLogScreen,
    ProjectManagerScreen,
    SetupWizardScreen,
    TaskFormScreen,
    ViewFilterScreen,
)


class TaskManagerApp(App):
    CSS_PATH = "styles.tcss"

    BINDINGS = [
        Binding("ctrl+1", "manage_projects", "Projects", show=False),
        Binding("ctrl+2", "add_task", "Add Task", show=False),
        Binding("ctrl+s", "add_subtask", "Add Sub-task", show=False),
        Binding("ctrl+e", "edit_task", "Edit Task", show=False),
        Binding("ctrl+d", "delete_task", "Delete Task", show=False),
        Binding("ctrl+f", "view_filter", "View/Filter", show=False),
        Binding("ctrl+h", "toggle_hide_done", "Hide Done", show=False),
        Binding("ctrl+m", "toggle_my_tasks", "My Tasks", show=False),
        Binding("ctrl+p", "open_preferences", "Preferences", show=False),
        Binding("ctrl+l", "open_project_log", "Project Log", show=False),
        Binding("?", "show_help", "Shortcuts"),
        Binding("ctrl+q", "app.quit", "Quit"),
    ]

    app_border = reactive("#00FF00")
    app_bg = reactive("")

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def on_mount(self) -> None:
        if not config_exists():
            self.push_screen(SetupWizardScreen(), self._after_setup)
        else:
            self._initialize()

    def _after_setup(self, success: bool | None) -> None:
        if success:
            self._initialize()
        else:
            self.exit()

    def _initialize(self) -> None:
        cfg = load_config()
        self.current_user: str = cfg["username"]
        self.my_tasks_only: bool = False

        self.data = db_load_data()
        self.expanded_rows: set[str] = set()
        self.hide_done: bool = self.data["view_settings"].get("hide_done", False)

        vs = self.data.get("view_settings", {})
        if "theme" in vs:
            self.theme = vs["theme"]
        if "border_color" in vs:
            self.app_border = vs["border_color"]
        if "bg_color" in vs:
            self.app_bg = vs["bg_color"]

        self._update_header()
        self.populate_table()

    def compose(self) -> ComposeResult:
        with Horizontal(id="top-bar"):
            yield Static("TASKY", id="app-title")
        yield DataTable(id="task-table", cursor_type="row")
        yield Footer()

    # ------------------------------------------------------------------
    # Reactive watchers
    # ------------------------------------------------------------------

    def watch_app_border(self, new_color: str) -> None:
        for title in self.query("#app-title"):
            title.styles.border = ("round", new_color)
        for dt in self.query(DataTable):
            dt.styles.border = ("round", new_color)
        for dialog in self.query("#dialog"):
            dialog.styles.border = ("heavy", new_color)
        for help_dialog in self.query("#help-dialog"):
            help_dialog.styles.border = ("heavy", new_color)
        if hasattr(self, "data") and "view_settings" in self.data:
            self.data["view_settings"]["border_color"] = new_color
            db_save_view_settings(self.data["view_settings"])

    def watch_app_bg(self, new_bg: str) -> None:
        bg_val = new_bg or None
        self.styles.background = bg_val
        for dialog in self.query("#dialog, #help-dialog"):
            if bg_val:
                dialog.styles.background = bg_val
            else:
                dialog.styles.background = None
        if hasattr(self, "data") and "view_settings" in self.data:
            self.data["view_settings"]["bg_color"] = new_bg
            db_save_view_settings(self.data["view_settings"])

    def watch_theme(self, new_theme: str) -> None:
        if hasattr(self, "data") and "view_settings" in self.data:
            self.data["view_settings"]["theme"] = new_theme
            db_save_view_settings(self.data["view_settings"])

    # ------------------------------------------------------------------
    # Header
    # ------------------------------------------------------------------

    def _update_header(self) -> None:
        user = getattr(self, "current_user", "")
        my = getattr(self, "my_tasks_only", False)
        label = f"TASKY  —  @{user}" if user else "TASKY"
        if my:
            label += "  [MY TASKS]"
        try:
            self.query_one("#app-title", Static).update(label)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Table rendering
    # ------------------------------------------------------------------

    def populate_table(self) -> None:
        self.data = db_load_data()
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
            table.add_columns("PROJECT", "PRIORITY", "TASK", "STATUS", "ASSIGNED", "NOTES")

        view = self.data["view_settings"]
        all_tasks = [
            (project, t)
            for project, tasks in self.data.get("projects", {}).items()
            for t in tasks
        ]
        all_tasks = _filter_tasks(
            all_tasks, view, self.hide_done,
            getattr(self, "my_tasks_only", False),
            getattr(self, "current_user", ""),
        )
        all_tasks = _sort_tasks(all_tasks, view)

        for proj, t in all_tasks:
            p_col = self.data["project_colors"].get(proj, "cyan")
            proj_str = f"[{p_col} bold]{proj}[/]"
            prio_str = _format_priority(t["priority"])
            stat_str = _format_status(t["status"])
            assigned = t.get("assigned_to") or ""
            assigned_str = f"[bold cyan]@{assigned}[/]" if assigned else "[gray]—[/]"

            task_db_id = t["_id"]
            row_key = f"task::{task_db_id}"
            sub_tasks = t.get("sub_tasks", [])
            visible_subs = [s for s in sub_tasks if s.get("status") != "DONE"] if self.hide_done else sub_tasks

            indicator = (
                "[bold cyan]▼[/] " if row_key in self.expanded_rows
                else "[bold white]▶[/] "
            ) if visible_subs else "  "

            table.add_row(
                proj_str, prio_str, f"{indicator}{t['task']}", stat_str,
                assigned_str, t.get("notes", "") or "", key=row_key,
            )

            if row_key in self.expanded_rows:
                for sub in sub_tasks:
                    if self.hide_done and sub.get("status") == "DONE":
                        continue
                    table.add_row(
                        "", "",
                        f"    [gray]↳[/] {sub['task']}",
                        _format_status(sub.get("status", "TO DO")),
                        assigned_str,
                        sub.get("notes", "") or "",
                        key=f"sub::{sub['_id']}",
                    )

        if cursor_key:
            try:
                table.move_cursor(row=table.get_row_index(cursor_key))
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
    # Helpers
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
            parent = db_get_subtask_parent(sub_id)
            if parent:
                return parent, sub_id
        return None

    # ------------------------------------------------------------------
    # ACTIONS — Help
    # ------------------------------------------------------------------

    def action_show_help(self) -> None:
        bindings_list = []
        for b in self.BINDINGS:
            if isinstance(b, tuple):
                bindings_list.append((b[0], b[2] if len(b) == 3 else str(b[1])))
            else:
                bindings_list.append((b.key, b.description))
        self.push_screen(HelpScreen(bindings_list))

    # ------------------------------------------------------------------
    # ACTIONS — Projects
    # ------------------------------------------------------------------

    def action_manage_projects(self) -> None:
        self.push_screen(ProjectManagerScreen(list(self.data["projects"].keys())), self.handle_project_manage)

    def handle_project_manage(self, result: dict | None) -> None:
        if not result:
            return
        name = result["name"]

        if result["action"] == "add":
            if not db_add_project(name, result["color"]):
                self.notify("DESIGNATION ALREADY EXISTS.", severity="error")
                return
            self.notify(f"PROJECT '{name}' INITIALIZED.", severity="information")

        elif result["action"] == "edit":
            new_name = result["new_name"] or None
            new_color = result["new_color"]
            new_color = None if new_color == Select.BLANK else new_color
            if not db_edit_project(name, new_name, new_color):
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

    # ------------------------------------------------------------------
    # ACTIONS — Tasks
    # ------------------------------------------------------------------

    def action_add_task(self) -> None:
        projects = list(self.data["projects"].keys())
        if not projects:
            self.notify("NO PROJECTS DETECTED. Create a project first.", severity="error")
            return
        self.push_screen(TaskFormScreen(projects, db_get_users()), self.handle_task_save)

    def action_add_subtask(self) -> None:
        selected = self.get_selected_task()
        if not selected:
            self.notify("NO TASK SELECTED.", severity="warning")
            return
        task_id, sub_id = selected
        if sub_id is not None:
            self.notify("CANNOT NEST SUB-TASKS. Select a main parent task instead.", severity="error")
            return
        proj = db_get_project_for_task(task_id)
        self.push_screen(
            TaskFormScreen(
                list(self.data["projects"].keys()), db_get_users(),
                parent_proj=proj, parent_task_id=task_id, is_subtask=True,
            ),
            self.handle_task_save,
        )

    def action_edit_task(self) -> None:
        selected = self.get_selected_task()
        if not selected:
            self.notify("NO TASK SELECTED.", severity="warning")
            return
        task_id, sub_id = selected
        projects = list(self.data["projects"].keys())
        proj = db_get_project_for_task(task_id)

        if sub_id is not None:
            row = db_get_subtask(sub_id)
            if row:
                task_data = {"task": row["task"], "status": row["status"], "notes": row["notes"]}
                self.push_screen(
                    TaskFormScreen(
                        projects, db_get_users(), edit_proj=proj, edit_task_id=task_id,
                        edit_sub_id=sub_id, task_data=task_data, is_subtask=True,
                    ),
                    self.handle_task_save,
                )
        else:
            row = db_get_task(task_id)
            if row:
                task_data = {
                    "task": row["task"], "priority": row["priority"],
                    "status": row["status"], "notes": row["notes"],
                    "assigned_to": row.get("assigned_to"),
                }
                self.push_screen(
                    TaskFormScreen(projects, db_get_users(), edit_proj=proj, edit_task_id=task_id, task_data=task_data),
                    self.handle_task_save,
                )

    def handle_task_save(self, result: dict | None) -> None:
        if not result:
            return

        proj           = result["project"]
        task_text      = result["task"]
        priority       = result["priority"]
        status         = result["status"]
        notes          = result["notes"]
        assigned_to    = result.get("assigned_to")
        edit_task_id   = result["edit_task_id"]
        edit_sub_id    = result["edit_sub_id"]
        parent_task_id = result["parent_task_id"]
        is_subtask     = result["is_subtask"]

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
                db_update_task(edit_task_id, task_text, priority, status, notes, assigned_to)
                self.notify("TASK OVERRIDE SUCCESSFUL.", severity="information")
            else:
                db_add_task(proj, task_text, priority, status, notes, assigned_to)
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

    # ------------------------------------------------------------------
    # ACTIONS — View / Filter
    # ------------------------------------------------------------------

    def action_view_filter(self) -> None:
        self.push_screen(
            ViewFilterScreen(list(self.data["projects"].keys()), self.data["view_settings"]),
            self.handle_view_filter,
        )

    def handle_view_filter(self, result: dict | None) -> None:
        if result:
            result["hide_done"] = self.hide_done
            self.data["view_settings"].update(result)
            db_save_view_settings(self.data["view_settings"])
            self.populate_table()
            self.notify("VIEW PARAMETERS UPDATED.", severity="information")

    # ------------------------------------------------------------------
    # ACTIONS — Preferences
    # ------------------------------------------------------------------

    def action_open_preferences(self) -> None:
        current_border = self.data["view_settings"].get("border_color", "#00FF00")
        current_bg = self.data["view_settings"].get("bg_color", "")
        self.push_screen(PreferencesScreen(current_border, current_bg), self.handle_preferences)

    def handle_preferences(self, result: dict | None) -> None:
        if result:
            self.app_border = result["border"]
            self.app_bg = result["bg"]
            self.notify("UI PARAMETERS OVERRIDDEN.", severity="information")

    # ------------------------------------------------------------------
    # ACTIONS — Project Log
    # ------------------------------------------------------------------

    def action_open_project_log(self) -> None:
        selected = self.get_selected_task()
        if not selected:
            self.notify("SELECT A TASK FIRST.", severity="warning")
            return
        task_id, _ = selected
        project = db_get_project_for_task(task_id)
        if project:
            self.push_screen(ProjectLogScreen(project))

    # ------------------------------------------------------------------
    # ACTIONS — Toggle filters
    # ------------------------------------------------------------------

    def action_toggle_hide_done(self) -> None:
        self.hide_done = not self.hide_done
        self.data["view_settings"]["hide_done"] = self.hide_done
        db_save_view_settings(self.data["view_settings"])
        status_msg = "HIDDEN" if self.hide_done else "VISIBLE"
        self.notify(f"'DONE' TASKS ARE NOW {status_msg}.", severity="information")
        self.populate_table()

    def action_toggle_my_tasks(self) -> None:
        self.my_tasks_only = not self.my_tasks_only
        self._update_header()
        status_msg = "MY TASKS" if self.my_tasks_only else "ALL TASKS"
        self.notify(f"VIEW: {status_msg}", severity="information")
        self.populate_table()


# ---------------------------------------------------------------------------
# TABLE RENDERING HELPERS
# ---------------------------------------------------------------------------

def _filter_tasks(
    all_tasks: list,
    view: dict,
    hide_done: bool,
    my_tasks_only: bool = False,
    current_user: str = "",
) -> list:
    if view.get("filter_project"):
        all_tasks = [x for x in all_tasks if x[0] == view["filter_project"]]
    if view.get("filter_priority"):
        all_tasks = [x for x in all_tasks if x[1]["priority"] == view["filter_priority"]]
    if hide_done:
        all_tasks = [x for x in all_tasks if x[1].get("status") != "DONE"]
    if my_tasks_only and current_user:
        all_tasks = [x for x in all_tasks if x[1].get("assigned_to") == current_user]
    return all_tasks


def _sort_tasks(all_tasks: list, view: dict) -> list:
    if view.get("sort_by", "priority") == "project":
        return sorted(all_tasks, key=lambda x: x[0])
    return sorted(all_tasks, key=lambda x: (x[1]["priority"], x[0]))


def _format_priority(prio: str) -> str:
    if "HIGH" in prio:
        return f"[bold red]{prio}[/]"
    if "MEDIUM" in prio:
        return f"[bold yellow]{prio}[/]"
    if "LOW" in prio:
        return f"[cyan]{prio}[/]"
    return f"[white]{prio}[/]"


def _format_status(stat: str) -> str:
    if "DONE" in stat:
        return f"[bold green]{stat}[/]"
    if "IN PROGRESS" in stat:
        return f"[bold cyan]{stat}[/]"
    if "ON HOLD" in stat:
        return f"[bold red]{stat}[/]"
    return f"[white]{stat}[/]"


# ---------------------------------------------------------------------------
# ENTRY POINT
# ---------------------------------------------------------------------------

APP_VERSION = "1.0.0"


def _check_version() -> None:
    try:
        from db import get_client
        result = (
            get_client()
            .table("app_version")
            .select("version, notes")
            .order("updated_at", desc=True)
            .limit(1)
            .execute()
        )
        if not result.data:
            return
        required = result.data[0]["version"]
        if required == APP_VERSION:
            return
        notes = result.data[0].get("notes") or ""
        print()
        print("=" * 52)
        print("  TASKY — UPDATE REQUIRED")
        print("=" * 52)
        print(f"  Tu versión   : {APP_VERSION}")
        print(f"  Versión actual : {required}")
        if notes:
            print(f"  Notas        : {notes}")
        print()
        print("  Ejecutá:  git pull")
        print("  Luego reiniciá la app.")
        print("=" * 52)
        print()
        sys.exit(1)
    except SystemExit:
        raise
    except Exception:
        pass  # Si falla el check, no bloquear el arranque


def main() -> None:
    if config_exists():
        _check_version()
    TaskManagerApp().run()


if __name__ == "__main__":
    main()
