import os
from typing import Optional, List, Dict, Any

try:
    import yaml  # type: ignore
except Exception:
    yaml = None  # type: ignore

from pydantic import BaseModel


class ServerConfig(BaseModel):
    host: str = "localhost"
    port: int = 8080
    log_level: str = "INFO"


class AuthConfig(BaseModel):
    enabled: bool = False
    api_keys: List[str] = []
    allow_headers: List[str] = ["X-API-Key", "Authorization"]


class SSEConfig(BaseModel):
    heartbeat_interval_secs: int = 15
    retry_ms: int = 3000
    buffer_ttl_secs: int = 600
    buffer_size: int = 1000


class ExecutorConfig(BaseModel):
    max_workers: int = 4
    queue_size: int = 100
    task_timeout_ms: int = 60000


class JobsConfig(BaseModel):
    ttl_secs: int = 3600


class RegistryConfig(BaseModel):
    enable_builtin: bool = True
    enable_vika_tools: bool = True
    auto_discover: bool = True
    enabled_toolsets: List[str] = []


class CacheConfig(BaseModel):
    enabled: bool = True
    db_path: Optional[str] = None
    ttl_hours: int = 24


class VikaConfig(BaseModel):
    api_token: Optional[str] = None
    host: str = "https://vika.cn"
    default_space_id: Optional[str] = None
    auto_sync_on_startup: bool = True
    cache_duration_hours: int = 24




class AppConfig(BaseModel):
    version: str = "v1"
    server: ServerConfig = ServerConfig()
    auth: AuthConfig = AuthConfig()
    sse: SSEConfig = SSEConfig()
    executor: ExecutorConfig = ExecutorConfig()
    jobs: JobsConfig = JobsConfig()
    registry: RegistryConfig = RegistryConfig()
    cache: CacheConfig = CacheConfig()
    vika: VikaConfig = VikaConfig()

    # 兼容旧用法：顶层透传属性
    @property
    def api_keys(self) -> List[str]:
        return self.auth.api_keys

    @property
    def sse_heartbeat_interval_secs(self) -> int:
        return self.sse.heartbeat_interval_secs

    @property
    def executor_max_workers(self) -> int:
        return self.executor.max_workers


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


def _load_yaml_file(path: str) -> Dict[str, Any]:
    if not path:
        return {}
    try:
        if os.path.exists(path) and os.path.isfile(path):
            if yaml is not None:
                with open(path, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
                    if isinstance(data, dict):
                        return data
            return {}
    except Exception:
        return {}
    return {}


def _collect_env_overrides() -> Dict[str, Any]:
    """
    收集环境变量覆盖项：
    - 平铺：VIKAMCP_API_KEYS、VIKAMCP_API_KEY
    - 嵌套：VIKAMCP_SERVER__PORT 等（双下划线分割）
    - 兼容旧名：VIKAMCP_SSE_HEARTBEAT_INTERVAL_SECS、VIKAMCP_EXECUTOR_MAX_WORKERS
    - 兼容外部：VIKA_API_TOKEN -> vika.api_token；VIKA_API_BASE -> vika.host
    """
    prefix = "VIKAMCP_"
    env_data: Dict[str, Any] = {}

    compat_map = {
            "VIKAMCP_SSE_HEARTBEAT_INTERVAL_SECS": "sse.heartbeat_interval_secs",
            "VIKAMCP_EXECUTOR_MAX_WORKERS": "executor.max_workers",
    
            # Nested alias support (map to existing internal fields)
            "VIKAMCP_AUTH__API_KEY": "auth.api_keys",
            "VIKAMCP_SSE__HEARTBEAT_INTERVAL": "sse.heartbeat_interval_secs",
            "VIKAMCP_SSE__RETRY": "sse.retry_ms",
            "VIKAMCP_EXECUTOR__WORKERS": "executor.max_workers",
            "VIKAMCP_JOBS__EXPIRATION_SECONDS": "jobs.ttl_secs",
            "VIKAMCP_REGISTRY__ENABLE_BUILTIN": "registry.enable_builtin",
            "VIKAMCP_REGISTRY__ENABLE_VIKA": "registry.enable_vika_tools",
            "VIKAMCP_CACHE__ENABLED": "cache.enabled",
            "VIKAMCP_CACHE__DB_PATH": "cache.db_path",
            "VIKAMCP_CACHE__TTL_HOURS": "cache.ttl_hours",
        }

    list_fields = {
        "auth.api_keys",
        "auth.allow_headers",
        "registry.enabled_toolsets",
    }

    for raw_key, raw_value in os.environ.items():
        if raw_key == "VIKAMCP_CONFIG":
            continue

        # 平铺 API Key(s)
        if raw_key == "VIKAMCP_API_KEYS" and raw_value:
            _set_nested(env_data, ["auth", "api_keys"], _parse_list_value(raw_value))
            continue
        if raw_key == "VIKAMCP_API_KEY" and raw_value:
            _set_nested(env_data, ["auth", "api_keys"], _parse_list_value(raw_value))
            continue

        # 兼容旧单层命名
        if raw_key in compat_map and raw_value is not None:
            path = compat_map[raw_key]
            if path in list_fields:
                value: Any = _parse_list_value(raw_value)
            else:
                value = raw_value
            _set_nested(env_data, path.split("."), value)
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

        # 兼容：VIKA_API_TOKEN / VIKA_API_BASE
        if raw_key == "VIKA_API_TOKEN" and raw_value:
            _set_nested(env_data, ["vika", "api_token"], raw_value)
            continue
        if raw_key == "VIKA_API_BASE" and raw_value:
            _set_nested(env_data, ["vika", "host"], raw_value)
            continue

    return env_data


def load_config(config_path: Optional[str] = None) -> AppConfig:
    """
    合并优先级：环境变量 > YAML 文件 > 默认值
    - YAML 路径优先级：参数 config_path > 环境变量 VIKAMCP_CONFIG > 默认 vika_mcp.yaml（若存在）
    - 自动鉴权开关：若最终 auth.api_keys 非空，则 auth.enabled=True，否则 False
    """
    yaml_path = config_path or os.getenv("VIKAMCP_CONFIG") or "vika_mcp.yaml"

    yaml_data: Dict[str, Any] = {}
    if yaml_path and os.path.exists(yaml_path):
        yaml_data = _load_yaml_file(yaml_path) or {}

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

    # 自动启用鉴权
    try:
        cfg.auth.enabled = bool(cfg.auth.api_keys)
    except Exception:
        pass

    return cfg


__all__ = [
    "ServerConfig",
    "AuthConfig",
    "SSEConfig",
    "ExecutorConfig",
    "JobsConfig",
    "RegistryConfig",
    "CacheConfig",
    "VikaConfig",
    "AppConfig",
    "load_config",
]
