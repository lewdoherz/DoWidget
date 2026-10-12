"""Use ordinary temporary directories, not pytest's 'current' directory symlinks.

Windows 11's untrusted-symlink policy rejects those links with WinError 448
under Python 3.14. Each test still receives an isolated, automatically removed
folder; no operating-system security policy needs to be changed.
"""
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest


@pytest.fixture
def tmp_path():
    with TemporaryDirectory(prefix="dowidget-test-") as directory:
        yield Path(directory)
