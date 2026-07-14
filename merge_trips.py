#!/usr/bin/env python3
import os
import sys
import re
import subprocess
import tempfile
from datetime import datetime

def parse_arguments():
    if len(sys.argv) < 3:
        print("Usage: python3 merge_trips.py <root_dir> <output_dir> [gap_seconds]", file=sys.stderr)
        sys.exit(1)
    
    root_dir = sys.argv[1]
    output_dir = sys.argv[2]
    gap_seconds = int(sys.argv[3]) if len(sys.argv) > 3 else 65
    return root_dir, output_dir, gap_seconds

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

def parse_selection(selection_str, max_val):
    selection_str = selection_str.strip().lower()
    if selection_str == 'all':
        return list(range(1, max_val + 1))
    
    selected = set()
    parts = selection_str.split(',')
    for part in parts:
        part = part.strip()
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
    root_dir, output_dir, gap_seconds = parse_arguments()
    
    if not os.path.isdir(root_dir):
        print(f"Error: Root directory '{root_dir}' does not exist.", file=sys.stderr)
        sys.exit(1)
        
    clips = get_clips(root_dir)
    if not clips:
        print("No valid MP4 clips found.", file=sys.stderr)
        sys.exit(1)
        
    trips = group_into_trips(clips, gap_seconds)
    total_trips = len(trips)
    print(f"Found {len(clips)} clips. Grouped into {total_trips} trips.")
    print("-" * 80)
    
    # Afișare listă simplificată în terminal
    for idx, trip in enumerate(trips, start=1):
        start_str = trip[0]['time'].strftime('%Y-%m-%d %H:%M:%S')
        end_str = trip[-1]['time'].strftime('%Y-%m-%d %H:%M:%S')
        events = sum(1 for c in trip if c['subdir'] == 'Event')
        normals = sum(1 for c in trip if c['subdir'] == 'Normal')
        print(f"[{idx:2d}] Start: {start_str} | End: {end_str} | Clips: {len(trip):2d} (Normal: {normals}, Event: {events})")
        
    print("-" * 80)
    
    # Solicitare selecție
    try:
        user_input = input("Introduceți trip-urile pentru merge (Ex: '1,3,5-8', 'all', 'q' pentru ieșire): ")
    except (KeyboardInterrupt, EOFError):
        print("\nAborted.")
        sys.exit(0)
        
    if user_input.strip().lower() in ['q', 'quit', 'exit', '']:
        print("No trips processed.")
        sys.exit(0)
        
    selected_indices = parse_selection(user_input, total_trips)
    if not selected_indices:
        print("Selecție invalidă.")
        sys.exit(1)
        
    print(f"\nS-au selectat {len(selected_indices)} trip-uri pentru îmbinare: {selected_indices}\n")
    os.makedirs(output_dir, exist_ok=True)
    
    for idx in selected_indices:
        trip = trips[idx - 1]
        print(f"Procesare Trip #{idx}...")
        merge_trip(trip, output_dir)

if __name__ == "__main__":
    main()