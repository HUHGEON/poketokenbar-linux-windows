"""Options for background helpers that must not open a Windows console."""

import subprocess
import sys


def background_options() -> dict:
    return {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}
