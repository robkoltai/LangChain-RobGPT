import unittest
from unittest.mock import Mock, patch

from unit_helpers import app_settings
from scripts.conversation import Reaction, EmptyMessageError, ModelResponseError, SessionStatistics, TokenLimitResponse
from scripts.settings import GenerationParameterError
from scripts.window import Window


class WindowTest(unittest.TestCase):
    def setUp(self):
        self.config = app_settings()
        self.root = Mock()
        self.conversation = Mock()
        self.conversation.remaining = self.config["interaction_limit"]
        self.conversation.finished = False
        self.conversation.can_repeat = False
        self.conversation.statistics = SessionStatistics()
        self.conversation.start.return_value = "Synthetic starter"
        self.conversation.respond.return_value = Reaction(reply="Synthetic reply", emoji="🙂")
        widgets_patch = patch("scripts.window.tk")
        self.widgets = widgets_patch.start()
        self.addCleanup(widgets_patch.stop)
        themed_patch = patch("scripts.window.ttk")
        self.themed_widgets = themed_patch.start()
        self.addCleanup(themed_patch.stop)
        self.widgets.Text.side_effect = [Mock(), Mock(), Mock()]
        self.widgets.Label.side_effect = [Mock() for _ in range(8)]
        self.widgets.Button.side_effect = [Mock(), Mock()]
        self.widgets.Scale.side_effect = [Mock() for _ in self.config["model_parameters"]]
        self.themed_widgets.Radiobutton.side_effect = [Mock() for _ in self.config["requested_formats"]]
        self.window = Window(self.config, self.conversation, self.root)
        self.window.previous_message_box.get.return_value = "Edited previous message"
        self.window.format_var.get.return_value = self.config["requested_formats"][self.config["default_format_index"]]
        for name, slider in self.window.parameter_sliders.items():
            slider.get.return_value = self.config["model_parameters"][name]["default"]

    def test_run_displays_starter_before_event_loop(self):
        with patch.object(self.window, "display") as display:
            self.root.mainloop.side_effect = lambda: display.assert_called_once_with(
                self.conversation.start.return_value, "", self.conversation.remaining)
            self.window.run()
        self.conversation.respond.assert_not_called()
        self.root.mainloop.assert_called_once()

    def test_success_displays_both_fields_and_remaining_count(self):
        with patch.object(self.window, "display") as display:
            self.window.submit("Current message")
        self.conversation.respond.assert_called_once_with("Current message", self.window._parameters(),
            requested_format=self.window.format_var.get())
        result = self.conversation.respond.return_value
        display.assert_called_once_with(result.reply, result.emoji, self.conversation.remaining)
        self.window.previous_message_box.delete.assert_called_once_with("1.0", "end")
        self.window.previous_message_box.insert.assert_called_once_with("1.0", "Current message")
        self.window.input_box.delete.assert_called_once_with("1.0", "end")
        self.root.after.assert_not_called()

    def test_failure_reports_error_without_displaying_success_or_closing(self):
        error = RuntimeError("Synthetic failure")
        self.conversation.respond.side_effect = error
        with patch.object(self.window, "display") as display, \
                patch.object(self.window, "show_error") as report:
            self.window.submit("Current message")
        report.assert_called_once_with(error)
        display.assert_not_called()
        self.root.after.assert_not_called()

    def test_final_reply_stays_visible_with_input_disabled_until_user_closes(self):
        self.conversation.finished = True
        self.conversation.remaining = 0
        with patch.object(self.window, "display") as display:
            self.window.submit("Final message")
        result = self.conversation.respond.return_value
        display.assert_called_once_with(result.reply, result.emoji, 0)
        self.root.after.assert_not_called()
        self.root.destroy.assert_not_called()
        self.window.input_box.configure.assert_called_with(state="disabled")
        self.window.send_button.configure.assert_called_with(state="disabled")

    def test_final_session_rejects_further_submissions(self):
        self.conversation.finished = True
        self.window.submit("Final message")
        self.conversation.respond.reset_mock()
        self.window.submit("Extra message")
        self.conversation.respond.assert_not_called()
        self.root.after.assert_not_called()
        self.root.destroy.assert_not_called()

    def test_failure_preserves_input_and_reenables_submission(self):
        self.conversation.respond.side_effect = RuntimeError("Synthetic failure")
        self.window.submit("Keep this input")
        self.window.input_box.delete.assert_not_called()
        self.window.previous_message_box.delete.assert_not_called()
        self.window.input_box.configure.assert_called_with(state="normal")
        self.window.send_button.configure.assert_called_with(state="normal")

    def test_display_replaces_reply_emoji_and_counter(self):
        result = self.conversation.respond.return_value
        self.window.display(result.reply, result.emoji, self.conversation.remaining)
        self.window.reply_box.delete.assert_called_once_with("1.0", "end")
        self.window.reply_box.insert.assert_called_once_with("1.0", result.reply)
        self.window.reply_box.configure.assert_called_with(state="disabled")
        self.window.emoji.configure.assert_any_call(text=result.emoji)
        self.window.counter.configure.assert_any_call(text=self.config["remaining_text"].format(
            remaining=self.conversation.remaining))

    def test_error_display_does_not_expose_exception_contents(self):
        secret = "synthetic-secret-marker"
        self.window.show_error(RuntimeError(secret))
        text = self.window.status.configure.call_args.kwargs["text"]
        self.assertNotIn(secret, text)
        self.assertEqual(text, self.config["error_text"].format(error_type="RuntimeError"))

    def test_window_uses_configured_title_and_dimensions(self):
        self.root.title.assert_called_once_with(self.config["window_title"])
        self.root.geometry.assert_called_once_with(
            f"{self.config['window_width']}x{self.config['window_height']}")

    def test_sliders_use_configured_ranges_steps_and_defaults(self):
        for call, (name, spec) in zip(self.widgets.Scale.call_args_list,
                                      self.config["model_parameters"].items()):
            self.assertEqual(call.kwargs["from_"], spec["min"])
            self.assertEqual(call.kwargs["to"], spec["max"])
            self.assertEqual(call.kwargs["resolution"], spec["step"])
            self.window.parameter_sliders[name].set.assert_called_once_with(spec["default"])

    def test_repeat_disabled_until_a_successful_request_exists(self):
        self.window.repeat_button.configure.assert_called_with(state="disabled")
        self.window.repeat()
        self.conversation.repeat.assert_not_called()

    def test_repeat_uses_sliders_preserves_draft_and_displays_result(self):
        self.conversation.can_repeat = True
        self.conversation.repeat.return_value = self.conversation.respond.return_value
        with patch.object(self.window, "display") as display:
            self.window.repeat()
        self.conversation.repeat.assert_called_once_with(
            self.window._parameters(), requested_format=self.window.format_var.get(),
            user_message="Edited previous message")
        self.conversation.respond.assert_not_called()
        self.window.input_box.delete.assert_not_called()
        self.window.previous_message_box.delete.assert_not_called()
        result = self.conversation.repeat.return_value
        display.assert_called_once_with(result.reply, result.emoji, self.conversation.remaining)

    def test_repeat_remains_available_after_final_reply(self):
        self.conversation.can_repeat = True
        self.conversation.finished = True
        self.conversation.remaining = 0
        self.conversation.repeat.return_value = self.conversation.respond.return_value
        self.window.submit("Final message")
        self.window.repeat_button.configure.assert_called_with(state="normal")
        self.window.repeat()
        self.conversation.repeat.assert_called_once()
        self.window.send_button.configure.assert_called_with(state="disabled")
        for slider in self.window.parameter_sliders.values():
            slider.configure.assert_called_with(state="normal")
        self.window.previous_message_box.configure.assert_called_with(state="normal")
        self.root.destroy.assert_not_called()

    def test_failed_repeat_preserves_display_and_input(self):
        self.conversation.can_repeat = True
        self.conversation.repeat.side_effect = RuntimeError("Synthetic failure")
        with patch.object(self.window, "display") as display:
            self.window.repeat()
        display.assert_not_called()
        self.window.input_box.delete.assert_not_called()
        self.window.repeat_button.configure.assert_called_with(state="normal")

    def test_slider_decimal_strings_are_read_as_numeric_values(self):
        self.window.parameter_sliders["temperature"].get.return_value = "0.12"
        values = self.window._parameters()
        self.assertEqual(values["temperature"], 0.12)
        self.assertIsInstance(values["top_p"], float)
        self.assertIsInstance(values["max_tokens"], int)

    def test_empty_send_explains_how_to_use_repeat(self):
        self.conversation.respond.side_effect = EmptyMessageError("Synthetic hidden text")
        self.window.submit("")
        self.window.status.configure.assert_called_with(text=self.config["empty_message_error_text"])
        self.window.input_box.delete.assert_not_called()

    def test_known_errors_show_specific_safe_guidance(self):
        for error, expected in (
            (GenerationParameterError("temperature"),
             self.config["parameter_error_text"].format(parameter="temperature")),
            (ModelResponseError("synthetic-secret-marker"), self.config["response_error_text"]),
        ):
            with self.subTest(error=type(error).__name__):
                self.window.show_error(error)
                self.window.status.configure.assert_called_with(text=expected)
                self.assertNotIn("synthetic-secret-marker", expected)

    def test_token_limit_displays_partial_reply_and_moves_input_to_previous(self):
        error = TokenLimitResponse(None, Reaction(reply="Partial reply", emoji=""))
        self.conversation.respond.side_effect = error
        self.conversation.can_repeat = True
        with patch.object(self.window, "display") as display:
            self.window.submit("Submitted message for retry")
        display.assert_called_once_with("Partial reply", "", self.conversation.remaining)
        self.window.status.configure.assert_called_with(
            text="Maxtokens reached. Response incomplete")
        self.window.previous_message_box.insert.assert_called_once_with(
            "1.0", "Submitted message for retry")
        self.window.input_box.delete.assert_called_once_with("1.0", "end")
        self.window.repeat_button.configure.assert_called_with(state="normal")

    def test_format_radio_choices_and_default_come_from_configuration(self):
        self.assertEqual([call.kwargs["value"] for call in self.themed_widgets.Radiobutton.call_args_list],
                         self.config["requested_formats"])
        self.assertEqual(self.widgets.StringVar.call_args.kwargs["value"],
                         self.config["requested_formats"][self.config["default_format_index"]])

    def test_selected_format_is_sent_on_send_and_repeat(self):
        selected = self.config["requested_formats"][-1]
        self.window.format_var.get.return_value = selected
        self.window.submit("Current message")
        self.conversation.respond.assert_called_once_with(
            "Current message", self.window._parameters(), requested_format=selected)
        self.conversation.can_repeat = True
        self.conversation.repeat.return_value = self.conversation.respond.return_value
        self.window.repeat()
        self.conversation.repeat.assert_called_once_with(
            self.window._parameters(), requested_format=self.window.format_var.get(),
            user_message="Edited previous message")

    def test_statistics_distinguish_missing_usage_from_zero(self):
        self.window.display_statistics()
        text = self.window.statistics_box.configure.call_args.kwargs["text"]
        self.assertIn(self.config["statistics_unavailable_text"], text)
        self.assertIn(self.config["balance_unavailable_text"], text)
        stats = self.conversation.statistics
        stats.input_tokens = stats.output_tokens = 0
        stats.duration_seconds = 1.25
        stats.limit_reached = True
        self.window.display_statistics()
        text = self.window.statistics_box.configure.call_args.kwargs["text"]
        self.assertIn(self.config["statistics_duration_text"].format(seconds=stats.duration_seconds), text)
        self.assertIn(self.config["statistics_yes_text"], text)
