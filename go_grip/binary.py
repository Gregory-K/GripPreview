import os
import re
import shutil
import subprocess
from typing import NamedTuple

import sublime

# ~ Constants
# -----------

PACKAGE = 'GripPreview'
SETTINGS = 'GripPreview.sublime-settings'

# Upstream release (chrishrb/go-grip) that a download fetches, and the
# folder name a downloaded copy is stored under.
GRIP_VERSION = 'v0.10.0'

BINARY_NAME = 'go-grip.exe' if sublime.platform() == 'windows' else 'go-grip'


# ~ Errors
# --------

class GripBinaryError(Exception):
    """The 'go_grip_binary' setting names a binary that cannot be used."""


# ~ Paths
# -------

def storage_dir(version: str = GRIP_VERSION) -> str:
    """Folder that holds a downloaded go-grip of the given version.

    Package Storage sits next to Packages, so package upgrades leave it
    alone.

    Args:
        version: release tag, e.g. 'v0.10.0'.

    Returns:
        The folder path, which may not exist yet.
    """
    data = os.path.dirname(sublime.packages_path())
    return os.path.join(data, 'Package Storage', PACKAGE, 'go-grip', version)


def stored_binary(version: str = GRIP_VERSION) -> str:
    """Path of the downloaded go-grip binary of the given version."""
    return os.path.join(storage_dir(version), BINARY_NAME)


def _is_executable(path: str) -> bool:
    return os.path.isfile(path) and os.access(path, os.X_OK)


# ~ Resolver
# ----------

class Resolved(NamedTuple):
    path: str
    # 'setting', 'path' or 'storage'
    source: str


def _from_setting(value: str) -> str:
    # A bare name is looked up in PATH, anything else is a file path.
    if os.sep not in value and '/' not in value:
        found = shutil.which(value)
        if found is None:
            raise GripBinaryError(
                f"go_grip_binary: '{value}' was not found in PATH")
        return found
    path = os.path.expandvars(os.path.expanduser(value))
    if not _is_executable(path):
        raise GripBinaryError(
            f"go_grip_binary: '{path}' is not an executable file")
    return path


def resolve() -> Resolved | None:
    """Find the go-grip binary to run.

    Order, first hit wins:
    1. the 'go_grip_binary' setting, when set
    2. go-grip in PATH
    3. the copy downloaded to Package Storage, for GRIP_VERSION

    A set but unusable 'go_grip_binary' raises instead of falling back, so a
    typo in it is not hidden by another go-grip.

    Returns:
        The binary and where it came from, or None when there is none, which
        is the cue to offer a download.

    Raises:
        GripBinaryError: the 'go_grip_binary' setting cannot be used.
    """
    settings = sublime.load_settings(SETTINGS)
    value = settings.get('go_grip_binary') or ''
    if not isinstance(value, str):
        raise GripBinaryError(
            f'go_grip_binary: expected a string, got {value!r}')
    value = value.strip()
    if value:
        return Resolved(_from_setting(value), 'setting')

    found = shutil.which('go-grip')
    if found is not None:
        return Resolved(found, 'path')

    stored = stored_binary()
    if _is_executable(stored):
        return Resolved(stored, 'storage')

    return None


# ~ Version
# ---------

def binary_version(path: str) -> str | None:
    """Ask a go-grip binary for its version.

    '--version' exists since v0.10.0. Older binaries fail on it, and so do
    files that are not go-grip at all.

    Args:
        path: the go-grip binary.

    Returns:
        The version, e.g. 'v0.10.0', or None when it cannot be told.
    """
    # No console window flashing up for a GUI-less call. Only Windows has the
    # flag, and 0 (the default) is the only value other platforms accept.
    flags = 0
    if sublime.platform() == 'windows':
        flags = subprocess.CREATE_NO_WINDOW
    try:
        result = subprocess.run(
            [path, '--version'], capture_output=True, text=True, timeout=5,
            creationflags=flags)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    # Prints 'go-grip <version>', and a go install build may add a commit
    # and date after it.
    match = re.search(r'\bv?\d+\.\d+\.\d+\S*', result.stdout)
    return match.group(0) if match else None
