"""LLM analysis subsystem for dataset processing."""

from __future__ import annotations

import os
from typing import Any, NoReturn

from anysite.llm.errors import ConfigError
from anysite.llm.models import LLMConfig


def check_llm_deps() -> None:
    """Check that optional LLM dependencies are installed.

    Raises:
        SystemExit: If openai or anthropic packages are not installed.
    """
    missing: list[str] = []

    try:
        import openai  # noqa: F401
    except ImportError:
        missing.append("openai")

    try:
        import anthropic  # noqa: F401
    except ImportError:
        missing.append("anthropic")

    if missing:
        _missing_deps_error(missing)


def _missing_deps_error(missing: list[str]) -> NoReturn:
    import typer

    names = ", ".join(missing)
    typer.echo(
        f"Error: Missing required packages: {names}\n"
        f"Install with: pip install anysite-cli[llm]",
        err=True,
    )
    raise typer.Exit(1)


def load_llm_config() -> LLMConfig:
    """Load LLM config from ~/.anysite/config.yaml."""
    from anysite.config.settings import load_yaml_config

    yaml_config = load_yaml_config()
    llm_data = yaml_config.get("llm", {})
    if not llm_data:
        raise ConfigError(
            "No LLM configuration found. Run 'anysite llm setup' first."
        )
    return LLMConfig.from_dict(llm_data)


def get_api_key(provider_config: Any) -> str:
    """Resolve API key from env var reference."""
    env_var = provider_config.api_key_env
    key = os.environ.get(env_var, "")
    if not key:
        raise ConfigError(
            f"API key not found. Set the {env_var} environment variable."
        )
    return key
