import json
import os
import sys
import urllib.request
import time
from datetime import datetime
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.prompt import Prompt
from rich.columns import Columns

# --- SYSTEM INITIALIZATION ---
console = Console()
DATA_FILE = "tasks.json"
WEATHER_CACHE = {"temp": None, "last_fetch": 0}

# --- DATA HANDLING ---
def load_data():
    if not os.path.exists(DATA_FILE):
        return {
            "projects": {}, 
            "project_colors": {},
            "view_settings": {
                "sort_by": "priority", 
                "filter_project": None, 
                "filter_priority": None
            }
        }
    with open(DATA_FILE, "r") as file:
        data = json.load(file)
        if "project_colors" not in data:
            data["project_colors"] = {}
            for proj in data.get("projects", {}):
                data["project_colors"][proj] = "cyan" 
        if "view_settings" not in data:
            data["view_settings"] = {
                "sort_by": "priority",
                "filter_project": None,
                "filter_priority": None
            }
        return data

def save_data(data):
    with open(DATA_FILE, "w") as file:
        json.dump(data, file, indent=4)

# --- UI HELPERS ---
def pause():
    console.print("\n[white]Press ENTER to continue...[/white]")
    input()

def get_system_status():
    global WEATHER_CACHE
    now_ts = time.time()
    
    # Fetch API every 300 seconds (5 mins) to prevent UI lag and API limits
    if WEATHER_CACHE["temp"] is None or (now_ts - WEATHER_CACHE["last_fetch"] > 300):
        try:
            url = "https://api.open-meteo.com/v1/forecast?latitude=-33.3667&longitude=-70.7333&current_weather=true"
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=2) as response:
                api_data = json.loads(response.read().decode())
                WEATHER_CACHE["temp"] = api_data["current_weather"]["temperature"]
                WEATHER_CACHE["last_fetch"] = now_ts
        except Exception:
            if WEATHER_CACHE["temp"] is None:
                WEATHER_CACHE["temp"] = "--"
                
    now_str = datetime.now().strftime("%H:%M:%S")
    temp = WEATHER_CACHE["temp"]
    return f"[bold cyan]TIME:[/bold cyan] {now_str}  |  [bold yellow]TEMP:[/bold yellow] {temp}°C [white](Quilicura)[/white]"

def cyber_ask(prompt_text, choices=None, default=None, allow_back=True) -> str:
    actual_choices = None
    if choices is not None:
        actual_choices = [str(c) for c in choices]
        if allow_back:
            actual_choices.extend(["b", "B"])
        actual_choices.extend(["q", "Q"])
        
    val = str(Prompt.ask(prompt_text, choices=actual_choices, default=default, show_choices=False))
    
    if val.strip().lower() == "q":
        console.clear()
        console.print(Panel("[bold red]DISCONNECTING FROM MAINFRAME... GOODBYE.[/bold red]", border_style="red", expand=False))
        sys.exit(0)
        
    if allow_back and val.strip().lower() == "b":
        return "b"
        
    return val

def select_project_then_task(data, action_name):
    project_list = list(data["projects"].keys())
    if not project_list:
        return None, None

    console.print()
    proj_str = "\n".join([f" [[bold white]{i+1}[/bold white]] [green]{p}[/green]" for i, p in enumerate(project_list)])
    console.print(Panel(proj_str, title="[bold green]SELECT PROJECT[/bold green]", border_style="green", expand=False))
    
    valid_proj_choices = [str(i) for i in range(1, len(project_list) + 1)]
    proj_idx = cyber_ask(f"[bold green]╰─> Select PROJECT number to {action_name}[/bold green]", choices=valid_proj_choices)
    if proj_idx == "b": return None, None
    selected_proj = project_list[int(proj_idx) - 1]

    tasks = data["projects"][selected_proj]
    if not tasks:
        console.print(f"\n[bold red]>> NO TASKS FOUND IN PROJECT '{selected_proj}'.[/bold red]")
        pause()
        return None, None

    console.print(f"\n[white]-- TASKS FOR {selected_proj} --[/white]")
    for i, t in enumerate(tasks):
        console.print(f" [[bold white]{i+1}[/bold white]] {t['task']}")
    
    valid_task_choices = [str(i) for i in range(1, len(tasks) + 1)]
    task_idx = cyber_ask(f"\n[bold green]╰─> Select TASK number to {action_name}[/bold green]", choices=valid_task_choices)
    if task_idx == "b": return None, None
    
    return selected_proj, int(task_idx) - 1

# --- VIEW AND FILTER MANAGEMENT ---
def manage_view(data):
    view_settings = data["view_settings"]
    while True:
        console.clear()
        console.rule("[bold green]VIEW_AND_FILTER_CONFIGURATION[/bold green]")
        
        sort_state = view_settings["sort_by"].upper()
        proj_filt = view_settings["filter_project"] or "NONE"
        prio_filt = view_settings["filter_priority"] or "NONE"
        
        state_text = f"Sort By: [bold white]{sort_state}[/bold white] | Project Filter: [bold white]{proj_filt}[/bold white] | Priority Filter: [bold white]{prio_filt}[/bold white]"
        console.print(Panel(state_text, title="[bold green]CURRENT DASHBOARD SETTINGS[/bold green]", border_style="green", expand=False))
        
        menu_text = (
            "[1] Sort by PROJECT\n"
            "[2] Sort by PRIORITY\n"
            "[3] Set Filter by PROJECT\n"
            "[4] Set Filter by PRIORITY\n"
            "[5] CLEAR all filters\n"
            "[B] Back to Dashboard"
        )
        console.print(Panel(menu_text, border_style="green", expand=False))
        
        choice = cyber_ask("[bold green]╰─> Execute command[/bold green]", choices=["1", "2", "3", "4", "5"])
        
        if choice == "b":
            break
        elif choice == "1":
            view_settings["sort_by"] = "project"
            save_data(data)
        elif choice == "2":
            view_settings["sort_by"] = "priority"
            save_data(data)
        elif choice == "3":
            project_list = list(data["projects"].keys())
            if not project_list:
                continue
            proj_str = "\n".join([f" [[bold white]{i+1}[/bold white]] [green]{p}[/green]" for i, p in enumerate(project_list)])
            console.print(Panel(proj_str, title="[bold green]SELECT PROJECT TO FILTER[/bold green]", border_style="green", expand=False))
            valid_choices = [str(i) for i in range(1, len(project_list) + 1)]
            proj_idx = cyber_ask("[bold green]╰─> Select project NUMBER[/bold green]", choices=valid_choices)
            if proj_idx != "b":
                view_settings["filter_project"] = project_list[int(proj_idx) - 1]
                save_data(data)
        elif choice == "4":
            console.print("\n[white]Priorities: [1] HIGH | [2] MEDIUM | [3] LOW | [4] ----[/white]")
            p_choice = cyber_ask("[bold green]╰─> Select PRIORITY to filter[/bold green]", choices=["1", "2", "3", "4"])
            if p_choice != "b":
                pmap = {"1": "1. HIGH", "2": "2. MEDIUM", "3": "3. LOW", "4": "4. ----"}
                view_settings["filter_priority"] = pmap[p_choice]
                save_data(data)
        elif choice == "5":
            view_settings["filter_project"] = None
            view_settings["filter_priority"] = None
            save_data(data)

# --- PROJECT MANAGEMENT ---
def manage_projects(data):
    while True:
        console.clear()
        console.rule("[bold green]PROJECT_MANAGEMENT_OVERRIDE[/bold green]")
        
        options_text = "[bold white][1][/bold white] Add Project  |  [bold white][2][/bold white] Edit Project  |  [bold white][3][/bold white] Purge Project  |  [bold white][B][/bold white] Back to Dashboard"
        console.print(Panel(options_text, title="[bold green]OPTIONS[/bold green]", title_align="left", border_style="green", expand=False))
        console.print()
        
        if not data["projects"]:
            console.print(Panel("[bold red]>> NO PROJECTS DETECTED IN THE MAINFRAME.[/bold red]", border_style="red", expand=False))
        else:
            table = Table(border_style="green", header_style="bold white")
            table.add_column("PROJECT NAME")
            table.add_column("ACTIVE TASKS", justify="center")
            for proj, tasks in data["projects"].items():
                p_col = data["project_colors"].get(proj, "cyan")
                table.add_row(f"[bold {p_col}]{proj}[/bold {p_col}]", str(len(tasks)))
            console.print(table)
        
        console.print()
        choice = cyber_ask("[bold green]╰─> Execute command[/bold green]", choices=["1", "2", "3"])
        
        if choice == "b":
            break
                
        elif choice == "1":
            console.clear()
            console.print(Panel("[bold green]INITIALIZING NEW PROJECT...[/bold green]", border_style="green", expand=False))
            new_proj = cyber_ask("[bold green]╰─> Enter NEW PROJECT Designation[/bold green]")
            if new_proj == "b": continue
            new_proj = new_proj.upper().strip()
            
            if not new_proj:
                console.print("\n[bold red]>> INVALID INPUT.[/bold red]")
            elif new_proj in data["projects"]:
                console.print("\n[bold red]>> PROJECT DESIGNATION ALREADY EXISTS.[/bold red]")
            else:
                console.print("\n[white]Available Colors: [1] Cyan | [2] Magenta | [3] Green | [4] Yellow | [5] Red | [6] Blue | [7] White | [8] Orange | [9] Violet[/white]")
                color_map = {"1": "cyan", "2": "magenta", "3": "green", "4": "yellow", "5": "red", "6": "blue", "7": "white", "8": "orange", "9": "violet"}
                c_choice = cyber_ask("[bold green]╰─> Select LABEL COLOR[/bold green]", choices=["1", "2", "3", "4", "5", "6", "7", "8", "9"], default="1")
                if c_choice == "b": continue
                
                data["projects"][new_proj] = []
                data["project_colors"][new_proj] = color_map[c_choice]
                save_data(data)
                console.print(f"\n[bold green]>> PROJECT '{new_proj}' SUCCESSFULLY INITIALIZED.[/bold green]")
            pause()
                
        elif choice == "2":
            console.clear()
            if not data["projects"]:
                console.print(Panel("[bold red]>> NO PROJECTS AVAILABLE TO EDIT.[/bold red]", border_style="red"))
                pause()
                continue
                
            project_list = list(data["projects"].keys())
            proj_str = "\n".join([f" [[bold white]{i+1}[/bold white]] [green]{p}[/green]" for i, p in enumerate(project_list)])
            console.print(Panel(proj_str, title="[bold green]AVAILABLE PROJECTS[/bold green]", border_style="green", expand=False))
            
            valid_choices = [str(i) for i in range(1, len(project_list) + 1)]
            proj_idx = cyber_ask("[bold green]╰─> Select project NUMBER to EDIT[/bold green]", choices=valid_choices)
            if proj_idx == "b": continue
            proj_to_edit = project_list[int(proj_idx) - 1]
            
            new_name = cyber_ask(f"[bold green]╰─> Enter NEW DESIGNATION (Press Enter to keep '{proj_to_edit}')[/bold green]", default="")
            if new_name == "b": continue
            new_name = new_name.upper().strip()
            final_name = new_name if new_name else proj_to_edit
            
            if final_name != proj_to_edit and final_name in data["projects"]:
                console.print("\n[bold red]>> DESIGNATION ALREADY IN USE.[/bold red]")
                pause()
                continue
                
            current_color = data["project_colors"].get(proj_to_edit, "cyan")
            reverse_cmap = {"cyan": "1", "magenta": "2", "green": "3", "yellow": "4", "red": "5", "blue": "6", "white": "7", "orange": "8", "violet": "9"}
            def_c = reverse_cmap.get(current_color, "1")
            
            console.print("\n[white]Available Colors: [1] Cyan | [2] Magenta | [3] Green | [4] Yellow | [5] Red | [6] Blue | [7] White | [8] Orange | [9] Violet[/white]")
            color_map = {"1": "cyan", "2": "magenta", "3": "green", "4": "yellow", "5": "red", "6": "blue", "7": "white", "8": "orange", "9": "violet"}
            c_choice = cyber_ask(f"[bold green]╰─> Select NEW LABEL COLOR[/bold green]", choices=["1", "2", "3", "4", "5", "6", "7", "8", "9"], default=def_c)
            if c_choice == "b": continue
            final_color = color_map[c_choice]
            
            if final_name != proj_to_edit:
                data["projects"][final_name] = data["projects"].pop(proj_to_edit)
                data["project_colors"].pop(proj_to_edit, None)
                
            data["project_colors"][final_name] = final_color
            save_data(data)
            console.print(f"\n[bold green]>> PROJECT '{final_name}' OVERRIDE SUCCESSFUL.[/bold green]")
            pause()
                
        elif choice == "3":
            console.clear()
            if not data["projects"]:
                console.print(Panel("[bold red]>> NO PROJECTS AVAILABLE TO PURGE.[/bold red]", border_style="red"))
                pause()
                continue
                
            project_list = list(data["projects"].keys())
            proj_str = "\n".join([f" [[bold white]{i+1}[/bold white]] [green]{p}[/green]" for i, p in enumerate(project_list)])
            console.print(Panel(proj_str, title="[bold green]AVAILABLE PROJECTS[/bold green]", border_style="green", expand=False))
            
            valid_choices = [str(i) for i in range(1, len(project_list) + 1)]
            proj_idx = cyber_ask("[bold green]╰─> Select project NUMBER to PURGE[/bold green]", choices=valid_choices)
            if proj_idx == "b": continue
            proj_to_del = project_list[int(proj_idx) - 1]
            
            confirm = cyber_ask(f"\n[bold red]WARNING: Purge {proj_to_del} and ALL associated tasks? (y/n)[/bold red]", choices=["y", "n"])
            if confirm == "b": continue
            
            if confirm == "y":
                del data["projects"][proj_to_del]
                data["project_colors"].pop(proj_to_del, None)
                save_data(data)
                console.print(f"\n[bold green]>> PROJECT '{proj_to_del}' AND ALL TASKS DELETED FROM MAINFRAME.[/bold green]")
            pause()

# --- TASK INTERACTION FUNCTIONS ---
def draw_task_table(data):
    view_settings = data["view_settings"]
    all_tasks = []
    
    for project, tasks in data["projects"].items():
        for t in tasks:
            all_tasks.append((project, t))
            
    if not all_tasks:
        if not data["projects"]:
            console.print(Panel("[bold red]>> NO DATA FOUND IN THE MAINFRAME.[/bold red]", border_style="red", expand=False))
        else:
            console.print(Panel("[bold green]>> PROJECTS EXIST, BUT NO TASKS FOUND.[/bold green]", border_style="green", expand=False))
        return

    if view_settings["filter_project"]:
        all_tasks = [x for x in all_tasks if x[0] == view_settings["filter_project"]]
    if view_settings["filter_priority"]:
        all_tasks = [x for x in all_tasks if x[1]["priority"] == view_settings["filter_priority"]]
        
    if not all_tasks:
        console.print(Panel("[bold yellow]>> NO TASKS MATCH THE CURRENT FILTERS.[/bold yellow]", border_style="yellow", expand=False))
        return

    if view_settings["sort_by"] == "project":
        all_tasks.sort(key=lambda x: x[0])
    elif view_settings["sort_by"] == "priority":
        all_tasks.sort(key=lambda x: (x[1]["priority"], x[0]))

    table = Table(
        show_header=True,
        header_style="bold white",
        border_style="green"
    )
    
    table.add_column("PROJECT")
    table.add_column("PRIORITY")
    table.add_column("TASK")
    table.add_column("STATUS", justify="center")
    table.add_column("NOTES", style="white")

    for project, t in all_tasks:
        p_col = data.get("project_colors", {}).get(project, "cyan")
        
        priority = t["priority"]
        if "HIGH" in priority:
            priority_str = f"[bold red]{priority}[/bold red]"
        elif "MEDIUM" in priority:
            priority_str = f"[bold yellow]{priority}[/bold yellow]"
        elif "LOW" in priority:
            priority_str = f"[cyan]{priority}[/cyan]"
        else:
            priority_str = f"[white]{priority}[/white]"
            
        status = t["status"]
        if "DONE" in status:
            status_str = f"[bold green]{status}[/bold green]"
        elif "IN PROGRESS" in status:
            status_str = f"[bold cyan]{status}[/bold cyan]"
        elif "ON HOLD" in status:
            status_str = f"[bold red]{status}[/bold red]"
        else:
            status_str = f"[white]{status}[/white]"

        notes = t.get("notes")

        table.add_row(
            f"[bold {p_col}]{project}[/bold {p_col}]",
            priority_str,
            t["task"],
            status_str,
            notes if notes else ""
        )
            
    console.print(table)

def add_task(data):
    console.clear()
    if not data["projects"]:
        console.print(Panel("[bold red]>> ERROR: NO PROJECTS EXIST. PLEASE INITIALIZE A PROJECT FIRST.[/bold red]", border_style="red"))
        pause()
        return

    console.print(Panel("[bold green]INITIALIZING NEW TASK SEQUENCE...[/bold green]", border_style="green", expand=False))
    
    project_list = list(data["projects"].keys())
    proj_list_str = "\n".join([f" [[bold white]{i+1}[/bold white]] [green]{p}[/green]" for i, p in enumerate(project_list)])
    console.print(Panel(proj_list_str, title="[bold green]AVAILABLE PROJECTS[/bold green]", border_style="green", expand=False))
    
    valid_proj_choices = [str(i) for i in range(1, len(project_list) + 1)]
    proj_idx = cyber_ask("[bold green]╰─> Select PROJECT number[/bold green]", choices=valid_proj_choices)
    if proj_idx == "b": return
    project = project_list[int(proj_idx) - 1]
    
    console.print("\n[white]-- TASK PARAMETERS --[/white]")
    task_desc = cyber_ask("[bold green]╰─> Enter TASK Description[/bold green]")
    if task_desc == "b": return
    
    priority_map = {"1": "1. HIGH", "2": "2. MEDIUM", "3": "3. LOW", "4": "4. ----"}
    console.print("\n[white]Priorities: [1] HIGH | [2] MEDIUM | [3] LOW | [4] ----[/white]")
    p_choice = cyber_ask("[bold green]╰─> Select PRIORITY[/bold green]", choices=["1", "2", "3", "4"], default="2")
    if p_choice == "b": return
    priority = priority_map[p_choice]

    status_map = {"1": "TO DO", "2": "IN PROGRESS", "3": "ON HOLD", "4": "DONE"}
    console.print("\n[white]Statuses: [1] TO DO | [2] IN PROGRESS | [3] ON HOLD | [4] DONE[/white]")
    s_choice = cyber_ask("[bold green]╰─> Select STATUS[/bold green]", choices=["1", "2", "3", "4"], default="1")
    if s_choice == "b": return
    status = status_map[s_choice]
    
    if status == "DONE":
        priority = "4. ----"
    
    console.print()
    notes = cyber_ask("[bold green]╰─> Enter NOTES or press Enter to skip[/bold green]", default="")
    if notes == "b": return
    
    new_task = {
        "task": task_desc,
        "priority": priority,
        "status": status,
        "notes": notes if notes else None
    }
    
    data["projects"][project].append(new_task)
    save_data(data)
    console.print(f"\n[bold green]>> TASK SUCCESSFULLY UPLOADED TO MAINFRAME.[/bold green]")
    pause()

def edit_task_data(data, proj, idx):
    console.clear()
    target_task = data["projects"][proj][idx]
    
    console.print(Panel(f"[bold green]EDITING TASK OVERRIDE[/bold green]", border_style="green", expand=False))
    console.print("[white](Press ENTER to keep current value. Enter 'b' to cancel override)[/white]\n")
    
    new_desc = cyber_ask("[bold green]╰─> TASK Description[/bold green]", default=target_task['task'])
    if new_desc == "b": return
    
    priority_map = {"1": "1. HIGH", "2": "2. MEDIUM", "3": "3. LOW", "4": "4. ----"}
    reverse_p_map = {"1. HIGH": "1", "2. MEDIUM": "2", "3. LOW": "3", "4. ----": "4"}
    curr_p_num = reverse_p_map.get(target_task['priority'], "2")
    console.print("\n[white]Priorities: [1] HIGH | [2] MEDIUM | [3] LOW | [4] ----[/white]")
    p_choice = cyber_ask("[bold green]╰─> PRIORITY[/bold green]", choices=["1", "2", "3", "4"], default=curr_p_num)
    if p_choice == "b": return
    new_priority = priority_map[p_choice]

    status_map = {"1": "TO DO", "2": "IN PROGRESS", "3": "ON HOLD", "4": "DONE"}
    reverse_s_map = {"TO DO": "1", "IN PROGRESS": "2", "ON HOLD": "3", "DONE": "4"}
    curr_s_num = reverse_s_map.get(target_task['status'], "1")
    console.print("\n[white]Statuses: [1] TO DO | [2] IN PROGRESS | [3] ON HOLD | [4] DONE[/white]")
    s_choice = cyber_ask("[bold green]╰─> STATUS[/bold green]", choices=["1", "2", "3", "4"], default=curr_s_num)
    if s_choice == "b": return
    new_status = status_map[s_choice]
    
    if new_status == "DONE":
        new_priority = "4. ----"
    
    console.print()
    curr_notes = target_task.get('notes') or ""
    new_notes = cyber_ask("[bold green]╰─> NOTES[/bold green]", default=curr_notes)
    if new_notes == "b": return
    
    target_task["task"] = new_desc
    target_task["priority"] = new_priority
    target_task["status"] = new_status
    target_task["notes"] = new_notes if new_notes else None
    
    save_data(data)
    console.print(f"\n[bold green]>> TASK OVERRIDE SUCCESSFUL.[/bold green]")
    pause()

def delete_task_data(data, proj, idx):
    confirm = cyber_ask(f"\n[bold red]WARNING: Permanently delete this task? (y/n)[/bold red]", choices=["y", "n"])
    
    if confirm == "y":
        del data["projects"][proj][idx]
        save_data(data)
        console.print(f"\n[bold green]>> TASK PURGED FROM MAINFRAME.[/bold green]")
        pause()

# --- MAIN DASHBOARD ---
def main_menu():
    data = load_data()
    
    while True:
        console.clear()
        
        console.rule("[bold green]TASKS_MANAGER[/bold green]")
        
        options_text = "[bold white][1][/bold white] Manage Projects  |  [bold white][2][/bold white] Add Task  |  [bold white][E][/bold white] Edit Task  |  [bold white][D][/bold white] Delete Task  |  [bold white][V][/bold white] View/Filter  |  [bold white][Q][/bold white] Quit"
        options_panel = Panel(options_text, title="[bold green]OPTIONS[/bold green]", title_align="left", border_style="green", expand=False)
        
        status_text = get_system_status()
        status_panel = Panel(status_text, title="[bold green]SYS_STATUS[/bold green]", title_align="left", border_style="green", expand=False)
        
        # Render both panels side-by-side
        console.print(Columns([options_panel, status_panel]))
        console.print()
        
        draw_task_table(data)
        console.print()
        
        choice = cyber_ask("[bold green]╰─> Execute command[/bold green]", choices=["1", "2", "e", "E", "d", "D", "v", "V"], allow_back=False)
        
        if choice == "1":
            manage_projects(data)
        elif choice == "2":
            add_task(data)
        elif choice.lower() == "e":
            proj, idx = select_project_then_task(data, "EDIT")
            if proj:
                edit_task_data(data, proj, idx)
        elif choice.lower() == "d":
            proj, idx = select_project_then_task(data, "DELETE")
            if proj:
                delete_task_data(data, proj, idx)
        elif choice.lower() == "v":
            manage_view(data)

if __name__ == "__main__":
    main_menu()
