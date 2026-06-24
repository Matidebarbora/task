# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the app

```bash
python sqtask.py
```

On first run, a setup wizard asks for Supabase credentials and username. Config is saved to `~/.tasky/config.json` and never re-asked.

## Dependencies

```bash
pip install textual supabase
```

## File structure

```
task/
├── sqtask.py              # Entry point (3-line wrapper)
├── app.py                 # TaskManagerApp + table rendering helpers + entry point
├── screens.py             # All Screen and ModalScreen classes
├── db.py                  # Public db_* API — routes reads to SQLite, writes to both
├── local_db.py            # SQLite layer (~/.tasky/tasky.db)
├── config.py              # Local config file management (~/.tasky/config.json)
├── styles.tcss            # Textual CSS
├── supabase_schema.sql    # Run once in Supabase SQL Editor to create tables
└── migrate_to_supabase.py # One-time migration from legacy tasks.db
```

## Architecture

### Hybrid local/remote storage

The app uses **SQLite as the primary store** (`~/.tasky/tasky.db`) and **Supabase as the sync target and source of truth** for multi-user collaboration.

- **Reads** always come from local SQLite — instant, works offline.
- **INSERT operations** (new task/subtask/project/log) go to Supabase first to obtain the canonical integer PK, then the row is written to SQLite.
- **UPDATE and DELETE operations** write to SQLite immediately (the UI refreshes at once), then push to Supabase in a background thread.
- **Startup sync**: on each launch, `sync_from_supabase()` pulls all tables from Supabase and replaces the local SQLite data. On first run (SQLite empty) this is blocking; on subsequent runs it happens in the background so the app opens instantly with the cached data.
- **Periodic sync**: every 30 seconds a background thread re-syncs from Supabase and refreshes the table — picks up changes made by other users.

`local_db.py` is the SQLite layer; `db.py` is the public `db_*` API that orchestrates both layers. The rest of the app only imports from `db.py`.

Each user connects with the same `supabase_url` and `supabase_key`, stored locally in `~/.tasky/config.json`. The config also holds the user's `username`, `display_name`, and personal UI preferences (`view_settings`).

### Data model

Five tables in Supabase:

| Table | Key columns |
|---|---|
| `users` | `username PK`, `display_name` |
| `projects` | `name PK`, `color` |
| `tasks` | `id`, `project FK`, `task`, `priority`, `status`, `notes`, `sort_order`, `assigned_to FK→users` |
| `sub_tasks` | `id`, `task_id FK`, `task`, `status`, `notes`, `sort_order` |
| `project_logs` | `id`, `project FK`, `log_date`, `title`, `notes` |

Sub-tasks have no `assigned_to` — they inherit from the parent task for display.

`view_settings` (sort, filters, theme, colors) are **not** in Supabase. They live per-user in `~/.tasky/config.json`.

### Screen stack

`TaskManagerApp` owns the root screen. Navigation uses `push_screen` / `pop_screen`:

| Screen | Purpose |
|---|---|
| `SetupWizardScreen` | Full screen shown on first run — collects credentials and creates user |
| `TaskManagerApp` | Main task list (DataTable) |
| `ProjectLogScreen` | Full-screen milestone log for a project |
| `TaskFormScreen` | Modal — add/edit task or sub-task, includes assignee selector |
| `ProjectManagerScreen` | Modal — create/rename/delete projects |
| `ViewFilterScreen` | Modal — sort and filter options |
| `PreferencesScreen` | Modal — border and background color |
| `LogFormScreen` | Modal — add/edit/delete a log entry |
| `LogDetailScreen` | Modal — read-only view of a log entry |
| `ConfirmScreen` | Modal — generic yes/no confirmation |
| `HelpScreen` | Modal — keybinding reference |

### Row keys

The main DataTable encodes type and DB id into row keys:
- `task::<id>` — a task row
- `sub::<id>` — a sub-task row (indented under its parent when expanded)

`ProjectLogScreen` uses `log::<id>` and `note::<id>` (expanded preview). `_parse_log_key()` in `screens.py` handles the distinction.

### Reactive state

`TaskManagerApp` has two reactive attributes (`app_border`, `app_bg`) that propagate border/background colors to all widgets and persist to local config via their `watch_*` methods.

## Keybindings

| Atajo | Acción |
|---|---|
| `ctrl+1` | Gestionar proyectos |
| `ctrl+2` | Nueva tarea |
| `ctrl+s` | Nueva subtarea |
| `ctrl+e` | Editar tarea/subtarea |
| `ctrl+d` | Eliminar tarea/subtarea |
| `ctrl+f` | Filtros / vista |
| `ctrl+h` | Ocultar/mostrar DONE |
| `ctrl+m` | Mis tareas / todas |
| `ctrl+a` | Ocultar/mostrar columna ASSIGNED |
| `ctrl+p` | Preferencias |
| `ctrl+l` | Log del proyecto (estando sobre una tarea) |
| `ctrl+u` | Guía de actualización (in-app) |
| `ctrl+q` | Salir |
| `?` | Ayuda |

**Log screen only:** `ctrl+a` agregar entrada, `ctrl+r` editar entrada, `escape` volver.

Notas:
- `ENABLE_COMMAND_PALETTE = False` en `TaskManagerApp` desactiva el command palette de Textual para liberar `ctrl+p`.
- Las tareas nuevas se autoasignan al usuario actual (`action_add_task` pasa `task_data={"assigned_to": self.current_user}`). Editar una tarea respeta el responsable existente.
- `hide_assigned` y `my_tasks_only` son estado en memoria (no persisten); `hide_done` y los colores sí persisten en el config local.
- La columna ASSIGNED se agrega/quita recreando las columnas del DataTable (`table.clear(columns=True)`), por eso las filas se construyen con un número variable de valores.

## Adding a new user

1. Copy or clone the project folder
2. `pip install textual supabase`
3. `python sqtask.py` → setup wizard appears
4. Enter the shared Supabase URL and anon key, plus personal username and display name

## Onboarding a new team member

1. `git clone <repo_url>` (repo privado en GitHub)
2. `pip install textual supabase`
3. `python sqtask.py` → el setup wizard aparece automáticamente
4. Ingresar la Supabase URL y anon key compartidas del equipo, más username y display name propios

## Workflow de actualización (para el desarrollador)

Cuando hay un cambio que requiere que todos actualicen:

1. Hacer el cambio en el código y pushearlo a GitHub
2. Si el cambio incluye una modificación de schema, ejecutar el ALTER en el SQL Editor de Supabase y actualizar `supabase_schema.sql`
3. Registrar la nueva versión en Supabase:
   ```sql
   INSERT INTO app_version (version, notes)
   VALUES ('1.x.x', 'Descripción breve del cambio');
   ```
4. Bumpearlo también en `APP_VERSION` en `app.py`

Los usuarios verán un mensaje al iniciar la app y deberán correr `git pull` antes de continuar.

## Workflow de actualización (para cada usuario)

```bash
git pull
python sqtask.py
```

## Schema changes

Schema lives in Supabase. To add a column or table:
1. Run the ALTER/CREATE in the Supabase SQL Editor
2. Update `supabase_schema.sql` to reflect the change
3. Update `db.py` functions as needed
4. Bump `APP_VERSION` in `app.py` and register it in the `app_version` table
