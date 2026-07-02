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

En el primer arranque aparece el **Setup Wizard** automáticamente.

---

## Primer arranque — Setup Wizard

Al correr la app por primera vez se pide:

| Campo | Descripción |
|---|---|
| **Supabase URL** | `https://xxxx.supabase.co` — la del proyecto compartido |
| **Supabase Anon Key** | La clave anon del proyecto |
| **Username** | Tu identificador único (minúsculas, sin espacios). Ej: `matias` |
| **Display Name** | Tu nombre visible. Ej: `Matías De Barbora` |

Al guardar, la app:
1. Verifica la conexión con Supabase
2. Crea tu usuario en la tabla `users` si no existe
3. Guarda la configuración en `~/.tasky/config.json`
4. Descarga todos los datos del equipo a SQLite local

> El Setup Wizard solo aparece una vez. Para cambiar credenciales, editá manualmente `~/.tasky/config.json`.

---

## Incorporar un nuevo integrante

1. Compartirle la Supabase URL y la Anon Key del equipo
2. `git clone <url-del-repo>`
3. `pip install textual supabase`
4. `python sqtask.py` → el Setup Wizard lo guía
5. Al terminar ya aparece en la lista "Assigned To" del resto del equipo

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
| `users` | `username PK`, `display_name` |
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

Al abrir la app, si hay una versión más nueva disponible, aparece un aviso:

```
══════════════════════════════════════════════
  TASKY — UPDATE REQUIRED
══════════════════════════════════════════════
  Tu versión   : 1.1.0
  Versión actual : 1.1.1
  Ejecutá:  git pull
══════════════════════════════════════════════
```

Para actualizar:

```bash
git pull
python sqtask.py
```

> Tus datos no se tocan: viven en Supabase y en `~/.tasky/tasky.db`, no en los archivos del repo.

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
   A partir de este momento los demás usuarios ven el aviso de actualización.

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
| `~/.tasky/config.json` | Credenciales, username, preferencias de vista |
| `~/.tasky/tasky.db` | Caché SQLite local (se regenera desde Supabase) |

Borrar `tasky.db` es seguro — se recrea en el próximo arranque descargando todo desde Supabase. Borrar `config.json` reinicia el Setup Wizard.
