import unittest
from unittest.mock import DEFAULT, patch

from unit_helpers import ROOT, app_settings
from scripts import RobGPT


class EntrypointTest(unittest.TestCase):
    def setUp(self):
        dependencies = patch.multiple(
            RobGPT, load_settings=DEFAULT, load_credentials=DEFAULT,
            load_prompt_template=DEFAULT, load_realms=DEFAULT, load_starters=DEFAULT, create_model=DEFAULT,
            Conversation=DEFAULT, Window=DEFAULT,
        )
        self.mocks = dependencies.start()
        self.addCleanup(dependencies.stop)
        tk_patch = patch.object(RobGPT.tk, "Tk")
        self.tk = tk_patch.start()
        self.addCleanup(tk_patch.stop)
        self.config = app_settings()
        self.mocks["load_settings"].return_value = self.config

    def test_wires_dependencies_and_starts_window(self):
        RobGPT.main()
        self.mocks["load_settings"].assert_called_once_with(ROOT)
        self.mocks["load_credentials"].assert_called_once_with(ROOT)
        for name in ("load_prompt_template", "load_realms", "load_starters"):
            self.mocks[name].assert_called_once_with(ROOT, self.config)
        self.mocks["create_model"].assert_called_once_with(
            self.config, self.mocks["load_credentials"].return_value)
        self.mocks["Conversation"].assert_called_once_with(
            self.config, self.mocks["load_prompt_template"].return_value,
            self.mocks["load_realms"].return_value,
            self.mocks["load_starters"].return_value,
            self.mocks["create_model"].return_value, RobGPT.random.choice)
        self.mocks["Window"].assert_called_once_with(
            self.config, self.mocks["Conversation"].return_value, self.tk.return_value)
        self.mocks["Window"].return_value.run.assert_called_once_with()

    def test_invalid_configuration_stops_before_model_or_window_creation(self):
        self.mocks["load_settings"].side_effect = ValueError("Synthetic invalid config")
        with self.assertRaises(ValueError):
            RobGPT.main()
        self.mocks["create_model"].assert_not_called()
        self.tk.assert_not_called()

    def test_missing_resources_stop_before_model_or_window_creation(self):
        self.mocks["load_prompt_template"].side_effect = ValueError("Synthetic missing prompts")
        with self.assertRaises(ValueError):
            RobGPT.main()
        self.mocks["create_model"].assert_not_called()
        self.tk.assert_not_called()

    def test_failed_window_construction_destroys_root(self):
        self.mocks["Window"].side_effect = RuntimeError("Synthetic widget failure")
        with self.assertRaises(RuntimeError):
            RobGPT.main()
        self.tk.return_value.destroy.assert_called_once_with()
