from __future__ import annotations

import threading

# Supabase anon keys are designed to be embedded in client apps — the real
# security boundary is RLS, not this key. Hardcoded here so onboarding a new
# teammate is just "git clone + pip install + run", no shared-secret file.
SUPABASE_URL = "https://tywzqmvvjsbdgkabplfc.supabase.co"
SUPABASE_ANON_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InR5d3pxbXZ2anNiZGdrYWJwbGZjIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODIxMzgzNDcsImV4cCI6MjA5NzcxNDM0N30.o67OExYMepGZMvhnXpzCqXfM6By_QxznwgCVFVp-W3c"

_client = None


def get_client():
    global _client
    if _client is None:
        from supabase import create_client
        _client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
    return _client


def _bg(fn, *args, **kwargs) -> None:
    threading.Thread(target=fn, args=args, kwargs=kwargs, daemon=True).start()


# ---------------------------------------------------------------------------
# AUTH — email/password via Supabase Auth. Identity gate only: RLS is not
# used, the anon key keeps reading/writing every table as before. This just
# proves who's logging in and links them to a `users.username` row.
# ---------------------------------------------------------------------------

class _UsernameTakenError(Exception):
    pass


def _auth_error_message(e: Exception) -> str:
    return getattr(e, "message", None) or str(e)


def _claim_or_create_user_row(email: str, username_hint: str | None, display_name_hint: str | None) -> str:
    """Resolve `email` to an app-level `users.username`, claiming a legacy
    (pre-auth) row or creating a new one. Returns the resolved username.
    Raises _UsernameTakenError if username_hint belongs to a different email.
    """
    sb = get_client()

    existing = sb.table("users").select("username").eq("email", email).execute().data
    if existing:
        return existing[0]["username"]

    if not username_hint:
        raise _UsernameTakenError("")

    # Atomic claim: succeeds only if the row exists AND nobody claimed it yet.
    claimed = (
        sb.table("users")
        .update({"email": email, "display_name": display_name_hint})
        .eq("username", username_hint)
        .is_("email", "null")
        .execute()
    )
    if claimed.data:
        return username_hint

    if sb.table("users").select("username").eq("username", username_hint).execute().data:
        raise _UsernameTakenError(username_hint)

    sb.table("users").insert({
        "username": username_hint, "display_name": display_name_hint, "email": email,
    }).execute()
    return username_hint


def _persist_session(session, email: str, username: str, display_name: str) -> None:
    from config import update_config
    update_config({
        "email": email,
        "username": username,
        "display_name": display_name,
        "auth_session": {
            "access_token": session.access_token,
            "refresh_token": session.refresh_token,
            "expires_at": session.expires_at,
        },
    })


def db_auth_sign_up(email: str, password: str, username: str, display_name: str) -> dict:
    """Returns {"status": "logged_in"|"confirm_email"|"error", ...}."""
    sb = get_client()

    existing = sb.table("users").select("email").eq("username", username).execute().data
    if existing and existing[0].get("email"):
        return {"status": "error", "message": f"El usuario '{username}' ya está en uso. Elegí otro, o iniciá sesión si sos vos."}

    try:
        resp = sb.auth.sign_up({
            "email": email, "password": password,
            "options": {"data": {"username": username, "display_name": display_name}},
        })
    except Exception as e:
        return {"status": "error", "message": _auth_error_message(e)}

    if resp.user is None:
        return {"status": "error", "message": "No se pudo crear la cuenta. Intentá de nuevo."}

    if resp.session is None:
        # "Confirm email" está activo en Supabase. No reclamamos el username
        # todavía (evitaría squatting con una cuenta sin confirmar) — se
        # reclama en el primer login exitoso, leyendo user_metadata.
        return {"status": "confirm_email", "email": email}

    try:
        resolved = _claim_or_create_user_row(email, username, display_name)
    except _UsernameTakenError:
        return {"status": "error", "message": f"El usuario '{username}' ya está en uso. La cuenta se creó igual — contactá al administrador."}

    _persist_session(resp.session, email, resolved, display_name)
    return {"status": "logged_in", "username": resolved, "display_name": display_name}


def db_auth_sign_in(email: str, password: str) -> dict:
    """Returns {"status": "ok"|"error", ...}."""
    sb = get_client()
    try:
        resp = sb.auth.sign_in_with_password({"email": email, "password": password})
    except Exception as e:
        return {"status": "error", "message": _auth_error_message(e)}
    if resp.session is None or resp.user is None:
        return {"status": "error", "message": "No se pudo iniciar sesión."}

    meta = resp.user.user_metadata or {}
    try:
        username = _claim_or_create_user_row(resp.user.email, meta.get("username"), meta.get("display_name"))
    except _UsernameTakenError:
        return {"status": "error", "message": "Esta cuenta no tiene un usuario asociado y el que pidió ya está en uso. Contactá al administrador."}
    display_name = meta.get("display_name") or username

    _persist_session(resp.session, resp.user.email, username, display_name)
    return {"status": "ok", "username": username, "display_name": display_name}


def db_auth_restore_session() -> dict | None:
    """Try to restore a persisted session without user interaction. Returns
    {"username", "display_name"} on success, or None if the user genuinely
    needs to (re-)authenticate. A network failure while validating does NOT
    return None — the rest of the app already works offline from the SQLite
    cache, so a connectivity hiccup must not force a returning, already
    logged-in user back to a login screen.
    """
    from supabase_auth.errors import AuthApiError
    from config import load_config
    cfg = load_config()
    session = cfg.get("auth_session")
    if not session or not session.get("refresh_token"):
        return None

    cached = {"username": cfg.get("username"), "display_name": cfg.get("display_name")}
    sb = get_client()
    try:
        sb.auth.set_session(session["access_token"], session["refresh_token"])
        resp = sb.auth.refresh_session(session["refresh_token"])
    except AuthApiError:
        return None  # explicitly rejected (expired/revoked) — real logout
    except Exception:
        return cached  # offline / Supabase down — trust the cache

    if resp.session is None or resp.user is None:
        return None
    _persist_session(resp.session, resp.user.email, cfg.get("username"), cfg.get("display_name"))
    return cached


# ---------------------------------------------------------------------------
# STARTUP SYNC: Supabase → SQLite
# ---------------------------------------------------------------------------

def sync_from_supabase() -> bool:
    """Pull all Supabase data into local SQLite. Returns True if online."""
    try:
        from local_db import local_replace_all
        sb = get_client()
        projects    = sb.table("projects").select("name, color").execute().data or []
        users       = sb.table("users").select("username, display_name, email").execute().data or []
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


def db_get_all_users() -> list[dict]:
    from local_db import local_get_all_users
    return local_get_all_users()


def db_update_user(username: str, display_name: str) -> None:
    from local_db import local_update_user
    local_update_user(username, display_name)
    def _sb():
        try:
            get_client().table("users").update({"display_name": display_name}).eq("username", username).execute()
        except Exception:
            pass
    _bg(_sb)


def db_delete_user(username: str) -> None:
    from local_db import local_delete_user
    local_delete_user(username)
    def _sb():
        try:
            sb = get_client()
            sb.table("tasks").update({"assigned_to": None}).eq("assigned_to", username).execute()
            sb.table("users").delete().eq("username", username).execute()
        except Exception:
            pass
    _bg(_sb)


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
