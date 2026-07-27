import os
import sys
import tempfile
import json
import shutil
import unittest
from unittest.mock import patch, MagicMock
from datetime import datetime

import vantrue_sync

class TestVantrueSync(unittest.TestCase):

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.normal_dir = os.path.join(self.test_dir, "Normal")
        self.event_dir = os.path.join(self.test_dir, "Event")
        os.makedirs(self.normal_dir)
        os.makedirs(self.event_dir)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)
        if os.path.exists(vantrue_sync.CHECKPOINT_FILE):
            try:
                os.unlink(vantrue_sync.CHECKPOINT_FILE)
            except OSError:
                pass

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
        
        # Check sorting
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
        remote = "GoogleDriveMain190:Dashcam_Auto"
        completed_trips = {"20260510_151242_to_20260510_151342"}
        completed_clips = {"20260510_151242_to_20260510_151342": ["20260510_151242_00004_N_A.MP4"]}

        vantrue_sync.save_checkpoint(usb, remote, completed_trips, completed_clips)
        self.assertTrue(os.path.exists(vantrue_sync.CHECKPOINT_FILE))

        # Test loading valid checkpoint
        cp = vantrue_sync.load_checkpoint(usb, remote)
        self.assertIsNotNone(cp)
        self.assertEqual(cp['completed_trips'], list(completed_trips))
        self.assertEqual(cp['completed_clips'], completed_clips)

        # Test loading mismatching USB / Remote
        self.assertIsNone(vantrue_sync.load_checkpoint("/different/usb", remote))
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

    @patch("subprocess.run")
    def test_upload_trip_ram_mode(self, mock_subproc):
        mock_subproc.return_value = MagicMock(returncode=0)

        dt = datetime(2026, 5, 10, 15, 12, 42)
        f1_path = os.path.join(self.normal_dir, "20260510_151242_00004_N_A.MP4")
        with open(f1_path, "w") as f: f.write("video content")

        trip = [{
            'path': f1_path,
            'name': "20260510_151242_00004_N_A.MP4",
            'subdir': "Normal",
            'stamp': "20260510_151242",
            'time': dt,
            'is_event': False,
            'size': os.path.getsize(f1_path)
        }]

        completed_trips = set()
        completed_clips = {}
        shm_dir = self.test_dir

        fmt_path = os.path.join(self.test_dir, "gpx.fmt")
        with open(fmt_path, "w") as f: f.write("dummy fmt")

        with patch("vantrue_sync.generate_gpx_in_shm", return_value=True):
            vantrue_sync.upload_trip(
                trip=trip,
                remote_base="GoogleDriveMain190:Dashcam_Auto",
                fmt_path=fmt_path,
                mode="ram",
                shm_dir=shm_dir,
                usb_dir=self.test_dir,
                completed_trip_ids=completed_trips,
                completed_clips=completed_clips,
                dry_run=False
            )

        self.assertIn("20260510_151242_to_20260510_151242", completed_trips)
        self.assertTrue(mock_subproc.called)

if __name__ == "__main__":
    unittest.main()
