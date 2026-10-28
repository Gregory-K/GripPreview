import os
from typing import TYPE_CHECKING

import sublime
import sublime_plugin

if TYPE_CHECKING:
    from sublime_types import CommandArgs

from .go_grip import (GRIP_VERSION, SETTINGS, DownloadError, GripBinaryError,
                      GripMissingError, Server, ServerError, download,
                      ensure_server, kill_all, open_in_browser, root_for_file,
                      running, server_for_file, stop, stop_all)

# ~ Constants
# -----------

NAME = 'GripPreview'

# The settings, default and user side by side.
EDIT_SETTINGS_ARGS: CommandArgs = {
    'base_file': f'${{packages}}/{NAME}/{SETTINGS}',
    'default': '{\n\t$0\n}\n',
}


# ~ Lifecycle
# -----------

# go-grip processes outlive ST unless stopped, so stop them on a plugin
# reload or upgrade, and on exit.

def plugin_unloaded() -> None:
    stop_all()


class GripServerExitListener(sublime_plugin.EventListener):

    def on_exit(self) -> None:
        stop_all()


# ~ Messages
# ----------

def _status(message: str) -> None:
    sublime.status_message(f'{NAME}: {message}')


def _error(message: str) -> None:
    sublime.error_message(f'{NAME}\n\n{message}')


# ~ Download
# ----------

def _download_progress(done: int, total: int) -> None:
    if total:
        _status(f'downloading go-grip {GRIP_VERSION}... '
                f'{done * 100 // total}%')
    else:
        _status(f'downloading go-grip {GRIP_VERSION}... {done // 1024} KiB')


def _offer_download(window: sublime.Window) -> bool:
    """Ask to download go-grip, and download it on a yes.

    Runs on the async thread, the download blocks it.

    Returns:
        True when go-grip was downloaded.
    """
    choice = sublime.yes_no_cancel_dialog(
        'go-grip was not found.\n\n'
        f'Download go-grip {GRIP_VERSION} from its GitHub releases '
        '(github.com/chrishrb/go-grip) into Sublime Text\'s Package '
        'Storage?\n\n'
        'Or point "go_grip_binary" in the settings to a go-grip you have.',
        yes_title='Download', no_title='Open Settings', title=NAME)
    if choice == sublime.DialogResult.NO:
        sublime.set_timeout(
            lambda: window.run_command('edit_settings', EDIT_SETTINGS_ARGS))
        return False
    if choice != sublime.DialogResult.YES:
        return False

    _download_progress(0, 0)
    try:
        path = download(_download_progress)
    except DownloadError as e:
        _error(f'go-grip could not be downloaded.\n\n{e}')
        return False
    _status(f'go-grip {GRIP_VERSION} downloaded to {path}')
    return True


# ~ Start
# -------

def _start(window: sublime.Window, start) -> Server | None:
    """Run a server start, reporting a failure.

    A missing go-grip offers a download, then the start runs again.

    Args:
        window: the window to open the settings in, when asked.
        start: a callable returning a Server, e.g. a lambda calling
               ensure_server().

    Returns:
        The server, or None when it failed and was reported.
    """
    try:
        return start()
    except GripMissingError:
        if not _offer_download(window):
            return None
    except (GripBinaryError, ServerError) as e:
        _error(str(e))
        return None

    # go-grip is in Package Storage now.
    try:
        return start()
    except (GripMissingError, GripBinaryError, ServerError) as e:
        _error(str(e))
    return None


def _previewable(view: sublime.View) -> bool:
    """Whether Preview File is available for a view.

    The saved file matches 'preview_selector' or 'preview_extensions'.
    go-grip renders .md files only, the browser shows others as it would.
    """
    file = view.file_name()
    if not file:
        return False
    settings = sublime.load_settings(SETTINGS)

    selector = settings.get('preview_selector') or ''
    if isinstance(selector, str) and selector.strip():
        if view.match_selector(0, selector):
            return True

    extensions = settings.get('preview_extensions') or []
    if not isinstance(extensions, list):
        return False
    name = file.lower()
    for ext in extensions:
        if not isinstance(ext, str) or not ext.strip('.'):
            continue
        # The dot is optional, but always matched, so 'md' misses '.cmd'.
        ext = '.' + ext.lower().lstrip('.')
        if name.endswith(ext):
            return True
    return False


# ~ Preview File
# --------------

class GripPreviewCommand(sublime_plugin.TextCommand):
    """Preview the current file in the browser."""

    def is_enabled(self) -> bool:
        return _previewable(self.view)

    def run(self, edit) -> None:
        file = self.view.file_name()
        window = self.view.window()
        if not file or window is None:
            return
        # go-grip reads the file from disk, and reloads on save.
        dirty = self.view.is_dirty()
        folders = window.folders()
        sublime.set_timeout_async(
            lambda: self._preview(window, file, folders, dirty))

    def _preview(self, window: sublime.Window, file: str,
                 folders: list[str], dirty: bool) -> None:
        root = root_for_file(file, folders)
        _status('starting go-grip...')
        server = _start(window, lambda: server_for_file(file, root))
        if server is None:
            return
        url = open_in_browser(server, file)
        _status(f'{url} (unsaved changes show after a save)' if dirty
                else url)


# ~ Serve Folder
# --------------

class GripPreviewServeFolderCommand(sublime_plugin.WindowCommand):
    """Serve a project folder, with a choice when there are several."""

    def is_enabled(self) -> bool:
        return bool(self.window.folders())

    def run(self) -> None:
        folders = self.window.folders()
        if len(folders) == 1:
            self._serve(folders[0])
            return
        items = [sublime.QuickPanelItem(os.path.basename(f) or f, details=f)
                 for f in folders]

        def on_select(idx: int) -> None:
            if idx >= 0:
                self._serve(folders[idx])

        self.window.show_quick_panel(
            items, on_select, placeholder='Folder to serve')

    def _serve(self, root: str) -> None:
        sublime.set_timeout_async(lambda: self._serve_async(root))

    def _serve_async(self, root: str) -> None:
        _status('starting go-grip...')
        server = _start(self.window, lambda: ensure_server(root))
        if server is None:
            return
        _status(open_in_browser(server))


# ~ Stop Server
# -------------

class GripPreviewStopCommand(sublime_plugin.WindowCommand):
    """Stop a running server, or all of them."""

    def is_enabled(self) -> bool:
        return bool(running())

    def run(self) -> None:
        servers = running()
        if not servers:
            return
        items = [sublime.QuickPanelItem(
                    os.path.basename(s.root) or s.root,
                    details=s.root, annotation=f'port {s.port}')
                 for s in servers]
        if len(servers) > 1:
            items.insert(0, sublime.QuickPanelItem(
                'All servers', annotation=f'{len(servers)} running'))

        def on_select(idx: int) -> None:
            if idx < 0:
                return
            if len(servers) > 1:
                idx -= 1
            target = servers[idx] if idx >= 0 else None
            sublime.set_timeout_async(lambda: self._stop(target))

        self.window.show_quick_panel(
            items, on_select, placeholder='Server to stop')

    def _stop(self, server: Server | None) -> None:
        if server is None:
            stop_all()
            _status('stopped all servers')
            return
        stop(server.root)
        _status(f'stopped the server for {server.root}')


class GripPreviewStopForceAllCommand(sublime_plugin.WindowCommand):
    """End every go-grip process, also the ones this session does not know,
    e.g. left over from a crash."""

    def run(self) -> None:
        confirmed = sublime.ok_cancel_dialog(
            'End every go-grip process on this computer?\n\n'
            'This also ends go-grip servers not started by this Sublime Text '
            'session, e.g. ones left over from a crash, or started in a '
            'terminal.',
            ok_title='End All', title=NAME)
        if confirmed:
            sublime.set_timeout_async(self._kill)

    def _kill(self) -> None:
        if kill_all():
            _status('ended all go-grip processes')
        else:
            _status('no other go-grip processes were running')
