from __future__ import annotations

from pathlib import Path
import yaml


def load_config(root: Path) -> dict:
    with (root / "configs" / "project.yaml").open(encoding="utf-8") as handle:
        config = yaml.safe_load(handle)
    for key, value in config["paths"].items():
        config["paths"][key] = root / value
    return config
