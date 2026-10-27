"""Live API connectivity check. Run: python test/connectivity_test.py.

Reads the project-root config.json and checks the OpenAI-compatible /models
endpoint. This is an integration test, not an isolated unit test. It does not
generate text or establish whether a particular model can be invoked.
"""

import json
from pathlib import Path
import unittest
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


class ConnectivityTest(unittest.TestCase):
    def test_api_key_can_list_models(self):
        project_root = Path(__file__).resolve().parent.parent
        config_path = project_root / "config.json"
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.fail("Cannot read valid JSON from the project-root config.json.")

        self.assertIsInstance(config, dict, "config.json must contain a JSON object.")
        try:
            settings = json.loads(
                (project_root / "config/RobGPT_config.json").read_text(encoding="utf-8")
            )
            timeout = settings["request_timeout_seconds"]
        except (OSError, ValueError, KeyError, TypeError):
            self.fail("Set request_timeout_seconds in config/RobGPT_config.json.")
        key = config.get("API_KEY")
        base = config.get("OPENAI_API_BASE")
        self.assertTrue(
            isinstance(key, str) and key.strip(),
            "Set API_KEY in the project-root config.json (not .cursor/config.json).",
        )
        self.assertTrue(
            isinstance(base, str) and base.strip(),
            "Set OPENAI_API_BASE in the project-root config.json.",
        )
        parts = urlsplit(base)
        self.assertTrue(
            parts.scheme == "https" and parts.hostname
            and not parts.username and not parts.password
            and not parts.query and not parts.fragment,
            "OPENAI_API_BASE must be an HTTPS base URL without credentials or query parameters.",
        )
        request = Request(
            base.rstrip("/") + "/models",
            headers={"Authorization": "Bearer " + key, "Accept": "application/json"},
        )
        try:
            with urlopen(request, timeout=timeout) as response:
                payload = json.load(response)
        except HTTPError as error:
            messages = {
                401: "Authentication rejected. Check the API key and endpoint pairing.",
                403: "Access forbidden. Check key permissions and gateway restrictions.",
                404: "The /models endpoint was not found; this does not prove the key is invalid.",
                429: "Rate limit or quota exceeded; retry later or check your account quota.",
            }
            self.fail(f"HTTP {error.code}: " + messages.get(
                error.code, "API request failed. Check gateway availability."
            ))
        except (URLError, TimeoutError, OSError):
            self.fail("Connection failed. Check the endpoint, network, and TLS certificates.")
        except ValueError:
            self.fail("The endpoint returned invalid JSON.")

        self.assertIsInstance(payload, dict, "Expected a model-list JSON object.")
        self.assertIsInstance(payload.get("data"), list, "Expected a 'data' model list.")


if __name__ == "__main__":
    unittest.main(verbosity=2)
