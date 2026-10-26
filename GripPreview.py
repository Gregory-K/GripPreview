import os

import sublime
import sublime_plugin

from .go_grip import (SETTINGS, GripBinaryError, GripMissingError, Server,
                      ServerError, ensure_server, kill_all, open_in_browser,
                      root_for_file, running, server_for_file, stop, stop_all)

# ~ Constants
# -----------

NAME = 'GripPreview'


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


def _missing() -> None:
    _error(
        'go-grip was not found.\n\n'
        'Install it from https://github.com/chrishrb/go-grip and put it in '
        'PATH, or set "go_grip_binary" in the package settings.')


def _start(start) -> Server | None:
    """Run a server start, reporting a failure.

    Args:
        start: a callable returning a Server, e.g. a lambda calling
               ensure_server().

    Returns:
        The server, or None when it failed and was reported.
    """
    try:
        return start()
    except GripMissingError:
        _missing()
    except (GripBinaryError, ServerError) as e:
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


def _readme(root: str) -> str | None:
    # What go-grip opens when started on a folder itself.
    readme = os.path.join(root, 'README.md')
    return readme if os.path.isfile(readme) else None


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
            lambda: self._preview(file, folders, dirty))

    def _preview(self, file: str, folders: list[str], dirty: bool) -> None:
        root = root_for_file(file, folders)
        _status('starting go-grip...')
        server = _start(lambda: server_for_file(file, root))
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
        server = _start(lambda: ensure_server(root))
        if server is None:
            return
        _status(open_in_browser(server, _readme(root)))


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
