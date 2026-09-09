import os
import sys
import socket
import atexit
import threading
from pathlib import Path
from typing import Optional, Callable

from core.config import get_config_dir

APP_MUTEX_NAME = "Local\\gemini-token-counter-app"
RESTORE_COMMAND = b"GEMINI_TOKEN_COUNTER_RESTORE\n"
PORT_FILENAME = "gemini-token-counter-instance.port"


class SingleInstanceManager:
    """
    Guarantees that only a single instance of the Gemini Token Counter desktop app runs.
    If another instance is launched:
    1. It notifies the existing running instance to restore and focus its window.
    2. The secondary process exits immediately with zero overhead.
    """

    def __init__(self, app_name: str = "gemini-token-counter"):
        self.app_name = app_name
        self.mutex_name = f"Local\\{app_name}-app"
        self._mutex_handle = None
        self._server_socket: Optional[socket.socket] = None
        self._server_thread: Optional[threading.Thread] = None
        self._restore_callback: Optional[Callable[[], None]] = None
        self._is_primary: bool = False
        self._released: bool = False
        self._port_file = get_config_dir() / PORT_FILENAME

    def set_restore_callback(self, callback: Callable[[], None]):
        """Registers callback to be called when a secondary instance requests window restoration."""
        self._restore_callback = callback

    def acquire_or_activate(self) -> bool:
        """
        Attempts to acquire single-instance ownership.
        Returns True if this is the primary instance (proceed with app startup).
        Returns False if another instance is already running (notified and should exit).
        """
        if sys.platform == "win32":
            return self._acquire_windows()
        else:
            return self._acquire_posix()

    def _acquire_windows(self) -> bool:
        try:
            import ctypes
            import ctypes.wintypes

            ERROR_ALREADY_EXISTS = 183
            kernel32 = ctypes.windll.kernel32

            # Create or open named mutex
            handle = kernel32.CreateMutexW(None, True, self.mutex_name)
            last_err = kernel32.GetLastError()

            if last_err == ERROR_ALREADY_EXISTS:
                # Primary instance already exists
                if handle:
                    kernel32.CloseHandle(handle)
                self._notify_primary_instance()
                return False

            self._mutex_handle = handle
            self._is_primary = True
            self._start_ipc_server()
            atexit.register(self.release)
            return True

        except Exception:
            # Fallback to port-based detection if ctypes mutex fails
            return self._acquire_posix()

    def _acquire_posix(self) -> bool:
        """POSIX / non-Windows fallback using local port check."""
        port = self._read_saved_port()
        if port:
            if self._send_restore_signal(port):
                return False

        self._is_primary = True
        self._start_ipc_server()
        atexit.register(self.release)
        return True

    def _read_saved_port(self) -> Optional[int]:
        try:
            if self._port_file.exists():
                val = self._port_file.read_text(encoding="utf-8").strip()
                if val.isdigit():
                    return int(val)
        except Exception:
            pass
        return None

    def _write_saved_port(self, port: int):
        try:
            self._port_file.parent.mkdir(parents=True, exist_ok=True)
            self._port_file.write_text(str(port), encoding="utf-8")
        except Exception:
            pass

    def _remove_saved_port(self):
        try:
            if self._port_file.exists():
                self._port_file.unlink(missing_ok=True)
        except Exception:
            pass

    def _notify_primary_instance(self):
        """Sends wake-up signal to the primary instance and brings its window to front."""
        notified = False
        port = self._read_saved_port()
        if port:
            notified = self._send_restore_signal(port)

        # Extra defense-in-depth on Windows: use FindWindow and SetForegroundWindow
        if sys.platform == "win32":
            self._activate_existing_window()

        return notified

    def _send_restore_signal(self, port: int) -> bool:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(1.5)
                s.connect(("127.0.0.1", port))
                s.sendall(RESTORE_COMMAND)
                resp = s.recv(32)
                return b"OK" in resp
        except Exception:
            return False

    def _activate_existing_window(self):
        """Finds existing window and requests Windows to restore and focus it."""
        try:
            import ctypes
            user32 = ctypes.windll.user32
            SW_RESTORE = 9

            # Window title defined in GeminiTokenCounterApp
            window_title = "Gemini Token Counter - Desktop Monitor"
            hwnd = user32.FindWindowW(None, window_title)
            if hwnd:
                user32.ShowWindow(hwnd, SW_RESTORE)
                user32.SetForegroundWindow(hwnd)
        except Exception:
            pass

    def _start_ipc_server(self):
        """Binds a localhost TCP socket on an ephemeral port to listen for restore requests."""
        try:
            srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            srv.bind(("127.0.0.1", 0))
            srv.listen(5)
            self._server_socket = srv

            assigned_port = srv.getsockname()[1]
            self._write_saved_port(assigned_port)

            t = threading.Thread(target=self._ipc_listen_loop, daemon=True, name="SingleInstanceIPCListener")
            self._server_thread = t
            t.start()
        except Exception:
            pass

    def _ipc_listen_loop(self):
        """Background listener loop waiting for restore commands with 0% CPU."""
        while not self._released and self._server_socket:
            try:
                conn, _ = self._server_socket.accept()
                with conn:
                    conn.settimeout(1.0)
                    data = conn.recv(128)
                    if RESTORE_COMMAND.strip() in data:
                        conn.sendall(b"OK\n")
                        if self._restore_callback:
                            try:
                                self._restore_callback()
                            except Exception:
                                pass
            except (socket.error, OSError):
                break
            except Exception:
                pass

    def release(self):
        """Cleans up resources upon primary instance exit."""
        if self._released:
            return
        self._released = True

        if self._server_socket:
            try:
                self._server_socket.close()
            except Exception:
                pass
            self._server_socket = None

        self._remove_saved_port()

        if self._mutex_handle and sys.platform == "win32":
            try:
                import ctypes
                ctypes.windll.kernel32.CloseHandle(self._mutex_handle)
            except Exception:
                pass
            self._mutex_handle = None
