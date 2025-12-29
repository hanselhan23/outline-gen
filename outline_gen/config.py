"""Configuration management for outline-gen."""

import os
import yaml
from pathlib import Path
from typing import Optional, Dict, Any


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
        """Get Dashscope API key from environment or config file."""
        # Environment variable takes precedence
        api_key = os.getenv("DASHSCOPE_API_KEY")
        if api_key:
            return api_key

        # Fall back to config file
        return self._config_data.get("dashscope_api_key")

    def get_model(self) -> str:
        """Get model name from config, default to qwen-turbo."""
        return self._config_data.get("model", "qwen-turbo")

    def get_default_depth(self) -> int:
        """Get default recursion depth from config."""
        return self._config_data.get("default_depth", 2)

    def get_output_format(self) -> str:
        """Get default output format from config."""
        return self._config_data.get("output_format", "txt")

    def create_default_config(self):
        """Create default config file."""
        self.config_dir.mkdir(parents=True, exist_ok=True)

        default_config = {
            "dashscope_api_key": "your-api-key-here",
            "model": "qwen-turbo",
            "default_depth": 2,
            "output_format": "txt"
        }

        with open(self.config_file, 'w', encoding='utf-8') as f:
            yaml.dump(default_config, f, allow_unicode=True)

        return self.config_file
