import json
from pathlib import Path

CONFIG_DIR = Path.home() / ".tasky"
CONFIG_FILE = CONFIG_DIR / "config.json"

DEFAULT_VIEW_SETTINGS = {
    "sort_by": "priority",
    "filter_project": None,
    "filter_priority": None,
    "theme": "textual-dark",
    "hide_done": False,
    "border_color": "#00FF00",
    "bg_color": "",
}


def config_exists() -> bool:
    return CONFIG_FILE.exists()


def load_config() -> dict:
    with open(CONFIG_FILE) as f:
        data = json.load(f)
    if "view_settings" not in data:
        data["view_settings"] = DEFAULT_VIEW_SETTINGS.copy()
    return data


def save_config(data: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(data, f, indent=2)


def save_view_settings(vs: dict) -> None:
    data = load_config()
    data["view_settings"] = {
        "sort_by": vs.get("sort_by", "priority"),
        "filter_project": vs.get("filter_project"),
        "filter_priority": vs.get("filter_priority"),
        "theme": vs.get("theme", "textual-dark"),
        "hide_done": vs.get("hide_done", False),
        "border_color": vs.get("border_color", "#00FF00"),
        "bg_color": vs.get("bg_color", ""),
    }
    save_config(data)
