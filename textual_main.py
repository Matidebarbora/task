import json
import os
import ssl
import urllib.request
from datetime import datetime

from textual import work
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
            "view_settings": {"sort_by": "priority", "filter_project": None, "filter_priority": None, "theme": "textual-dark"}
        }
    with open(DATA_FILE, "r") as file:
        return json.load(file)

def save_data(data):
    with open(DATA_FILE, "w") as file:
        json.dump(data, file, indent=4)

# --- UI COMPONENTS ---
class SystemStatus(Static):
    time_str = reactive("")
    weather_str = reactive("--")

    def on_mount(self) -> None:
        self.update_time()
        self.set_interval(1, self.update_time)
        self.fetch_weather()
        self.set_interval(300, self.fetch_weather)

    def update_time(self) -> None:
        self.time_str = datetime.now().strftime("%H:%M:%S")
        self.render_status()

    @work(thread=True)
    def fetch_weather(self) -> None:
        try:
            url = "https://api.open-meteo.com/v1/forecast?latitude=-33.3667&longitude=-70.7333&current_weather=true"
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            
            # Bypass strict SSL validation which often causes urllib to fail silently
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
        content = f"[bold cyan]TIME:[/bold cyan] {self.time_str}  |  [bold yellow]TEMP:[/bold yellow] {self.weather_str}°C [white](Quilicura)[/white]"
        self.update(content)

class DashboardPanel(Static):
    def on_mount(self) -> None:
        self.update_dashboard()

    def update_dashboard(self) -> None:
        # Use getattr to safely fetch 'data' and bypass Pylance's strict type checking
        app_data = getattr(self.app, "data", None)
        if not app_data: 
            return
            
        total_tasks = 0
        completed = 0
        high_prio = 0
        
        for tasks in app_data.get("projects", {}).values():
            total_tasks += len(tasks)
            for t in tasks:
                if t.get("status") == "DONE": completed += 1
                if "HIGH" in t.get("priority", ""): high_prio += 1
                
        content = (
            f"[bold cyan]TASKS_MANAGER[/bold cyan] v1.1\n\n"
            f"[bold white]Total Tasks:[/bold white] {total_tasks}  |  "
            f"[bold green]Completed:[/bold green] {completed}  |  "
            f"[bold red]High Priority:[/bold red] {high_prio}"
        )
        self.update(content)


# --- MODAL SCREENS ---
class ConfirmScreen(ModalScreen[bool]):
    """Generic confirmation dialog."""
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
    """Handles both Adding and Editing tasks."""
    def __init__(self, projects: list, edit_proj=None, edit_idx=None, task_data=None) -> None:
        super().__init__()
        self.projects = projects
        self.edit_proj = edit_proj
        self.edit_idx = edit_idx
        self.task_data = task_data or {}

    def compose(self) -> ComposeResult:
        proj_options = [(p, p) for p in self.projects]
        prio_options = [("1. HIGH", "1. HIGH"), ("2. MEDIUM", "2. MEDIUM"), ("3. LOW", "3. LOW"), ("4. ----", "4. ----")]
        stat_options = [("TO DO", "TO DO"), ("IN PROGRESS", "IN PROGRESS"), ("ON HOLD", "ON HOLD"), ("DONE", "DONE")]
        
        is_edit = self.edit_proj is not None
        title = "[bold yellow]EDITING TASK OVERRIDE[/]" if is_edit else "[bold green]INITIALIZING NEW TASK SEQUENCE...[/]"
        
        with Vertical(id="dialog"):
            yield Label(title, id="dialog-title")
            
            yield Label("Project Designation:")
            sel_proj = Select(proj_options, id="select-project", value=self.edit_proj if is_edit else Select.BLANK)
            sel_proj.disabled = is_edit # Don't allow changing project during edit for simplicity
            yield sel_proj
            
            yield Label("Task Description:")
            yield Input(value=self.task_data.get("task", ""), placeholder="Enter task...", id="input-desc")
            
            yield Label("Priority:")
            yield Select(prio_options, id="select-priority", value=self.task_data.get("priority", "2. MEDIUM"))
            
            yield Label("Status:")
            yield Select(stat_options, id="select-status", value=self.task_data.get("status", "TO DO"))
            
            yield Label("Notes (Optional):")
            yield Input(value=self.task_data.get("notes", ""), placeholder="Enter notes...", id="input-notes")
            
            with Horizontal(id="dialog-buttons"):
                yield Button("SAVE TASK", variant="success", id="btn-submit")
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
                "edit_idx": self.edit_idx
            }
            self.dismiss(result)
        elif event.button.id == "btn-cancel":
            self.dismiss(None)


class ViewFilterScreen(ModalScreen[dict]):
    """Configures sorting and filtering."""
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
    def __init__(self, projects: list):
        super().__init__()
        self.projects = projects

    def compose(self) -> ComposeResult:
        color_opts = [(c.upper(), c) for c in ["cyan", "magenta", "green", "yellow", "red", "blue", "white", "orange", "violet"]]
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
    #top-bar { height: 7; margin-bottom: 1; }
    DashboardPanel { width: 60%; height: 100%; border: round #00ff00; border-title-color: #00ff00; content-align: center middle; }
    SystemStatus { width: 40%; height: 100%; border: round #00ff00; border-title-color: #00ff00; content-align: center middle; }
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
        ("e", "edit_task", "Edit Task"),
        ("d", "delete_task", "Delete Task"),
        ("v", "view_filter", "View/Filter"),
        ("q", "app.quit", "Quit"),
    ]

    def on_mount(self) -> None:
        self.title = "TASKS_MANAGER"
        self.data = load_data()
        
        # Load saved theme on boot
        if "theme" in self.data.get("view_settings", {}):
            self.theme = self.data["view_settings"]["theme"]
            
        self.populate_table()

    def watch_theme(self, new_theme: str) -> None:
        """Automatically saves palette/theme modifications persistently."""
        if hasattr(self, "data") and "view_settings" in self.data:
            self.data["view_settings"]["theme"] = new_theme
            save_data(self.data)

    def compose(self) -> ComposeResult:
        with Horizontal(id="top-bar"):
            dashboard = DashboardPanel()
            dashboard.border_title = "DASHBOARD"
            yield dashboard
            
            status = SystemStatus()
            status.border_title = "SYS_STATUS"
            yield status

        yield DataTable(id="task-table", cursor_type="row")
        yield Footer()

    def populate_table(self) -> None:
        table = self.query_one(DataTable)
        table.clear(columns=True)
        table.add_columns("PROJECT", "PRIORITY", "TASK", "STATUS", "NOTES")
        
        view = self.data["view_settings"]
        all_tasks = []
        
        for project, tasks in self.data.get("projects", {}).items():
            for idx, t in enumerate(tasks):
                all_tasks.append((project, idx, t))
                
        if view["filter_project"]:
            all_tasks = [x for x in all_tasks if x[0] == view["filter_project"]]
        if view["filter_priority"]:
            all_tasks = [x for x in all_tasks if x[2]["priority"] == view["filter_priority"]]
            
        if view["sort_by"] == "project":
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
            table.add_row(proj_str, prio_str, t["task"], stat_str, t.get("notes", ""), key=row_key)
            
        # Keep Dashboard in sync
        try:
            self.query_one(DashboardPanel).update_dashboard()
        except Exception:
            pass

    def get_selected_task(self):
        table = self.query_one(DataTable)
        if not table.row_count: 
            return None
            
        row_key_value = table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value
        
        if not row_key_value:
            return None
            
        proj, idx = str(row_key_value).split("::")
        return proj, int(idx)

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
                # Migrate tasks and colors
                self.data["projects"][new_name] = self.data["projects"].pop(name)
                self.data["project_colors"][new_name] = self.data["project_colors"].pop(name)
                
                # Fix filters if this project was selected
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

    def action_edit_task(self) -> None:
        selected = self.get_selected_task()
        if not selected:
            self.notify("NO TASK SELECTED.", severity="warning")
            return
            
        proj, idx = selected
        task_data = self.data["projects"][proj][idx]
        projects = list(self.data["projects"].keys())
        
        self.push_screen(TaskFormScreen(projects, edit_proj=proj, edit_idx=idx, task_data=task_data), self.handle_task_save)

    def handle_task_save(self, result: dict | None) -> None:
        if not result: return
        
        proj = result.pop("project")
        idx = result.pop("edit_idx")
        
        if idx is not None:
            self.data["projects"][proj][idx] = result
            self.notify("TASK OVERRIDE SUCCESSFUL.", severity="information")
        else:
            self.data["projects"][proj].append(result)
            self.notify("TASK UPLOADED TO MAINFRAME.", severity="information")
            
        save_data(self.data)
        self.populate_table()

    def action_delete_task(self) -> None:
        selected = self.get_selected_task()
        if not selected: return
        
        self.push_screen(ConfirmScreen("Permanently delete this task?"), lambda conf: self.finalize_delete_task(conf, selected[0], selected[1]))

    def finalize_delete_task(self, confirm: bool | None, proj: str, idx: int) -> None:
        if confirm:
            del self.data["projects"][proj][idx]
            save_data(self.data)
            self.populate_table()
            self.notify("TASK PURGED.", severity="warning")

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
