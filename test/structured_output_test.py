"""Live gateway test. Run: python test/structured_output_test.py."""

from pathlib import Path
import sys
import unittest

import httpx
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.conversation import Reaction, create_model
from scripts.settings import load_credentials, load_settings


class StructuredOutputTest(unittest.TestCase):
    def test_reply_and_emoji_in_one_request(self):
        root = Path(__file__).resolve().parent.parent
        credentials = load_credentials(root)
        settings = load_settings(root)
        scenario = settings["structured_output_test"]
        requests = []

        # Count actual HTTP requests rather than assuming invoke() sends only one.
        with httpx.Client(event_hooks={"request": [requests.append]}) as client:
            structured_model = create_model(settings, credentials, http_client=client)
            try:
                response = structured_model.invoke([
                    ("system", scenario["system_message"]),
                    ("human", scenario["user_message"]),
                ])
                self.assertIsNone(response["parsing_error"])
                result = response["parsed"]
            except Exception as error:
                # Gateway error bodies may contain credentials; never print them.
                raise self.failureException(
                    f"Structured-output request failed: {type(error).__name__}"
                ) from None

        self.assertEqual(len(requests), 1, "Expected exactly one HTTP request.")
        self.assertIsInstance(result, Reaction)
        self.assertTrue(result.reply.strip(), "Reply must not be empty.")
        self.assertTrue(result.emoji.strip(), "Emoji must not be empty.")
        print("\nValidated response:", result.model_dump_json())
        print("HTTP requests:", len(requests))
        print("Provider usage metadata:", response["raw"].usage_metadata)


if __name__ == "__main__":
    unittest.main(verbosity=2)
