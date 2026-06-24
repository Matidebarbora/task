"""
import_tasks_db.py
------------------
Importa las tareas de un tasks.db viejo al Supabase compartido,
mergeando con los datos existentes (no reemplaza nada).

Uso:
    python import_tasks_db.py ruta/al/tasks.db

Lee credenciales de ~/.tasky/config.json (setup ya realizado).
Asigna las tareas importadas al usuario actual del config.
"""

import sqlite3
import sys
from pathlib import Path


def load_config() -> dict:
    import json
    cfg_path = Path.home() / ".tasky" / "config.json"
    if not cfg_path.exists():
        print("[ERROR] ~/.tasky/config.json no encontrado.")
        print("        Corré 'python sqtask.py' primero para hacer el setup.")
        sys.exit(1)
    with open(cfg_path) as f:
        return json.load(f)


def connect_supabase(cfg: dict):
    try:
        from supabase import create_client
    except ImportError:
        print("[ERROR] supabase no instalado. Corré: pip install supabase")
        sys.exit(1)
    return create_client(cfg["supabase_url"], cfg["supabase_key"])


def open_old_db(path: str) -> sqlite3.Connection:
    p = Path(path)
    if not p.exists():
        print(f"[ERROR] No se encontró: {path}")
        sys.exit(1)
    conn = sqlite3.connect(str(p))
    conn.row_factory = sqlite3.Row
    return conn


def import_projects(sb, conn: sqlite3.Connection) -> None:
    rows = conn.execute("SELECT name, color FROM projects").fetchall()
    if not rows:
        print("  projects: nada para importar.")
        return

    existing = {r["name"] for r in sb.table("projects").select("name").execute().data or []}
    to_insert = [{"name": r["name"], "color": r["color"]} for r in rows if r["name"] not in existing]

    if to_insert:
        sb.table("projects").insert(to_insert).execute()
        print(f"  projects: {len(to_insert)} nuevos, {len(rows) - len(to_insert)} ya existían.")
    else:
        print(f"  projects: todos ({len(rows)}) ya existían, sin cambios.")


def import_tasks(sb, conn: sqlite3.Connection, assigned_to: str) -> dict[int, int]:
    """Inserta las tareas y devuelve {sqlite_old_id: supabase_new_id}."""
    rows = conn.execute("SELECT * FROM tasks ORDER BY id").fetchall()
    if not rows:
        print("  tasks: nada para importar.")
        return {}

    id_map: dict[int, int] = {}
    inserted = 0
    for r in rows:
        # Determinar el sort_order máximo actual para ese proyecto
        max_res = (
            sb.table("tasks")
            .select("sort_order")
            .eq("project", r["project"])
            .order("sort_order", desc=True)
            .limit(1)
            .execute()
        )
        max_order = max_res.data[0]["sort_order"] if max_res.data else 0

        result = sb.table("tasks").insert({
            "project":    r["project"],
            "task":       r["task"],
            "priority":   r["priority"],
            "status":     r["status"],
            "notes":      r["notes"],
            "sort_order": max_order + 1,
            "assigned_to": assigned_to,
        }).execute()
        new_id = result.data[0]["id"]
        id_map[r["id"]] = new_id
        inserted += 1

    print(f"  tasks: {inserted} importadas (asignadas a @{assigned_to}).")
    return id_map


def import_subtasks(sb, conn: sqlite3.Connection, id_map: dict[int, int]) -> None:
    rows = conn.execute("SELECT * FROM sub_tasks ORDER BY task_id, sort_order").fetchall()
    if not rows:
        print("  sub_tasks: nada para importar.")
        return

    to_insert = []
    skipped = 0
    for r in rows:
        new_task_id = id_map.get(r["task_id"])
        if new_task_id is None:
            skipped += 1
            continue
        to_insert.append({
            "task_id":    new_task_id,
            "task":       r["task"],
            "status":     r["status"],
            "notes":      r["notes"],
            "sort_order": r["sort_order"],
        })

    for i in range(0, len(to_insert), 100):
        sb.table("sub_tasks").insert(to_insert[i:i + 100]).execute()

    msg = f"  sub_tasks: {len(to_insert)} importadas"
    if skipped:
        msg += f", {skipped} saltadas (huérfanas)"
    print(msg + ".")


def import_project_logs(sb, conn: sqlite3.Connection) -> None:
    rows = conn.execute("SELECT * FROM project_logs ORDER BY id").fetchall()
    if not rows:
        print("  project_logs: nada para importar.")
        return

    to_insert = [
        {
            "project":  r["project"],
            "log_date": r["log_date"],
            "title":    r["title"],
            "notes":    r["notes"],
        }
        for r in rows
    ]
    for i in range(0, len(to_insert), 100):
        sb.table("project_logs").insert(to_insert[i:i + 100]).execute()
    print(f"  project_logs: {len(to_insert)} importadas.")


def main() -> None:
    if len(sys.argv) < 2:
        print("Uso: python import_tasks_db.py ruta/al/tasks.db")
        sys.exit(1)

    db_path = sys.argv[1]

    print("=" * 54)
    print("  TASKY — Importar tasks.db → Supabase")
    print("=" * 54)

    cfg = load_config()
    username = cfg.get("username", "")
    print(f"\n  Credenciales de: ~/.tasky/config.json")
    print(f"  Usuario destino:  @{username}")
    print(f"  Base de datos:    {db_path}")
    print()

    confirm = input("¿Continuar? [s/N]: ").strip().lower()
    if confirm != "s":
        print("Cancelado.")
        sys.exit(0)

    sb = connect_supabase(cfg)
    conn = open_old_db(db_path)

    print("\nImportando...")
    import_projects(sb, conn)
    id_map = import_tasks(sb, conn, assigned_to=username)
    import_subtasks(sb, conn, id_map)
    import_project_logs(sb, conn)

    conn.close()
    print("\n[OK] Importación completa.")
    print("     Reiniciá la app o usá ctrl+r para sincronizar.")


if __name__ == "__main__":
    main()
