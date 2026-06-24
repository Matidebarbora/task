# Onboarding — TASKY

Guía para sumarte al gestor de tareas del equipo.

> **Importante:** No necesitás crear una cuenta en Supabase ni migrar ninguna base
> de datos. Todo el equipo se conecta a un único proyecto Supabase compartido.
> Pedile a Matías la **Supabase URL** y la **anon key** por un canal privado
> (mensaje directo o gestor de contraseñas — nunca por mail abierto).

---

## Requisitos previos

- **Python 3.10+** — [python.org](https://python.org) (en Windows, marcá "Add to PATH" durante la instalación)
- **Git** — [git-scm.com](https://git-scm.com)
- Acceso al repositorio privado en GitHub (pedile a Matías que te agregue como colaborador)

---

## Paso 1 — Clonar el repositorio

```bash
git clone https://github.com/Matidebarbora/task.git
cd task
```

> Cloná el repo, no descargues el ZIP. El comando `git pull` para futuras
> actualizaciones solo funciona sobre un clon.

## Paso 2 — Instalar dependencias

```bash
pip install textual supabase
```

## Paso 3 — Iniciar la app

```bash
python sqtask.py
```

## Paso 4 — Completar el asistente de configuración

La primera vez aparece un formulario. Completá:

| Campo            | Qué poner                                                        |
| ---------------- | --------------------------------------------------------------- |
| **Supabase URL** | La que te pasó Matías (`https://....supabase.co`)               |
| **Anon Key**     | La que te pasó Matías (`eyJhbGci...`)                           |
| **Username**     | Tu nombre en minúsculas, sin espacios (ej. `juan`)             |
| **Display name** | Tu nombre completo (ej. `Juan Pérez`)                          |

Al guardar, la app valida la conexión, crea tu usuario en la tabla compartida y
arranca. La configuración queda en `~/.tasky/config.json` y no se vuelve a pedir.

---

## Listo

Ya ves y editás las tareas del equipo en tiempo compartido.
Con `ctrl+m` alternás entre **todas las tareas** y **solo las tuyas**.

Presioná `?` dentro de la app para ver todos los atajos de teclado.

---

## (Opcional) Importar tus tareas de la versión vieja con SQLite

Si ya usabas Tasky cuando guardaba todo en un archivo `tasks.db` local y querés
conservar esos proyectos y tareas, podés importarlos al Supabase compartido.

1. Asegurate de haber completado el asistente primero (Paso 4) — el merge usa esa configuración.
2. Dejá tu `tasks.db` viejo en la carpeta del proyecto (o tené a mano su ruta).
3. Ejecutá:

   ```bash
   python merge_db.py
   ```

   Si tu `tasks.db` está en otra ubicación:

   ```bash
   python merge_db.py C:\ruta\a\tu\tasks.db
   ```

Todas las tareas importadas quedan asignadas a tu usuario. Si un proyecto tuyo
coincidiera con uno ya existente, se omite su creación pero las tareas igual se
cargan.

> Corré este script **una sola vez**. Repetirlo duplicaría tus tareas.

---

## Cómo actualizar la app

Cuando se publica una versión nueva del programa, la próxima vez que lo abras
**no va a arrancar** y en su lugar vas a ver un mensaje como este:

```
====================================================
  TASKY — UPDATE REQUIRED
====================================================
  Tu versión     : 1.0.0
  Versión actual : 1.1.0
  Notas          : Qué cambió

  Ejecutá:  git pull
  Luego reiniciá la app.
====================================================
```

Es normal: significa que hay una versión más nueva disponible. Para actualizar,
parate en la carpeta del proyecto y ejecutá:

```bash
git pull
python sqtask.py
```

`git pull` descarga la última versión desde GitHub y la app vuelve a abrir
normalmente. Tus datos no se tocan — viven en Supabase, no en tu computadora.

### Si `git pull` da error

Lo más común es que tengas cambios locales sin querer (por ejemplo, tocaste un
archivo sin darte cuenta). Para descartarlos y traer la versión limpia:

```bash
git stash
git pull
python sqtask.py
```

Si el problema persiste, avisale a Matías.

> **Nota:** mientras Supabase esté disponible, la app solo bloquea si hay una
> versión nueva de verdad. Si no hay internet o Supabase está caído, la app
> arranca igual para no dejarte trabado.
