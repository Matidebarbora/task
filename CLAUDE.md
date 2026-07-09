# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the app

```bash
python sqtask.py
```

On first run, an email + password login/signup screen appears. No Supabase URL/key to enter — those are baked into `db.py`. Session is saved to `~/.tasky/config.json` and restored automatically on later launches (no need to log in every time).

## Dependencies

```bash
pip install -r requirements.txt
```

Pinned exact versions (`textual==7.4.0`, `supabase==2.31.0`) — avoids new users getting an untested newer version that might break something.

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
├── requirements.txt       # Pinned dependency versions
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

Every user connects with the same `SUPABASE_URL`/`SUPABASE_ANON_KEY`, hardcoded as constants in `db.py` (not user-entered — see "Authentication" below for why that's fine). `~/.tasky/config.json` holds the logged-in user's `email`, `auth_session`, `username`, `display_name`, and personal UI preferences (`view_settings`).

### Authentication

Login is email + password via Supabase Auth (`db.py`'s `db_auth_sign_up`/`db_auth_sign_in`/`db_auth_restore_session`). This is an **identity gate only** — there's no Row Level Security; the anon key keeps reading/writing every table exactly as before. Auth just proves who's logging in and links them to a `users.username` row, so people can no longer type an arbitrary username with zero verification like the old setup wizard allowed.

- `SUPABASE_URL`/`SUPABASE_ANON_KEY` are hardcoded in `db.py`. This is intentional: Supabase anon keys are designed to be public in client apps (RLS is the real security boundary, not the key) — baking them in means onboarding is just `git clone` + `pip install` + run, no shared-secret file to pass around.
- `users.email` links a Supabase Auth account to an app-level `username`. `_claim_or_create_user_row()` in `db.py` either claims a pre-existing (pre-auth) username row whose `email` is still `NULL`, or creates a new one — atomically, race-safe against two people claiming the same legacy username.
- If Supabase's "Confirm email" setting is on, `sign_up()` returns no session until the user clicks the confirmation link; `db_auth_sign_up` reports `status: "confirm_email"` and the actual username claim happens on the next successful login (reading `username`/`display_name` back from `user_metadata`).
- Session tokens (`access_token`/`refresh_token`) are cached in `config.json` via `config.update_config()` (a merge-safe partial update, unlike the full-overwrite `save_config()`) and restored on startup by `db_auth_restore_session()`. A network failure while restoring does **not** force a re-login — only an explicit rejection from Supabase (expired/revoked session) does; this matches the rest of the app's offline-first design.

### Data model

Five tables in Supabase:

| Table | Key columns |
|---|---|
| `users` | `username PK`, `display_name`, `email` (nullable, links to Supabase Auth) |
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
| `AuthScreen` | Full screen shown on first run / when a session can't be restored — email+password login or signup |
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
| `ctrl+o` | Gestionar proyectos |
| `ctrl+n` | Nueva tarea |
| `ctrl+s` | Nueva subtarea |
| `ctrl+e` | Editar tarea/subtarea |
| `ctrl+d` | Eliminar tarea/subtarea |
| `ctrl+f` | Filtros / vista |
| `ctrl+k` | Ocultar/mostrar DONE |
| `ctrl+m` | Mis tareas / todas |
| `ctrl+w` | Focus Mode (filtra la tabla principal para mostrar solo IN PROGRESS) |
| `ctrl+flecha abajo` | Desplegar todas las tareas (subtareas) |
| `ctrl+flecha arriba` | Colapsar todas las tareas |
| `ctrl+a` | Ocultar/mostrar columna ASSIGNED |
| `ctrl+p` | Preferencias |
| `ctrl+l` | Log del proyecto (estando sobre una tarea) |
| `ctrl+u` | Manual (in-app) |
| `ctrl+q` | Salir |
| `?` | Ayuda |

**Log screen only:** `ctrl+a` agregar entrada, `ctrl+r` editar entrada, `escape` volver.

Notas:
- `ENABLE_COMMAND_PALETTE = False` en `TaskManagerApp` desactiva el command palette de Textual para liberar `ctrl+p`.
- Las tareas nuevas se autoasignan al usuario actual (`action_add_task` pasa `task_data={"assigned_to": self.current_user}`). Editar una tarea respeta el responsable existente.
- `hide_assigned`, `my_tasks_only` (view_user) y `focus_mode` son estado en memoria (no persisten); `hide_done` y los colores sí persisten en el config local.
- La columna ASSIGNED se agrega/quita recreando las columnas del DataTable (`table.clear(columns=True)`), por eso las filas se construyen con un número variable de valores.

## Adding a new user

1. Copy or clone the project folder
2. `pip install -r requirements.txt`
3. `python sqtask.py` → login/signup screen appears
4. Create an account: email, password, username, display name (no credentials to share — the Supabase connection is baked in)

## Onboarding a new team member

1. `git clone <repo_url>` (repo privado en GitHub)
2. `pip install -r requirements.txt`
3. `python sqtask.py` → aparece la pantalla de login
4. "CREAR CUENTA": email, contraseña, username y nombre propios. Si ya usabas Tasky antes de este cambio, usá el **mismo username** que ya tenías (aparece precargado) para reclamar tus tareas asignadas en vez de duplicar el usuario.
5. Si Supabase pide confirmar el email, revisar la casilla y después volver a la app para iniciar sesión.

## Workflow de actualización (para el desarrollador)

La app se auto-actualiza (`git pull` automático al iniciar, ver `_auto_update()` en `app.py`). Cuando hay un cambio que lo requiere:

1. Hacer el cambio en el código y pushearlo a GitHub
2. Si el cambio incluye una modificación de schema, ejecutar el ALTER en el SQL Editor de Supabase y actualizar `supabase_schema.sql`
3. Registrar la nueva versión en Supabase:
   ```sql
   INSERT INTO app_version (version, notes)
   VALUES ('1.x.x', 'Descripción breve del cambio');
   ```
4. Bumpearlo también en `APP_VERSION` en `app.py`

Los usuarios reciben la actualización solos en su próximo arranque — no tienen que hacer nada. Si el auto-update no pudo completarse (sin conexión, sin repo git, cambios locales sin commitear), ven un aviso no bloqueante sugiriendo `git pull` manual.

## Workflow de actualización (para cada usuario)

No hace falta hacer nada — `python sqtask.py` se actualiza solo al iniciar. Si por algún motivo no se pudo auto-actualizar (ver aviso en pantalla), como fallback manual:

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
