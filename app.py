import json
import os
import ctypes
import re
import sys
import tempfile
import uuid
from io import BytesIO
import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from PIL import Image, ImageDraw, ImageFont, ImageGrab, ImageTk, ImageWin
from docx import Document
from docx.oxml.ns import qn
from docx.shared import Inches, Pt

from updater import GitHubUpdater, UpdateError

APP_NAME = "AutoSave Notepad"
APP_VERSION = "2.5.3"

WINDOWS_APP_ID = "BignerCZE.SimpleNotePad"

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



def configure_windows_app_identity():
    """Give Windows a stable identity for taskbar grouping."""
    if os.name != "nt":
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            WINDOWS_APP_ID
        )
    except Exception:
        pass


def resource_path(filename):
    """Resolve bundled resources in source and PyInstaller one-file builds."""
    try:
        base = Path(sys._MEIPASS)
    except Exception:
        base = Path(__file__).resolve().parent
    return base / filename


def apply_tk_window_icon(root):
    """
    Set the Tk application icon using iconphoto.

    This is the icon source used by Tk itself for the window/taskbar icon.
    Keep a Python reference to PhotoImage for the lifetime of the window.
    """
    icon_path = resource_path("icon.png")
    if not icon_path.exists():
        return None

    try:
        icon = tk.PhotoImage(file=str(icon_path))
        root.iconphoto(True, icon)
        return icon
    except tk.TclError:
        return None


class NoteTab:
    def __init__(
        self,
        app,
        title,
        content="",
        file_path=None,
        custom_title=None,
        formatting=None,
        images=None,
    ):
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
        self.embedded_images = {}
        self.selected_image_name = None
        self.image_resize_handles = {}
        self._image_resize_drag = None
        self._image_handle_refresh_job = None
        self._loading_document = False
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
        self.text.bind("<ButtonRelease-1>", self.on_editor_click, add="+")
        self.text.bind("<Configure>", self.schedule_image_handle_refresh, add="+")
        self.text.bind("<MouseWheel>", self.schedule_image_handle_refresh, add="+")
        self.text.bind("<Button-4>", self.schedule_image_handle_refresh, add="+")
        self.text.bind("<Button-5>", self.schedule_image_handle_refresh, add="+")
        self.text.bind("<KeyRelease>", self.schedule_image_handle_refresh, add="+")
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
        # Prefer an image if the Windows clipboard contains one; otherwise
        # allow Tk's normal text paste and apply the active typing style.
        if self.paste_image_from_clipboard():
            return "break"

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

    def paste_image_from_clipboard(self):
        try:
            clipboard = ImageGrab.grabclipboard()
        except Exception:
            return False

        image = None

        if isinstance(clipboard, Image.Image):
            image = clipboard.copy()
        elif isinstance(clipboard, list):
            # Windows may expose a copied image file as a list of paths.
            for item in clipboard:
                try:
                    path = Path(item)
                    if path.is_file():
                        with Image.open(path) as opened:
                            image = opened.convert("RGBA").copy()
                        break
                except Exception:
                    continue

        if image is None:
            return False

        self.insert_pil_image(image)
        return True

    def insert_pil_image(self, image, mark_modified=True):
        try:
            start = self.text.index("sel.first")
            end = self.text.index("sel.last")
            self.text.delete(start, end)
            index = start
        except tk.TclError:
            index = self.text.index("insert")

        try:
            rgba = image.convert("RGBA")
            buffer = BytesIO()
            rgba.save(buffer, format="PNG")
            image_bytes = buffer.getvalue()
        except Exception as e:
            messagebox.showerror(
                "Vložení obrázku",
                f"Obrázek se nepodařilo zpracovat:\n{e}",
                parent=self.app.root,
            )
            return

        display_width = self._default_image_display_width(rgba.width)
        photo = self._make_display_photo(rgba, display_width)
        tk_name = f"img_{uuid.uuid4().hex}"

        try:
            self.text.image_create(
                index,
                image=photo,
                name=tk_name,
                padx=4,
                pady=4,
            )
        except tk.TclError as e:
            messagebox.showerror(
                "Vložení obrázku",
                f"Obrázek se nepodařilo vložit:\n{e}",
                parent=self.app.root,
            )
            return

        self.embedded_images[tk_name] = {
            "photo": photo,
            "bytes": image_bytes,
            "pixel_size": rgba.size,
            "display_width_px": display_width,
        }
        self.select_image(tk_name)

        try:
            self.text.mark_set("insert", f"{tk_name} +1c")
        except tk.TclError:
            pass

        if mark_modified:
            self.saved = False
            self.app.update_tab_title(self)
            # Image insertion is infrequent, so write a recovery DOCX immediately.
            self.write_temp_snapshot()
            self.app.save_state()
            self.app.set_status("Obrázek vložen ze schránky")

    def insert_image_bytes(
        self,
        image_bytes,
        mark_modified=False,
        display_width_px=None,
    ):
        try:
            with Image.open(BytesIO(image_bytes)) as opened:
                image = opened.convert("RGBA").copy()
        except Exception:
            return False

        try:
            index = self.text.index("insert")
            rgba = image.convert("RGBA")
            buffer = BytesIO()
            rgba.save(buffer, format="PNG")
            normalized_bytes = buffer.getvalue()

            if display_width_px is None:
                display_width_px = self._default_image_display_width(rgba.width)

            photo = self._make_display_photo(rgba, display_width_px)
            tk_name = "img_" + uuid.uuid4().hex
        except Exception:
            return False

        # Correct name string construction separately for clarity.
        tk_name = "img_" + uuid.uuid4().hex

        try:
            self.text.image_create(
                index,
                image=photo,
                name=tk_name,
                padx=4,
                pady=4,
            )
        except tk.TclError:
            return False

        self.embedded_images[tk_name] = {
            "photo": photo,
            "bytes": normalized_bytes,
            "pixel_size": rgba.size,
            "display_width_px": int(display_width_px),
        }

        try:
            self.text.mark_set("insert", f"{tk_name} +1c")
        except tk.TclError:
            pass

        if mark_modified:
            self.select_image(tk_name)
            self.saved = False
            self.app.update_tab_title(self)
            self.app.save_state()

        return True

    def _editor_available_image_width(self):
        try:
            width = int(self.text.winfo_width())
        except (tk.TclError, ValueError):
            width = 0

        if width <= 1:
            # Reasonable fallback before the widget has been laid out.
            width = 900

        # Keep a small visual margin inside the editor.
        return max(80, width - 44)

    def _default_image_display_width(self, original_width):
        available = self._editor_available_image_width()
        return max(1, min(int(original_width), int(available)))

    def _make_display_photo(self, image, display_width_px=None):
        display = image.copy()

        if display_width_px is None:
            display_width_px = self._default_image_display_width(display.width)

        display_width_px = max(1, int(display_width_px))

        if display.width != display_width_px:
            ratio = display_width_px / display.width
            new_size = (
                display_width_px,
                max(1, int(round(display.height * ratio))),
            )
            display = display.resize(new_size, Image.Resampling.LANCZOS)

        return ImageTk.PhotoImage(display)

    def resize_selected_image(
        self,
        width_px,
        save_state=True,
        refresh_handles=True,
    ):
        meta = self.get_selected_image_meta()
        if not meta:
            return False

        try:
            original_width, original_height = meta["pixel_size"]
            width_px = int(round(float(width_px)))
        except (KeyError, TypeError, ValueError):
            return False

        # Allow deliberate enlargement above the window width, but keep a
        # sane technical range.
        width_px = max(40, min(6000, width_px))

        try:
            with Image.open(BytesIO(meta["bytes"])) as opened:
                image = opened.convert("RGBA").copy()
        except Exception:
            return False

        photo = self._make_display_photo(image, width_px)

        try:
            self.text.image_configure(self.selected_image_name, image=photo)
        except tk.TclError:
            return False

        meta["photo"] = photo
        meta["display_width_px"] = width_px
        self.saved = False
        self.app.update_tab_title(self)

        if refresh_handles:
            self.schedule_image_handle_refresh()

        self.app.sync_image_menu_state()

        if save_state:
            self.app.save_state()

        return True

    def reset_selected_image_size(self):
        meta = self.get_selected_image_meta()
        if not meta:
            return False
        try:
            original_width = int(meta["pixel_size"][0])
        except (KeyError, TypeError, ValueError):
            return False
        return self.resize_selected_image(original_width)

    def fit_selected_image_to_window(self):
        if not self.get_selected_image_meta():
            return False
        return self.resize_selected_image(self._editor_available_image_width())

    def scale_selected_image(self, factor):
        meta = self.get_selected_image_meta()
        if not meta:
            return False
        try:
            current = int(meta.get("display_width_px") or meta["pixel_size"][0])
        except (KeyError, TypeError, ValueError):
            return False
        return self.resize_selected_image(current * float(factor))

    def _cleanup_stale_images(self):
        live_names = set(self.text.image_names())
        for name in list(self.embedded_images):
            if name not in live_names:
                self.embedded_images.pop(name, None)

    def _set_run_format(self, run, style):
        run.bold = bool(style.get("bold"))
        run.italic = bool(style.get("italic"))
        run.underline = bool(style.get("underline"))
        run.font.name = "Segoe UI"
        run.font.size = Pt(int(style.get("size") or DEFAULT_FONT_SIZE))

    def _append_text_to_docx(self, document, paragraph, value, style):
        if paragraph is None:
            paragraph = document.add_paragraph()
            paragraph.paragraph_format.space_before = Pt(0)
            paragraph.paragraph_format.space_after = Pt(0)

        parts = value.split("\n")
        for idx, part in enumerate(parts):
            if part:
                run = paragraph.add_run(part)
                self._set_run_format(run, style)

            if idx < len(parts) - 1:
                paragraph = document.add_paragraph()
                paragraph.paragraph_format.space_before = Pt(0)
                paragraph.paragraph_format.space_after = Pt(0)

        return paragraph

    def _append_image_to_docx(self, document, paragraph, image_name):
        meta = self.embedded_images.get(image_name)
        if not meta or not meta.get("bytes"):
            return paragraph

        if paragraph is None:
            paragraph = document.add_paragraph()
            paragraph.paragraph_format.space_before = Pt(0)
            paragraph.paragraph_format.space_after = Pt(0)

        image_bytes = meta["bytes"]

        try:
            original_width, original_height = meta.get("pixel_size") or (0, 0)
            if not original_width:
                with Image.open(BytesIO(image_bytes)) as img:
                    original_width, original_height = img.size

            display_width_px = int(
                meta.get("display_width_px") or original_width
            )

            # Store the actual size chosen in the editor. 96 DPI gives a
            # predictable mapping between screen pixels and Word inches.
            width_inches = max(0.2, display_width_px / 96.0)
            run = paragraph.add_run()
            run.add_picture(BytesIO(image_bytes), width=Inches(width_inches))
        except Exception as e:
            raise OSError(f"Obrázek se nepodařilo zapsat do DOCX: {e}") from e

        return paragraph

    def save_docx(self, path):
        self._cleanup_stale_images()

        document = Document()
        normal = document.styles["Normal"]
        normal.font.name = "Segoe UI"
        normal.font.size = Pt(DEFAULT_FONT_SIZE)

        try:
            document.core_properties.title = self.get_title()
        except Exception:
            pass

        paragraph = None
        dump = self.text.dump(
            "1.0",
            "end-1c",
            text=True,
            tag=True,
            image=True,
        )

        for kind, value, index in dump:
            if kind == "text":
                style = self.style_at(index)
                paragraph = self._append_text_to_docx(
                    document, paragraph, value, style
                )
            elif kind == "image":
                paragraph = self._append_image_to_docx(
                    document, paragraph, value
                )

        if paragraph is None:
            paragraph = document.add_paragraph()
            paragraph.paragraph_format.space_before = Pt(0)
            paragraph.paragraph_format.space_after = Pt(0)

        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        document.save(path)

    def _style_from_docx_run(self, run):
        size = DEFAULT_FONT_SIZE
        if run.font.size is not None:
            try:
                size = int(round(run.font.size.pt))
            except Exception:
                pass

        return {
            "bold": bool(run.bold),
            "italic": bool(run.italic),
            "underline": bool(run.underline),
            "size": max(6, min(96, size)),
        }

    def _insert_loaded_text(self, value, style):
        if not value:
            return

        start = self.text.index("insert")
        self.text.insert("insert", value)
        end = self.text.index("insert")
        if self.text.compare(end, ">", start):
            tag = self.ensure_format_tag(style)
            self.text.tag_add(tag, start, end)

    def _drawing_width_px(self, drawing):
        # OOXML stores drawing extents in EMU. 914400 EMU = 1 inch.
        # We use the same 96 DPI mapping as the saver.
        try:
            for extent in drawing.iter(qn("wp:extent")):
                cx = extent.get("cx")
                if cx:
                    return max(1, int(round(int(cx) / 914400 * 96)))
        except Exception:
            pass
        return None

    def _insert_docx_drawing(self, document, drawing):
        display_width_px = self._drawing_width_px(drawing)

        for blip in drawing.iter(qn("a:blip")):
            rel_id = blip.get(qn("r:embed"))
            if not rel_id:
                continue
            part = document.part.related_parts.get(rel_id)
            if part is None:
                continue
            blob = getattr(part, "blob", None)
            if blob:
                self.insert_image_bytes(
                    blob,
                    mark_modified=False,
                    display_width_px=display_width_px,
                )

    def load_docx(self, path):
        document = Document(path)

        self._loading_document = True
        try:
            self.text.delete("1.0", "end")
            self.embedded_images.clear()

            for p_index, paragraph in enumerate(document.paragraphs):
                if p_index:
                    self.text.insert("insert", "\n")

                for run in paragraph.runs:
                    style = self._style_from_docx_run(run)

                    # Preserve the order of text, tabs, line breaks and inline
                    # drawings inside the run.
                    for child in run._r.iterchildren():
                        if child.tag == qn("w:rPr"):
                            continue
                        if child.tag == qn("w:t"):
                            self._insert_loaded_text(child.text or "", style)
                        elif child.tag == qn("w:tab"):
                            self._insert_loaded_text("\t", style)
                        elif child.tag == qn("w:br"):
                            self._insert_loaded_text("\n", style)
                        elif child.tag == qn("w:drawing"):
                            self._insert_docx_drawing(document, child)

            self.text.mark_set("insert", "end-1c")
            self.text.edit_modified(False)

            try:
                end = self.text.index("end-1c")
                if self.text.compare(end, ">", "1.0"):
                    probe = self.text.index(f"{end} -1c")
                    self.set_typing_style(self.style_at(probe))
            except tk.TclError:
                pass
        finally:
            self._loading_document = False

        self.app.sync_format_controls(use_typing_style=True)

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

    def on_editor_click(self, event=None):
        self.select_image_at_pointer(event)
        self.app.sync_format_controls(update_typing_style=True)
        return None

    def select_image_at_pointer(self, event):
        selected = None

        if event is not None:
            for name in self.text.image_names():
                try:
                    box = self.text.bbox(name)
                except tk.TclError:
                    box = None

                if not box:
                    continue

                x, y, width, height = box
                if x <= event.x <= x + width and y <= event.y <= y + height:
                    selected = name
                    break

        self.select_image(selected)

    def select_image(self, image_name):
        if image_name and image_name not in self.text.image_names():
            image_name = None

        self.selected_image_name = image_name

        if image_name:
            self.show_image_resize_handles()
        else:
            self.hide_image_resize_handles()

        self.app.sync_image_menu_state()

    def schedule_image_handle_refresh(self, event=None):
        if self._image_handle_refresh_job is not None:
            try:
                self.text.after_cancel(self._image_handle_refresh_job)
            except tk.TclError:
                pass

        self._image_handle_refresh_job = self.text.after(
            15,
            self.refresh_image_resize_handles,
        )

    def _make_resize_handle(self, corner):
        handle = tk.Frame(
            self.text,
            width=10,
            height=10,
            background="#ffffff",
            highlightbackground="#2563eb",
            highlightcolor="#2563eb",
            highlightthickness=2,
            borderwidth=0,
            cursor="size_nw_se" if corner in ("nw", "se") else "size_ne_sw",
        )

        handle.bind(
            "<ButtonPress-1>",
            lambda event, c=corner: self.begin_image_corner_resize(event, c),
        )
        handle.bind(
            "<B1-Motion>",
            lambda event, c=corner: self.drag_image_corner_resize(event, c),
        )
        handle.bind(
            "<ButtonRelease-1>",
            self.end_image_corner_resize,
        )
        return handle

    def show_image_resize_handles(self):
        if not self.selected_image_name:
            self.hide_image_resize_handles()
            return

        if not self.image_resize_handles:
            for corner in ("nw", "ne", "sw", "se"):
                self.image_resize_handles[corner] = self._make_resize_handle(corner)

        self.refresh_image_resize_handles()

    def hide_image_resize_handles(self):
        for handle in self.image_resize_handles.values():
            try:
                handle.place_forget()
            except tk.TclError:
                pass

    def refresh_image_resize_handles(self):
        self._image_handle_refresh_job = None

        if not self.selected_image_name:
            self.hide_image_resize_handles()
            return

        try:
            box = self.text.bbox(self.selected_image_name)
        except tk.TclError:
            box = None

        if not box:
            self.hide_image_resize_handles()
            return

        x, y, width, height = box
        half = 5

        positions = {
            "nw": (x - half, y - half),
            "ne": (x + width - half, y - half),
            "sw": (x - half, y + height - half),
            "se": (x + width - half, y + height - half),
        }

        for corner, (px, py) in positions.items():
            handle = self.image_resize_handles.get(corner)
            if handle is not None:
                handle.place(x=px, y=py, width=10, height=10)
                handle.lift()

    def begin_image_corner_resize(self, event, corner):
        meta = self.get_selected_image_meta()
        if not meta:
            return "break"

        try:
            current_width = int(
                meta.get("display_width_px") or meta["pixel_size"][0]
            )
        except (KeyError, TypeError, ValueError):
            return "break"

        self._image_resize_drag = {
            "corner": corner,
            "start_x_root": event.x_root,
            "start_width": current_width,
        }
        return "break"

    def drag_image_corner_resize(self, event, corner):
        drag = self._image_resize_drag
        if not drag or drag.get("corner") != corner:
            return "break"

        delta_x = event.x_root - drag["start_x_root"]
        direction = 1 if corner in ("ne", "se") else -1
        new_width = drag["start_width"] + direction * delta_x

        self.resize_selected_image(
            new_width,
            save_state=False,
            refresh_handles=True,
        )
        return "break"

    def end_image_corner_resize(self, event=None):
        if self._image_resize_drag is None:
            return "break"

        self._image_resize_drag = None
        self.saved = False
        self.app.update_tab_title(self)
        self.app.save_state()
        self.schedule_image_handle_refresh()
        return "break"

    def get_selected_image_meta(self):
        if not self.selected_image_name:
            return None
        if self.selected_image_name not in self.text.image_names():
            self.selected_image_name = None
            self.hide_image_resize_handles()
            self.app.sync_image_menu_state()
            return None
        return self.embedded_images.get(self.selected_image_name)

    def ensure_temp_path(self):
        if self.temp_path:
            return
        temp_dir = Path(tempfile.gettempdir()) / "autosave_notepad"
        temp_dir.mkdir(parents=True, exist_ok=True)
        fd, path = tempfile.mkstemp(prefix="note_", suffix=".docx", dir=temp_dir)
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
        if self._loading_document:
            self.text.edit_modified(False)
            return
        self.saved = False
        self.app.update_tab_title(self)
        # DOCX creation is intentionally not done on every keystroke.
        # Periodic autosave writes a complete recovery document.
        self.app.save_state()
        self.text.edit_modified(False)

    def autosave(self):
        self.write_temp_snapshot()
        self.app.export_tab_to_autosave_folder(self)
        self.app.save_state()

    def write_temp_snapshot(self):
        try:
            self.ensure_temp_path()
            self.save_docx(self.temp_path)
        except (OSError, ValueError) as e:
            self.app.set_status(f"Autosave DOCX návrhu selhal: {e}")

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
        self._app_icon_photo = apply_tk_window_icon(self.root)
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
        self.notebook.bind(
            "<<NotebookTabChanged>>",
            self.on_notebook_tab_changed,
        )

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
        file_menu.add_command(label="Tisk...", command=self.print_current_document, accelerator="Ctrl+P")
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
        edit_menu.add_command(label="Vložit obrázek ze schránky", command=self.paste_image_current_tab)
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

        image_menu = tk.Menu(menubar, tearoff=0)
        image_menu.add_command(
            label="Vložit ze schránky",
            command=self.paste_image_current_tab,
        )
        image_menu.add_separator()
        image_menu.add_command(
            label="Zmenšit o 10 %",
            command=lambda: self.scale_selected_image(0.9),
        )
        image_menu.add_command(
            label="Zvětšit o 10 %",
            command=lambda: self.scale_selected_image(1.1),
        )
        image_menu.add_command(
            label="Nastavit přesnou šířku...",
            command=self.prompt_image_width,
        )
        image_menu.add_separator()
        image_menu.add_command(
            label="Původní velikost",
            command=self.reset_selected_image_size,
        )
        image_menu.add_command(
            label="Přizpůsobit šířce okna",
            command=self.fit_selected_image,
        )

        self.image_menu = image_menu
        self.image_menu_edit_indices = (2, 3, 4, 6, 7)
        menubar.add_cascade(label="Obrázek", menu=image_menu)

        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="Zkontrolovat aktualizace", command=self.check_for_updates_manual)
        help_menu.add_command(label="Nastavit GitHub přístup", command=self.configure_github_token)
        help_menu.add_separator()
        help_menu.add_command(label="O programu", command=self.show_about)
        menubar.add_cascade(label="Nápověda", menu=help_menu)

        self.root.config(menu=menubar)
        self.root.after_idle(self.sync_image_menu_state)
        self.root.bind("<Control-n>", lambda e: self.new_tab())
        self.root.bind("<Control-o>", lambda e: self.open_file())
        self.root.bind("<Control-p>", lambda e: self.print_current_document())
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

        print_button = ttk.Button(
            file_group,
            text="Tisk",
            command=self.print_current_document,
            style="Toolbar.TButton",
        )
        print_button.pack(side="left", padx=(0, 4))
        print_button.bind("<Shift-MouseWheel>", horizontal_mousewheel)

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

    def paste_image_current_tab(self):
        tab = self.current_tab()
        if not tab:
            return
        if not tab.paste_image_from_clipboard():
            messagebox.showinfo(
                "Vložit obrázek",
                "Ve schránce není obrázek.",
                parent=self.root,
            )

    def on_notebook_tab_changed(self, event=None):
        for tab in self.tabs:
            if tab is not self.current_tab():
                tab.hide_image_resize_handles()

        self.sync_format_controls()
        self.sync_image_menu_state()

        tab = self.current_tab()
        if tab and tab.selected_image_name:
            tab.schedule_image_handle_refresh()

    def sync_image_menu_state(self):
        menu = getattr(self, "image_menu", None)
        if menu is None:
            return

        tab = self.current_tab()
        meta = tab.get_selected_image_meta() if tab else None
        state = "normal" if meta else "disabled"

        for index in getattr(self, "image_menu_edit_indices", ()):
            try:
                menu.entryconfigure(index, state=state)
            except tk.TclError:
                pass

    def prompt_image_width(self):
        tab = self.current_tab()
        meta = tab.get_selected_image_meta() if tab else None
        if not meta:
            return

        try:
            current = int(
                meta.get("display_width_px") or meta["pixel_size"][0]
            )
        except (KeyError, TypeError, ValueError):
            return

        width = simpledialog.askinteger(
            "Velikost obrázku",
            "Šířka obrázku v pixelech:",
            initialvalue=current,
            minvalue=40,
            maxvalue=6000,
            parent=self.root,
        )
        if width is None:
            return

        tab.resize_selected_image(width)
        self.sync_image_menu_state()

    def scale_selected_image(self, factor):
        tab = self.current_tab()
        if tab and tab.scale_selected_image(factor):
            self.sync_image_menu_state()

    def reset_selected_image_size(self):
        tab = self.current_tab()
        if tab and tab.reset_selected_image_size():
            self.sync_image_menu_state()

    def fit_selected_image(self):
        tab = self.current_tab()
        if tab and tab.fit_selected_image_to_window():
            self.sync_image_menu_state()


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
            path = self.ensure_autosave_directory() / (
                self.sanitize_filename(tab.get_title()) + ".docx"
            )
            if (
                tab.export_path
                and Path(tab.export_path) != path
                and Path(tab.export_path).exists()
            ):
                try:
                    Path(tab.export_path).unlink()
                except OSError:
                    pass

            tab.save_docx(path)
            tab.export_path = str(path)
        except (OSError, ValueError) as e:
            self.set_status(f"Automatické uložení DOCX selhalo: {e}")

    def delete_tab_export_file(self, tab):
        try:
            path = (
                Path(tab.export_path)
                if tab.export_path
                else self.ensure_autosave_directory()
                / (self.sanitize_filename(tab.get_title()) + ".docx")
            )
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

    def new_tab(
        self,
        content="",
        title=None,
        file_path=None,
        temp_path=None,
        custom_title=None,
        prompt_for_name=True,
        formatting=None,
        images=None,
        document_path=None,
    ):
        if custom_title is None and prompt_for_name:
            custom_title = self.prompt_unique_tab_name(title="Nová karta", prompt="Zadej název nové karty:")
            if custom_title is None:
                return None
        title = title or custom_title or f"{UNTITLED_PREFIX} {len(self.tabs) + 1}"
        tab = NoteTab(
            self,
            title,
            content,
            file_path,
            custom_title,
            formatting,
            images,
        )
        if temp_path:
            tab.temp_path = temp_path
            tab.write_temp_snapshot()
        if document_path:
            try:
                tab.load_docx(document_path)
                tab.write_temp_snapshot()
            except Exception as e:
                try:
                    self.notebook.forget(tab.frame)
                except tk.TclError:
                    pass
                messagebox.showerror(
                    "Otevření DOCX",
                    f"Dokument se nepodařilo otevřít:\n{e}",
                    parent=self.root,
                )
                return None

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
        ttk.Label(frame, text="Složka automaticky ukládaných DOCX:").grid(row=1, column=0, sticky="w", pady=4)
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
            title="Otevřít dokument",
            filetypes=[
                ("Word documents", "*.docx"),
                ("Staré textové poznámky", "*.txt"),
                ("All files", "*.*"),
            ],
        )
        if not path:
            return

        source = Path(path)
        name = self.sanitize_filename(source.stem)
        if name.lower() in self.get_used_titles():
            name = self.prompt_unique_tab_name(
                name,
                "Duplicitní název",
                "Zadej jiný název karty:",
            )
            if name is None:
                return

        if source.suffix.lower() == ".docx":
            tab = self.new_tab(
                title=name,
                file_path=str(source),
                custom_title=name,
                prompt_for_name=False,
                document_path=str(source),
            )
            if tab:
                tab.saved = True
                self.update_tab_title(tab)
                self.save_state()
                self.set_status(f"Otevřen DOCX: {source}")
            return

        if source.suffix.lower() == ".txt":
            try:
                try:
                    content = source.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    content = source.read_text(encoding="cp1250")
            except OSError as e:
                messagebox.showerror(
                    "Chyba",
                    f"Soubor nešlo otevřít:\n{e}",
                    parent=self.root,
                )
                return

            # TXT is import-only. Saving creates a new DOCX.
            tab = self.new_tab(
                content=content,
                title=name,
                file_path=None,
                custom_title=name,
                prompt_for_name=False,
            )
            if tab:
                tab.saved = False
                self.update_tab_title(tab)
                self.set_status(
                    "Starý TXT byl importován. Při uložení vznikne DOCX."
                )
            return

        messagebox.showerror(
            "Nepodporovaný formát",
            "Aplikace ukládá dokumenty jako DOCX. Otevřít lze DOCX nebo starý TXT pro import.",
            parent=self.root,
        )

    def _windows_print_dialog(self):
        """Show the native Windows print dialog and return a configured printer DC."""
        if os.name != "nt":
            raise OSError("Tiskový dialog je v této verzi podporován pouze ve Windows.")

        import ctypes
        from ctypes import wintypes

        PD_RETURNDC = 0x00000100
        PD_NOSELECTION = 0x00000004
        PD_NOPAGENUMS = 0x00000008
        PD_HIDEPRINTTOFILE = 0x00100000
        PD_USEDEVMODECOPIESANDCOLLATE = 0x00040000

        class PRINTDLGW(ctypes.Structure):
            _fields_ = [
                ("lStructSize", wintypes.DWORD),
                ("hwndOwner", wintypes.HWND),
                ("hDevMode", wintypes.HGLOBAL),
                ("hDevNames", wintypes.HGLOBAL),
                ("hDC", wintypes.HDC),
                ("Flags", wintypes.DWORD),
                ("nFromPage", wintypes.WORD),
                ("nToPage", wintypes.WORD),
                ("nMinPage", wintypes.WORD),
                ("nMaxPage", wintypes.WORD),
                ("nCopies", wintypes.WORD),
                ("hInstance", wintypes.HINSTANCE),
                ("lCustData", wintypes.LPARAM),
                ("lpfnPrintHook", ctypes.c_void_p),
                ("lpfnSetupHook", ctypes.c_void_p),
                ("lpPrintTemplateName", wintypes.LPCWSTR),
                ("lpSetupTemplateName", wintypes.LPCWSTR),
                ("hPrintTemplate", wintypes.HGLOBAL),
                ("hSetupTemplate", wintypes.HGLOBAL),
            ]

        comdlg32 = ctypes.WinDLL("comdlg32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

        comdlg32.PrintDlgW.argtypes = [ctypes.POINTER(PRINTDLGW)]
        comdlg32.PrintDlgW.restype = wintypes.BOOL
        comdlg32.CommDlgExtendedError.argtypes = []
        comdlg32.CommDlgExtendedError.restype = wintypes.DWORD

        kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
        kernel32.GlobalLock.restype = ctypes.c_void_p
        kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
        kernel32.GlobalUnlock.restype = wintypes.BOOL
        kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]
        kernel32.GlobalFree.restype = wintypes.HGLOBAL

        dialog = PRINTDLGW()
        dialog.lStructSize = ctypes.sizeof(PRINTDLGW)
        dialog.hwndOwner = self.root.winfo_id()
        dialog.Flags = (
            PD_RETURNDC
            | PD_NOSELECTION
            | PD_NOPAGENUMS
            | PD_HIDEPRINTTOFILE
            | PD_USEDEVMODECOPIESANDCOLLATE
        )
        dialog.nCopies = 1

        if not comdlg32.PrintDlgW(ctypes.byref(dialog)):
            error_code = comdlg32.CommDlgExtendedError()
            if error_code:
                raise OSError(f"Windows tiskový dialog selhal (0x{error_code:08X}).")
            return None

        printer = "Vybraná tiskárna"

        try:
            if dialog.hDevNames:
                ptr = kernel32.GlobalLock(dialog.hDevNames)
                if ptr:
                    try:
                        offsets = ctypes.cast(ptr, ctypes.POINTER(ctypes.c_ushort))
                        device_offset = offsets[1]
                        base = int(ptr)
                        printer = ctypes.wstring_at(base + device_offset * 2)
                    finally:
                        kernel32.GlobalUnlock(dialog.hDevNames)
        finally:
            if dialog.hDevMode:
                kernel32.GlobalFree(dialog.hDevMode)
            if dialog.hDevNames:
                kernel32.GlobalFree(dialog.hDevNames)

        if not dialog.hDC:
            raise OSError("Windows nevrátil tiskový kontext zvolené tiskárny.")

        return {
            "printer": printer,
            "hdc": int(dialog.hDC),
        }

    def _print_font_path(self, bold=False, italic=False):
        """Return a Windows font file that matches the editor as closely as possible."""
        windir = Path(os.environ.get("WINDIR", r"C:\Windows"))
        fonts = windir / "Fonts"

        if bold and italic:
            candidates = ("segoeuiz.ttf", "arialbi.ttf")
        elif bold:
            candidates = ("segoeuib.ttf", "arialbd.ttf")
        elif italic:
            candidates = ("segoeuii.ttf", "ariali.ttf")
        else:
            candidates = ("segoeui.ttf", "arial.ttf")

        for name in candidates:
            path = fonts / name
            if path.exists():
                return str(path)

        # Pillow can sometimes resolve the family name through FreeType.
        return "arial.ttf"

    def _print_font(self, style, dpi):
        size_pt = int(style.get("size") or DEFAULT_FONT_SIZE)
        size_px = max(8, int(round(size_pt * dpi / 72.0)))
        path = self._print_font_path(
            bold=bool(style.get("bold")),
            italic=bool(style.get("italic")),
        )
        return ImageFont.truetype(path, size_px)

    def _draw_print_text(
        self,
        draw,
        text,
        style,
        x,
        y,
        content_left,
        content_right,
        content_bottom,
        line_gap,
        dpi,
        new_page,
    ):
        """Draw wrapped styled text and return updated x/y/draw state."""
        font = self._print_font(style, dpi)
        underline = bool(style.get("underline"))

        try:
            ascent, descent = font.getmetrics()
            line_height = max(1, ascent + descent + line_gap)
        except Exception:
            bbox = draw.textbbox((0, 0), "Ag", font=font)
            line_height = max(1, bbox[3] - bbox[1] + line_gap)

        def text_width(value):
            if not value:
                return 0
            box = draw.textbbox((0, 0), value, font=font)
            return max(0, box[2] - box[0])

        def ensure_vertical_space(height):
            nonlocal draw, x, y
            if y + height > content_bottom:
                draw, x, y = new_page()
            return draw, x, y

        # Preserve whitespace and explicit newlines, but wrap normal text.
        chunks = re.findall(r"\n|[^\S\n]+|[^\s\n]+", text)

        for chunk in chunks:
            if chunk == "\n":
                x = content_left
                y += line_height
                ensure_vertical_space(line_height)
                continue

            if not chunk:
                continue

            width = text_width(chunk)

            # Skip leading spaces on a wrapped line.
            if chunk.isspace() and x == content_left:
                continue

            if x > content_left and x + width > content_right:
                x = content_left
                y += line_height
                ensure_vertical_space(line_height)
                if chunk.isspace():
                    continue

            # Very long unbroken text: split by character to avoid clipping.
            if width > (content_right - content_left):
                remaining = chunk
                while remaining:
                    fit = ""
                    for char in remaining:
                        candidate = fit + char
                        if fit and text_width(candidate) > (content_right - x):
                            break
                        fit = candidate

                    if not fit:
                        fit = remaining[0]

                    draw.text((x, y), fit, font=font, fill="black")

                    if underline:
                        w = text_width(fit)
                        underline_y = y + line_height - max(1, int(dpi / 96))
                        draw.line(
                            (x, underline_y, x + w, underline_y),
                            fill="black",
                            width=max(1, int(round(dpi / 192))),
                        )

                    remaining = remaining[len(fit):]
                    x += text_width(fit)

                    if remaining:
                        x = content_left
                        y += line_height
                        ensure_vertical_space(line_height)
                continue

            draw.text((x, y), chunk, font=font, fill="black")

            if underline:
                underline_y = y + line_height - max(1, int(dpi / 96))
                draw.line(
                    (x, underline_y, x + width, underline_y),
                    fill="black",
                    width=max(1, int(round(dpi / 192))),
                )

            x += width

        return draw, x, y, line_height

    def _print_note_to_dc(self, tab, printer_info):
        """Render the current editor directly to the selected Windows printer DC."""
        import ctypes
        from ctypes import wintypes

        hdc = int(printer_info["hdc"])
        printer_name = printer_info.get("printer", "Tiskárna")

        gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

        gdi32.GetDeviceCaps.argtypes = [wintypes.HDC, ctypes.c_int]
        gdi32.GetDeviceCaps.restype = ctypes.c_int
        gdi32.StartDocW.argtypes = [wintypes.HDC, ctypes.c_void_p]
        gdi32.StartDocW.restype = ctypes.c_int
        gdi32.StartPage.argtypes = [wintypes.HDC]
        gdi32.StartPage.restype = ctypes.c_int
        gdi32.EndPage.argtypes = [wintypes.HDC]
        gdi32.EndPage.restype = ctypes.c_int
        gdi32.EndDoc.argtypes = [wintypes.HDC]
        gdi32.EndDoc.restype = ctypes.c_int
        gdi32.AbortDoc.argtypes = [wintypes.HDC]
        gdi32.AbortDoc.restype = ctypes.c_int
        gdi32.DeleteDC.argtypes = [wintypes.HDC]
        gdi32.DeleteDC.restype = wintypes.BOOL

        HORZRES = 8
        VERTRES = 10
        LOGPIXELSX = 88
        LOGPIXELSY = 90

        class DOCINFOW(ctypes.Structure):
            _fields_ = [
                ("cbSize", ctypes.c_int),
                ("lpszDocName", wintypes.LPCWSTR),
                ("lpszOutput", wintypes.LPCWSTR),
                ("lpszDatatype", wintypes.LPCWSTR),
                ("fwType", wintypes.DWORD),
            ]

        printable_w = gdi32.GetDeviceCaps(hdc, HORZRES)
        printable_h = gdi32.GetDeviceCaps(hdc, VERTRES)
        device_dpi_x = max(72, gdi32.GetDeviceCaps(hdc, LOGPIXELSX))
        device_dpi_y = max(72, gdi32.GetDeviceCaps(hdc, LOGPIXELSY))

        if printable_w <= 0 or printable_h <= 0:
            gdi32.DeleteDC(hdc)
            raise OSError("Zvolená tiskárna nevrátila platnou tiskovou oblast.")

        # Render at up to 300 DPI. This keeps text and screenshots sharp while
        # preventing excessive memory use on 600/1200 DPI printer drivers.
        render_dpi = min(300, max(150, device_dpi_y))
        scale_x = printable_w / max(1, int(round(printable_w * render_dpi / device_dpi_x)))
        scale_y = printable_h / max(1, int(round(printable_h * render_dpi / device_dpi_y)))

        page_w = max(1, int(round(printable_w * render_dpi / device_dpi_x)))
        page_h = max(1, int(round(printable_h * render_dpi / device_dpi_y)))

        # 15 mm logical page margins inside the printable region.
        margin = max(24, int(round(render_dpi * 15 / 25.4)))
        content_left = margin
        content_top = margin
        content_right = max(content_left + 50, page_w - margin)
        content_bottom = max(content_top + 50, page_h - margin)
        line_gap = max(2, int(round(render_dpi * 0.035)))

        pages = []
        page = None
        draw = None
        x = content_left
        y = content_top

        def create_page():
            nonlocal page, draw, x, y
            page = Image.new("RGB", (page_w, page_h), "white")
            draw = ImageDraw.Draw(page)
            pages.append(page)
            x = content_left
            y = content_top
            return draw, x, y

        create_page()

        dump = tab.text.dump(
            "1.0",
            "end-1c",
            text=True,
            tag=True,
            image=True,
        )

        for kind, value, index in dump:
            if kind == "text":
                style = tab.style_at(index)

                def new_page_for_text():
                    return create_page()

                draw, x, y, _line_height = self._draw_print_text(
                    draw=draw,
                    text=value,
                    style=style,
                    x=x,
                    y=y,
                    content_left=content_left,
                    content_right=content_right,
                    content_bottom=content_bottom,
                    line_gap=line_gap,
                    dpi=render_dpi,
                    new_page=new_page_for_text,
                )

            elif kind == "image":
                meta = tab.embedded_images.get(value)
                if not meta or not meta.get("bytes"):
                    continue

                try:
                    with Image.open(BytesIO(meta["bytes"])) as opened:
                        image = opened.convert("RGB").copy()
                except Exception:
                    continue

                original_w, original_h = image.size
                display_width_px = int(
                    meta.get("display_width_px") or original_w
                )

                # Editor pixels map to 96 DPI physical units, same convention
                # used when saving the image size to DOCX.
                target_w = max(
                    1,
                    int(round(display_width_px / 96.0 * render_dpi)),
                )
                max_w = content_right - content_left
                target_w = min(target_w, max_w)
                target_h = max(
                    1,
                    int(round(original_h * target_w / original_w)),
                )

                # Images are block-like for printing. Finish the current text
                # line first if needed.
                if x != content_left:
                    base_style = {"size": DEFAULT_FONT_SIZE}
                    font = self._print_font(base_style, render_dpi)
                    try:
                        ascent, descent = font.getmetrics()
                        normal_line_h = ascent + descent + line_gap
                    except Exception:
                        normal_line_h = int(round(DEFAULT_FONT_SIZE * render_dpi / 72)) + line_gap
                    x = content_left
                    y += normal_line_h

                # If the image itself is taller than a printable page, shrink
                # it to fit one page while preserving aspect ratio.
                max_h = content_bottom - content_top
                if target_h > max_h:
                    ratio = max_h / target_h
                    target_w = max(1, int(round(target_w * ratio)))
                    target_h = max(1, int(round(target_h * ratio)))

                if y + target_h > content_bottom:
                    create_page()

                if image.size != (target_w, target_h):
                    image = image.resize(
                        (target_w, target_h),
                        Image.Resampling.LANCZOS,
                    )

                page.paste(image, (content_left, y))
                y += target_h + max(6, int(round(render_dpi * 0.06)))
                x = content_left

        docinfo = DOCINFOW()
        docinfo.cbSize = ctypes.sizeof(DOCINFOW)
        docinfo.lpszDocName = tab.get_title() or APP_NAME
        docinfo.lpszOutput = None
        docinfo.lpszDatatype = None
        docinfo.fwType = 0

        started_doc = False

        try:
            if gdi32.StartDocW(hdc, ctypes.byref(docinfo)) <= 0:
                raise OSError(
                    f"Windows nedokázal zahájit tiskovou úlohu pro {printer_name}."
                )
            started_doc = True

            for page_image in pages:
                if gdi32.StartPage(hdc) <= 0:
                    raise OSError("Windows nedokázal zahájit tisk stránky.")

                try:
                    dib = ImageWin.Dib(page_image)
                    dib.draw(
                        hdc,
                        (
                            0,
                            0,
                            printable_w,
                            printable_h,
                        ),
                    )
                finally:
                    if gdi32.EndPage(hdc) <= 0:
                        raise OSError("Windows nedokázal dokončit tisk stránky.")

            if gdi32.EndDoc(hdc) <= 0:
                raise OSError("Windows nedokázal dokončit tiskovou úlohu.")

            started_doc = False

        except Exception:
            if started_doc:
                try:
                    gdi32.AbortDoc(hdc)
                except Exception:
                    pass
            raise
        finally:
            gdi32.DeleteDC(hdc)

    def print_current_document(self, event=None):
        tab = self.current_tab()
        if not tab:
            return "break" if event is not None else None

        if os.name != "nt":
            messagebox.showerror(
                "Tisk",
                "Tisk je v této verzi podporován pouze ve Windows.",
                parent=self.root,
            )
            return "break" if event is not None else None

        printer_info = None

        try:
            printer_info = self._windows_print_dialog()
            if printer_info is None:
                return "break" if event is not None else None

            self.set_status(
                f"Připravuji tisk: {printer_info['printer']}"
            )
            self.root.update_idletasks()

            self._print_note_to_dc(tab, printer_info)
            printer_info = None  # DC was released by _print_note_to_dc.

            self.set_status("Dokument byl odeslán do tiskové fronty.")

        except Exception as e:
            # If rendering failed before _print_note_to_dc took ownership of
            # the DC, release it here.
            if printer_info and printer_info.get("hdc"):
                try:
                    import ctypes
                    from ctypes import wintypes
                    gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
                    gdi32.DeleteDC.argtypes = [wintypes.HDC]
                    gdi32.DeleteDC.restype = wintypes.BOOL
                    gdi32.DeleteDC(int(printer_info["hdc"]))
                except Exception:
                    pass

            messagebox.showerror(
                "Tisk",
                "Dokument se nepodařilo vytisknout.\n\n"
                f"{e}",
                parent=self.root,
            )

        return "break" if event is not None else None

    def save_current_file(self, event=None):
        tab = self.current_tab()
        if not tab:
            return
        if tab.file_path and Path(tab.file_path).suffix.lower() == ".docx":
            self.write_to_path(tab, tab.file_path)
        else:
            self.save_current_file_as()

    def save_current_file_as(self):
        tab = self.current_tab()
        if not tab:
            return

        path = filedialog.asksaveasfilename(
            title="Uložit jako DOCX",
            initialfile=self.sanitize_filename(tab.get_title()) + ".docx",
            defaultextension=".docx",
            filetypes=[("Word documents", "*.docx")],
        )
        if path:
            self.write_to_path(tab, path)

    def write_to_path(self, tab, path):
        path = Path(path)
        if path.suffix.lower() != ".docx":
            path = path.with_suffix(".docx")

        try:
            tab.save_docx(path)
            tab.mark_saved(str(path))
            self.set_status(f"Uloženo jako DOCX: {path}")
        except (OSError, ValueError) as e:
            messagebox.showerror(
                "Chyba ukládání",
                f"DOCX se nepodařilo uložit:\n{e}",
                parent=self.root,
            )

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
        tab.hide_image_resize_handles()
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

    def create_update_progress_dialog(self, target_version):
        dialog = tk.Toplevel(self.root)
        dialog.title("Aktualizace AutoSave Notepad")
        dialog.transient(self.root)
        dialog.resizable(False, False)
        dialog.protocol("WM_DELETE_WINDOW", lambda: None)

        frame = ttk.Frame(dialog, padding=18)
        frame.pack(fill="both", expand=True)

        ttk.Label(
            frame,
            text=f"Aktualizace na verzi {target_version}",
            font=("Segoe UI", 11, "bold"),
        ).pack(anchor="w", pady=(0, 12))

        phase_var = tk.StringVar(value="Připravuji aktualizaci…")
        ttk.Label(
            frame,
            textvariable=phase_var,
            width=58,
            anchor="w",
        ).pack(fill="x", pady=(0, 8))

        progress_var = tk.DoubleVar(value=0)
        progress = ttk.Progressbar(
            frame,
            variable=progress_var,
            maximum=100,
            mode="determinate",
            length=480,
        )
        progress.pack(fill="x", pady=(0, 6))

        percent_var = tk.StringVar(value="0 %")
        ttk.Label(
            frame,
            textvariable=percent_var,
            anchor="e",
        ).pack(fill="x")

        dialog.update_idletasks()
        x = self.root.winfo_rootx() + max(0, (self.root.winfo_width() - dialog.winfo_reqwidth()) // 2)
        y = self.root.winfo_rooty() + max(0, (self.root.winfo_height() - dialog.winfo_reqheight()) // 2)
        dialog.geometry(f"+{x}+{y}")
        dialog.grab_set()

        def set_phase(text):
            phase_var.set(text)
            dialog.update_idletasks()

        def set_progress(value):
            value = max(0.0, min(100.0, float(value)))
            progress_var.set(value)
            percent_var.set(f"{int(round(value))} %")
            dialog.update_idletasks()

        return dialog, set_phase, set_progress

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
            messagebox.showinfo(
                "Aktualizace",
                "Automatická instalace funguje v EXE verzi.",
                parent=self.root
            )
            return

        dialog, set_phase, set_progress = self.create_update_progress_dialog(
            release["version"]
        )

        try:
            self.save_state()

            set_phase("Připravuji stahování…")
            set_progress(5)

            new_exe = self.updater.download_and_verify(
                release,
                progress_callback=set_progress,
                phase_callback=set_phase,
            )

            set_phase("Připravuji bezpečnou výměnu programu…")
            set_progress(97)
            self.updater.install_after_exit(new_exe)

            set_phase("Instalátor je připraven. Ukončuji starou verzi…")
            set_progress(100)
            dialog.update_idletasks()

            # Give the user a brief chance to see the final phase.
            self.root.after(700, self.root.destroy)

        except UpdateError as e:
            try:
                dialog.grab_release()
                dialog.destroy()
            except tk.TclError:
                pass

            log_path = self.updater.get_update_log_path()
            messagebox.showerror(
                "Aktualizace",
                f"{e}\n\n"
                f"Diagnostický log aktualizace:\n{log_path}",
                parent=self.root
            )

    def show_about(self):
        messagebox.showinfo(
            "O programu",
            f"{APP_NAME}\nVerze {APP_VERSION}\n\n"
            "Dokumenty se ukládají ve formátu DOCX včetně formátování a obrázků.\n"
            "Aktuální kartu lze tisknout přes Ctrl+P.\n\n"
            f"{GITHUB_OWNER}/{GITHUB_REPO}",
        )

    def set_status(self, text):
        self.status_var.set(text)

    def save_state(self):
        data = {"tabs": [], "settings": self.settings}
        for tab in self.tabs:
            try:
                data["tabs"].append({
                    "title": tab.get_title(),
                    "file_path": tab.file_path,
                    "custom_title": tab.custom_title,
                    "temp_path": tab.temp_path,
                    "saved": tab.saved,
                    "export_path": tab.export_path,
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
            temp_path = item.get("temp_path")
            file_path = item.get("file_path")

            source = None
            if temp_path and os.path.exists(temp_path):
                source = Path(temp_path)
            elif file_path and os.path.exists(file_path):
                source = Path(file_path)

            tab = None

            if source and source.suffix.lower() == ".docx":
                tab = self.new_tab(
                    title=item.get("title") or UNTITLED_PREFIX,
                    file_path=file_path if file_path and Path(file_path).suffix.lower() == ".docx" else None,
                    custom_title=item.get("custom_title"),
                    prompt_for_name=False,
                    document_path=str(source),
                )
            elif source and source.suffix.lower() == ".txt":
                # Migration from pre-DOCX versions.
                try:
                    try:
                        content = source.read_text(encoding="utf-8")
                    except UnicodeDecodeError:
                        content = source.read_text(encoding="cp1250")
                except OSError:
                    content = ""

                tab = self.new_tab(
                    content=content,
                    title=item.get("title") or UNTITLED_PREFIX,
                    file_path=None,
                    custom_title=item.get("custom_title"),
                    prompt_for_name=False,
                )
                if tab:
                    tab.saved = False
            elif not source:
                continue

            if tab:
                tab.saved = item.get("saved", True) if source and source.suffix.lower() == ".docx" else False
                old_export = item.get("export_path")
                if old_export and Path(old_export).suffix.lower() == ".docx":
                    tab.export_path = old_export
                self.update_tab_title(tab)

    def on_close(self):
        for tab in self.tabs:
            tab.write_temp_snapshot()
        self.save_state()
        if self.periodic_autosave_job is not None:
            self.root.after_cancel(self.periodic_autosave_job)
        self.root.destroy()


def main():
    configure_windows_app_identity()
    root = tk.Tk()
    AutoSaveNotepadApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
