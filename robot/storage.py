import json
import os
from typing import Any

from robot.servo import DEFAULT_SERVOS

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")


def _ensure_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


def load_json(filename: str, default: Any = None) -> Any:
    path = os.path.join(DATA_DIR, filename)
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return default


def save_json(filename: str, data: Any):
    _ensure_dir()
    path = os.path.join(DATA_DIR, filename)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    try:
        os.replace(tmp, path)
    except OSError as e:
        print(f"Warning: Could not save {filename}: {e}")


def load_animations() -> list[dict]:
    return load_json("animations.json", [])


def save_animations(animations: list[dict]):
    save_json("animations.json", animations)


def load_servo_config() -> dict:
    default = {
        s.id: {"pin": s.pin, "min": s.min_angle, "max": s.max_angle, "center": s.center, "name": s.name}
        for s in DEFAULT_SERVOS
    }
    return load_json("servo_config.json", default)


def save_servo_config(config: dict):
    save_json("servo_config.json", config)


def load_key_bindings() -> dict[str, str]:
    return load_json("key_bindings.json", {})


def save_key_bindings(bindings: dict[str, str]):
    save_json("key_bindings.json", bindings)


def load_settings() -> dict:
    return load_json("settings.json", {"idle_animation": None, "paused": False})


def save_settings(settings: dict):
    save_json("settings.json", settings)
