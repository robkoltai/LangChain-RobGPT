# RobGPT

A small Python desktop chatbot for learning LangChain and experimenting with LLMs. It combines a system-prompt template, a random realm, and a user-selected response format to generate surprising replies and emojis.

Use the sliders to experiment with generation parameters. **Send** submits **Current message** as a new interaction. **Repeat with different settings** submits the editable **Previous message** using the current sliders and response format, preserving the original realm and remaining-question count. The final reply stays visible until you close the window.

## Requirements

- Python with Tkinter. The project has been tested with Homebrew Python 3.15 on macOS.
- Python packages listed in [requirements.txt](requirements.txt).
- An API key and HTTPS base URL for an OpenAI-compatible provider supporting the configured model and structured-output method. API access and available credit are required for live requests.
- Git to clone the repository. Homebrew is used for the macOS setup below.

## Installation on macOS

Clone the repository and enter it:

```bash
git clone https://github.com/robkoltai/LangChain-RobGPT.git
cd LangChain-RobGPT
```

Install the base Python and its matching Tkinter support if needed:

```bash
brew install python@3.15 python-tk@3.15
```

Create and activate a project-local environment, then install dependencies:

```bash
"$(brew --prefix python@3.15)/bin/python3.15" -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip check
```

Tkinter support belongs to the base Python installation; it is not installed with pip. The virtual environment uses that support. No Jupyter installation is needed.

## API credentials

Create your local credential file from the placeholder template:

```bash
cp -n config_template.json config.json
```

This preserves an existing `config.json`. Edit the local file and replace both placeholders with your provider-issued API key and its HTTPS API base URL. Use a key issued for that endpoint.

The root `config.json` contains secrets and is ignored by Git. [config_template.json](config_template.json) contains placeholders only and can be committed. The application explicitly reads this file; it does not use a ChatGPT login or automatically load credentials from environment variables.

## Run

From the project root:

```bash
.venv/bin/python scripts/RobGPT.py
```

This command does not require activation. Paths to configuration and prompt resources are resolved relative to the project, rather than the terminal's working directory.

Enter text in **Current message**, select a response format, and click **Send** at its top right. After a successful or token-limited response, the submitted text moves to **Previous message** and Current message clears. Other failures preserve both boxes.

Edit Previous message if desired, adjust the sliders or format, and click **Repeat with different settings** at its top right. Repeat uses that lower text and the current settings, keeps the original realm and question count, and leaves any draft in Current message untouched. Previous message remains editable after the last interaction.

The interface shows provider-reported token usage, session totals, request counts, response time, and token-limit status. Missing metadata is shown as unavailable. Account balance is currently unavailable because a working gateway balance endpoint has not been verified.

## Configuration and prompts

Application constants and defaults have one source: [config/RobGPT_config.json](config/RobGPT_config.json). It defines the model, request settings, slider ranges/defaults, format choices, interaction limit, labels, window dimensions, and resource paths. Refer to that file for their actual values.

The configured text resources are:

- [prompts/system_prompt.txt](prompts/system_prompt.txt): the single system template, containing `{{realm}}` and `{{requested_format}}`.
- [prompts/list_of_realms.txt](prompts/list_of_realms.txt): one realm per nonempty line, randomly chosen for each new interaction.
- [prompts/starter_lines.txt](prompts/starter_lines.txt): one starter per nonempty line, randomly chosen at launch.

The configured continuation instruction is appended only for non-final interactions. The configured farewell is appended by the application to the final reply. Failed requests leave the interaction count unchanged. When Max tokens is reached, any recoverable reply is displayed with “Maxtokens reached. Response incomplete”. The submitted text is retained in Previous message and the question count is unchanged; increase Max tokens and click Repeat with different settings to retry.

## AI, tools, and techniques

- **LangChain / ChatOpenAI:** model calls through an OpenAI-compatible API, including per-request generation parameters.
- **Pydantic and structured output:** one model invocation returns a validated reply and emoji; raw response metadata supplies usage statistics.
- **Tkinter:** a single-user, single-threaded desktop interface. The UI can pause during API requests.
- **Template substitution and random selection:** literal placeholder replacement, randomized realms, and selectable response formats.
- **Dependency injection and mocks:** model, random chooser, and GUI dependencies can be replaced for offline tests.
- **Python unittest and HTTPX mock transport:** behavior tests and checks of the real LangChain request serialization without network access.
- **Development tools:** OpenAI Codex, VS Code, Homebrew, Git, and GitHub.

There is no stored conversation transcript. Only the latest successful or token-limited system/user message pair is retained in memory for Repeat, along with numeric session statistics; previous turns are not sent as model context.

## Tests

Run the offline suite without API credentials or network access:

```bash
.venv/bin/python -m unittest discover -s test -p 'test_*.py'
```

Run live integration checks explicitly after configuring credentials:

```bash
.venv/bin/python test/connectivity_test.py
.venv/bin/python test/structured_output_test.py
```

The connectivity check tests model-list access. The structured-output check generates a short reply and emoji and reports usage metadata; it can consume provider credit. Live tests are excluded from the offline discovery pattern.

## Code structure

| File | Responsibility |
|---|---|
| `scripts/RobGPT.py` | Load resources, connect components, launch the window. |
| `scripts/settings.py` | Configuration validation and text-resource loading/rendering. |
| `scripts/conversation.py` | Model setup, request/replay logic, response validation, and statistics. |
| `scripts/window.py` | Widgets, controls, display updates, and error messages. |
| `test/` | Offline unit tests and explicitly run live checks. |

See [project_plan.md](project_plan.md) for the requirements, architecture, and validation notes.
