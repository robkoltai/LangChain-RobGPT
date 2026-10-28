"""Configuration and text resource loading. Paths resolve from project_root."""

import json
import math
import re
from pathlib import Path
from urllib.parse import urlsplit


class GenerationParameterError(ValueError):
    """Invalid generation input, exposing only a trusted parameter name to the UI."""

    def __init__(self, parameter: str):
        self.parameter = parameter
        super().__init__(f"Invalid generation parameter: {parameter}")


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        raise ValueError(f"Cannot read UTF-8 file: {path}") from None


def _read_object(path: Path) -> dict:
    try:
        data = json.loads(_read_text(path))
    except json.JSONDecodeError:
        raise ValueError(f"Invalid JSON in {path}") from None
    if not isinstance(data, dict):
        raise ValueError(f"Expected a JSON object in {path}")
    return data


def _require_text(data: dict, name: str) -> None:
    value = data.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a nonempty string.")


def load_settings(project_root: Path) -> dict:
    """Load application settings and reject missing/invalid required values."""
    data = _read_object(project_root / "config/RobGPT_config.json")
    for name in (
        "model_name", "model_label", "structured_output_method", "window_title", "reply_label",
        "input_label", "farewell_text", "next_question_text", "starter_file",
        "system_prompt_file", "realms_file", "format_label",
        "text_font_family", "send_button_text", "remaining_text", "error_text",
        "repeat_button_text",
        "previous_message_label",
        "empty_message_error_text", "parameter_error_text", "response_error_text", "token_limit_text",
        "statistics_text", "statistics_unavailable_text", "balance_unavailable_text",
        "statistics_yes_text", "statistics_no_text", "statistics_duration_text",
        "cost_estimate_text", "cost_unavailable_text",
    ):
        _require_text(data, name)
    for name in ("window_width", "window_height", "emoji_font_size", "interaction_limit",
                 "ui_padding", "text_font_size", "reply_box_height", "input_box_height",
                 "statistics_font_size", "controls_width", "previous_message_box_height"):
        value = data.get(name)
        if type(value) is not int or value <= 0:
            raise ValueError(f"{name} must be a positive integer.")
    retries = data.get("request_max_retries")
    if type(retries) is not int or retries < 0:
        raise ValueError("request_max_retries must be a nonnegative integer.")
    timeout = data.get("request_timeout_seconds")
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("request_timeout_seconds must be a finite positive number.")
    if data["structured_output_method"] not in ("json_schema", "function_calling", "json_mode"):
        raise ValueError("Unsupported structured_output_method.")
    formats = data.get("requested_formats")
    if not isinstance(formats, list) or not formats or any(
        not isinstance(value, str) or not value.strip() for value in formats
    ) or len(set(formats)) != len(formats):
        raise ValueError("requested_formats must contain distinct nonempty strings.")
    index = data.get("default_format_index")
    if type(index) is not int or not 0 <= index < len(formats):
        raise ValueError("default_format_index must select a configured format.")
    specs = data.get("model_parameters")
    prices = data.get("model_prices_usd_per_million_tokens")
    if not isinstance(prices, dict) or not prices:
        raise ValueError("model_prices_usd_per_million_tokens must contain model-specific prices.")
    if data["model_name"] not in prices:
        raise ValueError("model_name must select a model with configured prices.")
    for model, rates in prices.items():
        if not isinstance(model, str) or not model.strip() or not isinstance(rates, dict):
            raise ValueError("Invalid model pricing configuration.")
        for category in ("input", "cached_input", "output"):
            rate = rates.get(category)
            if type(rate) not in (int, float) or not math.isfinite(rate) or rate < 0:
                raise ValueError(f"Invalid {category} price for {model}.")
    if not isinstance(specs, dict) or set(specs) != {"temperature", "top_p", "max_tokens"}:
        raise ValueError("model_parameters must define temperature, top_p, and max_tokens.")
    for name, spec in specs.items():
        if not isinstance(spec, dict):
            raise ValueError(f"Invalid slider configuration for {name}.")
        _require_text(spec, "label")
        for field in ("min", "max", "default", "step"):
            value = spec.get(field)
            if type(value) not in (int, float) or not math.isfinite(value):
                raise ValueError(f"{name}.{field} must be a finite number.")
            if name == "max_tokens" and type(value) is not int:
                raise ValueError(f"{name}.{field} must be an integer.")
        if not spec["min"] <= spec["default"] <= spec["max"] or spec["step"] <= 0:
            raise ValueError(f"Invalid range, default, or step for {name}.")
    return data


def generation_parameters(settings: dict, values: dict | None = None) -> dict:
    """Resolve defaults and validate per-call values against configured ranges."""
    specs = settings["model_parameters"]
    parameters = {name: spec["default"] for name, spec in specs.items()}
    if values is not None:
        if set(values) != set(specs):
            raise GenerationParameterError("model parameters")
        parameters.update(values)
    for name, value in parameters.items():
        if type(value) not in (int, float) or not math.isfinite(value):
            raise GenerationParameterError(name)
        if name == "max_tokens" and type(value) is not int:
            raise GenerationParameterError(name)
        if not specs[name]["min"] <= value <= specs[name]["max"]:
            raise GenerationParameterError(name)
    return parameters


def load_credentials(project_root: Path) -> dict:
    """Load credentials from root config.json; never include secrets in errors."""
    data = _read_object(project_root / "config.json")
    for name in ("API_KEY", "OPENAI_API_BASE"):
        _require_text(data, name)
    try:
        parts = urlsplit(data["OPENAI_API_BASE"])
        valid = (
            parts.scheme == "https" and parts.hostname and not parts.username
            and not parts.password and not parts.query and not parts.fragment
        )
        parts.port  # Validate a port if supplied.
    except ValueError:
        valid = False
    if not valid:
        raise ValueError("OPENAI_API_BASE must be an HTTPS base URL without credentials or query parameters.")
    return data


def load_starters(project_root: Path, settings: dict) -> list[str]:
    """Read configured starter file; strip whitespace and reject an empty list."""
    return _load_lines(project_root / settings["starter_file"])


def _load_lines(path: Path) -> list[str]:
    lines = [line.strip() for line in _read_text(path).splitlines() if line.strip()]
    if not lines:
        raise ValueError(f"No nonempty lines in {path}")
    return lines


def load_realms(project_root: Path, settings: dict) -> list[str]:
    """Read one realm per nonempty line from the configured resource."""
    return _load_lines(project_root / settings["realms_file"])


_PLACEHOLDER = re.compile(r"{{\s*([^{}]+?)\s*}}")


def validate_prompt_template(template: str) -> None:
    if not isinstance(template, str) or set(_PLACEHOLDER.findall(template)) != {"realm", "requested_format"}:
        raise ValueError("System prompt must contain only the realm and requested_format template variables, with both present.")


def render_prompt_template(template: str, realm: str, requested_format: str) -> str:
    """Substitute literal values once; never interpret braces inside their values."""
    values = {"realm": realm, "requested_format": requested_format}
    return _PLACEHOLDER.sub(lambda match: values[match.group(1)], template)


def load_prompt_template(project_root: Path, settings: dict) -> str:
    template = _read_text(project_root / settings["system_prompt_file"]).strip()
    validate_prompt_template(template)
    return template
