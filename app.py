import json
import os
import re
import sys
import tempfile
import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from updater import GitHubUpdater, UpdateError

APP_NAME = "AutoSave Notepad"
APP_VERSION = "2.0.2"
GITHUB_OWNER = "BignerCZE"
GITHUB_REPO = "SimpleNotePad"

STATE_FILE = Path.home() / ".autosave_notepad_state.json"
DEFAULT_AUTOSAVE_INTERVAL_SECONDS = 10
DEFAULT_EXPORT_DIR = str(Path.home() / "Documents" / "AutoSaveNotepad")
UNTITLED_PREFIX = "Poznámka"
DEFAULT_FONT_SIZE = 11
FONT_SIZES = (8, 9, 10, 11, 12, 14, 16, 18, 20, 24, 28, 32, 36, 48)

UI_BG = "#f3f3f3"
TOOLBAR_BG = "#fafafa"
EDITOR_BG = "#ffffff"
BORDER = "#d6d6d6"
TEXT_COLOR = "#202020"
BUTTON_BG = "#fafafa"
BUTTON_HOVER = "#eeeeee"
FORMAT_ACTIVE_BG = "#dbeafe"
FORMAT_ACTIVE_HOVER = "#cfe3fc"
FORMAT_ACTIVE_BORDER = "#7aa7d9"


class NoteTab:
    def __init__(self, app, title, content="", file_path=None, custom_title=None, formatting=None):
        self.app = app
        self.file_path = file_path
        self.custom_title = custom_title
        self.saved = True
        self.temp_path = None
        self.export_path = None
        self.frame = ttk.Frame(app.notebook, style="Editor.TFrame")
        self.text = tk.Text(
            self.frame,
            wrap="word",
            undo=True,
            font=app.base_font,
            padx=18,
            pady=16,
            background=EDITOR_BG,
            foreground=TEXT_COLOR,
            insertbackground=TEXT_COLOR,
            selectbackground="#cce4ff",
            selectforeground=TEXT_COLOR,
            relief="flat",
            borderwidth=0,
            highlightthickness=0,
        )
        self.scrollbar = ttk.Scrollbar(self.frame, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=self.scrollbar.set)
        self.scrollbar.pack(side="right", fill="y")
        self.text.pack(side="left", fill="both", expand=True)
        self.text.insert("1.0", content)

        self._format_tags = {}
        self.typing_style = {
            "bold": False,
            "italic": False,
            "underline": False,
            "size": DEFAULT_FONT_SIZE,
        }
        self._pending_insert_start = None

        self.text.edit_modified(False)
        self.text.bind("<<Modified>>", self.on_modified)
        self.text.bind("<Control-s>", self.save_event)
        self.text.bind("<Control-b>", lambda e: self._shortcut("bold"))
        self.text.bind("<Control-i>", lambda e: self._shortcut("italic"))
        self.text.bind("<Control-u>", lambda e: self._shortcut("underline"))
        self.text.bind("<KeyPress>", self.on_keypress, add="+")
        self.text.bind("<<Paste>>", self.on_paste, add="+")
        self.text.bind("<ButtonRelease-1>", self.on_caret_moved, add="+")
        for sequence in (
            "<KeyRelease-Left>", "<KeyRelease-Right>",
            "<KeyRelease-Up>", "<KeyRelease-Down>",
            "<KeyRelease-Home>", "<KeyRelease-End>",
            "<KeyRelease-Prior>", "<KeyRelease-Next>",
        ):
            self.text.bind(sequence, self.on_caret_moved, add="+")

        self.app.notebook.add(self.frame, text=title)
        self.restore_formatting(formatting or [])
        self.ensure_temp_path()
        self.write_temp_snapshot()

    def _shortcut(self, kind):
        self.app.toggle_format(kind)
        return "break"

    def set_typing_style(self, style):
        self.typing_style = {
            "bold": bool(style.get("bold")),
            "italic": bool(style.get("italic")),
            "underline": bool(style.get("underline")),
            "size": max(6, min(96, int(style.get("size") or DEFAULT_FONT_SIZE))),
        }

    def on_keypress(self, event):
        non_inserting = {
            "Shift_L", "Shift_R", "Control_L", "Control_R", "Alt_L", "Alt_R",
            "Caps_Lock", "Escape", "Left", "Right", "Up", "Down", "Home", "End",
            "Prior", "Next", "BackSpace", "Delete",
        }
        if event.keysym in non_inserting or (event.state & 0x4):
            return None
        try:
            self._pending_insert_start = (
                self.text.index("sel.first")
                if self.text.tag_ranges("sel")
                else self.text.index("insert")
            )
        except tk.TclError:
            self._pending_insert_start = self.text.index("insert")
        self.text.after_idle(self.apply_typing_style_to_recent_insert)
        return None

    def on_paste(self, event=None):
        try:
            self._pending_insert_start = (
                self.text.index("sel.first")
                if self.text.tag_ranges("sel")
                else self.text.index("insert")
            )
        except tk.TclError:
            self._pending_insert_start = self.text.index("insert")
        self.text.after_idle(self.apply_typing_style_to_recent_insert)

    def apply_typing_style_to_recent_insert(self):
        if self._pending_insert_start is None:
            return
        start = self._pending_insert_start
        self._pending_insert_start = None
        try:
            end = self.text.index("insert")
            if self.text.compare(end, ">", start):
                self.apply_style(start, end, self.typing_style, update_typing=False)
                self.app.sync_format_controls(use_typing_style=True)
        except tk.TclError:
            pass

    def on_caret_moved(self, event=None):
        self.app.sync_format_controls(update_typing_style=True)

    def ensure_temp_path(self):
        if self.temp_path:
            return
        temp_dir = Path(tempfile.gettempdir()) / "autosave_notepad"
        temp_dir.mkdir(parents=True, exist_ok=True)
        fd, path = tempfile.mkstemp(prefix="note_", suffix=".txt", dir=temp_dir)
        os.close(fd)
        self.temp_path = path

    def get_content(self):
        return self.text.get("1.0", "end-1c")

    def get_title(self):
        if self.custom_title:
            return self.custom_title
        if self.file_path:
            return Path(self.file_path).stem
        try:
            idx = self.app.notebook.index(self.frame)
        except tk.TclError:
            idx = len(self.app.tabs)
        return f"{UNTITLED_PREFIX} {idx + 1}"

    def on_modified(self, event=None):
        if not self.text.edit_modified():
            return
        self.saved = False
        self.app.update_tab_title(self)
        self.write_temp_snapshot()
        self.app.save_state()
        self.text.edit_modified(False)

    def autosave(self):
        self.write_temp_snapshot()
        self.app.export_tab_to_autosave_folder(self)
        self.app.save_state()

    def write_temp_snapshot(self):
        try:
            self.ensure_temp_path()
            Path(self.temp_path).write_text(self.get_content(), encoding="utf-8")
        except OSError as e:
            self.app.set_status(f"Autosave návrhu selhal: {e}")

    def mark_saved(self, file_path=None):
        if file_path:
            self.file_path = file_path
        self.saved = True
        self.write_temp_snapshot()
        self.app.update_tab_title(self)
        self.app.save_state()

    def save_event(self, event=None):
        self.app.save_current_file()
        return "break"

    def delete_temp_snapshot(self):
        if self.temp_path and os.path.exists(self.temp_path):
            try:
                os.remove(self.temp_path)
            except OSError:
                pass

    def delete_linked_file(self):
        if self.file_path and os.path.exists(self.file_path):
            try:
                os.remove(self.file_path)
            except OSError as e:
                messagebox.showerror("Chyba mazání", f"Soubor nešlo smazat:\n{e}")
                return False
        return True

    def delete_export_file(self):
        self.app.delete_tab_export_file(self)

    @staticmethod
    def tag_name(style):
        return "fmt_" + "_".join([
            "b1" if style["bold"] else "b0",
            "i1" if style["italic"] else "i0",
            "u1" if style["underline"] else "u0",
            f"s{int(style['size'])}",
        ])

    def ensure_format_tag(self, style):
        style = {
            "bold": bool(style.get("bold")),
            "italic": bool(style.get("italic")),
            "underline": bool(style.get("underline")),
            "size": int(style.get("size") or DEFAULT_FONT_SIZE),
        }
        name = self.tag_name(style)
        if name in self._format_tags:
            return name
        font = tkfont.Font(
            family=self.app.base_font.actual("family"),
            size=style["size"],
            weight="bold" if style["bold"] else "normal",
            slant="italic" if style["italic"] else "roman",
            underline=1 if style["underline"] else 0,
        )
        self._format_tags[name] = (style, font)
        self.text.tag_configure(name, font=font)
        return name

    def style_at(self, index):
        style = {"bold": False, "italic": False, "underline": False, "size": DEFAULT_FONT_SIZE}
        for tag in self.text.tag_names(index):
            if tag in self._format_tags:
                stored_style, _ = self._format_tags[tag]
                style.update(stored_style)
        return style

    def apply_style(self, start, end, style, update_typing=True):
        style = {
            "bold": bool(style.get("bold")),
            "italic": bool(style.get("italic")),
            "underline": bool(style.get("underline")),
            "size": max(6, min(96, int(style.get("size") or DEFAULT_FONT_SIZE))),
        }
        for tag in list(self._format_tags):
            self.text.tag_remove(tag, start, end)
        self.text.tag_add(self.ensure_format_tag(style), start, end)
        if update_typing:
            self.set_typing_style(style)
        self.saved = False
        self.app.update_tab_title(self)
        self.app.save_state()

    def selected_range(self):
        try:
            return self.text.index("sel.first"), self.text.index("sel.last")
        except tk.TclError:
            return None

    def serialize_formatting(self):
        result = []
        for tag, (style, _) in self._format_tags.items():
            ranges = self.text.tag_ranges(tag)
            for i in range(0, len(ranges), 2):
                result.append({"start": str(ranges[i]), "end": str(ranges[i + 1]), "style": dict(style)})
        return result

    def restore_formatting(self, items):
        for item in items:
            try:
                tag = self.ensure_format_tag(item.get("style") or {})
                self.text.tag_add(tag, item["start"], item["end"])
            except (KeyError, tk.TclError):
                pass


class AutoSaveNotepadApp:
    def __init__(self, root):
        self.root = root
        self.root.title(f"{APP_NAME} {APP_VERSION}")
        self.root.geometry("1050x700")
        self.root.minsize(760, 480)
        self.root.configure(background=UI_BG)
        self.configure_ui_styles()
        self.tabs = []
        self.settings = {
            "autosave_interval_seconds": DEFAULT_AUTOSAVE_INTERVAL_SECONDS,
            "autosave_directory": DEFAULT_EXPORT_DIR,
            "check_updates_on_start": True,
        }
        self.periodic_autosave_job = None
        self.base_font = tkfont.nametofont("TkTextFont").copy()
        self.base_font.configure(family="Segoe UI", size=DEFAULT_FONT_SIZE)

        self.bold_var = tk.BooleanVar(value=False)
        self.italic_var = tk.BooleanVar(value=False)
        self.underline_var = tk.BooleanVar(value=False)
        self.font_size_var = tk.StringVar(value=str(DEFAULT_FONT_SIZE))

        self.updater = GitHubUpdater(
            owner=GITHUB_OWNER, repo=GITHUB_REPO,
            current_version=APP_VERSION, app_name=APP_NAME
        )

        self.create_menu()
        self.create_toolbar()
        notebook_wrap = ttk.Frame(self.root)
        notebook_wrap.pack(fill="both", expand=True)
        self.notebook = ttk.Notebook(notebook_wrap)
        self.notebook.pack(fill="both", expand=True, padx=6, pady=(5, 0))
        self.notebook.bind("<<NotebookTabChanged>>", lambda e: self.sync_format_controls())

        self.status_var = tk.StringVar(value="Připraveno")
        ttk.Separator(self.root, orient="horizontal").pack(fill="x", side="bottom")
        ttk.Label(
            self.root,
            textvariable=self.status_var,
            anchor="w",
            style="Status.TLabel",
        ).pack(fill="x", side="bottom")
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        self.load_state()
        self.restart_periodic_autosave()
        if self.settings.get("check_updates_on_start", True):
            self.root.after(1200, self.check_for_updates_silent)

    def configure_ui_styles(self):
        style = ttk.Style(self.root)
        try:
            style.theme_use("vista")
        except tk.TclError:
            try:
                style.theme_use("clam")
            except tk.TclError:
                pass

        default_font = ("Segoe UI", 9)
        self.root.option_add("*Font", default_font)
        self.root.option_add("*Menu.Font", default_font)

        style.configure(".", font=default_font)
        style.configure("TFrame", background=UI_BG)
        style.configure("Toolbar.TFrame", background=TOOLBAR_BG)
        style.configure("Editor.TFrame", background=EDITOR_BG)

        style.configure(
            "Toolbar.TButton",
            font=("Segoe UI", 9),
            padding=(10, 6),
        )
        style.map(
            "Toolbar.TButton",
            background=[("active", BUTTON_HOVER)],
        )

        style.configure(
            "TNotebook",
            background=UI_BG,
            borderwidth=0,
            tabmargins=(6, 4, 6, 0),
        )
        style.configure(
            "TNotebook.Tab",
            font=("Segoe UI", 9),
            padding=(14, 6),
        )
        style.map(
            "TNotebook.Tab",
            background=[("selected", EDITOR_BG)],
        )

        style.configure(
            "Status.TLabel",
            background=UI_BG,
            foreground="#5a5a5a",
            padding=(8, 4),
            font=("Segoe UI", 9),
        )
        style.configure(
            "Toolbar.TLabel",
            background=TOOLBAR_BG,
            foreground=TEXT_COLOR,
            font=("Segoe UI", 9),
        )
        style.configure(
            "Toolbar.TCombobox",
            padding=(4, 4),
        )

    def create_menu(self):
        menubar = tk.Menu(self.root)

        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Nová karta", command=self.new_tab, accelerator="Ctrl+N")
        file_menu.add_command(label="Otevřít...", command=self.open_file, accelerator="Ctrl+O")
        file_menu.add_separator()
        file_menu.add_command(label="Uložit", command=self.save_current_file, accelerator="Ctrl+S")
        file_menu.add_command(label="Uložit jako...", command=self.save_current_file_as)
        file_menu.add_separator()
        file_menu.add_command(label="Zavřít kartu", command=self.close_current_tab, accelerator="Ctrl+W")
        file_menu.add_separator()
        file_menu.add_command(label="Nastavení", command=self.open_settings)
        file_menu.add_command(label="Konec", command=self.on_close)
        menubar.add_cascade(label="Soubor", menu=file_menu)

        edit_menu = tk.Menu(menubar, tearoff=0)
        edit_menu.add_command(label="Zpět", command=lambda: self.text_event("edit_undo"), accelerator="Ctrl+Z")
        edit_menu.add_command(label="Znovu", command=lambda: self.text_event("edit_redo"), accelerator="Ctrl+Y")
        edit_menu.add_separator()
        edit_menu.add_command(label="Vyjmout", command=lambda: self.text_event("event_generate", "<<Cut>>"), accelerator="Ctrl+X")
        edit_menu.add_command(label="Kopírovat", command=lambda: self.text_event("event_generate", "<<Copy>>"), accelerator="Ctrl+C")
        edit_menu.add_command(label="Vložit", command=lambda: self.text_event("event_generate", "<<Paste>>"), accelerator="Ctrl+V")
        edit_menu.add_separator()
        edit_menu.add_command(label="Přejmenovat kartu", command=self.rename_current_tab, accelerator="F2")
        menubar.add_cascade(label="Úpravy", menu=edit_menu)

        format_menu = tk.Menu(menubar, tearoff=0)
        format_menu.add_command(label="Tučné", command=lambda: self.toggle_format("bold"), accelerator="Ctrl+B")
        format_menu.add_command(label="Kurzíva", command=lambda: self.toggle_format("italic"), accelerator="Ctrl+I")
        format_menu.add_command(label="Podtržení", command=lambda: self.toggle_format("underline"), accelerator="Ctrl+U")
        format_menu.add_separator()
        for size in FONT_SIZES:
            format_menu.add_command(label=f"{size} pt", command=lambda s=size: self.set_font_size(s))
        menubar.add_cascade(label="Formát", menu=format_menu)

        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="Zkontrolovat aktualizace", command=self.check_for_updates_manual)
        help_menu.add_command(label="Nastavit GitHub přístup", command=self.configure_github_token)
        help_menu.add_separator()
        help_menu.add_command(label="O programu", command=self.show_about)
        menubar.add_cascade(label="Nápověda", menu=help_menu)

        self.root.config(menu=menubar)
        self.root.bind("<Control-n>", lambda e: self.new_tab())
        self.root.bind("<Control-o>", lambda e: self.open_file())
        self.root.bind("<Control-s>", lambda e: self.save_current_file())
        self.root.bind("<Control-w>", lambda e: self.close_current_tab())
        self.root.bind("<F2>", lambda e: self.rename_current_tab())

    def create_toolbar(self):
        toolbar_outer = tk.Frame(
            self.root,
            background=BORDER,
            borderwidth=0,
            highlightthickness=0,
        )
        toolbar_outer.pack(fill="x")

        # Scrollable horizontal toolbar.
        toolbar_canvas = tk.Canvas(
            toolbar_outer,
            background=TOOLBAR_BG,
            highlightthickness=0,
            borderwidth=0,
            height=48,
        )
        toolbar_canvas.pack(side="top", fill="x", expand=True)

        toolbar_scroll = ttk.Scrollbar(
            toolbar_outer,
            orient="horizontal",
            command=toolbar_canvas.xview,
        )
        toolbar_canvas.configure(xscrollcommand=toolbar_scroll.set)

        toolbar = ttk.Frame(toolbar_canvas, style="Toolbar.TFrame", padding=(8, 7))
        toolbar_window = toolbar_canvas.create_window(
            (0, 0),
            window=toolbar,
            anchor="nw",
        )

        def update_scroll_region(event=None):
            toolbar_canvas.configure(scrollregion=toolbar_canvas.bbox("all"))

            required_width = toolbar.winfo_reqwidth()
            available_width = toolbar_canvas.winfo_width()

            if required_width > available_width:
                if not toolbar_scroll.winfo_ismapped():
                    toolbar_scroll.pack(side="bottom", fill="x")
            else:
                if toolbar_scroll.winfo_ismapped():
                    toolbar_scroll.pack_forget()
                toolbar_canvas.xview_moveto(0)

        def resize_inner_window(event):
            required_width = toolbar.winfo_reqwidth()
            canvas_width = event.width
            toolbar_canvas.itemconfigure(
                toolbar_window,
                width=max(required_width, canvas_width),
            )
            toolbar_canvas.after_idle(update_scroll_region)

        def horizontal_mousewheel(event):
            # Shift + mouse wheel scrolls the toolbar horizontally.
            delta = event.delta
            if delta == 0:
                return
            direction = -1 if delta > 0 else 1
            toolbar_canvas.xview_scroll(direction * 3, "units")
            return "break"

        toolbar.bind("<Configure>", update_scroll_region)
        toolbar_canvas.bind("<Configure>", resize_inner_window)
        toolbar_canvas.bind("<Shift-MouseWheel>", horizontal_mousewheel)
        toolbar.bind("<Shift-MouseWheel>", horizontal_mousewheel)

        file_group = ttk.Frame(toolbar, style="Toolbar.TFrame")
        file_group.pack(side="left")

        for label, command in (
            ("Nová karta", self.new_tab),
            ("Otevřít", self.open_file),
            ("Uložit", self.save_current_file),
            ("Zavřít kartu", self.close_current_tab),
            ("Přejmenovat kartu", self.rename_current_tab),
        ):
            button = ttk.Button(
                file_group,
                text=label,
                command=command,
                style="Toolbar.TButton",
            )
            button.pack(side="left", padx=(0, 4))
            button.bind("<Shift-MouseWheel>", horizontal_mousewheel)

        sep1 = ttk.Separator(toolbar, orient="vertical")
        sep1.pack(side="left", fill="y", padx=(8, 10), pady=2)
        sep1.bind("<Shift-MouseWheel>", horizontal_mousewheel)

        format_group = ttk.Frame(toolbar, style="Toolbar.TFrame")
        format_group.pack(side="left")
        format_group.bind("<Shift-MouseWheel>", horizontal_mousewheel)

        self.bold_button = self.create_format_button(
            format_group, "Tučně", lambda: self.toggle_format("bold")
        )
        self.underline_button = self.create_format_button(
            format_group, "Podtržené", lambda: self.toggle_format("underline")
        )
        self.italic_button = self.create_format_button(
            format_group, "Kurzíva", lambda: self.toggle_format("italic")
        )

        for button in (self.bold_button, self.underline_button, self.italic_button):
            button.bind("<Shift-MouseWheel>", horizontal_mousewheel)

        size_label = ttk.Label(
            format_group,
            text="Velikost",
            style="Toolbar.TLabel",
        )
        size_label.pack(side="left", padx=(10, 5))
        size_label.bind("<Shift-MouseWheel>", horizontal_mousewheel)

        combo = ttk.Combobox(
            format_group,
            textvariable=self.font_size_var,
            values=[str(x) for x in FONT_SIZES],
            width=5,
            state="normal",
            style="Toolbar.TCombobox",
            justify="center",
        )
        combo.pack(side="left")
        combo.bind("<<ComboboxSelected>>", lambda e: self.apply_size_from_control())
        combo.bind("<Return>", lambda e: self.apply_size_from_control())
        combo.bind("<Shift-MouseWheel>", horizontal_mousewheel)

        sep2 = ttk.Separator(toolbar, orient="vertical")
        sep2.pack(side="left", fill="y", padx=(10, 10), pady=2)
        sep2.bind("<Shift-MouseWheel>", horizontal_mousewheel)

        app_group = ttk.Frame(toolbar, style="Toolbar.TFrame")
        app_group.pack(side="left")
        app_group.bind("<Shift-MouseWheel>", horizontal_mousewheel)

        settings_button = ttk.Button(
            app_group,
            text="Nastavení",
            command=self.open_settings,
            style="Toolbar.TButton",
        )
        settings_button.pack(side="left", padx=(0, 4))
        settings_button.bind("<Shift-MouseWheel>", horizontal_mousewheel)

        update_button = ttk.Button(
            app_group,
            text="Aktualizace",
            command=self.check_for_updates_manual,
            style="Toolbar.TButton",
        )
        update_button.pack(side="left")
        update_button.bind("<Shift-MouseWheel>", horizontal_mousewheel)

        toolbar_canvas.after_idle(update_scroll_region)

    def create_format_button(self, parent, text, command):
        button = tk.Button(
            parent,
            text=text,
            command=command,
            font=("Segoe UI", 9),
            background=BUTTON_BG,
            foreground=TEXT_COLOR,
            activebackground=BUTTON_HOVER,
            activeforeground=TEXT_COLOR,
            relief="flat",
            overrelief="flat",
            borderwidth=1,
            highlightthickness=1,
            highlightbackground=TOOLBAR_BG,
            highlightcolor=TOOLBAR_BG,
            padx=10,
            pady=5,
            cursor="hand2",
        )
        button.pack(side="left", padx=(0, 4))
        return button

    def current_tab(self):
        current = self.notebook.select()
        if not current:
            return None
        for tab in self.tabs:
            if str(tab.frame) == current:
                return tab
        return None

    def text_event(self, method_name, arg=None):
        tab = self.current_tab()
        if not tab:
            return
        try:
            getattr(tab.text, method_name)() if arg is None else getattr(tab.text, method_name)(arg)
        except tk.TclError:
            pass

    def selection_or_word(self, tab):
        selected = tab.selected_range()
        if selected:
            return selected
        try:
            index = tab.text.index("insert")
            start = tab.text.index(f"{index} wordstart")
            end = tab.text.index(f"{index} wordend")
            return None if tab.text.compare(start, "==", end) else (start, end)
        except tk.TclError:
            return None

    def toggle_format(self, kind, from_control=False):
        tab = self.current_tab()
        if not tab:
            return "break"

        rng = tab.selected_range()
        if rng:
            style = tab.style_at(rng[0])
            if from_control:
                style[kind] = {
                    "bold": self.bold_var,
                    "italic": self.italic_var,
                    "underline": self.underline_var,
                }[kind].get()
            else:
                style[kind] = not bool(style[kind])
            tab.apply_style(*rng, style)
            tab.text.tag_add("sel", *rng)
        else:
            style = dict(tab.typing_style)
            if from_control:
                style[kind] = {
                    "bold": self.bold_var,
                    "italic": self.italic_var,
                    "underline": self.underline_var,
                }[kind].get()
            else:
                style[kind] = not bool(style[kind])
            tab.set_typing_style(style)

        self.sync_format_controls(use_typing_style=True)
        tab.text.focus_set()
        return "break"

    def set_font_size(self, size):
        tab = self.current_tab()
        if not tab:
            return

        size = max(6, min(96, int(size)))
        rng = tab.selected_range()
        if rng:
            style = tab.style_at(rng[0])
            style["size"] = size
            tab.apply_style(*rng, style)
            tab.text.tag_add("sel", *rng)
        else:
            style = dict(tab.typing_style)
            style["size"] = size
            tab.set_typing_style(style)

        self.font_size_var.set(str(size))
        self.sync_format_controls(use_typing_style=True)
        tab.text.focus_set()

    def apply_size_from_control(self):
        try:
            self.set_font_size(int(self.font_size_var.get().strip()))
        except ValueError:
            tab = self.current_tab()
            self.font_size_var.set(str(tab.typing_style["size"] if tab else DEFAULT_FONT_SIZE))

    def sync_format_controls(self, update_typing_style=False, use_typing_style=False):
        tab = self.current_tab()
        if not tab:
            return

        rng = tab.selected_range()
        if use_typing_style:
            style = dict(tab.typing_style)
        elif rng:
            style = tab.style_at(rng[0])
            if update_typing_style:
                tab.set_typing_style(style)
        else:
            try:
                index = tab.text.index("insert")
                if tab.text.compare(index, ">", "1.0"):
                    style = tab.style_at(tab.text.index(f"{index} -1c"))
                else:
                    style = dict(tab.typing_style)
            except tk.TclError:
                style = dict(tab.typing_style)
            if update_typing_style:
                tab.set_typing_style(style)

        self.bold_var.set(bool(style["bold"]))
        self.italic_var.set(bool(style["italic"]))
        self.underline_var.set(bool(style["underline"]))
        self.font_size_var.set(str(style["size"]))
        self.update_format_buttons()

    def update_format_buttons(self):
        button_states = (
            (self.bold_button, self.bold_var.get()),
            (self.underline_button, self.underline_var.get()),
            (self.italic_button, self.italic_var.get()),
        )
        for button, active in button_states:
            if active:
                button.configure(
                    background=FORMAT_ACTIVE_BG,
                    activebackground=FORMAT_ACTIVE_HOVER,
                    highlightbackground=FORMAT_ACTIVE_BORDER,
                    highlightcolor=FORMAT_ACTIVE_BORDER,
                )
            else:
                button.configure(
                    background=BUTTON_BG,
                    activebackground=BUTTON_HOVER,
                    highlightbackground=TOOLBAR_BG,
                    highlightcolor=TOOLBAR_BG,
                )

    def sanitize_filename(self, value):
        value = (value or "").strip()
        value = re.sub(r'[\\/:*?"<>|]+', "_", value)
        value = re.sub(r"\s+", " ", value)
        return value[:120].strip(" .") or UNTITLED_PREFIX

    def get_used_titles(self, exclude_tab=None):
        return {self.sanitize_filename(t.get_title()).lower() for t in self.tabs if t is not exclude_tab}

    def prompt_unique_tab_name(self, initial_value="", title="Název karty", prompt="Zadej název karty:"):
        while True:
            name = simpledialog.askstring(title, prompt, initialvalue=initial_value, parent=self.root)
            if name is None:
                return None
            name = self.sanitize_filename(name)
            if name.lower() in self.get_used_titles():
                messagebox.showerror("Duplicitní název", "Karta s tímto názvem už existuje.", parent=self.root)
                initial_value = name
            else:
                return name

    def prompt_unique_rename(self, tab):
        while True:
            name = simpledialog.askstring("Přejmenovat kartu", "Nový název karty:",
                                          initialvalue=tab.get_title(), parent=self.root)
            if name is None:
                return None
            name = self.sanitize_filename(name)
            if name.lower() in self.get_used_titles(exclude_tab=tab):
                messagebox.showerror("Duplicitní název", "Karta s tímto názvem už existuje.", parent=self.root)
            else:
                return name

    def ensure_autosave_directory(self):
        p = Path(self.settings.get("autosave_directory") or DEFAULT_EXPORT_DIR)
        p.mkdir(parents=True, exist_ok=True)
        return p

    def export_tab_to_autosave_folder(self, tab):
        try:
            path = self.ensure_autosave_directory() / (self.sanitize_filename(tab.get_title()) + ".txt")
            if tab.export_path and Path(tab.export_path) != path and Path(tab.export_path).exists():
                try:
                    Path(tab.export_path).unlink()
                except OSError:
                    pass
            path.write_text(tab.get_content(), encoding="utf-8")
            tab.export_path = str(path)
        except OSError as e:
            self.set_status(f"Automatické uložení selhalo: {e}")

    def delete_tab_export_file(self, tab):
        try:
            path = Path(tab.export_path) if tab.export_path else                 self.ensure_autosave_directory() / (self.sanitize_filename(tab.get_title()) + ".txt")
            if path.exists():
                path.unlink()
            tab.export_path = None
        except OSError as e:
            self.set_status(f"Smazání autosave souboru selhalo: {e}")

    def run_periodic_autosave(self):
        for tab in self.tabs:
            tab.autosave()
        ms = max(1000, int(self.settings.get("autosave_interval_seconds", 10) * 1000))
        self.periodic_autosave_job = self.root.after(ms, self.run_periodic_autosave)

    def restart_periodic_autosave(self):
        if self.periodic_autosave_job is not None:
            self.root.after_cancel(self.periodic_autosave_job)
        ms = max(1000, int(self.settings.get("autosave_interval_seconds", 10) * 1000))
        self.periodic_autosave_job = self.root.after(ms, self.run_periodic_autosave)

    def new_tab(self, content="", title=None, file_path=None, temp_path=None,
                custom_title=None, prompt_for_name=True, formatting=None):
        if custom_title is None and prompt_for_name:
            custom_title = self.prompt_unique_tab_name(title="Nová karta", prompt="Zadej název nové karty:")
            if custom_title is None:
                return None
        title = title or custom_title or f"{UNTITLED_PREFIX} {len(self.tabs) + 1}"
        tab = NoteTab(self, title, content, file_path, custom_title, formatting)
        if temp_path:
            tab.temp_path = temp_path
            tab.write_temp_snapshot()
        self.tabs.append(tab)
        self.notebook.select(tab.frame)
        self.update_tab_title(tab)
        self.export_tab_to_autosave_folder(tab)
        self.save_state()
        self.set_status("Vytvořena nová karta")
        return tab

    def update_tab_title(self, tab):
        self.notebook.tab(tab.frame, text=("* " if not tab.saved else "") + tab.get_title())

    def rename_current_tab(self, event=None):
        tab = self.current_tab()
        if not tab:
            return
        old_export = tab.export_path
        new_name = self.prompt_unique_rename(tab)
        if new_name is None:
            return
        tab.custom_title = new_name
        tab.saved = False
        self.update_tab_title(tab)
        tab.autosave()
        if old_export and old_export != tab.export_path:
            try:
                if Path(old_export).exists():
                    Path(old_export).unlink()
            except OSError:
                pass

    def open_settings(self):
        d = tk.Toplevel(self.root)
        d.title("Nastavení")
        d.transient(self.root)
        d.grab_set()
        frame = ttk.Frame(d, padding=12)
        frame.pack(fill="both", expand=True)

        interval = tk.StringVar(value=str(self.settings["autosave_interval_seconds"]))
        directory = tk.StringVar(value=self.settings["autosave_directory"])
        updates = tk.BooleanVar(value=self.settings.get("check_updates_on_start", True))

        ttk.Label(frame, text="Interval autosave (sekundy):").grid(row=0, column=0, sticky="w", pady=4)
        ttk.Entry(frame, textvariable=interval, width=12).grid(row=0, column=1, sticky="ew", pady=4)
        ttk.Label(frame, text="Složka autosave:").grid(row=1, column=0, sticky="w", pady=4)
        ttk.Entry(frame, textvariable=directory, width=45).grid(row=1, column=1, sticky="ew", pady=4)
        ttk.Button(frame, text="Procházet...", command=lambda: directory.set(
            filedialog.askdirectory(initialdir=directory.get() or str(Path.home())) or directory.get()
        )).grid(row=1, column=2, padx=6)
        ttk.Checkbutton(frame, text="Kontrolovat aktualizace při spuštění",
                        variable=updates).grid(row=2, column=0, columnspan=3, sticky="w", pady=6)
        ttk.Button(frame, text="Nastavit GitHub přístup...",
                   command=self.configure_github_token).grid(row=3, column=0, columnspan=3, sticky="w", pady=4)

        def save():
            try:
                sec = int(interval.get())
                if sec < 1:
                    raise ValueError
            except ValueError:
                messagebox.showerror("Neplatná hodnota", "Interval musí být celé číslo >= 1.", parent=d)
                return
            path = directory.get().strip()
            if not path:
                return
            try:
                Path(path).mkdir(parents=True, exist_ok=True)
            except OSError as e:
                messagebox.showerror("Chyba", str(e), parent=d)
                return
            self.settings.update(
                autosave_interval_seconds=sec,
                autosave_directory=path,
                check_updates_on_start=updates.get()
            )
            self.restart_periodic_autosave()
            self.save_state()
            d.destroy()

        row = ttk.Frame(frame)
        row.grid(row=4, column=0, columnspan=3, sticky="e", pady=(10, 0))
        ttk.Button(row, text="Uložit", command=save).pack(side="left", padx=4)
        ttk.Button(row, text="Zrušit", command=d.destroy).pack(side="left", padx=4)
        frame.columnconfigure(1, weight=1)

    def open_file(self):
        path = filedialog.askopenfilename(
            title="Otevřít textový soubor",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")]
        )
        if not path:
            return
        try:
            try:
                content = Path(path).read_text(encoding="utf-8")
            except UnicodeDecodeError:
                content = Path(path).read_text(encoding="cp1250")
        except OSError as e:
            messagebox.showerror("Chyba", f"Soubor nešlo otevřít:\n{e}")
            return
        name = self.sanitize_filename(Path(path).stem)
        if name.lower() in self.get_used_titles():
            name = self.prompt_unique_tab_name(name, "Duplicitní název", "Zadej jiný název karty:")
            if name is None:
                return
        tab = self.new_tab(content=content, title=name, file_path=path,
                           custom_title=name, prompt_for_name=False)
        if tab:
            tab.mark_saved(path)

    def save_current_file(self, event=None):
        tab = self.current_tab()
        if not tab:
            return
        if tab.file_path:
            self.write_to_path(tab, tab.file_path)
        else:
            self.save_current_file_as()

    def save_current_file_as(self):
        tab = self.current_tab()
        if not tab:
            return
        path = filedialog.asksaveasfilename(
            title="Uložit jako",
            initialfile=self.sanitize_filename(tab.get_title()) + ".txt",
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")]
        )
        if path:
            self.write_to_path(tab, path)

    def write_to_path(self, tab, path):
        try:
            Path(path).write_text(tab.get_content(), encoding="utf-8")
            tab.mark_saved(path)
            self.set_status(f"Uloženo: {path}")
        except OSError as e:
            messagebox.showerror("Chyba ukládání", f"Soubor nešlo uložit:\n{e}")

    def close_current_tab(self, event=None):
        tab = self.current_tab()
        if not tab:
            return
        result = messagebox.askyesnocancel(
            "Zavření karty",
            "Ano = uložit a zavřít\nNe = smazat a zavřít\nZrušit = ponechat otevřené",
            parent=self.root
        )
        if result is None:
            return
        if result:
            before = tab.file_path
            self.save_current_file()
            if not before and not tab.file_path:
                return
        else:
            if not tab.delete_linked_file():
                return
            tab.delete_export_file()
            tab.delete_temp_snapshot()
        self.notebook.forget(tab.frame)
        self.tabs.remove(tab)
        self.save_state()

    def configure_github_token(self):
        token = simpledialog.askstring(
            "GitHub přístup",
            "Vlož fine-grained GitHub token s oprávněním Contents: Read-only\n"
            "pouze pro BignerCZE/SimpleNotePad.\n\n"
            "Token bude uložen ve Windows Credential Manager.",
            parent=self.root, show="•"
        )
        if token is None:
            return
        token = token.strip()
        if not token:
            return
        try:
            self.updater.save_token(token)
            self.updater.test_access()
        except UpdateError as e:
            messagebox.showerror("GitHub přístup", str(e), parent=self.root)
            return
        messagebox.showinfo("GitHub přístup", "Přístup je funkční.", parent=self.root)

    def check_for_updates_silent(self):
        try:
            release = self.updater.check_latest()
        except UpdateError as e:
            self.set_status(f"Kontrola aktualizace: {e}")
            return
        if release:
            self.offer_update(release)

    def check_for_updates_manual(self):
        try:
            release = self.updater.check_latest()
        except UpdateError as e:
            messagebox.showerror("Aktualizace", str(e), parent=self.root)
            return
        if not release:
            messagebox.showinfo("Aktualizace", f"Používáš aktuální verzi {APP_VERSION}.", parent=self.root)
            return
        self.offer_update(release)

    def offer_update(self, release):
        if not messagebox.askyesno(
            "Je dostupná aktualizace",
            f"Je dostupná verze {release['version']}.\n\n"
            f"{(release.get('notes') or 'Bez poznámek k vydání.')[:1000]}\n\n"
            "Stáhnout a nainstalovat?",
            parent=self.root
        ):
            return
        if not getattr(sys, "frozen", False):
            messagebox.showinfo("Aktualizace", "Automatická instalace funguje v EXE verzi.", parent=self.root)
            return
        try:
            self.save_state()
            new_exe = self.updater.download_and_verify(release)
            self.updater.install_after_exit(new_exe)
        except UpdateError as e:
            messagebox.showerror("Aktualizace", str(e), parent=self.root)
            return
        self.root.destroy()

    def show_about(self):
        messagebox.showinfo("O programu", f"{APP_NAME}\nVerze {APP_VERSION}\n\n{GITHUB_OWNER}/{GITHUB_REPO}")

    def set_status(self, text):
        self.status_var.set(text)

    def save_state(self):
        data = {"tabs": [], "settings": self.settings}
        for tab in self.tabs:
            try:
                tab.write_temp_snapshot()
                data["tabs"].append({
                    "title": tab.get_title(),
                    "file_path": tab.file_path,
                    "custom_title": tab.custom_title,
                    "temp_path": tab.temp_path,
                    "saved": tab.saved,
                    "export_path": tab.export_path,
                    "formatting": tab.serialize_formatting(),
                })
            except Exception:
                pass
        try:
            STATE_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass

    def load_state(self):
        if not STATE_FILE.exists():
            return
        try:
            data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        settings = data.get("settings") or {}
        try:
            self.settings["autosave_interval_seconds"] = int(settings.get("autosave_interval_seconds", 10))
        except (TypeError, ValueError):
            self.settings["autosave_interval_seconds"] = 10
        self.settings["autosave_directory"] = settings.get("autosave_directory", DEFAULT_EXPORT_DIR)
        self.settings["check_updates_on_start"] = bool(settings.get("check_updates_on_start", True))

        for item in data.get("tabs", []):
            content = ""
            temp_path = item.get("temp_path")
            file_path = item.get("file_path")
            source = temp_path if temp_path and os.path.exists(temp_path) else file_path
            if source and os.path.exists(source):
                try:
                    content = Path(source).read_text(encoding="utf-8")
                except OSError:
                    pass
            tab = self.new_tab(
                content=content,
                title=item.get("title") or UNTITLED_PREFIX,
                file_path=file_path,
                temp_path=temp_path,
                custom_title=item.get("custom_title"),
                prompt_for_name=False,
                formatting=item.get("formatting") or [],
            )
            if tab:
                tab.saved = item.get("saved", True)
                tab.export_path = item.get("export_path")
                self.update_tab_title(tab)

    def on_close(self):
        self.save_state()
        if self.periodic_autosave_job is not None:
            self.root.after_cancel(self.periodic_autosave_job)
        self.root.destroy()


def main():
    root = tk.Tk()
    AutoSaveNotepadApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
