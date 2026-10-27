"""Conversation state and one-call LangChain integration."""

from dataclasses import dataclass
from time import perf_counter
from pydantic import BaseModel, Field, ValidationError
from openai import LengthFinishReasonError
from langchain_core.exceptions import OutputParserException
from langchain_openai import ChatOpenAI
from scripts.settings import generation_parameters, render_prompt_template, validate_prompt_template


@dataclass
class SessionStatistics:
    """Usage reported by the provider; missing metadata is never guessed."""

    send_calls: int = 0
    repeat_calls: int = 0
    successes: int = 0
    failures: int = 0
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    unreported_usage_calls: int = 0
    duration_seconds: float | None = None
    limit_reached: bool | None = None


class EmptyMessageError(ValueError):
    """Send was pressed without a message; no model request was made."""


class ModelResponseError(ValueError):
    """The generated response was truncated, malformed, or missing required content."""


class Reaction(BaseModel):
    """Shared structured-output contract for the application and live test."""

    reply: str = Field(description="The conversational reply to the user.")
    emoji: str = Field(description="An emoji reflecting the user's message.")


class StructuredModel:
    """Bind per-call parameters before LangChain's raw/parsed response mapping."""

    def __init__(self, model, options):
        self.model = model
        self.options = options

    def invoke(self, messages, **parameters):
        # include_raw uses a RunnableMap that does not forward invoke kwargs.
        # Copying model settings preserves its HTTP client and binds sliders first.
        model = self.model.model_copy(update=parameters)
        return model.with_structured_output(
            Reaction, include_raw=True, **self.options).invoke(messages)


def create_model(settings: dict, credentials: dict, *, http_client=None):
    """Build a LangChain model returning Reaction through structured output."""
    model = ChatOpenAI(
        model=settings["model_name"],
        api_key=credentials["API_KEY"],
        base_url=credentials["OPENAI_API_BASE"],
        timeout=settings["request_timeout_seconds"],
        max_retries=settings["request_max_retries"],
        http_client=http_client,
        **generation_parameters(settings),
    )
    options = {"method": settings["structured_output_method"]}
    if options["method"] != "json_mode":
        options["strict"] = True
    return StructuredModel(model, options)


class Conversation:
    def __init__(self, settings: dict, template: str, realms: list[str], starters: list[str], model, choose):
        """Inject a structured model and random.choice-compatible chooser.

        Keep only the latest successful request for Repeat, never a transcript.
        """
        validate_prompt_template(template)
        if not realms or not starters:
            raise ValueError("Conversation requires realms and starters.")
        self._settings = settings
        self._template = template
        self._realms = realms
        self._starters = starters
        self._model = model
        self._choose = choose
        self._remaining = settings["interaction_limit"]
        self._last_request = None
        self.statistics = SessionStatistics()

    @property
    def remaining(self) -> int:
        return self._remaining

    @property
    def finished(self) -> bool:
        return self.remaining == 0

    @property
    def can_repeat(self) -> bool:
        return self._last_request is not None

    def start(self) -> str:
        """Choose a starter without changing the remaining count."""
        return self._choose(self._starters)

    def respond(self, user_message: str, parameters: dict | None = None,
                requested_format: str | None = None) -> Reaction:
        """Render the template with a random realm and selected UI format.

        Append configured next_question_text to the system prompt unless this
        is the final interaction. Never include previous conversation messages.
        On valid success decrement remaining and append the configured farewell
        on the final reply. On failure preserve remaining and propagate the error.
        Reject blank input, empty output fields, and submissions after completion.
        """
        if self.finished:
            raise ValueError("No interactions remaining.")
        if not isinstance(user_message, str) or not user_message.strip():
            raise EmptyMessageError("Enter a nonempty message.")

        if requested_format is None:
            requested_format = self._settings["requested_formats"][self._settings["default_format_index"]]
        if requested_format not in self._settings["requested_formats"]:
            raise ValueError("Select a configured response format.")
        generation_parameters(self._settings, parameters)
        prompt = render_prompt_template(self._template, self._choose(self._realms), requested_format)
        if self.remaining > 1:
            prompt += "\n\n" + self._settings["next_question_text"]
        messages = (("system", prompt), ("human", user_message))
        final = self.remaining == 1
        result = self._invoke(messages, parameters, final, repeat=False)
        self._last_request = (messages, final)
        self._remaining -= 1
        return result

    def repeat(self, parameters: dict | None = None) -> Reaction:
        """Resend the exact last successful request with new parameters; no count change."""
        if not self.can_repeat:
            raise ValueError("Send a message successfully before using Repeat.")
        messages, final = self._last_request
        return self._invoke(messages, parameters, final, repeat=True)

    def _record_usage(self, raw):
        stats = self.statistics
        usage = getattr(raw, "usage_metadata", None)
        metadata = getattr(raw, "response_metadata", None) or {}
        if isinstance(usage, dict):
            stats.input_tokens = usage.get("input_tokens")
            stats.output_tokens = usage.get("output_tokens")
        # The OpenAI SDK can raise on truncation before LangChain returns a message.
        sdk_usage = getattr(raw, "usage", None)
        if sdk_usage is not None:
            stats.input_tokens = sdk_usage.prompt_tokens
            stats.output_tokens = sdk_usage.completion_tokens
        reason = metadata.get("finish_reason")
        choices = getattr(raw, "choices", None)
        if choices:
            reason = choices[0].finish_reason
        stats.limit_reached = reason == "length" if reason else None

    def _invoke(self, messages, parameters, final: bool, repeat: bool) -> Reaction:
        values = generation_parameters(self._settings, parameters)
        stats = self.statistics
        if repeat:
            stats.repeat_calls += 1
        else:
            stats.send_calls += 1
        stats.input_tokens = stats.output_tokens = None
        stats.limit_reached = None
        started = perf_counter()
        try:
            response = self._model.invoke(list(messages), **values)
            if isinstance(response, dict):
                self._record_usage(response.get("raw"))
                if response.get("parsing_error"):
                    raise ModelResponseError("The model response could not be parsed.")
                result = response.get("parsed")
            else:
                # Also accept simple injected models in offline tests.
                result = response
            if not isinstance(result, Reaction) or not result.reply.strip() or not result.emoji.strip():
                raise ModelResponseError("The model must return a nonempty reply and emoji.")
        except LengthFinishReasonError as error:
            self._record_usage(error.completion)
            stats.limit_reached = True
            stats.failures += 1
            raise ModelResponseError("The model response reached its token limit.") from None
        except (OutputParserException, ValidationError):
            stats.failures += 1
            raise ModelResponseError("The model response could not be parsed.") from None
        except Exception:
            stats.failures += 1
            raise
        else:
            stats.successes += 1
        finally:
            stats.duration_seconds = perf_counter() - started
            if stats.input_tokens is not None:
                stats.total_input_tokens += stats.input_tokens
            if stats.output_tokens is not None:
                stats.total_output_tokens += stats.output_tokens
            if stats.input_tokens is None or stats.output_tokens is None:
                stats.unreported_usage_calls += 1

        if final:
            result = result.model_copy(update={
                "reply": result.reply.rstrip() + "\n\n" + self._settings["farewell_text"]
            })
        return result
