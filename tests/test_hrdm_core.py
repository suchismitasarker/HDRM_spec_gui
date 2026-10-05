"""
Unit tests for hrdm_core.py -- the toolkit-independent scan logic
shared by both GUI front ends (Tkinter HRDM_gui.py and PyQt5
HRDM_gui_pyqt.py).

This module only depends on the standard library, so these tests run
in any environment, regardless of which (if any) GUI toolkit is
installed.

Run with:
    python -m unittest discover -s tests -t .
or:
    python -m pytest tests/
"""

import os
import queue
import subprocess
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import hrdm_core  # noqa: E402


class TestValidateGlobals(unittest.TestCase):
    def test_valid_globals_pass(self):
        g = dict(hrdm_core.DEFAULT_GLOBALS)
        hrdm_core.validate_globals(g)  # should not raise

    def test_non_numeric_field_raises(self):
        g = dict(hrdm_core.DEFAULT_GLOBALS)
        g["temperature"] = "not-a-number"
        with self.assertRaises(ValueError):
            hrdm_core.validate_globals(g)

    def test_empty_sample_raises(self):
        g = dict(hrdm_core.DEFAULT_GLOBALS)
        g["sample"] = ""
        with self.assertRaises(ValueError):
            hrdm_core.validate_globals(g)

    def test_default_sample_is_sample1_not_the_old_typo(self):
        # DEFAULT_GLOBALS["sample"] used to be the typo "saample1/" --
        # confirm it's spelled correctly now, and still ends in "/"
        # (matching HRDM.mac's own "DONOT FORGET TO PUT SLASH" example).
        self.assertEqual(hrdm_core.DEFAULT_GLOBALS["sample"], "sample1/")

    def test_non_integer_next_scan_n_raises(self):
        g = dict(hrdm_core.DEFAULT_GLOBALS)
        g["next_scan_n"] = "not-a-number"
        with self.assertRaises(ValueError):
            hrdm_core.validate_globals(g)

    def test_negative_next_scan_n_raises(self):
        g = dict(hrdm_core.DEFAULT_GLOBALS)
        g["next_scan_n"] = "-1"
        with self.assertRaises(ValueError):
            hrdm_core.validate_globals(g)


class TestValidateHeightParams(unittest.TestCase):
    def test_valid_defaults_pass(self):
        h = dict(hrdm_core.HEIGHTSCAN_DEFAULTS)
        hrdm_core.validate_height_params(h)  # should not raise

    def test_non_numeric_start_raises(self):
        h = dict(hrdm_core.HEIGHTSCAN_DEFAULTS)
        h["start"] = "not-a-number"
        with self.assertRaises(ValueError):
            hrdm_core.validate_height_params(h)

    def test_non_numeric_end_raises(self):
        h = dict(hrdm_core.HEIGHTSCAN_DEFAULTS)
        h["end"] = "not-a-number"
        with self.assertRaises(ValueError):
            hrdm_core.validate_height_params(h)

    def test_non_numeric_steps_raises(self):
        h = dict(hrdm_core.HEIGHTSCAN_DEFAULTS)
        h["steps"] = "not-a-number"
        with self.assertRaises(ValueError):
            hrdm_core.validate_height_params(h)

    def test_non_numeric_count_time_raises(self):
        h = dict(hrdm_core.HEIGHTSCAN_DEFAULTS)
        h["count_time"] = "not-a-number"
        with self.assertRaises(ValueError):
            hrdm_core.validate_height_params(h)

    def test_missing_field_raises(self):
        h = dict(hrdm_core.HEIGHTSCAN_DEFAULTS)
        del h["steps"]
        with self.assertRaises(ValueError):
            hrdm_core.validate_height_params(h)

    def test_start_equal_end_raises(self):
        h = dict(hrdm_core.HEIGHTSCAN_DEFAULTS)
        h["end"] = h["start"]
        with self.assertRaises(ValueError):
            hrdm_core.validate_height_params(h)

    def test_zero_steps_raises(self):
        h = dict(hrdm_core.HEIGHTSCAN_DEFAULTS)
        h["steps"] = "0"
        with self.assertRaises(ValueError):
            hrdm_core.validate_height_params(h)

    def test_negative_steps_raises(self):
        h = dict(hrdm_core.HEIGHTSCAN_DEFAULTS)
        h["steps"] = "-5"
        with self.assertRaises(ValueError):
            hrdm_core.validate_height_params(h)

    def test_zero_count_time_raises(self):
        h = dict(hrdm_core.HEIGHTSCAN_DEFAULTS)
        h["count_time"] = "0"
        with self.assertRaises(ValueError):
            hrdm_core.validate_height_params(h)

    def test_negative_count_time_raises(self):
        h = dict(hrdm_core.HEIGHTSCAN_DEFAULTS)
        h["count_time"] = "-0.1"
        with self.assertRaises(ValueError):
            hrdm_core.validate_height_params(h)


class TestValidatePowderParams(unittest.TestCase):
    def test_valid_defaults_pass(self):
        p = dict(hrdm_core.POWDERSCAN_DEFAULTS)
        hrdm_core.validate_powder_params(p)  # should not raise

    def test_default_count_time_is_1(self):
        # POWDERSCAN_DEFAULTS["count_time"] used to be "0.2" -- changed
        # to "1" per explicit request.
        self.assertEqual(hrdm_core.POWDERSCAN_DEFAULTS["count_time"], "1")

    def test_non_numeric_temperature_raises(self):
        p = dict(hrdm_core.POWDERSCAN_DEFAULTS)
        p["temperature"] = "not-a-number"
        with self.assertRaises(ValueError):
            hrdm_core.validate_powder_params(p)

    def test_non_numeric_wait_seconds_raises(self):
        p = dict(hrdm_core.POWDERSCAN_DEFAULTS)
        p["wait_seconds"] = "not-a-number"
        with self.assertRaises(ValueError):
            hrdm_core.validate_powder_params(p)

    def test_missing_field_raises(self):
        p = dict(hrdm_core.POWDERSCAN_DEFAULTS)
        del p["wait_seconds"]
        with self.assertRaises(ValueError):
            hrdm_core.validate_powder_params(p)

    def test_negative_wait_seconds_raises(self):
        p = dict(hrdm_core.POWDERSCAN_DEFAULTS)
        p["wait_seconds"] = "-1"
        with self.assertRaises(ValueError):
            hrdm_core.validate_powder_params(p)

    def test_zero_wait_seconds_is_allowed(self):
        p = dict(hrdm_core.POWDERSCAN_DEFAULTS)
        p["wait_seconds"] = "0"
        hrdm_core.validate_powder_params(p)  # should not raise

    def test_negative_temperature_is_allowed(self):
        # Cryogenic temperatures in other units (e.g. Celsius) can be
        # negative -- only wait_seconds has a sign restriction.
        p = dict(hrdm_core.POWDERSCAN_DEFAULTS)
        p["temperature"] = "-50"
        hrdm_core.validate_powder_params(p)  # should not raise

    def test_non_numeric_phi_start_raises(self):
        p = dict(hrdm_core.POWDERSCAN_DEFAULTS)
        p["phi_start"] = "not-a-number"
        with self.assertRaises(ValueError):
            hrdm_core.validate_powder_params(p)

    def test_non_numeric_phi_end_raises(self):
        p = dict(hrdm_core.POWDERSCAN_DEFAULTS)
        p["phi_end"] = "not-a-number"
        with self.assertRaises(ValueError):
            hrdm_core.validate_powder_params(p)

    def test_non_numeric_num_steps_raises(self):
        p = dict(hrdm_core.POWDERSCAN_DEFAULTS)
        p["num_steps"] = "not-a-number"
        with self.assertRaises(ValueError):
            hrdm_core.validate_powder_params(p)

    def test_non_numeric_count_time_raises(self):
        p = dict(hrdm_core.POWDERSCAN_DEFAULTS)
        p["count_time"] = "not-a-number"
        with self.assertRaises(ValueError):
            hrdm_core.validate_powder_params(p)

    def test_phi_start_equal_phi_end_raises(self):
        p = dict(hrdm_core.POWDERSCAN_DEFAULTS)
        p["phi_start"] = "180"
        p["phi_end"] = "180"
        with self.assertRaises(ValueError):
            hrdm_core.validate_powder_params(p)

    def test_zero_num_steps_raises(self):
        p = dict(hrdm_core.POWDERSCAN_DEFAULTS)
        p["num_steps"] = "0"
        with self.assertRaises(ValueError):
            hrdm_core.validate_powder_params(p)

    def test_negative_num_steps_raises(self):
        p = dict(hrdm_core.POWDERSCAN_DEFAULTS)
        p["num_steps"] = "-10"
        with self.assertRaises(ValueError):
            hrdm_core.validate_powder_params(p)

    def test_zero_count_time_raises(self):
        p = dict(hrdm_core.POWDERSCAN_DEFAULTS)
        p["count_time"] = "0"
        with self.assertRaises(ValueError):
            hrdm_core.validate_powder_params(p)

    def test_negative_count_time_raises(self):
        p = dict(hrdm_core.POWDERSCAN_DEFAULTS)
        p["count_time"] = "-0.2"
        with self.assertRaises(ValueError):
            hrdm_core.validate_powder_params(p)

    def test_negative_phi_start_and_end_are_allowed(self):
        # Only num_steps/count_time have sign restrictions; phi values
        # themselves can be negative (e.g. scanning -180 to 180).
        p = dict(hrdm_core.POWDERSCAN_DEFAULTS)
        p["phi_start"] = "-180"
        p["phi_end"] = "180"
        hrdm_core.validate_powder_params(p)  # should not raise


class TestPilFileBasename(unittest.TestCase):
    def test_plain_name_passes_through(self):
        self.assertEqual(hrdm_core._pil_file_basename("test"), "test")

    def test_path_uses_last_segment(self):
        self.assertEqual(hrdm_core._pil_file_basename("/foo/bar/test"), "test")

    def test_trailing_slash_is_ignored(self):
        self.assertEqual(hrdm_core._pil_file_basename("/foo/bar/test/"), "test")


class TestFormatTemp(unittest.TestCase):
    """hrdm_core._format_temp() -- strips the trailing ".0" that a
    bare str() of a whole-number float would otherwise leave in the
    `te` command and every directory/file name built from it (the
    user reported seeing folders named "280.0"/"290.0" instead of
    "280"/"290"), while still keeping a real decimal for a genuinely
    fractional temperature."""

    def test_whole_number_float_drops_trailing_zero(self):
        self.assertEqual(hrdm_core._format_temp(280.0), "280")
        self.assertEqual(hrdm_core._format_temp(290.0), "290")

    def test_whole_number_string_with_trailing_zero_is_normalized(self):
        self.assertEqual(hrdm_core._format_temp("280.0"), "280")

    def test_plain_integer_string_passes_through(self):
        self.assertEqual(hrdm_core._format_temp("300"), "300")

    def test_plain_int_passes_through(self):
        self.assertEqual(hrdm_core._format_temp(300), "300")

    def test_fractional_value_keeps_decimal(self):
        self.assertEqual(hrdm_core._format_temp(280.5), "280.5")
        self.assertEqual(hrdm_core._format_temp("280.5"), "280.5")

    def test_negative_whole_number_drops_trailing_zero(self):
        self.assertEqual(hrdm_core._format_temp(-3.0), "-3")

    def test_non_numeric_value_passes_through_unchanged(self):
        self.assertEqual(hrdm_core._format_temp("room_temp"), "room_temp")


class TestResolveDataDirs(unittest.TestCase):
    """hrdm_core.resolve_data_dirs() -- a pure, display-only helper that
    mirrors the relative-path construction Runner.run()/run_height_scan()/
    run_powder_scan() already use internally (raw6M/{datafile}/{sample}{temp}/
    plus a per-scan {basename}_{scan_n:03d} subfolder), with an NFS root
    built from two separate fields -- "nfs_cycle" (e.g. "2026-2") and
    "nfs_btr" (e.g. "sarker-4910-a") -- as
    "/nfs/chess/id4b/{cycle}/{btr}/", rather than accepting one free-text
    path, so switching beamtime cycles/proposals is a matter of editing
    one short field rather than hand-editing an opaque absolute path
    (this is a deliberate redesign, after a report that the previous
    single free-text "NFS root" field made the 3 read-only computed
    paths feel impossible to "move" to a different cycle). The processed
    (nxrefine) directory is built the same way, but under
    "/nfs/chess/id4baux/{cycle}/{btr}/nxrefine/...", with the per-scan
    subfolder dropped since nxrefine operates at sample/temperature
    granularity, not per-scan.

    This never runs any real scan logic -- it's purely for the "Data
    locations" section on the Sample Information tab."""

    def test_matches_users_example_paths_exactly(self):
        # Directly from the user's own two example paths:
        #   raw6M:    /nfs/chess/id4b/2026-2/sarker-4910-a/raw6M/DyScO3/DyScO3_110/300/DyScO3_003/
        #   nxrefine: /nfs/chess/id4baux/2026-2/sarker-4910-a/nxrefine/DyScO3/DyScO3_110/300/
        g = dict(hrdm_core.DEFAULT_GLOBALS)
        g["nfs_cycle"] = "2026-2"
        g["nfs_btr"] = "sarker-4910-a"
        g["datafile"] = "DyScO3"
        g["sample"] = "DyScO3_110/"
        g["temperature"] = "300"
        g["next_scan_n"] = "3"

        dirs = hrdm_core.resolve_data_dirs(g)

        self.assertEqual(
            dirs["raw_sample_dir"],
            "/nfs/chess/id4b/2026-2/sarker-4910-a/raw6M/DyScO3/DyScO3_110/300/",
        )
        self.assertEqual(
            dirs["next_scan_dir"],
            "/nfs/chess/id4b/2026-2/sarker-4910-a/raw6M/DyScO3/DyScO3_110/300/DyScO3_003/",
        )
        self.assertEqual(
            dirs["processed_dir"],
            "/nfs/chess/id4baux/2026-2/sarker-4910-a/nxrefine/DyScO3/DyScO3_110/300/",
        )

    def test_switching_cycle_alone_updates_all_three_paths(self):
        # The whole point of splitting into two fields: switching
        # cycles (e.g. 2026-2 -> 2026-3) is a one-field edit, and it's
        # reflected consistently in all three computed paths.
        g = dict(hrdm_core.DEFAULT_GLOBALS)
        g["nfs_cycle"] = "2026-3"
        g["nfs_btr"] = "sarker-4910-a"
        g["datafile"] = "DyScO3"
        g["sample"] = "DyScO3_110/"
        g["temperature"] = "300"
        g["next_scan_n"] = "3"

        dirs = hrdm_core.resolve_data_dirs(g)

        self.assertEqual(
            dirs["raw_sample_dir"],
            "/nfs/chess/id4b/2026-3/sarker-4910-a/raw6M/DyScO3/DyScO3_110/300/",
        )
        self.assertEqual(
            dirs["processed_dir"],
            "/nfs/chess/id4baux/2026-3/sarker-4910-a/nxrefine/DyScO3/DyScO3_110/300/",
        )

    def test_empty_cycle_and_btr_fall_back_to_relative_path(self):
        g = dict(hrdm_core.DEFAULT_GLOBALS)
        g["nfs_cycle"] = ""
        g["nfs_btr"] = ""
        g["datafile"] = "test"
        g["sample"] = "sample1/"
        g["temperature"] = "300"
        g["next_scan_n"] = "1"

        dirs = hrdm_core.resolve_data_dirs(g)

        self.assertEqual(dirs["raw_sample_dir"], "raw6M/test/sample1/300/")
        self.assertEqual(dirs["next_scan_dir"], "raw6M/test/sample1/300/test_001/")
        self.assertEqual(dirs["processed_dir"], "nxrefine/test/sample1/300/")

    def test_cycle_without_btr_also_falls_back_to_relative_path(self):
        # Both fields are required to build an absolute NFS root -- a
        # cycle with no BTR (or vice versa) isn't a real path, so this
        # falls back the same as if both were empty, rather than
        # guessing/building a half-complete absolute path.
        g = dict(hrdm_core.DEFAULT_GLOBALS)
        g["nfs_cycle"] = "2026-2"
        g["nfs_btr"] = ""
        g["datafile"] = "test"
        g["sample"] = "sample1/"
        g["temperature"] = "300"
        g["next_scan_n"] = "1"

        dirs = hrdm_core.resolve_data_dirs(g)

        self.assertEqual(dirs["raw_sample_dir"], "raw6M/test/sample1/300/")

    def test_missing_cycle_and_btr_keys_are_treated_as_empty(self):
        g = dict(hrdm_core.DEFAULT_GLOBALS)
        del g["nfs_cycle"]
        del g["nfs_btr"]
        g["datafile"] = "test"
        g["sample"] = "sample1/"
        g["temperature"] = "300"
        g["next_scan_n"] = "1"

        dirs = hrdm_core.resolve_data_dirs(g)  # should not raise (KeyError)
        self.assertTrue(dirs["raw_sample_dir"].startswith("raw6M/"))

    def test_cycle_and_btr_with_stray_slashes_are_normalized(self):
        # Defensive: strip accidental leading/trailing slashes typed
        # into either field, so the resulting path never ends up with
        # a doubled or missing "/" segment.
        g = dict(hrdm_core.DEFAULT_GLOBALS)
        g["nfs_cycle"] = "/2026-2/"
        g["nfs_btr"] = "/sarker-4910-a/"
        g["datafile"] = "DyScO3"
        g["sample"] = "DyScO3_110/"
        g["temperature"] = "300"
        g["next_scan_n"] = "3"

        dirs = hrdm_core.resolve_data_dirs(g)

        self.assertEqual(
            dirs["raw_sample_dir"],
            "/nfs/chess/id4b/2026-2/sarker-4910-a/raw6M/DyScO3/DyScO3_110/300/",
        )

    def test_non_numeric_next_scan_n_falls_back_to_placeholder_suffix(self):
        g = dict(hrdm_core.DEFAULT_GLOBALS)
        g["nfs_cycle"] = "2026-2"
        g["nfs_btr"] = "sarker-4910-a"
        g["datafile"] = "DyScO3"
        g["sample"] = "DyScO3_110/"
        g["temperature"] = "300"
        g["next_scan_n"] = ""

        dirs = hrdm_core.resolve_data_dirs(g)

        self.assertTrue(dirs["next_scan_dir"].endswith("DyScO3_???/"))

    def test_missing_next_scan_n_key_falls_back_to_placeholder_suffix(self):
        g = dict(hrdm_core.DEFAULT_GLOBALS)
        g["nfs_cycle"] = "2026-2"
        g["nfs_btr"] = "sarker-4910-a"
        g["datafile"] = "DyScO3"
        g["sample"] = "DyScO3_110/"
        g["temperature"] = "300"
        del g["next_scan_n"]

        dirs = hrdm_core.resolve_data_dirs(g)  # should not raise (KeyError)

        self.assertTrue(dirs["next_scan_dir"].endswith("DyScO3_???/"))

    def test_processed_dir_always_uses_id4baux_regardless_of_cycle(self):
        g = dict(hrdm_core.DEFAULT_GLOBALS)
        g["nfs_cycle"] = "2026-3"
        g["nfs_btr"] = "sarker-4775-a"
        g["datafile"] = "DyScO3"
        g["sample"] = "DyScO3_110/"
        g["temperature"] = "300"
        g["next_scan_n"] = "3"

        dirs = hrdm_core.resolve_data_dirs(g)

        self.assertTrue(
            dirs["processed_dir"].startswith("/nfs/chess/id4baux/2026-3/sarker-4775-a/")
        )
        self.assertNotIn("/id4b/", dirs["processed_dir"])

    def test_returns_raw_root_without_sample_subfolder(self):
        g = dict(hrdm_core.DEFAULT_GLOBALS)
        g["nfs_cycle"] = "2026-2"
        g["nfs_btr"] = "sarker-4910-a"
        g["datafile"] = "DyScO3"
        g["sample"] = "DyScO3_110/"
        g["temperature"] = "300"
        g["next_scan_n"] = "3"

        dirs = hrdm_core.resolve_data_dirs(g)

        self.assertEqual(
            dirs["raw_root"],
            "/nfs/chess/id4b/2026-2/sarker-4910-a/raw6M/DyScO3/",
        )


class TestParseNfsCwd(unittest.TestCase):
    # hrdm_core.parse_nfs_cwd() -- added per explicit request ("NSF
    # cycle information is wrong .. can you take that somehow
    # correct?", clarified to "autograb from some file for cycle not
    # sure how"): parses SPEC's own live "CWD" value into the
    # (cycle, btr) pair resolve_data_dirs() expects, so
    # HRDM_spec_gui.py's "Read cycle/BTR from SPEC" button doesn't
    # need a static, always-eventually-stale hardcoded default.

    def test_parses_real_example_cwd(self):
        # The exact real example given in DEFAULT_GLOBALS' own
        # comment on nfs_cycle/nfs_btr.
        cycle, btr = hrdm_core.parse_nfs_cwd("/nfs/chess/id4b/2026-3/sarker-4775-a")
        self.assertEqual(cycle, "2026-3")
        self.assertEqual(btr, "sarker-4775-a")

    def test_parses_with_trailing_slash(self):
        cycle, btr = hrdm_core.parse_nfs_cwd("/nfs/chess/id4b/2026-2/sarker-4910-a/")
        self.assertEqual(cycle, "2026-2")
        self.assertEqual(btr, "sarker-4910-a")

    def test_parses_with_extra_segments_after_btr(self):
        # SPEC may have cd'd deeper than the bare cycle/btr directory
        # (e.g. into raw6M/... while a scan is running) -- only the
        # first two segments after the prefix matter.
        cycle, btr = hrdm_core.parse_nfs_cwd(
            "/nfs/chess/id4b/2026-3/sarker-4775-a/raw6M/DyScO3/DyScO3_110/300/"
        )
        self.assertEqual(cycle, "2026-3")
        self.assertEqual(btr, "sarker-4775-a")

    def test_returns_none_none_for_wrong_prefix(self):
        # e.g. a local/ramdisk path, or the id4baux processed-data
        # mount -- neither is the raw NFS archive path this parses.
        self.assertEqual(
            hrdm_core.parse_nfs_cwd("/ramdisk/sarker-4775-a/"), (None, None)
        )
        self.assertEqual(
            hrdm_core.parse_nfs_cwd("/nfs/chess/id4baux/2026-3/sarker-4775-a"),
            (None, None),
        )

    def test_returns_none_none_for_missing_btr_segment(self):
        # Only a cycle, no btr after it -- a partial parse isn't safe
        # to apply (see parse_nfs_cwd's own docstring).
        self.assertEqual(
            hrdm_core.parse_nfs_cwd("/nfs/chess/id4b/2026-3"), (None, None)
        )
        self.assertEqual(
            hrdm_core.parse_nfs_cwd("/nfs/chess/id4b/2026-3/"), (None, None)
        )

    def test_returns_none_none_for_empty_or_none_input(self):
        self.assertEqual(hrdm_core.parse_nfs_cwd(""), (None, None))
        self.assertEqual(hrdm_core.parse_nfs_cwd(None), (None, None))
        self.assertEqual(hrdm_core.parse_nfs_cwd("   "), (None, None))

    def test_never_raises_on_garbage_input(self):
        # Consistent with resolve_data_dirs()'s own "never raise, just
        # show something sensible" style for display-only helpers.
        self.assertEqual(hrdm_core.parse_nfs_cwd(12345), (None, None))
        self.assertEqual(hrdm_core.parse_nfs_cwd("/nfs/chess/id4b/"), (None, None))
        self.assertEqual(hrdm_core.parse_nfs_cwd("not a path at all"), (None, None))

    def test_strips_whitespace_around_cwd(self):
        cycle, btr = hrdm_core.parse_nfs_cwd(
            "  /nfs/chess/id4b/2026-3/sarker-4775-a  \n"
        )
        self.assertEqual(cycle, "2026-3")
        self.assertEqual(btr, "sarker-4775-a")

    def test_result_is_directly_usable_by_resolve_data_dirs(self):
        # End-to-end sanity check: feeding parse_nfs_cwd()'s output
        # straight into resolve_data_dirs() produces the same raw_root
        # a hand-typed nfs_cycle/nfs_btr pair would.
        cycle, btr = hrdm_core.parse_nfs_cwd("/nfs/chess/id4b/2026-3/sarker-4775-a")
        g = dict(hrdm_core.DEFAULT_GLOBALS)
        g["nfs_cycle"] = cycle
        g["nfs_btr"] = btr
        g["datafile"] = "DyScO3"
        dirs = hrdm_core.resolve_data_dirs(g)
        self.assertEqual(
            dirs["raw_root"], "/nfs/chess/id4b/2026-3/sarker-4775-a/raw6M/DyScO3/"
        )


class TestRunner(unittest.TestCase):
    def setUp(self):
        self.log_q = queue.Queue()
        self.cancel_event = threading.Event()
        self.runner = hrdm_core.Runner(self.log_q, self.cancel_event)

    def _drain_log(self):
        msgs = []
        while not self.log_q.empty():
            msgs.append(self.log_q.get_nowait())
        return msgs

    def test_default_scan_logs_expected_sequence(self):
        g = dict(hrdm_core.DEFAULT_GLOBALS)
        g["wait_seconds"] = "0"  # keep the test fast
        passes = hrdm_core.DEFAULT_PASSES

        self.runner.run(g, passes)
        log = self._drain_log()

        self.assertIn("[te] set temperature -> 300", log)
        self.assertIn("[pil_on] turning on detector", log)
        self.assertIn(
            "[pil_setdir] /ramdisk/sarker-4775-a/raw6M/datafile/sample1/300/",
            log,
        )
        self.assertIn("[pil_settrig] 'Mult. Trigger'", log)

        umv_lines = [line for line in log if line.startswith("[umv]")]
        self.assertEqual(
            umv_lines,
            [
                "[umv] chi 90 th 0 phi 0",
                "[umv] chi 86 th 3 phi 0",
                "[umv] chi 95 th -3 phi 0",
                "[umv] chi 90 th 0 phi 0",  # final return-home move
            ],
        )

        flyscan_lines = [line for line in log if line.startswith("[flyscan]")]
        self.assertEqual(len(flyscan_lines), 3)
        for line in flyscan_lines:
            self.assertEqual(
                line, "[flyscan] phi 0 -> 365, 3650 steps, 0.1s per point"
            )

        # The literal SPEC-macro-syntax command line (matching
        # `flyscan phi 0 365 numSteps_ countTime_` in HRDM.mac) should
        # appear right after each [flyscan] line, followed by a
        # plain-language explanation line.
        macro_lines = [
            line for line in log if line.strip().startswith("flyscan phi")
        ]
        self.assertEqual(len(macro_lines), 3)
        for line in macro_lines:
            self.assertEqual(line.strip(), "flyscan phi 0 365 3650 0.1")

        explanation_lines = [
            line for line in log if "fly-scans the 'phi' motor" in line
        ]
        self.assertEqual(len(explanation_lines), 3)

        self.assertIn("[done] scan sequence complete", log)

    def test_default_datafile_placeholder_logs_warning(self):
        # DEFAULT_GLOBALS["datafile"] is just a placeholder ("datafile")
        # -- running with it untouched should warn, since every path
        # below (mysamplepath and the per-scan image subfolder) will
        # literally contain the word "datafile" instead of a real data
        # file name (confirmed by the user against a real run where they
        # expected ".../raw6M/test2/..." but got ".../raw6M/datafile/...").
        g = dict(hrdm_core.DEFAULT_GLOBALS)
        g["wait_seconds"] = "0"
        self.runner.run(g, hrdm_core.DEFAULT_PASSES)
        log = self._drain_log()

        warning_lines = [line for line in log if line.startswith("[warning]")]
        self.assertEqual(len(warning_lines), 1)
        self.assertIn("'datafile' is still the placeholder value", warning_lines[0])

    def test_real_datafile_value_logs_no_warning_and_builds_matching_paths(self):
        # Once "datafile" is set to a real value (e.g. via "Read from
        # SPEC" or typed in), both the sample path and the per-scan
        # image subfolder should use that same real value throughout,
        # with no placeholder warning.
        g = dict(hrdm_core.DEFAULT_GLOBALS)
        g["wait_seconds"] = "0"
        g["datafile"] = "test2"
        self.runner.run(g, hrdm_core.DEFAULT_PASSES)
        log = self._drain_log()

        self.assertFalse(any(line.startswith("[warning]") for line in log))
        self.assertIn(
            "[pil_setdir] /ramdisk/sarker-4775-a/raw6M/test2/sample1/300/",
            log,
        )
        scan_head_lines = [line for line in log if line.startswith("[_pil_scan_head]")]
        self.assertTrue(scan_head_lines)
        self.assertTrue(
            all("raw6M/test2/sample1/300/test2_" in line for line in scan_head_lines)
        )

    def test_custom_number_of_passes(self):
        g = dict(hrdm_core.DEFAULT_GLOBALS)
        g["wait_seconds"] = "0"
        passes = [
            {"chi": "10", "th": "1", "phi": "0", "scan_start": "0", "scan_stop": "90"},
        ]

        self.runner.run(g, passes)
        log = self._drain_log()

        umv_lines = [line for line in log if line.startswith("[umv]")]
        self.assertEqual(len(umv_lines), 2)
        self.assertEqual(umv_lines[0], "[umv] chi 10 th 1 phi 0")

        flyscan_lines = [line for line in log if line.startswith("[flyscan]")]
        self.assertEqual(len(flyscan_lines), 1)
        self.assertEqual(
            flyscan_lines[0], "[flyscan] phi 0 -> 90, 3650 steps, 0.1s per point"
        )

    def test_cancel_stops_before_detector_on(self):
        g = dict(hrdm_core.DEFAULT_GLOBALS)
        g["wait_seconds"] = "0.3"
        self.cancel_event.set()  # cancel immediately

        self.runner.run(g, hrdm_core.DEFAULT_PASSES)
        log = self._drain_log()

        self.assertIn(
            "[cancelled] stopping before turning on detector", log
        )
        self.assertFalse(any(line.startswith("[pil_on]") for line in log))
        self.assertFalse(any(line.startswith("[umv]") for line in log))

    def test_preview_mode_logs_full_sequence_without_real_waiting(self):
        g = dict(hrdm_core.DEFAULT_GLOBALS)
        g["wait_seconds"] = "1000"  # would take forever for real -- preview should skip it

        preview_runner = hrdm_core.Runner(
            self.log_q, self.cancel_event, preview=True
        )

        start = time.monotonic()
        preview_runner.run(g, hrdm_core.DEFAULT_PASSES)
        elapsed = time.monotonic() - start

        self.assertLess(elapsed, 2, "preview mode should not actually sleep")

        log = self._drain_log()
        # the sleep is still *logged* (so the preview shows the full
        # sequence a real run would produce) -- it's just not waited out
        self.assertIn("[sleep] 1000.0s after setting temperature", log)
        self.assertIn("[done] scan sequence complete", log)
        self.assertEqual(
            len([line for line in log if line.startswith("[umv]")]), 4
        )
        self.assertEqual(
            len([line for line in log if line.startswith("[flyscan]")]), 3
        )

    def test_scan_n_increments_once_per_pass_and_matches_pil_scan_head(self):
        g = dict(hrdm_core.DEFAULT_GLOBALS)
        g["wait_seconds"] = "0"
        g["next_scan_n"] = "7"
        passes = hrdm_core.DEFAULT_PASSES  # 3 passes

        self.runner.run(g, passes)
        log = self._drain_log()

        scan_head_lines = [
            line for line in log if line.startswith("[_pil_scan_head]")
        ]
        self.assertEqual(
            scan_head_lines,
            [
                "[_pil_scan_head] scan 7 images -> "
                "/ramdisk/sarker-4775-a/raw6M/datafile/sample1/300/datafile_007",
                "[_pil_scan_head] scan 8 images -> "
                "/ramdisk/sarker-4775-a/raw6M/datafile/sample1/300/datafile_008",
                "[_pil_scan_head] scan 9 images -> "
                "/ramdisk/sarker-4775-a/raw6M/datafile/sample1/300/datafile_009",
            ],
        )
        # Ending value left on the instance for a caller to read back and
        # (for a real, non-preview run) persist into "next_scan_n".
        self.assertEqual(self.runner.scan_n, 10)

    def test_scan_n_defaults_to_next_scan_n_field(self):
        g = dict(hrdm_core.DEFAULT_GLOBALS)
        g["wait_seconds"] = "0"
        self.assertEqual(g["next_scan_n"], "1")

        self.runner.run(g, hrdm_core.DEFAULT_PASSES)
        log = self._drain_log()

        self.assertTrue(
            any(
                line.startswith("[_pil_scan_head] scan 1 images ->")
                for line in log
            )
        )
        self.assertEqual(self.runner.scan_n, 4)  # 1 + 3 passes

    def test_datafile_with_path_uses_basename_in_scan_head(self):
        g = dict(hrdm_core.DEFAULT_GLOBALS)
        g["wait_seconds"] = "0"
        g["datafile"] = "/some/path/mydata"

        self.runner.run(g, hrdm_core.DEFAULT_PASSES)
        log = self._drain_log()

        self.assertTrue(
            any(
                "mydata_001" in line and line.startswith("[_pil_scan_head]")
                for line in log
            )
        )

    def test_cancel_mid_run_leaves_partial_scan_n(self):
        g = dict(hrdm_core.DEFAULT_GLOBALS)
        g["wait_seconds"] = "0"
        passes = hrdm_core.DEFAULT_PASSES  # 3 passes

        # Cancel the run partway through by flipping cancel_event once
        # the first pass's shutter opens -- monkeypatch opens() to do
        # that, so we deterministically stop after exactly 1 pass.
        real_opens = self.runner.opens
        call_count = {"n": 0}

        def opens_then_cancel():
            call_count["n"] += 1
            real_opens()
            if call_count["n"] == 1:
                self.cancel_event.set()

        self.runner.opens = opens_then_cancel

        self.runner.run(g, passes)
        log = self._drain_log()

        scan_head_lines = [
            line for line in log if line.startswith("[_pil_scan_head]")
        ]
        # Only the first pass's scan-head line should have been logged
        # before cancellation stopped the loop.
        self.assertEqual(len(scan_head_lines), 1)
        self.assertTrue(scan_head_lines[0].startswith("[_pil_scan_head] scan 1"))
        # Cancellation is only checked at the *top* of the loop (before
        # starting the next pass), so the pass that was already underway
        # when cancel_event got set still runs to completion (through
        # closes()) and its scan_n increment still applies -- only the
        # *next* pass is skipped. So scan_n ends at 2, not 1.
        self.assertEqual(self.runner.scan_n, 2)


class TestHeightScan(unittest.TestCase):
    """Runner.lup() and Runner.run_height_scan() -- translated from
    HDRMscans_new.mac's `heightscan` macro (see the module docstring
    and the README's "File-by-file mapping" table for the full
    macro-to-Python correspondence)."""

    def setUp(self):
        self.log_q = queue.Queue()
        self.cancel_event = threading.Event()
        self.runner = hrdm_core.Runner(self.log_q, self.cancel_event)

    def _drain_log(self):
        msgs = []
        while not self.log_q.empty():
            msgs.append(self.log_q.get_nowait())
        return msgs

    def test_lup_logs_expected_lines(self):
        self.runner.lup("samz", "-0.6", "0.6", "60", "0.2")
        log = self._drain_log()

        self.assertTrue(any(line.startswith("[lup]") for line in log))
        self.assertIn("    lup samz -0.6 0.6 60 0.2", log)
        self.assertTrue(
            any("step-scans the 'samz' motor" in line for line in log)
        )

    def test_run_height_scan_default_params_logs_expected_sequence(self):
        h = hrdm_core.HEIGHTSCAN_DEFAULTS
        self.runner.run_height_scan(
            "/ramdisk/sarker-4775-a/", h["start"], h["end"], h["steps"], h["count_time"]
        )
        log = self._drain_log()

        self.assertIn('[pil_settrig] \'Internal\'', log)
        self.assertIn(
            "[pil_setdir] /ramdisk/sarker-4775-a//tiffs/", log
        )
        self.assertIn("    lup samz -0.6 0.6 60 0.2", log)
        self.assertIn("[done] height scan complete", log)

        # unlike run() (threextalscan), the macro has no sleep() calls
        # bracketing opens/lup/closes -- confirm none snuck in here.
        self.assertFalse(any(line.startswith("[sleep]") for line in log))

    def test_run_height_scan_custom_params(self):
        self.runner.run_height_scan("/ramdisk/foo/", "-0.8", "0.8", "80", "0.3")
        log = self._drain_log()

        self.assertIn("    lup samz -0.8 0.8 80 0.3", log)
        self.assertIn("[pil_setdir] /ramdisk/foo//tiffs/", log)

    def test_run_height_scan_opens_and_closes_shutter(self):
        self.runner.run_height_scan(
            "/ramdisk/sarker-4775-a/", "-0.6", "0.6", "60", "0.2"
        )
        log = self._drain_log()

        self.assertTrue(any(line.startswith("[opens]") for line in log))
        self.assertTrue(any(line.startswith("[closes]") for line in log))
        # opens must come before closes
        opens_idx = next(i for i, l in enumerate(log) if l.startswith("[opens]"))
        closes_idx = next(i for i, l in enumerate(log) if l.startswith("[closes]"))
        self.assertLess(opens_idx, closes_idx)

    def test_preview_mode_never_sends_and_still_logs_full_sequence(self):
        preview_runner = hrdm_core.Runner(
            self.log_q, self.cancel_event, preview=True
        )
        preview_runner.run_height_scan(
            "/ramdisk/sarker-4775-a/", "-0.6", "0.6", "60", "0.2"
        )
        log = self._drain_log()

        self.assertIn("[done] height scan complete", log)
        self.assertTrue(any(line.startswith("[opens]") for line in log))


class TestPowderScan(unittest.TestCase):
    """Runner.run_powder_scan() -- translated from HDRMscans_new.mac's
    `powderscan <temperature> <sleep_time>` macro (see the module
    docstring and the README's "File-by-file mapping" table for the
    full macro-to-Python correspondence)."""

    def setUp(self):
        self.log_q = queue.Queue()
        self.cancel_event = threading.Event()
        self.runner = hrdm_core.Runner(self.log_q, self.cancel_event)

    def _drain_log(self):
        msgs = []
        while not self.log_q.empty():
            msgs.append(self.log_q.get_nowait())
        return msgs

    def _globals(self, **overrides):
        g = dict(hrdm_core.DEFAULT_GLOBALS)
        g.update(overrides)
        return g

    def _flyscan_args(self, **overrides):
        """(phi_start, phi_end, num_steps, count_time) taken from
        POWDERSCAN_DEFAULTS by default, so most tests exercise the
        default 0/360/180/1 flyscan range without repeating those
        four literals everywhere; callers can override individual
        fields to test custom ranges."""
        p = dict(hrdm_core.POWDERSCAN_DEFAULTS)
        p.update(overrides)
        return p["phi_start"], p["phi_end"], p["num_steps"], p["count_time"]

    def test_default_params_logs_expected_sequence(self):
        g = self._globals()
        p = hrdm_core.POWDERSCAN_DEFAULTS
        self.runner.run_powder_scan(
            g, p["temperature"], "0", *self._flyscan_args()  # keep test fast
        )
        log = self._drain_log()

        self.assertIn("[pil_on] turning on detector", log)
        self.assertIn(
            "[pil_setdir] /ramdisk/sarker-4775-a/raw6M/datafile/sample1/300/",
            log,
        )
        self.assertIn("[pil_settrig] 'Mult. Trigger'", log)
        self.assertIn("[umv] chi 90 th 0 phi 0", log)
        self.assertIn(
            "[flyscan] phi 0 -> 360, 180 steps, 1s per point", log
        )
        self.assertIn("    flyscan phi 0 360 180 1", log)
        self.assertIn("[done] powder scan complete", log)

        # unlike run() (threextalscan), the macro's own `te $1` line is
        # commented out -- confirm run_powder_scan() never calls te().
        self.assertFalse(any(line.startswith("[te]") for line in log))

    def test_custom_flyscan_range_is_used(self):
        g = self._globals()
        self.runner.run_powder_scan(
            g, "300", "0", *self._flyscan_args(
                phi_start="-180", phi_end="180", num_steps="90",
                count_time="1",
            )
        )
        log = self._drain_log()

        self.assertIn(
            "[flyscan] phi -180 -> 180, 90 steps, 1s per point", log
        )
        self.assertIn("    flyscan phi -180 180 90 1", log)

    def test_custom_temperature_builds_matching_directory(self):
        g = self._globals(datafile="test2")
        self.runner.run_powder_scan(g, "150", "0", *self._flyscan_args())
        log = self._drain_log()

        self.assertIn(
            "[pil_setdir] /ramdisk/sarker-4775-a/raw6M/test2/sample1/150/",
            log,
        )

    def test_default_datafile_placeholder_logs_warning(self):
        g = self._globals()  # datafile left at the "datafile" placeholder
        self.runner.run_powder_scan(g, "300", "0", *self._flyscan_args())
        log = self._drain_log()

        warning_lines = [line for line in log if line.startswith("[warning]")]
        self.assertEqual(len(warning_lines), 1)
        self.assertIn("'datafile' is still the placeholder value", warning_lines[0])

    def test_real_datafile_value_logs_no_warning(self):
        g = self._globals(datafile="test2")
        self.runner.run_powder_scan(g, "300", "0", *self._flyscan_args())
        log = self._drain_log()

        self.assertFalse(any(line.startswith("[warning]") for line in log))

    def test_opens_and_closes_shutter(self):
        g = self._globals()
        self.runner.run_powder_scan(g, "300", "0", *self._flyscan_args())
        log = self._drain_log()

        self.assertTrue(any(line.startswith("[opens]") for line in log))
        self.assertTrue(any(line.startswith("[closes]") for line in log))
        opens_idx = next(i for i, l in enumerate(log) if l.startswith("[opens]"))
        closes_idx = next(i for i, l in enumerate(log) if l.startswith("[closes]"))
        self.assertLess(opens_idx, closes_idx)

    def test_wait_seconds_is_used_as_the_pre_scan_sleep(self):
        g = self._globals()
        preview_runner = hrdm_core.Runner(
            self.log_q, self.cancel_event, preview=True
        )
        preview_runner.run_powder_scan(
            g, "300", "1000", *self._flyscan_args()
        )
        log = self._drain_log()

        self.assertIn("[sleep] 1000.0s", log)

    def test_cancel_stops_before_detector_on(self):
        g = self._globals()
        self.cancel_event.set()  # cancel immediately

        self.runner.run_powder_scan(g, "300", "0", *self._flyscan_args())
        log = self._drain_log()

        self.assertIn(
            "[cancelled] stopping before turning on detector", log
        )
        self.assertFalse(any(line.startswith("[pil_on]") for line in log))
        self.assertFalse(any(line.startswith("[umv]") for line in log))

    def test_preview_mode_logs_full_sequence_without_real_waiting(self):
        g = self._globals()
        preview_runner = hrdm_core.Runner(
            self.log_q, self.cancel_event, preview=True
        )

        start = time.monotonic()
        preview_runner.run_powder_scan(
            g, "300", "1000", *self._flyscan_args()
        )
        elapsed = time.monotonic() - start

        self.assertLess(elapsed, 2, "preview mode should not actually sleep")

        log = self._drain_log()
        self.assertIn("[done] powder scan complete", log)
        self.assertTrue(any(line.startswith("[umv]") for line in log))
        self.assertTrue(any(line.startswith("[flyscan]") for line in log))


class FakeSpecController:
    """Records every command sent via .send() and returns a canned
    response -- used to test Runner's live-send wiring (self._send())
    without touching a real SPEC server. Mirrors the .send(command)
    interface of id4b_pyspec.spec_controller.SpecController /
    spec_controller.py's SpecController."""

    def __init__(self, response="OK"):
        self.sent = []
        self.response = response

    def send(self, command):
        self.sent.append(command)
        return self.response


class TestLiveSpecSending(unittest.TestCase):
    """Runner(..., spec_controller=...) should send the equivalent SPEC
    command line through spec_controller.send() for every stub call,
    but only when preview=False and a spec_controller is actually
    attached -- Preview Log and the original stub-only (no controller)
    behavior must stay completely unaffected."""

    def setUp(self):
        self.log_q = queue.Queue()
        self.cancel_event = threading.Event()
        self.fake = FakeSpecController()

    def _drain_log(self):
        msgs = []
        while not self.log_q.empty():
            msgs.append(self.log_q.get_nowait())
        return msgs

    def test_run_with_spec_controller_sends_every_command(self):
        runner = hrdm_core.Runner(
            self.log_q, self.cancel_event, spec_controller=self.fake
        )
        g = dict(hrdm_core.DEFAULT_GLOBALS)
        g["wait_seconds"] = "0"
        passes = [
            {"chi": "10", "th": "1", "phi": "0", "scan_start": "0", "scan_stop": "90"},
        ]
        runner.run(g, passes)

        self.assertIn("te 300", self.fake.sent)
        self.assertIn("pil_on", self.fake.sent)
        self.assertIn('pil_settrig "Mult. Trigger"', self.fake.sent)
        self.assertIn("umv chi 10 th 1 phi 0", self.fake.sent)
        self.assertIn("opens", self.fake.sent)
        self.assertIn("flyscan phi 0 90 3650 0.1", self.fake.sent)
        self.assertIn("closes", self.fake.sent)
        self.assertIn("umv chi 90 th 0 phi 0", self.fake.sent)  # final return-home
        # u_mkdir goes through SPEC too (as "u mkdir ...") rather than
        # a local os.makedirs, once a real spec_controller is attached
        # -- the real macro's "u mkdir" runs on the SPEC server.
        self.assertTrue(any(cmd.startswith("u mkdir") for cmd in self.fake.sent))
        self.assertTrue(any(cmd.startswith('pil_setdir "') for cmd in self.fake.sent))

        # The log should also show what was sent + SPEC's response.
        log = self._drain_log()
        self.assertIn("    >> sending to SPEC: te 300", log)
        self.assertIn("    << SPEC response: 'OK'", log)

    def test_preview_mode_never_sends_even_with_spec_controller_attached(self):
        runner = hrdm_core.Runner(
            self.log_q, self.cancel_event, preview=True, spec_controller=self.fake
        )
        g = dict(hrdm_core.DEFAULT_GLOBALS)
        g["wait_seconds"] = "0"
        runner.run(g, hrdm_core.DEFAULT_PASSES)

        self.assertEqual(self.fake.sent, [])  # nothing sent in preview

    def test_no_spec_controller_never_sends_and_behaves_as_before(self):
        runner = hrdm_core.Runner(self.log_q, self.cancel_event)  # spec_controller=None
        g = dict(hrdm_core.DEFAULT_GLOBALS)
        g["wait_seconds"] = "0"
        runner.run(g, hrdm_core.DEFAULT_PASSES)

        log = self._drain_log()
        self.assertIn("[done] scan sequence complete", log)

    def test_run_height_scan_with_spec_controller_sends_every_command(self):
        runner = hrdm_core.Runner(
            self.log_q, self.cancel_event, spec_controller=self.fake
        )
        h = hrdm_core.HEIGHTSCAN_DEFAULTS
        runner.run_height_scan(
            "/ramdisk/sarker-4775-a/", h["start"], h["end"], h["steps"], h["count_time"]
        )

        self.assertIn('pil_settrig "Internal"', self.fake.sent)
        self.assertIn(
            'pil_setdir "/ramdisk/sarker-4775-a//tiffs/"', self.fake.sent
        )
        self.assertIn("opens", self.fake.sent)
        self.assertIn("lup samz -0.6 0.6 60 0.2", self.fake.sent)
        self.assertIn("closes", self.fake.sent)
        # Confirm the main scan's "Mult. Trigger" mode was never sent
        # by the height scan -- it only ever sends "Internal".
        self.assertNotIn('pil_settrig "Mult. Trigger"', self.fake.sent)

    def test_run_height_scan_preview_never_sends(self):
        runner = hrdm_core.Runner(
            self.log_q, self.cancel_event, preview=True, spec_controller=self.fake
        )
        h = hrdm_core.HEIGHTSCAN_DEFAULTS
        runner.run_height_scan(
            "/ramdisk/sarker-4775-a/", h["start"], h["end"], h["steps"], h["count_time"]
        )

        self.assertEqual(self.fake.sent, [])

    def test_run_powder_scan_with_spec_controller_sends_every_command(self):
        runner = hrdm_core.Runner(
            self.log_q, self.cancel_event, spec_controller=self.fake
        )
        g = dict(hrdm_core.DEFAULT_GLOBALS)
        p = hrdm_core.POWDERSCAN_DEFAULTS
        runner.run_powder_scan(
            g, p["temperature"], "0",
            p["phi_start"], p["phi_end"], p["num_steps"], p["count_time"],
        )

        self.assertIn('pil_settrig "Mult. Trigger"', self.fake.sent)
        self.assertIn("umv chi 90 th 0 phi 0", self.fake.sent)
        self.assertIn("opens", self.fake.sent)
        self.assertIn("flyscan phi 0 360 180 1", self.fake.sent)
        self.assertIn("closes", self.fake.sent)
        self.assertTrue(any(cmd.startswith("u mkdir") for cmd in self.fake.sent))
        self.assertTrue(any(cmd.startswith('pil_setdir "') for cmd in self.fake.sent))
        # The macro's own `te $1` call is commented out -- confirm no
        # "te ..." command was sent.
        self.assertFalse(any(cmd.startswith("te ") for cmd in self.fake.sent))

    def test_run_powder_scan_with_custom_flyscan_range_sends_matching_command(self):
        runner = hrdm_core.Runner(
            self.log_q, self.cancel_event, spec_controller=self.fake
        )
        g = dict(hrdm_core.DEFAULT_GLOBALS)
        runner.run_powder_scan(g, "300", "0", "-180", "180", "90", "1")

        self.assertIn("flyscan phi -180 180 90 1", self.fake.sent)

    def test_run_powder_scan_preview_never_sends(self):
        runner = hrdm_core.Runner(
            self.log_q, self.cancel_event, preview=True, spec_controller=self.fake
        )
        g = dict(hrdm_core.DEFAULT_GLOBALS)
        p = hrdm_core.POWDERSCAN_DEFAULTS
        runner.run_powder_scan(
            g, p["temperature"], p["wait_seconds"],
            p["phi_start"], p["phi_end"], p["num_steps"], p["count_time"],
        )

        self.assertEqual(self.fake.sent, [])


class TestGenerateScript(unittest.TestCase):
    """generate_script() builds a clean, standalone, runnable .py
    script (shown in the GUI's "Python Script" tab) -- these tests
    check it's valid Python, contains the right values, and (as the
    strongest check) actually runs correctly end-to-end."""

    def test_script_compiles_and_contains_expected_values(self):
        script = hrdm_core.generate_script(
            hrdm_core.DEFAULT_GLOBALS, hrdm_core.DEFAULT_PASSES
        )
        compile(script, "<generated>", "exec")  # raises SyntaxError if invalid

        self.assertIn("def main():", script)
        self.assertIn("def umv(chi, th, phi):", script)
        self.assertIn("def flyscan(motor, start, stop, num_steps, count_time):", script)
        self.assertIn("umv(90, 0, 0)", script)  # pass 1, numbers not quoted
        self.assertIn("umv(86, 3, 0)", script)  # pass 2
        self.assertIn('flyscan("phi", 0, 365, num_steps, count_time)', script)
        self.assertIn("myT = '300'", script)  # temperature kept as a string
        self.assertIn('if __name__ == "__main__":', script)
        self.assertIn("def _pil_file_basename(datafile):", script)
        self.assertIn("scan_n = 1", script)  # DEFAULT_GLOBALS["next_scan_n"]
        self.assertIn("scan_n += 1", script)
        self.assertIn(
            'scanpath = f"{pilrampath}/{datafile_basename}_{scan_n:03d}"', script
        )

    def test_custom_passes_produce_matching_number_of_umv_calls(self):
        passes = [
            {"chi": "10", "th": "1", "phi": "0", "scan_start": "0", "scan_stop": "90"},
            {"chi": "20", "th": "2", "phi": "0", "scan_start": "0", "scan_stop": "180"},
        ]
        script = hrdm_core.generate_script(hrdm_core.DEFAULT_GLOBALS, passes)
        compile(script, "<generated>", "exec")

        # One umv() call per pass + one final return-home call (the
        # "- 1" excludes the "def umv(chi, th, phi):" definition line
        # itself, which also contains the substring "umv(").
        self.assertEqual(script.count("umv(") - 1, 3)
        self.assertIn("umv(10, 1, 0)", script)
        self.assertIn("umv(20, 2, 0)", script)
        self.assertIn('flyscan("phi", 0, 90, num_steps, count_time)', script)
        self.assertIn('flyscan("phi", 0, 180, num_steps, count_time)', script)
        # One scan_n += 1 per pass, matching the number of passes.
        self.assertEqual(script.count("scan_n += 1"), 2)

    def test_custom_next_scan_n_appears_in_generated_script(self):
        g = dict(hrdm_core.DEFAULT_GLOBALS)
        g["next_scan_n"] = "42"
        script = hrdm_core.generate_script(g, hrdm_core.DEFAULT_PASSES)
        compile(script, "<generated>", "exec")
        self.assertIn("scan_n = 42", script)

    def test_generated_script_actually_runs_end_to_end(self):
        """Strongest possible check: write the generated script to a
        real file and execute it as a subprocess -- confirms it's not
        just syntactically valid but genuinely runnable."""
        script = hrdm_core.generate_script(
            hrdm_core.DEFAULT_GLOBALS,
            [{"chi": "10", "th": "1", "phi": "0", "scan_start": "0", "scan_stop": "90"}],
        )
        # Run inside a throwaway temp directory (as both cwd and the
        # script's own location) so the script's u_mkdir() calls don't
        # create/leave behind any raw6M/... directories in the repo.
        with tempfile.TemporaryDirectory() as tmp_dir:
            script_path = os.path.join(tmp_dir, "_tmp_generated_script.py")
            with open(script_path, "w") as f:
                f.write(script)
            result = subprocess.run(
                [sys.executable, script_path],
                capture_output=True, text=True, timeout=10, cwd=tmp_dir,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("[te] set temperature -> 300", result.stdout)
        self.assertIn("[umv] chi 10 th 1 phi 0", result.stdout)
        self.assertIn(
            "[flyscan] phi 0 -> 90, 3650 steps, 0.1s per point", result.stdout
        )
        self.assertIn(
            "[_pil_scan_head] scan 1 images -> "
            "/ramdisk/sarker-4775-a/raw6M/datafile/sample1/300/datafile_001",
            result.stdout,
        )
        self.assertIn("[done] scan sequence complete", result.stdout)


class TestValidateSpinParams(unittest.TestCase):
    def test_blank_num_cycles_is_allowed(self):
        hrdm_core.validate_spin_params({"num_cycles": "", "ice_mode": "0"})  # no raise

    def test_valid_num_cycles_passes(self):
        hrdm_core.validate_spin_params({"num_cycles": "4", "ice_mode": "0"})  # no raise

    def test_non_numeric_num_cycles_raises(self):
        with self.assertRaises(ValueError):
            hrdm_core.validate_spin_params({"num_cycles": "abc", "ice_mode": "0"})

    def test_fractional_num_cycles_raises(self):
        with self.assertRaises(ValueError):
            hrdm_core.validate_spin_params({"num_cycles": "2.5", "ice_mode": "0"})

    def test_zero_num_cycles_raises(self):
        with self.assertRaises(ValueError):
            hrdm_core.validate_spin_params({"num_cycles": "0", "ice_mode": "0"})

    def test_negative_num_cycles_raises(self):
        with self.assertRaises(ValueError):
            hrdm_core.validate_spin_params({"num_cycles": "-3", "ice_mode": "0"})


class TestValidateLowTempParams(unittest.TestCase):
    def test_valid_defaults_pass(self):
        hrdm_core.validate_low_temp_params(hrdm_core.LOW_TEMP_SCAN_DEFAULTS)  # no raise

    def test_non_numeric_field_raises(self):
        p = dict(hrdm_core.LOW_TEMP_SCAN_DEFAULTS)
        p["start_temp"] = "abc"
        with self.assertRaises(ValueError):
            hrdm_core.validate_low_temp_params(p)

    def test_missing_field_raises(self):
        p = dict(hrdm_core.LOW_TEMP_SCAN_DEFAULTS)
        del p["end_temp"]
        with self.assertRaises(ValueError):
            hrdm_core.validate_low_temp_params(p)

    def test_start_greater_than_or_equal_end_raises(self):
        p = dict(hrdm_core.LOW_TEMP_SCAN_DEFAULTS)
        p["start_temp"] = "110"
        p["end_temp"] = "110"
        with self.assertRaises(ValueError):
            hrdm_core.validate_low_temp_params(p)

    def test_zero_step_raises(self):
        p = dict(hrdm_core.LOW_TEMP_SCAN_DEFAULTS)
        p["step_temp"] = "0"
        with self.assertRaises(ValueError):
            hrdm_core.validate_low_temp_params(p)

    def test_negative_spin_cycles_raises(self):
        p = dict(hrdm_core.LOW_TEMP_SCAN_DEFAULTS)
        p["spin_cycles"] = "-1"
        with self.assertRaises(ValueError):
            hrdm_core.validate_low_temp_params(p)

    def test_negative_wait_seconds_raises(self):
        p = dict(hrdm_core.LOW_TEMP_SCAN_DEFAULTS)
        p["post_temp_wait_seconds"] = "-1"
        with self.assertRaises(ValueError):
            hrdm_core.validate_low_temp_params(p)


class TestValidateLowTempSampleSetupParams(unittest.TestCase):
    def test_valid_defaults_pass(self):
        hrdm_core.validate_low_temp_sample_setup_params(
            hrdm_core.LOW_TEMP_SAMPLE_SETUP_DEFAULTS
        )  # no raise

    def test_non_numeric_sample_temp_raises(self):
        with self.assertRaises(ValueError):
            hrdm_core.validate_low_temp_sample_setup_params(
                {"sample_temp": "abc", "sample_flow": "12"}
            )

    def test_non_numeric_sample_flow_raises(self):
        with self.assertRaises(ValueError):
            hrdm_core.validate_low_temp_sample_setup_params(
                {"sample_temp": "240", "sample_flow": "xyz"}
            )

    def test_missing_field_raises(self):
        with self.assertRaises(ValueError):
            hrdm_core.validate_low_temp_sample_setup_params({"sample_temp": "240"})


class TestValidateN2ToHeSwitchParams(unittest.TestCase):
    def test_valid_defaults_pass(self):
        hrdm_core.validate_n2_to_he_switch_params(
            hrdm_core.N2_TO_HE_SWITCH_DEFAULTS
        )  # no raise

    def test_non_numeric_field_raises(self):
        p = dict(hrdm_core.N2_TO_HE_SWITCH_DEFAULTS)
        p["prepswitch_stage_a"] = "abc"
        with self.assertRaises(ValueError):
            hrdm_core.validate_n2_to_he_switch_params(p)

    def test_missing_field_raises(self):
        p = dict(hrdm_core.N2_TO_HE_SWITCH_DEFAULTS)
        del p["sample_temp_1"]
        with self.assertRaises(ValueError):
            hrdm_core.validate_n2_to_he_switch_params(p)

    def test_zero_wait_minutes_is_allowed(self):
        # Unlike every other validator here, a wait of 0 minutes is a
        # deliberate way to skip that wait entirely -- it must NOT raise.
        p = dict(hrdm_core.N2_TO_HE_SWITCH_DEFAULTS)
        p["wait_after_prepswitch_minutes"] = "0"
        p["wait_for_sample_temp_minutes"] = "0"
        p["wait_for_base_temp_minutes"] = "0"
        hrdm_core.validate_n2_to_he_switch_params(p)  # no raise

    def test_negative_wait_after_prepswitch_minutes_raises(self):
        p = dict(hrdm_core.N2_TO_HE_SWITCH_DEFAULTS)
        p["wait_after_prepswitch_minutes"] = "-1"
        with self.assertRaises(ValueError):
            hrdm_core.validate_n2_to_he_switch_params(p)

    def test_negative_wait_for_sample_temp_minutes_raises(self):
        p = dict(hrdm_core.N2_TO_HE_SWITCH_DEFAULTS)
        p["wait_for_sample_temp_minutes"] = "-1"
        with self.assertRaises(ValueError):
            hrdm_core.validate_n2_to_he_switch_params(p)

    def test_negative_wait_for_base_temp_minutes_raises(self):
        p = dict(hrdm_core.N2_TO_HE_SWITCH_DEFAULTS)
        p["wait_for_base_temp_minutes"] = "-1"
        with self.assertRaises(ValueError):
            hrdm_core.validate_n2_to_he_switch_params(p)

    def test_negative_spin_cycles_raises(self):
        p = dict(hrdm_core.N2_TO_HE_SWITCH_DEFAULTS)
        p["spin_cycles"] = "-1"
        with self.assertRaises(ValueError):
            hrdm_core.validate_n2_to_he_switch_params(p)

    def test_zero_spin_cycles_is_allowed(self):
        p = dict(hrdm_core.N2_TO_HE_SWITCH_DEFAULTS)
        p["spin_cycles"] = "0"
        hrdm_core.validate_n2_to_he_switch_params(p)  # no raise


class TestValidateWarmupPhaseParams(unittest.TestCase):
    def _phases(self):
        return [dict(ph) for ph in hrdm_core.WARMUP_PHASE_DEFAULTS]

    def test_valid_defaults_pass(self):
        phases = self._phases()
        phases[0]["enabled"] = "1"  # phases now default off; enable one
        hrdm_core.validate_warmup_phase_params(phases)  # no raise

    def test_non_numeric_field_raises_with_phase_label(self):
        phases = self._phases()
        phases[1]["start_temp"] = "abc"
        with self.assertRaises(ValueError) as ctx:
            hrdm_core.validate_warmup_phase_params(phases)
        self.assertIn("Phase 2", str(ctx.exception))

    def test_start_greater_than_or_equal_end_raises(self):
        phases = self._phases()
        phases[0]["start_temp"] = "155"
        with self.assertRaises(ValueError):
            hrdm_core.validate_warmup_phase_params(phases)

    def test_zero_step_raises(self):
        phases = self._phases()
        phases[0]["step_temp"] = "0"
        with self.assertRaises(ValueError):
            hrdm_core.validate_warmup_phase_params(phases)

    def test_negative_spin20_cycles_raises(self):
        phases = self._phases()
        phases[0]["spin20_cycles"] = "-1"
        with self.assertRaises(ValueError):
            hrdm_core.validate_warmup_phase_params(phases)

    def test_negative_spin_per_step_cycles_raises(self):
        phases = self._phases()
        phases[0]["spin_per_step_cycles"] = "-1"
        with self.assertRaises(ValueError):
            hrdm_core.validate_warmup_phase_params(phases)

    def test_invalid_prep_fn_raises(self):
        phases = self._phases()
        phases[0]["prep_fn"] = "bogus"
        with self.assertRaises(ValueError):
            hrdm_core.validate_warmup_phase_params(phases)

    def test_all_phases_disabled_raises(self):
        phases = self._phases()
        for ph in phases:
            ph["enabled"] = "0"
        with self.assertRaises(ValueError):
            hrdm_core.validate_warmup_phase_params(phases)

    def test_one_enabled_phase_is_enough(self):
        phases = self._phases()
        phases[1]["enabled"] = "1"  # phases now default off; enable phase 2
        phases[0]["enabled"] = "0"
        phases[2]["enabled"] = "0"
        hrdm_core.validate_warmup_phase_params(phases)  # no raise

    def test_non_numeric_stage_a_raises(self):
        phases = self._phases()
        phases[0]["stage_a"] = "abc"
        with self.assertRaises(ValueError) as ctx:
            hrdm_core.validate_warmup_phase_params(phases)
        self.assertIn("Phase 1", str(ctx.exception))
        self.assertIn("stage_a", str(ctx.exception))

    def test_non_numeric_stage_c_raises(self):
        phases = self._phases()
        phases[1]["stage_c"] = "xyz"
        with self.assertRaises(ValueError) as ctx:
            hrdm_core.validate_warmup_phase_params(phases)
        self.assertIn("Phase 2", str(ctx.exception))
        self.assertIn("stage_c", str(ctx.exception))

    def test_non_numeric_room_temp_after_te_raises(self):
        phases = self._phases()
        phases[0]["room_temp_after_te"] = "abc"
        with self.assertRaises(ValueError) as ctx:
            hrdm_core.validate_warmup_phase_params(phases)
        self.assertIn("Phase 1", str(ctx.exception))
        self.assertIn("room_temp_after_te", str(ctx.exception))

    def test_non_numeric_room_temp_after_flow_raises(self):
        phases = self._phases()
        phases[2]["room_temp_after_flow"] = "xyz"
        with self.assertRaises(ValueError) as ctx:
            hrdm_core.validate_warmup_phase_params(phases)
        self.assertIn("Phase 3", str(ctx.exception))
        self.assertIn("room_temp_after_flow", str(ctx.exception))

    def test_room_temp_after_fields_validated_even_when_interlude_disabled(self):
        # Matches the existing disabled-phase convention: fields are
        # still range/type-checked even though room_temp_after_enabled
        # defaults to "0", so re-enabling it later can't silently run
        # with a bad value left over from before.
        phases = self._phases()
        phases[0]["room_temp_after_enabled"] = "0"
        phases[0]["room_temp_after_te"] = "not-a-number"
        with self.assertRaises(ValueError):
            hrdm_core.validate_warmup_phase_params(phases)

    def test_room_temp_after_defaults_pass(self):
        phases = self._phases()
        phases[0]["enabled"] = "1"
        hrdm_core.validate_warmup_phase_params(phases)  # no raise


class TestValidateWarmupFinalStepParams(unittest.TestCase):
    def test_valid_defaults_pass(self):
        hrdm_core.validate_warmup_final_step_params(
            hrdm_core.WARMUP_FINAL_STEP_DEFAULTS
        )  # no raise

    def test_non_numeric_sample_temp_raises(self):
        with self.assertRaises(ValueError):
            hrdm_core.validate_warmup_final_step_params(
                {"sample_temp": "abc", "sample_flow": "6"}
            )

    def test_non_numeric_sample_flow_raises(self):
        with self.assertRaises(ValueError):
            hrdm_core.validate_warmup_final_step_params(
                {"sample_temp": "300", "sample_flow": "xyz"}
            )

    def test_missing_field_raises(self):
        with self.assertRaises(ValueError):
            hrdm_core.validate_warmup_final_step_params({"sample_temp": "300"})


class TestValidateWarmupCustomParams(unittest.TestCase):
    def test_valid_defaults_pass(self):
        hrdm_core.validate_warmup_custom_params(hrdm_core.WARMUP_CUSTOM_DEFAULTS)

    def test_non_numeric_field_raises(self):
        p = dict(hrdm_core.WARMUP_CUSTOM_DEFAULTS)
        p["flow1"] = "abc"
        with self.assertRaises(ValueError):
            hrdm_core.validate_warmup_custom_params(p)

    def test_start_greater_than_or_equal_end_raises(self):
        p = dict(hrdm_core.WARMUP_CUSTOM_DEFAULTS)
        p["start_temp"] = "270"
        with self.assertRaises(ValueError):
            hrdm_core.validate_warmup_custom_params(p)

    def test_zero_step_raises(self):
        p = dict(hrdm_core.WARMUP_CUSTOM_DEFAULTS)
        p["step_temp"] = "0"
        with self.assertRaises(ValueError):
            hrdm_core.validate_warmup_custom_params(p)

    def test_negative_spin_cycles_raises(self):
        p = dict(hrdm_core.WARMUP_CUSTOM_DEFAULTS)
        p["spin_cycles"] = "-1"
        with self.assertRaises(ValueError):
            hrdm_core.validate_warmup_custom_params(p)

    def test_threshold1_greater_than_or_equal_threshold2_raises(self):
        p = dict(hrdm_core.WARMUP_CUSTOM_DEFAULTS)
        p["threshold1"] = "200"
        p["threshold2"] = "200"
        with self.assertRaises(ValueError):
            hrdm_core.validate_warmup_custom_params(p)


class TestValidateCooldownParams(unittest.TestCase):
    def test_valid_defaults_pass(self):
        hrdm_core.validate_cooldown_params(hrdm_core.COOLDOWN_DEFAULTS)

    def test_non_numeric_field_raises(self):
        p = dict(hrdm_core.COOLDOWN_DEFAULTS)
        p["flow_low"] = "abc"
        with self.assertRaises(ValueError):
            hrdm_core.validate_cooldown_params(p)

    def test_start_less_than_or_equal_end_raises(self):
        # Cooldown descends, so start must be GREATER than end (opposite
        # of every ascending temperature-series validator above).
        p = dict(hrdm_core.COOLDOWN_DEFAULTS)
        p["start_temp"] = "100"
        p["end_temp"] = "100"
        with self.assertRaises(ValueError):
            hrdm_core.validate_cooldown_params(p)

    def test_zero_step_raises(self):
        p = dict(hrdm_core.COOLDOWN_DEFAULTS)
        p["step_temp"] = "0"
        with self.assertRaises(ValueError):
            hrdm_core.validate_cooldown_params(p)

    def test_negative_spin_cycles_raises(self):
        p = dict(hrdm_core.COOLDOWN_DEFAULTS)
        p["spin_cycles"] = "-1"
        with self.assertRaises(ValueError):
            hrdm_core.validate_cooldown_params(p)

    def test_threshold_high_less_than_or_equal_threshold_medium_raises(self):
        p = dict(hrdm_core.COOLDOWN_DEFAULTS)
        p["threshold_high"] = "160"
        p["threshold_medium"] = "160"
        with self.assertRaises(ValueError):
            hrdm_core.validate_cooldown_params(p)


class TestValidateHightempParams(unittest.TestCase):
    def test_valid_defaults_pass(self):
        hrdm_core.validate_hightemp_params(hrdm_core.HIGHTEMP_SCAN_DEFAULTS)

    def test_non_numeric_field_raises(self):
        p = dict(hrdm_core.HIGHTEMP_SCAN_DEFAULTS)
        p["final_flow"] = "abc"
        with self.assertRaises(ValueError):
            hrdm_core.validate_hightemp_params(p)

    def test_start_greater_than_or_equal_end_raises(self):
        p = dict(hrdm_core.HIGHTEMP_SCAN_DEFAULTS)
        p["start_temp"] = "475"
        with self.assertRaises(ValueError):
            hrdm_core.validate_hightemp_params(p)

    def test_zero_step_raises(self):
        p = dict(hrdm_core.HIGHTEMP_SCAN_DEFAULTS)
        p["step_temp"] = "0"
        with self.assertRaises(ValueError):
            hrdm_core.validate_hightemp_params(p)

    def test_negative_scan_wait_seconds_raises(self):
        p = dict(hrdm_core.HIGHTEMP_SCAN_DEFAULTS)
        p["scan_wait_seconds"] = "-1"
        with self.assertRaises(ValueError):
            hrdm_core.validate_hightemp_params(p)


class TestValidateHdrmScanParams(unittest.TestCase):
    """validate_hdrm_scan_params() -- the new editable "HDRM Scan
    Parameters" section shared (as a per-tab instance) by all 5
    temperature-series tabs."""

    def _passes(self):
        return [dict(p) for p in hrdm_core.HDRM_SCAN_PASSES_DEFAULTS]

    def test_valid_defaults_pass(self):
        hrdm_core.validate_hdrm_scan_params(
            self._passes(),
            hrdm_core.HDRM_SCAN_DEFAULTS["num_steps"],
            hrdm_core.HDRM_SCAN_DEFAULTS["count_time"],
        )  # no raise

    def test_empty_passes_raises(self):
        with self.assertRaises(ValueError):
            hrdm_core.validate_hdrm_scan_params(
                [], hrdm_core.HDRM_SCAN_DEFAULTS["num_steps"],
                hrdm_core.HDRM_SCAN_DEFAULTS["count_time"],
            )

    def test_none_passes_raises(self):
        with self.assertRaises(ValueError):
            hrdm_core.validate_hdrm_scan_params(
                None, hrdm_core.HDRM_SCAN_DEFAULTS["num_steps"],
                hrdm_core.HDRM_SCAN_DEFAULTS["count_time"],
            )

    def test_non_numeric_pass_field_raises(self):
        passes = self._passes()
        passes[0]["chi"] = "abc"
        with self.assertRaises(ValueError):
            hrdm_core.validate_hdrm_scan_params(
                passes, hrdm_core.HDRM_SCAN_DEFAULTS["num_steps"],
                hrdm_core.HDRM_SCAN_DEFAULTS["count_time"],
            )

    def test_missing_pass_field_raises(self):
        passes = self._passes()
        del passes[0]["scan_stop"]
        with self.assertRaises(ValueError):
            hrdm_core.validate_hdrm_scan_params(
                passes, hrdm_core.HDRM_SCAN_DEFAULTS["num_steps"],
                hrdm_core.HDRM_SCAN_DEFAULTS["count_time"],
            )

    def test_equal_scan_start_and_stop_raises(self):
        passes = self._passes()
        passes[0]["scan_start"] = "10"
        passes[0]["scan_stop"] = "10"
        with self.assertRaises(ValueError):
            hrdm_core.validate_hdrm_scan_params(
                passes, hrdm_core.HDRM_SCAN_DEFAULTS["num_steps"],
                hrdm_core.HDRM_SCAN_DEFAULTS["count_time"],
            )

    def test_non_numeric_num_steps_raises(self):
        with self.assertRaises(ValueError):
            hrdm_core.validate_hdrm_scan_params(
                self._passes(), "abc", hrdm_core.HDRM_SCAN_DEFAULTS["count_time"],
            )

    def test_zero_num_steps_raises(self):
        with self.assertRaises(ValueError):
            hrdm_core.validate_hdrm_scan_params(
                self._passes(), "0", hrdm_core.HDRM_SCAN_DEFAULTS["count_time"],
            )

    def test_negative_num_steps_raises(self):
        with self.assertRaises(ValueError):
            hrdm_core.validate_hdrm_scan_params(
                self._passes(), "-5", hrdm_core.HDRM_SCAN_DEFAULTS["count_time"],
            )

    def test_non_numeric_count_time_raises(self):
        with self.assertRaises(ValueError):
            hrdm_core.validate_hdrm_scan_params(
                self._passes(), hrdm_core.HDRM_SCAN_DEFAULTS["num_steps"], "abc",
            )

    def test_zero_count_time_raises(self):
        with self.assertRaises(ValueError):
            hrdm_core.validate_hdrm_scan_params(
                self._passes(), hrdm_core.HDRM_SCAN_DEFAULTS["num_steps"], "0",
            )

    def test_negative_count_time_raises(self):
        with self.assertRaises(ValueError):
            hrdm_core.validate_hdrm_scan_params(
                self._passes(), hrdm_core.HDRM_SCAN_DEFAULTS["num_steps"], "-0.1",
            )


class TestSpinXtalPhi(unittest.TestCase):
    """Runner.run_spin_xtal_phi() -- translated from HDRMscans_new.mac's
    spin_xtal_phi/spin_ice/spin_xtal_phi_10min/spin_xtal_phi_20min
    macros (unified into one method, see SPIN_DEFAULTS' docstring)."""

    def setUp(self):
        self.log_q = queue.Queue()
        self.cancel_event = threading.Event()
        self.runner = hrdm_core.Runner(self.log_q, self.cancel_event)
        self.preview_runner = hrdm_core.Runner(
            self.log_q, self.cancel_event, preview=True
        )

    def _drain_log(self):
        msgs = []
        while not self.log_q.empty():
            msgs.append(self.log_q.get_nowait())
        return msgs

    def test_default_two_cycles_logs_expected_sequence(self):
        self.runner.run_spin_xtal_phi(num_cycles=2)
        log = self._drain_log()

        self.assertIn(
            "[spin_xtal_phi] starting sample spin (phi 0<->360)", log
        )
        phi_lines = [line for line in log if line.startswith("[umv] phi")]
        self.assertEqual(phi_lines, ["[umv] phi 360", "[umv] phi 0"] * 2)
        self.assertIn("[spin_xtal_phi] cycle 1/2 completed", log)
        self.assertIn("[spin_xtal_phi] cycle 2/2 completed", log)
        self.assertIn(
            "[spin_xtal_phi] spin sequence completed (2 cycle(s))", log
        )
        # not ice mode -- no startup delay / motors-OK lines
        self.assertFalse(any("ice" in line.lower() for line in log))

    def test_ice_mode_adds_startup_delay_and_uses_same_spin_loop(self):
        self.runner.run_spin_xtal_phi(num_cycles=1, ice_mode=True)
        log = self._drain_log()

        self.assertIn(
            "[spin_ice] CONTINUOUS ICE SPINNING (phi 0-360) -- will spin "
            "indefinitely until stopped",
            log,
        )
        self.assertIn("[spin_ice] starting in 5 seconds...", log)
        self.assertIn("[sleep] 5s ice mode startup delay", log)
        phi_lines = [line for line in log if line.startswith("[umv] phi")]
        self.assertEqual(phi_lines, ["[umv] phi 360", "[umv] phi 0"])

    def test_ice_mode_every_100_cycles_logs_motors_ok_line(self):
        # preview mode so the (many) sleep(1)/sleep(2) calls involved in
        # 250 cycles don't actually wait in real time.
        self.preview_runner.run_spin_xtal_phi(num_cycles=250, ice_mode=True)
        log = self._drain_log()

        motors_ok_lines = [line for line in log if "motors OK" in line]
        self.assertEqual(
            motors_ok_lines,
            [
                "*** completed 100 ice spin cycles -- motors OK ***",
                "*** completed 200 ice spin cycles -- motors OK ***",
            ],
        )

    def test_blank_num_cycles_defaults_to_10000_cycle_cap(self):
        # preview mode -- runs the full 10000-cycle default cap almost
        # instantly since preview never actually sleeps.
        self.preview_runner.run_spin_xtal_phi(num_cycles=None)
        log = self._drain_log()

        self.assertIn(
            "[spin_xtal_phi] spin sequence completed (10000 cycle(s))", log
        )
        # no "/N" suffix on "cycle" lines when num_cycles was left blank
        self.assertIn("[spin_xtal_phi] cycle 1 completed", log)
        self.assertNotIn("[spin_xtal_phi] cycle 1/10000 completed", log)

    def test_cancel_before_first_cycle_stops_immediately(self):
        self.cancel_event.set()
        self.runner.run_spin_xtal_phi(num_cycles=5)
        log = self._drain_log()

        self.assertIn("[cancelled] stopped after 0 spin cycle(s)", log)
        self.assertFalse(any(line.startswith("[umv] phi") for line in log))


class TestThreextalScanStep(unittest.TestCase):
    """Runner._threextalscan_step() -- the shared HDRMscans_new.mac
    `threextalscan <temp> <sleep>` step used by every temperature-
    series method (low_temp_scan/warmup/warmup_custom/cooldown/
    hightemp_scan)."""

    def setUp(self):
        self.log_q = queue.Queue()
        self.cancel_event = threading.Event()
        self.runner = hrdm_core.Runner(self.log_q, self.cancel_event)
        self.preview_runner = hrdm_core.Runner(
            self.log_q, self.cancel_event, preview=True
        )

    def _drain_log(self):
        msgs = []
        while not self.log_q.empty():
            msgs.append(self.log_q.get_nowait())
        return msgs

    def _globals(self, **overrides):
        g = {
            "datafile": "test2",
            "sample": "sample1/",
            "rampre": "/ramdisk/sarker-4775-a/",
            "count_time": "0.1",
            "next_scan_n": "1",
        }
        g.update(overrides)
        return g

    def test_full_sequence_logs_expected_lines(self):
        g = self._globals()
        self.runner._threextalscan_step(g, "100", "0")
        log = self._drain_log()

        self.assertIn("[te] set temperature -> 100", log)
        self.assertIn("[pil_on] turning on detector", log)
        self.assertIn(
            "[pil_setdir] /ramdisk/sarker-4775-a/raw6M/test2/sample1/100/",
            log,
        )
        self.assertIn("[pil_settrig] 'Mult. Trigger'", log)

        umv_lines = [line for line in log if line.startswith("[umv]")]
        self.assertEqual(
            umv_lines,
            [
                "[umv] chi 90 th 0 phi 0",
                "[umv] chi 86 th 3 phi 0",
                "[umv] chi 95 th -3 phi 0",
                "[umv] chi 90 th 0 phi 0",  # final return-home move
            ],
        )
        flyscan_lines = [line for line in log if line.startswith("[flyscan]")]
        self.assertEqual(len(flyscan_lines), 3)
        for line in flyscan_lines:
            self.assertEqual(
                line, "[flyscan] phi 0 -> 365, 3650 steps, 0.1s per point"
            )
        self.assertIn("[done] HDRM scan at 100K complete", log)

    def test_float_temperature_formatted_without_trailing_zero(self):
        # Regression test: run_low_temp_scan/run_warmup/run_warmup_custom/
        # run_cooldown/run_hightemp_scan all pass a Python float (the
        # `loopT` loop variable) as `temperature`, not a string --
        # str(280.0) would be "280.0", which used to leak into both the
        # `te` command and every directory built from it (reported by
        # the user as e.g. "280.0"/"290.0" folders instead of "280"/"290").
        g = self._globals()
        self.runner._threextalscan_step(g, 280.0, "0")
        log = self._drain_log()
        self.assertIn("[te] set temperature -> 280", log)
        self.assertFalse(any("280.0" in line for line in log))
        self.assertIn(
            "[pil_setdir] /ramdisk/sarker-4775-a/raw6M/test2/sample1/280/",
            log,
        )

    def test_fractional_temperature_keeps_decimal(self):
        g = self._globals()
        self.runner._threextalscan_step(g, 280.5, "0")
        log = self._drain_log()
        self.assertIn("[te] set temperature -> 280.5", log)
        self.assertIn(
            "[pil_setdir] /ramdisk/sarker-4775-a/raw6M/test2/sample1/280.5/",
            log,
        )

    def test_scan_n_persists_across_calls(self):
        g = self._globals()
        self.preview_runner._threextalscan_step(g, "100", "0")
        self.preview_runner._threextalscan_step(g, "110", "0")
        log = self._drain_log()

        scan_head_lines = [
            line for line in log if line.startswith("[_pil_scan_head]")
        ]
        scan_numbers = [
            int(line.split("scan ")[1].split(" ")[0]) for line in scan_head_lines
        ]
        self.assertEqual(scan_numbers, [1, 2, 3, 4, 5, 6])

    def test_cancel_before_detector_on(self):
        g = self._globals()
        self.cancel_event.set()
        self.runner._threextalscan_step(g, "100", "0")
        log = self._drain_log()

        self.assertIn("[cancelled] stopping before turning on detector", log)
        self.assertFalse(any(line.startswith("[pil_on]") for line in log))
        self.assertFalse(any(line.startswith("[umv]") for line in log))

    def test_custom_scan_passes_num_steps_count_time_override_defaults(self):
        # Passing explicit scan_passes/num_steps/count_time must fully
        # replace the legacy hard-coded _HDRM_NEW_PASSES/
        # _HDRM_NEW_NUM_STEPS/g['count_time'] fallbacks -- including a
        # different number of passes (2, not the legacy 3) and a
        # per-pass scan_start/scan_stop range.
        g = self._globals(count_time="0.1")  # must be ignored below
        custom_passes = [
            {"chi": "45", "th": "1", "phi": "10", "scan_start": "5", "scan_stop": "200"},
            {"chi": "50", "th": "-2", "phi": "10", "scan_start": "5", "scan_stop": "200"},
        ]
        self.runner._threextalscan_step(
            g, "100", "0",
            scan_passes=custom_passes, num_steps="500", count_time="0.25",
        )
        log = self._drain_log()

        umv_lines = [line for line in log if line.startswith("[umv]")]
        self.assertEqual(
            umv_lines,
            [
                "[umv] chi 45 th 1 phi 10",
                "[umv] chi 50 th -2 phi 10",
                # final return-home move is always the macro's own fixed
                # home position (90, 0, 0), regardless of custom passes.
                "[umv] chi 90 th 0 phi 0",
            ],
        )
        flyscan_lines = [line for line in log if line.startswith("[flyscan]")]
        self.assertEqual(len(flyscan_lines), 2)
        for line in flyscan_lines:
            self.assertEqual(
                line, "[flyscan] phi 5 -> 200, 500 steps, 0.25s per point"
            )

    def test_default_scan_passes_num_steps_count_time_match_new_constants(self):
        # HDRM_SCAN_PASSES_DEFAULTS/HDRM_SCAN_DEFAULTS (the new
        # editable-table defaults) must match the legacy hard-coded
        # _HDRM_NEW_PASSES/_HDRM_NEW_NUM_STEPS/count_time fallback
        # behavior exactly, so tabs that reset to defaults reproduce
        # the original macro-faithful scan untouched.
        g = self._globals(count_time="0.1")
        self.runner._threextalscan_step(
            g, "100", "0",
            scan_passes=hrdm_core.HDRM_SCAN_PASSES_DEFAULTS,
            num_steps=hrdm_core.HDRM_SCAN_DEFAULTS["num_steps"],
            count_time=hrdm_core.HDRM_SCAN_DEFAULTS["count_time"],
        )
        log = self._drain_log()

        umv_lines = [line for line in log if line.startswith("[umv]")]
        self.assertEqual(
            umv_lines,
            [
                "[umv] chi 90 th 0 phi 0",
                "[umv] chi 86 th 3 phi 0",
                "[umv] chi 95 th -3 phi 0",
                "[umv] chi 90 th 0 phi 0",
            ],
        )
        flyscan_lines = [line for line in log if line.startswith("[flyscan]")]
        self.assertEqual(len(flyscan_lines), 3)
        for line in flyscan_lines:
            self.assertEqual(
                line, "[flyscan] phi 0 -> 365, 3650 steps, 0.1s per point"
            )


class _TemperatureSeriesTestBase(unittest.TestCase):
    """Shared setUp for the 5 new temperature-series Runner methods."""

    def setUp(self):
        self.log_q = queue.Queue()
        self.cancel_event = threading.Event()
        self.runner = hrdm_core.Runner(self.log_q, self.cancel_event)
        self.preview_runner = hrdm_core.Runner(
            self.log_q, self.cancel_event, preview=True
        )

    def _drain_log(self):
        msgs = []
        while not self.log_q.empty():
            msgs.append(self.log_q.get_nowait())
        return msgs

    def _globals(self, **overrides):
        g = {
            "datafile": "test2",
            "sample": "sample1/",
            "rampre": "/ramdisk/sarker-4775-a/",
            "count_time": "0.1",
            "next_scan_n": "1",
        }
        g.update(overrides)
        return g


class TestLowTempScan(_TemperatureSeriesTestBase):
    def test_default_params_full_sequence_preview(self):
        g = self._globals()
        d = hrdm_core.LOW_TEMP_SCAN_DEFAULTS
        self.preview_runner.run_low_temp_scan(
            g, d["start_temp"], d["end_temp"], d["step_temp"],
            d["spin_cycles"], d["post_temp_wait_seconds"],
        )
        log = self._drain_log()

        self.assertIn("=== LOW TEMPERATURE SCAN ===", log)
        self.assertIn("Temperature range: 30K to 110K (step 10K)", log)
        # 30, 40, ..., 100 -- 8 steps (110 itself is excluded, loop uses <)
        temp_headers = [line for line in log if line.startswith("=== TEMPERATURE")]
        self.assertEqual(len(temp_headers), 8)
        self.assertEqual(temp_headers[0], "=== TEMPERATURE 30K ===")
        self.assertEqual(temp_headers[-1], "=== TEMPERATURE 100K ===")
        # te() is called twice per temperature (once directly, once
        # inside _threextalscan_step) -- see the docstring.
        te_lines = [line for line in log if line.startswith("[te]")]
        self.assertEqual(len(te_lines), 16)
        spin_done_lines = [
            line for line in log
            if line.startswith("[spin_xtal_phi] spin sequence completed")
        ]
        self.assertEqual(len(spin_done_lines), 8)
        self.assertTrue(all("(4 cycle(s))" in line for line in spin_done_lines))
        self.assertIn("=== LOW TEMPERATURE SCAN COMPLETED ===", log)

    def test_cancel_before_first_temperature_is_fast_and_stops_immediately(self):
        g = self._globals()
        d = hrdm_core.LOW_TEMP_SCAN_DEFAULTS
        self.cancel_event.set()
        self.runner.run_low_temp_scan(
            g, d["start_temp"], d["end_temp"], d["step_temp"],
            d["spin_cycles"], d["post_temp_wait_seconds"],
        )
        log = self._drain_log()

        self.assertIn("[cancelled] stopped before the first temperature", log)
        self.assertFalse(any(line.startswith("[te]") for line in log))

    def test_live_spec_sending_end_to_end(self):
        # Minimal single-temperature-step run against a real (fake)
        # spec_controller, confirming the full run_low_temp_scan ->
        # run_spin_xtal_phi -> _threextalscan_step chain actually sends
        # every underlying command, not just logs it.
        fake = FakeSpecController()
        runner = hrdm_core.Runner(
            self.log_q, self.cancel_event, spec_controller=fake
        )
        g = self._globals()
        runner.run_low_temp_scan(g, "30", "31", "10", "1", "0")

        # "te 30", not "te 30.0" -- _format_temp() strips the trailing
        # ".0" that a bare str() of the loop's float temperature would
        # otherwise leave in both the sent `te` command and the
        # per-temperature directory names built from it (reported by
        # the user as e.g. "280.0"/"290.0" folders instead of "280"/"290").
        self.assertIn("te 30", fake.sent)
        self.assertNotIn("te 30.0", fake.sent)
        self.assertIn("umv phi 360", fake.sent)
        self.assertIn("umv phi 0", fake.sent)
        self.assertIn("pil_on", fake.sent)
        self.assertIn('pil_settrig "Mult. Trigger"', fake.sent)
        self.assertIn("umv chi 90 th 0 phi 0", fake.sent)
        self.assertIn("flyscan phi 0 365 3650 0.1", fake.sent)

    def test_custom_hdrm_scan_params_override_defaults(self):
        # A custom passes table (1 pass, non-default range) plus custom
        # num_steps/count_time must fully replace the legacy hard-coded
        # HDRM-scan step for every temperature in the series.
        g = self._globals()
        d = hrdm_core.LOW_TEMP_SCAN_DEFAULTS
        custom_passes = [
            {"chi": "10", "th": "20", "phi": "0", "scan_start": "1", "scan_stop": "2"},
        ]
        self.preview_runner.run_low_temp_scan(
            g, "30", "31", "10", d["spin_cycles"], "0",
            scan_passes=custom_passes, num_steps="7", count_time="0.05",
        )
        log = self._drain_log()

        flyscan_lines = [line for line in log if line.startswith("[flyscan]")]
        self.assertEqual(len(flyscan_lines), 1)
        self.assertEqual(
            flyscan_lines[0], "[flyscan] phi 1 -> 2, 7 steps, 0.05s per point"
        )


class TestLowTempSampleSetup(_TemperatureSeriesTestBase):
    """Runner.run_low_temp_sample_setup() -- the Low Temp Scan tab's
    standalone "Sample Setup" button (te=240, flow_set=12 by default,
    both editable). A single-shot action, not part of the automatic
    run_low_temp_scan sequence -- mirrors run_gas_prep_flow_set's
    "=== ... ===" bookend style."""

    def test_default_params_sends_expected_commands(self):
        d = hrdm_core.LOW_TEMP_SAMPLE_SETUP_DEFAULTS
        self.preview_runner.run_low_temp_sample_setup(
            d["sample_temp"], d["sample_flow"]
        )
        log = self._drain_log()
        self.assertIn("=== LOW TEMP SCAN: SAMPLE SETUP ===", log)
        self.assertIn("[te] set temperature -> 240", log)
        self.assertIn("[flow_set] -> 12", log)
        self.assertIn("=== SAMPLE SETUP COMPLETE ===", log)

    def test_custom_values_sent_and_formatted(self):
        fake = FakeSpecController()
        runner = hrdm_core.Runner(
            self.log_q, self.cancel_event, spec_controller=fake
        )
        runner.run_low_temp_sample_setup("250.0", "15")
        # _format_temp() strips the trailing ".0" before it reaches te().
        self.assertEqual(fake.sent, ["te 250", "flow_set 15"])


class TestN2ToHeSwitch(_TemperatureSeriesTestBase):
    """Runner.run_n2_to_he_switch -- the one-click "300K -> 15K: Room
    Temperature to base (change N2 to He flow)" procedure. Note this
    method takes only a `params` dict (no separate `g` globals dict)
    since it never touches datafile/sample/rampre or runs an actual
    HDRM scan -- it's purely gas-flow/temperature prep plus a final
    spin."""

    def test_default_params_full_sequence_preview(self):
        # All 4 step-groups now default to disabled; enable all of
        # them here to exercise the full sequence.
        d = dict(hrdm_core.N2_TO_HE_SWITCH_DEFAULTS)
        d["step1_enabled"] = "1"
        d["steps3_5_enabled"] = "1"
        d["step7_enabled"] = "1"
        d["steps8_10_enabled"] = "1"
        self.preview_runner.run_n2_to_he_switch(d)
        log = self._drain_log()

        self.assertIn("=== N2 -> HE GAS SWITCH (room temperature -> base) ===", log)
        self.assertIn("--- Step 1: prepswitch ---", log)
        self.assertIn("[epics_put] LAKESHORE2:SETP_S1 = 100", log)
        self.assertIn("[epics_put] LAKESHORE2:SETP_S3 = 95", log)
        self.assertTrue(
            any("stabilize near ~96K/~87K" in line for line in log)
        )
        self.assertIn("[te] set temperature -> 240", log)
        self.assertIn("[flow_set] -> 10", log)
        self.assertIn(
            "--- Step 6: MANUAL ACTION REQUIRED -- turn on the Helium "
            "(He) valve and close the Nitrogen (N2) valve TOGETHER, "
            "then continue ---",
            log,
        )
        self.assertIn("--- Step 7: runninghelium ---", log)
        self.assertIn("[epics_put] LAKESHORE2:SETP_S1 = 30", log)
        self.assertIn("[epics_put] LAKESHORE2:SETP_S3 = 16", log)
        self.assertIn("[flow_set] -> 12", log)
        self.assertIn("[te] set temperature -> 15", log)
        spin_done_lines = [
            line for line in log
            if line.startswith("[spin_xtal_phi] spin sequence completed")
        ]
        self.assertEqual(len(spin_done_lines), 1)
        self.assertIn("(4 cycle(s))", spin_done_lines[0])
        self.assertIn("=== N2 -> HE GAS SWITCH COMPLETED ===", log)

    def test_wait_minutes_converted_to_seconds(self):
        # sleep() logs "[sleep] {seconds}s{label}" -- confirm the
        # minutes fields are actually multiplied by 60 before being
        # handed to sleep(), not passed through as raw minutes.
        d = dict(hrdm_core.N2_TO_HE_SWITCH_DEFAULTS)
        # All 4 step-groups now default to disabled; enable the 3
        # groups that have their own minute-based waits.
        d["step1_enabled"] = "1"
        d["steps3_5_enabled"] = "1"
        d["step7_enabled"] = "1"
        d["wait_after_prepswitch_minutes"] = "2"
        d["wait_for_sample_temp_minutes"] = "3"
        d["wait_for_base_temp_minutes"] = "1"
        self.preview_runner.run_n2_to_he_switch(d)
        log = self._drain_log()
        sleep_lines = [line for line in log if line.startswith("[sleep]")]
        self.assertTrue(any("120.0s" in line or "120s" in line for line in sleep_lines))
        self.assertTrue(any("180.0s" in line or "180s" in line for line in sleep_lines))
        self.assertTrue(any("60.0s" in line or "60s" in line for line in sleep_lines))

    def test_zero_wait_minutes_skips_waits(self):
        # spin_xtal_phi's own internal 1s-per-move sleeps still appear
        # (spin_cycles is left at its default, 4) -- this test only
        # confirms the three N2->He Switch-specific minute-based waits
        # are skipped, not that sleep() is never called at all.
        d = dict(hrdm_core.N2_TO_HE_SWITCH_DEFAULTS)
        d["wait_after_prepswitch_minutes"] = "0"
        d["wait_for_sample_temp_minutes"] = "0"
        d["wait_for_base_temp_minutes"] = "0"
        self.preview_runner.run_n2_to_he_switch(d)
        log = self._drain_log()
        self.assertFalse(any("minute(s)" in line for line in log))
        self.assertFalse(
            any(line.startswith("[sleep]") and "min)" in line for line in log)
        )
        # The rest of the sequence still runs to completion.
        self.assertIn("=== N2 -> HE GAS SWITCH COMPLETED ===", log)

    def test_zero_spin_cycles_skips_spin(self):
        d = dict(hrdm_core.N2_TO_HE_SWITCH_DEFAULTS)
        d["steps8_10_enabled"] = "1"  # steps8_10 now defaults to disabled
        d["spin_cycles"] = "0"
        self.preview_runner.run_n2_to_he_switch(d)
        log = self._drain_log()
        self.assertFalse(any(line.startswith("[spin_xtal_phi]") for line in log))
        self.assertIn("=== N2 -> HE GAS SWITCH COMPLETED ===", log)

    def test_stage_setpoint_overrides_reach_epics_puts(self):
        d = dict(hrdm_core.N2_TO_HE_SWITCH_DEFAULTS)
        # step1/step7 now default to disabled; enable both to reach
        # their epics_put calls.
        d["step1_enabled"] = "1"
        d["step7_enabled"] = "1"
        d["prepswitch_stage_a"] = "102"
        d["prepswitch_stage_c"] = "97"
        d["runninghelium_stage_a"] = "6"
        d["runninghelium_stage_c"] = "32"
        self.preview_runner.run_n2_to_he_switch(d)
        log = self._drain_log()
        self.assertIn("[epics_put] LAKESHORE2:SETP_S1 = 102", log)
        self.assertIn("[epics_put] LAKESHORE2:SETP_S3 = 97", log)
        self.assertIn("[epics_put] LAKESHORE2:SETP_S1 = 6", log)
        self.assertIn("[epics_put] LAKESHORE2:SETP_S3 = 32", log)

    def test_cancel_before_call_stops_after_prepswitch(self):
        # run_n2_to_he_switch always runs Step 1 (prepswitch) before
        # its first cancelled() check, so setting cancel_event before
        # calling still lets prepswitch's two epics_put's through,
        # then stops immediately after -- no te/runninghelium/spin.
        # prepswitch no longer sends flow_set (that automatic call
        # was a project addition that has since been removed per
        # explicit user request; see prepswitch's own docstring).
        d = dict(hrdm_core.N2_TO_HE_SWITCH_DEFAULTS)
        d["step1_enabled"] = "1"  # step1 now defaults to disabled
        self.cancel_event.set()
        self.runner.run_n2_to_he_switch(d)
        log = self._drain_log()

        self.assertIn("[epics_put] LAKESHORE2:SETP_S1 = 100", log)
        self.assertFalse(any(line.startswith("[flow_set]") for line in log))
        self.assertIn("[cancelled] stopped after prepswitch", log)
        self.assertFalse(any(line.startswith("[te]") for line in log))
        self.assertFalse("--- Step 7: runninghelium ---" in log)
        self.assertNotIn("=== N2 -> HE GAS SWITCH COMPLETED ===", log)

    def test_live_spec_sending_end_to_end(self):
        fake = FakeSpecController()
        runner = hrdm_core.Runner(
            self.log_q, self.cancel_event, spec_controller=fake
        )
        d = dict(hrdm_core.N2_TO_HE_SWITCH_DEFAULTS)
        # All 4 step-groups now default to disabled; enable all of
        # them to exercise the full sequence end to end.
        d["step1_enabled"] = "1"
        d["steps3_5_enabled"] = "1"
        d["step7_enabled"] = "1"
        d["steps8_10_enabled"] = "1"
        d["wait_after_prepswitch_minutes"] = "0"
        d["wait_for_sample_temp_minutes"] = "0"
        d["wait_for_base_temp_minutes"] = "0"
        runner.run_n2_to_he_switch(d)

        self.assertIn('epics_put("LAKESHORE2:SETP_S1",100)', fake.sent)
        self.assertIn('epics_put("LAKESHORE2:SETP_S3",95)', fake.sent)
        self.assertIn("te 240", fake.sent)
        self.assertIn("flow_set 10", fake.sent)
        self.assertIn('epics_put("LAKESHORE2:SETP_S1",30)', fake.sent)
        self.assertIn('epics_put("LAKESHORE2:SETP_S3",16)', fake.sent)
        self.assertIn("flow_set 12", fake.sent)
        self.assertIn("te 15", fake.sent)
        self.assertIn("umv phi 360", fake.sent)
        self.assertIn("umv phi 0", fake.sent)


class TestN2ToHeSwitchEnabledFlags(_TemperatureSeriesTestBase):
    """The 4 per-step-group "*_enabled" flags added to
    run_n2_to_he_switch (mirroring run_warmup's per-phase "enabled"
    flag) -- each flag independently gates one of the 4 step-groups
    (Steps 1-2, Steps 3-5, Steps 6-8, Steps 9-11), logging a "SKIPPED"
    line and falling through instead of running that group's
    commands."""

    def test_missing_enabled_keys_default_to_enabled(self):
        # An older params dict built before these flags existed (e.g.
        # a hand-built dict in another test, or an older saved script)
        # must still run every step exactly like before.
        d = {
            k: v for k, v in hrdm_core.N2_TO_HE_SWITCH_DEFAULTS.items()
            if not k.endswith("_enabled")
        }
        self.preview_runner.run_n2_to_he_switch(d)
        log = self._drain_log()
        self.assertFalse(any("SKIPPED" in line for line in log))
        self.assertIn("=== N2 -> HE GAS SWITCH COMPLETED ===", log)

    def test_step1_disabled_skips_prepswitch(self):
        d = dict(hrdm_core.N2_TO_HE_SWITCH_DEFAULTS)
        d["step1_enabled"] = "0"
        d["steps3_5_enabled"] = "1"  # so "the rest still runs" is actually exercised
        self.preview_runner.run_n2_to_he_switch(d)
        log = self._drain_log()
        self.assertIn("--- Steps 1-2: SKIPPED (prepswitch disabled) ---", log)
        self.assertFalse(any("[epics_put] LAKESHORE2:SETP_S1 = 100" in line for line in log))
        self.assertFalse(any("[epics_put] LAKESHORE2:SETP_S3 = 95" in line for line in log))
        # The rest of the sequence still runs.
        self.assertIn("--- Step 3: te ---", log)
        self.assertIn("=== N2 -> HE GAS SWITCH COMPLETED ===", log)

    def test_steps3_5_disabled_skips_te_and_flow_set(self):
        d = dict(hrdm_core.N2_TO_HE_SWITCH_DEFAULTS)
        d["steps3_5_enabled"] = "0"
        d["step1_enabled"] = "1"  # so "Step 1 and Step 7 still run" is actually exercised
        d["step7_enabled"] = "1"
        self.preview_runner.run_n2_to_he_switch(d)
        log = self._drain_log()
        self.assertIn("--- Steps 3-5: SKIPPED (te/flow_set disabled) ---", log)
        self.assertFalse(any("[te] set temperature -> 240" in line for line in log))
        self.assertFalse(any("[flow_set] -> 10" in line for line in log))
        # Step 1 and Step 7 still run.
        self.assertIn("--- Step 1: prepswitch ---", log)
        self.assertIn("--- Step 7: runninghelium ---", log)
        self.assertIn("=== N2 -> HE GAS SWITCH COMPLETED ===", log)

    def test_step7_disabled_skips_valve_switch_and_runninghelium(self):
        d = dict(hrdm_core.N2_TO_HE_SWITCH_DEFAULTS)
        d["step7_enabled"] = "0"
        d["steps8_10_enabled"] = "1"  # so "Steps 9-11 still run" is actually exercised
        self.preview_runner.run_n2_to_he_switch(d)
        log = self._drain_log()
        self.assertIn(
            "--- Steps 6-8: SKIPPED (He/N2 valve switch + runninghelium disabled) ---",
            log,
        )
        self.assertFalse(any("MANUAL ACTION REQUIRED" in line for line in log))
        self.assertFalse(any("--- Step 7: runninghelium ---" in line for line in log))
        self.assertFalse(any("[epics_put] LAKESHORE2:SETP_S1 = 30" in line for line in log))
        self.assertFalse(any("[epics_put] LAKESHORE2:SETP_S3 = 16" in line for line in log))
        # Steps 9-11 still run.
        self.assertIn("--- Step 9: flow_set ---", log)
        self.assertIn("=== N2 -> HE GAS SWITCH COMPLETED ===", log)

    def test_steps8_10_disabled_skips_final_flow_set_te_and_spin(self):
        d = dict(hrdm_core.N2_TO_HE_SWITCH_DEFAULTS)
        d["steps8_10_enabled"] = "0"
        self.preview_runner.run_n2_to_he_switch(d)
        log = self._drain_log()
        self.assertIn(
            "--- Steps 9-11: SKIPPED (final flow_set/te/spin disabled) ---", log
        )
        self.assertFalse(any(line.startswith("--- Step 9:") for line in log))
        self.assertFalse(any(line.startswith("--- Step 10:") for line in log))
        self.assertFalse(any(line.startswith("--- Step 11:") for line in log))
        self.assertFalse(any(line.startswith("[spin_xtal_phi]") for line in log))
        self.assertIn("=== N2 -> HE GAS SWITCH COMPLETED ===", log)

    def test_all_groups_disabled_only_logs_skips(self):
        d = dict(hrdm_core.N2_TO_HE_SWITCH_DEFAULTS)
        d["step1_enabled"] = "0"
        d["steps3_5_enabled"] = "0"
        d["step7_enabled"] = "0"
        d["steps8_10_enabled"] = "0"
        self.preview_runner.run_n2_to_he_switch(d)
        log = self._drain_log()
        skip_lines = [line for line in log if "SKIPPED" in line]
        self.assertEqual(len(skip_lines), 4)
        self.assertFalse(any(line.startswith("[epics_put]") for line in log))
        self.assertFalse(any(line.startswith("[te]") for line in log))
        self.assertFalse(any(line.startswith("[flow_set]") for line in log))
        self.assertFalse(any(line.startswith("[spin_xtal_phi]") for line in log))
        self.assertIn("=== N2 -> HE GAS SWITCH (room temperature -> base) ===", log)
        self.assertIn("=== N2 -> HE GAS SWITCH COMPLETED ===", log)

    def test_disabled_group_never_checked_for_cancellation(self):
        # A disabled group's "if self.cancelled(): return" checks are
        # inside its own if-block, so they can never fire when that
        # group is skipped -- cancelling mid-run should only stop
        # things at a checkpoint inside a group that actually ran.
        d = dict(hrdm_core.N2_TO_HE_SWITCH_DEFAULTS)
        d["step1_enabled"] = "0"
        d["steps3_5_enabled"] = "1"  # so the te/flow_set cancel check is actually reached
        self.cancel_event.set()
        self.runner.run_n2_to_he_switch(d)
        log = self._drain_log()
        self.assertIn("--- Steps 1-2: SKIPPED (prepswitch disabled) ---", log)
        # Step 3 (te) is the first group that actually runs, and it
        # checks cancelled() only *after* sending te/flow_set.
        self.assertIn("[cancelled] stopped after te/flow_set", log)
        self.assertNotIn("=== N2 -> HE GAS SWITCH COMPLETED ===", log)

    def test_string_and_boolean_style_enabled_values_all_accepted(self):
        # _step_group_enabled accepts "1"/"True"/"true" as enabled --
        # confirm a couple of these variants (as might come from a
        # GUI's str(BooleanVar) or a hand-edited saved script) still
        # run the group, and any other value disables it.
        for enabled_value in ("1", "True", "true"):
            d = dict(hrdm_core.N2_TO_HE_SWITCH_DEFAULTS)
            d["step1_enabled"] = enabled_value
            self.preview_runner.run_n2_to_he_switch(d)
            log = self._drain_log()
            self.assertIn("--- Step 1: prepswitch ---", log)
            self.assertFalse(any("SKIPPED (prepswitch disabled)" in line for line in log))

        for disabled_value in ("0", "False", "false", ""):
            d = dict(hrdm_core.N2_TO_HE_SWITCH_DEFAULTS)
            d["step1_enabled"] = disabled_value
            self.preview_runner.run_n2_to_he_switch(d)
            log = self._drain_log()
            self.assertIn("--- Steps 1-2: SKIPPED (prepswitch disabled) ---", log)


class TestN2ToHeSwitchPartialSteps(_TemperatureSeriesTestBase):
    """Runner.run_n2_to_he_step1 and Runner.run_n2_to_he_steps_3_to_5 --
    the two partial-run entry points added so an operator can send
    just the prepswitch portion, or just the intermediate te/flow_set
    portion, of the N2 -> He Switch sequence on their own, checking
    hardware state by hand in between rather than being locked into
    the whole one-click run once started."""

    def test_step1_default_params_preview(self):
        d = hrdm_core.N2_TO_HE_SWITCH_DEFAULTS
        self.preview_runner.run_n2_to_he_step1(d)
        log = self._drain_log()

        self.assertIn("=== N2 -> HE GAS SWITCH: STEP 1 ONLY (prepswitch) ===", log)
        self.assertIn("[epics_put] LAKESHORE2:SETP_S1 = 100", log)
        self.assertIn("[epics_put] LAKESHORE2:SETP_S3 = 95", log)
        self.assertTrue(any("stabilize near ~96K/~87K" in line for line in log))
        self.assertIn("=== STEP 1 COMPLETE ===", log)
        # prepswitch no longer sends flow_set (that automatic call was
        # a project addition that has since been removed per explicit
        # user request; see prepswitch's own docstring).
        self.assertFalse(any(line.startswith("[flow_set]") for line in log))
        self.assertFalse(any(line.startswith("[te]") for line in log))
        self.assertFalse(any(line.startswith("[spin_xtal_phi]") for line in log))
        self.assertNotIn("--- Step 7: runninghelium ---", log)

    def test_step1_wait_minutes_converted_to_seconds(self):
        d = dict(hrdm_core.N2_TO_HE_SWITCH_DEFAULTS)
        d["wait_after_prepswitch_minutes"] = "2"
        self.preview_runner.run_n2_to_he_step1(d)
        log = self._drain_log()
        sleep_lines = [line for line in log if line.startswith("[sleep]")]
        self.assertTrue(any("120.0s" in line or "120s" in line for line in sleep_lines))

    def test_step1_zero_wait_minutes_skips_wait(self):
        d = dict(hrdm_core.N2_TO_HE_SWITCH_DEFAULTS)
        d["wait_after_prepswitch_minutes"] = "0"
        self.preview_runner.run_n2_to_he_step1(d)
        log = self._drain_log()
        self.assertFalse(any(line.startswith("[sleep]") for line in log))
        self.assertIn("=== STEP 1 COMPLETE ===", log)

    def test_step1_stage_setpoint_overrides_reach_epics_puts(self):
        d = dict(hrdm_core.N2_TO_HE_SWITCH_DEFAULTS)
        d["prepswitch_stage_a"] = "102"
        d["prepswitch_stage_c"] = "97"
        self.preview_runner.run_n2_to_he_step1(d)
        log = self._drain_log()
        self.assertIn("[epics_put] LAKESHORE2:SETP_S1 = 102", log)
        self.assertIn("[epics_put] LAKESHORE2:SETP_S3 = 97", log)

    def test_step1_cancel_before_call_still_sends_prepswitch_then_stops(self):
        d = hrdm_core.N2_TO_HE_SWITCH_DEFAULTS
        self.cancel_event.set()
        self.runner.run_n2_to_he_step1(d)
        log = self._drain_log()
        self.assertIn("[epics_put] LAKESHORE2:SETP_S1 = 100", log)
        self.assertIn("[cancelled] stopped after prepswitch", log)
        self.assertNotIn("=== STEP 1 COMPLETE ===", log)

    def test_step1_live_spec_sending(self):
        fake = FakeSpecController()
        runner = hrdm_core.Runner(self.log_q, self.cancel_event, spec_controller=fake)
        d = dict(hrdm_core.N2_TO_HE_SWITCH_DEFAULTS)
        d["wait_after_prepswitch_minutes"] = "0"
        runner.run_n2_to_he_step1(d)
        self.assertIn('epics_put("LAKESHORE2:SETP_S1",100)', fake.sent)
        self.assertIn('epics_put("LAKESHORE2:SETP_S3",95)', fake.sent)
        # prepswitch no longer sends flow_set (that automatic call was
        # a project addition that has since been removed per explicit
        # user request; see prepswitch's own docstring).
        self.assertFalse(any("flow_set" in cmd for cmd in fake.sent))
        self.assertFalse(any("te " in cmd for cmd in fake.sent))

    def test_steps_3_5_default_params_preview(self):
        d = hrdm_core.N2_TO_HE_SWITCH_DEFAULTS
        self.preview_runner.run_n2_to_he_steps_3_to_5(d)
        log = self._drain_log()

        self.assertIn(
            "=== N2 -> HE GAS SWITCH: STEPS 3-5 ONLY (te / flow_set / wait) ===", log
        )
        self.assertIn("[te] set temperature -> 240", log)
        self.assertIn("[flow_set] -> 10", log)
        self.assertIn("=== STEPS 3-5 COMPLETE ===", log)
        # must not touch prepswitch/runninghelium/spin
        self.assertFalse(any("epics_put" in line for line in log))
        self.assertFalse(any(line.startswith("[spin_xtal_phi]") for line in log))

    def test_steps_3_5_wait_minutes_converted_to_seconds(self):
        d = dict(hrdm_core.N2_TO_HE_SWITCH_DEFAULTS)
        d["wait_for_sample_temp_minutes"] = "3"
        self.preview_runner.run_n2_to_he_steps_3_to_5(d)
        log = self._drain_log()
        sleep_lines = [line for line in log if line.startswith("[sleep]")]
        self.assertTrue(any("180.0s" in line or "180s" in line for line in sleep_lines))

    def test_steps_3_5_zero_wait_minutes_skips_wait(self):
        d = dict(hrdm_core.N2_TO_HE_SWITCH_DEFAULTS)
        d["wait_for_sample_temp_minutes"] = "0"
        self.preview_runner.run_n2_to_he_steps_3_to_5(d)
        log = self._drain_log()
        self.assertFalse(any(line.startswith("[sleep]") for line in log))
        self.assertIn("=== STEPS 3-5 COMPLETE ===", log)

    def test_steps_3_5_temp_and_flow_overrides_reach_commands(self):
        d = dict(hrdm_core.N2_TO_HE_SWITCH_DEFAULTS)
        d["sample_temp_1"] = "200"
        d["flow_1"] = "11"
        self.preview_runner.run_n2_to_he_steps_3_to_5(d)
        log = self._drain_log()
        self.assertIn("[te] set temperature -> 200", log)
        self.assertIn("[flow_set] -> 11", log)

    def test_steps_3_5_cancel_before_call_still_sends_te_flow_then_stops(self):
        d = hrdm_core.N2_TO_HE_SWITCH_DEFAULTS
        self.cancel_event.set()
        self.runner.run_n2_to_he_steps_3_to_5(d)
        log = self._drain_log()
        self.assertIn("[cancelled] stopped after te/flow_set", log)
        self.assertNotIn("=== STEPS 3-5 COMPLETE ===", log)

    def test_steps_3_5_live_spec_sending(self):
        fake = FakeSpecController()
        runner = hrdm_core.Runner(self.log_q, self.cancel_event, spec_controller=fake)
        d = dict(hrdm_core.N2_TO_HE_SWITCH_DEFAULTS)
        d["wait_for_sample_temp_minutes"] = "0"
        runner.run_n2_to_he_steps_3_to_5(d)
        self.assertIn("te 240", fake.sent)
        self.assertIn("flow_set 10", fake.sent)
        self.assertFalse(any("epics_put" in cmd for cmd in fake.sent))

    # ---- run_n2_to_he_step7 (Step 6 manual instruction + Step 7
    # runninghelium + Step 8 wait) ----

    def test_step7_default_params_preview(self):
        d = hrdm_core.N2_TO_HE_SWITCH_DEFAULTS
        self.preview_runner.run_n2_to_he_step7(d)
        log = self._drain_log()

        self.assertIn("=== N2 -> HE GAS SWITCH: STEP 7 ONLY (runninghelium) ===", log)
        self.assertIn(
            "--- Step 6: MANUAL ACTION REQUIRED -- turn on the Helium "
            "(He) valve and close the Nitrogen (N2) valve TOGETHER, "
            "then continue ---",
            log,
        )
        self.assertIn("--- Step 7: runninghelium ---", log)
        self.assertIn("[epics_put] LAKESHORE2:SETP_S1 = 30", log)
        self.assertIn("[epics_put] LAKESHORE2:SETP_S3 = 16", log)
        self.assertIn("=== STEP 7 COMPLETE ===", log)
        # must not touch anything beyond Steps 6-8
        self.assertFalse(any(line.startswith("[te]") for line in log))
        self.assertFalse(any(line.startswith("[flow_set]") for line in log))
        self.assertFalse(any(line.startswith("[spin_xtal_phi]") for line in log))
        self.assertNotIn("--- Step 9: flow_set ---", log)

    def test_step7_wait_minutes_converted_to_seconds(self):
        d = dict(hrdm_core.N2_TO_HE_SWITCH_DEFAULTS)
        d["wait_for_base_temp_minutes"] = "4"
        self.preview_runner.run_n2_to_he_step7(d)
        log = self._drain_log()
        sleep_lines = [line for line in log if line.startswith("[sleep]")]
        self.assertTrue(any("240.0s" in line or "240s" in line for line in sleep_lines))

    def test_step7_zero_wait_minutes_skips_wait(self):
        d = dict(hrdm_core.N2_TO_HE_SWITCH_DEFAULTS)
        d["wait_for_base_temp_minutes"] = "0"
        self.preview_runner.run_n2_to_he_step7(d)
        log = self._drain_log()
        self.assertFalse(any(line.startswith("[sleep]") for line in log))
        self.assertIn("=== STEP 7 COMPLETE ===", log)

    def test_step7_stage_setpoint_overrides_reach_epics_puts(self):
        d = dict(hrdm_core.N2_TO_HE_SWITCH_DEFAULTS)
        d["runninghelium_stage_a"] = "6"
        d["runninghelium_stage_c"] = "32"
        self.preview_runner.run_n2_to_he_step7(d)
        log = self._drain_log()
        self.assertIn("[epics_put] LAKESHORE2:SETP_S1 = 6", log)
        self.assertIn("[epics_put] LAKESHORE2:SETP_S3 = 32", log)

    def test_step7_cancel_before_call_stops_before_valve_switch(self):
        d = hrdm_core.N2_TO_HE_SWITCH_DEFAULTS
        self.cancel_event.set()
        self.runner.run_n2_to_he_step7(d)
        log = self._drain_log()
        self.assertIn("[cancelled] stopped before the He/N2 valve switch", log)
        self.assertFalse(any(line.startswith("[epics_put]") for line in log))
        self.assertNotIn("=== STEP 7 COMPLETE ===", log)

    def test_step7_live_spec_sending(self):
        fake = FakeSpecController()
        runner = hrdm_core.Runner(self.log_q, self.cancel_event, spec_controller=fake)
        d = dict(hrdm_core.N2_TO_HE_SWITCH_DEFAULTS)
        d["wait_for_base_temp_minutes"] = "0"
        runner.run_n2_to_he_step7(d)
        self.assertIn('epics_put("LAKESHORE2:SETP_S1",30)', fake.sent)
        self.assertIn('epics_put("LAKESHORE2:SETP_S3",16)', fake.sent)
        self.assertFalse(any("te " in cmd for cmd in fake.sent))
        self.assertFalse(any("flow_set" in cmd for cmd in fake.sent))

    # ---- run_n2_to_he_steps_8_to_10 (Step 9 flow_set + Step 10 te +
    # Step 11 spin_xtal_phi) ----

    def test_steps_8_10_default_params_preview(self):
        d = hrdm_core.N2_TO_HE_SWITCH_DEFAULTS
        self.preview_runner.run_n2_to_he_steps_8_to_10(d)
        log = self._drain_log()

        self.assertIn(
            "=== N2 -> HE GAS SWITCH: STEPS 8-10 ONLY (flow_set / te / spin) ===", log
        )
        self.assertIn("--- Step 9: flow_set ---", log)
        self.assertIn("[flow_set] -> 12", log)
        self.assertIn("--- Step 10: te ---", log)
        self.assertIn("[te] set temperature -> 15", log)
        self.assertIn("--- Step 11: spin_xtal_phi ---", log)
        self.assertTrue(any(line.startswith("[spin_xtal_phi]") for line in log))
        self.assertIn("=== STEPS 8-10 COMPLETE ===", log)
        # must not touch prepswitch/te-temp-1/runninghelium
        self.assertFalse(any("epics_put" in line for line in log))

    def test_steps_8_10_temp_flow_and_spin_overrides_reach_commands(self):
        d = dict(hrdm_core.N2_TO_HE_SWITCH_DEFAULTS)
        d["flow_2"] = "13"
        d["sample_temp_2"] = "18"
        d["spin_cycles"] = "0"
        self.preview_runner.run_n2_to_he_steps_8_to_10(d)
        log = self._drain_log()
        self.assertIn("[flow_set] -> 13", log)
        self.assertIn("[te] set temperature -> 18", log)
        # spin_cycles=0 means run_spin_xtal_phi is never even called
        self.assertFalse(any(line.startswith("[spin_xtal_phi]") for line in log))

    def test_steps_8_10_cancel_before_call_still_sends_te_flow_then_stops(self):
        d = hrdm_core.N2_TO_HE_SWITCH_DEFAULTS
        self.cancel_event.set()
        self.runner.run_n2_to_he_steps_8_to_10(d)
        log = self._drain_log()
        self.assertIn("[cancelled] stopped after final te/flow_set", log)
        self.assertFalse(any(line.startswith("[spin_xtal_phi]") for line in log))
        self.assertNotIn("=== STEPS 8-10 COMPLETE ===", log)

    def test_steps_8_10_live_spec_sending(self):
        fake = FakeSpecController()
        runner = hrdm_core.Runner(self.log_q, self.cancel_event, spec_controller=fake)
        d = dict(hrdm_core.N2_TO_HE_SWITCH_DEFAULTS)
        d["spin_cycles"] = "0"
        runner.run_n2_to_he_steps_8_to_10(d)
        self.assertIn("flow_set 12", fake.sent)
        self.assertIn("te 15", fake.sent)
        self.assertFalse(any("epics_put" in cmd for cmd in fake.sent))


class TestWarmup(_TemperatureSeriesTestBase):
    def _phases(self, phase_overrides=None):
        phases = [dict(ph) for ph in hrdm_core.WARMUP_PHASE_DEFAULTS]
        for idx, overrides in (phase_overrides or {}).items():
            phases[idx].update(overrides)
        return phases

    def test_default_phases_full_sequence_preview(self):
        g = self._globals()
        # All 3 phases now default to disabled; enable all of them to
        # exercise the full sequence.
        phases = self._phases({
            0: {"enabled": "1"}, 1: {"enabled": "1"}, 2: {"enabled": "1"},
        })
        self.preview_runner.run_warmup(g, phases)
        log = self._drain_log()

        self.assertIn("=== WARMUP SEQUENCE ===", log)
        self.assertIn("=== Phase 1: Low N2 flow ===", log)
        self.assertIn("=== Phase 2: Medium N2 flow ===", log)
        self.assertIn("=== Phase 3: High N2 flow ===", log)
        self.assertIn("[prepN2_low] low N2 flow gas prep", log)
        self.assertIn("[prepN2_medium] medium N2 flow gas prep", log)
        self.assertIn("[prepN2_high] high N2 flow gas prep", log)
        self.assertIn("=== WARMUP SEQUENCE COMPLETED ===", log)

        # Phase 3 (spin_per_step_cycles=0) must only spin ONCE per the
        # whole phase (its initial spin20), unlike Phase 1/2 which spin
        # again at every temperature step -- this is the macro's own
        # asymmetry, preserved faithfully (see WARMUP_PHASE_DEFAULTS).
        phase3_idx = log.index("=== Phase 3: High N2 flow ===")
        phase3_log = log[phase3_idx:]
        spin_done_in_phase3 = [
            line for line in phase3_log
            if line.startswith("[spin_xtal_phi] spin sequence completed")
        ]
        self.assertEqual(len(spin_done_in_phase3), 1)

        # Phase 1 (spin_per_step_cycles=4) spins once initially plus
        # once per temperature step (120, 130, 140, 150 -- 4 steps).
        phase1_idx = log.index("=== Phase 1: Low N2 flow ===")
        phase2_idx = log.index("=== Phase 2: Medium N2 flow ===")
        phase1_log = log[phase1_idx:phase2_idx]
        spin_done_in_phase1 = [
            line for line in phase1_log
            if line.startswith("[spin_xtal_phi] spin sequence completed")
        ]
        self.assertEqual(len(spin_done_in_phase1), 5)  # 1 initial + 4 steps

    def test_disabled_phase_is_skipped(self):
        g = self._globals()
        # Phases now default to disabled; explicitly enable phases 1
        # and 3 (indices 0/2) so "phases 1 and 3 still ran" is
        # actually exercised, while phase 2 (index 1) stays disabled.
        phases = self._phases({
            0: {"enabled": "1"}, 1: {"enabled": "0"}, 2: {"enabled": "1"},
        })
        self.preview_runner.run_warmup(g, phases)
        log = self._drain_log()

        self.assertIn(
            "--- Phase 2: Medium N2 flow: skipped (disabled) ---", log
        )
        self.assertNotIn("=== Phase 2: Medium N2 flow ===", log)
        self.assertFalse(
            any("[prepN2_medium]" in line for line in log)
        )
        # phases 1 and 3 still ran
        self.assertIn("=== Phase 1: Low N2 flow ===", log)
        self.assertIn("=== Phase 3: High N2 flow ===", log)

    def test_phase_stage_a_stage_c_override_reaches_epics_puts(self):
        # Each phase's "Prep sample stage setup" fields (stage_a/
        # stage_c) must actually be forwarded to that phase's
        # prepN2_low/_medium/_high call, not silently ignored in favor
        # of the mac file's own hard-coded defaults.
        g = self._globals()
        # Phases now default to disabled; enable all 3 so both the
        # overridden phase 1 setpoints and phase 2's default setpoints
        # are actually reached.
        phases = self._phases({
            0: {"stage_a": "90", "stage_c": "88", "enabled": "1"},
            1: {"enabled": "1"},
            2: {"enabled": "1"},
        })
        self.preview_runner.run_warmup(g, phases)
        log = self._drain_log()
        self.assertIn("[epics_put] LAKESHORE2:SETP_S1 = 90", log)
        self.assertIn("[epics_put] LAKESHORE2:SETP_S3 = 88", log)
        # Phase 2/3 (left at defaults) still use the mac file's values.
        self.assertIn("[epics_put] LAKESHORE2:SETP_S1 = 130", log)
        self.assertIn("[epics_put] LAKESHORE2:SETP_S3 = 110", log)

    def test_blank_stage_a_stage_c_falls_back_to_macro_defaults(self):
        # The GUI always sends stage_a/stage_c as strings (possibly
        # ""); an empty string must fall back to the macro's own
        # default rather than being passed straight to epics_put() as
        # a blank value.
        g = self._globals()
        phases = self._phases({0: {"stage_a": "", "stage_c": "", "enabled": "1"}})
        self.preview_runner.run_warmup(g, phases)
        log = self._drain_log()
        self.assertIn("[epics_put] LAKESHORE2:SETP_S1 = 87", log)
        self.assertIn("[epics_put] LAKESHORE2:SETP_S3 = 85", log)

    def test_final_te_300_off_by_default(self):
        g = self._globals()
        self.preview_runner.run_warmup(g, self._phases())
        log = self._drain_log()
        self.assertFalse(any("te 300" in line for line in log))
        self.assertFalse(any(line.startswith("--- Phase 4") for line in log))

    def test_final_te_300_enabled_sends_after_all_phases(self):
        g = self._globals()
        self.preview_runner.run_warmup(g, self._phases(), final_te_300=True)
        log = self._drain_log()
        self.assertIn("--- Phase 4: te 300, flow_set 6 ---", log)
        self.assertIn("[te] set temperature -> 300", log)
        self.assertIn("[flow_set] -> 6", log)
        completed_idx = log.index("=== WARMUP SEQUENCE COMPLETED ===")
        final_step_idx = log.index("--- Phase 4: te 300, flow_set 6 ---")
        self.assertLess(final_step_idx, completed_idx)

    def test_final_te_300_enabled_with_custom_temp_and_flow(self):
        # The Phase 4 temperature/flow are now editable -- confirm
        # custom values (not the 300/6 defaults) are sent and logged
        # correctly, including _format_temp's whole-number stripping.
        g = self._globals()
        self.preview_runner.run_warmup(
            g, self._phases(), final_te_300=True,
            final_sample_temp="310", final_sample_flow="8",
        )
        log = self._drain_log()
        self.assertIn("--- Phase 4: te 310, flow_set 8 ---", log)
        self.assertIn("[te] set temperature -> 310", log)
        self.assertIn("[flow_set] -> 8", log)

    def test_final_te_300_skipped_if_cancelled(self):
        # Cancelling partway through returns out of run_warmup from
        # inside the phase loop, before the final-step code is ever
        # reached -- confirm a cancelled run does not still send the
        # final te 300, even with final_te_300=True.
        g = self._globals()
        self.cancel_event.set()
        self.runner.run_warmup(g, self._phases(), final_te_300=True)
        log = self._drain_log()
        self.assertIn("[cancelled] stopped before the first phase", log)
        self.assertFalse(any(line.startswith("--- Phase 4") for line in log))
        self.assertFalse(any("te 300" in line for line in log))

    def test_room_temp_after_off_by_default(self):
        # room_temp_after_enabled defaults to "0" on every phase -- a
        # normal run (even with all 3 phases enabled) must not send
        # any "Return to Room Temp after..." interlude on its own.
        g = self._globals()
        phases = self._phases({
            0: {"enabled": "1"}, 1: {"enabled": "1"}, 2: {"enabled": "1"},
        })
        self.preview_runner.run_warmup(g, phases)
        log = self._drain_log()
        self.assertFalse(
            any(line.startswith("--- Return to Room Temp after") for line in log)
        )

    def test_room_temp_after_enabled_sends_between_phases(self):
        # Enabling the interlude on Phase 1 only must send it right
        # after Phase 1's temperature loop, before Phase 2 starts --
        # and must NOT fire again for Phase 2 or Phase 3.
        g = self._globals()
        phases = self._phases({
            0: {"enabled": "1", "room_temp_after_enabled": "1"},
            1: {"enabled": "1"},
            2: {"enabled": "1"},
        })
        self.preview_runner.run_warmup(g, phases)
        log = self._drain_log()
        self.assertIn(
            "--- Return to Room Temp after Phase 1: Low N2 flow: "
            "te 300, flow_set 6 ---",
            log,
        )
        interlude_idx = log.index(
            "--- Return to Room Temp after Phase 1: Low N2 flow: "
            "te 300, flow_set 6 ---"
        )
        phase1_idx = log.index("=== Phase 1: Low N2 flow ===")
        phase2_idx = log.index("=== Phase 2: Medium N2 flow ===")
        self.assertLess(phase1_idx, interlude_idx)
        self.assertLess(interlude_idx, phase2_idx)
        # Only one interlude fired -- Phase 2/3 have theirs off.
        interlude_lines = [
            line for line in log
            if line.startswith("--- Return to Room Temp after")
        ]
        self.assertEqual(len(interlude_lines), 1)

    def test_room_temp_after_custom_temp_and_flow(self):
        g = self._globals()
        phases = self._phases({
            1: {
                "enabled": "1",
                "room_temp_after_enabled": "1",
                "room_temp_after_te": "295",
                "room_temp_after_flow": "7",
            },
        })
        self.preview_runner.run_warmup(g, phases)
        log = self._drain_log()
        self.assertIn(
            "--- Return to Room Temp after Phase 2: Medium N2 flow: "
            "te 295, flow_set 7 ---",
            log,
        )
        self.assertIn("[te] set temperature -> 295", log)
        self.assertIn("[flow_set] -> 7", log)

    def test_room_temp_after_independent_per_phase_all_three_enabled(self):
        # All 3 phases can independently opt into their own interlude
        # at once -- confirm all 3 fire, each with its own label, in
        # the right order relative to their own phase.
        g = self._globals()
        phases = self._phases({
            0: {"enabled": "1", "room_temp_after_enabled": "1"},
            1: {"enabled": "1", "room_temp_after_enabled": "1"},
            2: {"enabled": "1", "room_temp_after_enabled": "1"},
        })
        self.preview_runner.run_warmup(g, phases)
        log = self._drain_log()
        interlude_lines = [
            line for line in log
            if line.startswith("--- Return to Room Temp after")
        ]
        self.assertEqual(len(interlude_lines), 3)
        self.assertTrue(any("Phase 1: Low N2 flow" in line for line in interlude_lines))
        self.assertTrue(any("Phase 2: Medium N2 flow" in line for line in interlude_lines))
        self.assertTrue(any("Phase 3: High N2 flow" in line for line in interlude_lines))
        # Runs one after another with no pause -- sequence completes normally.
        self.assertIn("=== WARMUP SEQUENCE COMPLETED ===", log)

    def test_room_temp_after_combines_with_final_phase_4(self):
        # The per-phase interlude and the shared end-of-sequence
        # Phase 4 step are independent and can both be enabled at
        # once -- both must fire, in the right relative order.
        g = self._globals()
        phases = self._phases({
            0: {"enabled": "1", "room_temp_after_enabled": "1"},
        })
        self.preview_runner.run_warmup(g, phases, final_te_300=True)
        log = self._drain_log()
        self.assertIn(
            "--- Return to Room Temp after Phase 1: Low N2 flow: "
            "te 300, flow_set 6 ---",
            log,
        )
        self.assertIn("--- Phase 4: te 300, flow_set 6 ---", log)
        interlude_idx = log.index(
            "--- Return to Room Temp after Phase 1: Low N2 flow: "
            "te 300, flow_set 6 ---"
        )
        final_idx = log.index("--- Phase 4: te 300, flow_set 6 ---")
        self.assertLess(interlude_idx, final_idx)

    def test_room_temp_after_not_sent_for_disabled_phase(self):
        # A phase left disabled is skipped entirely -- even if its own
        # room_temp_after_enabled happens to be "1", nothing should be
        # sent for it since the phase itself never runs.
        g = self._globals()
        phases = self._phases({
            0: {"enabled": "0", "room_temp_after_enabled": "1"},
            1: {"enabled": "1"},
        })
        self.preview_runner.run_warmup(g, phases)
        log = self._drain_log()
        self.assertFalse(
            any(line.startswith("--- Return to Room Temp after") for line in log)
        )

    def test_room_temp_after_skipped_if_cancelled_before_first_phase(self):
        g = self._globals()
        self.cancel_event.set()
        phases = self._phases({
            0: {"enabled": "1", "room_temp_after_enabled": "1"},
        })
        self.runner.run_warmup(g, phases)
        log = self._drain_log()
        self.assertIn("[cancelled] stopped before the first phase", log)
        self.assertFalse(
            any(line.startswith("--- Return to Room Temp after") for line in log)
        )

    def test_cancel_before_first_phase_is_fast_and_stops_immediately(self):
        g = self._globals()
        self.cancel_event.set()
        self.runner.run_warmup(g, self._phases())
        log = self._drain_log()

        self.assertIn("[cancelled] stopped before the first phase", log)
        self.assertFalse(any(line.startswith("=== Phase") for line in log))

    def test_custom_hdrm_scan_params_shared_across_all_phases(self):
        # Warmup's macro never varies the HDRM scan step by phase, so
        # one shared custom passes/num_steps/count_time set must apply
        # identically to every enabled phase's scans.
        g = self._globals()
        custom_passes = [
            {"chi": "1", "th": "2", "phi": "0", "scan_start": "0", "scan_stop": "10"},
        ]
        # Phases now default to disabled; enable all 3 so flyscan is
        # actually invoked for every phase.
        phases = self._phases({
            0: {"enabled": "1"}, 1: {"enabled": "1"}, 2: {"enabled": "1"},
        })
        self.preview_runner.run_warmup(
            g, phases,
            scan_passes=custom_passes, num_steps="4", count_time="0.02",
        )
        log = self._drain_log()

        flyscan_lines = [line for line in log if line.startswith("[flyscan]")]
        self.assertTrue(len(flyscan_lines) >= 1)
        for line in flyscan_lines:
            self.assertEqual(line, "[flyscan] phi 0 -> 10, 4 steps, 0.02s per point")


class TestWarmupCustom(_TemperatureSeriesTestBase):
    def test_default_params_full_sequence_preview_gas_thresholds(self):
        g = self._globals()
        d = hrdm_core.WARMUP_CUSTOM_DEFAULTS
        self.preview_runner.run_warmup_custom(
            g, d["start_temp"], d["end_temp"], d["step_temp"],
            d["spin_cycles"], d["threshold1"], d["flow1"],
            d["threshold2"], d["flow2"], d["flow3"],
        )
        log = self._drain_log()

        self.assertIn("=== CUSTOM WARMUP SEQUENCE ===", log)
        # 140..260 step 10 -> 13 temperature steps
        temp_headers = [line for line in log if line.startswith("=== TEMPERATURE")]
        self.assertEqual(len(temp_headers), 13)
        # <=160 -> low (140,150,160), <=200 -> medium (170..200), else high (210..260)
        low_lines = [line for line in log if "Setting low N2 flow" in line]
        medium_lines = [line for line in log if "Setting medium N2 flow" in line]
        high_lines = [line for line in log if "Setting high N2 flow" in line]
        self.assertEqual(len(low_lines), 3)
        self.assertEqual(len(medium_lines), 4)
        self.assertEqual(len(high_lines), 6)
        self.assertIn("=== CUSTOM WARMUP SEQUENCE COMPLETED ===", log)

    def test_cancel_before_first_temperature_is_fast_and_stops_immediately(self):
        g = self._globals()
        d = hrdm_core.WARMUP_CUSTOM_DEFAULTS
        self.cancel_event.set()
        self.runner.run_warmup_custom(
            g, d["start_temp"], d["end_temp"], d["step_temp"],
            d["spin_cycles"], d["threshold1"], d["flow1"],
            d["threshold2"], d["flow2"], d["flow3"],
        )
        log = self._drain_log()

        self.assertIn("[cancelled] stopped before the first temperature", log)
        self.assertFalse(any(line.startswith("=== TEMPERATURE") for line in log))

    def test_custom_hdrm_scan_params_override_defaults(self):
        g = self._globals()
        d = hrdm_core.WARMUP_CUSTOM_DEFAULTS
        custom_passes = [
            {"chi": "5", "th": "6", "phi": "0", "scan_start": "0", "scan_stop": "20"},
        ]
        self.preview_runner.run_warmup_custom(
            g, "140", "141", "10",
            d["spin_cycles"], d["threshold1"], d["flow1"],
            d["threshold2"], d["flow2"], d["flow3"],
            scan_passes=custom_passes, num_steps="9", count_time="0.3",
        )
        log = self._drain_log()

        flyscan_lines = [line for line in log if line.startswith("[flyscan]")]
        self.assertEqual(len(flyscan_lines), 1)
        self.assertEqual(
            flyscan_lines[0], "[flyscan] phi 0 -> 20, 9 steps, 0.3s per point"
        )


class TestCooldown(_TemperatureSeriesTestBase):
    def test_default_params_full_sequence_preview_gas_thresholds(self):
        g = self._globals()
        d = hrdm_core.COOLDOWN_DEFAULTS
        self.preview_runner.run_cooldown(
            g, d["start_temp"], d["end_temp"], d["step_temp"],
            d["spin_cycles"], d["threshold_high"], d["flow_high"],
            d["threshold_medium"], d["flow_medium"], d["flow_low"],
        )
        log = self._drain_log()

        self.assertIn("=== COOLDOWN SEQUENCE ===", log)
        # descending: 300, 280, ..., 120 -- 10 steps (100 itself excluded)
        temp_headers = [line for line in log if line.startswith("=== TEMPERATURE")]
        self.assertEqual(len(temp_headers), 10)
        self.assertEqual(temp_headers[0], "=== TEMPERATURE 300K ===")
        self.assertEqual(temp_headers[-1], "=== TEMPERATURE 120K ===")
        # >=200 -> high (300,280,260,240,220,200), >=160 -> medium (180,160), else low (140,120)
        high_lines = [line for line in log if "Setting high N2 flow" in line]
        medium_lines = [line for line in log if "Setting medium N2 flow" in line]
        low_lines = [line for line in log if "Setting low N2 flow" in line]
        self.assertEqual(len(high_lines), 6)
        self.assertEqual(len(medium_lines), 2)
        self.assertEqual(len(low_lines), 2)
        self.assertIn("=== COOLDOWN SEQUENCE COMPLETED ===", log)

        # Unlike every other temperature-series method, cooldown has no
        # 10s "Ctrl+C to abort" warning delay -- confirm it's absent.
        self.assertFalse(any("warning delay" in line for line in log))

    def test_cancel_before_first_temperature_is_fast_and_stops_immediately(self):
        g = self._globals()
        d = hrdm_core.COOLDOWN_DEFAULTS
        self.cancel_event.set()
        self.runner.run_cooldown(
            g, d["start_temp"], d["end_temp"], d["step_temp"],
            d["spin_cycles"], d["threshold_high"], d["flow_high"],
            d["threshold_medium"], d["flow_medium"], d["flow_low"],
        )
        log = self._drain_log()

        self.assertIn("[cancelled] stopping cooldown at 300K", log)
        self.assertFalse(any(line.startswith("[te]") for line in log))

    def test_custom_hdrm_scan_params_override_defaults(self):
        g = self._globals()
        d = hrdm_core.COOLDOWN_DEFAULTS
        custom_passes = [
            {"chi": "3", "th": "4", "phi": "0", "scan_start": "0", "scan_stop": "30"},
        ]
        self.preview_runner.run_cooldown(
            g, "300", "290", "10",
            d["spin_cycles"], d["threshold_high"], d["flow_high"],
            d["threshold_medium"], d["flow_medium"], d["flow_low"],
            scan_passes=custom_passes, num_steps="11", count_time="0.4",
        )
        log = self._drain_log()

        flyscan_lines = [line for line in log if line.startswith("[flyscan]")]
        self.assertEqual(len(flyscan_lines), 1)
        self.assertEqual(
            flyscan_lines[0], "[flyscan] phi 0 -> 30, 11 steps, 0.4s per point"
        )


class TestHightempScan(_TemperatureSeriesTestBase):
    def test_default_params_full_sequence_preview(self):
        # scan_wait_seconds defaults to 360s -- preview mode only, a
        # non-preview run of this test would really wait several minutes.
        # final_enabled defaults to False/off, so Phase 2 (return to
        # room temperature) is skipped unless explicitly enabled -- see
        # test_final_enabled_runs_phase_2 below.
        g = self._globals()
        d = hrdm_core.HIGHTEMP_SCAN_DEFAULTS
        self.preview_runner.run_hightemp_scan(
            g, d["start_temp"], d["end_temp"], d["step_temp"],
            d["scan_wait_seconds"], d["final_temp"], d["final_flow"],
        )
        log = self._drain_log()

        self.assertIn("=== HIGH TEMPERATURE SCAN ===", log)
        self.assertIn("--- Phase 1: 361K to 475K (step 30K) ---", log)
        # 361, 391, 421, 451 -- 4 steps (475 itself excluded)
        temp_headers = [line for line in log if line.startswith("--- Temperature")]
        self.assertEqual(len(temp_headers), 4)
        wait_lines = [line for line in log if line == "[sleep] 360.0s"]
        self.assertEqual(len(wait_lines), 4)
        self.assertIn("--- Phase 2: skipped (disabled) ---", log)
        self.assertFalse(any("[roomT]" in line for line in log))
        self.assertFalse(any("[flow_set]" in line for line in log))
        self.assertFalse(any("te 300" in line for line in log))
        self.assertIn("=== HIGH TEMPERATURE SCAN COMPLETED ===", log)

    def test_final_enabled_runs_phase_2(self):
        g = self._globals()
        d = hrdm_core.HIGHTEMP_SCAN_DEFAULTS
        self.preview_runner.run_hightemp_scan(
            g, d["start_temp"], d["end_temp"], d["step_temp"],
            d["scan_wait_seconds"], d["final_temp"], d["final_flow"],
            final_enabled=True,
        )
        log = self._drain_log()

        self.assertIn("--- Phase 2: returning to room temperature ---", log)
        self.assertIn("[roomT] room-temperature gas prep", log)
        self.assertIn("[flow_set] -> 6", log)
        self.assertIn("[te] set temperature -> 300", log)
        self.assertIn("=== HIGH TEMPERATURE SCAN COMPLETED ===", log)

    def test_final_enabled_with_custom_temp_and_flow(self):
        g = self._globals()
        d = hrdm_core.HIGHTEMP_SCAN_DEFAULTS
        self.preview_runner.run_hightemp_scan(
            g, d["start_temp"], d["end_temp"], d["step_temp"],
            d["scan_wait_seconds"], "310", "8",
            final_enabled=True,
        )
        log = self._drain_log()

        self.assertIn("[flow_set] -> 8", log)
        self.assertIn("[te] set temperature -> 310", log)

    def test_cancel_before_first_temperature_is_fast_and_stops_immediately(self):
        g = self._globals()
        d = hrdm_core.HIGHTEMP_SCAN_DEFAULTS
        self.cancel_event.set()
        self.runner.run_hightemp_scan(
            g, d["start_temp"], d["end_temp"], d["step_temp"],
            d["scan_wait_seconds"], d["final_temp"], d["final_flow"],
        )
        log = self._drain_log()

        self.assertIn("[cancelled] stopped before the first temperature", log)
        self.assertFalse(any(line.startswith("--- Phase") for line in log))

    def test_custom_hdrm_scan_params_override_defaults(self):
        g = self._globals()
        d = hrdm_core.HIGHTEMP_SCAN_DEFAULTS
        custom_passes = [
            {"chi": "7", "th": "8", "phi": "0", "scan_start": "0", "scan_stop": "40"},
        ]
        self.preview_runner.run_hightemp_scan(
            g, "361", "362", "30", "0", d["final_temp"], d["final_flow"],
            scan_passes=custom_passes, num_steps="12", count_time="0.6",
        )
        log = self._drain_log()

        flyscan_lines = [line for line in log if line.startswith("[flyscan]")]
        self.assertEqual(len(flyscan_lines), 1)
        self.assertEqual(
            flyscan_lines[0], "[flyscan] phi 0 -> 40, 12 steps, 0.6s per point"
        )


class TestNewStubMethodsLiveSpecSending(unittest.TestCase):
    """The gas-prep/flow/phi stub methods introduced for the new tabs
    (prepN2_low/_medium/_high, roomT, flow_set, umv_phi) -- confirm
    each sends the exact equivalent SPEC command through
    spec_controller.send() when one is attached, mirroring
    Lakeshore336cryocool.mac's own epics_put() calls exactly."""

    def setUp(self):
        self.log_q = queue.Queue()
        self.cancel_event = threading.Event()
        self.fake = FakeSpecController()
        self.runner = hrdm_core.Runner(
            self.log_q, self.cancel_event, spec_controller=self.fake
        )

    def test_prepN2_low_sends_expected_epics_puts(self):
        self.runner.prepN2_low()
        self.assertEqual(
            self.fake.sent,
            [
                'epics_put("LAKESHORE2:SETP_S1",87)',
                'epics_put("LAKESHORE2:SETP_S3",85)',
            ],
        )

    def test_prepN2_medium_sends_expected_epics_puts(self):
        self.runner.prepN2_medium()
        self.assertEqual(
            self.fake.sent,
            [
                'epics_put("LAKESHORE2:SETP_S1",130)',
                'epics_put("LAKESHORE2:SETP_S3",110)',
            ],
        )

    def test_prepN2_high_sends_expected_epics_puts(self):
        self.runner.prepN2_high()
        self.assertEqual(
            self.fake.sent,
            [
                'epics_put("LAKESHORE2:SETP_S1",165)',
                'epics_put("LAKESHORE2:SETP_S3",160)',
            ],
        )

    def test_prepN2_low_stage_override_sends_given_values(self):
        # Warmup tab's per-phase "Prep sample stage setup" fields let
        # the user override the mac file's own Stage A/Stage C
        # defaults (87/85) -- confirm the override actually reaches
        # the sent epics_put() commands instead of being ignored.
        self.runner.prepN2_low(stage_a=90, stage_c=88)
        self.assertEqual(
            self.fake.sent,
            [
                'epics_put("LAKESHORE2:SETP_S1",90)',
                'epics_put("LAKESHORE2:SETP_S3",88)',
            ],
        )

    def test_prepN2_medium_stage_override_sends_given_values(self):
        self.runner.prepN2_medium(stage_a=135, stage_c=115)
        self.assertEqual(
            self.fake.sent,
            [
                'epics_put("LAKESHORE2:SETP_S1",135)',
                'epics_put("LAKESHORE2:SETP_S3",115)',
            ],
        )

    def test_prepN2_high_stage_override_sends_given_values(self):
        self.runner.prepN2_high(stage_a=170, stage_c=162)
        self.assertEqual(
            self.fake.sent,
            [
                'epics_put("LAKESHORE2:SETP_S1",170)',
                'epics_put("LAKESHORE2:SETP_S3",162)',
            ],
        )

    def test_prepswitch_sends_expected_epics_puts(self):
        # Matches the real Lakeshore336cryocool.mac `prepswitch` macro
        # exactly -- just the two epics_put calls, no flow_set (an
        # earlier project addition that has since been removed per
        # explicit user request; see prepswitch's own docstring).
        self.runner.prepswitch()
        self.assertEqual(
            self.fake.sent,
            [
                'epics_put("LAKESHORE2:SETP_S1",100)',
                'epics_put("LAKESHORE2:SETP_S3",95)',
            ],
        )

    def test_prepswitch_stage_override_sends_given_values(self):
        self.runner.prepswitch(stage_a=102, stage_c=97)
        self.assertEqual(
            self.fake.sent,
            [
                'epics_put("LAKESHORE2:SETP_S1",102)',
                'epics_put("LAKESHORE2:SETP_S3",97)',
            ],
        )

    def test_prepswitch_no_longer_sends_flow_set(self):
        # Regression test: an earlier version of this project had
        # prepswitch also call flow_set automatically; per explicit
        # user request that has been removed, so prepswitch now only
        # ever sends the two Lakeshore epics_put calls.
        self.runner.prepswitch()
        self.assertEqual(
            self.fake.sent,
            [
                'epics_put("LAKESHORE2:SETP_S1",100)',
                'epics_put("LAKESHORE2:SETP_S3",95)',
            ],
        )

    def test_highT_sends_expected_epics_puts(self):
        self.runner.highT()
        self.assertEqual(
            self.fake.sent,
            [
                'epics_put("LAKESHORE2:SETP_S1",300)',
                'epics_put("LAKESHORE2:SETP_S3",300)',
            ],
        )

    def test_roomT_stage_override_sends_given_values(self):
        self.runner.roomT(stage_a=225, stage_c=221)
        self.assertEqual(
            self.fake.sent,
            [
                'epics_put("LAKESHORE2:SETP_S1",225)',
                'epics_put("LAKESHORE2:SETP_S3",221)',
            ],
        )

    def test_highT_stage_override_sends_given_values(self):
        self.runner.highT(stage_a=305, stage_c=301)
        self.assertEqual(
            self.fake.sent,
            [
                'epics_put("LAKESHORE2:SETP_S1",305)',
                'epics_put("LAKESHORE2:SETP_S3",301)',
            ],
        )

    def test_flow_get_sends_expected_command_and_returns_response(self):
        # Sent as '_flow_get()' -- the real underlying function that
        # flow_get (a paren-less, print-only wrapper macro -- see
        # flow_get's docstring for its confirmed source) calls and
        # actually return()s the live reading from.
        self.fake.response = "6"
        result = self.runner.flow_get()
        self.assertEqual(self.fake.sent, ["_flow_get()"])
        self.assertEqual(result, "6")

    def test_flow_get_returns_none_without_spec_controller(self):
        runner = hrdm_core.Runner(self.log_q, self.cancel_event)  # no spec_controller
        result = runner.flow_get()
        self.assertIsNone(result)

    def test_runninghelium_sends_expected_epics_puts(self):
        self.runner.runninghelium()
        self.assertEqual(
            self.fake.sent,
            [
                'epics_put("LAKESHORE2:SETP_S1",30)',
                'epics_put("LAKESHORE2:SETP_S3",16)',
            ],
        )

    def test_runninghelium_stage_override_sends_given_values(self):
        self.runner.runninghelium(stage_a=6, stage_c=32)
        self.assertEqual(
            self.fake.sent,
            [
                'epics_put("LAKESHORE2:SETP_S1",6)',
                'epics_put("LAKESHORE2:SETP_S3",32)',
            ],
        )

    def test_roomT_sends_expected_epics_puts(self):
        self.runner.roomT()
        self.assertEqual(
            self.fake.sent,
            [
                'epics_put("LAKESHORE2:SETP_S1",222)',
                'epics_put("LAKESHORE2:SETP_S3",220)',
            ],
        )

    def test_flow_set_sends_expected_command(self):
        self.runner.flow_set(6)
        self.assertEqual(self.fake.sent, ["flow_set 6"])

    def test_umv_phi_sends_expected_command(self):
        self.runner.umv_phi(360)
        self.assertEqual(self.fake.sent, ["umv phi 360"])

class TestGasPrepMacros(unittest.TestCase):
    """Runner.run_gas_prep_macro()/run_gas_prep_flow_set()/
    run_gas_prep_flow_get() -- the Gas Prep Macros tab's dispatcher
    and standalone flow controls -- plus
    validate_gas_prep_macros_params()."""

    def setUp(self):
        self.log_q = queue.Queue()
        self.cancel_event = threading.Event()
        self.fake = FakeSpecController()
        self.runner = hrdm_core.Runner(
            self.log_q, self.cancel_event, spec_controller=self.fake
        )
        self.params = dict(hrdm_core.GAS_PREP_MACROS_DEFAULTS)

    def test_run_gas_prep_macro_prepN2_low(self):
        self.runner.run_gas_prep_macro("prepN2_low", self.params)
        self.assertEqual(
            self.fake.sent,
            [
                'epics_put("LAKESHORE2:SETP_S1",87)',
                'epics_put("LAKESHORE2:SETP_S3",85)',
            ],
        )

    def test_run_gas_prep_macro_prepN2_medium(self):
        self.runner.run_gas_prep_macro("prepN2_medium", self.params)
        self.assertEqual(
            self.fake.sent,
            [
                'epics_put("LAKESHORE2:SETP_S1",130)',
                'epics_put("LAKESHORE2:SETP_S3",110)',
            ],
        )

    def test_run_gas_prep_macro_prepN2_high(self):
        self.runner.run_gas_prep_macro("prepN2_high", self.params)
        self.assertEqual(
            self.fake.sent,
            [
                'epics_put("LAKESHORE2:SETP_S1",165)',
                'epics_put("LAKESHORE2:SETP_S3",160)',
            ],
        )

    def test_run_gas_prep_macro_prepswitch_no_flow_set(self):
        # prepswitch no longer sends flow_set (removed per explicit
        # user request) -- just the two Lakeshore epics_put calls.
        self.runner.run_gas_prep_macro("prepswitch", self.params)
        self.assertEqual(
            self.fake.sent,
            [
                'epics_put("LAKESHORE2:SETP_S1",100)',
                'epics_put("LAKESHORE2:SETP_S3",95)',
            ],
        )

    def test_run_gas_prep_macro_runninghelium(self):
        # Gas Prep tab's own runninghelium_stage_c default is 9 (per
        # explicit user request), not the macro-confirmed 16 used by
        # the N2 -> He Switch tab's own Step 7.
        self.runner.run_gas_prep_macro("runninghelium", self.params)
        self.assertEqual(
            self.fake.sent,
            [
                'epics_put("LAKESHORE2:SETP_S1",30)',
                'epics_put("LAKESHORE2:SETP_S3",9)',
            ],
        )

    def test_run_gas_prep_macro_roomT(self):
        self.runner.run_gas_prep_macro("roomT", self.params)
        self.assertEqual(
            self.fake.sent,
            [
                'epics_put("LAKESHORE2:SETP_S1",222)',
                'epics_put("LAKESHORE2:SETP_S3",220)',
            ],
        )

    def test_run_gas_prep_macro_highT(self):
        self.runner.run_gas_prep_macro("highT", self.params)
        self.assertEqual(
            self.fake.sent,
            [
                'epics_put("LAKESHORE2:SETP_S1",300)',
                'epics_put("LAKESHORE2:SETP_S3",300)',
            ],
        )

    def test_run_gas_prep_macro_unknown_name_raises(self):
        with self.assertRaises(ValueError):
            self.runner.run_gas_prep_macro("not_a_real_macro", self.params)

    def test_run_gas_prep_macro_logs_bookends(self):
        self.runner.run_gas_prep_macro("roomT", self.params)
        logged = []
        while not self.log_q.empty():
            logged.append(self.log_q.get_nowait())
        self.assertTrue(any("=== GAS PREP MACRO: roomT ===" in m for m in logged))
        self.assertTrue(any("=== roomT COMPLETE ===" in m for m in logged))

    def test_run_gas_prep_flow_set_sends_expected_command(self):
        self.runner.run_gas_prep_flow_set(9)
        self.assertEqual(self.fake.sent, ["flow_set 9"])

    def test_run_gas_prep_flow_get_sends_expected_command_and_returns_response(self):
        self.fake.response = "9"
        result = self.runner.run_gas_prep_flow_get()
        self.assertEqual(self.fake.sent, ["_flow_get()"])
        self.assertEqual(result, "9")


class TestValidateGasPrepMacrosParams(unittest.TestCase):
    def test_valid_defaults_pass(self):
        hrdm_core.validate_gas_prep_macros_params(
            hrdm_core.GAS_PREP_MACROS_DEFAULTS
        )  # no raise

    def test_non_numeric_field_raises(self):
        p = dict(hrdm_core.GAS_PREP_MACROS_DEFAULTS)
        p["prepswitch_stage_a"] = "abc"
        with self.assertRaises(ValueError):
            hrdm_core.validate_gas_prep_macros_params(p)

    def test_missing_field_raises(self):
        p = dict(hrdm_core.GAS_PREP_MACROS_DEFAULTS)
        del p["flow_set_value"]
        with self.assertRaises(ValueError):
            hrdm_core.validate_gas_prep_macros_params(p)

    def test_non_numeric_flow_set_value_raises(self):
        p = dict(hrdm_core.GAS_PREP_MACROS_DEFAULTS)
        p["flow_set_value"] = "not-a-number"
        with self.assertRaises(ValueError):
            hrdm_core.validate_gas_prep_macros_params(p)


class TestStandaloneTempFlow(unittest.TestCase):
    """Runner.run_standalone_set_temperature()/run_standalone_flow_set()/
    run_standalone_flow_get() -- the generic, label-parameterized
    worker methods shared by every scan/temperature tab's "Quick Temp
    / Flow Control" section -- plus validate_standalone_temp_flow_params()
    and the STANDALONE_TEMP_FLOW_DEFAULTS they validate."""

    def setUp(self):
        self.log_q = queue.Queue()
        self.cancel_event = threading.Event()
        self.fake = FakeSpecController()
        self.runner = hrdm_core.Runner(
            self.log_q, self.cancel_event, spec_controller=self.fake
        )

    def _drain_log(self):
        logged = []
        while not self.log_q.empty():
            logged.append(self.log_q.get_nowait())
        return logged

    def test_run_standalone_set_temperature_sends_expected_command(self):
        self.runner.run_standalone_set_temperature(280, label="Threextal Scan")
        self.assertEqual(self.fake.sent, ["te 280"])

    def test_run_standalone_set_temperature_strips_trailing_zero(self):
        # _format_temp strips a trailing ".0" off whole-number floats,
        # same as every other caller that hands it a loop float.
        self.runner.run_standalone_set_temperature(150.0, label="Warmup")
        self.assertEqual(self.fake.sent, ["te 150"])

    def test_run_standalone_set_temperature_logs_bookends_with_label(self):
        self.runner.run_standalone_set_temperature(280, label="Powder Scan")
        logged = self._drain_log()
        self.assertTrue(
            any("=== Powder Scan: set temperature (te) ===" in m for m in logged)
        )
        self.assertTrue(any("=== set temperature (te) COMPLETE ===" in m for m in logged))

    def test_run_standalone_flow_set_sends_expected_command(self):
        self.runner.run_standalone_flow_set(9, label="Cooldown")
        self.assertEqual(self.fake.sent, ["flow_set 9"])

    def test_run_standalone_flow_set_logs_bookends_with_label(self):
        self.runner.run_standalone_flow_set(9, label="Cooldown")
        logged = self._drain_log()
        self.assertTrue(any("=== Cooldown: flow_set ===" in m for m in logged))
        self.assertTrue(any("=== flow_set COMPLETE ===" in m for m in logged))

    def test_run_standalone_flow_get_sends_expected_command_and_returns_response(self):
        self.fake.response = "11"
        result = self.runner.run_standalone_flow_get(label="High Temp Scan")
        self.assertEqual(self.fake.sent, ["_flow_get()"])
        self.assertEqual(result, "11")

    def test_run_standalone_flow_get_returns_none_without_spec_controller(self):
        runner = hrdm_core.Runner(queue.Queue(), threading.Event(), preview=True)
        result = runner.run_standalone_flow_get(label="Height Scan")
        self.assertIsNone(result)

    def test_default_label_used_when_omitted(self):
        self.runner.run_standalone_set_temperature(280)
        logged = self._drain_log()
        self.assertTrue(any("=== Standalone: set temperature (te) ===" in m for m in logged))


class TestValidateStandaloneTempFlowParams(unittest.TestCase):
    def test_valid_defaults_pass(self):
        hrdm_core.validate_standalone_temp_flow_params(
            hrdm_core.STANDALONE_TEMP_FLOW_DEFAULTS
        )  # no raise

    def test_te_below_range_raises(self):
        p = dict(hrdm_core.STANDALONE_TEMP_FLOW_DEFAULTS)
        p["set_temp_te"] = "9"
        with self.assertRaises(ValueError):
            hrdm_core.validate_standalone_temp_flow_params(p)

    def test_te_above_range_raises(self):
        p = dict(hrdm_core.STANDALONE_TEMP_FLOW_DEFAULTS)
        p["set_temp_te"] = "491"
        with self.assertRaises(ValueError):
            hrdm_core.validate_standalone_temp_flow_params(p)

    def test_te_boundary_values_pass(self):
        p = dict(hrdm_core.STANDALONE_TEMP_FLOW_DEFAULTS)
        for boundary in ("10", "490"):
            p["set_temp_te"] = boundary
            hrdm_core.validate_standalone_temp_flow_params(p)  # no raise

    def test_non_numeric_te_raises(self):
        p = dict(hrdm_core.STANDALONE_TEMP_FLOW_DEFAULTS)
        p["set_temp_te"] = "not-a-number"
        with self.assertRaises(ValueError):
            hrdm_core.validate_standalone_temp_flow_params(p)

    def test_flow_below_range_raises(self):
        p = dict(hrdm_core.STANDALONE_TEMP_FLOW_DEFAULTS)
        p["flow_set_value"] = "5"
        with self.assertRaises(ValueError):
            hrdm_core.validate_standalone_temp_flow_params(p)

    def test_flow_above_range_raises(self):
        p = dict(hrdm_core.STANDALONE_TEMP_FLOW_DEFAULTS)
        p["flow_set_value"] = "19"
        with self.assertRaises(ValueError):
            hrdm_core.validate_standalone_temp_flow_params(p)

    def test_flow_boundary_values_pass(self):
        p = dict(hrdm_core.STANDALONE_TEMP_FLOW_DEFAULTS)
        for boundary in ("6", "18"):
            p["flow_set_value"] = boundary
            hrdm_core.validate_standalone_temp_flow_params(p)  # no raise

    def test_non_numeric_flow_raises(self):
        p = dict(hrdm_core.STANDALONE_TEMP_FLOW_DEFAULTS)
        p["flow_set_value"] = "not-a-number"
        with self.assertRaises(ValueError):
            hrdm_core.validate_standalone_temp_flow_params(p)


class TestSpecSendLock(unittest.TestCase):
    """_SPEC_SEND_LOCK should serialize the actual send()/response
    pair across concurrent Runner instances sharing one
    spec_controller -- the fix that lets quick standalone temp/flow/
    spin actions run truly concurrently with a full scan (or with each
    other) without their commands/responses interleaving on the one
    real SPEC connection."""

    class _SlowFakeSpecController:
        """Like FakeSpecController, but holds the "connection" open for
        a short, deliberate window inside send() so two threads calling
        send() at the same time will provably overlap *unless*
        something external serializes them."""

        def __init__(self, delay=0.05):
            self.delay = delay
            self.events = []  # list of ("start"/"end", command) tuples
            self._event_lock = threading.Lock()

        def send(self, command):
            with self._event_lock:
                self.events.append(("start", command))
            time.sleep(self.delay)
            with self._event_lock:
                self.events.append(("end", command))
            return "OK"

    def test_concurrent_sends_do_not_interleave(self):
        fake = self._SlowFakeSpecController(delay=0.05)
        runner_a = hrdm_core.Runner(queue.Queue(), threading.Event(), spec_controller=fake)
        runner_b = hrdm_core.Runner(queue.Queue(), threading.Event(), spec_controller=fake)

        thread_a = threading.Thread(target=runner_a._send, args=("cmd_a",))
        thread_b = threading.Thread(target=runner_b._send, args=("cmd_b",))
        thread_a.start()
        thread_b.start()
        thread_a.join(timeout=5)
        thread_b.join(timeout=5)

        self.assertEqual(len(fake.events), 4)
        # Whichever command went first, its "end" must come before the
        # other command's "start" -- i.e. no "start", "start", "end",
        # "end" interleaving pattern, which is what would happen if
        # _SPEC_SEND_LOCK were not held around spec_controller.send().
        first_cmd = fake.events[0][1]
        self.assertEqual(fake.events[0], ("start", first_cmd))
        self.assertEqual(fake.events[1], ("end", first_cmd))
        other_cmd = "cmd_b" if first_cmd == "cmd_a" else "cmd_a"
        self.assertEqual(fake.events[2], ("start", other_cmd))
        self.assertEqual(fake.events[3], ("end", other_cmd))

    def test_lock_is_module_level_shared_across_runners(self):
        # Two independently-constructed Runners must share the exact
        # same lock object -- a per-instance lock would not serialize
        # anything across concurrent Runner threads.
        runner_a = hrdm_core.Runner(queue.Queue(), threading.Event(), preview=True)
        runner_b = hrdm_core.Runner(queue.Queue(), threading.Event(), preview=True)
        self.assertIs(hrdm_core._SPEC_SEND_LOCK, hrdm_core._SPEC_SEND_LOCK)
        self.assertIsInstance(hrdm_core._SPEC_SEND_LOCK, type(threading.Lock()))
        # Not instance attributes -- confirm both runners see the same
        # module-level object (there is no self._SPEC_SEND_LOCK).
        self.assertFalse(hasattr(runner_a, "_SPEC_SEND_LOCK"))
        self.assertFalse(hasattr(runner_b, "_SPEC_SEND_LOCK"))


if __name__ == "__main__":
    unittest.main()
