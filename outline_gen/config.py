"""Configuration management for outline-gen."""

import os
import yaml
from pathlib import Path
from typing import Optional, Dict, Any


# Default configuration values used when creating a new config file
# and as a fallback when specific fields are missing from the YAML.
DEFAULT_CONFIG: Dict[str, Any] = {
    "api_key": "",
    "model": "deepseek-chat",
    "base_url": "https://api.deepseek.com/v1",
    "default_depth": 2,
    "output_format": "txt",
    "data_root": "data",
    # Placeholder pricing; you can edit values here to change
    # default prices, even if YAML does not specify them.
    "pricing": {
        # 示例：请根据实际模型价格修改
        "deepseek-chat": {
            "input_per_1k": 0.0003,
            "output_per_1k": 0.0006,
            "currency": "CNY",
        }
    },
}


class Config:
    """Manages configuration from environment variables and config files."""

    def __init__(self):
        self.config_dir = Path.home() / ".outline-gen"
        self.config_file = self.config_dir / "config.yaml"
        self._config_data: Dict[str, Any] = {}
        self._load_config()

    def _load_config(self):
        """Load configuration from file if it exists."""
        if self.config_file.exists():
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    self._config_data = yaml.safe_load(f) or {}
            except Exception as e:
                print(f"Warning: Failed to load config file: {e}")
                self._config_data = {}

    def get_api_key(self) -> Optional[str]:
        """Get LLM API key from environment or config file."""
        # Environment variable takes precedence
        for env_var in ["DEEPSEEK_API_KEY", "DASHSCOPE_API_KEY", "OPENAI_API_KEY"]:
            api_key = os.getenv(env_var)
            if api_key:
                return api_key

        # Fall back to config file
        return self._config_data.get("api_key") or self._config_data.get("dashscope_api_key")

    def get_model(self) -> str:
        """Get model name from config, default to deepseek-chat."""
        return self._config_data.get("model", "deepseek-chat")

    def get_base_url(self) -> str:
        """Get OpenAI-compatible base URL for the LLM service."""
        return self._config_data.get("base_url", "https://api.deepseek.com")

    def get_default_depth(self) -> int:
        """Get default recursion depth from config."""
        return self._config_data.get("default_depth", 2)

    def get_output_format(self) -> str:
        """Get default output format from config."""
        return self._config_data.get("output_format", "txt")

    def get_data_root(self) -> Path:
        """Get default data root directory for PDF + outline + rewritten docs."""
        root = self._config_data.get("data_root")
        if root:
            return Path(root)
        return Path("data")

    def get_pricing(self) -> Dict[str, Any]:
        """Get model pricing configuration.

        Expected structure in config.yaml (example placeholder):
        pricing:
          qwen-turbo:
            input_per_1k: 0.0000  # 每 1k 输入 token 价格
            output_per_1k: 0.0000 # 每 1k 输出 token 价格
            currency: "CNY"
        """
        # Start from code-level defaults so editing DEFAULT_CONFIG["pricing"]
        # in config.py can take effect even without YAML changes.
        base_pricing = dict(DEFAULT_CONFIG.get("pricing") or {})

        pricing = self._config_data.get("pricing")
        if isinstance(pricing, dict):
            # Shallow-merge YAML pricing into defaults (per-model, per-field)
            for model, cfg in pricing.items():
                if not isinstance(cfg, dict):
                    # If YAML entry is not a dict, override completely
                    base_pricing[model] = cfg
                    continue
                merged = dict(base_pricing.get(model, {}))
                merged.update(cfg)
                base_pricing[model] = merged

        return base_pricing

    def get_model_pricing(self, model: str) -> Dict[str, Any]:
        """Get pricing config for a specific model."""
        return self.get_pricing().get(model, {})

    def create_default_config(self):
        """Create default config file."""
        self.config_dir.mkdir(parents=True, exist_ok=True)

        with open(self.config_file, 'w', encoding='utf-8') as f:
            yaml.dump(DEFAULT_CONFIG, f, allow_unicode=True)

        return self.config_file
