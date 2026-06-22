from __future__ import annotations

_client = None


def get_client():
    global _client
    if _client is None:
        from supabase import create_client
        from config import load_config
        cfg = load_config()
        _client = create_client(cfg["supabase_url"], cfg["supabase_key"])
    return _client


# ---------------------------------------------------------------------------
# VIEW SETTINGS  (persisted locally, not in Supabase)
# ---------------------------------------------------------------------------

def db_save_view_settings(vs: dict) -> None:
    from config import save_view_settings
    save_view_settings(vs)


# ---------------------------------------------------------------------------
# READ
# ---------------------------------------------------------------------------

def db_load_data() -> dict:
    from config import load_config
    sb = get_client()

    proj_rows = sb.table("projects").select("name, color").order("name").execute().data or []
    project_colors = {r["name"]: r["color"] for r in proj_rows}
    projects: dict[str, list] = {r["name"]: [] for r in proj_rows}

    task_rows = (
        sb.table("tasks")
        .select("*")
        .order("project")
        .order("sort_order")
        .order("id")
        .execute()
        .data or []
    )
    task_ids = [t["id"] for t in task_rows]

    sub_map: dict[int, list] = {tid: [] for tid in task_ids}
    if task_ids:
        sub_rows = (
            sb.table("sub_tasks")
            .select("*")
            .in_("task_id", task_ids)
            .order("sort_order")
            .order("id")
            .execute()
            .data or []
        )
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
            "assigned_to": t.get("assigned_to"),
            "sub_tasks": sub_map[t["id"]],
            "_id": t["id"],
        })

    cfg = load_config()
    vs = cfg.get("view_settings", {})
    view_settings = {
        "sort_by": vs.get("sort_by", "priority"),
        "filter_project": vs.get("filter_project"),
        "filter_priority": vs.get("filter_priority"),
        "theme": vs.get("theme", "textual-dark"),
        "hide_done": vs.get("hide_done", False),
        "border_color": vs.get("border_color", "#00FF00"),
        "bg_color": vs.get("bg_color", ""),
    }

    return {
        "projects": projects,
        "project_colors": project_colors,
        "view_settings": view_settings,
    }


def db_get_task(task_id: int) -> dict | None:
    result = get_client().table("tasks").select("*").eq("id", task_id).execute()
    return result.data[0] if result.data else None


def db_get_subtask(sub_id: int) -> dict | None:
    result = get_client().table("sub_tasks").select("*").eq("id", sub_id).execute()
    return result.data[0] if result.data else None


def db_get_subtask_parent(sub_id: int) -> int | None:
    result = get_client().table("sub_tasks").select("task_id").eq("id", sub_id).execute()
    return result.data[0]["task_id"] if result.data else None


# ---------------------------------------------------------------------------
# USERS
# ---------------------------------------------------------------------------

def db_get_users() -> list[str]:
    result = get_client().table("users").select("username").order("username").execute()
    return [r["username"] for r in (result.data or [])]


def db_ensure_user(username: str, display_name: str) -> None:
    sb = get_client()
    existing = sb.table("users").select("username").eq("username", username).execute()
    if not existing.data:
        sb.table("users").insert({"username": username, "display_name": display_name}).execute()


# ---------------------------------------------------------------------------
# PROJECTS
# ---------------------------------------------------------------------------

def db_add_project(name: str, color: str) -> bool:
    try:
        get_client().table("projects").insert({"name": name, "color": color}).execute()
        return True
    except Exception:
        return False


def db_edit_project(old_name: str, new_name: str | None, new_color: str | None) -> bool:
    try:
        sb = get_client()
        if new_color:
            sb.table("projects").update({"color": new_color}).eq("name", old_name).execute()
        if new_name and new_name != old_name:
            sb.table("projects").update({"name": new_name}).eq("name", old_name).execute()
        return True
    except Exception:
        return False


def db_delete_project(name: str) -> None:
    get_client().table("projects").delete().eq("name", name).execute()


def db_get_project_for_task(task_id: int) -> str | None:
    result = get_client().table("tasks").select("project").eq("id", task_id).execute()
    return result.data[0]["project"] if result.data else None


# ---------------------------------------------------------------------------
# TASKS
# ---------------------------------------------------------------------------

def db_add_task(
    project: str, task: str, priority: str, status: str,
    notes: str | None, assigned_to: str | None = None,
) -> int:
    sb = get_client()
    max_result = (
        sb.table("tasks")
        .select("sort_order")
        .eq("project", project)
        .order("sort_order", desc=True)
        .limit(1)
        .execute()
    )
    max_order = max_result.data[0]["sort_order"] if max_result.data else 0
    result = sb.table("tasks").insert({
        "project": project,
        "task": task,
        "priority": priority,
        "status": status,
        "notes": notes,
        "sort_order": max_order + 1,
        "assigned_to": assigned_to,
    }).execute()
    return result.data[0]["id"] if result.data else 0


def db_update_task(
    task_id: int, task: str, priority: str, status: str,
    notes: str | None, assigned_to: str | None = None,
) -> None:
    get_client().table("tasks").update({
        "task": task,
        "priority": priority,
        "status": status,
        "notes": notes,
        "assigned_to": assigned_to,
    }).eq("id", task_id).execute()


def db_delete_task(task_id: int) -> None:
    get_client().table("tasks").delete().eq("id", task_id).execute()


# ---------------------------------------------------------------------------
# SUB-TASKS
# ---------------------------------------------------------------------------

def db_add_subtask(task_id: int, task: str, status: str, notes: str | None) -> int:
    sb = get_client()
    max_result = (
        sb.table("sub_tasks")
        .select("sort_order")
        .eq("task_id", task_id)
        .order("sort_order", desc=True)
        .limit(1)
        .execute()
    )
    max_order = max_result.data[0]["sort_order"] if max_result.data else 0
    result = sb.table("sub_tasks").insert({
        "task_id": task_id,
        "task": task,
        "status": status,
        "notes": notes,
        "sort_order": max_order + 1,
    }).execute()
    return result.data[0]["id"] if result.data else 0


def db_update_subtask(sub_id: int, task: str, status: str, notes: str | None) -> None:
    get_client().table("sub_tasks").update({
        "task": task, "status": status, "notes": notes,
    }).eq("id", sub_id).execute()


def db_delete_subtask(sub_id: int) -> None:
    get_client().table("sub_tasks").delete().eq("id", sub_id).execute()


# ---------------------------------------------------------------------------
# PROJECT LOGS
# ---------------------------------------------------------------------------

def db_get_project_logs(project: str) -> list[dict]:
    result = (
        get_client()
        .table("project_logs")
        .select("id, log_date, title, notes")
        .eq("project", project)
        .order("log_date", desc=True)
        .order("id", desc=True)
        .execute()
    )
    return result.data or []


def db_get_log_by_id(log_id: int) -> dict | None:
    result = (
        get_client()
        .table("project_logs")
        .select("id, log_date, title, notes")
        .eq("id", log_id)
        .execute()
    )
    return result.data[0] if result.data else None


def db_add_project_log(project: str, log_date: str, title: str, notes: str) -> None:
    get_client().table("project_logs").insert({
        "project": project, "log_date": log_date, "title": title, "notes": notes,
    }).execute()


def db_update_project_log(log_id: int, log_date: str, title: str, notes: str) -> None:
    get_client().table("project_logs").update({
        "log_date": log_date, "title": title, "notes": notes,
    }).eq("id", log_id).execute()


def db_delete_project_log(log_id: int) -> None:
    get_client().table("project_logs").delete().eq("id", log_id).execute()
