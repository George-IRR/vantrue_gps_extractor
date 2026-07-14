#!/usr/bin/env python3
import os
import sys
import re
import subprocess
import tempfile
from datetime import datetime

def parse_arguments():
    if len(sys.argv) < 3:
        print("Usage: python3 merge_trips.py <root_dir> <output_dir> [gap_seconds] [--dry-run <report_file>]", file=sys.stderr)
        sys.exit(1)
    
    root_dir = sys.argv[1]
    output_dir = sys.argv[2]
    
    gap_seconds = 65
    dry_run_file = None
    
    # Parsare parametri opționali
    args = sys.argv[3:]
    i = 0
    while i < len(args):
        if args[i] == '--dry-run':
            if i + 1 < len(args):
                dry_run_file = args[i+1]
                i += 2
            else:
                print("Error: --dry-run requires a target report file path", file=sys.stderr)
                sys.exit(1)
        else:
            try:
                gap_seconds = int(args[i])
                i += 1
            except ValueError:
                print(f"Error: Invalid argument '{args[i]}'", file=sys.stderr)
                sys.exit(1)
                
    return root_dir, output_dir, gap_seconds, dry_run_file

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
                            'time': dt
                        })
                    except ValueError:
                        continue
    return clips

def group_into_trips(clips, gap_seconds):
    if not clips:
        return []
    
    clips.sort(key=lambda x: x['time'])
    
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

def generate_dry_run_report(trips, report_file):
    with open(report_file, 'w', encoding='utf-8') as f:
        f.write(f"DRY RUN TRIP REPORT - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write("=" * 70 + "\n\n")
        for idx, trip in enumerate(trips, start=1):
            start_str = trip[0]['time'].strftime('%Y-%m-%d %H:%M:%S')
            end_str = trip[-1]['time'].strftime('%Y-%m-%d %H:%M:%S')
            f.write(f"Trip #{idx} ({len(trip)} clips) | Start: {start_str} | End: {end_str}\n")
            f.write("-" * 70 + "\n")
            for clip in trip:
                f.write(f"  [{clip['subdir']}] {clip['name']}\n")
            f.write("\n")
    print(f"Dry run report successfully written to: {report_file}")

def merge_trip(trip, output_dir):
    start_stamp = trip[0]['stamp']
    end_stamp = trip[-1]['stamp']
    out_filename = f"trip_{start_stamp}_to_{end_stamp}.mp4"
    out_path = os.path.join(output_dir, out_filename)
    
    print(f"Merging {len(trip)} clips into {out_path}...")
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
        for clip in trip:
            escaped_path = clip['path'].replace("'", "'\\''")
            f.write(f"file '{escaped_path}'\n")
        temp_list_path = f.name
        
    try:
        cmd = [
            'ffmpeg', '-y',
            '-f', 'concat',
            '-safe', '0',
            '-i', temp_list_path,
            '-c', 'copy',
            out_path
        ]
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    except subprocess.CalledProcessError as e:
        print(f"Error merging trip {start_stamp} to {end_stamp}:", file=sys.stderr)
        print(e.stderr.decode(), file=sys.stderr)
    finally:
        os.unlink(temp_list_path)

def main():
    root_dir, output_dir, gap_seconds, dry_run_file = parse_arguments()
    
    if not os.path.isdir(root_dir):
        print(f"Error: Root directory '{root_dir}' does not exist.", file=sys.stderr)
        sys.exit(1)
        
    clips = get_clips(root_dir)
    if not clips:
        print("No valid MP4 clips found in 'Normal' or 'Event' subdirectories.", file=sys.stderr)
        sys.exit(1)
        
    trips = group_into_trips(clips, gap_seconds)
    print(f"Found {len(clips)} total clips. Grouped into {len(trips)} distinct trips.")
    
    if dry_run_file:
        generate_dry_run_report(trips, dry_run_file)
    else:
        os.makedirs(output_dir, exist_ok=True)
        for trip in trips:
            merge_trip(trip, output_dir)

if __name__ == "__main__":
    main()