# Vantrue GPS Extractor & Cloud Sync

A command-line tool and interactive terminal interface for organizing, extracting GPS tracks (GPX), generating journey manifests, and syncing Vantrue dashcam footage to cloud storage via `rclone`.

Tested and verified on **Vantrue Element 1 (Vantrue E1)**. Compatible with other Vantrue dashcams (E2, E3, N2 Pro, N4, N5, Nexus series) sharing the same timestamp naming convention and embedded Novatek GPS telemetry streams.

## Features

- **RAM Pipeline (Zero SSD Wear)**: Stages clips and extracts metadata in memory (`/dev/shm`) before upload, eliminating intermediate writes to local disk drives.
- **Prefetching**: Reads and parses the next clip from the SD card in a background worker while the current clip uploads.
- **Checkpointing & Resume**: Tracks completed uploads per trip; interrupted sessions resume from the last completed file.
- **Trip Grouping**: Automatically groups individual 1-minute dashcam segments into continuous journeys based on timestamp gaps.
- **Interactive TUI**: Terminal UI for selecting connected media devices, destination remotes, and specific trips to sync.

---

## Google Drive Setup (Custom Client ID)

By default, `rclone` uses a shared Google API client ID. Under heavy usage or multi-file uploads, Google's global query rate limits can trigger `HTTP 403 Rate Limit Exceeded` responses, causing significant delays between uploads. Creating a personal OAuth client ID avoids these shared limits.

### 1. Enable the Google Drive API
1. Open the [Google Cloud Console](https://console.cloud.google.com/).
2. Create or select a project.
3. Navigate to **APIs & Services** -> **Enabled APIs & Services**.
4. Click **+ Enable APIs and Services**, search for **Google Drive API**, and enable it.

### 2. Configure OAuth Consent Screen & Test Users
1. Go to **APIs & Services** -> **OAuth consent screen** (or **Google Auth Platform** -> **Audience** in newer console layouts).
2. Select **External** and fill in the required application name and support email.
3. Under the **Test users** section (or **Audience** -> **Test users**):
   - Add your Google account email address.
   - Save the configuration.

### 3. Create Desktop Credentials
1. Navigate to **APIs & Services** -> **Credentials**.
2. Click **Create Credentials** -> **OAuth client ID**.
3. Select **Desktop app** as the application type.
4. Save and copy the generated **Client ID** and **Client Secret**.

### 4. Configure Rclone
Run the configuration wizard:
```bash
rclone config
```
- Edit an existing Google Drive remote or create a new one of type `drive`.
- Enter your custom `client_id` and `client_secret` when prompted.
- Set scope to `1` (full access).
- Complete the authentication flow in your web browser.

---

## Requirements

- Python 3.8+
- `rclone`
- `exiftool`
- Python packages: `rich`, `psutil`

```bash
pip install -r requirements.txt  # or: pip install rich psutil
```

---

## Usage

### Interactive Mode (TUI)
Running the script without arguments or with `--tui` launches the guided interface:
```bash
python vantrue_sync.py
```

### CLI Direct Mode
```bash
python vantrue_sync.py \
  --usb-dir /path/to/sdcard \
  --remote Google_Drive:Dashcam_Auto \
  --mode ram \
  --resume
```

### Options

| Flag | Description | Default |
|---|---|---|
| `--usb-dir` | Path to mounted SD card root (containing `Normal/` and `Event/`) | Required in CLI mode |
| `--remote` | Destination rclone remote (e.g. `remote:path`) | Required in CLI mode |
| `--mode` | Transfer pipeline: `ram` (memory-buffered) or `direct` | `ram` |
| `--gap` | Maximum timestamp gap in seconds between clips in a trip | `65` |
| `--fmt` | Path to ExifTool GPX format definition file | `gpx.fmt` |
| `--resume` | Resume previous sync session using checkpoint data | `False` |
| `--dry-run` | Simulate operations without uploading files | `False` |
| `--allow-local-dest` | Permit target path on local filesystem instead of remote | `False` |
| `--tui` | Force interactive terminal user interface | Auto when no args |

---

## Utilities

- `merge_trips.py`: Combines video segments of selected trips locally using `ffmpeg`.
- `upload_local_folder.py`: Uploads an existing local folder of organized trips to Google Drive with optimized transfer parameters.
