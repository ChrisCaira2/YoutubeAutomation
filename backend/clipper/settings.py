"""The clipper's tunables come from config.toml; secrets only from the environment or the git-ignored .env."""
import logging
import os
import tomllib
from pathlib import Path

from studio.config import ROOT  # also loads .env

HERE = Path(__file__).resolve().parent


def load(path: Path | None = None, **overrides: dict) -> dict:
    """The config, with paths made absolute. Overrides replace single values per section, for tests."""
    cfg = tomllib.loads(Path(path or os.getenv("CLIPPER_CONFIG") or HERE / "config.toml").read_text())
    for section, values in overrides.items():
        cfg.setdefault(section, {}).update(values)
    cfg["paths"] = {k: Path(v) if Path(v).is_absolute() else ROOT / v for k, v in cfg["paths"].items()}
    return cfg


def logger(cfg: dict) -> logging.Logger:
    log = logging.getLogger("clipper")
    if not log.handlers:
        log.setLevel(logging.INFO)
        cfg["paths"]["log"].parent.mkdir(parents=True, exist_ok=True)
        for handler in (logging.StreamHandler(), logging.FileHandler(cfg["paths"]["log"])):
            handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S"))
            log.addHandler(handler)
    return log
