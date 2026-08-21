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
        console.print("[bold red]Eroare: 'rclone' nu a fost găsit în sistem.[/bold red]")
        sys.exit(1)

    src_dir = os.path.abspath(args.src)
    if not os.path.isdir(src_dir):
        console.print(f"[bold red]Eroare: Folderul sursă '{src_dir}' nu există.[/bold red]")
        sys.exit(1)

    # Validate remote target has a colon
    dest = args.dest.strip()
    if ":" not in dest:
        console.print(f"[bold red]Avertisment: Destinația '{dest}' nu conține ':' - va fi tratată ca destinație rclone remote '{dest}:'[/bold red]")
        dest = f"{dest}:"

    action_name = "move" if args.delete_after else "copy"

    console.print(Panel(
        f"[bold cyan]MIGRARE FOLDER LOCAL -> GOOGLE DRIVE[/bold cyan]\n\n"
        f"[bold]Sursă locală:[/bold] {src_dir}\n"
        f"[bold]Destinație Cloud:[/bold] {dest}\n"
        f"[bold]Mod acțiune:[/bold] {'MUTARE (Șterge local după upload)' if args.delete_after else 'COPIERE (Păstrează copia locală)'}\n"
        f"[bold]Transferuri paralele:[/bold] {args.transfers} fluxuri video simultane\n"
        f"[bold]Optimizări:[/bold] Multipart direct pentru GPX/JSON, Drive Chunk 64M pentru video\n"
        f"[bold]Simulare (Dry-Run):[/bold] {'DA' if args.dry_run else 'NU'}",
        title="Configurație Migrare",
        border_style="cyan"
    ))

    try:
        if not Confirm.ask("Doriți să porniți încărcarea în Cloud acum?", default=True):
            console.print("[yellow]Operațiune anulată.[/yellow]")
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

    console.print(f"\n[bold green]🚀 Se lansează rclone optimizat pentru Google Drive...[/bold green]\n")
    
    t0 = time.time()
    try:
        res = subprocess.run(cmd)
        elapsed = time.time() - t0
        if res.returncode == 0:
            console.print(Panel(
                f"[bold green]✓ Migrarea s-a finalizat cu succes![/bold green]\n"
                f"Timp total: {elapsed:.1f} secunde\n"
                f"Destinație: {dest}",
                title="Succes",
                border_style="green"
            ))
            if args.delete_after and os.path.exists(src_dir):
                try:
                    shutil.rmtree(src_dir, ignore_errors=True)
                except Exception:
                    pass
        else:
            console.print(f"[bold red]❌ Rclone a întâmpinat o eroare (exit code {res.returncode}).[/bold red]")
    except KeyboardInterrupt:
        console.print("\n[bold yellow]Întrerupt de utilizator. Puteți relua oricând aceeași comandă fără a pierde datele deja urcate.[/bold yellow]")

if __name__ == "__main__":
    main()
