import json
import os
import ssl
import urllib.request
from datetime import datetime

from textual import on, work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widgets import DataTable, Footer, Static, Input, Select, Button, Label

DATA_FILE = "tasks.json"

# --- DATA HANDLING ---
def load_data():
    if not os.path.exists(DATA_FILE):
        return {
            "projects": {}, 
            "project_colors": {}, 
            "view_settings": {
                "sort_by": "priority", 
                "filter_project": None, 
                "filter_priority": None, 
                "theme": "textual-dark",
                "hide_done": False  # Add this line
            }
        }
    with open(DATA_FILE, "r") as file:
        return json.load(file)
    
def save_data(data):
    with open(DATA_FILE, "w") as file:
        json.dump(data, file, indent=4)

# --- UI COMPONENTS ---
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
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            
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
        content = f"[#00ff00]DATE:[/#00ff00] {self.date_str}  |  [#00ff00]TIME:[/#00ff00] {self.time_str}  |  [#00ff00]TEMP:[/#00ff00] {self.weather_str}°C"
        self.update(content)


# --- MODAL SCREENS ---
class ConfirmScreen(ModalScreen[bool]):
    """Generic confirmation dialog."""

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


class TaskFormScreen(ModalScreen[dict]):
    """Handles Adding and Editing both Main Tasks and Sub-tasks."""

    BINDINGS = [("escape", "cancel", "Cancel")]
    
    def __init__(self, projects: list, edit_proj: str | None = None, edit_idx: int | None = None, edit_sub_idx: int | None = None, task_data: dict | None = None, is_subtask: bool = False, parent_proj: str | None = None) -> None:
        super().__init__()
        self.projects = projects
        self.edit_proj = edit_proj
        self.edit_idx = edit_idx
        self.edit_sub_idx = edit_sub_idx
        self.task_data = task_data or {}
        self.is_subtask = is_subtask
        self.parent_proj = parent_proj

    def compose(self) -> ComposeResult:
        proj_options = [(p, p) for p in self.projects]
        prio_options = [("1. HIGH", "1. HIGH"), ("2. MEDIUM", "2. MEDIUM"), ("3. LOW", "3. LOW"), ("4. ----", "4. ----")]
        stat_options = [("TO DO", "TO DO"), ("IN PROGRESS", "IN PROGRESS"), ("ON HOLD", "ON HOLD"), ("DONE", "DONE")]
        
        is_edit = self.edit_idx is not None
        if self.is_subtask:
            title = "[bold yellow]EDITING SUB-TASK[/]" if self.edit_sub_idx is not None else "[bold cyan]INITIALIZING SUB-TASK...[/]"
        else:
            title = "[bold yellow]EDITING TASK OVERRIDE[/]" if is_edit else "[bold green]INITIALIZING NEW TASK SEQUENCE...[/]"
        
        with Vertical(id="dialog"):
            yield Label(title, id="dialog-title")
            
            yield Label("Project Designation:")
            sel_proj = Select(proj_options, id="select-project", prompt="Select Project...")
            
            if self.edit_proj is not None or self.is_subtask:
                sel_proj.value = self.edit_proj or self.parent_proj  # type: ignore
                sel_proj.disabled = True
            yield sel_proj
            
            yield Label("Task Description:")
            yield Input(value=self.task_data.get("task", ""), placeholder="Enter task...", id="input-desc")
            
            yield Label("Priority:")
            sel_prio = Select(prio_options, id="select-priority", value=self.task_data.get("priority", "2. MEDIUM"))
            if self.is_subtask:
                sel_prio.disabled = True
            yield sel_prio
            
            yield Label("Status:")
            yield Select(stat_options, id="select-status", value=self.task_data.get("status", "TO DO"))
            
            yield Label("Notes (Optional):")
            yield Input(value=self.task_data.get("notes", ""), placeholder="Enter notes...", id="input-notes")
            
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
                
            result = {
                "project": project,
                "task": desc.strip(),
                "priority": priority,
                "status": status,
                "notes": notes.strip() if notes.strip() else None,
                "edit_idx": self.edit_idx,
                "edit_sub_idx": self.edit_sub_idx,
                "is_subtask": self.is_subtask
            }
            self.dismiss(result)
        elif event.button.id == "btn-cancel":
            self.dismiss(None)


class ViewFilterScreen(ModalScreen[dict]):
    """Configures sorting and filtering."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, projects: list, current_settings: dict):
        super().__init__()
        self.projects = projects
        self.settings = current_settings

    def compose(self) -> ComposeResult:
        sort_opts = [("PROJECT", "project"), ("PRIORITY", "priority")]
        proj_opts = [("NONE", "NONE")] + [(p, p) for p in self.projects]
        prio_opts = [("NONE", "NONE"), ("1. HIGH", "1. HIGH"), ("2. MEDIUM", "2. MEDIUM"), ("3. LOW", "3. LOW"), ("4. ----", "4. ----")]
        
        with Vertical(id="dialog"):
            yield Label("[bold cyan]VIEW & FILTER CONFIGURATION[/bold cyan]", id="dialog-title")
            
            yield Label("Sort By:")
            yield Select(sort_opts, id="sort-by", value=self.settings.get("sort_by", "priority"))
            
            yield Label("Project Filter:")
            yield Select(proj_opts, id="filter-proj", value=self.settings.get("filter_project") or "NONE")
            
            yield Label("Priority Filter:")
            yield Select(prio_opts, id="filter-prio", value=self.settings.get("filter_priority") or "NONE")
            
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
                "filter_priority": None if fpr in ("NONE", Select.BLANK) else fpr
            })
            
        elif event.button.id == "btn-clear":
            self.dismiss({
                "sort_by": self.settings.get("sort_by", "priority"),
                "filter_project": None,
                "filter_priority": None
            })
            
        elif event.button.id == "btn-cancel":
            self.dismiss(None)


class ProjectManagerScreen(ModalScreen[dict]):
    """Adds, edits, or deletes projects."""

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
            "VIOLET": "#EE82EE"
        }
        
        color_opts = [(f"[{hex_code} bold]{name}[/]", hex_code) for name, hex_code in color_palette.items()]
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
            self.dismiss({"action": "edit", "name": target, "new_name": new_name, "new_color": new_color})
            
        elif event.button.id == "btn-del":
            target = self.query_one("#del-proj-name", Select).value
            if target == Select.BLANK:
                self.app.notify("No project selected to purge.", severity="warning")
                return
            self.dismiss({"action": "delete", "name": target})
            
        elif event.button.id == "btn-cancel":
            self.dismiss(None)


# --- MAIN APP ---

class TaskManagerApp(App):
    CSS = """
    Screen { background: $surface; }
    
    /* Reduced height and adapted for a single 100% width panel */
    #top-bar { height: 3; margin-bottom: 0; }
    SystemStatus { width: 100%; height: 100%; border: round #00ff00; border-title-color: #00ff00; content-align: center middle; }
    DataTable { border: round #00ff00; height: 1fr; }
    
    /* Modals */
    ConfirmScreen, TaskFormScreen, ViewFilterScreen, ProjectManagerScreen {
        align: center middle;
        background: $background 50%;
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
        ("h", "toggle_hide_done", "Hide Done"),  # Add this line
        ("q", "app.quit", "Quit"),
    ]

    def action_toggle_hide_done(self) -> None:
        """Toggles the visibility of tasks marked as DONE."""
        self.hide_done = not self.hide_done
        self.data["view_settings"]["hide_done"] = self.hide_done
        save_data(self.data)
        
        status_msg = "HIDDEN" if self.hide_done else "VISIBLE"
        self.notify(f"'DONE' TASKS ARE NOW {status_msg}.", severity="information")
        self.populate_table()

    def on_mount(self) -> None:
        self.title = "TASKS_MANAGER"
        self.data = load_data()
        self.expanded_rows = set()
        
        # Load the hide_done state
        self.hide_done = self.data.setdefault("view_settings", {}).get("hide_done", False)
        
        if "theme" in self.data.get("view_settings", {}):
            self.theme = self.data["view_settings"]["theme"]
            
        self.populate_table()

    def watch_theme(self, new_theme: str) -> None:
        if hasattr(self, "data") and "view_settings" in self.data:
            self.data["view_settings"]["theme"] = new_theme
            save_data(self.data)

    def compose(self) -> ComposeResult:
        with Horizontal(id="top-bar"):
            status = SystemStatus()
            status.border_title = " TASKS MANAGER "
            yield status

        yield DataTable(id="task-table", cursor_type="row")
        yield Footer()

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
            table.add_columns("PROJECT", "PRIORITY", "TASK", "STATUS", "NOTES")
        
        view = self.data["view_settings"]
        all_tasks = []
        
        for project, tasks in self.data.get("projects", {}).items():
            for idx, t in enumerate(tasks):
                all_tasks.append((project, idx, t))
                
        if view.get("filter_project"):
            all_tasks = [x for x in all_tasks if x[0] == view["filter_project"]]
        if view.get("filter_priority"):
            all_tasks = [x for x in all_tasks if x[2]["priority"] == view["filter_priority"]]
            
        # === NEW: Filter out DONE main tasks ===
        if self.hide_done:
            all_tasks = [x for x in all_tasks if x[2].get("status") != "DONE"]
            
        if view.get("sort_by", "priority") == "project":
            all_tasks.sort(key=lambda x: x[0])
        else:
            all_tasks.sort(key=lambda x: (x[2]["priority"], x[0]))

        for proj, idx, t in all_tasks:
            p_col = self.data["project_colors"].get(proj, "cyan")
            proj_str = f"[{p_col} bold]{proj}[/]"
            
            prio = t["priority"]
            if "HIGH" in prio: prio_str = f"[bold red]{prio}[/]"
            elif "MEDIUM" in prio: prio_str = f"[bold yellow]{prio}[/]"
            elif "LOW" in prio: prio_str = f"[cyan]{prio}[/]"
            else: prio_str = f"[white]{prio}[/]"

            stat = t["status"]
            if "DONE" in stat: stat_str = f"[bold green]{stat}[/]"
            elif "IN PROGRESS" in stat: stat_str = f"[bold cyan]{stat}[/]"
            elif "ON HOLD" in stat: stat_str = f"[bold red]{stat}[/]"
            else: stat_str = f"[white]{stat}[/]"

            row_key = f"{proj}::{idx}"
            sub_tasks = t.get("sub_tasks", [])
            
            # === NEW: Determine if there are visible sub-tasks ===
            if self.hide_done:
                visible_subs = [s for s in sub_tasks if s.get("status") != "DONE"]
            else:
                visible_subs = sub_tasks
            
            if visible_subs:
                indicator = "[bold cyan]▼[/] " if row_key in self.expanded_rows else "[bold white]▶[/] "
            else:
                indicator = "  "
                
            table.add_row(proj_str, prio_str, f"{indicator}{t['task']}", stat_str, t.get("notes", ""), key=row_key)
            
            if row_key in self.expanded_rows:
                for sub_idx, sub in enumerate(sub_tasks):
                    # === NEW: Filter out DONE sub-tasks ===
                    if self.hide_done and sub.get("status") == "DONE":
                        continue
                    
                    sub_key = f"{row_key}::sub::{sub_idx}"
                    sub_stat = sub.get("status", "TO DO")
                    
                    if "DONE" in sub_stat: sub_stat_str = f"[bold green]{sub_stat}[/]"
                    elif "IN PROGRESS" in sub_stat: sub_stat_str = f"[bold cyan]{sub_stat}[/]"
                    elif "ON HOLD" in sub_stat: sub_stat_str = f"[bold red]{sub_stat}[/]"
                    else: sub_stat_str = f"[white]{sub_stat}[/]"
                    
                    table.add_row("", "", f"    [gray]↳[/] {sub['task']}", sub_stat_str, sub.get("notes", ""), key=sub_key)

        if cursor_key:
            try:
                row_idx = table.get_row_index(cursor_key)
                table.move_cursor(row=row_idx)
            except Exception:
                pass

    @on(DataTable.RowSelected)
    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        row_key = str(event.row_key.value)
        if "::sub::" in row_key:
            return
            
        if row_key in self.expanded_rows:
            self.expanded_rows.remove(row_key)
        else:
            self.expanded_rows.add(row_key)
            
        self.populate_table()

    def get_selected_task(self):
        table = self.query_one(DataTable)
        if not table.row_count: 
            return None
            
        row_key_value = table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value
        if not row_key_value:
            return None
            
        parts = str(row_key_value).split("::")
        if len(parts) == 2:
            return parts[0], int(parts[1]), None 
        elif len(parts) == 4 and parts[2] == "sub":
            return parts[0], int(parts[1]), int(parts[3])
            
        return None
    

    # --- ACTIONS ---
    def action_manage_projects(self) -> None:
        projects = list(self.data["projects"].keys())
        self.push_screen(ProjectManagerScreen(projects), self.handle_project_manage)

    def handle_project_manage(self, result: dict | None) -> None:
        if not result: return
        
        name = result["name"]
        if result["action"] == "add":
            if name in self.data["projects"]:
                self.notify("DESIGNATION ALREADY EXISTS.", severity="error")
                return
            self.data["projects"][name] = []
            self.data["project_colors"][name] = result["color"]
            self.notify(f"PROJECT '{name}' INITIALIZED.", severity="information")

        elif result["action"] == "edit":
            new_name = result["new_name"]
            new_color = result["new_color"]
            
            if new_color != Select.BLANK:
                self.data["project_colors"][name] = new_color
                
            if new_name and new_name != name:
                if new_name in self.data["projects"]:
                    self.notify("NEW DESIGNATION ALREADY EXISTS.", severity="error")
                    return
                self.data["projects"][new_name] = self.data["projects"].pop(name)
                self.data["project_colors"][new_name] = self.data["project_colors"].pop(name)
                
                if self.data["view_settings"]["filter_project"] == name:
                    self.data["view_settings"]["filter_project"] = new_name
                    
            self.notify(f"PROJECT '{name}' OVERRIDDEN.", severity="information")
            
        elif result["action"] == "delete":
            self.push_screen(ConfirmScreen(f"Purge {name} and ALL its tasks?"), lambda conf: self.finalize_project_purge(conf, name))
            return
            
        save_data(self.data)
        self.populate_table()

    def finalize_project_purge(self, confirm: bool | None, name: str) -> None:
        if confirm:
            del self.data["projects"][name]
            self.data["project_colors"].pop(name, None)
            
            if self.data["view_settings"]["filter_project"] == name:
                self.data["view_settings"]["filter_project"] = None
                
            save_data(self.data)
            self.populate_table()
            self.notify(f"PROJECT '{name}' PURGED.", severity="warning")

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
            
        proj, idx, sub_idx = selected
        if sub_idx is not None:
            self.notify("CANNOT NEST SUB-TASKS. Select a main parent task instead.", severity="error")
            return
            
        projects = list(self.data["projects"].keys())
        self.push_screen(TaskFormScreen(projects, parent_proj=proj, edit_idx=idx, is_subtask=True), self.handle_task_save)

    def action_edit_task(self) -> None:
        selected = self.get_selected_task()
        if not selected:
            self.notify("NO TASK SELECTED.", severity="warning")
            return
            
        proj, idx, sub_idx = selected
        projects = list(self.data["projects"].keys())
        
        if sub_idx is not None:
            task_data = self.data["projects"][proj][idx].get("sub_tasks", [])[sub_idx]
            self.push_screen(TaskFormScreen(projects, edit_proj=proj, edit_idx=idx, edit_sub_idx=sub_idx, task_data=task_data, is_subtask=True), self.handle_task_save)
        else:
            task_data = self.data["projects"][proj][idx]
            self.push_screen(TaskFormScreen(projects, edit_proj=proj, edit_idx=idx, task_data=task_data), self.handle_task_save)

    def handle_task_save(self, result: dict | None) -> None:
        if not result: return
        
        proj = result.pop("project")
        idx = result.pop("edit_idx")
        sub_idx = result.pop("edit_sub_idx")
        is_subtask = result.pop("is_subtask")
        
        if is_subtask:
            if "sub_tasks" not in self.data["projects"][proj][idx]:
                self.data["projects"][proj][idx]["sub_tasks"] = []
                
            if sub_idx is not None:
                self.data["projects"][proj][idx]["sub_tasks"][sub_idx] = result
                self.notify("SUB-TASK OVERRIDE SUCCESSFUL.", severity="information")
            else:
                self.data["projects"][proj][idx]["sub_tasks"].append(result)
                self.expanded_rows.add(f"{proj}::{idx}")
                self.notify("SUB-TASK UPLOADED.", severity="information")
        else:
            if idx is not None:
                existing_subs = self.data["projects"][proj][idx].get("sub_tasks", [])
                result["sub_tasks"] = existing_subs
                self.data["projects"][proj][idx] = result
                self.notify("TASK OVERRIDE SUCCESSFUL.", severity="information")
            else:
                result["sub_tasks"] = []
                self.data["projects"][proj].append(result)
                self.notify("TASK UPLOADED TO MAINFRAME.", severity="information")
            
        save_data(self.data)
        self.populate_table()

    def action_delete_task(self) -> None:
        selected = self.get_selected_task()
        if not selected: return
        
        proj, idx, sub_idx = selected
        msg = "Permanently delete this sub-task?" if sub_idx is not None else "Permanently delete this task and ALL its sub-tasks?"
        self.push_screen(ConfirmScreen(msg), lambda conf: self.finalize_delete_task(conf, proj, idx, sub_idx))

    def finalize_delete_task(self, confirm: bool | None, proj: str, idx: int, sub_idx: int | None) -> None:
        if confirm:
            if sub_idx is not None:
                del self.data["projects"][proj][idx]["sub_tasks"][sub_idx]
                self.notify("SUB-TASK PURGED.", severity="warning")
            else:
                del self.data["projects"][proj][idx]
                self.notify("TASK PURGED.", severity="warning")
                
            save_data(self.data)
            self.populate_table()

    def action_view_filter(self) -> None:
        projects = list(self.data["projects"].keys())
        self.push_screen(ViewFilterScreen(projects, self.data["view_settings"]), self.handle_view_filter)

    def handle_view_filter(self, result: dict | None) -> None:
        if result:
            self.data["view_settings"] = result
            save_data(self.data)
            self.populate_table()
            self.notify("VIEW PARAMETERS UPDATED.", severity="information")


if __name__ == "__main__":
    app = TaskManagerApp()
    app.run()
