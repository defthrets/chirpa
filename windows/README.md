# Chirpa for Windows — self-contained installer

This folder builds **`ChirpaSetup.exe`**, a fully enclosed Windows installer.
The resulting setup bundles *everything* Chirpa needs, so the target PC needs
**nothing pre-installed** — no Python, no pip, no ffmpeg, no PATH changes.

## What gets bundled

| Component | Why it's included |
|-----------|-------------------|
| **Embedded Python** (private runtime) | Runs `birdnet_gui.py` without any system Python |
| **ffmpeg / ffprobe** | Powers the camera wizard's RTSP stream verification |
| **`birdnet_gui.py` + `chart.min.js`** | The Chirpa app and its charting asset |
| **`Chirpa.cmd` launcher** | Starts the server and opens the dashboard in the browser |

The app discovers the bundled `ffprobe.exe` automatically (it looks in
`ffmpeg\bin\` next to itself), so the **Test Connection** step in the camera
wizard fully validates RTSP streams on a clean machine.

## Build the installer

**On a Windows build machine** (the only place that needs tooling):

1. Install **Inno Setup 6** — <https://jrsoftware.org/isdl.php>.
2. From this `windows\` folder, run:

   ```powershell
   powershell -ExecutionPolicy Bypass -File build.ps1
   ```

   The script downloads the Python embeddable package and an ffmpeg build,
   stages them with the app, and compiles the installer.

3. The finished installer lands in **`windows\dist\ChirpaSetup.exe`**.

### Options

```powershell
# Pin a specific Python, or point at an Inno Setup install:
powershell -ExecutionPolicy Bypass -File build.ps1 -PythonVersion 3.11.9 -IsccPath "C:\Inno\ISCC.exe"
```

If Inno Setup isn't found, the script still stages a ready-to-zip app folder at
`windows\build\staging\` and tells you where it is.

## What the installer does

- Installs to `C:\Program Files\Chirpa` (per-machine) or your user folder.
- Creates a **Start Menu** shortcut (and optional **Desktop** / **run-at-login**
  shortcuts).
- Optionally launches Chirpa at the end of setup.
- Chirpa serves the dashboard at <http://localhost:8090> and opens your default
  browser automatically.

Your camera configuration lives in `%USERPROFILE%\.skyrats\cameras.json` and is
**kept** on uninstall.

## Running without the installer (portable)

After `build.ps1` stages the app, `windows\build\staging\` is a portable folder.
Copy it anywhere and double-click **`Chirpa.cmd`** — it runs entirely from that
folder using the bundled Python.

## Configuration

Environment variables (optional):

| Variable | Default | Effect |
|----------|---------|--------|
| `CHIRPA_HOST` | `127.0.0.1` | Bind address |
| `CHIRPA_PORT` | `8090` | Port |
| `CHIRPA_NO_BROWSER` | _unset_ | Set to `1` to not auto-open the browser |
