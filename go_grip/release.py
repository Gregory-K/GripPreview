import hashlib
import io
import os
import posixpath
import re
import tarfile
import threading
import urllib.request
import zipfile
from collections.abc import Callable

import sublime

from .binary import (BINARY_NAME, GRIP_VERSION, PACKAGE, binary_version,
                     storage_dir, stored_binary)

# ~ Constants
# -----------

RELEASES_URL = 'https://github.com/chrishrb/go-grip/releases/download'

# Seconds without data before a download gives up.
TIMEOUT = 30

CHUNK_SIZE = 64 * 1024

# sublime.platform() and sublime.arch() to the release asset names.
GOOS = {'windows': 'windows', 'osx': 'darwin', 'linux': 'linux'}
GOARCH = {'x32': '386', 'x64': 'amd64', 'arm64': 'arm64'}

# Kept next to the binary, go-grip is MIT licensed.
LICENSE = 'LICENSE'

# One download at a time, a second caller waits and reuses its result.
_lock = threading.Lock()


# ~ Errors
# --------

class DownloadError(Exception):
    """go-grip could not be downloaded."""


# ~ Release Assets
# ----------------

def asset_name(version: str = GRIP_VERSION) -> str:
    """Name of the release archive for this system.

    Args:
        version: release tag, e.g. 'v0.10.0'.

    Returns:
        e.g. 'go-grip-v0.10.0-windows-amd64.zip'.

    Raises:
        DownloadError: go-grip has no release for this system.
    """
    goos = GOOS.get(sublime.platform())
    goarch = GOARCH.get(sublime.arch())
    # No 32-bit macOS build.
    if goos is None or goarch is None or (goos, goarch) == ('darwin', '386'):
        raise DownloadError(
            f'go-grip has no release for {sublime.platform()} '
            f'{sublime.arch()}')
    ext = 'zip' if goos == 'windows' else 'tar.gz'
    return f'go-grip-{version}-{goos}-{goarch}.{ext}'


def asset_url(name: str, version: str = GRIP_VERSION) -> str:
    return f'{RELEASES_URL}/{version}/{name}'


# ~ Fetch & Verify
# ----------------

def _fetch(url: str,
           progress: Callable[[int, int], None] | None = None) -> bytes:
    request = urllib.request.Request(url, headers={'User-Agent': PACKAGE})
    chunks = []
    done = 0
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            total = int(response.headers.get('Content-Length') or 0)
            while chunk := response.read(CHUNK_SIZE):
                chunks.append(chunk)
                done += len(chunk)
                if progress is not None:
                    progress(done, total)
    except (OSError, ValueError) as e:
        # urllib's URLError and HTTPError are OSErrors.
        raise DownloadError(f'cannot download {url}:\n{e}') from e
    return b''.join(chunks)


def _expected_md5(text: str) -> str:
    # The .md5 asset holds the hash alone, 'md5sum' output would add the
    # file name after it.
    match = re.match(r'\s*([0-9a-fA-F]{32})\b', text)
    if match is None:
        raise DownloadError(f'unexpected checksum file: {text[:80]!r}')
    return match.group(1).lower()


def _extract(archive: bytes, name: str) -> dict[str, bytes]:
    # Only the binary and its licence, by base name, so no path in the
    # archive is ever written to disk as such.
    wanted = {BINARY_NAME, LICENSE}
    found = {}
    if name.endswith('.zip'):
        with zipfile.ZipFile(io.BytesIO(archive)) as zf:
            for info in zf.infolist():
                base = posixpath.basename(info.filename)
                if not info.is_dir() and base in wanted:
                    found[base] = zf.read(info)
    else:
        with tarfile.open(fileobj=io.BytesIO(archive), mode='r:gz') as tf:
            for member in tf.getmembers():
                base = posixpath.basename(member.name)
                if member.isfile() and base in wanted:
                    data = tf.extractfile(member)
                    if data is not None:
                        found[base] = data.read()
    if BINARY_NAME not in found:
        raise DownloadError(f'{BINARY_NAME} is missing from {name}')
    return found


def _write(path: str, data: bytes, executable: bool = False) -> None:
    # Written next to the target, then swapped in, so an interrupted
    # download never leaves a half-written binary that resolve() finds.
    part = path + '.part'
    with open(part, 'wb') as f:
        f.write(data)
    if executable and sublime.platform() != 'windows':
        os.chmod(part, 0o755)
    os.replace(part, path)


def _discard(path: str) -> None:
    # Removes a rejected binary, and its folder when nothing else is in it.
    os.remove(path)
    try:
        os.rmdir(os.path.dirname(path))
    except OSError:
        pass


# ~ Download
# ----------

def download(progress: Callable[[int, int], None] | None = None,
             version: str = GRIP_VERSION) -> str:
    """Download go-grip from its GitHub releases into Package Storage.

    Fetches the release archive for this system, checks it against the
    release's MD5 checksum, and keeps the binary and its licence. Blocks
    for the whole download, so call it off the main thread.

    Args:
        progress: called with (bytes done, bytes total) while the archive
                  downloads. The total is 0 when the server does not tell.
        version: release tag to download.

    Returns:
        Path of the downloaded binary.

    Raises:
        DownloadError: no release for this system, a network error,
                       a checksum mismatch, a binary that does not run,
                       or one that reports another version.
    """
    with _lock:
        target = stored_binary(version)
        # Another caller downloaded it while this one waited.
        if os.path.isfile(target):
            return target

        name = asset_name(version)
        url = asset_url(name, version)
        expected = _expected_md5(
            _fetch(url + '.md5').decode('ascii', 'replace'))
        archive = _fetch(url, progress)
        actual = hashlib.md5(archive, usedforsecurity=False).hexdigest()
        if actual != expected:
            raise DownloadError(
                f'checksum mismatch for {name}:\n'
                f'expected {expected}, got {actual}')

        files = _extract(archive, name)
        os.makedirs(storage_dir(version), exist_ok=True)
        _write(target, files[BINARY_NAME], executable=True)

        got = binary_version(target)
        if got is None:
            _discard(target)
            raise DownloadError(
                f'the downloaded {BINARY_NAME} does not run on this system')
        # The checksum comes from the same release, so only the binary
        # itself can tell that the release is the one asked for.
        if got.lstrip('v') != version.lstrip('v'):
            _discard(target)
            raise DownloadError(
                f'the downloaded {BINARY_NAME} reports {got}, '
                f'expected {version}')

        # Only next to a binary that is kept.
        if LICENSE in files:
            _write(os.path.join(storage_dir(version), LICENSE),
                   files[LICENSE])
        return target
