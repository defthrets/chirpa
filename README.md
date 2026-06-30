# 🐦 Chirpa

BirdNET detection dashboard, RTSP camera wizard, species encyclopedia, and real-time charts.

## Features

- **Dashboard** — hourly/daily/weekly/monthly stats with Chart.js visualizations
- **Species detail popup** — Wikidata-powered encyclopedia with stats infographics
- **Camera management** — RTSP wizard for Tapo, Reolink, Hikvision, and generic cameras
- **BirdNET integration** — reads from BirdNET SQLite detection database

## Requirements

- Python 3.9+
- No pip packages required (stdlib only)
- Chart.js served locally (`chart.min.js`) — included in this repo
- `ffprobe` (from ffmpeg) on `PATH` or bundled — *optional*; enables RTSP stream
  verification in the camera wizard. Without it the wizard still works (it
  validates host + port 554).
- Running BirdNET instance with `~/.skyrats/species.db` populated
- Species images in `~/.skyrats/images/`

> **Windows users:** you don't need to install anything manually. Use the
> self-contained installer in [`windows/`](windows/README.md) — it bundles
> Python and ffmpeg into a one-click `ChirpaSetup.exe`.

## Windows (one-click installer)

A fully self-contained Windows installer is built from [`windows/`](windows/README.md):

```powershell
cd windows
powershell -ExecutionPolicy Bypass -File build.ps1
```

This produces `windows/dist/ChirpaSetup.exe`, which bundles a private Python
runtime + ffmpeg so the app runs on a clean machine with nothing pre-installed.
See [`windows/README.md`](windows/README.md) for details.

## Camera setup wizard

The **Settings → + Add Camera** wizard walks you through connecting an RTSP
camera, with built-in walkthroughs for:

- **Finding your camera's IP address** — via your router's admin page, the
  manufacturer's app, or a network scan (`arp -a`, Advanced IP Scanner, Fing,
  ONVIF Device Manager).
- **Building & testing the RTSP URL** — per-brand stream paths (Tapo, Reolink,
  Hikvision, Dahua, Amcrest, Wyze, Kogan, generic ONVIF) plus a universal
  walkthrough and VLC test instructions.
- **Connection testing** — the wizard pings the camera, checks port 554, and
  (when `ffprobe` is available) probes the RTSP handshake before saving.

## Quick Start

```bash
# Clone
git clone https://github.com/defthrets/chirpa.git
cd chirpa

# Place chart.min.js where the server expects it
mkdir -p ~/.skyrats
cp chart.min.js ~/.skyrats/

# Run
python3 birdnet_gui.py
```

Server runs on `http://127.0.0.1:8090`.

## Tailscale Serve (recommended for remote access)

```bash
tailscale serve --bg --https=8090 http://127.0.0.1:8090
```

Then access via `https://<your-tailnet>.ts.net:8090`.

## Systemd Service

```bash
mkdir -p ~/.config/systemd/user
cp birdnet-gui.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now birdnet-gui
```

## Architecture

```
birdnet_gui.py          — Single-file Python HTTP server
  /                    — Dashboard (tables, charts, species cards)
  /api/species         — JSON species list from species.db
  /api/stats           — Aggregated detection stats
  /api/bird-detail     — Species detail with Wikidata enrichment
  /api/camera-config   — Camera CRUD
  /api/recent          — Recent detections with pagination
  /chart-js            — Serves chart.min.js
  /img/<filename>      — Serves ~/.skyrats/images/*
```

## Data

Depends on BirdNET's SQLite schema:
- `detections` table — species, confidence, timestamp, camera

Species images and stats SVGs are sourced from `~/.skyrats/images/`.
