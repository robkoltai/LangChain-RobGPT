# RobGPT project plan

Status: all application modules implemented and wired, including parameter sliders, templated prompts, format selection, and Repeat; offline unit tests pass.
The live structured-output test passes with the current configured defaults. A hidden real-Tk widget smoke check passes using a fake model. Visual review and a complete live GUI conversation remain pending.

## Goal and scope

- A fun, learning-focused hobby project: a first demo one level above Hello World.
- Learn the basics of LangChain through a small working application.
- Keep the architecture simple while maintaining clear structure and modularity.
- Run directly from the terminal as a Python application, without Jupyter.

## Development process

Proceed systematically through these stages:

1. Requirements.
2. Architecture design.
3. Test plan and stubs.
4. Implementation.
5. Tests.
6. Play with the application.

Work iteratively: test and refine after a few tests rather than waiting until the end.

## Functional requirements

### Window and layout

- Open a new window using the title defined in `config/RobGPT_config.json`.
- Place two textboxes in the center of the window:
  - Upper textbox for the model's reply.
  - Lower textbox for the user's input.
  - Read both labels from `config/RobGPT_config.json`.
- Display relatively large emojis in a box at the top right of the window.
- Have the model choose emojis based on the current user's interaction.
- Offer radio buttons for the configured response formats. Format selection applies to new Send requests and is disabled after the interaction limit; Repeat retains the original format.
- Place the parameter sliders and vertically arranged format radio buttons in a right-hand controls panel; keep conversation textboxes on the left. Panel width and window dimensions are defined in the app configuration. The header and statistics span both columns.
- Display a countdown of the remaining questions in a box, preferably on the left.
- Provide sliders for temperature, Top P (a probability fraction), and maximum output tokens. Their labels, defaults, bounds, and steps are defined only in `model_parameters` in `config/RobGPT_config.json`.
- Provide a Repeat button whose label is defined in the app configuration. It is disabled until a request has succeeded.
- Display account balance availability, latest input/output tokens, reported session input/output token totals, missing-usage call count, latest request duration, Send/Repeat counts, success/failure counts, and whether the latest generation hit its token limit. Do not display estimated cost or last-used parameters.

### Conversation

- Allow the number of interactions defined in `config/RobGPT_config.json`.
- For each new interaction, render the single configured system template with a randomly chosen realm and the response format selected in the UI. Keep the rendered system message hidden.
- For non-final interactions, append `next_question_text` from `config/RobGPT_config.json` to the rendered system prompt. Omit this continuation instruction on the final interaction.
- Use prompts to produce surprising responses, including funny, sad, and interesting responses.
- Keep no conversation transcript and persist no messages. Retain only the latest successful system/user message pair in memory to support Repeat. Each model call sends only that interaction's system and user messages, never earlier turns.
- Append the configured farewell text to the final reply.
- Keep the window open with the final reply and emoji visible after the final interaction. Disable new-message input and Send; keep parameter sliders and Repeat available. The user closes the window using its normal window controls.
- Read the farewell text from `config/RobGPT_config.json`. There is no automatic closing timer or closing-delay setting.
- The user supplies and edits the single template and the realm list; do not modify their content automatically.
- If a request fails, report an error and leave the remaining-question count unchanged so the user can retry.
- Distinguish empty input, invalid slider values, and incomplete/unreadable model output with specific guidance from the app configuration. Empty Send input directs the user to type a message or use Repeat; never expose raw API responses or credentials in errors.
- Read the model name from the `model_name` field in `config/RobGPT_config.json`.
- Obtain the reply and model-selected emoji in one model call, using a shared Pydantic schema with `reply` and `emoji` fields.
- Treat structured-output parsing or validation failures as failed requests.

### Parameter experiments and Repeat

- Apply the current slider values to both Send and Repeat requests; initialize them from the configured defaults.
- Temperature and Top P bounds follow the [OpenAI Chat Completions API](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create); the token slider uses the user-requested bounds recorded in configuration.
- Repeat resends the exact latest successful system/user message pair, including its original continuation instruction when applicable. Do not choose a new realm, re-render with a newly selected format, decrement the counter, or include unsubmitted input text. Format changes affect the next Send, not Repeat.
- A successful new Send replaces the saved pair; failed sends/repeats preserve it and the counter. Repeat keeps any unsubmitted draft intact.
- Repeat remains available after the final interaction and preserves the final farewell behavior without consuming another interaction.
- One Send or Repeat makes one model invocation returning both reply and emoji. Disable request controls while it runs and restore them appropriately afterward.
- The maximum-token value limits the generated structured response, including JSON and emoji, rather than just the visible reply. If the limit causes truncation/parsing failure, show the usual error and preserve the counter.

### Statistics and provider balance

- Retain only numeric usage/timing/count statistics, not a conversation transcript. Send and Repeat both contribute to session totals; rejected blank input and invalid parameters do not count as model requests.
- Keep provider-reported usage even if parsing fails. Count those requests as failures and leave the question count unchanged.
- Missing token usage or finish-reason metadata is unavailable, never inferred as zero or a successful non-truncated finish. Session totals show reported tokens only and identify calls with missing usage.
- Response time measures the model invocation and parsing, including failed requests. Request counters count application model invocations; provider/SDK retries can make additional HTTP requests if enabled in configuration.
- Account balance currently displays the configured unavailable message: no documented balance endpoint for the configured gateway was found. The application does not invent a balance, estimate it from usage, or probe speculative billing endpoints.
- Statistics labels, unavailable messages, duration formatting, and font size come from `config/RobGPT_config.json`.

### Prompt and conversation-starter files

- Use only `prompts/system_prompt.txt` as the system template, selected by `system_prompt_file` in the app configuration. Old numbered prompt files are not loaded.
- Substitute `{{realm}}` using a random nonempty line from `prompts/list_of_realms.txt`, selected by `realms_file`.
- Substitute `{{requested_format}}` using the selected radio-button value. Choices and the default selection are defined by `requested_formats` and `default_format_index` in the app configuration; the UI label is also configured there.
- Require both template variables and reject unknown variables. Substitute literal text once without executing template content or recursively interpreting values.
- Store conversation starters in `prompts/starter_lines.txt`, with one starter per nonempty line, selected by `starter_file` in the app configuration.
- Randomly select a starter and display it when the window opens, without consuming a user interaction.
- Random realm selection may repeat a previous realm. Repeat explicitly reuses the previous successful rendered prompt.

### Central configuration

- Store all application constants and default values in `config/RobGPT_config.json`.
- This includes window dimensions, window title, UI labels, emoji sizing, interaction limit, farewell text, model settings, and configurable resource paths.
- Keep API credentials and the API base URL in the existing project-root `config.json`, separate from application settings. Do not duplicate them in `config/RobGPT_config.json`.
- Do not duplicate these values in source code, fallback defaults, documentation, prose, or tests.
- Documentation and tests must reference or load `config/RobGPT_config.json` for the actual values instead of restating them.
- Prompt content and conversation-starter content remain authoritative in their respective text files; configuration references those resources rather than copying their contents.
- Application configuration values are populated; this plan references their authoritative configuration fields without repeating the values.

### Interaction during API calls

- Freezing the UI while waiting for an LLM response is acceptable.
- The application is single-user and single-threaded; do not add background threads for API calls.

## Architecture principles and constraints

- Use LangChain for the LLM integration.
- Define each idea, instruction, and constant in one authoritative place; avoid duplication.
- Use a structured, modular design, with potential reuse of parts in future projects.
- Keep module boundaries proportional to this small learning project; avoid unnecessary architectural complexity.
- Use Tkinter for the GUI as part of the accepted architecture.

## Accepted module structure

| Module | Responsibility |
|---|---|
| `scripts/RobGPT.py` | Load resources, connect components, launch the application. |
| `scripts/settings.py` | Load and validate application settings, credentials, starters, the system template, and realms. |
| `scripts/conversation.py` | Shared response schema, LangChain model construction, template rendering and realm selection, per-call parameters, replay of the latest successful request, and remaining-question state. |
| `scripts/window.py` | Tkinter widgets, submission handling, response/error display, and disabling input when the conversation finishes. |

Inject the structured model and random chooser into conversation logic so unit tests need no network. Window tests use an injected fake root and mock display methods rather than opening a real window. GUI layout and font rendering require manual checks during implementation.

## Unit test plan and current status

- `test/test_settings.py`: configuration loading, required settings, resource selection, and empty-resource handling. Tests use temporary files and synthetic credentials, never live secrets.
- `test/test_conversation.py`: starter selection, realm selection and format rendering, continuation instruction on non-final interactions only, one invocation per reaction, no history, countdown, failures/retry, invalid output, blank input, farewell, and interaction exhaustion.
- `test/test_window.py`: starter display, response/emoji/count updates, error reporting, and leaving the final reply visible with input disabled until the user closes the window.
- `test/test_entrypoint.py`: startup dependency wiring, stopping on invalid configuration or missing resources, and destroying the root if widget construction fails.
- All application-default assertions load `config/RobGPT_config.json`; synthetic inputs are test fixtures rather than duplicated application defaults.
- Run offline unit tests with `python -m unittest discover -s test -p 'test_*.py'`.
- Settings verification: all settings unit tests pass, including invalid/missing configuration, secret-safe error messages, resource loading, template-variable validation, realm parsing, and format choices. Actual project settings and all configured resources load successfully.
- Conversation verification: all conversation and model-factory unit tests pass. They cover continuation instructions, one invocation, no history, count preservation on errors, final-reply behavior, and configured LangChain construction without network calls.
- Window verification: mocked-widget tests cover configured dimensions, initial display, response/emoji/count updates, error privacy, preserving input on failure, disabling final input, blocking further submissions, and keeping the completed window open without scheduling or invoking closure.
- All offline unit tests pass. Direct-script startup from another working directory also passed using the actual project files and mocked model/window. A hidden real-Tk smoke check verified slider defaults, final-interaction state, changed Repeat parameters, identical replay messages, and unchanged counts with a fake model. The actual GUI layout and emoji appearance have not yet been visually verified.
- Parameter/Repeat tests cover configured slider construction, value validation and forwarding, replay without realm reselection or prompt re-rendering or count changes, preserving drafts and saved requests on errors, and replay after completion. An offline HTTP transport test checks real LangChain serialization of both requests.
- Numeric regression tests cover every configured slider tick, exact boundaries and immediately out-of-range values, nonfinite/boolean/string inputs, and the reported decimal temperature. Error-display regressions distinguish an empty Send from invalid parameters and parsing failures.
- Statistics tests cover reported and missing usage, timing, totals across Repeat, success/failure accounting, failed parsing with reported usage, SDK truncation, unavailable balance, and display formatting. The HTTP serialization regression also ensures slider overrides survive raw-metadata collection.
- Existing `connectivity_test.py` and `structured_output_test.py` remain explicitly run live integration tests, excluded by the offline discovery pattern.
- UI and lifecycle behavior is implemented using the app configuration. Initial values remain adjustable during visual review and play-testing.

## Planning stages still to complete

- Review application settings during play-testing; retain the root `config.json` for API credentials and the API base URL.
- Visually review the running GUI and test a complete conversation using the wired entry point.

## Running the application

- From the project root, use the project environment: `.venv/bin/python scripts/RobGPT.py`.
- Startup resolves configuration and resource paths from the script location, independent of the terminal's working directory.
- No model request is made until the user submits a message; the opening starter comes from its configured text file.
- To experiment, send a message, change slider values, then click Repeat. The reply and emoji are replaced while the question count stays unchanged.

## Architecture feasibility check

- `test/structured_output_test.py` successfully exercised LangChain's native JSON-schema structured output against the configured gateway.
- Evidence: the live test passed, returned a validated reply and emoji, and counted exactly one HTTP request.
- The test reads model, request settings, and test messages from `config/RobGPT_config.json`; credentials remain in the root `config.json`.
- The live test reuses the implemented settings loaders and model factory. It was rerun successfully with the current parameter defaults, counted exactly one HTTP request, and confirmed that the gateway returns input/output token usage metadata.
- A hidden real-Tk check with a fake model verified statistics rendering and session totals across Send and Repeat. Manual visual review of the complete layout remains pending.
- This check verifies the response structure and nonempty fields; emoji quality and relevance still require manual evaluation.

## Template and format verification

- Offline tests cover loading the single template and moved starters, blank/missing realms, required/unknown variables, all configured format choices, per-Send realm selection, exact replay, and radio-button forwarding.
- A hidden real-Tk smoke check passed with the actual project resources and a fake model: configured format selection renders correctly, and changing it does not alter Repeat's saved prompt or question count.
- No live API calls are needed for this change; gateway access was last reported as locked out.
