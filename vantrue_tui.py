#!/usr/bin/env python3
"""
Vantrue Dashcam Cloud Sync - Interactive Terminal User Interface (TUI)
Provides automatic discovery of removable SD cards/drives, RClone cloud remotes,
interactive trip selection, and zero SSD write sync execution.
"""

import os
import sys
import glob
import psutil
from datetime import datetime
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.prompt import Prompt, Confirm, IntPrompt
from rich.text import Text
from rich import box

import vantrue_sync

console = Console()

def get_removable_dashcam_drives():
    """
    Scans mount points and media directories to discover attached Vantrue dashcam SD cards / USBs.
    """
    candidates = []
    checked_paths = set()
    user = os.environ.get("USER", "")

    search_patterns = [
        f"/run/media/{user}/*",
        f"/media/{user}/*",
        "/media/*",
        "/mnt/*"
    ]
    
    potential_dirs = []
    for pattern in search_patterns:
        potential_dirs.extend(glob.glob(pattern))

    for part in psutil.disk_partitions(all=False):
        if part.mountpoint and part.mountpoint not in potential_dirs:
            if not part.mountpoint.startswith(("/snap", "/boot", "/sys", "/proc", "/dev")):
                potential_dirs.append(part.mountpoint)

    for p in potential_dirs:
        abs_p = os.path.abspath(p)
        if abs_p in checked_paths or not os.path.isdir(abs_p):
            continue
        checked_paths.add(abs_p)

        has_normal = os.path.isdir(os.path.join(abs_p, "Normal"))
        has_event = os.path.isdir(os.path.join(abs_p, "Event"))
        
        clips = []
        if has_normal or has_event:
            try:
                clips = vantrue_sync.get_clips(abs_p)
            except Exception:
                clips = []

        if clips or (has_normal and has_event):
            try:
                usage = psutil.disk_usage(abs_p)
                free_gb = usage.free / (1024 ** 3)
                total_gb = usage.total / (1024 ** 3)
            except Exception:
                free_gb, total_gb = 0.0, 0.0

            normal_count = sum(1 for c in clips if not c.get('is_event'))
            event_count = sum(1 for c in clips if c.get('is_event'))

            candidates.append({
                'path': abs_p,
                'name': os.path.basename(abs_p) or abs_p,
                'total_gb': total_gb,
                'free_gb': free_gb,
                'clips_total': len(clips),
                'normal_count': normal_count,
                'event_count': event_count,
                'is_dashcam': True
            })

    return candidates

def select_source_drive():
    """
    Prompts user to select from detected removable dashcam drives or browse manually.
    """
    console.print(Panel("[bold cyan]STEP 1: Select Video Source (SD Card / Dashcam USB)[/bold cyan]", border_style="cyan"))
    
    drives = get_removable_dashcam_drives()
    
    table = Table(title="Automatically Detected Dashcam Devices", box=box.ROUNDED)
    table.add_column("#", style="bold yellow", justify="center", width=4)
    table.add_column("Device / Volume Name", style="bold white")
    table.add_column("Mount Path", style="green")
    table.add_column("Clips Found", style="magenta")
    table.add_column("Free Space", style="blue")

    for idx, d in enumerate(drives, start=1):
        clip_info = f"{d['clips_total']} clips ({d['normal_count']} Normal, {d['event_count']} Event)"
        space_info = f"{d['free_gb']:.1f} GB free / {d['total_gb']:.1f} GB"
        table.add_row(str(idx), d['name'], d['path'], clip_info, space_info)

    browse_idx = len(drives) + 1
    table.add_row(str(browse_idx), "[italic]Enter manual path / Browse folder[/italic]", "-", "-", "-")

    console.print(table)

    while True:
        choice = Prompt.ask(
            f"Select source [1-{browse_idx}]",
            default="1" if drives else str(browse_idx)
        )
        try:
            val = int(choice.strip())
            if 1 <= val <= len(drives):
                chosen_drive = drives[val - 1]['path']
                console.print(f"[bold green]✓ Selected source:[/bold green] {chosen_drive}\n")
                return chosen_drive
            elif val == browse_idx:
                while True:
                    custom_path = Prompt.ask("Enter the full path to the source folder (containing Normal/ and Event/)")
                    custom_path = os.path.expanduser(custom_path.strip())
                    if os.path.isdir(custom_path):
                        clips = vantrue_sync.get_clips(custom_path)
                        if not clips:
                            console.print("[yellow]Warning: No MP4 clips found in Normal/ or Event/ subfolders in this path.[/yellow]")
                            if Confirm.ask("Do you still want to use this folder?", default=False):
                                return custom_path
                        else:
                            console.print(f"[bold green]✓ Selected source ({len(clips)} clips):[/bold green] {custom_path}\n")
                            return custom_path
                    else:
                        console.print(f"[bold red]Error: Path '{custom_path}' does not exist or is not a directory.[/bold red]")
        except ValueError:
            console.print("[bold red]Please enter a valid number.[/bold red]")

def select_remote_destination():
    """
    Prompts user to select an rclone cloud remote or explicitly a local destination.
    """
    console.print(Panel("[bold cyan]STEP 2: Select Rclone Cloud Destination[/bold cyan]", border_style="cyan"))
    
    remotes = vantrue_sync.get_rclone_remotes()
    
    table = Table(title="Detected Rclone Cloud Remotes", box=box.ROUNDED)
    table.add_column("#", style="bold yellow", justify="center", width=4)
    table.add_column("Remote Name", style="bold green")
    table.add_column("Type / Destination", style="white")

    for idx, r in enumerate(remotes, start=1):
        table.add_row(str(idx), r, "Rclone Cloud Account (Google Drive / OneDrive / etc.)")

    local_idx = len(remotes) + 1
    table.add_row(str(local_idx), "[italic]Local Disk Folder (No Cloud upload)[/italic]", "Save locally to SSD/HDD")

    console.print(table)

    while True:
        choice = Prompt.ask(
            f"Select destination [1-{local_idx}]",
            default="1" if remotes else str(local_idx)
        )
        try:
            val = int(choice.strip())
            if 1 <= val <= len(remotes):
                chosen_remote = remotes[val - 1]
                console.print(f"\n[bold green]Selected Cloud remote:[/bold green] [bold cyan]{chosen_remote}[/bold cyan]")
                
                subfolder = Prompt.ask(
                    "Enter cloud subfolder (leave blank for root)",
                    default="Dashcam_Auto"
                ).strip()
                
                if subfolder:
                    subfolder = subfolder.strip("/")
                    final_dest = f"{chosen_remote}{subfolder}"
                else:
                    final_dest = chosen_remote
                
                console.print(f"[bold green]Final Cloud destination:[/bold green] [bold yellow]{final_dest}[/bold yellow]\n")
                return final_dest, False

            elif val == local_idx:
                console.print(Panel(
                    "[bold red]IMPORTANT: LOCAL STORAGE SELECTION[/bold red]\n\n"
                    "You have selected a local disk folder.\n"
                    "• Files will [bold underline]NOT be uploaded to Google Drive or any cloud[/bold underline]!\n"
                    "• All videos will be copied to your computer's local storage (SSD/HDD),\n"
                    "  consuming disk space in the chosen directory.\n",
                    title="Warning",
                    border_style="yellow"
                ))
                
                if not Confirm.ask("Are you sure you want local storage and NOT cloud upload?", default=False):
                    continue

                local_path = Prompt.ask("Enter destination local folder path", default="./output_dashcam")
                local_path = os.path.expanduser(local_path.strip())
                return local_path, True

        except ValueError:
            console.print("[bold red]Please enter a valid number.[/bold red]")

def select_trips_interactive(trips, completed_trip_ids, completed_clips):
    """
    Displays trip summary in a rich table and asks for selection.
    """
    console.print(Panel("[bold cyan]STEP 3: Select Trips[/bold cyan]", border_style="cyan"))
    
    table = Table(title=f"Detected Trips ({len(trips)} journeys)", box=box.ROUNDED)
    table.add_column("#", style="bold yellow", justify="center", width=4)
    table.add_column("Status", justify="center")
    table.add_column("Trip Start", style="cyan")
    table.add_column("Trip End", style="cyan")
    table.add_column("Normal Clips", justify="center", style="green")
    table.add_column("Events", justify="center", style="bold red")
    table.add_column("Total Clips", justify="center", style="bold white")

    for idx, trip in enumerate(trips, start=1):
        start_str = trip[0]['time'].strftime('%Y-%m-%d %H:%M:%S')
        end_str = trip[-1]['time'].strftime('%Y-%m-%d %H:%M:%S')
        events = sum(1 for c in trip if c['is_event'])
        normals = sum(1 for c in trip if not c['is_event'])
        trip_id = f"{trip[0]['stamp']}_to_{trip[-1]['stamp']}"

        if trip_id in completed_trip_ids:
            status = "[bold green]✓ Synced[/bold green]"
        elif trip_id in completed_clips and completed_clips[trip_id]:
            done_count = len(completed_clips[trip_id])
            status = f"[yellow]Partial ({done_count}/{len(trip)})[/yellow]"
        else:
            status = "[bold blue]New[/bold blue]"

        event_str = f"[bold red]{events}[/bold red]" if events > 0 else "0"
        table.add_row(str(idx), status, start_str, end_str, str(normals), event_str, str(len(trip)))

    console.print(table)
    console.print("[dim]You can select 'all' for all trips, or ranges like '1,3,5-8'. Type 'q' to quit.[/dim]")

    while True:
        sel_str = Prompt.ask("Select trips to synchronize", default="all").strip()
        if sel_str.lower() in ['q', 'quit', 'exit']:
            console.print("[yellow]Operation aborted by user.[/yellow]")
            sys.exit(0)
        
        indices = vantrue_sync.parse_selection(sel_str, len(trips))
        if indices:
            console.print(f"[bold green]✓ Selected {len(indices)} trip(s):[/bold green] {indices}\n")
            return indices
        else:
            console.print("[bold red]Invalid selection. Please try again.[/bold red]")

def main():
    console.clear()
    console.print(Panel.fit(
        "[bold cyan]VANTRUE DASHCAM CLOUD SYNC & GPS EXTRACTOR[/bold cyan]\n"
        "[dim]Zero SSD Wear | RAM Prefetch Pipeline | Checkpoint Resume | Rclone Cloud Upload[/dim]",
        border_style="blue"
    ))

    vantrue_sync.check_dependencies()
    shm_dir = vantrue_sync.get_shm_dir()

    # Step 1: Select Source USB / SD Card
    usb_dir = select_source_drive()

    # Step 2: Select Cloud Destination
    remote_dest, is_local = select_remote_destination()

    # Step 3: Checkpoint & Resume Handling
    checkpoint = vantrue_sync.load_checkpoint(usb_dir, remote_dest)
    completed_trip_ids = set()
    completed_clips = {}
    resume_mode = False

    if checkpoint:
        console.print(Panel(
            f"[bold green]Previous session detected![/bold green]\n"
            f"Last update: {checkpoint.get('updated_at')}\n"
            f"Trips completed earlier: {len(checkpoint.get('completed_trips', []))}\n",
            title="Checkpoint Found",
            border_style="green"
        ))
        if Confirm.ask("Do you want to continue where you left off (Resume)?", default=True):
            resume_mode = True
            completed_trip_ids = set(checkpoint.get("completed_trips", []))
            completed_clips = checkpoint.get("completed_clips", {})
        else:
            console.print("[yellow]Previous checkpoint has been reset.[/yellow]")
            vantrue_sync.clear_checkpoint()

    # Step 4: Scan and Group Trips
    with console.status("[bold green]Scanning video files on card...[/bold green]"):
        clips = vantrue_sync.get_clips(usb_dir)
        if not clips:
            console.print("[bold red]No valid MP4 clips found in Normal/ or Event/ folders of this source.[/bold red]")
            sys.exit(1)
        trips = vantrue_sync.group_into_trips(clips, gap_seconds=65)

    # Clean completed clips list
    available_clip_names = {c['name'] for c in clips}
    if resume_mode and completed_clips:
        cleaned_completed_clips = {}
        for trip_id, clip_list in completed_clips.items():
            valid_clips = [c for c in clip_list if c in available_clip_names]
            if valid_clips:
                cleaned_completed_clips[trip_id] = valid_clips
        completed_clips = cleaned_completed_clips

    # Step 5: Select Trips
    selected_indices = select_trips_interactive(trips, completed_trip_ids, completed_clips)

    # Step 6: Advanced Sync Settings
    console.print(Panel("[bold cyan]STEP 4: Transfer Options[/bold cyan]", border_style="cyan"))
    
    mode_choice = Prompt.ask(
        "Transfer mode:\n"
        "  [1] RAM Prefetch Pipeline (Recommended: max speed, zero SSD wear)\n"
        "  [2] Direct USB -> Cloud (for systems with very low RAM)\n"
        "Choose mode",
        choices=["1", "2"],
        default="1"
    )
    mode = "ram" if mode_choice == "1" else "direct"
    
    dry_run = Confirm.ask("Run in simulation mode (Dry-Run without actual upload)?", default=False)

    # Locate GPX format file
    fmt_path = "gpx.fmt"
    if not os.path.isfile(fmt_path):
        script_dir = os.path.dirname(os.path.abspath(__file__))
        fmt_in_script_dir = os.path.join(script_dir, "gpx.fmt")
        if os.path.isfile(fmt_in_script_dir):
            fmt_path = fmt_in_script_dir

    # Summary Panel
    summary_text = (
        f"[bold]Source:[/bold] {usb_dir}\n"
        f"[bold]Destination:[/bold] {remote_dest} {'[red](LOCAL DISK)[/red]' if is_local else '[green](CLOUD RCLONE)[/green]'}\n"
        f"[bold]Selected Trips:[/bold] {len(selected_indices)} journeys\n"
        f"[bold]Transfer Mode:[/bold] {'RAM Prefetch Pipeline (Zero SSD Write)' if mode == 'ram' else 'Direct USB'}\n"
        f"[bold]Dry-Run Simulation:[/bold] {'YES' if dry_run else 'NO'}"
    )
    console.print(Panel(summary_text, title="[bold green]Sync Configuration Confirmation[/bold green]", border_style="green"))

    if not Confirm.ask("Start processing now?", default=True):
        console.print("[yellow]Synchronization canceled.[/yellow]")
        sys.exit(0)

    console.print("\n[bold green]Starting synchronization...[/bold green]\n")
    
    # Execute upload for selected trips
    for idx in selected_indices:
        trip = trips[idx - 1]
        vantrue_sync.upload_trip(
            trip=trip,
            remote_base=remote_dest,
            fmt_path=fmt_path,
            mode=mode,
            shm_dir=shm_dir,
            usb_dir=usb_dir,
            completed_trip_ids=completed_trip_ids,
            completed_clips=completed_clips,
            dry_run=dry_run
        )

    console.print(Panel(
        "[bold green]All selected trips have been successfully processed.[/bold green]\n"
        f"Destination: {remote_dest}",
        title="Success",
        border_style="green"
    ))
    vantrue_sync.clear_checkpoint()

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        console.print("\n[bold yellow]Synchronization interrupted by user.[/bold yellow]")
        sys.exit(0)
