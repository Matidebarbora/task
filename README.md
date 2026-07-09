# TASKY

Gestor de tareas colaborativo que corre en la terminal. Diseñado para equipos pequeños que comparten proyectos y necesitan una herramienta rápida, sin fricciones y que funcione offline.

```
████████╗ █████╗ ███████╗██╗  ██╗██╗   ██╗
╚══██╔══╝██╔══██╗██╔════╝██║ ██╔╝╚██╗ ██╔╝
   ██║   ███████║███████╗█████╔╝  ╚████╔╝
   ██║   ██╔══██║╚════██║██╔═██╗   ╚██╔╝
   ██║   ██║  ██║███████║██║  ██╗   ██║
   ╚═╝   ╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝   ╚═╝
```

---

## Características

- **TUI completa** — navegación 100% por teclado, sin mouse requerido
- **Colaborativo** — múltiples usuarios comparten proyectos y tareas en tiempo real
- **Híbrido local/nube** — SQLite local para velocidad instantánea, Supabase como fuente de verdad
- **Offline-ready** — la app abre y permite editar aunque no haya conexión
- **Sincronización automática** — cada 30 segundos en background, o manual con `ctrl+r`
- **Filtros por usuario** — cada uno ve sus tareas por defecto, con opción de ver las de cualquier compañero
- **Log de proyectos** — registro histórico de hitos por proyecto
- **Subtareas** — pasos dentro de cada tarea, con expand/collapse
- **Preferencias visuales** — color de borde y fondo personalizables por usuario

---

## Requisitos

- Python 3.10+
- Proyecto en Supabase (gratuito) con el schema aplicado

```bash
pip install textual supabase
```

---

## Instalación

```bash
git clone <url-del-repo>
cd task
pip install textual supabase
python sqtask.py
```

En el primer arranque aparece la pantalla de **login / crear cuenta** automáticamente. No hace falta compartir ninguna credencial — la conexión a Supabase ya viene incluida en el código.

---

## Primer arranque — Login

Al correr la app por primera vez se pide crear una cuenta (email + contraseña vía Supabase Auth):

| Campo | Descripción |
|---|---|
| **Email** | Tu email real |
| **Contraseña** | La que quieras usar para entrar a Tasky |
| **Usuario** | Tu identificador único (minúsculas, sin espacios). Ej: `matias` |
| **Nombre** | Tu nombre visible. Ej: `Matías De Barbora` |

Al crear la cuenta, la app:
1. Registra el email/contraseña en Supabase Auth (y, si Supabase pide confirmar el email, te avisa para que revises tu casilla antes de poder entrar)
2. Vincula esa cuenta a tu fila en la tabla `users` — crea una nueva si el usuario no existía, o "reclama" una existente si ya usabas Tasky antes de este login
3. Guarda la sesión en `~/.tasky/config.json` (se restaura sola en próximos arranques, no hay que volver a loguearse)
4. Descarga todos los datos del equipo a SQLite local

> El login solo se pide en el primer arranque de cada máquina, o si la sesión guardada dejó de ser válida. Para cerrar sesión manualmente, borrá `~/.tasky/config.json`.

---

## Incorporar un nuevo integrante

1. `git clone <url-del-repo>`
2. `pip install textual supabase`
3. `python sqtask.py` → la pantalla de login lo guía, "CREAR UNA CUENTA NUEVA"
4. Al terminar ya aparece en la lista "Assigned To" del resto del equipo

---

## Atajos de teclado

### Proyectos / Tareas

| Atajo | Acción |
|---|---|
| `ctrl+o` | Gestionar proyectos (crear, editar, eliminar) |
| `ctrl+n` | Nueva tarea |
| `ctrl+s` | Nueva subtarea (sobre una tarea seleccionada) |
| `ctrl+e` | Editar tarea o subtarea seleccionada |
| `ctrl+d` | Eliminar tarea o subtarea seleccionada |
| `ctrl+l` | Abrir log del proyecto (sobre cualquier tarea del proyecto) |
| `Enter` | Expandir / colapsar subtareas |

### Usuarios / Vista

| Atajo | Acción |
|---|---|
| `ctrl+g` | Gestionar usuarios (ver lista, editar display name) |
| `ctrl+m` | Alternar entre "mis tareas" y "todas las tareas" |
| `ctrl+b` | Elegir qué usuario ver (popup de selección) |
| `ctrl+a` | Mostrar / ocultar columna ASSIGNED |
| `ctrl+f` | Filtros y opciones de vista |
| `ctrl+k` | Ocultar / mostrar tareas con estado DONE |

### Sistema

| Atajo | Acción |
|---|---|
| `ctrl+r` | Sincronizar con Supabase ahora |
| `ctrl+p` | Preferencias (color de borde y fondo) |
| `ctrl+u` | Manual de usuario completo |
| `?` | Referencia rápida de atajos |
| `ctrl+q` | Salir |

### Pantalla de Log (solo dentro del log)

| Atajo | Acción |
|---|---|
| `ctrl+a` | Agregar entrada al log |
| `ctrl+r` | Editar / borrar entrada seleccionada |
| `Enter` | Ver detalle completo de la entrada |
| `Escape` | Volver a la lista de tareas |

---

## Modelo de datos

Cinco tablas en Supabase:

| Tabla | Columnas clave |
|---|---|
| `users` | `username PK`, `display_name`, `email` (nullable, vincula con Supabase Auth) |
| `projects` | `name PK`, `color` |
| `tasks` | `id`, `project FK`, `task`, `priority`, `status`, `notes`, `sort_order`, `assigned_to FK→users` |
| `sub_tasks` | `id`, `task_id FK`, `task`, `status`, `notes`, `sort_order` |
| `project_logs` | `id`, `project FK`, `log_date`, `title`, `notes` |

**Prioridades:** `1. HIGH` → `2. MEDIUM` → `3. LOW` → `4. ----`

**Estados:** `TO DO` → `IN PROGRESS` → `ON HOLD` → `DONE`

> Las subtareas no tienen prioridad ni asignado propio — heredan los del padre para mostrar en pantalla.

> Las preferencias de vista (filtros, colores, tema) se guardan localmente en `~/.tasky/config.json` y no se sincronizan entre usuarios — cada uno tiene las suyas.

---

## Arquitectura

### Almacenamiento híbrido

```
┌──────────────────────────────────────────────────────┐
│                      TASKY                           │
│                                                      │
│  ┌─────────────────┐         ┌────────────────────┐  │
│  │  SQLite local   │◄────────│     Supabase       │  │
│  │ ~/.tasky/       │  sync   │  (PostgreSQL)      │  │
│  │  tasky.db       │         │  fuente de verdad  │  │
│  └────────┬────────┘         └────────────────────┘  │
│           │ lecturas                  ▲               │
│           ▼                 writes en background      │
│      UI instantánea                                   │
└──────────────────────────────────────────────────────┘
```

- **Lecturas** → siempre desde SQLite local (instantáneo, funciona offline)
- **INSERT** → Supabase primero (para obtener el ID canónico), luego SQLite
- **UPDATE / DELETE** → SQLite inmediato (UI se actualiza al instante), Supabase en thread background
- **Sync al arrancar** → si SQLite está vacío (primera vez), bloquea hasta bajar todo; en arranques posteriores usa el caché y sincroniza en background
- **Sync periódico** → cada 30 segundos, recarga la tabla si hubo cambios

### Archivos

```
task/
├── sqtask.py              # Entry point (3 líneas)
├── app.py                 # TaskManagerApp + helpers de tabla + entry point
├── screens.py             # Todas las Screen y ModalScreen
├── db.py                  # API pública db_* — orquesta SQLite y Supabase
├── local_db.py            # Capa SQLite (~/.tasky/tasky.db)
├── config.py              # Config local (~/.tasky/config.json)
├── styles.tcss            # CSS de Textual
├── supabase_schema.sql    # Schema inicial — ejecutar una vez en Supabase
├── migrate_to_supabase.py # Migración desde tasks.db legacy (uso único)
└── import_tasks_db.py     # Importar tasks.db de un usuario al Supabase compartido
```

---

## Gestión de usuarios

### Agregar un usuario
Ver sección [Incorporar un nuevo integrante](#incorporar-un-nuevo-integrante).

### Ver / editar usuarios desde la app
`ctrl+g` abre el gestor de usuarios:
- Lista todos los usuarios registrados con su display name
- Permite cambiar el display name de cualquier usuario

### Eliminar un usuario
La eliminación se hace directamente en Supabase para evitar operaciones destructivas accidentales desde la app.

```sql
-- Desasignar sus tareas primero
UPDATE tasks SET assigned_to = NULL WHERE assigned_to = 'username';

-- Eliminar el usuario
DELETE FROM users WHERE username = 'username';
```

La próxima sincronización (`ctrl+r` o el ciclo de 30s) actualiza la lista en todas las instancias.

### Importar tareas desde un DB viejo

Si un usuario tiene un `tasks.db` de una versión anterior:

```bash
python import_tasks_db.py ruta/al/tasks.db
```

El script lee las credenciales de `~/.tasky/config.json`, mergea los datos al Supabase compartido y asigna las tareas al usuario actual.

---

## Actualización para usuarios

La app se actualiza sola: al abrir `python sqtask.py`, revisa si hay una versión nueva en GitHub, hace `git pull` y se reinicia automáticamente con el código actualizado. Vas a ver un mensaje breve ("Tasky se actualizó. Reiniciando...") cuando eso pasa — no hace falta hacer nada.

> Tus datos no se tocan: viven en Supabase y en `~/.tasky/tasky.db`, no en los archivos del repo.

Si la auto-actualización no pudo completarse (sin conexión, sin carpeta `.git`, o cambios locales sin commitear), aparece un aviso no bloqueante y hay que actualizar a mano:

```bash
git pull
python sqtask.py
```

Si `git pull` falla por cambios locales accidentales:

```bash
git stash
git pull
```

---

## Workflow de actualización para el desarrollador

Hay dos casos según lo que cambió:

### Caso A — Solo cambios de código Python

1. Hacé los cambios en el código
2. Subí `APP_VERSION` en `app.py`:
   ```python
   APP_VERSION = "1.1.1"  # era 1.1.0
   ```
3. Commiteá y **pusheá primero**:
   ```bash
   git add .
   git commit -m "v1.1.1: descripción del cambio"
   git push
   ```
4. Registrá la nueva versión en Supabase (SQL Editor):
   ```sql
   INSERT INTO app_version (version, notes)
   VALUES ('1.1.1', 'Descripción breve del cambio');
   ```
   A partir de este momento los demás usuarios se actualizan solos en su próximo arranque (auto `git pull`). Este registro es solo para que la app sepa mostrar un aviso si por algún motivo la auto-actualización no pudo completarse.

---

### Caso B — Cambios de código + cambios de schema

1. Hacé los cambios en el código Python
2. Aplicá el cambio de schema en el SQL Editor de Supabase:
   ```sql
   ALTER TABLE tasks ADD COLUMN nueva_columna TEXT;
   -- o CREATE TABLE nueva_tabla (...);
   ```
   > Hacé esto **antes** de pushear el código que lo usa.
3. Actualizá `supabase_schema.sql` en el repo para que refleje el estado actual
4. Actualizá `local_db.py` si la nueva columna se lee/escribe localmente
   > Nota: para usuarios existentes, un cambio de columna en SQLite requiere borrar `~/.tasky/tasky.db` para que se recree, o agregar la columna manualmente con `ALTER TABLE`.
5. Subí `APP_VERSION` en `app.py`
6. Commiteá y pusheá:
   ```bash
   git add .
   git commit -m "v1.2.0: descripción del cambio"
   git push
   ```
7. Registrá la nueva versión en Supabase:
   ```sql
   INSERT INTO app_version (version, notes)
   VALUES ('1.2.0', 'Descripción breve');
   ```

---

### Checklist rápido

```
□ Cambié el código
□ (si aplica) Ejecuté el ALTER/CREATE en Supabase SQL Editor
□ (si aplica) Actualicé supabase_schema.sql
□ (si aplica) Actualicé local_db.py
□ Subí APP_VERSION en app.py
□ git push  ← ANTES de registrar en Supabase
□ INSERT INTO app_version en Supabase SQL Editor
```

---

## Configuración del schema en Supabase

Ejecutar `supabase_schema.sql` en el SQL Editor de tu proyecto Supabase antes del primer uso. El archivo crea todas las tablas necesarias incluyendo `app_version` para el sistema de actualizaciones.

---

## Datos locales

| Ruta | Contenido |
|---|---|
| `~/.tasky/config.json` | Sesión (email, tokens), username, preferencias de vista |
| `~/.tasky/tasky.db` | Caché SQLite local (se regenera desde Supabase) |

Borrar `tasky.db` es seguro — se recrea en el próximo arranque descargando todo desde Supabase. Borrar `config.json` cierra la sesión y vuelve a mostrar la pantalla de login.
