from pathlib import Path
import yaml


def load_app_config(path: Path = Path("config/app.yaml")) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def load_agents_config(path: Path = Path("config/agents.yaml")) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)
