#!/usr/bin/env python3
import os
import sys
import shutil
import tempfile
import json
import unittest
from unittest.mock import patch, MagicMock
from datetime import datetime

import vantrue_sync

class TestSmokeAndResume(unittest.TestCase):

    def setUp(self):
        # Create a temporary simulated USB root directory
        self.simulated_usb = tempfile.mkdtemp(prefix="vantrue_usb_sim_")
        self.normal_dir = os.path.join(self.simulated_usb, "Normal")
        self.event_dir = os.path.join(self.simulated_usb, "Event")
        os.makedirs(self.normal_dir)
        os.makedirs(self.event_dir)

        # Create dummy mock binaries so test doesn't fail if tools aren't present
        vantrue_sync.BINARIES['exiftool'] = '/usr/bin/exiftool'
        vantrue_sync.BINARIES['rclone'] = '/usr/bin/rclone'

        # Set up dummy mock cloud destination
        self.remote_mock = "MockRemote:Dashcam_Test"

    def tearDown(self):
        shutil.rmtree(self.simulated_usb, ignore_errors=True)
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

    # --- SMOKE TEST 1: End-to-End simulation with empty USB ---
    def test_smoke_empty_usb(self):
        print("\n[SMOKE TEST 1] Testing execution on empty USB structure...")
        clips = vantrue_sync.get_clips(self.simulated_usb)
        self.assertEqual(len(clips), 0)
        trips = vantrue_sync.group_into_trips(clips, gap_seconds=65)
        self.assertEqual(len(trips), 0)

    # --- SMOKE TEST 2: Multi-Trip discovery & parsing ---
    def test_smoke_multi_trip_parsing(self):
        print("\n[SMOKE TEST 2] Testing multi-trip parsing & grouping...")
        # Trip 1 (Normal)
        self.create_dummy_video(self.normal_dir, "20260510_150000_00001_N_A.MP4")
        self.create_dummy_video(self.normal_dir, "20260510_150100_00002_N_A.MP4")
        
        # Trip 2 (Event + Normal, 1 hour later)
        self.create_dummy_video(self.normal_dir, "20260510_160000_00003_N_A.MP4")
        self.create_dummy_video(self.event_dir,  "20260510_160100_00004_E_A.MP4")

        clips = vantrue_sync.get_clips(self.simulated_usb)
        self.assertEqual(len(clips), 4)

        trips = vantrue_sync.group_into_trips(clips, gap_seconds=65)
        self.assertEqual(len(trips), 2)
        self.assertEqual(len(trips[0]), 2)
        self.assertEqual(len(trips[1]), 2)
        self.assertFalse(trips[0][0]['is_event'])
        self.assertTrue(any(c['is_event'] for c in trips[1]))

    # --- RESUME TEST 1: Simulated Interruption during Trip Upload ---
    @patch("subprocess.run")
    def test_resume_interrupted_trip(self, mock_subproc):
        print("\n[RESUME TEST 1] Simulating interruption & resume halfway through a trip...")
        mock_subproc.return_value = MagicMock(returncode=0)

        # Create 3 clips in Trip 1
        clip1 = self.create_dummy_video(self.normal_dir, "20260510_100000_00001_N_A.MP4")
        clip2 = self.create_dummy_video(self.normal_dir, "20260510_100100_00002_N_A.MP4")
        clip3 = self.create_dummy_video(self.normal_dir, "20260510_100200_00003_N_A.MP4")

        clips = vantrue_sync.get_clips(self.simulated_usb)
        trips = vantrue_sync.group_into_trips(clips, gap_seconds=65)
        trip = trips[0]
        trip_id = f"{trip[0]['stamp']}_to_{trip[-1]['stamp']}"

        # 1. Simulate prior partial upload: clip 1 and clip 2 were already completed in checkpoint
        completed_trip_ids = set()
        completed_clips = {
            trip_id: ["20260510_100000_00001_N_A.MP4", "20260510_100100_00002_N_A.MP4"]
        }
        vantrue_sync.save_checkpoint(self.simulated_usb, self.remote_mock, completed_trip_ids, completed_clips)

        # 2. Run upload_trip with --resume active (loaded from checkpoint)
        shm_dir = tempfile.gettempdir()
        fmt_path = os.path.join(self.simulated_usb, "gpx.fmt")
        with open(fmt_path, "w") as f: f.write("dummy fmt")

        with patch("vantrue_sync.generate_gpx_in_shm", return_value=True):
            vantrue_sync.upload_trip(
                trip=trip,
                remote_base=self.remote_mock,
                fmt_path=fmt_path,
                mode="ram",
                shm_dir=shm_dir,
                usb_dir=self.simulated_usb,
                completed_trip_ids=completed_trip_ids,
                completed_clips=completed_clips,
                dry_run=False
            )

        # Verify: clip 3 was processed and the entire trip is now marked as completed in checkpoint
        self.assertIn(trip_id, completed_trip_ids)
        self.assertIn("20260510_100200_00003_N_A.MP4", completed_clips[trip_id])

        # Verify saved checkpoint state
        cp = vantrue_sync.load_checkpoint(self.simulated_usb, self.remote_mock)
        self.assertIsNotNone(cp)
        self.assertIn(trip_id, cp['completed_trips'])

    # --- RESUME TEST 2: Safety filter - Ignore deleted clips from old USB sessions ---
    def test_resume_deleted_old_clips_safety(self):
        print("\n[RESUME TEST 2] Safety check: Ignore checkpoint entries for clips no longer on USB...")
        
        # Present on USB: Clip B
        self.create_dummy_video(self.normal_dir, "20260510_120000_00002_N_A.MP4")

        trip_id = "20260510_115900_to_20260510_120000"
        # Checkpoint contains: Clip A (deleted from USB) and Clip B (present)
        completed_clips = {
            trip_id: ["20260510_115900_00001_N_A.MP4", "20260510_120000_00002_N_A.MP4"]
        }
        vantrue_sync.save_checkpoint(self.simulated_usb, self.remote_mock, set(), completed_clips)

        # Run filtering logic as main() does
        clips = vantrue_sync.get_clips(self.simulated_usb)
        available_names = {c['name'] for c in clips}

        cleaned_completed_clips = {}
        for tid, clip_list in completed_clips.items():
            valid_clips = [c for c in clip_list if c in available_names]
            if valid_clips:
                cleaned_completed_clips[tid] = valid_clips

        # Verify: Deleted Clip A was removed from the active resume set, while Clip B was kept
        self.assertNotIn("20260510_115900_00001_N_A.MP4", cleaned_completed_clips[trip_id])
        self.assertIn("20260510_120000_00002_N_A.MP4", cleaned_completed_clips[trip_id])

if __name__ == "__main__":
    unittest.main()
