"""This Mac's load, for the hub's system monitor: drawing pictures and rendering video lean on it hard."""
import os
import re
import shutil
import subprocess

from .config import ROOT


def _percent(part: float, whole: float) -> int | None:
    return round(min(max(part / whole, 0.0), 1.0) * 100) if whole else None


def _memory() -> int | None:
    """Memory in use, the way Activity Monitor counts it: app, wired and compressed pages. None off macOS."""
    try:
        total = int(subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True, timeout=2).stdout)
        stats = subprocess.run(["vm_stat"], capture_output=True, text=True, timeout=2).stdout
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None
    size = int(re.search(r"page size of (\d+)", stats).group(1)) if "page size of" in stats else 16384
    pages = {k.strip(): int(v.strip().rstrip(".")) for k, v in re.findall(r"^([^:\n]+):\s+(\d+)\.?$", stats, re.M)}
    used = pages.get("Anonymous pages", pages.get("Pages active", 0)) - pages.get("Pages purgeable", 0)
    used += pages.get("Pages wired down", 0) + pages.get("Pages occupied by compressor", 0)
    return _percent(used * size, total)


def machine() -> dict:
    cores = os.cpu_count() or 1
    disk = shutil.disk_usage(ROOT)
    return {
        "cpu": _percent(os.getloadavg()[0], cores),
        "memory": _memory(),
        "disk": _percent(disk.used, disk.total),
        "disk_free_gb": round(disk.free / 1e9),
        "image_model": (ROOT / "models" / "flux-schnell-4bit" / "transformer").is_dir(),
    }
