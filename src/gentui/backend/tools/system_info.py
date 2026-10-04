"""Sample tool (read-only, safe). Shows how little a new tool needs: one decorated function."""

import os
import platform
import shutil

from strands import tool

from gentui.backend.registry import register_tool


@register_tool
@tool
def get_system_info() -> dict[str, str]:
    """Get basic facts about the machine the agent runs on: OS, Python version, working directory, free disk space."""
    free_gb = shutil.disk_usage(".").free / 1e9
    return {
        "os": f"{platform.system()} {platform.release()}",
        "python": platform.python_version(),
        "cwd": os.getcwd(),
        "disk_free": f"{free_gb:.1f} GB",
    }
