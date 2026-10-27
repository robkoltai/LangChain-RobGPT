"""Single-threaded Tkinter view. Importing this module must not open a window."""

import tkinter as tk
from scripts.conversation import EmptyMessageError, ModelResponseError
from scripts.settings import GenerationParameterError


class Window:
    def __init__(self, settings: dict, conversation, root):
        """Build configured widgets on the supplied Tk root; retain dependencies."""
        self.settings = settings
        self.conversation = conversation
        self.root = root
        self._busy = False
        self._completed = False
        root.title(settings["window_title"])
        root.geometry(f"{settings['window_width']}x{settings['window_height']}")
        root.columnconfigure(0, weight=1)
        root.columnconfigure(1, weight=0, minsize=settings["controls_width"])
        root.rowconfigure(2, weight=1)
        root.rowconfigure(4, weight=1)
        padding = settings["ui_padding"]
        font = (settings["text_font_family"], settings["text_font_size"])

        header = tk.Frame(root)
        header.grid(row=0, column=0, columnspan=2, sticky="ew", padx=padding, pady=padding)
        header.columnconfigure(0, weight=1)
        self.counter = tk.Label(header, font=font)
        self.counter.grid(row=0, column=0, sticky="w")
        self.emoji = tk.Label(
            header, font=(settings["text_font_family"], settings["emoji_font_size"])
        )
        self.emoji.grid(row=0, column=1, sticky="e")

        tk.Label(root, text=settings["reply_label"], font=font).grid(
            row=1, column=0, sticky="w", padx=padding)
        self.reply_box = tk.Text(
            root, wrap="word", font=font, height=settings["reply_box_height"], state="disabled")
        self.reply_box.grid(row=2, column=0, sticky="nsew", padx=padding)
        tk.Label(root, text=settings["input_label"], font=font).grid(
            row=3, column=0, sticky="w", padx=padding, pady=padding)
        self.input_box = tk.Text(
            root, wrap="word", font=font, height=settings["input_box_height"])
        self.input_box.grid(row=4, column=0, sticky="nsew", padx=padding)

        controls = tk.Frame(root)
        controls.grid(row=1, column=1, rowspan=4, sticky="nsew", padx=padding, pady=padding)
        controls.columnconfigure(0, weight=1)
        self.parameter_sliders = {}
        for row, (name, spec) in enumerate(settings["model_parameters"].items()):
            slider = tk.Scale(
                controls, label=spec["label"], from_=spec["min"], to=spec["max"],
                resolution=spec["step"], orient="horizontal", font=font,
            )
            slider.set(spec["default"])
            slider.grid(row=row, column=0, sticky="ew", pady=padding)
            self.parameter_sliders[name] = slider

        formats = tk.Frame(controls)
        formats.grid(row=len(self.parameter_sliders), column=0, sticky="ew", pady=padding)
        tk.Label(formats, text=settings["format_label"], font=font).grid(row=0, column=0, sticky="w")
        self.format_var = tk.StringVar(
            master=root, value=settings["requested_formats"][settings["default_format_index"]])
        self.format_buttons = []
        for row, value in enumerate(settings["requested_formats"], start=1):
            button = tk.Radiobutton(formats, text=value, value=value,
                                    variable=self.format_var, font=font)
            button.grid(row=row, column=0, sticky="w")
            self.format_buttons.append(button)

        actions = tk.Frame(root)
        actions.grid(row=5, column=0, sticky="e", padx=padding, pady=padding)
        self.send_button = tk.Button(
            actions, text=settings["send_button_text"], font=font,
            command=lambda: self.submit(self.input_box.get("1.0", "end-1c")))
        self.send_button.grid(row=0, column=0, padx=padding)
        self.repeat_button = tk.Button(
            actions, text=settings["repeat_button_text"], font=font, command=self.repeat)
        self.repeat_button.grid(row=0, column=1)
        self.status = tk.Label(root, font=font, anchor="w", justify="left",
                               wraplength=settings["window_width"] - 2 * padding)
        self.status.grid(row=6, column=0, columnspan=2, sticky="ew", padx=padding, pady=padding)
        self.statistics_box = tk.Label(
            root, font=(settings["text_font_family"], settings["statistics_font_size"]),
            anchor="w", justify="left", wraplength=settings["window_width"] - 2 * padding)
        self.statistics_box.grid(row=7, column=0, columnspan=2, sticky="ew", padx=padding, pady=padding)
        self._update_controls()

    def display_statistics(self):
        stats = self.conversation.statistics
        unavailable = self.settings["statistics_unavailable_text"]
        values = vars(stats).copy()
        values["input_tokens"] = stats.input_tokens if stats.input_tokens is not None else unavailable
        values["output_tokens"] = stats.output_tokens if stats.output_tokens is not None else unavailable
        values["balance"] = self.settings["balance_unavailable_text"]
        values["duration"] = (self.settings["statistics_duration_text"].format(seconds=stats.duration_seconds)
                              if stats.duration_seconds is not None else unavailable)
        values["limit_reached"] = (unavailable if stats.limit_reached is None else
                                   self.settings["statistics_yes_text"] if stats.limit_reached else
                                   self.settings["statistics_no_text"])
        self.statistics_box.configure(text=self.settings["statistics_text"].format(**values))

    def _parameters(self) -> dict:
        return {name: int(slider.get()) if name == "max_tokens" else float(slider.get())
                for name, slider in self.parameter_sliders.items()}

    def _update_controls(self):
        self._enable_input(not self._busy and not self._completed)
        self.repeat_button.configure(
            state="normal" if not self._busy and self.conversation.can_repeat else "disabled")
        for slider in self.parameter_sliders.values():
            slider.configure(state="disabled" if self._busy else "normal")
        for button in self.format_buttons:
            button.configure(state="normal" if not self._busy and not self._completed else "disabled")

    def _enable_input(self, enabled: bool):
        state = "normal" if enabled else "disabled"
        self.input_box.configure(state=state)
        self.send_button.configure(state=state)
        if enabled:
            self.input_box.focus_set()

    def run(self):
        """Display the starter and remaining count, then enter root.mainloop()."""
        self.display(self.conversation.start(), "", self.conversation.remaining)
        self.display_statistics()
        self.input_box.focus_set()
        self.root.mainloop()

    def submit(self, user_message: str):
        """Display reply/emoji/count, or report an error without decrementing.

        After displaying the final reply, disable input and keep the window open
        until the user closes it using the normal window controls.
        """
        if self._busy or self._completed:
            return
        self._request(user_message=user_message)

    def repeat(self):
        """Regenerate the previous successful request using current slider values."""
        if self._busy or not self.conversation.can_repeat:
            return
        self._request(repeat=True)

    def _request(self, user_message=None, repeat=False):
        self._busy = True
        self._update_controls()
        self.status.configure(text="")
        self.root.update_idletasks()
        try:
            parameters = self._parameters()
            result = (self.conversation.repeat(parameters) if repeat
                      else self.conversation.respond(
                          user_message, parameters, requested_format=self.format_var.get()))
        except Exception as error:
            self.show_error(error)
        else:
            self.display(result.reply, result.emoji, self.conversation.remaining)
            if not repeat:
                # Repeat preserves any unsubmitted draft in the input box.
                self.input_box.configure(state="normal")
                self.input_box.delete("1.0", "end")
            self._completed = self.conversation.finished
        finally:
            self._busy = False
            self._update_controls()
            self.display_statistics()

    def display(self, reply: str, emoji: str, remaining: int):
        """Replace the visible response, emoji, and remaining count."""
        self.reply_box.configure(state="normal")
        self.reply_box.delete("1.0", "end")
        self.reply_box.insert("1.0", reply)
        self.reply_box.configure(state="disabled")
        self.emoji.configure(text=emoji)
        self.counter.configure(text=self.settings["remaining_text"].format(remaining=remaining))
        self.root.update_idletasks()

    def show_error(self, error: Exception):
        """Show a useful error without exposing credentials or hidden prompts."""
        # Exception messages can contain credentials or hidden prompts. Show only
        # their class, alongside the configured retry guidance.
        if isinstance(error, EmptyMessageError):
            text = self.settings["empty_message_error_text"]
        elif isinstance(error, GenerationParameterError):
            text = self.settings["parameter_error_text"].format(parameter=error.parameter)
        elif isinstance(error, ModelResponseError):
            text = self.settings["response_error_text"]
        else:
            text = self.settings["error_text"].format(error_type=type(error).__name__)
        self.status.configure(text=text)
