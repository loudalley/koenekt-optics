# Koenekt Optics

Koenekt video tools. One folder, shared codec layer, separate products.

| Path | What | Licence |
|---|---|---|
| `shared/koenekt_codecs/` | GREC parser + FFmpeg pipeline, shared by all apps | MIT |
| `apps/grec_converter/` | **Koenekt GREC Converter**: Windows app, GREC → MP4 / AVI | MIT (for now) |
| `brand/` | Logo and icon, copied from Koenekt Reporter | Koenekt |
| `apps/onvif_screens/` | Koenekt ONVIF Screens (licensed). A **separate private repo** nested here and git-ignored by this one; not public. | proprietary |

## GREC Converter

Drop folders or `.grec` files onto the window, tick the ones you want (or *Select all*), choose MP4 or AVI and an output folder, then press **Convert**.

- Originals are only read. Existing outputs are never overwritten.
- If one file fails, the batch carries on. Cancel cleans up the file that is in progress.
- **MP4** (H.264/AAC) keeps the recording's variable frame timing.
- **AVI** (Xvid-compatible MPEG-4 + MP3) is constant 25 fps, for older players. Files are about twice the size.
- Every output file is fully decoded and checked before it gets its final name.
- If a recording has no end index or ends mid-packet, it is converted up to that point and flagged with a warning.
- Settings, logs and JSON reports are saved to `%LOCALAPPDATA%\Koenekt\GREC Converter`.

### Develop

```powershell
py -3.14 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python apps\grec_converter\main.py      # run from source
.venv\Scripts\python -m pytest tests                  # parser tests
```

### Build the MSI

```powershell
powershell -ExecutionPolicy Bypass -File apps\grec_converter\build.ps1
```

Output: `apps\grec_converter\dist\KoenektGrecConverter-<version>-win64.msi`. The MSI bundles Python, Tcl/Tk + tkdnd, PyAV, Pillow and FFmpeg, so the target PC needs nothing pre-installed. It installs per machine to `Program Files\Koenekt\GREC Converter` and adds a Start-menu and a desktop shortcut. To release an update, bump `VERSION` in `apps/grec_converter/grec_converter/__init__.py`. Never change `UPGRADE_CODE`.

Scripted check of a build: `GrecConverter.exe --convert FILE --out DIR --format mp4 --report out.json`

### Format support (inferred, not a vendor spec)

The parser supports the SureCam/CMSV6 variant seen so far: H.265 video and G.711 A-law audio at 8 kHz. See the docstring in `shared/koenekt_codecs/grec.py`. Unknown headers, markers or codecs are rejected with a message. Nothing is guessed.

### Licensing

The source code is [MIT](LICENSE). The Koenekt name, logo and icons in `brand/` are Koenekt trademarks and are **not** covered by the MIT licence. If you fork this, use your own branding.

The bundled FFmpeg is a GPLv3 build (libx264, libxvid). It runs as a separate executable and is not linked. See `apps/grec_converter/THIRD-PARTY-NOTICES.txt`. Before the paid version, confirm GPL source-offer obligations for the shipped binary, or swap in an LGPL build plus a licensed H.264 encoder.
