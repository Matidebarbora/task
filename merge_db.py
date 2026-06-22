"""
merge_db.py — Importa un tasks.db local (de la época SQLite) al Supabase compartido.

Pensado para integrantes que ya usaban Tasky en su versión single-user y quieren
conservar sus proyectos, tareas y logs. Todas las tareas importadas quedan
asignadas al usuario actual (assigned_to).

Uso:
    1. Configurá la app primero: `python sqtask.py` y completá el asistente.
    2. Dejá tu tasks.db viejo en esta carpeta (o pasá la ruta como argumento).
    3. python merge_db.py [ruta-al-tasks.db]

Requisitos: pip install supabase

IMPORTANTE: corré este script UNA sola vez. Volver a correrlo duplicaría tus tareas.
"""

import sqlite3
import sys
from pathlib import Path

from config import config_exists, load_config
from db import db_ensure_user, get_client

DEFAULT_DB = "tasks.db"


def get_sqlite_conn(path: str) -> sqlite3.Connection:
    if not Path(path).exists():
        print(f"[ERROR] No se encontró '{path}'.")
        print("Pasá la ruta a tu tasks.db viejo:  python merge_db.py C:\\ruta\\tasks.db")
        sys.exit(1)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def confirm() -> bool:
    print("\nEste script importará tu base SQLite vieja al Supabase compartido.")
    print("Las tareas quedarán asignadas a tu usuario.")
    print("Corré esto UNA sola vez (repetirlo duplicaría tus tareas).\n")
    answer = input("¿Continuar? Escribí 'si' para confirmar: ").strip().lower()
    return answer in ("si", "sí", "yes", "y")


def merge_projects(sb, conn: sqlite3.Connection) -> None:
    rows = conn.execute("SELECT name, color FROM projects").fetchall()
    if not rows:
        print("  proyectos: nada que importar.")
        return

    existing = {r["name"] for r in (sb.table("projects").select("name").execute().data or [])}
    to_insert = [{"name": r["name"], "color": r["color"]} for r in rows if r["name"] not in existing]
    skipped = len(rows) - len(to_insert)

    if to_insert:
        sb.table("projects").insert(to_insert).execute()
    msg = f"  proyectos: {len(to_insert)} importados"
    if skipped:
        msg += f", {skipped} ya existían (omitidos)"
    print(msg + ".")


def merge_tasks(sb, conn: sqlite3.Connection, username: str) -> dict[int, int]:
    """Inserta tareas asignadas al usuario. Devuelve {id_sqlite: id_supabase}."""
    rows = conn.execute("SELECT * FROM tasks ORDER BY id").fetchall()
    if not rows:
        print("  tareas: nada que importar.")
        return {}

    id_map: dict[int, int] = {}
    for r in rows:
        result = sb.table("tasks").insert({
            "project": r["project"],
            "task": r["task"],
            "priority": r["priority"],
            "status": r["status"],
            "notes": r["notes"],
            "sort_order": r["sort_order"],
            "assigned_to": username,
        }).execute()
        id_map[r["id"]] = result.data[0]["id"]

    print(f"  tareas: {len(id_map)} importadas (asignadas a @{username}).")
    return id_map


def merge_sub_tasks(sb, conn: sqlite3.Connection, id_map: dict[int, int]) -> None:
    rows = conn.execute("SELECT * FROM sub_tasks ORDER BY task_id, sort_order").fetchall()
    if not rows:
        print("  subtareas: nada que importar.")
        return

    data = []
    orphaned = 0
    for r in rows:
        new_task_id = id_map.get(r["task_id"])
        if new_task_id is None:
            orphaned += 1
            continue
        data.append({
            "task_id": new_task_id,
            "task": r["task"],
            "status": r["status"],
            "notes": r["notes"],
            "sort_order": r["sort_order"],
        })

    for i in range(0, len(data), 100):
        sb.table("sub_tasks").insert(data[i:i + 100]).execute()

    msg = f"  subtareas: {len(data)} importadas"
    if orphaned:
        msg += f", {orphaned} huérfanas omitidas"
    print(msg + ".")


def merge_project_logs(sb, conn: sqlite3.Connection) -> None:
    rows = conn.execute("SELECT * FROM project_logs ORDER BY id").fetchall()
    if not rows:
        print("  logs: nada que importar.")
        return

    data = [
        {"project": r["project"], "log_date": r["log_date"], "title": r["title"], "notes": r["notes"]}
        for r in rows
    ]
    for i in range(0, len(data), 100):
        sb.table("project_logs").insert(data[i:i + 100]).execute()
    print(f"  logs: {len(data)} importados.")


def main() -> None:
    print("=" * 52)
    print("  TASKY — Merge: tu SQLite viejo → Supabase compartido")
    print("=" * 52)

    if not config_exists():
        print("\n[ERROR] La app no está configurada todavía.")
        print("Corré primero:  python sqtask.py  (y completá el asistente)")
        sys.exit(1)

    cfg = load_config()
    username = cfg["username"]
    display_name = cfg.get("display_name", username)

    db_path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_DB
    conn = get_sqlite_conn(db_path)

    print(f"\nUsuario actual : @{username}")
    print(f"Base a importar: {db_path}")

    if not confirm():
        print("Cancelado.")
        sys.exit(0)

    sb = get_client()
    db_ensure_user(username, display_name)  # garantiza la FK assigned_to

    print("\nImportando...")
    merge_projects(sb, conn)
    id_map = merge_tasks(sb, conn, username)
    merge_sub_tasks(sb, conn, id_map)
    merge_project_logs(sb, conn)

    conn.close()
    print("\n[OK] Merge completo. Abrí la app para ver tus datos:  python sqtask.py")


if __name__ == "__main__":
    main()
