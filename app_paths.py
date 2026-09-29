"""Persistent user data is separate from bundled, read-only resources."""
import os
from pathlib import Path
import sys


def user_data_dir():
    override = os.environ.get("FLYBRAINPET_DATA_DIR")
    if override:
        return Path(override).expanduser()
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "FlyBrainPet"
    return Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "FlyBrainPet"
