#!/usr/bin/env python3
"""
HRDM_spec_gui.py

Merges spec_controller_gui.py's raw SPEC command sender (type any
command, hit Enter/Send, or the red STOP button to abort whatever SPEC
is currently doing -- exactly like ^C at the SPEC console) with
HRDM_gui.py's full HDRM three-crystal scan GUI (Global parameters,
Passes table, Preview Log, Run Scan, Cancel, and the Open/Close
Shutter toggle) into a single Tkinter window. Both halves share one
already-connected id4b_pyspec.spec_controller.SpecController -- the
exact class spec_controller_gui.py uses, so it's a drop-in-compatible
connection.

Unlike HRDM_gui.py (which connects lazily, from GUI fields, the first
time you click Run Scan), this window connects once at startup --
the same pattern spec_controller_gui.py uses -- from command-line
arguments:

    python HRDM_spec_gui.py <host> <port> [--timeout SECONDS] [--verbose]

Because the connection already exists by the time the window opens,
Global parameters here has no SPEC host/port/timeout fields (unlike
HRDM_gui.py) -- Run Scan, the shutter toggle, and the raw command box
all just use the one shared connection. hrdm_core.DEFAULT_GLOBALS
still defines those three keys (for HRDM_gui.py's benefit); they're
simply not shown here and never read by Runner.run() itself, so
leaving them out of this window's fields is safe.

Preview Log stays 100% simulated -- it builds/shows the full command
sequence instantly and never touches the shared connection, no matter
what. Run Scan, the Open/Close Shutter toggle, the raw command Send
box, and the "Read from SPEC" button are the only things that ever
send real commands -- all through that one shared connection, and all
logged (outgoing command + response) to the same "Log" tab, so
everything that happened in a session shows up in one place.

"Read from SPEC" (in the Global parameters box) queries SPEC live --
sending the bare expression "DATAFILE" (SPEC's own global variable)
and filling in the DATAFILE field with whatever comes back. It's sent
as a bare variable expression rather than "p DATAFILE": a "p ..."
command prints to the SPEC console for a human to read and isn't
guaranteed to hand back clean, parseable text through the id4b_pyspec
bridge, whereas evaluating a bare variable returns its value directly.
See _SPEC_READ_COMMANDS to add more fields the same way.

Clicking "Read from SPEC" isn't the only way DATAFILE gets read live,
though: a checkbox right next to that button, "Auto-watch DATAFILE",
is checked by default and keeps the field in sync on its own -- a
background poll fires every _DATAFILE_WATCH_INTERVAL_MS (15s by
default) for as long as the window is open, sending that same bare
"DATAFILE" expression, and only touches the field (and logs a line)
when the value actually *changed* since the last poll, so it doesn't
spam the Log tab with an identical line every 15 seconds. Unchecking
the box pauses the watch (it keeps ticking on the same schedule, it
just stops sending) rather than stopping it outright, so re-checking
it resumes immediately without needing to reopen the window. This is
on top of, not a replacement for, "Read from SPEC" and Run Scan's own
auto-refresh -- all three ultimately do the same read, just on
different triggers (a click, right before a real run, and on a
timer).

The detector path prefix field (_rampre) is deliberately NOT read live
from SPEC. It's tempting to think it should come from SPEC's current
working directory (CWD/pwd), since that also changes with every
proposal/cycle -- but CWD reflects the NFS-mounted archive path SPEC
itself is sitting in (e.g. "/nfs/chess/id4b/2026-3/sarker-4775-a"),
which is a *different filesystem* from the Pilatus detector's own
local ramdisk storage that pil_setdir actually points the detector at
(PIL_PATH_BASE = "/ramdisk" in multi_pilatus_v5.mac). Setting _rampre
to the live NFS CWD value pointed the detector at a path it can't
write to, so images silently stopped saving. _rampre is a manually-set
field (see DEFAULT_GLOBALS["rampre"] in hrdm_core.py for its default,
e.g. "/ramdisk/sarker-4775-a/") -- update it by hand when the
proposal/cycle changes.

The detector trigger mode field is a dropdown locked to the 2 modes
actually used here -- Internal and Mult. Trigger (see
hrdm_core.TRIGGER_MODE_STATES; the real PV can report 3 other states
too, but they're intentionally left out of this dropdown). Its "Read
from EPICS" button reads that PV live via the optional `pyepics`
package, entirely independent of the SPEC connection above -- pyepics
is only imported when that button is actually clicked, so it stays
optional if you never use it.

The window's Global parameters / Passes / Run Scan workflow and the
separate "Height Scan" and "Powder Scan" workflows are each
full-fledged scans in their own right, so they live in their own
top-level tabs -- a main notebook with "Sample Information" first
(DATAFILE, Sample name, Detector path prefix, Detector trigger mode,
and Next scan number, plus the "Read from SPEC"/"Auto-watch
DATAFILE"/"Read from EPICS" controls that only ever touch those
fields), "Height Scan" second, "Threextal Scan" (its own remaining
Global parameters -- temperature, num flyscan steps, final chi/phi/th,
count time, wait after temp set -- plus Passes, Preview Log, Run Scan,
Cancel, Open/Close Shutter, Save/Load Config, Clear Log) third, and
"Powder Scan" fourth -- rather than Height Scan/Powder Scan being
nested inside the Log/Python Script Output notebook alongside pure
output displays. All tabs share the same underlying self.global_vars
dict, so splitting the fields across Sample Information and Threextal
Scan is purely a display/organization change with no effect on the
data itself. The raw SPEC command box above this main notebook, and
the Log / Python Script Output notebook below it, are shared by all
tabs.

The "Height Scan" tab runs the quick sample-quality check translated
from HDRMscans_new.mac's `heightscan` macro (see
hrdm_core.Runner.run_height_scan) -- a step-scan (`lup`) of the
sample-height motor (samz) through the beam, independent of the
Threextal Scan tab's threextalscan sequence. It shares the Sample
Information tab's 'rampre' field (images go to a fixed
"<rampre>/tiffs/" folder, not the per-sample/temperature folders Run
Scan uses) but has its own Start/End/Steps/Count time fields,
defaulted to hrdm_core.HEIGHTSCAN_DEFAULTS (-0.6, 0.6, 60, 0.2 --
matching the macro's own no-argument defaults). Its own Preview and
Run Height Scan buttons work exactly like the Threextal Scan tab's
Preview Log / Run Scan buttons (Preview is fully simulated and never
sends anything; Run Height Scan sends real commands through the same
shared self.controller), and both log to the same shared "Log" tab as
everything else in this window.

The "Powder Scan" tab runs the powder-diffraction calibration scan
translated from HDRMscans_new.mac's `powderscan <temperature>
<sleep_time>` macro (see hrdm_core.Runner.run_powder_scan) -- a single
fixed motor move (chi 90, th 0, phi 0) and flyscan (phi 0 to 360, 180
steps, 2s count time), sharing threextalscan's SAME per-sample/
per-temperature directory scheme (unlike Height Scan's fixed
"<rampre>/tiffs/" folder). It reads the Sample Information tab's
'datafile', 'sample', and 'rampre' fields for that directory
structure, but has its own Temperature/Wait time fields (defaulted to
hrdm_core.POWDERSCAN_DEFAULTS), since run_powder_scan() takes those as
their own arguments (mirroring the macro's own "$1"/"$2" call
arguments) rather than reading Threextal Scan's own
'temperature'/'wait_seconds' fields. Its Preview/Run Powder Scan
buttons work the same way as the other two tabs' scan buttons, and log
to the same shared "Log" tab.

Run Scan, Run Height Scan, and Run Powder Scan each refuse to start
while either of the other two is already in progress, since all three
change the detector's trigger mode and storage directory -- running
more than one at the same time would corrupt whichever real scan is
still going.

See HRDM_gui.py / hrdm_core.py for the underlying scan logic (shared,
unchanged here) and spec_controller_gui.py for the raw command sender
this was merged from (also left unchanged, as its own standalone
tool).
"""

import argparse
import json
import logging
import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter import font as tkfont

from id4b_pyspec.prompt import describe_result
from id4b_pyspec.spec_controller import SpecController

from hrdm_core import (
    COOLDOWN_DEFAULTS,
    DEFAULT_GLOBALS,
    DEFAULT_PASSES,
    GAS_PREP_MACRO_NAMES,
    GAS_PREP_MACROS_DEFAULTS,
    HDRM_SCAN_DEFAULTS,
    HDRM_SCAN_PASSES_DEFAULTS,
    HEIGHTSCAN_DEFAULTS,
    HIGHTEMP_SCAN_DEFAULTS,
    LOW_TEMP_SAMPLE_SETUP_DEFAULTS,
    LOW_TEMP_SCAN_DEFAULTS,
    N2_TO_HE_SWITCH_DEFAULTS,
    POWDERSCAN_DEFAULTS,
    SAMPLE_TEMP_PV,
    SPIN_DEFAULTS,
    STAGE_A_TEMP_PV,
    STAGE_C_TEMP_PV,
    STANDALONE_TEMP_FLOW_DEFAULTS,
    TRIGGER_MODE_PV,
    TRIGGER_MODE_STATES,
    WARMUP_CUSTOM_DEFAULTS,
    WARMUP_FINAL_STEP_DEFAULTS,
    WARMUP_PHASE_DEFAULTS,
    Runner,
    generate_script,
    parse_nfs_cwd,
    resolve_data_dirs,
    validate_cooldown_params,
    validate_gas_prep_macros_params,
    validate_hdrm_scan_params,
    validate_height_params,
    validate_hightemp_params,
    validate_low_temp_params,
    validate_low_temp_sample_setup_params,
    validate_n2_to_he_switch_params,
    validate_powder_params,
    validate_spin_params,
    validate_standalone_temp_flow_params,
    validate_warmup_custom_params,
    validate_warmup_final_step_params,
    validate_warmup_phase_params,
)

# Tabs that get the new standalone "Live temperatures (EPICS) + Set
# Temp (te) + Flow Control (flow_set/flow_get)" block, per user
# request -- every Threextal/Height/Powder scan tab and every
# temperature-series tab. (key, display label) pairs; key is used to
# namespace every Tk variable/attribute/thread for that tab's own copy
# of the block (self.standalone[key] -- see _init_standalone_state),
# and label is used in log messages / dialog titles. Low Temp Scan
# additionally gets its own standalone Spin control -- see
# _build_low_temp_standalone_spin_section -- which is NOT part of this
# list since it isn't a Set Temp/Flow Control block.
STANDALONE_TEMP_FLOW_TABS = [
    ("threextal", "Threextal Scan"),
    ("height", "Height Scan"),
    ("powder", "Powder Scan"),
    ("lowtemp", "Low Temp Scan"),
    ("warmup", "Warmup"),
    ("warmupcustom", "Warmup Custom"),
    ("cooldown", "Cooldown"),
    ("hightemp", "High Temp Scan"),
]

# Same auto-watch cadence as the Gas Prep Macros / N2 -> He Switch
# "Live temperatures (EPICS)" sections (see _GAS_PREP_TEMP_WATCH_INTERVAL_MS).
_STANDALONE_TEMP_WATCH_INTERVAL_MS = 15000

# Fields that HRDM_gui.py exposes for its own (lazy, GUI-driven)
# connection setup, but that don't apply here -- this window already
# has a live, already-connected controller by the time it's built.
_SPEC_CONNECTION_KEYS = ("spec_host", "spec_port", "spec_timeout")

# Local Global-parameters field key -> the exact command to send to
# SPEC when "Read from SPEC" is clicked. Entries here should always be
# bare SPEC global-variable expressions, NOT "p <VAR>" print commands:
#   - "DATAFILE" evaluates SPEC's live DATAFILE variable directly
#     (confirmed against a real SPEC session, where "p DATAFILE"
#     prints it for a human to read:
#       1865.FOURC> p DATAFILE
#       test3
#     -- but sending the bare expression "DATAFILE" through the
#     id4b_pyspec bridge's eval channel gets the same value back
#     as an actual Python return value, rather than console text
#     that would need to be scraped and that isn't guaranteed to
#     come back clean).
# "rampre" is intentionally NOT in this dict -- see the module
# docstring's "detector path prefix" section for why: SPEC's CWD
# reflects the NFS archive mount, not the Pilatus detector's own
# local ramdisk storage, so reading it live pointed the detector at a
# path it couldn't write to and images stopped saving. Only add a key
# here if the field's live SPEC value is actually usable as-is by
# whatever consumes it (pil_setdir, in rampre's case, needs the local
# ramdisk path, which SPEC has no variable for).
_SPEC_READ_COMMANDS = {
    "datafile": "DATAFILE",
}

# How often (in milliseconds) the "Auto-watch DATAFILE" checkbox polls
# SPEC for DATAFILE in the background, for as long as the window is
# open -- see HRDMSpecApp._datafile_watch_tick. Only DATAFILE is ever
# watched this way, for the same reason it's the only entry in
# _SPEC_READ_COMMANDS above (rampre needs a value SPEC has no live
# variable for).
_DATAFILE_WATCH_INTERVAL_MS = 15000

# How often (in milliseconds) the "Auto-watch Temperatures" checkbox
# in the N2 -> He Gas Switch section polls Stage A/Stage C/sample
# temperature from EPICS in the background -- see
# HRDMSpecApp._n2_he_temp_watch_tick. Same interval as
# _DATAFILE_WATCH_INTERVAL_MS above, for consistency; temperatures
# change slowly enough that a faster poll wouldn't add much.
_N2_HE_TEMP_WATCH_INTERVAL_MS = 15000

# How close (in Kelvin) a live Stage A/Stage C reading must get to its
# prepswitch setpoint field to count as "reached" for the "next stage
# is ready" log message -- see
# HRDMSpecApp._check_n2_he_prepswitch_ready. Cooling a Lakeshore 336
# stage rarely lands on the exact setpoint float, so a small tolerance
# avoids the message never firing due to noise (e.g. 99.6K vs a 100K
# setpoint).
_PREPSWITCH_READY_TOLERANCE_K = 1.0

# Same interval as _N2_HE_TEMP_WATCH_INTERVAL_MS above, but for the
# Gas Prep Macros tab's own "Auto-watch Temperatures" checkbox -- see
# HRDMSpecApp._gas_prep_temp_watch_tick. Kept as its own named
# constant (rather than reusing _N2_HE_TEMP_WATCH_INTERVAL_MS
# directly) for the same reason every other tab here keeps its own
# copy of shared-looking values: each tab's timer is independent.
_GAS_PREP_TEMP_WATCH_INTERVAL_MS = 15000

# Display label used in each Gas Prep tab button's text ("Run
# <label>") and in the matching Preview button's closing log line
# ("click Run <label> to actually send this"). Used to be keyed by
# "room_temperature_sample" (a project addition since removed per
# explicit user request -- see hrdm_core.py's GAS_PREP_MACRO_NAMES
# docstring); every one of the 7 real macros from
# Lakeshore336cryocool.mac just uses its own name as-is, so this is
# now an empty override table kept only so
# _on_gas_prep_preview_macro/_on_gas_prep_run_macro's
# `.get(name, name)` lookups need no further changes if a future
# macro ever needs a friendlier display label again.
_GAS_PREP_MACRO_BUTTON_LABELS = {}

# Palette of visually-distinct accent colors used to give each
# LabelFrame "card" on the Gas Prep tab (and anywhere else
# _make_section is used) its own identity at a glance -- see
# _make_section. Cycled in order; same colors in both Dark/Light
# themes so a section's color doesn't shift when the theme is
# switched, only the surrounding bg/fg do.
_SECTION_ACCENT_COLORS = [
    "#2f8fe0",  # blue
    "#2fbf71",  # green
    "#e0a72f",  # amber
    "#bf5fe0",  # purple
    "#e05f5f",  # red
    "#2fc7c2",  # teal
]

# Per-tab accent colors for the 5 tabs the user explicitly asked to
# have their own color ("Make color tab: threextal Scan, Gas Prep,
# Low Temp Scan, Warmup, spin control"). ttk's Notebook has no
# supported way to give one tab's own label/strip a background color
# different from every other tab's (the whole tab strip shares one
# style, same limitation _make_section works around for LabelFrames --
# see its docstring) -- so each of these 5 tabs instead gets a small
# solid-color square swatch image placed directly on its tab label
# (via Notebook.tab(..., image=..., compound="left")), immediately to
# the left of the tab's text. That square *is* "this tab's own
# label/strip" colored distinctly, the closest truly-per-tab
# equivalent ttk actually supports. Picked to loosely match each
# tab's own theme (blue=Threextal/general, green=Gas Prep,
# teal=cold/Low Temp, amber=warm/Warmup, purple=Spin Control) and
# kept distinct from one another; see _make_scrollable_tab, which
# looks up a tab's title here and skips every other (unlisted) tab.
_TAB_ACCENT_COLORS = {
    "Threextal Scan": "#2f8fe0",   # blue
    "Gas Prep": "#2fbf71",         # green
    "Low Temp Scan": "#2fc7c2",    # teal (cold)
    "Warmup": "#e0a72f",           # amber (warm)
    "Spin Control": "#bf5fe0",     # purple
}

# ============================================================
# Theme system (Dark / Light) -- same palettes/pattern as HRDM_gui.py,
# plus a "Stop.TButton" style for the red abort button (styled to
# match the theme rather than hardcoding tk colors, the way
# spec_controller_gui.py's plain-tk STOP button does).
# ============================================================
# Modernized (2026 restyle) palettes -- same two themes, same keys the
# rest of this file already reads (bg/fg/entry_bg/button_bg/
# button_hover/border/accent/accent_hover/accent_fg/stop/stop_hover/
# stop_fg/log_bg/log_fg), plus several new keys added for widgets that
# previously had no theme-aware styling at all (TNotebook tabs,
# TScrollbar, TCombobox, the scrollable-tab Canvas background) -- see
# _apply_theme for where each one is used. Colors are a Tailwind-
# inspired flat palette (consistent blue accent / red "stop" accent
# across both themes) rather than the previous theme's slightly
# mismatched per-theme accent hues.
THEMES = {
    "dark": {
        "bg": "#17181c",
        "fg": "#e8eaef",
        "entry_bg": "#24262c",
        "button_bg": "#24262c",
        "button_hover": "#2f323a",
        "border": "#2d2f36",
        "accent": "#3b82f6",
        "accent_hover": "#5c9bf5",
        "accent_fg": "#ffffff",
        "stop": "#e5484d",
        "stop_hover": "#f2666a",
        "stop_fg": "#ffffff",
        "log_bg": "#0d0e11",
        "log_fg": "#d7dae0",
        "tab_bg": "#1b1d22",
        "tab_fg": "#9aa0ae",
        "tab_selected_bg": "#24262c",
        "tab_selected_fg": "#e8eaef",
        "scroll_trough": "#1b1d22",
        "scroll_thumb": "#3a3d46",
        "scroll_thumb_hover": "#4a4e59",
    },
    "light": {
        "bg": "#f7f8fa",
        "fg": "#161a22",
        "entry_bg": "#ffffff",
        "button_bg": "#eef1f5",
        "button_hover": "#e3e7ee",
        "border": "#dde1e8",
        "accent": "#2563eb",
        "accent_hover": "#3b82f6",
        "accent_fg": "#ffffff",
        "stop": "#dc2626",
        "stop_hover": "#ef4444",
        "stop_fg": "#ffffff",
        "log_bg": "#ffffff",
        "log_fg": "#1f2430",
        "tab_bg": "#eef1f5",
        "tab_fg": "#5b6472",
        "tab_selected_bg": "#ffffff",
        "tab_selected_fg": "#161a22",
        "scroll_trough": "#eef1f5",
        "scroll_thumb": "#c7ccd4",
        "scroll_thumb_hover": "#b3b9c4",
    },
}


class PassRow:
    """One editable row in the pass table (chi, th, phi, scan start/stop).
    Identical to HRDM_gui.py's PassRow."""

    def __init__(self, parent, on_remove, values=None):
        values = values or {}
        self.frame = ttk.Frame(parent)
        self.frame.pack(fill="x", pady=2)

        self.vars = {
            "chi": tk.StringVar(value=values.get("chi", "0")),
            "th": tk.StringVar(value=values.get("th", "0")),
            "phi": tk.StringVar(value=values.get("phi", "0")),
            "scan_start": tk.StringVar(value=values.get("scan_start", "0")),
            "scan_stop": tk.StringVar(value=values.get("scan_stop", "365")),
        }

        for key, width in (
            ("chi", 8), ("th", 8), ("phi", 8), ("scan_start", 10), ("scan_stop", 10)
        ):
            ttk.Entry(self.frame, textvariable=self.vars[key], width=width).pack(
                side="left", padx=3
            )

        ttk.Button(
            self.frame, text="Remove", width=8, command=lambda: on_remove(self)
        ).pack(side="left", padx=6)

    def get(self):
        return {k: v.get().strip() for k, v in self.vars.items()}

    def destroy(self):
        self.frame.destroy()


class PassesTableController:
    """Manages one independent, editable table of PassRow widgets
    (chi/th/phi/scan start/stop) inside some container frame --
    generalizes the Threextal Scan tab's own long-standing pass_rows/
    passes_container/_add_pass_row/_remove_pass_row/_set_num_passes
    pattern on HRDMSpecApp (left exactly as-is below, for backward
    compatibility with every existing test) so each of the 5
    temperature-series tabs' new "HDRM Scan Parameters" section (see
    HRDMSpecApp._build_hdrm_scan_params_section) can have its own
    passes table without duplicating that add/remove/set-count logic
    5 separate times."""

    def __init__(self, container, defaults, num_passes_var):
        self.container = container
        self.defaults = defaults
        self.num_passes_var = num_passes_var
        self.rows = []

    def add_row(self, values=None):
        row = PassRow(self.container, self.remove_row, values)
        self.rows.append(row)
        return row

    def remove_row(self, row):
        if len(self.rows) <= 1:
            messagebox.showwarning("HDRM Scan", "At least one pass is required.")
            return
        row.destroy()
        self.rows.remove(row)

    def set_num_passes(self, n):
        try:
            n = int(str(n).strip())
        except ValueError:
            messagebox.showerror("HDRM Scan", f"'{n}' is not a valid number of passes.")
            return
        n = max(1, n)

        while len(self.rows) > n:
            row = self.rows[-1]
            row.destroy()
            self.rows.remove(row)

        while len(self.rows) < n:
            idx = len(self.rows)
            defaults = (
                self.defaults[idx]
                if idx < len(self.defaults)
                else {"chi": "0", "th": "0", "phi": "0", "scan_start": "0", "scan_stop": "365"}
            )
            self.add_row(defaults)

        self.num_passes_var.set(str(len(self.rows)))

    def reset_to_defaults(self):
        for row in list(self.rows):
            row.destroy()
        self.rows.clear()
        for p in self.defaults:
            self.add_row(p)
        self.num_passes_var.set(str(len(self.rows)))

    def get(self):
        return [row.get() for row in self.rows]


class HRDMSpecApp(tk.Tk):
    """The merged window. `controller` must already be connected (a
    real id4b_pyspec.spec_controller.SpecController, or in tests, any
    duck-typed object with .send(command), .abort(), .spec_host,
    .spec_port, .spec_timeout)."""

    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self.title(
            f"Data Collection: {controller.spec_host} {controller.spec_port} "
            f"-- HDRM Scan + SPEC {controller.spec_host}:{controller.spec_port}"
        )
        # Smaller default size than the old fixed 900x880 -- the window
        # is resizable and every description label's wraplength now
        # tracks its own width dynamically (see _make_wrapping_label),
        # so shrinking the default no longer clips or overflows text.
        # A bit taller than before (760x680 -> 900x760) to give the
        # tabs area and the Output/Log section below it (see
        # self.body_paned in _build_main_notebook's docstring) more
        # combined room by default -- individual tabs also scroll now
        # (see _make_scrollable_tab), so nothing is unreachable even
        # below this size, but starting larger means less resizing is
        # needed up front.
        self.geometry("900x760")
        self.minsize(620, 480)

        self.log_queue = queue.Queue()
        self.cancel_event = threading.Event()
        self.run_thread = None

        self.global_vars = {
            k: tk.StringVar(value=v)
            for k, v in DEFAULT_GLOBALS.items()
            if k not in _SPEC_CONNECTION_KEYS
        }
        self.pass_rows = []
        self.shutter_open = False  # tracks the manual Open/Close Shutter toggle
        # Every ttk.Button that mirrors this same Open/Close Shutter
        # toggle -- the original one on the Threextal Scan tab
        # (_build_controls_section) plus the always-visible one added
        # to the top raw-command area (_build_raw_command_section), so
        # the shutter can be operated without switching to the
        # Threextal Scan tab first (matching how the raw SPEC command
        # box itself is always visible regardless of tab). Both
        # buttons drive/reflect the exact same self.shutter_open state
        # and self._on_toggle_shutter() handler -- see that method,
        # which loops over this list to keep every button's text in
        # sync rather than picking one as "the real one."
        self.shutter_buttons = []

        # ---- Data locations (Sample Information tab) -- this
        # project's own addition (see hrdm_core.resolve_data_dirs),
        # added per explicit request ("Check the final data collection
        # and data save folder .. mention that to the sample
        # information"). Read-only, live-computed raw-data and
        # processed-data (nxrefine) directory paths, kept in sync with
        # the Sample Information fields they're built from via the
        # trace_add calls below -- so they update the moment any of
        # those fields change, with no separate "Refresh" click
        # needed. See _refresh_data_dirs / _build_data_locations_section.
        # (Only these two paths are shown -- the per-scan "next scan's
        # image folder" path was removed from this section per a later
        # request to keep it to just Raw + Processed, plain
        # display-only, no Open/Copy buttons; next_scan_n therefore
        # isn't watched here since neither remaining path depends on
        # it.)
        self.raw_sample_dir_var = tk.StringVar(value="")
        self.processed_dir_var = tk.StringVar(value="")
        for _key in (
            "nfs_cycle", "nfs_btr", "datafile", "sample", "temperature",
        ):
            self.global_vars[_key].trace_add("write", self._refresh_data_dirs)
        self._refresh_data_dirs()

        # Height Scan tab -- see _build_height_scan_tab / _on_height_run.
        # Its own field values (independent of Global parameters'
        # threextalscan-oriented fields above), defaulted to
        # hrdm_core.HEIGHTSCAN_DEFAULTS.
        self.height_vars = {
            k: tk.StringVar(value=v) for k, v in HEIGHTSCAN_DEFAULTS.items()
        }
        self.height_run_thread = None

        # Powder Scan tab -- see _build_powder_scan_tab / _on_powder_run.
        # Its own (temperature, wait_seconds) field values, defaulted to
        # hrdm_core.POWDERSCAN_DEFAULTS -- independent of Global
        # parameters' threextalscan-oriented 'temperature'/
        # 'wait_seconds' fields, since run_powder_scan() takes these as
        # their own plain arguments (mirroring the macro's own "$1"/
        # "$2" call arguments), not out of the Threextal Scan tab's `g`.
        self.powder_vars = {
            k: tk.StringVar(value=v) for k, v in POWDERSCAN_DEFAULTS.items()
        }
        self.powder_run_thread = None

        # ---- Spin Control tab -- see _build_spin_tab / _on_spin_start.
        # Unifies HDRMscans_new.mac's `spin_xtal_phi` and `spin_ice`
        # into one Start/Stop control (see Runner.run_spin_xtal_phi's
        # docstring for the side-by-side comparison that justified
        # this) -- "ice_mode" is the one extra field beyond
        # SPIN_DEFAULTS' own "num_cycles", exposed as a checkbox
        # rather than a text field. This is a Start/Stop (not
        # Preview/Run) tab since it can run indefinitely (blank
        # num_cycles), so it gets its own dedicated cancel_event
        # rather than reusing self.cancel_event (which belongs to the
        # Threextal Scan tab's own Cancel button).
        self.spin_vars = {
            k: tk.StringVar(value=v) for k, v in SPIN_DEFAULTS.items() if k != "ice_mode"
        }
        self.spin_ice_mode_var = tk.BooleanVar(value=bool(int(SPIN_DEFAULTS["ice_mode"])))
        self.spin_run_thread = None
        self.spin_cancel_event = threading.Event()

        # ---- Low Temp Scan tab -- see _build_low_temp_tab /
        # _on_low_temp_run. Long-running (many temperature steps), so
        # it gets a Stop button backed by its own dedicated
        # cancel_event, same reasoning as Spin Control above and every
        # other temperature-series tab below.
        self.low_temp_vars = {
            k: tk.StringVar(value=v) for k, v in LOW_TEMP_SCAN_DEFAULTS.items()
        }
        self.low_temp_run_thread = None
        self.low_temp_cancel_event = threading.Event()
        # HDRM Scan Parameters section (see
        # _build_hdrm_scan_params_section) -- an independent, editable
        # copy of the passes/num_steps/count_time the full HDRM scan
        # at each temperature step uses, previously hard-coded inside
        # Runner._threextalscan_step. self.low_temp_passes_table (the
        # PassesTableController) is created in _build_low_temp_tab,
        # once its container frame exists.
        self.low_temp_num_steps_var = tk.StringVar(value=HDRM_SCAN_DEFAULTS["num_steps"])
        self.low_temp_count_time_var = tk.StringVar(value=HDRM_SCAN_DEFAULTS["count_time"])
        self.low_temp_passes_table = None

        # ---- Low Temp Scan tab's standalone "Sample Setup" button --
        # a project addition, no macro precedent (see
        # LOW_TEMP_SAMPLE_SETUP_DEFAULTS' docstring): just sends te +
        # flow_set on their own, independent of the automatic Low Temp
        # Scan sequence above and the N2 -> He Gas Switch section.
        # Gets its own thread slot/cancel event -- same "one scan-type
        # thread at a time" convention as every other button on this
        # tab (registered in _scan_thread_registry).
        self.low_temp_sample_setup_vars = {
            k: tk.StringVar(value=v) for k, v in LOW_TEMP_SAMPLE_SETUP_DEFAULTS.items()
        }
        self.low_temp_sample_setup_run_thread = None
        self.low_temp_sample_setup_cancel_event = threading.Event()

        # ---- N2 -> He Switch section -- lives at the very top of the
        # Low Temp Scan tab (see _build_low_temp_tab /
        # _on_n2_to_he_switch_run). This project's own addition: it
        # consolidates the site's manual, multi-command "300K -> 15K:
        # Room Temperature to base (change N2 to He flow)" procedure
        # (prepswitch -> wait -> te 240 -> flow_set 10 -> wait -> [manual
        # valve switch] -> runninghelium -> wait -> flow_set 12 ->
        # te 15 -> spin_xtal_phi) into a single one-click Run button,
        # with every value (including all three wait times, now
        # expressed in minutes to match how beamline staff think about
        # this procedure) editable. Long-running, so it gets its own
        # Stop button/cancel_event, same reasoning as every other
        # temperature-series tab.
        #
        # The 4 "*_enabled" keys in N2_TO_HE_SWITCH_DEFAULTS (this
        # project's own addition, mirroring Warmup's per-phase
        # "Enabled" checkbox) are pulled out into their own BooleanVar
        # dict rather than left in self.n2_he_switch_vars, since every
        # other value in that dict is a plain numeric StringVar shown
        # in an Entry -- exactly the same split WARMUP_PHASE_DEFAULTS'
        # "enabled" key gets from every other per-phase field.
        _n2_he_enabled_keys = (
            "step1_enabled", "steps3_5_enabled", "step7_enabled", "steps8_10_enabled",
        )
        self.n2_he_switch_vars = {
            k: tk.StringVar(value=v) for k, v in N2_TO_HE_SWITCH_DEFAULTS.items()
            if k not in _n2_he_enabled_keys
        }
        self.n2_he_switch_enabled_vars = {
            k: tk.BooleanVar(value=N2_TO_HE_SWITCH_DEFAULTS[k] == "1")
            for k in _n2_he_enabled_keys
        }
        self.n2_he_switch_run_thread = None
        self.n2_he_switch_cancel_event = threading.Event()

        # Live Stage A / Stage C / sample temperature readback (this
        # project's own addition -- see _on_read_n2_he_temps /
        # _n2_he_temp_watch_tick). Read via the optional `pyepics`
        # package from STAGE_A_TEMP_PV/STAGE_C_TEMP_PV/SAMPLE_TEMP_PV
        # in hrdm_core.py, entirely independent of the SPEC connection
        # -- same pattern as the detector trigger-mode "Read from
        # EPICS" button. Auto-watch is on by default, same as
        # Auto-watch DATAFILE, since these readings matter most while
        # unattended during Step 2's/Step 8's multi-minute waits.
        self.n2_he_stage_a_temp_var = tk.StringVar(value="?")
        self.n2_he_stage_c_temp_var = tk.StringVar(value="?")
        self.n2_he_sample_temp_var = tk.StringVar(value="?")
        self.n2_he_temp_watch_var = tk.BooleanVar(value=True)
        self._n2_he_temp_read_thread = None
        self._n2_he_temp_watch_after_id = None
        # Tracks whether the "ready for next stage" line has already
        # been logged for the *current* prepswitch setpoints, so the
        # auto-watch poll only logs it once per readiness transition
        # instead of on every tick once both stages are above target
        # -- reset to False any time Run/Reset changes the prepswitch
        # setpoints, so a later re-run gets its own fresh notice.
        self._n2_he_prepswitch_ready_logged = False

        # ---- Warmup tab -- see _build_warmup_tab / _on_warmup_run.
        # One dict of StringVars per phase (shaped like
        # WARMUP_PHASE_DEFAULTS), plus a per-phase "enabled"
        # BooleanVar -- this project's own addition, letting each
        # phase be independently skipped (the macro itself always
        # runs all 3 in sequence). "label" and "prep_fn" are left as
        # plain (non-editable) strings on each phase dict -- they
        # identify *which* phase this is (Low/Medium/High N2 flow),
        # not a tunable number, so they aren't exposed as fields; every
        # numeric field on each phase is. This generic loop also picks
        # up each phase's "room_temp_after_enabled"/"_te"/"_flow" keys
        # (the per-phase "return to room temp after this phase"
        # interlude -- see WARMUP_PHASE_DEFAULTS' comment) as plain
        # StringVars; "room_temp_after_enabled" is bound to its
        # Checkbutton with onvalue/offvalue "1"/"0" in
        # _build_warmup_tab rather than needing its own BooleanVar, so
        # it (and its 2 numeric fields) flow through this
        # collection's/reset's generic per-phase key handling
        # unchanged, same as every other non-(label/prep_fn/enabled)
        # key here.
        self.warmup_phase_vars = []
        for phase_defaults in WARMUP_PHASE_DEFAULTS:
            phase_vars = {
                "label": phase_defaults["label"],
                "prep_fn": phase_defaults["prep_fn"],
                "enabled": tk.BooleanVar(value=phase_defaults["enabled"] == "1"),
            }
            for key, value in phase_defaults.items():
                if key in ("label", "prep_fn", "enabled"):
                    continue
                phase_vars[key] = tk.StringVar(value=value)
            self.warmup_phase_vars.append(phase_vars)
        self.warmup_run_thread = None
        self.warmup_cancel_event = threading.Event()
        # Optional "Phase 4" final step (this project's own addition,
        # off by default -- not part of the real `warmup` macro): send
        # a sample temperature (te) + gas flow (flow_set) after every
        # enabled phase finishes, to leave the sample near room
        # temperature/flow at the end of the sequence. Both numbers
        # are editable (default 300K/6, see WARMUP_FINAL_STEP_DEFAULTS)
        # -- the checkbox variable keeps its original name
        # (warmup_final_te_300_var) for continuity with existing code/
        # tests, even though it now also gates flow_set.
        self.warmup_final_te_300_var = tk.BooleanVar(value=False)
        self.warmup_final_sample_temp_var = tk.StringVar(
            value=WARMUP_FINAL_STEP_DEFAULTS["sample_temp"]
        )
        self.warmup_final_sample_flow_var = tk.StringVar(
            value=WARMUP_FINAL_STEP_DEFAULTS["sample_flow"]
        )
        # HDRM Scan Parameters section, shared by all 3 phases on this
        # tab (see _build_hdrm_scan_params_section and run_warmup's
        # docstring) -- independent of every other tab's own copy.
        self.warmup_num_steps_var = tk.StringVar(value=HDRM_SCAN_DEFAULTS["num_steps"])
        self.warmup_count_time_var = tk.StringVar(value=HDRM_SCAN_DEFAULTS["count_time"])
        self.warmup_passes_table = None

        # ---- Warmup Custom tab -- see _build_warmup_custom_tab /
        # _on_warmup_custom_run. Genuinely different algorithm from
        # Warmup above (one continuous threshold-driven loop instead
        # of 3 hard-coded phases -- see WARMUP_CUSTOM_DEFAULTS'
        # docstring), so it gets its own tab/vars/thread/cancel_event.
        self.warmup_custom_vars = {
            k: tk.StringVar(value=v) for k, v in WARMUP_CUSTOM_DEFAULTS.items()
        }
        self.warmup_custom_run_thread = None
        self.warmup_custom_cancel_event = threading.Event()
        # HDRM Scan Parameters section (see _build_hdrm_scan_params_section)
        # -- independent of every other tab's own copy.
        self.warmup_custom_num_steps_var = tk.StringVar(value=HDRM_SCAN_DEFAULTS["num_steps"])
        self.warmup_custom_count_time_var = tk.StringVar(value=HDRM_SCAN_DEFAULTS["count_time"])
        self.warmup_custom_passes_table = None

        # ---- Cooldown tab -- see _build_cooldown_tab /
        # _on_cooldown_run. Not explicitly requested, but added as the
        # descending mirror of Warmup Custom's threshold-driven
        # algorithm (see COOLDOWN_DEFAULTS' docstring) -- flagged here
        # and in the README so it's easy to remove/ignore if unwanted.
        self.cooldown_vars = {
            k: tk.StringVar(value=v) for k, v in COOLDOWN_DEFAULTS.items()
        }
        self.cooldown_run_thread = None
        self.cooldown_cancel_event = threading.Event()
        # HDRM Scan Parameters section (see _build_hdrm_scan_params_section)
        # -- independent of every other tab's own copy.
        self.cooldown_num_steps_var = tk.StringVar(value=HDRM_SCAN_DEFAULTS["num_steps"])
        self.cooldown_count_time_var = tk.StringVar(value=HDRM_SCAN_DEFAULTS["count_time"])
        self.cooldown_passes_table = None

        # ---- High Temp Scan tab -- see _build_hightemp_tab /
        # _on_hightemp_run.
        # "final_enabled" is a boolean "enable" flag (mirrors the Warmup
        # phase / N2->He switch step-group checkboxes), so it's pulled out
        # of the blanket StringVar dict comprehension into its own
        # BooleanVar rather than living as a plain "0"/"1" string.
        self._hightemp_enabled_keys = {"final_enabled"}
        self.hightemp_vars = {
            k: tk.StringVar(value=v)
            for k, v in HIGHTEMP_SCAN_DEFAULTS.items()
            if k not in self._hightemp_enabled_keys
        }
        self.hightemp_final_enabled_var = tk.BooleanVar(
            value=HIGHTEMP_SCAN_DEFAULTS.get("final_enabled") == "1"
        )
        self.hightemp_run_thread = None
        self.hightemp_cancel_event = threading.Event()
        # HDRM Scan Parameters section (see _build_hdrm_scan_params_section)
        # -- independent of every other tab's own copy.
        self.hightemp_num_steps_var = tk.StringVar(value=HDRM_SCAN_DEFAULTS["num_steps"])
        self.hightemp_count_time_var = tk.StringVar(value=HDRM_SCAN_DEFAULTS["count_time"])
        self.hightemp_passes_table = None

        # ---- Gas Prep Macros tab -- see _build_gas_prep_tab /
        # _on_gas_prep_run_macro. Exposes each of
        # Lakeshore336cryocool.mac's 7 gas/temperature-prep macros
        # (prepN2_low, prepN2_medium, prepN2_high, prepswitch,
        # runninghelium, roomT, highT -- see GAS_PREP_MACRO_NAMES) as
        # its own independently-runnable button, plus a standalone
        # flow_set/flow_get control and the same live Stage A/Stage
        # C/sample temperature EPICS readback + auto-watch pattern as
        # the N2 -> He Switch section above. Kept as its own
        # independent set of vars/thread/cancel_event rather than
        # reusing N2 -> He Switch's, consistent with every other tab
        # here keeping its own copy even when the underlying PVs/
        # values overlap conceptually (e.g. Warmup's/Cooldown's
        # separate prep_fn setpoints).
        self.gas_prep_vars = {
            k: tk.StringVar(value=v) for k, v in GAS_PREP_MACROS_DEFAULTS.items()
        }
        self.gas_prep_run_thread = None
        self.gas_prep_cancel_event = threading.Event()
        self.gas_prep_stage_a_temp_var = tk.StringVar(value="?")
        self.gas_prep_stage_c_temp_var = tk.StringVar(value="?")
        self.gas_prep_sample_temp_var = tk.StringVar(value="?")
        self.gas_prep_temp_watch_var = tk.BooleanVar(value=True)
        self._gas_prep_temp_read_thread = None
        self._gas_prep_temp_watch_after_id = None
        # Same "reached the prepswitch setpoints" latch as
        # self._n2_he_prepswitch_ready_logged, but scoped to this
        # tab's own prepswitch_stage_a/prepswitch_stage_c fields.
        self._gas_prep_prepswitch_ready_logged = False
        # Result of the standalone "flow_get" button, "?" until read
        # at least once -- only ever set from a real (non-preview,
        # connected) read, since Runner.flow_get() returns None in
        # preview mode / with no spec_controller attached.
        self.gas_prep_flow_result_var = tk.StringVar(value="?")
        # Filled in by _build_gas_prep_tab: {macro_name: ttk.Button},
        # so every macro button (plus flow_set/flow_get) can be
        # disabled/re-enabled together while any one of them runs --
        # see _gas_prep_all_buttons.
        self.gas_prep_macro_buttons = {}
        self.gas_prep_flow_set_button = None
        self.gas_prep_flow_get_button = None
        self.gas_prep_set_temp_button = None
        self.gas_prep_stop_button = None
        # Gas Prep's Set Temp/Flow Set/Flow Get buttons each got their
        # own independent background-thread slot here (separate from
        # gas_prep_run_thread, which stays shared by -- and still
        # mutually-exclusive via _scan_thread_registry with -- the 8
        # macro buttons), per explicit user request: these 3 quick
        # actions must never block, or be blocked by, anything else on
        # this tab or any other tab. Keyed dict (not 3 separate
        # attributes) so it can be passed straight to
        # _start_independent_job's `state` parameter -- see that
        # method's docstring and _on_gas_prep_run_set_temperature/
        # _on_gas_prep_flow_set/_on_gas_prep_flow_get below.
        self.gas_prep_independent_threads = {
            "set_temp": None,
            "flow_set": None,
            "flow_get": None,
        }

        # ---- standalone Set Temp (te) / Flow Control block, one per
        # scan/temperature tab (STANDALONE_TEMP_FLOW_TABS) ----
        # Each tab gets its own fully independent copy: own Tk
        # variables, own Live-temperatures-EPICS vars/thread/auto-
        # watch timer, own Set Temp/Flow Set/Flow Get buttons and
        # background-thread slots. None of these threads are ever
        # registered in _scan_thread_registry and none of their
        # handlers ever call _other_scan_running -- by explicit user
        # request, a quick temperature/flow action must never block,
        # or be blocked by, any scan/macro running on this tab or any
        # other tab. See _init_standalone_state, _build_standalone_
        # temp_flow_section, and _start_independent_job.
        self.standalone = {}
        for _prefix, _label in STANDALONE_TEMP_FLOW_TABS:
            self._init_standalone_state(_prefix, _label)

        # ---- Shared "last target temp/flow (any tab)" display --
        # per explicit user request ("If I set the temperature te
        # 240 to any tab ... other tab target temperature should
        # show that value, otherwise, I am confused" / "Same with
        # flow set"). Every tab's own Set Temp/flow_set controls stay
        # fully independent (this is purely a read-only echo, not a
        # shared field the tabs write into), but whichever tab last
        # actually sent a real `te`/`flow_set` command (see
        # _set_shared_target_temp/_set_shared_target_flow, called
        # from _on_standalone_run_set_temp/_on_standalone_run_flow_set
        # and the Gas Prep tab's own _on_gas_prep_run_set_temperature/
        # _on_gas_prep_flow_set) updates these two shared vars, which
        # every tab's standalone section displays side by side with
        # its own entry field. The numeric *_value copies (kept
        # separate from the human-readable *_var text, which also
        # includes units + which tab set it) are what
        # _check_target_temp_reached below actually compares live
        # EPICS readings against -- None until the first real Set
        # Temp of the session.
        self.shared_target_temp_value = None
        self.shared_target_flow_value = None
        self.shared_target_temp_var = tk.StringVar(value="-- (not set yet)")
        self.shared_target_flow_var = tk.StringVar(value="-- (not set yet)")
        # Per-section (keyed by the same "label" used in log lines,
        # e.g. "Threextal Scan", "Gas Prep", "N2->He Switch") latch
        # for _check_target_temp_reached's one-time "reached" log
        # line -- same latch-per-transition idea as the existing
        # self._n2_he_prepswitch_ready_logged /
        # self._gas_prep_prepswitch_ready_logged, just one dict
        # shared across every section instead of one bool per
        # section, and cleared whenever a new target temp is set (see
        # _set_shared_target_temp) since a new target means any
        # previous "reached" state no longer applies.
        self._target_temp_reached_logged = {}

        # ---- Low Temp Scan tab's standalone Spin (spin_xtal_phi)
        # control -- independent of Set Temp/Flow Set/Flow Get above,
        # of the tab's own automatic Low Temp Scan sequence, of its
        # Sample Setup button, and of the Spin Control tab's own
        # separate fields/thread. Continuous (Start/Stop), same
        # pattern as the Spin Control tab itself (see _on_spin_start),
        # just on its own thread that's never registered in
        # _scan_thread_registry.
        self.low_temp_spin_vars = {
            k: tk.StringVar(value=v) for k, v in SPIN_DEFAULTS.items()
            if k != "ice_mode"
        }
        self.low_temp_spin_ice_mode_var = tk.BooleanVar(
            value=SPIN_DEFAULTS["ice_mode"] == "1"
        )
        self.low_temp_spin_run_thread = None
        self.low_temp_spin_cancel_event = threading.Event()
        self.low_temp_spin_start_button = None
        self.low_temp_spin_stop_button = None

        # ---- Gas Prep tab's own standalone Spin (spin_xtal_phi)
        # control -- a second, independent copy of the Low Temp Scan
        # tab's own standalone spin section above (same pattern,
        # same SPIN_DEFAULTS, own vars/thread/cancel_event), added per
        # explicit user request ("Spin control tab type option in gas
        # flow tab, I want to rotate the crystal"). Independent of
        # every macro/Set Temp/Flow Control button on the Gas Prep
        # tab and of the Spin Control tab's own separate fields.
        self.gas_prep_spin_vars = {
            k: tk.StringVar(value=v) for k, v in SPIN_DEFAULTS.items()
            if k != "ice_mode"
        }
        self.gas_prep_spin_ice_mode_var = tk.BooleanVar(
            value=SPIN_DEFAULTS["ice_mode"] == "1"
        )
        self.gas_prep_spin_run_thread = None
        self.gas_prep_spin_cancel_event = threading.Event()
        self.gas_prep_spin_start_button = None
        self.gas_prep_spin_stop_button = None

        # DATAFILE auto-watch -- a self-rescheduling self.after() timer
        # (see _datafile_watch_tick) that polls SPEC for DATAFILE every
        # _DATAFILE_WATCH_INTERVAL_MS on its own, without needing
        # "Read from SPEC" or Run Scan to be clicked. On by default;
        # the checkbox next to "Read from SPEC" just pauses/resumes it
        # (see _on_toggle_datafile_watch) rather than starting/stopping
        # the underlying timer.
        self.datafile_watch_var = tk.BooleanVar(value=True)
        self._datafile_watch_thread = None
        self._datafile_watch_after_id = None
        self._last_watched_datafile = None

        # Raw command Send/STOP -- results come back on background
        # threads (SPEC calls block), which hand their Tk updates back
        # through this queue, polled by _run_tk_calls() on the Tk
        # thread -- same pattern spec_controller_gui.py uses.
        self._tk_calls = queue.Queue()
        self._send_busy = False
        # Most recently started background thread for a raw command
        # Send / STOP -- not used for any GUI logic, just lets tests
        # (and any future caller) wait for the in-flight call to
        # finish via .join() instead of guessing at a sleep duration.
        self._last_send_thread = None
        self._last_abort_thread = None
        self._last_read_globals_thread = None
        self._last_read_trigmode_thread = None
        # Same not-used-for-logic, just-so-tests-can-.join() role as
        # _last_abort_thread above, one per Spin Control Stop button
        # (see _on_spin_stop/_on_low_temp_spin_stop/
        # _on_gas_prep_spin_stop) -- per explicit user request, each
        # of these now also sends a real SPEC abort (like the raw
        # STOP button) so an in-flight `umv phi ...` move is
        # interrupted immediately instead of being allowed to finish
        # before the cancel_event check at the next loop iteration.
        self._last_spin_abort_thread = None
        self._last_low_temp_spin_abort_thread = None
        self._last_gas_prep_spin_abort_thread = None
        # "Read cycle/BTR from SPEC" button (see _on_read_nfs_cycle_btr)
        # -- same not-used-for-logic, just-so-tests-can-.join() role as
        # _last_read_globals_thread above.
        self._last_read_nfs_cycle_btr_thread = None

        # Cross-platform modern font selection -- the previous version
        # of this file hardcoded "Segoe UI" (a Windows-only font) and
        # "Consolas" (same) everywhere a font was set explicitly. On
        # this Linux/SPEC machine neither exists, so Tk was silently
        # substituting its own fallback, which is part of why the
        # fonts/spacing looked inconsistent. _pick_font_family() picks
        # the first available modern-looking font from a candidate
        # list (checked once, here, before any widget is built) and
        # otherwise falls back to Tk's own platform-correct default
        # font rather than a hardcoded name that might not exist.
        self.ui_font_family = self._pick_font_family(
            ["Inter", "Segoe UI", "Helvetica Neue", "Noto Sans",
             "DejaVu Sans", "Liberation Sans", "Arial"],
        )
        self.ui_mono_font_family = self._pick_font_family(
            ["Cascadia Code", "Consolas", "Menlo", "DejaVu Sans Mono",
             "Liberation Mono", "Courier New"],
            default_named_font="TkFixedFont",
        )

        self.current_theme = "dark"
        # Keeps every per-tab accent-color swatch tk.PhotoImage alive
        # for as long as its tab exists -- see
        # _apply_tab_accent_color's docstring for why this list has
        # to exist at all. Must exist before the first
        # _make_scrollable_tab call below (_build_main_notebook itself
        # makes no tabs; every _build_*_tab call after it does).
        self._tab_accent_images = []
        # Every scrollable tab's inner tk.Canvas (see
        # _make_scrollable_tab) -- plain tk widgets like Canvas aren't
        # covered by ttk's style system, so without tracking them here
        # and recoloring them in _apply_theme, each one stayed at Tk's
        # default canvas background (light gray/white) regardless of
        # theme, showing up as a mismatched rectangle behind every
        # single scrollable tab's content, especially jarring in dark
        # mode. Must exist before the first _make_scrollable_tab call,
        # same as _tab_accent_images above.
        self._scroll_canvases = []
        self._apply_theme()
        self._build_menu_bar()
        self._build_raw_command_section()
        # self.body_paned: a draggable vertical split between the tabs
        # area (self.main_notebook) and the shared Output section below
        # it, so the user can resize either one -- see
        # _build_main_notebook's docstring for why this replaced a
        # plain pack() (short version: tall tabs were squeezing Output
        # down to an unusable, unresizable sliver).
        self.body_paned = ttk.PanedWindow(self, orient="vertical")
        self.body_paned.pack(fill="both", expand=True, padx=0, pady=0)
        self._build_main_notebook()  # self.main_notebook: top-level tabs
        self._build_home_tab()  # 1st main tab (added first == listed first)
        self._build_sample_info_tab()  # 2nd main tab
        self._build_height_scan_tab()  # 3rd main tab
        self._build_scan_tab()  # 4th main tab: Global params / Passes / Controls
        self._build_powder_scan_tab()  # 5th main tab
        self._build_spin_tab()  # 6th main tab
        self._build_low_temp_tab()  # 7th main tab
        self._build_warmup_tab()  # 8th main tab
        self._build_warmup_custom_tab()  # 9th main tab
        self._build_cooldown_tab()  # 10th main tab
        self._build_hightemp_tab()  # 11th main tab
        self._build_gas_prep_tab()  # 12th main tab
        self._build_log_section()  # shared Output (Log / Python Script), below all
        self._apply_theme()  # re-apply now that log_text exists too

        for p in DEFAULT_PASSES:
            self._add_pass_row(p)

        self.after(150, self._set_initial_sash_position)
        self._poll_log()
        self.after(100, self._run_tk_calls)
        self._schedule_datafile_watch()
        self._schedule_n2_he_temp_watch()
        self._schedule_gas_prep_temp_watch()
        for _prefix, _label in STANDALONE_TEMP_FLOW_TABS:
            self._schedule_standalone_temp_watch(_prefix)

    # ---- shared widgets ----

    def _make_wrapping_label(self, parent, text, padx=8, pady=(10, 6)):
        """Create a ttk.Label whose wraplength tracks its own current
        width live, via <Configure>, instead of a fixed pixel value
        (the old `wraplength=830` on the Height Scan / Powder Scan
        tabs' description labels, which didn't respond to the window
        being resized -- the reported "not wrapping" bug). Every
        description-style label in this file (existing tabs and the
        new temperature/spin tabs) should be built through this
        helper so they all reflow correctly, including in the smaller
        default window size below."""
        lbl = ttk.Label(parent, text=text, justify="left")
        lbl.bind(
            "<Configure>",
            lambda e: lbl.configure(wraplength=max(200, e.width - 4)),
        )
        lbl.pack(fill="x", padx=padx, pady=pady)
        return lbl

    def _make_section(self, parent, title, color_index, fill="x", **pack_kwargs):
        """Build one visually-distinct "card" -- a thin colored
        accent stripe directly above a ttk.LabelFrame -- instead of a
        plain ttk.LabelFrame on its own. Added per explicit user
        request that panels (the Gas Prep tab most of all) were hard
        to tell apart at a glance; a flat, single-color LabelFrame
        border is subtle enough in both themes that a tab with many
        of them back-to-back reads as one undifferentiated block.
        `color_index` selects a color from _SECTION_ACCENT_COLORS
        (wrapping around via modulo, so any int is safe); callers
        pass a different index for each section on a tab so
        neighboring sections never share a color. Returns the
        ttk.LabelFrame itself -- pack every field/button for that
        section into the returned frame exactly as with a plain
        ttk.LabelFrame built directly.

        `fill`/`**pack_kwargs` are forwarded to the outer wrapper's
        own .pack() (defaulting to fill="x", same as most LabelFrames
        in this file); the colored stripe and the LabelFrame below it
        always fill the wrapper's own width."""
        color = _SECTION_ACCENT_COLORS[color_index % len(_SECTION_ACCENT_COLORS)]
        wrapper = ttk.Frame(parent)
        wrapper.pack(fill=fill, **pack_kwargs)

        stripe = tk.Frame(wrapper, height=3, bg=color, highlightthickness=0)
        stripe.pack(fill="x", side="top")

        box = ttk.LabelFrame(wrapper, text=title)
        box.pack(fill="x", side="top")
        return box

    # ---- concurrency guard (shared across all 10 scan-type tabs,
    # plus the N2 -> He Switch section living at the top of the Low
    # Temp Scan tab -- 11 registered scan-type threads in total) ----
    # Every long-running scan type in this window keeps its own named
    # background-thread attribute (self.<name>_thread, set up in
    # __init__ -- NOT a dict, so existing/new tests that reference
    # self.app.run_thread / .height_run_thread / .powder_run_thread by
    # name keep working unchanged). _other_scan_running() below
    # replaces what used to be hand-written pairwise
    # "if self.X_thread and self.X_thread.is_alive(): messagebox..."
    # blocks (3 tabs x 2 other tabs each, written out by hand) with
    # one generalized check, so it scales to 11 registered entries
    # (110 ordered pairs) without repeating that block dozens of
    # times. All 11 share the same underlying SPEC connection,
    # motors, detector and temperature controller, so only one may
    # run at a time regardless of which pair it is. (Low Temp Scan's
    # Sample Setup, Gas Prep's Set Temp/Flow Set/Flow Get, the
    # per-tab standalone Set Temp/Flow Control sections, and Low Temp
    # Scan's standalone Spin control are deliberately NOT registered
    # here -- per explicit user request, those quick one-click
    # actions must never block, or be blocked by, anything in this
    # registry; see _start_independent_job.)

    def _scan_thread_registry(self):
        return {
            "run_thread": "Run Scan",
            "height_run_thread": "Height Scan",
            "powder_run_thread": "Powder Scan",
            "spin_run_thread": "Spin Control",
            "low_temp_run_thread": "Low Temp Scan",
            "n2_he_switch_run_thread": "N2 -> He Switch",
            "warmup_run_thread": "Warmup",
            "warmup_custom_run_thread": "Warmup Custom",
            "cooldown_run_thread": "Cooldown",
            "hightemp_run_thread": "High Temp Scan",
            "gas_prep_run_thread": "Gas Prep Macros",
        }

    def _other_scan_running(self, this_attr, this_label):
        """Return True (and pop up a warning naming the culprit) if
        some OTHER scan-type thread is currently alive. Callers should
        check their own thread first (`if self.X_thread and
        self.X_thread.is_alive(): return`, silently, same as before)
        before calling this."""
        for attr, label in self._scan_thread_registry().items():
            if attr == this_attr:
                continue
            thread = getattr(self, attr, None)
            if thread and thread.is_alive():
                messagebox.showwarning(
                    this_label,
                    f"A {label} is currently running -- wait for it to "
                    f"finish before starting {this_label} (they share "
                    "the same motors, detector, and temperature "
                    "controller through one SPEC connection).",
                )
                return True
        return False

    # ---- theme ----

    def _build_menu_bar(self):
        menubar = tk.Menu(self)
        view_menu = tk.Menu(menubar, tearoff=0)
        theme_menu = tk.Menu(view_menu, tearoff=0)

        self.theme_var = tk.StringVar(value=self.current_theme)
        theme_menu.add_radiobutton(
            label="Dark", variable=self.theme_var, value="dark",
            command=lambda: self._apply_theme("dark"),
        )
        theme_menu.add_radiobutton(
            label="Light", variable=self.theme_var, value="light",
            command=lambda: self._apply_theme("light"),
        )
        view_menu.add_cascade(label="Theme", menu=theme_menu)
        menubar.add_cascade(label="View", menu=view_menu)
        self.config(menu=menubar)

    def _pick_font_family(self, candidates, default_named_font="TkDefaultFont"):
        """Returns the first font family in `candidates` that's actually
        installed, or Tk's own platform-appropriate default font family
        (via `default_named_font`, one of Tk's built-in named fonts) if
        none are. Used once in __init__ to pick self.ui_font_family /
        self.ui_mono_font_family, replacing this file's old hardcoded
        "Segoe UI" / "Consolas" (both Windows-only fonts that silently
        fall back to whatever Tk feels like on Linux/macOS -- part of
        why the GUI looked inconsistent on this SPEC machine)."""
        try:
            available = set(tkfont.families(self))
        except Exception:
            available = set()
        for name in candidates:
            if name in available:
                return name
        try:
            return tkfont.nametofont(default_named_font).actual("family")
        except Exception:
            return "Helvetica"

    def _apply_theme(self, name=None):
        if name is not None:
            self.current_theme = name
            if hasattr(self, "theme_var"):
                self.theme_var.set(name)
        t = THEMES[self.current_theme]
        body_font = (self.ui_font_family, 10)
        bold_font = (self.ui_font_family, 10, "bold")
        mono_font = (self.ui_mono_font_family, 10)

        self.configure(bg=t["bg"])

        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except Exception:
            pass

        style.configure(
            ".", background=t["bg"], foreground=t["fg"],
            fieldbackground=t["entry_bg"], bordercolor=t["border"],
            font=body_font,
        )
        style.configure("TFrame", background=t["bg"])
        # LabelFrame: flat 1px border + a bit of internal padding so
        # every section box on every tab gets consistent breathing
        # room around its contents, instead of the previous
        # edge-to-edge, slightly cramped look.
        style.configure(
            "TLabelframe", background=t["bg"], foreground=t["fg"],
            bordercolor=t["border"], borderwidth=1, relief="solid",
            padding=(10, 8),
        )
        style.configure(
            "TLabelframe.Label", background=t["bg"], foreground=t["accent"],
            font=bold_font,
        )
        style.configure("TLabel", background=t["bg"], foreground=t["fg"])
        style.configure(
            "TEntry", fieldbackground=t["entry_bg"], foreground=t["fg"],
            insertcolor=t["fg"], bordercolor=t["border"],
            borderwidth=1, relief="flat", padding=4,
        )
        style.map(
            "TEntry",
            bordercolor=[("focus", t["accent"])],
            lightcolor=[("focus", t["accent"])],
            darkcolor=[("focus", t["accent"])],
        )
        style.configure(
            "TSpinbox", fieldbackground=t["entry_bg"], foreground=t["fg"],
            background=t["entry_bg"], arrowcolor=t["fg"],
            bordercolor=t["border"], borderwidth=1, relief="flat",
            padding=4,
        )
        style.configure(
            "TButton", background=t["button_bg"], foreground=t["fg"],
            bordercolor=t["border"], focuscolor=t["bg"], borderwidth=1,
            relief="flat", padding=(10, 6),
        )
        style.map(
            "TButton",
            background=[("active", t["button_hover"]), ("pressed", t["button_hover"])],
        )
        style.configure(
            "Accent.TButton", background=t["accent"], foreground=t["accent_fg"],
            borderwidth=0, relief="flat", padding=(10, 6), font=bold_font,
        )
        style.map(
            "Accent.TButton",
            background=[("active", t["accent_hover"]), ("pressed", t["accent_hover"])],
        )
        style.configure(
            "Stop.TButton", background=t["stop"], foreground=t["stop_fg"],
            borderwidth=0, relief="flat", padding=(10, 8), font=bold_font,
        )
        style.map(
            "Stop.TButton",
            background=[("active", t["stop_hover"]), ("pressed", t["stop_hover"])],
        )
        # Slim, flat, modern scrollbars (no arrows, just a colored
        # thumb) instead of the previous theme-mismatched default.
        style.configure(
            "TScrollbar", background=t["scroll_thumb"], troughcolor=t["scroll_trough"],
            bordercolor=t["scroll_trough"], arrowcolor=t["fg"],
            borderwidth=0, relief="flat", arrowsize=12, gripcount=0,
        )
        style.map(
            "TScrollbar",
            background=[("active", t["scroll_thumb_hover"]), ("pressed", t["scroll_thumb_hover"])],
        )
        style.configure(
            "TCheckbutton", background=t["bg"], foreground=t["fg"],
            focuscolor=t["bg"], font=body_font,
        )
        style.map(
            "TCheckbutton",
            indicatorcolor=[("selected", t["accent"]), ("!selected", t["entry_bg"])],
            foreground=[("active", t["fg"])],
        )
        # Combobox: the previous theme left this entirely unstyled, so
        # the Detector Trigger Mode dropdown kept its generic clam
        # colors (a light field) even in dark mode. fieldbackground is
        # set for both the normal and "readonly" states explicitly,
        # since clam's own default readonly-state color would
        # otherwise override the base fieldbackground above.
        style.configure(
            "TCombobox", fieldbackground=t["entry_bg"], background=t["button_bg"],
            foreground=t["fg"], arrowcolor=t["fg"], bordercolor=t["border"],
            borderwidth=1, relief="flat", padding=4,
        )
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", t["entry_bg"]), ("disabled", t["bg"])],
            foreground=[("readonly", t["fg"]), ("disabled", t["border"])],
            selectbackground=[("readonly", t["entry_bg"])],
            selectforeground=[("readonly", t["fg"])],
        )
        # The Combobox dropdown list itself is a plain (non-ttk) Tk
        # Listbox, so it's only reachable via the option database, not
        # style.configure -- without this it would keep showing up
        # with a plain white background/black text no matter the
        # theme.
        self.option_add("*TCombobox*Listbox.background", t["entry_bg"])
        self.option_add("*TCombobox*Listbox.foreground", t["fg"])
        self.option_add("*TCombobox*Listbox.selectBackground", t["accent"])
        self.option_add("*TCombobox*Listbox.selectForeground", t["accent_fg"])
        self.option_add("*TCombobox*Listbox.font", body_font)
        # Top-level tab bar: flat, muted-text unselected tabs, brighter
        # selected tab -- previously completely unstyled, so it used
        # clam's generic (theme-mismatched) tab colors.
        style.configure(
            "TNotebook", background=t["bg"], borderwidth=0,
        )
        style.configure(
            "TNotebook.Tab", background=t["tab_bg"], foreground=t["tab_fg"],
            padding=(12, 6), font=body_font, borderwidth=0,
        )
        style.map(
            "TNotebook.Tab",
            background=[("selected", t["tab_selected_bg"]), ("active", t["button_hover"])],
            foreground=[("selected", t["tab_selected_fg"])],
            font=[("selected", bold_font)],
        )
        # The draggable splitter between the tabs area and the Output
        # section (self.body_paned) -- previously an unthemed default
        # gray sash line in both themes.
        style.configure(
            "TPanedwindow", background=t["bg"],
        )

        if hasattr(self, "log_text"):
            self.log_text.configure(
                bg=t["log_bg"], fg=t["log_fg"], insertbackground=t["fg"],
                font=mono_font,
            )
            # Keep the "alert" tag's color matched to this theme's own
            # red "stop" accent (see _build_log_section) rather than
            # leaving it frozen at whichever theme was active when
            # the Text widget was first created.
            self.log_text.tag_configure(
                "alert", foreground=t["stop"],
                font=(self.ui_mono_font_family, 10, "bold"),
            )
        if hasattr(self, "script_text"):
            self.script_text.configure(
                bg=t["log_bg"], fg=t["log_fg"], insertbackground=t["fg"],
                font=mono_font,
            )
        # Every scrollable tab's inner Canvas -- see _scroll_canvases'
        # docstring in __init__ for why this is needed at all (plain
        # tk widgets aren't covered by the ttk style system above).
        for canvas in getattr(self, "_scroll_canvases", []):
            canvas.configure(bg=t["bg"])

    # ---- UI construction ----

    def _build_raw_command_section(self):
        """Type any raw SPEC command and Send it, or hit STOP to abort
        whatever SPEC is currently running (like ^C at the console) --
        ported from spec_controller_gui.py's SpecGui. Results are
        written to the same "Log" tab used by Preview/Run, so
        everything that happened in a session shows up in one place.

        Also hosts a mirrored Open/Close Shutter button (see the
        shutter_row below) -- per explicit request, so the shutter can
        be toggled from here without first switching to the Threextal
        Scan tab, exactly like this whole box (and the STOP button in
        it) is already reachable no matter which tab is showing."""
        box = ttk.LabelFrame(self, text="Raw SPEC command")
        box.pack(fill="x", padx=10, pady=(8, 0))

        entry_row = ttk.Frame(box)
        entry_row.pack(fill="x", padx=8, pady=(6, 4))

        self.command_var = tk.StringVar()
        self.command_entry = ttk.Entry(entry_row, textvariable=self.command_var)
        self.command_entry.pack(side="left", fill="x", expand=True)
        self.command_entry.bind("<Return>", lambda event: self._send_command())
        self.command_entry.focus_set()

        self.send_button = ttk.Button(
            entry_row, text="Send", command=self._send_command
        )
        self.send_button.pack(side="left", padx=(4, 0))

        self.stop_button = ttk.Button(
            box, text="STOP (abort current SPEC command)",
            command=self._stop_command, style="Stop.TButton",
        )
        self.stop_button.pack(fill="x", padx=8, pady=(0, 8))

        # Mirrored shutter control -- see self.shutter_buttons'
        # docstring in __init__ and _on_toggle_shutter, which keeps
        # this button and the Threextal Scan tab's own copy in sync.
        shutter_row = ttk.Frame(box)
        shutter_row.pack(fill="x", padx=8, pady=(0, 8))
        ttk.Label(
            shutter_row,
            text="Shutter (same control as the Threextal Scan tab):",
        ).pack(side="left")
        self.shutter_button_top = ttk.Button(
            shutter_row, text="Open Shutter", command=self._on_toggle_shutter
        )
        self.shutter_button_top.pack(side="left", padx=(6, 0))
        self.shutter_buttons.append(self.shutter_button_top)

    def _build_globals_section(self, parent):
        """Threextal Scan's own "Global parameters" box -- the 7
        fields specific to the threextalscan sequence itself
        (Temperature, Wait after temp set, Num flyscan steps, Count
        time, Final chi/th/phi). The other 5 original fields here
        (DATAFILE, Sample name, Detector path prefix, Detector
        trigger mode, Next scan number) moved to their own "Sample
        Information" tab -- see _build_sample_info_tab -- since
        they're shared/used across most other tabs (Height Scan,
        Powder Scan, Low Temp Scan, Warmup, Warmup Custom, Cooldown,
        High Temp Scan, Gas Prep Macros) too, rather than being
        Threextal-Scan-specific like the 7 fields that stayed here.
        Both tabs read/write the exact same self.global_vars
        StringVars dict either way -- nothing here is a new or
        duplicated variable, so this split is purely about which tab
        a field is displayed on, not a change to the underlying data
        model."""
        box = ttk.LabelFrame(parent, text="Global parameters")
        box.pack(fill="x", padx=10, pady=8)

        fields = [
            ("temperature", "Temperature ($1)"),
            ("wait_seconds", "Wait after temp set, s ($2)"),
            ("num_steps", "Num flyscan steps"),
            ("count_time", "Count time, s"),
            ("final_chi", "Final chi"),
            ("final_th", "Final th"),
            ("final_phi", "Final phi"),
        ]

        for i, (key, label) in enumerate(fields):
            row, col = divmod(i, 2)
            frame = ttk.Frame(box)
            frame.grid(row=row, column=col, sticky="w", padx=8, pady=4)
            ttk.Label(frame, text=label + ":", width=26, anchor="w").pack(side="left")
            ttk.Entry(frame, textvariable=self.global_vars[key], width=22).pack(
                side="left"
            )

    def _build_home_tab(self):
        """1st main-notebook tab (added first == listed first, before
        Sample Information) -- a plain-language overview of what this
        window is and how to use it, per explicit request ("better
        home page with description"). Purely descriptive: it reads no
        state and has no buttons of its own, other than a couple of
        Notebook.select() shortcuts into the tabs it mentions, so
        there's nothing here that duplicates or could drift out of
        sync with the real controls living on every other tab."""
        tab = self._make_scrollable_tab("Home")

        title = ttk.Label(
            tab, text="HDRM Scan + SPEC GUI",
            font=(self.ui_font_family, 14, "bold"),
        )
        title.pack(anchor="w", padx=10, pady=(10, 0))
        data_collection = ttk.Label(
            tab,
            text=f"Data Collection: {self.controller.spec_host} {self.controller.spec_port}",
            font=(self.ui_font_family, 10, "bold"),
        )
        data_collection.pack(anchor="w", padx=10, pady=(2, 0))
        self._make_wrapping_label(
            tab,
            f"Connected to {self.controller.spec_host}:{self.controller.spec_port}. "
            "This window merges a raw SPEC command console with the full set of "
            "HDRM three-crystal beamline scan workflows below, all sharing this "
            "one live SPEC connection.",
            pady=(2, 10),
        )

        overview = ttk.LabelFrame(tab, text="What's always on screen")
        overview.pack(fill="x", padx=10, pady=8)
        self._make_wrapping_label(
            overview,
            "\u2022 Raw SPEC command (top of the window, every tab): type any SPEC "
            "command and Send it, or hit STOP to abort whatever SPEC is currently "
            "doing (like Ctrl+C at the SPEC console). The Shutter button next to it "
            "opens/closes the beam shutter directly -- it's the same control as the "
            "one on the Threextal Scan tab, kept in sync with it.\n"
            "\u2022 Output (bottom of the window, every tab): the Log tab shows "
            "every command sent and its response, from every source (Preview, Run, "
            "the raw command box, Shutter, auto-watch timers); the Python Script "
            "tab shows the equivalent scan as a standalone Python script. Drag the "
            "divider above it up or down to give either area more room.",
            pady=(4, 8),
        )

        tabs_box = ttk.LabelFrame(tab, text="Tabs at a glance")
        tabs_box.pack(fill="x", padx=10, pady=8)
        self._make_wrapping_label(
            tabs_box,
            "\u2022 Sample Information -- DATAFILE, sample name, detector path/"
            "trigger mode, next scan number, and (see below) where this run's "
            "data actually lands on disk. Fill this in first -- almost every "
            "other tab reads it.\n"
            "\u2022 Height Scan / Threextal Scan / Powder Scan / Spin Control -- "
            "independent scan workflows, each with its own Preview Log (simulates "
            "the command sequence, touches no hardware) and Run Scan (sends it "
            "for real).\n"
            "\u2022 Low Temp Scan / Warmup / Warmup Custom / Cooldown / High Temp "
            "Scan -- temperature-series workflows, each with a Stop button for a "
            "long-running sequence. Low Temp Scan also has the N2 -> He Gas "
            "Switch section.\n"
            "\u2022 Gas Prep Macros -- the individual gas/temperature-prep macros "
            "(prepN2_low/medium/high, prepswitch, runninghelium, roomT, highT) as "
            "one-off buttons, plus live Stage A/Stage C/sample temperature "
            "readback.\n\n"
            "Only one scan-type workflow can run at a time -- starting a second "
            "one while another is active is blocked with a message naming which "
            "one is currently running.",
            pady=(4, 8),
        )

        quickstart = ttk.LabelFrame(tab, text="Quick start")
        quickstart.pack(fill="x", padx=10, pady=8)
        self._make_wrapping_label(
            quickstart,
            "1. Open the Sample Information tab and fill in DATAFILE, Sample name "
            "(a trailing / is added automatically), and the other fields, or click "
            "\"Read from SPEC\" to pull DATAFILE from the live session.\n"
            "2. Pick a scan tab and fill in its parameters.\n"
            "3. Click Preview Log to check the exact command sequence before "
            "anything touches real hardware.\n"
            "4. Click Run Scan (or the tab's equivalent Start/Run button) when "
            "you're satisfied with the preview.\n"
            "5. Watch progress in the Log tab below, or Cancel/Stop if you need "
            "to interrupt it at the next safe checkpoint.",
            pady=(4, 8),
        )

        go_row = ttk.Frame(tab)
        go_row.pack(fill="x", padx=10, pady=(0, 12))
        ttk.Button(
            go_row, text="Go to Sample Information",
            command=lambda: self._select_tab_by_title("Sample Information"),
        ).pack(side="left")

    def _select_tab_by_title(self, title):
        """Selects the main-notebook tab whose displayed text matches
        `title` exactly -- used by the Home tab's shortcut button(s)
        instead of hard-coding a tab index, so it keeps working even
        if tabs are reordered/added/removed later."""
        for tab_id in self.main_notebook.tabs():
            if self.main_notebook.tab(tab_id, "text") == title:
                self.main_notebook.select(tab_id)
                return

    def _build_sample_info_tab(self):
        """2nd main-notebook tab (after Home, before Height Scan) --
        holds 5 of the 12 original "Global
        parameters" fields: DATAFILE, Sample name, Detector path
        prefix ('rampre'), Detector trigger mode, and Next scan
        number. These describe *where images/data go and which
        sample is being run*, and are read/used by nearly every other
        tab (Height Scan, Powder Scan, Low Temp Scan, Warmup, Warmup
        Custom, Cooldown, High Temp Scan, Gas Prep Macros all share
        'rampre' and/or 'datafile'/'sample'; see each tab's own
        docstring) -- unlike the remaining 7 fields (Temperature,
        Wait after temp set, Num flyscan steps, Count time, Final
        chi/th/phi), which are specific to the threextalscan sequence
        and stayed on the Threextal Scan tab (_build_globals_section).

        Split out into its own tab per user request, purely as a
        display/organization change -- these are still backed by the
        exact same self.global_vars StringVars dict as before, so
        editing a field here is the exact same action (on the exact
        same underlying value) as editing it used to be inside the
        Threextal Scan tab's Global parameters box. Nothing about
        self.global_vars itself, or any other tab's use of it, is
        touched by this split.

        The "Read from SPEC" button, "Auto-watch DATAFILE" checkbox,
        and "Read from EPICS" (trigger mode) button move here too,
        since they only ever touch 'datafile' (_SPEC_READ_COMMANDS
        has exactly one entry) and 'trig_mode' respectively -- both
        now on this tab -- and never touch any of the 7 fields that
        stayed on Threextal Scan."""
        tab = self._make_scrollable_tab("Sample Information")
        box = ttk.LabelFrame(tab, text="Global parameters")
        box.pack(fill="x", padx=10, pady=8)

        top_row = ttk.Frame(box)
        top_row.grid(row=0, column=0, columnspan=2, sticky="w", padx=8, pady=(4, 0))
        self.read_globals_button = ttk.Button(
            top_row, text="Read from SPEC", command=self._on_read_globals
        )
        self.read_globals_button.pack(side="left")
        ttk.Label(
            top_row,
            text="  (sends " + ", ".join(_SPEC_READ_COMMANDS.values())
            + " to the connected SPEC session)",
        ).pack(side="left")
        self.datafile_watch_check = ttk.Checkbutton(
            top_row,
            text=f"Auto-watch DATAFILE (every {_DATAFILE_WATCH_INTERVAL_MS // 1000}s)",
            variable=self.datafile_watch_var,
            command=self._on_toggle_datafile_watch,
        )
        self.datafile_watch_check.pack(side="left", padx=(16, 0))

        cycle_btr_row = ttk.Frame(box)
        # Own grid row (1), directly below top_row (row 0) and above
        # the individual field rows (which start at row 2 below, one
        # row lower than before, to make room) -- keeps this button
        # visually grouped with "Read from SPEC" above, right next to
        # the nfs_cycle/nfs_btr fields it fills in just underneath.
        cycle_btr_row.grid(row=1, column=0, columnspan=2, sticky="w", padx=8, pady=(4, 0))
        # Second, separate button+row (not merged into top_row above)
        # specifically because this sends a *different* SPEC
        # expression ("CWD") than "Read from SPEC" does ("DATAFILE")
        # -- see _on_read_nfs_cycle_btr's docstring and
        # hrdm_core.parse_nfs_cwd for the full story. Added per
        # explicit request ("NSF cycle information is wrong .. can
        # you take that somehow correct?", clarified to "autograb
        # from some file for cycle not sure how") -- rather than just
        # editing DEFAULT_GLOBALS['nfs_cycle']'s stale hardcoded
        # string (which would just go stale again next cycle), this
        # reads SPEC's own live CWD and parses the cycle/BTR out of
        # it, since SPEC's CWD already *is* that NFS path once it's
        # cd'd into a real beamtime directory.
        self.read_nfs_cycle_btr_button = ttk.Button(
            cycle_btr_row,
            text="Read cycle/BTR from SPEC",
            command=self._on_read_nfs_cycle_btr,
        )
        self.read_nfs_cycle_btr_button.pack(side="left")
        ttk.Label(
            cycle_btr_row,
            text="  (sends CWD to the connected SPEC session and parses"
            " the cycle/BTR out of it)",
        ).pack(side="left")

        fields = [
            ("datafile", "DATAFILE"),
            ("sample", "Sample name (trailing /)"),
            ("rampre", "Detector path prefix (_rampre, ramdisk path -- set manually)"),
            ("nfs_cycle", "NFS cycle (e.g. 2026-2)"),
            ("nfs_btr", "NFS BTR / proposal (e.g. sarker-4910-a)"),
            ("trig_mode", "Detector trigger mode"),
            ("next_scan_n", "Next scan number (SCAN_N)"),
        ]

        for i, (key, label) in enumerate(fields):
            row, col = divmod(i, 2)
            frame = ttk.Frame(box)
            # row + 2, not row + 1: row 0 is top_row ("Read from
            # SPEC"), row 1 is cycle_btr_row ("Read cycle/BTR from
            # SPEC") added just above.
            frame.grid(row=row + 2, column=col, sticky="w", padx=8, pady=4)
            ttk.Label(frame, text=label + ":", width=26, anchor="w").pack(side="left")
            if key == "trig_mode":
                # Locked to the 2 modes actually used here (Internal,
                # Mult. Trigger) -- see TRIGGER_MODE_STATES in
                # hrdm_core.py. "Read from EPICS" fills this in live
                # from the PIL10:cam1:TriggerMode_RBV PV directly; it's
                # independent of the SPEC connection above.
                self.trig_mode_combo = ttk.Combobox(
                    frame,
                    textvariable=self.global_vars[key],
                    values=TRIGGER_MODE_STATES,
                    state="readonly",
                    width=14,
                )
                self.trig_mode_combo.pack(side="left")
                self.read_trigmode_button = ttk.Button(
                    frame, text="Read from EPICS", command=self._on_read_trigger_mode
                )
                self.read_trigmode_button.pack(side="left", padx=(4, 0))
            elif key == "sample":
                # Every downstream path is built as
                # mysamplepath + mysample + ... (see Runner.run,
                # run_height_scan, run_powder_scan in hrdm_core.py),
                # which assumes 'sample' already ends in "/" --
                # exactly like the original macro's own "DONOT FORGET
                # TO PUT SLASH" comment warns. Auto-appending it here
                # on focus-out (rather than on every keystroke, which
                # would fight the user while they're still typing)
                # means the field always ends up path-safe without
                # anyone having to remember to type the slash by hand.
                sample_entry = ttk.Entry(
                    frame, textvariable=self.global_vars[key], width=22
                )
                sample_entry.pack(side="left")
                sample_entry.bind("<FocusOut>", self._on_sample_focus_out)
            elif key in ("nfs_cycle", "nfs_btr"):
                # Two separate short fields -- rather than one
                # free-text NFS path -- specifically so switching
                # beamtime cycles/proposals is picking a cycle and a
                # BTR, not hand-editing an opaque absolute path (see
                # DEFAULT_GLOBALS["nfs_cycle"]/["nfs_btr"]'s comment in
                # hrdm_core.py and _build_data_locations_section just
                # below this method for what these feed into --
                # hrdm_core.resolve_data_dirs() combines them into
                # "/nfs/chess/id4b/{cycle}/{btr}/").
                ttk.Entry(
                    frame, textvariable=self.global_vars[key], width=20
                ).pack(side="left")
            else:
                ttk.Entry(frame, textvariable=self.global_vars[key], width=22).pack(
                    side="left"
                )

        self._build_data_locations_section(tab)

    def _build_data_locations_section(self, parent):
        """"Data locations" box on the Sample Information tab -- shows
        where this run's data actually lands on disk, per explicit
        request ("Check the final data collection and data save
        folder .. mention that to the sample information where you
        can see the files if you navigate, put the accesible link to
        the Sample information"). Two read-only, plain display-only
        fields (self.raw_sample_dir_var / processed_dir_var, kept
        live-updated by _refresh_data_dirs -- see its trace_add wiring
        in __init__): just the resolved path text, no Open/Copy
        buttons and no per-scan "next scan's image folder" row -- a
        later request asked for exactly this pared-down view (only
        Raw + Processed, visible only, not editable, no buttons), so
        the earlier 3-row/Open+Copy-button version was simplified down
        to this.

        Built from hrdm_core.resolve_data_dirs(), which mirrors --
        without duplicating -- the exact same relative-path
        construction Runner.run()/run_height_scan()/run_powder_scan()
        already use (see that function's own docstring for the full
        explanation and the real example paths it was confirmed
        against). resolve_data_dirs() still computes a next_scan_dir
        value too (used elsewhere, e.g. the naming-convention
        verification in README.md and its own tests) -- it's just no
        longer displayed here."""
        box = ttk.LabelFrame(
            parent,
            text="Data locations (where this run's files actually land)",
        )
        box.pack(fill="x", padx=10, pady=8)

        self._make_wrapping_label(
            box,
            "Computed from DATAFILE / Sample name / Temperature above, plus "
            "\"NFS cycle\" and \"NFS BTR / proposal\" -- fill those in (see the "
            "fields above) if the paths below still look like a bare "
            "\"raw6M/...\" with no /nfs/... prefix. To switch to a different "
            "beamtime, just change the cycle and/or BTR fields above; the paths "
            "below update automatically -- they're shown for reference only, "
            "not editable directly.",
            pady=(4, 6),
        )

        rows = [
            (
                "Raw sample directory\n(all scans at this sample/temp)",
                self.raw_sample_dir_var,
            ),
            ("Processed directory (nxrefine)", self.processed_dir_var),
        ]
        for label_text, var in rows:
            row = ttk.Frame(box)
            row.pack(fill="x", padx=8, pady=4)
            ttk.Label(row, text=label_text + ":", width=26, anchor="w").pack(
                side="left"
            )
            entry = ttk.Entry(row, textvariable=var, state="readonly", width=48)
            entry.pack(side="left", fill="x", expand=True, padx=(0, 4))

    def _refresh_data_dirs(self, *_trace_args):
        """Recomputes raw_sample_dir_var / processed_dir_var from the
        current Sample Information field values, via
        hrdm_core.resolve_data_dirs(). Bound (see __init__) as a
        trace_add("write", ...) callback on every global_vars entry
        these two displayed paths actually depend on (nfs_cycle,
        nfs_btr, datafile, sample, temperature), so they stay
        live/current with no separate "Refresh" button needed --
        *_trace_args absorbs the (varname, index, mode) arguments Tk
        passes to trace callbacks, which this method has no use for."""
        g = {k: v.get() for k, v in self.global_vars.items()}
        dirs = resolve_data_dirs(g)
        self.raw_sample_dir_var.set(dirs["raw_sample_dir"])
        self.processed_dir_var.set(dirs["processed_dir"])

    def _open_in_file_manager(self, path):
        """Reveals `path` in the host OS's file manager (Explorer on
        Windows, Finder on macOS, or whatever handles `xdg-open` on
        Linux) -- originally the "accesible link ... where you can see
        the files if you navigate" requested for the Data locations
        section above. Not currently wired to any button there (a
        later request pared that section down to plain read-only path
        text, no Open/Copy buttons) -- kept as a standalone, tested
        utility in case a future request wants it back. Does nothing
        destructive: this only ever asks the OS to *open/display* the
        folder, the same as double-clicking it -- it never reads,
        writes, or deletes anything inside it.

        Deliberately tolerant of failure (missing/unmounted path,
        `xdg-open` not installed, headless environment, ...) -- logs a
        clear message to the Log tab instead of raising, since this is
        a convenience feature and a failure here should never look
        like a scan/connection error."""
        path = (path or "").strip()
        if not path:
            self._append_log("[open folder] no path to open yet.")
            return
        if not os.path.isdir(path):
            self._append_log(
                f"[open folder] {path!r} doesn't exist (yet) or isn't reachable "
                "from this machine -- check that the NFS share is mounted here, "
                "or that a scan has actually run to create it."
            )
            return
        try:
            if sys.platform.startswith("win"):
                os.startfile(path)  # noqa: this branch only runs on Windows
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
            self._append_log(f"[open folder] {path}")
        except Exception as exc:
            self._append_log(f"[open folder] could not open {path!r}: {exc}")

    def _copy_path_to_clipboard(self, path):
        """Copies `path` to the system clipboard -- originally useful
        when the Data locations paths above weren't reachable from
        this machine as a local folder (e.g. no NFS mount here), so
        the user could paste them into a terminal/ssh session or
        another tool instead. Not currently wired to any button there
        (see _open_in_file_manager's docstring) -- kept as a
        standalone, tested utility. Never raises -- clipboard access
        can fail in headless/test environments, and that's not worth
        surfacing as an error."""
        path = (path or "").strip()
        if not path:
            return
        try:
            self.clipboard_clear()
            self.clipboard_append(path)
            self._append_log(f"[copy path] copied to clipboard: {path}")
        except tk.TclError as exc:
            self._append_log(f"[copy path] could not access the clipboard: {exc}")

    def _on_sample_focus_out(self, event=None):
        """Auto-append a trailing '/' to the Sample Information tab's
        'sample' field when the user tabs/clicks away from it, if
        it's non-empty and doesn't already end in one. Every path
        built downstream from 'sample' (mysamplepath + mysample +
        ..., in Runner.run/run_height_scan/run_powder_scan/etc.)
        assumes the trailing slash is already there -- exactly what
        HRDM.mac's own sortmypathout comment warns about ("DONOT
        FORGET TO PUT SLASH"). This makes that no longer something
        the user has to remember by hand. Deliberately does nothing
        for an empty field -- _validate_globals()/validate_globals()
        already raise a clear "Sample name cannot be empty" error for
        that case, and silently turning "" into "/" would be worse
        (a bare slash is not a useful sample name)."""
        value = self.global_vars["sample"].get()
        if value and not value.endswith("/"):
            self.global_vars["sample"].set(value + "/")

    def _build_passes_section(self, parent):
        box = ttk.LabelFrame(parent, text="Passes (chi / th / phi position, then flyscan phi start->stop)")
        box.pack(fill="x", padx=10, pady=8)

        header = ttk.Frame(box)
        header.pack(fill="x", pady=(2, 4))
        for text, width in (
            ("Chi", 8), ("Th", 8), ("Phi", 8), ("Scan start", 10), ("Scan stop", 10)
        ):
            ttk.Label(header, text=text, width=width).pack(side="left", padx=3)

        self.passes_container = ttk.Frame(box)
        self.passes_container.pack(fill="x")

        row_controls = ttk.Frame(box)
        row_controls.pack(fill="x", pady=4)

        ttk.Button(row_controls, text="+ Add pass", command=self._add_pass_row).pack(
            side="left"
        )

        ttk.Label(row_controls, text="   Number of passes:").pack(side="left")
        self.num_passes_var = tk.StringVar(value=str(len(DEFAULT_PASSES)))
        ttk.Spinbox(
            row_controls, from_=1, to=50, width=5, textvariable=self.num_passes_var
        ).pack(side="left", padx=4)
        ttk.Button(
            row_controls,
            text="Set",
            command=lambda: self._set_num_passes(self.num_passes_var.get()),
        ).pack(side="left")

    def _build_hdrm_scan_params_section(self, parent, num_steps_var, count_time_var):
        """Builds the "HDRM Scan Parameters" section used by each of
        the 5 temperature-series tabs below (Low Temp Scan, Warmup,
        Warmup Custom, Cooldown, High Temp Scan) -- an editable passes
        table (chi/th/phi/scan start/stop, identical layout to
        _build_passes_section above) plus "Number of flyscan steps"
        and "Count time" fields, exposing the full HDRM scan that each
        temperature step runs (previously hard-coded inside
        Runner._threextalscan_step as `_HDRM_NEW_PASSES`/
        `_HDRM_NEW_NUM_STEPS`, with count_time silently shared from
        the Threextal Scan tab's own Global parameters). Each tab gets
        its own independent copy -- defaulted to
        HDRM_SCAN_PASSES_DEFAULTS/HDRM_SCAN_DEFAULTS, but never shared
        with the Threextal Scan tab or with each other (except Warmup,
        whose 3 phases all share the one set on that tab, matching how
        the macro itself never varies the scan step by phase either).
        Returns the PassesTableController managing this section's
        passes -- callers should keep it (e.g.
        self.low_temp_passes_table) to call .get()/.reset_to_defaults()
        from their Preview/Run/Reset handlers."""
        box = ttk.LabelFrame(
            parent,
            text="HDRM Scan Parameters (full HDRM scan run at each temperature step)",
        )
        box.pack(fill="x", padx=8, pady=8)

        header = ttk.Frame(box)
        header.pack(fill="x", pady=(2, 4))
        for text, width in (
            ("Chi", 8), ("Th", 8), ("Phi", 8), ("Scan start", 10), ("Scan stop", 10)
        ):
            ttk.Label(header, text=text, width=width).pack(side="left", padx=3)

        container = ttk.Frame(box)
        container.pack(fill="x")

        num_passes_var = tk.StringVar(value=str(len(HDRM_SCAN_PASSES_DEFAULTS)))
        controller = PassesTableController(container, HDRM_SCAN_PASSES_DEFAULTS, num_passes_var)
        for p in HDRM_SCAN_PASSES_DEFAULTS:
            controller.add_row(p)

        row_controls = ttk.Frame(box)
        row_controls.pack(fill="x", pady=4)
        ttk.Button(
            row_controls, text="+ Add pass", command=lambda: controller.add_row()
        ).pack(side="left")
        ttk.Label(row_controls, text="   Number of passes:").pack(side="left")
        ttk.Spinbox(
            row_controls, from_=1, to=50, width=5, textvariable=num_passes_var
        ).pack(side="left", padx=4)
        ttk.Button(
            row_controls, text="Set",
            command=lambda: controller.set_num_passes(num_passes_var.get()),
        ).pack(side="left")

        steps_row = ttk.Frame(box)
        steps_row.pack(fill="x", pady=(6, 2))
        ttk.Label(steps_row, text="Number of flyscan steps:").pack(side="left")
        ttk.Entry(steps_row, textvariable=num_steps_var, width=10).pack(
            side="left", padx=(4, 18)
        )
        ttk.Label(steps_row, text="Count time, s:").pack(side="left")
        ttk.Entry(steps_row, textvariable=count_time_var, width=10).pack(
            side="left", padx=4
        )

        return controller

    def _build_controls_section(self, parent):
        box = ttk.Frame(parent)
        box.pack(fill="x", padx=10, pady=6)

        ttk.Button(box, text="Preview Log", command=self._on_preview).pack(
            side="left", padx=4
        )

        self.run_button = ttk.Button(
            box, text="Run Scan", command=self._on_run, style="Accent.TButton"
        )
        self.run_button.pack(side="left", padx=4)

        self.cancel_button = ttk.Button(
            box, text="Cancel", command=self._on_cancel, state="disabled"
        )
        self.cancel_button.pack(side="left", padx=4)

        # Manual shutter control -- independent of Run Scan/Preview.
        # Mirrored at the top of the window too (see
        # _build_raw_command_section's shutter_row); both buttons are
        # kept in self.shutter_buttons and synced together by
        # _on_toggle_shutter.
        self.shutter_button = ttk.Button(
            box, text="Open Shutter", command=self._on_toggle_shutter
        )
        self.shutter_button.pack(side="left", padx=4)
        self.shutter_buttons.append(self.shutter_button)

        ttk.Button(box, text="Save Config...", command=self._on_save_config).pack(
            side="left", padx=4
        )
        ttk.Button(box, text="Load Config...", command=self._on_load_config).pack(
            side="left", padx=4
        )
        ttk.Button(box, text="Clear Log", command=self._on_clear_log).pack(
            side="left", padx=4
        )

    def _build_main_notebook(self):
        """Top-level notebook holding the ten independent scan
        workflows as equal, separate tabs, instead of stacking them
        (or nesting their controls inside the Log/Python Script Output
        notebook, which mixed scan controls in with pure output
        displays). "Home" (a plain-language description of the whole
        window -- see _build_home_tab) is added first below so it's
        the leftmost/default tab; "Sample Information" (DATAFILE,
        Sample name, Detector path prefix, Detector trigger mode, Next
        scan number -- 5 of the original "Global parameters" fields,
        shared by most other tabs) is second; "Height Scan" is third;
        "Threextal Scan" (the original Global parameters / Passes /
        Run Scan workflow, now showing only the 7 fields specific to
        it) is fourth; and so on.
        The raw SPEC command box above and the shared Log / Python
        Script Output notebook below both stay outside this notebook,
        since every tab uses them.

        self.main_notebook lives inside self.body_paned (a vertical
        ttk.PanedWindow, built just above this call in __init__)
        alongside the Output section below it, rather than being
        packed directly into the window. Previously, with nine tabs'
        worth of fields -- and, once the five temperature-series tabs
        each grew their own "HDRM Scan Parameters" section (a full
        editable Passes table plus step/count-time fields), some tabs
        taller than the whole default window -- this notebook's
        natural height (it was packed with fill="x" only, no vertical
        expand) could exceed the window's actual height, squeezing the
        Output/Log section below it down to little or no visible
        space with no way to get it back (reported: "output ... is not
        visible properly ... not flexible ... not able to make it
        bigger"). A PanedWindow gives the user a draggable sash between
        the two so they can allocate as much height as they want to
        either side, and _set_initial_sash_position (called once,
        shortly after startup) gives the Output/Log pane a reasonable
        default share rather than being squeezed to (near) zero."""
        self.main_notebook = ttk.Notebook(self.body_paned)
        self.body_paned.add(self.main_notebook, weight=1)

    def _apply_tab_accent_color(self, tab_widget, title):
        """Gives `title`'s tab a small solid-color square swatch on
        its own tab label, if `title` is one of the 5 tabs listed in
        _TAB_ACCENT_COLORS (every other tab is left exactly as
        before, no swatch) -- see _TAB_ACCENT_COLORS' own comment for
        why an image swatch, rather than an actual background color,
        is the mechanism here. The tk.PhotoImage must be kept
        referenced for as long as the tab exists (Tk drops an image
        the instant nothing in Python still holds it, even though the
        widget is still using it) -- self._tab_accent_images is a
        plain list created in __init__ for exactly this."""
        color = _TAB_ACCENT_COLORS.get(title)
        if color is None:
            return
        size = 14
        swatch = tk.PhotoImage(width=size, height=size)
        swatch.put(color, to=(0, 0, size, size))
        self._tab_accent_images.append(swatch)
        self.main_notebook.tab(tab_widget, image=swatch, compound="left")

    def _make_scrollable_tab(self, title):
        """Adds a new tab to self.main_notebook and returns an inner
        ttk.Frame for _build_*_tab methods to pack their content into,
        exactly as if it were the tab itself -- the canvas/scrollbar
        machinery that makes it scrollable is invisible to callers.

        This exists for the same reason self.body_paned does (see
        _build_main_notebook's docstring): several tabs -- especially
        the five temperature-series ones, each now with their own full
        "HDRM Scan Parameters" section -- can be taller than whatever
        share of the window the user has given the tabs area (whether
        via the sash or by not maximizing the window). Without this,
        that extra content was simply invisible with no way to reach
        it. With it, the tab scrolls vertically (mouse wheel while
        hovering it, or the scrollbar) instead of being clipped."""
        outer = ttk.Frame(self.main_notebook)
        self.main_notebook.add(outer, text=title)
        self._apply_tab_accent_color(outer, title)

        canvas = tk.Canvas(
            outer, highlightthickness=0, borderwidth=0,
            bg=THEMES[self.current_theme]["bg"],
        )
        self._scroll_canvases.append(canvas)
        vscroll = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vscroll.set)
        canvas.pack(side="left", fill="both", expand=True)
        vscroll.pack(side="right", fill="y")

        inner = ttk.Frame(canvas)
        inner_window_id = canvas.create_window((0, 0), window=inner, anchor="nw")

        def _on_inner_configure(event):
            canvas.configure(scrollregion=canvas.bbox("all"))

        def _on_canvas_configure(event):
            # keep the inner frame's width matching the canvas's
            # viewport width, so widgets that fill/wrap horizontally
            # (e.g. the wrapping description labels) still behave as
            # if they were packed straight into a plain tab.
            canvas.itemconfigure(inner_window_id, width=event.width)

        inner.bind("<Configure>", _on_inner_configure)
        canvas.bind("<Configure>", _on_canvas_configure)

        def _on_mousewheel(event):
            if event.num == 4:  # Linux scroll up
                canvas.yview_scroll(-1, "units")
            elif event.num == 5:  # Linux scroll down
                canvas.yview_scroll(1, "units")
            else:  # Windows / macOS
                canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        def _bind_wheel(_event):
            canvas.bind_all("<MouseWheel>", _on_mousewheel)
            canvas.bind_all("<Button-4>", _on_mousewheel)
            canvas.bind_all("<Button-5>", _on_mousewheel)

        def _unbind_wheel(_event):
            canvas.unbind_all("<MouseWheel>")
            canvas.unbind_all("<Button-4>")
            canvas.unbind_all("<Button-5>")

        # only scroll this canvas with the mouse wheel while the
        # pointer is actually over this tab, so scrolling elsewhere
        # (another tab, a dropdown, ...) isn't hijacked.
        canvas.bind("<Enter>", _bind_wheel)
        canvas.bind("<Leave>", _unbind_wheel)

        return inner

    def _set_initial_sash_position(self):
        """Gives the Output/Log pane of self.body_paned a reasonable
        default share of the window on first display, rather than
        leaving it at whatever the tabs area's natural (possibly very
        tall) requested height would otherwise squeeze it down to.
        Called once via self.after() shortly after the window is first
        drawn, since sash positions can only be set meaningfully once
        the paned window has real on-screen geometry. The user can
        always drag the sash to a different split afterwards, or
        resize the whole window -- this just sets a sane starting
        point instead of an unusable one."""
        try:
            self.update_idletasks()
            total_height = self.body_paned.winfo_height()
            if total_height > 100:
                # leave at least ~220px for Output/Log, but never put
                # the sash above the top 200px either
                target = max(200, total_height - 220)
                self.body_paned.sashpos(0, target)
        except tk.TclError:
            pass  # window may not be mapped yet in some environments (e.g. headless tests)

    # ========================================================
    # Generic standalone "Live temperatures (EPICS) + Set Temp
    # (te) + Flow Control (flow_set/flow_get)" block, added to every
    # scan/temperature tab (STANDALONE_TEMP_FLOW_TABS), per user
    # request. One copy of this UI block + its own independent state
    # (Tk variables, temperature-read thread, auto-watch timer, Set
    # Temp/Flow Set/Flow Get buttons and their own independent
    # background-thread slots) is built per tab, keyed by that tab's
    # `prefix` (e.g. "threextal", "lowtemp") -- see _init_standalone_
    # state below for the exact shape of self.standalone[prefix].
    # None of these actions are ever registered in
    # _scan_thread_registry, and none of their handlers ever call
    # _other_scan_running: by explicit user request, a quick
    # temperature/flow action must never block, or be blocked by, any
    # scan/macro running on this tab or any other tab -- see
    # _start_independent_job.
    # ========================================================

    def _init_standalone_state(self, prefix, label):
        """Initializes self.standalone[prefix] -- called once per tab
        from __init__ (see STANDALONE_TEMP_FLOW_TABS). Mirrors the Gas
        Prep Macros tab's own Live-temperatures-EPICS + Set Temp +
        Flow Control state (self.gas_prep_stage_a_temp_var etc.,
        self.gas_prep_vars, self.gas_prep_flow_result_var) one-for-
        one, just keyed by `prefix` in one dict instead of being named
        gas_prep_* directly, so the same state shape/handlers can be
        reused for all 8 tabs without hand-duplicating 8 copies of
        every attribute."""
        self.standalone[prefix] = {
            "label": label,
            "vars": {
                k: tk.StringVar(value=v)
                for k, v in STANDALONE_TEMP_FLOW_DEFAULTS.items()
            },
            "stage_a_temp_var": tk.StringVar(value="?"),
            "stage_c_temp_var": tk.StringVar(value="?"),
            "sample_temp_var": tk.StringVar(value="?"),
            "temp_watch_var": tk.BooleanVar(value=False),
            "flow_result_var": tk.StringVar(value="?"),
            "read_temps_button": None,
            "set_temp_button": None,
            "flow_set_button": None,
            "flow_get_button": None,
            # Each of the 3 actions gets its OWN background-thread
            # slot -- per user request ("everything should
            # independent, flow set, temperature set") these don't
            # even block each other on the SAME tab, only guard
            # against double-clicking themselves.
            "set_temp_run_thread": None,
            "flow_set_run_thread": None,
            "flow_get_run_thread": None,
            "temp_read_thread": None,
            "temp_watch_after_id": None,
        }

    def _start_independent_job(self, state, thread_key, worker_fn, start_label, buttons, done_sentinel):
        """Generic launcher for a fully-independent one-click temp/
        flow action -- deliberately bypasses _other_scan_running
        entirely (see this method group's docstring above). `state`
        is the dict holding this one action's own thread slot (e.g.
        self.standalone[prefix], or a small per-action dict for the
        Gas Prep Macros tab's retrofitted Set Temp/Flow Set/Flow Get
        -- see _on_gas_prep_run_set_temperature et al.); `thread_key`
        is the key inside it. Still guards against double-clicking
        the SAME button while its own previous click is still
        running -- just never checks, or is checked by, any other
        action's thread. `buttons` are disabled for the duration and
        re-enabled by _poll_log when `done_sentinel` (a string or
        tuple) comes back through self.log_queue."""
        thread = state.get(thread_key)
        if thread is not None and thread.is_alive():
            return
        for btn in buttons:
            if btn is not None:
                btn.configure(state="disabled")
        self._append_log(f"========== {start_label} ==========")
        self._append_log(
            f"[spec] sending real commands to SPEC {self.controller.spec_host}:"
            f"{self.controller.spec_port}"
        )

        def worker():
            # Not cancellable -- every action launched this way (te,
            # flow_set, flow_get) is a single instant command with no
            # sleep/loop to interrupt (see Runner.run_standalone_*'s
            # docstring), so a fresh, never-set Event is enough; there
            # is deliberately no Stop button for any of these.
            runner = Runner(
                self.log_queue, threading.Event(), spec_controller=self.controller
            )
            try:
                worker_fn(runner)
            except Exception as exc:  # surface any unexpected error to the log
                self.log_queue.put(f"[error] {exc}")
            finally:
                self.log_queue.put(done_sentinel)

        new_thread = threading.Thread(target=worker, daemon=True)
        state[thread_key] = new_thread
        new_thread.start()

    def _build_standalone_temp_flow_section(self, tab, prefix):
        """Builds this tab's own copy of the standalone block at the
        top of `tab` -- same 3 sub-sections as the Gas Prep Macros
        tab's own Live temperatures (EPICS) / Set Temp (te) / Flow
        Control rows (see _build_gas_prep_tab), just generic over
        `prefix` via self.standalone[prefix]. Wrapped with
        _make_section (rather than a plain ttk.LabelFrame) per
        explicit user request for more visually-distinct panels
        (item 7) -- fixed at color index 0 (blue) on every tab this
        appears on, so this one shared panel type reads as the same
        "kind" of thing everywhere it's used, while still standing
        out from whatever panel comes after it on each given tab."""
        state = self.standalone[prefix]
        label = state["label"]

        outer = self._make_section(
            tab, f"Quick Temp / Flow Control ({label}) -- independent of "
            "everything else on this tab or any other tab",
            0, padx=8, pady=(4, 8),
        )

        temps_row = ttk.LabelFrame(outer, text="Live temperatures (EPICS)")
        temps_row.pack(fill="x", padx=6, pady=(6, 4))
        for col_label, var in (
            ("Stage A:", state["stage_a_temp_var"]),
            ("Stage C:", state["stage_c_temp_var"]),
            ("Sample:", state["sample_temp_var"]),
        ):
            col = ttk.Frame(temps_row)
            col.pack(side="left", padx=(6, 16), pady=4)
            ttk.Label(col, text=col_label).pack(side="left")
            ttk.Label(col, textvariable=var, width=10, anchor="w").pack(side="left")
        state["read_temps_button"] = ttk.Button(
            temps_row, text="Read Temperatures",
            command=lambda p=prefix: self._on_standalone_read_temps(p),
        )
        state["read_temps_button"].pack(side="left", padx=(0, 12), pady=4)
        ttk.Checkbutton(
            temps_row,
            text=f"Auto-watch Temperatures (every {_STANDALONE_TEMP_WATCH_INTERVAL_MS // 1000}s)",
            variable=state["temp_watch_var"],
            command=lambda p=prefix: self._on_toggle_standalone_temp_watch(p),
        ).pack(side="left", pady=4)

        set_temp_row = ttk.LabelFrame(
            outer, text="Set Temp (te) -- any value 10-490K"
        )
        set_temp_row.pack(fill="x", padx=6, pady=4)
        ttk.Label(set_temp_row, text="Target temp (te), K [10-490]:").pack(
            side="left", padx=(6, 2), pady=6
        )
        ttk.Entry(
            set_temp_row, textvariable=state["vars"]["set_temp_te"], width=10,
        ).pack(side="left", padx=(0, 16), pady=6)
        ttk.Button(
            set_temp_row, text="Preview",
            command=lambda p=prefix: self._on_standalone_preview_set_temp(p),
        ).pack(side="left", padx=(0, 4), pady=6)
        state["set_temp_button"] = ttk.Button(
            set_temp_row, text="Set Temp",
            command=lambda p=prefix: self._on_standalone_run_set_temp(p),
        )
        state["set_temp_button"].pack(side="left", padx=(0, 8), pady=6)
        ttk.Label(set_temp_row, text="Target temp set anywhere:").pack(
            side="left", padx=(12, 2), pady=6
        )
        ttk.Label(
            set_temp_row, textvariable=self.shared_target_temp_var,
            width=28, anchor="w",
        ).pack(side="left", pady=6)

        flow_row = ttk.LabelFrame(outer, text="Flow Control -- any value 6-18")
        flow_row.pack(fill="x", padx=6, pady=(4, 6))
        ttk.Label(flow_row, text="flow_set value [6-18]:").pack(
            side="left", padx=(6, 2), pady=6
        )
        ttk.Entry(
            flow_row, textvariable=state["vars"]["flow_set_value"], width=10,
        ).pack(side="left", padx=(0, 8), pady=6)
        ttk.Button(
            flow_row, text="Preview",
            command=lambda p=prefix: self._on_standalone_preview_flow_set(p),
        ).pack(side="left", padx=(0, 4), pady=6)
        state["flow_set_button"] = ttk.Button(
            flow_row, text="Send flow_set",
            command=lambda p=prefix: self._on_standalone_run_flow_set(p),
        )
        state["flow_set_button"].pack(side="left", padx=(0, 16), pady=6)
        state["flow_get_button"] = ttk.Button(
            flow_row, text="Read flow_get",
            command=lambda p=prefix: self._on_standalone_flow_get(p),
        )
        state["flow_get_button"].pack(side="left", padx=(0, 8), pady=6)
        ttk.Label(flow_row, text="Current flow:").pack(side="left", padx=(8, 2), pady=6)
        ttk.Label(
            flow_row, textvariable=state["flow_result_var"], width=14, anchor="w",
        ).pack(side="left", pady=6)
        ttk.Label(flow_row, text="Target flow set anywhere:").pack(
            side="left", padx=(12, 2), pady=6
        )
        ttk.Label(
            flow_row, textvariable=self.shared_target_flow_var,
            width=22, anchor="w",
        ).pack(side="left", pady=6)

    def _collect_standalone_params(self, prefix):
        return {k: v.get().strip() for k, v in self.standalone[prefix]["vars"].items()}

    def _on_standalone_preview_set_temp(self, prefix):
        state = self.standalone[prefix]
        p = self._collect_standalone_params(prefix)
        try:
            validate_standalone_temp_flow_params(p)
        except ValueError as exc:
            messagebox.showerror(state["label"], str(exc))
            return
        self._append_log(
            f"========== Preview: {state['label']}: set temperature (te) (nothing sent) =========="
        )
        preview_queue = queue.Queue()
        runner = Runner(preview_queue, threading.Event(), preview=True)
        runner.run_standalone_set_temperature(p["set_temp_te"], label=state["label"])
        while not preview_queue.empty():
            self._append_log(preview_queue.get_nowait())
        self._append_log(
            "========== End preview -- click Set Temp to actually send this =========="
        )

    def _on_standalone_run_set_temp(self, prefix):
        state = self.standalone[prefix]
        p = self._collect_standalone_params(prefix)
        try:
            validate_standalone_temp_flow_params(p)
        except ValueError as exc:
            messagebox.showerror(state["label"], str(exc))
            return
        self._set_shared_target_temp(p["set_temp_te"], state["label"])
        self._start_independent_job(
            state, "set_temp_run_thread",
            lambda runner: runner.run_standalone_set_temperature(
                p["set_temp_te"], label=state["label"]
            ),
            f"Starting {state['label']}: set temperature (te)",
            [state["set_temp_button"]],
            ("__STANDALONE_DONE__", prefix, "set_temp"),
        )

    def _on_standalone_preview_flow_set(self, prefix):
        state = self.standalone[prefix]
        p = self._collect_standalone_params(prefix)
        try:
            validate_standalone_temp_flow_params(p)
        except ValueError as exc:
            messagebox.showerror(state["label"], str(exc))
            return
        self._append_log(
            f"========== Preview: {state['label']}: flow_set (nothing sent) =========="
        )
        preview_queue = queue.Queue()
        runner = Runner(preview_queue, threading.Event(), preview=True)
        runner.run_standalone_flow_set(p["flow_set_value"], label=state["label"])
        while not preview_queue.empty():
            self._append_log(preview_queue.get_nowait())
        self._append_log(
            "========== End preview -- click Send flow_set to actually send this =========="
        )

    def _on_standalone_run_flow_set(self, prefix):
        state = self.standalone[prefix]
        p = self._collect_standalone_params(prefix)
        try:
            validate_standalone_temp_flow_params(p)
        except ValueError as exc:
            messagebox.showerror(state["label"], str(exc))
            return
        self._set_shared_target_flow(p["flow_set_value"], state["label"])
        self._start_independent_job(
            state, "flow_set_run_thread",
            lambda runner: runner.run_standalone_flow_set(
                p["flow_set_value"], label=state["label"]
            ),
            f"Starting {state['label']}: flow_set",
            [state["flow_set_button"]],
            ("__STANDALONE_DONE__", prefix, "flow_set"),
        )

    def _on_standalone_flow_get(self, prefix):
        state = self.standalone[prefix]

        def worker_fn(runner):
            result = runner.run_standalone_flow_get(label=state["label"])
            self._call_in_tk(self._set_standalone_flow_result, prefix, result)

        self._start_independent_job(
            state, "flow_get_run_thread", worker_fn,
            f"Starting {state['label']}: flow_get",
            [state["flow_get_button"]],
            ("__STANDALONE_DONE__", prefix, "flow_get"),
        )

    def _set_standalone_flow_result(self, prefix, result):
        """Only safe to call on the Tk thread -- see _call_in_tk's
        docstring."""
        self.standalone[prefix]["flow_result_var"].set(
            "?" if result is None else str(result)
        )

    # ---- Shared "last target temp (te) / flow_set set anywhere"
    # echo -- per explicit user request (items 3/4): setting te or
    # flow_set on one tab (e.g. Gas Prep) was leaving every other
    # tab's own "Target temp (te)"/"flow_set value" ENTRY field
    # unchanged, which is correct (each tab's entry is independent
    # and this app intentionally has no single global setpoint), but
    # left the user with no way to tell what they'd actually just
    # sent from some *other* tab. These two setters, plus the
    # read-only display rows added to _build_standalone_temp_flow_
    # section and _build_gas_prep_tab, are purely an informational
    # echo of "the last value sent, and from where" -- they never
    # write back into any tab's own entry field and never change
    # what gets sent anywhere.
    def _set_shared_target_temp(self, value, source_label):
        """Record the most recently sent target temp (te), from any
        of the 8 generic standalone tabs or the Gas Prep tab. Resets
        self._target_temp_reached_logged so a freshly-set target is
        immediately eligible for its own "reached" notification again
        (see _check_target_temp_reached) -- otherwise a tab that
        already reported "reached" for an old target could stay
        silently latched if the exact same numeric value is set
        again."""
        self.shared_target_temp_value = value
        self.shared_target_temp_var.set(f"{value} K (set from {source_label})")
        self._target_temp_reached_logged = {}

    def _set_shared_target_flow(self, value, source_label):
        """Same idea as _set_shared_target_temp, but for flow_set
        (item 4). flow_set has no "reached" notification (item 5 is
        about temperatures only), so there's no latch to reset here."""
        self.shared_target_flow_value = value
        self.shared_target_flow_var.set(f"{value} (set from {source_label})")

    def _check_target_temp_reached(self, label, stage_a, stage_c, sample):
        """Per explicit user request (item 5): "If at the gas flow or
        other tab I set the temperature stage A or Stage C or even
        sample temperature, when that temperature reached, it should
        inform me ... in the log it can show now you reached the
        temperature go to next stage in red colour". Compares each of
        Stage A / Stage C / Sample (whichever reading is numeric --
        not every tab exposes all three) against the shared target
        temp set from ANY tab (self.shared_target_temp_value, see
        _set_shared_target_temp) within the same
        _PREPSWITCH_READY_TOLERANCE_K tolerance already used by
        _check_n2_he_prepswitch_ready/_check_gas_prep_prepswitch_
        ready, so "reached" means the same thing everywhere in this
        app. Called from every one of the 10 temperature-read finish
        handlers (the 8 generic standalone tabs via
        _finish_read_standalone_temps, plus Gas Prep and N2->He
        Switch's own copies), each passing its own `label` so the log
        line always says which tab/section reached it.

        Logged once per (label, field) transition into "reached" --
        latched in self._target_temp_reached_logged, keyed by
        (label, field_name) so Stage A/Stage C/Sample on the same tab
        each get their own independent one-shot notification, exactly
        like the existing prepswitch-ready latches -- and un-latched
        again once that field drifts back out of tolerance, so a
        later re-arrival (e.g. after setting a new target, which
        resets the whole dict anyway) can log again. Uses
        _append_log(..., tag="alert") so the line renders in this
        theme's red "stop" accent color (see _build_log_section) per
        the user's "in red colour or different color" request."""
        target = self.shared_target_temp_value
        if target is None:
            return
        try:
            target_f = float(target)
        except (TypeError, ValueError):
            return
        for field_name, value in (
            ("Stage A", stage_a), ("Stage C", stage_c), ("Sample", sample),
        ):
            try:
                value_f = float(value)
            except (TypeError, ValueError):
                continue
            key = (label, field_name)
            reached = abs(value_f - target_f) <= _PREPSWITCH_READY_TOLERANCE_K
            if reached and not self._target_temp_reached_logged.get(key):
                self._append_log(
                    f"[{label}] {field_name} ({value_f:g}K) has reached the "
                    f"target temperature ({target_f:g}K) -- now you reached "
                    "the temperature, go to next stage",
                    tag="alert",
                )
                self._target_temp_reached_logged[key] = True
            elif not reached and self._target_temp_reached_logged.get(key):
                self._target_temp_reached_logged[key] = False

    def _finish_standalone_action(self, prefix, action):
        """Called from _poll_log when a ("__STANDALONE_DONE__",
        prefix, action) sentinel comes back -- re-enables just that
        one action's own button (the other two actions on this same
        tab, and every other tab, were never disabled by this run in
        the first place)."""
        state = self.standalone[prefix]
        button_key = {
            "set_temp": "set_temp_button",
            "flow_set": "flow_set_button",
            "flow_get": "flow_get_button",
        }[action]
        btn = state[button_key]
        if btn is not None:
            btn.configure(state="normal")
        self._append_log(f"========== {state['label']}: {action} finished ==========")

    # ---- Read a standalone section's live temperatures from EPICS ----

    def _on_standalone_read_temps(self, prefix):
        state = self.standalone[prefix]
        thread = state["temp_read_thread"]
        if thread is not None and thread.is_alive():
            return
        state["read_temps_button"].config(state="disabled")
        self._append_log(
            f"[{state['label']}] reading temperatures from EPICS: "
            f"{STAGE_A_TEMP_PV}, {STAGE_C_TEMP_PV}, {SAMPLE_TEMP_PV}"
        )
        new_thread = threading.Thread(
            target=self._read_standalone_temps_in_background, args=(prefix,), daemon=True
        )
        state["temp_read_thread"] = new_thread
        new_thread.start()

    def _read_standalone_temps_in_background(self, prefix, log_result=True):
        """`log_result` is False only when called from
        _standalone_temp_watch_tick's own background polling -- per
        explicit user request, the auto-watch timer must keep the
        on-screen Stage A/Stage C/Sample fields live-updating every
        tick without spamming the Log tab with a repeated line every
        interval. A manual "Read Temperatures" click always passes
        the default True and still logs once, as before."""
        try:
            import epics  # optional dependency, imported lazily on purpose
            # Channel Access (the C library pyepics wraps) is NOT
            # thread-safe by default: it keeps a separate CA context
            # per OS thread, and a thread that calls caget/caput
            # without ever creating or attaching to one hits
            # undefined behavior in the C library -- not a Python
            # exception, but a hard native crash (segfault, no
            # traceback). This method always runs on a brand-new
            # background thread (see _on_standalone_read_temps and
            # the auto-watch timer below), so it must attach to the
            # context the main/Tk thread already created on first
            # `import epics` before making any CA call. This is
            # pyepics' own documented fix for exactly this situation
            # (a GUI's background polling/worker threads calling CA).
            epics.ca.use_initial_context()
        except ImportError as e:
            self._call_in_tk(
                self._finish_read_standalone_temps, prefix, None, None, None, e, log_result
            )
            return
        try:
            stage_a = epics.caget(STAGE_A_TEMP_PV, as_string=True)
            stage_c = epics.caget(STAGE_C_TEMP_PV, as_string=True)
            sample = epics.caget(SAMPLE_TEMP_PV, as_string=True)
        except Exception as e:
            self._call_in_tk(
                self._finish_read_standalone_temps, prefix, None, None, None, e, log_result
            )
            return
        self._call_in_tk(
            self._finish_read_standalone_temps,
            prefix, stage_a, stage_c, sample, None, log_result,
        )

    def _finish_read_standalone_temps(
        self, prefix, stage_a, stage_c, sample, error, log_result=True
    ):
        state = self.standalone[prefix]
        if error is not None:
            if log_result:
                if isinstance(error, ImportError):
                    self._append_log(
                        f"[{state['label']}] pyepics is not installed -- install it "
                        "(pip install pyepics) to read live temperatures."
                    )
                else:
                    self._append_log(f"[{state['label']}] temperature read failed: {error!r}")
        else:
            state["stage_a_temp_var"].set(stage_a if stage_a is not None else "?")
            state["stage_c_temp_var"].set(stage_c if stage_c is not None else "?")
            state["sample_temp_var"].set(sample if sample is not None else "?")
            if log_result:
                self._append_log(
                    f"[{state['label']}] Stage A={stage_a} Stage C={stage_c} Sample={sample}"
                )
            self._check_target_temp_reached(state["label"], stage_a, stage_c, sample)
        state["read_temps_button"].config(state="normal")

    def _on_toggle_standalone_temp_watch(self, prefix):
        state = self.standalone[prefix]
        watch_state = "on" if state["temp_watch_var"].get() else "paused"
        self._append_log(f"[watch] {state['label']} temperature auto-watch {watch_state}")

    def _schedule_standalone_temp_watch(self, prefix):
        state = self.standalone[prefix]
        state["temp_watch_after_id"] = self.after(
            _STANDALONE_TEMP_WATCH_INTERVAL_MS, self._standalone_temp_watch_tick, prefix
        )

    def _standalone_temp_watch_tick(self, prefix):
        state = self.standalone[prefix]
        thread = state["temp_read_thread"]
        if state["temp_watch_var"].get() and (thread is None or not thread.is_alive()):
            # log_result=False -- auto-watch updates the on-screen
            # fields live every tick without writing a line to the
            # Log tab each time (see _read_standalone_temps_in_
            # background's docstring); only a manual "Read
            # Temperatures" click still logs.
            new_thread = threading.Thread(
                target=self._read_standalone_temps_in_background,
                args=(prefix, False), daemon=True,
            )
            state["temp_read_thread"] = new_thread
            new_thread.start()
        self._schedule_standalone_temp_watch(prefix)

    # ---- Low Temp Scan: standalone Spin (spin_xtal_phi) control ----
    # A second, independent copy of the Spin Control tab's Start/Stop
    # UI, added directly to the Low Temp Scan tab per the user's
    # request for a "spin_control option" there too. Deliberately its
    # own state (self.low_temp_spin_*, initialized in __init__) and
    # its own thread slot -- NOT the Spin Control tab's
    # self.spin_run_thread -- so starting a spin from here can never
    # collide with, be blocked by, or block the main Spin Control tab.
    # And unlike the main Spin Control tab's _on_spin_start, this
    # NEVER calls self._other_scan_running(...): per the user's
    # explicit "it should not block anything" requirement, spinning
    # from Low Temp Scan must stay independent of every other
    # scan/macro/standalone action running anywhere else in the app.
    def _build_low_temp_standalone_spin_section(self, tab):
        # _make_section (rather than a plain ttk.LabelFrame) per
        # explicit user request for more visually-distinct panels
        # (item 7); color index 2 keeps it visually distinct from the
        # Quick Temp/Flow Control (index 0) and N2 -> He Switch
        # (index 1) panels above it on this tab.
        box = self._make_section(
            tab,
            "Quick Spin Control (spin_xtal_phi) -- independent of "
            "everything else on this tab or any other tab",
            2, padx=8, pady=6,
        )

        self._make_wrapping_label(
            box,
            "Continuously spins the sample (phi 0 <-> 360) without "
            "affecting -- and without being blocked by -- any scan, "
            "macro, or other quick action anywhere else in the app. "
            "Same controls as the main Spin Control tab; leave "
            "'Number of cycles' blank to spin until Stop is clicked.",
        )

        fields_row = ttk.Frame(box)
        fields_row.pack(fill="x", padx=8, pady=4)
        col = ttk.Frame(fields_row)
        col.pack(side="left", padx=(0, 18))
        ttk.Label(col, text="Number of cycles (blank = continuous):").pack(anchor="w")
        ttk.Entry(
            col, textvariable=self.low_temp_spin_vars["num_cycles"], width=12
        ).pack(anchor="w")

        ttk.Checkbutton(
            fields_row, text="Ice mode (spin_ice)",
            variable=self.low_temp_spin_ice_mode_var,
        ).pack(side="left", padx=(0, 18), anchor="s", pady=(14, 0))

        buttons_row = ttk.Frame(box)
        buttons_row.pack(fill="x", padx=8, pady=(8, 4))
        self.low_temp_spin_start_button = ttk.Button(
            buttons_row, text="Start Spin", command=self._on_low_temp_spin_start,
            style="Accent.TButton",
        )
        self.low_temp_spin_start_button.pack(side="left", padx=4)
        self.low_temp_spin_stop_button = ttk.Button(
            buttons_row, text="Stop", command=self._on_low_temp_spin_stop,
            state="disabled", style="Stop.TButton",
        )
        self.low_temp_spin_stop_button.pack(side="left", padx=4)
        ttk.Button(
            buttons_row, text="Reset to defaults",
            command=self._on_low_temp_spin_reset_defaults,
        ).pack(side="left", padx=4)

    def _collect_low_temp_spin_params(self):
        p = {k: v.get().strip() for k, v in self.low_temp_spin_vars.items()}
        p["ice_mode"] = "1" if self.low_temp_spin_ice_mode_var.get() else "0"
        return p

    def _on_low_temp_spin_reset_defaults(self):
        for key, value in SPIN_DEFAULTS.items():
            if key == "ice_mode":
                self.low_temp_spin_ice_mode_var.set(value == "1")
            else:
                self.low_temp_spin_vars[key].set(value)
        self._append_log(
            "[low temp spin] fields reset to defaults (continuous, ice mode off)"
        )

    def _on_low_temp_spin_start(self):
        """Start spinning for real -- deliberately does NOT call
        self._other_scan_running(...): this quick action must never
        block, or be blocked by, any other scan/macro/standalone
        action (see this method's section docstring above)."""
        if self.low_temp_spin_run_thread and self.low_temp_spin_run_thread.is_alive():
            return

        p = self._collect_low_temp_spin_params()
        try:
            validate_spin_params(p)
        except ValueError as exc:
            messagebox.showerror("Low Temp Scan: Spin", str(exc))
            return

        self.low_temp_spin_cancel_event.clear()
        self.low_temp_spin_start_button.configure(state="disabled")
        self.low_temp_spin_stop_button.configure(state="normal")
        self._append_log("========== Low Temp Scan: Starting Spin ==========")
        self._append_log(
            f"[spec] sending real commands to SPEC {self.controller.spec_host}:"
            f"{self.controller.spec_port}"
        )

        def worker():
            runner = Runner(
                self.log_queue, self.low_temp_spin_cancel_event,
                spec_controller=self.controller,
            )
            try:
                num_cycles = float(p["num_cycles"]) if p["num_cycles"] else None
                runner.run_spin_xtal_phi(num_cycles=num_cycles, ice_mode=p["ice_mode"] == "1")
            except Exception as exc:  # surface any unexpected error to the log
                self.log_queue.put(f"[error] {exc}")
            finally:
                self.log_queue.put("__LOW_TEMP_SPIN_DONE__")

        self.low_temp_spin_run_thread = threading.Thread(target=worker, daemon=True)
        self.low_temp_spin_run_thread.start()

    def _on_low_temp_spin_stop(self):
        """Same immediate-abort fix as _on_spin_stop -- see its
        docstring for why setting cancel_event alone isn't enough.
        Uses _abort_until_stopped (a few automatic retries while
        low_temp_spin_run_thread is still alive) rather than a single
        attempt -- see its docstring."""
        self.low_temp_spin_cancel_event.set()
        self._append_log("[low temp spin] stop requested -- aborting current move...")
        self._last_low_temp_spin_abort_thread = self._abort_until_stopped(
            lambda: self.low_temp_spin_run_thread is not None
            and self.low_temp_spin_run_thread.is_alive()
        )

    def _build_scan_tab(self):
        """Fourth main-notebook tab -- the original Threextal Scan
        workflow (Global parameters, Passes, Preview Log / Run Scan /
        Cancel / Shutter / Save / Load / Clear), unchanged except that
        it now lives inside its own tab instead of being packed
        directly into the window."""
        tab = self._make_scrollable_tab("Threextal Scan")
        # Quick Temp/Flow Control placed ABOVE Global parameters per
        # explicit user request ("Make Quick temp/Flow control for
        # threextal scan above global parameter").
        self._build_standalone_temp_flow_section(tab, "threextal")
        self._build_globals_section(tab)
        self._build_passes_section(tab)
        self._build_controls_section(tab)

    def _build_log_section(self):
        # Lives in self.body_paned (the draggable vertical split
        # created in __init__) as the pane below self.main_notebook,
        # rather than packed directly into the window -- see
        # _build_main_notebook's docstring for why. weight=1 (equal
        # with self.main_notebook's own weight=1, rather than the
        # previous weight=2) per explicit user request ("Make the
        # output channel smaller") -- any extra space from resizing
        # the window larger is now split evenly between the tabs area
        # and this Output pane instead of favoring Output, though the
        # user's own sash drag always takes priority over either.
        outer = ttk.LabelFrame(self.body_paned, text="Output")
        # Cap this pane's own *requested* size and stop it from
        # growing to match its children's natural size (pack_propagate
        # off) -- per earlier explicit report ("currently I can't
        # make it smaller"). Unlike the classic tk.PanedWindow,
        # ttk.PanedWindow has no per-pane "minsize" option of its
        # own; without this, its fallback floor for how far the sash
        # can be dragged is simply this pane widget's own reqheight,
        # which -- with log_text/script_text both requesting height=8
        # (8 text lines, shrunk from the original height=18 per the
        # same "Make the output channel smaller" request) below --
        # would otherwise set the floor at ~8 lines tall. Fixing the
        # floor here independently keeps it shrinkable even smaller
        # than that via the sash, while the height=8 default above
        # already makes the normal/default view noticeably more
        # compact than before.
        outer.configure(height=70)
        outer.pack_propagate(False)
        self.body_paned.add(outer, weight=1)

        self.notebook = ttk.Notebook(outer)
        self.notebook.pack(fill="both", expand=True)

        t = THEMES[self.current_theme]

        log_tab = ttk.Frame(self.notebook)
        self.notebook.add(log_tab, text="Log")
        self.log_text = tk.Text(
            log_tab, wrap="word", height=8, state="disabled",
            bg=t["log_bg"], fg=t["log_fg"], insertbackground=t["fg"],
            relief="flat", borderwidth=0, highlightthickness=0,
            font=(self.ui_mono_font_family, 10),
        )
        self.log_text.pack(side="left", fill="both", expand=True)
        log_scrollbar = ttk.Scrollbar(log_tab, command=self.log_text.yview)
        log_scrollbar.pack(side="right", fill="y")
        self.log_text.configure(yscrollcommand=log_scrollbar.set)
        # "alert" tag -- used by _check_target_temp_reached (item 5)
        # to make the "reached target temperature" line stand out in
        # a different color, reusing this theme's existing red "stop"
        # accent color rather than introducing a new one. Re-applied
        # on theme switch by _apply_theme.
        self.log_text.tag_configure(
            "alert", foreground=t["stop"], font=(self.ui_mono_font_family, 10, "bold")
        )

        script_tab = ttk.Frame(self.notebook)
        self.notebook.add(script_tab, text="Python Script")
        self.script_text = tk.Text(
            script_tab, wrap="none", height=8, state="disabled",
            bg=t["log_bg"], fg=t["log_fg"], insertbackground=t["fg"],
            relief="flat", borderwidth=0, highlightthickness=0,
            font=(self.ui_mono_font_family, 10),
        )
        self.script_text.pack(side="left", fill="both", expand=True)
        script_scrollbar = ttk.Scrollbar(script_tab, command=self.script_text.yview)
        script_scrollbar.pack(side="right", fill="y")
        self.script_text.configure(yscrollcommand=script_scrollbar.set)

    def _build_height_scan_tab(self):
        """Third main-notebook tab -- the quick sample-quality "height
        scan" translated from HDRMscans_new.mac's `heightscan` macro
        (see hrdm_core.Runner.run_height_scan). It's a separate scan
        workflow in its own right, just like the Threextal Scan tab
        next to it -- not a Log/Python Script-style output display --
        so it gets its own top-level tab (its own Start / End / Steps
        / Count time fields, defaulted to hrdm_core.HEIGHTSCAN_DEFAULTS),
        rather than being nested inside the Output notebook. It shares
        this window's 'rampre' field from the Threextal Scan tab's
        Global parameters box -- height-scan images always go to a
        fixed "<rampre>/tiffs/" folder rather than the per-sample/
        temperature folders threextalscan uses."""
        tab = self._make_scrollable_tab("Height Scan")
        self._build_standalone_temp_flow_section(tab, "height")

        self._make_wrapping_label(
            tab,
            "Quick sample-quality check (translated from "
            "HDRMscans_new.mac's 'heightscan' macro) -- step-scans "
            "the sample-height motor (samz) through the beam and "
            "saves images to <rampre>/tiffs/ (using the 'rampre' "
            "field on the Threextal Scan tab), independent of Run "
            "Scan's per-sample/temperature folders. Switches the detector "
            "trigger mode to 'Internal' for this scan only -- Run "
            "Scan's own trig_mode field is left untouched.",
        )

        fields_row = ttk.Frame(tab)
        fields_row.pack(fill="x", padx=8, pady=4)
        for key, label, width in (
            ("start", "Start (samz)", 10),
            ("end", "End (samz)", 10),
            ("steps", "Steps", 8),
            ("count_time", "Count time, s", 10),
        ):
            col = ttk.Frame(fields_row)
            col.pack(side="left", padx=(0, 18))
            ttk.Label(col, text=label + ":").pack(anchor="w")
            ttk.Entry(
                col, textvariable=self.height_vars[key], width=width
            ).pack(anchor="w")

        buttons_row = ttk.Frame(tab)
        buttons_row.pack(fill="x", padx=8, pady=(8, 4))
        ttk.Button(
            buttons_row, text="Preview", command=self._on_height_preview
        ).pack(side="left", padx=4)
        self.height_run_button = ttk.Button(
            buttons_row, text="Run Height Scan",
            command=self._on_height_run, style="Accent.TButton",
        )
        self.height_run_button.pack(side="left", padx=4)
        ttk.Button(
            buttons_row, text="Reset to defaults",
            command=self._on_height_reset_defaults,
        ).pack(side="left", padx=4)

        ttk.Label(
            tab,
            text="Preview and Run Height Scan both log to the shared "
            "\"Log\" tab in the Output section below, same as Preview "
            "Log / Run Scan on the Threextal Scan tab.",
        ).pack(fill="x", padx=8, pady=(4, 8))

    def _build_powder_scan_tab(self):
        """Fifth main-notebook tab -- the powder-diffraction
        calibration scan translated from HDRMscans_new.mac's
        `powderscan <temperature> <sleep_time>` macro (see
        hrdm_core.Runner.run_powder_scan). It's a separate scan
        workflow, just like the Height Scan and Threextal Scan tabs
        next to it -- so it gets its own top-level tab (its own
        Temperature / Wait time fields, defaulted to
        hrdm_core.POWDERSCAN_DEFAULTS), rather than being nested
        inside the Output notebook. Unlike Height Scan (which uses a
        fixed <rampre>/tiffs/ folder), Powder Scan shares the SAME
        per-sample/per-temperature directory scheme threextalscan
        uses -- so it reads 'datafile', 'sample', and 'rampre' from
        the Sample Information tab's Global parameters box, the same
        way Height Scan already shares just 'rampre' from there. The
        motor angles (chi 90, th 0, phi 0) are hard-coded to match the
        macro exactly -- there's no field for them here, since the
        macro itself never parameterizes that move. The flyscan's phi
        start/end, step count, and count time, though, ARE editable
        here (defaulted to hrdm_core.POWDERSCAN_DEFAULTS -- 0/360/180/
        1) -- a deliberate partial parametrization beyond the
        macro's own hard-coded `flyscan phi 0 360 180 2`, so the scan
        range can be tuned per run without editing code."""
        tab = self._make_scrollable_tab("Powder Scan")
        self._build_standalone_temp_flow_section(tab, "powder")

        self._make_wrapping_label(
            tab,
            "Powder-diffraction calibration scan (translated from "
            "HDRMscans_new.mac's 'powderscan' macro) -- moves to a "
            "fixed chi 90 / th 0 / phi 0, then flyscans phi over the "
            "range/steps/count time set below (defaults: 0 to 360, "
            "180 steps, 1s), saving into the same per-sample/"
            "temperature folder structure as the Threextal Scan tab "
            "(using its 'datafile', 'sample', and 'rampre' fields). "
            "Sets the detector trigger mode to 'Mult. Trigger', same "
            "as Run Scan. Unlike Run Scan, the macro's own "
            "temperature-set command is commented out, so this "
            "never calls 'te' -- the temperature below is only used "
            "to build the output directory.",
        )

        fields_row = ttk.Frame(tab)
        fields_row.pack(fill="x", padx=8, pady=4)
        for key, label, width in (
            ("temperature", "Temperature", 10),
            ("wait_seconds", "Wait time, s", 10),
            ("phi_start", "Phi start", 10),
            ("phi_end", "Phi end", 10),
            ("num_steps", "Steps", 8),
            ("count_time", "Count time, s", 10),
        ):
            col = ttk.Frame(fields_row)
            col.pack(side="left", padx=(0, 18))
            ttk.Label(col, text=label + ":").pack(anchor="w")
            ttk.Entry(
                col, textvariable=self.powder_vars[key], width=width
            ).pack(anchor="w")

        buttons_row = ttk.Frame(tab)
        buttons_row.pack(fill="x", padx=8, pady=(8, 4))
        ttk.Button(
            buttons_row, text="Preview", command=self._on_powder_preview
        ).pack(side="left", padx=4)
        self.powder_run_button = ttk.Button(
            buttons_row, text="Run Powder Scan",
            command=self._on_powder_run, style="Accent.TButton",
        )
        self.powder_run_button.pack(side="left", padx=4)
        ttk.Button(
            buttons_row, text="Reset to defaults",
            command=self._on_powder_reset_defaults,
        ).pack(side="left", padx=4)

        ttk.Label(
            tab,
            text="Preview and Run Powder Scan both log to the shared "
            "\"Log\" tab in the Output section below, same as Preview "
            "Log / Run Scan on the Threextal Scan tab.",
        ).pack(fill="x", padx=8, pady=(4, 8))

    # ---- pass row management ----

    def _add_pass_row(self, values=None):
        row = PassRow(self.passes_container, self._remove_pass_row, values)
        self.pass_rows.append(row)

    def _remove_pass_row(self, row):
        if len(self.pass_rows) <= 1:
            messagebox.showwarning("HDRM Scan", "At least one pass is required.")
            return
        row.destroy()
        self.pass_rows.remove(row)

    def _set_num_passes(self, n):
        try:
            n = int(str(n).strip())
        except ValueError:
            messagebox.showerror("HDRM Scan", f"'{n}' is not a valid number of passes.")
            return
        n = max(1, n)

        while len(self.pass_rows) > n:
            row = self.pass_rows[-1]
            row.destroy()
            self.pass_rows.remove(row)

        while len(self.pass_rows) < n:
            idx = len(self.pass_rows)
            defaults = (
                DEFAULT_PASSES[idx]
                if idx < len(DEFAULT_PASSES)
                else {"chi": "0", "th": "0", "phi": "0", "scan_start": "0", "scan_stop": "365"}
            )
            self._add_pass_row(defaults)

        self.num_passes_var.set(str(len(self.pass_rows)))

    # ---- config save/load ----

    def _collect_config(self):
        g = {k: v.get().strip() for k, v in self.global_vars.items()}
        passes = [row.get() for row in self.pass_rows]
        return {"globals": g, "passes": passes}

    def _apply_config(self, config):
        for k, v in config.get("globals", {}).items():
            if k in self.global_vars:
                self.global_vars[k].set(v)

        for row in list(self.pass_rows):
            row.destroy()
        self.pass_rows.clear()

        passes = config.get("passes") or DEFAULT_PASSES
        for p in passes:
            self._add_pass_row(p)

    def _on_save_config(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON", "*.json")],
            title="Save HDRM scan config",
        )
        if not path:
            return
        with open(path, "w") as f:
            json.dump(self._collect_config(), f, indent=2)
        self._append_log(f"[config] saved to {path}")

    def _on_load_config(self):
        path = filedialog.askopenfilename(
            filetypes=[("JSON", "*.json")], title="Load HDRM scan config"
        )
        if not path:
            return
        try:
            with open(path) as f:
                config = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            messagebox.showerror("HDRM Scan", f"Could not load config:\n{exc}")
            return
        self._apply_config(config)
        self._append_log(f"[config] loaded from {path}")

    # ---- HDRM scan: preview / run / cancel ----

    def _validate_globals(self, g):
        numeric_fields = ["temperature", "wait_seconds", "num_steps", "count_time"]
        for key in numeric_fields:
            try:
                float(g[key])
            except ValueError:
                raise ValueError(f"'{key}' must be a number, got {g[key]!r}")
        if not g["sample"]:
            raise ValueError("Sample name cannot be empty.")
        try:
            next_scan_n = int(g["next_scan_n"])
        except ValueError:
            raise ValueError(
                f"'next_scan_n' must be a whole number, got {g['next_scan_n']!r}"
            )
        if next_scan_n < 0:
            raise ValueError("'next_scan_n' cannot be negative.")

    def _on_preview(self):
        """Show the full generated command log instantly (no real
        waiting, nothing sent -- doesn't touch self.controller at
        all) so it can be reviewed before clicking Run Scan."""
        g = {k: v.get().strip() for k, v in self.global_vars.items()}
        passes = [row.get() for row in self.pass_rows]

        if not passes:
            messagebox.showwarning("HDRM Scan", "Add at least one pass before previewing.")
            return
        try:
            self._validate_globals(g)
        except ValueError as exc:
            messagebox.showerror("HDRM Scan", str(exc))
            return

        self._append_log("========== Preview (no waiting, nothing sent) ==========")
        preview_queue = queue.Queue()
        runner = Runner(preview_queue, threading.Event(), preview=True)
        runner.run(g, passes)
        while not preview_queue.empty():
            self._append_log(preview_queue.get_nowait())
        self._append_log(
            "========== End preview -- click Run Scan to actually send this =========="
        )
        self._set_script(g, passes)

    def _on_run(self):
        """Run the scan for real, sending every command through the
        already-connected self.controller (no lazy connect step
        needed here, unlike HRDM_gui.py -- the connection was made at
        startup, before this window even opened). Before building any
        paths, the background worker also auto-refreshes 'datafile'
        from live SPEC state (same commands/parsing as the "Read from
        SPEC" button) so Run Scan always uses SPEC's current DATAFILE
        value, whether or not "Read from SPEC" was clicked first.
        'rampre' is never auto-refreshed -- see _SPEC_READ_COMMANDS'
        comment for why (it's a manually-set ramdisk path, not
        something SPEC can report live)."""
        if self.run_thread and self.run_thread.is_alive():
            return
        if self._other_scan_running("run_thread", "Run Scan"):
            return

        g = {k: v.get().strip() for k, v in self.global_vars.items()}
        passes = [row.get() for row in self.pass_rows]

        if not passes:
            messagebox.showwarning("HDRM Scan", "Add at least one pass before running.")
            return

        try:
            self._validate_globals(g)
        except ValueError as exc:
            messagebox.showerror("HDRM Scan", str(exc))
            return

        self.cancel_event.clear()
        self.run_button.configure(state="disabled")
        self.cancel_button.configure(state="normal")
        self._append_log("========== Starting HDRM scan ==========")
        self._append_log(
            f"[spec] sending real commands to SPEC {self.controller.spec_host}:"
            f"{self.controller.spec_port}"
        )
        self._set_script(g, passes)

        def worker():
            # Auto-refresh 'datafile' from live SPEC state right before
            # building paths, the same way "Read from SPEC" does (same
            # _SPEC_READ_COMMANDS, same _extract_global_value parsing)
            # -- so Run Scan always uses what SPEC's DATAFILE actually
            # is *right now*, not whatever was last typed in or read
            # earlier. Confirmed necessary by the user: SPEC's live
            # DATAFILE was "test2" but the GUI field still held the
            # "datafile" placeholder because "Read from SPEC" hadn't
            # been (re-)clicked since. This updates both `g` (used for
            # this run) and the on-screen field (via _call_in_tk, since
            # we're on a background thread), and every outcome is
            # logged either way -- this IS the "Read from SPEC"
            # button's own logic, just run automatically right before a
            # real run instead of requiring a separate manual click
            # first. 'rampre' is deliberately not in _SPEC_READ_COMMANDS
            # (see its comment) so it's never touched here -- it keeps
            # whatever value is currently in the field/g.
            self.log_queue.put(
                "[globals] auto-reading from SPEC before run: "
                + ", ".join(_SPEC_READ_COMMANDS.values())
            )
            for key, command in _SPEC_READ_COMMANDS.items():
                try:
                    result = self.controller.send(command)
                except Exception as exc:
                    text = describe_result(exc, self.controller.spec_timeout)
                    self.log_queue.put(f"[globals] {command}: {text}")
                    continue
                value = self._extract_global_value(result)
                if value is None:
                    text = describe_result(result, self.controller.spec_timeout)
                    self.log_queue.put(
                        f"[globals] {command} -> {text} "
                        f"(keeping existing '{key}' value for this run)"
                    )
                    continue
                g[key] = value
                self._call_in_tk(self._set_global_var, key, value)
                self.log_queue.put(
                    f"[globals] {command} = {value!r} -> using for this run's "
                    f"'{key}' (and updated the field)"
                )
            # Regenerate the Python Script tab so it reflects these
            # possibly-refreshed values too, not the stale ones from
            # before this auto-read (it was already built once, up in
            # _on_run, from the pre-refresh `g`).
            self._call_in_tk(self._set_script, g, passes)

            runner = Runner(self.log_queue, self.cancel_event, spec_controller=self.controller)
            try:
                runner.run(g, passes)
            except Exception as exc:  # surface any unexpected error to the log
                self.log_queue.put(f"[error] {exc}")
            finally:
                # Real run (not Preview) that actually wrote real images
                # to disk, so persist the ending SCAN_N back into the
                # "next_scan_n" field for next time -- see the matching
                # comment in HRDM_gui.py's _on_run for the full
                # explanation. Guard with getattr since runner.scan_n
                # may not exist if run() raised before setting it.
                scan_n = getattr(runner, "scan_n", None)
                if scan_n is not None:
                    self.log_queue.put(("__SCANN__", scan_n))
                self.log_queue.put("__DONE__")

        self.run_thread = threading.Thread(target=worker, daemon=True)
        self.run_thread.start()

    def _on_cancel(self):
        self.cancel_event.set()
        self._append_log("[cancel requested] finishing current step...")

    def _on_toggle_shutter(self):
        """Manually open or close the shutter, independent of Run
        Scan/Preview -- calls the exact same opens()/closes() stub
        (see Runner in hrdm_core.py) that the scan sequence itself
        uses, through the same already-connected self.controller, so
        it really opens/closes the shutter on real hardware. Doesn't
        interrupt or otherwise interact with a scan that's running."""
        runner = Runner(
            self.log_queue, threading.Event(), spec_controller=self.controller
        )
        if self.shutter_open:
            runner.closes()
            for button in self.shutter_buttons:
                button.configure(text="Open Shutter")
            self.shutter_open = False
        else:
            runner.opens()
            for button in self.shutter_buttons:
                button.configure(text="Close Shutter")
            self.shutter_open = True

    # ---- Height Scan tab: preview / run / reset ----

    def _collect_height_params(self):
        return {k: v.get().strip() for k, v in self.height_vars.items()}

    def _on_height_reset_defaults(self):
        for key, value in HEIGHTSCAN_DEFAULTS.items():
            self.height_vars[key].set(value)
        self._append_log(
            "[heightscan] fields reset to defaults ("
            + ", ".join(HEIGHTSCAN_DEFAULTS[k] for k in ("start", "end", "steps", "count_time"))
            + ")"
        )

    def _on_height_preview(self):
        """Same treatment as _on_preview above, for the height scan:
        shows the full generated command log instantly (no real
        waiting, nothing sent -- doesn't touch self.controller at
        all)."""
        h = self._collect_height_params()
        try:
            validate_height_params(h)
        except ValueError as exc:
            messagebox.showerror("Height Scan", str(exc))
            return
        rampre = self.global_vars["rampre"].get().strip()

        self._append_log("========== Preview: Height Scan (no waiting, nothing sent) ==========")
        preview_queue = queue.Queue()
        runner = Runner(preview_queue, threading.Event(), preview=True)
        runner.run_height_scan(rampre, h["start"], h["end"], h["steps"], h["count_time"])
        while not preview_queue.empty():
            self._append_log(preview_queue.get_nowait())
        self._append_log(
            "========== End preview -- click Run Height Scan to actually send this =========="
        )

    def _on_height_run(self):
        """Run the height scan for real, sending every command through
        the already-connected self.controller -- same pattern as
        _on_run above. Refuses to start while a Run Scan is already in
        progress (see the matching guard in _on_run for why: both
        change the detector's trigger mode and storage directory)."""
        if self.height_run_thread and self.height_run_thread.is_alive():
            return
        if self._other_scan_running("height_run_thread", "Height Scan"):
            return

        h = self._collect_height_params()
        try:
            validate_height_params(h)
        except ValueError as exc:
            messagebox.showerror("Height Scan", str(exc))
            return
        rampre = self.global_vars["rampre"].get().strip()

        self.height_run_button.configure(state="disabled")
        self._append_log("========== Starting Height Scan ==========")
        self._append_log(
            f"[spec] sending real commands to SPEC {self.controller.spec_host}:"
            f"{self.controller.spec_port}"
        )

        def worker():
            runner = Runner(
                self.log_queue, threading.Event(), spec_controller=self.controller
            )
            try:
                runner.run_height_scan(
                    rampre, h["start"], h["end"], h["steps"], h["count_time"]
                )
            except Exception as exc:  # surface any unexpected error to the log
                self.log_queue.put(f"[error] {exc}")
            finally:
                self.log_queue.put("__HEIGHT_DONE__")

        self.height_run_thread = threading.Thread(target=worker, daemon=True)
        self.height_run_thread.start()

    # ---- Powder Scan tab: preview / run / reset ----

    def _collect_powder_params(self):
        return {k: v.get().strip() for k, v in self.powder_vars.items()}

    def _on_powder_reset_defaults(self):
        for key, value in POWDERSCAN_DEFAULTS.items():
            self.powder_vars[key].set(value)
        self._append_log(
            "[powderscan] fields reset to defaults ("
            + ", ".join(
                POWDERSCAN_DEFAULTS[k] for k in (
                    "temperature", "wait_seconds", "phi_start",
                    "phi_end", "num_steps", "count_time",
                )
            )
            + ")"
        )

    def _on_powder_preview(self):
        """Same treatment as _on_preview/_on_height_preview above, for
        the powder scan: shows the full generated command log
        instantly (no real waiting, nothing sent -- doesn't touch
        self.controller at all)."""
        p = self._collect_powder_params()
        try:
            validate_powder_params(p)
        except ValueError as exc:
            messagebox.showerror("Powder Scan", str(exc))
            return
        g = {k: v.get().strip() for k, v in self.global_vars.items()}

        self._append_log("========== Preview: Powder Scan (no waiting, nothing sent) ==========")
        preview_queue = queue.Queue()
        runner = Runner(preview_queue, threading.Event(), preview=True)
        runner.run_powder_scan(
            g, p["temperature"], p["wait_seconds"],
            p["phi_start"], p["phi_end"], p["num_steps"], p["count_time"],
        )
        while not preview_queue.empty():
            self._append_log(preview_queue.get_nowait())
        self._append_log(
            "========== End preview -- click Run Powder Scan to actually send this =========="
        )

    def _on_powder_run(self):
        """Run the powder scan for real, sending every command through
        the already-connected self.controller -- same pattern as
        _on_run/_on_height_run above. Refuses to start while either a
        Run Scan or a Height Scan is already in progress (see the
        matching guards in _on_run/_on_height_run for why: all three
        change the detector's trigger mode and storage directory)."""
        if self.powder_run_thread and self.powder_run_thread.is_alive():
            return
        if self._other_scan_running("powder_run_thread", "Powder Scan"):
            return

        p = self._collect_powder_params()
        try:
            validate_powder_params(p)
        except ValueError as exc:
            messagebox.showerror("Powder Scan", str(exc))
            return
        g = {k: v.get().strip() for k, v in self.global_vars.items()}

        self.powder_run_button.configure(state="disabled")
        self._append_log("========== Starting Powder Scan ==========")
        self._append_log(
            f"[spec] sending real commands to SPEC {self.controller.spec_host}:"
            f"{self.controller.spec_port}"
        )

        def worker():
            runner = Runner(
                self.log_queue, threading.Event(), spec_controller=self.controller
            )
            try:
                runner.run_powder_scan(
                    g, p["temperature"], p["wait_seconds"],
                    p["phi_start"], p["phi_end"], p["num_steps"], p["count_time"],
                )
            except Exception as exc:  # surface any unexpected error to the log
                self.log_queue.put(f"[error] {exc}")
            finally:
                self.log_queue.put("__POWDER_DONE__")

        self.powder_run_thread = threading.Thread(target=worker, daemon=True)
        self.powder_run_thread.start()

    # ---- Spin Control tab ----

    def _build_spin_tab(self):
        """6th main-notebook tab -- unifies HDRMscans_new.mac's
        `spin_xtal_phi`, `spin_ice`, `spin_xtal_phi_10min`, and
        `spin_xtal_phi_20min` macros into one Start/Stop control (see
        Runner.run_spin_xtal_phi's docstring for the side-by-side
        comparison of spin_xtal_phi vs spin_ice that justified merging
        them here; the 'Number of cycles' field folds in the two
        fixed-cycle presets: 4 for the old spin_xtal_phi_10min preset,
        10 for spin_xtal_phi_20min, blank for continuous
        spin_xtal_phi/spin_ice). Unlike every other tab, this is
        Start/Stop rather than Preview/Run/Stop -- it can run
        indefinitely (blank num_cycles), so there's no fixed sequence
        worth previewing."""
        tab = self._make_scrollable_tab("Spin Control")

        self._make_wrapping_label(
            tab,
            "Continuously spins the sample (phi 0 <-> 360, translated "
            "from HDRMscans_new.mac's 'spin_xtal_phi' macro). Leave "
            "'Number of cycles' blank to spin continuously until Stop "
            "is clicked (matches spin_xtal_phi's own ~10000-cycle cap "
            "and spin_ice's unbounded loop, both effectively 'run "
            "until stopped'), or set a number for a fixed-length spin "
            "-- e.g. 4 for the old 'spin_xtal_phi_10min' preset, 10 "
            "for 'spin_xtal_phi_20min'. 'Ice mode' reproduces "
            "spin_ice's only two differences from spin_xtal_phi: a 5s "
            "startup delay, and a health-check log line + 2s pause "
            "every 100 cycles -- the sample motion itself is "
            "identical either way.",
        )

        # _make_section (rather than packing these rows straight into
        # `tab`) per explicit user request for more visually-distinct
        # panels (item 7) -- gives this tab's one control area its
        # own card instead of floating directly on the tab background.
        box = self._make_section(
            tab, "Spin Control (spin_xtal_phi)", 0, padx=8, pady=4
        )

        fields_row = ttk.Frame(box)
        fields_row.pack(fill="x", padx=8, pady=4)
        col = ttk.Frame(fields_row)
        col.pack(side="left", padx=(0, 18))
        ttk.Label(col, text="Number of cycles (blank = continuous):").pack(anchor="w")
        ttk.Entry(col, textvariable=self.spin_vars["num_cycles"], width=12).pack(anchor="w")

        ttk.Checkbutton(
            fields_row, text="Ice mode (spin_ice)", variable=self.spin_ice_mode_var,
        ).pack(side="left", padx=(0, 18), anchor="s", pady=(14, 0))

        buttons_row = ttk.Frame(box)
        buttons_row.pack(fill="x", padx=8, pady=(8, 4))
        self.spin_start_button = ttk.Button(
            buttons_row, text="Start Spin", command=self._on_spin_start,
            style="Accent.TButton",
        )
        self.spin_start_button.pack(side="left", padx=4)
        self.spin_stop_button = ttk.Button(
            buttons_row, text="Stop", command=self._on_spin_stop,
            state="disabled", style="Stop.TButton",
        )
        self.spin_stop_button.pack(side="left", padx=4)
        ttk.Button(
            buttons_row, text="Reset to defaults",
            command=self._on_spin_reset_defaults,
        ).pack(side="left", padx=4)

        ttk.Label(
            tab,
            text="Start/Stop log to the shared \"Log\" tab in the "
            "Output section below, same as every other tab.",
        ).pack(fill="x", padx=8, pady=(4, 8))

    def _collect_spin_params(self):
        p = {k: v.get().strip() for k, v in self.spin_vars.items()}
        p["ice_mode"] = "1" if self.spin_ice_mode_var.get() else "0"
        return p

    def _on_spin_reset_defaults(self):
        for key, value in SPIN_DEFAULTS.items():
            if key == "ice_mode":
                self.spin_ice_mode_var.set(value == "1")
            else:
                self.spin_vars[key].set(value)
        self._append_log("[spin] fields reset to defaults (continuous, ice mode off)")

    def _on_spin_start(self):
        """Start spinning for real, sending every command through the
        already-connected self.controller -- same pattern as
        _on_run/_on_height_run/_on_powder_run, but Start/Stop instead
        of Run/Cancel (see _build_spin_tab's docstring for why)."""
        if self.spin_run_thread and self.spin_run_thread.is_alive():
            return
        if self._other_scan_running("spin_run_thread", "Spin Control"):
            return

        p = self._collect_spin_params()
        try:
            validate_spin_params(p)
        except ValueError as exc:
            messagebox.showerror("Spin Control", str(exc))
            return

        self.spin_cancel_event.clear()
        self.spin_start_button.configure(state="disabled")
        self.spin_stop_button.configure(state="normal")
        self._append_log("========== Starting Spin Control ==========")
        self._append_log(
            f"[spec] sending real commands to SPEC {self.controller.spec_host}:"
            f"{self.controller.spec_port}"
        )

        def worker():
            runner = Runner(
                self.log_queue, self.spin_cancel_event, spec_controller=self.controller
            )
            try:
                num_cycles = float(p["num_cycles"]) if p["num_cycles"] else None
                runner.run_spin_xtal_phi(num_cycles=num_cycles, ice_mode=p["ice_mode"] == "1")
            except Exception as exc:  # surface any unexpected error to the log
                self.log_queue.put(f"[error] {exc}")
            finally:
                self.log_queue.put("__SPIN_DONE__")

        self.spin_run_thread = threading.Thread(target=worker, daemon=True)
        self.spin_run_thread.start()

    def _on_spin_stop(self):
        """Per explicit user request, Stop must halt rotation
        immediately rather than letting the in-flight `umv phi ...`
        move finish first (SPEC's CMD_WITH_RETURN sends/blocks on the
        whole move; cancel_event is only ever checked by
        run_spin_xtal_phi between moves -- see its docstring). Setting
        cancel_event alone still stops looping, but the move already
        sent to SPEC keeps going to completion on its own; sending a
        real SPEC abort (the same one the raw STOP button sends --
        see _stop_command) interrupts that move immediately, like
        Ctrl+C at the console. Uses _abort_until_stopped (a few
        automatic retries while spin_run_thread is still alive)
        rather than a single attempt -- see its docstring."""
        self.spin_cancel_event.set()
        self._append_log("[spin] stop requested -- aborting current move...")
        self._last_spin_abort_thread = self._abort_until_stopped(
            lambda: self.spin_run_thread is not None and self.spin_run_thread.is_alive()
        )

    # ---- N2 -> He Switch section (top of Low Temp Scan tab) ----

    def _build_n2_to_he_switch_section(self, tab):
        """Lives at the very top of the Low Temp Scan tab, per the
        site's own description of this procedure as the thing done
        immediately before a low-temperature scan. Translated from
        Lakeshore336cryocool.mac's `prepswitch`/`runninghelium`
        macros plus several other manual FOURC commands, normally run
        one at a time by hand -- this consolidates the whole "300K ->
        15K: Room Temperature to base (change N2 to He flow)"
        procedure into a single one-click Run button. See
        N2_TO_HE_SWITCH_DEFAULTS' docstring in hrdm_core.py for the
        full step-by-step breakdown and the reasoning behind every
        default value. One step (turning the He valve on and the N2
        valve off together) is a physical action that can't be
        automated -- Run will pause only in the sense of logging a
        clear instruction there, then immediately continues (it does
        NOT actually wait for operator confirmation before moving on,
        since there's no reliable way to detect the valve switch from
        here -- see the log line and the README for details)."""
        # _make_section (rather than a plain ttk.LabelFrame) per
        # explicit user request for more visually-distinct panels
        # (item 7); color index 1 keeps it visually distinct from the
        # Quick Temp/Flow Control panel above it on this tab (index 0).
        frame = self._make_section(
            tab, "N2 -> He Gas Switch (300K -> 15K: Room Temperature to base)",
            1, padx=8, pady=(4, 4),
        )

        self._make_wrapping_label(
            frame,
            "One-click version of the manual gas-switch procedure "
            "(translated from Lakeshore336cryocool.mac's `prepswitch`/"
            "`runninghelium` macros and several other manual FOURC "
            "commands). All setpoints and all three wait times "
            "(expressed here in minutes) are editable. Run this "
            "before Low Temp Scan below when switching from N2 to He "
            "gas flow. All 4 step-groups are unchecked (disabled) by "
            "default -- check a step-group's \"Enabled\" box below to "
            "have \"Run N2 -> He Switch\" include it (like checking a "
            "phase on the Warmup tab). Step 1 only sets the two "
            "Lakeshore setpoints, matching the real "
            "Lakeshore336cryocool.mac `prepswitch` macro exactly -- it "
            "never calls flow_set.",
        )

        temps_row = ttk.LabelFrame(frame, text="Live temperatures (EPICS)")
        temps_row.pack(fill="x", padx=8, pady=(0, 4))
        for label, var in (
            ("Stage A:", self.n2_he_stage_a_temp_var),
            ("Stage C:", self.n2_he_stage_c_temp_var),
            ("Sample:", self.n2_he_sample_temp_var),
        ):
            col = ttk.Frame(temps_row)
            col.pack(side="left", padx=(6, 16), pady=4)
            ttk.Label(col, text=label).pack(side="left")
            ttk.Label(col, textvariable=var, width=10, anchor="w").pack(side="left")
        self.n2_he_read_temps_button = ttk.Button(
            temps_row, text="Read Temperatures", command=self._on_read_n2_he_temps
        )
        self.n2_he_read_temps_button.pack(side="left", padx=(0, 12), pady=4)
        ttk.Checkbutton(
            temps_row,
            text=f"Auto-watch Temperatures (every {_N2_HE_TEMP_WATCH_INTERVAL_MS // 1000}s)",
            variable=self.n2_he_temp_watch_var,
            command=self._on_toggle_n2_he_temp_watch,
        ).pack(side="left", pady=4)

        stage_row = ttk.Frame(frame)
        stage_row.pack(fill="x", padx=8, pady=4)

        prepswitch_col = ttk.LabelFrame(stage_row, text="Step 1: prepswitch")
        prepswitch_col.pack(side="left", padx=(0, 14), fill="y")
        ttk.Checkbutton(
            prepswitch_col, text="Enabled", variable=self.n2_he_switch_enabled_vars["step1_enabled"]
        ).pack(anchor="w", padx=6, pady=(4, 0))
        for key, label, width in (
            ("prepswitch_stage_a", "Stage A setpoint, K", 14),
            ("prepswitch_stage_c", "Stage C setpoint, K", 14),
            ("wait_after_prepswitch_minutes", "Wait, min", 10),
        ):
            row = ttk.Frame(prepswitch_col)
            row.pack(anchor="w", padx=6, pady=2)
            ttk.Label(row, text=label + ":").pack(side="left")
            ttk.Entry(
                row, textvariable=self.n2_he_switch_vars[key], width=width
            ).pack(side="left", padx=(4, 0))

        temp_col = ttk.LabelFrame(stage_row, text="Steps 3-5: te / flow_set / wait")
        temp_col.pack(side="left", padx=(0, 14), fill="y")
        ttk.Checkbutton(
            temp_col, text="Enabled", variable=self.n2_he_switch_enabled_vars["steps3_5_enabled"]
        ).pack(anchor="w", padx=6, pady=(4, 0))
        for key, label, width in (
            ("sample_temp_1", "Sample temp, K", 14),
            ("flow_1", "flow_set", 14),
            ("wait_for_sample_temp_minutes", "Wait, min", 10),
        ):
            row = ttk.Frame(temp_col)
            row.pack(anchor="w", padx=6, pady=2)
            ttk.Label(row, text=label + ":").pack(side="left")
            ttk.Entry(
                row, textvariable=self.n2_he_switch_vars[key], width=width
            ).pack(side="left", padx=(4, 0))

        helium_col = ttk.LabelFrame(stage_row, text="Step 7: runninghelium")
        helium_col.pack(side="left", padx=(0, 14), fill="y")
        ttk.Checkbutton(
            helium_col, text="Enabled", variable=self.n2_he_switch_enabled_vars["step7_enabled"]
        ).pack(anchor="w", padx=6, pady=(4, 0))
        for key, label, width in (
            ("runninghelium_stage_a", "Stage A setpoint, K", 14),
            ("runninghelium_stage_c", "Stage C setpoint, K", 14),
            ("wait_for_base_temp_minutes", "Wait, min", 10),
        ):
            row = ttk.Frame(helium_col)
            row.pack(anchor="w", padx=6, pady=2)
            ttk.Label(row, text=label + ":").pack(side="left")
            ttk.Entry(
                row, textvariable=self.n2_he_switch_vars[key], width=width
            ).pack(side="left", padx=(4, 0))

        final_col = ttk.LabelFrame(stage_row, text="Steps 8-10: flow_set / te / spin")
        final_col.pack(side="left", fill="y")
        ttk.Checkbutton(
            final_col, text="Enabled", variable=self.n2_he_switch_enabled_vars["steps8_10_enabled"]
        ).pack(anchor="w", padx=6, pady=(4, 0))
        for key, label, width in (
            ("flow_2", "flow_set", 14),
            ("sample_temp_2", "Sample temp, K", 14),
            ("spin_cycles", "spin_xtal_phi cycles", 14),
        ):
            row = ttk.Frame(final_col)
            row.pack(anchor="w", padx=6, pady=2)
            ttk.Label(row, text=label + ":").pack(side="left")
            ttk.Entry(
                row, textvariable=self.n2_he_switch_vars[key], width=width
            ).pack(side="left", padx=(4, 0))

        buttons_row = ttk.Frame(frame)
        buttons_row.pack(fill="x", padx=8, pady=(8, 4))
        ttk.Button(
            buttons_row, text="Preview", command=self._on_n2_to_he_switch_preview
        ).pack(side="left", padx=4)
        self.n2_he_switch_run_button = ttk.Button(
            buttons_row, text="Run N2 -> He Switch",
            command=self._on_n2_to_he_switch_run,
        )
        self.n2_he_switch_run_button.pack(side="left", padx=4)
        self.n2_he_switch_step1_button = ttk.Button(
            buttons_row, text="Run Step 1 Only (prepswitch)",
            command=self._on_n2_to_he_switch_run_step1,
        )
        self.n2_he_switch_step1_button.pack(side="left", padx=4)
        self.n2_he_switch_steps35_button = ttk.Button(
            buttons_row, text="Run Steps 3-5 Only",
            command=self._on_n2_to_he_switch_run_steps_3_5,
        )
        self.n2_he_switch_steps35_button.pack(side="left", padx=4)
        self.n2_he_switch_step7_button = ttk.Button(
            buttons_row, text="Run Step 7 Only (runninghelium)",
            command=self._on_n2_to_he_switch_run_step7,
        )
        self.n2_he_switch_step7_button.pack(side="left", padx=4)
        self.n2_he_switch_steps8_10_button = ttk.Button(
            buttons_row, text="Run Steps 8-10 Only",
            command=self._on_n2_to_he_switch_run_steps_8_10,
        )
        self.n2_he_switch_steps8_10_button.pack(side="left", padx=4)
        self.n2_he_switch_stop_button = ttk.Button(
            buttons_row, text="Stop", command=self._on_n2_to_he_switch_stop,
            state="disabled", style="Stop.TButton",
        )
        self.n2_he_switch_stop_button.pack(side="left", padx=4)
        ttk.Button(
            buttons_row, text="Reset to defaults",
            command=self._on_n2_to_he_switch_reset_defaults,
        ).pack(side="left", padx=4)

        self._make_wrapping_label(
            frame,
            "Note: turning on the Helium valve and closing the "
            "Nitrogen valve together (step 6) is a physical action "
            "that cannot be automated from here -- Run logs a clear "
            "instruction at that point in the sequence, then "
            "continues immediately (it does not pause for "
            "confirmation). Set any wait time to 0 to skip it "
            "entirely. \"Run Step 1 Only\" sends just the prepswitch "
            "setpoints and its wait; \"Run Steps 3-5 Only\" sends just "
            "the intermediate te/flow_set and its wait; \"Run Step 7 "
            "Only\" logs the Step 6 valve-switch instruction then "
            "sends just the runninghelium setpoints and its wait; "
            "\"Run Steps 8-10 Only\" sends just the final flow_set/te "
            "setpoints and spin cycles -- use any one of these "
            "instead of the full \"Run N2 -> He Switch\" button if "
            "you want to check hardware state by hand between steps.",
        )

    def _collect_n2_to_he_switch_params(self):
        params = {k: v.get().strip() for k, v in self.n2_he_switch_vars.items()}
        params.update(
            {k: ("1" if v.get() else "0") for k, v in self.n2_he_switch_enabled_vars.items()}
        )
        return params

    def _on_n2_to_he_switch_reset_defaults(self):
        for key, value in N2_TO_HE_SWITCH_DEFAULTS.items():
            if key in self.n2_he_switch_enabled_vars:
                self.n2_he_switch_enabled_vars[key].set(value == "1")
            else:
                self.n2_he_switch_vars[key].set(value)
        # A fresh reset means the prepswitch setpoints may have changed --
        # clear the "next stage is ready" latch so a stale readiness
        # message isn't left showing against new setpoints.
        self._n2_he_prepswitch_ready_logged = False
        self._append_log("[n2_to_he_switch] fields reset to defaults")

    def _on_n2_to_he_switch_preview(self):
        p = self._collect_n2_to_he_switch_params()
        try:
            validate_n2_to_he_switch_params(p)
        except ValueError as exc:
            messagebox.showerror("N2 -> He Switch", str(exc))
            return

        self._append_log("========== Preview: N2 -> He Switch (no waiting, nothing sent) ==========")
        preview_queue = queue.Queue()
        runner = Runner(preview_queue, threading.Event(), preview=True)
        runner.run_n2_to_he_switch(p)
        while not preview_queue.empty():
            self._append_log(preview_queue.get_nowait())
        self._append_log(
            "========== End preview -- click Run N2 -> He Switch to actually send this =========="
        )

    def _n2_he_switch_buttons(self):
        """All five "Run..." buttons for this section -- always
        enabled/disabled together, since they share one cancel event
        and one thread slot (self.n2_he_switch_run_thread) and so can
        never run concurrently with each other, only sequentially."""
        return (
            self.n2_he_switch_run_button,
            self.n2_he_switch_step1_button,
            self.n2_he_switch_steps35_button,
            self.n2_he_switch_step7_button,
            self.n2_he_switch_steps8_10_button,
        )

    def _start_n2_to_he_switch_job(self, runner_method_name, start_label):
        """Shared launcher for the whole-sequence Run button and the
        Step 1 / Steps 3-5 / Step 7 / Steps 8-10 partial-run buttons
        -- they all send real commands over the one shared SPEC
        connection, so they share the same concurrency guard, cancel
        event, and thread slot; only the Runner method actually
        invoked (by name, looked up via getattr) differs between
        them."""
        if self.n2_he_switch_run_thread and self.n2_he_switch_run_thread.is_alive():
            return
        if self._other_scan_running("n2_he_switch_run_thread", "N2 -> He Switch"):
            return

        p = self._collect_n2_to_he_switch_params()
        try:
            validate_n2_to_he_switch_params(p)
        except ValueError as exc:
            messagebox.showerror("N2 -> He Switch", str(exc))
            return

        self.n2_he_switch_cancel_event.clear()
        for btn in self._n2_he_switch_buttons():
            btn.configure(state="disabled")
        self.n2_he_switch_stop_button.configure(state="normal")
        self._append_log(f"========== {start_label} ==========")
        self._append_log(
            f"[spec] sending real commands to SPEC {self.controller.spec_host}:"
            f"{self.controller.spec_port}"
        )

        def worker():
            runner = Runner(
                self.log_queue, self.n2_he_switch_cancel_event, spec_controller=self.controller
            )
            try:
                getattr(runner, runner_method_name)(p)
            except Exception as exc:  # surface any unexpected error to the log
                self.log_queue.put(f"[error] {exc}")
            finally:
                self.log_queue.put("__N2_HE_SWITCH_DONE__")

        self.n2_he_switch_run_thread = threading.Thread(target=worker, daemon=True)
        self.n2_he_switch_run_thread.start()

    def _on_n2_to_he_switch_run(self):
        self._start_n2_to_he_switch_job("run_n2_to_he_switch", "Starting N2 -> He Switch")

    def _on_n2_to_he_switch_run_step1(self):
        self._start_n2_to_he_switch_job(
            "run_n2_to_he_step1", "Starting N2 -> He Switch: Step 1 Only (prepswitch)"
        )

    def _on_n2_to_he_switch_run_steps_3_5(self):
        self._start_n2_to_he_switch_job(
            "run_n2_to_he_steps_3_to_5", "Starting N2 -> He Switch: Steps 3-5 Only"
        )

    def _on_n2_to_he_switch_run_step7(self):
        self._start_n2_to_he_switch_job(
            "run_n2_to_he_step7", "Starting N2 -> He Switch: Step 7 Only (runninghelium)"
        )

    def _on_n2_to_he_switch_run_steps_8_10(self):
        self._start_n2_to_he_switch_job(
            "run_n2_to_he_steps_8_to_10", "Starting N2 -> He Switch: Steps 8-10 Only"
        )

    def _on_n2_to_he_switch_stop(self):
        self.n2_he_switch_cancel_event.set()
        self._append_log("[n2_to_he_switch] stop requested -- finishing current step...")

    # ---- Low Temp Scan tab ----

    def _build_low_temp_tab(self):
        """7th main-notebook tab -- translated from
        HDRMscans_new.mac's `low_temp_scan` macro. Fully parametrized,
        including the loop bounds -- see LOW_TEMP_SCAN_DEFAULTS'
        docstring in hrdm_core.py for why the defaults here (30/110/
        10) come from the macro's ACTUAL loop, not its own
        (mismatched) printed messages. Shares 'datafile', 'sample',
        and 'rampre' from the Sample Information tab's Global
        parameters box, same as Powder Scan -- each temperature step runs a full
        HDRM scan there via the same per-sample/temperature folder
        scheme. The full HDRM scan itself (passes, flyscan step
        count, count time) is set independently below, in its own
        "HDRM Scan Parameters" section -- it no longer shares
        'count_time' with the Threextal Scan tab."""
        tab = self._make_scrollable_tab("Low Temp Scan")

        self._build_standalone_temp_flow_section(tab, "lowtemp")
        self._build_low_temp_standalone_spin_section(tab)

        self._build_n2_to_he_switch_section(tab)

        ttk.Separator(tab, orient="horizontal").pack(fill="x", padx=8, pady=(4, 10))

        self._make_wrapping_label(
            tab,
            "Steps the sample temperature from Start to End (by "
            "Step), spinning the sample and running a full HDRM scan "
            "at each temperature (translated from "
            "HDRMscans_new.mac's 'low_temp_scan' macro). Defaults "
            "(30K to 110K, step 10K) match the macro's ACTUAL loop "
            "bounds, not its own printed messages, which describe a "
            "different, inconsistent range -- see the README for "
            "details. Uses 'datafile', 'sample', and 'rampre' from "
            "the Sample Information tab's Global parameters box for "
            "each scan, same as Powder Scan -- the full HDRM scan's own "
            "passes/steps/count time are set below and are "
            "independent of the Threextal Scan tab.",
        )

        fields_row = ttk.Frame(tab)
        fields_row.pack(fill="x", padx=8, pady=4)
        for key, label, width in (
            ("start_temp", "Start temp, K", 10),
            ("end_temp", "End temp, K", 10),
            ("step_temp", "Step, K", 8),
            ("spin_cycles", "Spin cycles/step", 14),
            ("post_temp_wait_seconds", "Wait after te, s", 14),
        ):
            col = ttk.Frame(fields_row)
            col.pack(side="left", padx=(0, 14))
            ttk.Label(col, text=label + ":").pack(anchor="w")
            ttk.Entry(col, textvariable=self.low_temp_vars[key], width=width).pack(anchor="w")

        self.low_temp_passes_table = self._build_hdrm_scan_params_section(
            tab, self.low_temp_num_steps_var, self.low_temp_count_time_var
        )

        buttons_row = ttk.Frame(tab)
        buttons_row.pack(fill="x", padx=8, pady=(8, 4))
        ttk.Button(
            buttons_row, text="Preview", command=self._on_low_temp_preview
        ).pack(side="left", padx=4)
        self.low_temp_run_button = ttk.Button(
            buttons_row, text="Run Low Temp Scan", command=self._on_low_temp_run,
            style="Accent.TButton",
        )
        self.low_temp_run_button.pack(side="left", padx=4)
        self.low_temp_stop_button = ttk.Button(
            buttons_row, text="Stop", command=self._on_low_temp_stop,
            state="disabled", style="Stop.TButton",
        )
        self.low_temp_stop_button.pack(side="left", padx=4)
        ttk.Button(
            buttons_row, text="Reset to defaults",
            command=self._on_low_temp_reset_defaults,
        ).pack(side="left", padx=4)

        ttk.Label(
            tab,
            text="Preview and Run both log to the shared \"Log\" tab "
            "in the Output section below, same as every other tab. "
            "This is a long-running, multi-temperature scan -- use "
            "Stop to cancel partway through.",
        ).pack(fill="x", padx=8, pady=(4, 8))

        ttk.Separator(tab, orient="horizontal").pack(fill="x", padx=8, pady=(4, 10))

        sample_setup_frame = ttk.LabelFrame(
            tab, text="Sample Setup (standalone -- no macro precedent, project addition)"
        )
        sample_setup_frame.pack(fill="x", padx=8, pady=4)
        ttk.Label(
            sample_setup_frame,
            text="Sends only te and flow_set, independent of the Low "
            "Temp Scan sequence above and the N2 -> He Gas Switch "
            "section -- click any time, in any order.",
            wraplength=760, justify="left",
        ).pack(fill="x", padx=6, pady=(4, 2), anchor="w")
        setup_fields_row = ttk.Frame(sample_setup_frame)
        setup_fields_row.pack(fill="x", padx=6, pady=(0, 4))
        for key, label, width in (
            ("sample_temp", "Sample temp, te (K)", 16),
            ("sample_flow", "flow_set", 12),
        ):
            col = ttk.Frame(setup_fields_row)
            col.pack(side="left", padx=(0, 14))
            ttk.Label(col, text=label + ":").pack(anchor="w")
            ttk.Entry(
                col, textvariable=self.low_temp_sample_setup_vars[key], width=width
            ).pack(anchor="w")
        setup_buttons_row = ttk.Frame(sample_setup_frame)
        setup_buttons_row.pack(fill="x", padx=6, pady=(0, 6))
        self.low_temp_sample_setup_run_button = ttk.Button(
            setup_buttons_row, text="Run Sample Setup",
            command=self._on_low_temp_sample_setup_run,
        )
        self.low_temp_sample_setup_run_button.pack(side="left", padx=4)
        self.low_temp_sample_setup_stop_button = ttk.Button(
            setup_buttons_row, text="Stop", command=self._on_low_temp_sample_setup_stop,
            state="disabled", style="Stop.TButton",
        )
        self.low_temp_sample_setup_stop_button.pack(side="left", padx=4)
        ttk.Button(
            setup_buttons_row, text="Reset to defaults",
            command=self._on_low_temp_sample_setup_reset_defaults,
        ).pack(side="left", padx=4)

    def _collect_low_temp_params(self):
        p = {k: v.get().strip() for k, v in self.low_temp_vars.items()}
        p["scan_passes"] = self.low_temp_passes_table.get()
        p["num_steps"] = self.low_temp_num_steps_var.get().strip()
        p["count_time"] = self.low_temp_count_time_var.get().strip()
        return p

    def _on_low_temp_reset_defaults(self):
        for key, value in LOW_TEMP_SCAN_DEFAULTS.items():
            self.low_temp_vars[key].set(value)
        self.low_temp_passes_table.reset_to_defaults()
        self.low_temp_num_steps_var.set(HDRM_SCAN_DEFAULTS["num_steps"])
        self.low_temp_count_time_var.set(HDRM_SCAN_DEFAULTS["count_time"])
        self._append_log(
            "[low_temp_scan] fields reset to defaults ("
            + ", ".join(
                LOW_TEMP_SCAN_DEFAULTS[k] for k in (
                    "start_temp", "end_temp", "step_temp",
                    "spin_cycles", "post_temp_wait_seconds",
                )
            )
            + "), HDRM Scan Parameters reset to defaults too"
        )

    def _on_low_temp_preview(self):
        p = self._collect_low_temp_params()
        try:
            validate_low_temp_params(p)
            validate_hdrm_scan_params(p["scan_passes"], p["num_steps"], p["count_time"])
        except ValueError as exc:
            messagebox.showerror("Low Temp Scan", str(exc))
            return
        g = {k: v.get().strip() for k, v in self.global_vars.items()}

        self._append_log("========== Preview: Low Temp Scan (no waiting, nothing sent) ==========")
        preview_queue = queue.Queue()
        runner = Runner(preview_queue, threading.Event(), preview=True)
        runner.run_low_temp_scan(
            g, p["start_temp"], p["end_temp"], p["step_temp"],
            p["spin_cycles"], p["post_temp_wait_seconds"],
            scan_passes=p["scan_passes"], num_steps=p["num_steps"],
            count_time=p["count_time"],
        )
        while not preview_queue.empty():
            self._append_log(preview_queue.get_nowait())
        self._append_log(
            "========== End preview -- click Run Low Temp Scan to actually send this =========="
        )

    def _on_low_temp_run(self):
        if self.low_temp_run_thread and self.low_temp_run_thread.is_alive():
            return
        if self._other_scan_running("low_temp_run_thread", "Low Temp Scan"):
            return

        p = self._collect_low_temp_params()
        try:
            validate_low_temp_params(p)
            validate_hdrm_scan_params(p["scan_passes"], p["num_steps"], p["count_time"])
        except ValueError as exc:
            messagebox.showerror("Low Temp Scan", str(exc))
            return
        g = {k: v.get().strip() for k, v in self.global_vars.items()}

        self.low_temp_cancel_event.clear()
        self.low_temp_run_button.configure(state="disabled")
        self.low_temp_stop_button.configure(state="normal")
        self._append_log("========== Starting Low Temp Scan ==========")
        self._append_log(
            f"[spec] sending real commands to SPEC {self.controller.spec_host}:"
            f"{self.controller.spec_port}"
        )

        def worker():
            runner = Runner(
                self.log_queue, self.low_temp_cancel_event, spec_controller=self.controller
            )
            try:
                runner.run_low_temp_scan(
                    g, p["start_temp"], p["end_temp"], p["step_temp"],
                    p["spin_cycles"], p["post_temp_wait_seconds"],
                    scan_passes=p["scan_passes"], num_steps=p["num_steps"],
                    count_time=p["count_time"],
                )
            except Exception as exc:  # surface any unexpected error to the log
                self.log_queue.put(f"[error] {exc}")
            finally:
                scan_n = getattr(runner, "scan_n", None)
                if scan_n is not None:
                    self.log_queue.put(("__SCANN__", scan_n))
                self.log_queue.put("__LOW_TEMP_DONE__")

        self.low_temp_run_thread = threading.Thread(target=worker, daemon=True)
        self.low_temp_run_thread.start()

    def _on_low_temp_stop(self):
        """Unlike every spin-stop handler, this previously only set
        low_temp_cancel_event and never aborted the in-flight SPEC
        command, so a running Low Temp Scan spin cycle kept rotating
        until it happened to finish on its own. Now matches the same
        abort-and-retry pattern as _on_spin_stop via
        _abort_until_stopped."""
        self.low_temp_cancel_event.set()
        self._append_log("[low_temp_scan] stop requested -- aborting current step...")
        self._last_low_temp_abort_thread = self._abort_until_stopped(
            lambda: self.low_temp_run_thread is not None
            and self.low_temp_run_thread.is_alive()
        )

    # ---- Low Temp Scan tab's standalone "Sample Setup" button ----

    def _collect_low_temp_sample_setup_params(self):
        return {k: v.get().strip() for k, v in self.low_temp_sample_setup_vars.items()}

    def _on_low_temp_sample_setup_reset_defaults(self):
        for key, value in LOW_TEMP_SAMPLE_SETUP_DEFAULTS.items():
            self.low_temp_sample_setup_vars[key].set(value)
        self._append_log(
            "[low_temp_scan] Sample Setup fields reset to defaults ("
            + ", ".join(
                LOW_TEMP_SAMPLE_SETUP_DEFAULTS[k] for k in ("sample_temp", "sample_flow")
            )
            + ")"
        )

    def _on_low_temp_sample_setup_run(self):
        """Deliberately independent of every other scan/macro/action
        anywhere else in the app (no _other_scan_running call) --
        per explicit user request that quick temperature/flow setup
        actions must never block, or be blocked by, anything else.
        Still guards against double-clicking this same button while
        its own previous click is still running."""
        if (
            self.low_temp_sample_setup_run_thread
            and self.low_temp_sample_setup_run_thread.is_alive()
        ):
            return

        p = self._collect_low_temp_sample_setup_params()
        try:
            validate_low_temp_sample_setup_params(p)
        except ValueError as exc:
            messagebox.showerror("Low Temp Scan: Sample Setup", str(exc))
            return

        self.low_temp_sample_setup_cancel_event.clear()
        self.low_temp_sample_setup_run_button.configure(state="disabled")
        self.low_temp_sample_setup_stop_button.configure(state="normal")
        self._append_log("========== Starting Low Temp Scan: Sample Setup ==========")
        self._append_log(
            f"[spec] sending real commands to SPEC {self.controller.spec_host}:"
            f"{self.controller.spec_port}"
        )

        def worker():
            runner = Runner(
                self.log_queue, self.low_temp_sample_setup_cancel_event,
                spec_controller=self.controller,
            )
            try:
                runner.run_low_temp_sample_setup(p["sample_temp"], p["sample_flow"])
            except Exception as exc:  # surface any unexpected error to the log
                self.log_queue.put(f"[error] {exc}")
            finally:
                self.log_queue.put("__LOW_TEMP_SAMPLE_SETUP_DONE__")

        self.low_temp_sample_setup_run_thread = threading.Thread(target=worker, daemon=True)
        self.low_temp_sample_setup_run_thread.start()

    def _on_low_temp_sample_setup_stop(self):
        self.low_temp_sample_setup_cancel_event.set()
        self._append_log("[low_temp_scan] Sample Setup stop requested...")

    # ---- Warmup tab ----

    def _build_warmup_tab(self):
        """8th main-notebook tab -- translated from
        HDRMscans_new.mac's `warmup` macro's 3 hard-coded phases (Low/
        Medium/High N2 flow). Every number on every phase is editable
        (defaults from hrdm_core.WARMUP_PHASE_DEFAULTS) -- including
        each phase's "Prep sample stage setup" (Lakeshore Stage A/
        Stage C setpoints sent by prepN2_low/_medium/_high, straight
        from Lakeshore336cryocool.mac, e.g. Phase 1/Low N2 flow: Stage
        A=87, Stage C=85); each phase can also be independently
        enabled/disabled via its own checkbox -- the macro itself
        always runs all 3 in sequence with no way to skip one, so this
        is a deliberate, additive parametrization beyond the macro,
        same as Powder Scan's flyscan range. Phase 3's 'Spin cycles/
        step' defaults to 0 -- faithfully matching a real asymmetry in
        the macro, where Phase 3's per-step loop (unlike Phase 1 and
        2's) never calls spin_xtal_phi_10min; see the README for
        details. Each phase also has its own "Return to Room Temp
        after this phase" checkbox (off by default, also not part of
        the real macro) that, if checked, sends a sample temperature
        (te) + gas flow (flow_set) immediately after that phase's own
        temperature loop finishes, before moving on to the next phase
        -- independent of, and freely combinable with, the other
        phases' own checkboxes and the shared "Phase 4 (final step)"
        checkbox below; the run always proceeds automatically with no
        pause either way. A "Phase 4 (final step)" checkbox (off by
        default, also not part of the real macro) optionally sends one
        more sample temperature (te) + gas flow (flow_set) after every
        enabled phase finishes -- both editable, defaulting to 300K/6."""
        tab = self._make_scrollable_tab("Warmup")
        self._build_standalone_temp_flow_section(tab, "warmup")

        self._make_wrapping_label(
            tab,
            "Runs up to 3 warmup phases in sequence (translated from "
            "HDRMscans_new.mac's 'warmup' macro) -- each phase preps "
            "a N2 gas flow (with editable Lakeshore Stage A/Stage C "
            "setpoints), does an initial spin, then steps the "
            "temperature from Start to End (by Step), spinning and "
            "running a full HDRM scan at each step. All 3 phases are "
            "unchecked (disabled) by default -- check a phase to "
            "include it (the macro itself always runs all 3). Uses "
            "'datafile', 'sample', and 'rampre' from the Threextal "
            "Scan tab's Global parameters box for each scan -- the "
            "full HDRM scan's own passes/steps/count time (shared by "
            "all 3 phases) are set below and are independent of the "
            "Threextal Scan tab. Each phase also has its own \"Return "
            "to Room Temp after this phase\" checkbox (unchecked by "
            "default) to pause at room temperature right after that "
            "phase finishes before continuing on -- independent of, "
            "and combinable with, the other phases' own checkboxes. "
            "Optionally enable Phase 4 below to send a final sample "
            "temperature + gas flow, returning toward room "
            "temperature/flow once all phases finish.",
        )

        # _make_section (rather than a plain ttk.LabelFrame) per
        # explicit user request for more visually-distinct panels
        # (item 7) -- each phase gets its own color (offset by 1 so
        # Phase 1 doesn't repeat the Quick Temp/Flow Control panel's
        # color 0 above), so the 3 phases are distinguishable from
        # each other at a glance, not just by their text labels.
        for phase_index, phase in enumerate(self.warmup_phase_vars):
            frame = self._make_section(
                tab, phase["label"], phase_index + 1, padx=8, pady=4
            )

            ttk.Checkbutton(
                frame, text="Enabled", variable=phase["enabled"]
            ).pack(anchor="w", padx=6, pady=(4, 2))

            fields_row = ttk.Frame(frame)
            fields_row.pack(fill="x", padx=6, pady=(0, 6))
            for key, label, width in (
                ("initial_temp", "Initial temp, K", 12),
                ("flow_initial", "Initial flow", 10),
                ("spin20_cycles", "Initial spin cycles", 15),
                ("start_temp", "Start temp, K", 12),
                ("end_temp", "End temp, K", 12),
                ("step_temp", "Step, K", 8),
                ("spin_per_step_cycles", "Spin cycles/step", 15),
            ):
                col = ttk.Frame(fields_row)
                col.pack(side="left", padx=(0, 10))
                ttk.Label(col, text=label + ":").pack(anchor="w")
                ttk.Entry(col, textvariable=phase[key], width=width).pack(anchor="w")

            # Prep sample stage setup -- the Lakeshore 336 cryocooler
            # setpoints this phase's gas prep (prepN2_low/_medium/
            # _high) sends, straight from Lakeshore336cryocool.mac
            # (e.g. Phase 1/Low N2 flow: Stage A=87, Stage C=85).
            # Editable here like every other number on this tab, in
            # case the real macro's setpoints ever change.
            stage_row = ttk.Frame(frame)
            stage_row.pack(fill="x", padx=6, pady=(0, 6))
            ttk.Label(
                stage_row, text="Prep sample stage setup (Lakeshore):"
            ).pack(side="left", padx=(0, 8))
            for key, label, width in (
                ("stage_a", "Stage A, K", 10),
                ("stage_c", "Stage C, K", 10),
            ):
                col = ttk.Frame(stage_row)
                col.pack(side="left", padx=(0, 10))
                ttk.Label(col, text=label + ":").pack(anchor="w")
                ttk.Entry(col, textvariable=phase[key], width=width).pack(anchor="w")

            # Optional "return to room temp after this phase"
            # interlude -- off by default, independent per phase (see
            # this method's docstring and WARMUP_PHASE_DEFAULTS'
            # comment). Bound directly to a StringVar with onvalue/
            # offvalue "1"/"0" (rather than a separate tk.BooleanVar)
            # so it flows through the existing generic per-phase
            # vars-collection/reset code above/below unchanged.
            room_temp_row = ttk.Frame(frame)
            room_temp_row.pack(fill="x", padx=6, pady=(0, 6))
            ttk.Checkbutton(
                room_temp_row,
                text="Return to Room Temp after this phase",
                variable=phase["room_temp_after_enabled"],
                onvalue="1", offvalue="0",
            ).pack(side="left", padx=(0, 10))
            for key, label, width in (
                ("room_temp_after_te", "Sample temp, te (K)", 16),
                ("room_temp_after_flow", "flow_set", 12),
            ):
                col = ttk.Frame(room_temp_row)
                col.pack(side="left", padx=(0, 10))
                ttk.Label(col, text=label + ":").pack(anchor="w")
                ttk.Entry(col, textvariable=phase[key], width=width).pack(anchor="w")

        self.warmup_passes_table = self._build_hdrm_scan_params_section(
            tab, self.warmup_num_steps_var, self.warmup_count_time_var
        )

        final_step_frame = ttk.LabelFrame(tab, text="Phase 4 (final step)")
        final_step_frame.pack(fill="x", padx=8, pady=4)
        ttk.Checkbutton(
            final_step_frame,
            text="Enable Phase 4 after all enabled phases finish "
            "(not part of the original macro; sends the sample "
            "temperature and gas flow below to leave the sample near "
            "room temperature/flow at the end of the warmup sequence)",
            variable=self.warmup_final_te_300_var,
        ).pack(anchor="w", padx=6, pady=(4, 2))
        final_step_fields_row = ttk.Frame(final_step_frame)
        final_step_fields_row.pack(fill="x", padx=6, pady=(0, 6))
        for var, label, width in (
            (self.warmup_final_sample_temp_var, "Sample temp, te (K)", 16),
            (self.warmup_final_sample_flow_var, "flow_set", 12),
        ):
            col = ttk.Frame(final_step_fields_row)
            col.pack(side="left", padx=(0, 14))
            ttk.Label(col, text=label + ":").pack(anchor="w")
            ttk.Entry(col, textvariable=var, width=width).pack(anchor="w")

        buttons_row = ttk.Frame(tab)
        buttons_row.pack(fill="x", padx=8, pady=(8, 4))
        ttk.Button(
            buttons_row, text="Preview", command=self._on_warmup_preview
        ).pack(side="left", padx=4)
        self.warmup_run_button = ttk.Button(
            buttons_row, text="Run Warmup", command=self._on_warmup_run,
            style="Accent.TButton",
        )
        self.warmup_run_button.pack(side="left", padx=4)
        self.warmup_stop_button = ttk.Button(
            buttons_row, text="Stop", command=self._on_warmup_stop,
            state="disabled", style="Stop.TButton",
        )
        self.warmup_stop_button.pack(side="left", padx=4)
        ttk.Button(
            buttons_row, text="Reset to defaults",
            command=self._on_warmup_reset_defaults,
        ).pack(side="left", padx=4)

        ttk.Label(
            tab,
            text="Preview and Run both log to the shared \"Log\" tab "
            "in the Output section below. This is a long-running, "
            "multi-phase scan -- use Stop to cancel partway through.",
        ).pack(fill="x", padx=8, pady=(4, 8))

    def _collect_warmup_phases(self):
        phases = []
        for phase in self.warmup_phase_vars:
            d = {
                "label": phase["label"],
                "prep_fn": phase["prep_fn"],
                "enabled": "1" if phase["enabled"].get() else "0",
            }
            for key, var in phase.items():
                if key in ("label", "prep_fn", "enabled"):
                    continue
                d[key] = var.get().strip()
            phases.append(d)
        return phases

    def _on_warmup_reset_defaults(self):
        for phase_vars, defaults in zip(self.warmup_phase_vars, WARMUP_PHASE_DEFAULTS):
            phase_vars["enabled"].set(defaults["enabled"] == "1")
            for key, value in defaults.items():
                if key in ("label", "prep_fn", "enabled"):
                    continue
                phase_vars[key].set(value)
        self.warmup_passes_table.reset_to_defaults()
        self.warmup_num_steps_var.set(HDRM_SCAN_DEFAULTS["num_steps"])
        self.warmup_count_time_var.set(HDRM_SCAN_DEFAULTS["count_time"])
        self.warmup_final_te_300_var.set(False)
        self.warmup_final_sample_temp_var.set(WARMUP_FINAL_STEP_DEFAULTS["sample_temp"])
        self.warmup_final_sample_flow_var.set(WARMUP_FINAL_STEP_DEFAULTS["sample_flow"])
        self._append_log("[warmup] all phases reset to defaults, HDRM Scan Parameters reset to defaults too")

    def _collect_warmup_final_step_params(self):
        return {
            "sample_temp": self.warmup_final_sample_temp_var.get().strip(),
            "sample_flow": self.warmup_final_sample_flow_var.get().strip(),
        }

    def _on_warmup_preview(self):
        phases = self._collect_warmup_phases()
        scan_passes = self.warmup_passes_table.get()
        num_steps = self.warmup_num_steps_var.get().strip()
        count_time = self.warmup_count_time_var.get().strip()
        final_step = self._collect_warmup_final_step_params()
        try:
            validate_warmup_phase_params(phases)
            validate_hdrm_scan_params(scan_passes, num_steps, count_time)
            validate_warmup_final_step_params(final_step)
        except ValueError as exc:
            messagebox.showerror("Warmup", str(exc))
            return
        g = {k: v.get().strip() for k, v in self.global_vars.items()}
        enabled_phases = [ph for ph in phases if ph["enabled"] in ("1", "True", "true")]

        self._append_log("========== Preview: Warmup (no waiting, nothing sent) ==========")
        preview_queue = queue.Queue()
        runner = Runner(preview_queue, threading.Event(), preview=True)
        runner.run_warmup(
            g, enabled_phases,
            scan_passes=scan_passes, num_steps=num_steps, count_time=count_time,
            final_te_300=self.warmup_final_te_300_var.get(),
            final_sample_temp=final_step["sample_temp"],
            final_sample_flow=final_step["sample_flow"],
        )
        while not preview_queue.empty():
            self._append_log(preview_queue.get_nowait())
        self._append_log(
            "========== End preview -- click Run Warmup to actually send this =========="
        )

    def _on_warmup_run(self):
        if self.warmup_run_thread and self.warmup_run_thread.is_alive():
            return
        if self._other_scan_running("warmup_run_thread", "Warmup"):
            return

        phases = self._collect_warmup_phases()
        scan_passes = self.warmup_passes_table.get()
        num_steps = self.warmup_num_steps_var.get().strip()
        count_time = self.warmup_count_time_var.get().strip()
        final_step = self._collect_warmup_final_step_params()
        try:
            validate_warmup_phase_params(phases)
            validate_hdrm_scan_params(scan_passes, num_steps, count_time)
            validate_warmup_final_step_params(final_step)
        except ValueError as exc:
            messagebox.showerror("Warmup", str(exc))
            return
        g = {k: v.get().strip() for k, v in self.global_vars.items()}
        enabled_phases = [ph for ph in phases if ph["enabled"] in ("1", "True", "true")]

        self.warmup_cancel_event.clear()
        self.warmup_run_button.configure(state="disabled")
        self.warmup_stop_button.configure(state="normal")
        self._append_log("========== Starting Warmup ==========")
        self._append_log(
            f"[spec] sending real commands to SPEC {self.controller.spec_host}:"
            f"{self.controller.spec_port}"
        )

        def worker():
            runner = Runner(
                self.log_queue, self.warmup_cancel_event, spec_controller=self.controller
            )
            try:
                runner.run_warmup(
                    g, enabled_phases,
                    scan_passes=scan_passes, num_steps=num_steps, count_time=count_time,
                    final_te_300=self.warmup_final_te_300_var.get(),
                    final_sample_temp=final_step["sample_temp"],
                    final_sample_flow=final_step["sample_flow"],
                )
            except Exception as exc:  # surface any unexpected error to the log
                self.log_queue.put(f"[error] {exc}")
            finally:
                scan_n = getattr(runner, "scan_n", None)
                if scan_n is not None:
                    self.log_queue.put(("__SCANN__", scan_n))
                self.log_queue.put("__WARMUP_DONE__")

        self.warmup_run_thread = threading.Thread(target=worker, daemon=True)
        self.warmup_run_thread.start()

    def _on_warmup_stop(self):
        self.warmup_cancel_event.set()
        self._append_log("[warmup] stop requested -- finishing current step...")

    # ---- Warmup Custom tab ----

    def _build_warmup_custom_tab(self):
        """9th main-notebook tab -- translated from
        HDRMscans_new.mac's `warmup_custom` macro: a single continuous
        loop (unlike Warmup's 3 hard-coded phases) that re-picks low/
        medium/high N2 flow at EVERY temperature step based on two
        thresholds -- see WARMUP_CUSTOM_DEFAULTS' docstring in
        hrdm_core.py for why this is a genuinely different algorithm,
        not just different default numbers, and so gets its own tab
        rather than folding into Warmup."""
        tab = self._make_scrollable_tab("Warmup Custom")
        self._build_standalone_temp_flow_section(tab, "warmupcustom")

        self._make_wrapping_label(
            tab,
            "Single continuous warmup loop from Start to End (by "
            "Step) (translated from HDRMscans_new.mac's "
            "'warmup_custom' macro) -- at each temperature, picks "
            "low/medium/high N2 flow based on Threshold 1/Threshold "
            "2 (<= Threshold 1: low flow; <= Threshold 2: medium "
            "flow; above: high flow), then spins the sample and runs "
            "a full HDRM scan. Uses 'datafile', 'sample', and "
            "'rampre' from the Sample Information tab's Global "
            "parameters box for each scan -- the full HDRM scan's own passes/"
            "steps/count time are set below and are independent of "
            "the Threextal Scan tab.",
        )

        fields_row = ttk.Frame(tab)
        fields_row.pack(fill="x", padx=8, pady=4)
        for key, label, width in (
            ("start_temp", "Start temp, K", 10),
            ("end_temp", "End temp, K", 10),
            ("step_temp", "Step, K", 8),
            ("spin_cycles", "Spin cycles/step", 14),
        ):
            col = ttk.Frame(fields_row)
            col.pack(side="left", padx=(0, 12))
            ttk.Label(col, text=label + ":").pack(anchor="w")
            ttk.Entry(col, textvariable=self.warmup_custom_vars[key], width=width).pack(anchor="w")

        fields_row2 = ttk.Frame(tab)
        fields_row2.pack(fill="x", padx=8, pady=4)
        for key, label, width in (
            ("threshold1", "Threshold 1, K", 13),
            ("flow1", "Flow (<= T1)", 10),
            ("threshold2", "Threshold 2, K", 13),
            ("flow2", "Flow (<= T2)", 10),
            ("flow3", "Flow (> T2)", 10),
        ):
            col = ttk.Frame(fields_row2)
            col.pack(side="left", padx=(0, 12))
            ttk.Label(col, text=label + ":").pack(anchor="w")
            ttk.Entry(col, textvariable=self.warmup_custom_vars[key], width=width).pack(anchor="w")

        self.warmup_custom_passes_table = self._build_hdrm_scan_params_section(
            tab, self.warmup_custom_num_steps_var, self.warmup_custom_count_time_var
        )

        buttons_row = ttk.Frame(tab)
        buttons_row.pack(fill="x", padx=8, pady=(8, 4))
        ttk.Button(
            buttons_row, text="Preview", command=self._on_warmup_custom_preview
        ).pack(side="left", padx=4)
        self.warmup_custom_run_button = ttk.Button(
            buttons_row, text="Run Warmup Custom", command=self._on_warmup_custom_run,
            style="Accent.TButton",
        )
        self.warmup_custom_run_button.pack(side="left", padx=4)
        self.warmup_custom_stop_button = ttk.Button(
            buttons_row, text="Stop", command=self._on_warmup_custom_stop,
            state="disabled", style="Stop.TButton",
        )
        self.warmup_custom_stop_button.pack(side="left", padx=4)
        ttk.Button(
            buttons_row, text="Reset to defaults",
            command=self._on_warmup_custom_reset_defaults,
        ).pack(side="left", padx=4)

        ttk.Label(
            tab,
            text="Preview and Run both log to the shared \"Log\" tab "
            "in the Output section below. This is a long-running "
            "scan -- use Stop to cancel partway through.",
        ).pack(fill="x", padx=8, pady=(4, 8))

    def _collect_warmup_custom_params(self):
        p = {k: v.get().strip() for k, v in self.warmup_custom_vars.items()}
        p["scan_passes"] = self.warmup_custom_passes_table.get()
        p["num_steps"] = self.warmup_custom_num_steps_var.get().strip()
        p["count_time"] = self.warmup_custom_count_time_var.get().strip()
        return p

    def _on_warmup_custom_reset_defaults(self):
        for key, value in WARMUP_CUSTOM_DEFAULTS.items():
            self.warmup_custom_vars[key].set(value)
        self.warmup_custom_passes_table.reset_to_defaults()
        self.warmup_custom_num_steps_var.set(HDRM_SCAN_DEFAULTS["num_steps"])
        self.warmup_custom_count_time_var.set(HDRM_SCAN_DEFAULTS["count_time"])
        self._append_log("[warmup_custom] fields reset to defaults, HDRM Scan Parameters reset to defaults too")

    def _on_warmup_custom_preview(self):
        p = self._collect_warmup_custom_params()
        try:
            validate_warmup_custom_params(p)
            validate_hdrm_scan_params(p["scan_passes"], p["num_steps"], p["count_time"])
        except ValueError as exc:
            messagebox.showerror("Warmup Custom", str(exc))
            return
        g = {k: v.get().strip() for k, v in self.global_vars.items()}

        self._append_log("========== Preview: Warmup Custom (no waiting, nothing sent) ==========")
        preview_queue = queue.Queue()
        runner = Runner(preview_queue, threading.Event(), preview=True)
        runner.run_warmup_custom(
            g, p["start_temp"], p["end_temp"], p["step_temp"], p["spin_cycles"],
            p["threshold1"], p["flow1"], p["threshold2"], p["flow2"], p["flow3"],
            scan_passes=p["scan_passes"], num_steps=p["num_steps"],
            count_time=p["count_time"],
        )
        while not preview_queue.empty():
            self._append_log(preview_queue.get_nowait())
        self._append_log(
            "========== End preview -- click Run Warmup Custom to actually send this =========="
        )

    def _on_warmup_custom_run(self):
        if self.warmup_custom_run_thread and self.warmup_custom_run_thread.is_alive():
            return
        if self._other_scan_running("warmup_custom_run_thread", "Warmup Custom"):
            return

        p = self._collect_warmup_custom_params()
        try:
            validate_warmup_custom_params(p)
            validate_hdrm_scan_params(p["scan_passes"], p["num_steps"], p["count_time"])
        except ValueError as exc:
            messagebox.showerror("Warmup Custom", str(exc))
            return
        g = {k: v.get().strip() for k, v in self.global_vars.items()}

        self.warmup_custom_cancel_event.clear()
        self.warmup_custom_run_button.configure(state="disabled")
        self.warmup_custom_stop_button.configure(state="normal")
        self._append_log("========== Starting Warmup Custom ==========")
        self._append_log(
            f"[spec] sending real commands to SPEC {self.controller.spec_host}:"
            f"{self.controller.spec_port}"
        )

        def worker():
            runner = Runner(
                self.log_queue, self.warmup_custom_cancel_event, spec_controller=self.controller
            )
            try:
                runner.run_warmup_custom(
                    g, p["start_temp"], p["end_temp"], p["step_temp"], p["spin_cycles"],
                    p["threshold1"], p["flow1"], p["threshold2"], p["flow2"], p["flow3"],
                    scan_passes=p["scan_passes"], num_steps=p["num_steps"],
                    count_time=p["count_time"],
                )
            except Exception as exc:  # surface any unexpected error to the log
                self.log_queue.put(f"[error] {exc}")
            finally:
                scan_n = getattr(runner, "scan_n", None)
                if scan_n is not None:
                    self.log_queue.put(("__SCANN__", scan_n))
                self.log_queue.put("__WARMUP_CUSTOM_DONE__")

        self.warmup_custom_run_thread = threading.Thread(target=worker, daemon=True)
        self.warmup_custom_run_thread.start()

    def _on_warmup_custom_stop(self):
        self.warmup_custom_cancel_event.set()
        self._append_log("[warmup_custom] stop requested -- finishing current step...")

    # ---- Cooldown tab ----

    def _build_cooldown_tab(self):
        """10th main-notebook tab -- translated from
        HDRMscans_new.mac's `cooldown` macro. Not explicitly
        requested, but added as the descending mirror of Warmup
        Custom's threshold-driven algorithm -- see COOLDOWN_DEFAULTS'
        docstring in hrdm_core.py. Flagging this here and in the
        README in case it isn't wanted."""
        tab = self._make_scrollable_tab("Cooldown")
        self._build_standalone_temp_flow_section(tab, "cooldown")

        self._make_wrapping_label(
            tab,
            "Single continuous cooldown loop, DEscending from Start "
            "to End (by Step) (translated from HDRMscans_new.mac's "
            "'cooldown' macro -- not explicitly requested, added as "
            "the descending mirror of Warmup Custom; see the "
            "README) -- at each temperature, picks high/medium/low "
            "N2 flow based on Threshold High/Threshold Medium (>= "
            "Threshold High: high flow; >= Threshold Medium: medium "
            "flow; below: low flow), then spins the sample and runs "
            "a full HDRM scan. Unlike every other temperature-series "
            "tab, the macro's own 'cooldown' has no 10s warning "
            "delay before it starts, preserved faithfully here. Uses "
            "'datafile', 'sample', and 'rampre' from the Threextal "
            "Scan tab's Global parameters box for each scan -- the "
            "full HDRM scan's own passes/steps/count time are set "
            "below and are independent of the Threextal Scan tab.",
        )

        fields_row = ttk.Frame(tab)
        fields_row.pack(fill="x", padx=8, pady=4)
        for key, label, width in (
            ("start_temp", "Start temp, K", 10),
            ("end_temp", "End temp, K", 10),
            ("step_temp", "Step, K", 8),
            ("spin_cycles", "Spin cycles/step", 14),
        ):
            col = ttk.Frame(fields_row)
            col.pack(side="left", padx=(0, 12))
            ttk.Label(col, text=label + ":").pack(anchor="w")
            ttk.Entry(col, textvariable=self.cooldown_vars[key], width=width).pack(anchor="w")

        fields_row2 = ttk.Frame(tab)
        fields_row2.pack(fill="x", padx=8, pady=4)
        for key, label, width in (
            ("threshold_high", "Threshold High, K", 15),
            ("flow_high", "Flow (>= High)", 13),
            ("threshold_medium", "Threshold Medium, K", 17),
            ("flow_medium", "Flow (>= Med)", 13),
            ("flow_low", "Flow (< Med)", 12),
        ):
            col = ttk.Frame(fields_row2)
            col.pack(side="left", padx=(0, 12))
            ttk.Label(col, text=label + ":").pack(anchor="w")
            ttk.Entry(col, textvariable=self.cooldown_vars[key], width=width).pack(anchor="w")

        self.cooldown_passes_table = self._build_hdrm_scan_params_section(
            tab, self.cooldown_num_steps_var, self.cooldown_count_time_var
        )

        buttons_row = ttk.Frame(tab)
        buttons_row.pack(fill="x", padx=8, pady=(8, 4))
        ttk.Button(
            buttons_row, text="Preview", command=self._on_cooldown_preview
        ).pack(side="left", padx=4)
        self.cooldown_run_button = ttk.Button(
            buttons_row, text="Run Cooldown", command=self._on_cooldown_run,
            style="Accent.TButton",
        )
        self.cooldown_run_button.pack(side="left", padx=4)
        self.cooldown_stop_button = ttk.Button(
            buttons_row, text="Stop", command=self._on_cooldown_stop,
            state="disabled", style="Stop.TButton",
        )
        self.cooldown_stop_button.pack(side="left", padx=4)
        ttk.Button(
            buttons_row, text="Reset to defaults",
            command=self._on_cooldown_reset_defaults,
        ).pack(side="left", padx=4)

        ttk.Label(
            tab,
            text="Preview and Run both log to the shared \"Log\" tab "
            "in the Output section below. This is a long-running "
            "scan -- use Stop to cancel partway through.",
        ).pack(fill="x", padx=8, pady=(4, 8))

    def _collect_cooldown_params(self):
        p = {k: v.get().strip() for k, v in self.cooldown_vars.items()}
        p["scan_passes"] = self.cooldown_passes_table.get()
        p["num_steps"] = self.cooldown_num_steps_var.get().strip()
        p["count_time"] = self.cooldown_count_time_var.get().strip()
        return p

    def _on_cooldown_reset_defaults(self):
        for key, value in COOLDOWN_DEFAULTS.items():
            self.cooldown_vars[key].set(value)
        self.cooldown_passes_table.reset_to_defaults()
        self.cooldown_num_steps_var.set(HDRM_SCAN_DEFAULTS["num_steps"])
        self.cooldown_count_time_var.set(HDRM_SCAN_DEFAULTS["count_time"])
        self._append_log("[cooldown] fields reset to defaults, HDRM Scan Parameters reset to defaults too")

    def _on_cooldown_preview(self):
        p = self._collect_cooldown_params()
        try:
            validate_cooldown_params(p)
            validate_hdrm_scan_params(p["scan_passes"], p["num_steps"], p["count_time"])
        except ValueError as exc:
            messagebox.showerror("Cooldown", str(exc))
            return
        g = {k: v.get().strip() for k, v in self.global_vars.items()}

        self._append_log("========== Preview: Cooldown (no waiting, nothing sent) ==========")
        preview_queue = queue.Queue()
        runner = Runner(preview_queue, threading.Event(), preview=True)
        runner.run_cooldown(
            g, p["start_temp"], p["end_temp"], p["step_temp"], p["spin_cycles"],
            p["threshold_high"], p["flow_high"], p["threshold_medium"],
            p["flow_medium"], p["flow_low"],
            scan_passes=p["scan_passes"], num_steps=p["num_steps"],
            count_time=p["count_time"],
        )
        while not preview_queue.empty():
            self._append_log(preview_queue.get_nowait())
        self._append_log(
            "========== End preview -- click Run Cooldown to actually send this =========="
        )

    def _on_cooldown_run(self):
        if self.cooldown_run_thread and self.cooldown_run_thread.is_alive():
            return
        if self._other_scan_running("cooldown_run_thread", "Cooldown"):
            return

        p = self._collect_cooldown_params()
        try:
            validate_cooldown_params(p)
            validate_hdrm_scan_params(p["scan_passes"], p["num_steps"], p["count_time"])
        except ValueError as exc:
            messagebox.showerror("Cooldown", str(exc))
            return
        g = {k: v.get().strip() for k, v in self.global_vars.items()}

        self.cooldown_cancel_event.clear()
        self.cooldown_run_button.configure(state="disabled")
        self.cooldown_stop_button.configure(state="normal")
        self._append_log("========== Starting Cooldown ==========")
        self._append_log(
            f"[spec] sending real commands to SPEC {self.controller.spec_host}:"
            f"{self.controller.spec_port}"
        )

        def worker():
            runner = Runner(
                self.log_queue, self.cooldown_cancel_event, spec_controller=self.controller
            )
            try:
                runner.run_cooldown(
                    g, p["start_temp"], p["end_temp"], p["step_temp"], p["spin_cycles"],
                    p["threshold_high"], p["flow_high"], p["threshold_medium"],
                    p["flow_medium"], p["flow_low"],
                    scan_passes=p["scan_passes"], num_steps=p["num_steps"],
                    count_time=p["count_time"],
                )
            except Exception as exc:  # surface any unexpected error to the log
                self.log_queue.put(f"[error] {exc}")
            finally:
                scan_n = getattr(runner, "scan_n", None)
                if scan_n is not None:
                    self.log_queue.put(("__SCANN__", scan_n))
                self.log_queue.put("__COOLDOWN_DONE__")

        self.cooldown_run_thread = threading.Thread(target=worker, daemon=True)
        self.cooldown_run_thread.start()

    def _on_cooldown_stop(self):
        self.cooldown_cancel_event.set()
        self._append_log("[cooldown] stop requested -- finishing current step...")

    # ---- High Temp Scan tab ----

    def _build_hightemp_tab(self):
        """11th main-notebook tab -- translated from
        HDRMscans_new.mac's `hightemp_scan` macro. Defaults (361K to
        475K, step 30K, 360s wait) match the macro's ACTUAL loop
        bounds and its own `threextalscan <T> 360` call -- NOT its
        printed messages, which are copy-pasted from 'warmup' and
        describe neither this range nor step; see
        HIGHTEMP_SCAN_DEFAULTS' docstring in hrdm_core.py. The
        macro's own Phase 1 prep/spin calls are commented out in the
        source, so this tab has no gas-prep/spin fields for Phase 1 --
        only the loop bounds/wait, plus Phase 2's final temperature/
        flow."""
        tab = self._make_scrollable_tab("High Temp Scan")
        self._build_standalone_temp_flow_section(tab, "hightemp")

        self._make_wrapping_label(
            tab,
            "Steps the sample temperature from Start to End (by "
            "Step), waiting 'Scan wait' seconds before each HDRM "
            "scan (translated from HDRMscans_new.mac's "
            "'hightemp_scan' macro -- defaults 361K to 475K, step "
            "30K, 360s wait, from the macro's ACTUAL loop; its own "
            "printed messages describe a different range copy-pasted "
            "from 'warmup' -- see the README). The macro's own gas-"
            "prep/spin calls before and during this loop are "
            "commented out in the source, so none are sent here "
            "either. Once the loop finishes, returns to room "
            "temperature at 'Final flow' and 'Final temp'. Uses "
            "'datafile', 'sample', and 'rampre' from the Threextal "
            "Scan tab's Global parameters box for each scan -- the "
            "full HDRM scan's own passes/steps/count time are set "
            "below and are independent of the Threextal Scan tab.",
        )

        fields_row = ttk.Frame(tab)
        fields_row.pack(fill="x", padx=8, pady=4)
        for key, label, width in (
            ("start_temp", "Start temp, K", 10),
            ("end_temp", "End temp, K", 10),
            ("step_temp", "Step, K", 8),
            ("scan_wait_seconds", "Scan wait, s", 12),
        ):
            col = ttk.Frame(fields_row)
            col.pack(side="left", padx=(0, 12))
            ttk.Label(col, text=label + ":").pack(anchor="w")
            ttk.Entry(col, textvariable=self.hightemp_vars[key], width=width).pack(anchor="w")

        fields_row2 = ttk.Frame(tab)
        fields_row2.pack(fill="x", padx=8, pady=4)
        for key, label, width in (
            ("final_temp", "Final temp, K", 12),
            ("final_flow", "Final flow", 10),
        ):
            col = ttk.Frame(fields_row2)
            col.pack(side="left", padx=(0, 12))
            ttk.Label(col, text=label + ":").pack(anchor="w")
            ttk.Entry(col, textvariable=self.hightemp_vars[key], width=width).pack(anchor="w")

        ttk.Checkbutton(
            fields_row2,
            text="Enable Phase 2 (return to room temperature)",
            variable=self.hightemp_final_enabled_var,
        ).pack(side="left", padx=(12, 0), anchor="s")

        self.hightemp_passes_table = self._build_hdrm_scan_params_section(
            tab, self.hightemp_num_steps_var, self.hightemp_count_time_var
        )

        buttons_row = ttk.Frame(tab)
        buttons_row.pack(fill="x", padx=8, pady=(8, 4))
        ttk.Button(
            buttons_row, text="Preview", command=self._on_hightemp_preview
        ).pack(side="left", padx=4)
        self.hightemp_run_button = ttk.Button(
            buttons_row, text="Run High Temp Scan", command=self._on_hightemp_run,
            style="Accent.TButton",
        )
        self.hightemp_run_button.pack(side="left", padx=4)
        self.hightemp_stop_button = ttk.Button(
            buttons_row, text="Stop", command=self._on_hightemp_stop,
            state="disabled", style="Stop.TButton",
        )
        self.hightemp_stop_button.pack(side="left", padx=4)
        ttk.Button(
            buttons_row, text="Reset to defaults",
            command=self._on_hightemp_reset_defaults,
        ).pack(side="left", padx=4)

        ttk.Label(
            tab,
            text="Preview and Run both log to the shared \"Log\" tab "
            "in the Output section below. This is a long-running "
            "scan -- use Stop to cancel partway through.",
        ).pack(fill="x", padx=8, pady=(4, 8))

    def _collect_hightemp_params(self):
        p = {k: v.get().strip() for k, v in self.hightemp_vars.items()}
        p["final_enabled"] = "1" if self.hightemp_final_enabled_var.get() else "0"
        p["scan_passes"] = self.hightemp_passes_table.get()
        p["num_steps"] = self.hightemp_num_steps_var.get().strip()
        p["count_time"] = self.hightemp_count_time_var.get().strip()
        return p

    def _on_hightemp_reset_defaults(self):
        for key, value in HIGHTEMP_SCAN_DEFAULTS.items():
            if key in self._hightemp_enabled_keys:
                continue
            self.hightemp_vars[key].set(value)
        self.hightemp_final_enabled_var.set(
            HIGHTEMP_SCAN_DEFAULTS.get("final_enabled") == "1"
        )
        self.hightemp_passes_table.reset_to_defaults()
        self.hightemp_num_steps_var.set(HDRM_SCAN_DEFAULTS["num_steps"])
        self.hightemp_count_time_var.set(HDRM_SCAN_DEFAULTS["count_time"])
        self._append_log("[hightemp_scan] fields reset to defaults, HDRM Scan Parameters reset to defaults too")

    def _on_hightemp_preview(self):
        p = self._collect_hightemp_params()
        try:
            validate_hightemp_params(p)
            validate_hdrm_scan_params(p["scan_passes"], p["num_steps"], p["count_time"])
        except ValueError as exc:
            messagebox.showerror("High Temp Scan", str(exc))
            return
        g = {k: v.get().strip() for k, v in self.global_vars.items()}

        self._append_log("========== Preview: High Temp Scan (no waiting, nothing sent) ==========")
        preview_queue = queue.Queue()
        runner = Runner(preview_queue, threading.Event(), preview=True)
        runner.run_hightemp_scan(
            g, p["start_temp"], p["end_temp"], p["step_temp"],
            p["scan_wait_seconds"], p["final_temp"], p["final_flow"],
            scan_passes=p["scan_passes"], num_steps=p["num_steps"],
            count_time=p["count_time"],
            final_enabled=p["final_enabled"] == "1",
        )
        while not preview_queue.empty():
            self._append_log(preview_queue.get_nowait())
        self._append_log(
            "========== End preview -- click Run High Temp Scan to actually send this =========="
        )

    def _on_hightemp_run(self):
        if self.hightemp_run_thread and self.hightemp_run_thread.is_alive():
            return
        if self._other_scan_running("hightemp_run_thread", "High Temp Scan"):
            return

        p = self._collect_hightemp_params()
        try:
            validate_hightemp_params(p)
            validate_hdrm_scan_params(p["scan_passes"], p["num_steps"], p["count_time"])
        except ValueError as exc:
            messagebox.showerror("High Temp Scan", str(exc))
            return
        g = {k: v.get().strip() for k, v in self.global_vars.items()}

        self.hightemp_cancel_event.clear()
        self.hightemp_run_button.configure(state="disabled")
        self.hightemp_stop_button.configure(state="normal")
        self._append_log("========== Starting High Temp Scan ==========")
        self._append_log(
            f"[spec] sending real commands to SPEC {self.controller.spec_host}:"
            f"{self.controller.spec_port}"
        )

        def worker():
            runner = Runner(
                self.log_queue, self.hightemp_cancel_event, spec_controller=self.controller
            )
            try:
                runner.run_hightemp_scan(
                    g, p["start_temp"], p["end_temp"], p["step_temp"],
                    p["scan_wait_seconds"], p["final_temp"], p["final_flow"],
                    scan_passes=p["scan_passes"], num_steps=p["num_steps"],
                    count_time=p["count_time"],
                    final_enabled=p["final_enabled"] == "1",
                )
            except Exception as exc:  # surface any unexpected error to the log
                self.log_queue.put(f"[error] {exc}")
            finally:
                scan_n = getattr(runner, "scan_n", None)
                if scan_n is not None:
                    self.log_queue.put(("__SCANN__", scan_n))
                self.log_queue.put("__HIGHTEMP_DONE__")

        self.hightemp_run_thread = threading.Thread(target=worker, daemon=True)
        self.hightemp_run_thread.start()

    def _on_hightemp_stop(self):
        self.hightemp_cancel_event.set()
        self._append_log("[hightemp_scan] stop requested -- finishing current step...")

    # ---- Gas Prep Macros tab (12th main tab) ----

    def _build_gas_prep_tab(self):
        """12th main-notebook tab, "Gas Prep" (renamed from "Gas Prep
        Macros" per explicit user request). Exposes each of
        Lakeshore336cryocool.mac's 7 gas/temperature-prep macros
        (prepN2_low, prepN2_medium, prepN2_high, prepswitch,
        runninghelium, roomT, highT -- see GAS_PREP_MACRO_NAMES in
        hrdm_core.py) as its own independently-runnable button,
        rather than only reachable indirectly through Warmup/N2 -> He
        Switch/Low Temp Scan as before -- for an operator who just
        wants to send one gas-prep macro on its own. Also has the
        same live Stage A/Stage C/sample temperature EPICS readback +
        auto-watch pattern as the N2 -> He Switch section (its own
        independent copy, see self.gas_prep_* vars), a standalone
        flow_set/flow_get control that isn't tied to any one macro,
        and its own Spin Control (spin_xtal_phi) section -- a third
        independent copy of the same Start/Stop UI as the main Spin
        Control tab and the Low Temp Scan tab's standalone section,
        per explicit user request ("Spin control tab type option in
        gas flow tab").

        Panel order on this tab is explicit, per user request:
        Live Temperature (EPICS) -> Set Temperature (te) -> Flow
        Control (flow_set) -> the 7 macro buttons -> Spin Control.
        The previous standalone "Room Temp Condition"
        (room_temperature_sample) panel has been deleted entirely per
        explicit user request -- it was a project addition with no
        Lakeshore336cryocool.mac precedent, and roomT() above already
        covers the real macro. prepswitch's own standalone flow_set
        field has also been removed per explicit user request
        ("Prepswitch: takeout flow_set") -- prepswitch() itself never
        sent flow_set in the real macro (see hrdm_core.py's
        Runner.run_gas_prep_macro/prepswitch docstring), so this was
        purely a UI field tied to nothing; the standalone Flow Control
        panel above already covers sending an arbitrary flow_set value
        on its own.

        Every panel on this tab is wrapped with self._make_section
        (a colored accent stripe above a ttk.LabelFrame) rather than a
        plain ttk.LabelFrame, per explicit user request for a more
        "distinct and modern" look -- each panel gets its own color
        from _SECTION_ACCENT_COLORS so neighboring panels are never
        the same color.

        Every one of the 7 macro buttons has its own adjacent
        "Preview" button -- see _on_gas_prep_preview_macro -- that
        logs the exact commands that macro would send using a fresh
        `Runner(preview=True)`, the same pattern every other tab's
        Preview button already uses, without touching the shared SPEC
        connection or this tab's concurrency guard."""
        tab = self._make_scrollable_tab("Gas Prep")

        self._make_wrapping_label(
            tab,
            "Runs each of Lakeshore336cryocool.mac's 7 gas/"
            "temperature-prep macros on its own, independent of "
            "Warmup/N2 -> He Switch/Low Temp Scan. Every Stage A/"
            "Stage C setpoint below defaults to that macro's own "
            "confirmed value (see each button's tooltip-style label) "
            "and is editable. The standalone Flow Control section "
            "below is a project addition with no Lakeshore336cryocool"
            ".mac precedent -- flagged here since it isn't a "
            "macro-confirmed value. Each macro also has its own "
            "\"Preview\" button to see exactly what it would send "
            "before running it for real.",
        )

        section_color = 0

        temps_row = self._make_section(
            tab, "Live Temperature (EPICS)", section_color, padx=8, pady=(0, 4)
        )
        section_color += 1
        for label, var in (
            ("Stage A:", self.gas_prep_stage_a_temp_var),
            ("Stage C:", self.gas_prep_stage_c_temp_var),
            ("Sample:", self.gas_prep_sample_temp_var),
        ):
            col = ttk.Frame(temps_row)
            col.pack(side="left", padx=(6, 16), pady=4)
            ttk.Label(col, text=label).pack(side="left")
            ttk.Label(col, textvariable=var, width=10, anchor="w").pack(side="left")
        self.gas_prep_read_temps_button = ttk.Button(
            temps_row, text="Read Temperatures", command=self._on_read_gas_prep_temps
        )
        self.gas_prep_read_temps_button.pack(side="left", padx=(0, 12), pady=4)
        ttk.Checkbutton(
            temps_row,
            text=f"Auto-watch Temperatures (every {_GAS_PREP_TEMP_WATCH_INTERVAL_MS // 1000}s)",
            variable=self.gas_prep_temp_watch_var,
            command=self._on_toggle_gas_prep_temp_watch,
        ).pack(side="left", pady=4)

        set_temp_row = self._make_section(
            tab, "Set Temperature (te) -- any value 10-490K, project addition",
            section_color, padx=8, pady=4,
        )
        section_color += 1
        ttk.Label(set_temp_row, text="Target temp (te), K [10-490]:").pack(
            side="left", padx=(6, 2), pady=6
        )
        ttk.Entry(
            set_temp_row,
            textvariable=self.gas_prep_vars["set_temperature_te"],
            width=10,
        ).pack(side="left", padx=(0, 16), pady=6)
        ttk.Button(
            set_temp_row,
            text="Preview",
            command=self._on_gas_prep_preview_set_temperature,
        ).pack(side="left", padx=(0, 4), pady=6)
        self.gas_prep_set_temp_button = ttk.Button(
            set_temp_row,
            text="Set Temp",
            command=self._on_gas_prep_run_set_temperature,
        )
        self.gas_prep_set_temp_button.pack(side="left", padx=(0, 8), pady=6)
        ttk.Label(set_temp_row, text="Target temp set anywhere:").pack(
            side="left", padx=(12, 2), pady=6
        )
        ttk.Label(
            set_temp_row, textvariable=self.shared_target_temp_var,
            width=28, anchor="w",
        ).pack(side="left", pady=6)

        flow_row = self._make_section(
            tab, "Flow Control (flow_set) -- no macro precedent, project addition",
            section_color, padx=8, pady=4,
        )
        section_color += 1
        ttk.Label(flow_row, text="flow_set value:").pack(side="left", padx=(6, 2), pady=6)
        ttk.Entry(
            flow_row, textvariable=self.gas_prep_vars["flow_set_value"], width=10
        ).pack(side="left", padx=(0, 8), pady=6)
        self.gas_prep_flow_set_button = ttk.Button(
            flow_row, text="Send flow_set", command=self._on_gas_prep_flow_set
        )
        self.gas_prep_flow_set_button.pack(side="left", padx=(0, 16), pady=6)
        self.gas_prep_flow_get_button = ttk.Button(
            flow_row, text="Read flow_get", command=self._on_gas_prep_flow_get
        )
        self.gas_prep_flow_get_button.pack(side="left", padx=(0, 8), pady=6)
        ttk.Label(flow_row, text="Current flow:").pack(side="left", padx=(8, 2), pady=6)
        ttk.Label(
            flow_row, textvariable=self.gas_prep_flow_result_var, width=14, anchor="w"
        ).pack(side="left", pady=6)
        ttk.Label(flow_row, text="Target flow set anywhere:").pack(
            side="left", padx=(12, 2), pady=6
        )
        ttk.Label(
            flow_row, textvariable=self.shared_target_flow_var,
            width=22, anchor="w",
        ).pack(side="left", pady=6)

        # 7 macro columns, split across two rows (4 + 3) so nothing
        # runs off the side of the tab -- same LabelFrame-per-step
        # layout as _build_n2_to_he_switch_section's stage_row, just
        # one macro per column instead of one step-group. Each row is
        # itself wrapped in one _make_section "card" (rather than one
        # card per individual macro column) so the 7 buttons read as
        # one coherent "macros" panel, consistent with every other
        # panel on this tab now being a distinct, colored card.
        macro_specs = [
            ("prepN2_low", "prepN2_low", "prepn2_low_stage_a", "prepn2_low_stage_c"),
            ("prepN2_medium", "prepN2_medium", "prepn2_medium_stage_a", "prepn2_medium_stage_c"),
            ("prepN2_high", "prepN2_high", "prepn2_high_stage_a", "prepn2_high_stage_c"),
            ("prepswitch", "prepswitch", "prepswitch_stage_a", "prepswitch_stage_c"),
            ("runninghelium", "runninghelium", "runninghelium_stage_a", "runninghelium_stage_c"),
            ("roomT", "roomT", "roomt_stage_a", "roomt_stage_c"),
            ("highT", "highT", "hight_stage_a", "hight_stage_c"),
        ]
        rows = [macro_specs[:4], macro_specs[4:]]
        for row_specs in rows:
            macros_box = self._make_section(
                tab, "Gas Prep Macros", section_color, padx=8, pady=4
            )
            section_color += 1
            row_frame = ttk.Frame(macros_box)
            row_frame.pack(fill="x", padx=2, pady=2)
            for name, title, stage_a_key, stage_c_key in row_specs:
                col = ttk.LabelFrame(row_frame, text=title)
                col.pack(side="left", padx=(0, 14), fill="y")
                for key, label, width in (
                    (stage_a_key, "Stage A, K", 12),
                    (stage_c_key, "Stage C, K", 12),
                ):
                    field_row = ttk.Frame(col)
                    field_row.pack(anchor="w", padx=6, pady=2)
                    ttk.Label(field_row, text=label + ":").pack(side="left")
                    ttk.Entry(
                        field_row, textvariable=self.gas_prep_vars[key], width=width
                    ).pack(side="left", padx=(4, 0))
                button_row = ttk.Frame(col)
                button_row.pack(padx=6, pady=(4, 6), fill="x")
                ttk.Button(
                    button_row, text="Preview",
                    command=lambda n=name: self._on_gas_prep_preview_macro(n),
                ).pack(side="left", padx=(0, 4), fill="x", expand=True)
                button = ttk.Button(
                    button_row, text=f"Run {name}",
                    command=lambda n=name: self._on_gas_prep_run_macro(n),
                )
                button.pack(side="left", fill="x", expand=True)
                self.gas_prep_macro_buttons[name] = button

        buttons_row = ttk.Frame(tab)
        buttons_row.pack(fill="x", padx=8, pady=(4, 8))
        self.gas_prep_stop_button = ttk.Button(
            buttons_row, text="Stop", command=self._on_gas_prep_stop,
            state="disabled", style="Stop.TButton",
        )
        self.gas_prep_stop_button.pack(side="left", padx=4)
        ttk.Button(
            buttons_row, text="Reset to defaults",
            command=self._on_gas_prep_reset_defaults,
        ).pack(side="left", padx=4)

        self._make_wrapping_label(
            tab,
            "Each \"Run\" button above sends only that one macro's "
            "setpoints -- there is no wait or sequencing here, unlike "
            "Warmup/N2 -> He Switch. Each macro also has its own "
            "\"Preview\" button that logs exactly what it would send "
            "without touching the SPEC connection -- safe to click "
            "anytime, even while another button here (or on any other "
            "tab) has a real run in flight. Only one \"Run\" button on "
            "this tab (or any other scan-type tab/section) can run at "
            "a time.",
        )

        self._build_gas_prep_spin_section(tab, section_color)

    # ---- Gas Prep tab's own standalone Spin (spin_xtal_phi) control
    # -- a third, independent copy of the Spin Control tab's/Low Temp
    # Scan tab's own Start/Stop UI (see _build_low_temp_standalone_
    # spin_section's docstring for the shared rationale: its own
    # state, own thread slot, own cancel event, never blocks or is
    # blocked by anything else in the app), added per explicit user
    # request ("Spin control tab type option in gas flow tab, I want
    # to rotate the crystal").
    def _build_gas_prep_spin_section(self, tab, color_index=0):
        box = self._make_section(
            tab,
            "Spin Control (spin_xtal_phi) -- independent of "
            "everything else on this tab or any other tab",
            color_index, padx=8, pady=6,
        )

        self._make_wrapping_label(
            box,
            "Continuously spins the sample (phi 0 <-> 360) without "
            "affecting -- and without being blocked by -- any scan, "
            "macro, or other quick action anywhere else in the app. "
            "Same controls as the main Spin Control tab; leave "
            "'Number of cycles' blank to spin until Stop is clicked.",
        )

        fields_row = ttk.Frame(box)
        fields_row.pack(fill="x", padx=8, pady=4)
        col = ttk.Frame(fields_row)
        col.pack(side="left", padx=(0, 18))
        ttk.Label(col, text="Number of cycles (blank = continuous):").pack(anchor="w")
        ttk.Entry(
            col, textvariable=self.gas_prep_spin_vars["num_cycles"], width=12
        ).pack(anchor="w")

        ttk.Checkbutton(
            fields_row, text="Ice mode (spin_ice)",
            variable=self.gas_prep_spin_ice_mode_var,
        ).pack(side="left", padx=(0, 18), anchor="s", pady=(14, 0))

        buttons_row = ttk.Frame(box)
        buttons_row.pack(fill="x", padx=8, pady=(8, 4))
        self.gas_prep_spin_start_button = ttk.Button(
            buttons_row, text="Start Spin", command=self._on_gas_prep_spin_start,
            style="Accent.TButton",
        )
        self.gas_prep_spin_start_button.pack(side="left", padx=4)
        self.gas_prep_spin_stop_button = ttk.Button(
            buttons_row, text="Stop", command=self._on_gas_prep_spin_stop,
            state="disabled", style="Stop.TButton",
        )
        self.gas_prep_spin_stop_button.pack(side="left", padx=4)
        ttk.Button(
            buttons_row, text="Reset to defaults",
            command=self._on_gas_prep_spin_reset_defaults,
        ).pack(side="left", padx=4)

    def _collect_gas_prep_spin_params(self):
        p = {k: v.get().strip() for k, v in self.gas_prep_spin_vars.items()}
        p["ice_mode"] = "1" if self.gas_prep_spin_ice_mode_var.get() else "0"
        return p

    def _on_gas_prep_spin_reset_defaults(self):
        for key, value in SPIN_DEFAULTS.items():
            if key == "ice_mode":
                self.gas_prep_spin_ice_mode_var.set(value == "1")
            else:
                self.gas_prep_spin_vars[key].set(value)
        self._append_log(
            "[gas prep spin] fields reset to defaults (continuous, ice mode off)"
        )

    def _on_gas_prep_spin_start(self):
        """Start spinning for real -- deliberately does NOT call
        self._other_scan_running(...): this quick action must never
        block, or be blocked by, any other scan/macro/standalone
        action (see _build_gas_prep_spin_section's docstring)."""
        if self.gas_prep_spin_run_thread and self.gas_prep_spin_run_thread.is_alive():
            return

        p = self._collect_gas_prep_spin_params()
        try:
            validate_spin_params(p)
        except ValueError as exc:
            messagebox.showerror("Gas Prep: Spin", str(exc))
            return

        self.gas_prep_spin_cancel_event.clear()
        self.gas_prep_spin_start_button.configure(state="disabled")
        self.gas_prep_spin_stop_button.configure(state="normal")
        self._append_log("========== Gas Prep: Starting Spin ==========")
        self._append_log(
            f"[spec] sending real commands to SPEC {self.controller.spec_host}:"
            f"{self.controller.spec_port}"
        )

        def worker():
            runner = Runner(
                self.log_queue, self.gas_prep_spin_cancel_event,
                spec_controller=self.controller,
            )
            try:
                num_cycles = float(p["num_cycles"]) if p["num_cycles"] else None
                runner.run_spin_xtal_phi(num_cycles=num_cycles, ice_mode=p["ice_mode"] == "1")
            except Exception as exc:  # surface any unexpected error to the log
                self.log_queue.put(f"[error] {exc}")
            finally:
                self.log_queue.put("__GAS_PREP_SPIN_DONE__")

        self.gas_prep_spin_run_thread = threading.Thread(target=worker, daemon=True)
        self.gas_prep_spin_run_thread.start()

    def _on_gas_prep_spin_stop(self):
        """Same immediate-abort fix as _on_spin_stop/_on_low_temp_
        spin_stop -- see _on_spin_stop's docstring for why setting
        cancel_event alone isn't enough to stop an in-flight move.
        Uses _abort_until_stopped (a few automatic retries while
        gas_prep_spin_run_thread is still alive) rather than a single
        attempt -- see its docstring."""
        self.gas_prep_spin_cancel_event.set()
        self._append_log("[gas prep spin] stop requested -- aborting current move...")
        self._last_gas_prep_spin_abort_thread = self._abort_until_stopped(
            lambda: self.gas_prep_spin_run_thread is not None
            and self.gas_prep_spin_run_thread.is_alive()
        )

    def _gas_prep_all_buttons(self):
        """Every button on this tab that shares the single
        gas_prep_run_thread/_other_scan_running concurrency guard --
        the 7 macro buttons, always enabled/disabled together since
        they share one cancel event and one thread slot and so can
        never run concurrently with each other, only sequentially.
        Set Temp/Flow Set/Flow Get are deliberately NOT included here
        any more: they were retrofitted onto their own independent
        thread slots (self.gas_prep_independent_threads) via
        _start_independent_job, exactly like the per-tab standalone
        Set Temp/Flow Control sections, so each is enabled/disabled
        only around its own click -- never tied to this tab's macro
        buttons or to any other scan/macro/action anywhere else in
        the app. (Read Temperatures/Auto-watch are a separate,
        independent EPICS-only path with their own button state, same
        as the N2 -> He Switch section.)"""
        return list(self.gas_prep_macro_buttons.values())

    def _collect_gas_prep_params(self):
        return {k: v.get().strip() for k, v in self.gas_prep_vars.items()}

    def _on_gas_prep_reset_defaults(self):
        for key, value in GAS_PREP_MACROS_DEFAULTS.items():
            self.gas_prep_vars[key].set(value)
        self._gas_prep_prepswitch_ready_logged = False
        self._append_log("[gas_prep] fields reset to defaults")

    def _start_gas_prep_job(self, worker_fn, start_label):
        """Shared launcher for every button on this tab (7 macro
        buttons + flow_set + flow_get) -- they all send real commands
        over the one shared SPEC connection, so they share the same
        concurrency guard, cancel event, and thread slot. `worker_fn`
        is called with no arguments on the background thread and
        should use the closed-over Runner it's given (see callers
        below); it must not touch any Tk widget directly."""
        if self.gas_prep_run_thread and self.gas_prep_run_thread.is_alive():
            return
        if self._other_scan_running("gas_prep_run_thread", "Gas Prep Macros"):
            return

        self.gas_prep_cancel_event.clear()
        for btn in self._gas_prep_all_buttons():
            btn.configure(state="disabled")
        self.gas_prep_stop_button.configure(state="normal")
        self._append_log(f"========== {start_label} ==========")
        self._append_log(
            f"[spec] sending real commands to SPEC {self.controller.spec_host}:"
            f"{self.controller.spec_port}"
        )

        def worker():
            runner = Runner(
                self.log_queue, self.gas_prep_cancel_event, spec_controller=self.controller
            )
            try:
                worker_fn(runner)
            except Exception as exc:  # surface any unexpected error to the log
                self.log_queue.put(f"[error] {exc}")
            finally:
                self.log_queue.put("__GAS_PREP_DONE__")

        self.gas_prep_run_thread = threading.Thread(target=worker, daemon=True)
        self.gas_prep_run_thread.start()

    def _on_gas_prep_preview_macro(self, name):
        """Preview for a single Gas Prep Macros tab button -- unlike
        every button on this tab (which always sends real commands,
        see _build_gas_prep_tab's docstring), Preview never touches
        the shared SPEC connection or the tab's concurrency guard: it
        builds a fresh `Runner(preview=True)` (no spec_controller) the
        same way every other tab's Preview button does (see
        _on_hightemp_preview et al.), runs it synchronously, and logs
        the result. Safe to click at any time, including while another
        Gas Prep Macros button (or any other scan-type tab) has a real
        run in flight."""
        p = self._collect_gas_prep_params()
        try:
            validate_gas_prep_macros_params(p)
        except ValueError as exc:
            messagebox.showerror("Gas Prep Macros", str(exc))
            return
        label = _GAS_PREP_MACRO_BUTTON_LABELS.get(name, name)
        self._append_log(
            f"========== Preview: Gas Prep Macro: {name} (nothing sent) =========="
        )
        preview_queue = queue.Queue()
        runner = Runner(preview_queue, threading.Event(), preview=True)
        runner.run_gas_prep_macro(name, p)
        while not preview_queue.empty():
            self._append_log(preview_queue.get_nowait())
        self._append_log(
            f"========== End preview -- click Run {label} to actually send this =========="
        )

    def _on_gas_prep_run_macro(self, name):
        p = self._collect_gas_prep_params()
        try:
            validate_gas_prep_macros_params(p)
        except ValueError as exc:
            messagebox.showerror("Gas Prep Macros", str(exc))
            return
        label = _GAS_PREP_MACRO_BUTTON_LABELS.get(name, name)
        self._start_gas_prep_job(
            lambda runner: runner.run_gas_prep_macro(name, p),
            f"Starting Gas Prep Macro: {label}",
        )

    def _on_gas_prep_flow_set(self):
        """Independent of the 7 macro buttons above (and of every
        other scan/macro/standalone action anywhere else in the app):
        uses _start_independent_job rather than _start_gas_prep_job,
        so it never calls _other_scan_running and never waits on, or
        blocks, gas_prep_run_thread. See the __init__ comment on
        self.gas_prep_independent_threads for why."""
        p = self._collect_gas_prep_params()
        try:
            validate_gas_prep_macros_params(p)
        except ValueError as exc:
            messagebox.showerror("Gas Prep Macros", str(exc))
            return
        self._set_shared_target_flow(p["flow_set_value"], "Gas Prep")
        self._start_independent_job(
            self.gas_prep_independent_threads, "flow_set",
            lambda runner: runner.run_gas_prep_flow_set(p["flow_set_value"]),
            "Starting Gas Prep: flow_set",
            [self.gas_prep_flow_set_button],
            "__GAS_PREP_FLOW_SET_DONE__",
        )

    def _on_gas_prep_flow_get(self):
        """Independent of the 7 macro buttons above and of every other
        scan/macro/standalone action -- see _on_gas_prep_flow_set's
        docstring."""
        def worker_fn(runner):
            result = runner.run_gas_prep_flow_get()
            self._call_in_tk(self._set_gas_prep_flow_result, result)

        self._start_independent_job(
            self.gas_prep_independent_threads, "flow_get",
            worker_fn,
            "Starting Gas Prep: flow_get",
            [self.gas_prep_flow_get_button],
            "__GAS_PREP_FLOW_GET_DONE__",
        )

    def _set_gas_prep_flow_result(self, result):
        """Only safe to call on the Tk thread -- see _call_in_tk's
        docstring. `result` is whatever Runner.flow_get() returned:
        None in preview mode / with no spec_controller attached (this
        tab never previews, so in practice this means "no SPEC
        connection"), otherwise the raw SPEC response."""
        self.gas_prep_flow_result_var.set("?" if result is None else str(result))

    def _on_gas_prep_preview_set_temperature(self):
        """Preview for the standalone "Set Temperature (te)" control --
        same pattern as _on_gas_prep_preview_macro: builds a fresh
        Runner(preview=True) with no spec_controller, so nothing is
        actually sent, and logs exactly what would be sent."""
        p = self._collect_gas_prep_params()
        try:
            validate_gas_prep_macros_params(p)
        except ValueError as exc:
            messagebox.showerror("Gas Prep Macros", str(exc))
            return
        self._append_log(
            "========== Preview: Gas Prep: set temperature (te) (nothing sent) =========="
        )
        preview_queue = queue.Queue()
        runner = Runner(preview_queue, threading.Event(), preview=True)
        runner.run_gas_prep_set_temperature(p["set_temperature_te"])
        while not preview_queue.empty():
            self._append_log(preview_queue.get_nowait())
        self._append_log(
            "========== End preview -- click Set Temperature to actually send this =========="
        )

    def _on_gas_prep_run_set_temperature(self):
        """Independent of the 7 macro buttons above and of every other
        scan/macro/standalone action -- see _on_gas_prep_flow_set's
        docstring."""
        p = self._collect_gas_prep_params()
        try:
            validate_gas_prep_macros_params(p)
        except ValueError as exc:
            messagebox.showerror("Gas Prep Macros", str(exc))
            return
        self._set_shared_target_temp(p["set_temperature_te"], "Gas Prep")
        self._start_independent_job(
            self.gas_prep_independent_threads, "set_temp",
            lambda runner: runner.run_gas_prep_set_temperature(p["set_temperature_te"]),
            "Starting Gas Prep: set temperature (te)",
            [self.gas_prep_set_temp_button],
            "__GAS_PREP_SET_TEMP_DONE__",
        )

    def _on_gas_prep_stop(self):
        self.gas_prep_cancel_event.set()
        self._append_log("[gas_prep] stop requested...")

    # ---- Read Gas Prep Macros tab's live temperatures from EPICS ----

    def _on_read_gas_prep_temps(self):
        """Identical in shape to _on_read_n2_he_temps, but for this
        tab's own independent gas_prep_* temperature vars/thread --
        see the __init__ comment on self.gas_prep_stage_a_temp_var
        for why this isn't just reusing the N2 -> He Switch section's
        copy."""
        if self._gas_prep_temp_read_thread and self._gas_prep_temp_read_thread.is_alive():
            return
        self.gas_prep_read_temps_button.config(state="disabled")
        self._append_log(
            "[gas_prep] reading temperatures from EPICS: "
            f"{STAGE_A_TEMP_PV}, {STAGE_C_TEMP_PV}, {SAMPLE_TEMP_PV}"
        )
        self._gas_prep_temp_read_thread = threading.Thread(
            target=self._read_gas_prep_temps_in_background, daemon=True
        )
        self._gas_prep_temp_read_thread.start()

    def _read_gas_prep_temps_in_background(self, log_result=True):
        """`log_result` is False only when called from
        _gas_prep_temp_watch_tick's own background polling -- see
        _read_standalone_temps_in_background's docstring for the
        same pattern/reasoning; a manual "Read Temperatures" click
        always passes the default True and still logs once."""
        try:
            import epics  # optional dependency, imported lazily on purpose
            # See _read_standalone_temps_in_background's comment on
            # this same call -- every one of these background-thread
            # EPICS readers must attach to the main thread's CA
            # context before any caget, or risk a native segfault.
            epics.ca.use_initial_context()
        except ImportError as e:
            self._call_in_tk(self._finish_read_gas_prep_temps, None, None, None, e, log_result)
            return
        try:
            stage_a = epics.caget(STAGE_A_TEMP_PV, as_string=True)
            stage_c = epics.caget(STAGE_C_TEMP_PV, as_string=True)
            sample = epics.caget(SAMPLE_TEMP_PV, as_string=True)
        except Exception as e:
            self._call_in_tk(self._finish_read_gas_prep_temps, None, None, None, e, log_result)
            return
        self._call_in_tk(
            self._finish_read_gas_prep_temps, stage_a, stage_c, sample, None, log_result
        )

    def _finish_read_gas_prep_temps(self, stage_a, stage_c, sample, error, log_result=True):
        if error is not None:
            if log_result:
                if isinstance(error, ImportError):
                    self._append_log(
                        "[gas_prep] pyepics is not installed -- install it "
                        "(pip install pyepics) to read live temperatures."
                    )
                else:
                    self._append_log(f"[gas_prep] temperature read failed: {error!r}")
        else:
            self.gas_prep_stage_a_temp_var.set(stage_a if stage_a is not None else "?")
            self.gas_prep_stage_c_temp_var.set(stage_c if stage_c is not None else "?")
            self.gas_prep_sample_temp_var.set(sample if sample is not None else "?")
            if log_result:
                self._append_log(
                    f"[gas_prep] Stage A={stage_a} Stage C={stage_c} Sample={sample}"
                )
            self._check_gas_prep_prepswitch_ready()
            self._check_target_temp_reached("gas_prep", stage_a, stage_c, sample)
        self.gas_prep_read_temps_button.config(state="normal")

    def _on_toggle_gas_prep_temp_watch(self):
        state = "on" if self.gas_prep_temp_watch_var.get() else "paused"
        self._append_log(f"[watch] Gas Prep temperature auto-watch {state}")

    def _schedule_gas_prep_temp_watch(self):
        self._gas_prep_temp_watch_after_id = self.after(
            _GAS_PREP_TEMP_WATCH_INTERVAL_MS, self._gas_prep_temp_watch_tick
        )

    def _gas_prep_temp_watch_tick(self):
        if self.gas_prep_temp_watch_var.get() and (
            self._gas_prep_temp_read_thread is None
            or not self._gas_prep_temp_read_thread.is_alive()
        ):
            self._gas_prep_temp_read_thread = threading.Thread(
                target=self._gas_prep_temp_watch_in_background, daemon=True
            )
            self._gas_prep_temp_read_thread.start()
        self._schedule_gas_prep_temp_watch()

    def _gas_prep_temp_watch_in_background(self):
        # log_result=False -- auto-watch keeps the on-screen Stage A/
        # Stage C/Sample fields live without writing a line to the
        # Log tab every tick; only a manual "Read Temperatures" click
        # still logs (see _read_gas_prep_temps_in_background's
        # docstring).
        self._read_gas_prep_temps_in_background(log_result=False)

    def _check_gas_prep_prepswitch_ready(self):
        """Same "next stage is ready" comparison as
        _check_n2_he_prepswitch_ready, scoped to this tab's own
        prepswitch_stage_a/prepswitch_stage_c fields
        (self.gas_prep_vars) and its own latch
        (self._gas_prep_prepswitch_ready_logged)."""
        try:
            stage_a = float(self.gas_prep_stage_a_temp_var.get())
            stage_c = float(self.gas_prep_stage_c_temp_var.get())
            setpoint_a = float(self.gas_prep_vars["prepswitch_stage_a"].get())
            setpoint_c = float(self.gas_prep_vars["prepswitch_stage_c"].get())
        except (TypeError, ValueError):
            return
        ready = (
            stage_a <= setpoint_a + _PREPSWITCH_READY_TOLERANCE_K
            and stage_c <= setpoint_c + _PREPSWITCH_READY_TOLERANCE_K
        )
        if ready and not self._gas_prep_prepswitch_ready_logged:
            self._append_log(
                f"[gas_prep] Stage A ({stage_a:g}K) and Stage C "
                f"({stage_c:g}K) have reached the prepswitch setpoints "
                f"({setpoint_a:g}K / {setpoint_c:g}K) -- next stage is ready"
            )
            self._gas_prep_prepswitch_ready_logged = True
        elif not ready and self._gas_prep_prepswitch_ready_logged:
            self._gas_prep_prepswitch_ready_logged = False

    # ---- Read Globals from SPEC ----

    def _on_read_globals(self):
        """Send every command in _SPEC_READ_COMMANDS through the shared
        connection -- currently just the bare expression "DATAFILE" --
        evaluating it directly rather than typing "p DATAFILE" at the
        SPEC prompt, and fill in the matching Global-parameters field
        here. Runs on a background thread since SPEC calls block;
        every result (success, unparseable, or error) is always
        logged, whether or not a field got updated. 'rampre' is NOT
        touched by this button -- see _SPEC_READ_COMMANDS' comment."""
        if self._last_read_globals_thread and self._last_read_globals_thread.is_alive():
            return
        self.read_globals_button.config(state="disabled")
        self._append_log(
            "[globals] reading from SPEC: " + ", ".join(_SPEC_READ_COMMANDS.values())
        )
        self._last_read_globals_thread = threading.Thread(
            target=self._read_globals_in_background, daemon=True
        )
        self._last_read_globals_thread.start()

    def _read_globals_in_background(self):
        results = {}
        for key, command in _SPEC_READ_COMMANDS.items():
            # `command` is already the exact thing to send -- the bare
            # expression "DATAFILE" -- _SPEC_READ_COMMANDS holds full
            # commands, so this is sent as-is.
            try:
                result = self.controller.send(command)
            except Exception as e:
                result = e
            results[key] = (command, result)
        self._call_in_tk(self._finish_read_globals, results)

    def _finish_read_globals(self, results):
        for key, (command, result) in results.items():
            if isinstance(result, Exception):
                text = describe_result(result, self.controller.spec_timeout)
                self._append_log(f"[globals] {command}: {text}")
                continue

            value = self._extract_global_value(result)
            if value is not None and key in self.global_vars:
                self.global_vars[key].set(value)
                self._append_log(f"[globals] {command} = {value!r} -> set '{key}' field")
            else:
                # Couldn't confidently parse a plain value out of the
                # response -- still show it (via describe_result, same
                # formatting the raw command box uses) so it can be
                # read and copied in by hand.
                text = describe_result(result, self.controller.spec_timeout)
                self._append_log(f"[globals] {command} -> {text}")
        self.read_globals_button.config(state="normal")

    @staticmethod
    def _extract_global_value(result):
        """Best-effort extraction of a plain value from a SPEC command
        response -- e.g. the bare "DATAFILE" expression (returning
        "test3\\n", matching what a real SPEC session shows for
        "p DATAFILE" at the prompt). Comes back as a plain string. If
        the response isn't a plain string this returns None rather
        than guessing, so the caller falls back to logging the raw
        response for the user to read (and copy in) by hand instead of
        silently setting a wrong/garbled field value."""
        if isinstance(result, str):
            value = result.strip()
            return value if value else None
        return None

    # ---- Read cycle/BTR from SPEC (live CWD) ----

    def _on_read_nfs_cycle_btr(self):
        """"Read cycle/BTR from SPEC" button handler -- added per
        explicit request ("NSF cycle information is wrong .. can you
        take that somehow correct?", clarified to "autograb from some
        file for cycle not sure how"). Sends the bare SPEC expression
        "CWD" (SPEC's own current working directory) through the
        shared connection and parses the cycle/BTR out of it via
        hrdm_core.parse_nfs_cwd(), same background-thread pattern as
        _on_read_globals above.

        Deliberately a separate button/handler from "Read from SPEC"
        (_on_read_globals) rather than adding "CWD" to
        _SPEC_READ_COMMANDS -- that dict, and _on_read_globals, are
        specifically guarded (see _SPEC_READ_COMMANDS' own comment,
        and the module docstring's "detector path prefix" section) to
        never send "CWD", because an earlier version of this GUI read
        _rampre live from CWD and pointed the detector at a path it
        couldn't write to. That risk is about 'rampre', not about
        nfs_cycle/nfs_btr -- those two fields exist specifically to
        represent the NFS path CWD already reflects -- so this new,
        separate button sends "CWD" on its own, without touching
        _SPEC_READ_COMMANDS or _on_read_globals at all."""
        if (
            self._last_read_nfs_cycle_btr_thread
            and self._last_read_nfs_cycle_btr_thread.is_alive()
        ):
            return
        self.read_nfs_cycle_btr_button.config(state="disabled")
        self._append_log("[globals] reading cycle/BTR from SPEC: CWD")
        self._last_read_nfs_cycle_btr_thread = threading.Thread(
            target=self._read_nfs_cycle_btr_in_background, daemon=True
        )
        self._last_read_nfs_cycle_btr_thread.start()

    def _read_nfs_cycle_btr_in_background(self):
        try:
            result = self.controller.send("CWD")
        except Exception as e:
            result = e
        self._call_in_tk(self._finish_read_nfs_cycle_btr, result)

    def _finish_read_nfs_cycle_btr(self, result):
        if isinstance(result, Exception):
            text = describe_result(result, self.controller.spec_timeout)
            self._append_log(f"[globals] CWD: {text}")
            self.read_nfs_cycle_btr_button.config(state="normal")
            return

        cwd_value = self._extract_global_value(result)
        if cwd_value is None:
            # Same "don't guess" fallback _finish_read_globals uses --
            # still show the raw response so it can be read/copied by
            # hand instead of silently doing nothing.
            text = describe_result(result, self.controller.spec_timeout)
            self._append_log(f"[globals] CWD -> {text}")
            self.read_nfs_cycle_btr_button.config(state="normal")
            return

        cycle, btr = parse_nfs_cwd(cwd_value)
        if cycle is None or btr is None:
            self._append_log(
                f"[globals] CWD = {cwd_value!r} -> doesn't look like an"
                " NFS path (expected /nfs/chess/id4b/<cycle>/<btr>/...)"
                " -- 'NFS cycle'/'NFS BTR' fields left unchanged"
            )
            self.read_nfs_cycle_btr_button.config(state="normal")
            return

        self.global_vars["nfs_cycle"].set(cycle)
        self.global_vars["nfs_btr"].set(btr)
        self._append_log(
            f"[globals] CWD = {cwd_value!r} -> set 'NFS cycle' field to"
            f" {cycle!r}, 'NFS BTR / proposal' field to {btr!r}"
        )
        self.read_nfs_cycle_btr_button.config(state="normal")

    # ---- DATAFILE auto-watch (background, no click required) ----

    def _on_toggle_datafile_watch(self):
        """Called when the "Auto-watch DATAFILE" checkbox is clicked.
        Doesn't start or stop anything itself -- the timer keeps
        ticking either way (see _datafile_watch_tick) -- it just logs
        the new state; the next tick reads the checkbox itself to
        decide whether to actually send anything."""
        state = "on" if self.datafile_watch_var.get() else "paused"
        self._append_log(f"[watch] DATAFILE auto-watch {state}")

    def _schedule_datafile_watch(self):
        """(Re)schedule the next auto-watch tick via self.after() --
        the same timer mechanism _poll_log/_run_tk_calls already use.
        In a real Tk mainloop this actually fires every
        _DATAFILE_WATCH_INTERVAL_MS; in the fake tkinter stub used by
        tests, self.after() is a no-op that never calls back on its
        own, so tests call _datafile_watch_tick() directly instead of
        waiting on a real timer."""
        self._datafile_watch_after_id = self.after(
            _DATAFILE_WATCH_INTERVAL_MS, self._datafile_watch_tick
        )

    def _datafile_watch_tick(self):
        """Runs every _DATAFILE_WATCH_INTERVAL_MS on the Tk thread.
        Starts a background SPEC read only if the checkbox is checked
        and no previous watch read is still in flight -- a slow or
        blocked SPEC connection just gets skipped this tick rather
        than piling up threads. Always reschedules itself afterward,
        so pausing/resuming the checkbox never needs to restart
        anything."""
        if self.datafile_watch_var.get() and (
            self._datafile_watch_thread is None
            or not self._datafile_watch_thread.is_alive()
        ):
            self._datafile_watch_thread = threading.Thread(
                target=self._datafile_watch_in_background, daemon=True
            )
            self._datafile_watch_thread.start()
        self._schedule_datafile_watch()

    def _datafile_watch_in_background(self):
        """Send the bare "DATAFILE" expression (same command "Read
        from SPEC" and Run Scan's auto-refresh use) and update the
        field only if the value actually changed since the last watch
        tick -- an unattended poll every 15 seconds would otherwise
        fill the Log tab with an identical line every cycle. Errors
        are logged but never raised; a temporarily-unreachable SPEC
        just gets tried again on the next tick."""
        try:
            result = self.controller.send("DATAFILE")
        except Exception as exc:
            text = describe_result(exc, self.controller.spec_timeout)
            self._call_in_tk(self._append_log, f"[watch] DATAFILE: {text}")
            return
        value = self._extract_global_value(result)
        if value is None or value == self._last_watched_datafile:
            return
        self._last_watched_datafile = value
        self._call_in_tk(self._set_global_var, "datafile", value)
        self._call_in_tk(
            self._append_log,
            f"[watch] DATAFILE changed to {value!r} -> updated 'datafile' field",
        )

    # ---- Read detector trigger mode from EPICS ----

    def _on_read_trigger_mode(self):
        """Read the detector's live trigger mode from the
        PIL10:cam1:TriggerMode_RBV EPICS PV via the optional `pyepics`
        package -- an entirely separate protocol/connection from the
        SPEC session above, so this never touches self.controller.
        Runs on a background thread since EPICS Channel Access calls
        can block; every outcome (success, unreachable PV, or pyepics
        not installed) is always logged, whether or not the trig_mode
        field got updated."""
        if self._last_read_trigmode_thread and self._last_read_trigmode_thread.is_alive():
            return
        self.read_trigmode_button.config(state="disabled")
        self._append_log(f"[trig_mode] reading from EPICS: {TRIGGER_MODE_PV}")
        self._last_read_trigmode_thread = threading.Thread(
            target=self._read_trigger_mode_in_background, daemon=True
        )
        self._last_read_trigmode_thread.start()

    def _read_trigger_mode_in_background(self):
        try:
            import epics  # optional dependency, imported lazily on purpose
            # See _read_standalone_temps_in_background's comment on
            # this same call -- every one of these background-thread
            # EPICS readers must attach to the main thread's CA
            # context before any caget, or risk a native segfault.
            epics.ca.use_initial_context()
        except ImportError as e:
            self._call_in_tk(self._finish_read_trigger_mode, None, e)
            return
        try:
            value = epics.caget(TRIGGER_MODE_PV, as_string=True)
        except Exception as e:
            self._call_in_tk(self._finish_read_trigger_mode, None, e)
            return
        self._call_in_tk(self._finish_read_trigger_mode, value, None)

    def _finish_read_trigger_mode(self, value, error):
        if error is not None:
            if isinstance(error, ImportError):
                self._append_log(
                    "[trig_mode] pyepics is not installed -- install it "
                    "(pip install pyepics) to use \"Read from EPICS\", or "
                    "set the dropdown by hand."
                )
            else:
                self._append_log(f"[trig_mode] {TRIGGER_MODE_PV}: {error!r}")
        elif value in TRIGGER_MODE_STATES:
            self.global_vars["trig_mode"].set(value)
            self._append_log(
                f"[trig_mode] {TRIGGER_MODE_PV} = {value!r} -> set 'trig_mode' field"
            )
        else:
            self._append_log(
                f"[trig_mode] {TRIGGER_MODE_PV} returned unexpected value "
                f"{value!r} (not one of the 5 known states) -- field left "
                "unchanged"
            )
        self.read_trigmode_button.config(state="normal")

    # ---- Read N2 -> He Gas Switch live temperatures from EPICS ----

    def _on_read_n2_he_temps(self):
        """Read Stage A, Stage C, and sample temperature from their
        Lakeshore 336 EPICS PVs (STAGE_A_TEMP_PV / STAGE_C_TEMP_PV /
        SAMPLE_TEMP_PV) -- an entirely separate protocol/connection
        from the SPEC session above, so this never touches
        self.controller. Runs on a background thread since EPICS
        Channel Access calls can block; shared code path with the
        auto-watch timer below via _read_n2_he_temps_in_background."""
        if self._n2_he_temp_read_thread and self._n2_he_temp_read_thread.is_alive():
            return
        self.n2_he_read_temps_button.config(state="disabled")
        self._append_log(
            "[n2_to_he_switch] reading temperatures from EPICS: "
            f"{STAGE_A_TEMP_PV}, {STAGE_C_TEMP_PV}, {SAMPLE_TEMP_PV}"
        )
        self._n2_he_temp_read_thread = threading.Thread(
            target=self._read_n2_he_temps_in_background, daemon=True
        )
        self._n2_he_temp_read_thread.start()

    def _read_n2_he_temps_in_background(self, log_result=True):
        """`log_result` is False only when called from
        _n2_he_temp_watch_tick's own background polling (via
        _n2_he_temp_watch_in_background) -- see
        _read_standalone_temps_in_background's docstring for the
        same pattern/reasoning; a manual "Read Temperatures" click
        always passes the default True and still logs once."""
        try:
            import epics  # optional dependency, imported lazily on purpose
            # See _read_standalone_temps_in_background's comment on
            # this same call -- every one of these background-thread
            # EPICS readers must attach to the main thread's CA
            # context before any caget, or risk a native segfault.
            epics.ca.use_initial_context()
        except ImportError as e:
            self._call_in_tk(self._finish_read_n2_he_temps, None, None, None, e, log_result)
            return
        try:
            stage_a = epics.caget(STAGE_A_TEMP_PV, as_string=True)
            stage_c = epics.caget(STAGE_C_TEMP_PV, as_string=True)
            sample = epics.caget(SAMPLE_TEMP_PV, as_string=True)
        except Exception as e:
            self._call_in_tk(self._finish_read_n2_he_temps, None, None, None, e, log_result)
            return
        self._call_in_tk(
            self._finish_read_n2_he_temps, stage_a, stage_c, sample, None, log_result
        )

    def _finish_read_n2_he_temps(self, stage_a, stage_c, sample, error, log_result=True):
        if error is not None:
            if log_result:
                if isinstance(error, ImportError):
                    self._append_log(
                        "[n2_to_he_switch] pyepics is not installed -- install "
                        "it (pip install pyepics) to read live temperatures."
                    )
                else:
                    self._append_log(
                        f"[n2_to_he_switch] temperature read failed: {error!r}"
                    )
        else:
            self.n2_he_stage_a_temp_var.set(stage_a if stage_a is not None else "?")
            self.n2_he_stage_c_temp_var.set(stage_c if stage_c is not None else "?")
            self.n2_he_sample_temp_var.set(sample if sample is not None else "?")
            if log_result:
                self._append_log(
                    f"[n2_to_he_switch] Stage A={stage_a} Stage C={stage_c} "
                    f"Sample={sample}"
                )
            self._check_n2_he_prepswitch_ready()
            self._check_target_temp_reached("n2_to_he_switch", stage_a, stage_c, sample)
        self.n2_he_read_temps_button.config(state="normal")

    def _on_toggle_n2_he_temp_watch(self):
        """Called when the "Auto-watch Temperatures" checkbox is
        clicked. Doesn't start or stop anything itself -- the timer
        keeps ticking either way (see _n2_he_temp_watch_tick) -- it
        just logs the new state; the next tick reads the checkbox
        itself to decide whether to actually read anything."""
        state = "on" if self.n2_he_temp_watch_var.get() else "paused"
        self._append_log(f"[watch] N2->He temperature auto-watch {state}")

    def _schedule_n2_he_temp_watch(self):
        """(Re)schedule the next auto-watch tick via self.after() --
        the same timer mechanism _schedule_datafile_watch uses. In a
        real Tk mainloop this actually fires every
        _N2_HE_TEMP_WATCH_INTERVAL_MS; in the fake tkinter stub used
        by tests, self.after() is a no-op that never calls back on
        its own, so tests call _n2_he_temp_watch_tick() directly
        instead of waiting on a real timer."""
        self._n2_he_temp_watch_after_id = self.after(
            _N2_HE_TEMP_WATCH_INTERVAL_MS, self._n2_he_temp_watch_tick
        )

    def _n2_he_temp_watch_tick(self):
        """Runs every _N2_HE_TEMP_WATCH_INTERVAL_MS on the Tk thread.
        Starts a background EPICS read only if the checkbox is
        checked and no previous watch read is still in flight -- a
        slow or unreachable EPICS gateway just gets skipped this tick
        rather than piling up threads. Always reschedules itself
        afterward, so pausing/resuming the checkbox never needs to
        restart anything."""
        if self.n2_he_temp_watch_var.get() and (
            self._n2_he_temp_read_thread is None
            or not self._n2_he_temp_read_thread.is_alive()
        ):
            self._n2_he_temp_read_thread = threading.Thread(
                target=self._n2_he_temp_watch_in_background, daemon=True
            )
            self._n2_he_temp_read_thread.start()
        self._schedule_n2_he_temp_watch()

    def _n2_he_temp_watch_in_background(self):
        """Identical to _read_n2_he_temps_in_background -- kept as a
        separate method (rather than reusing that one directly as the
        thread target) only so the Log tab / thread-naming stays
        parallel with the DATAFILE watch's
        _datafile_watch_in_background, and so a future divergence
        between the manual-button path and the auto-watch path has
        an obvious place to go. log_result=False -- auto-watch keeps
        the on-screen fields live without writing a line to the Log
        tab every tick; only a manual "Read Temperatures" click still
        logs."""
        self._read_n2_he_temps_in_background(log_result=False)

    def _check_n2_he_prepswitch_ready(self):
        """After every successful temperature read (manual or
        auto-watch), compare the live Stage A / Stage C readings
        against the current prepswitch setpoint fields
        (prepswitch_stage_a / prepswitch_stage_c in
        self.n2_he_switch_vars). prepswitch cools these stages down
        *to* their setpoints, so "reached" means the live reading has
        dropped to at or below the setpoint, within
        _PREPSWITCH_READY_TOLERANCE_K to absorb float noise around
        the exact setpoint. Logs the "next stage is ready" message
        once per transition -- self._n2_he_prepswitch_ready_logged
        latches it so a steady temperature doesn't repeat the message
        on every poll, and un-latches it if the stages warm back up
        past the setpoint (e.g. before a fresh attempt), so a later
        re-arrival logs again. Silently does nothing if a field isn't
        a valid number yet (e.g. still "?" before the first read)."""
        try:
            stage_a = float(self.n2_he_stage_a_temp_var.get())
            stage_c = float(self.n2_he_stage_c_temp_var.get())
            setpoint_a = float(self.n2_he_switch_vars["prepswitch_stage_a"].get())
            setpoint_c = float(self.n2_he_switch_vars["prepswitch_stage_c"].get())
        except (TypeError, ValueError):
            return
        ready = (
            stage_a <= setpoint_a + _PREPSWITCH_READY_TOLERANCE_K
            and stage_c <= setpoint_c + _PREPSWITCH_READY_TOLERANCE_K
        )
        if ready and not self._n2_he_prepswitch_ready_logged:
            self._append_log(
                f"[n2_to_he_switch] Stage A ({stage_a:g}K) and Stage C "
                f"({stage_c:g}K) have reached the prepswitch setpoints "
                f"({setpoint_a:g}K / {setpoint_c:g}K) -- next stage is ready"
            )
            self._n2_he_prepswitch_ready_logged = True
        elif not ready and self._n2_he_prepswitch_ready_logged:
            self._n2_he_prepswitch_ready_logged = False

    # ---- raw SPEC command Send / STOP (ported from spec_controller_gui.py) ----

    def _send_command(self):
        """Send the command in the entry box to SPEC, through the same
        shared self.controller used by Run Scan/shutter toggle. Does
        nothing if the box is empty or a command is still running."""
        command = self.command_var.get().strip()
        if not command or self._send_busy:
            return
        self.command_var.set("")
        self._append_log(f"> {command}")
        self._set_send_busy(True)
        self._last_send_thread = threading.Thread(
            target=self._send_command_in_background, args=(command,), daemon=True
        )
        self._last_send_thread.start()

    def _stop_command(self):
        """Abort whatever command SPEC is currently running -- like ^C
        at the SPEC console. Sent from a background thread so the
        window never freezes waiting for it, and STOP can always be
        pressed again."""
        self._append_log("STOP: sending abort to SPEC")
        self._last_abort_thread = threading.Thread(
            target=self._abort_in_background, daemon=True
        )
        self._last_abort_thread.start()

    def _send_command_in_background(self, command):
        try:
            result = self.controller.send(command)
        except Exception as e:
            result = e
        self._call_in_tk(self._finish_send_command, result)

    def _abort_in_background(self):
        result = self.controller.abort()
        if isinstance(result, Exception):
            self._call_in_tk(
                self._append_log,
                f"Failed to abort the SPEC command: {result!r}",
            )

    def _abort_until_stopped(self, is_running_fn, attempts=6, interval=0.5):
        """Send a real SPEC abort -- the same ABORT message
        _abort_in_background sends, like Ctrl+C at the console -- and
        keep resending it every `interval` seconds, up to `attempts`
        times total, for as long as `is_running_fn()` still reports
        the relevant worker thread alive. Stops retrying the instant
        `is_running_fn()` goes False (either because the abort
        actually interrupted the in-flight SPEC command, or because
        the run simply finished on its own in the meantime), so this
        never sends more abort attempts than it needs to and is a
        complete no-op once the thread has already exited.

        Added per explicit user request ("I want to stop the phi
        rotation as soon as I click stop"): a single abort() call
        already sends the real interrupt immediately -- that part
        isn't new, see _abort_in_background, which the raw STOP
        button (_stop_command) still uses as-is, since it has no
        long-running worker thread to poll against -- but a single
        attempt can in principle race the in-flight SPEC command's
        own reply depending on timing. Every Stop button that watches
        a long-running worker thread (_on_spin_stop,
        _on_low_temp_spin_stop, _on_gas_prep_spin_stop,
        _on_low_temp_stop) now calls this instead of starting a single
        one-shot _abort_in_background thread, so a Stop click gets a
        few automatic extra chances to interrupt a move that's still
        running, without the operator needing to click Stop
        repeatedly themselves.

        Returns the background thread doing the retrying (already
        started), purely so callers can keep stashing it in their own
        `self._last_*_abort_thread` attribute as before -- nothing
        currently reads that attribute back, but keeping it populated
        costs nothing and avoids changing those attributes' meaning."""
        def worker():
            for _attempt in range(attempts):
                if not is_running_fn():
                    return
                result = self.controller.abort()
                if isinstance(result, Exception):
                    self._call_in_tk(
                        self._append_log,
                        f"Failed to abort the SPEC command: {result!r}",
                    )
                if not is_running_fn():
                    return
                time.sleep(interval)

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        return thread

    def _finish_send_command(self, result):
        text = describe_result(result, self.controller.spec_timeout)
        if text is not None:
            self._append_log(text)
        self._set_send_busy(False)

    def _set_send_busy(self, busy):
        self._send_busy = busy
        self.send_button.config(state="disabled" if busy else "normal")

    def _call_in_tk(self, func, *args):
        """Queue *func* to be called with *args* on the Tk thread."""
        self._tk_calls.put((func, args))

    def _set_global_var(self, key, value):
        """Set a Global-parameters field's Tk variable -- only safe to
        call on the Tk thread itself, so background threads (e.g. the
        Run Scan worker auto-refreshing 'datafile' from live SPEC
        state) must go through _call_in_tk(self._set_global_var, key,
        value) rather than calling this directly."""
        if key in self.global_vars:
            self.global_vars[key].set(value)

    def _run_tk_calls(self):
        """Run the queued calls on the Tk thread, then reschedule."""
        while True:
            try:
                func, args = self._tk_calls.get_nowait()
            except queue.Empty:
                break
            func(*args)
        self.after(100, self._run_tk_calls)

    def destroy(self):
        """Cancel every auto-watch timer (DATAFILE, N2->He Switch
        temperatures, Gas Prep Macros temperatures) before the window
        actually closes, so none of them try to fire (or reschedule
        themselves) against a window that no longer exists. Each
        watch's background thread, if one happens to be in flight, is
        a daemon thread and simply finishes (or is dropped at
        interpreter exit) on its own -- nothing further to clean up
        there. (The N2->He Switch and Gas Prep Macros entries were
        added alongside their respective auto-watch features -- see
        _schedule_n2_he_temp_watch/_schedule_gas_prep_temp_watch.)"""
        if self._datafile_watch_after_id is not None:
            self.after_cancel(self._datafile_watch_after_id)
            self._datafile_watch_after_id = None
        if self._n2_he_temp_watch_after_id is not None:
            self.after_cancel(self._n2_he_temp_watch_after_id)
            self._n2_he_temp_watch_after_id = None
        if self._gas_prep_temp_watch_after_id is not None:
            self.after_cancel(self._gas_prep_temp_watch_after_id)
            self._gas_prep_temp_watch_after_id = None
        for _prefix, _label in STANDALONE_TEMP_FLOW_TABS:
            state = self.standalone[_prefix]
            if state["temp_watch_after_id"] is not None:
                self.after_cancel(state["temp_watch_after_id"])
                state["temp_watch_after_id"] = None
        super().destroy()

    # ---- log helpers ----

    def _append_log(self, msg, tag=None):
        """`tag`, when given, is a Text tag name (e.g. "alert") applied
        to just the line(s) being inserted here, so this one call can
        both log a message and have it stand out visually (item 5's
        "reached target temperature" notification uses tag="alert" --
        see _build_log_section for where that tag's color comes
        from). Every existing caller omits `tag`, so this is purely
        additive and changes nothing about how the log already
        looked."""
        self.log_text.configure(state="normal")
        start_index = self.log_text.index("end-1c")
        self.log_text.insert("end", msg + "\n")
        if tag:
            self.log_text.tag_add(tag, start_index, "end-1c")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _on_clear_log(self):
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    def _set_script(self, g, passes):
        script = generate_script(g, passes)
        self.script_text.configure(state="normal")
        self.script_text.delete("1.0", "end")
        self.script_text.insert("end", script)
        self.script_text.configure(state="disabled")

    def _poll_log(self):
        try:
            while True:
                msg = self.log_queue.get_nowait()
                if msg == "__DONE__":
                    self.run_button.configure(state="normal")
                    self.cancel_button.configure(state="disabled")
                    self._append_log("========== Finished ==========")
                elif msg == "__HEIGHT_DONE__":
                    # Sent by _on_height_run's worker() once a real
                    # Height Scan finishes (never Preview -- see
                    # _on_height_preview, which never touches
                    # self.log_queue with this sentinel).
                    self.height_run_button.configure(state="normal")
                    self._append_log("========== Height Scan finished ==========")
                elif msg == "__POWDER_DONE__":
                    # Sent by _on_powder_run's worker() once a real
                    # Powder Scan finishes (never Preview -- see
                    # _on_powder_preview, which never touches
                    # self.log_queue with this sentinel).
                    self.powder_run_button.configure(state="normal")
                    self._append_log("========== Powder Scan finished ==========")
                elif msg == "__SPIN_DONE__":
                    # Sent by _on_spin_start's worker() once spinning
                    # stops, whether from Stop being clicked or (with
                    # a fixed num_cycles) the spin sequence completing
                    # on its own.
                    self.spin_start_button.configure(state="normal")
                    self.spin_stop_button.configure(state="disabled")
                    self._append_log("========== Spin Control finished ==========")
                elif msg == "__LOW_TEMP_DONE__":
                    self.low_temp_run_button.configure(state="normal")
                    self.low_temp_stop_button.configure(state="disabled")
                    self._append_log("========== Low Temp Scan finished ==========")
                elif msg == "__LOW_TEMP_SAMPLE_SETUP_DONE__":
                    self.low_temp_sample_setup_run_button.configure(state="normal")
                    self.low_temp_sample_setup_stop_button.configure(state="disabled")
                    self._append_log("========== Low Temp Scan: Sample Setup finished ==========")
                elif msg == "__N2_HE_SWITCH_DONE__":
                    for btn in self._n2_he_switch_buttons():
                        btn.configure(state="normal")
                    self.n2_he_switch_stop_button.configure(state="disabled")
                    self._append_log("========== N2 -> He Switch finished ==========")
                elif msg == "__WARMUP_DONE__":
                    self.warmup_run_button.configure(state="normal")
                    self.warmup_stop_button.configure(state="disabled")
                    self._append_log("========== Warmup finished ==========")
                elif msg == "__WARMUP_CUSTOM_DONE__":
                    self.warmup_custom_run_button.configure(state="normal")
                    self.warmup_custom_stop_button.configure(state="disabled")
                    self._append_log("========== Warmup Custom finished ==========")
                elif msg == "__COOLDOWN_DONE__":
                    self.cooldown_run_button.configure(state="normal")
                    self.cooldown_stop_button.configure(state="disabled")
                    self._append_log("========== Cooldown finished ==========")
                elif msg == "__HIGHTEMP_DONE__":
                    self.hightemp_run_button.configure(state="normal")
                    self.hightemp_stop_button.configure(state="disabled")
                    self._append_log("========== High Temp Scan finished ==========")
                elif msg == "__GAS_PREP_DONE__":
                    for btn in self._gas_prep_all_buttons():
                        btn.configure(state="normal")
                    self.gas_prep_stop_button.configure(state="disabled")
                    self._append_log("========== Gas Prep Macros finished ==========")
                elif msg == "__GAS_PREP_SET_TEMP_DONE__":
                    # Set Temp/Flow Set/Flow Get on the Gas Prep Macros
                    # tab each got their own independent thread/button
                    # -- see _on_gas_prep_run_set_temperature -- so only
                    # this one button is re-enabled here, not the whole
                    # _gas_prep_all_buttons() group.
                    self.gas_prep_set_temp_button.configure(state="normal")
                    self._append_log("========== Gas Prep: set temperature (te) finished ==========")
                elif msg == "__GAS_PREP_FLOW_SET_DONE__":
                    self.gas_prep_flow_set_button.configure(state="normal")
                    self._append_log("========== Gas Prep: flow_set finished ==========")
                elif msg == "__GAS_PREP_FLOW_GET_DONE__":
                    self.gas_prep_flow_get_button.configure(state="normal")
                    self._append_log("========== Gas Prep: flow_get finished ==========")
                elif msg == "__LOW_TEMP_SPIN_DONE__":
                    self.low_temp_spin_start_button.configure(state="normal")
                    self.low_temp_spin_stop_button.configure(state="disabled")
                    self._append_log("========== Low Temp Scan: Spin finished ==========")
                elif msg == "__GAS_PREP_SPIN_DONE__":
                    self.gas_prep_spin_start_button.configure(state="normal")
                    self.gas_prep_spin_stop_button.configure(state="disabled")
                    self._append_log("========== Gas Prep: Spin finished ==========")
                elif isinstance(msg, tuple) and msg[0] == "__STANDALONE_DONE__":
                    # Sent by _start_independent_job's worker() for any
                    # of the new per-tab standalone Set Temp/Flow Set/
                    # Flow Get buttons (see STANDALONE_TEMP_FLOW_TABS) --
                    # msg[1] is the tab's prefix, msg[2] is which action
                    # ("set_temp"/"flow_set"/"flow_get").
                    _, standalone_prefix, standalone_action = msg
                    self._finish_standalone_action(standalone_prefix, standalone_action)
                elif isinstance(msg, tuple) and msg[0] == "__SCANN__":
                    # Only sent after a real Run Scan (never Preview Log
                    # -- see _on_run's worker()) once it actually
                    # finishes, so it's safe to persist straight into
                    # the field.
                    _, scan_n = msg
                    self.global_vars["next_scan_n"].set(str(scan_n))
                    self._append_log(
                        f"[next_scan_n] advanced to {scan_n} for next run"
                    )
                else:
                    self._append_log(msg)
        except queue.Empty:
            pass
        self.after(100, self._poll_log)


def main():
    parser = argparse.ArgumentParser(
        description="HDRM scan GUI + raw SPEC command sender, sharing one SPEC connection."
    )
    parser.add_argument("host", help="Hostname of the SPEC server.")
    parser.add_argument("port", type=int, help="Port of the SPEC server.")
    parser.add_argument(
        "--timeout", type=float, default=None,
        help="Seconds to wait for each command (default: wait indefinitely)."
    )
    parser.add_argument(
        "--verbose", action="store_true",
        help="Show the controller's INFO and DEBUG log messages."
    )
    args = parser.parse_args()

    if not args.verbose:
        logging.getLogger("spec_controller").setLevel(logging.WARNING)

    # Fail fast if there's clearly no display to open a window on,
    # before the (possibly long) SPEC connection attempt below --
    # checked via the DISPLAY environment variable rather than by
    # creating-then-destroying a throwaway tk.Tk() root the way an
    # earlier version of this function did. HRDMSpecApp is itself a
    # Tk root that applies a ttk theme, and creating a second,
    # separate Tk()/ttk application in the same process after
    # destroying a first one is NOT safe: in practice it produced
    # exactly this crash --
    #   can't invoke "event" command: application has been destroyed
    #       while executing "event generate $w <<ThemeChanged>>"
    #   Segmentation fault (core dumped)
    # -- because Tk's window/application registry for a given X
    # display is shared across every Tk() instance in the process,
    # not isolated per interpreter, so destroying the first root left
    # a dangling entry that the second root's ttk theme setup (and
    # Tcl's own deferred idle-callback processing) then crashed on.
    # Only one Tk() root must ever exist per process here -- so the
    # display check below never constructs one.
    if sys.platform.startswith("linux") and not os.environ.get("DISPLAY"):
        print(
            "No display available (DISPLAY is not set) -- cannot open the GUI.",
            file=sys.stderr,
        )
        sys.exit(1)

    controller = SpecController(args.host, args.port, args.timeout)
    try:
        app = HRDMSpecApp(controller)
    except tk.TclError as exc:
        print(f"Could not open the GUI display: {exc}", file=sys.stderr)
        sys.exit(1)
    app.mainloop()


if __name__ == "__main__":
    main()
