import json
import os
import re
import tempfile
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

APP_NAME = "AutoSave Notepad"
STATE_FILE = Path.home() / ".autosave_notepad_state.json"
DEFAULT_AUTOSAVE_INTERVAL_SECONDS = 10
DEFAULT_EXPORT_DIR = str(Path.home() / "Documents" / "AutoSaveNotepad")
UNTITLED_PREFIX = "Poznámka"


class NoteTab:
    def __init__(self, app, title, content="", file_path=None, custom_title=None):
        self.app = app
        self.file_path = file_path
        self.custom_title = custom_title
        self.saved = True
        self.temp_path = None
        self.export_path = None

        self.frame = ttk.Frame(app.notebook)
        self.text = tk.Text(self.frame, wrap="word", undo=True)
        self.scrollbar = ttk.Scrollbar(self.frame, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=self.scrollbar.set)

        self.scrollbar.pack(side="right", fill="y")
        self.text.pack(side="left", fill="both", expand=True)

        self.text.insert("1.0", content)
        self.text.edit_modified(False)
        self.text.bind("<<Modified>>", self.on_modified)
        self.text.bind("<Control-s>", self.save_event)

        self.app.notebook.add(self.frame, text=title)
        self.ensure_temp_path()
        self.write_temp_snapshot()

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
            with open(self.temp_path, "w", encoding="utf-8") as f:
                f.write(self.get_content())
        except OSError as e:
            messagebox.showerror("Chyba autosave", f"Nepodařilo se uložit návrh:\n{e}")

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


class AutoSaveNotepadApp:
    def __init__(self, root):
        self.root = root
        self.root.title(APP_NAME)
        self.root.geometry("1000x680")

        self.tabs = []
        self.settings = {
            "autosave_interval_seconds": DEFAULT_AUTOSAVE_INTERVAL_SECONDS,
            "autosave_directory": DEFAULT_EXPORT_DIR,
        }
        self.periodic_autosave_job = None

        self.create_menu()
        self.create_toolbar()

        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True)

        self.status_var = tk.StringVar(value="Připraveno")
        self.status = ttk.Label(self.root, textvariable=self.status_var, anchor="w")
        self.status.pack(fill="x", side="bottom")

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        self.load_state()
        self.restart_periodic_autosave()

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

        self.root.config(menu=menubar)

        self.root.bind("<Control-n>", lambda e: self.new_tab())
        self.root.bind("<Control-o>", lambda e: self.open_file())
        self.root.bind("<Control-s>", lambda e: self.save_current_file())
        self.root.bind("<Control-w>", lambda e: self.close_current_tab())
        self.root.bind("<F2>", lambda e: self.rename_current_tab())

    def create_toolbar(self):
        toolbar = ttk.Frame(self.root, padding=6)
        toolbar.pack(fill="x")

        ttk.Button(toolbar, text="Nová karta", command=self.new_tab).pack(side="left", padx=3)
        ttk.Button(toolbar, text="Otevřít", command=self.open_file).pack(side="left", padx=3)
        ttk.Button(toolbar, text="Uložit", command=self.save_current_file).pack(side="left", padx=3)
        ttk.Button(toolbar, text="Zavřít kartu", command=self.close_current_tab).pack(side="left", padx=3)
        ttk.Button(toolbar, text="Přejmenovat kartu", command=self.rename_current_tab).pack(side="left", padx=3)
        ttk.Button(toolbar, text="Nastavení", command=self.open_settings).pack(side="left", padx=3)

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
            if arg is None:
                getattr(tab.text, method_name)()
            else:
                getattr(tab.text, method_name)(arg)
        except tk.TclError:
            pass

    def sanitize_filename(self, value):
        value = (value or "").strip()
        value = re.sub(r'[\\/:*?"<>|]+', "_", value)
        value = re.sub(r"\s+", " ", value)
        return value[:120].strip(" .") or UNTITLED_PREFIX

    def get_used_titles(self, exclude_tab=None):
        used = set()
        for tab in self.tabs:
            if tab is exclude_tab:
                continue
            used.add(self.sanitize_filename(tab.get_title()).lower())
        return used

    def prompt_unique_tab_name(self, initial_value="", title="Název karty", prompt="Zadej název karty:"):
        while True:
            name = simpledialog.askstring(title, prompt, initialvalue=initial_value, parent=self.root)
            if name is None:
                return None

            sanitized = self.sanitize_filename(name)
            if sanitized.lower() in self.get_used_titles():
                messagebox.showerror(
                    "Duplicitní název",
                    "Karta s tímto názvem už existuje. Zvol jiný název.",
                    parent=self.root,
                )
                initial_value = sanitized
                continue
            return sanitized

    def prompt_unique_rename(self, tab):
        while True:
            name = simpledialog.askstring(
                "Přejmenovat kartu",
                "Nový název karty:",
                initialvalue=tab.get_title(),
                parent=self.root,
            )
            if name is None:
                return None

            sanitized = self.sanitize_filename(name)
            if sanitized.lower() in self.get_used_titles(exclude_tab=tab):
                messagebox.showerror(
                    "Duplicitní název",
                    "Karta s tímto názvem už existuje. Zvol jiný název.",
                    parent=self.root,
                )
                continue
            return sanitized

    def ensure_autosave_directory(self):
        directory = Path(self.settings.get("autosave_directory") or DEFAULT_EXPORT_DIR)
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def export_tab_to_autosave_folder(self, tab):
        try:
            directory = self.ensure_autosave_directory()
            filename = self.sanitize_filename(tab.get_title()) + ".txt"
            path = directory / filename

            if tab.export_path and Path(tab.export_path) != path and Path(tab.export_path).exists():
                try:
                    Path(tab.export_path).unlink()
                except OSError:
                    pass

            with open(path, "w", encoding="utf-8") as f:
                f.write(tab.get_content())

            tab.export_path = str(path)
        except OSError as e:
            self.set_status(f"Automatické uložení selhalo: {e}")

    def delete_tab_export_file(self, tab):
        try:
            if tab.export_path:
                path = Path(tab.export_path)
            else:
                directory = self.ensure_autosave_directory()
                filename = self.sanitize_filename(tab.get_title()) + ".txt"
                path = directory / filename

            if path.exists():
                path.unlink()

            tab.export_path = None
        except OSError as e:
            self.set_status(f"Smazání autosave souboru selhalo: {e}")

    def run_periodic_autosave(self):
        for tab in self.tabs:
            tab.autosave()

        interval_ms = max(1000, int(self.settings.get("autosave_interval_seconds", DEFAULT_AUTOSAVE_INTERVAL_SECONDS) * 1000))
        self.periodic_autosave_job = self.root.after(interval_ms, self.run_periodic_autosave)

    def restart_periodic_autosave(self):
        if self.periodic_autosave_job is not None:
            self.root.after_cancel(self.periodic_autosave_job)

        interval_ms = max(1000, int(self.settings.get("autosave_interval_seconds", DEFAULT_AUTOSAVE_INTERVAL_SECONDS) * 1000))
        self.periodic_autosave_job = self.root.after(interval_ms, self.run_periodic_autosave)

    def new_tab(self, content="", title=None, file_path=None, temp_path=None, custom_title=None, prompt_for_name=True):
        if custom_title is None and prompt_for_name:
            custom_title = self.prompt_unique_tab_name(
                title="Nová karta",
                prompt="Zadej název nové karty:",
            )
            if custom_title is None:
                return None

        title = title or custom_title or f"{UNTITLED_PREFIX} {len(self.tabs) + 1}"

        tab = NoteTab(self, title=title, content=content, file_path=file_path, custom_title=custom_title)

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
        title = tab.get_title()
        if not tab.saved:
            title = f"* {title}"
        self.notebook.tab(tab.frame, text=title)

    def rename_current_tab(self, event=None):
        tab = self.current_tab()
        if not tab:
            return

        old_export_path = tab.export_path
        new_name = self.prompt_unique_rename(tab)
        if new_name is None:
            return

        tab.custom_title = new_name
        tab.saved = False
        self.update_tab_title(tab)
        tab.autosave()

        if old_export_path and old_export_path != tab.export_path:
            try:
                old_path = Path(old_export_path)
                if old_path.exists():
                    old_path.unlink()
            except OSError:
                pass

        self.set_status(f"Karta přejmenována na: {new_name}")

    def open_settings(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("Nastavení")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.resizable(False, False)

        frame = ttk.Frame(dialog, padding=12)
        frame.pack(fill="both", expand=True)

        ttk.Label(frame, text="Interval automatického ukládání (sekundy):").grid(row=0, column=0, sticky="w", pady=(0, 6))
        interval_var = tk.StringVar(value=str(self.settings.get("autosave_interval_seconds", DEFAULT_AUTOSAVE_INTERVAL_SECONDS)))
        ttk.Entry(frame, textvariable=interval_var, width=12).grid(row=0, column=1, sticky="ew", pady=(0, 6))

        ttk.Label(frame, text="Složka pro periodické ukládání karet:").grid(row=1, column=0, sticky="w", pady=(0, 6))
        directory_var = tk.StringVar(value=self.settings.get("autosave_directory", DEFAULT_EXPORT_DIR))
        ttk.Entry(frame, textvariable=directory_var, width=45).grid(row=1, column=1, sticky="ew", pady=(0, 6))

        def browse_directory():
            path = filedialog.askdirectory(
                title="Vyber složku pro automatické ukládání",
                initialdir=directory_var.get() or str(Path.home()),
            )
            if path:
                directory_var.set(path)

        ttk.Button(frame, text="Procházet...", command=browse_directory).grid(row=1, column=2, padx=(6, 0), pady=(0, 6))

        def save_settings():
            try:
                interval = int(interval_var.get().strip())
            except ValueError:
                messagebox.showerror("Neplatná hodnota", "Interval musí být celé číslo.", parent=dialog)
                return

            if interval < 1:
                messagebox.showerror("Neplatná hodnota", "Interval musí být alespoň 1 sekunda.", parent=dialog)
                return

            directory = directory_var.get().strip()
            if not directory:
                messagebox.showerror("Neplatná hodnota", "Musíš zadat cílovou složku.", parent=dialog)
                return

            try:
                Path(directory).mkdir(parents=True, exist_ok=True)
            except OSError as e:
                messagebox.showerror("Chyba složky", f"Složku nešlo vytvořit:\n{e}", parent=dialog)
                return

            self.settings["autosave_interval_seconds"] = interval
            self.settings["autosave_directory"] = directory
            self.restart_periodic_autosave()

            for tab in self.tabs:
                self.export_tab_to_autosave_folder(tab)

            self.save_state()
            self.set_status("Nastavení bylo uloženo")
            dialog.destroy()

        button_row = ttk.Frame(frame)
        button_row.grid(row=2, column=0, columnspan=3, sticky="e", pady=(10, 0))
        ttk.Button(button_row, text="Uložit", command=save_settings).pack(side="left", padx=4)
        ttk.Button(button_row, text="Zrušit", command=dialog.destroy).pack(side="left", padx=4)

        frame.columnconfigure(1, weight=1)

    def open_file(self):
        path = filedialog.askopenfilename(
            title="Otevřít textový soubor",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
        )
        if not path:
            return

        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
        except UnicodeDecodeError:
            try:
                with open(path, "r", encoding="cp1250") as f:
                    content = f.read()
            except OSError as e:
                messagebox.showerror("Chyba", f"Soubor nešlo otevřít:\n{e}")
                return
        except OSError as e:
            messagebox.showerror("Chyba", f"Soubor nešlo otevřít:\n{e}")
            return

        proposed_name = self.sanitize_filename(Path(path).stem)
        custom_title = proposed_name

        if custom_title.lower() in self.get_used_titles():
            custom_title = self.prompt_unique_tab_name(
                initial_value=proposed_name,
                title="Duplicitní název",
                prompt="Soubor by měl duplicitní název karty. Zadej jiný název:",
            )
            if custom_title is None:
                return

        tab = self.new_tab(
            content=content,
            title=custom_title,
            file_path=path,
            custom_title=custom_title,
            prompt_for_name=False,
        )
        if tab is None:
            return

        tab.mark_saved(path)
        self.set_status(f"Otevřen soubor: {path}")

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

        suggested_name = self.sanitize_filename(tab.get_title()) + ".txt"
        path = filedialog.asksaveasfilename(
            title="Uložit jako",
            initialfile=suggested_name,
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
        )
        if not path:
            return

        self.write_to_path(tab, path)

    def write_to_path(self, tab, path):
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(tab.get_content())
            tab.mark_saved(path)
            self.set_status(f"Uloženo: {path}")
        except OSError as e:
            messagebox.showerror("Chyba ukládání", f"Soubor nešlo uložit:\n{e}")

    def close_current_tab(self, event=None):
        tab = self.current_tab()
        if not tab:
            return

        dialog = tk.Toplevel(self.root)
        dialog.title("Zavření karty")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.resizable(False, False)

        result = {"value": None}

        frame = ttk.Frame(dialog, padding=14)
        frame.pack(fill="both", expand=True)

        ttk.Label(
            frame,
            text="Vyber, co chceš s touto kartou provést:",
            justify="left",
        ).pack(anchor="w", pady=(0, 10))

        button_row = ttk.Frame(frame)
        button_row.pack(anchor="e")

        def choose(value):
            result["value"] = value
            dialog.destroy()

        ttk.Button(button_row, text="Uložit a zavřít", command=lambda: choose("save")).pack(side="left", padx=4)
        ttk.Button(button_row, text="Smazat a zavřít", command=lambda: choose("delete")).pack(side="left", padx=4)
        ttk.Button(button_row, text="Zrušit", command=lambda: choose("cancel")).pack(side="left", padx=4)

        dialog.wait_window()

        if result["value"] in (None, "cancel"):
            return

        if result["value"] == "save":
            before_path = tab.file_path
            self.save_current_file()
            if not before_path and not tab.file_path:
                return

        elif result["value"] == "delete":
            if not tab.delete_linked_file():
                return
            tab.delete_export_file()
            tab.delete_temp_snapshot()

        self.notebook.forget(tab.frame)
        if tab in self.tabs:
            self.tabs.remove(tab)

        self.save_state()
        self.set_status("Karta zavřena")

    def set_status(self, text):
        self.status_var.set(text)

    def save_state(self):
        data = {"tabs": [], "settings": self.settings}

        for tab in self.tabs:
            try:
                tab.write_temp_snapshot()
                data["tabs"].append(
                    {
                        "title": tab.get_title(),
                        "file_path": tab.file_path,
                        "custom_title": tab.custom_title,
                        "temp_path": tab.temp_path,
                        "saved": tab.saved,
                        "export_path": tab.export_path,
                    }
                )
            except Exception:
                pass

        try:
            with open(STATE_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except OSError:
            pass

    def load_state(self):
        if not STATE_FILE.exists():
            return

        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            return

        settings = data.get("settings") or {}
        try:
            self.settings["autosave_interval_seconds"] = int(
                settings.get("autosave_interval_seconds", DEFAULT_AUTOSAVE_INTERVAL_SECONDS)
            )
        except (TypeError, ValueError):
            self.settings["autosave_interval_seconds"] = DEFAULT_AUTOSAVE_INTERVAL_SECONDS

        self.settings["autosave_directory"] = settings.get("autosave_directory", DEFAULT_EXPORT_DIR)

        for item in data.get("tabs", []):
            content = ""
            temp_path = item.get("temp_path")
            file_path = item.get("file_path")

            if temp_path and os.path.exists(temp_path):
                try:
                    with open(temp_path, "r", encoding="utf-8") as f:
                        content = f.read()
                except OSError:
                    content = ""
            elif file_path and os.path.exists(file_path):
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        content = f.read()
                except OSError:
                    content = ""

            tab = self.new_tab(
                content=content,
                title=item.get("title") or UNTITLED_PREFIX,
                file_path=file_path,
                temp_path=temp_path,
                custom_title=item.get("custom_title"),
                prompt_for_name=False,
            )
            if tab is not None:
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

    style = ttk.Style()
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    AutoSaveNotepadApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()