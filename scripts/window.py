"""Single-threaded Tkinter view. Importing this module must not open a window."""

import tkinter as tk
from tkinter import ttk
from scripts.conversation import EmptyMessageError, ModelResponseError, TokenLimitResponse
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
        root.rowconfigure(1, weight=1)
        padding = settings["ui_padding"]
        font = (settings["text_font_family"], settings["text_font_size"])
        # Native Text outlines can disappear when focus moves or state changes.
        # Each field has a separate, permanently visible dark frame instead.
        text_options = dict(
            background="#ffffff", foreground="#000000", insertbackground="#000000",
            borderwidth=0, highlightthickness=2, highlightbackground="#ffffff",
            highlightcolor="#005fcc",
        )

        header = tk.Frame(root)
        header.grid(row=0, column=0, columnspan=2, sticky="ew", padx=padding, pady=padding)
        header.columnconfigure(0, weight=1)
        self.counter = tk.Label(header, font=font)
        self.counter.grid(row=0, column=0, sticky="w")
        self.emoji = tk.Label(
            header, font=(settings["text_font_family"], settings["emoji_font_size"])
        )
        self.emoji.grid(row=0, column=1, sticky="e")

        # Keep the editor's rows independent of the sidebar's requested height.
        editor = tk.Frame(root)
        editor.grid(row=1, column=0, sticky="nsew", padx=padding)
        editor.columnconfigure(0, weight=1)
        editor.rowconfigure(1, weight=1)
        tk.Label(editor, text=settings["reply_label"], font=font).grid(
            row=0, column=0, sticky="w")
        response = tk.Frame(editor, background="#202020", borderwidth=0)
        response.grid(row=1, column=0, sticky="nsew")
        response.columnconfigure(0, weight=1)
        response.rowconfigure(0, weight=1)
        self.reply_box = tk.Text(
            response, wrap="word", font=font, width=1,
            height=settings["reply_box_height"], state="disabled", **text_options)
        self.reply_box.grid(row=0, column=0, sticky="nsew", padx=(2, 0), pady=2)
        self.reply_scrollbar = ttk.Scrollbar(
            response, orient="vertical", command=self.reply_box.yview)
        self.reply_scrollbar.grid(row=0, column=1, sticky="ns", padx=(0, 2), pady=2)
        self.reply_box.configure(yscrollcommand=self.reply_scrollbar.set)
        current_header = tk.Frame(editor)
        current_header.grid(row=2, column=0, sticky="ew", pady=(padding, 0))
        current_header.columnconfigure(0, weight=1)
        tk.Label(current_header, text=settings["input_label"], font=font).grid(
            row=0, column=0, sticky="w")
        self.send_button = tk.Button(
            current_header, text=settings["send_button_text"], font=font,
            command=lambda: self.submit(self.input_box.get("1.0", "end-1c")))
        self.send_button.grid(row=0, column=1, sticky="e")
        current_border = tk.Frame(editor, background="#202020", borderwidth=0)
        current_border.grid(row=3, column=0, sticky="ew")
        current_border.columnconfigure(0, weight=1)
        self.input_box = tk.Text(
            current_border, wrap="word", font=font, width=1,
            height=settings["input_box_height"], **text_options)
        self.input_box.grid(row=0, column=0, sticky="ew", padx=2, pady=2)
        previous_header = tk.Frame(editor)
        previous_header.grid(row=4, column=0, sticky="ew", pady=(padding, 0))
        previous_header.columnconfigure(0, weight=1)
        tk.Label(previous_header, text=settings["previous_message_label"], font=font).grid(
            row=0, column=0, sticky="w")
        self.repeat_button = tk.Button(
            previous_header, text=settings["repeat_button_text"], font=font, command=self.repeat)
        self.repeat_button.grid(row=0, column=1, sticky="e")
        previous_border = tk.Frame(editor, background="#202020", borderwidth=0)
        previous_border.grid(row=5, column=0, sticky="ew")
        previous_border.columnconfigure(0, weight=1)
        self.previous_message_box = tk.Text(
            previous_border, wrap="word", font=font, width=1,
            height=settings["previous_message_box_height"], **text_options)
        self.previous_message_box.grid(row=0, column=0, sticky="ew", padx=2, pady=2)

        controls = tk.Frame(root)
        controls.grid(row=1, column=1, sticky="nsew", padx=padding, pady=padding)
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

        # Use a drawable theme: macOS native radio indicators ignore many colors.
        style = ttk.Style(root)
        style.theme_use("clam")
        style.configure(
            "Format.TRadiobutton", font=font, background="#ffffff",
            foreground="#000000", indicatorbackground="#ffffff",
            indicatorforeground="#000000", bordercolor="#000000",
            lightcolor="#000000", darkcolor="#000000", focuscolor="#000000",
            padding=(4, 3),
        )
        style.map(
            "Format.TRadiobutton",
            background=[("active", "#ffffff"), ("disabled", "#ffffff")],
            foreground=[("disabled", "#666666")],
            indicatorbackground=[("disabled", "#ffffff"), ("pressed", "#ffffff")],
            indicatorforeground=[("disabled", "#666666")],
        )
        formats = tk.Frame(controls, background="#ffffff")
        formats.grid(row=len(self.parameter_sliders), column=0, sticky="ew", pady=padding)
        tk.Label(formats, text=settings["format_label"], font=font,
                 background="#ffffff", foreground="#000000").grid(row=0, column=0, sticky="w")
        self.format_var = tk.StringVar(
            master=root, value=settings["requested_formats"][settings["default_format_index"]])
        self.format_buttons = []
        for row, value in enumerate(settings["requested_formats"], start=1):
            button = ttk.Radiobutton(formats, text=value, value=value,
                                     variable=self.format_var, style="Format.TRadiobutton",
                                     takefocus=True)
            button.grid(row=row, column=0, sticky="w")
            self.format_buttons.append(button)

        self.status = tk.Label(root, font=font, anchor="w", justify="left",
                               wraplength=settings["window_width"] - 2 * padding)
        self.status.grid(row=2, column=0, columnspan=2, sticky="ew", padx=padding, pady=padding)
        self.statistics_box = tk.Label(
            root, font=(settings["text_font_family"], settings["statistics_font_size"]),
            anchor="w", justify="left", wraplength=settings["window_width"] - 2 * padding)
        self.statistics_box.grid(row=3, column=0, columnspan=2, sticky="ew", padx=padding, pady=padding)
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
        self.previous_message_box.configure(
            state="normal" if not self._busy and self.conversation.can_repeat else "disabled")
        for slider in self.parameter_sliders.values():
            slider.configure(state="disabled" if self._busy else "normal")
        for button in self.format_buttons:
            button.configure(state="disabled" if self._busy else "normal")

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
        self._fit_content()
        self.input_box.focus_set()
        self.root.mainloop()

    def _fit_content(self):
        """Reserve space for all fields, including after status text changes."""
        self.root.update_idletasks()
        self.root.minsize(self.root.winfo_reqwidth(), self.root.winfo_reqheight())

    def submit(self, user_message: str):
        """Display reply/emoji/count, or report an error without decrementing.

        After displaying the final reply, disable input and keep the window open
        until the user closes it using the normal window controls.
        """
        if self._busy or self._completed:
            return
        self._request(user_message=user_message)

    def repeat(self):
        """Regenerate the editable previous message using current settings."""
        if self._busy or not self.conversation.can_repeat:
            return
        self._request(user_message=self.previous_message_box.get("1.0", "end-1c"), repeat=True)

    def _move_to_previous(self, user_message):
        """Retain a submitted message separately from the next unsubmitted draft."""
        self.previous_message_box.configure(state="normal")
        self.previous_message_box.delete("1.0", "end")
        self.previous_message_box.insert("1.0", user_message)
        self.input_box.configure(state="normal")
        self.input_box.delete("1.0", "end")

    def _request(self, user_message=None, repeat=False):
        self._busy = True
        self._update_controls()
        self.status.configure(text="")
        self.root.update_idletasks()
        try:
            parameters = self._parameters()
            result = (self.conversation.repeat(
                          parameters, requested_format=self.format_var.get(),
                          user_message=user_message) if repeat
                      else self.conversation.respond(
                          user_message, parameters, requested_format=self.format_var.get()))
        except TokenLimitResponse as error:
            if not repeat:
                self._move_to_previous(user_message)
            self.show_error(error)
        except Exception as error:
            self.show_error(error)
        else:
            self.display(result.reply, result.emoji, self.conversation.remaining)
            if not repeat:
                self._move_to_previous(user_message)
            self._completed = self.conversation.finished
        finally:
            self._busy = False
            self._update_controls()
            self.display_statistics()
            self._fit_content()

    def display(self, reply: str, emoji: str, remaining: int):
        """Replace the visible response, emoji, and remaining count."""
        self.reply_box.configure(state="normal")
        self.reply_box.delete("1.0", "end")
        self.reply_box.insert("1.0", reply)
        self.reply_box.yview_moveto(0)
        self.reply_box.configure(state="disabled")
        self.emoji.configure(text=emoji)
        self.counter.configure(text=self.settings["remaining_text"].format(remaining=remaining))
        self.root.update_idletasks()

    def show_error(self, error: Exception):
        """Show a useful error without exposing credentials or hidden prompts."""
        # Exception messages can contain credentials or hidden prompts. Show only
        # their class, alongside the configured retry guidance.
        if isinstance(error, TokenLimitResponse):
            self.display(error.partial.reply, error.partial.emoji, self.conversation.remaining)
            text = self.settings["token_limit_text"]
        elif isinstance(error, EmptyMessageError):
            text = self.settings["empty_message_error_text"]
        elif isinstance(error, GenerationParameterError):
            text = self.settings["parameter_error_text"].format(parameter=error.parameter)
        elif isinstance(error, ModelResponseError):
            text = self.settings["response_error_text"]
        else:
            text = self.settings["error_text"].format(error_type=type(error).__name__)
        self.status.configure(text=text)
