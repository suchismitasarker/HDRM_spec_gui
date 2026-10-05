"""
hrdm_core.py

Toolkit-independent scan logic for the HDRM three-crystal scan
(translated from HRDM.mac's `sortmypathout` / `threextalscan`), for
the quick sample-quality "height scan" (translated from
HDRMscans_new.mac's `heightscan` macro -- see `Runner.run_height_scan`
below), and for the powder-diffraction calibration "powder scan"
(translated from HDRMscans_new.mac's `powderscan` macro -- see
`Runner.run_powder_scan` below).

This module has ZERO GUI-toolkit dependencies (no tkinter, no PyQt5,
no pyqtgraph -- only the standard library), so it can be imported and
unit-tested on its own, and reused by more than one GUI front end
(e.g. the Tkinter `HRDM_gui.py` and the PyQt5 `HRDM_gui_pyqt.py` in
this project both build on the same `Runner` class defined here).

All beamline/instrument commands from the original macro (te, pil_on,
pil_setdir, pil_settrig, umv, opens, closes, flyscan, lup,
"u mkdir ...") are implemented as stub methods on `Runner` that just
log what they would do and return immediately -- see each method's
"# TODO: wire up real hardware call" comment. Nothing here talks to
real hardware.
"""

import os
import threading
import time

# ============================================================
# Defaults (mirror the values baked into HRDM.mac)
# ============================================================

DEFAULT_GLOBALS = {
    "datafile": "datafile",
    "sample": "sample1/",
    "rampre": "/ramdisk/sarker-4775-a/",
    # The beamtime cycle and BTR/proposal ID that, together, make up
    # the NFS root the raw6M/... directory (see Runner.run/
    # run_height_scan/run_powder_scan's own
    # mysamplepath = f"raw6M/{datafile}/" lines) actually sits under
    # once SPEC is cd'd into a real beamtime directory -- e.g. SPEC's
    # own working directory looks like
    # "/nfs/chess/id4b/2026-3/sarker-4775-a" (see this file's module
    # docstring / HRDM_spec_gui.py's "rampre" discussion for that same
    # observation): cycle="2026-3", btr="sarker-4775-a". This
    # project's own addition, purely for display: none of the scan
    # methods above need either value themselves (SPEC's cwd already
    # points here when they run "u mkdir raw6M/..."), but
    # resolve_data_dirs() below combines them into
    # "/nfs/chess/id4b/{cycle}/{btr}/" to show/link the actual
    # absolute raw-data and processed-data (nxrefine) directories on
    # the GUI's Sample Information tab, since there was previously no
    # field anywhere representing either one. Kept as two separate
    # fields (rather than one free-text path) specifically so
    # switching beamtime cycles/proposals is a matter of picking the
    # cycle and BTR, not hand-editing an opaque NFS path -- update
    # these by hand when the cycle/proposal changes, same as "rampre"
    # above; the values here are a real example from a past run, not
    # a guess.
    "nfs_cycle": "2026-2",
    "nfs_btr": "sarker-4910-a",
    "temperature": "300",
    "wait_seconds": "5",
    "num_steps": "3650",
    "count_time": "0.1",
    "trig_mode": "Mult. Trigger",
    # The next SCAN_N to use -- mirrors multi_pilatus_v5.mac's SPEC
    # built-in SCAN_N counter, which _pil_file_setpath uses to build
    # each scan's own image subfolder (see the comment above Runner.run
    # for the full explanation). "1" matches where a fresh SPEC data
    # file's own scan counter starts.
    "next_scan_n": "1",
    "final_chi": "90",
    "final_th": "0",
    "final_phi": "0",
    # SPEC connection info (see spec_controller.py / SpecController).
    # Only used by the Tkinter GUI's Run Scan -- these are placeholder
    # values, edit them to point at your real SPEC server before
    # running for real. Preview Log never connects/sends anything,
    # regardless of these values.
    "spec_host": "localhost",
    "spec_port": "6510",
    "spec_timeout": "30",
}

# (chi, th, phi_start, scan_start, scan_stop) -- default passes shown
# in both GUIs (editable, and rows can be added/removed).
DEFAULT_PASSES = [
    {"chi": "90", "th": "0", "phi": "0", "scan_start": "0", "scan_stop": "365"},
    {"chi": "86", "th": "3", "phi": "0", "scan_start": "0", "scan_stop": "365"},
    {"chi": "95", "th": "-3", "phi": "0", "scan_start": "0", "scan_stop": "365"},
]

# Default passes for the shared HDRM-scan step used by all 5
# temperature-series tabs (Low Temp Scan, Warmup, Warmup Custom,
# Cooldown, High Temp Scan) -- see Runner._threextalscan_step(). These
# originally matched that method's own previously hard-coded
# `_HDRM_NEW_PASSES`/HDRMscans_new.mac chi/th/phi values (90/0, 88/3,
# 97/-3) exactly; per explicit user request these have since been
# upgraded to a new shared pass set (90/0, 86/3, 95/-3), applied
# uniformly here AND in `_HDRM_NEW_PASSES` below so both stay in sync.
# "scan_start"/"scan_stop" keys are added (defaulting to the method's
# previously hard-coded flyscan phi range, "0"->"365") so this list is
# shaped identically to DEFAULT_PASSES/a Passes table row above -- but
# it is a SEPARATE list from DEFAULT_PASSES, since the Threextal Scan tab's
# own Passes table (translated from HRDM.mac's `threextalscan`) and
# this shared temperature-series HDRM scan step (translated from
# HDRMscans_new.mac's own, differently-named local `threextalscan`
# macro) are two different macros with different hard-coded values --
# see the comment above Runner._threextalscan_step for the full
# explanation. Each temperature-series tab gets its OWN independent,
# editable copy of this list (and of HDRM_SCAN_DEFAULTS below) -- they
# are never shared with each other or with the Threextal Scan tab.
HDRM_SCAN_PASSES_DEFAULTS = [
    {"chi": "90", "th": "0", "phi": "0", "scan_start": "0", "scan_stop": "365"},
    {"chi": "86", "th": "3", "phi": "0", "scan_start": "0", "scan_stop": "365"},
    {"chi": "95", "th": "-3", "phi": "0", "scan_start": "0", "scan_stop": "365"},
]

# Default (num_steps, count_time) for the shared HDRM-scan step above,
# matching Runner._threextalscan_step()'s previously hard-coded
# `_HDRM_NEW_NUM_STEPS` ("3650") and the count_time it used to read
# live from the Threextal Scan tab's own Global-parameters
# 'count_time' field (DEFAULT_GLOBALS["count_time"], "0.1") -- now
# each temperature-series tab has its own independent 'count_time'
# field defaulting to the same "0.1", rather than silently sharing the
# Threextal Scan tab's value.
HDRM_SCAN_DEFAULTS = {
    "num_steps": "3650",
    "count_time": "0.1",
}

# Default (start, end, steps, count_time) for Runner.run_height_scan(),
# mirroring HDRMscans_new.mac's `heightscan` macro when called with no
# arguments ("Using default height scan parameters: -0.6 0.6 60 0.2").
# The older HDRMscans.mac's `heightscan` used -2/2/50/.1 instead (see
# its comment "For bigger sample change the hightrange") -- these
# defaults follow the newer/more actively maintained macro, but every
# value here is just a GUI field default and can be overridden per
# run, same as the older macro's hard-coded call could be edited by
# hand.
HEIGHTSCAN_DEFAULTS = {
    "start": "-0.6",
    "end": "0.6",
    "steps": "60",
    "count_time": "0.2",
}

# Default (temperature, wait_seconds, phi_start, phi_end, num_steps,
# count_time) for Runner.run_powder_scan(), mirroring
# HDRMscans_new.mac's `powderscan <temperature> <sleep_time>` macro.
# temperature/wait_seconds are just GUI field defaults (300 K / 5s,
# matching the same placeholder-style defaults DEFAULT_GLOBALS uses
# for its own 'temperature'/'wait_seconds' fields). phi_start/phi_end/
# num_steps default to 0/360/180 -- the phi range and step count match
# the macro's hard-coded `flyscan phi 0 360 180 2` exactly. count_time
# defaults here to 1s (a GUI-only default, not the macro's hard-coded
# 2s, and per explicit user request changed from an earlier 0.2s
# default) since the macro itself never parameterizes any of these
# four -- unlike the macro, all four are editable per run here, same
# as calling flyscan with different arguments by hand.
POWDERSCAN_DEFAULTS = {
    "temperature": "300",
    "wait_seconds": "5",
    "phi_start": "0",
    "phi_end": "360",
    "num_steps": "180",
    "count_time": "1",
}

# ------------------------------------------------------------------
# Temperature-series scans + sample spinning, all translated from
# HDRMscans_new.mac (spin_xtal_phi / spin_ice / spin_xtal_phi_10min /
# spin_xtal_phi_20min / low_temp_scan / low_temp_scan_custom / warmup
# / warmup_custom / cooldown / hightemp_scan), plus the gas-flow/
# temperature-prep macros from Lakeshore336cryocool.mac that
# warmup/warmup_custom/cooldown/hightemp_scan call (prepN2_low/
# _medium/_high, roomT, highT) -- see the stub methods below Runner's
# existing te/pil_on/etc. stubs, and Runner.run_warmup /
# run_warmup_custom / run_cooldown / run_hightemp_scan /
# run_low_temp_scan / run_spin_xtal_phi further down.
#
# IMPORTANT -- these five macros in HDRMscans_new.mac call their OWN
# LOCAL `threextalscan <temp> <sleep>` macro (defined earlier in the
# same file, hard-coding passes chi90/th0, chi88/th3, chi97/th-3 and
# flyscan phi 0->365 over numSteps_=3650 steps) every time they need a
# full HDRM scan at a temperature -- this is a DIFFERENT macro from
# the one Runner.run() above translates (which is HRDM.mac's
# threextalscan, used by the "Threextal Scan" tab with its own
# editable Passes table and different hard-coded angles: 90/0, 88/0.7,
# 92/1.0). To stay faithful to HDRMscans_new.mac, all five methods
# below call Runner._threextalscan_step() -- a private helper that
# reproduces HDRMscans_new.mac's OWN threextalscan exactly -- rather
# than reusing Runner.run() / the Threextal Scan tab's Passes table.
# _threextalscan_step() still reads 'datafile'/'sample'/'rampre'/
# 'count_time'/'next_scan_n' from the SAME Global-parameters `g` dict
# as Runner.run(), since HDRMscans_new.mac's setup_scan_parameters/
# sortmypathout use the same _mysample/_rampre/countTime_ globals as
# HRDM.mac.

# flow_set is called throughout HDRMscans_new.mac's warmup/
# warmup_custom/cooldown/hightemp_scan macros but is never actually
# DEFINED in either HDRMscans_new.mac or Lakeshore336cryocool.mac (nor
# anywhere else in HDRM_scripts/) -- like `te`, it's treated here as
# an external hardware stub (Runner.flow_set below) rather than
# something this project can show the "real" implementation of.

# Default (num_cycles, ice_mode) for Runner.run_spin_xtal_phi(),
# mirroring HDRMscans_new.mac's `spin_xtal_phi` macro (continuous
# spin, phi 0<->360 with 1s sleeps each way, until stopped -- the
# macro's own for-loop bound is 10000 cycles, which Runner.
# run_spin_xtal_phi() also uses as its ceiling when num_cycles is left
# blank/None, since a real spin session is always stopped with the
# Stop button / Ctrl+C long before 10000 cycles (~5.5 hours) complete
# regardless). `ice_mode` toggles the two behaviors that make
# `spin_ice` different from `spin_xtal_phi` -- see
# Runner.run_spin_xtal_phi's docstring for the (very small) diff:
# spin_ice is functionally the SAME spin loop, with only (1) an
# initial 5s startup delay and (2) a "motors OK" log line + 2s pause
# every 100 cycles added on top. `num_cycles`, when set, also
# generalizes spin_xtal_phi_10min (a fixed 4-cycle spin, despite its
# name/printed message claiming "5 cycles" -- see the docstring) and
# spin_xtal_phi_20min (a fixed 10-cycle spin) into one editable field.
SPIN_DEFAULTS = {
    "num_cycles": "",  # blank == continuous (Stop button required)
    "ice_mode": "0",
}

# Default (start_temp, end_temp, step_temp, spin_cycles,
# post_temp_wait_seconds) for Runner.run_low_temp_scan(), mirroring
# HDRMscans_new.mac's `low_temp_scan` macro's ACTUAL for-loop bounds
# (`for (loopT=30; loopT<111; loopT=loopT+10)`) -- NOT the several
# mutually-inconsistent temperature ranges its own printf() lines
# claim ("15K to 110K (step 15K)" in one line, "Temperatures: 15K,
# 30K, ... 105K" in another -- neither matches the real loop, which
# actually runs 30K, 40K, ..., 110K). This mismatch is called out
# here, and in the GUI/README, rather than silently treated as
# authoritative -- the loop bounds are what actually runs, so that's
# what these defaults (and low_temp_scan_custom's own 20/130/20
# printed-but-also-unused defaults) are replaced by. spin_cycles
# defaults to 4, matching spin_xtal_phi_10min's ACTUAL loop bound
# (`for (ii=0;ii<4;ii++)`) -- again despite its own name/printed
# message claiming "5-cycle"/"approx 10 minutes".
LOW_TEMP_SCAN_DEFAULTS = {
    "start_temp": "30",
    "end_temp": "110",
    "step_temp": "10",
    "spin_cycles": "4",
    "post_temp_wait_seconds": "1",
}

# Defaults for Runner.run_low_temp_sample_setup() -- a standalone,
# one-click "sample setup" button on the Low Temp Scan tab (this
# project's own addition, no macro precedent): just sends a sample
# temperature (`te`) and gas flow (`flow_set`), independent of -- and
# not part of -- the automatic Low Temp Scan loop above or the
# N2 -> He Gas Switch section. Per user request, defaults to
# te=240K, flow_set=12 (both editable in the GUI); this pair does not
# match either of N2_TO_HE_SWITCH_DEFAULTS' existing te/flow_set
# combos (240/10 for Steps 3-4, 12/15 for Steps 9-10), confirming this
# is a distinct, independent setpoint pair rather than a duplicate of
# either.
LOW_TEMP_SAMPLE_SETUP_DEFAULTS = {
    "sample_temp": "240",
    "sample_flow": "12",
}

# Defaults for Runner.run_n2_to_he_switch() -- the manual, one-command-
# at-a-time N2->He gas-switch procedure normally run by hand at the
# FOURC prompt to take the sample from room temperature down toward
# base temperature (roughly 300K -> 15K), before Low Temp Scan's own
# temperature-stepping loop even starts. This project's own addition
# (not itself a single macro): it stitches together
# Lakeshore336cryocool.mac's `prepswitch`/`runninghelium` macros with
# the manual "turn the He valve on / N2 valve off together" step (which
# can't be automated -- the log just prints clear instructions for the
# operator to follow) and HDRMscans_new.mac's `spin_xtal_phi`, so the
# whole sequence can be run with one click instead of one command at a
# time. Every wait is expressed in MINUTES (unlike every other wait
# elsewhere in this project, which use seconds) since these are
# genuinely multi-minute physical stabilization waits, not brief
# software delays; a wait of "0" skips that pause entirely (e.g. for
# Preview, or if the operator prefers to judge it by eye on the sample
# stage temperature GUI instead).
#   Step 1: prepswitch (SETP_S1=100 "Stage A", SETP_S3=95 "Stage C" --
#     switching from N2 to He is safe once Stage A is above ~90K and
#     Stage C is above ~85K). An earlier version of this project also
#     had prepswitch call flow_set automatically; per explicit user
#     request that has been removed again, so Step 1 now matches the
#     real Lakeshore336cryocool.mac `prepswitch` macro exactly (just
#     the two epics_put calls, no flow side effect).
#   Step 2: wait (editable minutes) for Stage A/Stage C to stabilize
#     near ~96K/~87K (verify on the sample stage temperature GUI --
#     these are the macro's ACTUAL settling values, slightly off from
#     the 100/95 setpoint, not new setpoints of their own).
#   Steps 3-4: te 240, flow_set 10.
#   Step 5: wait (editable minutes) for the sample itself to reach
#     240K (watch for ice).
#   Step 6: MANUAL -- turn on the He valve and close the N2 valve
#     TOGETHER; only a log instruction, since this can't be automated.
#   Step 7: runninghelium (SETP_S1=30 "Stage A", SETP_S3=16 "Stage C" --
#     confirmed directly against Lakeshore336cryocool.mac's own
#     `runninghelium` definition).
#   Step 8: wait (editable minutes) for base temperature to stabilize
#     near Stage A~30K/Stage C~16K (verify on the sample stage
#     temperature GUI).
#   Steps 9-10: flow_set 12, te 15.
#   Step 11: spin_xtal_phi (editable cycle count, default 4 to match
#     this project's usual default rather than the macro's own
#     "continuous until stopped" behavior).
#
# Each of the 4 step-groups above (Steps 1-2, Steps 3-5, Steps 6-8,
# Steps 9-11) also has its own "*_enabled" flag ("1"/"0", like
# WARMUP_PHASE_DEFAULTS' per-phase "enabled" flag) -- this project's
# own addition, not part of any macro. Per user request, all default
# to disabled ("0") rather than enabled, so nothing in this section
# fires until a step-group is deliberately checked on first; checking
# a group's "Enabled" checkbox in the GUI includes it (with a log
# line noting which groups are skipped) the next time the single
# "Run N2 -> He Switch" button is clicked, the same way checking a
# Warmup phase includes it. The dedicated "Run Step 1 Only" /
# "Run Steps 3-5 Only" buttons (see run_n2_to_he_step1 /
# run_n2_to_he_steps_3_to_5) are independent of these flags -- they
# always run, regardless of what's checked here.
N2_TO_HE_SWITCH_DEFAULTS = {
    "prepswitch_stage_a": "100",
    "prepswitch_stage_c": "95",
    "wait_after_prepswitch_minutes": "5",
    "step1_enabled": "0",
    "sample_temp_1": "240",
    "flow_1": "10",
    "wait_for_sample_temp_minutes": "5",
    "steps3_5_enabled": "0",
    "runninghelium_stage_a": "30",
    "runninghelium_stage_c": "16",
    "wait_for_base_temp_minutes": "5",
    "step7_enabled": "0",
    "flow_2": "12",
    "sample_temp_2": "15",
    "spin_cycles": "4",
    "steps8_10_enabled": "0",
}

# One entry per phase for Runner.run_warmup(), mirroring
# HDRMscans_new.mac's `warmup` macro's 3 hard-coded phases exactly
# (Phase 1: prepN2_low, te 120, flow_set 9, spin_xtal_phi_20min, then
# loop 120K<155K step 10K each with spin_xtal_phi_10min before its
# threextalscan call; Phase 2: same shape at prepN2_medium/te 160/
# flow_set 8/160K<205K; Phase 3: prepN2_high/te 210/flow_set 6/
# 210K<291K -- but Phase 3's own loop does NOT call
# spin_xtal_phi_10min before threextalscan, unlike Phase 1 and 2 --
# this looks like it could be a macro bug/inconsistency, but is
# preserved faithfully here via spin_per_step_cycles="0" on Phase 3
# only, rather than "fixed" silently). "enabled" lets each phase be
# included independently (GUI checkbox) -- the macro itself always
# runs all 3 in sequence with no way to skip one, so this is a
# deliberate, additive parametrization beyond the macro, same as
# Powder Scan's flyscan range. Per user request, all 3 phases default
# to disabled ("0") rather than enabled, so nothing runs until a
# phase is deliberately checked on; this matches
# N2_TO_HE_SWITCH_DEFAULTS' step-groups, which default the same way.
#
# Each phase dict also carries its own "room_temp_after_*" interlude
# (room_temp_after_enabled/room_temp_after_te/room_temp_after_flow):
# an optional, per-phase, off-by-default step that -- if checked on --
# sends a te/flow_set pair to return the sample to (by default) room
# temperature immediately after that phase's own temperature loop
# finishes, before moving on to the next phase. This is a deliberate,
# additive parametrization beyond the macro (there is no equivalent in
# the real `warmup` macro), requested so a run can pause at room
# temperature between phases as needed. It is completely independent
# of, and does not replace or interact with, the existing single
# end-of-sequence "Phase 4" step below
# (WARMUP_FINAL_STEP_DEFAULTS/final_te_300) -- that step still only
# fires once, after every enabled phase has completed, exactly as
# before. Like every other Enabled checkbox on this tab,
# room_temp_after_enabled defaults to "0" (off), and run_warmup()
# always proceeds automatically from one step to the next regardless
# of which combination of phase/interlude checkboxes are checked --
# there is no pause-for-confirmation between steps.
WARMUP_PHASE_DEFAULTS = [
    {
        "label": "Phase 1: Low N2 flow",
        "enabled": "0",
        "prep_fn": "low",
        "initial_temp": "120",
        "flow_initial": "9",
        "spin20_cycles": "10",
        "start_temp": "120",
        "end_temp": "155",
        "step_temp": "10",
        "spin_per_step_cycles": "4",
        # Lakeshore 336 cryocooler stage setpoints sent by this
        # phase's prep_fn ("low" -> Runner.prepN2_low(), which mirrors
        # Lakeshore336cryocool.mac's `prepN2_low` macro exactly:
        # epics_put LAKESHORE2:SETP_S1=87, LAKESHORE2:SETP_S3=85,
        # i.e. "Stage A"=87, "Stage C"=85 in the macro's own terms --
        # confirmed against the .mac source). Editable here (same as
        # every other number on this tab) so a change to the real
        # macro's setpoints doesn't require a code change; left as the
        # macro's own defaults otherwise.
        "stage_a": "87",
        "stage_c": "85",
        # Optional "return to room temp after this phase" interlude --
        # off by default; see the comment above WARMUP_PHASE_DEFAULTS.
        "room_temp_after_enabled": "0",
        "room_temp_after_te": "300",
        "room_temp_after_flow": "6",
    },
    {
        "label": "Phase 2: Medium N2 flow",
        "enabled": "0",
        "prep_fn": "medium",
        "initial_temp": "160",
        "flow_initial": "8",
        "spin20_cycles": "10",
        "start_temp": "160",
        "end_temp": "205",
        "step_temp": "10",
        "spin_per_step_cycles": "4",
        # Stage setpoints for "medium" -> Runner.prepN2_medium(),
        # mirroring Lakeshore336cryocool.mac's `prepN2_medium` macro
        # exactly: SETP_S1=130, SETP_S3=110.
        "stage_a": "130",
        "stage_c": "110",
        # Optional "return to room temp after this phase" interlude --
        # off by default; see the comment above WARMUP_PHASE_DEFAULTS.
        "room_temp_after_enabled": "0",
        "room_temp_after_te": "300",
        "room_temp_after_flow": "6",
    },
    {
        "label": "Phase 3: High N2 flow",
        "enabled": "0",
        "prep_fn": "high",
        "initial_temp": "210",
        "flow_initial": "6",
        "spin20_cycles": "10",
        "start_temp": "210",
        "end_temp": "291",
        "step_temp": "10",
        "spin_per_step_cycles": "0",  # matches the macro: Phase 3's loop never calls spin_xtal_phi_10min
        # Stage setpoints for "high" -> Runner.prepN2_high(),
        # mirroring Lakeshore336cryocool.mac's `prepN2_high` macro
        # exactly: SETP_S1=165, SETP_S3=160.
        "stage_a": "165",
        "stage_c": "160",
        # Optional "return to room temp after this phase" interlude --
        # off by default; see the comment above WARMUP_PHASE_DEFAULTS.
        # Note this is independent of the existing end-of-sequence
        # "Phase 4" step below (WARMUP_FINAL_STEP_DEFAULTS): if both
        # this and Phase 4 are enabled, the sample is sent to room
        # temperature twice in a row (once here, once at the very
        # end) -- harmless, but worth knowing.
        "room_temp_after_enabled": "0",
        "room_temp_after_te": "300",
        "room_temp_after_flow": "6",
    },
]

# Defaults for Warmup's "Phase 4" final step (see run_warmup's
# `final_te_300`/`final_sample_temp`/`final_sample_flow` docstring) --
# an optional, off-by-default extra step (this project's own addition,
# not part of the real `warmup` macro) that sends a sample temperature
# + gas flow after every enabled phase has finished. Defaults match
# High Temp Scan's own final step (300K/6) since both serve the same
# "return to room temperature" purpose.
WARMUP_FINAL_STEP_DEFAULTS = {
    "sample_temp": "300",
    "sample_flow": "6",
}

# Default (start_temp, end_temp, step_temp, spin_cycles, threshold1,
# flow1, threshold2, flow2, flow3) for Runner.run_warmup_custom(),
# mirroring HDRMscans_new.mac's `warmup_custom` macro's no-argument
# ("interactive mode") defaults (140/270/10) plus its per-temperature
# gas-selection thresholds (<=160 -> prepN2_low/flow_set 10, <=200 ->
# prepN2_medium/flow_set 9, else -> prepN2_high/flow_set 6). Unlike
# `warmup` (3 separate hard-coded phases, each with its own gas prep
# called once at the start of the phase), `warmup_custom` is a SINGLE
# continuous loop that re-evaluates which gas to use at EVERY
# temperature step based on these thresholds -- a genuinely different
# algorithm, not just different default numbers, which is why it gets
# its own tab/Runner method here rather than being folded into
# run_warmup().
WARMUP_CUSTOM_DEFAULTS = {
    "start_temp": "140",
    "end_temp": "270",
    "step_temp": "10",
    "spin_cycles": "4",
    "threshold1": "160",
    "flow1": "10",
    "threshold2": "200",
    "flow2": "9",
    "flow3": "6",
}

# Default (start_temp, end_temp, step_temp, spin_cycles,
# threshold_high, flow_high, threshold_medium, flow_medium, flow_low)
# for Runner.run_cooldown(), mirroring HDRMscans_new.mac's `cooldown`
# macro's no-argument defaults (300/100/20, descending) plus its
# per-temperature gas thresholds (>=200 -> prepN2_high/flow_set 6,
# >=160 -> prepN2_medium/flow_set 9, else -> prepN2_low/flow_set 10)
# -- the same threshold-driven single-loop shape as warmup_custom, just
# descending instead of ascending and with the threshold comparisons
# flipped to match. Unlike warmup/warmup_custom (and low_temp_scan),
# the macro's own `cooldown` has no 10s "Ctrl+C to abort" warning
# delay before it starts -- preserved faithfully (no sleep(10) call
# here either).
COOLDOWN_DEFAULTS = {
    "start_temp": "300",
    "end_temp": "100",
    "step_temp": "20",
    "spin_cycles": "4",
    "threshold_high": "200",
    "flow_high": "6",
    "threshold_medium": "160",
    "flow_medium": "9",
    "flow_low": "10",
}

# Default (start_temp, end_temp, step_temp, scan_wait_seconds,
# final_temp, final_flow) for Runner.run_hightemp_scan(), mirroring
# HDRMscans_new.mac's `hightemp_scan` macro's ACTUAL for-loop bounds
# (`for (loopT=361; loopT<475; loopT=loopT+30)`) and its
# `eval(sprintf("threextalscan %d 360", loopT))` call -- note the
# 360-SECOND (6 minute) wait before each temperature's scan, unlike
# every other temperature-series macro here which passes 1. The
# macro's own printed messages for this ("=== WARMUP SEQUENCE
# (DEFAULT) ===", "Temperature range: 140K to 270K (10K steps)") are
# copy-pasted from `warmup` and describe neither hightemp_scan's real
# range (361-475K) nor its real step (30K) -- another doc/code
# mismatch translated around rather than propagated; see the matching
# note on LOW_TEMP_SCAN_DEFAULTS above. The macro's Phase 1 loop body
# also has `highT`/`te 330`/`flow_set 6`/`spin_xtal_phi_20min` (before
# the loop) and `spin_xtal_phi_10min` (inside the loop) all commented
# out with '#' -- so none of those actually run, and
# Runner.run_hightemp_scan() below faithfully does not call them
# either. Phase 2 (uncommented) sets room temperature/flow and a
# final `te` call once the loop finishes. "final_enabled" (this
# project's own addition, off by default) is a deliberate departure
# from the macro, which always runs Phase 2 unconditionally -- lets an
# operator skip Phase 2 entirely rather than only being able to edit
# its numbers.
HIGHTEMP_SCAN_DEFAULTS = {
    "start_temp": "361",
    "end_temp": "475",
    "step_temp": "30",
    "scan_wait_seconds": "360",
    "final_temp": "300",
    "final_flow": "6",
    "final_enabled": "0",
}

# The detector's trigger mode is reported by an EPICS areaDetector-style
# "TriggerMode_RBV" PV (an mbbi record). The real PV can report 5
# states total (Internal, Ext. Enable, Ext. Trigger, Mult. Trigger,
# Alignment -- see multi_pilatus_v5.mac's PIL_TRIGGER_MODES, which
# also excludes "Alignment" as a settable pil_settrig() mode since
# it's a readback-only state set internally by pil_von/pil_voff), but
# per the user only "Internal" and "Mult. Trigger" are actually used
# here, so this list is intentionally restricted to just those two.
# DEFAULT_GLOBALS["trig_mode"] and pil_settrig() both use the plain
# state string (e.g. "Mult. Trigger") -- not a numeric index -- so
# this list must keep matching those strings exactly. Both Tkinter
# GUIs use this to build a locked trig_mode dropdown (so it can't be
# mistyped or set to something pil_settrig() would reject) and to
# validate a live EPICS read against.
TRIGGER_MODE_STATES = [
    "Internal",
    "Mult. Trigger",
]

# EPICS PV that reports the detector's live trigger mode -- read via
# the optional `pyepics` package (see HRDM_gui.py's / HRDM_spec_gui.py's
# "Read from EPICS" button, next to the trig_mode field). Confirmed by
# the user against a real PV monitor (VALUE: "Mult. Trigger").
TRIGGER_MODE_PV = "PIL10:cam1:TriggerMode_RBV"

# Lakeshore 336 live temperature readback PVs -- a Lakeshore 336 has 4
# input channels (A/B/C/D), reported as KRDG0/KRDG1/KRDG2/KRDG3. Per
# the user: KRDG0 is Stage A, KRDG2 is Stage C, and KRDG1 is the
# sample temperature -- the last of which also matches
# Lakeshore336cryocool.mac's own `measuretemp` macro, which reads the
# sample temperature via `epics_get("LAKESHORE2:KRDG1")` (and the
# sample setpoint via `LAKESHORE2:SETP_S2`, not read live here since
# the GUI's own setpoint fields already show what was last sent).
# Read live via the optional `pyepics` package, exactly like
# TRIGGER_MODE_PV above -- see HRDM_spec_gui.py's "Read Temperatures"
# button in the N2 -> He Gas Switch section.
STAGE_A_TEMP_PV = "LAKESHORE2:KRDG0"
STAGE_C_TEMP_PV = "LAKESHORE2:KRDG2"
SAMPLE_TEMP_PV = "LAKESHORE2:KRDG1"

# Defaults for the Gas Prep tab -- a standalone tab that exposes each
# of Lakeshore336cryocool.mac's 7 gas/temperature-prep macros
# (prepN2_low, prepN2_medium, prepN2_high, prepswitch, runninghelium,
# roomT, highT) as its own independently-runnable button, rather than
# only reachable indirectly through Warmup/N2->He Switch/Low Temp Scan
# as before. Every macro's Stage A/Stage C setpoint fields default to
# the exact values already used elsewhere in this project (see each
# Runner method's own docstring for the macro-confirmed value), so
# this tab is just a more direct way to reach the same 7 methods, not
# a new set of values. "runninghelium_stage_c" is the one exception,
# per explicit user request (see Runner.runninghelium's docstring):
# changed from the macro-confirmed 16 to 9 for this tab. "flow_set_
# value" is the other exception -- see Runner.flow_get's docstring:
# this tab's own standalone flow_set/flow_get control is a project
# addition with no Lakeshore336cryocool.mac precedent, not a macro-
# confirmed value. The previous standalone "room_temperature_sample"
# button/fields (te/flow_set to a room-temperature sample setpoint,
# independent of roomT()) have been removed per explicit user request.
GAS_PREP_MACROS_DEFAULTS = {
    "prepn2_low_stage_a": "87",
    "prepn2_low_stage_c": "85",
    "prepn2_medium_stage_a": "130",
    "prepn2_medium_stage_c": "110",
    "prepn2_high_stage_a": "165",
    "prepn2_high_stage_c": "160",
    "prepswitch_stage_a": "100",
    "prepswitch_stage_c": "95",
    "runninghelium_stage_a": "30",
    "runninghelium_stage_c": "9",
    "roomt_stage_a": "222",
    "roomt_stage_c": "220",
    "hight_stage_a": "300",
    "hight_stage_c": "300",
    # Standalone flow_set control on this tab -- independent of any of
    # the macro buttons above, for sending an arbitrary flow_set
    # value on its own (e.g. matching one of the flow_set values used
    # elsewhere: 6, 8, 9, 10, 12).
    "flow_set_value": "6",
    # Standalone "Set Temperature (te)" control on this tab --
    # independent of any of the 7 macro buttons: lets an operator send
    # an arbitrary sample temperature (`te`) on its own, anywhere in
    # the 10-490K range (see validate_gas_prep_macros_params). No
    # Lakeshore336cryocool.mac precedent -- a project addition, per
    # user request, defaulting to 300K.
    "set_temperature_te": "300",
}

# Names accepted by Runner.run_gas_prep_macro(), in the order they
# appear on the Gas Prep tab -- kept as one shared list so the GUI and
# any tests iterate the exact same macros in the exact same order.
GAS_PREP_MACRO_NAMES = [
    "prepN2_low",
    "prepN2_medium",
    "prepN2_high",
    "prepswitch",
    "runninghelium",
    "roomT",
    "highT",
]

# Shared defaults for the standalone "Live temperatures (EPICS) + Set
# Temp (te) + Flow Control (flow_set/flow_get)" block added, per user
# request, to EVERY scan/temperature tab (Threextal Scan, Height
# Scan, Powder Scan, Low Temp Scan, Warmup, Warmup Custom, Cooldown,
# High Temp Scan) -- one shared dict since every tab's copy of this
# block starts from the exact same two values (set_temp_te=300,
# flow_set_value=6, matching the Gas Prep Macros tab's own
# set_temperature_te/flow_set_value defaults above), not because the
# fields are literally shared state -- each tab still gets its own
# independent Tk variables bound to these starting values (same
# "duplicate per tab, own state" convention already used for the
# Live-temperatures-EPICS block on the Gas Prep Macros and N2 -> He
# Switch sections). No macro precedent -- project additions, same as
# every other standalone te/flow_set/flow_get control in this file.
# Deliberately NOT reused by the Gas Prep Macros tab's own fields
# (GAS_PREP_MACROS_DEFAULTS above) or Low Temp Scan's existing "Sample
# Setup" fields (LOW_TEMP_SAMPLE_SETUP_DEFAULTS) -- those predate this
# dict and keep their own independent default dicts unchanged.
STANDALONE_TEMP_FLOW_DEFAULTS = {
    "set_temp_te": "300",
    "flow_set_value": "6",
}


def validate_standalone_temp_flow_params(p):
    """Validates one tab's copy of the standalone Set Temp (te) /
    Flow Control (flow_set) block (see STANDALONE_TEMP_FLOW_DEFAULTS
    above) -- reuses the exact same shared range helpers every other
    te/flow_set field in this file uses, so the 10-490K / 6-18 limits
    are identical everywhere. flow_get has no value to validate (it
    only reads)."""
    _validate_te_range(p["set_temp_te"], "Set Temp (te)")
    _validate_flow_set_range(p["flow_set_value"], "Flow Set")


def _pil_file_basename(datafile):
    """Mirrors multi_pilatus_v5.mac's `_pil_file_setpath`:
    `num = split(DATAFILE, file, "/")` then uses `file[num-1]` -- i.e.
    the last "/"-separated segment of DATAFILE -- as the prefix for
    each scan's own image subfolder. Used here so a `datafile` value
    that happens to contain a path still produces a sane subfolder
    name (e.g. "/foo/bar/test" -> "test"); a plain name like "test"
    (the normal case) passes through unchanged."""
    trimmed = str(datafile).rstrip("/")
    return trimmed.rsplit("/", 1)[-1] if trimmed else str(datafile)


def _format_temp(temperature):
    """Format a temperature value the way the real `te` SPEC macro and
    the resulting directory/file names expect: whole numbers render
    without a trailing ".0" (e.g. `280` rather than `280.0`), while a
    genuinely fractional value keeps its decimal (e.g. `280.5` stays
    `280.5`). This matters because several callers hand this function
    a Python `float` (e.g. the `loopT` loop variable in
    run_low_temp_scan/run_warmup/run_warmup_custom/run_cooldown/
    run_hightemp_scan), and `str(280.0)` is `"280.0"` -- which, before
    this fix, leaked into the `te` command sent to SPEC and into every
    directory/file name built from it (confirmed by the user: they
    were seeing folders named e.g. "280.0"/"290.0" instead of "280"/
    "290"). Non-numeric input (unexpected, but handled defensively)
    passes through as `str(temperature)` unchanged."""
    try:
        value = float(temperature)
    except (TypeError, ValueError):
        return str(temperature)
    if value.is_integer():
        return str(int(value))
    return f"{value:g}"


def resolve_data_dirs(g):
    """Compute the absolute raw-data and processed-data (nxrefine)
    directories a run with these Sample Information field values (`g`,
    same shape as DEFAULT_GLOBALS -- a plain dict of strings) will use/
    produce -- purely for display (e.g. on the GUI's Sample Information
    tab, next to "Open in file manager" / "Copy path" buttons), never
    called by Runner.run()/run_height_scan()/run_powder_scan()
    themselves. This project's own addition, added per explicit
    request ("Check the final data collection and data save folder ..
    mention that to the sample information").

    The NFS root is built here from two separate fields,
    `g['nfs_cycle']` (e.g. "2026-2") and `g['nfs_btr']` (e.g.
    "sarker-4910-a") -- see DEFAULT_GLOBALS' comment on them -- as
    `f"/nfs/chess/id4b/{cycle}/{btr}/"`, rather than accepting one
    free-text path, specifically so switching beamtime cycles/
    proposals (e.g. going from cycle 2026-2 to 2026-3) is a matter of
    editing one short field on the Sample Information tab, not
    hand-editing an opaque absolute path.

    Mirrors, without duplicating any hardware/logging behavior, the
    exact same relative-path construction Runner.run()/
    run_height_scan()/run_powder_scan() already use (see each one's
    own `mysamplepath = f"raw6M/{g['datafile']}/"` /
    `pilrampath = f"{rampre}{mysamplepath}{mysample}{myT}"` lines):
    `raw6M/{datafile}/{sample}{temperature}/`, with the NFS root
    prefixed on to make it absolute. None of those three methods
    needed that prefix themselves, since SPEC's own working directory
    already points there by the time they run `u mkdir raw6M/...` --
    but a human trying to browse to the result from outside SPEC does
    need it spelled out.

    The processed (nxrefine) directory belongs to a separate,
    downstream pipeline this project's GUI/engine never writes to --
    it's included here purely so Sample Information can show/link to
    it too. It's built the same way, but under
    `f"/nfs/chess/id4baux/{cycle}/{btr}/nxrefine/..."` (the "id4b" NFS
    mount becomes "id4baux", and "raw6M" becomes "nxrefine", with no
    final per-scan subfolder) -- confirmed against two real example
    paths given directly:
        raw:       /nfs/chess/id4b/2026-2/sarker-4910-a/raw6M/DyScO3/DyScO3_110/300/DyScO3_003/
        processed: /nfs/chess/id4baux/2026-2/sarker-4910-a/nxrefine/DyScO3/DyScO3_110/300/
    -- not guessed.

    Returns a dict of plain strings, never raises:
      - "raw_root": .../id4b/{cycle}/{btr}/raw6M/ (created via
        u_mkdir(..., parents=True) the first time any scan runs -- see
        Runner.run).
      - "raw_sample_dir": .../raw6M/{datafile}/{sample}{temperature}/
        -- the folder to open to watch this sample/temperature's scans
        accumulate; each one gets its own "{datafile}_{NNN}" subfolder
        inside it (see "next_scan_dir" below).
      - "next_scan_dir": raw_sample_dir + the *next* scan's own image
        subfolder, using g['next_scan_n'] -- i.e. exactly where the
        next Run Scan's images will land once it completes.
      - "processed_dir": the corresponding nxrefine directory (no
        per-scan subfolder -- nxrefine operates at the sample/
        temperature level, matching the example above).
    An empty/missing "nfs_cycle" or "nfs_btr" isn't treated as an
    error -- callers should show the result as-is (it will look like a
    relative path, e.g. "raw6M/datafile/sample1/300/") and let that be
    the signal to the user that both fields need to be filled in on
    the Sample Information tab, rather than popping up a validation
    error for what is, after all, just a display feature."""
    cycle = str(g.get("nfs_cycle") or "").strip().strip("/")
    btr = str(g.get("nfs_btr") or "").strip().strip("/")
    nfs_root = f"/nfs/chess/id4b/{cycle}/{btr}/" if (cycle and btr) else ""
    processed_nfs_root = (
        f"/nfs/chess/id4baux/{cycle}/{btr}/" if (cycle and btr) else ""
    )
    datafile = str(g.get("datafile") or "")
    sample = str(g.get("sample") or "")
    myT = _format_temp(g.get("temperature", ""))

    mysamplepath = f"raw6M/{datafile}/"
    raw_root = f"{nfs_root}{mysamplepath}"
    raw_sample_dir = f"{raw_root}{sample}{myT}/"

    datafile_basename = _pil_file_basename(datafile)
    try:
        next_scan_n = int(g.get("next_scan_n"))
        scan_suffix = f"{datafile_basename}_{next_scan_n:03d}"
    except (TypeError, ValueError):
        scan_suffix = f"{datafile_basename}_???"
    next_scan_dir = f"{raw_sample_dir}{scan_suffix}/"

    processed_dir = f"{processed_nfs_root}nxrefine/{datafile}/{sample}{myT}/"

    return {
        "raw_root": raw_root,
        "raw_sample_dir": raw_sample_dir,
        "next_scan_dir": next_scan_dir,
        "processed_dir": processed_dir,
    }


def parse_nfs_cwd(cwd):
    """Parse a live SPEC "CWD" (current working directory) string into
    the `(cycle, btr)` pair `resolve_data_dirs()` above expects for its
    `g['nfs_cycle']` / `g['nfs_btr']` inputs -- added per explicit
    request ("NSF cycle information is wrong .. can you take that
    somehow correct?", clarified to "autograb from some file for cycle
    not sure how"): rather than hand-editing DEFAULT_GLOBALS'
    `nfs_cycle`/`nfs_btr` strings (a static value that will always
    eventually go stale again the next time the beamtime cycle
    changes), the GUI's "Read cycle/BTR from SPEC" button (see
    HRDM_spec_gui.py's `_on_read_nfs_cycle_btr`) sends the bare SPEC
    expression "CWD" and hands the result to this function.

    SPEC's own CWD, once cd'd into a real beamtime directory, *is* the
    NFS path these two fields exist to represent -- e.g.
    "/nfs/chess/id4b/2026-3/sarker-4775-a" (see DEFAULT_GLOBALS'
    comment on nfs_cycle/nfs_btr, and this module's other CWD
    discussion in HRDM_spec_gui.py's module docstring). That's
    different from "rampre" (the Pilatus detector's own local ramdisk
    path prefix), which is deliberately NOT read live from CWD --
    see HRDM_spec_gui.py's `_SPEC_READ_COMMANDS` comment for why that
    one earlier attempt broke image saving. This function only ever
    parses the "/nfs/chess/id4b/<cycle>/<btr>" prefix into its two
    components; it doesn't touch rampre or any other field.

    Accepts any string SPEC might return for CWD (with or without a
    trailing slash, with or without extra path segments after
    <cycle>/<btr> -- e.g. a scan subfolder SPEC happened to cd deeper
    into). Only the "/nfs/chess/id4b/" prefix is required; anything
    else is a "wrong shape" answer, and every branch below is a
    deliberate best-effort match rather than a strict grammar, in
    keeping with this module's "never raise, never guess wildly"
    style for display-only helpers (see `resolve_data_dirs()` above,
    `_extract_global_value()` in HRDM_spec_gui.py).

    Returns a `(cycle, btr)` tuple of plain strings. If `cwd` doesn't
    start with the expected "/nfs/chess/id4b/" prefix, or doesn't have
    at least a cycle and a btr segment after it, returns `(None, None)`
    -- never raises, and never returns just one of the two (a partial
    parse is treated the same as no parse, since a cycle without a btr,
    or vice versa, isn't safe to apply to the Sample Information
    fields)."""
    prefix = "/nfs/chess/id4b/"
    text = str(cwd or "").strip()
    if not text.startswith(prefix):
        return None, None
    remainder = text[len(prefix):].strip("/")
    if not remainder:
        return None, None
    parts = remainder.split("/")
    if len(parts) < 2:
        return None, None
    cycle, btr = parts[0], parts[1]
    if not cycle or not btr:
        return None, None
    return cycle, btr


# ============================================================
# Runner: holds the stub "hardware" functions + the scan logic,
# logging everything through a caller-supplied thread-safe queue so
# it can run in a background thread without blocking a GUI event
# loop, regardless of which GUI toolkit is on top.
# ============================================================

# Module-level lock guarding the ONE real wire to SPEC
# (spec_controller.send()). Multiple independent Runner instances can
# now legitimately be active in different background threads at the
# same time (e.g. a quick standalone "Set Temperature" click running
# alongside a Low Temp Scan, now that those are no longer mutually
# exclusive at the GUI level -- see _other_scan_running in
# HRDM_spec_gui.py). All of those Runners still share the SAME
# underlying SpecController/socket, though, so without this lock two
# threads could interleave bytes on the wire and corrupt each other's
# commands/responses. This lock does NOT serialize whole scans against
# each other (that would defeat the point of allowing them to run
# concurrently) -- it only serializes the instant of actually writing
# one command and reading its response, so concurrent Runners are safe
# to use even though they're sharing one spec_controller.
_SPEC_SEND_LOCK = threading.Lock()


class Runner:
    def __init__(self, log_queue, cancel_event, preview=False, spec_controller=None):
        self.log_queue = log_queue
        self.cancel_event = cancel_event
        # preview=True: log every step exactly as normal, but don't
        # actually wait out any of the sleeps -- lets a GUI show the
        # full generated command log almost instantly, to review
        # before clicking "Run Scan" for the real (timed) run.
        self.preview = preview
        # spec_controller: optional SpecController instance (see
        # spec_controller.py). When provided AND preview is False,
        # every stub method below also sends the equivalent SPEC
        # command through it via self._send() -- see that method's
        # docstring. When None (the default) or preview=True, nothing
        # is ever sent anywhere; only the "[stub]" log lines happen,
        # exactly as before this was added.
        self.spec_controller = spec_controller

    def log(self, msg):
        self.log_queue.put(msg)

    def cancelled(self):
        return self.cancel_event.is_set()

    def _send(self, cmd):
        """Send `cmd` to SPEC through self.spec_controller.send(), and
        log the response -- but only if a real spec_controller was
        supplied AND we're not in preview mode. Preview is always 100%
        safe/simulated regardless of spec_controller; Run Scan with no
        spec_controller attached behaves exactly like the original
        stub-only version (nothing sent, log line only).

        Returns the raw response from spec_controller.send(), or None
        in preview mode / when no spec_controller is attached. Every
        existing caller predates this return value and simply
        discards it (fire-and-forget), so adding it is safe; flow_get
        below is the first caller that actually uses it.

        The actual spec_controller.send() call is wrapped in the
        module-level _SPEC_SEND_LOCK so that, now that multiple
        independent Runners/threads can legitimately be running at
        once (quick standalone temp/flow/spin actions alongside a
        full scan -- see _other_scan_running in HRDM_spec_gui.py),
        their commands/responses on the single shared SPEC connection
        never interleave. This only serializes the moment of sending
        one command and reading its reply -- it does not make
        concurrent Runners wait on each other for anything else."""
        if self.preview or self.spec_controller is None:
            return None
        self.log(f"    >> sending to SPEC: {cmd}")
        with _SPEC_SEND_LOCK:
            result = self.spec_controller.send(cmd)
        self.log(f"    << SPEC response: {result!r}")
        return result

    # ---- stub hardware / instrument functions ----
    # Each of these still always logs the same human-readable
    # "[stub-name] ..." line as before (so Preview Log and the
    # on-screen log look identical either way); self._send() is the
    # only part that's new, and it's a no-op unless a real
    # spec_controller was passed in and preview=False.

    def te(self, temperature):
        self.log(f"[te] set temperature -> {temperature}")
        self._send(f"te {temperature}")

    def pil_on(self):
        self.log("[pil_on] turning on detector")
        self._send("pil_on")

    def pil_setdir(self, path):
        self.log(f"[pil_setdir] {path}")
        self._send(f'pil_setdir "{path}"')

    def pil_settrig(self, mode):
        self.log(f"[pil_settrig] {mode!r}")
        self._send(f'pil_settrig "{mode}"')

    def umv(self, chi, th, phi):
        self.log(f"[umv] chi {chi} th {th} phi {phi}")
        self._send(f"umv chi {chi} th {th} phi {phi}")

    def opens(self):
        self.log("[opens] shutter open")
        self._send("opens")

    def closes(self):
        self.log("[closes] shutter closed")
        self._send("closes")

    def flyscan(self, motor, start, stop, num_steps, count_time):
        self.log(
            f"[flyscan] {motor} {start} -> {stop}, "
            f"{num_steps} steps, {count_time}s per point"
        )
        # Also show the exact SPEC macro command line this step
        # corresponds to (e.g. `flyscan phi 0 365 3650 0.1`, matching
        # `flyscan phi 0 365 numSteps_ countTime_` in HRDM.mac), plus a
        # plain-language explanation of what it does -- so the log
        # reads like the real macro output, not just a paraphrase.
        self.log(f"    flyscan {motor} {start} {stop} {num_steps} {count_time}")
        self.log(
            f"    -> fly-scans the '{motor}' motor continuously from "
            f"{start} to {stop} degrees, collecting {num_steps} data "
            f"points along the way with {count_time}s of detector "
            f"counting time at each point."
        )
        self._send(f"flyscan {motor} {start} {stop} {num_steps} {count_time}")

    def lup(self, motor, start, stop, num_intervals, count_time):
        """SPEC 'lup' command ("line-up scan"): step-scan `motor` from
        `start` to `stop` over `num_intervals` intervals, counting for
        `count_time` seconds at each point, then return to the
        starting position -- unlike flyscan, this is a stepped (not
        continuous/fly) scan, which is why `run_height_scan` below
        uses "Internal" trigger mode rather than "Mult. Trigger"."""
        self.log(
            f"[lup] {motor} {start} -> {stop}, "
            f"{num_intervals} intervals, {count_time}s per point"
        )
        # Same "show the exact macro command line" treatment as
        # flyscan above (matching `lup samz -0.6 0.6 60 0.2` in
        # HDRMscans_new.mac's heightscan).
        self.log(f"    lup {motor} {start} {stop} {num_intervals} {count_time}")
        self.log(
            f"    -> step-scans the '{motor}' motor from {start} to "
            f"{stop}, stopping at {num_intervals} evenly-spaced points "
            f"along the way and counting for {count_time}s of detector "
            f"time at each one, then returns '{motor}' to its starting "
            f"position."
        )
        self._send(f"lup {motor} {start} {stop} {num_intervals} {count_time}")

    def umv_phi(self, phi):
        """SPEC 'umv phi <value>' -- moves ONLY the phi motor (unlike
        umv() above, which always moves chi/th/phi together). Mirrors
        HDRMscans_new.mac's spin macros, which only ever move phi
        (`umv phi 360` / `umv phi 0`)."""
        self.log(f"[umv] phi {phi}")
        self._send(f"umv phi {phi}")

    def epics_put(self, pv, value):
        """SPEC 'epics_put("<pv>",<value>)' -- writes an EPICS PV
        directly. Mirrors Lakeshore336cryocool.mac's gas-flow/
        temperature-prep macros (prepN2_low, prepN2_medium,
        prepN2_high, roomT, highT, runninghelium, prepswitch, ramp),
        which are themselves just a handful of epics_put() calls on
        LAKESHORE2:* PVs -- see Runner.prepN2_low/_medium/_high,
        Runner.roomT, Runner.highT below, each of which calls this."""
        self.log(f"[epics_put] {pv} = {value}")
        self._send(f'epics_put("{pv}",{value})')

    def flow_set(self, value):
        """SPEC 'flow_set <value>' -- sets the N2/He gas flow rate.
        Referenced throughout HDRMscans_new.mac's warmup/
        warmup_custom/cooldown/hightemp_scan macros but never actually
        DEFINED anywhere in HDRM_scripts/ (not in HDRMscans_new.mac,
        not in Lakeshore336cryocool.mac) -- treated as an external
        hardware stub here, the same way `te` is."""
        self.log(f"[flow_set] -> {value}")
        self._send(f"flow_set {value}")

    def flow_get(self):
        """Reads back the current N2/He gas flow rate.

        The user supplied `flow_get`'s real source, from
        /mnt/home/chess_id4b/Macros/surrena/aalborg_flow.mac:

            def flow_get '{
                local flow
                flow = _flow_get()
                p "flow is currently " flow
            }'

        This explains the exact symptom reported ("SPEC/FOURC showing
        10.02 at the console, but the GUI logging a 'spec response'
        of 1"): `flow_get` is a paren-less `def` macro whose only
        jobs are to call the real underlying function `_flow_get()`,
        stash its result in a `local` (so it's invisible outside the
        macro's own scope -- no global variable to read instead), and
        `p` (print) it to the console. Since `flow_get` itself never
        `return()`s that value, SPEC's CMD_WITH_RETURN transport (used
        for every command sent through this app, regardless of
        syntax -- see SpecController.send) hands back only the
        macro's generic exit/success status, which happens to print
        as `1` -- a completely different thing from the live reading
        printed at the console.

        `_flow_get()` is the fix: it's the actual function with the
        real return value, called with parentheses right there in the
        macro source above, so (unlike the paren-less `flow_get`
        wrapper -- see the historical note below) parentheses are the
        correct, macro-confirmed syntax for this one. Calling it
        directly bypasses the print-only wrapper entirely and should
        get back the same number the console shows.

        Historical note: an earlier revision of this method called
        'flow_get()' (the wrapper, WITH parentheses) on a now-disproved
        theory that parentheses alone would unlock the real value; the
        live SPEC server rejected that with 'Error from server: Syntax
        error on ")"', since `flow_get` really is paren-less. That
        error was about the wrong name, not about parentheses in
        general -- `_flow_get()` is a different, underscore-prefixed
        function that the macro source itself calls with parentheses,
        so this isn't a repeat of that mistake."""
        self.log("[flow_get] reading current gas flow rate")
        result = self._send("_flow_get()")
        if result is not None:
            self.log(f"    -> current flow: {result!r}")
        return result

    def prepN2_low(self, stage_a=None, stage_c=None):
        """Mirrors Lakeshore336cryocool.mac's `prepN2_low` macro
        exactly: epics_put SETP_S1=87, SETP_S3=85 (i.e. Lakeshore
        "Stage A"=87, "Stage C"=85 in the macro's own terms).
        `stage_a`/`stage_c` default to those exact macro values but
        can be overridden (e.g. from the Warmup tab's per-phase Stage
        A/Stage C fields), so a change to the real macro's setpoints
        doesn't require a code change."""
        stage_a = 87 if stage_a is None else stage_a
        stage_c = 85 if stage_c is None else stage_c
        self.log("[prepN2_low] low N2 flow gas prep")
        self.epics_put("LAKESHORE2:SETP_S1", stage_a)
        self.epics_put("LAKESHORE2:SETP_S3", stage_c)

    def prepN2_medium(self, stage_a=None, stage_c=None):
        """Mirrors Lakeshore336cryocool.mac's `prepN2_medium` macro
        exactly: epics_put SETP_S1=130, SETP_S3=110. `stage_a`/
        `stage_c` default to those exact macro values but can be
        overridden -- see prepN2_low's docstring."""
        stage_a = 130 if stage_a is None else stage_a
        stage_c = 110 if stage_c is None else stage_c
        self.log("[prepN2_medium] medium N2 flow gas prep")
        self.epics_put("LAKESHORE2:SETP_S1", stage_a)
        self.epics_put("LAKESHORE2:SETP_S3", stage_c)

    def prepN2_high(self, stage_a=None, stage_c=None):
        """Mirrors Lakeshore336cryocool.mac's `prepN2_high` macro
        exactly: epics_put SETP_S1=165, SETP_S3=160. `stage_a`/
        `stage_c` default to those exact macro values but can be
        overridden -- see prepN2_low's docstring."""
        stage_a = 165 if stage_a is None else stage_a
        stage_c = 160 if stage_c is None else stage_c
        self.log("[prepN2_high] high N2 flow gas prep")
        self.epics_put("LAKESHORE2:SETP_S1", stage_a)
        self.epics_put("LAKESHORE2:SETP_S3", stage_c)

    def prepswitch(self, stage_a=None, stage_c=None):
        """Mirrors Lakeshore336cryocool.mac's `prepswitch` macro
        exactly: epics_put SETP_S1=100, SETP_S3=95 (Lakeshore "Stage
        A"=100, "Stage C"=95). Used to begin switching the gas flow
        from N2 to He (see run_n2_to_he_switch): safe to physically
        switch once the ACTUAL Stage A temperature is above ~90K and
        Stage C is above ~85K. `stage_a`/`stage_c` default to the
        macro's exact values but can be overridden -- see
        prepN2_low's docstring for the same pattern.

        NOTE: an earlier version of this project added an automatic
        `flow_set` call here (not present in the real
        Lakeshore336cryocool.mac `prepswitch` macro, which only ever
        does the two epics_put calls above). Per explicit user
        request, that flow_set call has been removed again --
        prepswitch now matches the real macro exactly, with no gas
        flow side effect. Set the flow rate separately via flow_set/
        the standalone Flow Control if needed."""
        stage_a = 100 if stage_a is None else stage_a
        stage_c = 95 if stage_c is None else stage_c
        self.log("[prepswitch] preparing to switch N2 -> He gas flow")
        self.epics_put("LAKESHORE2:SETP_S1", stage_a)
        self.epics_put("LAKESHORE2:SETP_S3", stage_c)

    def runninghelium(self, stage_a=None, stage_c=None):
        """Mirrors Lakeshore336cryocool.mac's `runninghelium` macro:
        epics_put SETP_S1=30.0, SETP_S3=16 (Lakeshore "Stage A"=30,
        "Stage C"=16 -- confirmed directly against the .mac source),
        setting up the Lakeshore controller for running on Helium once
        the He/N2 valves have been switched by hand (see
        run_n2_to_he_switch). `stage_a`/`stage_c` default to those
        values but can be overridden -- see prepN2_low's docstring for
        the same pattern. The N2 -> He Switch tab's own Step 7 keeps
        the macro-confirmed stage_c=16 default; the Gas Prep tab's own
        runninghelium button overrides this to stage_c=9 per explicit
        user request (see GAS_PREP_MACROS_DEFAULTS' comment)."""
        stage_a = 30 if stage_a is None else stage_a
        stage_c = 16 if stage_c is None else stage_c
        self.log("[runninghelium] running on Helium gas flow")
        self.epics_put("LAKESHORE2:SETP_S1", stage_a)
        self.epics_put("LAKESHORE2:SETP_S3", stage_c)

    def roomT(self, stage_a=None, stage_c=None):
        """Mirrors Lakeshore336cryocool.mac's `roomT` macro exactly:
        epics_put SETP_S1=222, SETP_S3=220. `stage_a`/`stage_c` were
        added so this method takes optional overrides the same way
        prepN2_low/prepN2_medium/prepN2_high/prepswitch/runninghelium
        already do (needed for the Gas Prep Macros tab's editable
        setpoint fields) -- default to the macro's exact values,
        unchanged from before this parameter existed."""
        stage_a = 222 if stage_a is None else stage_a
        stage_c = 220 if stage_c is None else stage_c
        self.log("[roomT] room-temperature gas prep")
        self.epics_put("LAKESHORE2:SETP_S1", stage_a)
        self.epics_put("LAKESHORE2:SETP_S3", stage_c)

    def highT(self, stage_a=None, stage_c=None):
        """Mirrors Lakeshore336cryocool.mac's `highT` macro exactly:
        epics_put SETP_S1=300, SETP_S3=300. Not currently called by
        any other Runner method (HDRMscans_new.mac's own `highT` call
        inside `hightemp_scan` is commented out -- see
        HIGHTEMP_SCAN_DEFAULTS' docstring), but included here for
        completeness/fidelity to Lakeshore336cryocool.mac, and now
        directly runnable from the Gas Prep Macros tab. `stage_a`/
        `stage_c` were added for the same reason as roomT's above --
        optional overrides, defaulting to the macro's exact values."""
        stage_a = 300 if stage_a is None else stage_a
        stage_c = 300 if stage_c is None else stage_c
        self.log("[highT] high-temperature gas prep")
        self.epics_put("LAKESHORE2:SETP_S1", stage_a)
        self.epics_put("LAKESHORE2:SETP_S3", stage_c)

    def run_gas_prep_macro(self, name, params):
        """Dispatches to one of the individual gas-prep macros exposed
        on the Gas Prep tab, by `name` (one of GAS_PREP_MACRO_NAMES).
        `params` is a dict shaped like GAS_PREP_MACROS_DEFAULTS; only
        the keys relevant to `name` are read, the rest are ignored.
        This is a thin dispatcher over the prepN2_low/prepN2_medium/
        prepN2_high/prepswitch/runninghelium/roomT/highT methods
        already defined above -- it doesn't add any new SPEC/EPICS
        behavior of its own, it just gives the GUI's per-macro buttons
        (and tests) one common entry point and one common pair of
        "=== ... ===" log bookends, the same style run_n2_to_he_switch/
        run_warmup use for their own runs."""
        dispatch = {
            "prepN2_low": lambda: self.prepN2_low(
                stage_a=params.get("prepn2_low_stage_a"),
                stage_c=params.get("prepn2_low_stage_c"),
            ),
            "prepN2_medium": lambda: self.prepN2_medium(
                stage_a=params.get("prepn2_medium_stage_a"),
                stage_c=params.get("prepn2_medium_stage_c"),
            ),
            "prepN2_high": lambda: self.prepN2_high(
                stage_a=params.get("prepn2_high_stage_a"),
                stage_c=params.get("prepn2_high_stage_c"),
            ),
            "prepswitch": lambda: self.prepswitch(
                stage_a=params.get("prepswitch_stage_a"),
                stage_c=params.get("prepswitch_stage_c"),
            ),
            "runninghelium": lambda: self.runninghelium(
                stage_a=params.get("runninghelium_stage_a"),
                stage_c=params.get("runninghelium_stage_c"),
            ),
            "roomT": lambda: self.roomT(
                stage_a=params.get("roomt_stage_a"),
                stage_c=params.get("roomt_stage_c"),
            ),
            "highT": lambda: self.highT(
                stage_a=params.get("hight_stage_a"),
                stage_c=params.get("hight_stage_c"),
            ),
        }
        if name not in dispatch:
            raise ValueError(f"Unknown gas prep macro: {name!r}")
        self.log(f"=== GAS PREP MACRO: {name} ===")
        dispatch[name]()
        self.log(f"=== {name} COMPLETE ===")

    def run_gas_prep_flow_set(self, value):
        """Standalone flow_set control on the Gas Prep Macros tab,
        independent of any of the 7 macro buttons above -- just a
        thin wrapper around flow_set() with the same "=== ... ==="
        log bookends as run_gas_prep_macro, so its log entries read
        consistently with the rest of the tab."""
        self.log("=== GAS PREP: flow_set ===")
        self.flow_set(value)
        self.log("=== flow_set COMPLETE ===")

    def run_gas_prep_flow_get(self):
        """Standalone flow_get control on the Gas Prep Macros tab --
        thin wrapper around flow_get() with the same "=== ... ==="
        log bookends as run_gas_prep_macro/run_gas_prep_flow_set.
        Returns whatever flow_get() returns (None in preview mode /
        with no spec_controller attached)."""
        self.log("=== GAS PREP: flow_get ===")
        result = self.flow_get()
        self.log("=== flow_get COMPLETE ===")
        return result

    def run_gas_prep_set_temperature(self, temperature):
        """Standalone "Set Temperature (te)" control on the Gas Prep
        tab, independent of any of the 7 macro buttons -- lets an
        operator send an arbitrary sample temperature (`te`) on its
        own, anywhere in the 10-490K range (enforced by
        validate_gas_prep_macros_params, not here). No
        Lakeshore336cryocool.mac precedent -- a project addition, per
        user request. Thin wrapper around te() with the same
        "=== ... ===" log bookends as run_gas_prep_flow_set/
        run_gas_prep_flow_get."""
        self.log("=== GAS PREP: set temperature (te) ===")
        self.te(_format_temp(temperature))
        self.log("=== set temperature (te) COMPLETE ===")

    # ---- generic standalone Set Temp (te) / Flow Control block ----
    # Shared by the new standalone section added to EVERY scan/
    # temperature tab (Threextal Scan, Height Scan, Powder Scan, Low
    # Temp Scan, Warmup, Warmup Custom, Cooldown, High Temp Scan), per
    # user request -- unlike run_gas_prep_set_temperature/
    # run_gas_prep_flow_set/run_gas_prep_flow_get above (which predate
    # these and are left as-is for the Gas Prep Macros tab specifically),
    # these three take a `label` so every tab's log output names
    # itself (e.g. "Threextal Scan: set temperature (te)") rather than
    # being hard-coded to one tab. Thin wrappers around te()/flow_set()/
    # flow_get(), same "=== ... ===" log-bookend style as every other
    # standalone action in this file. No macro precedent -- project
    # additions, per user request, each independent of any scan/macro
    # on its own tab or any other tab (see HRDM_spec_gui.py's
    # _start_independent_job for how the GUI keeps these out of the
    # global _scan_thread_registry mutual-exclusion lock).

    def run_standalone_set_temperature(self, temperature, label="Standalone"):
        self.log(f"=== {label}: set temperature (te) ===")
        self.te(_format_temp(temperature))
        self.log("=== set temperature (te) COMPLETE ===")

    def run_standalone_flow_set(self, value, label="Standalone"):
        self.log(f"=== {label}: flow_set ===")
        self.flow_set(value)
        self.log("=== flow_set COMPLETE ===")

    def run_standalone_flow_get(self, label="Standalone"):
        self.log(f"=== {label}: flow_get ===")
        result = self.flow_get()
        self.log("=== flow_get COMPLETE ===")
        return result

    def u_mkdir(self, path, parents=False):
        self.log(f"[u mkdir{' -p' if parents else ''}] {path}")
        if self.preview or self.spec_controller is None:
            # No real SPEC connection: fall back to creating the
            # directory locally so preview/demo runs still "do
            # something" visible on disk, same as before this was
            # added.
            try:
                os.makedirs(path, exist_ok=True)
            except OSError as exc:
                self.log(f"    (warning: could not create directory: {exc})")
        else:
            # Real macro's "u mkdir ..." runs on the SPEC server, not
            # the client -- so when actually talking to SPEC, send the
            # real command instead of creating the directory locally.
            self._send(f"u mkdir{' -p' if parents else ''} {path}")

    def sleep(self, seconds, label=""):
        if seconds <= 0:
            return
        self.log(f"[sleep] {seconds}s{' ' + label if label else ''}")
        if self.preview:
            return  # preview mode: log it, but don't actually wait
        # sleep in small increments so cancel requests are responsive
        remaining = float(seconds)
        step = 0.1
        while remaining > 0 and not self.cancelled():
            time.sleep(min(step, remaining))
            remaining -= step

    # ---- main scan logic (== threextalscan / sortmypathout) ----

    def run(self, g, passes):
        mysamplepath = f"raw6M/{g['datafile']}/"
        mysample = g["sample"]
        rampre = g["rampre"]
        myT = _format_temp(g["temperature"])

        if g["datafile"] == DEFAULT_GLOBALS["datafile"]:
            # DEFAULT_GLOBALS["datafile"] is just a placeholder value
            # (it happens to be the literal word "datafile") -- if the
            # field is still sitting at that placeholder when a scan
            # runs, every path built below (both mysamplepath and the
            # per-scan image subfolder, since both come from this same
            # value -- see _pil_file_basename() below) will literally
            # contain "datafile" instead of the real data file name
            # (confirmed by the user: they expected
            # ".../raw6M/test2/.../test2_001" but the folder segment
            # came out as ".../raw6M/datafile/..." because the field
            # hadn't been set to the real name "test2" yet). Warn here
            # rather than silently writing to the wrong folder.
            self.log(
                f"[warning] 'datafile' is still the placeholder value "
                f"{g['datafile']!r} -- set it to the real data file "
                f"name (e.g. via 'Read from SPEC' or by typing it in) "
                f"before running, or every path below will use "
                f"{g['datafile']!r} instead of the real name."
            )

        self.te(myT)
        self.sleep(float(g["wait_seconds"]), label="after setting temperature")
        if self.cancelled():
            self.log("[cancelled] stopping before turning on detector")
            return
        self.pil_on()

        num_steps = g["num_steps"]
        count_time = g["count_time"]

        self.u_mkdir(mysamplepath, parents=True)
        self.u_mkdir(f"{mysamplepath}{mysample}")
        self.u_mkdir(f"{mysamplepath}{mysample}{myT}")

        pilrampath = f"{rampre}{mysamplepath}{mysample}{myT}"
        self.pil_setdir(f"{pilrampath}/")
        self.pil_settrig(g["trig_mode"])

        # SCAN_N mirroring: multi_pilatus_v5.mac's _pil_file_setpath builds
        # each scan's own image subfolder from SPEC's persistent SCAN_N
        # counter (scanpath = sprintf("%s/%s_%03d", PIL[i]["path"],
        # file[num-1], SCAN_N)). We mirror that here with self.scan_n,
        # seeded from the user-editable "next_scan_n" global field.
        # self.scan_n is left on the Runner instance after run() finishes
        # so a caller (GUI) can read back the ending value and, for a real
        # (non-preview) run that actually wrote images to disk, persist it
        # into the "next_scan_n" field for next time. Preview runs also
        # advance self.scan_n the same way (so the log matches what a real
        # run would do), but the caller must NOT write it back to the
        # field for preview -- only a real Run Scan should persist it.
        self.scan_n = int(g["next_scan_n"])
        datafile_basename = _pil_file_basename(g["datafile"])

        for i, p in enumerate(passes, start=1):
            if self.cancelled():
                self.log(f"[cancelled] stopping before pass {i}")
                return
            self.log(f"--- Pass {i}/{len(passes)} ---")
            scanpath = f"{pilrampath}/{datafile_basename}_{self.scan_n:03d}"
            self.log(f"[_pil_scan_head] scan {self.scan_n} images -> {scanpath}")
            self.umv(p["chi"], p["th"], p["phi"])
            self.opens()
            self.sleep(1)
            self.flyscan("phi", p["scan_start"], p["scan_stop"], num_steps, count_time)
            self.sleep(1)
            self.closes()
            self.scan_n += 1

        if not self.cancelled():
            self.umv(g["final_chi"], g["final_th"], g["final_phi"])
            self.log("[done] scan sequence complete")

    # ---- height scan (== heightscan, from HDRMscans_new.mac) ----

    def run_height_scan(self, rampre, start, end, steps, count_time):
        """Mirrors HDRMscans_new.mac's `heightscan` macro: a quick
        check of sample quality/alignment by step-scanning the
        sample-height motor (samz) through the beam. Unlike
        threextalscan/run() above, this does NOT use the per-sample,
        per-temperature directory structure (_mysamplepath / _mysample
        / _myT) -- images always go to a fixed "<rampre>/tiffs/"
        folder instead (matching
        `eval(sprintf("pil_setdir %s/tiffs/",_rampre))` in the macro),
        and the detector trigger mode is switched to "Internal" for
        the duration of this scan only (threextalscan's own trig_mode
        field/dropdown, and whatever it's currently set to, is left
        completely untouched -- this method never reads or writes
        it).

        `rampre` is taken as a plain argument here (not read from a
        `g` dict like run() takes 'rampre' out of `g["rampre"]`)
        because the height scan tab has no per-sample/temperature
        fields of its own -- the caller passes whatever the shared
        Global-parameters 'rampre' field currently holds.

        Note: like the macro's own `sprintf("%s/tiffs/", _rampre)`,
        if `rampre` already ends with "/" (its usual form, e.g.
        "/ramdisk/sarker-4775-a/") this produces a doubled "//" before
        "tiffs" (e.g. ".../sarker-4775-a//tiffs/") -- that's carried
        over unchanged from the original macro rather than "fixed"
        here, and is harmless on POSIX paths (SPEC/the OS both
        collapse repeated slashes)."""
        self.pil_settrig("Internal")
        tiffs_path = f"{rampre}/tiffs/"
        self.pil_setdir(tiffs_path)
        # Unlike threextalscan/run() above, the macro has no sleep(1)
        # calls bracketing opens/lup/closes here -- faithfully
        # translated as-is (no sleeps added).
        self.opens()
        self.lup("samz", start, end, steps, count_time)
        self.closes()
        self.log("[done] height scan complete")

    # ---- powder scan (== powderscan, from HDRMscans_new.mac) ----

    def run_powder_scan(self, g, temperature, wait_seconds, phi_start,
                         phi_end, num_steps, count_time):
        """Mirrors HDRMscans_new.mac's `powderscan <temperature>
        <sleep_time>` macro: a powder-diffraction calibration scan for
        the calibration/powder sample. Like threextalscan/run() above
        (and unlike run_height_scan()), it uses the same per-sample,
        per-temperature directory structure (_mysamplepath / _mysample
        / _myT, built via sortmypathout) -- but instead of
        threextalscan's multi-pass loop over user-editable (chi, th,
        phi, scan_start, scan_stop) rows, it does a single fixed motor
        move (`umv chi 90 th 0 phi 0`, still hard-coded, matching the
        macro exactly -- there's no user-editable field for it) then a
        single flyscan. Unlike the macro's own hard-coded `flyscan phi
        0 360 180 2`, the flyscan's phi start/end, step count, and
        count time ARE user-editable here (passed in as `phi_start`,
        `phi_end`, `num_steps`, `count_time` below, defaulting to
        `POWDERSCAN_DEFAULTS` -- 0/360/180/1) -- a deliberate,
        partial parametrization beyond the macro, so the scan range
        can be tuned per run without hand-editing this file.

        `g` is only used here for the directory-related fields it
        shares with threextalscan (datafile/sample/rampre) -- not for
        `g["temperature"]`/`g["wait_seconds"]`, since the Powder Scan
        tab has its own temperature/wait_seconds fields (passed in as
        the plain `temperature`/`wait_seconds` arguments below,
        mirroring the macro's own "$1"/"$2" call arguments) separate
        from the Threextal Scan tab's Global-parameters fields of the
        same name.

        Note: like the macro (whose own `te $1  #set the temperature
        parameter` line is commented out), this method does NOT call
        self.te() -- `temperature` is only used to build the
        per-temperature output directory, matching the macro exactly.
        Also note all three `u mkdir` calls below pass parents=True
        (matching the macro's `u mkdir -p` on every one of them, unlike
        run()'s first-call-only `-p`)."""
        mysamplepath = f"raw6M/{g['datafile']}/"
        mysample = g["sample"]
        rampre = g["rampre"]
        myT = _format_temp(temperature)

        if g["datafile"] == DEFAULT_GLOBALS["datafile"]:
            self.log(
                f"[warning] 'datafile' is still the placeholder value "
                f"{g['datafile']!r} -- set it to the real data file "
                f"name (e.g. via 'Read from SPEC' or by typing it in) "
                f"before running, or every path below will use "
                f"{g['datafile']!r} instead of the real name."
            )

        self.sleep(float(wait_seconds))
        if self.cancelled():
            self.log("[cancelled] stopping before turning on detector")
            return
        self.pil_on()

        self.u_mkdir(mysamplepath, parents=True)
        self.u_mkdir(f"{mysamplepath}{mysample}", parents=True)
        self.u_mkdir(f"{mysamplepath}{mysample}{myT}", parents=True)

        pilrampath = f"{rampre}{mysamplepath}{mysample}{myT}"
        self.pil_setdir(f"{pilrampath}/")
        self.pil_settrig("Mult. Trigger")

        if self.cancelled():
            self.log("[cancelled] stopping before motor move")
            return

        self.umv(90, 0, 0)
        self.opens()
        self.sleep(1)
        self.flyscan("phi", phi_start, phi_end, num_steps, count_time)
        self.sleep(1)
        self.closes()
        self.log("[done] powder scan complete")

    # ---- sample spinning (== spin_xtal_phi / spin_ice /
    # spin_xtal_phi_10min / spin_xtal_phi_20min, from HDRMscans_new.mac) ----

    def run_spin_xtal_phi(self, num_cycles=None, ice_mode=False):
        """Mirrors HDRMscans_new.mac's `spin_xtal_phi` macro (and,
        with `ice_mode=True`, `spin_ice`): continuously spins the
        sample by moving phi 0 -> 360 -> 0 (1s sleep each way),
        logging a "cycle N completed" line after every full 0->360->0
        cycle, until either `num_cycles` cycles have run or this gets
        cancelled (Stop button / cancel_event).

        Comparing HDRMscans_new.mac's `spin_xtal_phi` and `spin_ice`
        macros side by side, they are the SAME spin loop (identical
        umv/sleep calls) with exactly two differences, both of which
        `ice_mode=True` reproduces here: (1) spin_ice waits 5 extra
        seconds before the first cycle ("Starting in 5 seconds...");
        and (2) every 100 cycles, spin_ice logs a "*** Completed N ice
        spin cycles - motors OK ***" line and pauses 2 more seconds.
        Functionally the sample spins identically either way -- there
        is no difference in how phi actually moves. spin_ice's loop
        bound is also a literal `while (1)` (no fixed cap at all,
        matching spin_xtal_phi's own 10000-cycle cap functioning as
        "keep going until stopped" in practice) rather than a smaller
        number, which is why this method's own default cap (used when
        `num_cycles` is left None/blank) is 10000 for both modes --
        see SPIN_DEFAULTS' docstring.

        `num_cycles` set to a specific number (rather than left blank)
        generalizes spin_xtal_phi_10min (a fixed, non-cancellable
        4-cycle spin in the macro -- its own loop is `for
        (ii=0;ii<4;ii++)`, despite its name and printed messages
        claiming "5-cycle"/"approx 10 minutes") and spin_xtal_phi_20min
        (a fixed 10-cycle spin) into one editable field -- e.g. call
        with num_cycles=4 for the "10 min" preset, num_cycles=10 for
        the "20 min" preset, or any other value for a custom spin
        count. Regardless of `num_cycles`, this method (unlike the
        fixed-cycle macros, which have no Ctrl+C-responsive sleep
        between individual umv calls beyond SPEC's own default
        Ctrl+C handling) is always cancellable mid-spin via
        cancel_event, same as every other Runner method here."""
        if ice_mode:
            self.log(
                "[spin_ice] CONTINUOUS ICE SPINNING (phi 0-360) -- will "
                "spin indefinitely until stopped"
            )
            self.log("[spin_ice] starting in 5 seconds...")
            self.sleep(5, label="ice mode startup delay")
            if self.cancelled():
                self.log("[cancelled] stopped before the first spin cycle")
                return
        else:
            self.log("[spin_xtal_phi] starting sample spin (phi 0<->360)")

        cap = int(num_cycles) if num_cycles else 10000
        ii = 0
        while ii < cap:
            if self.cancelled():
                self.log(f"[cancelled] stopped after {ii} spin cycle(s)")
                return
            self.umv_phi(360)
            self.sleep(1)
            if self.cancelled():
                self.log(f"[cancelled] stopped after {ii} spin cycle(s)")
                return
            self.umv_phi(0)
            self.sleep(1)
            ii += 1
            suffix = f"/{int(num_cycles)}" if num_cycles else ""
            self.log(f"[spin_xtal_phi] cycle {ii}{suffix} completed")
            if ice_mode and ii % 100 == 0:
                self.log(f"*** completed {ii} ice spin cycles -- motors OK ***")
                self.sleep(2)
        self.log(f"[spin_xtal_phi] spin sequence completed ({ii} cycle(s))")

    # ---- shared HDRMscans_new.mac threextalscan step, used by every
    # temperature-series method below (== the LOCAL `threextalscan
    # <temp> <sleep>` macro defined in HDRMscans_new.mac itself --
    # NOT Runner.run() above, which is HRDM.mac's threextalscan; see
    # the long comment above LOW_TEMP_SCAN_DEFAULTS in this file for
    # why these are two different macros with different hard-coded
    # pass angles) ----

    _HDRM_NEW_PASSES = (
        {"chi": "90", "th": "0", "phi": "0"},
        {"chi": "86", "th": "3", "phi": "0"},
        {"chi": "95", "th": "-3", "phi": "0"},
    )
    _HDRM_NEW_NUM_STEPS = "3650"

    def _threextalscan_step(self, g, temperature, sleep_seconds,
                             scan_passes=None, num_steps=None, count_time=None):
        """One HDRM scan at `temperature`, exactly as HDRMscans_new.mac's
        own `threextalscan <temp> <sleep>` macro does it: te(temperature),
        sleep(sleep_seconds), pil_on(), build the per-sample/per-
        temperature directory (from g['datafile']/g['sample']/
        g['rampre']), set Mult. Trigger, then each pass in
        `scan_passes` -- a flyscan phi scan_start->scan_stop over
        `num_steps` steps at `count_time`, finishing with
        umv(90, 0, 0). Advances/reads back self.scan_n the same way
        Runner.run() does, so repeated calls (e.g. once per
        temperature in run_low_temp_scan()) keep numbering scans
        forward rather than restarting at the same number each time.

        `scan_passes`/`num_steps`/`count_time` are optional, trailing
        keyword arguments so every existing caller (and every
        pre-existing test) keeps working unchanged: when left as
        `None`, this falls back to the previous hard-coded behavior --
        `_HDRM_NEW_PASSES` (3 fixed chi/th/phi passes, each flyscanning
        phi 0->365, since those legacy pass dicts have no
        'scan_start'/'scan_stop' keys of their own), `_HDRM_NEW_NUM_STEPS`
        ("3650"), and `g['count_time']` (the Threextal Scan tab's own
        Global-parameters field) respectively. New callers can instead
        pass their own list of pass dicts (each shaped like a Passes-
        table row: chi/th/phi/scan_start/scan_stop -- see
        HDRM_SCAN_PASSES_DEFAULTS) plus their own num_steps/count_time,
        entirely independent of both `_HDRM_NEW_PASSES` and the
        Threextal Scan tab's Global parameters."""
        mysamplepath = f"raw6M/{g['datafile']}/"
        mysample = g["sample"]
        rampre = g["rampre"]
        myT = _format_temp(temperature)
        passes = scan_passes if scan_passes is not None else self._HDRM_NEW_PASSES
        steps = num_steps if num_steps is not None else self._HDRM_NEW_NUM_STEPS
        ct = count_time if count_time is not None else g["count_time"]

        self.te(myT)
        self.sleep(float(sleep_seconds))
        if self.cancelled():
            self.log("[cancelled] stopping before turning on detector")
            return
        self.pil_on()

        self.u_mkdir(mysamplepath, parents=True)
        self.u_mkdir(f"{mysamplepath}{mysample}", parents=True)
        self.u_mkdir(f"{mysamplepath}{mysample}{myT}", parents=True)

        pilrampath = f"{rampre}{mysamplepath}{mysample}{myT}"
        self.pil_setdir(f"{pilrampath}/")
        self.pil_settrig("Mult. Trigger")

        if not hasattr(self, "scan_n"):
            self.scan_n = int(g.get("next_scan_n", 1))
        datafile_basename = _pil_file_basename(g["datafile"])

        num_passes = len(passes)
        for i, p in enumerate(passes, start=1):
            if self.cancelled():
                self.log(f"[cancelled] stopping before pass {i}")
                return
            self.log(f"--- Pass {i}/{num_passes} (HDRM scan @ {myT}K) ---")
            scanpath = f"{pilrampath}/{datafile_basename}_{self.scan_n:03d}"
            self.log(f"[_pil_scan_head] scan {self.scan_n} images -> {scanpath}")
            self.umv(p["chi"], p["th"], p["phi"])
            self.opens()
            self.sleep(1)
            self.flyscan(
                "phi", p.get("scan_start", "0"), p.get("scan_stop", "365"),
                steps, ct,
            )
            self.sleep(1)
            self.closes()
            self.scan_n += 1

        if not self.cancelled():
            self.umv(90, 0, 0)
            self.log(f"[done] HDRM scan at {myT}K complete")

    # ---- N2 -> He gas switch (manual procedure, run before Low Temp
    # Scan -- see N2_TO_HE_SWITCH_DEFAULTS' docstring) ----

    @staticmethod
    def _step_group_enabled(params, key):
        """Shared "is this step-group enabled" check for
        run_n2_to_he_switch's 4 step-groups -- same string-membership
        test run_warmup already uses for its per-phase "enabled" flag,
        for consistency. Missing key defaults to enabled ("1"), so a
        `params` dict built before these flags existed (e.g. an older
        saved script, or a hand-built dict in a test) still runs every
        step exactly like before."""
        return str(params.get(key, "1")) in ("1", "True", "true")

    def run_n2_to_he_switch(self, params):
        """Runs the beamline's manual N2->He gas-switch procedure
        (room temperature down toward base temperature, roughly 300K
        -> 15K), normally executed one command at a time by hand at
        the FOURC prompt -- see N2_TO_HE_SWITCH_DEFAULTS' docstring
        for the full step-by-step breakdown and the reasoning behind
        each setpoint/wait default. `params` is a dict shaped like
        N2_TO_HE_SWITCH_DEFAULTS. One step (turning the He valve on
        and the N2 valve off together) is a physical action that
        can't be automated -- this method only logs a clear
        instruction for the operator at that point, then continues
        once cancelled() isn't set (i.e. the operator hasn't hit
        Stop).

        Each of the 4 step-groups (Steps 1-2, Steps 3-5, Steps 6-8,
        Steps 9-11) can be independently skipped via its own
        "*_enabled" flag in `params` (see N2_TO_HE_SWITCH_DEFAULTS'
        docstring) -- this project's own addition, mirroring
        run_warmup's per-phase "enabled" flag. A skipped group just
        logs one "SKIPPED" line and falls through to the next group;
        it does not affect cancellation, which is still checked after
        every group that actually ran."""
        self.log("=== N2 -> HE GAS SWITCH (room temperature -> base) ===")

        if self._step_group_enabled(params, "step1_enabled"):
            self.log("--- Step 1: prepswitch ---")
            self.prepswitch(
                stage_a=params.get("prepswitch_stage_a"),
                stage_c=params.get("prepswitch_stage_c"),
            )
            self.log(
                "    (safe to switch N2 -> He once Stage A is above ~90K "
                "and Stage C is above ~85K)"
            )
            if self.cancelled():
                self.log("[cancelled] stopped after prepswitch")
                return

            wait1 = float(params.get("wait_after_prepswitch_minutes", 0) or 0)
            if wait1 > 0:
                self.log(
                    f"--- Step 2: waiting {wait1:g} minute(s) for Stage A/"
                    "Stage C to stabilize near ~96K/~87K (verify on the "
                    "sample stage temperature GUI) ---"
                )
                self.sleep(wait1 * 60, label=f"stabilize after prepswitch ({wait1:g} min)")
            if self.cancelled():
                self.log("[cancelled] stopped waiting for prepswitch stabilization")
                return
        else:
            self.log("--- Steps 1-2: SKIPPED (prepswitch disabled) ---")

        if self._step_group_enabled(params, "steps3_5_enabled"):
            self.log("--- Step 3: te ---")
            self.te(_format_temp(params["sample_temp_1"]))
            self.log("--- Step 4: flow_set ---")
            self.flow_set(params["flow_1"])
            if self.cancelled():
                self.log("[cancelled] stopped after te/flow_set")
                return

            wait2 = float(params.get("wait_for_sample_temp_minutes", 0) or 0)
            if wait2 > 0:
                self.log(
                    f"--- Step 5: waiting {wait2:g} minute(s) for the "
                    f"sample to reach {_format_temp(params['sample_temp_1'])}K "
                    "(make sure there is no ice) ---"
                )
                self.sleep(wait2 * 60, label=f"wait for sample temperature ({wait2:g} min)")
            if self.cancelled():
                self.log("[cancelled] stopped waiting for sample temperature")
                return
        else:
            self.log("--- Steps 3-5: SKIPPED (te/flow_set disabled) ---")

        if self._step_group_enabled(params, "step7_enabled"):
            self.log(
                "--- Step 6: MANUAL ACTION REQUIRED -- turn on the Helium "
                "(He) valve and close the Nitrogen (N2) valve TOGETHER, "
                "then continue ---"
            )
            if self.cancelled():
                self.log("[cancelled] stopped before the He/N2 valve switch")
                return

            self.log("--- Step 7: runninghelium ---")
            self.runninghelium(
                stage_a=params.get("runninghelium_stage_a"),
                stage_c=params.get("runninghelium_stage_c"),
            )
            if self.cancelled():
                self.log("[cancelled] stopped after runninghelium")
                return

            wait3 = float(params.get("wait_for_base_temp_minutes", 0) or 0)
            if wait3 > 0:
                self.log(
                    f"--- Step 8: waiting {wait3:g} minute(s) for base "
                    "temperature to stabilize (Stage A ~30K, Stage C "
                    "~16K -- verify on the sample stage temperature "
                    "GUI) ---"
                )
                self.sleep(wait3 * 60, label=f"stabilize at base temperature ({wait3:g} min)")
            if self.cancelled():
                self.log("[cancelled] stopped waiting for base temperature")
                return
        else:
            self.log("--- Steps 6-8: SKIPPED (He/N2 valve switch + runninghelium disabled) ---")

        if self._step_group_enabled(params, "steps8_10_enabled"):
            self.log("--- Step 9: flow_set ---")
            self.flow_set(params["flow_2"])
            self.log("--- Step 10: te ---")
            self.te(_format_temp(params["sample_temp_2"]))
            if self.cancelled():
                self.log("[cancelled] stopped after final te/flow_set")
                return

            self.log("--- Step 11: spin_xtal_phi ---")
            spin_cycles = int(float(params.get("spin_cycles", 0) or 0))
            if spin_cycles > 0:
                self.run_spin_xtal_phi(num_cycles=spin_cycles)
        else:
            self.log("--- Steps 9-11: SKIPPED (final flow_set/te/spin disabled) ---")

        self.log("=== N2 -> HE GAS SWITCH COMPLETED ===")

    def run_n2_to_he_step1(self, params):
        """Runs only Step 1 (prepswitch) and its follow-up wait
        (Step 2) of the N2->He Gas Switch procedure -- see
        N2_TO_HE_SWITCH_DEFAULTS' docstring and run_n2_to_he_switch
        for the full sequence this is a subset of. Exists so an
        operator can send just the initial gas-prep setpoints and
        wait for Stage A/Stage C to climb toward ~96K/~87K, confirm
        that on the sample stage temperature GUI, and only then
        decide whether to continue on to the rest of the procedure --
        rather than being locked into the whole one-click run once
        started. `params` is a dict shaped like
        N2_TO_HE_SWITCH_DEFAULTS (only the prepswitch_stage_a/
        prepswitch_stage_c/wait_after_prepswitch_minutes keys are
        actually used here; the rest are ignored)."""
        self.log("=== N2 -> HE GAS SWITCH: STEP 1 ONLY (prepswitch) ===")
        self.log("--- Step 1: prepswitch ---")
        self.prepswitch(
            stage_a=params.get("prepswitch_stage_a"),
            stage_c=params.get("prepswitch_stage_c"),
        )
        self.log(
            "    (safe to switch N2 -> He once Stage A is above ~90K "
            "and Stage C is above ~85K)"
        )
        if self.cancelled():
            self.log("[cancelled] stopped after prepswitch")
            return

        wait1 = float(params.get("wait_after_prepswitch_minutes", 0) or 0)
        if wait1 > 0:
            self.log(
                f"--- Step 2: waiting {wait1:g} minute(s) for Stage A/"
                "Stage C to stabilize near ~96K/~87K (verify on the "
                "sample stage temperature GUI) ---"
            )
            self.sleep(wait1 * 60, label=f"stabilize after prepswitch ({wait1:g} min)")
        if self.cancelled():
            self.log("[cancelled] stopped waiting for prepswitch stabilization")
            return

        self.log("=== STEP 1 COMPLETE ===")

    def run_n2_to_he_steps_3_to_5(self, params):
        """Runs only Steps 3-5 (te / flow_set / wait for sample
        temperature) of the N2->He Gas Switch procedure -- see
        N2_TO_HE_SWITCH_DEFAULTS' docstring and run_n2_to_he_switch
        for the full sequence this is a subset of. Exists so an
        operator who already ran Step 1 (prepswitch) separately and
        confirmed Stage A/Stage C are ready can move the sample to
        its intermediate temperature and flow rate on its own,
        without also triggering the He/N2 valve-switch instruction or
        runninghelium yet. `params` is a dict shaped like
        N2_TO_HE_SWITCH_DEFAULTS (only the sample_temp_1/flow_1/
        wait_for_sample_temp_minutes keys are actually used here; the
        rest are ignored)."""
        self.log("=== N2 -> HE GAS SWITCH: STEPS 3-5 ONLY (te / flow_set / wait) ===")
        self.log("--- Step 3: te ---")
        self.te(_format_temp(params["sample_temp_1"]))
        self.log("--- Step 4: flow_set ---")
        self.flow_set(params["flow_1"])
        if self.cancelled():
            self.log("[cancelled] stopped after te/flow_set")
            return

        wait2 = float(params.get("wait_for_sample_temp_minutes", 0) or 0)
        if wait2 > 0:
            self.log(
                f"--- Step 5: waiting {wait2:g} minute(s) for the "
                f"sample to reach {_format_temp(params['sample_temp_1'])}K "
                "(make sure there is no ice) ---"
            )
            self.sleep(wait2 * 60, label=f"wait for sample temperature ({wait2:g} min)")
        if self.cancelled():
            self.log("[cancelled] stopped waiting for sample temperature")
            return

        self.log("=== STEPS 3-5 COMPLETE ===")

    def run_n2_to_he_step7(self, params):
        """Runs only Step 6 (the manual He/N2 valve-switch
        instruction), Step 7 (runninghelium), and Step 8 (wait for
        base temperature) of the N2->He Gas Switch procedure -- see
        N2_TO_HE_SWITCH_DEFAULTS' docstring and run_n2_to_he_switch
        for the full sequence this is a subset of. Exists so an
        operator who has already run Step 1 and/or Steps 3-5
        separately, and has now physically switched the He/N2 valves
        by hand, can send just the runninghelium setpoints and its
        wait on their own -- the same "run just this step-group,
        check hardware by hand, then decide what's next" pattern as
        run_n2_to_he_step1 and run_n2_to_he_steps_3_to_5. `params` is
        a dict shaped like N2_TO_HE_SWITCH_DEFAULTS (only the
        runninghelium_stage_a/runninghelium_stage_c/
        wait_for_base_temp_minutes keys are actually used here; the
        rest are ignored). Named "step7" to match the "Step 7:
        runninghelium" GUI section and the step7_enabled flag, even
        though it also covers the Step 6 manual instruction and Step
        8 wait that flag already groups it with inside
        run_n2_to_he_switch."""
        self.log("=== N2 -> HE GAS SWITCH: STEP 7 ONLY (runninghelium) ===")
        self.log(
            "--- Step 6: MANUAL ACTION REQUIRED -- turn on the Helium "
            "(He) valve and close the Nitrogen (N2) valve TOGETHER, "
            "then continue ---"
        )
        if self.cancelled():
            self.log("[cancelled] stopped before the He/N2 valve switch")
            return

        self.log("--- Step 7: runninghelium ---")
        self.runninghelium(
            stage_a=params.get("runninghelium_stage_a"),
            stage_c=params.get("runninghelium_stage_c"),
        )
        if self.cancelled():
            self.log("[cancelled] stopped after runninghelium")
            return

        wait3 = float(params.get("wait_for_base_temp_minutes", 0) or 0)
        if wait3 > 0:
            self.log(
                f"--- Step 8: waiting {wait3:g} minute(s) for base "
                "temperature to stabilize (Stage A ~30K, Stage C "
                "~16K -- verify on the sample stage temperature "
                "GUI) ---"
            )
            self.sleep(wait3 * 60, label=f"stabilize at base temperature ({wait3:g} min)")
        if self.cancelled():
            self.log("[cancelled] stopped waiting for base temperature")
            return

        self.log("=== STEP 7 COMPLETE ===")

    def run_n2_to_he_steps_8_to_10(self, params):
        """Runs only Steps 9-11 (flow_set / te / spin_xtal_phi) of
        the N2->He Gas Switch procedure -- see
        N2_TO_HE_SWITCH_DEFAULTS' docstring and run_n2_to_he_switch
        for the full sequence this is a subset of. Named
        "steps_8_to_10" to match the "Steps 8-10: flow_set / te /
        spin" GUI section and the steps8_10_enabled flag, even though
        the step numbers logged below are 9, 10, and 11 -- a
        pre-existing mismatch between that group's name and its
        actual content (see run_n2_to_he_switch's own step-by-step
        breakdown and N2_TO_HE_SWITCH_DEFAULTS' docstring), not
        something this method's own naming changes. Exists so an
        operator who has already run Step 7 (runninghelium)
        separately and confirmed base temperature is stable can send
        just the final flow_set/te setpoints and spin cycles on their
        own. `params` is a dict shaped like N2_TO_HE_SWITCH_DEFAULTS
        (only the flow_2/sample_temp_2/spin_cycles keys are actually
        used here; the rest are ignored)."""
        self.log("=== N2 -> HE GAS SWITCH: STEPS 8-10 ONLY (flow_set / te / spin) ===")
        self.log("--- Step 9: flow_set ---")
        self.flow_set(params["flow_2"])
        self.log("--- Step 10: te ---")
        self.te(_format_temp(params["sample_temp_2"]))
        if self.cancelled():
            self.log("[cancelled] stopped after final te/flow_set")
            return

        self.log("--- Step 11: spin_xtal_phi ---")
        spin_cycles = int(float(params.get("spin_cycles", 0) or 0))
        if spin_cycles > 0:
            self.run_spin_xtal_phi(num_cycles=spin_cycles)

        self.log("=== STEPS 8-10 COMPLETE ===")

    # ---- low_temp_scan / low_temp_scan_custom (unified: fully
    # parametrized, see LOW_TEMP_SCAN_DEFAULTS' docstring for why a
    # separate "_custom" method/tab isn't needed here -- the two
    # macros' loop bodies are identical, they only differ in which
    # start/end/step values are hard-coded vs. asked for interactively) ----

    def run_low_temp_scan(self, g, start_temp, end_temp, step_temp,
                           spin_cycles, post_temp_wait_seconds,
                           scan_passes=None, num_steps=None, count_time=None):
        """Mirrors HDRMscans_new.mac's `low_temp_scan` macro's ACTUAL
        loop (`for (loopT=start_temp; loopT<end_temp;
        loopT=loopT+step_temp)`), each iteration calling `te loopT`,
        then spin_xtal_phi_10min (here: run_spin_xtal_phi(num_cycles=
        spin_cycles)), then `threextalscan loopT 1` (here:
        _threextalscan_step(), which itself calls te() again --
        faithfully preserved, see _threextalscan_step's docstring).
        Note `te` therefore gets called TWICE per temperature, exactly
        like the real macro (once directly, once inside
        threextalscan). `scan_passes`/`num_steps`/`count_time` are
        optional and forwarded as-is to every _threextalscan_step()
        call -- see that method's docstring for the fallback behavior
        when they're left as `None`."""
        self.log("=== LOW TEMPERATURE SCAN ===")
        self.log(f"Temperature range: {start_temp}K to {end_temp}K (step {step_temp}K)")
        self.log(
            "WARNING: follow beamline manual for N2/He; sample "
            "temperature must be below 80K before running."
        )
        self.sleep(10, label="warning delay (Stop to abort)")
        if self.cancelled():
            self.log("[cancelled] stopped before the first temperature")
            return

        loopT = float(start_temp)
        end_temp_f = float(end_temp)
        step_temp_f = float(step_temp)
        while loopT < end_temp_f:
            if self.cancelled():
                self.log(f"[cancelled] stopping low temp scan at {loopT:g}K")
                return
            self.log(f"=== TEMPERATURE {loopT:g}K ===")
            self.te(_format_temp(loopT))
            self.log(f"Spinning sample ({spin_cycles} cycle(s)) at {loopT:g}K")
            self.run_spin_xtal_phi(num_cycles=int(float(spin_cycles)))
            if self.cancelled():
                self.log(f"[cancelled] stopping low temp scan at {loopT:g}K")
                return
            self.log(f"Starting HDRM scan at {loopT:g}K")
            self._threextalscan_step(
                g, loopT, post_temp_wait_seconds,
                scan_passes=scan_passes, num_steps=num_steps, count_time=count_time,
            )
            self.log(f"Completed temperature {loopT:g}K")
            loopT += step_temp_f

        self.log("=== LOW TEMPERATURE SCAN COMPLETED ===")

    def run_low_temp_sample_setup(self, sample_temp, sample_flow):
        """Standalone "Sample Setup" button on the Low Temp Scan tab
        (see LOW_TEMP_SAMPLE_SETUP_DEFAULTS' docstring): just sends
        `te` then `flow_set`, independent of -- and NOT part of -- the
        automatic Low Temp Scan sequence above or the N2 -> He Gas
        Switch section. Not a sequencing/multi-step method like
        run_low_temp_scan/run_n2_to_he_switch; a thin, single-shot
        wrapper with its own "=== ... ===" log bookends (same style as
        run_gas_prep_macro/run_gas_prep_flow_set), so it can be
        clicked on its own at any time, in any order, relative to the
        rest of this tab."""
        self.log("=== LOW TEMP SCAN: SAMPLE SETUP ===")
        self.te(_format_temp(sample_temp))
        self.flow_set(sample_flow)
        self.log("=== SAMPLE SETUP COMPLETE ===")

    # ---- warmup (3 selectable/parametrized phases) ----

    def run_warmup(self, g, phases, scan_passes=None, num_steps=None,
                   count_time=None, final_te_300=False,
                   final_sample_temp=None, final_sample_flow=None):
        """Mirrors HDRMscans_new.mac's `warmup` macro: 3 phases run in
        sequence, each phase doing its gas prep + initial te/flow_set/
        spin_xtal_phi_20min once, then looping start_temp..end_temp by
        step_temp, each step doing te + (if spin_per_step_cycles > 0)
        a spin_xtal_phi_10min-equivalent spin + a full HDRM scan.
        `phases` is a list of dicts shaped like WARMUP_PHASE_DEFAULTS
        (this project's own addition: each phase can be independently
        skipped via "enabled", every number is editable -- including
        each phase's Lakeshore Stage A/Stage C gas-prep setpoints --
        and the macro itself always runs all 3 with fixed numbers).
        Each phase dict can also independently opt into a
        "room_temp_after_enabled" interlude (off by default) that, if
        checked on, sends a te/flow_set pair (via that phase's own
        "room_temp_after_te"/"room_temp_after_flow", 300K/6 by
        default) immediately after that phase's temperature loop
        finishes and before moving on to the next phase -- see the
        comment above WARMUP_PHASE_DEFAULTS. This is independent of,
        and can be combined freely with, the shared end-of-sequence
        "Phase 4" step described below; execution always continues
        automatically with no pause regardless of which phase/
        interlude checkboxes are enabled.
        One shared `scan_passes`/`num_steps`/`count_time` (optional,
        forwarded as-is to every _threextalscan_step() call across all
        phases -- see that method's docstring for the `None` fallback
        behavior) applies to every phase's HDRM scan, since the macro
        itself never varies the scan step by phase either.
        `final_te_300` (this project's own addition, off by default --
        not part of the real `warmup` macro) optionally runs one final
        "Phase 4" step after every enabled phase has finished, sending
        a sample temperature (`te`, via `final_sample_temp`) and a gas
        flow (`flow_set`, via `final_sample_flow`) to leave the sample
        near room temperature/flow at the end of the sequence. Both
        default to 300K/6 (matching High Temp Scan's own final step)
        when left as `None`, and both are fully editable -- see
        WARMUP_FINAL_STEP_DEFAULTS. The boolean parameter itself keeps
        its original name (`final_te_300`) for backward compatibility
        with existing callers, even though it now also sends
        flow_set."""
        self.log("=== WARMUP SEQUENCE ===")
        self.log(
            "WARNING: ensure temperature channels A, B, C are above 80K."
        )
        self.sleep(10, label="warning delay (Stop to abort)")
        if self.cancelled():
            self.log("[cancelled] stopped before the first phase")
            return

        prep_fns = {
            "low": self.prepN2_low,
            "medium": self.prepN2_medium,
            "high": self.prepN2_high,
        }

        for idx, ph in enumerate(phases, start=1):
            if not (str(ph.get("enabled", "1")) in ("1", "True", "true")):
                self.log(f"--- {ph.get('label', f'Phase {idx}')}: skipped (disabled) ---")
                continue
            if self.cancelled():
                self.log(f"[cancelled] stopping warmup before phase {idx}")
                return

            self.log(f"=== {ph.get('label', f'Phase {idx}')} ===")
            stage_a = ph.get("stage_a")
            stage_c = ph.get("stage_c")
            prep_fns[ph["prep_fn"]](
                stage_a=None if stage_a in (None, "") else stage_a,
                stage_c=None if stage_c in (None, "") else stage_c,
            )
            self.te(_format_temp(ph["initial_temp"]))
            self.flow_set(ph["flow_initial"])
            spin20 = int(float(ph.get("spin20_cycles", 0) or 0))
            if spin20 > 0:
                self.run_spin_xtal_phi(num_cycles=spin20)
            if self.cancelled():
                self.log(f"[cancelled] stopping warmup during phase {idx}")
                return

            loopT = float(ph["start_temp"])
            end_temp_f = float(ph["end_temp"])
            step_temp_f = float(ph["step_temp"])
            spin_per_step = int(float(ph.get("spin_per_step_cycles", 0) or 0))
            while loopT < end_temp_f:
                if self.cancelled():
                    self.log(f"[cancelled] stopping warmup phase {idx} at {loopT:g}K")
                    return
                self.log(f"--- Temperature {loopT:g}K ---")
                self.te(_format_temp(loopT))
                if spin_per_step > 0:
                    self.run_spin_xtal_phi(num_cycles=spin_per_step)
                if self.cancelled():
                    self.log(f"[cancelled] stopping warmup phase {idx} at {loopT:g}K")
                    return
                self._threextalscan_step(
                    g, loopT, 1,
                    scan_passes=scan_passes, num_steps=num_steps, count_time=count_time,
                )
                loopT += step_temp_f

            # Optional per-phase "return to room temp after this
            # phase" interlude (see the comment above
            # WARMUP_PHASE_DEFAULTS) -- off by default, independent of
            # the shared end-of-sequence "Phase 4" step below. When
            # enabled, this always fires immediately after this
            # phase's own temperature loop and always continues
            # automatically into the next phase with no pause, exactly
            # like every other step in this method.
            if str(ph.get("room_temp_after_enabled", "0")) in ("1", "True", "true"):
                rt_temp = ph.get("room_temp_after_te")
                rt_temp = 300 if rt_temp in (None, "") else rt_temp
                rt_flow = ph.get("room_temp_after_flow")
                rt_flow = 6 if rt_flow in (None, "") else rt_flow
                self.log(
                    f"--- Return to Room Temp after {ph.get('label', f'Phase {idx}')}: "
                    f"te {_format_temp(rt_temp)}, flow_set {rt_flow} ---"
                )
                self.te(_format_temp(rt_temp))
                self.flow_set(rt_flow)
                if self.cancelled():
                    self.log(f"[cancelled] stopping warmup after phase {idx}")
                    return

        # Every cancellation check above returns out of run_warmup
        # immediately, so reaching this point always means the whole
        # phase loop ran to completion uninterrupted -- no separate
        # cancelled() check is needed here.
        if final_te_300:
            temp = 300 if final_sample_temp in (None, "") else final_sample_temp
            flow = 6 if final_sample_flow in (None, "") else final_sample_flow
            self.log(
                f"--- Phase 4: te {_format_temp(temp)}, flow_set {flow} ---"
            )
            self.te(_format_temp(temp))
            self.flow_set(flow)

        self.log("=== WARMUP SEQUENCE COMPLETED ===")

    # ---- warmup_custom (single continuous loop, dynamic per-temp gas
    # thresholds -- see WARMUP_CUSTOM_DEFAULTS' docstring for why this
    # stays a separate tab/method from run_warmup() rather than being
    # folded in) ----

    def run_warmup_custom(self, g, start_temp, end_temp, step_temp,
                           spin_cycles, threshold1, flow1, threshold2,
                           flow2, flow3,
                           scan_passes=None, num_steps=None, count_time=None):
        """Mirrors HDRMscans_new.mac's `warmup_custom` macro: a single
        loop from start_temp to end_temp (step_temp), each iteration
        picking low/medium/high N2 flow based on whether loopT <=
        threshold1, <= threshold2, or above (matching the macro's own
        `if (loopT <= 160) ... else if (loopT <= 200) ... else ...`),
        then spinning (spin_xtal_phi_10min-equivalent) and running a
        full HDRM scan at that temperature. `scan_passes`/`num_steps`/
        `count_time` are optional and forwarded as-is to every
        _threextalscan_step() call -- see that method's docstring for
        the fallback behavior when they're left as `None`."""
        self.log("=== CUSTOM WARMUP SEQUENCE ===")
        self.log(
            "WARNING: ensure temperature channels A, B, C are above 80K."
        )
        self.sleep(10, label="warning delay (Stop to abort)")
        if self.cancelled():
            self.log("[cancelled] stopped before the first temperature")
            return

        loopT = float(start_temp)
        end_temp_f = float(end_temp)
        step_temp_f = float(step_temp)
        threshold1_f = float(threshold1)
        threshold2_f = float(threshold2)
        while loopT < end_temp_f:
            if self.cancelled():
                self.log(f"[cancelled] stopping custom warmup at {loopT:g}K")
                return
            self.log(f"=== TEMPERATURE {loopT:g}K ===")
            self.te(_format_temp(loopT))
            if loopT <= threshold1_f:
                self.log(f"Setting low N2 flow for {loopT:g}K")
                self.prepN2_low()
                self.flow_set(flow1)
            elif loopT <= threshold2_f:
                self.log(f"Setting medium N2 flow for {loopT:g}K")
                self.prepN2_medium()
                self.flow_set(flow2)
            else:
                self.log(f"Setting high N2 flow for {loopT:g}K")
                self.prepN2_high()
                self.flow_set(flow3)
            self.log(f"Spinning sample ({spin_cycles} cycle(s)) at {loopT:g}K")
            self.run_spin_xtal_phi(num_cycles=int(float(spin_cycles)))
            if self.cancelled():
                self.log(f"[cancelled] stopping custom warmup at {loopT:g}K")
                return
            self.log(f"Starting HDRM scan at {loopT:g}K")
            self._threextalscan_step(
                g, loopT, 1,
                scan_passes=scan_passes, num_steps=num_steps, count_time=count_time,
            )
            self.log(f"Completed temperature {loopT:g}K")
            loopT += step_temp_f

        self.log("=== CUSTOM WARMUP SEQUENCE COMPLETED ===")

    # ---- cooldown (descending mirror of warmup_custom) ----

    def run_cooldown(self, g, start_temp, end_temp, step_temp,
                      spin_cycles, threshold_high, flow_high,
                      threshold_medium, flow_medium, flow_low,
                      scan_passes=None, num_steps=None, count_time=None):
        """Mirrors HDRMscans_new.mac's `cooldown` macro: a single loop
        DEscending from start_temp to end_temp (step_temp), each
        iteration picking high/medium/low N2 flow based on whether
        loopT >= threshold_high, >= threshold_medium, or below
        (matching the macro's own `if (loopT >= 200) ... else if
        (loopT >= 160) ... else ...`). Unlike every other temperature-
        series method here, the macro's own `cooldown` has no 10s
        warning-delay sleep before it starts -- faithfully, neither
        does this method. `scan_passes`/`num_steps`/`count_time` are
        optional and forwarded as-is to every _threextalscan_step()
        call -- see that method's docstring for the fallback behavior
        when they're left as `None`."""
        self.log("=== COOLDOWN SEQUENCE ===")
        self.log(
            f"Temperature range: {start_temp}K to {end_temp}K "
            f"(step -{step_temp}K)"
        )

        loopT = float(start_temp)
        end_temp_f = float(end_temp)
        step_temp_f = float(step_temp)
        threshold_high_f = float(threshold_high)
        threshold_medium_f = float(threshold_medium)
        while loopT > end_temp_f:
            if self.cancelled():
                self.log(f"[cancelled] stopping cooldown at {loopT:g}K")
                return
            self.log(f"=== TEMPERATURE {loopT:g}K ===")
            self.te(_format_temp(loopT))
            if loopT >= threshold_high_f:
                self.log(f"Setting high N2 flow for {loopT:g}K")
                self.prepN2_high()
                self.flow_set(flow_high)
            elif loopT >= threshold_medium_f:
                self.log(f"Setting medium N2 flow for {loopT:g}K")
                self.prepN2_medium()
                self.flow_set(flow_medium)
            else:
                self.log(f"Setting low N2 flow for {loopT:g}K")
                self.prepN2_low()
                self.flow_set(flow_low)
            self.log(f"Spinning sample ({spin_cycles} cycle(s)) at {loopT:g}K")
            self.run_spin_xtal_phi(num_cycles=int(float(spin_cycles)))
            if self.cancelled():
                self.log(f"[cancelled] stopping cooldown at {loopT:g}K")
                return
            self.log(f"Starting HDRM scan at {loopT:g}K")
            self._threextalscan_step(
                g, loopT, 1,
                scan_passes=scan_passes, num_steps=num_steps, count_time=count_time,
            )
            self.log(f"Completed temperature {loopT:g}K")
            loopT -= step_temp_f

        self.log("=== COOLDOWN SEQUENCE COMPLETED ===")

    # ---- hightemp_scan ----

    def run_hightemp_scan(self, g, start_temp, end_temp, step_temp,
                           scan_wait_seconds, final_temp, final_flow,
                           scan_passes=None, num_steps=None, count_time=None,
                           final_enabled=False):
        """Mirrors HDRMscans_new.mac's `hightemp_scan` macro: Phase 1
        loops start_temp..end_temp (step_temp), each iteration calling
        te() then a full HDRM scan with `scan_wait_seconds` as the
        wait-before-pil_on time (the macro passes 360 here, unlike
        every other temperature-series macro's 1 -- a 6-minute wait,
        preserved faithfully as the default). The macro's own
        `highT`/initial te/flow_set/spin_xtal_phi_20min (before the
        loop) and spin_xtal_phi_10min (inside the loop) are all
        commented out with '#' in the source, so none of those are
        called here either. Phase 2 (uncommented in the macro) sets
        room temperature + a final gas flow + a final te() once the
        loop finishes. `scan_passes`/`num_steps`/`count_time` are
        optional and forwarded as-is to every _threextalscan_step()
        call -- see that method's docstring for the fallback behavior
        when they're left as `None`. `final_enabled` (this project's
        own addition, off by default -- the macro itself always runs
        Phase 2 unconditionally) lets Phase 2 be skipped entirely."""
        self.log("=== HIGH TEMPERATURE SCAN ===")
        self.log(
            "WARNING: ensure temperature channels A, B, C are above 80K."
        )
        self.sleep(10, label="warning delay (Stop to abort)")
        if self.cancelled():
            self.log("[cancelled] stopped before the first temperature")
            return

        self.log(f"--- Phase 1: {start_temp}K to {end_temp}K (step {step_temp}K) ---")
        loopT = float(start_temp)
        end_temp_f = float(end_temp)
        step_temp_f = float(step_temp)
        while loopT < end_temp_f:
            if self.cancelled():
                self.log(f"[cancelled] stopping high temp scan at {loopT:g}K")
                return
            self.log(f"--- Temperature {loopT:g}K ---")
            self.te(_format_temp(loopT))
            self._threextalscan_step(
                g, loopT, scan_wait_seconds,
                scan_passes=scan_passes, num_steps=num_steps, count_time=count_time,
            )
            loopT += step_temp_f

        if self.cancelled():
            self.log("[cancelled] stopping before Phase 2 (return to room temperature)")
            return
        if final_enabled:
            self.log("--- Phase 2: returning to room temperature ---")
            self.roomT()
            self.flow_set(final_flow)
            self.te(_format_temp(final_temp))
        else:
            self.log("--- Phase 2: skipped (disabled) ---")
        self.log("=== HIGH TEMPERATURE SCAN COMPLETED ===")


# ============================================================
# generate_script: build a clean, standalone, runnable Python script
# (as a string) that reproduces the current scan sequence -- same
# stub-function style as HRDM.py, but generated fresh from whatever
# globals/passes are passed in (so it works for any number of passes,
# not just the original three). Used by the GUI's "Python Script" tab
# so the user can review/copy/save real, valid Python -- not just a
# human-readable log line -- before running anything for real.
# ============================================================

def _str_lit(value):
    """Render value as a quoted Python string literal."""
    return repr(str(value))


def _num_lit(value):
    """Render value as a bare Python number literal when possible
    (e.g. '90' -> 90, '0.7' -> 0.7, so generated code reads like real
    values: umv(90, 0.7, 0)) -- falls back to a quoted string literal
    if it isn't actually numeric, so the generated script always
    parses as valid Python either way."""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return repr(value)
    return str(int(f)) if f.is_integer() else str(f)


def generate_script(g, passes):
    """Return a clean, standalone, runnable Python script (as a
    string) that reproduces the scan sequence for the given globals
    and passes -- same stub-function style/output as HRDM.py, but
    generalized to any number of passes. Safe to save as a .py file
    and run directly (the hardware calls are stub prints, just like
    everywhere else in this project)."""
    lines = [
        '#!/usr/bin/env python3',
        '"""',
        'Auto-generated HDRM scan script.',
        '',
        "Generated from the HDRM Scan GUI's current field values -- mirrors",
        'the stub-function style of HRDM.py, and is safe to run as-is (the',
        'hardware calls just print what they would do). Wire up real',
        'hardware by editing the "# TODO" bodies below.',
        '"""',
        '',
        'import os',
        'import time',
        '',
        '',
        'def te(temperature):',
        '    """SPEC \'te\' command: set the temperature setpoint."""',
        '    print(f"[te] set temperature -> {temperature}")',
        '    # TODO: wire up real hardware call',
        '',
        '',
        'def pil_on():',
        '    """SPEC \'pil_on\' command: turn on the Pilatus detector."""',
        '    print("[pil_on] turning on detector")',
        '    # TODO: wire up real hardware call',
        '',
        '',
        'def pil_setdir(path):',
        '    """SPEC \'pil_setdir\' command: set the detector image storage directory."""',
        '    print(f"[pil_setdir] {path}")',
        '    # TODO: wire up real hardware call',
        '',
        '',
        'def pil_settrig(mode):',
        '    """SPEC \'pil_settrig\' command: set the detector trigger mode."""',
        '    print(f"[pil_settrig] {mode!r}")',
        '    # TODO: wire up real hardware call',
        '',
        '',
        'def umv(chi, th, phi):',
        '    """SPEC \'umv\' command: move chi/th/phi and wait until they arrive."""',
        '    print(f"[umv] chi {chi} th {th} phi {phi}")',
        '    # TODO: wire up real hardware call',
        '',
        '',
        'def opens():',
        '    """SPEC \'opens\' command: open the shutter."""',
        '    print("[opens] shutter open")',
        '    # TODO: wire up real hardware call',
        '',
        '',
        'def closes():',
        '    """SPEC \'closes\' command: close the shutter."""',
        '    print("[closes] shutter closed")',
        '    # TODO: wire up real hardware call',
        '',
        '',
        'def flyscan(motor, start, stop, num_steps, count_time):',
        '    """SPEC \'flyscan\' command: fly-scan a motor, collecting detector frames."""',
        '    print(',
        '        f"[flyscan] {motor} {start} -> {stop}, "',
        '        f"{num_steps} steps, {count_time}s per point"',
        '    )',
        '    # TODO: wire up real hardware call',
        '',
        '',
        'def u_mkdir(path, parents=False):',
        '    """SPEC \'u mkdir ...\' shell-out."""',
        '    flag = " -p" if parents else ""',
        '    print(f"[u mkdir{flag}] {path}")',
        '    os.makedirs(path, exist_ok=True)',
        '',
        '',
        'def _pil_file_basename(datafile):',
        '    """Mirrors multi_pilatus_v5.mac\'s _pil_file_setpath: the last',
        '    "/"-separated segment of datafile, used as the per-scan image',
        '    subfolder prefix."""',
        '    trimmed = str(datafile).rstrip("/")',
        '    return trimmed.rsplit("/", 1)[-1] if trimmed else str(datafile)',
        '',
        '',
        'def main():',
        f'    datafile = {_str_lit(g["datafile"])}',
        f'    mysample = {_str_lit(g["sample"])}',
        f'    rampre = {_str_lit(g["rampre"])}',
        f'    myT = {_str_lit(g["temperature"])}',
        f'    wait_seconds = {_num_lit(g["wait_seconds"])}',
        f'    num_steps = {_num_lit(g["num_steps"])}',
        f'    count_time = {_num_lit(g["count_time"])}',
        f'    trig_mode = {_str_lit(g["trig_mode"])}',
        f'    scan_n = {_num_lit(g["next_scan_n"])}',
        '',
        '    mysamplepath = f"raw6M/{datafile}/"',
        '',
        '    te(myT)',
        '    time.sleep(wait_seconds)',
        '    pil_on()',
        '',
        '    u_mkdir(mysamplepath, parents=True)',
        '    u_mkdir(f"{mysamplepath}{mysample}")',
        '    u_mkdir(f"{mysamplepath}{mysample}{myT}")',
        '',
        '    pilrampath = f"{rampre}{mysamplepath}{mysample}{myT}"',
        '    pil_setdir(f"{pilrampath}/")',
        '    pil_settrig(trig_mode)',
        '',
        '    datafile_basename = _pil_file_basename(datafile)',
        '',
    ]

    for i, p in enumerate(passes, start=1):
        lines.append(f'    # Pass {i}/{len(passes)}')
        lines.append(
            '    scanpath = f"{pilrampath}/{datafile_basename}_{scan_n:03d}"'
        )
        lines.append('    print(f"[_pil_scan_head] scan {scan_n} images -> {scanpath}")')
        lines.append(
            f'    umv({_num_lit(p["chi"])}, {_num_lit(p["th"])}, {_num_lit(p["phi"])})'
        )
        lines.append('    opens()')
        lines.append('    time.sleep(1)')
        lines.append(
            f'    flyscan("phi", {_num_lit(p["scan_start"])}, '
            f'{_num_lit(p["scan_stop"])}, num_steps, count_time)'
        )
        lines.append('    time.sleep(1)')
        lines.append('    closes()')
        lines.append('    scan_n += 1')
        lines.append('')

    lines.append(
        f'    umv({_num_lit(g["final_chi"])}, {_num_lit(g["final_th"])}, '
        f'{_num_lit(g["final_phi"])})'
    )
    lines.append('    print("[done] scan sequence complete")')
    lines.append('')
    lines.append('')
    lines.append('if __name__ == "__main__":')
    lines.append('    main()')

    return "\n".join(lines) + "\n"


def _validate_flow_set_range(value, label):
    """Shared 6-18 range check for every `flow_set` value anywhere in
    this file (project addition, per user request -- SPEC's flow_set
    macro itself enforces no range; this is this project's own
    operating-range guard, applied uniformly to every flow_set-backed
    field across every tab so the same limits hold everywhere).
    Raises ValueError (not-a-number, or out of [6, 18]) with a message
    prefixed by `label`; returns the parsed float on success, though
    every current caller just uses this for its side effect (raising)
    the same way the per-field numeric_fields loops above do."""
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{label} must be a number, got {value!r}")
    if not (6 <= parsed <= 18):
        raise ValueError(f"{label} must be between 6 and 18, got {parsed:g}")
    return parsed


def _validate_te_range(value, label):
    """Shared 10-490K range check for every standalone `te` (Set
    Temperature) value anywhere in this file -- same reasoning as
    _validate_flow_set_range above, generalized from the Gas Prep
    Macros tab's own set_temperature_te check so every tab's
    standalone Set Temp control enforces the identical range."""
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{label} must be a number, got {value!r}")
    if not (10 <= parsed <= 490):
        raise ValueError(f"{label} must be between 10 and 490 K, got {parsed:g}")
    return parsed


def validate_globals(g):
    """Raise ValueError with a clear message if a global field is invalid."""
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
    except (KeyError, ValueError):
        raise ValueError(
            f"'next_scan_n' must be a whole number, got {g.get('next_scan_n')!r}"
        )
    if next_scan_n < 0:
        raise ValueError("'next_scan_n' cannot be negative.")


def validate_height_params(h):
    """Raise ValueError with a clear message if a height-scan field is
    invalid -- mirrors validate_globals() above, but for the
    (start, end, steps, count_time) parameters Runner.run_height_scan()
    takes. `h` is a dict with those 4 keys (string values, same as the
    GUI's tk.StringVar-backed fields)."""
    numeric_fields = ["start", "end", "steps", "count_time"]
    for key in numeric_fields:
        try:
            float(h[key])
        except (KeyError, ValueError):
            raise ValueError(
                f"Height scan '{key}' must be a number, got {h.get(key)!r}"
            )
    if float(h["start"]) == float(h["end"]):
        raise ValueError("Height scan start and end cannot be equal.")
    if float(h["steps"]) <= 0:
        raise ValueError("Height scan steps must be positive.")
    if float(h["count_time"]) <= 0:
        raise ValueError("Height scan count time must be positive.")


def validate_powder_params(p):
    """Raise ValueError with a clear message if a powder-scan field is
    invalid -- mirrors validate_height_params() above, but for the
    (temperature, wait_seconds, phi_start, phi_end, num_steps,
    count_time) parameters Runner.run_powder_scan() takes. `p` is a
    dict with those 6 keys (string values, same as the GUI's
    tk.StringVar-backed fields)."""
    numeric_fields = [
        "temperature", "wait_seconds", "phi_start", "phi_end",
        "num_steps", "count_time",
    ]
    for key in numeric_fields:
        try:
            float(p[key])
        except (KeyError, ValueError):
            raise ValueError(
                f"Powder scan '{key}' must be a number, got {p.get(key)!r}"
            )
    if float(p["wait_seconds"]) < 0:
        raise ValueError("Powder scan wait time cannot be negative.")
    if float(p["phi_start"]) == float(p["phi_end"]):
        raise ValueError("Powder scan phi start and end cannot be equal.")
    if float(p["num_steps"]) <= 0:
        raise ValueError("Powder scan steps must be positive.")
    if float(p["count_time"]) <= 0:
        raise ValueError("Powder scan count time must be positive.")


def validate_spin_params(p):
    """Raise ValueError with a clear message if a Spin Control field
    is invalid. `p` is a dict with keys "num_cycles" (may be blank --
    "" means continuous/Stop-button-required) and "ice_mode" (not
    validated here, it's a checkbox)."""
    num_cycles = p.get("num_cycles", "").strip()
    if num_cycles == "":
        return
    try:
        value = float(num_cycles)
    except ValueError:
        raise ValueError(
            f"Spin Control 'num_cycles' must be a whole number or blank "
            f"(blank = continuous), got {num_cycles!r}"
        )
    if value != int(value):
        raise ValueError("Spin Control 'num_cycles' must be a whole number.")
    if value <= 0:
        raise ValueError("Spin Control 'num_cycles' must be positive.")


def validate_n2_to_he_switch_params(p):
    """Raise ValueError with a clear message if an N2->He Switch field
    is invalid. `p` is a dict with the N2_TO_HE_SWITCH_DEFAULTS keys.
    Unlike every other validator here, the three "wait_*_minutes"
    fields are allowed to be 0 (skip that wait entirely) but not
    negative."""
    numeric_fields = [
        "prepswitch_stage_a", "prepswitch_stage_c",
        "wait_after_prepswitch_minutes",
        "sample_temp_1", "flow_1", "wait_for_sample_temp_minutes",
        "runninghelium_stage_a", "runninghelium_stage_c",
        "wait_for_base_temp_minutes",
        "flow_2", "sample_temp_2", "spin_cycles",
    ]
    for key in numeric_fields:
        try:
            float(p[key])
        except (KeyError, ValueError):
            raise ValueError(
                f"N2 -> He Switch '{key}' must be a number, got {p.get(key)!r}"
            )
    for key in (
        "wait_after_prepswitch_minutes", "wait_for_sample_temp_minutes",
        "wait_for_base_temp_minutes",
    ):
        if float(p[key]) < 0:
            raise ValueError(f"N2 -> He Switch '{key}' cannot be negative.")
    if float(p["spin_cycles"]) < 0:
        raise ValueError("N2 -> He Switch 'spin_cycles' cannot be negative.")
    for key in ("flow_1", "flow_2"):
        _validate_flow_set_range(p[key], f"N2 -> He Switch '{key}'")


def validate_gas_prep_macros_params(p):
    """Raise ValueError with a clear message if a Gas Prep Macros tab
    field is invalid. `p` is a dict with the GAS_PREP_MACROS_DEFAULTS
    keys -- every one of them is a plain number (no waits, no
    negative-allowed fields, unlike validate_n2_to_he_switch_params)."""
    numeric_fields = list(GAS_PREP_MACROS_DEFAULTS.keys())
    for key in numeric_fields:
        try:
            float(p[key])
        except (KeyError, ValueError):
            raise ValueError(
                f"Gas Prep Macros '{key}' must be a number, got {p.get(key)!r}"
            )
    _validate_te_range(p["set_temperature_te"], "Gas Prep Macros 'set_temperature_te'")
    _validate_flow_set_range(p["flow_set_value"], "Gas Prep Macros 'flow_set_value'")


def validate_low_temp_params(p):
    """Raise ValueError with a clear message if a Low Temp Scan field
    is invalid. `p` is a dict with the 5 LOW_TEMP_SCAN_DEFAULTS keys."""
    numeric_fields = [
        "start_temp", "end_temp", "step_temp", "spin_cycles",
        "post_temp_wait_seconds",
    ]
    for key in numeric_fields:
        try:
            float(p[key])
        except (KeyError, ValueError):
            raise ValueError(
                f"Low Temp Scan '{key}' must be a number, got {p.get(key)!r}"
            )
    if float(p["start_temp"]) >= float(p["end_temp"]):
        raise ValueError("Low Temp Scan start temperature must be less than end temperature.")
    if float(p["step_temp"]) <= 0:
        raise ValueError("Low Temp Scan temperature step must be positive.")
    if float(p["spin_cycles"]) < 0:
        raise ValueError("Low Temp Scan spin cycles cannot be negative.")
    if float(p["post_temp_wait_seconds"]) < 0:
        raise ValueError("Low Temp Scan wait time cannot be negative.")


def validate_low_temp_sample_setup_params(p):
    """Raise ValueError with a clear message if the Low Temp Scan
    tab's standalone "Sample Setup" fields are invalid. `p` is a dict
    with the 2 LOW_TEMP_SAMPLE_SETUP_DEFAULTS keys."""
    for key in ("sample_temp", "sample_flow"):
        try:
            float(p[key])
        except (KeyError, ValueError):
            raise ValueError(
                f"Low Temp Scan Sample Setup '{key}' must be a number, got {p.get(key)!r}"
            )
    _validate_flow_set_range(p["sample_flow"], "Low Temp Scan Sample Setup 'sample_flow'")


def validate_warmup_final_step_params(p):
    """Raise ValueError with a clear message if Warmup's "Phase 4"
    final-step fields are invalid. `p` is a dict with the 2
    WARMUP_FINAL_STEP_DEFAULTS keys. Validated the same way regardless
    of whether the Phase 4 checkbox is enabled -- so re-enabling it
    later can't silently run with a bad value left over from before,
    matching validate_warmup_phase_params' own disabled-phase
    convention."""
    for key in ("sample_temp", "sample_flow"):
        try:
            float(p[key])
        except (KeyError, ValueError):
            raise ValueError(
                f"Warmup Phase 4 '{key}' must be a number, got {p.get(key)!r}"
            )
    _validate_flow_set_range(p["sample_flow"], "Warmup Phase 4 'sample_flow'")


def validate_warmup_phase_params(phases):
    """Raise ValueError with a clear message if any warmup phase field
    is invalid. `phases` is a list of dicts shaped like
    WARMUP_PHASE_DEFAULTS. Disabled phases (enabled != "1"/"True") are
    still range/type-checked (so re-enabling one later can't silently
    run with a bad value left over from before), but a phase left
    exactly at its own defaults obviously always passes."""
    numeric_fields = [
        "initial_temp", "flow_initial", "spin20_cycles",
        "start_temp", "end_temp", "step_temp", "spin_per_step_cycles",
        "stage_a", "stage_c", "room_temp_after_te", "room_temp_after_flow",
    ]
    for i, ph in enumerate(phases, start=1):
        label = ph.get("label", f"Phase {i}")
        for key in numeric_fields:
            try:
                float(ph[key])
            except (KeyError, ValueError):
                raise ValueError(
                    f"Warmup {label} '{key}' must be a number, got {ph.get(key)!r}"
                )
        if float(ph["start_temp"]) >= float(ph["end_temp"]):
            raise ValueError(
                f"Warmup {label} start temperature must be less than end temperature."
            )
        if float(ph["step_temp"]) <= 0:
            raise ValueError(f"Warmup {label} temperature step must be positive.")
        if float(ph["spin20_cycles"]) < 0:
            raise ValueError(f"Warmup {label} initial spin cycles cannot be negative.")
        if float(ph["spin_per_step_cycles"]) < 0:
            raise ValueError(f"Warmup {label} per-step spin cycles cannot be negative.")
        if ph.get("prep_fn") not in ("low", "medium", "high"):
            raise ValueError(
                f"Warmup {label} 'prep_fn' must be 'low', 'medium', or "
                f"'high', got {ph.get('prep_fn')!r}"
            )
        for key in ("flow_initial", "room_temp_after_flow"):
            _validate_flow_set_range(ph[key], f"Warmup {label} '{key}'")
    if not any(str(ph.get("enabled", "1")) in ("1", "True", "true") for ph in phases):
        raise ValueError("Warmup: at least one phase must be enabled.")


def validate_warmup_custom_params(p):
    """Raise ValueError with a clear message if a Warmup Custom field
    is invalid. `p` is a dict with the 9 WARMUP_CUSTOM_DEFAULTS keys."""
    numeric_fields = [
        "start_temp", "end_temp", "step_temp", "spin_cycles",
        "threshold1", "flow1", "threshold2", "flow2", "flow3",
    ]
    for key in numeric_fields:
        try:
            float(p[key])
        except (KeyError, ValueError):
            raise ValueError(
                f"Warmup Custom '{key}' must be a number, got {p.get(key)!r}"
            )
    if float(p["start_temp"]) >= float(p["end_temp"]):
        raise ValueError("Warmup Custom start temperature must be less than end temperature.")
    if float(p["step_temp"]) <= 0:
        raise ValueError("Warmup Custom temperature step must be positive.")
    if float(p["spin_cycles"]) < 0:
        raise ValueError("Warmup Custom spin cycles cannot be negative.")
    if float(p["threshold1"]) >= float(p["threshold2"]):
        raise ValueError("Warmup Custom threshold1 must be less than threshold2.")
    for key in ("flow1", "flow2", "flow3"):
        _validate_flow_set_range(p[key], f"Warmup Custom '{key}'")


def validate_cooldown_params(p):
    """Raise ValueError with a clear message if a Cooldown field is
    invalid. `p` is a dict with the 9 COOLDOWN_DEFAULTS keys."""
    numeric_fields = [
        "start_temp", "end_temp", "step_temp", "spin_cycles",
        "threshold_high", "flow_high", "threshold_medium", "flow_medium",
        "flow_low",
    ]
    for key in numeric_fields:
        try:
            float(p[key])
        except (KeyError, ValueError):
            raise ValueError(
                f"Cooldown '{key}' must be a number, got {p.get(key)!r}"
            )
    if float(p["start_temp"]) <= float(p["end_temp"]):
        raise ValueError("Cooldown start temperature must be greater than end temperature.")
    if float(p["step_temp"]) <= 0:
        raise ValueError("Cooldown temperature step must be positive.")
    if float(p["spin_cycles"]) < 0:
        raise ValueError("Cooldown spin cycles cannot be negative.")
    if float(p["threshold_high"]) <= float(p["threshold_medium"]):
        raise ValueError("Cooldown threshold_high must be greater than threshold_medium.")
    for key in ("flow_high", "flow_medium", "flow_low"):
        _validate_flow_set_range(p[key], f"Cooldown '{key}'")


def validate_hightemp_params(p):
    """Raise ValueError with a clear message if a High Temp Scan field
    is invalid. `p` is a dict with the 6 HIGHTEMP_SCAN_DEFAULTS keys."""
    numeric_fields = [
        "start_temp", "end_temp", "step_temp", "scan_wait_seconds",
        "final_temp", "final_flow",
    ]
    for key in numeric_fields:
        try:
            float(p[key])
        except (KeyError, ValueError):
            raise ValueError(
                f"High Temp Scan '{key}' must be a number, got {p.get(key)!r}"
            )
    if float(p["start_temp"]) >= float(p["end_temp"]):
        raise ValueError("High Temp Scan start temperature must be less than end temperature.")
    if float(p["step_temp"]) <= 0:
        raise ValueError("High Temp Scan temperature step must be positive.")
    if float(p["scan_wait_seconds"]) < 0:
        raise ValueError("High Temp Scan wait time cannot be negative.")
    _validate_flow_set_range(p["final_flow"], "High Temp Scan 'final_flow'")


def validate_hdrm_scan_params(scan_passes, num_steps, count_time):
    """Raise ValueError with a clear message if the "HDRM Scan
    Parameters" section on a temperature-series tab (Low Temp Scan,
    Warmup, Warmup Custom, Cooldown, High Temp Scan) is invalid --
    mirrors validate_globals()'s per-pass style, but for the editable
    passes table + num_steps + count_time each of those 5 tabs now
    has of its own (see HDRM_SCAN_PASSES_DEFAULTS/HDRM_SCAN_DEFAULTS
    and Runner._threextalscan_step's docstring). `scan_passes` is a
    list of dicts, each shaped like a Passes-table row (chi/th/phi/
    scan_start/scan_stop, string values); `num_steps`/`count_time` are
    the shared flyscan step count / count time for every pass."""
    if not scan_passes:
        raise ValueError("HDRM Scan Parameters: at least one pass is required.")
    for i, p in enumerate(scan_passes, start=1):
        for key in ("chi", "th", "phi", "scan_start", "scan_stop"):
            try:
                float(p[key])
            except (KeyError, ValueError):
                raise ValueError(
                    f"HDRM Scan Parameters pass {i} '{key}' must be a "
                    f"number, got {p.get(key)!r}"
                )
        if float(p["scan_start"]) == float(p["scan_stop"]):
            raise ValueError(
                f"HDRM Scan Parameters pass {i} scan start and scan stop cannot be equal."
            )
    try:
        num_steps_f = float(num_steps)
    except (TypeError, ValueError):
        raise ValueError(
            f"HDRM Scan Parameters 'Number of flyscan steps' must be a "
            f"number, got {num_steps!r}"
        )
    if num_steps_f <= 0:
        raise ValueError("HDRM Scan Parameters 'Number of flyscan steps' must be positive.")
    try:
        count_time_f = float(count_time)
    except (TypeError, ValueError):
        raise ValueError(
            f"HDRM Scan Parameters 'Count time' must be a number, got {count_time!r}"
        )
    if count_time_f <= 0:
        raise ValueError("HDRM Scan Parameters 'Count time' must be positive.")
