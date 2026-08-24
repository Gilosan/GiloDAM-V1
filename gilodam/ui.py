from __future__ import annotations

import json
import logging
import queue
import threading
import traceback
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any, Callable

from PIL import Image, ImageOps, ImageTk

from . import __version__
from .models import AnalysisReport, AssetView, CancelRequested
from .paths import app_data_dir, backup_dir
from .platform_services import open_path
from .service import GiloDAMService
from .vocabularies import STARTER_VOCABULARIES, vocabulary_values


def format_bytes(value: int) -> str:
    size = float(value)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


class GiloDAMApp:
    def __init__(self, root: tk.Tk, service: GiloDAMService, *, logger: logging.Logger):
        self.root = root
        self.service = service
        self.logger = logger
        self.root.title(f"GiloDAM V1 — Local Asset Catalog")
        self.root.geometry(str(self.service.database.get_setting("window_geometry", "1450x900")))
        self.root.minsize(1080, 700)

        self.events: queue.Queue[tuple[Any, ...]] = queue.Queue()
        self.worker_thread: threading.Thread | None = None
        self.cancel_event = threading.Event()
        self.closing = False
        self.search_after_id: str | None = None
        self.thumbnail_token = 0
        self.assets: list[AssetView] = []
        self.assets_by_id: dict[str, AssetView] = {}
        self.source_ids: list[str | None] = [None]
        self.source_roots: dict[str, Path] = {}
        self.tree_images: dict[str, ImageTk.PhotoImage] = {}
        self.placeholder_images: dict[str, ImageTk.PhotoImage] = {}
        self.selected_asset: AssetView | None = None
        self.preview_source: Image.Image | None = None
        self.preview_photo: ImageTk.PhotoImage | None = None
        self.preview_mode = "fit"
        self.preview_zoom = 1.0
        self.slideshow_after_id: str | None = None
        self.slideshow_running = False
        self.keyword_values: list[str] = []

        self._configure_style()
        self._build_menu()
        self._build_ui()
        self._bind_shortcuts()
        self._create_placeholders()
        self._refresh_sources()
        self._refresh_assets()
        self._set_status("Ready. Choose Add Folder to analyze media; GiloDAM will not move originals.")
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.after(80, self._poll_events)

    def _configure_style(self) -> None:
        style = ttk.Style(self.root)
        available = style.theme_names()
        if "vista" in available:
            style.theme_use("vista")
        elif "clam" in available:
            style.theme_use("clam")
        style.configure("Title.TLabel", font=("Segoe UI", 18, "bold"), foreground="#163947")
        style.configure("Subtle.TLabel", foreground="#5f6b73")
        style.configure("Primary.TButton", font=("Segoe UI", 10, "bold"))
        style.configure("Treeview", rowheight=72, font=("Segoe UI", 10))
        style.configure("Treeview.Heading", font=("Segoe UI", 9, "bold"))

    def _build_menu(self) -> None:
        menu = tk.Menu(self.root)
        file_menu = tk.Menu(menu, tearoff=False)
        file_menu.add_command(label="Add Folder…", accelerator="Ctrl+O", command=self.select_folder)
        file_menu.add_separator()
        file_menu.add_command(label="Back Up Catalog…", command=self.backup_catalog)
        export_menu = tk.Menu(file_menu, tearoff=False)
        export_menu.add_command(label="Export Metadata as JSON…", command=lambda: self.export_metadata("json"))
        export_menu.add_command(label="Export Metadata as CSV…", command=lambda: self.export_metadata("csv"))
        file_menu.add_cascade(label="Export Metadata", menu=export_menu)
        file_menu.add_separator()
        file_menu.add_command(label="Open GiloDAM Data Folder", command=lambda: self._open_safely(app_data_dir()))
        file_menu.add_command(label="Clear Thumbnail Cache", command=self.clear_cache)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", accelerator="Alt+F4", command=self.close)
        menu.add_cascade(label="File", menu=file_menu)

        edit_menu = tk.Menu(menu, tearoff=False)
        edit_menu.add_command(label="Save Metadata", accelerator="Ctrl+S", command=self.save_metadata)
        edit_menu.add_command(label="Find", accelerator="Ctrl+F", command=lambda: self.search_entry.focus_set())
        menu.add_cascade(label="Edit", menu=edit_menu)

        view_menu = tk.Menu(menu, tearoff=False)
        view_menu.add_command(label="Refresh Catalog View", accelerator="F5", command=self._refresh_assets)
        view_menu.add_command(label="Slideshow Settings…", command=self.slideshow_settings)
        menu.add_cascade(label="View", menu=view_menu)

        help_menu = tk.Menu(menu, tearoff=False)
        help_menu.add_command(label="DAM Terms", command=self.show_terms)
        help_menu.add_command(label="About GiloDAM", command=self.show_about)
        menu.add_cascade(label="Help", menu=help_menu)
        self.root.configure(menu=menu)

    def _build_ui(self) -> None:
        top = ttk.Frame(self.root, padding=(12, 10))
        top.pack(fill=tk.X)
        ttk.Label(top, text="GiloDAM", style="Title.TLabel").pack(side=tk.LEFT)
        ttk.Label(top, text="  local • private • non-destructive", style="Subtle.TLabel").pack(side=tk.LEFT, pady=(5, 0))
        self.add_button = ttk.Button(top, text="Add Folder…", style="Primary.TButton", command=self.select_folder)
        self.add_button.pack(side=tk.RIGHT)

        search_bar = ttk.Frame(self.root, padding=(12, 0, 12, 10))
        search_bar.pack(fill=tk.X)
        ttk.Label(search_bar, text="Search").pack(side=tk.LEFT, padx=(0, 6))
        self.search_var = tk.StringVar()
        self.search_entry = ttk.Entry(search_bar, textvariable=self.search_var)
        self.search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.search_entry.bind("<KeyRelease>", self._schedule_search)
        self.type_var = tk.StringVar(value="all")
        self.type_filter = ttk.Combobox(
            search_bar,
            textvariable=self.type_var,
            values=("all", "image", "video", "audio", "document", "other"),
            state="readonly",
            width=12,
        )
        self.type_filter.pack(side=tk.LEFT, padx=(8, 0))
        self.type_filter.bind("<<ComboboxSelected>>", lambda _event: self._refresh_assets())
        ttk.Button(search_bar, text="Clear", command=self.clear_search).pack(side=tk.LEFT, padx=(6, 0))

        pane = ttk.Panedwindow(self.root, orient=tk.HORIZONTAL)
        pane.pack(fill=tk.BOTH, expand=True, padx=12)

        left = ttk.Frame(pane, padding=(0, 0, 8, 0), width=220)
        pane.add(left, weight=0)
        ttk.Label(left, text="Sources", font=("Segoe UI", 11, "bold")).pack(anchor=tk.W, pady=(0, 6))
        self.source_list = tk.Listbox(left, exportselection=False, activestyle="dotbox", width=26)
        self.source_list.pack(fill=tk.BOTH, expand=True)
        self.source_list.bind("<<ListboxSelect>>", lambda _event: self._refresh_assets())
        self.source_list.bind("<Double-1>", lambda _event: self.scan_selected_source())
        ttk.Button(left, text="Scan Selected Source", command=self.scan_selected_source).pack(fill=tk.X, pady=(6, 0))
        self.catalog_summary = ttk.Label(left, text="", style="Subtle.TLabel", justify=tk.LEFT, wraplength=210)
        self.catalog_summary.pack(fill=tk.X, pady=(10, 0))

        center = ttk.Frame(pane)
        pane.add(center, weight=3)
        columns = ("title", "type", "size", "status", "locations")
        self.asset_tree = ttk.Treeview(center, columns=columns, show="tree headings", selectmode="browse")
        self.asset_tree.heading("#0", text="File")
        self.asset_tree.heading("title", text="Title")
        self.asset_tree.heading("type", text="Type")
        self.asset_tree.heading("size", text="Size")
        self.asset_tree.heading("status", text="Status")
        self.asset_tree.heading("locations", text="Copies")
        self.asset_tree.column("#0", width=260, minwidth=180)
        self.asset_tree.column("title", width=180, minwidth=100)
        self.asset_tree.column("type", width=80, anchor=tk.CENTER)
        self.asset_tree.column("size", width=82, anchor=tk.E)
        self.asset_tree.column("status", width=90, anchor=tk.CENTER)
        self.asset_tree.column("locations", width=55, anchor=tk.CENTER)
        tree_y = ttk.Scrollbar(center, orient=tk.VERTICAL, command=self.asset_tree.yview)
        tree_x = ttk.Scrollbar(center, orient=tk.HORIZONTAL, command=self.asset_tree.xview)
        self.asset_tree.configure(yscrollcommand=tree_y.set, xscrollcommand=tree_x.set)
        self.asset_tree.grid(row=0, column=0, sticky="nsew")
        tree_y.grid(row=0, column=1, sticky="ns")
        tree_x.grid(row=1, column=0, sticky="ew")
        center.rowconfigure(0, weight=1)
        center.columnconfigure(0, weight=1)
        self.asset_tree.bind("<<TreeviewSelect>>", self._on_asset_select)
        self.asset_tree.bind("<Double-1>", lambda _event: self.open_original())

        right = ttk.Frame(pane, padding=(10, 0, 0, 0), width=430)
        pane.add(right, weight=2)
        self.inspector_heading = ttk.Label(right, text="Select an asset", font=("Segoe UI", 12, "bold"), wraplength=400)
        self.inspector_heading.pack(fill=tk.X, pady=(0, 6))
        self._build_preview(right)
        self._build_inspector_notebook(right)

        status = ttk.Frame(self.root, padding=(12, 8))
        status.pack(fill=tk.X)
        self.status_var = tk.StringVar()
        ttk.Label(status, textvariable=self.status_var).pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.progress = ttk.Progressbar(status, length=220, mode="determinate")
        self.progress.pack(side=tk.LEFT, padx=(8, 6))
        self.cancel_button = ttk.Button(status, text="Cancel", command=self.cancel_work, state=tk.DISABLED)
        self.cancel_button.pack(side=tk.LEFT)

    def _build_preview(self, parent: ttk.Frame) -> None:
        preview_frame = ttk.Frame(parent)
        preview_frame.pack(fill=tk.BOTH, expand=False)
        preview_frame.configure(height=320)
        preview_frame.pack_propagate(False)

        self.preview_stack = ttk.Frame(preview_frame)
        self.preview_stack.pack(fill=tk.BOTH, expand=True)
        self.preview_stack.rowconfigure(0, weight=1)
        self.preview_stack.columnconfigure(0, weight=1)

        canvas_frame = ttk.Frame(self.preview_stack)
        canvas_frame.grid(row=0, column=0, sticky="nsew")
        canvas_frame.rowconfigure(0, weight=1)
        canvas_frame.columnconfigure(0, weight=1)
        self.preview_canvas = tk.Canvas(canvas_frame, background="#1f2529", highlightthickness=0)
        canvas_x = ttk.Scrollbar(canvas_frame, orient=tk.HORIZONTAL, command=self.preview_canvas.xview)
        canvas_y = ttk.Scrollbar(canvas_frame, orient=tk.VERTICAL, command=self.preview_canvas.yview)
        self.preview_canvas.configure(xscrollcommand=canvas_x.set, yscrollcommand=canvas_y.set)
        self.preview_canvas.grid(row=0, column=0, sticky="nsew")
        canvas_y.grid(row=0, column=1, sticky="ns")
        canvas_x.grid(row=1, column=0, sticky="ew")
        self.preview_canvas.bind("<ButtonPress-1>", lambda event: self.preview_canvas.scan_mark(event.x, event.y))
        self.preview_canvas.bind("<B1-Motion>", lambda event: self.preview_canvas.scan_dragto(event.x, event.y, gain=1))
        self.preview_canvas.bind(
            "<Configure>",
            lambda _event: self._render_preview_image() if self.preview_source is not None and self.preview_mode == "fit" else None,
        )

        self.preview_text = tk.Text(
            self.preview_stack,
            wrap=tk.WORD,
            state=tk.DISABLED,
            background="#f7f8fa",
            foreground="#263238",
            padx=10,
            pady=10,
            relief=tk.FLAT,
        )
        self.preview_text.grid(row=0, column=0, sticky="nsew")
        self.canvas_frame = canvas_frame
        self.canvas_frame.tkraise()

        controls = ttk.Frame(parent, padding=(0, 5))
        controls.pack(fill=tk.X)
        ttk.Button(controls, text="◀", width=3, command=lambda: self.navigate(-1)).pack(side=tk.LEFT)
        self.play_button = ttk.Button(controls, text="Play", width=6, command=self.toggle_slideshow)
        self.play_button.pack(side=tk.LEFT, padx=3)
        ttk.Button(controls, text="▶", width=3, command=lambda: self.navigate(1)).pack(side=tk.LEFT)
        ttk.Separator(controls, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6)
        ttk.Button(controls, text="−", width=3, command=lambda: self.zoom_preview(0.8)).pack(side=tk.LEFT)
        ttk.Button(controls, text="Fit", width=4, command=self.fit_preview).pack(side=tk.LEFT, padx=2)
        ttk.Button(controls, text="100%", width=5, command=self.actual_size_preview).pack(side=tk.LEFT)
        ttk.Button(controls, text="+", width=3, command=lambda: self.zoom_preview(1.25)).pack(side=tk.LEFT, padx=(2, 0))
        ttk.Button(controls, text="Open Original", command=self.open_original).pack(side=tk.RIGHT)

    def _build_inspector_notebook(self, parent: ttk.Frame) -> None:
        notebook = ttk.Notebook(parent)
        notebook.pack(fill=tk.BOTH, expand=True)
        metadata_tab = ttk.Frame(notebook, padding=8)
        technical_tab = ttk.Frame(notebook, padding=8)
        notebook.add(metadata_tab, text="Metadata")
        notebook.add(technical_tab, text="Technical")

        metadata_tab.columnconfigure(1, weight=1)
        ttk.Label(metadata_tab, text="Title").grid(row=0, column=0, sticky="nw", padx=(0, 6), pady=3)
        self.title_var = tk.StringVar()
        self.title_entry = ttk.Entry(metadata_tab, textvariable=self.title_var)
        self.title_entry.grid(row=0, column=1, sticky="ew", pady=3)

        ttk.Label(metadata_tab, text="Description").grid(row=1, column=0, sticky="nw", padx=(0, 6), pady=3)
        self.description_text = tk.Text(metadata_tab, height=4, wrap=tk.WORD, font=("Segoe UI", 9))
        self.description_text.grid(row=1, column=1, sticky="ew", pady=3)

        ttk.Label(metadata_tab, text="Vocabulary").grid(row=2, column=0, sticky="w", padx=(0, 6), pady=3)
        self.vocabulary_var = tk.StringVar(value="General Creator")
        self.vocabulary_combo = ttk.Combobox(
            metadata_tab,
            textvariable=self.vocabulary_var,
            values=tuple(STARTER_VOCABULARIES),
            state="readonly",
        )
        self.vocabulary_combo.grid(row=2, column=1, sticky="ew", pady=3)
        self.vocabulary_combo.bind("<<ComboboxSelected>>", self._vocabulary_changed)

        ttk.Label(metadata_tab, text="Add keyword").grid(row=3, column=0, sticky="w", padx=(0, 6), pady=3)
        keyword_row = ttk.Frame(metadata_tab)
        keyword_row.grid(row=3, column=1, sticky="ew", pady=3)
        keyword_row.columnconfigure(0, weight=1)
        self.keyword_var = tk.StringVar()
        self.keyword_combo = ttk.Combobox(keyword_row, textvariable=self.keyword_var)
        self.keyword_combo.grid(row=0, column=0, sticky="ew")
        self.keyword_combo.bind("<Return>", lambda _event: self.add_keyword())
        ttk.Button(keyword_row, text="Add", command=self.add_keyword).grid(row=0, column=1, padx=(4, 0))

        ttk.Label(metadata_tab, text="Keywords").grid(row=4, column=0, sticky="nw", padx=(0, 6), pady=3)
        keyword_list_frame = ttk.Frame(metadata_tab)
        keyword_list_frame.grid(row=4, column=1, sticky="nsew", pady=3)
        keyword_list_frame.columnconfigure(0, weight=1)
        self.keyword_list = tk.Listbox(keyword_list_frame, height=5, exportselection=False)
        self.keyword_list.grid(row=0, column=0, sticky="nsew")
        ttk.Button(keyword_list_frame, text="Remove selected", command=self.remove_keyword).grid(row=1, column=0, sticky="e", pady=(3, 0))

        metadata_tab.rowconfigure(4, weight=1)
        button_row = ttk.Frame(metadata_tab)
        button_row.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        self.save_button = ttk.Button(button_row, text="Save to Catalog", style="Primary.TButton", command=self.save_metadata)
        self.save_button.pack(side=tk.LEFT)
        self.sidecar_button = ttk.Button(button_row, text="Sync JSON Sidecar", command=self.sync_sidecar)
        self.sidecar_button.pack(side=tk.LEFT, padx=(5, 0))
        self.relink_button = ttk.Button(button_row, text="Relink…", command=self.relink_selected)
        self.relink_button.pack(side=tk.RIGHT)

        ttk.Label(
            metadata_tab,
            text="Catalog edits save locally. A JSON sidecar is written only when you choose Sync JSON Sidecar.",
            style="Subtle.TLabel",
            wraplength=390,
            justify=tk.LEFT,
        ).grid(row=6, column=0, columnspan=2, sticky="w", pady=(8, 0))

        self.technical_text = tk.Text(
            technical_tab,
            wrap=tk.WORD,
            state=tk.DISABLED,
            font=("Consolas", 9),
            background="#f7f8fa",
            padx=8,
            pady=8,
        )
        self.technical_text.pack(fill=tk.BOTH, expand=True)

    def _bind_shortcuts(self) -> None:
        self.root.bind_all("<Control-o>", lambda _event: self.select_folder())
        self.root.bind_all("<Control-s>", lambda _event: self.save_metadata())
        self.root.bind_all("<Control-f>", lambda _event: self.search_entry.focus_set())
        self.root.bind_all("<F5>", lambda _event: self._refresh_assets())
        self.root.bind_all("<Alt-Left>", lambda _event: self.navigate(-1))
        self.root.bind_all("<Alt-Right>", lambda _event: self.navigate(1))
        self.root.bind_all("<Control-space>", lambda _event: self.toggle_slideshow())

    def _create_placeholders(self) -> None:
        for media_type in ("image", "video", "audio", "document", "other"):
            image = self.service.thumbnail_cache.placeholder(media_type, size=64)
            self.placeholder_images[media_type] = ImageTk.PhotoImage(image)

    def _schedule_search(self, _event: tk.Event[Any] | None = None) -> None:
        if self.search_after_id:
            self.root.after_cancel(self.search_after_id)
        self.search_after_id = self.root.after(250, self._refresh_assets)

    def clear_search(self) -> None:
        self.search_var.set("")
        self.type_var.set("all")
        self._refresh_assets()

    def _selected_source_id(self) -> str | None:
        selection = self.source_list.curselection()
        if not selection:
            return None
        index = int(selection[0])
        return self.source_ids[index] if index < len(self.source_ids) else None

    def _refresh_sources(self) -> None:
        current = self._selected_source_id()
        rows = self.service.database.source_rows()
        self.source_list.delete(0, tk.END)
        self.source_ids = [None]
        self.source_roots = {}
        self.source_list.insert(tk.END, "All Sources")
        selected_index = 0
        for index, row in enumerate(rows, start=1):
            self.source_ids.append(str(row["source_id"]))
            self.source_roots[str(row["source_id"])] = Path(str(row["root_locator"]))
            self.source_list.insert(tk.END, f"{row['display_name']}  ({row['asset_count']})")
            if row["source_id"] == current:
                selected_index = index
        self.source_list.selection_set(selected_index)
        counts = self.service.database.catalog_counts()
        self.catalog_summary.configure(
            text=(
                f"{counts.get('total', 0)} assets\n"
                f"{counts.get('image', 0)} images • {counts.get('video', 0)} video\n"
                f"{counts.get('audio', 0)} audio • {counts.get('document', 0)} documents\n"
                f"{counts.get('duplicate_locations', 0)} duplicate locations"
            )
        )

    def _refresh_assets(self) -> None:
        self.search_after_id = None
        source_id = self._selected_source_id()
        try:
            assets = self.service.assets(query=self.search_var.get(), media_type=self.type_var.get(), source_id=source_id)
        except Exception as exc:
            self._show_error("Search failed", exc)
            return
        self.assets = assets
        self.assets_by_id = {asset.asset_id: asset for asset in assets}
        self.asset_tree.delete(*self.asset_tree.get_children())
        self.tree_images.clear()
        for asset in assets:
            self.asset_tree.insert(
                "",
                tk.END,
                iid=asset.asset_id,
                text=asset.filename,
                image=self.placeholder_images.get(asset.media_type, self.placeholder_images["other"]),
                values=(asset.title, asset.media_type.title(), format_bytes(asset.file_size), asset.status.replace("_", " ").title(), asset.location_count),
            )
        self._set_status(f"Showing {len(assets)} asset{'s' if len(assets) != 1 else ''}.")
        self._begin_thumbnail_loading(assets[:300])

    def _begin_thumbnail_loading(self, assets: list[AssetView]) -> None:
        self.thumbnail_token += 1
        token = self.thumbnail_token

        def work() -> None:
            for asset in assets:
                if self.closing or token != self.thumbnail_token:
                    return
                path = self.service.thumbnail_for(asset, size=96)
                if path:
                    self.events.put(("thumbnail", token, asset.asset_id, path))

        threading.Thread(target=work, name="gilodam-thumbnails", daemon=True).start()

    def _apply_thumbnail(self, token: int, asset_id: str, path: Path) -> None:
        if token != self.thumbnail_token or not self.asset_tree.exists(asset_id):
            return
        try:
            with Image.open(path) as image:
                copy = image.copy()
            copy.thumbnail((64, 64), Image.Resampling.LANCZOS)
            photo = ImageTk.PhotoImage(copy)
            self.tree_images[asset_id] = photo
            self.asset_tree.item(asset_id, image=photo)
        except Exception:
            return

    def select_folder(self) -> None:
        if self.worker_thread and self.worker_thread.is_alive():
            messagebox.showinfo("GiloDAM is working", "Wait for the current operation to finish or choose Cancel.")
            return
        selected = filedialog.askdirectory(title="Select a folder to analyze — originals will remain in place")
        if not selected:
            return
        folder = Path(selected)

        self._analyze_folder(folder)

    def scan_selected_source(self) -> None:
        source_id = self._selected_source_id()
        if not source_id:
            messagebox.showinfo("Choose a source", "Select a source in the left panel, then choose Scan Selected Source.")
            return
        root = self.source_roots.get(source_id)
        if root is None:
            return
        if not root.exists():
            messagebox.showwarning(
                "Source is offline",
                f"The source folder is currently unavailable:\n\n{root}\n\nCatalog records and metadata remain safe.",
            )
            return
        self._analyze_folder(root)

    def _analyze_folder(self, folder: Path) -> None:
        if self.worker_thread and self.worker_thread.is_alive():
            messagebox.showinfo("GiloDAM is working", "Wait for the current operation to finish or choose Cancel.")
            return

        def task() -> AnalysisReport:
            return self.service.analyze(folder, cancel_event=self.cancel_event, progress=self._queue_scan_progress)

        self._start_worker("Analyzing folder read-only…", task, self._analysis_complete)

    def _queue_scan_progress(self, phase: str, current: int, total: int, message: str) -> None:
        self.events.put(("progress", current, total, message))

    def _queue_index_progress(self, current: int, total: int, message: str) -> None:
        self.events.put(("progress", current, total, message))

    def _analysis_complete(self, report: AnalysisReport) -> None:
        self._set_status(f"Analysis complete: {report.total_files} files found. Review before indexing.")
        ReviewDialog(self, report)

    def index_report(self, report: AnalysisReport, selected_paths: list[Path] | None = None) -> None:
        def task() -> dict[str, int]:
            return self.service.index_report(
                report,
                selected_paths=selected_paths,
                cancel_event=self.cancel_event,
                progress=self._queue_index_progress,
            )

        def complete(counts: dict[str, int]) -> None:
            self._refresh_sources()
            self._refresh_assets()
            self._set_status(
                f"Index complete: {counts['indexed']} indexed, {counts['created']} new, "
                f"{counts['reused']} matched, {counts['missing']} marked missing, {counts['failed']} failed."
            )
            messagebox.showinfo(
                "Index complete",
                f"Indexed: {counts['indexed']}\nNew assets: {counts['created']}\n"
                f"Matched existing assets: {counts['reused']}\nFailures: {counts['failed']}\n\n"
                f"Locations marked missing: {counts['missing']}\n\n"
                "Original files were not moved or changed.",
            )

        self._start_worker("Indexing selected media…", task, complete)

    def _start_worker(self, label: str, task: Callable[[], Any], on_success: Callable[[Any], None]) -> None:
        if self.worker_thread and self.worker_thread.is_alive():
            return
        self.cancel_event = threading.Event()
        self.add_button.configure(state=tk.DISABLED)
        self.cancel_button.configure(state=tk.NORMAL)
        self.progress.configure(mode="indeterminate")
        self.progress.start(12)
        self._set_status(label)

        def runner() -> None:
            try:
                result = task()
                self.events.put(("worker_done", on_success, result))
            except CancelRequested as exc:
                self.events.put(("worker_cancelled", str(exc)))
            except Exception as exc:
                self.events.put(("worker_error", exc, traceback.format_exc()))

        self.worker_thread = threading.Thread(target=runner, name="gilodam-worker", daemon=True)
        self.worker_thread.start()

    def _finish_worker(self) -> None:
        self.progress.stop()
        self.progress.configure(mode="determinate", maximum=100, value=0)
        self.cancel_button.configure(state=tk.DISABLED)
        self.add_button.configure(state=tk.NORMAL)
        self.worker_thread = None

    def cancel_work(self) -> None:
        self.cancel_event.set()
        self.cancel_button.configure(state=tk.DISABLED)
        self._set_status("Cancelling safely after the current file…")

    def _poll_events(self) -> None:
        if self.closing:
            return
        while True:
            try:
                event = self.events.get_nowait()
            except queue.Empty:
                break
            kind = event[0]
            if kind == "progress":
                _, current, total, message = event
                if total:
                    self.progress.stop()
                    self.progress.configure(mode="determinate", maximum=total, value=current)
                self._set_status(message)
            elif kind == "worker_done":
                _, callback, result = event
                self._finish_worker()
                callback(result)
            elif kind == "worker_cancelled":
                self._finish_worker()
                self._set_status("Operation cancelled safely. No originals were changed.")
            elif kind == "worker_error":
                _, error, detail = event
                self._finish_worker()
                self.logger.error("Background operation failed: %s\n%s", error, detail)
                self._show_error("GiloDAM could not complete the operation", error)
            elif kind == "thumbnail":
                _, token, asset_id, path = event
                self._apply_thumbnail(token, asset_id, path)
        self.root.after(80, self._poll_events)

    def _on_asset_select(self, _event: tk.Event[Any] | None = None) -> None:
        selection = self.asset_tree.selection()
        if not selection:
            return
        asset_id = selection[0]
        asset = self.service.asset(asset_id)
        if asset is None:
            return
        self.selected_asset = asset
        self.assets_by_id[asset_id] = asset
        self.inspector_heading.configure(text=asset.title or asset.filename)
        self.title_var.set(asset.title)
        self.description_text.delete("1.0", tk.END)
        self.description_text.insert("1.0", asset.description)
        self.vocabulary_var.set(asset.vocabulary_name if asset.vocabulary_name in STARTER_VOCABULARIES else "General Creator")
        self.keyword_values = list(asset.keywords)
        self._refresh_keyword_list()
        self._vocabulary_changed()
        self._show_technical(asset)
        self._show_preview(asset)

    def _show_technical(self, asset: AssetView) -> None:
        payload = {
            "asset_id": asset.asset_id,
            "content_hash": asset.content_hash,
            "status": asset.status,
            "location_count": asset.location_count,
            "path": asset.path,
            "mime_type": asset.mime_type,
            **asset.technical_metadata,
        }
        self.technical_text.configure(state=tk.NORMAL)
        self.technical_text.delete("1.0", tk.END)
        self.technical_text.insert("1.0", json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        self.technical_text.configure(state=tk.DISABLED)

    def _show_preview(self, asset: AssetView) -> None:
        self.preview_source = None
        path = Path(asset.path)
        if asset.media_type == "image" and path.exists():
            try:
                with Image.open(path) as image:
                    image.seek(0)
                    self.preview_source = ImageOps.exif_transpose(image).convert("RGBA")
                self.preview_mode = "fit"
                self.canvas_frame.tkraise()
                self._render_preview_image()
                return
            except Exception as exc:
                self._show_preview_text(f"Preview could not be generated.\n\n{exc}")
                return
        if asset.media_type == "document" and path.exists() and path.suffix.lower() in {".txt", ".md"}:
            try:
                with path.open("r", encoding="utf-8", errors="replace") as handle:
                    body = handle.read(50_000)
                suffix = "\n\n[Preview truncated]" if path.stat().st_size > 50_000 else ""
                self._show_preview_text(body + suffix)
            except OSError as exc:
                self._show_preview_text(f"Text preview failed.\n\n{exc}")
            return
        if asset.media_type == "document" and path.exists() and path.suffix.lower() == ".pdf":
            try:
                import fitz

                document = fitz.open(path)
                try:
                    page = document.load_page(0)
                    pixmap = page.get_pixmap(matrix=fitz.Matrix(1.4, 1.4), alpha=False)
                    self.preview_source = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples).convert("RGBA")
                finally:
                    document.close()
                self.preview_mode = "fit"
                self.canvas_frame.tkraise()
                self._render_preview_image()
                return
            except Exception as exc:
                self._show_preview_text(f"PDF preview is unavailable.\n\n{exc}")
                return
        if not path.exists():
            self._show_preview_text("Offline / Missing\n\nThe catalog and metadata are safe. Use Relink to reconnect the verified file.")
        elif asset.media_type in {"video", "audio"}:
            self._show_preview_text(
                f"{asset.media_type.title()} indexed successfully.\n\n"
                "Use Open Original to play it in your default desktop player. "
                "Embedded playback is listed as a known alpha limitation."
            )
        else:
            self._show_preview_text("No Preview Available\n\nTechnical and descriptive metadata remain available.")

    def _show_preview_text(self, text: str) -> None:
        self.preview_text.configure(state=tk.NORMAL)
        self.preview_text.delete("1.0", tk.END)
        self.preview_text.insert("1.0", text)
        self.preview_text.configure(state=tk.DISABLED)
        self.preview_text.tkraise()

    def _render_preview_image(self) -> None:
        if self.preview_source is None:
            return
        self.canvas_frame.tkraise()
        self.preview_canvas.update_idletasks()
        canvas_width = max(320, self.preview_canvas.winfo_width())
        canvas_height = max(240, self.preview_canvas.winfo_height())
        source_width, source_height = self.preview_source.size
        if self.preview_mode == "fit":
            scale = min(canvas_width / source_width, canvas_height / source_height, 1.0)
        elif self.preview_mode == "actual":
            scale = 1.0
        else:
            scale = self.preview_zoom
        width = max(1, int(source_width * scale))
        height = max(1, int(source_height * scale))
        displayed = self.preview_source.resize((width, height), Image.Resampling.LANCZOS) if (width, height) != self.preview_source.size else self.preview_source
        self.preview_photo = ImageTk.PhotoImage(displayed)
        self.preview_canvas.delete("all")
        x = max(canvas_width // 2, width // 2)
        y = max(canvas_height // 2, height // 2)
        self.preview_canvas.create_image(x, y, image=self.preview_photo, anchor=tk.CENTER)
        self.preview_canvas.configure(scrollregion=(0, 0, max(canvas_width, width), max(canvas_height, height)))
        self.preview_canvas.xview_moveto(0)
        self.preview_canvas.yview_moveto(0)

    def fit_preview(self) -> None:
        self.preview_mode = "fit"
        self._render_preview_image()

    def actual_size_preview(self) -> None:
        self.preview_mode = "actual"
        self._render_preview_image()

    def zoom_preview(self, multiplier: float) -> None:
        if self.preview_source is None:
            return
        if self.preview_mode == "fit":
            self.preview_zoom = min(
                self.preview_canvas.winfo_width() / self.preview_source.width,
                self.preview_canvas.winfo_height() / self.preview_source.height,
                1.0,
            )
        elif self.preview_mode == "actual":
            self.preview_zoom = 1.0
        self.preview_mode = "zoom"
        self.preview_zoom = min(4.0, max(0.05, self.preview_zoom * multiplier))
        self._render_preview_image()

    def navigate(self, direction: int, *, images_only: bool = False) -> None:
        if not self.assets:
            return
        candidates = [asset for asset in self.assets if not images_only or asset.media_type == "image"]
        if not candidates:
            return
        current_id = self.selected_asset.asset_id if self.selected_asset else ""
        index = next((i for i, asset in enumerate(candidates) if asset.asset_id == current_id), -1 if direction > 0 else 0)
        target = candidates[(index + direction) % len(candidates)]
        if self.asset_tree.exists(target.asset_id):
            self.asset_tree.selection_set(target.asset_id)
            self.asset_tree.focus(target.asset_id)
            self.asset_tree.see(target.asset_id)
            self._on_asset_select()

    def toggle_slideshow(self) -> None:
        if self.slideshow_running:
            self.stop_slideshow()
            return
        image_assets = [asset for asset in self.assets if asset.media_type == "image"]
        if not image_assets:
            messagebox.showinfo("No images", "The current result set does not contain images.")
            return
        self.slideshow_running = True
        self.play_button.configure(text="Pause")
        if not self.selected_asset or self.selected_asset.media_type != "image":
            target = image_assets[0]
            self.asset_tree.selection_set(target.asset_id)
            self._on_asset_select()
        self._schedule_slideshow_step()

    def _schedule_slideshow_step(self) -> None:
        if not self.slideshow_running:
            return
        interval = int(self.service.database.get_setting("slideshow_interval_seconds", 3))
        self.slideshow_after_id = self.root.after(max(1, interval) * 1000, self._slideshow_step)

    def _slideshow_step(self) -> None:
        self.navigate(1, images_only=True)
        self._schedule_slideshow_step()

    def stop_slideshow(self) -> None:
        self.slideshow_running = False
        self.play_button.configure(text="Play")
        if self.slideshow_after_id:
            self.root.after_cancel(self.slideshow_after_id)
            self.slideshow_after_id = None

    def slideshow_settings(self) -> None:
        dialog = tk.Toplevel(self.root)
        dialog.title("Slideshow Settings")
        dialog.transient(self.root)
        dialog.resizable(False, False)
        frame = ttk.Frame(dialog, padding=16)
        frame.pack(fill=tk.BOTH, expand=True)
        ttk.Label(frame, text="Seconds between images").grid(row=0, column=0, sticky="w", padx=(0, 8))
        value = tk.IntVar(value=int(self.service.database.get_setting("slideshow_interval_seconds", 3)))
        spin = ttk.Spinbox(frame, from_=1, to=30, textvariable=value, width=6)
        spin.grid(row=0, column=1)

        def save() -> None:
            self.service.database.set_setting("slideshow_interval_seconds", max(1, min(30, int(value.get()))))
            dialog.destroy()

        ttk.Button(frame, text="Save", command=save).grid(row=1, column=0, columnspan=2, sticky="e", pady=(12, 0))
        dialog.grab_set()

    def _vocabulary_changed(self, _event: tk.Event[Any] | None = None) -> None:
        values = vocabulary_values(self.vocabulary_var.get())
        self.keyword_combo.configure(values=values)
        self.keyword_var.set("")

    def add_keyword(self) -> None:
        value = self.keyword_var.get().strip()
        if not value:
            return
        if value.casefold() not in {item.casefold() for item in self.keyword_values}:
            self.keyword_values.append(value)
            self.keyword_values.sort(key=str.casefold)
        self.keyword_var.set("")
        self._refresh_keyword_list()

    def remove_keyword(self) -> None:
        selected = list(self.keyword_list.curselection())
        for index in reversed(selected):
            del self.keyword_values[index]
        self._refresh_keyword_list()

    def _refresh_keyword_list(self) -> None:
        self.keyword_list.delete(0, tk.END)
        for keyword in self.keyword_values:
            self.keyword_list.insert(tk.END, keyword)

    def save_metadata(self) -> bool:
        if not self.selected_asset:
            return False
        try:
            updated = self.service.save_metadata(
                self.selected_asset.asset_id,
                title=self.title_var.get(),
                description=self.description_text.get("1.0", "end-1c"),
                keywords=self.keyword_values,
                vocabulary_name=self.vocabulary_var.get(),
            )
            self.selected_asset = updated
            self.assets_by_id[updated.asset_id] = updated
            if self.asset_tree.exists(updated.asset_id):
                self.asset_tree.set(updated.asset_id, "title", updated.title)
            self.inspector_heading.configure(text=updated.title or updated.filename)
            self._set_status("Metadata saved to the local catalog and search index.")
            return True
        except Exception as exc:
            self._show_error("Metadata could not be saved", exc)
            return False

    def sync_sidecar(self) -> None:
        if not self.selected_asset:
            return
        if not self.save_metadata():
            return
        try:
            path = self.service.sync_sidecar(self.selected_asset.asset_id)
            self._set_status(f"JSON sidecar synced: {path.name}")
            messagebox.showinfo("Sidecar synced", f"Portable metadata was written to:\n\n{path}")
        except Exception as exc:
            self._show_error("The sidecar could not be written; catalog metadata is still safe", exc)

    def relink_selected(self) -> None:
        if not self.selected_asset:
            return
        selected = filedialog.askopenfilename(title="Choose the same file at its new location")
        if not selected:
            return
        try:
            updated = self.service.relink(self.selected_asset.asset_id, Path(selected))
            self.selected_asset = updated
            self._refresh_assets()
            if self.asset_tree.exists(updated.asset_id):
                self.asset_tree.selection_set(updated.asset_id)
                self._on_asset_select()
            self._set_status("Asset relinked after verified content-hash match.")
        except Exception as exc:
            self._show_error("Relink refused", exc)

    def open_original(self) -> None:
        if not self.selected_asset:
            return
        self._open_safely(Path(self.selected_asset.path))

    def _open_safely(self, path: Path) -> None:
        try:
            if not path.exists():
                raise FileNotFoundError(path)
            open_path(path)
        except Exception as exc:
            self._show_error("The item could not be opened", exc)

    def clear_cache(self) -> None:
        if not messagebox.askyesno(
            "Clear thumbnail cache?",
            "Cached previews will be removed and rebuilt on demand. Catalog metadata and original files will not be touched.",
        ):
            return
        try:
            count = self.service.clear_thumbnail_cache()
            self.tree_images.clear()
            self._refresh_assets()
            self._set_status(f"Cleared {count} cached preview file{'s' if count != 1 else ''}. Catalog and originals unchanged.")
        except Exception as exc:
            self._show_error("The cache could not be cleared", exc)

    def backup_catalog(self) -> None:
        default = backup_dir() / "GiloDAM-catalog-backup.sqlite3"
        selected = filedialog.asksaveasfilename(
            title="Back Up GiloDAM Catalog",
            initialdir=default.parent,
            initialfile=default.name,
            defaultextension=".sqlite3",
            filetypes=(("SQLite catalog", "*.sqlite3"), ("All files", "*.*")),
        )
        if not selected:
            return
        try:
            path = self.service.backup_catalog(Path(selected))
            self._set_status(f"Validated catalog backup saved: {path.name}")
            messagebox.showinfo("Backup complete", f"A validated catalog backup was saved to:\n\n{path}")
        except Exception as exc:
            self._show_error("Catalog backup failed", exc)

    def export_metadata(self, format_name: str) -> None:
        extension = f".{format_name}"
        selected = filedialog.asksaveasfilename(
            title="Export GiloDAM Metadata",
            initialfile=f"GiloDAM-metadata{extension}",
            defaultextension=extension,
            filetypes=((format_name.upper(), f"*{extension}"), ("All files", "*.*")),
        )
        if not selected:
            return
        try:
            path = self.service.export_json(Path(selected)) if format_name == "json" else self.service.export_csv(Path(selected))
            self._set_status(f"Metadata exported without original media: {path.name}")
            messagebox.showinfo("Export complete", f"Catalog metadata was exported to:\n\n{path}\n\nOriginal media was not bundled.")
        except Exception as exc:
            self._show_error("Metadata export failed", exc)

    def show_terms(self) -> None:
        messagebox.showinfo(
            "DAM terms in plain language",
            "Metadata: information that describes an asset.\n\n"
            "Controlled vocabulary: a starter list of consistent words; GiloDAM also allows your own terms.\n\n"
            "Sidecar: a small JSON file beside the original that carries portable metadata. It is written only when you choose Sync.\n\n"
            "Asset ID: the permanent catalog identity. A path is only a location.\n\n"
            "Duplicate: verified identical content. GiloDAM reports it and never auto-deletes it.",
        )

    def show_about(self) -> None:
        messagebox.showinfo(
            "About GiloDAM",
            f"GiloDAM {__version__}\n\n"
            "Windows-first local DAM vertical slice\n"
            "Offline catalog • SQLite • JSON sidecars\n\n"
            "No telemetry. No cloud account. Originals remain in place.",
        )

    def _set_status(self, message: str) -> None:
        self.status_var.set(message)

    def _show_error(self, title: str, error: Exception) -> None:
        self.logger.error("%s: %s", title, error)
        self._set_status(f"{title}: {error}")
        messagebox.showerror(title, f"{error}\n\nGiloDAM did not alter or remove your original media.")

    def close(self) -> None:
        if self.closing:
            return
        self.closing = True
        self.stop_slideshow()
        self.cancel_event.set()
        try:
            self.service.database.set_setting("window_geometry", self.root.geometry())
        except Exception:
            pass
        self.thumbnail_token += 1
        self.root.quit()
        self.root.destroy()


class ReviewDialog:
    def __init__(self, app: GiloDAMApp, report: AnalysisReport):
        self.app = app
        self.report = report
        self.window = tk.Toplevel(app.root)
        self.window.title("Review folder analysis")
        self.window.transient(app.root)
        self.window.geometry("720x560")
        self.window.minsize(620, 500)
        self.window.protocol("WM_DELETE_WINDOW", self.window.destroy)

        frame = ttk.Frame(self.window, padding=16)
        frame.pack(fill=tk.BOTH, expand=True)
        ttk.Label(frame, text="Review before indexing", font=("Segoe UI", 15, "bold")).pack(anchor=tk.W)
        ttk.Label(
            frame,
            text=f"{report.root}\nThis analysis was read-only. Nothing has been moved or written to the selected folder.",
            style="Subtle.TLabel",
            wraplength=660,
            justify=tk.LEFT,
        ).pack(anchor=tk.W, fill=tk.X, pady=(4, 12))

        grid = ttk.Frame(frame)
        grid.pack(fill=tk.X)
        metrics = [
            ("Total files", str(report.total_files)),
            ("Images", str(report.counts["image"])),
            ("Video", str(report.counts["video"])),
            ("Audio", str(report.counts["audio"])),
            ("Documents", str(report.counts["document"])),
            ("Other / unknown", str(report.counts["other"])),
            ("Duplicate candidates", str(report.duplicate_candidates)),
            ("Unreadable / read errors", str(report.unreadable_count)),
            ("Estimated catalog size", format_bytes(report.estimated_index_bytes) + " (estimate)"),
            ("Estimated cache size", format_bytes(report.estimated_cache_bytes) + " (estimate)"),
        ]
        for row, (label, value) in enumerate(metrics):
            ttk.Label(grid, text=label).grid(row=row, column=0, sticky="w", padx=(0, 18), pady=2)
            ttk.Label(grid, text=value, font=("Segoe UI", 9, "bold")).grid(row=row, column=1, sticky="w", pady=2)

        ttk.Label(frame, text="Warnings and read errors", font=("Segoe UI", 10, "bold")).pack(anchor=tk.W, pady=(14, 4))
        errors = [f"{candidate.path}: {candidate.error}" for candidate in report.unreadable] + report.scan_errors
        error_box = tk.Listbox(frame, height=6)
        error_box.pack(fill=tk.BOTH, expand=True)
        if errors:
            for item in errors:
                error_box.insert(tk.END, item)
        else:
            error_box.insert(tk.END, "No unreadable files or scan errors were found.")

        buttons = ttk.Frame(frame)
        buttons.pack(fill=tk.X, pady=(12, 0))
        ttk.Button(buttons, text="Cancel", command=self.window.destroy).pack(side=tk.RIGHT)
        ttk.Button(buttons, text="Review Selection…", command=self.review_selection).pack(side=tk.RIGHT, padx=6)
        ttk.Button(buttons, text="Index All", style="Primary.TButton", command=self.index_all).pack(side=tk.RIGHT)
        self.window.grab_set()

    def index_all(self) -> None:
        self.window.destroy()
        self.app.index_report(self.report)

    def review_selection(self) -> None:
        SelectionDialog(self)


class SelectionDialog:
    def __init__(self, review: ReviewDialog):
        self.review = review
        self.window = tk.Toplevel(review.window)
        self.window.title("Review Selection")
        self.window.transient(review.window)
        self.window.geometry("760x560")
        frame = ttk.Frame(self.window, padding=14)
        frame.pack(fill=tk.BOTH, expand=True)
        ttk.Label(
            frame,
            text="Select the files to index. Use Ctrl/Shift for a range; all files are selected initially.",
            wraplength=720,
        ).pack(anchor=tk.W, pady=(0, 8))
        list_frame = ttk.Frame(frame)
        list_frame.pack(fill=tk.BOTH, expand=True)
        self.listbox = tk.Listbox(list_frame, selectmode=tk.EXTENDED, exportselection=False)
        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=scrollbar.set)
        self.listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        for candidate in review.report.candidates:
            marker = " [read error]" if candidate.error else ""
            self.listbox.insert(tk.END, f"{candidate.path}{marker}")
        self.listbox.selection_set(0, tk.END)
        controls = ttk.Frame(frame)
        controls.pack(fill=tk.X, pady=(8, 0))
        ttk.Button(controls, text="Select All", command=lambda: self.listbox.selection_set(0, tk.END)).pack(side=tk.LEFT)
        ttk.Button(controls, text="Select None", command=lambda: self.listbox.selection_clear(0, tk.END)).pack(side=tk.LEFT, padx=5)
        ttk.Button(controls, text="Cancel", command=self.window.destroy).pack(side=tk.RIGHT)
        ttk.Button(controls, text="Index Selected", style="Primary.TButton", command=self.index_selected).pack(side=tk.RIGHT, padx=5)
        self.window.grab_set()

    def index_selected(self) -> None:
        indices = list(self.listbox.curselection())
        if not indices:
            messagebox.showinfo("Nothing selected", "Select at least one file or choose Cancel.", parent=self.window)
            return
        selected = [self.review.report.candidates[index].path for index in indices]
        self.window.destroy()
        self.review.window.destroy()
        self.review.app.index_report(self.review.report, selected)
