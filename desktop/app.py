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
import textwrap
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
from installer.migration import build_migration_plan, execute_migration_plan, write_migration_plan
from installer.verify import verify_installation

DEFAULT_PROFILE = Path(os.environ.get("ACADEMIC_OS_CONFIG", str(Path.home() / ".academic-os" / "profile.json"))).expanduser()


class AcademicOSApp(tk.Tk):
    BG = "#101827"
    PANEL = "#172235"
    PANEL_ALT = "#1d2b42"
    TEXT = "#f4f7fb"
    MUTED = "#a9b7ca"
    ACCENT = "#7dd3fc"
    SUCCESS = "#86efac"
    WARNING = "#fcd34d"

    def __init__(self, profile_path: Path | None = None) -> None:
        super().__init__()
        self.profile_path = (profile_path or DEFAULT_PROFILE).expanduser().resolve()
        self.title("Academic OS")
        self.geometry("1100x760")
        self.minsize(900, 620)
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
        style.configure("Panel.TFrame", background=self.PANEL)
        style.configure("AltPanel.TFrame", background=self.PANEL_ALT)
        style.configure("Title.TLabel", background=self.BG, foreground=self.TEXT, font=("SF Pro Display", 28, "bold"))
        style.configure("Heading.TLabel", background=self.BG, foreground=self.TEXT, font=("SF Pro Display", 17, "bold"))
        style.configure("PanelHeading.TLabel", background=self.PANEL, foreground=self.TEXT, font=("SF Pro Display", 15, "bold"))
        style.configure("Body.TLabel", background=self.BG, foreground=self.TEXT, font=("SF Pro Text", 11))
        style.configure("Muted.TLabel", background=self.BG, foreground=self.MUTED, font=("SF Pro Text", 10))
        style.configure("PanelBody.TLabel", background=self.PANEL, foreground=self.TEXT, font=("SF Pro Text", 10))
        style.configure("PanelMuted.TLabel", background=self.PANEL, foreground=self.MUTED, font=("SF Pro Text", 9))
        style.configure("Accent.TButton", background=self.ACCENT, foreground="#062033", padding=(14, 9), font=("SF Pro Text", 10, "bold"))
        style.map("Accent.TButton", background=[("active", "#bae6fd")])
        style.configure("Secondary.TButton", background=self.PANEL_ALT, foreground=self.TEXT, padding=(12, 8))
        style.configure("TEntry", fieldbackground="#0b1321", foreground=self.TEXT, insertcolor=self.TEXT, padding=7)
        style.configure("TCombobox", fieldbackground="#0b1321", foreground=self.TEXT, padding=6)
        style.configure("TCheckbutton", background=self.PANEL, foreground=self.TEXT)
        style.map("TCheckbutton", background=[("active", self.PANEL)])
        style.configure("TNotebook", background=self.BG, borderwidth=0)
        style.configure("TNotebook.Tab", background=self.PANEL_ALT, foreground=self.TEXT, padding=(12, 8))

    def _clear_body(self) -> ttk.Frame:
        if self._body is not None:
            self._body.destroy()
        self._body = ttk.Frame(self, style="App.TFrame", padding=28)
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

        self.setup_vars: dict[str, Any] = {
            "workspace_mode": tk.StringVar(value="new"),
            "name": tk.StringVar(),
            "institution": tk.StringVar(),
            "program": tk.StringVar(),
            "semester": tk.StringVar(value=semester_suggestions()[0]),
            "root": tk.StringVar(value=str(Path.home() / "Desktop" / "University OS")),
            "timezone": tk.StringVar(value=friendly_timezone_label(detect_local_timezone() or "UTC")),
            "school_portal": tk.StringVar(value="Brightspace"),
            "gmail": tk.BooleanVar(value=False),
            "calendar": tk.BooleanVar(value=False),
            "drive": tk.BooleanVar(value=False),
            "school_portal_enabled": tk.BooleanVar(value=False),
            "daily_brief": tk.BooleanVar(value=True),
            "inbox_processor": tk.BooleanVar(value=True),
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
        ttk.Button(footer, text="Create my Academic OS", style="Accent.TButton", command=self._create_installation).pack(side="right")

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
        return validate_manifest(
            {
                "schema_version": 1,
                "student": {
                    "name": values["name"].get().strip(),
                    "institution": values["institution"].get().strip(),
                    "program": values["program"].get().strip() or "Not yet specified",
                },
                "academic": {
                    "semester": values["semester"].get().strip() or semester_suggestions()[0],
                    "timezone": timezone_from_friendly_label(values["timezone"].get().strip() or friendly_timezone_label(detect_local_timezone() or "UTC")),
                    "root_directory": root,
                    "school_portal": values["school_portal"].get().strip() or "Not yet specified",
                },
                "preferences": {
                    "explanation_style": "detailed",
                    "preferred_format": "markdown",
                    "use_visuals": True,
                    "study_method": "active recall",
                },
                "integrations": {
                    "gmail": bool(values["gmail"].get()),
                    "calendar": bool(values["calendar"].get()),
                    "drive": bool(values["drive"].get()),
                    "school_portal": bool(values["school_portal_enabled"].get()),
                },
                "automation": {
                    "daily_brief_enabled": bool(values["daily_brief"].get()),
                    "daily_brief_time": "09:00",
                    "inbox_processor_enabled": bool(values["inbox_processor"].get()),
                    "inbox_interval_minutes": 5,
                },
                "browser": {"name": "auto", "user_data_dir": "", "profile_directory": ""},
                "hermes": {
                    "home_directory": str(Path.home() / ".hermes"),
                    "profile": "default",
                    "install_directory": str(Path.home() / ".academic-os"),
                },
            }
        )

    def _create_installation(self) -> None:
        try:
            manifest = self._manifest_from_setup()
        except Exception as exc:
            messagebox.showerror("A little more information is needed", str(exc))
            return
        root = Path(manifest["academic"]["root_directory"]).expanduser()
        requested_mode = self.setup_vars["workspace_mode"].get()
        attach_existing = requested_mode == "existing" and (root / "ACADEMIC_OS_RULES.md").is_file() and (root / "COURSE_TEMPLATE").is_dir()
        legacy_candidates = [candidate for candidate in discover_academic_folders() if candidate.path != root.resolve()]
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
            self.profile_path = Path(manifest["hermes"]["install_directory"]).expanduser() / "profile.json"
            messagebox.showinfo("Your Academic OS is ready", "The local folder and dashboard were created. The next screen shows what is ready and what still needs your account authorization.")
            self.show_dashboard()
            if requested_mode == "new" and legacy_candidates:
                self.after(100, lambda: self._offer_migration(legacy_candidates))
        except Exception as exc:
            messagebox.showerror("Setup stopped safely", str(exc))

    def show_dashboard(self) -> None:
        try:
            dashboard = load_dashboard(self.profile_path)
        except Exception as exc:
            self.show_setup(error=str(exc))
            return
        body = self._clear_body()
        top = ttk.Frame(body, style="App.TFrame")
        top.pack(fill="x")
        self._header(top, "Your local workspace", f"Welcome, {dashboard['student_name']}", f"{dashboard['institution']} · {dashboard['semester']} · {dashboard['timezone']}")
        actions = ttk.Frame(top, style="App.TFrame")
        actions.pack(anchor="e", pady=(10, 0))
        ttk.Button(actions, text="Refresh", style="Secondary.TButton", command=self.show_dashboard).pack(side="left", padx=4)
        ttk.Button(actions, text="Settings", style="Secondary.TButton", command=self.show_setup).pack(side="left", padx=4)
        ttk.Button(actions, text="Open Hermes", style="Secondary.TButton", command=self._open_hermes).pack(side="left", padx=4)

        stats = ttk.Frame(body, style="App.TFrame")
        stats.pack(fill="x", pady=(24, 14))
        self._stat_card(stats, "Courses", str(dashboard["course_count"]), "confirmed course folders", 0)
        self._stat_card(stats, "Inbox", str(dashboard["inbox_count"]), "files awaiting review", 1)
        root_state = "Ready" if dashboard["root_exists"] else "Needs setup"
        self._stat_card(stats, "Workspace", root_state, "local files stay on this computer", 2)

        lower = ttk.Frame(body, style="App.TFrame")
        lower.pack(fill="both", expand=True)
        left = ttk.Frame(lower, style="Panel.TFrame", padding=18)
        left.pack(side="left", fill="both", expand=True, padx=(0, 9))
        right = ttk.Frame(lower, style="Panel.TFrame", padding=18)
        right.pack(side="left", fill="both", expand=True, padx=(9, 0))
        ttk.Label(left, text="Quick actions", style="PanelHeading.TLabel").pack(anchor="w")
        for label, command in (
            ("Open University folder", lambda: open_local_path(Path(dashboard["academic_root"]))),
            ("Open today's dashboard", lambda: self._open_today(dashboard)),
            ("Add a course", lambda: self._add_course(dashboard)),
            ("Import older University material", lambda: self._migration_dialog(dashboard)),
            ("Run verification", lambda: self._run_verification()),
            ("Open setup handoff guide", lambda: open_local_path(Path(dashboard["install_root"]) / "HANDOFF.md")),
        ):
            ttk.Button(left, text=label, style="Secondary.TButton", command=command).pack(fill="x", pady=(10, 0))
        ttk.Label(left, text=f"Files: {dashboard['academic_root']}", style="PanelMuted.TLabel", wraplength=420).pack(anchor="w", pady=(18, 0))

        ttk.Label(right, text="Current picture", style="PanelHeading.TLabel").pack(anchor="w")
        courses_text = "\n".join(f"• {course}" for course in dashboard["courses"]) or "No courses yet — add a syllabus when you are ready."
        ttk.Label(right, text=courses_text, style="PanelBody.TLabel", justify="left", wraplength=420).pack(anchor="w", pady=(12, 12))
        ttk.Label(right, text="Today's dashboard preview", style="PanelHeading.TLabel").pack(anchor="w", pady=(8, 0))
        preview = dashboard["today_preview"] or "No daily brief has been generated yet."
        text = tk.Text(right, height=8, background="#0b1321", foreground=self.TEXT, insertbackground=self.TEXT, borderwidth=0, wrap="word", padx=10, pady=10)
        text.insert("1.0", preview)
        text.configure(state="disabled")
        text.pack(fill="both", expand=True, pady=(8, 0))

        integrations = ttk.Frame(body, style="App.TFrame")
        integrations.pack(fill="x", pady=(14, 0))
        configured = [label for label, key in (("Gmail", "gmail"), ("Calendar", "calendar"), ("Drive", "drive"), ("School portal", "school_portal")) if dashboard["integrations"].get(key)]
        state = "Prepared: " + ", ".join(configured) if configured else "No external accounts selected yet"
        ttk.Label(integrations, text=state + " · Authorization happens in the user's own browser.", style="Muted.TLabel", wraplength=850).pack(anchor="w")

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
            source_candidates[:] = [candidate for candidate in discover_academic_folders() if candidate.path != current]
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
                source = Path(source_var.get().strip()).expanduser().resolve()
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
            selected_indexes = migration_list.curselection()
            selected_items = [plan.items[index] for index in selected_indexes]
            if not selected_items:
                messagebox.showinfo("Nothing selected", "Select at least one file, or close this window to leave the old folder unchanged.", parent=dialog)
                return
            if mode == "move" and not messagebox.askyesno("Move selected originals?", "This will remove only the selected original files after hash verification. Copy is safer and recommended. Continue?", parent=dialog):
                return
            result = execute_migration_plan(plan, items=selected_items, mode=mode)
            report_dir = Path(dashboard["install_root"]) / "migration"
            report_dir.mkdir(parents=True, exist_ok=True)
            (report_dir / "migration-report.json").write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
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
