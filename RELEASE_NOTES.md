# DoWidget 0.2.0

- Compact Refresh and Settings controls are now reload/cog icons with tooltips and accessible names.
- Compact view has a small icon-only window-control strip and drag handle, without the application name. Demo previews still identify themselves as DEMO.
- Partially translucent Compact chrome and opaque provider rows preserve readability. Edge and corner resizing remain available.
- Original DoWidget application icon for the window, notification area, and Windows executable.
- Optional **Settings → Minimize to system tray**. Tray click restores the widget; the menu provides Show widget, Refresh, Settings, and Quit. Refresh continues while hidden. If no usable tray exists, the widget falls back to normal taskbar minimization. Close still quits.
- DeepSeek balance, currency precision, Codex subscription windows, stale/error handling, credential storage, and saved view/geometry are preserved.

## Windows download

Extract the entire Windows x64 ZIP, keep its `DoWidget` directory together, and launch `DoWidget.exe`. Close the previous application and launch this version once; switching views and changing tray settings need no further restart. The portable executable is unsigned and may trigger SmartScreen. SHA256SUMS.txt accompanies the ZIP.

## Verification and limits

Windows 11 UI/tray smoke exercised real tray registration, hide/restore/menu actions, continued refresh timer, icon controls, transparency, saved setting, missing-tray fallback, and application shutdown. Regression tests use synthetic data and no account credentials. Linux Mint is intended to use the same source but has not been visually or operationally tested here; tray/transparency depend on the desktop compositor. No Linux binary is included.

Codex uses documented stable account methods over stdio; OpenAI's app-server command still has an experimental/production-support caveat. The subscription percentages are service-reported, not token-based estimates. See README.md and the official documentation links there.
