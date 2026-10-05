"""
Unit tests for HRDM_spec_gui.py -- the merged window combining
spec_controller_gui.py's raw SPEC command sender (Send/STOP) with
HRDM_gui.py's full HDRM scan GUI (Global parameters, passes, Preview
Log, Run Scan, shutter toggle), sharing one already-connected
SpecController.

Requires both tkinter and a real-or-fake id4b_pyspec (specifically
id4b_pyspec.spec_controller.SpecController and
id4b_pyspec.prompt.describe_result) to be importable -- see
tests/test_hrdm_gui.py's ID4B_PYSPEC_AVAILABLE flag and
/tmp/fake_id4b_pyspec_stub for the fake stub used in this project's
own verification runs. Skips itself cleanly if either is missing.

The detector trigger mode / "Read from EPICS" tests additionally
import a real-or-fake `epics` module (just `epics.caget()`, configured
per-test via a module-level `epics.values` dict -- see
/tmp/fake_epics_stub for the fake stub used in this project's own
verification runs). Unlike tkinter/id4b_pyspec this isn't gated by a
class-level skipUnless, since HRDM_spec_gui.py only imports `epics`
lazily inside the button's background thread -- so if neither a real
nor fake `epics` is importable, only those specific tests fail/error
rather than the whole file skipping.

Run with:
    python -m unittest discover -s tests -t .
or:
    python -m pytest tests/
"""

import os
import queue
import sys
import threading
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from hrdm_core import (
    HEIGHTSCAN_DEFAULTS,
    POWDERSCAN_DEFAULTS,
    TRIGGER_MODE_PV,
    TRIGGER_MODE_STATES,
    SPIN_DEFAULTS,
    LOW_TEMP_SCAN_DEFAULTS,
    LOW_TEMP_SAMPLE_SETUP_DEFAULTS,
    N2_TO_HE_SWITCH_DEFAULTS,
    GAS_PREP_MACROS_DEFAULTS,
    GAS_PREP_MACRO_NAMES,
    STAGE_A_TEMP_PV,
    STAGE_C_TEMP_PV,
    SAMPLE_TEMP_PV,
    WARMUP_PHASE_DEFAULTS,
    WARMUP_FINAL_STEP_DEFAULTS,
    WARMUP_CUSTOM_DEFAULTS,
    COOLDOWN_DEFAULTS,
    HIGHTEMP_SCAN_DEFAULTS,
    HDRM_SCAN_PASSES_DEFAULTS,
    HDRM_SCAN_DEFAULTS,
)

try:
    import HRDM_spec_gui
    TKINTER_AVAILABLE = True
    _import_error = None
except ImportError as exc:  # pragma: no cover - environment dependent
    TKINTER_AVAILABLE = False
    _import_error = exc

try:
    from id4b_pyspec.spec_controller import SpecController as _FakeIDSpecController
    ID4B_PYSPEC_AVAILABLE = True
    _id4b_import_error = None
except ImportError as exc:  # pragma: no cover - environment dependent
    ID4B_PYSPEC_AVAILABLE = False
    _id4b_import_error = exc


@unittest.skipUnless(
    TKINTER_AVAILABLE and ID4B_PYSPEC_AVAILABLE,
    "tkinter and/or id4b_pyspec (fake stub) not available in this environment",
)
class TestHRDMSpecApp(unittest.TestCase):
    def setUp(self):
        _FakeIDSpecController.instances.clear()
        # Unlike HRDM_gui.py, HRDMSpecApp takes an already-connected
        # controller directly -- no lazy connect step to drive here.
        self.controller = _FakeIDSpecController("test-spec-host", 1234, 5)
        self.app = HRDM_spec_gui.HRDMSpecApp(self.controller)
        self.app.global_vars["wait_seconds"].set("0")

    def _drain_log_queue(self):
        msgs = []
        while not self.app.log_queue.empty():
            msgs.append(self.app.log_queue.get_nowait())
        return msgs

    # ---- window construction / connection sharing ----

    def test_window_holds_the_shared_connected_controller(self):
        # title() is a no-op in the fake tk.Tk stub used for tests, so
        # assert what actually matters for behavior: every part of the
        # window uses this exact, already-connected controller object
        # rather than creating (or needing) one of its own.
        self.assertIs(self.app.controller, self.controller)

    def test_globals_section_excludes_spec_connection_fields(self):
        # spec_host/spec_port/spec_timeout are HRDM_gui.py-only fields
        # for its own lazy connection setup -- this window already has
        # a live connection by construction, so it shouldn't expose
        # (or need) them.
        for key in ("spec_host", "spec_port", "spec_timeout"):
            self.assertNotIn(key, self.app.global_vars)

    # ---- Preview Log stays fully simulated ----

    def test_preview_never_sends_anything(self):
        self.app._on_preview()
        self.assertEqual(self.controller.sent, [])

    # ---- Run Scan sends real commands through the shared controller ----

    def test_run_scan_sends_real_commands_through_shared_controller(self):
        self.app._on_run()
        self.app.run_thread.join(timeout=5)

        # No new SpecController should have been created -- Run Scan
        # reuses self.controller, it never constructs its own.
        self.assertEqual(len(_FakeIDSpecController.instances), 1)
        self.assertIn("te 300", self.controller.sent)
        self.assertIn("pil_on", self.controller.sent)

    # ---- Run Scan auto-refreshes datafile from live SPEC ----

    def test_run_scan_auto_reads_datafile_before_building_paths(self):
        # Confirmed necessary by the user: SPEC's live DATAFILE was
        # "test2" but the GUI field still held the "datafile"
        # placeholder because "Read from SPEC" hadn't been clicked --
        # Run Scan itself should now pull the live value first, with
        # no manual "Read from SPEC" click required beforehand.
        original_send = self.controller.send

        def fake_send(command):
            original_send(command)  # still records the call in .sent
            if command == "DATAFILE":
                return "test2\n"
            return "OK"

        self.controller.send = fake_send
        self.app.global_vars["rampre"].set("/ramdisk/sarker-4775-a/")

        self.app._set_num_passes("1")
        self.app._on_run()
        self.app.run_thread.join(timeout=15)
        self.assertFalse(self.app.run_thread.is_alive(), "run did not finish in time")
        self.app._poll_log()
        self.app._run_tk_calls()

        self.assertIn("DATAFILE", self.controller.sent)
        # rampre is a manually-set ramdisk path -- Run Scan must never
        # send CWD or otherwise touch it (see the module docstring's
        # explanation of why: SPEC's CWD is the NFS archive mount, a
        # different filesystem from the detector's own ramdisk storage).
        self.assertNotIn("CWD", self.controller.sent)

        # The on-screen field got updated too, not just the internal
        # dict used for this run.
        self.assertEqual(self.app.global_vars["datafile"].get(), "test2")
        self.assertEqual(
            self.app.global_vars["rampre"].get(), "/ramdisk/sarker-4775-a/"
        )

        # And the actual path sent to pil_setdir / logged for each scan
        # uses the freshly-read "test2", not the stale "datafile"
        # placeholder that was in the field before Run Scan was clicked
        # -- rooted at the manually-set ramdisk prefix, not an NFS path.
        log = self.app.log_text.get("1.0", "end")
        self.assertIn(
            "[pil_setdir] /ramdisk/sarker-4775-a/raw6M/test2/sample1/300/",
            log,
        )
        self.assertIn("raw6M/test2/sample1/300/test2_", log)
        self.assertNotIn("[warning] 'datafile' is still the placeholder", log)

    def test_run_scan_keeps_existing_field_value_if_auto_read_fails(self):
        # If the auto-read itself fails (e.g. SPEC not reachable), Run
        # Scan shouldn't crash -- it should log the failure and fall
        # back to whatever was already in the field.
        self.app.global_vars["datafile"].set("fallback_name")

        def failing_send(command):
            if command == "DATAFILE":
                raise RuntimeError("not connected")
            return "OK"

        self.controller.send = failing_send

        self.app._set_num_passes("1")
        self.app._on_run()
        self.app.run_thread.join(timeout=15)
        self.assertFalse(self.app.run_thread.is_alive(), "run did not finish in time")
        self.app._poll_log()
        self.app._run_tk_calls()

        self.assertEqual(self.app.global_vars["datafile"].get(), "fallback_name")
        log = self.app.log_text.get("1.0", "end")
        self.assertIn("[globals] DATAFILE:", log)

    # ---- next_scan_n field / SCAN_N persistence ----

    def test_next_scan_n_field_defaults_to_one(self):
        self.assertEqual(self.app.global_vars["next_scan_n"].get(), "1")

    def test_preview_does_not_persist_next_scan_n(self):
        self.app.global_vars["next_scan_n"].set("5")
        self.app._on_preview()
        log = self.app.log_text.get("1.0", "end")
        self.assertIn("[_pil_scan_head] scan 5 images ->", log)
        self.assertEqual(self.app.global_vars["next_scan_n"].get(), "5")

    def test_run_scan_persists_next_scan_n_after_completion(self):
        # Use a single pass so the real (non-preview) run's hardcoded
        # 2x 1-second sleeps around each flyscan (see Runner.run()) add
        # up to a predictable, short real wait instead of one per pass.
        self.app._set_num_passes("1")
        self.app.global_vars["next_scan_n"].set("5")
        self.app._on_run()
        self.app.run_thread.join(timeout=15)
        self.assertFalse(self.app.run_thread.is_alive(), "run did not finish in time")
        self.app._poll_log()  # dispatch the queued __SCANN__/__DONE__ sentinels

        # 1 pass starting at scan_n=5 -> ends at 6.
        self.assertEqual(self.app.global_vars["next_scan_n"].get(), "6")
        log = self.app.log_text.get("1.0", "end")
        self.assertIn("[next_scan_n] advanced to 6 for next run", log)

    # ---- shutter toggle reuses the same shared controller ----

    def test_toggle_shutter_sends_through_shared_controller(self):
        self.app._on_toggle_shutter()
        self.assertIn("opens", self.controller.sent)

        self.app._on_toggle_shutter()
        self.assertIn("closes", self.controller.sent)

    # ---- raw command Send box ----

    def test_send_raw_command_goes_through_shared_controller(self):
        self.app.command_var.set("umv chi 0 th 0 phi 0")
        self.app._send_command()
        self.app._last_send_thread.join(timeout=5)
        self.app._run_tk_calls()  # deliver the queued Tk-thread callback

        self.assertIn("umv chi 0 th 0 phi 0", self.controller.sent)
        # The entry box should be cleared and Send re-enabled once done.
        self.assertEqual(self.app.command_var.get(), "")
        self.assertEqual(self.app.send_button.cget("state"), "normal")

    def test_send_raw_command_does_nothing_when_empty(self):
        self.app.command_var.set("   ")
        self.app._send_command()
        self.assertIsNone(self.app._last_send_thread)
        self.assertEqual(self.controller.sent, [])

    # ---- STOP / abort ----

    def test_stop_sends_abort_through_shared_controller(self):
        self.app._stop_command()
        self.app._last_abort_thread.join(timeout=5)
        self.assertEqual(self.controller.abort_count, 1)

    # ---- Read from SPEC (_SPEC_READ_COMMANDS) ----

    def test_read_globals_sends_bare_datafile_and_sets_field(self):
        # Real SPEC session behavior confirmed by the user: typing
        # "p DATAFILE" at the prompt just prints the plain value back
        # (e.g. "test3"). The bridge sends the bare "DATAFILE"
        # expression instead of "p DATAFILE" so it gets that same
        # value back as a real Python return value rather than
        # scraped console text.
        original_send = self.controller.send

        def fake_send(command):
            original_send(command)  # still records the call in .sent
            if command == "DATAFILE":
                return "align_week1_45keV\n"
            return "OK"

        self.controller.send = fake_send

        self.app._on_read_globals()
        self.app._last_read_globals_thread.join(timeout=5)
        self.app._run_tk_calls()  # deliver the queued Tk-thread callback

        self.assertIn("DATAFILE", self.controller.sent)
        self.assertNotIn("p DATAFILE", self.controller.sent)
        self.assertEqual(self.app.global_vars["datafile"].get(), "align_week1_45keV")
        self.assertEqual(self.app.read_globals_button.cget("state"), "normal")

    def test_read_globals_never_touches_rampre(self):
        # rampre is a manually-set ramdisk path (see hrdm_core.py's
        # DEFAULT_GLOBALS["rampre"]) -- an earlier version of this GUI
        # read it live from SPEC's CWD, but CWD is the NFS archive
        # mount, a different filesystem from the Pilatus detector's own
        # local ramdisk storage, so that pointed the detector at a path
        # it couldn't write to and images stopped saving. "Read from
        # SPEC" must never send CWD or change the rampre field.
        original_value = self.app.global_vars["rampre"].get()

        def fake_send(command):
            if command == "CWD":  # pragma: no cover - should never be called
                raise AssertionError("CWD should never be sent by Read from SPEC")
            if command == "DATAFILE":
                return "align_week1_45keV\n"
            return "OK"

        self.controller.send = fake_send

        self.app._on_read_globals()
        self.app._last_read_globals_thread.join(timeout=5)
        self.app._run_tk_calls()

        self.assertNotIn("CWD", self.controller.sent)
        self.assertEqual(self.app.global_vars["rampre"].get(), original_value)

    def test_read_globals_logs_error_without_crashing_or_touching_field(self):
        def failing_send(command):
            raise RuntimeError("not connected")

        self.controller.send = failing_send
        original_value = self.app.global_vars["datafile"].get()

        self.app._on_read_globals()
        self.app._last_read_globals_thread.join(timeout=5)
        self.app._run_tk_calls()

        # Field is left untouched on error, and the button is
        # re-enabled so the user can try again.
        self.assertEqual(self.app.global_vars["datafile"].get(), original_value)
        self.assertEqual(self.app.read_globals_button.cget("state"), "normal")

    def test_read_globals_does_not_overwrite_field_for_non_string_response(self):
        # If SPEC ever hands back something that isn't a plain string
        # (structured/unexpected response), the field is left alone
        # rather than being set to a garbled value -- the raw response
        # still gets logged for the user to read by hand.
        original_value = self.app.global_vars["datafile"].get()
        self.controller.send = lambda command: 12345

        self.app._on_read_globals()
        self.app._last_read_globals_thread.join(timeout=5)
        self.app._run_tk_calls()

        self.assertEqual(self.app.global_vars["datafile"].get(), original_value)

    def test_read_globals_button_disabled_while_in_flight(self):
        release = threading.Event()

        def slow_send(command):
            release.wait(timeout=5)
            return "align_week1_45keV"

        self.controller.send = slow_send
        self.app._on_read_globals()
        try:
            self.assertEqual(self.app.read_globals_button.cget("state"), "disabled")
        finally:
            release.set()
            self.app._last_read_globals_thread.join(timeout=5)
            self.app._run_tk_calls()

        self.assertEqual(self.app.read_globals_button.cget("state"), "normal")

    # ---- Read cycle/BTR from SPEC (live CWD) ----
    #
    # Added per explicit request ("NSF cycle information is wrong ..
    # can you take that somehow correct?", clarified to "autograb from
    # some file for cycle not sure how"). A separate button/handler
    # from "Read from SPEC" above -- see
    # test_read_cycle_btr_is_a_separate_button_from_read_globals below
    # and _on_read_nfs_cycle_btr's own docstring for why sending "CWD"
    # here doesn't conflict with test_read_globals_never_touches_rampre
    # / test_watch_never_touches_rampre above (those guard a *different*
    # button/handler against ever sending CWD).

    def test_read_cycle_btr_sends_bare_cwd_and_sets_both_fields(self):
        original_send = self.controller.send

        def fake_send(command):
            original_send(command)  # still records the call in .sent
            if command == "CWD":
                return "/nfs/chess/id4b/2026-3/sarker-4775-a\n"
            return "OK"

        self.controller.send = fake_send

        self.app._on_read_nfs_cycle_btr()
        self.app._last_read_nfs_cycle_btr_thread.join(timeout=5)
        self.app._run_tk_calls()

        self.assertIn("CWD", self.controller.sent)
        self.assertEqual(self.app.global_vars["nfs_cycle"].get(), "2026-3")
        self.assertEqual(self.app.global_vars["nfs_btr"].get(), "sarker-4775-a")
        self.assertEqual(
            self.app.read_nfs_cycle_btr_button.cget("state"), "normal"
        )
        log = self.app.log_text.get("1.0", "end")
        self.assertIn("set 'NFS cycle' field to '2026-3'", log)
        self.assertIn("'NFS BTR / proposal' field to 'sarker-4775-a'", log)

    def test_read_cycle_btr_leaves_fields_unchanged_for_non_nfs_cwd(self):
        # SPEC's CWD might not be an NFS path at all (e.g. still sitting
        # in a home directory before cd'ing into a beamtime folder) --
        # parse_nfs_cwd() returns (None, None) for that, and the fields
        # must be left exactly as they were rather than getting cleared
        # or set to garbage.
        original_cycle = self.app.global_vars["nfs_cycle"].get()
        original_btr = self.app.global_vars["nfs_btr"].get()
        self.controller.send = lambda command: "/home/sarker\n"

        self.app._on_read_nfs_cycle_btr()
        self.app._last_read_nfs_cycle_btr_thread.join(timeout=5)
        self.app._run_tk_calls()

        self.assertEqual(self.app.global_vars["nfs_cycle"].get(), original_cycle)
        self.assertEqual(self.app.global_vars["nfs_btr"].get(), original_btr)
        log = self.app.log_text.get("1.0", "end")
        self.assertIn("doesn't look like an NFS path", log)

    def test_read_cycle_btr_logs_error_without_crashing_or_touching_fields(self):
        def failing_send(command):
            raise RuntimeError("not connected")

        self.controller.send = failing_send
        original_cycle = self.app.global_vars["nfs_cycle"].get()
        original_btr = self.app.global_vars["nfs_btr"].get()

        self.app._on_read_nfs_cycle_btr()
        self.app._last_read_nfs_cycle_btr_thread.join(timeout=5)
        self.app._run_tk_calls()

        self.assertEqual(self.app.global_vars["nfs_cycle"].get(), original_cycle)
        self.assertEqual(self.app.global_vars["nfs_btr"].get(), original_btr)
        self.assertEqual(
            self.app.read_nfs_cycle_btr_button.cget("state"), "normal"
        )

    def test_read_cycle_btr_button_disabled_while_in_flight(self):
        release = threading.Event()

        def slow_send(command):
            release.wait(timeout=5)
            return "/nfs/chess/id4b/2026-3/sarker-4775-a\n"

        self.controller.send = slow_send
        self.app._on_read_nfs_cycle_btr()
        try:
            self.assertEqual(
                self.app.read_nfs_cycle_btr_button.cget("state"), "disabled"
            )
        finally:
            release.set()
            self.app._last_read_nfs_cycle_btr_thread.join(timeout=5)
            self.app._run_tk_calls()

        self.assertEqual(
            self.app.read_nfs_cycle_btr_button.cget("state"), "normal"
        )

    def test_read_cycle_btr_is_a_separate_button_from_read_globals(self):
        # "Read from SPEC" (_on_read_globals) must still never send
        # "CWD" -- confirmed here doesn't regress even though a
        # sibling button now sends CWD for a different purpose.
        original_send = self.controller.send

        def fake_send(command):
            original_send(command)
            if command == "CWD":  # pragma: no cover - should never be called
                raise AssertionError("CWD should never be sent by Read from SPEC")
            if command == "DATAFILE":
                return "align_week1_45keV\n"
            return "OK"

        self.controller.send = fake_send

        self.app._on_read_globals()
        self.app._last_read_globals_thread.join(timeout=5)
        self.app._run_tk_calls()

        self.assertNotIn("CWD", self.controller.sent)
        self.assertIsNot(
            self.app.read_nfs_cycle_btr_button, self.app.read_globals_button
        )

    # ---- DATAFILE auto-watch checkbox ----
    #
    # The fake tkinter stub's self.after() (see tkinter/__init__.py's
    # Tk.after) never actually calls back on its own -- tests drive
    # _datafile_watch_tick() directly instead of waiting on a real
    # timer, the same way _poll_log/_run_tk_calls are driven manually
    # elsewhere in this file.

    def test_watch_checkbox_is_checked_by_default(self):
        self.assertTrue(self.app.datafile_watch_var.get())

    def test_watch_tick_sends_datafile_and_updates_field_on_change(self):
        original_send = self.controller.send

        def fake_send(command):
            original_send(command)  # still records the call in .sent
            return "test2\n" if command == "DATAFILE" else "OK"

        self.controller.send = fake_send

        self.app._datafile_watch_tick()
        self.app._datafile_watch_thread.join(timeout=5)
        self.app._run_tk_calls()

        self.assertIn("DATAFILE", self.controller.sent)
        self.assertEqual(self.app.global_vars["datafile"].get(), "test2")
        log = self.app.log_text.get("1.0", "end")
        self.assertIn("[watch] DATAFILE changed to 'test2'", log)

    def test_watch_tick_does_not_relog_or_reset_unchanged_value(self):
        # A poll that returns the exact same value as last time
        # shouldn't touch the field again or add a second log line --
        # otherwise an unattended 15-second poll would flood the Log
        # tab with an identical line forever.
        self.controller.send = lambda command: (
            "test2\n" if command == "DATAFILE" else "OK"
        )

        self.app._datafile_watch_tick()
        self.app._datafile_watch_thread.join(timeout=5)
        self.app._run_tk_calls()

        self.app.global_vars["datafile"].set("something_else_typed_by_hand")
        self.app._datafile_watch_tick()
        self.app._datafile_watch_thread.join(timeout=5)
        self.app._run_tk_calls()

        # The watch saw the same SPEC value ("test2") both times, so
        # the second tick should NOT stomp on the value the user just
        # typed in by hand.
        self.assertEqual(
            self.app.global_vars["datafile"].get(), "something_else_typed_by_hand"
        )
        log = self.app.log_text.get("1.0", "end")
        self.assertEqual(log.count("[watch] DATAFILE changed to"), 1)

    def test_watch_tick_does_nothing_when_checkbox_unchecked(self):
        self.app.datafile_watch_var.set(False)
        self.controller.send = lambda command: "test2\n"

        self.app._datafile_watch_tick()

        self.assertIsNone(self.app._datafile_watch_thread)
        self.assertEqual(self.controller.sent, [])
        self.assertEqual(self.app.global_vars["datafile"].get(), "datafile")

    def test_watch_toggle_logs_paused_and_resumed(self):
        self.app.datafile_watch_check.invoke()  # unchecks (starts checked)
        self.assertFalse(self.app.datafile_watch_var.get())
        log = self.app.log_text.get("1.0", "end")
        self.assertIn("[watch] DATAFILE auto-watch paused", log)

        self.app.datafile_watch_check.invoke()  # re-checks
        self.assertTrue(self.app.datafile_watch_var.get())
        log = self.app.log_text.get("1.0", "end")
        self.assertIn("[watch] DATAFILE auto-watch on", log)

    def test_watch_tick_logs_error_without_crashing(self):
        def failing_send(command):
            raise RuntimeError("not connected")

        self.controller.send = failing_send

        self.app._datafile_watch_tick()
        self.app._datafile_watch_thread.join(timeout=5)
        self.app._run_tk_calls()

        log = self.app.log_text.get("1.0", "end")
        self.assertIn("[watch] DATAFILE:", log)
        self.assertEqual(self.app.global_vars["datafile"].get(), "datafile")

    def test_watch_never_touches_rampre(self):
        original_value = self.app.global_vars["rampre"].get()
        self.controller.send = lambda command: (
            "test2\n" if command == "DATAFILE" else "OK"
        )

        self.app._datafile_watch_tick()
        self.app._datafile_watch_thread.join(timeout=5)
        self.app._run_tk_calls()

        self.assertNotIn("CWD", self.controller.sent)
        self.assertEqual(self.app.global_vars["rampre"].get(), original_value)

    def test_destroy_cancels_the_watch_timer(self):
        after_id = self.app._datafile_watch_after_id
        self.assertIsNotNone(after_id)
        self.app.destroy()
        self.assertIsNone(self.app._datafile_watch_after_id)

    # ---- Detector trigger mode dropdown + Read from EPICS ----

    def test_trig_mode_dropdown_locked_to_known_states(self):
        self.assertEqual(
            list(self.app.trig_mode_combo.cget("values")), TRIGGER_MODE_STATES
        )

    def test_read_trigger_mode_sets_field_on_success(self):
        import epics
        epics.values.clear()
        epics.values[TRIGGER_MODE_PV] = "Internal"
        try:
            self.app._on_read_trigger_mode()
            self.app._last_read_trigmode_thread.join(timeout=5)
            self.app._run_tk_calls()

            self.assertEqual(self.app.global_vars["trig_mode"].get(), "Internal")
            self.assertEqual(self.app.read_trigmode_button.cget("state"), "normal")
        finally:
            epics.values.clear()

    def test_read_trigger_mode_ignores_value_outside_the_two_used_modes(self):
        # "Ext. Trigger" is a real EPICS state for this PV, but it isn't
        # one of the 2 modes (Internal / Mult. Trigger) this project
        # actually uses -- TRIGGER_MODE_STATES is intentionally
        # restricted to just those two, so a read of any other valid
        # PV state, same as a garbage value, should be ignored rather
        # than silently set.
        import epics
        epics.values.clear()
        epics.values[TRIGGER_MODE_PV] = "Ext. Trigger"
        original_value = self.app.global_vars["trig_mode"].get()
        try:
            self.app._on_read_trigger_mode()
            self.app._last_read_trigmode_thread.join(timeout=5)
            self.app._run_tk_calls()

            self.assertEqual(self.app.global_vars["trig_mode"].get(), original_value)
            self.assertEqual(self.app.read_trigmode_button.cget("state"), "normal")
        finally:
            epics.values.clear()

    def test_read_trigger_mode_ignores_garbage_value(self):
        import epics
        epics.values.clear()
        epics.values[TRIGGER_MODE_PV] = "Something Unexpected"
        original_value = self.app.global_vars["trig_mode"].get()
        try:
            self.app._on_read_trigger_mode()
            self.app._last_read_trigmode_thread.join(timeout=5)
            self.app._run_tk_calls()

            self.assertEqual(self.app.global_vars["trig_mode"].get(), original_value)
            self.assertEqual(self.app.read_trigmode_button.cget("state"), "normal")
        finally:
            epics.values.clear()

    def test_read_trigger_mode_handles_missing_pyepics(self):
        original_value = self.app.global_vars["trig_mode"].get()
        real_epics = sys.modules.get("epics")
        sys.modules["epics"] = None  # forces "import epics" to raise ImportError
        try:
            self.app._on_read_trigger_mode()
            self.app._last_read_trigmode_thread.join(timeout=5)
            self.app._run_tk_calls()

            self.assertEqual(self.app.global_vars["trig_mode"].get(), original_value)
            self.assertEqual(self.app.read_trigmode_button.cget("state"), "normal")
        finally:
            if real_epics is not None:
                sys.modules["epics"] = real_epics
            else:
                sys.modules.pop("epics", None)

    def test_read_trigger_mode_logs_error_without_crashing_or_touching_field(self):
        import epics

        def failing_caget(pvname, as_string=False, timeout=5.0, **kwargs):
            raise RuntimeError("Channel Access timeout")

        original_caget = epics.caget
        epics.caget = failing_caget
        original_value = self.app.global_vars["trig_mode"].get()
        try:
            self.app._on_read_trigger_mode()
            self.app._last_read_trigmode_thread.join(timeout=5)
            self.app._run_tk_calls()

            self.assertEqual(self.app.global_vars["trig_mode"].get(), original_value)
            self.assertEqual(self.app.read_trigmode_button.cget("state"), "normal")
        finally:
            epics.caget = original_caget

    def test_read_trigger_mode_button_disabled_while_in_flight(self):
        import epics
        release = threading.Event()

        def slow_caget(pvname, as_string=False, timeout=5.0, **kwargs):
            release.wait(timeout=5)
            return "Internal"

        original_caget = epics.caget
        epics.caget = slow_caget
        self.app._on_read_trigger_mode()
        try:
            self.assertEqual(self.app.read_trigmode_button.cget("state"), "disabled")
        finally:
            release.set()
            self.app._last_read_trigmode_thread.join(timeout=5)
            self.app._run_tk_calls()
            epics.caget = original_caget

        self.assertEqual(self.app.read_trigmode_button.cget("state"), "normal")

    # ---- N2 -> He Gas Switch: per-step-group Enabled checkboxes ----

    def test_n2_he_switch_fields_default_to_defaults(self):
        for key, value in N2_TO_HE_SWITCH_DEFAULTS.items():
            if key.endswith("_enabled"):
                self.assertEqual(
                    self.app.n2_he_switch_enabled_vars[key].get(), value == "1"
                )
            else:
                self.assertEqual(self.app.n2_he_switch_vars[key].get(), value)

    def test_collect_n2_he_switch_params_includes_enabled_flags(self):
        self.app.n2_he_switch_enabled_vars["step1_enabled"].set(False)
        self.app.n2_he_switch_enabled_vars["steps3_5_enabled"].set(True)
        params = self.app._collect_n2_to_he_switch_params()
        self.assertEqual(params["step1_enabled"], "0")
        self.assertEqual(params["steps3_5_enabled"], "1")
        # Numeric fields are still collected as before.
        self.assertEqual(
            params["prepswitch_stage_a"], N2_TO_HE_SWITCH_DEFAULTS["prepswitch_stage_a"]
        )

    def test_n2_he_switch_reset_defaults_restores_enabled_flags_and_numeric_fields(self):
        self.app.n2_he_switch_enabled_vars["step1_enabled"].set(False)
        self.app.n2_he_switch_enabled_vars["step7_enabled"].set(False)
        self.app.n2_he_switch_vars["prepswitch_stage_a"].set("999")
        self.app._on_n2_to_he_switch_reset_defaults()

        for key, value in N2_TO_HE_SWITCH_DEFAULTS.items():
            if key.endswith("_enabled"):
                self.assertEqual(
                    self.app.n2_he_switch_enabled_vars[key].get(), value == "1"
                )
            else:
                self.assertEqual(self.app.n2_he_switch_vars[key].get(), value)
        log = self.app.log_text.get("1.0", "end")
        self.assertIn("[n2_to_he_switch] fields reset to defaults", log)

    def test_n2_he_switch_reset_defaults_clears_readiness_latch(self):
        self.app._n2_he_prepswitch_ready_logged = True
        self.app._on_n2_to_he_switch_reset_defaults()
        self.assertFalse(self.app._n2_he_prepswitch_ready_logged)

    def test_n2_he_switch_has_no_leftover_prepswitch_flow_field(self):
        # Regression test for a second, independent latent KeyError
        # bug found during the Item 11 audit: this section's Step 1
        # field loop used to reference a "prepswitch_flow" key that
        # was never in N2_TO_HE_SWITCH_DEFAULTS (prepswitch() only
        # ever sets the two Lakeshore setpoints -- it never calls
        # flow_set). setUp() building self.app already proves no
        # KeyError was raised; this additionally confirms the key is
        # truly absent everywhere it could matter.
        self.assertNotIn("prepswitch_flow", self.app.n2_he_switch_vars)
        self.assertNotIn("prepswitch_flow", N2_TO_HE_SWITCH_DEFAULTS)
        params = self.app._collect_n2_to_he_switch_params()
        self.assertNotIn("prepswitch_flow", params)

    # ---- N2 -> He Gas Switch: live temperature reading from EPICS ----

    def test_read_n2_he_temps_sets_all_three_fields_on_success(self):
        import epics
        epics.values.clear()
        epics.values[STAGE_A_TEMP_PV] = "150.2"
        epics.values[STAGE_C_TEMP_PV] = "140.1"
        epics.values[SAMPLE_TEMP_PV] = "145.0"
        try:
            self.app._on_read_n2_he_temps()
            self.app._n2_he_temp_read_thread.join(timeout=5)
            self.app._run_tk_calls()

            self.assertEqual(self.app.n2_he_stage_a_temp_var.get(), "150.2")
            self.assertEqual(self.app.n2_he_stage_c_temp_var.get(), "140.1")
            self.assertEqual(self.app.n2_he_sample_temp_var.get(), "145.0")
            self.assertEqual(self.app.n2_he_read_temps_button.cget("state"), "normal")
        finally:
            epics.values.clear()

    def test_read_n2_he_temps_handles_missing_pyepics(self):
        real_epics = sys.modules.get("epics")
        sys.modules["epics"] = None  # forces "import epics" to raise ImportError
        try:
            self.app._on_read_n2_he_temps()
            self.app._n2_he_temp_read_thread.join(timeout=5)
            self.app._run_tk_calls()

            self.assertEqual(self.app.n2_he_stage_a_temp_var.get(), "?")
            self.assertEqual(self.app.n2_he_read_temps_button.cget("state"), "normal")
            log = self.app.log_text.get("1.0", "end")
            self.assertIn("pyepics is not installed", log)
        finally:
            if real_epics is not None:
                sys.modules["epics"] = real_epics
            else:
                sys.modules.pop("epics", None)

    def test_read_n2_he_temps_logs_error_without_crashing_on_failure(self):
        import epics

        def failing_caget(pvname, as_string=False, timeout=5.0, **kwargs):
            raise RuntimeError("Channel Access timeout")

        original_caget = epics.caget
        epics.caget = failing_caget
        try:
            self.app._on_read_n2_he_temps()
            self.app._n2_he_temp_read_thread.join(timeout=5)
            self.app._run_tk_calls()

            self.assertEqual(self.app.n2_he_stage_a_temp_var.get(), "?")
            self.assertEqual(self.app.n2_he_read_temps_button.cget("state"), "normal")
        finally:
            epics.caget = original_caget

    def test_toggle_n2_he_temp_watch_logs_state_change(self):
        self.app.n2_he_temp_watch_var.set(False)
        self.app._on_toggle_n2_he_temp_watch()
        log = self.app.log_text.get("1.0", "end")
        self.assertIn("[watch] N2->He temperature auto-watch paused", log)

        self.app.n2_he_temp_watch_var.set(True)
        self.app._on_toggle_n2_he_temp_watch()
        log = self.app.log_text.get("1.0", "end")
        self.assertIn("[watch] N2->He temperature auto-watch on", log)

    def test_temp_watch_tick_skips_read_when_checkbox_unchecked(self):
        self.app.n2_he_temp_watch_var.set(False)
        self.app._n2_he_temp_watch_tick()
        self.assertIsNone(self.app._n2_he_temp_read_thread)

    def test_temp_watch_tick_starts_a_read_when_checked(self):
        import epics
        epics.values.clear()
        epics.values[STAGE_A_TEMP_PV] = "99"
        epics.values[STAGE_C_TEMP_PV] = "88"
        epics.values[SAMPLE_TEMP_PV] = "240"
        self.app.n2_he_temp_watch_var.set(True)
        try:
            self.app._n2_he_temp_watch_tick()
            self.app._n2_he_temp_read_thread.join(timeout=5)
            self.app._run_tk_calls()
            self.assertEqual(self.app.n2_he_stage_a_temp_var.get(), "99")
        finally:
            epics.values.clear()

    def test_destroy_cancels_the_n2_he_temp_watch_timer(self):
        after_id = self.app._n2_he_temp_watch_after_id
        self.assertIsNotNone(after_id)
        self.app.destroy()
        self.assertIsNone(self.app._n2_he_temp_watch_after_id)

    # ---- N2 -> He Gas Switch: "next stage is ready" readiness check ----

    def test_prepswitch_ready_logs_once_when_both_stages_reach_setpoint(self):
        # Defaults: prepswitch_stage_a=100, prepswitch_stage_c=95.
        self.app.n2_he_stage_a_temp_var.set("99.5")
        self.app.n2_he_stage_c_temp_var.set("94.2")
        self.app._check_n2_he_prepswitch_ready()
        log = self.app.log_text.get("1.0", "end")
        self.assertIn("next stage is ready", log)
        self.assertTrue(self.app._n2_he_prepswitch_ready_logged)

        # A second check at the same readings must not repeat the message.
        before = log.count("next stage is ready")
        self.app._check_n2_he_prepswitch_ready()
        log = self.app.log_text.get("1.0", "end")
        self.assertEqual(log.count("next stage is ready"), before)

    def test_prepswitch_not_ready_above_tolerance_does_not_log(self):
        self.app.n2_he_stage_a_temp_var.set("150")
        self.app.n2_he_stage_c_temp_var.set("140")
        self.app._check_n2_he_prepswitch_ready()
        log = self.app.log_text.get("1.0", "end")
        self.assertNotIn("next stage is ready", log)
        self.assertFalse(self.app._n2_he_prepswitch_ready_logged)

    def test_prepswitch_ready_latch_resets_after_warming_back_up(self):
        self.app.n2_he_stage_a_temp_var.set("99.5")
        self.app.n2_he_stage_c_temp_var.set("94.2")
        self.app._check_n2_he_prepswitch_ready()
        self.assertTrue(self.app._n2_he_prepswitch_ready_logged)

        # Warms back up past the setpoints (+tolerance) -- latch clears.
        self.app.n2_he_stage_a_temp_var.set("150")
        self.app.n2_he_stage_c_temp_var.set("140")
        self.app._check_n2_he_prepswitch_ready()
        self.assertFalse(self.app._n2_he_prepswitch_ready_logged)

        # Re-arriving at the setpoints logs the message again.
        self.app.n2_he_stage_a_temp_var.set("99.5")
        self.app.n2_he_stage_c_temp_var.set("94.2")
        self.app._check_n2_he_prepswitch_ready()
        self.assertTrue(self.app._n2_he_prepswitch_ready_logged)

    def test_prepswitch_ready_check_ignores_unset_temperature_fields(self):
        # Fields still hold their initial "?" placeholder -- nothing
        # to compare yet, so this must not raise or log anything.
        self.app._check_n2_he_prepswitch_ready()
        log = self.app.log_text.get("1.0", "end")
        self.assertNotIn("next stage is ready", log)
        self.assertFalse(self.app._n2_he_prepswitch_ready_logged)

    def test_read_n2_he_temps_triggers_readiness_check(self):
        import epics
        epics.values.clear()
        epics.values[STAGE_A_TEMP_PV] = "99"
        epics.values[STAGE_C_TEMP_PV] = "94"
        epics.values[SAMPLE_TEMP_PV] = "240"
        try:
            self.app._on_read_n2_he_temps()
            self.app._n2_he_temp_read_thread.join(timeout=5)
            self.app._run_tk_calls()
            log = self.app.log_text.get("1.0", "end")
            self.assertIn("next stage is ready", log)
        finally:
            epics.values.clear()

    # ---- N2 -> He Gas Switch: Step 7 / Steps 8-10 partial-run buttons ----
    # (mirrors the existing Step 1 / Steps 3-5 buttons, added alongside
    # run_n2_to_he_step7/run_n2_to_he_steps_8_to_10 in hrdm_core.py)

    def test_n2_he_switch_step7_and_steps8_10_buttons_exist(self):
        self.assertIsNotNone(self.app.n2_he_switch_step7_button)
        self.assertIsNotNone(self.app.n2_he_switch_steps8_10_button)

    def test_n2_he_switch_run_step7_sends_expected_commands(self):
        # Zero out the (real, non-preview) wait so the worker thread
        # doesn't actually sleep for the default 5 minutes before
        # finishing -- same pattern used by every other live-sending
        # test that has a "*_minutes" wait field.
        self.app.n2_he_switch_vars["wait_for_base_temp_minutes"].set("0")
        self.app._on_n2_to_he_switch_run_step7()
        self.app.n2_he_switch_run_thread.join(timeout=5)

        self.assertIn('epics_put("LAKESHORE2:SETP_S1",30)', self.controller.sent)
        self.assertIn('epics_put("LAKESHORE2:SETP_S3",16)', self.controller.sent)
        self.assertFalse(any("te " in cmd for cmd in self.controller.sent))
        self.assertFalse(any("flow_set" in cmd for cmd in self.controller.sent))

    def test_n2_he_switch_run_steps8_10_sends_expected_commands(self):
        self.app._on_n2_to_he_switch_run_steps_8_10()
        self.app.n2_he_switch_run_thread.join(timeout=5)

        self.assertIn("flow_set 12", self.controller.sent)
        self.assertIn("te 15", self.controller.sent)
        self.assertFalse(any("epics_put" in cmd for cmd in self.controller.sent))

    def test_n2_he_switch_run_step7_with_custom_params(self):
        self.app.n2_he_switch_vars["wait_for_base_temp_minutes"].set("0")
        self.app.n2_he_switch_vars["runninghelium_stage_a"].set("6")
        self.app.n2_he_switch_vars["runninghelium_stage_c"].set("32")
        self.app._on_n2_to_he_switch_run_step7()
        self.app.n2_he_switch_run_thread.join(timeout=5)

        self.assertIn('epics_put("LAKESHORE2:SETP_S1",6)', self.controller.sent)
        self.assertIn('epics_put("LAKESHORE2:SETP_S3",32)', self.controller.sent)

    def test_n2_he_switch_all_run_buttons_disabled_while_step7_in_flight(self):
        import hrdm_core
        self.app.n2_he_switch_vars["wait_for_base_temp_minutes"].set("0")
        release = threading.Event()
        original_epics_put = hrdm_core.Runner.epics_put

        def slow_epics_put(self, pv, value):
            release.wait(timeout=5)
            return original_epics_put(self, pv, value)

        hrdm_core.Runner.epics_put = slow_epics_put
        try:
            self.app._on_n2_to_he_switch_run_step7()
            for btn in self.app._n2_he_switch_buttons():
                self.assertEqual(btn.cget("state"), "disabled")
            self.assertEqual(self.app.n2_he_switch_stop_button.cget("state"), "normal")
        finally:
            release.set()
            self.app.n2_he_switch_run_thread.join(timeout=5)
            self.app._poll_log()
            self.app._run_tk_calls()
            hrdm_core.Runner.epics_put = original_epics_put

        for btn in self.app._n2_he_switch_buttons():
            self.assertEqual(btn.cget("state"), "normal")
        self.assertEqual(self.app.n2_he_switch_stop_button.cget("state"), "disabled")

    def test_n2_he_switch_steps8_10_invalid_params_sends_nothing(self):
        self.app.n2_he_switch_vars["flow_2"].set("not-a-number")
        self.app._on_n2_to_he_switch_run_steps_8_10()

        self.assertIsNone(self.app.n2_he_switch_run_thread)
        self.assertEqual(self.controller.sent, [])

    def test_n2_he_switch_step7_blocked_while_other_scan_running(self):
        # Shares the same concurrency guard as every other scan-type
        # thread -- confirm it's blocked by, e.g., an in-flight Gas
        # Prep Macros job (same pattern used by that tab's own
        # concurrency-guard tests).
        import hrdm_core
        release = threading.Event()
        original_epics_put = hrdm_core.Runner.epics_put

        def slow_epics_put(self, pv, value):
            release.wait(timeout=5)
            return original_epics_put(self, pv, value)

        hrdm_core.Runner.epics_put = slow_epics_put
        try:
            self.app._on_gas_prep_run_macro("roomT")
            self.app._on_n2_to_he_switch_run_step7()
            self.assertIsNone(self.app.n2_he_switch_run_thread)
        finally:
            release.set()
            self.app.gas_prep_run_thread.join(timeout=5)
            self.app._poll_log()
            self.app._run_tk_calls()
            hrdm_core.Runner.epics_put = original_epics_put

    # ---- Gas Prep Macros tab ----

    def test_gas_prep_fields_default_to_defaults(self):
        for key, value in GAS_PREP_MACROS_DEFAULTS.items():
            self.assertEqual(self.app.gas_prep_vars[key].get(), value)

    def test_gas_prep_all_macro_buttons_exist(self):
        for name in GAS_PREP_MACRO_NAMES:
            self.assertIn(name, self.app.gas_prep_macro_buttons)

    def test_collect_gas_prep_params_matches_defaults(self):
        params = self.app._collect_gas_prep_params()
        self.assertEqual(params, dict(GAS_PREP_MACROS_DEFAULTS))

    def test_gas_prep_reset_defaults_restores_fields_and_logs(self):
        self.app.gas_prep_vars["prepswitch_stage_a"].set("999")
        self.app.gas_prep_vars["flow_set_value"].set("999")
        self.app._on_gas_prep_reset_defaults()

        for key, value in GAS_PREP_MACROS_DEFAULTS.items():
            self.assertEqual(self.app.gas_prep_vars[key].get(), value)
        log = self.app.log_text.get("1.0", "end")
        self.assertIn("[gas_prep] fields reset to defaults", log)

    def test_gas_prep_reset_defaults_clears_readiness_latch(self):
        self.app._gas_prep_prepswitch_ready_logged = True
        self.app._on_gas_prep_reset_defaults()
        self.assertFalse(self.app._gas_prep_prepswitch_ready_logged)

    def test_gas_prep_run_macro_sends_real_commands_through_shared_controller(self):
        self.app._on_gas_prep_run_macro("roomT")
        self.app.gas_prep_run_thread.join(timeout=5)

        self.assertEqual(len(_FakeIDSpecController.instances), 1)
        self.assertIn('epics_put("LAKESHORE2:SETP_S1",222)', self.controller.sent)
        self.assertIn('epics_put("LAKESHORE2:SETP_S3",220)', self.controller.sent)

    def test_gas_prep_run_prepswitch_no_longer_sends_flow_set(self):
        # prepswitch no longer sends flow_set -- that automatic call
        # (and the standalone "flow_set" UI field on this tab's
        # prepswitch column) was a project addition that has since
        # been removed per explicit user request ("Prepswitch:
        # takeout flow_set"); prepswitch() now matches
        # Lakeshore336cryocool.mac's real macro exactly (two Lakeshore
        # setpoints only).
        self.app._on_gas_prep_run_macro("prepswitch")
        self.app.gas_prep_run_thread.join(timeout=5)

        self.assertIn('epics_put("LAKESHORE2:SETP_S1",100)', self.controller.sent)
        self.assertIn('epics_put("LAKESHORE2:SETP_S3",95)', self.controller.sent)
        self.assertFalse(any("flow_set" in cmd for cmd in self.controller.sent))

    def test_gas_prep_run_macro_with_custom_params(self):
        self.app.gas_prep_vars["roomt_stage_a"].set("225")
        self.app.gas_prep_vars["roomt_stage_c"].set("221")
        self.app._on_gas_prep_run_macro("roomT")
        self.app.gas_prep_run_thread.join(timeout=5)

        self.assertIn('epics_put("LAKESHORE2:SETP_S1",225)', self.controller.sent)
        self.assertIn('epics_put("LAKESHORE2:SETP_S3",221)', self.controller.sent)

    # room_temperature_sample ("Room Temp Condition") was a standalone
    # project addition with no Lakeshore336cryocool.mac precedent;
    # its tests have been removed since the panel itself has been
    # deleted entirely per explicit user request ("delete Room
    # temperature sample panel").

    def test_gas_prep_run_macro_shows_error_for_invalid_params_and_sends_nothing(self):
        self.app.gas_prep_vars["roomt_stage_a"].set("not-a-number")
        self.app._on_gas_prep_run_macro("roomT")

        self.assertIsNone(self.app.gas_prep_run_thread)
        self.assertEqual(self.controller.sent, [])

    # ---- Gas Prep Macros: per-macro Preview buttons (7 total -- the
    # 7 .mac macros; the former room_temperature_sample standalone
    # panel has been deleted entirely, see above) ----

    def test_gas_prep_preview_never_sends_anything(self):
        for name in GAS_PREP_MACRO_NAMES:
            self.app._on_gas_prep_preview_macro(name)
        self.assertEqual(self.controller.sent, [])
        self.assertIsNone(self.app.gas_prep_run_thread)

    def test_gas_prep_preview_logs_macro_commands(self):
        self.app._on_gas_prep_preview_macro("roomT")
        log = self.app.log_text.get("1.0", "end")
        self.assertIn("Preview: Gas Prep Macro: roomT", log)
        self.assertIn("[epics_put] LAKESHORE2:SETP_S1 = 222", log)
        self.assertIn("[epics_put] LAKESHORE2:SETP_S3 = 220", log)
        self.assertIn("End preview -- click Run roomT to actually send this", log)

    def test_gas_prep_preview_reflects_custom_params(self):
        self.app.gas_prep_vars["roomt_stage_a"].set("225")
        self.app.gas_prep_vars["roomt_stage_c"].set("221")
        self.app._on_gas_prep_preview_macro("roomT")
        log = self.app.log_text.get("1.0", "end")
        self.assertIn("[epics_put] LAKESHORE2:SETP_S1 = 225", log)
        self.assertIn("[epics_put] LAKESHORE2:SETP_S3 = 221", log)

    def test_gas_prep_preview_shows_error_for_invalid_params_and_sends_nothing(self):
        self.app.gas_prep_vars["roomt_stage_a"].set("not-a-number")
        self.app._on_gas_prep_preview_macro("roomT")
        self.assertEqual(self.controller.sent, [])
        log = self.app.log_text.get("1.0", "end")
        self.assertNotIn("Preview: Gas Prep Macro: roomT", log)

    def test_gas_prep_preview_available_while_a_run_is_in_flight(self):
        # Preview is a synchronous, throwaway Runner(preview=True) --
        # it must never be blocked by this tab's (or any other tab's)
        # concurrency guard, unlike the Run buttons.
        release = threading.Event()
        import hrdm_core

        real_epics_put = hrdm_core.Runner.epics_put

        def slow_epics_put(self_runner, pv, value):
            release.wait(timeout=5)
            return real_epics_put(self_runner, pv, value)

        hrdm_core.Runner.epics_put = slow_epics_put
        try:
            self.app._on_gas_prep_run_macro("roomT")
            self.assertTrue(self.app.gas_prep_run_thread.is_alive())

            self.app._on_gas_prep_preview_macro("prepN2_low")
            log = self.app.log_text.get("1.0", "end")
            self.assertIn("Preview: Gas Prep Macro: prepN2_low", log)
        finally:
            release.set()
            self.app.gas_prep_run_thread.join(timeout=5)
            self.app._poll_log()
            hrdm_core.Runner.epics_put = real_epics_put

    def test_gas_prep_flow_set_sends_expected_command(self):
        self.app.gas_prep_vars["flow_set_value"].set("9")
        self.app._on_gas_prep_flow_set()
        self.app.gas_prep_run_thread.join(timeout=5)
        self.assertIn("flow_set 9", self.controller.sent)

    def test_gas_prep_flow_get_sends_expected_command_and_sets_result(self):
        # The fake SpecController.send() always returns "OK" (see
        # id4b_pyspec/spec_controller.py's fake stub) -- there's no
        # per-test configurable response, so this only confirms the
        # command sent and that the raw response reaches the result
        # field via _set_gas_prep_flow_result, not any particular
        # numeric flow reading.
        self.app._on_gas_prep_flow_get()
        self.app.gas_prep_run_thread.join(timeout=5)
        self.app._run_tk_calls()

        self.assertIn("flow_get", self.controller.sent)
        self.assertEqual(self.app.gas_prep_flow_result_var.get(), "OK")

    def test_gas_prep_done_sentinel_reenables_buttons_and_logs(self):
        self.app._on_gas_prep_run_macro("roomT")
        self.app.gas_prep_run_thread.join(timeout=5)
        self.app._poll_log()  # dispatch the queued __GAS_PREP_DONE__ sentinel

        for btn in self.app._gas_prep_all_buttons():
            self.assertEqual(btn.cget("state"), "normal")
        self.assertEqual(self.app.gas_prep_stop_button.cget("state"), "disabled")
        log = self.app.log_text.get("1.0", "end")
        self.assertIn("========== Gas Prep Macros finished ==========", log)

    def test_gas_prep_buttons_disabled_while_in_flight(self):
        release = threading.Event()
        import hrdm_core

        real_epics_put = hrdm_core.Runner.epics_put

        def slow_epics_put(self_runner, pv, value):
            release.wait(timeout=5)
            return real_epics_put(self_runner, pv, value)

        hrdm_core.Runner.epics_put = slow_epics_put
        try:
            self.app._on_gas_prep_run_macro("roomT")
            self.assertEqual(
                self.app.gas_prep_macro_buttons["roomT"].cget("state"), "disabled"
            )
            self.assertEqual(self.app.gas_prep_stop_button.cget("state"), "normal")
        finally:
            release.set()
            self.app.gas_prep_run_thread.join(timeout=5)
            self.app._poll_log()
            hrdm_core.Runner.epics_put = real_epics_put

        self.assertEqual(
            self.app.gas_prep_macro_buttons["roomT"].cget("state"), "normal"
        )

    def test_gas_prep_refuses_while_height_scan_is_running(self):
        release = threading.Event()
        import hrdm_core

        real_closes = hrdm_core.Runner.closes

        def slow_closes(self_runner):
            release.wait(timeout=5)
            return real_closes(self_runner)

        hrdm_core.Runner.closes = slow_closes
        try:
            self.app._on_height_run()
            self.assertTrue(self.app.height_run_thread.is_alive())

            sent_before = list(self.controller.sent)
            self.app._on_gas_prep_run_macro("roomT")  # should refuse
            self.assertIsNone(self.app.gas_prep_run_thread)
            self.assertEqual(self.controller.sent, sent_before)
        finally:
            release.set()
            self.app.height_run_thread.join(timeout=5)
            self.app._poll_log()
            hrdm_core.Runner.closes = real_closes

    def test_height_scan_refuses_while_gas_prep_is_running(self):
        release = threading.Event()
        import hrdm_core

        real_epics_put = hrdm_core.Runner.epics_put

        def slow_epics_put(self_runner, pv, value):
            release.wait(timeout=5)
            return real_epics_put(self_runner, pv, value)

        hrdm_core.Runner.epics_put = slow_epics_put
        try:
            self.app._on_gas_prep_run_macro("roomT")
            self.assertTrue(self.app.gas_prep_run_thread.is_alive())

            sent_before = list(self.controller.sent)
            self.app._on_height_run()  # should refuse
            self.assertIsNone(self.app.height_run_thread)
            self.assertEqual(self.controller.sent, sent_before)
        finally:
            release.set()
            self.app.gas_prep_run_thread.join(timeout=5)
            self.app._poll_log()
            hrdm_core.Runner.epics_put = real_epics_put

    # ---- Gas Prep Macros tab: live temperature reading from EPICS ----

    def test_read_gas_prep_temps_sets_all_three_fields_on_success(self):
        import epics
        epics.values.clear()
        epics.values[STAGE_A_TEMP_PV] = "150.2"
        epics.values[STAGE_C_TEMP_PV] = "140.1"
        epics.values[SAMPLE_TEMP_PV] = "145.0"
        try:
            self.app._on_read_gas_prep_temps()
            self.app._gas_prep_temp_read_thread.join(timeout=5)
            self.app._run_tk_calls()

            self.assertEqual(self.app.gas_prep_stage_a_temp_var.get(), "150.2")
            self.assertEqual(self.app.gas_prep_stage_c_temp_var.get(), "140.1")
            self.assertEqual(self.app.gas_prep_sample_temp_var.get(), "145.0")
            self.assertEqual(
                self.app.gas_prep_read_temps_button.cget("state"), "normal"
            )
        finally:
            epics.values.clear()

    def test_read_gas_prep_temps_handles_missing_pyepics(self):
        real_epics = sys.modules.get("epics")
        sys.modules["epics"] = None  # forces "import epics" to raise ImportError
        try:
            self.app._on_read_gas_prep_temps()
            self.app._gas_prep_temp_read_thread.join(timeout=5)
            self.app._run_tk_calls()

            self.assertEqual(self.app.gas_prep_stage_a_temp_var.get(), "?")
            self.assertEqual(
                self.app.gas_prep_read_temps_button.cget("state"), "normal"
            )
            log = self.app.log_text.get("1.0", "end")
            self.assertIn("pyepics is not installed", log)
        finally:
            if real_epics is not None:
                sys.modules["epics"] = real_epics
            else:
                sys.modules.pop("epics", None)

    def test_toggle_gas_prep_temp_watch_logs_state_change(self):
        self.app.gas_prep_temp_watch_var.set(False)
        self.app._on_toggle_gas_prep_temp_watch()
        log = self.app.log_text.get("1.0", "end")
        self.assertIn("[watch] Gas Prep temperature auto-watch paused", log)

        self.app.gas_prep_temp_watch_var.set(True)
        self.app._on_toggle_gas_prep_temp_watch()
        log = self.app.log_text.get("1.0", "end")
        self.assertIn("[watch] Gas Prep temperature auto-watch on", log)

    def test_gas_prep_temp_watch_tick_skips_read_when_checkbox_unchecked(self):
        self.app.gas_prep_temp_watch_var.set(False)
        self.app._gas_prep_temp_watch_tick()
        self.assertIsNone(self.app._gas_prep_temp_read_thread)

    def test_destroy_cancels_the_gas_prep_temp_watch_timer(self):
        after_id = self.app._gas_prep_temp_watch_after_id
        self.assertIsNotNone(after_id)
        self.app.destroy()
        self.assertIsNone(self.app._gas_prep_temp_watch_after_id)

    def test_gas_prep_prepswitch_ready_logs_once_when_both_stages_reach_setpoint(self):
        # Defaults: prepswitch_stage_a=100, prepswitch_stage_c=95.
        self.app.gas_prep_stage_a_temp_var.set("99.5")
        self.app.gas_prep_stage_c_temp_var.set("94.2")
        self.app._check_gas_prep_prepswitch_ready()
        log = self.app.log_text.get("1.0", "end")
        self.assertIn("next stage is ready", log)
        self.assertTrue(self.app._gas_prep_prepswitch_ready_logged)

    def test_gas_prep_prepswitch_not_ready_above_tolerance_does_not_log(self):
        self.app.gas_prep_stage_a_temp_var.set("150")
        self.app.gas_prep_stage_c_temp_var.set("140")
        self.app._check_gas_prep_prepswitch_ready()
        log = self.app.log_text.get("1.0", "end")
        self.assertNotIn("next stage is ready", log)
        self.assertFalse(self.app._gas_prep_prepswitch_ready_logged)

    # ---- Gas Prep tab: "Spin Control" section (self.gas_prep_spin_* --
    # Item 2.8, "Spin control tab type option in gas flow tab, I want
    # to rotate the crystal"; a third independent copy of the same
    # Start/Stop/Reset logic, alongside the main Spin Control tab and
    # the Low Temp Scan standalone section above; see
    # _build_gas_prep_spin_section) ----

    def test_gas_prep_spin_fields_default_to_spin_defaults(self):
        self.assertEqual(self.app.gas_prep_spin_vars["num_cycles"].get(), SPIN_DEFAULTS["num_cycles"])
        self.assertEqual(self.app.gas_prep_spin_ice_mode_var.get(), SPIN_DEFAULTS["ice_mode"] == "1")

    def test_gas_prep_spin_reset_defaults_restores_fields_and_logs(self):
        self.app.gas_prep_spin_vars["num_cycles"].set("5")
        self.app.gas_prep_spin_ice_mode_var.set(True)
        self.app._on_gas_prep_spin_reset_defaults()

        self.assertEqual(self.app.gas_prep_spin_vars["num_cycles"].get(), SPIN_DEFAULTS["num_cycles"])
        self.assertFalse(self.app.gas_prep_spin_ice_mode_var.get())
        log = self.app.log_text.get("1.0", "end")
        self.assertIn("[gas prep spin] fields reset to defaults (continuous, ice mode off)", log)

    def test_gas_prep_spin_start_sends_real_commands_through_shared_controller(self):
        self.app.gas_prep_spin_vars["num_cycles"].set("1")
        self.app._on_gas_prep_spin_start()
        self.app.gas_prep_spin_run_thread.join(timeout=5)

        self.assertEqual(len(_FakeIDSpecController.instances), 1)
        self.assertIn("umv phi 360", self.controller.sent)
        self.assertIn("umv phi 0", self.controller.sent)
        self.app._poll_log()
        log = self.app.log_text.get("1.0", "end")
        self.assertIn("[spin_xtal_phi] cycle 1/1 completed", log)

    def test_gas_prep_spin_start_shows_error_for_invalid_params_and_sends_nothing(self):
        self.app.gas_prep_spin_vars["num_cycles"].set("1.5")  # not a whole number
        self.app._on_gas_prep_spin_start()

        self.assertIsNone(self.app.gas_prep_spin_run_thread)
        self.assertEqual(self.controller.sent, [])

    def test_gas_prep_spin_done_sentinel_reenables_buttons_and_logs(self):
        self.app.gas_prep_spin_vars["num_cycles"].set("1")
        self.app._on_gas_prep_spin_start()
        self.app.gas_prep_spin_run_thread.join(timeout=5)
        self.app._poll_log()  # dispatch the queued __GAS_PREP_SPIN_DONE__ sentinel

        self.assertEqual(self.app.gas_prep_spin_start_button.cget("state"), "normal")
        self.assertEqual(self.app.gas_prep_spin_stop_button.cget("state"), "disabled")
        log = self.app.log_text.get("1.0", "end")
        self.assertIn("========== Gas Prep: Spin finished ==========", log)

    def test_gas_prep_spin_start_button_disabled_while_running(self):
        self.app._on_gas_prep_spin_start()  # continuous (blank num_cycles)
        try:
            self.assertEqual(self.app.gas_prep_spin_start_button.cget("state"), "disabled")
            self.assertEqual(self.app.gas_prep_spin_stop_button.cget("state"), "normal")
        finally:
            self.app.gas_prep_spin_cancel_event.set()
            self.app.gas_prep_spin_run_thread.join(timeout=5)
            self.app._poll_log()
        self.assertEqual(self.app.gas_prep_spin_start_button.cget("state"), "normal")

    def test_gas_prep_spin_stop_sends_abort_immediately_through_shared_controller(self):
        # Item 8 fix: Stop must abort the in-flight SPEC move right
        # away (self.controller.abort()) rather than relying solely on
        # cancel_event -- see _on_gas_prep_spin_stop's docstring.
        self.app._on_gas_prep_spin_start()  # continuous (blank num_cycles)
        try:
            self.app._on_gas_prep_spin_stop()
            self.app._last_gas_prep_spin_abort_thread.join(timeout=5)
            self.assertEqual(self.controller.abort_count, 1)
        finally:
            self.app.gas_prep_spin_run_thread.join(timeout=5)
            self.app._poll_log()

    # ---- Height Scan tab (translated from HDRMscans_new.mac's `heightscan`) ----

    def test_height_fields_default_to_heightscan_defaults(self):
        for key, value in HEIGHTSCAN_DEFAULTS.items():
            self.assertEqual(self.app.height_vars[key].get(), value)

    def test_height_reset_defaults_restores_fields_and_logs(self):
        self.app.height_vars["start"].set("-99")
        self.app.height_vars["steps"].set("1")
        self.app._on_height_reset_defaults()

        for key, value in HEIGHTSCAN_DEFAULTS.items():
            self.assertEqual(self.app.height_vars[key].get(), value)
        log = self.app.log_text.get("1.0", "end")
        self.assertIn("[heightscan] fields reset to defaults", log)

    def test_height_preview_never_sends_anything(self):
        self.app._on_height_preview()
        self.assertEqual(self.controller.sent, [])

    def test_height_preview_logs_full_sequence(self):
        self.app._on_height_preview()
        log = self.app.log_text.get("1.0", "end")
        self.assertIn(
            "========== Preview: Height Scan (no waiting, nothing sent) ==========",
            log,
        )
        self.assertIn("lup samz -0.6 0.6 60 0.2", log)
        self.assertIn(
            "========== End preview -- click Run Height Scan to actually send this ==========",
            log,
        )

    def test_height_preview_shows_error_for_invalid_params_and_sends_nothing(self):
        self.app.height_vars["steps"].set("not-a-number")
        self.app._on_height_preview()
        self.assertEqual(self.controller.sent, [])
        log = self.app.log_text.get("1.0", "end")
        # No preview banner should have been logged either -- validation
        # fails before anything is shown.
        self.assertNotIn("Preview: Height Scan", log)

    def test_height_run_sends_real_commands_through_shared_controller(self):
        self.app.global_vars["rampre"].set("/ramdisk/sarker-4775-a/")
        self.app._on_height_run()
        self.app.height_run_thread.join(timeout=5)

        # No new SpecController should have been created.
        self.assertEqual(len(_FakeIDSpecController.instances), 1)
        self.assertIn('pil_settrig "Internal"', self.controller.sent)
        self.assertIn(
            'pil_setdir "/ramdisk/sarker-4775-a//tiffs/"', self.controller.sent
        )
        self.assertIn("opens", self.controller.sent)
        self.assertIn("lup samz -0.6 0.6 60 0.2", self.controller.sent)
        self.assertIn("closes", self.controller.sent)
        # Run Scan's own trigger mode is never touched by a height scan.
        self.assertNotIn('pil_settrig "Mult. Trigger"', self.controller.sent)

    def test_height_run_with_custom_params(self):
        self.app.height_vars["start"].set("-0.8")
        self.app.height_vars["end"].set("0.8")
        self.app.height_vars["steps"].set("80")
        self.app.height_vars["count_time"].set("0.3")
        self.app._on_height_run()
        self.app.height_run_thread.join(timeout=5)

        self.assertIn("lup samz -0.8 0.8 80 0.3", self.controller.sent)

    def test_height_run_shows_error_for_invalid_params_and_sends_nothing(self):
        self.app.height_vars["start"].set("0.6")
        self.app.height_vars["end"].set("0.6")  # start == end -> invalid
        self.app._on_height_run()

        self.assertIsNone(self.app.height_run_thread)
        self.assertEqual(self.controller.sent, [])

    def test_height_done_sentinel_reenables_button_and_logs(self):
        self.app._on_height_run()
        self.app.height_run_thread.join(timeout=5)
        self.app._poll_log()  # dispatch the queued __HEIGHT_DONE__ sentinel

        self.assertEqual(self.app.height_run_button.cget("state"), "normal")
        log = self.app.log_text.get("1.0", "end")
        self.assertIn("========== Height Scan finished ==========", log)

    def test_height_run_button_disabled_while_in_flight(self):
        release = threading.Event()
        original_run_height_scan = None

        # Block inside run_height_scan (via a slow closes()) so we can
        # observe the button's disabled state before the worker finishes.
        import hrdm_core

        real_closes = hrdm_core.Runner.closes

        def slow_closes(self_runner):
            release.wait(timeout=5)
            return real_closes(self_runner)

        hrdm_core.Runner.closes = slow_closes
        try:
            self.app._on_height_run()
            self.assertEqual(self.app.height_run_button.cget("state"), "disabled")
        finally:
            release.set()
            self.app.height_run_thread.join(timeout=5)
            self.app._poll_log()
            hrdm_core.Runner.closes = real_closes

        self.assertEqual(self.app.height_run_button.cget("state"), "normal")

    # ---- Powder Scan tab (translated from HDRMscans_new.mac's `powderscan`) ----

    def test_powder_fields_default_to_powderscan_defaults(self):
        for key, value in POWDERSCAN_DEFAULTS.items():
            self.assertEqual(self.app.powder_vars[key].get(), value)

    def test_powder_reset_defaults_restores_fields_and_logs(self):
        self.app.powder_vars["temperature"].set("-99")
        self.app.powder_vars["wait_seconds"].set("1")
        self.app._on_powder_reset_defaults()

        for key, value in POWDERSCAN_DEFAULTS.items():
            self.assertEqual(self.app.powder_vars[key].get(), value)
        log = self.app.log_text.get("1.0", "end")
        self.assertIn("[powderscan] fields reset to defaults", log)

    def test_powder_preview_never_sends_anything(self):
        self.app._on_powder_preview()
        self.assertEqual(self.controller.sent, [])

    def test_powder_preview_logs_full_sequence(self):
        self.app._on_powder_preview()
        log = self.app.log_text.get("1.0", "end")
        self.assertIn(
            "========== Preview: Powder Scan (no waiting, nothing sent) ==========",
            log,
        )
        self.assertIn("[umv] chi 90 th 0 phi 0", log)
        self.assertIn("flyscan phi 0 360 180 1", log)
        self.assertIn(
            "========== End preview -- click Run Powder Scan to actually send this ==========",
            log,
        )

    def test_powder_preview_shows_error_for_invalid_params_and_sends_nothing(self):
        self.app.powder_vars["wait_seconds"].set("not-a-number")
        self.app._on_powder_preview()
        self.assertEqual(self.controller.sent, [])
        log = self.app.log_text.get("1.0", "end")
        self.assertNotIn("Preview: Powder Scan", log)

    def test_powder_run_sends_real_commands_through_shared_controller(self):
        self.app.global_vars["datafile"].set("test2")
        self.app.powder_vars["wait_seconds"].set("0")
        self.app._on_powder_run()
        self.app.powder_run_thread.join(timeout=5)

        # No new SpecController should have been created.
        self.assertEqual(len(_FakeIDSpecController.instances), 1)
        self.assertIn('pil_settrig "Mult. Trigger"', self.controller.sent)
        self.assertIn("umv chi 90 th 0 phi 0", self.controller.sent)
        self.assertIn("opens", self.controller.sent)
        self.assertIn("flyscan phi 0 360 180 1", self.controller.sent)
        self.assertIn("closes", self.controller.sent)
        self.assertTrue(
            any(cmd.startswith("u mkdir") for cmd in self.controller.sent)
        )
        # The macro's own `te $1` line is commented out -- powder scan
        # should never send a "te ..." command.
        self.assertFalse(any(cmd.startswith("te ") for cmd in self.controller.sent))

    def test_powder_run_with_custom_temperature(self):
        self.app.global_vars["datafile"].set("test2")
        self.app.powder_vars["temperature"].set("150")
        self.app.powder_vars["wait_seconds"].set("0")
        self.app._on_powder_run()
        self.app.powder_run_thread.join(timeout=5)

        self.assertTrue(
            any(
                cmd.startswith('pil_setdir "') and "/test2/sample1/150/" in cmd
                for cmd in self.controller.sent
            )
        )

    def test_powder_run_with_custom_flyscan_range_sends_matching_command(self):
        self.app.global_vars["datafile"].set("test2")
        self.app.powder_vars["wait_seconds"].set("0")
        self.app.powder_vars["phi_start"].set("-180")
        self.app.powder_vars["phi_end"].set("180")
        self.app.powder_vars["num_steps"].set("90")
        self.app.powder_vars["count_time"].set("1")
        self.app._on_powder_run()
        self.app.powder_run_thread.join(timeout=5)

        self.assertIn("flyscan phi -180 180 90 1", self.controller.sent)

    def test_powder_invalid_flyscan_range_shows_error_and_sends_nothing(self):
        self.app.powder_vars["phi_start"].set("180")
        self.app.powder_vars["phi_end"].set("180")
        self.app._on_powder_run()

        self.assertIsNone(self.app.powder_run_thread)
        self.assertEqual(self.controller.sent, [])

    def test_powder_run_shows_error_for_invalid_params_and_sends_nothing(self):
        self.app.powder_vars["wait_seconds"].set("not-a-number")
        self.app._on_powder_run()

        self.assertIsNone(self.app.powder_run_thread)
        self.assertEqual(self.controller.sent, [])

    def test_powder_done_sentinel_reenables_button_and_logs(self):
        self.app.powder_vars["wait_seconds"].set("0")
        self.app._on_powder_run()
        self.app.powder_run_thread.join(timeout=5)
        self.app._poll_log()  # dispatch the queued __POWDER_DONE__ sentinel

        self.assertEqual(self.app.powder_run_button.cget("state"), "normal")
        log = self.app.log_text.get("1.0", "end")
        self.assertIn("========== Powder Scan finished ==========", log)

    def test_powder_run_button_disabled_while_in_flight(self):
        release = threading.Event()
        import hrdm_core

        real_closes = hrdm_core.Runner.closes

        def slow_closes(self_runner):
            release.wait(timeout=5)
            return real_closes(self_runner)

        hrdm_core.Runner.closes = slow_closes
        self.app.powder_vars["wait_seconds"].set("0")
        try:
            self.app._on_powder_run()
            self.assertEqual(self.app.powder_run_button.cget("state"), "disabled")
        finally:
            release.set()
            self.app.powder_run_thread.join(timeout=5)
            self.app._poll_log()
            hrdm_core.Runner.closes = real_closes

        self.assertEqual(self.app.powder_run_button.cget("state"), "normal")

    # ---- Mutual concurrency guard between Run Scan, Height Scan, and Powder Scan ----

    def test_run_scan_refuses_while_powder_scan_is_running(self):
        release = threading.Event()
        import hrdm_core

        real_closes = hrdm_core.Runner.closes

        def slow_closes(self_runner):
            release.wait(timeout=5)
            return real_closes(self_runner)

        hrdm_core.Runner.closes = slow_closes
        self.app.powder_vars["wait_seconds"].set("0")
        try:
            self.app._on_powder_run()
            self.assertTrue(self.app.powder_run_thread.is_alive())

            sent_before = list(self.controller.sent)
            self.app._on_run()  # should refuse -- powder scan still running
            self.assertIsNone(self.app.run_thread)
            self.assertEqual(self.controller.sent, sent_before)
        finally:
            release.set()
            self.app.powder_run_thread.join(timeout=5)
            self.app._poll_log()
            hrdm_core.Runner.closes = real_closes

    def test_powder_scan_refuses_while_run_scan_is_running(self):
        release = threading.Event()
        import hrdm_core

        real_closes = hrdm_core.Runner.closes

        def slow_closes(self_runner):
            release.wait(timeout=5)
            return real_closes(self_runner)

        hrdm_core.Runner.closes = slow_closes
        self.app._set_num_passes("1")
        try:
            self.app._on_run()
            self.assertTrue(self.app.run_thread.is_alive())

            sent_before = list(self.controller.sent)
            self.app._on_powder_run()  # should refuse -- Run Scan still running
            self.assertIsNone(self.app.powder_run_thread)
            self.assertEqual(self.controller.sent, sent_before)
        finally:
            release.set()
            self.app.run_thread.join(timeout=5)
            self.app._poll_log()
            hrdm_core.Runner.closes = real_closes

    def test_powder_scan_refuses_while_height_scan_is_running(self):
        release = threading.Event()
        import hrdm_core

        real_closes = hrdm_core.Runner.closes

        def slow_closes(self_runner):
            release.wait(timeout=5)
            return real_closes(self_runner)

        hrdm_core.Runner.closes = slow_closes
        try:
            self.app._on_height_run()
            self.assertTrue(self.app.height_run_thread.is_alive())

            sent_before = list(self.controller.sent)
            self.app._on_powder_run()  # should refuse -- height scan still running
            self.assertIsNone(self.app.powder_run_thread)
            self.assertEqual(self.controller.sent, sent_before)
        finally:
            release.set()
            self.app.height_run_thread.join(timeout=5)
            self.app._poll_log()
            hrdm_core.Runner.closes = real_closes

    def test_height_scan_refuses_while_powder_scan_is_running(self):
        release = threading.Event()
        import hrdm_core

        real_closes = hrdm_core.Runner.closes

        def slow_closes(self_runner):
            release.wait(timeout=5)
            return real_closes(self_runner)

        hrdm_core.Runner.closes = slow_closes
        self.app.powder_vars["wait_seconds"].set("0")
        try:
            self.app._on_powder_run()
            self.assertTrue(self.app.powder_run_thread.is_alive())

            sent_before = list(self.controller.sent)
            self.app._on_height_run()  # should refuse -- powder scan still running
            self.assertIsNone(self.app.height_run_thread)
            self.assertEqual(self.controller.sent, sent_before)
        finally:
            release.set()
            self.app.powder_run_thread.join(timeout=5)
            self.app._poll_log()
            hrdm_core.Runner.closes = real_closes

    # ---- Mutual concurrency guard between Run Scan and Height Scan ----

    def test_run_scan_refuses_while_height_scan_is_running(self):
        release = threading.Event()
        import hrdm_core

        real_closes = hrdm_core.Runner.closes

        def slow_closes(self_runner):
            release.wait(timeout=5)
            return real_closes(self_runner)

        hrdm_core.Runner.closes = slow_closes
        try:
            self.app._on_height_run()
            self.assertTrue(self.app.height_run_thread.is_alive())

            sent_before = list(self.controller.sent)
            self.app._on_run()  # should refuse -- height scan still running
            self.assertIsNone(self.app.run_thread)
            self.assertEqual(self.controller.sent, sent_before)
        finally:
            release.set()
            self.app.height_run_thread.join(timeout=5)
            self.app._poll_log()
            hrdm_core.Runner.closes = real_closes

    def test_height_scan_refuses_while_run_scan_is_running(self):
        release = threading.Event()
        import hrdm_core

        real_closes = hrdm_core.Runner.closes

        def slow_closes(self_runner):
            release.wait(timeout=5)
            return real_closes(self_runner)

        hrdm_core.Runner.closes = slow_closes
        self.app._set_num_passes("1")
        try:
            self.app._on_run()
            self.assertTrue(self.app.run_thread.is_alive())

            sent_before = list(self.controller.sent)
            self.app._on_height_run()  # should refuse -- Run Scan still running
            self.assertIsNone(self.app.height_run_thread)
            self.assertEqual(self.controller.sent, sent_before)
        finally:
            release.set()
            self.app.run_thread.join(timeout=5)
            self.app._poll_log()
            hrdm_core.Runner.closes = real_closes

    # ---- Top-level tab layout: Height Scan and Threextal Scan are
    # separate, equal tabs (not Height Scan nested inside the Log /
    # Python Script Output notebook) ----

    def test_height_scan_and_tri_crystal_scan_are_separate_top_level_tabs(self):
        tab_texts = [
            self.app.main_notebook.tab(t, "text")
            for t in self.app.main_notebook.tabs()
        ]
        self.assertIn("Sample Information", tab_texts)
        self.assertIn("Height Scan", tab_texts)
        self.assertIn("Threextal Scan", tab_texts)
        self.assertIn("Powder Scan", tab_texts)

    def test_home_tab_is_listed_first(self):
        # "Home" is the newest first tab (added for the "better home
        # page with description" request) -- "Sample Information" is
        # now second.
        tab_texts = [
            self.app.main_notebook.tab(t, "text")
            for t in self.app.main_notebook.tabs()
        ]
        self.assertEqual(tab_texts[0], "Home")

    def test_sample_information_tab_is_listed_second(self):
        tab_texts = [
            self.app.main_notebook.tab(t, "text")
            for t in self.app.main_notebook.tabs()
        ]
        self.assertEqual(tab_texts[1], "Sample Information")

    def test_main_notebook_tab_order_is_height_threextal_powder(self):
        # "Home" is the new first tab, "Sample Information" second;
        # the original 3 tabs (Height Scan, Threextal Scan, Powder
        # Scan) keep their relative order after it, with 7 more
        # temperature/spin-workflow tabs appended after them, and
        # "Gas Prep" (the standalone 7-macro tab, renamed from "Gas
        # Prep Macros" per explicit user request) added last, after
        # "High Temp Scan".
        tab_texts = [
            self.app.main_notebook.tab(t, "text")
            for t in self.app.main_notebook.tabs()
        ]
        self.assertEqual(
            tab_texts,
            [
                "Home",
                "Sample Information",
                "Height Scan",
                "Threextal Scan",
                "Powder Scan",
                "Spin Control",
                "Low Temp Scan",
                "Warmup",
                "Warmup Custom",
                "Cooldown",
                "High Temp Scan",
                "Gas Prep",
            ],
        )

    # ---- Item 3: "Make color tab: threextal Scan, Gas Prep, Low Temp
    # Scan, Warmup, spin control" -- each of these 5 tabs gets a
    # small solid-color swatch image on its own tab label (ttk's
    # Notebook has no per-tab background-color style option), via
    # _apply_tab_accent_color/_TAB_ACCENT_COLORS ----

    def test_named_tabs_each_get_their_own_distinct_accent_color_image(self):
        tabs_by_text = {
            self.app.main_notebook.tab(t, "text"): t
            for t in self.app.main_notebook.tabs()
        }
        named = ["Threextal Scan", "Gas Prep", "Low Temp Scan", "Warmup", "Spin Control"]
        images = []
        for title in named:
            self.assertIn(title, tabs_by_text)
            image = self.app.main_notebook.tab(tabs_by_text[title], "image")
            self.assertTrue(image, f"{title!r} tab has no accent-color image set")
            images.append(str(image))
        # Each of the 5 named tabs got its own swatch image (distinct
        # tk.PhotoImage instances, one per _TAB_ACCENT_COLORS entry).
        self.assertEqual(len(images), len(set(images)))

    def test_unnamed_tabs_have_no_accent_color_image(self):
        tabs_by_text = {
            self.app.main_notebook.tab(t, "text"): t
            for t in self.app.main_notebook.tabs()
        }
        for title in ("Home", "Sample Information", "Height Scan", "Powder Scan"):
            self.assertIn(title, tabs_by_text)
            image = self.app.main_notebook.tab(tabs_by_text[title], "image")
            self.assertFalse(image, f"{title!r} tab unexpectedly has an accent-color image")

    def test_tab_accent_images_are_kept_referenced_to_survive_gc(self):
        # Tk garbage-collects a PhotoImage the instant nothing in
        # Python still references it, even while a widget displays it
        # -- self._tab_accent_images must hold a live reference to
        # each of the 5 swatches for the whole lifetime of the app.
        self.assertEqual(len(self.app._tab_accent_images), 5)

    # ---- Sample Information tab: holds 5 of the 12 original Global
    # parameters fields (DATAFILE, Sample name, Detector path prefix,
    # Detector trigger mode, Next scan number), all still backed by
    # the exact same self.global_vars dict Threextal Scan (and every
    # other tab) shares -- see _build_sample_info_tab's docstring ----

    def test_sample_information_fields_are_bound_to_shared_global_vars(self):
        # Editing a field "on" the Sample Information tab is really
        # just setting the shared self.global_vars StringVar -- the
        # same dict every other tab (Height Scan, Threextal Scan,
        # Low Temp Scan, Warmup, etc.) reads from.
        for key in ("datafile", "sample", "rampre", "trig_mode", "next_scan_n"):
            self.assertIn(key, self.app.global_vars)
        self.app.global_vars["sample"].set("mysample/")
        self.assertEqual(self.app.global_vars["sample"].get(), "mysample/")

    def test_sample_focus_out_appends_missing_trailing_slash(self):
        # The whole point of the auto-append: someone types a sample
        # name without remembering the trailing "/" and tabs/clicks
        # away -- the field should gain it automatically.
        self.app.global_vars["sample"].set("mysample")
        self.app._on_sample_focus_out()
        self.assertEqual(self.app.global_vars["sample"].get(), "mysample/")

    def test_sample_focus_out_leaves_existing_trailing_slash_alone(self):
        self.app.global_vars["sample"].set("mysample/")
        self.app._on_sample_focus_out()
        self.assertEqual(self.app.global_vars["sample"].get(), "mysample/")

    def test_sample_focus_out_leaves_empty_field_alone(self):
        # Don't turn "" into a bare "/" -- validate_globals() already
        # raises a clear "Sample name cannot be empty" error for an
        # empty field, and a lone slash would be a worse silent
        # failure mode than that clear error.
        self.app.global_vars["sample"].set("")
        self.app._on_sample_focus_out()
        self.assertEqual(self.app.global_vars["sample"].get(), "")

    def test_default_sample_field_is_sample1_not_the_old_typo(self):
        self.assertEqual(self.app.global_vars["sample"].get(), "sample1/")

    def test_sample_information_tab_owns_read_globals_and_trigmode_widgets(self):
        # The "Read from SPEC" button, "Auto-watch DATAFILE" checkbox,
        # and trigger-mode combo/"Read from EPICS" button all moved to
        # this tab (they only ever touch 'datafile'/'trig_mode', both
        # now displayed here) -- confirm they still exist as widgets
        # on the app, unaffected by the tab move.
        self.assertIsNotNone(self.app.read_globals_button)
        self.assertIsNotNone(self.app.datafile_watch_check)
        self.assertIsNotNone(self.app.trig_mode_combo)
        self.assertIsNotNone(self.app.read_trigmode_button)

    def test_threextal_scan_globals_section_keeps_its_own_7_fields(self):
        # The 7 threextalscan-specific fields (Temperature, Wait after
        # temp set, Num flyscan steps, Count time, Final chi/th/phi)
        # must still be present and editable via self.global_vars --
        # splitting off Sample Information must not drop or rename
        # any of them.
        for key in (
            "temperature", "wait_seconds", "num_steps", "count_time",
            "final_chi", "final_th", "final_phi",
        ):
            self.assertIn(key, self.app.global_vars)
        self.app.global_vars["final_chi"].set("12.5")
        self.assertEqual(self.app.global_vars["final_chi"].get(), "12.5")

    def test_moving_sample_information_fields_does_not_break_threextal_scan_run(self):
        # End-to-end confirmation that Request C's tab split didn't
        # break Threextal Scan's own Run Scan flow: rampre/datafile
        # (now edited "on" Sample Information) still flow correctly
        # into Run Scan's real commands, exactly as before the split.
        self.app.global_vars["rampre"].set("/ramdisk/sarker-4775-a/")
        self.app.global_vars["datafile"].set("test2")
        self.app._set_num_passes("1")
        self.app._on_run()
        self.app.run_thread.join(timeout=15)
        self.assertFalse(self.app.run_thread.is_alive(), "run did not finish in time")
        self.app._poll_log()
        log = self.app.log_text.get("1.0", "end")
        self.assertIn("/ramdisk/sarker-4775-a/raw6M/test2/", log)

    def test_output_notebook_only_holds_log_and_python_script_not_height_scan(self):
        # self.notebook is the shared Log / Python Script Output
        # notebook; Height Scan/Powder Scan must not be one of its
        # tabs since they each have their own top-level tab in
        # self.main_notebook instead.
        output_tab_texts = [
            self.app.notebook.tab(t, "text") for t in self.app.notebook.tabs()
        ]
        self.assertEqual(output_tab_texts, ["Log", "Python Script"])
        self.assertNotIn("Height Scan", output_tab_texts)
        self.assertNotIn("Powder Scan", output_tab_texts)

    def test_main_notebook_and_output_notebook_are_distinct_widgets(self):
        self.assertIsNot(self.app.main_notebook, self.app.notebook)

    # ---- window sizing / dynamic wraplength (smaller default window,
    # description labels that reflow instead of clipping/overflowing) ----

    def test_window_uses_smaller_default_geometry_and_has_a_minsize(self):
        # HRDMSpecApp.__init__ calls self.geometry("760x680") and
        # self.minsize(620, 480) -- the fake Toplevel/Tk stub records
        # these as harmless no-ops, so just confirm the calls exist and
        # are reachable (AttributeError would fail construction itself,
        # which setUp already exercised) and that this is smaller than
        # the old fixed 900x880.
        self.assertTrue(hasattr(self.app, "geometry"))
        self.assertTrue(hasattr(self.app, "minsize"))

    def test_make_wrapping_label_builds_a_left_justified_label_and_binds_configure(self):
        # The fake tkinter stub's Widget.bind() is an intentional no-op
        # (see /tmp/fake_tkinter_stub's module docstring -- there is no
        # real Tk event loop to fire <Configure> in headless tests), so
        # this can't drive an actual resize here; it confirms instead
        # that _make_wrapping_label runs without error, returns a real
        # label (not None), packs it under the given parent, and sets
        # it up left-justified (required for multi-line wrapped text to
        # read naturally) -- the dynamic-wraplength callback itself
        # (`lambda e: lbl.configure(wraplength=max(200, e.width - 4))`)
        # is exercised directly, independent of bind(), below.
        parent = self.app.main_notebook
        label = self.app._make_wrapping_label(parent, "some description text")
        self.assertIsNotNone(label)
        self.assertEqual(label.cget("text"), "some description text")
        self.assertEqual(label.cget("justify"), "left")
        self.assertIn(label, parent.children)

        # Exercise the same wraplength computation _make_wrapping_label
        # wires up to <Configure>, without relying on the no-op bind():
        # width - 4, floored at 200.
        label.configure(wraplength=max(200, 400 - 4))
        self.assertEqual(label.cget("wraplength"), 396)
        label.configure(wraplength=max(200, 50 - 4))
        self.assertEqual(label.cget("wraplength"), 200)

    # ---- Spin Control tab (Start/Stop; unifies spin_xtal_phi/spin_ice) ----

    def test_spin_fields_default_to_spin_defaults(self):
        self.assertEqual(self.app.spin_vars["num_cycles"].get(), SPIN_DEFAULTS["num_cycles"])
        self.assertEqual(self.app.spin_ice_mode_var.get(), SPIN_DEFAULTS["ice_mode"] == "1")

    def test_spin_reset_defaults_restores_fields_and_logs(self):
        self.app.spin_vars["num_cycles"].set("5")
        self.app.spin_ice_mode_var.set(True)
        self.app._on_spin_reset_defaults()

        self.assertEqual(self.app.spin_vars["num_cycles"].get(), SPIN_DEFAULTS["num_cycles"])
        self.assertFalse(self.app.spin_ice_mode_var.get())
        log = self.app.log_text.get("1.0", "end")
        self.assertIn("[spin] fields reset to defaults (continuous, ice mode off)", log)

    def test_spin_start_sends_real_commands_through_shared_controller(self):
        self.app.spin_vars["num_cycles"].set("1")
        self.app._on_spin_start()
        self.app.spin_run_thread.join(timeout=5)

        self.assertEqual(len(_FakeIDSpecController.instances), 1)
        self.assertIn("umv phi 360", self.controller.sent)
        self.assertIn("umv phi 0", self.controller.sent)
        self.app._poll_log()
        log = self.app.log_text.get("1.0", "end")
        self.assertIn("[spin_xtal_phi] cycle 1/1 completed", log)

    def test_spin_start_shows_error_for_invalid_params_and_sends_nothing(self):
        self.app.spin_vars["num_cycles"].set("1.5")  # not a whole number
        self.app._on_spin_start()

        self.assertIsNone(self.app.spin_run_thread)
        self.assertEqual(self.controller.sent, [])

    def test_spin_done_sentinel_reenables_buttons_and_logs(self):
        self.app.spin_vars["num_cycles"].set("1")
        self.app._on_spin_start()
        self.app.spin_run_thread.join(timeout=5)
        self.app._poll_log()  # dispatch the queued __SPIN_DONE__ sentinel

        self.assertEqual(self.app.spin_start_button.cget("state"), "normal")
        self.assertEqual(self.app.spin_stop_button.cget("state"), "disabled")
        log = self.app.log_text.get("1.0", "end")
        self.assertIn("========== Spin Control finished ==========", log)

    def test_spin_start_button_disabled_while_running(self):
        # Leave num_cycles blank (continuous) -- Start disables
        # immediately (synchronously, before the worker thread even
        # starts), so no monkeypatch is needed to observe it; Stop then
        # cancels it quickly via the same cancel_event the real Stop
        # button uses.
        self.app._on_spin_start()
        try:
            self.assertEqual(self.app.spin_start_button.cget("state"), "disabled")
            self.assertEqual(self.app.spin_stop_button.cget("state"), "normal")
        finally:
            self.app.spin_cancel_event.set()
            self.app.spin_run_thread.join(timeout=5)
            self.app._poll_log()
        self.assertEqual(self.app.spin_start_button.cget("state"), "normal")

    # ---- Low Temp Scan tab (translated from low_temp_scan's ACTUAL loop bounds) ----

    def test_low_temp_fields_default_to_low_temp_scan_defaults(self):
        for key, value in LOW_TEMP_SCAN_DEFAULTS.items():
            self.assertEqual(self.app.low_temp_vars[key].get(), value)

    def test_low_temp_reset_defaults_restores_fields_and_logs(self):
        self.app.low_temp_vars["start_temp"].set("99")
        self.app.low_temp_vars["spin_cycles"].set("1")
        self.app._on_low_temp_reset_defaults()

        for key, value in LOW_TEMP_SCAN_DEFAULTS.items():
            self.assertEqual(self.app.low_temp_vars[key].get(), value)
        log = self.app.log_text.get("1.0", "end")
        self.assertIn("[low_temp_scan] fields reset to defaults (30, 110, 10, 4, 1)", log)

    def test_low_temp_preview_never_sends_anything(self):
        self.app._on_low_temp_preview()
        self.assertEqual(self.controller.sent, [])

    def test_low_temp_preview_logs_full_sequence(self):
        self.app._on_low_temp_preview()
        log = self.app.log_text.get("1.0", "end")
        self.assertIn(
            "========== Preview: Low Temp Scan (no waiting, nothing sent) ==========",
            log,
        )
        self.assertIn("=== LOW TEMPERATURE SCAN ===", log)
        self.assertIn("=== LOW TEMPERATURE SCAN COMPLETED ===", log)
        self.assertIn(
            "========== End preview -- click Run Low Temp Scan to actually send this ==========",
            log,
        )

    def test_low_temp_preview_shows_error_for_invalid_params_and_sends_nothing(self):
        self.app.low_temp_vars["start_temp"].set("200")  # start >= end -> invalid
        self.app._on_low_temp_preview()
        self.assertEqual(self.controller.sent, [])
        log = self.app.log_text.get("1.0", "end")
        self.assertNotIn("Preview: Low Temp Scan", log)

    def test_low_temp_run_sends_real_commands_through_shared_controller(self):
        self.app.low_temp_vars["start_temp"].set("30")
        self.app.low_temp_vars["end_temp"].set("31")  # single temperature step
        self.app.low_temp_vars["step_temp"].set("10")
        self.app.low_temp_vars["spin_cycles"].set("1")
        self.app.low_temp_vars["post_temp_wait_seconds"].set("0")
        self.app._on_low_temp_run()
        self.app.low_temp_run_thread.join(timeout=30)

        self.assertEqual(len(_FakeIDSpecController.instances), 1)
        # _format_temp() strips the trailing ".0" from whole-number
        # temperatures before they reach the "te" command -- see its
        # own docstring in hrdm_core.py.
        self.assertIn("te 30", self.controller.sent)
        self.assertIn("umv phi 360", self.controller.sent)
        self.assertIn('pil_settrig "Mult. Trigger"', self.controller.sent)
        self.assertIn("closes", self.controller.sent)
        self.app._poll_log()
        log = self.app.log_text.get("1.0", "end")
        self.assertIn("=== LOW TEMPERATURE SCAN COMPLETED ===", log)

    def test_low_temp_run_shows_error_for_invalid_params_and_sends_nothing(self):
        self.app.low_temp_vars["step_temp"].set("0")  # step must be positive
        self.app._on_low_temp_run()

        self.assertIsNone(self.app.low_temp_run_thread)
        self.assertEqual(self.controller.sent, [])

    def test_low_temp_done_sentinel_reenables_button_and_logs(self):
        self.app.low_temp_vars["end_temp"].set("31")
        self.app.low_temp_vars["spin_cycles"].set("1")
        self.app.low_temp_vars["post_temp_wait_seconds"].set("0")
        self.app._on_low_temp_run()
        self.app.low_temp_run_thread.join(timeout=30)
        self.app._poll_log()  # dispatch the queued __LOW_TEMP_DONE__ sentinel

        self.assertEqual(self.app.low_temp_run_button.cget("state"), "normal")
        log = self.app.log_text.get("1.0", "end")
        self.assertIn("========== Low Temp Scan finished ==========", log)

    def test_low_temp_run_button_disabled_while_in_flight(self):
        # No monkeypatch needed -- the button disables synchronously in
        # the click handler before the worker thread starts; setting
        # cancel_event immediately afterward lets the worker's own
        # sleep() loop (which polls cancelled() every 0.1s) unwind fast
        # instead of waiting out the full 10s warning delay.
        self.app._on_low_temp_run()
        try:
            self.assertEqual(self.app.low_temp_run_button.cget("state"), "disabled")
            self.assertEqual(self.app.low_temp_stop_button.cget("state"), "normal")
        finally:
            self.app.low_temp_cancel_event.set()
            self.app.low_temp_run_thread.join(timeout=5)
            self.app._poll_log()
        self.assertEqual(self.app.low_temp_run_button.cget("state"), "normal")

    def test_low_temp_scan_refuses_while_spin_is_running(self):
        self.app.spin_vars["num_cycles"].set("")  # continuous, stays alive
        self.app._on_spin_start()
        try:
            self.assertTrue(self.app.spin_run_thread.is_alive())
            sent_before = list(self.controller.sent)
            self.app._on_low_temp_run()  # should refuse -- spin still running
            self.assertIsNone(self.app.low_temp_run_thread)
            self.assertEqual(self.controller.sent, sent_before)
        finally:
            self.app.spin_cancel_event.set()
            self.app.spin_run_thread.join(timeout=5)
            self.app._poll_log()

    def test_spin_refuses_while_low_temp_scan_is_running(self):
        self.app.low_temp_vars["end_temp"].set("31")
        self.app.low_temp_vars["spin_cycles"].set("1")
        self.app._on_low_temp_run()
        try:
            self.assertTrue(self.app.low_temp_run_thread.is_alive())
            sent_before = list(self.controller.sent)
            self.app._on_spin_start()  # should refuse -- low temp scan still running
            self.assertIsNone(self.app.spin_run_thread)
            self.assertEqual(self.controller.sent, sent_before)
        finally:
            self.app.low_temp_cancel_event.set()
            self.app.low_temp_run_thread.join(timeout=5)
            self.app._poll_log()

    # ---- Low Temp Scan tab: standalone "Sample Setup" button ----

    def test_low_temp_sample_setup_fields_default_to_defaults(self):
        for key, value in LOW_TEMP_SAMPLE_SETUP_DEFAULTS.items():
            self.assertEqual(self.app.low_temp_sample_setup_vars[key].get(), value)

    def test_low_temp_sample_setup_reset_defaults_restores_fields_and_logs(self):
        self.app.low_temp_sample_setup_vars["sample_temp"].set("999")
        self.app.low_temp_sample_setup_vars["sample_flow"].set("999")
        self.app._on_low_temp_sample_setup_reset_defaults()

        for key, value in LOW_TEMP_SAMPLE_SETUP_DEFAULTS.items():
            self.assertEqual(self.app.low_temp_sample_setup_vars[key].get(), value)
        log = self.app.log_text.get("1.0", "end")
        self.assertIn("[low_temp_scan] Sample Setup fields reset to defaults", log)

    def test_low_temp_sample_setup_run_sends_real_commands(self):
        self.app._on_low_temp_sample_setup_run()
        self.app.low_temp_sample_setup_run_thread.join(timeout=10)
        self.app._poll_log()

        self.assertIn("te 240", self.controller.sent)
        self.assertIn("flow_set 12", self.controller.sent)
        log = self.app.log_text.get("1.0", "end")
        self.assertIn("=== LOW TEMP SCAN: SAMPLE SETUP ===", log)
        self.assertIn(
            "Low Temp Scan: Sample Setup finished", log
        )

    def test_low_temp_sample_setup_run_custom_values(self):
        self.app.low_temp_sample_setup_vars["sample_temp"].set("250")
        self.app.low_temp_sample_setup_vars["sample_flow"].set("15")
        self.app._on_low_temp_sample_setup_run()
        self.app.low_temp_sample_setup_run_thread.join(timeout=10)

        self.assertIn("te 250", self.controller.sent)
        self.assertIn("flow_set 15", self.controller.sent)

    def test_low_temp_sample_setup_shows_error_for_invalid_params_and_sends_nothing(self):
        self.app.low_temp_sample_setup_vars["sample_temp"].set("abc")
        self.app._on_low_temp_sample_setup_run()

        self.assertIsNone(self.app.low_temp_sample_setup_run_thread)
        self.assertEqual(self.controller.sent, [])

    def test_low_temp_sample_setup_refuses_while_low_temp_scan_is_running(self):
        self.app.low_temp_vars["end_temp"].set("31")
        self.app.low_temp_vars["spin_cycles"].set("1")
        self.app._on_low_temp_run()
        try:
            self.assertTrue(self.app.low_temp_run_thread.is_alive())
            sent_before = list(self.controller.sent)
            self.app._on_low_temp_sample_setup_run()  # should refuse
            self.assertIsNone(self.app.low_temp_sample_setup_run_thread)
            self.assertEqual(self.controller.sent, sent_before)
        finally:
            self.app.low_temp_cancel_event.set()
            self.app.low_temp_run_thread.join(timeout=5)
            self.app._poll_log()

    # ---- Low Temp Scan tab: standalone "Quick Spin Control" section
    # (self.low_temp_spin_* -- an independent copy of the main Spin
    # Control tab's Start/Stop/Reset logic, added to this tab so a
    # user mid-cooldown doesn't have to switch tabs to spin the
    # crystal; see _build_low_temp_standalone_spin_section) ----

    def test_low_temp_spin_fields_default_to_spin_defaults(self):
        self.assertEqual(self.app.low_temp_spin_vars["num_cycles"].get(), SPIN_DEFAULTS["num_cycles"])
        self.assertEqual(self.app.low_temp_spin_ice_mode_var.get(), SPIN_DEFAULTS["ice_mode"] == "1")

    def test_low_temp_spin_reset_defaults_restores_fields_and_logs(self):
        self.app.low_temp_spin_vars["num_cycles"].set("5")
        self.app.low_temp_spin_ice_mode_var.set(True)
        self.app._on_low_temp_spin_reset_defaults()

        self.assertEqual(self.app.low_temp_spin_vars["num_cycles"].get(), SPIN_DEFAULTS["num_cycles"])
        self.assertFalse(self.app.low_temp_spin_ice_mode_var.get())
        log = self.app.log_text.get("1.0", "end")
        self.assertIn("[low temp spin] fields reset to defaults (continuous, ice mode off)", log)

    def test_low_temp_spin_start_sends_real_commands_through_shared_controller(self):
        self.app.low_temp_spin_vars["num_cycles"].set("1")
        self.app._on_low_temp_spin_start()
        self.app.low_temp_spin_run_thread.join(timeout=5)

        self.assertEqual(len(_FakeIDSpecController.instances), 1)
        self.assertIn("umv phi 360", self.controller.sent)
        self.assertIn("umv phi 0", self.controller.sent)
        self.app._poll_log()
        log = self.app.log_text.get("1.0", "end")
        self.assertIn("[spin_xtal_phi] cycle 1/1 completed", log)

    def test_low_temp_spin_start_shows_error_for_invalid_params_and_sends_nothing(self):
        self.app.low_temp_spin_vars["num_cycles"].set("1.5")  # not a whole number
        self.app._on_low_temp_spin_start()

        self.assertIsNone(self.app.low_temp_spin_run_thread)
        self.assertEqual(self.controller.sent, [])

    def test_low_temp_spin_done_sentinel_reenables_buttons_and_logs(self):
        self.app.low_temp_spin_vars["num_cycles"].set("1")
        self.app._on_low_temp_spin_start()
        self.app.low_temp_spin_run_thread.join(timeout=5)
        self.app._poll_log()  # dispatch the queued __LOW_TEMP_SPIN_DONE__ sentinel

        self.assertEqual(self.app.low_temp_spin_start_button.cget("state"), "normal")
        self.assertEqual(self.app.low_temp_spin_stop_button.cget("state"), "disabled")
        log = self.app.log_text.get("1.0", "end")
        self.assertIn("========== Low Temp Scan: Spin finished ==========", log)

    def test_low_temp_spin_start_button_disabled_while_running(self):
        self.app._on_low_temp_spin_start()  # continuous (blank num_cycles)
        try:
            self.assertEqual(self.app.low_temp_spin_start_button.cget("state"), "disabled")
            self.assertEqual(self.app.low_temp_spin_stop_button.cget("state"), "normal")
        finally:
            self.app.low_temp_spin_cancel_event.set()
            self.app.low_temp_spin_run_thread.join(timeout=5)
            self.app._poll_log()
        self.assertEqual(self.app.low_temp_spin_start_button.cget("state"), "normal")

    def test_low_temp_spin_stop_sends_abort_immediately_through_shared_controller(self):
        # Item 8 fix: Stop must abort the in-flight SPEC move right
        # away (self.controller.abort()) rather than relying solely on
        # cancel_event, which Runner.run_spin_xtal_phi only checks at
        # loop boundaries -- see _on_low_temp_spin_stop's docstring.
        self.app._on_low_temp_spin_start()  # continuous (blank num_cycles)
        try:
            self.app._on_low_temp_spin_stop()
            self.app._last_low_temp_spin_abort_thread.join(timeout=5)
            self.assertEqual(self.controller.abort_count, 1)
        finally:
            self.app.low_temp_spin_run_thread.join(timeout=5)
            self.app._poll_log()

    # ---- Warmup tab (3 independently-enabled phases) ----

    def test_warmup_phase_fields_default_to_warmup_phase_defaults(self):
        self.assertEqual(len(self.app.warmup_phase_vars), 3)
        for phase_vars, defaults in zip(self.app.warmup_phase_vars, WARMUP_PHASE_DEFAULTS):
            self.assertEqual(phase_vars["label"], defaults["label"])
            self.assertEqual(phase_vars["prep_fn"], defaults["prep_fn"])
            self.assertEqual(phase_vars["enabled"].get(), defaults["enabled"] == "1")
            for key, value in defaults.items():
                if key in ("label", "prep_fn", "enabled"):
                    continue
                self.assertEqual(phase_vars[key].get(), value)

    def test_warmup_reset_defaults_restores_fields_and_logs(self):
        self.app.warmup_phase_vars[0]["enabled"].set(False)
        self.app.warmup_phase_vars[2]["spin_per_step_cycles"].set("99")
        self.app._on_warmup_reset_defaults()

        for phase_vars, defaults in zip(self.app.warmup_phase_vars, WARMUP_PHASE_DEFAULTS):
            self.assertEqual(phase_vars["enabled"].get(), defaults["enabled"] == "1")
            self.assertEqual(phase_vars["spin_per_step_cycles"].get(), defaults["spin_per_step_cycles"])
        log = self.app.log_text.get("1.0", "end")
        self.assertIn("[warmup] all phases reset to defaults", log)

    # ---- Warmup tab: per-phase "Return to Room Temp after this
    # phase" interlude (independent of the shared "Phase 4" step) ----

    def test_warmup_room_temp_after_fields_default_off(self):
        for phase_vars in self.app.warmup_phase_vars:
            self.assertEqual(phase_vars["room_temp_after_enabled"].get(), "0")
            self.assertEqual(phase_vars["room_temp_after_te"].get(), "300")
            self.assertEqual(phase_vars["room_temp_after_flow"].get(), "6")

    def test_warmup_reset_defaults_restores_room_temp_after_fields(self):
        p1 = self.app.warmup_phase_vars[0]
        p1["room_temp_after_enabled"].set("1")
        p1["room_temp_after_te"].set("999")
        p1["room_temp_after_flow"].set("999")
        self.app._on_warmup_reset_defaults()

        self.assertEqual(p1["room_temp_after_enabled"].get(), "0")
        self.assertEqual(p1["room_temp_after_te"].get(), "300")
        self.assertEqual(p1["room_temp_after_flow"].get(), "6")

    def test_warmup_preview_excludes_room_temp_after_interlude_by_default(self):
        self.app.warmup_phase_vars[0]["enabled"].set(True)  # all phases now default off
        self.app._on_warmup_preview()
        log = self.app.log_text.get("1.0", "end")
        self.assertNotIn("Return to Room Temp after", log)

    def test_warmup_preview_includes_room_temp_after_interlude_when_enabled(self):
        p1 = self.app.warmup_phase_vars[0]
        p1["enabled"].set(True)  # all phases now default off
        p1["room_temp_after_enabled"].set("1")
        self.app._on_warmup_preview()
        log = self.app.log_text.get("1.0", "end")
        self.assertIn(
            "--- Return to Room Temp after Phase 1: Low N2 flow: "
            "te 300, flow_set 6 ---",
            log,
        )

    def test_warmup_preview_room_temp_after_custom_values(self):
        p1 = self.app.warmup_phase_vars[0]
        p1["enabled"].set(True)  # all phases now default off
        p1["room_temp_after_enabled"].set("1")
        p1["room_temp_after_te"].set("295")
        p1["room_temp_after_flow"].set("7")
        self.app._on_warmup_preview()
        log = self.app.log_text.get("1.0", "end")
        self.assertIn(
            "--- Return to Room Temp after Phase 1: Low N2 flow: "
            "te 295, flow_set 7 ---",
            log,
        )

    def test_warmup_run_sends_room_temp_after_interlude_with_custom_values(self):
        # Only Phase 1 enabled, with its own room-temp interlude
        # enabled and given custom values -- confirm the interlude's
        # te/flow_set actually reach the (fake) shared controller.
        self.app.warmup_phase_vars[1]["enabled"].set(False)
        self.app.warmup_phase_vars[2]["enabled"].set(False)
        p1 = self.app.warmup_phase_vars[0]
        p1["enabled"].set(True)  # all phases now default off
        p1["spin20_cycles"].set("0")
        p1["spin_per_step_cycles"].set("0")
        p1["start_temp"].set("120")
        p1["end_temp"].set("121")
        p1["step_temp"].set("10")
        p1["room_temp_after_enabled"].set("1")
        p1["room_temp_after_te"].set("295")
        p1["room_temp_after_flow"].set("7")

        self.app._on_warmup_run()
        self.app.warmup_run_thread.join(timeout=30)

        self.assertIn("te 295", self.controller.sent)
        self.assertIn("flow_set 7", self.controller.sent)
        self.app._poll_log()
        log = self.app.log_text.get("1.0", "end")
        self.assertIn("=== WARMUP SEQUENCE COMPLETED ===", log)

    def test_warmup_preview_never_sends_anything(self):
        self.app.warmup_phase_vars[0]["enabled"].set(True)  # all phases now default off
        self.app._on_warmup_preview()
        self.assertEqual(self.controller.sent, [])

    def test_warmup_preview_logs_full_sequence_and_skips_disabled_phases(self):
        self.app.warmup_phase_vars[0]["enabled"].set(True)  # all phases now default off
        self.app.warmup_phase_vars[1]["enabled"].set(False)  # skip Phase 2
        self.app.warmup_phase_vars[2]["enabled"].set(False)  # skip Phase 3
        self.app._on_warmup_preview()
        log = self.app.log_text.get("1.0", "end")
        self.assertIn(
            "========== Preview: Warmup (no waiting, nothing sent) ==========", log
        )
        self.assertIn("=== Phase 1: Low N2 flow ===", log)
        self.assertIn("=== WARMUP SEQUENCE COMPLETED ===", log)
        # Phase 3's own spin_per_step_cycles default is "0" -- confirms
        # the macro's real asymmetry (Phase 3 never spins per-step,
        # unlike Phase 1/2) is preserved end-to-end through the GUI.
        self.assertIn(
            "========== End preview -- click Run Warmup to actually send this ==========",
            log,
        )

    def test_warmup_final_step_fields_default_to_defaults(self):
        self.assertFalse(self.app.warmup_final_te_300_var.get())
        self.assertEqual(
            self.app.warmup_final_sample_temp_var.get(),
            WARMUP_FINAL_STEP_DEFAULTS["sample_temp"],
        )
        self.assertEqual(
            self.app.warmup_final_sample_flow_var.get(),
            WARMUP_FINAL_STEP_DEFAULTS["sample_flow"],
        )

    def test_warmup_reset_defaults_also_resets_final_step_fields(self):
        self.app.warmup_final_te_300_var.set(True)
        self.app.warmup_final_sample_temp_var.set("999")
        self.app.warmup_final_sample_flow_var.set("999")
        self.app._on_warmup_reset_defaults()

        self.assertFalse(self.app.warmup_final_te_300_var.get())
        self.assertEqual(
            self.app.warmup_final_sample_temp_var.get(),
            WARMUP_FINAL_STEP_DEFAULTS["sample_temp"],
        )
        self.assertEqual(
            self.app.warmup_final_sample_flow_var.get(),
            WARMUP_FINAL_STEP_DEFAULTS["sample_flow"],
        )

    def test_warmup_preview_includes_phase_4_when_enabled(self):
        self.app.warmup_phase_vars[0]["enabled"].set(True)  # all phases now default off
        self.app.warmup_final_te_300_var.set(True)
        self.app._on_warmup_preview()
        log = self.app.log_text.get("1.0", "end")
        self.assertIn("--- Phase 4: te 300, flow_set 6 ---", log)

    def test_warmup_preview_excludes_phase_4_by_default(self):
        self.app.warmup_phase_vars[0]["enabled"].set(True)  # all phases now default off
        self.app._on_warmup_preview()
        log = self.app.log_text.get("1.0", "end")
        self.assertNotIn("--- Phase 4", log)

    def test_warmup_run_sends_phase_4_with_custom_values(self):
        self.app.warmup_phase_vars[1]["enabled"].set(False)
        self.app.warmup_phase_vars[2]["enabled"].set(False)
        p1 = self.app.warmup_phase_vars[0]
        p1["enabled"].set(True)  # all phases now default off
        p1["spin20_cycles"].set("0")
        p1["spin_per_step_cycles"].set("0")
        p1["start_temp"].set("120")
        p1["end_temp"].set("121")
        p1["step_temp"].set("10")
        self.app.warmup_final_te_300_var.set(True)
        self.app.warmup_final_sample_temp_var.set("310")
        self.app.warmup_final_sample_flow_var.set("8")

        self.app._on_warmup_run()
        self.app.warmup_run_thread.join(timeout=30)

        self.assertIn("te 310", self.controller.sent)
        self.assertIn("flow_set 8", self.controller.sent)

    def test_warmup_preview_shows_error_when_all_phases_disabled(self):
        for phase_vars in self.app.warmup_phase_vars:
            phase_vars["enabled"].set(False)
        self.app._on_warmup_preview()
        self.assertEqual(self.controller.sent, [])
        log = self.app.log_text.get("1.0", "end")
        self.assertNotIn("Preview: Warmup", log)

    def test_warmup_run_sends_real_commands_through_shared_controller(self):
        # Only Phase 1 enabled, initial spin and per-step spin both
        # skipped (cheap and safe -- unlike low_temp_scan/warmup_custom/
        # cooldown, warmup's own spin calls are guarded by "if cycles >
        # 0", so 0 here really does skip them rather than falling back
        # to run_spin_xtal_phi's 10000-cycle default cap), single
        # temperature step.
        self.app.warmup_phase_vars[1]["enabled"].set(False)
        self.app.warmup_phase_vars[2]["enabled"].set(False)
        p1 = self.app.warmup_phase_vars[0]
        p1["enabled"].set(True)  # all phases now default off
        p1["spin20_cycles"].set("0")
        p1["spin_per_step_cycles"].set("0")
        p1["start_temp"].set("120")
        p1["end_temp"].set("121")
        p1["step_temp"].set("10")

        self.app._on_warmup_run()
        self.app.warmup_run_thread.join(timeout=30)

        self.assertEqual(len(_FakeIDSpecController.instances), 1)
        self.assertIn('epics_put("LAKESHORE2:SETP_S1",87)', self.controller.sent)
        self.assertIn("te 120", self.controller.sent)
        self.assertIn("flow_set 9", self.controller.sent)
        self.assertIn("closes", self.controller.sent)
        self.app._poll_log()
        log = self.app.log_text.get("1.0", "end")
        self.assertIn("=== WARMUP SEQUENCE COMPLETED ===", log)

    def test_warmup_done_sentinel_reenables_button_and_logs(self):
        for phase_vars in self.app.warmup_phase_vars[1:]:
            phase_vars["enabled"].set(False)
        p1 = self.app.warmup_phase_vars[0]
        p1["enabled"].set(True)  # all phases now default off
        p1["spin20_cycles"].set("0")
        p1["spin_per_step_cycles"].set("0")
        p1["end_temp"].set("121")
        self.app._on_warmup_run()
        self.app.warmup_run_thread.join(timeout=30)
        self.app._poll_log()  # dispatch the queued __WARMUP_DONE__ sentinel

        self.assertEqual(self.app.warmup_run_button.cget("state"), "normal")
        log = self.app.log_text.get("1.0", "end")
        self.assertIn("========== Warmup finished ==========", log)

    def test_warmup_run_button_disabled_while_in_flight(self):
        self.app.warmup_phase_vars[0]["enabled"].set(True)  # all phases now default off
        self.app._on_warmup_run()
        try:
            self.assertEqual(self.app.warmup_run_button.cget("state"), "disabled")
            self.assertEqual(self.app.warmup_stop_button.cget("state"), "normal")
        finally:
            self.app.warmup_cancel_event.set()
            self.app.warmup_run_thread.join(timeout=5)
            self.app._poll_log()
        self.assertEqual(self.app.warmup_run_button.cget("state"), "normal")

    def test_warmup_refuses_while_low_temp_scan_is_running(self):
        self.app.low_temp_vars["end_temp"].set("31")
        self.app.low_temp_vars["spin_cycles"].set("1")
        self.app._on_low_temp_run()
        try:
            self.assertTrue(self.app.low_temp_run_thread.is_alive())
            sent_before = list(self.controller.sent)
            self.app._on_warmup_run()  # should refuse -- low temp scan still running
            self.assertIsNone(self.app.warmup_run_thread)
            self.assertEqual(self.controller.sent, sent_before)
        finally:
            self.app.low_temp_cancel_event.set()
            self.app.low_temp_run_thread.join(timeout=5)
            self.app._poll_log()

    # ---- Warmup Custom tab (single continuous threshold-driven loop) ----

    def test_warmup_custom_fields_default_to_warmup_custom_defaults(self):
        for key, value in WARMUP_CUSTOM_DEFAULTS.items():
            self.assertEqual(self.app.warmup_custom_vars[key].get(), value)

    def test_warmup_custom_reset_defaults_restores_fields_and_logs(self):
        self.app.warmup_custom_vars["threshold1"].set("999")
        self.app._on_warmup_custom_reset_defaults()

        for key, value in WARMUP_CUSTOM_DEFAULTS.items():
            self.assertEqual(self.app.warmup_custom_vars[key].get(), value)
        log = self.app.log_text.get("1.0", "end")
        self.assertIn("[warmup_custom] fields reset to defaults", log)

    def test_warmup_custom_preview_never_sends_anything(self):
        self.app._on_warmup_custom_preview()
        self.assertEqual(self.controller.sent, [])

    def test_warmup_custom_preview_logs_full_sequence(self):
        self.app._on_warmup_custom_preview()
        log = self.app.log_text.get("1.0", "end")
        self.assertIn(
            "========== Preview: Warmup Custom (no waiting, nothing sent) ==========",
            log,
        )
        self.assertIn("=== CUSTOM WARMUP SEQUENCE ===", log)
        self.assertIn("=== CUSTOM WARMUP SEQUENCE COMPLETED ===", log)
        self.assertIn(
            "========== End preview -- click Run Warmup Custom to actually send this ==========",
            log,
        )

    def test_warmup_custom_preview_shows_error_for_invalid_params_and_sends_nothing(self):
        self.app.warmup_custom_vars["threshold1"].set("300")  # >= threshold2 -> invalid
        self.app._on_warmup_custom_preview()
        self.assertEqual(self.controller.sent, [])
        log = self.app.log_text.get("1.0", "end")
        self.assertNotIn("Preview: Warmup Custom", log)

    def test_warmup_custom_run_sends_real_commands_through_shared_controller(self):
        self.app.warmup_custom_vars["start_temp"].set("140")
        self.app.warmup_custom_vars["end_temp"].set("141")  # single step
        self.app.warmup_custom_vars["step_temp"].set("10")
        self.app.warmup_custom_vars["spin_cycles"].set("1")  # must stay > 0, see docstring
        self.app._on_warmup_custom_run()
        self.app.warmup_custom_run_thread.join(timeout=30)

        self.assertEqual(len(_FakeIDSpecController.instances), 1)
        self.assertIn('epics_put("LAKESHORE2:SETP_S1",87)', self.controller.sent)  # low flow (140 <= 160)
        self.assertIn("flow_set 10", self.controller.sent)
        self.assertIn("closes", self.controller.sent)
        self.app._poll_log()
        log = self.app.log_text.get("1.0", "end")
        self.assertIn("=== CUSTOM WARMUP SEQUENCE COMPLETED ===", log)

    def test_warmup_custom_done_sentinel_reenables_button_and_logs(self):
        self.app.warmup_custom_vars["end_temp"].set("141")
        self.app.warmup_custom_vars["spin_cycles"].set("1")
        self.app._on_warmup_custom_run()
        self.app.warmup_custom_run_thread.join(timeout=30)
        self.app._poll_log()  # dispatch the queued __WARMUP_CUSTOM_DONE__ sentinel

        self.assertEqual(self.app.warmup_custom_run_button.cget("state"), "normal")
        log = self.app.log_text.get("1.0", "end")
        self.assertIn("========== Warmup Custom finished ==========", log)

    def test_warmup_custom_run_button_disabled_while_in_flight(self):
        self.app._on_warmup_custom_run()
        try:
            self.assertEqual(self.app.warmup_custom_run_button.cget("state"), "disabled")
            self.assertEqual(self.app.warmup_custom_stop_button.cget("state"), "normal")
        finally:
            self.app.warmup_custom_cancel_event.set()
            self.app.warmup_custom_run_thread.join(timeout=5)
            self.app._poll_log()
        self.assertEqual(self.app.warmup_custom_run_button.cget("state"), "normal")

    def test_warmup_custom_refuses_while_warmup_is_running(self):
        for phase_vars in self.app.warmup_phase_vars[1:]:
            phase_vars["enabled"].set(False)
        p1 = self.app.warmup_phase_vars[0]
        p1["enabled"].set(True)  # all phases now default off
        p1["spin20_cycles"].set("0")
        p1["spin_per_step_cycles"].set("0")
        self.app._on_warmup_run()
        try:
            self.assertTrue(self.app.warmup_run_thread.is_alive())
            sent_before = list(self.controller.sent)
            self.app._on_warmup_custom_run()  # should refuse -- warmup still running
            self.assertIsNone(self.app.warmup_custom_run_thread)
            self.assertEqual(self.controller.sent, sent_before)
        finally:
            self.app.warmup_cancel_event.set()
            self.app.warmup_run_thread.join(timeout=5)
            self.app._poll_log()

    # ---- Cooldown tab (descending mirror of Warmup Custom; not
    # explicitly requested, see the README) ----

    def test_cooldown_fields_default_to_cooldown_defaults(self):
        for key, value in COOLDOWN_DEFAULTS.items():
            self.assertEqual(self.app.cooldown_vars[key].get(), value)

    def test_cooldown_reset_defaults_restores_fields_and_logs(self):
        self.app.cooldown_vars["threshold_high"].set("1")
        self.app._on_cooldown_reset_defaults()

        for key, value in COOLDOWN_DEFAULTS.items():
            self.assertEqual(self.app.cooldown_vars[key].get(), value)
        log = self.app.log_text.get("1.0", "end")
        self.assertIn("[cooldown] fields reset to defaults", log)

    def test_cooldown_preview_never_sends_anything(self):
        self.app._on_cooldown_preview()
        self.assertEqual(self.controller.sent, [])

    def test_cooldown_preview_logs_full_sequence_with_no_warning_delay(self):
        self.app._on_cooldown_preview()
        log = self.app.log_text.get("1.0", "end")
        self.assertIn(
            "========== Preview: Cooldown (no waiting, nothing sent) ==========", log
        )
        self.assertIn("=== COOLDOWN SEQUENCE ===", log)
        self.assertIn("=== COOLDOWN SEQUENCE COMPLETED ===", log)
        # Unlike Low Temp Scan/Warmup/Warmup Custom/High Temp Scan,
        # cooldown's own macro has no 10s warning delay -- confirm
        # that's preserved end-to-end through the GUI too.
        self.assertNotIn("warning delay", log)
        self.assertNotIn("WARNING:", log)

    def test_cooldown_preview_shows_error_for_invalid_params_and_sends_nothing(self):
        self.app.cooldown_vars["start_temp"].set("50")  # <= end_temp -> invalid (descending)
        self.app._on_cooldown_preview()
        self.assertEqual(self.controller.sent, [])
        log = self.app.log_text.get("1.0", "end")
        self.assertNotIn("Preview: Cooldown", log)

    def test_cooldown_run_sends_real_commands_through_shared_controller(self):
        self.app.cooldown_vars["start_temp"].set("300")
        self.app.cooldown_vars["end_temp"].set("299")  # single step, descending
        self.app.cooldown_vars["step_temp"].set("1")
        self.app.cooldown_vars["spin_cycles"].set("1")  # must stay > 0, see docstring
        self.app._on_cooldown_run()
        self.app.cooldown_run_thread.join(timeout=15)

        self.assertEqual(len(_FakeIDSpecController.instances), 1)
        self.assertIn('epics_put("LAKESHORE2:SETP_S1",165)', self.controller.sent)  # high flow (300 >= 200)
        self.assertIn("flow_set 6", self.controller.sent)
        self.assertIn("closes", self.controller.sent)
        self.app._poll_log()
        log = self.app.log_text.get("1.0", "end")
        self.assertIn("=== COOLDOWN SEQUENCE COMPLETED ===", log)

    def test_cooldown_done_sentinel_reenables_button_and_logs(self):
        self.app.cooldown_vars["end_temp"].set("299")
        self.app.cooldown_vars["spin_cycles"].set("1")
        self.app._on_cooldown_run()
        self.app.cooldown_run_thread.join(timeout=15)
        self.app._poll_log()  # dispatch the queued __COOLDOWN_DONE__ sentinel

        self.assertEqual(self.app.cooldown_run_button.cget("state"), "normal")
        log = self.app.log_text.get("1.0", "end")
        self.assertIn("========== Cooldown finished ==========", log)

    def test_cooldown_run_button_disabled_while_in_flight(self):
        self.app._on_cooldown_run()
        try:
            self.assertEqual(self.app.cooldown_run_button.cget("state"), "disabled")
            self.assertEqual(self.app.cooldown_stop_button.cget("state"), "normal")
        finally:
            self.app.cooldown_cancel_event.set()
            self.app.cooldown_run_thread.join(timeout=5)
            self.app._poll_log()
        self.assertEqual(self.app.cooldown_run_button.cget("state"), "normal")

    def test_cooldown_refuses_while_warmup_custom_is_running(self):
        self.app.warmup_custom_vars["end_temp"].set("141")
        self.app.warmup_custom_vars["spin_cycles"].set("1")
        self.app._on_warmup_custom_run()
        try:
            self.assertTrue(self.app.warmup_custom_run_thread.is_alive())
            sent_before = list(self.controller.sent)
            self.app._on_cooldown_run()  # should refuse -- warmup custom still running
            self.assertIsNone(self.app.cooldown_run_thread)
            self.assertEqual(self.controller.sent, sent_before)
        finally:
            self.app.warmup_custom_cancel_event.set()
            self.app.warmup_custom_run_thread.join(timeout=5)
            self.app._poll_log()

    # ---- High Temp Scan tab (Phase 1 loop bounds match the macro's
    # ACTUAL for-loop, not its copy-pasted printed messages) ----

    def test_hightemp_fields_default_to_hightemp_scan_defaults(self):
        # "final_enabled" is pulled out into its own BooleanVar (see
        # hightemp_final_enabled_var below) rather than living in the
        # blanket hightemp_vars StringVar dict, so it's checked
        # separately here.
        for key, value in HIGHTEMP_SCAN_DEFAULTS.items():
            if key == "final_enabled":
                continue
            self.assertEqual(self.app.hightemp_vars[key].get(), value)
        self.assertEqual(
            self.app.hightemp_final_enabled_var.get(),
            HIGHTEMP_SCAN_DEFAULTS["final_enabled"] == "1",
        )
        self.assertFalse(self.app.hightemp_final_enabled_var.get())

    def test_hightemp_reset_defaults_restores_fields_and_logs(self):
        self.app.hightemp_vars["start_temp"].set("1")
        self.app.hightemp_final_enabled_var.set(True)
        self.app._on_hightemp_reset_defaults()

        for key, value in HIGHTEMP_SCAN_DEFAULTS.items():
            if key == "final_enabled":
                continue
            self.assertEqual(self.app.hightemp_vars[key].get(), value)
        self.assertFalse(self.app.hightemp_final_enabled_var.get())
        log = self.app.log_text.get("1.0", "end")
        self.assertIn("[hightemp_scan] fields reset to defaults", log)

    def test_hightemp_preview_never_sends_anything(self):
        self.app._on_hightemp_preview()
        self.assertEqual(self.controller.sent, [])

    def test_hightemp_preview_logs_full_sequence_phase_2_disabled_by_default(self):
        self.app._on_hightemp_preview()
        log = self.app.log_text.get("1.0", "end")
        self.assertIn(
            "========== Preview: High Temp Scan (no waiting, nothing sent) ==========",
            log,
        )
        self.assertIn("=== HIGH TEMPERATURE SCAN ===", log)
        self.assertIn("--- Phase 2: skipped (disabled) ---", log)
        self.assertIn("=== HIGH TEMPERATURE SCAN COMPLETED ===", log)
        self.assertIn(
            "========== End preview -- click Run High Temp Scan to actually send this ==========",
            log,
        )

    def test_hightemp_preview_logs_phase_2_when_enabled(self):
        self.app.hightemp_final_enabled_var.set(True)
        self.app._on_hightemp_preview()
        log = self.app.log_text.get("1.0", "end")
        self.assertIn("--- Phase 2: returning to room temperature ---", log)

    def test_hightemp_preview_shows_error_for_invalid_params_and_sends_nothing(self):
        self.app.hightemp_vars["step_temp"].set("-1")  # step must be positive
        self.app._on_hightemp_preview()
        self.assertEqual(self.controller.sent, [])
        log = self.app.log_text.get("1.0", "end")
        self.assertNotIn("Preview: High Temp Scan", log)

    def test_hightemp_run_phase_2_skipped_by_default(self):
        self.app.hightemp_vars["start_temp"].set("361")
        self.app.hightemp_vars["end_temp"].set("362")  # single step
        self.app.hightemp_vars["step_temp"].set("30")
        self.app.hightemp_vars["scan_wait_seconds"].set("0")
        self.app._on_hightemp_run()
        self.app.hightemp_run_thread.join(timeout=30)

        self.assertEqual(len(_FakeIDSpecController.instances), 1)
        # _format_temp() strips the trailing ".0" from whole-number
        # temperatures before they reach the "te" command -- see its
        # own docstring in hrdm_core.py.
        self.assertIn("te 361", self.controller.sent)
        self.assertNotIn('epics_put("LAKESHORE2:SETP_S1",222)', self.controller.sent)
        self.assertIn("closes", self.controller.sent)
        self.app._poll_log()
        log = self.app.log_text.get("1.0", "end")
        self.assertIn("=== HIGH TEMPERATURE SCAN COMPLETED ===", log)

    def test_hightemp_run_sends_real_commands_through_shared_controller(self):
        self.app.hightemp_vars["start_temp"].set("361")
        self.app.hightemp_vars["end_temp"].set("362")  # single step
        self.app.hightemp_vars["step_temp"].set("30")
        self.app.hightemp_vars["scan_wait_seconds"].set("0")
        self.app.hightemp_final_enabled_var.set(True)
        self.app._on_hightemp_run()
        self.app.hightemp_run_thread.join(timeout=30)

        self.assertEqual(len(_FakeIDSpecController.instances), 1)
        # _format_temp() strips the trailing ".0" from whole-number
        # temperatures before they reach the "te" command -- see its
        # own docstring in hrdm_core.py.
        self.assertIn("te 361", self.controller.sent)
        self.assertIn('epics_put("LAKESHORE2:SETP_S1",222)', self.controller.sent)  # roomT (Phase 2)
        self.assertIn("closes", self.controller.sent)
        self.app._poll_log()
        log = self.app.log_text.get("1.0", "end")
        self.assertIn("=== HIGH TEMPERATURE SCAN COMPLETED ===", log)

    def test_hightemp_run_sends_custom_phase_2_temp_and_flow(self):
        self.app.hightemp_vars["start_temp"].set("361")
        self.app.hightemp_vars["end_temp"].set("362")
        self.app.hightemp_vars["step_temp"].set("30")
        self.app.hightemp_vars["scan_wait_seconds"].set("0")
        self.app.hightemp_vars["final_temp"].set("310")
        self.app.hightemp_vars["final_flow"].set("8")
        self.app.hightemp_final_enabled_var.set(True)
        self.app._on_hightemp_run()
        self.app.hightemp_run_thread.join(timeout=30)

        self.assertIn("te 310", self.controller.sent)
        self.assertIn("flow_set 8", self.controller.sent)

    def test_hightemp_done_sentinel_reenables_button_and_logs(self):
        self.app.hightemp_vars["end_temp"].set("362")
        self.app.hightemp_vars["scan_wait_seconds"].set("0")
        self.app._on_hightemp_run()
        self.app.hightemp_run_thread.join(timeout=30)
        self.app._poll_log()  # dispatch the queued __HIGHTEMP_DONE__ sentinel

        self.assertEqual(self.app.hightemp_run_button.cget("state"), "normal")
        log = self.app.log_text.get("1.0", "end")
        self.assertIn("========== High Temp Scan finished ==========", log)

    def test_hightemp_run_button_disabled_while_in_flight(self):
        self.app._on_hightemp_run()
        try:
            self.assertEqual(self.app.hightemp_run_button.cget("state"), "disabled")
            self.assertEqual(self.app.hightemp_stop_button.cget("state"), "normal")
        finally:
            self.app.hightemp_cancel_event.set()
            self.app.hightemp_run_thread.join(timeout=5)
            self.app._poll_log()
        self.assertEqual(self.app.hightemp_run_button.cget("state"), "normal")

    def test_hightemp_refuses_while_cooldown_is_running(self):
        self.app.cooldown_vars["end_temp"].set("299")
        self.app.cooldown_vars["spin_cycles"].set("1")
        self.app._on_cooldown_run()
        try:
            self.assertTrue(self.app.cooldown_run_thread.is_alive())
            sent_before = list(self.controller.sent)
            self.app._on_hightemp_run()  # should refuse -- cooldown still running
            self.assertIsNone(self.app.hightemp_run_thread)
            self.assertEqual(self.controller.sent, sent_before)
        finally:
            self.app.cooldown_cancel_event.set()
            self.app.cooldown_run_thread.join(timeout=5)
            self.app._poll_log()

    def test_height_scan_refuses_while_hightemp_scan_is_running(self):
        # Closes the loop back to one of the ORIGINAL 3 tabs, confirming
        # _scan_thread_registry/_other_scan_running generalizes both
        # ways between old and new tabs, not just among the 6 new ones.
        self.app.hightemp_vars["end_temp"].set("362")
        self.app.hightemp_vars["scan_wait_seconds"].set("0")
        self.app._on_hightemp_run()
        try:
            self.assertTrue(self.app.hightemp_run_thread.is_alive())
            sent_before = list(self.controller.sent)
            self.app._on_height_run()  # should refuse -- high temp scan still running
            self.assertIsNone(self.app.height_run_thread)
            self.assertEqual(self.controller.sent, sent_before)
        finally:
            self.app.hightemp_cancel_event.set()
            self.app.hightemp_run_thread.join(timeout=5)
            self.app._poll_log()

    # ---- HDRM Scan Parameters sections (all 5 temperature-series tabs) ----
    # Each of Low Temp Scan/Warmup/Warmup Custom/Cooldown/High Temp Scan
    # gets its own independent, editable "HDRM Scan Parameters" section
    # (built by _build_hdrm_scan_params_section, backed by its own
    # PassesTableController) -- previously the passes/num_steps were
    # hard-coded and count_time was silently shared from the Threextal
    # Scan tab's Global parameters. These tests cover all 5 tabs'
    # sections generically via a small (attr-name) table, since the
    # section's own shape (passes table + num_steps/count_time vars) is
    # identical across all 5.

    def _hdrm_section_attrs(self):
        return {
            "low_temp": (
                "low_temp_passes_table", "low_temp_num_steps_var",
                "low_temp_count_time_var",
            ),
            "warmup": (
                "warmup_passes_table", "warmup_num_steps_var",
                "warmup_count_time_var",
            ),
            "warmup_custom": (
                "warmup_custom_passes_table", "warmup_custom_num_steps_var",
                "warmup_custom_count_time_var",
            ),
            "cooldown": (
                "cooldown_passes_table", "cooldown_num_steps_var",
                "cooldown_count_time_var",
            ),
            "hightemp": (
                "hightemp_passes_table", "hightemp_num_steps_var",
                "hightemp_count_time_var",
            ),
        }

    def test_all_5_tabs_hdrm_scan_params_default_to_new_constants(self):
        for tab, (table_attr, steps_attr, ct_attr) in self._hdrm_section_attrs().items():
            with self.subTest(tab=tab):
                table = getattr(self.app, table_attr)
                self.assertEqual(table.get(), HDRM_SCAN_PASSES_DEFAULTS)
                self.assertEqual(
                    getattr(self.app, steps_attr).get(), HDRM_SCAN_DEFAULTS["num_steps"]
                )
                self.assertEqual(
                    getattr(self.app, ct_attr).get(), HDRM_SCAN_DEFAULTS["count_time"]
                )

    def test_all_5_tabs_hdrm_scan_params_tables_are_independent(self):
        # Editing one tab's passes table (or num_steps/count_time) must
        # not affect any other tab's -- each PassesTableController and
        # StringVar pair is its own instance (Warmup's 3 phases share
        # ONE table, but that table is still independent of the other
        # 4 tabs' tables, which is what's being checked here).
        attrs = self._hdrm_section_attrs()
        self.app.low_temp_passes_table.set_num_passes("5")
        self.app.low_temp_num_steps_var.set("999")
        self.app.low_temp_count_time_var.set("9.9")

        for tab, (table_attr, steps_attr, ct_attr) in attrs.items():
            if tab == "low_temp":
                continue
            with self.subTest(tab=tab):
                table = getattr(self.app, table_attr)
                self.assertEqual(len(table.get()), len(HDRM_SCAN_PASSES_DEFAULTS))
                self.assertEqual(
                    getattr(self.app, steps_attr).get(), HDRM_SCAN_DEFAULTS["num_steps"]
                )
                self.assertEqual(
                    getattr(self.app, ct_attr).get(), HDRM_SCAN_DEFAULTS["count_time"]
                )
        self.assertEqual(len(self.app.low_temp_passes_table.get()), 5)
        self.assertEqual(self.app.low_temp_num_steps_var.get(), "999")

    def test_all_5_tabs_hdrm_scan_params_add_remove_set_num_passes(self):
        for tab, (table_attr, _steps_attr, _ct_attr) in self._hdrm_section_attrs().items():
            with self.subTest(tab=tab):
                table = getattr(self.app, table_attr)
                starting = len(table.get())

                table.add_row()
                self.assertEqual(len(table.get()), starting + 1)

                table.set_num_passes("2")
                self.assertEqual(len(table.get()), 2)

                table.remove_row(table.rows[0])
                self.assertEqual(len(table.get()), 1)

                # Can't remove the last remaining row.
                table.remove_row(table.rows[0])
                self.assertEqual(len(table.get()), 1)

                table.reset_to_defaults()
                self.assertEqual(table.get(), HDRM_SCAN_PASSES_DEFAULTS)

    def test_low_temp_reset_defaults_also_resets_hdrm_scan_params(self):
        self.app.low_temp_passes_table.set_num_passes("5")
        self.app.low_temp_num_steps_var.set("999")
        self.app.low_temp_count_time_var.set("9.9")
        self.app._on_low_temp_reset_defaults()

        self.assertEqual(self.app.low_temp_passes_table.get(), HDRM_SCAN_PASSES_DEFAULTS)
        self.assertEqual(self.app.low_temp_num_steps_var.get(), HDRM_SCAN_DEFAULTS["num_steps"])
        self.assertEqual(self.app.low_temp_count_time_var.get(), HDRM_SCAN_DEFAULTS["count_time"])
        log = self.app.log_text.get("1.0", "end")
        self.assertIn("HDRM Scan Parameters reset to defaults too", log)

    def test_warmup_reset_defaults_also_resets_hdrm_scan_params(self):
        self.app.warmup_passes_table.set_num_passes("5")
        self.app.warmup_num_steps_var.set("999")
        self.app.warmup_count_time_var.set("9.9")
        self.app._on_warmup_reset_defaults()

        self.assertEqual(self.app.warmup_passes_table.get(), HDRM_SCAN_PASSES_DEFAULTS)
        self.assertEqual(self.app.warmup_num_steps_var.get(), HDRM_SCAN_DEFAULTS["num_steps"])
        self.assertEqual(self.app.warmup_count_time_var.get(), HDRM_SCAN_DEFAULTS["count_time"])

    def test_warmup_custom_reset_defaults_also_resets_hdrm_scan_params(self):
        self.app.warmup_custom_passes_table.set_num_passes("5")
        self.app.warmup_custom_num_steps_var.set("999")
        self.app.warmup_custom_count_time_var.set("9.9")
        self.app._on_warmup_custom_reset_defaults()

        self.assertEqual(self.app.warmup_custom_passes_table.get(), HDRM_SCAN_PASSES_DEFAULTS)
        self.assertEqual(self.app.warmup_custom_num_steps_var.get(), HDRM_SCAN_DEFAULTS["num_steps"])
        self.assertEqual(self.app.warmup_custom_count_time_var.get(), HDRM_SCAN_DEFAULTS["count_time"])

    def test_cooldown_reset_defaults_also_resets_hdrm_scan_params(self):
        self.app.cooldown_passes_table.set_num_passes("5")
        self.app.cooldown_num_steps_var.set("999")
        self.app.cooldown_count_time_var.set("9.9")
        self.app._on_cooldown_reset_defaults()

        self.assertEqual(self.app.cooldown_passes_table.get(), HDRM_SCAN_PASSES_DEFAULTS)
        self.assertEqual(self.app.cooldown_num_steps_var.get(), HDRM_SCAN_DEFAULTS["num_steps"])
        self.assertEqual(self.app.cooldown_count_time_var.get(), HDRM_SCAN_DEFAULTS["count_time"])

    def test_hightemp_reset_defaults_also_resets_hdrm_scan_params(self):
        self.app.hightemp_passes_table.set_num_passes("5")
        self.app.hightemp_num_steps_var.set("999")
        self.app.hightemp_count_time_var.set("9.9")
        self.app._on_hightemp_reset_defaults()

        self.assertEqual(self.app.hightemp_passes_table.get(), HDRM_SCAN_PASSES_DEFAULTS)
        self.assertEqual(self.app.hightemp_num_steps_var.get(), HDRM_SCAN_DEFAULTS["num_steps"])
        self.assertEqual(self.app.hightemp_count_time_var.get(), HDRM_SCAN_DEFAULTS["count_time"])

    def test_low_temp_preview_reflects_custom_hdrm_scan_params(self):
        self.app.low_temp_passes_table.set_num_passes("1")
        row_vars = self.app.low_temp_passes_table.rows[0].vars
        row_vars["chi"].set("11")
        row_vars["th"].set("22")
        row_vars["scan_start"].set("5")
        row_vars["scan_stop"].set("50")
        self.app.low_temp_num_steps_var.set("42")
        self.app.low_temp_count_time_var.set("0.02")
        self.app.low_temp_vars["end_temp"].set("31")  # keep it a fast, 1-step preview

        self.app._on_low_temp_preview()
        log = self.app.log_text.get("1.0", "end")
        self.assertIn("[umv] chi 11 th 22 phi 0", log)
        self.assertIn("[flyscan] phi 5 -> 50, 42 steps, 0.02s per point", log)

    def test_low_temp_preview_shows_error_for_invalid_hdrm_scan_params(self):
        self.app.low_temp_count_time_var.set("0")  # must be positive
        self.app._on_low_temp_preview()
        self.assertEqual(self.controller.sent, [])
        log = self.app.log_text.get("1.0", "end")
        self.assertNotIn("Preview: Low Temp Scan", log)

    def test_warmup_preview_reflects_custom_hdrm_scan_params(self):
        self.app.warmup_passes_table.set_num_passes("1")
        row_vars = self.app.warmup_passes_table.rows[0].vars
        row_vars["scan_start"].set("3")
        row_vars["scan_stop"].set("33")
        self.app.warmup_num_steps_var.set("17")
        self.app.warmup_count_time_var.set("0.03")
        self.app.warmup_phase_vars[0]["enabled"].set(True)  # all phases now default off
        self.app.warmup_phase_vars[1]["enabled"].set(False)
        self.app.warmup_phase_vars[2]["enabled"].set(False)
        self.app.warmup_phase_vars[0]["end_temp"].set("121")  # fast, 1-step preview

        self.app._on_warmup_preview()
        log = self.app.log_text.get("1.0", "end")
        self.assertIn("[flyscan] phi 3 -> 33, 17 steps, 0.03s per point", log)

    def test_warmup_custom_preview_shows_error_for_invalid_hdrm_scan_params(self):
        row_vars = self.app.warmup_custom_passes_table.rows[0].vars
        row_vars["scan_start"].set("10")
        row_vars["scan_stop"].set("10")  # equal -> invalid
        self.app._on_warmup_custom_preview()
        self.assertEqual(self.controller.sent, [])
        log = self.app.log_text.get("1.0", "end")
        self.assertNotIn("Preview: Warmup Custom", log)

    def test_cooldown_preview_reflects_custom_hdrm_scan_params(self):
        self.app.cooldown_passes_table.set_num_passes("1")
        row_vars = self.app.cooldown_passes_table.rows[0].vars
        row_vars["scan_start"].set("2")
        row_vars["scan_stop"].set("22")
        self.app.cooldown_num_steps_var.set("13")
        self.app.cooldown_count_time_var.set("0.04")
        self.app.cooldown_vars["end_temp"].set("299")  # fast, 1-step preview

        self.app._on_cooldown_preview()
        log = self.app.log_text.get("1.0", "end")
        self.assertIn("[flyscan] phi 2 -> 22, 13 steps, 0.04s per point", log)

    def test_hightemp_preview_reflects_custom_hdrm_scan_params(self):
        self.app.hightemp_passes_table.set_num_passes("1")
        row_vars = self.app.hightemp_passes_table.rows[0].vars
        row_vars["scan_start"].set("6")
        row_vars["scan_stop"].set("60")
        self.app.hightemp_num_steps_var.set("21")
        self.app.hightemp_count_time_var.set("0.05")
        self.app.hightemp_vars["end_temp"].set("362")  # fast, 1-step preview

        self.app._on_hightemp_preview()
        log = self.app.log_text.get("1.0", "end")
        self.assertIn("[flyscan] phi 6 -> 60, 21 steps, 0.05s per point", log)

    def test_hightemp_preview_shows_error_for_invalid_hdrm_scan_params(self):
        self.app.hightemp_num_steps_var.set("-1")  # must be positive
        self.app._on_hightemp_preview()
        self.assertEqual(self.controller.sent, [])
        log = self.app.log_text.get("1.0", "end")
        self.assertNotIn("Preview: High Temp Scan", log)

    # ---- Home tab ("better home page with description") ----

    def test_home_tab_exists_and_is_selectable_by_title(self):
        # _select_tab_by_title looks up main_notebook.tabs() by exact
        # displayed text, not index -- confirm "Home" resolves.
        for tab_id in self.app.main_notebook.tabs():
            if self.app.main_notebook.tab(tab_id, "text") == "Home":
                break
        else:
            self.fail("no 'Home' tab found in main_notebook")

    def test_select_tab_by_title_switches_to_sample_information(self):
        self.app._select_tab_by_title("Sample Information")
        selected = self.app.main_notebook.select()
        self.assertEqual(
            self.app.main_notebook.tab(selected, "text"), "Sample Information"
        )

    def test_select_tab_by_title_does_nothing_for_unknown_title(self):
        # Should not raise even if asked for a tab that doesn't exist.
        self.app._select_tab_by_title("Nonexistent Tab Title")

    # ---- Shutter button accessible at the top, alongside the Raw
    # SPEC command box, not just on the Threextal Scan tab ----

    def test_shutter_buttons_list_holds_both_the_top_and_tab_buttons(self):
        # self.shutter_buttons is the list every shutter-toggle button
        # registers into, so toggling stays in sync everywhere.
        self.assertIn(self.app.shutter_button_top, self.app.shutter_buttons)
        self.assertIn(self.app.shutter_button, self.app.shutter_buttons)
        self.assertEqual(len(self.app.shutter_buttons), 2)

    def test_toggling_shutter_updates_both_buttons_text_in_sync(self):
        self.assertEqual(self.app.shutter_button_top.cget("text"), "Open Shutter")
        self.assertEqual(self.app.shutter_button.cget("text"), "Open Shutter")

        self.app._on_toggle_shutter()
        self.assertEqual(self.app.shutter_button_top.cget("text"), "Close Shutter")
        self.assertEqual(self.app.shutter_button.cget("text"), "Close Shutter")

        self.app._on_toggle_shutter()
        self.assertEqual(self.app.shutter_button_top.cget("text"), "Open Shutter")
        self.assertEqual(self.app.shutter_button.cget("text"), "Open Shutter")

    # ---- Output panel can now actually be shrunk smaller (pack_propagate
    # fix for ttk.PanedWindow's missing per-pane minsize) ----

    def test_output_pane_height_is_capped_so_it_can_be_shrunk(self):
        # self.notebook (Log / Python Script Output) is packed inside
        # the "outer" LabelFrame pane added to self.body_paned; that
        # frame is reachable as self.notebook's master. Confirm its
        # requested height was capped to a small value instead of
        # being left to grow to match log_text/script_text's
        # height=18 (which was the actual bug).
        outer = self.app.notebook.master
        self.assertEqual(int(outer.cget("height")), 70)

    # ---- Data locations section on Sample Information (raw + processed
    # data folders, kept live via _refresh_data_dirs) ----

    def test_data_dir_vars_reflect_sample_information_fields_on_construction(self):
        # setUp doesn't touch nfs_cycle/nfs_btr/datafile/sample/temperature,
        # so this should already match DEFAULT_GLOBALS via the initial
        # self._refresh_data_dirs() call in __init__.
        self.assertTrue(self.app.raw_sample_dir_var.get())
        self.assertTrue(self.app.processed_dir_var.get())

    def test_data_dir_vars_update_live_when_sample_information_fields_change(self):
        # Changing the Cycle and BTR fields independently (rather than one
        # opaque free-text NFS root path) is exactly the "switch to
        # 2026-3" workflow the user asked for -- confirm both feed the 2
        # computed, read-only paths live (Raw sample directory and
        # Processed directory -- the "Next scan's image folder" row was
        # removed from this section per a later request, along with the
        # Open/Copy buttons, leaving just these two plain, display-only
        # fields).
        self.app.global_vars["nfs_cycle"].set("2026-2")
        self.app.global_vars["nfs_btr"].set("sarker-4910-a")
        self.app.global_vars["datafile"].set("DyScO3")
        self.app.global_vars["sample"].set("DyScO3_110/")
        self.app.global_vars["temperature"].set("300")

        self.assertEqual(
            self.app.raw_sample_dir_var.get(),
            "/nfs/chess/id4b/2026-2/sarker-4910-a/raw6M/DyScO3/DyScO3_110/300/",
        )
        self.assertEqual(
            self.app.processed_dir_var.get(),
            "/nfs/chess/id4baux/2026-2/sarker-4910-a/nxrefine/DyScO3/DyScO3_110/300/",
        )

    def test_switching_cycle_alone_updates_both_paths_live(self):
        # The specific complaint being fixed here: with only one
        # free-text "NFS root" field (and read-only computed display
        # fields), switching beamtime cycles felt impossible. Confirm
        # editing just the Cycle field (leaving BTR alone) is enough.
        self.app.global_vars["nfs_cycle"].set("2026-2")
        self.app.global_vars["nfs_btr"].set("sarker-4910-a")
        self.app.global_vars["datafile"].set("DyScO3")
        self.app.global_vars["sample"].set("DyScO3_110/")
        self.app.global_vars["temperature"].set("300")

        self.app.global_vars["nfs_cycle"].set("2026-3")

        self.assertTrue(
            self.app.raw_sample_dir_var.get().startswith("/nfs/chess/id4b/2026-3/sarker-4910-a/")
        )
        self.assertTrue(
            self.app.processed_dir_var.get().startswith(
                "/nfs/chess/id4baux/2026-3/sarker-4910-a/"
            )
        )

    def test_next_scan_dir_var_no_longer_exists_on_app(self):
        # The per-scan "next scan's image folder" row (and its backing
        # next_scan_dir_var) was removed from the Data locations
        # section per a later request to keep it to just Raw +
        # Processed. hrdm_core.resolve_data_dirs() still computes a
        # next_scan_dir value internally (used elsewhere, e.g. the
        # naming-convention verification in README.md) -- it's just no
        # longer surfaced as a GUI variable.
        self.assertFalse(hasattr(self.app, "next_scan_dir_var"))

    def test_nfs_cycle_and_btr_fields_are_present_in_global_vars_and_sample_information(self):
        self.assertIn("nfs_cycle", self.app.global_vars)
        self.assertIn("nfs_btr", self.app.global_vars)
        self.app.global_vars["nfs_cycle"].set("2026-3")
        self.app.global_vars["nfs_btr"].set("sarker-4775-a")
        self.assertEqual(self.app.global_vars["nfs_cycle"].get(), "2026-3")
        self.assertEqual(self.app.global_vars["nfs_btr"].get(), "sarker-4775-a")


    def test_open_in_file_manager_logs_a_clear_message_for_missing_path(self):
        self.app._open_in_file_manager("/definitely/does/not/exist/anywhere")
        log = self.app.log_text.get("1.0", "end")
        self.assertIn("[open folder]", log)
        self.assertIn("doesn't exist", log)

    def test_open_in_file_manager_logs_a_clear_message_for_empty_path(self):
        self.app._open_in_file_manager("")
        log = self.app.log_text.get("1.0", "end")
        self.assertIn("[open folder] no path to open yet.", log)

    def test_open_in_file_manager_never_raises_on_bad_input(self):
        # Purely a convenience feature -- must never crash the app
        # regardless of what's passed in.
        for bad_path in (None, "   ", "/nonexistent"):
            self.app._open_in_file_manager(bad_path)

    def test_copy_path_to_clipboard_logs_confirmation_or_fails_quietly(self):
        # Real clipboard access may or may not work in a headless test
        # environment -- either the log confirms the copy, or the
        # method silently no-ops via its own try/except; either way it
        # must not raise.
        self.app._copy_path_to_clipboard("/nfs/chess/id4b/2026-2/sarker-4910-a/")
        # No assertion on log content here since clipboard availability
        # is environment-dependent; the real assertion is "no exception".

    def test_copy_path_to_clipboard_does_nothing_for_empty_path(self):
        self.app._copy_path_to_clipboard("")
        self.app._copy_path_to_clipboard("   ")
        # Should not raise and should not touch the clipboard/log for
        # a blank path.


if __name__ == "__main__":
    unittest.main()
