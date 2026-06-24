from __future__ import annotations

import threading

_client = None


def get_client():
    global _client
    if _client is None:
        from supabase import create_client
        from config import load_config
        cfg = load_config()
        _client = create_client(cfg["supabase_url"], cfg["supabase_key"])
    return _client


def _bg(fn, *args, **kwargs) -> None:
    threading.Thread(target=fn, args=args, kwargs=kwargs, daemon=True).start()


# ---------------------------------------------------------------------------
# STARTUP SYNC: Supabase → SQLite
# ---------------------------------------------------------------------------

def sync_from_supabase() -> bool:
    """Pull all Supabase data into local SQLite. Returns True if online."""
    try:
        from local_db import local_replace_all
        sb = get_client()
        projects    = sb.table("projects").select("name, color").execute().data or []
        users       = sb.table("users").select("username, display_name").execute().data or []
        tasks       = sb.table("tasks").select("*").execute().data or []
        sub_tasks   = sb.table("sub_tasks").select("*").execute().data or []
        proj_logs   = sb.table("project_logs").select("*").execute().data or []
        local_replace_all(projects, users, tasks, sub_tasks, proj_logs)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# VIEW SETTINGS  (persisted locally, not in Supabase)
# ---------------------------------------------------------------------------

def db_save_view_settings(vs: dict) -> None:
    from config import save_view_settings
    save_view_settings(vs)


# ---------------------------------------------------------------------------
# READ (from SQLite)
# ---------------------------------------------------------------------------

def db_load_data() -> dict:
    from local_db import local_load_data
    from config import load_config
    data = local_load_data()
    cfg = load_config()
    vs = cfg.get("view_settings", {})
    data["view_settings"] = {
        "sort_by":          vs.get("sort_by", "priority"),
        "filter_project":   vs.get("filter_project"),
        "filter_priority":  vs.get("filter_priority"),
        "theme":            vs.get("theme", "textual-dark"),
        "hide_done":        vs.get("hide_done", False),
        "border_color":     vs.get("border_color", "#00FF00"),
        "bg_color":         vs.get("bg_color", ""),
    }
    return data


def db_get_task(task_id: int) -> dict | None:
    from local_db import local_get_task
    return local_get_task(task_id)


def db_get_subtask(sub_id: int) -> dict | None:
    from local_db import local_get_subtask
    return local_get_subtask(sub_id)


def db_get_subtask_parent(sub_id: int) -> int | None:
    from local_db import local_get_subtask_parent
    return local_get_subtask_parent(sub_id)


# ---------------------------------------------------------------------------
# USERS
# ---------------------------------------------------------------------------

def db_get_users() -> list[str]:
    from local_db import local_get_users
    return local_get_users()


def db_ensure_user(username: str, display_name: str) -> None:
    from local_db import local_ensure_user
    local_ensure_user(username, display_name)
    def _sb():
        try:
            sb = get_client()
            if not sb.table("users").select("username").eq("username", username).execute().data:
                sb.table("users").insert({"username": username, "display_name": display_name}).execute()
        except Exception:
            pass
    _bg(_sb)


# ---------------------------------------------------------------------------
# PROJECTS
# ---------------------------------------------------------------------------

def db_add_project(name: str, color: str) -> bool:
    # Supabase first: validates uniqueness at the source of truth.
    try:
        get_client().table("projects").insert({"name": name, "color": color}).execute()
        from local_db import local_add_project
        local_add_project(name, color)
        return True
    except Exception:
        return False


def db_edit_project(old_name: str, new_name: str | None, new_color: str | None) -> bool:
    try:
        from local_db import local_update_project
        local_update_project(old_name, new_name, new_color)
        def _sb():
            try:
                sb = get_client()
                if new_color:
                    sb.table("projects").update({"color": new_color}).eq("name", old_name).execute()
                if new_name and new_name != old_name:
                    sb.table("projects").update({"name": new_name}).eq("name", old_name).execute()
            except Exception:
                pass
        _bg(_sb)
        return True
    except Exception:
        return False


def db_delete_project(name: str) -> None:
    from local_db import local_delete_project
    local_delete_project(name)
    def _sb():
        try:
            get_client().table("projects").delete().eq("name", name).execute()
        except Exception:
            pass
    _bg(_sb)


def db_get_project_for_task(task_id: int) -> str | None:
    from local_db import local_get_project_for_task
    return local_get_project_for_task(task_id)


# ---------------------------------------------------------------------------
# TASKS
# ---------------------------------------------------------------------------

def db_add_task(
    project: str, task: str, priority: str, status: str,
    notes: str | None, assigned_to: str | None = None,
) -> int:
    # Supabase first to get the authoritative id.
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
        "project": project, "task": task, "priority": priority,
        "status": status, "notes": notes,
        "sort_order": max_order + 1, "assigned_to": assigned_to,
    }).execute()
    task_id = result.data[0]["id"] if result.data else 0
    if task_id:
        from local_db import local_add_task
        local_add_task(task_id, project, task, priority, status, notes, max_order + 1, assigned_to)
    return task_id


def db_update_task(
    task_id: int, task: str, priority: str, status: str,
    notes: str | None, assigned_to: str | None = None,
) -> None:
    from local_db import local_update_task
    local_update_task(task_id, task, priority, status, notes, assigned_to)
    def _sb():
        try:
            get_client().table("tasks").update({
                "task": task, "priority": priority, "status": status,
                "notes": notes, "assigned_to": assigned_to,
            }).eq("id", task_id).execute()
        except Exception:
            pass
    _bg(_sb)


def db_delete_task(task_id: int) -> None:
    from local_db import local_delete_task
    local_delete_task(task_id)
    def _sb():
        try:
            get_client().table("tasks").delete().eq("id", task_id).execute()
        except Exception:
            pass
    _bg(_sb)


# ---------------------------------------------------------------------------
# SUB-TASKS
# ---------------------------------------------------------------------------

def db_add_subtask(task_id: int, task: str, status: str, notes: str | None) -> int:
    # Supabase first to get the authoritative id.
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
        "task_id": task_id, "task": task, "status": status,
        "notes": notes, "sort_order": max_order + 1,
    }).execute()
    sub_id = result.data[0]["id"] if result.data else 0
    if sub_id:
        from local_db import local_add_subtask
        local_add_subtask(sub_id, task_id, task, status, notes, max_order + 1)
    return sub_id


def db_update_subtask(sub_id: int, task: str, status: str, notes: str | None) -> None:
    from local_db import local_update_subtask
    local_update_subtask(sub_id, task, status, notes)
    def _sb():
        try:
            get_client().table("sub_tasks").update({
                "task": task, "status": status, "notes": notes,
            }).eq("id", sub_id).execute()
        except Exception:
            pass
    _bg(_sb)


def db_delete_subtask(sub_id: int) -> None:
    from local_db import local_delete_subtask
    local_delete_subtask(sub_id)
    def _sb():
        try:
            get_client().table("sub_tasks").delete().eq("id", sub_id).execute()
        except Exception:
            pass
    _bg(_sb)


# ---------------------------------------------------------------------------
# PROJECT LOGS
# ---------------------------------------------------------------------------

def db_get_project_logs(project: str) -> list[dict]:
    from local_db import local_get_project_logs
    return local_get_project_logs(project)


def db_get_log_by_id(log_id: int) -> dict | None:
    from local_db import local_get_log_by_id
    return local_get_log_by_id(log_id)


def db_add_project_log(project: str, log_date: str, title: str, notes: str) -> None:
    sb = get_client()
    result = sb.table("project_logs").insert({
        "project": project, "log_date": log_date, "title": title, "notes": notes,
    }).execute()
    if result.data:
        from local_db import local_add_project_log
        local_add_project_log(result.data[0]["id"], project, log_date, title, notes)


def db_update_project_log(log_id: int, log_date: str, title: str, notes: str) -> None:
    from local_db import local_update_project_log
    local_update_project_log(log_id, log_date, title, notes)
    def _sb():
        try:
            get_client().table("project_logs").update({
                "log_date": log_date, "title": title, "notes": notes,
            }).eq("id", log_id).execute()
        except Exception:
            pass
    _bg(_sb)


def db_delete_project_log(log_id: int) -> None:
    from local_db import local_delete_project_log
    local_delete_project_log(log_id)
    def _sb():
        try:
            get_client().table("project_logs").delete().eq("id", log_id).execute()
        except Exception:
            pass
    _bg(_sb)
