"""
migrate_to_supabase.py
----------------------
One-time migration from the local tasks.db (SQLite) to Supabase.

Usage:
    python migrate_to_supabase.py

Requirements:
    pip install supabase

Run AFTER creating the schema in Supabase (supabase_schema.sql).
Safe to re-run: skips tables that already have data.
"""

import sqlite3
import sys
from pathlib import Path

DB_FILE = "tasks.db"


def get_sqlite_conn() -> sqlite3.Connection:
    if not Path(DB_FILE).exists():
        print(f"[ERROR] '{DB_FILE}' not found. Run from the project directory.")
        sys.exit(1)
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def prompt(label: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"{label}{suffix}: ").strip()
    return value or default


def connect_supabase():
    try:
        from supabase import create_client
    except ImportError:
        print("[ERROR] supabase package not found. Run: pip install supabase")
        sys.exit(1)

    print("\n--- Supabase credentials ---")
    print("Find these in your Supabase dashboard under Settings > API\n")
    url = prompt("Supabase URL (https://xxxx.supabase.co)")
    key = prompt("Supabase anon key")

    if not url or not key:
        print("[ERROR] URL and key are required.")
        sys.exit(1)

    return create_client(url, key)


def check_empty(sb, table: str) -> bool:
    """Return True if the table has no rows."""
    result = sb.table(table).select("*", count="exact").limit(1).execute()
    return (result.count or 0) == 0


def migrate_projects(sb, conn: sqlite3.Connection) -> None:
    rows = conn.execute("SELECT name, color FROM projects").fetchall()
    if not rows:
        print("  projects: nothing to migrate.")
        return
    if not check_empty(sb, "projects"):
        print("  projects: already has data, skipping.")
        return

    data = [{"name": r["name"], "color": r["color"]} for r in rows]
    sb.table("projects").insert(data).execute()
    print(f"  projects: {len(data)} rows inserted.")


def migrate_tasks(sb, conn: sqlite3.Connection) -> dict[int, int]:
    """Returns mapping {sqlite_task_id: supabase_task_id}."""
    rows = conn.execute("SELECT * FROM tasks ORDER BY id").fetchall()
    if not rows:
        print("  tasks: nothing to migrate.")
        return {}
    if not check_empty(sb, "tasks"):
        print("  tasks: already has data, skipping.")
        # Build mapping from existing Supabase data by matching task text + project
        existing = sb.table("tasks").select("id, project, task, sort_order").execute().data
        existing_map = {(r["project"], r["task"], r["sort_order"]): r["id"] for r in existing}
        id_map = {}
        for r in rows:
            key = (r["project"], r["task"], r["sort_order"])
            if key in existing_map:
                id_map[r["id"]] = existing_map[key]
        return id_map

    id_map: dict[int, int] = {}
    for r in rows:
        result = sb.table("tasks").insert({
            "project":    r["project"],
            "task":       r["task"],
            "priority":   r["priority"],
            "status":     r["status"],
            "notes":      r["notes"],
            "sort_order": r["sort_order"],
            "assigned_to": None,
        }).execute()
        new_id = result.data[0]["id"]
        id_map[r["id"]] = new_id

    print(f"  tasks: {len(id_map)} rows inserted.")
    return id_map


def migrate_sub_tasks(sb, conn: sqlite3.Connection, id_map: dict[int, int]) -> None:
    rows = conn.execute("SELECT * FROM sub_tasks ORDER BY task_id, sort_order").fetchall()
    if not rows:
        print("  sub_tasks: nothing to migrate.")
        return
    if not check_empty(sb, "sub_tasks"):
        print("  sub_tasks: already has data, skipping.")
        return

    data = []
    skipped = 0
    for r in rows:
        new_task_id = id_map.get(r["task_id"])
        if new_task_id is None:
            skipped += 1
            continue
        data.append({
            "task_id":    new_task_id,
            "task":       r["task"],
            "status":     r["status"],
            "notes":      r["notes"],
            "sort_order": r["sort_order"],
        })

    if data:
        # Insert in batches of 100 to stay within Supabase limits
        for i in range(0, len(data), 100):
            sb.table("sub_tasks").insert(data[i:i + 100]).execute()

    print(f"  sub_tasks: {len(data)} rows inserted" + (f", {skipped} skipped (orphaned)." if skipped else "."))


def migrate_project_logs(sb, conn: sqlite3.Connection) -> None:
    rows = conn.execute("SELECT * FROM project_logs ORDER BY id").fetchall()
    if not rows:
        print("  project_logs: nothing to migrate.")
        return
    if not check_empty(sb, "project_logs"):
        print("  project_logs: already has data, skipping.")
        return

    data = [
        {
            "project":  r["project"],
            "log_date": r["log_date"],
            "title":    r["title"],
            "notes":    r["notes"],
        }
        for r in rows
    ]
    for i in range(0, len(data), 100):
        sb.table("project_logs").insert(data[i:i + 100]).execute()
    print(f"  project_logs: {len(data)} rows inserted.")


def main() -> None:
    print("=" * 50)
    print("  TASKY — Migration: SQLite → Supabase")
    print("=" * 50)

    conn = get_sqlite_conn()
    sb = connect_supabase()

    print("\nMigrating tables...")
    migrate_projects(sb, conn)
    id_map = migrate_tasks(sb, conn)
    migrate_sub_tasks(sb, conn, id_map)
    migrate_project_logs(sb, conn)

    conn.close()
    print("\n[OK] Migration complete.")
    print("You can now configure the app to use Supabase (run tasky and follow the setup wizard).")


if __name__ == "__main__":
    main()
