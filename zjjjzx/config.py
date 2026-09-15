from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, time
from pathlib import Path
from typing import Any

from zjjjzx.core.filters import Profile


DEFAULT_CONFIG_NAME = "config.json"
DEFAULT_ENV_NAME = ".env"


def find_file(filename: str, search_paths: list[Path] | None = None) -> Path | None:
    if search_paths is None:
        search_paths = [
            Path.cwd(),
            Path(__file__).resolve().parent.parent,
            Path.home() / ".config" / "zjjjzx",
            Path.home(),
        ]
    for directory in search_paths:
        target = directory / filename
        if target.is_file():
            return target
    return None


def load_dotenv(path: Path | str | None = None) -> Path | None:
    target_path = Path(path) if path else find_file(DEFAULT_ENV_NAME)
    if not target_path or not target_path.is_file():
        return None
    for raw_line in target_path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)
    return target_path


def load_config(path: Path | str | None = None) -> dict[str, Any]:
    target_path = Path(path) if path else find_file(DEFAULT_CONFIG_NAME)
    if not target_path or not target_path.is_file():
        # Fall back to default template if config.json does not exist
        example_path = find_file("config.example.json")
        if example_path and example_path.is_file():
            target_path = example_path
        else:
            raise FileNotFoundError(f"Configuration file not found. Please provide {DEFAULT_CONFIG_NAME}")

    cfg = json.loads(target_path.read_text(encoding="utf-8"))
    base_dir = target_path.parent.resolve()
    cfg["_config_path"] = str(target_path.resolve())
    cfg["_base_dir"] = str(base_dir)

    # Normalize storage paths relative to config file directory to avoid creating
    # accidental databases when running from arbitrary directories like C:\Users\<username>
    if "storage" in cfg:
        for key in ("database", "report"):
            if key in cfg["storage"]:
                raw = Path(cfg["storage"][key])
                if not raw.is_absolute():
                    cfg["storage"][key] = str((base_dir / raw).resolve())

    return cfg


def make_profile(config: dict[str, Any]) -> Profile:
    values = config.get("profile", {})
    return Profile(
        areas=tuple(values.get("areas", [])),
        subjects=tuple(values.get("subjects", [])),
        grades=tuple(values.get("grades", [])),
        min_price=values.get("min_price"),
        max_price=values.get("max_price"),
        max_distance_meters=values.get("max_distance_meters"),
        allow_online=bool(values.get("allow_online", False)),
        conditions=values.get("conditions", ""),
        user_gender=values.get("user_gender", ""),
    )


def evaluation_scope(config: dict[str, Any]) -> str:
    material = json.dumps(
        {
            "profile": config.get("profile", {}),
            "maps": config.get("maps", {}),
            "semantic_schema": 2,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def within_schedule(config: dict[str, Any]) -> bool:
    schedule = config.get("schedule", {})
    now = datetime.now().time()
    start = time.fromisoformat(schedule.get("start", "09:00"))
    end = time.fromisoformat(schedule.get("end", "21:00"))
    return start <= now <= end


def validate_config(config: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    if "source" not in config or "url" not in config["source"]:
        issues.append("配置缺失 source.url 数据源地址")
    if "profile" not in config:
        issues.append("配置缺失 profile 用户偏好")

    maps_cfg = config.get("maps", {})
    map_ak_env = maps_cfg.get("api_key_env", "BAIDU_MAP_AK")
    if not os.getenv(map_ak_env):
        issues.append(f"环境变量中未检测到百度地图 AK ({map_ak_env})，将无法进行距离测算")

    llm_cfg = config.get("llm", {})
    llm_ak_env = llm_cfg.get("api_key_env", "DEEPSEEK_API_KEY")
    if not os.getenv(llm_ak_env) and not llm_cfg.get("url"):
        # Check ~/.deepseek/config.toml
        from pathlib import Path
        if not (Path.home() / ".deepseek" / "config.toml").is_file():
            issues.append(f"未检测到 LLM API Key ({llm_ak_env}) 或 ~/.deepseek/config.toml")

    return issues
