from dataclasses import dataclass
import yaml


@dataclass
class EndpointConfig:
    api_url: str
    api_key: str
    model_name: str


@dataclass
class AppConfig:
    generation_endpoint: EndpointConfig
    analysis_endpoint: EndpointConfig


def load_config(config_path: str = "config.yaml") -> AppConfig:
    with open(config_path, "r") as f:
        raw = yaml.safe_load(f)

    required_sections = ["generation_endpoint", "analysis_endpoint"]
    required_keys = ["api_url", "api_key", "model_name"]

    for section in required_sections:
        if section not in raw:
            raise ValueError(f"config.yaml missing required section: '{section}'")
        for key in required_keys:
            if key not in raw[section]:
                raise ValueError(f"config.yaml [{section}] missing required key: '{key}'")

    return AppConfig(
        generation_endpoint=EndpointConfig(**{k: raw["generation_endpoint"][k] for k in required_keys}),
        analysis_endpoint=EndpointConfig(**{k: raw["analysis_endpoint"][k] for k in required_keys}),
    )
