import random
from datetime import datetime

from textual import on, work
from textual.binding import Binding
from textual.containers import Center, Horizontal, Middle, Vertical, VerticalScroll
from textual.screen import ModalScreen, Screen
from textual.widgets import Button, Checkbox, DataTable, Footer, Input, Label, Select, Static, TextArea

from db import (
    db_add_project_log,
    db_delete_project_log,
    db_ensure_user,
    db_get_log_by_id,
    db_get_project_logs,
    db_update_project_log,
)


# ---------------------------------------------------------------------------
# SPLASH / WELCOME ANIMATION  (shown on startup for returning users)
# ---------------------------------------------------------------------------

class SplashScreen(Screen[None]):
    """Animación de bienvenida tipo "descifrado": el logo TASKY se revela
    a partir de caracteres aleatorios.

    IMPORTANTE: esta pantalla NUNCA se cierra a sí misma. Cerrar una pantalla
    desde su propio handler/timer (dismiss o pop) congela el event loop de
    Textual en este caso. En vez de eso, solo expone los flags `done`
    (animación completa) y `skip_requested` (el usuario pidió saltar); la App
    los consulta desde su propio timer y hace el pop en su contexto.
    """

    ART = [
        r"████████╗ █████╗ ███████╗██╗  ██╗██╗   ██╗",
        r"╚══██╔══╝██╔══██╗██╔════╝██║ ██╔╝╚██╗ ██╔╝",
        r"   ██║   ███████║███████╗█████╔╝  ╚████╔╝ ",
        r"   ██║   ██╔══██║╚════██║██╔═██╗   ╚██╔╝  ",
        r"   ██║   ██║  ██║███████║██║  ██╗   ██║   ",
        r"   ╚═╝   ╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝   ╚═╝   ",
    ]

    GLYPHS = "ABCDEFGHJKLMNPQRSTUVWXYZ0123456789#%&@$?█▓▒░"

    def __init__(self) -> None:
        super().__init__()
        self.done = False            # animación terminó
        self.skip_requested = False  # el usuario apretó una tecla

    def compose(self):
        with Middle():
            with Center():
                yield Static("", id="splash-art")
            with Center():
                yield Static("[dim](presioná cualquier tecla para saltar)[/]", id="splash-hint")

    def on_mount(self) -> None:
        art = self.query_one("#splash-art", Static)
        art.styles.width = "auto"
        art.styles.text_align = "center"
        hint = self.query_one("#splash-hint", Static)
        hint.styles.width = "auto"
        hint.styles.margin = (1, 0, 0, 0)

        # Posiciones (fila, columna) de cada caracter no-vacío, en orden aleatorio.
        self._positions = [
            (r, c)
            for r, line in enumerate(self.ART)
            for c, ch in enumerate(line)
            if ch != " "
        ]
        random.shuffle(self._positions)
        self._locked = 0
        self._step = max(1, len(self._positions) // 28)  # ~28 frames para revelar todo
        self._render_frame(set())
        self._timer = self.set_interval(0.045, self._tick)

    def _tick(self) -> None:
        if self.done:
            return
        self._locked += self._step
        self._render_frame(set(self._positions[: self._locked]))
        if self._locked >= len(self._positions):
            self._timer.stop()
            self.done = True  # la App cerrará tras la pausa final

    def _render_frame(self, locked_set: set) -> None:
        color = getattr(self.app, "app_border", "#00FF00")
        out_lines = []
        for r, line in enumerate(self.ART):
            cells = []
            for c, ch in enumerate(line):
                if ch == " ":
                    cells.append(" ")
                elif (r, c) in locked_set:
                    cells.append(f"[{color} bold]{ch}[/]")
                else:
                    cells.append(f"[#1f7a1f]{random.choice(self.GLYPHS)}[/]")
            out_lines.append("".join(cells))
        try:
            self.query_one("#splash-art", Static).update("\n".join(out_lines))
        except Exception:
            pass

    def on_key(self, event) -> None:
        # Solo marca el pedido; la App hace el cierre real.
        self.skip_requested = True


# ---------------------------------------------------------------------------
# SETUP WIZARD  (shown on first run)
# ---------------------------------------------------------------------------

class AuthScreen(Screen):
    """Login / creación de cuenta con email + contraseña (Supabase Auth).

    Se muestra en el primer arranque (modo "signup") o cuando no se pudo
    restaurar una sesión guardada (app.py decide el modo según si esta
    máquina ya hizo login real alguna vez). `prefill_username`/`prefill_display_name`
    se usan para que alguien que ya usaba Tasky antes de este cambio pueda
    "reclamar" su username existente en vez de escribirlo de cero.
    """

    def __init__(
        self, mode: str = "login",
        prefill_username: str | None = None,
        prefill_display_name: str | None = None,
    ) -> None:
        super().__init__()
        self.mode = mode
        self._prefill_username = prefill_username or ""
        self._prefill_display_name = prefill_display_name or ""

    def compose(self):
        with Vertical(id="wizard"):
            yield Label("", id="dialog-title")
            yield Label("Email:")
            yield Input(placeholder="vos@ejemplo.com", id="input-email")
            yield Label("Contraseña:")
            yield Input(placeholder="••••••••", password=True, id="input-password")
            yield Label("Tu usuario (minúsculas, sin espacios):", id="label-username")
            yield Input(placeholder="ej: matias", id="input-username", value=self._prefill_username)
            yield Label("Tu nombre:", id="label-display")
            yield Input(placeholder="ej: Matías De Barbora", id="input-display", value=self._prefill_display_name)
            yield Checkbox("Recordar sesión (no pedir la contraseña la próxima vez)", value=True, id="chk-remember")
            yield Label("", id="status-msg")
            with Horizontal(id="dialog-buttons"):
                yield Button("", variant="success", id="btn-submit")
            yield Button("", variant="default", id="btn-toggle-mode")
            yield Button("¿Olvidaste tu contraseña?", variant="default", id="btn-forgot")

    def on_mount(self) -> None:
        try:
            self.query_one("#wizard").styles.border = ("heavy", "#00FF00")
        except Exception:
            pass
        self._apply_mode()

    def _apply_mode(self, clear_status: bool = True) -> None:
        signup = self.mode == "signup"
        self.query_one("#dialog-title", Label).update(
            "[bold cyan]TASKY — CREAR CUENTA[/]" if signup else "[bold cyan]TASKY — INICIAR SESIÓN[/]"
        )
        for wid in ("#label-username", "#input-username", "#label-display", "#input-display"):
            self.query_one(wid).display = signup
        self.query_one("#btn-submit", Button).label = "CREAR CUENTA" if signup else "INICIAR SESIÓN"
        self.query_one("#btn-toggle-mode", Button).label = (
            "YA TENGO CUENTA" if signup else "CREAR UNA CUENTA NUEVA"
        )
        # "¿Olvidaste tu contraseña?" solo aplica al iniciar sesión.
        self.query_one("#btn-forgot").display = not signup
        if clear_status:
            self.query_one("#status-msg", Label).update("")

    def _remember(self) -> bool:
        return self.query_one("#chk-remember", Checkbox).value

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-toggle-mode":
            self.mode = "login" if self.mode == "signup" else "signup"
            self._apply_mode()
            return
        if event.button.id == "btn-forgot":
            email = self.query_one("#input-email", Input).value.strip().lower()
            self.app.push_screen(
                PasswordResetScreen(email, self._remember()), self._on_reset_done
            )
            return
        if event.button.id != "btn-submit":
            return

        email = self.query_one("#input-email", Input).value.strip().lower()
        password = self.query_one("#input-password", Input).value

        if not email or not password:
            self.app.notify("Email y contraseña son obligatorios.", severity="error")
            return

        remember = self._remember()
        event.button.disabled = True
        if self.mode == "signup":
            username = self.query_one("#input-username", Input).value.strip().lower()
            display_name = self.query_one("#input-display", Input).value.strip()
            if not username or not display_name:
                self.app.notify("Usuario y nombre son obligatorios.", severity="error")
                event.button.disabled = False
                return
            self.query_one("#status-msg", Label).update("[yellow]Creando cuenta...[/]")
            self._do_signup(email, password, username, display_name, remember)
        else:
            self.query_one("#status-msg", Label).update("[yellow]Iniciando sesión...[/]")
            self._do_login(email, password, remember)

    @work(thread=True)
    def _do_signup(self, email: str, password: str, username: str, display_name: str, remember: bool) -> None:
        from db import db_auth_sign_up
        result = db_auth_sign_up(email, password, username, display_name, remember)
        self.app.call_from_thread(self._on_result, result)

    @work(thread=True)
    def _do_login(self, email: str, password: str, remember: bool) -> None:
        from db import db_auth_sign_in
        result = db_auth_sign_in(email, password, remember)
        self.app.call_from_thread(self._on_result, result)

    def _on_result(self, result: dict) -> None:
        status = result.get("status")
        if status in ("ok", "logged_in"):
            self.dismiss(True)
        elif status == "confirm_email":
            # La cuenta se creó pero falta validar el email con el código de 6
            # dígitos. Abrimos la pantalla de verificación.
            self.query_one("#status-msg", Label).update(
                f"[bold cyan]Te enviamos un código a {result['email']}.[/]"
            )
            self.query_one("#btn-submit", Button).disabled = False
            self.app.push_screen(
                OtpVerifyScreen(result["email"], self._remember()), self._on_otp_done
            )
        else:
            self.query_one("#status-msg", Label).update(f"[bold red]{result.get('message', 'Error desconocido')}[/]")
            self.query_one("#btn-submit", Button).disabled = False

    def _on_otp_done(self, success: bool | None) -> None:
        if success:
            self.dismiss(True)

    def _on_reset_done(self, success: bool | None) -> None:
        # verify_otp(recovery) deja la sesión iniciada, así que un reset exitoso
        # equivale a haber logueado.
        if success:
            self.dismiss(True)


# ---------------------------------------------------------------------------
# EMAIL OTP — verificación de cuenta y recuperación de contraseña
# ---------------------------------------------------------------------------

class OtpVerifyScreen(Screen[bool]):
    """Verificación del email con el código de 6 dígitos tras crear la cuenta."""

    BINDINGS = [("escape", "cancel", "Cancelar")]

    def __init__(self, email: str, remember: bool = True) -> None:
        super().__init__()
        self.email = email
        self.remember = remember

    def compose(self):
        with Vertical(id="wizard"):
            yield Label("[bold cyan]VERIFICÁ TU EMAIL[/]", id="dialog-title")
            yield Label(f"Ingresá el código de 6 dígitos que enviamos a:\n[bold]{self.email}[/]")
            yield Label("Código:")
            yield Input(placeholder="123456", max_length=6, id="input-otp")
            yield Label("", id="status-msg")
            with Horizontal(id="dialog-buttons"):
                yield Button("VERIFICAR", variant="success", id="btn-verify")
            yield Button("Reenviar código", variant="default", id="btn-resend")
            yield Button("Volver", variant="default", id="btn-back")

    def on_mount(self) -> None:
        try:
            self.query_one("#wizard").styles.border = ("heavy", "#00FF00")
        except Exception:
            pass
        self.query_one("#input-otp", Input).focus()

    def action_cancel(self) -> None:
        self.dismiss(False)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-back":
            self.dismiss(False)
            return
        if event.button.id == "btn-resend":
            self.query_one("#status-msg", Label).update("[yellow]Reenviando código...[/]")
            self._resend()
            return
        if event.button.id != "btn-verify":
            return
        code = self.query_one("#input-otp", Input).value.strip()
        if len(code) < 6:
            self.app.notify("Ingresá el código de 6 dígitos.", severity="error")
            return
        event.button.disabled = True
        self.query_one("#status-msg", Label).update("[yellow]Verificando...[/]")
        self._verify(code)

    @work(thread=True)
    def _verify(self, code: str) -> None:
        from db import db_auth_verify_signup_otp
        result = db_auth_verify_signup_otp(self.email, code, self.remember)
        self.app.call_from_thread(self._on_result, result)

    @work(thread=True)
    def _resend(self) -> None:
        from db import db_auth_resend_signup_otp
        result = db_auth_resend_signup_otp(self.email)
        self.app.call_from_thread(self._on_resend, result)

    def _on_resend(self, result: dict) -> None:
        if result.get("status") == "ok":
            self.query_one("#status-msg", Label).update("[green]Código reenviado. Revisá tu correo.[/]")
        else:
            self.query_one("#status-msg", Label).update(
                f"[bold red]{result.get('message', 'No se pudo reenviar.')}[/]"
            )

    def _on_result(self, result: dict) -> None:
        if result.get("status") == "ok":
            self.dismiss(True)
        else:
            self.query_one("#status-msg", Label).update(f"[bold red]{result.get('message', 'Error')}[/]")
            self.query_one("#btn-verify", Button).disabled = False


class PasswordResetScreen(Screen[bool]):
    """Recuperar contraseña: envía un código de 6 dígitos al email y permite
    definir una nueva contraseña. Tiene dos fases: pedir el código y cambiar la
    contraseña."""

    BINDINGS = [("escape", "cancel", "Cancelar")]

    def __init__(self, email: str = "", remember: bool = True) -> None:
        super().__init__()
        self._prefill_email = email or ""
        self.remember = remember
        self.email = self._prefill_email
        self.phase = "request"  # "request" -> "reset"

    def compose(self):
        with Vertical(id="wizard"):
            yield Label("[bold cyan]RECUPERAR CONTRASEÑA[/]", id="dialog-title")
            yield Label("Email:")
            yield Input(placeholder="vos@ejemplo.com", id="input-email", value=self._prefill_email)
            yield Label("Código de 6 dígitos:", id="label-otp")
            yield Input(placeholder="123456", max_length=6, id="input-otp")
            yield Label("Nueva contraseña:", id="label-newpass")
            yield Input(placeholder="••••••••", password=True, id="input-newpass")
            yield Label("", id="status-msg")
            with Horizontal(id="dialog-buttons"):
                yield Button("ENVIAR CÓDIGO", variant="success", id="btn-primary")
            yield Button("Volver", variant="default", id="btn-back")

    def on_mount(self) -> None:
        try:
            self.query_one("#wizard").styles.border = ("heavy", "#00FF00")
        except Exception:
            pass
        self._apply_phase()
        self.query_one("#input-email", Input).focus()

    def _apply_phase(self) -> None:
        reset = self.phase == "reset"
        for wid in ("#label-otp", "#input-otp", "#label-newpass", "#input-newpass"):
            self.query_one(wid).display = reset
        self.query_one("#input-email", Input).disabled = reset
        self.query_one("#btn-primary", Button).label = "CAMBIAR CONTRASEÑA" if reset else "ENVIAR CÓDIGO"

    def action_cancel(self) -> None:
        self.dismiss(False)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-back":
            self.dismiss(False)
            return
        if event.button.id != "btn-primary":
            return
        if self.phase == "request":
            email = self.query_one("#input-email", Input).value.strip().lower()
            if not email:
                self.app.notify("Ingresá tu email.", severity="error")
                return
            self.email = email
            event.button.disabled = True
            self.query_one("#status-msg", Label).update("[yellow]Enviando código...[/]")
            self._send(email)
        else:
            code = self.query_one("#input-otp", Input).value.strip()
            newpass = self.query_one("#input-newpass", Input).value
            if len(code) < 6 or not newpass:
                self.app.notify("Completá el código y la nueva contraseña.", severity="error")
                return
            event.button.disabled = True
            self.query_one("#status-msg", Label).update("[yellow]Actualizando contraseña...[/]")
            self._reset(self.email, code, newpass)

    @work(thread=True)
    def _send(self, email: str) -> None:
        from db import db_auth_send_password_reset
        result = db_auth_send_password_reset(email)
        self.app.call_from_thread(self._on_send, result)

    def _on_send(self, result: dict) -> None:
        if result.get("status") != "ok":
            self.query_one("#status-msg", Label).update(
                f"[bold red]{result.get('message', 'No se pudo enviar el código.')}[/]"
            )
            self.query_one("#btn-primary", Button).disabled = False
            return
        self.phase = "reset"
        self._apply_phase()
        self.query_one("#btn-primary", Button).disabled = False
        self.query_one("#status-msg", Label).update(
            "[green]Si el email existe, te llegó un código. Ingresálo y elegí una nueva contraseña.[/]"
        )
        self.query_one("#input-otp", Input).focus()

    @work(thread=True)
    def _reset(self, email: str, code: str, newpass: str) -> None:
        from db import db_auth_reset_password_with_otp
        result = db_auth_reset_password_with_otp(email, code, newpass, self.remember)
        self.app.call_from_thread(self._on_reset, result)

    def _on_reset(self, result: dict) -> None:
        if result.get("status") == "ok":
            self.app.notify("Contraseña actualizada. Sesión iniciada.", severity="information")
            self.dismiss(True)
        else:
            self.query_one("#status-msg", Label).update(f"[bold red]{result.get('message', 'Error')}[/]")
            self.query_one("#btn-primary", Button).disabled = False


# ---------------------------------------------------------------------------
# GENERIC MODALS
# ---------------------------------------------------------------------------

class ConfirmScreen(ModalScreen[bool]):
    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, message: str):
        super().__init__()
        self.message = message

    def compose(self):
        with Vertical(id="dialog"):
            yield Label(f"[bold red]WARNING:[/bold red] {self.message}", id="dialog-title")
            with Horizontal(id="dialog-buttons"):
                yield Button("YES, PURGE", variant="error", id="btn-yes")
                yield Button("CANCEL", variant="success", id="btn-no")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "btn-yes")

    def on_mount(self) -> None:
        _apply_dialog_style(self)


class HelpScreen(ModalScreen[None]):
    BINDINGS = [
        ("escape", "close", "Close"),
        ("?", "close", "Close"),
    ]

    GROUPS = [
        ("PROYECTOS / TAREAS", [
            ("ctrl+o", "Projects"),
            ("ctrl+n", "Add Task"),
            ("ctrl+s", "Add Sub-task"),
            ("ctrl+e", "Edit / view Task"),
            ("ctrl+d", "Delete Task"),
            ("ctrl+l", "Project Log"),
            ("Enter",  "Expand / Collapse"),
        ]),
        ("USUARIOS / VISTA", [
            ("ctrl+g", "Users"),
            ("ctrl+m", "My Tasks toggle"),
            ("ctrl+b", "View User"),
            ("ctrl+a", "Hide Assigned col"),
            ("ctrl+f", "Filters"),
            ("ctrl+k", "Hide Done"),
            ("ctrl+w", "Focus Mode"),
        ]),
        ("SISTEMA", [
            ("ctrl+r", "Sync now"),
            ("ctrl+p", "Preferences"),
            ("ctrl+u", "Manual"),
            ("?",      "Shortcuts"),
            ("ctrl+q", "Quit"),
        ]),
    ]

    def __init__(self, bindings_list: list[tuple[str, str]]):
        super().__init__()

    def compose(self):
        with Vertical(id="help-dialog"):
            yield Label("[bold cyan]KEYBOARD SHORTCUTS[/]", id="dialog-title")
            with Horizontal(id="help-columns"):
                for i, (_, _binds) in enumerate(self.GROUPS):
                    with Vertical(id=f"help-col-{i}"):
                        yield Label("", id=f"help-col-title-{i}")
                        yield DataTable(show_header=False, id=f"help-dt-{i}")
            with Horizontal(id="dialog-buttons"):
                yield Button("CLOSE", variant="primary", id="btn-close")

    def on_mount(self) -> None:
        color = getattr(self.app, "app_border", "#00ff00")
        bg_color = getattr(self.app, "app_bg", "")
        try:
            dialog = self.query_one("#help-dialog")
            dialog.styles.border = ("heavy", color)
            dialog.styles.width = 108
            dialog.styles.height = "auto"
            if bg_color:
                dialog.styles.background = bg_color
            self.query_one("#help-columns").styles.height = "auto"
        except Exception:
            pass

        for i, (group_title, bindings) in enumerate(self.GROUPS):
            try:
                col = self.query_one(f"#help-col-{i}")
                col.styles.width = "1fr"
                col.styles.height = "auto"
                col.styles.padding = (0, 2)
                if i > 0:
                    col.styles.border_left = ("vkey", color)
                title = self.query_one(f"#help-col-title-{i}", Label)
                title.update(f"[bold {color}]{group_title}[/]")
                title.styles.padding = (0, 0, 1, 0)
                table = self.query_one(f"#help-dt-{i}", DataTable)
                table.styles.height = "auto"
                table.styles.border = ("none", "transparent")
                table.add_columns("KEY", "ACTION")
                for key, desc in bindings:
                    table.add_row(f"[bold cyan]{key.upper()}[/]", desc)
            except Exception:
                pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-close":
            self.dismiss(None)

    def action_close(self) -> None:
        self.dismiss(None)


class UpdateGuideScreen(ModalScreen[None]):
    BINDINGS = [
        ("escape", "close", "Close"),
        ("ctrl+u", "close", "Close"),
    ]

    GUIDE = """
[bold cyan]╔══════════════════════════════════════════════════════╗
║              TASKY — MANUAL DE USUARIO               ║
╚══════════════════════════════════════════════════════╝[/]


[bold yellow]━━━  ¿QUÉ ES TASKY?  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[/]

  Tasky es un gestor de tareas colaborativo que corre en
  la terminal. Los datos se almacenan en [bold]SQLite local[/] para
  máxima velocidad, y se sincronizan automáticamente con
  [bold]Supabase[/] (PostgreSQL en la nube) para que todo el
  equipo comparta la misma información.

  · Las [bold]lecturas[/] siempre vienen de SQLite — instantáneas.
  · Las [bold]ediciones y borrados[/] se aplican localmente y se
    envían a Supabase en segundo plano.
  · Los [bold]proyectos y tareas nuevos[/] van a Supabase primero
    para obtener un ID único, luego se cachean localmente.
  · Cada [bold]30 segundos[/] la app sincroniza en background para
    mostrar cambios de otros usuarios.
  · Si no hay conexión, podés editar y borrar igual; los
    cambios llegarán a Supabase en cuanto se restablezca.


[bold yellow]━━━  PRIMER ARRANQUE — LOGIN  ━━━━━━━━━━━━━━━━━━━━━━━[/]

  Al correr la app por primera vez aparece la pantalla de
  [bold]login[/]. No hace falta compartir ninguna credencial: la
  conexión a Supabase ya viene incluida en el código.

  Tocá [bold]CREAR UNA CUENTA NUEVA[/] y completá:

    · [bold]Email[/]     → Tu email real.
    · [bold]Contraseña[/] → La que quieras usar para entrar.
    · [bold]Usuario[/]   → Tu identificador (minúsculas,
                   sin espacios). Ej: matias
    · [bold]Nombre[/]    → Tu nombre visible. Ej: Matías DB

  Al crear la cuenta, la app:
    1. Registra el email/contraseña en Supabase Auth.
    2. Vincula la cuenta a tu fila en la tabla [dim]users[/] (crea
       una nueva, o "reclama" tu usuario existente si ya
       usabas Tasky antes de este login).
    3. Guarda la sesión en [dim]~/.tasky/config.json[/] — se
       restaura sola en próximos arranques.
    4. Descarga todos los datos del equipo a SQLite local.

  [dim]Si Supabase pide confirmar el email, revisá tu casilla y
  volvé acá con "YA TENGO CUENTA" para iniciar sesión. Para
  cerrar sesión manualmente, borrá ~/.tasky/config.json.[/]


[bold yellow]━━━  USUARIOS  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[/]

  No existe un panel de administración de usuarios.
  Cada persona [bold]se registra sola[/] al correr la app por primera
  vez en su máquina, creando su cuenta con email y contraseña.
  Ese primer login:

    · Pide sus datos (email, contraseña, username, display name).
    · Inserta su usuario en la tabla compartida [dim]users[/].
    · A partir de ese momento aparece como opción en el
      selector "Assigned To" del resto del equipo.

  [bold]Importante:[/] un usuario tiene que haber creado su cuenta al
  menos una vez para que puedas asignarle tareas. Si intentás
  asignar antes, no aparecerá en la lista.

  [bold]Pasos para incorporar a un nuevo integrante:[/]

    1. Que clone el repo:  [bold]git clone <url-del-repo>[/]
    2. Que instale deps:   [bold]pip install -r requirements.txt[/]
    3. Que corra la app:   [bold]python sqtask.py[/]
    4. La pantalla de login lo guía, "CREAR UNA CUENTA NUEVA".
       Al terminar ya existe en el sistema y cualquiera puede
       asignarle tareas.


[bold yellow]━━━  PROYECTOS  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[/]

  Los proyectos son el nivel más alto de organización.
  Cada tarea pertenece a exactamente un proyecto.
  Cada proyecto tiene un nombre único y un color.

  Gestión de proyectos → [bold]ctrl+o[/]

    · [bold]Crear[/]   → Escribí el nombre y elegí un color.
    · [bold]Editar[/]  → Cambiá el nombre o el color de uno existente.
    · [bold]Eliminar[/] → Borra el proyecto Y todas sus tareas
                    (pide confirmación).

  [dim]Los nombres de proyecto se guardan en mayúsculas.[/]


[bold yellow]━━━  TAREAS  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[/]

  [bold]Crear tarea[/]  → [bold]ctrl+n[/]
  [bold]Editar tarea[/] → [bold]ctrl+e[/]  (con la fila seleccionada)
  [bold]Borrar tarea[/] → [bold]ctrl+d[/]  (con la fila seleccionada)

  Cada tarea tiene:

    · [bold]Proyecto[/]    → A qué proyecto pertenece.
    · [bold]Descripción[/] → El texto de la tarea.
    · [bold]Prioridad[/]   → 1.HIGH / 2.MEDIUM / 3.LOW / 4.----
    · [bold]Estado[/]      → TO DO / IN PROGRESS / ON HOLD / DONE
    · [bold]Assigned To[/] → El usuario responsable (opcional).
    · [bold]Notas[/]       → Texto libre adicional (opcional).

  Las tareas nuevas se autoasignan al usuario actual.
  Al editar, el responsable existente no cambia a menos
  que lo modifiques explícitamente.

  Si el estado se cambia a [bold]DONE[/], la prioridad pasa
  automáticamente a [bold]4.----[/].


[bold yellow]━━━  SUB-TAREAS  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[/]

  Las sub-tareas son pasos dentro de una tarea principal.
  No tienen prioridad ni asignado propio — heredan el del
  padre para mostrar en pantalla.

  [bold]Crear sub-tarea[/]  → [bold]ctrl+s[/]  (parado sobre una tarea)
  [bold]Editar sub-tarea[/] → [bold]ctrl+e[/]  (parado sobre la sub-tarea)
  [bold]Borrar sub-tarea[/] → [bold]ctrl+d[/]

  Para ver las sub-tareas: [bold]Enter[/] sobre la tarea padre
  (despliega ▶ / colapsa ▼). Las sub-tareas aparecen
  indentadas debajo de su padre.

  [dim]No se pueden anidar sub-tareas dentro de sub-tareas.[/]


[bold yellow]━━━  ASIGNAR TAREAS  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[/]

  Al crear o editar una tarea, el campo [bold]"Assigned To"[/]
  muestra una lista con todos los usuarios registrados.

  Para asignar:
    1. Abrí el formulario de tarea ([bold]ctrl+n[/] o [bold]ctrl+e[/]).
    2. Elegí un usuario en el selector "Assigned To".
    3. Guardá.

  Para ver solo tus tareas → [bold]ctrl+m[/]  (toggle MY TASKS)
  Para elegir qué usuario ver → [bold]ctrl+b[/]  (popup de selección)
  Para mostrar/ocultar la columna ASSIGNED → [bold]ctrl+a[/]


[bold yellow]━━━  ESTADOS Y PRIORIDADES  ━━━━━━━━━━━━━━━━━━━━━━━━━[/]

  [bold]Prioridades[/] (orden de visualización):
    [bold red]1. HIGH[/]    → Urgente
    [bold yellow]2. MEDIUM[/]  → Normal
    [cyan]3. LOW[/]     → Baja
    [white]4. ----[/]    → Sin prioridad / completado

  [bold]Estados[/]:
    [white]TO DO[/]        → Pendiente
    [bold cyan]IN PROGRESS[/] → En curso
    [bold red]ON HOLD[/]     → Pausado / bloqueado
    [bold green]DONE[/]        → Completado

  Para ocultar tareas DONE → [bold]ctrl+k[/]  (toggle HIDE DONE)


[bold yellow]━━━  FILTROS Y VISTA  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[/]

  [bold]ctrl+f[/] abre el panel de filtros:

    · [bold]Ordenar por[/]       → PRIORITY (default) o PROJECT
    · [bold]Filtrar proyecto[/]  → Mostrar solo un proyecto
    · [bold]Filtrar prioridad[/] → Mostrar solo una prioridad

  Los filtros se guardan en [dim]~/.tasky/config.json[/] y persisten
  entre sesiones. Usá "CLEAR FILTERS" para resetearlos.

  Otros toggles de vista:
    [bold]ctrl+k[/] → Ocultar/mostrar tareas DONE
    [bold]ctrl+m[/] → Solo mis tareas / todas
    [bold]ctrl+a[/] → Mostrar/ocultar columna ASSIGNED


[bold yellow]━━━  LOG DE PROYECTOS  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[/]

  Cada proyecto tiene un registro histórico de hitos y notas.

  Para abrirlo → [bold]ctrl+l[/]  (parado sobre cualquier tarea
                       del proyecto)

  Dentro del log:
    [bold]ctrl+a[/]  → Agregar entrada  (fecha, título, notas)
    [bold]ctrl+r[/]  → Editar/borrar la entrada seleccionada
    [bold]Enter[/]   → Ver el detalle completo de una entrada
    [bold]Escape[/]  → Volver a la lista de tareas

  Las entradas se ordenan por fecha descendente.


[bold yellow]━━━  PREFERENCIAS  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[/]

  [bold]ctrl+p[/] abre las preferencias visuales:

    · [bold]Color de borde[/]     → Color del marco de todos los paneles.
    · [bold]Color de fondo[/]     → Fondo de la app (o tema por defecto).

  Los cambios se aplican en tiempo real y se guardan en
  [dim]~/.tasky/config.json[/].


[bold yellow]━━━  ATAJOS DE TECLADO  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[/]

  [bold cyan]ctrl+o[/]   Gestionar proyectos
  [bold cyan]ctrl+g[/]   Gestionar usuarios
  [bold cyan]ctrl+n[/]   Nueva tarea
  [bold cyan]ctrl+s[/]   Nueva sub-tarea
  [bold cyan]ctrl+e[/]   Editar tarea / sub-tarea seleccionada
  [bold cyan]ctrl+d[/]   Eliminar tarea / sub-tarea seleccionada
  [bold cyan]ctrl+f[/]   Filtros y vista
  [bold cyan]ctrl+k[/]   Ocultar / mostrar tareas DONE
  [bold cyan]ctrl+m[/]   Mis tareas / todas las tareas
  [bold cyan]ctrl+w[/]   Focus Mode (filtra la tabla: solo IN PROGRESS)
  [bold cyan]ctrl+↓[/]   Desplegar todas las sub-tareas
  [bold cyan]ctrl+↑[/]   Colapsar todas las sub-tareas
  [bold cyan]ctrl+b[/]   Elegir qué usuario ver
  [bold cyan]ctrl+r[/]   Sincronizar con Supabase ahora
  [bold cyan]ctrl+a[/]   Mostrar / ocultar columna ASSIGNED
  [bold cyan]ctrl+p[/]   Preferencias de interfaz
  [bold cyan]ctrl+l[/]   Log del proyecto (desde una tarea)
  [bold cyan]ctrl+u[/]   Este manual
  [bold cyan]ctrl+q[/]   Salir
  [bold cyan]?[/]        Referencia rápida de atajos
  [bold cyan]Enter[/]    Expandir / colapsar sub-tareas


[bold yellow]━━━  SINCRONIZACIÓN Y TRABAJO OFFLINE  ━━━━━━━━━━━━━━[/]

  [bold]Al arrancar:[/]
    · Si es el primer inicio (SQLite vacío): descarga todo
      desde Supabase antes de mostrar la interfaz.
    · En inicios posteriores: abre con los datos del caché
      local y sincroniza con Supabase en segundo plano.

  [bold]Durante el uso:[/]
    · Cada 30 segundos se sincroniza en background.
    · Ediciones y borrados se reflejan en pantalla al instante;
      Supabase se actualiza en segundo plano.
    · La creación de tareas/subtareas nuevas requiere conexión
      (necesita el ID de Supabase).

  [bold]Sin conexión:[/]
    · La app abre y navega normalmente con los datos locales.
    · Podés editar y borrar tareas existentes sin problema.
    · Crear tareas nuevas fallará hasta recuperar conexión.


[bold yellow]━━━  ACTUALIZAR LA APP — PARA USUARIOS  ━━━━━━━━━━━━[/]

  No hace falta hacer nada. Al abrir la app (python sqtask.py)
  revisa sola si hay una versión nueva, hace [bold]git pull[/] y se
  reinicia automáticamente con el código actualizado. Vas a
  ver un mensaje breve ("Tasky se actualizó. Reiniciando...")
  cuando eso pasa.

  [dim]Tus datos no se tocan: viven en Supabase y en tu SQLite
  local (~/.tasky/tasky.db), no en los archivos del repo.[/]

  Si ves un aviso de "NUEVA VERSIÓN DISPONIBLE" que no se
  resuelve solo (sin conexión, sin carpeta .git, o cambios
  locales sin commitear), actualizá a mano en la carpeta
  del proyecto:

       [bold]git pull[/]
       [bold]python sqtask.py[/]

  Si [bold]git pull[/] falla por cambios locales accidentales:

       [bold]git stash[/]
       [bold]git pull[/]


[bold yellow]━━━  ACTUALIZAR LA APP — PARA EL DESARROLLADOR  ━━━━[/]

  Hay dos tipos de actualización según lo que cambiaste:
    [bold]A)[/] Solo código Python (sin tocar tablas de Supabase).
    [bold]B)[/] Código + cambios de schema (nueva columna, tabla, etc).

  Seguí el flujo correspondiente:


  [bold]── CASO A: solo cambios de código ──────────────────────[/]

  [bold cyan]Paso 1[/] — Hacé los cambios en el código.

  [bold cyan]Paso 2[/] — Subí el número de versión en [dim]app.py[/]:
    Buscá la línea [bold]APP_VERSION = "x.x.x"[/] cerca del final
    del archivo y cambiá el número. Ejemplo:
         APP_VERSION = "1.0.0"  →  APP_VERSION = "1.1.0"
    Usá versionado semántico: MAJOR.MINOR.PATCH.

  [bold cyan]Paso 3[/] — Committeá y pusheá a GitHub:
       [bold]git add .[/]
       [bold]git commit -m "v1.1.0: descripción del cambio"[/]
       [bold]git push[/]
    [dim]Importante: pusheá PRIMERO. En el siguiente paso vas a
    bloquear a los demás usuarios; si el código no está en
    GitHub todavía, no van a poder actualizar.[/]

  [bold cyan]Paso 4[/] — Registrá la nueva versión en Supabase.
    Abrí el [bold]SQL Editor[/] de tu proyecto Supabase y ejecutá:
       [bold]INSERT INTO app_version (version, notes)[/]
       [bold]VALUES ('1.1.0', 'Descripción breve del cambio');[/]
    Desde este momento, los demás se actualizan solos en su
    próximo arranque (auto [bold]git pull[/] + reinicio). Este registro
    es solo para que la app avise si alguien quedó con una
    versión vieja y la auto-actualización no pudo completarse.

  ──────────────────────────────────────────────────────


  [bold]── CASO B: cambios de código + cambios de schema ───────[/]

  [bold cyan]Paso 1[/] — Hacé los cambios en el código Python.

  [bold cyan]Paso 2[/] — Aplicá el cambio de schema en Supabase.
    Abrí el [bold]SQL Editor[/] de Supabase y ejecutá el ALTER o
    CREATE necesario. Ejemplos:
       [bold]ALTER TABLE tasks ADD COLUMN etiqueta TEXT;[/]
       [bold]CREATE TABLE nueva_tabla (...);[/]
    [dim]Esto modifica la base de datos en vivo. Hacelo antes de
    pushear el código que lo usa, para que si alguien abre
    la app antes de actualizar no rompa nada.[/]

  [bold cyan]Paso 3[/] — Actualizá [dim]supabase_schema.sql[/] en el repo para
    que refleje el estado actual del schema. Este archivo
    es solo documentación/referencia; no se ejecuta
    automáticamente.

  [bold cyan]Paso 4[/] — Si el cambio de schema afecta a [dim]local_db.py[/]
    (nueva columna que hay que leer/escribir localmente),
    actualizá las funciones correspondientes en ese archivo.
    [dim]Nota: las tablas SQLite locales se recrean en cada
    instalación nueva desde init_db(). Para usuarios
    existentes, un cambio de columna requiere borrar
    ~/.tasky/tasky.db para que se recree, o agregar la
    columna manualmente.[/]

  [bold cyan]Paso 5[/] — Subí el número de versión en [dim]app.py[/]:
       APP_VERSION = "x.x.x"  →  APP_VERSION = "x.y.0"

  [bold cyan]Paso 6[/] — Committeá y pusheá a GitHub:
       [bold]git add .[/]
       [bold]git commit -m "v1.2.0: descripción del cambio"[/]
       [bold]git push[/]

  [bold cyan]Paso 7[/] — Registrá la nueva versión en Supabase:
       [bold]INSERT INTO app_version (version, notes)[/]
       [bold]VALUES ('1.2.0', 'Descripción breve');[/]

  ──────────────────────────────────────────────────────


  [bold]── CHECKLIST RÁPIDO ────────────────────────────────────[/]

  [dim]□[/] Cambié el código
  [dim]□[/] (si aplica) Ejecuté el ALTER/CREATE en Supabase SQL Editor
  [dim]□[/] (si aplica) Actualicé supabase_schema.sql
  [dim]□[/] (si aplica) Actualicé local_db.py
  [dim]□[/] Subí APP_VERSION en app.py
  [dim]□[/] git push  ← ANTES de registrar en Supabase
  [dim]□[/] INSERT INTO app_version en Supabase SQL Editor

"""

    def compose(self):
        with Vertical(id="dialog"):
            yield Label("[bold cyan]MANUAL DE USUARIO[/]", id="dialog-title")
            with VerticalScroll():
                yield Static(self.GUIDE)
            with Horizontal(id="dialog-buttons"):
                yield Button("CERRAR", variant="primary", id="btn-close")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-close":
            self.dismiss(None)

    def action_close(self) -> None:
        self.dismiss(None)

    def on_mount(self) -> None:
        _apply_dialog_style(self)


# ---------------------------------------------------------------------------
# TASK / PROJECT MODALS
# ---------------------------------------------------------------------------

class TaskFormScreen(ModalScreen[dict]):
    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(
        self,
        projects: list,
        users: list[str],
        edit_proj: str | None = None,
        edit_task_id: int | None = None,
        edit_sub_id: int | None = None,
        task_data: dict | None = None,
        is_subtask: bool = False,
        parent_proj: str | None = None,
        parent_task_id: int | None = None,
    ) -> None:
        super().__init__()
        self.projects = projects
        self.users = users
        self.edit_proj = edit_proj
        self.edit_task_id = edit_task_id
        self.edit_sub_id = edit_sub_id
        self.task_data = task_data or {}
        self.is_subtask = is_subtask
        self.parent_proj = parent_proj
        self.parent_task_id = parent_task_id

    def compose(self):
        proj_options = [(p, p) for p in self.projects]
        prio_options = [
            ("1. HIGH", "1. HIGH"),
            ("2. MEDIUM", "2. MEDIUM"),
            ("3. LOW", "3. LOW"),
            ("4. ----", "4. ----"),
        ]
        stat_options = [
            ("TO DO", "TO DO"),
            ("IN PROGRESS", "IN PROGRESS"),
            ("ON HOLD", "ON HOLD"),
            ("DONE", "DONE"),
        ]
        user_options = [("— UNASSIGNED —", "")] + [(u, u) for u in self.users]

        if self.is_subtask:
            title = (
                "[bold yellow]EDITING SUB-TASK[/]"
                if self.edit_sub_id is not None
                else "[bold cyan]INITIALIZING SUB-TASK...[/]"
            )
        else:
            title = (
                "[bold yellow]EDITING TASK OVERRIDE[/]"
                if self.edit_task_id is not None
                else "[bold green]INITIALIZING NEW TASK SEQUENCE...[/]"
            )

        with Vertical(id="dialog"):
            yield Label(title, id="dialog-title")
            yield Label("Project Designation:")
            sel_proj = Select(proj_options, id="select-project", prompt="Select Project...")
            if self.edit_proj is not None or self.is_subtask:
                sel_proj.value = self.edit_proj or self.parent_proj  # type: ignore
                sel_proj.disabled = True
            yield sel_proj
            yield Label("Task Description:")
            yield Input(
                value=self.task_data.get("task", ""),
                placeholder="Enter task...",
                id="input-desc",
            )
            yield Label("Priority:")
            sel_prio = Select(
                prio_options,
                id="select-priority",
                value=self.task_data.get("priority", "2. MEDIUM"),
            )
            if self.is_subtask:
                sel_prio.disabled = True
            yield sel_prio
            yield Label("Status:")
            yield Select(
                stat_options,
                id="select-status",
                value=self.task_data.get("status", "TO DO"),
            )
            if not self.is_subtask:
                yield Label("Assigned To:")
                yield Select(
                    user_options,
                    id="select-assigned",
                    value=self.task_data.get("assigned_to") or "",
                )
            yield Label("Notes (Optional):")
            yield Input(
                value=self.task_data.get("notes", "") or "",
                placeholder="Enter notes...",
                id="input-notes",
            )
            with Horizontal(id="dialog-buttons"):
                yield Button("SAVE DATA", variant="success", id="btn-submit")
                yield Button("CANCEL", variant="error", id="btn-cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-submit":
            project = self.query_one("#select-project", Select).value
            desc = self.query_one("#input-desc", Input).value
            priority = self.query_one("#select-priority", Select).value
            status = self.query_one("#select-status", Select).value
            notes = self.query_one("#input-notes", Input).value

            if project == Select.BLANK or not desc.strip():
                self.app.notify("Project and Description are required.", severity="error")
                return

            if priority == Select.BLANK:
                priority = "2. MEDIUM"
            if status == Select.BLANK:
                status = "TO DO"
            if status == "DONE":
                priority = "4. ----"

            assigned_to: str | None = None
            if not self.is_subtask:
                raw = self.query_one("#select-assigned", Select).value
                assigned_to = str(raw) if raw and raw != Select.BLANK else None

            self.dismiss({
                "project": project,
                "task": desc.strip(),
                "priority": priority,
                "status": status,
                "notes": notes.strip() if notes.strip() else None,
                "assigned_to": assigned_to,
                "edit_task_id": self.edit_task_id,
                "edit_sub_id": self.edit_sub_id,
                "parent_task_id": self.parent_task_id,
                "is_subtask": self.is_subtask,
            })
        elif event.button.id == "btn-cancel":
            self.dismiss(None)

    def on_mount(self) -> None:
        _apply_dialog_style(self)


class ViewFilterScreen(ModalScreen[dict]):
    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, projects: list, current_settings: dict):
        super().__init__()
        self.projects = projects
        self.settings = current_settings

    def compose(self):
        sort_opts = [("PROJECT", "project"), ("PRIORITY", "priority")]
        proj_opts = [("NONE", "NONE")] + [(p, p) for p in self.projects]
        prio_opts = [
            ("NONE", "NONE"),
            ("1. HIGH", "1. HIGH"),
            ("2. MEDIUM", "2. MEDIUM"),
            ("3. LOW", "3. LOW"),
            ("4. ----", "4. ----"),
        ]

        with Vertical(id="dialog"):
            yield Label("[bold cyan]VIEW & FILTER CONFIGURATION[/bold cyan]", id="dialog-title")
            yield Label("Sort By:")
            yield Select(sort_opts, id="sort-by", value=self.settings.get("sort_by", "priority"))
            yield Label("Project Filter:")
            yield Select(
                proj_opts,
                id="filter-proj",
                value=self.settings.get("filter_project") or "NONE",
            )
            yield Label("Priority Filter:")
            yield Select(
                prio_opts,
                id="filter-prio",
                value=self.settings.get("filter_priority") or "NONE",
            )
            with Horizontal(id="dialog-buttons"):
                yield Button("APPLY", variant="success", id="btn-apply")
                yield Button("CLEAR FILTERS", variant="warning", id="btn-clear")
                yield Button("CANCEL", variant="error", id="btn-cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-apply":
            sb = self.query_one("#sort-by", Select).value
            fp = self.query_one("#filter-proj", Select).value
            fpr = self.query_one("#filter-prio", Select).value
            self.dismiss({
                "sort_by": "priority" if sb == Select.BLANK else sb,
                "filter_project": None if fp in ("NONE", Select.BLANK) else fp,
                "filter_priority": None if fpr in ("NONE", Select.BLANK) else fpr,
            })
        elif event.button.id == "btn-clear":
            self.dismiss({
                "sort_by": self.settings.get("sort_by", "priority"),
                "filter_project": None,
                "filter_priority": None,
            })
        elif event.button.id == "btn-cancel":
            self.dismiss(None)

    def on_mount(self) -> None:
        _apply_dialog_style(self)


class ProjectManagerScreen(ModalScreen[dict]):
    BINDINGS = [("escape", "cancel", "Cancel")]

    COLOR_PALETTE = {
        "CYAN": "#00FFFF",
        "MAGENTA": "#FF00FF",
        "GREEN": "#00FF00",
        "YELLOW": "#FFFF00",
        "RED": "#FF4444",
        "BLUE": "#3399FF",
        "WHITE": "#FFFFFF",
        "ORANGE": "#FFA500",
        "VIOLET": "#EE82EE",
    }

    def __init__(self, projects: list):
        super().__init__()
        self.projects = projects

    def compose(self):
        color_opts = [
            (f"[{hex_code} bold]{name}[/]", hex_code)
            for name, hex_code in self.COLOR_PALETTE.items()
        ]
        proj_opts = [(p, p) for p in self.projects]

        with VerticalScroll(id="dialog"):
            yield Label("[bold magenta]PROJECT MANAGEMENT OVERRIDE[/bold magenta]", id="dialog-title")
            yield Label("[bold white]--- ADD NEW PROJECT ---[/]")
            yield Input(placeholder="New Project Designation...", id="new-proj-name")
            yield Select(color_opts, id="new-proj-color", prompt="Select Color...")
            yield Button("CREATE PROJECT", variant="success", id="btn-add")
            yield Label("\n[bold white]--- EDIT EXISTING PROJECT ---[/]")
            yield Select(proj_opts, id="edit-proj-name", prompt="Select Project...")
            yield Input(placeholder="New Designation (leave blank to keep)", id="edit-proj-new-name")
            yield Select(color_opts, id="edit-proj-color", prompt="Select New Color...")
            yield Button("UPDATE PROJECT", variant="primary", id="btn-edit")
            yield Label("\n[bold white]--- PURGE EXISTING PROJECT ---[/]")
            yield Select(proj_opts, id="del-proj-name", prompt="Select Project to Purge...")
            yield Button("PURGE PROJECT", variant="error", id="btn-del")
            with Horizontal(id="dialog-buttons"):
                yield Button("CLOSE MENU", id="btn-cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-add":
            name = self.query_one("#new-proj-name", Input).value.strip().upper()
            color = self.query_one("#new-proj-color", Select).value
            if not name or color == Select.BLANK:
                self.app.notify("Designation and Color required.", severity="error")
                return
            self.dismiss({"action": "add", "name": name, "color": color})
        elif event.button.id == "btn-edit":
            target = self.query_one("#edit-proj-name", Select).value
            new_name = self.query_one("#edit-proj-new-name", Input).value.strip().upper()
            new_color = self.query_one("#edit-proj-color", Select).value
            if target == Select.BLANK:
                self.app.notify("No project selected to edit.", severity="warning")
                return
            self.dismiss({
                "action": "edit",
                "name": target,
                "new_name": new_name,
                "new_color": new_color,
            })
        elif event.button.id == "btn-del":
            target = self.query_one("#del-proj-name", Select).value
            if target == Select.BLANK:
                self.app.notify("No project selected to purge.", severity="warning")
                return
            self.dismiss({"action": "delete", "name": target})
        elif event.button.id == "btn-cancel":
            self.dismiss(None)

    def on_mount(self) -> None:
        _apply_dialog_style(self)


class PreferencesScreen(ModalScreen[dict]):
    BINDINGS = [("escape", "cancel", "Cancel")]

    BORDER_PALETTE = {
        "GREEN (Default)": "#00FF00",
        "CYAN": "#00FFFF",
        "MAGENTA": "#FF00FF",
        "YELLOW": "#FFFF00",
        "RED": "#FF4444",
        "BLUE": "#3399FF",
        "WHITE": "#FFFFFF",
        "ORANGE": "#FFA500",
        "VIOLET": "#EE82EE",
    }

    BG_PALETTE = {
        "DEFAULT (Theme)": "",
        "TRANSPARENT": "transparent",
        "LAZYGIT DARK": "#242424",
        "LAZYGIT BLUE": "#1e252c",
        "PURE BLACK": "#000000",
        "DEEP NAVY": "#000040",
        "UBUNTU PLUM": "#300a24",
    }

    def __init__(self, current_border: str, current_bg: str):
        super().__init__()
        self.current_border = current_border
        self.current_bg = current_bg

    def compose(self):
        border_opts = [
            (f"[{hex_code} bold]{name}[/]", hex_code)
            for name, hex_code in self.BORDER_PALETTE.items()
        ]
        bg_opts = []
        for name, hex_code in self.BG_PALETTE.items():
            if hex_code == "transparent":
                bg_opts.append((f"[#ffffff on transparent] {name} [/]", hex_code))
            else:
                bg_opts.append((f"[{hex_code or '#ffffff'} on {hex_code or 'transparent'}] {name} [/]", hex_code))

        with Vertical(id="dialog"):
            yield Label("[bold cyan]APP PREFERENCES[/bold cyan]", id="dialog-title")
            yield Label("Border Color:")
            yield Select(border_opts, id="select-border-color", value=self.current_border, prompt="Select border color...")
            yield Label("Background Color:")
            yield Select(bg_opts, id="select-bg-color", value=self.current_bg, prompt="Select background color...")
            with Horizontal(id="dialog-buttons"):
                yield Button("APPLY", variant="success", id="btn-apply")
                yield Button("CANCEL", variant="error", id="btn-cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-apply":
            b_color = self.query_one("#select-border-color", Select).value
            bg_color = self.query_one("#select-bg-color", Select).value
            self.dismiss({
                "border": str(b_color) if b_color != Select.BLANK else self.current_border,
                "bg": str(bg_color) if bg_color != Select.BLANK else "",
            })
        elif event.button.id == "btn-cancel":
            self.dismiss(None)

    def on_mount(self) -> None:
        _apply_dialog_style(self)


# ---------------------------------------------------------------------------
# LOG SCREENS
# ---------------------------------------------------------------------------

class LogDetailScreen(ModalScreen[None]):
    BINDINGS = [
        ("escape", "close", "Close"),
        ("enter", "close", "Close"),
    ]

    def __init__(self, log_data: dict):
        super().__init__()
        self.log_data = log_data

    def compose(self):
        with Vertical(id="dialog"):
            yield Label(
                f"[bold cyan]{self.log_data['log_date']} - {self.log_data['title']}[/]",
                id="dialog-title",
            )
            notes_area = TextArea(text=self.log_data.get("notes", ""), read_only=True)
            notes_area.styles.height = "1fr"
            yield notes_area
            with Horizontal(id="dialog-buttons"):
                yield Button("CLOSE", variant="primary", id="btn-close")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-close":
            self.dismiss(None)

    def action_close(self) -> None:
        self.dismiss(None)

    def on_mount(self) -> None:
        _apply_dialog_style(self)


class LogFormScreen(ModalScreen[dict]):
    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, log_data: dict | None = None):
        super().__init__()
        self.log_data = log_data or {}
        self.is_edit = bool(self.log_data)

    def compose(self):
        default_date = self.log_data.get("log_date", datetime.now().strftime("%Y-%m-%d"))
        form_title = "[bold yellow]EDIT MILESTONE LOG[/]" if self.is_edit else "[bold cyan]ADD MILESTONE LOG[/]"

        with Vertical(id="dialog"):
            yield Label(form_title, id="dialog-title")
            yield Label("Date (YYYY-MM-DD):")
            yield Input(value=default_date, id="input-date")
            yield Label("Title:")
            yield Input(value=self.log_data.get("title", ""), placeholder="e.g., Meeting with client...", id="input-title")
            yield Label("Notes:")
            notes_area = TextArea(text=self.log_data.get("notes", ""), id="input-notes")
            notes_area.styles.height = 15
            yield notes_area
            with Horizontal(id="dialog-buttons"):
                yield Button("SAVE", variant="success", id="btn-save")
                if self.is_edit:
                    yield Button("DELETE", variant="error", id="btn-delete")
                yield Button("CANCEL", variant="primary", id="btn-cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-save":
            date_val = self.query_one("#input-date", Input).value.strip()
            title_val = self.query_one("#input-title", Input).value.strip()
            notes_val = self.query_one("#input-notes", TextArea).text.strip()

            if not date_val or not title_val or not notes_val:
                self.app.notify("Date, Title, and Notes are required.", severity="error")
                return

            try:
                datetime.strptime(date_val, "%Y-%m-%d")
            except ValueError:
                self.app.notify("Date must be YYYY-MM-DD format.", severity="error")
                return

            self.dismiss({
                "action": "save",
                "id": self.log_data.get("id"),
                "date": date_val,
                "title": title_val,
                "notes": notes_val,
            })
        elif event.button.id == "btn-delete":
            self.dismiss({"action": "delete", "id": self.log_data.get("id")})
        elif event.button.id == "btn-cancel":
            self.dismiss(None)

    def on_mount(self) -> None:
        _apply_dialog_style(self)


class ProjectLogScreen(Screen):
    BINDINGS = [
        Binding("escape", "app.pop_screen", "Back to Tasks", show=False),
        Binding("ctrl+a", "add_log", "Add Log Entry", show=False),
        Binding("ctrl+r", "edit_log", "Edit Entry", show=False),
        Binding("?", "show_help", "Shortcuts"),
    ]

    def __init__(self, project_name: str):
        super().__init__()
        self.project_name = project_name
        self.expanded_logs: set[str] = set()

    def compose(self):
        with Horizontal(id="top-bar"):
            yield Static(f"TASKY  —  {self.project_name} LOG", id="app-title")
        yield DataTable(id="log-table", cursor_type="row")
        yield Footer()

    def on_mount(self) -> None:
        color = getattr(self.app, "app_border", "#00FF00")
        self.query_one("#app-title").styles.border = ("round", color)
        self.query_one(DataTable).styles.border = ("round", color)
        self.populate_table()

    def populate_table(self) -> None:
        table = self.query_one(DataTable)

        cursor_key = None
        if table.row_count > 0:
            try:
                cursor_key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value
            except Exception:
                pass

        table.clear(columns=False)
        if not table.columns:
            table.add_columns("DATE", "TITLE")

        for log in db_get_project_logs(self.project_name):
            row_key = f"log::{log['id']}"
            indicator = "[bold cyan]▼[/] " if row_key in self.expanded_logs else "[bold white]▶[/] "
            table.add_row(
                f"{indicator}[bold cyan]{log['log_date']}[/]",
                f"[bold white]{log['title']}[/]",
                key=row_key,
            )
            if row_key in self.expanded_logs:
                table.add_row("", f"[gray]↳[/] {log['notes']}", key=f"note::{log['id']}")

        if cursor_key:
            try:
                table.move_cursor(row=table.get_row_index(cursor_key))
            except Exception:
                pass

    @on(DataTable.RowSelected)
    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        log_id = _parse_log_key(event.row_key.value)
        if log_id is None:
            return
        log_data = db_get_log_by_id(log_id)
        if log_data:
            self.app.push_screen(LogDetailScreen(log_data))

    def action_add_log(self) -> None:
        self.app.push_screen(LogFormScreen(), self.handle_log_form)

    def action_edit_log(self) -> None:
        table = self.query_one(DataTable)
        if not table.row_count:
            self.app.notify("No logs to edit.", severity="warning")
            return
        try:
            row_key_value = table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value
        except Exception:
            return
        log_id = _parse_log_key(row_key_value)
        if log_id is None:
            return
        log_data = db_get_log_by_id(log_id)
        if log_data:
            self.app.push_screen(LogFormScreen(log_data), self.handle_log_form)

    def handle_log_form(self, result: dict | None) -> None:
        if not result:
            return
        action = result.get("action")
        log_id = result.get("id")

        try:
            if action == "save":
                if log_id:
                    db_update_project_log(log_id, result["date"], result["title"], result["notes"])
                    self.app.notify("Log entry updated.", severity="information")
                else:
                    db_add_project_log(self.project_name, result["date"], result["title"], result["notes"])
                    self.app.notify("Log entry added.", severity="information")
            elif action == "delete" and log_id:
                db_delete_project_log(log_id)
                self.expanded_logs.discard(f"log::{log_id}")
        except Exception as e:
            self.app.notify(f"ERROR: {e}", severity="error")
            return
            self.app.notify("Log entry deleted.", severity="warning")

        self.populate_table()

    def action_show_help(self) -> None:
        screen_binds = []
        for b in self.BINDINGS:
            if isinstance(b, tuple):
                screen_binds.append((b[0], b[2] if len(b) == 3 else str(b[1])))
            else:
                screen_binds.append((b.key, b.description))
        self.app.push_screen(HelpScreen(screen_binds + [("ctrl+q", "Quit"), ("ctrl+p", "Preferences"), ("ctrl+l", "Project Log")]))


# ---------------------------------------------------------------------------
# USER SELECTOR  (popup para elegir qué usuario ver, fondo principal visible)
# ---------------------------------------------------------------------------

class UserManagerScreen(ModalScreen[dict | None]):
    """Gestor de usuarios: ver, editar display name, eliminar.
    Flotante pequeño, fondo principal visible.
    """
    DEFAULT_CSS = """
    UserManagerScreen {
        background: transparent;
        align: center middle;
    }
    #user-mgr-box {
        width: 54;
        max-height: 80vh;
        padding: 1 2;
    }
    """
    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, users: list[dict], current_user: str):
        super().__init__()
        self.users = users
        self.current_user = current_user

    def compose(self):
        user_opts = [
            (f"@{u['username']}  —  {u['display_name']}", u["username"])
            for u in self.users
        ]
        with VerticalScroll(id="user-mgr-box"):
            yield Label("[bold magenta]GESTIÓN DE USUARIOS[/bold magenta]", id="dialog-title")

            yield Label("[bold white]── USUARIOS REGISTRADOS ──[/]")
            for u in self.users:
                me = "  [dim](vos)[/]" if u["username"] == self.current_user else ""
                yield Label(f"  [cyan]@{u['username']}[/]  [dim]{u['display_name']}[/]{me}")

            yield Label("\n[bold white]── EDITAR DISPLAY NAME ──[/]")
            yield Select(user_opts, id="edit-user-sel", prompt="Seleccionar usuario...")
            yield Input(placeholder="Nuevo display name...", id="edit-display-name")
            yield Button("ACTUALIZAR", variant="primary", id="btn-edit")

            with Horizontal(id="dialog-buttons"):
                yield Button("CERRAR", variant="default", id="btn-cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-edit":
            target = self.query_one("#edit-user-sel", Select).value
            new_name = self.query_one("#edit-display-name", Input).value.strip()
            if target == Select.BLANK or not new_name:
                self.app.notify("Seleccioná un usuario y escribí el nuevo nombre.", severity="warning")
                return
            self.dismiss({"action": "edit", "username": str(target), "display_name": new_name})
        elif event.button.id == "btn-cancel":
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_mount(self) -> None:
        color = getattr(self.app, "app_border", "#00FF00")
        bg = getattr(self.app, "app_bg", "") or "#1e1e1e"
        try:
            box = self.query_one("#user-mgr-box")
            box.styles.border = ("heavy", color)
            box.styles.background = bg
        except Exception:
            pass


class UserSelectorScreen(ModalScreen[dict | None]):
    """Popup pequeño y centrado para elegir qué usuario ver.
    Fondo principal visible. Solo teclado: Tab, flechas, Enter, Escape.
    Devuelve {"user": str | None} al confirmar, o None si se cancela.
    """
    DEFAULT_CSS = """
    UserSelectorScreen {
        background: transparent;
        align: center middle;
    }
    #user-sel-box {
        height: auto;
        width: 48;
        padding: 1 2;
    }
    """
    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, users: list[str], current_view: str | None, current_user: str):
        super().__init__()
        self.users = users
        self.current_view = current_view
        self.current_user = current_user

    def compose(self):
        opts = [("TODOS", "__all__")] + [
            (f"@{u}" + ("  (yo)" if u == self.current_user else ""), u)
            for u in self.users
        ]
        cur = self.current_view or "__all__"
        with Vertical(id="user-sel-box"):
            yield Label("[bold cyan]VER TAREAS DE...[/]", id="dialog-title")
            yield Select(opts, id="user-select", value=cur)
            with Horizontal(id="dialog-buttons"):
                yield Button("APLICAR", variant="success", id="btn-apply")
                yield Button("CANCELAR", variant="error", id="btn-cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-apply":
            self._confirm()
        elif event.button.id == "btn-cancel":
            self.dismiss(None)

    def _confirm(self) -> None:
        val = self.query_one("#user-select", Select).value
        if val == Select.BLANK:
            return
        self.dismiss({"user": None if val == "__all__" else str(val)})

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_mount(self) -> None:
        color = getattr(self.app, "app_border", "#00FF00")
        bg = getattr(self.app, "app_bg", "") or "#1e1e1e"
        try:
            box = self.query_one("#user-sel-box")
            box.styles.border = ("heavy", color)
            box.styles.background = bg
        except Exception:
            pass


# ---------------------------------------------------------------------------
# INTERNAL HELPERS
# ---------------------------------------------------------------------------

def _parse_log_key(row_key_value) -> int | None:
    key = str(row_key_value) if row_key_value is not None else ""
    if not key.startswith("log::"):
        return None
    try:
        return int(key.split("::")[1])
    except (IndexError, ValueError):
        return None


def _apply_dialog_style(screen: ModalScreen) -> None:
    color = getattr(screen.app, "app_border", "#00ff00")
    bg_color = getattr(screen.app, "app_bg", "")
    try:
        dialog = screen.query_one("#dialog")
        dialog.styles.border = ("heavy", color)
        if bg_color:
            dialog.styles.background = bg_color
    except Exception:
        pass
