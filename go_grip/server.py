import os
import socket
import subprocess
import threading
import time
import webbrowser
from collections import deque
from dataclasses import dataclass, field
from urllib.parse import quote

import sublime

from .binary import BINARY_NAME, SETTINGS, GripBinaryError, resolve

# ~ Constants
# -----------

HOST = 'localhost'

# Seconds to wait for a new server to accept connections.
START_TIMEOUT = 5.0

# Lines of go-grip output kept per server, for error messages.
OUTPUT_LINES = 20


# ~ Errors
# --------

class GripMissingError(Exception):
    """No go-grip binary was found, the cue to offer a download."""


class ServerError(Exception):
    """A go-grip server could not be started."""


# ~ Server
# --------

@dataclass
class Server:
    root: str
    port: int
    process: subprocess.Popen
    output: deque = field(default_factory=lambda: deque(maxlen=OUTPUT_LINES))

    def alive(self) -> bool:
        return self.process.poll() is None

    def url(self, file: str | None = None) -> str:
        """URL of the root, or of a file under the root."""
        base = f'http://{HOST}:{self.port}/'
        if file is None:
            return base
        rel = os.path.relpath(file, self.root).replace(os.sep, '/')
        return base + quote(rel)

    def contains(self, file: str) -> bool:
        return _is_under(file, self.root)


# Running servers by root key, guarded by _lock. Commands run on the async
# thread, and stop_all() also runs on the main thread when ST exits.
_servers: dict[str, Server] = {}
_lock = threading.Lock()


# ~ Paths
# -------

def _key(path: str) -> str:
    return os.path.normcase(os.path.abspath(path))


def _is_under(path: str, root: str) -> bool:
    path, root = _key(path), _key(root)
    try:
        return os.path.commonpath([path, root]) == root
    except ValueError:
        # Different drives on Windows.
        return False


def root_for_file(file: str, folders: list[str]) -> str:
    """Folder to serve a file from.

    The window's project folder that holds the file, so links up to that
    folder work, since go-grip serves nothing above its root. A file outside
    the project is served from its own folder.

    Args:
        file: the Markdown file.
        folders: the window's folders, window.folders().

    Returns:
        The folder to serve.
    """
    holding = [f for f in folders if _is_under(file, f)]
    if holding:
        # Nested project folders: the outermost one covers the most links.
        return min(holding, key=len)
    return os.path.dirname(file)


# ~ Ports
# -------

def _port_setting() -> int:
    port = sublime.load_settings(SETTINGS).get('port') or 0
    # bool is an int too, so 'true' would pass as port 1.
    if (not isinstance(port, int) or isinstance(port, bool)
            or not 0 <= port <= 65535):
        raise ServerError(f'port: expected 0 to 65535, got {port!r}')
    return port


def _bindable(port: int) -> bool:
    # go-grip listens on all interfaces (':port'), so test the same way.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind(('', port))
        except OSError:
            return False
    return True


def free_port() -> int:
    """A port that is free right now.

    Another program may take it before go-grip does. go-grip then fails to
    start, and the start reports so.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(('', 0))
        return sock.getsockname()[1]


def _pick_port() -> int:
    port = _port_setting()
    if port == 0:
        return free_port()
    for server in _servers.values():
        if server.port == port and server.alive():
            raise ServerError(
                f'port {port} is taken by the server for {server.root}, '
                'stop it or set "port" to 0')
    # A taken port would also look ready to _wait_ready(), with the other
    # process answering, so check it before starting.
    if not _bindable(port):
        raise ServerError(f'port {port} is taken by another program')
    return port


# ~ Start & Stop
# --------------

def _drain(server: Server) -> None:
    # Keeps the pipe from filling up, and the last lines for error messages.
    stdout = server.process.stdout
    if stdout is None:
        return
    for line in stdout:
        server.output.append(line.rstrip())


def _wait_ready(server: Server) -> bool:
    deadline = time.monotonic() + START_TIMEOUT
    while time.monotonic() < deadline:
        if not server.alive():
            return False
        try:
            with socket.create_connection((HOST, server.port), timeout=0.2):
                return server.alive()
        except OSError:
            time.sleep(0.05)
    return False


def _terminate(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def _start(root: str) -> Server:
    resolved = resolve()
    if resolved is None:
        raise GripMissingError('go-grip was not found')
    port = _pick_port()
    # No file argument: go-grip serves its working directory. A file path
    # would be split on '/' only, which breaks Windows paths.
    args = [resolved.path, '--browser=false', '--port', str(port)]
    # No console window flashing up. Only Windows has the flag, and 0 (the
    # default) is the only value other platforms accept.
    flags = 0
    if sublime.platform() == 'windows':
        flags = subprocess.CREATE_NO_WINDOW
    try:
        process = subprocess.Popen(
            args, cwd=root, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, encoding='utf-8',
            errors='replace', creationflags=flags)
    except OSError as e:
        raise ServerError(f'cannot run {resolved.path}: {e}') from e

    server = Server(root, port, process)
    threading.Thread(target=_drain, args=(server,), daemon=True).start()
    if not _wait_ready(server):
        _terminate(process)
        output = '\n'.join(server.output) or '(no output)'
        raise ServerError(
            f'go-grip did not start on port {port} for {root}:\n{output}')
    return server


def ensure_server(root: str) -> Server:
    """The running server for a root, started if there is none.

    Blocks up to START_TIMEOUT seconds on a start, so call it off the main
    thread.

    Raises:
        GripMissingError: no go-grip binary was found.
        GripBinaryError: the 'go_grip_binary' setting cannot be used.
        ServerError: the server could not be started.
    """
    with _lock:
        key = _key(root)
        server = _servers.get(key)
        if server is not None and server.alive():
            return server
        server = _start(root)
        _servers[key] = server
        return server


def server_for_file(file: str, root: str) -> Server:
    """A server that covers a file, reusing a running one if possible.

    A running server whose root holds the file is reused, the one with the
    outermost root first. Otherwise a server is started for root.

    Raises:
        Same as ensure_server().
    """
    with _lock:
        holding = [s for s in _servers.values()
                   if s.alive() and s.contains(file)]
    if holding:
        return min(holding, key=lambda s: len(s.root))
    return ensure_server(root)


def running() -> list[Server]:
    """The running servers, outermost root first."""
    with _lock:
        servers = [s for s in _servers.values() if s.alive()]
    return sorted(servers, key=lambda s: s.root)


def stop(root: str) -> bool:
    """Stop the server for a root. Returns False when there was none."""
    with _lock:
        server = _servers.pop(_key(root), None)
    if server is None:
        return False
    _terminate(server.process)
    return True


def stop_all() -> None:
    with _lock:
        servers = list(_servers.values())
        _servers.clear()
    for server in servers:
        _terminate(server.process)


def _binary_name() -> str:
    # The configured binary may go by another name, e.g. 'go-grip-dev'.
    try:
        resolved = resolve()
    except GripBinaryError:
        resolved = None
    return os.path.basename(resolved.path) if resolved else BINARY_NAME


def kill_all() -> bool:
    """End every go-grip process on the computer, by name.

    Also ends servers this session does not know of, e.g. ones left over
    from a session that crashed, and ones started outside ST.

    Returns:
        False when no go-grip process was found besides this session's.
    """
    stop_all()
    name = _binary_name()
    if sublime.platform() == 'windows':
        args = ['taskkill', '/F', '/IM', name]
        flags = subprocess.CREATE_NO_WINDOW
    else:
        args = ['pkill', '-x', name]
        flags = 0
    try:
        result = subprocess.run(
            args, capture_output=True, creationflags=flags)
    except OSError:
        return False
    # Both exit with 0 only when they ended something.
    return result.returncode == 0


# ~ Browser
# ---------

def open_in_browser(server: Server, file: str | None = None) -> str:
    """Open the root, or a file under it, in the default browser.

    Returns:
        The opened URL.
    """
    url = server.url(file)
    webbrowser.open(url)
    return url
