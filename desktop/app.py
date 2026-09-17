#!/usr/bin/env python3
"""Native local desktop application for the Academic OS."""
from __future__ import annotations

import argparse
import json
import os
import platform
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from desktop.model import (
    create_course_from_template,
    detect_local_timezone,
    discover_academic_folders,
    friendly_timezone_choices,
    friendly_timezone_label,
    load_dashboard,
    open_local_path,
    semester_suggestions,
    timezone_from_friendly_label,
)
from installer.core import initialize_installation, validate_manifest
from installer.migration import build_migration_plan, ensure_safe_text_target, execute_migration_plan, is_runtime_migration_source, safe_atomic_write_text, validate_migration_source, write_migration_plan
from installer.verify import verify_installation
from academia_os.config import load_config, runtime_directory, save_config
from academia_os.semester import resolve_current_semester
from academia_os.settings import config_diff, update_config

DEFAULT_PROFILE = Path(os.environ.get("ACADEMIC_OS_CONFIG", str(Path.home() / ".academic-os" / "profile.json"))).expanduser()


class AcademicOSApp(tk.Tk):
    BG = "#0e1625"
    SIDEBAR = "#0a111e"
    PANEL = "#151f31"
    PANEL_ALT = "#1c2a40"
    BORDER = "#2b3b55"
    TEXT = "#f5f7fb"
    MUTED = "#9aaac0"
    ACCENT = "#a7e3c8"
    ACCENT_STRONG = "#7dd3fc"
    SUCCESS = "#86efac"
    WARNING = "#fcd34d"
    DANGER = "#fca5a5"

    def __init__(self, profile_path: Path | None = None) -> None:
        super().__init__()
        self.profile_path = (profile_path or DEFAULT_PROFILE).expanduser().resolve()
        self.title("Academia OS — Your workspace")
        self.geometry("1180x800")
        self.minsize(980, 660)
        self.configure(bg=self.BG)
        self._configure_styles()
        self._body: ttk.Frame | None = None
        if self.profile_path.is_file():
            try:
                self.show_dashboard()
            except Exception as exc:
                self.show_setup(error=f"I found a profile, but could not load it yet: {exc}")
        else:
            self.show_welcome()

    def _configure_styles(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("App.TFrame", background=self.BG)
        style.configure("Sidebar.TFrame", background=self.SIDEBAR)
        style.configure("Panel.TFrame", background=self.PANEL)
        style.configure("AltPanel.TFrame", background=self.PANEL_ALT)
        style.configure("Card.TFrame", background=self.PANEL)
        style.configure("CardAlt.TFrame", background=self.PANEL_ALT)
        style.configure("Title.TLabel", background=self.BG, foreground=self.TEXT, font=("SF Pro Display", 28, "bold"))
        style.configure("PageTitle.TLabel", background=self.BG, foreground=self.TEXT, font=("SF Pro Display", 24, "bold"))
        style.configure("Heading.TLabel", background=self.BG, foreground=self.TEXT, font=("SF Pro Display", 17, "bold"))
        style.configure("PanelHeading.TLabel", background=self.PANEL, foreground=self.TEXT, font=("SF Pro Display", 15, "bold"))
        style.configure("CardHeading.TLabel", background=self.PANEL, foreground=self.TEXT, font=("SF Pro Display", 13, "bold"))
        style.configure("Body.TLabel", background=self.BG, foreground=self.TEXT, font=("SF Pro Text", 11))
        style.configure("Muted.TLabel", background=self.BG, foreground=self.MUTED, font=("SF Pro Text", 10))
        style.configure("Tiny.TLabel", background=self.BG, foreground=self.MUTED, font=("SF Pro Text", 9, "bold"))
        style.configure("PanelBody.TLabel", background=self.PANEL, foreground=self.TEXT, font=("SF Pro Text", 10))
        style.configure("PanelMuted.TLabel", background=self.PANEL, foreground=self.MUTED, font=("SF Pro Text", 9))
        style.configure("CardBody.TLabel", background=self.PANEL, foreground=self.TEXT, font=("SF Pro Text", 10))
        style.configure("CardMuted.TLabel", background=self.PANEL, foreground=self.MUTED, font=("SF Pro Text", 9))
        style.configure("SidebarTitle.TLabel", background=self.SIDEBAR, foreground=self.TEXT, font=("SF Pro Display", 15, "bold"))
        style.configure("SidebarMuted.TLabel", background=self.SIDEBAR, foreground=self.MUTED, font=("SF Pro Text", 9))
        style.configure("SidebarSection.TLabel", background=self.SIDEBAR, foreground="#6f819b", font=("SF Pro Text", 8, "bold"))
        style.configure("BrandMark.TLabel", background=self.ACCENT, foreground="#0b1b1a", font=("SF Pro Display", 17, "bold"), anchor="center")
        style.configure("MetricLabel.TLabel", background=self.PANEL, foreground=self.MUTED, font=("SF Pro Text", 9, "bold"))
        style.configure("MetricValue.TLabel", background=self.PANEL, foreground=self.TEXT, font=("SF Pro Display", 23, "bold"))
        style.configure("MetricCaption.TLabel", background=self.PANEL, foreground=self.MUTED, font=("SF Pro Text", 9))
        style.configure("Accent.TButton", background=self.ACCENT, foreground="#0b1b1a", padding=(15, 10), font=("SF Pro Text", 10, "bold"), borderwidth=0)
        style.map("Accent.TButton", background=[("active", "#c9f2df"), ("pressed", "#8bc9ad")], foreground=[("disabled", "#6c8178")])
        style.configure("Primary.TButton", background=self.ACCENT, foreground="#0b1b1a", padding=(15, 10), font=("SF Pro Text", 10, "bold"), borderwidth=0)
        style.map("Primary.TButton", background=[("active", "#c9f2df"), ("pressed", "#8bc9ad")])
        style.configure("Secondary.TButton", background=self.PANEL_ALT, foreground=self.TEXT, padding=(12, 9), font=("SF Pro Text", 10), borderwidth=0)
        style.map("Secondary.TButton", background=[("active", "#29405e"), ("pressed", "#243750")])
        style.configure("Ghost.TButton", background=self.BG, foreground=self.MUTED, padding=(10, 8), font=("SF Pro Text", 10), borderwidth=0)
        style.map("Ghost.TButton", background=[("active", self.PANEL_ALT)], foreground=[("active", self.TEXT)])
        style.configure("Nav.TButton", background=self.SIDEBAR, foreground=self.MUTED, anchor="w", padding=(12, 10), font=("SF Pro Text", 10), borderwidth=0)
        style.map("Nav.TButton", background=[("active", self.PANEL_ALT)], foreground=[("active", self.TEXT)])
        style.configure("NavSelected.TButton", background=self.PANEL_ALT, foreground=self.TEXT, anchor="w", padding=(12, 10), font=("SF Pro Text", 10, "bold"), borderwidth=0)
        style.map("NavSelected.TButton", background=[("active", "#29405e")])
        style.configure("TEntry", fieldbackground="#0b1321", foreground=self.TEXT, insertcolor=self.TEXT, padding=8)
        style.configure("TCombobox", fieldbackground="#0b1321", foreground=self.TEXT, padding=7)
        style.configure("TCheckbutton", background=self.PANEL, foreground=self.TEXT)
        style.map("TCheckbutton", background=[("active", self.PANEL)])
        style.configure("TRadiobutton", background=self.PANEL, foreground=self.TEXT)
        style.map("TRadiobutton", background=[("active", self.PANEL)])
        style.configure("TNotebook", background=self.BG, borderwidth=0)
        style.configure("TNotebook.Tab", background=self.PANEL_ALT, foreground=self.TEXT, padding=(12, 8))

    def _clear_body(self, padding: int = 28) -> ttk.Frame:
        if self._body is not None:
            self._body.destroy()
        self._body = ttk.Frame(self, style="App.TFrame", padding=padding)
        self._body.pack(fill="both", expand=True)
        return self._body

    def _header(self, parent: ttk.Frame, eyebrow: str, title: str, subtitle: str) -> None:
        ttk.Label(parent, text=eyebrow.upper(), style="Muted.TLabel").pack(anchor="w")
        ttk.Label(parent, text=title, style="Title.TLabel").pack(anchor="w", pady=(5, 3))
        ttk.Label(parent, text=subtitle, style="Muted.TLabel", wraplength=820).pack(anchor="w")

    def show_welcome(self) -> None:
        body = self._clear_body()
        self._header(body, "Local academic workspace", "Your University system, without the technical setup", "The app creates the folders, rules, safe automation, and dashboard locally. You choose what to connect; passwords and MFA codes never go into the app.")
        card = ttk.Frame(body, style="Panel.TFrame", padding=28)
        card.pack(fill="x", pady=(30, 18))
        ttk.Label(card, text="What happens next", style="PanelHeading.TLabel").pack(anchor="w")
        steps = [
            "1. We look for an existing University or academic folder.",
            "2. You choose where your local workspace should live.",
            "3. We detect your computer's time zone for you.",
            "4. We create your private dashboard and course template.",
            "5. You connect Google or your school portal later, on your own computer.",
        ]
        ttk.Label(card, text="\n".join(steps), style="PanelBody.TLabel", justify="left").pack(anchor="w", pady=(14, 0))
        buttons = ttk.Frame(body, style="App.TFrame")
        buttons.pack(anchor="w", pady=(8, 0))
        ttk.Button(buttons, text="Start setup", style="Accent.TButton", command=self.show_setup).pack(side="left")
        ttk.Button(buttons, text="I already have a setup", style="Secondary.TButton", command=self.choose_existing_profile).pack(side="left", padx=10)
        ttk.Label(body, text="You can always change your preferences later. The app will not overwrite existing academic files.", style="Muted.TLabel", wraplength=720).pack(anchor="w", pady=(26, 0))

    def choose_existing_profile(self) -> None:
        selected = filedialog.askopenfilename(title="Choose your Academic OS profile", filetypes=[("Academic OS profile", "profile.json"), ("JSON files", "*.json")])
        if not selected:
            return
        try:
            data = json.loads(Path(selected).read_text(encoding="utf-8"))
            validate_manifest(data)
            self.profile_path = Path(selected).expanduser().resolve()
            self.show_dashboard()
        except Exception as exc:
            messagebox.showerror("That profile could not be opened", str(exc))

    def show_setup(self, error: str = "") -> None:
        body = self._clear_body()
        self._header(body, "Simple setup", "Tell us about your study life", "You do not need to know technical folder paths or time-zone names. Use the buttons when you are unsure.")
        if error:
            ttk.Label(body, text=error, style="Muted.TLabel", wraplength=820).pack(anchor="w", pady=(10, 0))

        outer = ttk.Frame(body, style="App.TFrame")
        outer.pack(fill="both", expand=True, pady=(20, 0))
        left = ttk.Frame(outer, style="Panel.TFrame", padding=22)
        left.pack(side="left", fill="both", expand=True, padx=(0, 10))
        right = ttk.Frame(outer, style="Panel.TFrame", padding=22)
        right.pack(side="left", fill="both", expand=True, padx=(10, 0))

        self.editing_existing = self.profile_path.is_file()
        existing_config: dict[str, Any] | None = None
        if self.editing_existing:
            try:
                existing_config = load_config(self.profile_path)
            except Exception:
                existing_config = None
        self.setup_vars: dict[str, Any] = {
            "workspace_mode": tk.StringVar(value="existing" if self.editing_existing else "new"),
            "name": tk.StringVar(value=str((existing_config or {}).get("student", {}).get("name", ""))),
            "institution": tk.StringVar(value=str((existing_config or {}).get("student", {}).get("institution", ""))),
            "program": tk.StringVar(value=str((existing_config or {}).get("student", {}).get("program", ""))),
            "semester": tk.StringVar(value=str((existing_config or {}).get("academic", {}).get("semester", resolve_current_semester()))),
            "root": tk.StringVar(value=str((existing_config or {}).get("academic", {}).get("root_directory", Path.home() / "Desktop" / "University OS"))),
            "timezone": tk.StringVar(value=friendly_timezone_label(str((existing_config or {}).get("academic", {}).get("timezone", detect_local_timezone() or "UTC")))),
            "school_portal": tk.StringVar(value=str((existing_config or {}).get("academic", {}).get("school_portal", "Brightspace"))),
            "gmail": tk.BooleanVar(value=bool((existing_config or {}).get("integrations", {}).get("gmail", False))),
            "calendar": tk.BooleanVar(value=bool((existing_config or {}).get("integrations", {}).get("calendar", False))),
            "drive": tk.BooleanVar(value=bool((existing_config or {}).get("integrations", {}).get("drive", False))),
            "school_portal_enabled": tk.BooleanVar(value=bool((existing_config or {}).get("integrations", {}).get("school_portal", False))),
            "daily_brief": tk.BooleanVar(value=bool((existing_config or {}).get("automation", {}).get("daily_brief_enabled", True))),
            "inbox_processor": tk.BooleanVar(value=bool((existing_config or {}).get("automation", {}).get("inbox_processor_enabled", True))),
        }
        ttk.Label(left, text="Your profile", style="PanelHeading.TLabel").pack(anchor="w", pady=(0, 14))
        self._field(left, "Your name", self.setup_vars["name"])
        self._field(left, "University or school", self.setup_vars["institution"])
        self._field(left, "Program or faculty (optional)", self.setup_vars["program"])
        self._field(left, "Current semester", self.setup_vars["semester"], values=semester_suggestions())
        ttk.Label(left, text="Time zone", style="PanelBody.TLabel").pack(anchor="w", pady=(10, 4))
        zone_row = ttk.Frame(left, style="Panel.TFrame")
        zone_row.pack(fill="x")
        zone_box = ttk.Combobox(zone_row, textvariable=self.setup_vars["timezone"], values=friendly_timezone_choices(), state="normal")
        zone_box.pack(side="left", fill="x", expand=True)
        ttk.Button(zone_row, text="Use my computer", style="Secondary.TButton", command=self._detect_timezone).pack(side="left", padx=(8, 0))
        ttk.Label(left, text="If you are unsure, click “Use my computer.” You can also choose a familiar region from the list.", style="PanelMuted.TLabel", wraplength=390).pack(anchor="w", pady=(5, 8))

        ttk.Label(right, text="Your University workspace", style="PanelHeading.TLabel").pack(anchor="w", pady=(0, 7))
        ttk.Label(right, text="Start fresh in a new folder, or attach to an existing Academic OS folder. We never overwrite a messy folder automatically.", style="PanelBody.TLabel", wraplength=390).pack(anchor="w")
        mode_frame = ttk.Frame(right, style="Panel.TFrame")
        mode_frame.pack(fill="x", pady=(10, 4))
        ttk.Radiobutton(mode_frame, text="Create a brand-new workspace", variable=self.setup_vars["workspace_mode"], value="new", command=self._workspace_mode_changed).pack(anchor="w")
        ttk.Radiobutton(mode_frame, text="Use an existing workspace", variable=self.setup_vars["workspace_mode"], value="existing", command=self._workspace_mode_changed).pack(anchor="w", pady=(4, 0))
        folder_row = ttk.Frame(right, style="Panel.TFrame")
        folder_row.pack(fill="x", pady=(12, 5))
        ttk.Entry(folder_row, textvariable=self.setup_vars["root"]).pack(side="left", fill="x", expand=True)
        ttk.Button(folder_row, text="Browse", style="Secondary.TButton", command=self._browse_folder).pack(side="left", padx=(8, 0))
        ttk.Button(right, text="Find my existing University folder", style="Secondary.TButton", command=self._scan_folders).pack(anchor="w", pady=(2, 8))
        self.folder_list = tk.Listbox(right, height=5, background="#0b1321", foreground=self.TEXT, selectbackground="#2563eb", borderwidth=0, highlightthickness=0)
        self.folder_list.pack(fill="x", pady=(0, 5))
        self.folder_list.bind("<Double-Button-1>", self._choose_candidate)
        self.folder_results: list[Any] = []
        ttk.Label(right, text="For a fresh workspace, choose a new or empty location. For an existing workspace, double-click a detected Academic OS folder. Older messy material can be imported later through the migration screen.", style="PanelMuted.TLabel", wraplength=390).pack(anchor="w", pady=(2, 14))

        ttk.Label(right, text="Optional connections", style="PanelHeading.TLabel").pack(anchor="w", pady=(0, 8))
        for label, key in (("Gmail", "gmail"), ("Google Calendar", "calendar"), ("Google Drive", "drive"), ("School portal / browser handoff", "school_portal_enabled")):
            ttk.Checkbutton(right, text=label, variable=self.setup_vars[key]).pack(anchor="w")
        self._field(right, "School portal name", self.setup_vars["school_portal"])
        ttk.Label(right, text="These choices only prepare the workflow. You authorize each account later in your own browser.", style="PanelMuted.TLabel", wraplength=390).pack(anchor="w", pady=(0, 8))
        ttk.Checkbutton(right, text="Prepare the daily brief", variable=self.setup_vars["daily_brief"]).pack(anchor="w")
        ttk.Checkbutton(right, text="Prepare inbox monitoring", variable=self.setup_vars["inbox_processor"]).pack(anchor="w")

        footer = ttk.Frame(body, style="App.TFrame")
        footer.pack(fill="x", pady=(14, 0))
        ttk.Button(footer, text="Back", style="Secondary.TButton", command=self.show_welcome).pack(side="left")
        ttk.Button(footer, text="Save settings" if self.editing_existing else "Create my Academic OS", style="Accent.TButton", command=self._create_installation).pack(side="right")

    def _workspace_mode_changed(self) -> None:
        current = self.setup_vars["root"].get().strip()
        fresh_default = str(Path.home() / "Desktop" / "University OS")
        existing_default = str(Path.home() / "Desktop" / "University")
        if self.setup_vars["workspace_mode"].get() == "existing" and current == fresh_default:
            self.setup_vars["root"].set(existing_default)
        elif self.setup_vars["workspace_mode"].get() == "new" and current == existing_default:
            self.setup_vars["root"].set(fresh_default)

    def _field(self, parent: ttk.Frame, label: str, variable: tk.StringVar, values: list[str] | None = None) -> None:
        ttk.Label(parent, text=label, style="PanelBody.TLabel").pack(anchor="w", pady=(8, 4))
        if values is not None:
            ttk.Combobox(parent, textvariable=variable, values=values, state="normal").pack(fill="x")
        else:
            ttk.Entry(parent, textvariable=variable).pack(fill="x")

    def _detect_timezone(self) -> None:
        detected = detect_local_timezone()
        if detected:
            self.setup_vars["timezone"].set(friendly_timezone_label(detected))
            messagebox.showinfo("Time zone detected", f"I found your local time zone: {friendly_timezone_label(detected)}.")
        else:
            messagebox.showinfo("Choose a time zone", "I could not identify an IANA time-zone name automatically. Choose the city or region closest to you from the list.")

    def _browse_folder(self) -> None:
        selected = filedialog.askdirectory(title="Choose your University folder", mustexist=False)
        if selected:
            self.setup_vars["root"].set(selected)

    def _scan_folders(self) -> None:
        self.folder_list.delete(0, tk.END)
        self.folder_results = discover_academic_folders()
        if not self.folder_results:
            self.folder_list.insert(tk.END, "No likely folder found — choose Browse or keep the suggested path.")
            return
        for candidate in self.folder_results[:8]:
            self.folder_list.insert(tk.END, candidate.label)

    def _choose_candidate(self, _event: tk.Event | None = None) -> None:
        selected = self.folder_list.curselection()
        if not selected or not self.folder_results:
            return
        self.setup_vars["root"].set(str(self.folder_results[selected[0]].path))

    def _manifest_from_setup(self) -> dict[str, Any]:
        values = self.setup_vars
        default_root = Path.home() / "Desktop" / ("University OS" if self.setup_vars["workspace_mode"].get() == "new" else "University")
        root = str(Path(values["root"].get().strip() or str(default_root)).expanduser())
        timezone = timezone_from_friendly_label(values["timezone"].get().strip() or friendly_timezone_label(detect_local_timezone() or "UTC"))
        semester = values["semester"].get().strip() or resolve_current_semester(timezone_name=timezone)
        if semester.lower().startswith("current semester"):
            semester = resolve_current_semester(timezone_name=timezone)
        if self.editing_existing:
            existing = load_config(self.profile_path)
            candidate, changes = update_config(
                existing,
                {
                    "student.name": values["name"].get().strip(),
                    "student.institution": values["institution"].get().strip(),
                    "student.program": values["program"].get().strip() or "Not yet specified",
                    "academic.semester": semester,
                    "academic.timezone": timezone,
                    "academic.root_directory": root,
                    "academic.school_portal": values["school_portal"].get().strip() or "Not yet specified",
                    "integrations.gmail": bool(values["gmail"].get()),
                    "integrations.calendar": bool(values["calendar"].get()),
                    "integrations.drive": bool(values["drive"].get()),
                    "integrations.school_portal": bool(values["school_portal_enabled"].get()),
                    "automation.daily_brief_enabled": bool(values["daily_brief"].get()),
                    "automation.inbox_processor_enabled": bool(values["inbox_processor"].get()),
                },
                approve_structural=True,
            )
            self._settings_changes = changes
            return validate_manifest(candidate)
        return validate_manifest(
            {
                "schema_version": 2,
                "student": {
                    "name": values["name"].get().strip(),
                    "institution": values["institution"].get().strip(),
                    "program": values["program"].get().strip() or "Not yet specified",
                },
                "academic": {
                    "semester": semester,
                    "timezone": timezone,
                    "root_directory": root,
                    "school_portal": values["school_portal"].get().strip() or "Not yet specified",
                },
                "runtime": {"install_directory": str(Path.home() / ".academic-os")},
                "preferences": {"explanation_style": "detailed", "preferred_format": "markdown", "use_visuals": True, "study_method": "active recall"},
                "integrations": {
                    "gmail": bool(values["gmail"].get()), "calendar": bool(values["calendar"].get()), "drive": bool(values["drive"].get()), "school_portal": bool(values["school_portal_enabled"].get())
                },
                "automation": {"daily_brief_enabled": bool(values["daily_brief"].get()), "daily_brief_time": "09:00", "inbox_processor_enabled": bool(values["inbox_processor"].get()), "inbox_interval_minutes": 5},
                "acquisition": {"manual_import_enabled": True, "watched_folders": [], "browser_companion_enabled": False, "browser_access_enabled": False, "advanced_browser_enabled": False, "allowed_sites": []},
                "privacy": {"browser_access_enabled": False, "allowed_sites": [], "dedicated_profile_recommended": True},
                "browser": {"name": "auto", "user_data_dir": "", "profile_directory": "", "access_enabled": False, "allowed_sites": []},
                "agents": {"hermes": {"enabled": False, "profile": "default", "home_directory": ""}, "codex": {"enabled": False}, "claude": {"enabled": False}, "chatgpt": {"enabled": False}},
            }
        )

    def _create_installation(self) -> None:
        try:
            manifest = self._manifest_from_setup()
        except Exception as exc:
            messagebox.showerror("A little more information is needed", str(exc))
            return
        if self.editing_existing:
            try:
                previous = load_config(self.profile_path)
                changes = getattr(self, "_settings_changes", config_diff(previous, manifest))
                if not changes:
                    messagebox.showinfo("No changes", "Your settings are already up to date.")
                    return
                structural = [change for change in changes if change["structural"]]
                if structural:
                    summary = "\n".join(f"• {change['key']}: {change['before']} → {change['after']}" for change in structural)
                    if not messagebox.askyesno("Review workspace impact", f"These changes affect workspace structure or semester state:\n\n{summary}\n\nI will never delete or move your existing files. Continue and create only missing structure?", parent=self):
                        return
                    target_root = Path(manifest["academic"]["root_directory"]).expanduser()
                    if target_root.exists() and any(target_root.iterdir()) and not ((target_root / "ACADEMIC_OS_RULES.md").is_file() and (target_root / "COURSE_TEMPLATE").is_dir()):
                        messagebox.showwarning("Workspace not changed", "The requested workspace contains files but is not a recognized Academia OS workspace. Use the migration flow to bring material into a new location.", parent=self)
                        return
                save_config(self.profile_path, manifest)
                if structural:
                    target_root = Path(manifest["academic"]["root_directory"]).expanduser()
                    initialize_installation(manifest, template_root=REPO_ROOT / "templates" / "University", repo_root=REPO_ROOT, attach_existing=target_root.exists() and any(target_root.iterdir()))
                messagebox.showinfo("Settings saved", "Your settings were updated without rebuilding or overwriting your academic workspace.", parent=self)
                self.show_dashboard()
            except Exception as exc:
                messagebox.showerror("Settings were not saved", str(exc), parent=self)
            return
        root = Path(manifest["academic"]["root_directory"]).expanduser()
        requested_mode = self.setup_vars["workspace_mode"].get()
        attach_existing = requested_mode == "existing" and (root / "ACADEMIC_OS_RULES.md").is_file() and (root / "COURSE_TEMPLATE").is_dir()
        runtime_root = runtime_directory(manifest)
        legacy_candidates = [
            candidate
            for candidate in discover_academic_folders()
            if candidate.path != root.resolve() and not is_runtime_migration_source(candidate.path, runtime_root)
        ]
        if requested_mode == "existing" and root.exists() and any(root.iterdir()) and not attach_existing:
            messagebox.showwarning("I could not identify that workspace", "This folder contains files but does not look like an Academic OS folder. Choose the actual structured folder, or switch to Create a brand-new workspace and choose an empty location.")
            return
        if requested_mode == "new" and root.exists() and any(root.iterdir()):
            messagebox.showwarning("I will not overwrite this folder", "The new workspace location already contains files. Choose an empty location, or switch to Use an existing workspace if it is already structured as an Academic OS folder.")
            return
        try:
            initialize_installation(
                manifest,
                template_root=REPO_ROOT / "templates" / "University",
                repo_root=REPO_ROOT,
                attach_existing=attach_existing,
            )
            self.profile_path = runtime_directory(manifest) / "profile.json"
            messagebox.showinfo("Your Academia OS is ready", "The local workspace and dashboard were created. Hermes and browser access remain optional.")
            self.show_dashboard()
            if requested_mode == "new" and legacy_candidates:
                self.after(100, lambda: self._offer_migration(legacy_candidates))
        except Exception as exc:
            messagebox.showerror("Setup stopped safely", str(exc))

    def _card(self, parent: tk.Misc, *, padding: int = 18, accent: bool = False) -> tuple[tk.Frame, ttk.Frame]:
        border = self.ACCENT_STRONG if accent else self.BORDER
        outer = tk.Frame(parent, background=border, borderwidth=0, highlightthickness=0)
        inner = ttk.Frame(outer, style="Card.TFrame", padding=padding)
        inner.pack(fill="both", expand=True, padx=1, pady=1)
        return outer, inner

    def _pill(self, parent: tk.Misc, text: str, *, background: str, foreground: str) -> tk.Frame:
        pill = tk.Frame(parent, background=background, borderwidth=0, highlightthickness=0)
        tk.Label(pill, text=text, background=background, foreground=foreground, font=("SF Pro Text", 9, "bold"), padx=9, pady=4).pack()
        return pill

    def _nav_button(self, parent: ttk.Frame, text: str, command: Any, *, selected: bool = False) -> None:
        style = "NavSelected.TButton" if selected else "Nav.TButton"
        ttk.Button(parent, text=text, style=style, command=command).pack(fill="x", pady=2)

    def _build_sidebar(self, sidebar: ttk.Frame, dashboard: dict[str, Any]) -> None:
        sidebar.configure(width=226)
        sidebar.grid_propagate(False)
        brand = ttk.Frame(sidebar, style="Sidebar.TFrame")
        brand.pack(fill="x")
        ttk.Label(brand, text="A", style="BrandMark.TLabel", width=2).pack(side="left", padx=(0, 10), ipady=3)
        brand_copy = ttk.Frame(brand, style="Sidebar.TFrame")
        brand_copy.pack(side="left", fill="x", expand=True)
        ttk.Label(brand_copy, text="Academia OS", style="SidebarTitle.TLabel").pack(anchor="w")
        ttk.Label(brand_copy, text="PRIVATE STUDY SPACE", style="SidebarMuted.TLabel").pack(anchor="w", pady=(2, 0))

        tk.Frame(sidebar, background=self.BORDER, height=1, borderwidth=0).pack(fill="x", pady=(24, 22))
        ttk.Label(sidebar, text="WORKSPACE", style="SidebarSection.TLabel").pack(anchor="w", pady=(0, 8))
        self._nav_button(sidebar, "Overview", self.show_dashboard, selected=True)
        self._nav_button(sidebar, "Add a course", lambda: self._add_course(dashboard))
        self._nav_button(sidebar, "Import material", lambda: self._migration_dialog(dashboard))
        self._nav_button(sidebar, "Verify installation", self._run_verification)

        spacer = ttk.Frame(sidebar, style="Sidebar.TFrame")
        spacer.pack(fill="both", expand=True)
        ttk.Label(sidebar, text="QUICK ACCESS", style="SidebarSection.TLabel").pack(anchor="w", pady=(0, 8))
        self._nav_button(sidebar, "Open University folder", lambda: open_local_path(Path(dashboard["academic_root"])))
        self._nav_button(sidebar, "Today's dashboard", lambda: self._open_today(dashboard))
        if dashboard.get("hermes_enabled"):
            self._nav_button(sidebar, "Open optional Hermes", self._open_hermes)
        tk.Frame(sidebar, background=self.BORDER, height=1, borderwidth=0).pack(fill="x", pady=(22, 14))
        ttk.Label(sidebar, text=dashboard["institution"], style="SidebarMuted.TLabel", wraplength=185).pack(anchor="w")
        ttk.Label(sidebar, text=dashboard["student_name"], style="SidebarTitle.TLabel", wraplength=185).pack(anchor="w", pady=(4, 0))
        ttk.Button(sidebar, text="Settings", style="Ghost.TButton", command=self.show_setup).pack(fill="x", pady=(12, 0))

    def _metric_card(self, parent: ttk.Frame, title: str, value: str, caption: str, column: int) -> None:
        outer, card = self._card(parent, padding=15)
        outer.grid(row=0, column=column, sticky="nsew", padx=(0 if column == 0 else 6, 6 if column < 2 else 0))
        parent.columnconfigure(column, weight=1)
        ttk.Label(card, text=title.upper(), style="MetricLabel.TLabel").pack(anchor="w")
        ttk.Label(card, text=value, style="MetricValue.TLabel").pack(anchor="w", pady=(5, 1))
        ttk.Label(card, text=caption, style="MetricCaption.TLabel").pack(anchor="w")

    def show_dashboard(self) -> None:
        try:
            dashboard = load_dashboard(self.profile_path)
        except Exception as exc:
            self.show_setup(error=str(exc))
            return
        body = self._clear_body(padding=0)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        sidebar = ttk.Frame(body, style="Sidebar.TFrame", padding=(18, 22, 18, 18))
        sidebar.grid(row=0, column=0, sticky="nsew")
        self._build_sidebar(sidebar, dashboard)

        main = ttk.Frame(body, style="App.TFrame", padding=(30, 24, 30, 24))
        main.grid(row=0, column=1, sticky="nsew")
        main.columnconfigure(0, weight=1)
        main.rowconfigure(3, weight=1)

        header = ttk.Frame(main, style="App.TFrame")
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        header_left = ttk.Frame(header, style="App.TFrame")
        header_left.grid(row=0, column=0, sticky="w")
        ttk.Label(header_left, text="OVERVIEW  /  LOCAL WORKSPACE", style="Tiny.TLabel").pack(anchor="w")
        ttk.Label(header_left, text=f"Welcome back, {dashboard['student_name']}", style="PageTitle.TLabel").pack(anchor="w", pady=(5, 2))
        context = f"{dashboard['institution']}  ·  {dashboard['semester']}"
        if dashboard.get("program") and dashboard["program"] != "Not yet specified":
            context += f"  ·  {dashboard['program']}"
        ttk.Label(header_left, text=context, style="Muted.TLabel").pack(anchor="w")
        header_right = ttk.Frame(header, style="App.TFrame")
        header_right.grid(row=0, column=1, sticky="e", padx=(20, 0))
        self._pill(header_right, "●  Workspace ready" if dashboard["root_exists"] else "●  Setup needed", background="#173529" if dashboard["root_exists"] else "#3b2d19", foreground=self.SUCCESS if dashboard["root_exists"] else self.WARNING).pack(side="left", padx=(0, 10))
        ttk.Button(header_right, text="Refresh", style="Ghost.TButton", command=self.show_dashboard).pack(side="left")

        hero_outer, hero = self._card(main, padding=21, accent=True)
        hero_outer.grid(row=1, column=0, sticky="ew", pady=(22, 16))
        hero.columnconfigure(0, weight=1)
        hero_copy = ttk.Frame(hero, style="Card.TFrame")
        hero_copy.grid(row=0, column=0, sticky="w")
        ttk.Label(hero_copy, text="Your workspace is ready", style="CardHeading.TLabel").pack(anchor="w")
        ttk.Label(hero_copy, text="Keep today light: open your files, check what needs review, or bring older material into the new structure.", style="CardBody.TLabel", wraplength=520).pack(anchor="w", pady=(6, 8))
        ttk.Label(hero_copy, text=f"Local files stay on this computer  ·  {dashboard['timezone']}", style="CardMuted.TLabel").pack(anchor="w")
        hero_actions = ttk.Frame(hero, style="Card.TFrame")
        hero_actions.grid(row=0, column=1, sticky="e", padx=(20, 0))
        ttk.Button(hero_actions, text="Open University folder", style="Primary.TButton", command=lambda: open_local_path(Path(dashboard["academic_root"]))).pack(anchor="e")
        ttk.Button(hero_actions, text="Import older material", style="Secondary.TButton", command=lambda: self._migration_dialog(dashboard)).pack(anchor="e", pady=(8, 0))

        metrics = ttk.Frame(main, style="App.TFrame")
        metrics.grid(row=2, column=0, sticky="ew")
        self._metric_card(metrics, "Courses", str(dashboard["course_count"]), f"active in {dashboard['semester']}", 0)
        self._metric_card(metrics, "Inbox", str(dashboard["inbox_count"]), "items waiting for review", 1)
        self._metric_card(metrics, "Workspace", "Ready" if dashboard["root_exists"] else "Needs setup", "local structure status", 2)

        content = ttk.Frame(main, style="App.TFrame")
        content.grid(row=3, column=0, sticky="nsew", pady=(16, 0))
        content.columnconfigure(0, weight=3)
        content.columnconfigure(1, weight=2)
        content.rowconfigure(0, weight=1)

        today_outer, today = self._card(content, padding=18)
        today_outer.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        today.rowconfigure(2, weight=1)
        today.columnconfigure(0, weight=1)
        today_header = ttk.Frame(today, style="Card.TFrame")
        today_header.grid(row=0, column=0, sticky="ew")
        today_header.columnconfigure(0, weight=1)
        ttk.Label(today_header, text="Today", style="CardHeading.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Button(today_header, text="Open dashboard", style="Ghost.TButton", command=lambda: self._open_today(dashboard)).grid(row=0, column=1, sticky="e")
        ttk.Label(today, text="Your latest local brief and next focus area.", style="CardMuted.TLabel").grid(row=1, column=0, sticky="nw", pady=(4, 10))
        preview = dashboard["today_preview"] or "No daily brief has been generated yet. Your priorities will appear here after the first brief run."
        preview_box = tk.Text(today, height=8, background="#0d1727", foreground=self.TEXT, insertbackground=self.TEXT, borderwidth=0, highlightthickness=0, wrap="word", padx=13, pady=12, font=("SF Pro Text", 10), relief="flat")
        preview_box.insert("1.0", preview)
        preview_box.configure(state="disabled")
        preview_box.grid(row=2, column=0, sticky="nsew", pady=(0, 12))
        ttk.Label(today, text="Generated locally · not a source of truth", style="CardMuted.TLabel").grid(row=3, column=0, sticky="w")

        courses_outer, courses_card = self._card(content, padding=18)
        courses_outer.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        courses_card.rowconfigure(1, weight=1)
        courses_card.columnconfigure(0, weight=1)
        courses_header = ttk.Frame(courses_card, style="Card.TFrame")
        courses_header.grid(row=0, column=0, sticky="ew")
        courses_header.columnconfigure(0, weight=1)
        ttk.Label(courses_header, text="Courses", style="CardHeading.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Button(courses_header, text="Add", style="Ghost.TButton", command=lambda: self._add_course(dashboard)).grid(row=0, column=1, sticky="e")
        course_list = ttk.Frame(courses_card, style="Card.TFrame")
        course_list.grid(row=1, column=0, sticky="nsew", pady=(12, 0))
        if dashboard["courses"]:
            for course in dashboard["courses"][:6]:
                row = tk.Frame(course_list, background=self.PANEL, borderwidth=0, highlightthickness=0)
                row.pack(fill="x", pady=(0, 10))
                tk.Label(row, text="•", background=self.PANEL, foreground=self.ACCENT_STRONG, font=("SF Pro Display", 16, "bold"), width=2).pack(side="left", anchor="n")
                tk.Label(row, text=course, background=self.PANEL, foreground=self.TEXT, font=("SF Pro Text", 10), anchor="w", justify="left", wraplength=260).pack(side="left", fill="x", expand=True)
            if len(dashboard["courses"]) > 6:
                ttk.Label(course_list, text=f"+ {len(dashboard['courses']) - 6} more course folders", style="CardMuted.TLabel").pack(anchor="w", pady=(2, 0))
        else:
            ttk.Label(course_list, text="No courses yet", style="CardBody.TLabel").pack(anchor="w", pady=(6, 3))
            ttk.Label(course_list, text="Add a confirmed course to start organizing this semester.", style="CardMuted.TLabel", wraplength=240).pack(anchor="w")
        ttk.Label(courses_card, text="Only confirmed course folders appear here.", style="CardMuted.TLabel").grid(row=2, column=0, sticky="w", pady=(12, 0))

        footer = ttk.Frame(main, style="App.TFrame")
        footer.grid(row=4, column=0, sticky="ew", pady=(16, 0))
        footer.columnconfigure(0, weight=1)
        footer.columnconfigure(1, weight=1)
        health_outer, health = self._card(footer, padding=14)
        health_outer.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        health.columnconfigure(0, weight=1)
        ttk.Label(health, text="Workspace health", style="CardHeading.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(health, text="Your local structure is available and ready for review.", style="CardMuted.TLabel").grid(row=1, column=0, sticky="w", pady=(4, 0))
        ttk.Button(health, text="Run verification", style="Ghost.TButton", command=self._run_verification).grid(row=0, column=1, rowspan=2, sticky="e", padx=(12, 0))
        connections_outer, connections = self._card(footer, padding=14)
        connections_outer.grid(row=0, column=1, sticky="ew", padx=(8, 0))
        configured = [label for label, key in (("Gmail", "gmail"), ("Calendar", "calendar"), ("Drive", "drive"), ("School portal", "school_portal")) if dashboard["integrations"].get(key)]
        connection_state = "Prepared: " + ", ".join(configured) if configured else "No external accounts selected yet"
        ttk.Label(connections, text="Connections", style="CardHeading.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(connections, text=connection_state, style="CardMuted.TLabel", wraplength=270).grid(row=1, column=0, sticky="w", pady=(4, 0))
        ttk.Button(connections, text="Settings", style="Ghost.TButton", command=self.show_setup).grid(row=0, column=1, rowspan=2, sticky="e", padx=(12, 0))

    def _stat_card(self, parent: ttk.Frame, title: str, value: str, caption: str, column: int) -> None:
        card = ttk.Frame(parent, style="Panel.TFrame", padding=16)
        card.grid(row=0, column=column, sticky="nsew", padx=6)
        parent.columnconfigure(column, weight=1)
        ttk.Label(card, text=title.upper(), style="PanelMuted.TLabel").pack(anchor="w")
        ttk.Label(card, text=value, style="PanelHeading.TLabel").pack(anchor="w", pady=(6, 1))
        ttk.Label(card, text=caption, style="PanelMuted.TLabel").pack(anchor="w")

    def _open_today(self, dashboard: dict[str, Any]) -> None:
        path = Path(dashboard["academic_root"]) / dashboard["semester"] / "TODAY.md"
        if path.is_file():
            open_local_path(path)
        else:
            messagebox.showinfo("No dashboard yet", "The daily dashboard will appear after the first daily brief run.")

    def _run_verification(self) -> None:
        result = verify_installation(self.profile_path)
        if result["status"] == "pass":
            messagebox.showinfo("Verification passed", f"The local installation is healthy.\n\nChecked: {result['checked_count']} items")
        else:
            messagebox.showwarning("Review needed", "\n".join(result["failures"]))

    def _add_course(self, dashboard: dict[str, Any]) -> None:
        dialog = tk.Toplevel(self)
        dialog.title("Add a course")
        dialog.configure(bg=self.BG)
        dialog.resizable(False, False)
        frame = ttk.Frame(dialog, style="Panel.TFrame", padding=20)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Add a confirmed course", style="PanelHeading.TLabel").pack(anchor="w")
        ttk.Label(frame, text="Use the course code and title from the syllabus or official course page.", style="PanelMuted.TLabel", wraplength=360).pack(anchor="w", pady=(4, 12))
        code = tk.StringVar()
        title = tk.StringVar()
        self._field(frame, "Course code", code)
        self._field(frame, "Course title", title)

        def create() -> None:
            try:
                manifest = json.loads(self.profile_path.read_text(encoding="utf-8"))
                root = Path(dashboard["academic_root"])
                create_course_from_template(root, dashboard["semester"], code.get(), title.get(), root / "COURSE_TEMPLATE", manifest)
                dialog.destroy()
                self.show_dashboard()
            except Exception as exc:
                messagebox.showerror("Course not created", str(exc), parent=dialog)

        ttk.Button(frame, text="Create course folder", style="Accent.TButton", command=create).pack(anchor="e", pady=(16, 0))
        dialog.transient(self)
        dialog.grab_set()

    def _offer_migration(self, candidates: list[Any]) -> None:
        names = "\n".join(f"• {candidate.path}" for candidate in candidates[:3])
        if messagebox.askyesno("I found older University material", f"I found likely older academic folder(s):\n\n{names}\n\nWould you like to review what can be brought into your new workspace? The old folders will remain untouched unless you explicitly choose Move."):
            self._migration_dialog(load_dashboard(self.profile_path))

    def _migration_dialog(self, dashboard: dict[str, Any]) -> None:
        dialog = tk.Toplevel(self)
        dialog.title("Bring over older University material")
        dialog.configure(bg=self.BG)
        dialog.geometry("940x720")
        dialog.minsize(780, 560)
        frame = ttk.Frame(dialog, style="Panel.TFrame", padding=20)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Migration phase", style="PanelHeading.TLabel").pack(anchor="w")
        ttk.Label(frame, text="Your old folder stays untouched unless you explicitly choose Move. The app will show every proposed destination before importing anything.", style="PanelMuted.TLabel", wraplength=820).pack(anchor="w", pady=(4, 14))

        source_var = tk.StringVar()
        source_row = ttk.Frame(frame, style="Panel.TFrame")
        source_row.pack(fill="x")
        ttk.Label(source_row, text="Old University folder", style="PanelBody.TLabel").pack(side="left", padx=(0, 8))
        ttk.Entry(source_row, textvariable=source_var).pack(side="left", fill="x", expand=True)
        ttk.Button(source_row, text="Browse", style="Secondary.TButton", command=lambda: self._choose_migration_source(source_var)).pack(side="left", padx=(8, 0))

        source_candidates_list = tk.Listbox(frame, height=3, background="#0b1321", foreground=self.TEXT, selectbackground="#2563eb", borderwidth=0, highlightthickness=0)
        source_candidates_list.pack(fill="x", pady=(8, 4))
        source_candidates: list[Any] = []

        def find_sources() -> None:
            source_candidates_list.delete(0, tk.END)
            current = Path(dashboard["academic_root"]).expanduser().resolve()
            runtime_root = Path(dashboard["install_root"]).expanduser().resolve()
            source_candidates[:] = [
                candidate
                for candidate in discover_academic_folders()
                if candidate.path != current and not is_runtime_migration_source(candidate.path, runtime_root)
            ]
            if not source_candidates:
                source_candidates_list.insert(tk.END, "No likely older folder found — use Browse to choose one.")
            else:
                for candidate in source_candidates[:8]:
                    source_candidates_list.insert(tk.END, candidate.label)

        def choose_source(_event: tk.Event | None = None) -> None:
            selected = source_candidates_list.curselection()
            if selected and selected[0] < len(source_candidates):
                source_var.set(str(source_candidates[selected[0]].path))

        source_candidates_list.bind("<Double-Button-1>", choose_source)
        ttk.Button(frame, text="Find likely older folders", style="Secondary.TButton", command=find_sources).pack(anchor="w", pady=(0, 10))

        plan_status = tk.StringVar(value="Choose an old folder, then click Scan and preview.")
        ttk.Label(frame, textvariable=plan_status, style="PanelMuted.TLabel", wraplength=820).pack(anchor="w", pady=(0, 8))
        migration_list = tk.Listbox(frame, selectmode=tk.EXTENDED, height=15, background="#0b1321", foreground=self.TEXT, selectbackground="#2563eb", borderwidth=0, highlightthickness=0)
        migration_list.pack(fill="both", expand=True, pady=(0, 8))
        plan_ref: dict[str, Any] = {"plan": None, "paths": {}}

        def scan() -> None:
            try:
                source = validate_migration_source(
                    Path(source_var.get().strip()).expanduser(),
                    Path(dashboard["install_root"]).expanduser(),
                )
                plan = build_migration_plan(source, Path(dashboard["academic_root"]), dashboard["semester"])
                paths = write_migration_plan(plan, Path(dashboard["install_root"]) / "migration")
                plan_ref["plan"] = plan
                plan_ref["paths"] = paths
                migration_list.delete(0, tk.END)
                for item in plan.items:
                    migration_list.insert(tk.END, f"{item.relative_path}  →  {item.destination.relative_to(plan.academic_root)}")
                if plan.items:
                    migration_list.selection_set(0, tk.END)
                plan_status.set(f"Found {len(plan.items)} file(s). Select only what you want, then copy or move. The review plan is saved in {paths['markdown']}.")
            except Exception as exc:
                messagebox.showerror("Migration scan stopped", str(exc), parent=dialog)

        def select_all() -> None:
            if migration_list.size():
                migration_list.selection_set(0, tk.END)

        def clear_selection() -> None:
            migration_list.selection_clear(0, tk.END)

        def open_plan() -> None:
            path = plan_ref["paths"].get("markdown")
            if path:
                open_local_path(path)
            else:
                messagebox.showinfo("Scan first", "Run a scan before opening the AI-review plan.", parent=dialog)

        def execute(mode: str) -> None:
            plan = plan_ref.get("plan")
            if plan is None:
                messagebox.showinfo("Scan first", "Choose an old folder and scan it before importing.", parent=dialog)
                return
            validate_migration_source(plan.source_root, Path(dashboard["install_root"]).expanduser())
            selected_indexes = migration_list.curselection()
            selected_items = [plan.items[index] for index in selected_indexes]
            if not selected_items:
                messagebox.showinfo("Nothing selected", "Select at least one file, or close this window to leave the old folder unchanged.", parent=dialog)
                return
            if mode == "move" and not messagebox.askyesno("Move selected originals?", "This will remove only the selected original files after hash verification. Copy is safer and recommended. Continue?", parent=dialog):
                return
            report_dir = Path(dashboard["install_root"]) / "migration"
            report_path = report_dir / "migration-report.json"
            ensure_safe_text_target(report_path)
            if os.path.lexists(report_dir) and report_dir.is_symlink():
                raise ValueError(f"refusing to use symlink migration directory: {report_dir}")
            if os.path.lexists(report_dir) and not report_dir.is_dir():
                raise ValueError(f"migration output directory is not a folder: {report_dir}")
            report_dir.mkdir(parents=True, exist_ok=True)
            ensure_safe_text_target(report_path)
            result = execute_migration_plan(plan, items=selected_items, mode=mode)
            safe_atomic_write_text(report_path, json.dumps(result, indent=2, ensure_ascii=False) + "\n")
            if result["failed"]:
                messagebox.showwarning("Migration needs review", f"Completed with {result['failed']} failure(s). See migration-report.json.", parent=dialog)
            else:
                count = result["moved"] if mode == "move" else result["copied"]
                messagebox.showinfo("Migration complete", f"{count} selected file(s) were {mode}d into the structured workspace. The original folder was {'changed only for verified files' if mode == 'move' else 'left intact'}.", parent=dialog)
            dialog.destroy()
            self.show_dashboard()

        controls = ttk.Frame(frame, style="Panel.TFrame")
        controls.pack(fill="x", pady=(2, 0))
        ttk.Button(controls, text="Scan and preview", style="Accent.TButton", command=scan).pack(side="left")
        ttk.Button(controls, text="Select all", style="Secondary.TButton", command=select_all).pack(side="left", padx=(8, 0))
        ttk.Button(controls, text="Clear selection", style="Secondary.TButton", command=clear_selection).pack(side="left", padx=(8, 0))
        ttk.Button(controls, text="Open plan for AI review", style="Secondary.TButton", command=open_plan).pack(side="left", padx=(8, 0))
        ttk.Button(controls, text="Copy selected safely", style="Accent.TButton", command=lambda: execute("copy")).pack(side="right")
        ttk.Button(controls, text="Move selected", style="Secondary.TButton", command=lambda: execute("move")).pack(side="right", padx=(0, 8))
        ttk.Button(controls, text="Leave old folder unchanged", style="Secondary.TButton", command=dialog.destroy).pack(side="right", padx=(0, 8))
        dialog.transient(self)
        dialog.grab_set()

    def _choose_migration_source(self, variable: tk.StringVar) -> None:
        selected = filedialog.askdirectory(title="Choose the older University folder", mustexist=True)
        if selected:
            variable.set(selected)

    def _open_hermes(self) -> None:
        if platform.system() == "Darwin":
            command = f"cd {shlex.quote(str(REPO_ROOT))} && hermes"
            escaped = command.replace("\\", "\\\\").replace('"', '\\"')
            subprocess.Popen(["osascript", "-e", f'tell application "Terminal" to do script "{escaped}"'])
        else:
            subprocess.Popen(["hermes"])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, default=None)
    parser.add_argument("--print-dashboard", action="store_true", help="Print dashboard JSON without opening a window")
    args = parser.parse_args()
    profile = (args.profile or DEFAULT_PROFILE).expanduser().resolve()
    if args.print_dashboard:
        print(json.dumps(load_dashboard(profile), indent=2, ensure_ascii=False))
        return 0
    app = AcademicOSApp(profile)
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
