import unittest
import json
from unittest.mock import Mock, patch

import httpx
from langchain_core.exceptions import OutputParserException
from langchain_core.messages import AIMessage

from unit_helpers import app_settings
from scripts.conversation import Conversation, Reaction, create_model, EmptyMessageError, ModelResponseError, TokenLimitResponse
from scripts.settings import generation_parameters


class ConversationTest(unittest.TestCase):
    def setUp(self):
        self.config = app_settings()
        self.template = "A {{requested_format}} about {{realm}}"
        self.realms = ["Synthetic realm A", "Synthetic realm B"]
        self.rendered_prompt = "A " + self.config["requested_formats"][self.config["default_format_index"]] + " about " + self.realms[-1]
        self.starters = ["Synthetic starter A", "Synthetic starter B"]
        self.model = Mock()
        self.model.invoke.return_value = Reaction(reply="Synthetic reply", emoji="🙂")
        self.choose = Mock(side_effect=lambda items: items[-1])
        self.session = Conversation(self.config, self.template, self.realms, self.starters,
                                    self.model, self.choose)

    def test_starter_uses_chooser_without_spending_interaction(self):
        self.assertEqual(self.session.start(), self.starters[-1])
        self.choose.assert_called_once_with(self.starters)
        self.assertEqual(self.session.remaining, self.config["interaction_limit"])
        self.model.invoke.assert_not_called()

    def test_success_returns_reply_and_emoji_and_decrements(self):
        result = self.session.respond("Current message")
        self.assertEqual(result, self.model.invoke.return_value)
        self.assertEqual(self.session.remaining, self.config["interaction_limit"] - 1)
        self.model.invoke.assert_called_once()

    def test_each_call_selects_prompt_and_sends_no_history(self):
        for message in ("Previous message", "Current message"):
            self.session.respond(message)
        self.assertEqual(self.choose.call_count, self.model.invoke.call_count)
        self.choose.assert_called_with(self.realms)
        prompt = self.rendered_prompt
        if self.session.remaining > 0:
            prompt += "\n\n" + self.config["next_question_text"]
        self.assertEqual(self.model.invoke.call_args.args[0],
                         [("system", prompt), ("human", "Current message")])

    def test_nonfinal_prompt_includes_continuation_instruction(self):
        for _ in range(self.config["interaction_limit"] - 1):
            self.session.respond("Current message")
            prompt = self.model.invoke.call_args.args[0][0][1]
            self.assertEqual(prompt, self.rendered_prompt + "\n\n" + self.config["next_question_text"])

    def test_final_prompt_omits_continuation_instruction(self):
        for _ in range(self.config["interaction_limit"]):
            self.session.respond("Current message")
        self.assertEqual(self.model.invoke.call_args.args[0][0], ("system", self.rendered_prompt))

    def test_failed_request_preserves_count_and_allows_retry(self):
        self.model.invoke.side_effect = RuntimeError("Synthetic network failure")
        with self.assertRaises(RuntimeError):
            self.session.respond("Current message")
        self.assertEqual(self.session.remaining, self.config["interaction_limit"])
        self.model.invoke.side_effect = None
        self.session.respond("Retry")
        self.assertEqual(self.session.remaining, self.config["interaction_limit"] - 1)

    def test_invalid_output_preserves_count(self):
        self.model.invoke.return_value = Reaction(reply="", emoji="")
        with self.assertRaises(ValueError):
            self.session.respond("Current message")
        self.assertEqual(self.session.remaining, self.config["interaction_limit"])

    def test_blank_input_does_not_call_model(self):
        with self.assertRaises(ValueError):
            self.session.respond("   ")
        self.model.invoke.assert_not_called()
        self.assertEqual(self.session.remaining, self.config["interaction_limit"])

    def test_final_reply_appends_farewell_and_blocks_more_calls(self):
        for _ in range(self.config["interaction_limit"]):
            result = self.session.respond("Current message")
        self.assertTrue(result.reply.endswith(self.config["farewell_text"]))
        self.assertEqual(self.session.remaining, 0)
        self.assertTrue(self.session.finished)
        self.model.invoke.reset_mock()
        with self.assertRaises(ValueError):
            self.session.respond("One too many")
        self.model.invoke.assert_not_called()

    def test_final_request_failure_preserves_final_chance(self):
        for _ in range(self.config["interaction_limit"] - 1):
            self.session.respond("Current message")
        before = self.session.remaining
        self.model.invoke.side_effect = ValueError("Synthetic parsing error")
        with self.assertRaises(ValueError):
            self.session.respond("Final message")
        self.assertEqual(self.session.remaining, before)
        self.assertFalse(self.session.finished)

    def test_unexpected_result_type_preserves_count(self):
        self.model.invoke.return_value = None
        with self.assertRaises(ValueError):
            self.session.respond("Current message")
        self.assertEqual(self.session.remaining, self.config["interaction_limit"])

    def test_final_farewell_does_not_mutate_model_result(self):
        original = self.model.invoke.return_value.model_copy()
        for _ in range(self.config["interaction_limit"]):
            self.session.respond("Current message")
        self.assertEqual(self.model.invoke.return_value, original)

    def test_default_parameters_are_forwarded(self):
        self.session.respond("Current message")
        self.assertEqual(self.model.invoke.call_args.kwargs, generation_parameters(self.config))

    def test_repeat_uses_exact_messages_and_new_parameters_without_counting(self):
        self.session.respond("Original message")
        messages = self.model.invoke.call_args.args[0]
        remaining = self.session.remaining
        self.choose.reset_mock()
        changed = {name: spec["max"] for name, spec in self.config["model_parameters"].items()}
        self.session.repeat(changed)
        self.assertEqual(self.model.invoke.call_args.args[0], messages)
        self.assertEqual(self.model.invoke.call_args.kwargs, changed)
        self.assertEqual(self.session.remaining, remaining)
        self.choose.assert_not_called()

    def test_repeat_before_success_does_not_call_model(self):
        self.assertFalse(self.session.can_repeat)
        with self.assertRaises(ValueError):
            self.session.repeat()
        self.model.invoke.assert_not_called()

    def test_repeat_changes_format_preserving_message_realm_and_count(self):
        self.session.respond("Original message", requested_format="Poem")
        remaining = self.session.remaining
        self.choose.reset_mock()
        for selected in self.config["requested_formats"]:
            with self.subTest(selected=selected):
                self.session.repeat(requested_format=selected)
                messages = self.model.invoke.call_args.args[0]
                self.assertEqual(messages, [
                    ("system", f"A {selected} about {self.realms[-1]}\n\n"
                     + self.config["next_question_text"]),
                    ("human", "Original message")])
                self.assertEqual(self.session.remaining, remaining)
        self.choose.assert_not_called()
        self.session.repeat()
        self.assertEqual(self.model.invoke.call_args.args[0], messages)

    def test_repeat_rejects_invalid_format_without_a_model_call(self):
        self.session.respond("Original message")
        self.model.reset_mock()
        with self.assertRaises(ValueError):
            self.session.repeat(requested_format="invalid format")
        self.model.invoke.assert_not_called()

    def test_repeat_uses_edited_message_and_remembers_it_without_spending_question(self):
        self.session.respond("Original message")
        remaining = self.session.remaining
        self.choose.reset_mock()
        changed = {name: spec["max"] for name, spec in self.config["model_parameters"].items()}
        self.session.repeat(changed, requested_format="True Story", user_message="Edited message")
        messages = self.model.invoke.call_args.args[0]
        self.assertEqual(messages[1], ("human", "Edited message"))
        self.assertIn("True Story about " + self.realms[-1], messages[0][1])
        self.assertEqual(self.model.invoke.call_args.kwargs, changed)
        self.assertEqual(self.session.remaining, remaining)
        self.choose.assert_not_called()
        self.session.repeat()
        self.assertEqual(self.model.invoke.call_args.args[0], messages)

    def test_blank_edited_repeat_is_rejected_without_request_or_saved_message_change(self):
        self.session.respond("Original message")
        messages = self.model.invoke.call_args.args[0]
        self.model.reset_mock()
        with self.assertRaises(EmptyMessageError):
            self.session.repeat(user_message=" \n ")
        self.model.invoke.assert_not_called()
        self.session.repeat()
        self.assertEqual(self.model.invoke.call_args.args[0], messages)

    def test_repeat_after_final_keeps_farewell_and_zero_count(self):
        for _ in range(self.config["interaction_limit"]):
            self.session.respond("Current message")
        messages = self.model.invoke.call_args.args[0]
        result = self.session.repeat()
        self.assertEqual(self.model.invoke.call_args.args[0], messages)
        self.assertEqual(self.session.remaining, 0)
        self.assertTrue(result.reply.endswith(self.config["farewell_text"]))
        self.assertEqual(result.reply.count(self.config["farewell_text"]), 1)

    def test_failure_preserves_last_successful_request_for_repeat(self):
        self.session.respond("Successful message")
        original = self.model.invoke.call_args.args[0]
        remaining = self.session.remaining
        self.model.invoke.side_effect = RuntimeError("Synthetic failure")
        for action in (lambda: self.session.respond("Failed message"), self.session.repeat):
            with self.assertRaises(RuntimeError):
                action()
            self.assertEqual(self.session.remaining, remaining)
        self.model.invoke.side_effect = None
        self.session.repeat()
        self.assertEqual(self.model.invoke.call_args.args[0], original)

    def test_invalid_parameters_do_not_call_model_or_spend_question(self):
        parameters = generation_parameters(self.config)
        parameters["max_tokens"] = self.config["model_parameters"]["max_tokens"]["max"] + 1
        with self.assertRaises(ValueError):
            self.session.respond("Current message", parameters)
        self.model.invoke.assert_not_called()
        self.assertEqual(self.session.remaining, self.config["interaction_limit"])

    def test_repeat_accepts_screenshot_decimals(self):
        self.session.respond("I was born in Budapest")
        before = self.session.remaining
        values = generation_parameters(self.config)
        values["temperature"] = 0.12
        self.session.repeat(values)
        self.assertEqual(self.model.invoke.call_args.kwargs, values)
        self.assertEqual(self.session.remaining, before)

    def test_each_configured_format_renders_with_chosen_realm(self):
        # Each format is tested in a fresh session, independent of interaction limit.
        for requested_format in self.config["requested_formats"]:
            with self.subTest(requested_format=requested_format):
                session = Conversation(self.config, self.template, self.realms,
                                       self.starters, self.model, self.choose)
                session.respond("Current message", requested_format=requested_format)
                prompt = self.model.invoke.call_args.args[0][0][1]
                self.assertIn("A " + requested_format + " about " + self.realms[-1], prompt)
                self.assertNotIn("{{realm}}", prompt)
                self.assertNotIn("{{requested_format}}", prompt)

    def test_new_send_chooses_new_realm_but_repeat_preserves_rendered_prompt(self):
        self.choose.side_effect = [self.realms[0], self.realms[-1]]
        self.session.respond("First message", requested_format=self.config["requested_formats"][0])
        first = self.model.invoke.call_args.args[0]
        self.session.repeat()
        self.assertEqual(self.model.invoke.call_args.args[0], first)
        self.assertEqual(self.choose.call_count, 1)
        self.session.respond("Second message", requested_format=self.config["requested_formats"][-1])
        second = self.model.invoke.call_args.args[0]
        self.assertNotEqual(second[0], first[0])
        self.assertIn(self.realms[-1], second[0][1])
        self.assertEqual(self.choose.call_count, 2)

    def test_invalid_format_does_not_call_model_or_choose_realm(self):
        with self.assertRaises(ValueError):
            self.session.respond("Current message", requested_format="Not a configured format")
        self.model.invoke.assert_not_called()
        self.choose.assert_not_called()
        self.assertEqual(self.session.remaining, self.config["interaction_limit"])

    def test_blank_send_is_identified_separately_from_parameter_errors(self):
        values = generation_parameters(self.config)
        values["temperature"] = 0.12
        with self.assertRaises(EmptyMessageError):
            self.session.respond("", values)
        self.model.invoke.assert_not_called()

    def test_incomplete_response_is_identified_and_does_not_spend_question(self):
        self.model.invoke.return_value = Reaction(reply="Synthetic reply", emoji="")
        with self.assertRaises(ModelResponseError):
            self.session.respond("Current message")
        self.assertEqual(self.session.remaining, self.config["interaction_limit"])

    def test_parse_failure_is_identified_without_exposing_response(self):
        self.model.invoke.side_effect = OutputParserException("synthetic-secret-marker")
        with self.assertRaises(ModelResponseError) as caught:
            self.session.respond("Current message")
        self.assertNotIn("synthetic-secret-marker", str(caught.exception))
        self.assertEqual(self.session.remaining, self.config["interaction_limit"])

    def test_reported_usage_timing_and_repeat_totals(self):
        raw = AIMessage(content="", usage_metadata={
            "input_tokens": 12, "output_tokens": 8, "total_tokens": 20},
            response_metadata={"finish_reason": "stop"})
        self.model.invoke.return_value = {
            "raw": raw, "parsed": Reaction(reply="Synthetic reply", emoji="🙂"),
            "parsing_error": None}
        with patch("scripts.conversation.perf_counter", side_effect=[10.0, 11.25]):
            self.session.respond("Current message")
        stats = self.session.statistics
        self.assertEqual((stats.input_tokens, stats.output_tokens), (12, 8))
        self.assertEqual(stats.duration_seconds, 1.25)
        self.assertFalse(stats.limit_reached)
        self.session.repeat()
        self.assertEqual((stats.total_input_tokens, stats.total_output_tokens), (24, 16))
        self.assertEqual((stats.send_calls, stats.repeat_calls, stats.successes, stats.failures),
                         (1, 1, 2, 0))
        self.assertEqual(stats.unreported_usage_calls, 0)

    def test_missing_usage_is_unavailable_and_counts_only_real_invocations(self):
        with self.assertRaises(EmptyMessageError):
            self.session.respond("")
        self.assertEqual(self.session.statistics.send_calls, 0)
        self.session.respond("Current message")
        stats = self.session.statistics
        self.assertIsNone(stats.input_tokens)
        self.assertIsNone(stats.limit_reached)
        self.assertEqual(stats.unreported_usage_calls, 1)
        self.assertEqual(stats.total_input_tokens, 0)

    def test_usage_from_failed_parsing_is_counted_and_not_spent_as_question(self):
        self.model.invoke.return_value = {
            "raw": AIMessage(content="", usage_metadata={
                "input_tokens": 12, "output_tokens": 8, "total_tokens": 20},
                response_metadata={"finish_reason": "length"}),
            "parsed": None, "parsing_error": ValueError("Synthetic error")}
        with self.assertRaises(ModelResponseError):
            self.session.respond("Current message")
        stats = self.session.statistics
        self.assertEqual(stats.failures, 1)
        self.assertEqual(stats.total_output_tokens, 8)
        self.assertTrue(stats.limit_reached)
        self.assertEqual(self.session.remaining, self.config["interaction_limit"])

    def test_network_failure_clears_previous_usage_and_records_failure(self):
        self.session.respond("Current message")
        self.model.invoke.side_effect = RuntimeError("Synthetic network failure")
        with self.assertRaises(RuntimeError):
            self.session.repeat()
        stats = self.session.statistics
        self.assertEqual((stats.successes, stats.failures), (1, 1))
        self.assertIsNone(stats.input_tokens)
        self.assertIsNone(stats.output_tokens)

    def test_truncated_parsed_response_preserves_question_and_replays_incomplete_request(self):
        self.session.respond("Successful message")
        remaining = self.session.remaining
        self.model.invoke.return_value = {
            "raw": AIMessage(content="", usage_metadata={
                "input_tokens": 12, "output_tokens": 8, "total_tokens": 20},
                response_metadata={"finish_reason": "length"}),
            "parsed": Reaction(reply="Parseable but truncated", emoji="🙂"),
            "parsing_error": None,
        }
        for action in (lambda: self.session.respond("Truncated message"), self.session.repeat):
            with self.assertRaises(TokenLimitResponse) as caught:
                action()
            self.assertEqual(caught.exception.partial.reply, "Parseable but truncated")
            self.assertEqual(self.session.remaining, remaining)
        stats = self.session.statistics
        self.assertEqual((stats.successes, stats.failures), (1, 2))
        self.assertTrue(stats.limit_reached)
        self.assertEqual((stats.total_input_tokens, stats.total_output_tokens), (24, 16))
        self.model.invoke.return_value = Reaction(reply="Successful repeat", emoji="🙂")
        self.session.repeat()
        self.assertEqual(self.model.invoke.call_args.args[0][-1], ("human", "Truncated message"))

    def test_partial_json_recovery_decodes_text_and_allows_missing_emoji(self):
        for content, expected in (
            ('{"reply":"Hello\\nworld', "Hello\nworld"),
            ('{"reply":"Hello", "emoji":"', "Hello"),
            ('{"reply":', ""),
        ):
            with self.subTest(content=content):
                error = TokenLimitResponse(AIMessage(content=content))
                self.assertEqual(error.partial.reply, expected)
                self.assertEqual(error.partial.emoji, "")

    def test_truncated_tool_arguments_are_recovered(self):
        raw = AIMessage(content="", additional_kwargs={"tool_calls": [{
            "id": "partial-call", "type": "function", "function": {
                "name": "Reaction", "arguments": '{"reply":"Partial tool reply'}}]})
        self.assertEqual(TokenLimitResponse(raw).partial.reply, "Partial tool reply")


class ModelFactoryTest(unittest.TestCase):
    def test_sdk_truncation_keeps_reported_usage_and_limit_flag(self):
        config = app_settings()
        def handle(request):
            return httpx.Response(200, json={
                "id": "synthetic-response", "object": "chat.completion", "created": 0,
                "model": config["model_name"],
                "usage": {"prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 20},
                "choices": [{"index": 0, "finish_reason": "length", "message": {
                    "role": "assistant", "content": '{"reply":"Partial SDK reply'}}],
            })
        with httpx.Client(transport=httpx.MockTransport(handle)) as transport:
            model = create_model(config, {
                "API_KEY": "synthetic-key", "OPENAI_API_BASE": "https://example.invalid/v1"
            }, http_client=transport)
            session = Conversation(config, "{{requested_format}} about {{realm}}", ["Synthetic realm"], ["Synthetic starter"],
                                   model, lambda items: items[0])
            with self.assertRaises(TokenLimitResponse) as caught:
                session.respond("Synthetic message")
            self.assertEqual(caught.exception.partial.reply, "Partial SDK reply")
            self.assertTrue(session.can_repeat)
            self.assertEqual(session.remaining, config["interaction_limit"])
        self.assertEqual(session.statistics.output_tokens, 8)
        self.assertTrue(session.statistics.limit_reached)
        self.assertEqual(session.statistics.failures, 1)

    def test_real_langchain_serializes_changed_repeat_parameters(self):
        config = app_settings()
        payloads = []

        def handle(request):
            payloads.append(json.loads(request.content))
            return httpx.Response(200, json={
                "id": "synthetic-response", "object": "chat.completion", "created": 0,
                "model": config["model_name"],
                "choices": [{"index": 0, "finish_reason": "stop", "message": {
                    "role": "assistant", "content": Reaction(
                        reply="Synthetic response", emoji="🙂").model_dump_json()}}],
            })

        with httpx.Client(transport=httpx.MockTransport(handle)) as transport:
            model = create_model(config, {
                "API_KEY": "synthetic-key", "OPENAI_API_BASE": "https://example.invalid/v1"
            }, http_client=transport)
            session = Conversation(config, "{{requested_format}} about {{realm}}", ["Synthetic realm"], ["Synthetic starter"],
                                   model, lambda items: items[0])
            session.respond("Synthetic message")
            remaining = session.remaining
            changed = {name: spec["max"] for name, spec in config["model_parameters"].items()}
            changed["temperature"] = 0.12  # Regression for the reported slider position.
            session.repeat(changed, requested_format="True Story", user_message="Edited message")
        self.assertEqual(len(payloads), 2)
        self.assertEqual(payloads[1]["messages"][1]["content"], "Edited message")
        self.assertIn("True Story about Synthetic realm", payloads[1]["messages"][0]["content"])
        for payload, parameters in zip(payloads, (generation_parameters(config), changed)):
            for name, value in parameters.items():
                # Current OpenAI SDK may normalize the token-limit field name.
                field = "max_completion_tokens" if name == "max_tokens" and "max_completion_tokens" in payload else name
                self.assertEqual(payload[field], value)
        self.assertEqual(session.remaining, remaining)

    @patch("scripts.conversation.ChatOpenAI")
    def test_client_and_structured_output_use_shared_configuration(self, client_class):
        config = app_settings()
        credentials = {"API_KEY": "synthetic-key", "OPENAI_API_BASE": "https://example.invalid/v1"}
        transport = Mock()
        result = create_model(config, credentials, http_client=transport)
        client_class.assert_called_once_with(
            model=config["model_name"], api_key=credentials["API_KEY"],
            base_url=credentials["OPENAI_API_BASE"], timeout=config["request_timeout_seconds"],
            max_retries=config["request_max_retries"], http_client=transport,
            **generation_parameters(config),
        )
        structured = client_class.return_value.model_copy.return_value
        result.invoke([("human", "Synthetic message")])
        structured.with_structured_output.assert_called_once_with(
            Reaction, include_raw=True, method=config["structured_output_method"], strict=True,
        )
        structured.with_structured_output.return_value.invoke.assert_called_once()
