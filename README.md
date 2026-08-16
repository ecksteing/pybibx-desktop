# PyBibX Desktop

An easy way to run [pybibx](https://github.com/Valdecy/pybibx) on Windows. ➡️ [Install PyBibX Desktop](https://github.com/ecksteing/pybibx-desktop/releases) and run. No separate Python install needed.

> **Platform note:** The current release targets **Windows**. macOS and Linux versions are planned for later.

## Why this tool?

pybibx is excellent for bibliometric and scientometric analysis (including a browser-based Web App), but installing Python and dependencies is a hurdle for students. This project ships a one-click wrapper: install, then run.

## Installation (end users)

1. [Download the latest release](https://github.com/ecksteing/pybibx-desktop/releases).
2. Install.
4. Start **PyBibX Desktop** from the Start Menu or desktop shortcut. The pybibx Web App opens in your browser.

Logs (if something goes wrong) are written to `%LOCALAPPDATA%\PyBibX Desktop\launcher.log` (and `bootstrap.log` / `runtime.log` in the same folder).

### If Windows blocks the installer

Windows SmartScreen (and some browsers or antivirus tools) may warn that the app is from an “unknown publisher.” That is common for new, unsigned open-source installers and does **not** mean the file is malware.

**SmartScreen (“Windows protected your PC”):**

1. Click **More info**.
2. Click **Run anyway**.

**Microsoft Edge / Chrome download warning:**

1. Open the browser’s downloads list.
2. Choose **Keep** / **Keep anyway** (Edge may ask you to confirm under the **...** menu).

Only install builds downloaded from the official [GitHub Releases](https://github.com/ecksteing/pybibx-desktop/releases) page for this project. If your organisation’s antivirus still blocks the file, ask IT to allowlist it, or open a [GitHub Issue](https://github.com/ecksteing/pybibx-desktop/issues).

## FAQ

#### Do I need to install Python?

No. Just download and run the app.

#### Do I get the same features as pybibx?

Yes. This app launches the official pybibx Web App (`pybibx.web_app()`).

#### The app is slow to open after install?

First launch installs **core** libraries first so the web UI can open sooner, then downloads heavy AI wheels (PyTorch, transformers, BERTopic, …) **in the background**. Basic bibliometric tools work once the UI opens; AI features (topic modelling, embeddings, LLM helpers) become available after that background install finishes (progress is logged in `%LOCALAPPDATA%\PyBibX Desktop\runtime.log`). Later launches are much faster once packages are cached.

#### Is the latest version of pybibx included?

Each desktop release ships with a pybibx. When online, the app checks for a newer version weekly. If you are offline, the already-installed copy still runs.

#### Why did you create this tool?

I am a university lecturer. I encourage students to use bibliometric tools for literature analysis and wanted a one-click option, similar to [Bibliometrix Desktop](https://github.com/ecksteing/bibliometrix-desktop).

## Licence

This project is distributed under the [GNU GPL v3](LICENSE). pybibx and its dependencies retain their own licences; see upstream projects for details.

## Support

- Installer / desktop wrapper: [GitHub Issues](https://github.com/ecksteing/pybibx-desktop/issues)
- pybibx itself: contact the pybibx authors / [upstream repo](https://github.com/Valdecy/pybibx)

## Acknowledgements

- [pybibx](https://github.com/Valdecy/pybibx) by Valdecy Pereira and colleagues
- App icon adapted from Google Material Symbols **book_ribbon** (Apache 2.0)

## Building from source (maintainers)

End users can ignore this section.

### Prerequisites

- Windows x64
- [Python 3](https://www.python.org/) + `pip install -r requirements-build.txt` (host machine; used only to package the launcher)
- [Inno Setup 7+](https://jrsoftware.org/isinfo.php) (per-user or machine-wide install; 6+ also works)
- Internet access to download the embeddable Python runtime (and, when testing install, the AI wheels)

### One-shot Windows build

From the repo root:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_windows.ps1
```

This will:

1. Download / prepare a lean `Python-Portable\` (embeddable CPython + pip)
2. Compile the onedir launcher with PyInstaller (`--onedir --noconsole`) and stage `run_pybibx.exe` + `_internal\` at the repo root
3. Compile `installer_config.iss` into `Output\PyBibXSetup_<version>.exe`

Useful flags:

- `-SkipPreparePython` — skip embeddable Python download (only if already prepared)
- `-SkipInstaller` — build the launcher exe only

### Manual steps (equivalent)

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\prepare_python_portable.ps1
pip install -r requirements-build.txt
pyinstaller --onedir --noconsole --icon=app_icon.ico --name run_pybibx run_pybibx.py
# Copy dist\run_pybibx\run_pybibx.exe and dist\run_pybibx\_internal to the repo root,
# then compile installer_config.iss in Inno Setup
```

Optional full offline bake (makes the installer much larger):

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\bootstrap_runtime.ps1
```

Bump `version.txt` before each release. Publish **only** the setup exe on GitHub Releases (not the whole `Python-Portable` tree).
