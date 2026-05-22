import os
import shutil
import tempfile
import random

import stem
import stem.process
import stem.control


class TorController:
    def __init__(self):
        self._tor_process = None
        self._controller: stem.control.Controller | None = None
        self._data_dir: str | None = None
        self._service_id: str | None = None
        self._onion_address: str | None = None

        # Random ports to avoid conflicts with any existing Tor
        self._socks_port = random.randint(19050, 19150)
        self._control_port = random.randint(19200, 19350)
        self._local_port = random.randint(50000, 59999)

    @property
    def socks_port(self) -> int:
        return self._socks_port

    @property
    def local_port(self) -> int:
        return self._local_port

    @property
    def onion_address(self) -> str | None:
        return self._onion_address

    def start(self, progress_callback=None) -> None:
        """Launch Tor process and authenticate controller. Blocking."""
        self._data_dir = tempfile.mkdtemp(prefix="haze_tor_")

        try:
            self._tor_process = stem.process.launch_tor_with_config(
                config={
                    "SocksPort": str(self._socks_port),
                    "ControlPort": str(self._control_port),
                    "DataDirectory": self._data_dir,
                    "Log": "err stdout",
                    "CookieAuthentication": "1",
                    "ExitPolicy": "reject *:*",
                },
                init_msg_handler=progress_callback,
                take_ownership=True,
            )
        except Exception as exc:
            self._cleanup_data_dir()
            raise RuntimeError(f"Tor başlatılamadı: {exc}") from exc

        try:
            self._controller = stem.control.Controller.from_port(
                port=self._control_port
            )
            self._controller.authenticate()
        except Exception as exc:
            self.cleanup()
            raise RuntimeError(f"Tor controller bağlantısı kurulamadı: {exc}") from exc

    def create_hidden_service(self) -> str:
        """Create ephemeral hidden service. Returns full .onion address. Blocking."""
        if self._controller is None:
            raise RuntimeError("Tor controller bağlı değil.")

        response = self._controller.create_ephemeral_hidden_service(
            {80: self._local_port},
            await_publication=True,
            detached=False,
        )
        self._service_id = response.service_id
        self._onion_address = f"{response.service_id}.onion"
        return self._onion_address

    def remove_hidden_service(self) -> None:
        if self._controller and self._service_id:
            try:
                self._controller.remove_ephemeral_hidden_service(self._service_id)
            except Exception:
                pass
            self._service_id = None
            self._onion_address = None

    def cleanup(self) -> None:
        """Full cleanup: hidden service → controller → Tor process → data dir."""
        self.remove_hidden_service()

        if self._controller:
            try:
                self._controller.close()
            except Exception:
                pass
            self._controller = None

        if self._tor_process:
            try:
                self._tor_process.kill()
                self._tor_process.wait()
            except Exception:
                pass
            self._tor_process = None

        self._cleanup_data_dir()

    def _cleanup_data_dir(self) -> None:
        if self._data_dir and os.path.exists(self._data_dir):
            shutil.rmtree(self._data_dir, ignore_errors=True)
            self._data_dir = None
