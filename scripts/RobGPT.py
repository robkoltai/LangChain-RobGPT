"""Entry point for RobGPT. Run with: python scripts/RobGPT.py."""

from pathlib import Path
import random
import sys
import tkinter as tk

# Support both direct script execution and `python -m scripts.RobGPT`.
if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.conversation import Conversation, create_model
from scripts.settings import load_credentials, load_prompt_template, load_realms, load_settings, load_starters
from scripts.window import Window


def main():
    """Load settings/resources, connect the conversation and window, and run."""
    project_root = Path(__file__).resolve().parent.parent
    settings = load_settings(project_root)
    credentials = load_credentials(project_root)
    template = load_prompt_template(project_root, settings)
    realms = load_realms(project_root, settings)
    starters = load_starters(project_root, settings)
    model = create_model(settings, credentials)
    conversation = Conversation(settings, template, realms, starters, model, random.choice)

    root = tk.Tk()
    try:
        window = Window(settings, conversation, root)
    except Exception:
        root.destroy()
        raise
    window.run()


if __name__ == "__main__":
    main()
