import json
import math
from decimal import Decimal
from pathlib import Path
import tempfile
import unittest

from unit_helpers import app_settings
from scripts import settings


class SettingsTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.config = app_settings()
        self.write("config/RobGPT_config.json", json.dumps(self.config))

    def write(self, relative_path, text):
        path = self.root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def test_loads_settings_from_project_root(self):
        self.assertEqual(settings.load_settings(self.root), self.config)

    def test_rejects_missing_required_setting(self):
        del self.config["interaction_limit"]
        self.write("config/RobGPT_config.json", json.dumps(self.config))
        with self.assertRaises(ValueError):
            settings.load_settings(self.root)

    def test_rejects_nonpositive_interaction_limit(self):
        self.config["interaction_limit"] = 0
        self.write("config/RobGPT_config.json", json.dumps(self.config))
        with self.assertRaises(ValueError):
            settings.load_settings(self.root)

    def test_loads_credentials_separately(self):
        fixture = {"API_KEY": "synthetic-test-key", "OPENAI_API_BASE": "https://example.invalid/v1"}
        self.write("config.json", json.dumps(fixture))
        self.assertEqual(settings.load_credentials(self.root), fixture)

    def test_reads_starters_one_per_nonblank_line(self):
        self.write(self.config["starter_file"], " First starter \n\nSecond starter\n")
        self.assertEqual(settings.load_starters(self.root, self.config),
                         ["First starter", "Second starter"])

    def test_rejects_empty_starters(self):
        self.write(self.config["starter_file"], "\n  \n")
        with self.assertRaises(ValueError):
            settings.load_starters(self.root, self.config)

    def test_loads_single_configured_prompt_template(self):
        template = "Write a {{requested_format}} about {{realm}}."
        self.write(self.config["system_prompt_file"], template)
        self.write("prompts/system01.txt", "Old prompt must not be used")
        self.assertEqual(settings.load_prompt_template(self.root, self.config), template)

    def test_rejects_missing_prompts(self):
        with self.assertRaises(ValueError):
            settings.load_prompt_template(self.root, self.config)

    def test_validates_required_fields_without_fallback_defaults(self):
        fields = [key for key in self.config if key != "structured_output_test"]
        for field in fields:
            with self.subTest(field=field):
                invalid = dict(self.config)
                del invalid[field]
                self.write("config/RobGPT_config.json", json.dumps(invalid))
                with self.assertRaises(ValueError):
                    settings.load_settings(self.root)

    def test_rejects_invalid_setting_types_and_ranges(self):
        for field, value in (
            ("interaction_limit", True), ("window_width", -1),
            ("request_max_retries", -1), ("request_timeout_seconds", 0),
            ("request_timeout_seconds", -1), ("request_timeout_seconds", float("inf")),
            ("next_question_text", "  "), ("structured_output_method", "unsupported"),
        ):
            with self.subTest(field=field, value=value):
                invalid = dict(self.config, **{field: value})
                self.write("config/RobGPT_config.json", json.dumps(invalid))
                with self.assertRaises(ValueError):
                    settings.load_settings(self.root)

    def test_missing_starter_file_reports_value_error(self):
        with self.assertRaises(ValueError):
            settings.load_starters(self.root, self.config)

    def test_rejects_malformed_json_without_exposing_contents(self):
        secret = "synthetic-secret-marker"
        self.write("config.json", '{"API_KEY": "' + secret)
        with self.assertRaises(ValueError) as caught:
            settings.load_credentials(self.root)
        self.assertNotIn(secret, str(caught.exception))

    def test_rejects_missing_key_and_invalid_endpoint(self):
        for credentials in (
            {"OPENAI_API_BASE": "https://example.invalid/v1"},
            {"API_KEY": "synthetic-test-key", "OPENAI_API_BASE": "not-a-url"},
        ):
            with self.subTest(fields=list(credentials)):
                self.write("config.json", json.dumps(credentials))
                with self.assertRaises(ValueError):
                    settings.load_credentials(self.root)

    def test_realms_are_stripped_and_blank_lines_ignored(self):
        self.write(self.config["realms_file"], " Science \n\nHistory\n")
        self.assertEqual(settings.load_realms(self.root, self.config), ["Science", "History"])

    def test_missing_or_empty_realms_are_rejected(self):
        with self.assertRaises(ValueError):
            settings.load_realms(self.root, self.config)
        self.write(self.config["realms_file"], " \n")
        with self.assertRaises(ValueError):
            settings.load_realms(self.root, self.config)

    def test_template_requires_both_variables_and_rejects_unknown_ones(self):
        for template in ("", "{{realm}}", "{{requested_format}}", "{{realm}} {{requested_format}} {{unknown}}"):
            with self.subTest(template=template):
                self.write(self.config["system_prompt_file"], template)
                with self.assertRaises(ValueError):
                    settings.load_prompt_template(self.root, self.config)

    def test_placeholder_values_are_not_recursively_interpreted(self):
        self.assertEqual(settings.render_prompt_template(
            "{{ realm }} / {{requested_format}}", "{{requested_format}}", "Synthetic format"),
            "{{requested_format}} / Synthetic format")

    def test_format_choices_and_default_index_are_validated(self):
        for changes in ({"requested_formats": []}, {"requested_formats": ["", "x"]},
                        {"requested_formats": ["x", "x"]}, {"default_format_index": -1},
                        {"default_format_index": True}):
            with self.subTest(changes=changes):
                self.write("config/RobGPT_config.json", json.dumps(dict(self.config, **changes)))
                with self.assertRaises(ValueError):
                    settings.load_settings(self.root)

    def test_rejects_invalid_slider_configuration(self):
        for name, field, value in (
            ("temperature", "default", float("nan")),
            ("top_p", "default", self.config["model_parameters"]["top_p"]["max"] + 1),
            ("max_tokens", "default", 1.5),
            ("temperature", "step", 0),
        ):
            with self.subTest(name=name, field=field):
                config = app_settings()
                config["model_parameters"][name][field] = value
                self.write("config/RobGPT_config.json", json.dumps(config))
                with self.assertRaises(ValueError):
                    settings.load_settings(self.root)

    def test_generation_parameters_accept_configured_boundaries(self):
        for boundary in ("min", "max", "default"):
            values = {name: spec[boundary] for name, spec in self.config["model_parameters"].items()}
            self.assertEqual(settings.generation_parameters(self.config, values), values)

    def test_generation_parameters_reject_invalid_or_missing_values(self):
        values = settings.generation_parameters(self.config)
        for invalid in ({}, dict(values, top_p=True), dict(values, max_tokens=1.5),
                        dict(values, temperature=float("inf"))):
            with self.subTest(values=invalid):
                with self.assertRaises(ValueError):
                    settings.generation_parameters(self.config, invalid)

    def test_screenshot_decimal_temperature_is_accepted(self):
        values = settings.generation_parameters(self.config)
        values["temperature"] = 0.12
        self.assertEqual(settings.generation_parameters(self.config, values), values)

    def test_every_configured_slider_tick_is_accepted(self):
        for name, spec in self.config["model_parameters"].items():
            value = Decimal(str(spec["min"]))
            maximum = Decimal(str(spec["max"]))
            step = Decimal(str(spec["step"]))
            while value <= maximum:
                with self.subTest(parameter=name, value=str(value)):
                    values = settings.generation_parameters(self.config)
                    values[name] = int(value) if name == "max_tokens" else float(value)
                    self.assertEqual(settings.generation_parameters(self.config, values), values)
                value += step

    def test_values_immediately_outside_ranges_are_rejected(self):
        for name, spec in self.config["model_parameters"].items():
            for value in (
                spec["min"] - spec["step"], spec["max"] + spec["step"],
                math.nextafter(spec["min"], -math.inf),
                math.nextafter(spec["max"], math.inf),
            ):
                with self.subTest(parameter=name, value=value):
                    values = settings.generation_parameters(self.config)
                    values[name] = value
                    with self.assertRaises(ValueError):
                        settings.generation_parameters(self.config, values)

    def test_all_parameters_reject_nonfinite_boolean_and_string_values(self):
        for name in self.config["model_parameters"]:
            for value in (math.nan, math.inf, -math.inf, True, False, "0.12", None):
                with self.subTest(parameter=name, value=value):
                    values = settings.generation_parameters(self.config)
                    values[name] = value
                    with self.assertRaises(ValueError):
                        settings.generation_parameters(self.config, values)
