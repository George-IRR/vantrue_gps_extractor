#!/usr/bin/env python3
import os
import sys
import tempfile
import json
import shutil
import unittest
from unittest.mock import patch, MagicMock
from datetime import datetime

import vantrue_sync

class TestVantrueSyncUnified(unittest.TestCase):

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="vantrue_test_root_")
        self.normal_dir = os.path.join(self.test_dir, "Normal")
        self.event_dir = os.path.join(self.test_dir, "Event")
        os.makedirs(self.normal_dir)
        os.makedirs(self.event_dir)

        vantrue_sync.BINARIES['exiftool'] = '/usr/bin/exiftool'
        vantrue_sync.BINARIES['rclone'] = '/usr/bin/rclone'

        self.remote_mock = "GoogleDriveMain190:Dashcam_Auto"

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)
        if os.path.exists(vantrue_sync.CHECKPOINT_FILE):
            try:
                os.unlink(vantrue_sync.CHECKPOINT_FILE)
            except OSError:
                pass

    def create_dummy_video(self, folder, filename, size_mb=1):
        filepath = os.path.join(folder, filename)
        with open(filepath, "wb") as f:
            f.write(b"0" * (size_mb * 1024 * 1024))
        return filepath

    # --- 1. UNIT TESTS ---

    def test_find_tool(self):
        with patch("shutil.which", return_value="/usr/bin/exiftool"):
            self.assertEqual(vantrue_sync.find_tool("exiftool"), "/usr/bin/exiftool")
            
        with patch("shutil.which", return_value=None), \
             patch("os.path.exists", return_value=True), \
             patch("os.access", return_value=True):
            self.assertEqual(vantrue_sync.find_tool("rclone"), "/usr/bin/rclone")

    def test_check_dependencies(self):
        with patch("vantrue_sync.find_tool", return_value="/usr/bin/mock_tool"):
            vantrue_sync.check_dependencies()
            self.assertIn('exiftool', vantrue_sync.BINARIES)
            self.assertIn('rclone', vantrue_sync.BINARIES)

        with patch("vantrue_sync.find_tool", return_value=None), \
             patch("sys.exit") as mock_exit, \
             patch("sys.stderr.write"):
            vantrue_sync.check_dependencies()
            mock_exit.assert_called_with(1)

    def test_stamp_to_iso(self):
        iso = vantrue_sync.stamp_to_iso("20260510_151242")
        self.assertEqual(iso, "2026-05-10T15:12:42Z")

    def test_get_clips(self):
        f1 = os.path.join(self.normal_dir, "20260510_151242_00004_N_A.MP4")
        f2 = os.path.join(self.event_dir, "20260510_151342_00005_E_A.MP4")
        f_invalid = os.path.join(self.normal_dir, "invalid_name.mp4")

        with open(f1, "w") as f: f.write("dummy video 1")
        with open(f2, "w") as f: f.write("dummy video 2")
        with open(f_invalid, "w") as f: f.write("dummy")

        clips = vantrue_sync.get_clips(self.test_dir)
        self.assertEqual(len(clips), 2)
        
        clips.sort(key=lambda x: x['stamp'])
        self.assertEqual(clips[0]['name'], "20260510_151242_00004_N_A.MP4")
        self.assertFalse(clips[0]['is_event'])
        self.assertEqual(clips[1]['name'], "20260510_151342_00005_E_A.MP4")
        self.assertTrue(clips[1]['is_event'])

    def test_group_into_trips(self):
        dt1 = datetime(2026, 5, 10, 15, 12, 42)
        dt2 = datetime(2026, 5, 10, 15, 13, 42)
        dt3 = datetime(2026, 5, 10, 17, 0, 0)

        clips = [
            {'time': dt1, 'name': 'c1', 'stamp': '20260510_151242'},
            {'time': dt2, 'name': 'c2', 'stamp': '20260510_151342'},
            {'time': dt3, 'name': 'c3', 'stamp': '20260510_170000'}
        ]

        trips = vantrue_sync.group_into_trips(clips, gap_seconds=65)
        self.assertEqual(len(trips), 2)
        self.assertEqual(len(trips[0]), 2)
        self.assertEqual(len(trips[1]), 1)

    def test_parse_selection(self):
        self.assertEqual(vantrue_sync.parse_selection("all", 5), [1, 2, 3, 4, 5])
        self.assertEqual(vantrue_sync.parse_selection("1,3,5-7", 10), [1, 3, 5, 6, 7])
        self.assertEqual(vantrue_sync.parse_selection("invalid, 2-4", 5), [2, 3, 4])

    def test_checkpoint_save_and_load(self):
        usb = self.test_dir
        completed_trips = {"20260510_151242_to_20260510_151342"}
        completed_clips = {"20260510_151242_to_20260510_151342": ["20260510_151242_00004_N_A.MP4"]}

        vantrue_sync.save_checkpoint(usb, self.remote_mock, completed_trips, completed_clips)
        self.assertTrue(os.path.exists(vantrue_sync.CHECKPOINT_FILE))

        cp = vantrue_sync.load_checkpoint(usb, self.remote_mock)
        self.assertIsNotNone(cp)
        self.assertEqual(cp['completed_trips'], list(completed_trips))
        self.assertEqual(cp['completed_clips'], completed_clips)

        self.assertIsNone(vantrue_sync.load_checkpoint("/different/usb", self.remote_mock))
        self.assertIsNone(vantrue_sync.load_checkpoint(usb, "DifferentRemote:"))

        vantrue_sync.clear_checkpoint()
        self.assertFalse(os.path.exists(vantrue_sync.CHECKPOINT_FILE))

    def test_combine_gpx_fragments(self):
        frag1 = os.path.join(self.test_dir, "frag1.gpx")
        frag2 = os.path.join(self.test_dir, "frag2.gpx")
        out_gpx = os.path.join(self.test_dir, "out.gpx")

        with open(frag1, "w") as f:
            f.write('<gpx><trk><trkseg><trkpt lat="44.1" lon="26.1"><time>T1</time></trkpt></trkseg></trk></gpx>')
        with open(frag2, "w") as f:
            f.write('<gpx><trk><trkseg><trkpt lat="44.2" lon="26.2"><time>T2</time></trkpt></trkseg></trk></gpx>')

        vantrue_sync.combine_gpx_fragments([frag1, frag2], out_gpx)
        self.assertTrue(os.path.exists(out_gpx))

        with open(out_gpx, "r") as f:
            content = f.read()
            self.assertIn('lat="44.1"', content)
            self.assertIn('lat="44.2"', content)
            self.assertIn('<trkseg>', content)

    def test_copy_file_with_speed(self):
        src = os.path.join(self.test_dir, "src.bin")
        dst = os.path.join(self.test_dir, "dst.bin")
        with open(src, "wb") as f:
            f.write(b"X" * (2 * 1024 * 1024))
        
        bytes_read, elapsed, speed = vantrue_sync.copy_file_with_speed(src, dst)
        self.assertEqual(bytes_read, 2 * 1024 * 1024)
        self.assertTrue(os.path.exists(dst))
        self.assertGreater(speed, 0)

    # --- 2. SMOKE TESTS ---

    def test_smoke_empty_usb(self):
        clips = vantrue_sync.get_clips(self.test_dir)
        self.assertEqual(len(clips), 0)
        trips = vantrue_sync.group_into_trips(clips, gap_seconds=65)
        self.assertEqual(len(trips), 0)

    def test_smoke_multi_trip_parsing(self):
        self.create_dummy_video(self.normal_dir, "20260510_150000_00001_N_A.MP4")
        self.create_dummy_video(self.normal_dir, "20260510_150100_00002_N_A.MP4")
        self.create_dummy_video(self.normal_dir, "20260510_160000_00003_N_A.MP4")
        self.create_dummy_video(self.event_dir,  "20260510_160100_00004_E_A.MP4")

        clips = vantrue_sync.get_clips(self.test_dir)
        self.assertEqual(len(clips), 4)

        trips = vantrue_sync.group_into_trips(clips, gap_seconds=65)
        self.assertEqual(len(trips), 2)
        self.assertEqual(len(trips[0]), 2)
        self.assertEqual(len(trips[1]), 2)
        self.assertTrue(any(c['is_event'] for c in trips[1]))

    # --- 3. RESUME INTERRUPTION & PREFETCH PIPELINE TESTS ---

    @patch("subprocess.run")
    def test_resume_interrupted_trip_with_pipeline(self, mock_subproc):
        mock_subproc.return_value = MagicMock(returncode=0)

        clip1 = self.create_dummy_video(self.normal_dir, "20260510_100000_00001_N_A.MP4")
        clip2 = self.create_dummy_video(self.normal_dir, "20260510_100100_00002_N_A.MP4")
        clip3 = self.create_dummy_video(self.normal_dir, "20260510_100200_00003_N_A.MP4")

        clips = vantrue_sync.get_clips(self.test_dir)
        trips = vantrue_sync.group_into_trips(clips, gap_seconds=65)
        trip = trips[0]
        trip_id = f"{trip[0]['stamp']}_to_{trip[-1]['stamp']}"

        completed_trip_ids = set()
        completed_clips = {
            trip_id: ["20260510_100000_00001_N_A.MP4", "20260510_100100_00002_N_A.MP4"]
        }
        vantrue_sync.save_checkpoint(self.test_dir, self.remote_mock, completed_trip_ids, completed_clips)

        shm_dir = tempfile.gettempdir()
        fmt_path = os.path.join(self.test_dir, "gpx.fmt")
        with open(fmt_path, "w") as f: f.write("dummy fmt")

        with patch("vantrue_sync.generate_gpx_in_shm", return_value=True):
            vantrue_sync.upload_trip(
                trip=trip,
                remote_base=self.remote_mock,
                fmt_path=fmt_path,
                mode="ram",
                shm_dir=shm_dir,
                usb_dir=self.test_dir,
                completed_trip_ids=completed_trip_ids,
                completed_clips=completed_clips,
                dry_run=False
            )

        self.assertIn(trip_id, completed_trip_ids)
        self.assertIn("20260510_100200_00003_N_A.MP4", completed_clips[trip_id])

        cp = vantrue_sync.load_checkpoint(self.test_dir, self.remote_mock)
        self.assertIsNotNone(cp)
        self.assertIn(trip_id, cp['completed_trips'])

    def test_resume_deleted_old_clips_safety(self):
        self.create_dummy_video(self.normal_dir, "20260510_120000_00002_N_A.MP4")

        trip_id = "20260510_115900_to_20260510_120000"
        completed_clips = {
            trip_id: ["20260510_115900_00001_N_A.MP4", "20260510_120000_00002_N_A.MP4"]
        }
        vantrue_sync.save_checkpoint(self.test_dir, self.remote_mock, set(), completed_clips)

        clips = vantrue_sync.get_clips(self.test_dir)
        available_names = {c['name'] for c in clips}

        cleaned_completed_clips = {}
        for tid, clip_list in completed_clips.items():
            valid_clips = [c for c in clip_list if c in available_names]
            if valid_clips:
                cleaned_completed_clips[tid] = valid_clips

        self.assertNotIn("20260510_115900_00001_N_A.MP4", cleaned_completed_clips[trip_id])
        self.assertIn("20260510_120000_00002_N_A.MP4", cleaned_completed_clips[trip_id])

if __name__ == "__main__":
    unittest.main()
