"""TOML config loader with environment variable interpolation."""

import os
import re
import tomllib
from pathlib import Path

from dotenv import load_dotenv

from ..utils.errors import ConfigError
from .schema import AppConfig


def _interpolate_env_vars(obj: dict | list | str | int | float | bool) -> dict | list | str | int | float | bool:
    """Recursively replace ${ENV_VAR} patterns with environment variable values."""
    if isinstance(obj, str):
        pattern = re.compile(r"\$\{(\w+)\}")
        match = pattern.search(obj)
        if match:
            var_name = match.group(1)
            value = os.environ.get(var_name)
            if value is None:
                raise ConfigError(f"Environment variable '{var_name}' not set (referenced in config)")
            # Full replacement if entire string is one variable, else partial
            if match.group(0) == obj:
                return value
            return pattern.sub(lambda m: os.environ.get(m.group(1), ""), obj)
        return obj
    elif isinstance(obj, dict):
        return {k: _interpolate_env_vars(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_interpolate_env_vars(item) for item in obj]
    return obj


def load_config(config_path: str | Path = "config/settings.toml", env_path: str | Path = ".env") -> AppConfig:
    """Load and validate configuration from TOML file.

    Args:
        config_path: Path to TOML config file.
        env_path: Path to .env file for secrets.

    Returns:
        Validated AppConfig instance.
    """
    config_path = Path(config_path)
    env_path = Path(env_path)

    # Load .env if it exists
    if env_path.exists():
        load_dotenv(env_path)

    # Read TOML
    if not config_path.exists():
        raise ConfigError(f"Config file not found: {config_path}")

    with open(config_path, "rb") as f:
        raw = tomllib.load(f)

    # Interpolate environment variables
    interpolated = _interpolate_env_vars(raw)

    # Validate with Pydantic
    try:
        return AppConfig.model_validate(interpolated)
    except Exception as e:
        raise ConfigError(f"Config validation failed: {e}") from e
