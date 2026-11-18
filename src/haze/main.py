import sys
import shutil
import traceback

from PyQt6.QtWidgets import QApplication, QMessageBox, QDialog
from PyQt6.QtGui import QIcon
from PyQt6.QtCore import Qt

from .assets import LOGO_PATH
from .ui.styles import DARK_QSS
from .ui.setup_dialog import SetupDialog
from .ui.main_window import MainWindow
from .logging_setup import setup_logging, get_logger


def _check_tor() -> bool:
    return shutil.which("tor") is not None


def _install_excepthook() -> None:
    """Log any exception that escapes to the top level instead of letting it
    vanish silently — PyQt6 can abort the whole process on an unhandled
    exception raised from certain Qt callbacks, and without this the crash
    left no trace anywhere (haze.log only ever covered the network layer)."""
    log = get_logger()
    default_hook = sys.excepthook

    def _hook(exc_type, exc_value, exc_tb):
        log.error(
            "UNHANDLED EXCEPTION:\n%s",
            "".join(traceback.format_exception(exc_type, exc_value, exc_tb)),
        )
        default_hook(exc_type, exc_value, exc_tb)

    sys.excepthook = _hook


def _app_version() -> str:
    try:
        from importlib.metadata import version
        return version("haze")
    except Exception:
        return "unknown"


def main() -> None:
    log_path = setup_logging()
    log = get_logger()
    log.info("──────── Haze %s starting ────────", _app_version())
    print(f"[haze] v{_app_version()} — logging to {log_path or 'stderr only'}", file=sys.stderr)
    _install_excepthook()

    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setApplicationName("Haze")
    # Associate the running window with the installed haze.desktop entry so the
    # desktop shell (GNOME/KDE, Wayland & X11) uses Haze's own icon in the dock
    # instead of a generic/separate one. On Wayland this sets the surface
    # app_id; on X11 it drives the WM_CLASS. Must match haze.desktop's basename
    # and its StartupWMClass.
    app.setDesktopFileName("haze")
    app.setWindowIcon(QIcon(str(LOGO_PATH)))
    app.setQuitOnLastWindowClosed(False)
    app.setStyleSheet(DARK_QSS)

    if not _check_tor():
        QMessageBox.critical(
            None,
            "Tor Bulunamadı",
            "Tor kurulu değil.\n\n"
            "Kurulum:\n"
            "  Ubuntu/Debian : sudo apt install tor\n"
            "  Arch Linux    : sudo pacman -S tor\n"
            "  Fedora        : sudo dnf install tor\n",
        )
        sys.exit(1)

    dialog = SetupDialog()
    if dialog.exec() != QDialog.DialogCode.Accepted:
        sys.exit(0)

    window = MainWindow(
        mode=dialog.mode,
        nick=dialog.nick,
        tor=dialog.tor,
        onion_url=dialog.onion_url,
        session_password=dialog.session_password,
    )
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
