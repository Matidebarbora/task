# Onboarding — TASKY

Guía para sumarte al gestor de tareas del equipo.

> **Importante:** No hay nada que pedirle a nadie. La conexión a la base
> compartida ya viene incluida en el código — solo cloná el repo y creá tu
> cuenta con tu email y una contraseña la primera vez que abras la app.

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
pip install -r requirements.txt
```

Instala las versiones exactas ya probadas — evita que te toque una versión más nueva sin probar que rompa algo.

## Paso 3 — Iniciar la app

```bash
python sqtask.py
```

## Paso 4 — Crear tu cuenta

La primera vez aparece una pantalla de login. Tocá **CREAR UNA CUENTA NUEVA** y completá:

| Campo             | Qué poner                                          |
| ----------------- | --------------------------------------------------- |
| **Email**         | Tu email real                                        |
| **Contraseña**    | La que quieras usar para entrar a Tasky              |
| **Usuario**       | Tu nombre en minúsculas, sin espacios (ej. `juan`)   |
| **Nombre**        | Tu nombre completo (ej. `Juan Pérez`)                |

> Si ya usabas Tasky **antes** de que existiera este login: la app te va a
> precargar tu username existente. Usalo tal cual para reclamar tus tareas
> asignadas en vez de crear un usuario duplicado.

Si Supabase pide confirmar el email, revisá tu casilla, hacé click en el link
y volvé a la app para iniciar sesión (botón **YA TENGO CUENTA**). La sesión
queda guardada en `~/.tasky/config.json` y no se vuelve a pedir en próximos
arranques.

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

No hace falta hacer nada: cada vez que abrís Tasky (`python sqtask.py`), la
app revisa sola si hay una versión nueva en GitHub, la descarga (`git pull`) y
se reinicia automáticamente con el código actualizado. Vas a ver un mensaje
tipo "Tasky se actualizó. Reiniciando..." cuando eso pasa — es normal, esperá
un segundo y la app vuelve a abrir sola.

Tus datos no se tocan en ningún caso — viven en Supabase, no en tu computadora.

### Si ves un aviso de "NUEVA VERSIÓN DISPONIBLE" que no se resuelve solo

Significa que la auto-actualización no pudo completarse (sin conexión, sin
carpeta `.git` — por ejemplo si descargaste un ZIP en vez de clonar —, o
cambios locales sin commitear en algún archivo del proyecto). Fallback manual:

```bash
git pull
python sqtask.py
```

Si `git pull` da error por cambios locales sin querer:

```bash
git stash
git pull
python sqtask.py
```

Si el problema persiste, avisale a Matías.
