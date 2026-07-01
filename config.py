import os
from typing import Optional, List, Dict, Any

try:
    import yaml  # type: ignore
except Exception:
    yaml = None  # type: ignore

from pydantic import BaseModel, Field


class RateLimitConfig(BaseModel):
    enabled: bool = True
    qps: float = 5.0


class ServerConfig(BaseModel):
    host: str = "localhost"
    port: int = 8080
    log_level: str = "INFO"
    rate_limit: RateLimitConfig = Field(default_factory=RateLimitConfig)


class RegistryConfig(BaseModel):
    enable_builtin: bool = True
    enable_vika_tools: bool = True
    enabled_toolsets: List[str] = Field(default_factory=list)


class CacheConfig(BaseModel):
    enabled: bool = True
    db_path: Optional[str] = None
    ttl_hours: int = 24


class VikaConfig(BaseModel):
    api_token: Optional[str] = None
    host: str = "https://vika.cn"
    default_space_id: Optional[str] = None
    workbench_url: Optional[str] = None
    workbench_space_id: Optional[str] = None
    cache_duration_hours: int = 24
    attachment_download_allowed_hosts: List[str] = Field(default_factory=list)




class AppConfig(BaseModel):
    version: str = "v1"
    server: ServerConfig = Field(default_factory=ServerConfig)
    registry: RegistryConfig = Field(default_factory=RegistryConfig)
    cache: CacheConfig = Field(default_factory=CacheConfig)
    vika: VikaConfig = Field(default_factory=VikaConfig)


def _deep_update(d: Dict[str, Any], u: Dict[str, Any]) -> Dict[str, Any]:
    for k, v in (u or {}).items():
        if isinstance(v, dict) and isinstance(d.get(k), dict):
            _deep_update(d[k], v)
        else:
            d[k] = v
    return d


def _parse_list_value(value: str) -> List[str]:
    return [x.strip() for x in str(value).split(",") if str(x).strip()]


def _set_nested(d: Dict[str, Any], keys: List[str], value: Any) -> None:
    cur = d
    for k in keys[:-1]:
        if k not in cur or not isinstance(cur[k], dict):
            cur[k] = {}
        cur = cur[k]
    cur[keys[-1]] = value


def _load_yaml_file(path: str, *, required: bool = False) -> Dict[str, Any]:
    if not path:
        return {}
    if not os.path.exists(path) or not os.path.isfile(path):
        if required:
            raise ValueError(f"Config file not found: {path}")
        return {}
    if yaml is None:
        raise ValueError("PyYAML is required to load config files.")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except Exception as exc:
        raise ValueError(f"Failed to parse config file {path}: {exc}") from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError(f"Config file {path} must contain a YAML mapping at the top level.")
    return data


def _collect_env_overrides() -> Dict[str, Any]:
    """
    收集环境变量覆盖项：
    - 嵌套：VIKAMCP_SERVER__PORT 等（双下划线分割）
    """
    prefix = "VIKAMCP_"
    env_data: Dict[str, Any] = {}

    list_fields = {
        "registry.enabled_toolsets",
        "vika.attachment_download_allowed_hosts",
    }

    for raw_key, raw_value in os.environ.items():
        if raw_key == "VIKAMCP_CONFIG":
            continue

        # 嵌套：双下划线
        if raw_key.startswith(prefix):
            rest = raw_key[len(prefix):]
            if "__" in rest:
                parts = [p.strip().lower() for p in rest.split("__") if p.strip()]
                if not parts:
                    continue
                dot_path = ".".join(parts)
                value: Any = raw_value
                if dot_path in list_fields:
                    value = _parse_list_value(raw_value)
                _set_nested(env_data, parts, value)
                continue

    return env_data


def load_config(config_path: Optional[str] = None) -> AppConfig:
    """
    合并优先级：环境变量 > YAML 文件 > 默认值
    - YAML 路径优先级：参数 config_path > 环境变量 VIKAMCP_CONFIG > 默认 vika_mcp.yaml（若存在）
    """
    env_config_path = os.getenv("VIKAMCP_CONFIG")
    explicit_path = config_path or env_config_path
    yaml_path = explicit_path or "vika_mcp.yaml"

    yaml_data: Dict[str, Any] = {}
    if explicit_path:
        yaml_data = _load_yaml_file(yaml_path, required=True) or {}
    elif yaml_path and os.path.exists(yaml_path):
        yaml_data = _load_yaml_file(yaml_path, required=True) or {}

    env_overrides = _collect_env_overrides()

    # 默认 -> YAML -> ENV
    defaults = AppConfig()
    base_dict = (
        defaults.model_dump()
        if hasattr(defaults, "model_dump")
        else defaults.dict()
    )
    merged = _deep_update(base_dict, yaml_data)
    merged = _deep_update(merged, env_overrides)

    # Pydantic 构造与校验
    if hasattr(AppConfig, "model_validate"):
        cfg = AppConfig.model_validate(merged)
    else:
        cfg = AppConfig.parse_obj(merged)

    return cfg


__all__ = [
    "ServerConfig",
    "RateLimitConfig",
    "RegistryConfig",
    "CacheConfig",
    "VikaConfig",
    "AppConfig",
    "load_config",
]
