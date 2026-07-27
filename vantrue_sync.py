#!/usr/bin/env python3
import os
import sys
import re
import shutil
import argparse
import subprocess
import tempfile
import json
from datetime import datetime

BINARIES = {}

def find_tool(tool_name):
    path = shutil.which(tool_name)
    if path:
        return path
    common_paths = [
        f"/usr/bin/{tool_name}",
        f"/usr/local/bin/{tool_name}",
        f"/bin/{tool_name}",
        f"/snap/bin/{tool_name}"
    ]
    for p in common_paths:
        if os.path.exists(p) and os.access(p, os.X_OK):
            return p
    return None

def check_dependencies():
    missing = []
    for tool in ['exiftool', 'rclone']:
        found_path = find_tool(tool)
        if found_path:
            BINARIES[tool] = found_path
        else:
            missing.append(tool)
    if missing:
        print(f"Error: Missing required external dependencies: {', '.join(missing)}", file=sys.stderr)
        print("Please install them before running this script.", file=sys.stderr)
        sys.exit(1)

def get_shm_dir():
    shm = "/dev/shm"
    if os.path.exists(shm) and os.access(shm, os.W_OK):
        return shm
    return tempfile.gettempdir()

def check_free_space(path, required_bytes):
    stat = os.statvfs(path)
    free_bytes = stat.f_bavail * stat.f_frsize
    return free_bytes >= required_bytes, free_bytes

def get_clips(root_dir):
    clips = []
    subdirs = ["Normal", "Event"]
    pattern = re.compile(r'^(\d{8}_\d{6})')

    for subdir in subdirs:
        dir_path = os.path.join(root_dir, subdir)
        if not os.path.isdir(dir_path):
            continue
        for entry in os.scandir(dir_path):
            if entry.is_file() and entry.name.lower().endswith('.mp4'):
                match = pattern.match(entry.name)
                if match:
                    try:
                        dt = datetime.strptime(match.group(1), "%Y%m%d_%H%M%S")
                        clips.append({
                            'path': entry.path,
                            'name': entry.name,
                            'subdir': subdir,
                            'stamp': match.group(1),
                            'time': dt,
                            'is_event': (subdir == "Event"),
                            'size': entry.stat().st_size
                        })
                    except ValueError:
                        continue
    return clips

def group_into_trips(clips, gap_seconds):
    if not clips:
        return []
    
    clips.sort(key=lambda x: (x['time'], x['name']))
    
    trips = []
    current_trip = [clips[0]]
    
    for clip in clips[1:]:
        delta = (clip['time'] - current_trip[-1]['time']).total_seconds()
        if delta <= gap_seconds:
            current_trip.append(clip)
        else:
            trips.append(current_trip)
            current_trip = [clip]
    trips.append(current_trip)
    return trips

def stamp_to_iso(stamp):
    dt = datetime.strptime(stamp, "%Y%m%d_%H%M%S")
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")

def run_exiftool_for_paths(paths, fmt_path, out_gpx_path):
    exiftool_bin = BINARIES.get('exiftool', 'exiftool')
    cmd = [
        exiftool_bin,
        "-d", "%Y-%m-%dT%H:%M:%SZ",
        "-ee",
        "-q", "-q",
        "-p", fmt_path
    ] + list(paths)
    
    try:
        with open(out_gpx_path, "wb") as out_f:
            res = subprocess.run(cmd, stdout=out_f, stderr=subprocess.PIPE, check=True)
        return True
    except subprocess.CalledProcessError:
        return False

def exiftool_can_read(path):
    exiftool_bin = BINARIES.get('exiftool', 'exiftool')
    cmd = [
        exiftool_bin,
        "-ee",
        "-q", "-q",
        "-p", "$gpsdatetime",
        path
    ]
    res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return res.returncode == 0

def combine_gpx_fragments(fragment_paths, out_gpx_path):
    header = '<?xml version="1.0" encoding="utf-8"?>\n<gpx version="1.1" creator="ExifTool" xmlns="http://www.topografix.com/GPX/1/1" xmlns:gpxtpx="http://www.garmin.com/xmlschemas/TrackPointExtension/v1">\n<trk><trkseg>\n'
    footer = '</trkseg></trk></gpx>\n'
    
    trkpts = []
    for frag in fragment_paths:
        if not os.path.exists(frag):
            continue
        with open(frag, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
            matches = re.findall(r'<trkpt.*?</trkpt>', content, re.DOTALL)
            trkpts.extend(matches)
            
    with open(out_gpx_path, 'w', encoding='utf-8') as out_f:
        out_f.write(header)
        for trkpt in trkpts:
            out_f.write(trkpt + '\n')
        out_f.write(footer)

def generate_gpx_in_shm(trip_clips, fmt_path, out_gpx_path):
    paths = [clip['path'] for clip in trip_clips]
    if run_exiftool_for_paths(paths, fmt_path, out_gpx_path):
        return True
    
    good_paths = []
    for clip in trip_clips:
        if exiftool_can_read(clip['path']):
            good_paths.append(clip['path'])
        else:
            print(f"Warning: Skipping bad clip for GPX extraction: {clip['path']}", file=sys.stderr)
            
    if not good_paths:
        return False
    
    return run_exiftool_for_paths(good_paths, fmt_path, out_gpx_path)

def generate_manifest_in_shm(trip_clips, out_manifest_path):
    start_stamp = trip_clips[0]['stamp']
    end_stamp = trip_clips[-1]['stamp']
    has_events = any(clip['is_event'] for clip in trip_clips)
    
    manifest_data = {
        "journey_id": f"{start_stamp}_to_{end_stamp}",
        "start_time": stamp_to_iso(start_stamp),
        "end_time": stamp_to_iso(end_stamp),
        "has_events": has_events,
        "total_clips": len(trip_clips),
        "gpx_file": "journey.gpx",
        "clips": [
            {
                "playback_order": idx + 1,
                "filename": clip['name'],
                "source_folder": clip['subdir'],
                "is_event": clip['is_event']
            }
            for idx, clip in enumerate(trip_clips)
        ]
    }
    
    with open(out_manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest_data, f, indent=2)

def parse_selection(selection_str, max_val):
    selection_str = selection_str.strip().lower()
    if selection_str == 'all':
        return list(range(1, max_val + 1))
    
    selected = set()
    parts = selection_str.split(',')
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if '-' in part:
            try:
                start_str, end_str = part.split('-')
                start = int(start_str.strip())
                end = int(end_str.strip())
                if 1 <= start <= end <= max_val:
                    selected.update(range(start, end + 1))
            except ValueError:
                continue
        else:
            try:
                val = int(part)
                if 1 <= val <= max_val:
                    selected.add(val)
            except ValueError:
                continue
    return sorted(list(selected))

# --- CHECKPOINT MANAGEMENT ---
CHECKPOINT_FILE = ".sync_checkpoint.json"

def load_checkpoint(usb_dir, remote):
    if not os.path.exists(CHECKPOINT_FILE):
        return None
    try:
        with open(CHECKPOINT_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            # Validate that the checkpoint belongs to the exact same USB drive and remote!
            if data.get("usb_dir") == os.path.abspath(usb_dir) and data.get("remote") == remote:
                return data
    except Exception as e:
        print(f"Warning: Could not read checkpoint file: {e}", file=sys.stderr)
    return None

def save_checkpoint(usb_dir, remote, completed_trip_ids, completed_clips):
    data = {
        "usb_dir": os.path.abspath(usb_dir),
        "remote": remote,
        "updated_at": datetime.now().isoformat(),
        "completed_trips": list(completed_trip_ids),
        "completed_clips": completed_clips  # dict: {trip_id: [clip_names]}
    }
    temp_cp = f"{CHECKPOINT_FILE}.tmp"
    with open(temp_cp, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)
    os.replace(temp_cp, CHECKPOINT_FILE)

def clear_checkpoint():
    if os.path.exists(CHECKPOINT_FILE):
        try:
            os.unlink(CHECKPOINT_FILE)
        except OSError:
            pass

# --- UPLOAD WITH RESUME & CHECKPOINTING ---
def upload_trip(trip, remote_base, fmt_path, mode, shm_dir, usb_dir, completed_trip_ids, completed_clips, dry_run=False):
    start_stamp = trip[0]['stamp']
    end_stamp = trip[-1]['stamp']
    trip_id = f"{start_stamp}_to_{end_stamp}"
    
    if trip_id in completed_trip_ids:
        print(f"\n[SKIP] Trip {trip_id} is already fully synced according to checkpoint.")
        return

    start_dt = trip[0]['time']
    year_month = start_dt.strftime("%Y-%m")
    trip_folder_name = f"Trip_{trip_id}"
    cloud_dest = f"{remote_base.rstrip('/')}/{year_month}/{trip_folder_name}"
    
    print(f"\n---> Processing Trip: {trip_folder_name}")
    print(f"Cloud Destination: {cloud_dest}")
    
    shm_gpx = os.path.join(shm_dir, f"journey_{start_stamp}.gpx")
    shm_manifest = os.path.join(shm_dir, f"manifest_{start_stamp}.json")
    rclone_bin = BINARIES.get('rclone', 'rclone')
    
    if trip_id not in completed_clips:
        completed_clips[trip_id] = []
        
    try:
        print(f"Creating cloud folder: {cloud_dest}")
        if not dry_run:
            subprocess.run([rclone_bin, "mkdir", cloud_dest], check=True)

        if mode == 'ram':
            gpx_fragments = []
            
            for idx, clip in enumerate(trip, start=1):
                clip_cloud_dest = f"{cloud_dest}/{clip['name']}"
                
                # Checkpoint check per clip
                if clip['name'] in completed_clips[trip_id]:
                    print(f"[{idx}/{len(trip)}] [SKIP] Clip {clip['name']} already uploaded.")
                    continue

                print(f"[{idx}/{len(trip)}] Buffering in RAM & Uploading {clip['name']}...")
                
                req_space = clip['size'] + (50 * 1024 * 1024)
                ok, free_b = check_free_space(shm_dir, req_space)
                
                ram_clip_path = os.path.join(shm_dir, f"clip_{idx}.mp4")
                source_path_for_gpx = clip['path']
                
                if dry_run:
                    continue
                    
                if ok:
                    try:
                        shutil.copyfile(clip['path'], ram_clip_path)
                        source_path_for_gpx = ram_clip_path
                        subprocess.run([rclone_bin, "copyto", ram_clip_path, clip_cloud_dest], check=True)
                    except Exception as e:
                        print(f"Warning: RAM buffer failed for {clip['name']}: {e}. Direct USB upload fallback.", file=sys.stderr)
                        subprocess.run([rclone_bin, "copyto", clip['path'], clip_cloud_dest], check=True)
                else:
                    print(f"Warning: Insufficient RAM for {clip['name']}. Direct USB upload fallback.", file=sys.stderr)
                    subprocess.run([rclone_bin, "copyto", clip['path'], clip_cloud_dest], check=True)
                
                # Extract GPX fragment
                frag_gpx = os.path.join(shm_dir, f"frag_{idx}.gpx")
                if generate_gpx_in_shm([{'path': source_path_for_gpx}], fmt_path, frag_gpx):
                    gpx_fragments.append(frag_gpx)
                    
                if os.path.exists(ram_clip_path):
                    os.unlink(ram_clip_path)

                # Record clip success in checkpoint
                completed_clips[trip_id].append(clip['name'])
                save_checkpoint(usb_dir, remote_base, completed_trip_ids, completed_clips)

            print("Generating manifest.json in RAM (/dev/shm)...")
            if not dry_run:
                generate_manifest_in_shm(trip, shm_manifest)
                if os.path.exists(shm_manifest):
                    subprocess.run([rclone_bin, "copyto", shm_manifest, f"{cloud_dest}/manifest.json"], check=True)

            if not dry_run and gpx_fragments:
                print("Consolidating GPX in RAM and uploading...")
                combine_gpx_fragments(gpx_fragments, shm_gpx)
                if os.path.exists(shm_gpx):
                    subprocess.run([rclone_bin, "copyto", shm_gpx, f"{cloud_dest}/journey.gpx"], check=True)
                for frag in gpx_fragments:
                    if os.path.exists(frag):
                        os.unlink(frag)

        else:
            # Direct USB -> Cloud mode
            for idx, clip in enumerate(trip, start=1):
                clip_cloud_dest = f"{cloud_dest}/{clip['name']}"
                if clip['name'] in completed_clips[trip_id]:
                    print(f"[{idx}/{len(trip)}] [SKIP] Clip {clip['name']} already uploaded.")
                    continue

                print(f"[{idx}/{len(trip)}] Uploading clip {clip['name']}...")
                if not dry_run:
                    subprocess.run([rclone_bin, "copyto", clip['path'], clip_cloud_dest], check=True)
                    completed_clips[trip_id].append(clip['name'])
                    save_checkpoint(usb_dir, remote_base, completed_trip_ids, completed_clips)

            print("Generating GPX in RAM (/dev/shm)...")
            if not dry_run:
                generate_gpx_in_shm(trip, fmt_path, shm_gpx)

            print("Generating manifest.json in RAM (/dev/shm)...")
            if not dry_run:
                generate_manifest_in_shm(trip, shm_manifest)

            if not dry_run:
                if os.path.exists(shm_gpx):
                    subprocess.run([rclone_bin, "copyto", shm_gpx, f"{cloud_dest}/journey.gpx"], check=True)
                if os.path.exists(shm_manifest):
                    subprocess.run([rclone_bin, "copyto", shm_manifest, f"{cloud_dest}/manifest.json"], check=True)

        # Mark whole trip as completed in checkpoint
        if not dry_run:
            completed_trip_ids.add(trip_id)
            save_checkpoint(usb_dir, remote_base, completed_trip_ids, completed_clips)

    finally:
        for tmp_file in [shm_gpx, shm_manifest]:
            if os.path.exists(tmp_file):
                try:
                    os.unlink(tmp_file)
                except OSError:
                    pass
                    
    print(f"Completed upload for trip: {trip_folder_name}")

def main():
    parser = argparse.ArgumentParser(description="Vantrue Dashcam Cloud Sync (Zero HDD I/O & Checkpoint Resume)")
    parser.add_argument("--usb-dir", required=True, help="Path to mounted USB drive root containing Normal/ and Event/ folders")
    parser.add_argument("--remote", required=True, help="RClone remote destination (e.g. gdrive:Dashcam)")
    parser.add_argument("--gap", type=int, default=65, help="Time gap threshold in seconds for trip grouping (default: 65)")
    parser.add_argument("--fmt", default="gpx.fmt", help="Path to ExifTool GPX format file (default: gpx.fmt)")
    parser.add_argument("--mode", choices=["direct", "ram"], default="ram", help="Transfer mode: 'direct' (USB->Cloud) or 'ram' (RAM buffered) (default: ram)")
    parser.add_argument("--resume", action="store_true", help="Resume previous sync session from checkpoint if available")
    parser.add_argument("--dry-run", action="store_true", help="Simulate actions without performing actual uploads")
    
    args = parser.parse_args()
    
    check_dependencies()
    shm_dir = get_shm_dir()
    
    if not os.path.isdir(args.usb_dir):
        print(f"Error: USB root directory '{args.usb_dir}' does not exist.", file=sys.stderr)
        sys.exit(1)
        
    if not os.path.isfile(args.fmt):
        script_dir = os.path.dirname(os.path.abspath(__file__))
        fmt_in_script_dir = os.path.join(script_dir, args.fmt)
        if os.path.isfile(fmt_in_script_dir):
            args.fmt = fmt_in_script_dir
        else:
            print(f"Error: GPX format file '{args.fmt}' not found.", file=sys.stderr)
            sys.exit(1)
            
    # --- CHECKPOINT VALIDATION & RESUME LOGIC ---
    checkpoint = load_checkpoint(args.usb_dir, args.remote)
    completed_trip_ids = set()
    completed_clips = {}
    
    if checkpoint:
        if args.resume:
            print("================================================================================")
            print(" RESUME MODE DETECTED: Found existing checkpoint matching this USB & Remote!")
            print(f" Saved at: {checkpoint.get('updated_at')}")
            print(f" Completed Trips: {len(checkpoint.get('completed_trips', []))}")
            print("================================================================================")
            completed_trip_ids = set(checkpoint.get("completed_trips", []))
            completed_clips = checkpoint.get("completed_clips", {})
        else:
            print("Notice: An existing checkpoint was found, but --resume was not specified.")
            print("Overwriting existing checkpoint and starting clean sync session.")
            clear_checkpoint()

    print(f"Scanning USB directory: {args.usb_dir} ...")
    clips = get_clips(args.usb_dir)
    if not clips:
        print("No valid MP4 clips found in Normal/ or Event/.", file=sys.stderr)
        sys.exit(1)
        
    # Get current available clip names on USB
    available_clip_names = {c['name'] for c in clips}
    
    # Filter out completed clips from checkpoint that NO LONGER exist on the USB card
    if args.resume and completed_clips:
        cleaned_completed_clips = {}
        for trip_id, clip_list in completed_clips.items():
            valid_clips = [c for c in clip_list if c in available_clip_names]
            if valid_clips:
                cleaned_completed_clips[trip_id] = valid_clips
        completed_clips = cleaned_completed_clips

    trips = group_into_trips(clips, args.gap)
    total_trips = len(trips)
    print(f"Found {len(clips)} clips on USB. Grouped into {total_trips} trips.")
    print("=" * 80)
    
    for idx, trip in enumerate(trips, start=1):
        start_str = trip[0]['time'].strftime('%Y-%m-%d %H:%M:%S')
        end_str = trip[-1]['time'].strftime('%Y-%m-%d %H:%M:%S')
        events = sum(1 for c in trip if c['is_event'])
        normals = sum(1 for c in trip if not c['is_event'])
        trip_id = f"{trip[0]['stamp']}_to_{trip[-1]['stamp']}"
        
        status_tag = ""
        if trip_id in completed_trip_ids:
            status_tag = " [COMPLETED]"
        elif trip_id in completed_clips and completed_clips[trip_id]:
            status_tag = f" [PARTIAL {len(completed_clips[trip_id])}/{len(trip)} clips done]"

        print(f"[{idx:2d}]{status_tag} Start: {start_str} | End: {end_str} | Clips: {len(trip):2d} (Normal: {normals}, Event: {events})")
        
    print("=" * 80)
    
    try:
        user_input = input("Select trips to sync (e.g. '1,3,5-8', 'all', 'q' to quit): ")
    except (KeyboardInterrupt, EOFError):
        print("\nAborted.")
        sys.exit(0)
        
    if user_input.strip().lower() in ['q', 'quit', 'exit', '']:
        print("No trips processed.")
        sys.exit(0)
        
    selected_indices = parse_selection(user_input, total_trips)
    if not selected_indices:
        print("Invalid selection.")
        sys.exit(1)
        
    print(f"\nSelected {len(selected_indices)} trips for cloud sync: {selected_indices}")
    
    for idx in selected_indices:
        trip = trips[idx - 1]
        upload_trip(trip, args.remote, args.fmt, args.mode, shm_dir, args.usb_dir, completed_trip_ids, completed_clips, dry_run=args.dry_run)
        
    print("\nAll selected trips have been processed successfully!")
    # Clear checkpoint file upon complete successful finish
    clear_checkpoint()

if __name__ == "__main__":
    main()
