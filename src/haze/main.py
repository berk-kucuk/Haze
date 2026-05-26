import sys
import shutil

from PyQt6.QtWidgets import QApplication, QMessageBox, QDialog
from PyQt6.QtCore import Qt

from .ui.styles import DARK_QSS
from .ui.setup_dialog import SetupDialog
from .ui.main_window import MainWindow


def _check_tor() -> bool:
    return shutil.which("tor") is not None


def main() -> None:
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setApplicationName("Haze")
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
