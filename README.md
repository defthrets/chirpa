# 🐦 Chirpa

BirdNET detection dashboard, RTSP camera setup wizard, species encyclopedia, and
real-time charts.

- **Dashboard** — hourly/daily/weekly/monthly stats with Chart.js visualizations
- **Species detail popup** — Wikidata-powered encyclopedia with stats infographics
- **Camera wizard** — guided RTSP setup for Tapo, Reolink, Hikvision, Dahua,
  Amcrest, Wyze, Kogan, and generic ONVIF cameras, with built-in help for
  finding your camera's IP and testing the stream
- **BirdNET integration** — reads from a BirdNET SQLite detection database
- **Self-contained** — Python stdlib only; no machine- or account-specific
  values are baked in, and it makes no calls to any private server

---

## ⬇️ Download

- **[⬇️ Download Chirpa (source ZIP)](https://github.com/defthrets/chirpa/archive/refs/heads/master.zip)** — works on any OS; unzip and follow the [install steps](#install) below.
- **[📦 Releases page](https://github.com/defthrets/chirpa/releases/latest)** — grab the packaged **Windows installer** (`ChirpaSetup.exe`) here once a release is published.
- **Clone instead:** `git clone https://github.com/defthrets/chirpa.git`

---

## Install

Pick your platform:

- [Windows — one-click installer](#windows-walkthrough)
- [Linux — install script](#linux-walkthrough)
- [Manual / any OS](#manual-run-any-os)

Once it's running, open **http://127.0.0.1:8090** (it opens automatically) and
go to **Settings → + Add Camera** to connect your first camera.

---

## Windows walkthrough

Chirpa ships as a **fully self-contained installer** — the target PC needs
**nothing** pre-installed (no Python, no ffmpeg, no PATH changes). Everything is
bundled into a single `ChirpaSetup.exe`.

### A. Install (for end users)

1. Get **`ChirpaSetup.exe`** (from a release, or build it — see below).
2. Double-click it and follow the wizard:
   - Choose the install location (default `C:\Program Files\Chirpa`).
   - Optionally tick **Create a desktop shortcut** and/or **Start automatically
     when I log in**.
3. Leave **Launch Chirpa now** ticked and click **Finish**.
4. Chirpa starts and opens **http://localhost:8090** in your browser.

To start it later, use the **Chirpa** shortcut in the Start Menu (or desktop).

To remove it: **Settings → Apps → Chirpa → Uninstall**. This performs a full
clean removal, including your data folder `%USERPROFILE%\.chirpa`.

### B. Build the installer (for maintainers)

On a Windows machine with **[Inno Setup 6](https://jrsoftware.org/isdl.php)**
installed:

```powershell
cd windows
powershell -ExecutionPolicy Bypass -File build.ps1
```

`build.ps1` downloads an embedded Python runtime and ffmpeg, stages them with
the app, and compiles **`windows\dist\ChirpaSetup.exe`**. Full details and
options are in [`windows/README.md`](windows/README.md).

> No build machine handy? After staging, `windows\build\staging\` is a portable
> folder — copy it anywhere and double-click **`Chirpa.cmd`**.

---

## Linux walkthrough

### A. Install with the script (recommended)

```bash
git clone https://github.com/defthrets/chirpa.git
cd chirpa
./linux/install.sh
```

The script:

1. Checks for `python3` (and warns if `ffprobe`/ffmpeg is missing — optional).
2. Installs the app to `~/.local/share/chirpa` (no root required).
3. Sets up a **systemd user service** so Chirpa starts on login and restarts on
   failure, then starts it immediately.

Open **http://127.0.0.1:8090** when it's done.

**Options:**

```bash
./linux/install.sh --no-service     # install only, don't set up systemd
./linux/install.sh --port 9000      # serve on a different port
./linux/install.sh --dir /opt/chirpa
./linux/install.sh --uninstall      # remove service + files (keeps ~/.chirpa data)
```

**Manage the service:**

```bash
systemctl --user status chirpa
systemctl --user restart chirpa
journalctl --user -u chirpa -f      # live logs
```

If you don't use systemd, run with `--no-service` and start it manually (see
below). To install ffmpeg for full RTSP verification:

```bash
sudo apt install ffmpeg     # Debian/Ubuntu
sudo dnf install ffmpeg     # Fedora
sudo pacman -S ffmpeg       # Arch
```

### B. Remote access with Tailscale (optional)

```bash
tailscale serve --bg --https=8090 http://127.0.0.1:8090
```

Then reach it at `https://<your-tailnet>.ts.net:8090`.

---

## Manual run (any OS)

Requires **Python 3.9+** (stdlib only — no `pip install` needed):

```bash
git clone https://github.com/defthrets/chirpa.git
cd chirpa
python3 birdnet_gui.py
```

`chart.min.js` is auto-staged into the data dir (`~/.chirpa`) on first launch,
and the dashboard opens in your browser. Server runs on `http://127.0.0.1:8090`.

---

## Configuration

Everything is per-user and overridable via the environment — nothing is
hardcoded to a specific machine, account, or location:

| Variable | Default | Effect |
|----------|---------|--------|
| `CHIRPA_HOST` / `CHIRPA_PORT` | `127.0.0.1` / `8090` | Bind address / port |
| `CHIRPA_HOME` | `~/.chirpa` | Data directory (camera config, images, species DB) |
| `CHIRPA_LISTENER_DB` | `~/.birdnet-listener/detections.db` | BirdNET detection database to read |
| `CHIRPA_UTC_OFFSET` | _system timezone_ | Force a fixed UTC offset in hours |
| `CHIRPA_GEOLOOKUP` | _unset_ | `1` enables optional IP geolocation (off by default — no outbound calls) |
| `CHIRPA_NO_BROWSER` | _unset_ | `1` disables auto-opening the browser |

Times are shown in the machine's local timezone, and the BirdNET latitude/
longitude are set by each user in **Settings**.

> **Upgrading?** On first launch Chirpa automatically moves a legacy
> `~/.skyrats` data folder to `~/.chirpa`, so your cameras, images, and species
> DB carry over with no manual steps.

---

## Camera setup wizard

**Settings → + Add Camera** walks you through connecting an RTSP camera:

- **Finding your camera's IP address** — via your router's admin page, the
  manufacturer's app, or a network scan (`arp -a`, Advanced IP Scanner, Fing,
  ONVIF Device Manager).
- **Building & testing the RTSP URL** — per-brand stream paths plus a universal
  walkthrough and VLC test instructions.
- **Connection testing** — the wizard pings the camera, checks port 554, and
  (when `ffprobe` is available) probes the RTSP handshake before saving.

---

## Architecture

```
birdnet_gui.py          — Single-file Python HTTP server
  /                    — Dashboard (tables, charts, species cards)
  /api/species         — JSON species list from species.db
  /api/stats           — Aggregated detection stats
  /api/bird-detail     — Species detail with Wikidata enrichment
  /api/camera-config   — Camera CRUD
  /api/recent          — Recent detections with pagination
  /api/test-connection — Camera reachability + RTSP probe
  /chart-js            — Serves chart.min.js
  /img/<filename>      — Serves <data-dir>/images/*

windows/                — Self-contained Windows installer (Inno Setup + build.ps1)
linux/install.sh        — Linux installer + systemd user service
```

## Data

Depends on BirdNET's SQLite schema:

- `detections` table — species, confidence, timestamp, source (camera)

Species images and stats SVGs are sourced from the data directory's `images/`
folder (default `~/.chirpa/images/`).
