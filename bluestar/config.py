"""Persisted pairing data: the token (uat) the AC was bound with, and what it told us about itself."""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

PATH = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "bluestar-ac" / "device.json"


@dataclass
class DeviceConfig:
    uat: str = ""            # token chosen at pairing; also the AES key (first 16 chars) for status pushes
    pid: str = ""            # device id the AC reported at pairing
    address: str = ""        # BLE address
    info: dict = field(default_factory=dict)   # everything else from the type-6 reply (firmware versions...)

    @property
    def paired(self) -> bool:
        return len(self.uat) >= 16


def load() -> DeviceConfig:
    try:
        return DeviceConfig(**json.loads(PATH.read_text()))
    except (OSError, ValueError, TypeError):
        return DeviceConfig()


def save(cfg: DeviceConfig) -> None:
    PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(asdict(cfg), indent=2))
    os.chmod(tmp, 0o600)
    tmp.replace(PATH)
