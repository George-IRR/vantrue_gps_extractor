#!/usr/bin/env python3
"""
Upload Local Folder to Cloud (High-Speed Rclone Migrator)
Optimized specifically for Google Drive API to prevent rate-limiting and freezing.
"""

import os
import sys
import argparse
import subprocess
import shutil
import time

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.prompt import Confirm
    console = Console()
except ImportError:
    class FallbackConsole:
        def print(self, *args, **kwargs):
            text = " ".join(str(a) for a in args)
            import re
            clean = re.sub(r'\[.*?\]', '', text)
            print(clean)
    console = FallbackConsole()
    def Panel(content, title="", border_style=""):
        border = "=" * 60
        return f"\n{border}\n {title}\n{border}\n{content}\n{border}\n"
    class Confirm:
        @staticmethod
        def ask(prompt, default=True):
            suffix = " [Y/n]: " if default else " [y/N]: "
            try:
                res = input(prompt + suffix).strip().lower()
                if not res:
                    return default
                return res.startswith('y')
            except (KeyboardInterrupt, EOFError):
                return False

def find_rclone():
    path = shutil.which("rclone")
    if path:
        return path
    for p in ["/usr/bin/rclone", "/usr/local/bin/rclone", "/bin/rclone", "/snap/bin/rclone"]:
        if os.path.exists(p) and os.access(p, os.X_OK):
            return p
    return None

def main():
    parser = argparse.ArgumentParser(description="High-Speed upload of local Dashcam folder to Google Drive / Cloud")
    parser.add_argument("--src", default="./Google_Drive_190", help="Local folder to upload (default: ./Google_Drive_190)")
    parser.add_argument("--dest", default="Google_Drive_190:Dashcam_Auto", help="Target cloud destination (default: Google_Drive_190:Dashcam_Auto)")
    parser.add_argument("--transfers", type=int, default=2, help="Number of parallel file transfers (default: 2)")
    parser.add_argument("--checkers", type=int, default=4, help="Number of parallel checkers (default: 4)")
    parser.add_argument("--chunk-size", default="64M", help="Drive chunk size for large videos (default: 64M)")
    parser.add_argument("--dry-run", action="store_true", help="Simulate without uploading")
    parser.add_argument("--delete-after", action="store_true", help="Move files to cloud and delete locally after upload")
    
    args = parser.parse_args()

    rclone_bin = find_rclone()
    if not rclone_bin:
        console.print("[bold red]Error: 'rclone' executable not found in PATH.[/bold red]")
        sys.exit(1)

    src_dir = os.path.abspath(args.src)
    if not os.path.isdir(src_dir):
        console.print(f"[bold red]Error: Source folder '{src_dir}' does not exist.[/bold red]")
        sys.exit(1)

    # Validate remote target has a colon
    dest = args.dest.strip()
    if ":" not in dest:
        console.print(f"[bold yellow]Warning: Destination '{dest}' does not contain ':' - appending ':' to treat as rclone remote.[/bold yellow]")
        dest = f"{dest}:"

    action_name = "move" if args.delete_after else "copy"

    console.print(Panel(
        f"[bold cyan]MIGRATE LOCAL FOLDER -> GOOGLE DRIVE[/bold cyan]\n\n"
        f"[bold]Local source:[/bold] {src_dir}\n"
        f"[bold]Cloud destination:[/bold] {dest}\n"
        f"[bold]Action mode:[/bold] {'MOVE (Delete local copy after upload)' if args.delete_after else 'COPY (Keep local copy)'}\n"
        f"[bold]Parallel transfers:[/bold] {args.transfers} simultaneous video streams\n"
        f"[bold]Optimizations:[/bold] Direct multipart for GPX/JSON, Drive chunk size {args.chunk_size}\n"
        f"[bold]Dry-run simulation:[/bold] {'YES' if args.dry_run else 'NO'}",
        title="Migration Settings",
        border_style="cyan"
    ))

    try:
        if not Confirm.ask("Start cloud upload now?", default=True):
            console.print("[yellow]Operation canceled.[/yellow]")
            sys.exit(0)
    except Exception:
        pass

    # Optimized flags for Google Drive:
    # 1. --drive-upload-cutoff 10M -> files under 10MB (gpx, json) upload instantly in 1 request
    # 2. --transfers 2 -> avoids Google API 403 Rate Limit throttling
    # 3. --drive-chunk-size 64M -> fast video uploading
    cmd = [
        rclone_bin,
        action_name,
        "--progress",
        "--transfers", str(args.transfers),
        "--checkers", str(args.checkers),
        "--drive-upload-cutoff", "10M",
        "--drive-chunk-size", args.chunk_size,
        "--drive-pacer-min-sleep", "100ms",
        "--fast-list",
        "--stats", "1s",
        src_dir,
        dest
    ]

    if args.dry_run:
        cmd.append("--dry-run")

    console.print(f"\n[bold green]Launching rclone...[/bold green]\n")
    
    t0 = time.time()
    try:
        res = subprocess.run(cmd)
        elapsed = time.time() - t0
        if res.returncode == 0:
            console.print(Panel(
                f"[bold green]Migration completed successfully.[/bold green]\n"
                f"Total time: {elapsed:.1f}s\n"
                f"Destination: {dest}",
                title="Success",
                border_style="green"
            ))
            if args.delete_after and os.path.exists(src_dir):
                try:
                    shutil.rmtree(src_dir, ignore_errors=True)
                except Exception:
                    pass
        else:
            console.print(f"[bold red]Rclone exited with error (exit code {res.returncode}).[/bold red]")
    except KeyboardInterrupt:
        console.print("\n[bold yellow]Aborted by user. You can resume at any time without losing uploaded data.[/bold yellow]")

if __name__ == "__main__":
    main()
