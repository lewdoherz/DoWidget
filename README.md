# DoWidget

A small floating desktop window showing **DeepSeek API balance** and, after a separate ChatGPT sign-in, **Codex subscription allowance**. Python + PySide6 Qt Widgets keeps the architecture native and small: two provider adapters, a refresh-state object, credential/preferences storage, and the desktop UI. No web frontend or local HTTP server.

**Desktop assumption:** this is a draggable standalone floating window, not an integration into the Windows Widgets board. Windows Widgets board integration would be a separate requirement.

## What it displays

- **DeepSeek:** real `GET https://api.deepseek.com/user/balance`, authenticated with your API key. Every returned CNY/USD balance is displayed in its original currency, using `Decimal` and the original decimal precision. No conversion, rounding to cents, or float arithmetic. Includes total, granted, and topped-up balances, and the service's availability flag.
- **Codex subscription allowance:** the official Codex app-server's documented `account/rateLimits/read` API through its local stdio interface. Shows Codex buckets and each primary/secondary usage window separately, with the source's reset times. Remaining percentage is `100 - usedPercent`, clamped to 0–100. Missing/invalid usage stays **unknown**, not 0% or 100%.
- **General ChatGPT message allowances and OpenAI API billing are not displayed.** An ordinary OpenAI API key does not grant subscription-quota access. Pricing estimates, token counts, and request-per-minute limits are never used as substitute subscription percentages. The current OpenAI pricing documentation describes shared usage with ChatGPT Work, but this widget labels the source as Codex rather than claiming to show every ChatGPT limit.

### Why the Codex heading no longer says “preview”

The old `Codex · subscription (preview)` heading described this application's dependency on the experimental **app-server command**, not a subscription plan or an estimated percentage. The heading is now **Codex · subscription**; the integration caveat stays in settings and here.

The [current official app-server documentation](https://learn.chatgpt.com/docs/app-server) says “The app-server command and WebSocket transport are experimental and aren't supported for production workloads.” It separately documents stdio as a supported transport and a stable API surface when `experimentalApi` is omitted. DoWidget uses that stdio/stable account surface; it does not use WebSocket, remote Code Mode hosting, or experimental API opt-in. **Practical consequence:** OpenAI does not guarantee production support for the command dependency; CLI/protocol changes can require a DoWidget update. This is not evidence that the subscription is in preview or that the percentages are estimates: they come from the service's reported `usedPercent`.

The integration remains optional. If the CLI, authentication, account entitlement, or quota response is unavailable, the card explains the setup/failure state and DeepSeek continues independently. You can also inspect usage in the [official Codex dashboard](https://chatgpt.com/codex/settings/usage) or use `/status` in Codex; DoWidget does not scrape either.

## Windows 11 setup and launch

Install a 64-bit [Python](https://www.python.org/downloads/) **3.11 or newer**. Open PowerShell in this project directory:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m dowidget.app
```

For a clearly labeled offline preview:

```powershell
.\.venv\Scripts\python.exe -m dowidget.app --demo
```

Demo mode does not read account credentials, make provider requests, start Codex, or save changes to preferences. All example balances and allowances are synthetic and labeled DEMO on the cards and window.

## Linux Mint setup and launch

The same Python application is intended for Linux Mint; **Mint has not been tested**. Mint 22's Python 3.12 is suitable. Older Mint installations need Python 3.11+ and a compatible Qt wheel. On Mint 22, in a normal graphical desktop session:

```bash
sudo apt update
sudo apt install python3-venv libgl1 libegl1 libxkbcommon-x11-0 \
  libxcb-cursor0 libxcb-icccm4 libxcb-keysyms1 libxcb-shape0 \
  libxcb-xinerama0 libxcb-render-util0 libxcb-xkb1 gnome-keyring
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m dowidget.app
# Offline preview:
.venv/bin/python -m dowidget.app --demo
```

Linux secure storage requires an unlocked Secret Service keyring and a working session D-Bus (normally supplied by Cinnamon/GNOME Keyring). If unavailable, settings offer session-only credentials. Do not run the GUI with `sudo`. The compositor may restrict programmatic saved positions or always-on-top, particularly on Wayland; Mint's X11 desktop is the practical initial target. Qt's system-move API is used for dragging, with a fallback when available.

## Connect accounts through settings

### DeepSeek

1. Obtain your own key from [DeepSeek's API key page](https://platform.deepseek.com/api_keys).
2. Open **Settings**, enter it in the masked DeepSeek key field, and choose **Connect / replace key**.
3. Leave **Remember in operating system credential store** checked for secure persistence, or uncheck it for this session only. Replacing with session-only credentials first removes any previously saved DoWidget DeepSeek key; removal failure is reported rather than silently claiming it was deleted.
4. **Disconnect DeepSeek** removes both the saved credential and the session credential. If the OS refuses deletion, the error is shown and the account is not falsely reported as disconnected.

Missing/invalid keys show setup required; service/network errors show their connection state. A failed refresh after a success preserves the prior balance and timestamp and visibly marks it **Stale**. Account values are not cached to disk.

### Codex

1. Install the [official Codex CLI](https://learn.chatgpt.com/docs/cli), with `codex` on your desktop process's PATH. The documented npm option (requires Node.js/npm) works on Windows and Linux:

   ```bash
   npm install -g @openai/codex
   ```

   Restart DoWidget after installation so it receives the updated PATH. OpenAI also documents native installers.
2. Open **Settings → Sign in with ChatGPT** and complete the official browser flow. A ChatGPT account with a Codex entitlement and returned quota windows is required; an API key is not accepted as subscription authentication.
3. **Remember Codex sign-in in OS credential store** uses Codex's `cli_auth_credentials_store="keyring"`, never its plaintext fallback. Uncheck it for `"ephemeral"`: the sign-in remains only in DoWidget's running Codex process and expires on exit. If secure sign-in storage fails, explicitly select the session-only option and retry. Switching modes first logs out the previous mode; a failed logout stops the switch.
4. **Disconnect Codex** uses the documented account logout operation for DoWidget's isolated session. It does not log you out of another Codex installation.

DoWidget supplies its own application-data `CODEX_HOME`; it never reads another application's `auth.json`, imports access tokens, or copies browser cookies. Codex itself owns the OAuth flow, secure token storage, and refresh. DoWidget strips inherited provider-key/token environment variables before starting its server. The backend uses account initialization/read/login/logout/quota methods only: **no threads, turns, model-generation calls, or quota-consuming probes**.

If the CLI is missing, install it. If no ChatGPT sign-in exists, sign in in settings. If the account has no returned Codex quota, DoWidget cannot manufacture an allowance. General ChatGPT message limits remain unavailable because the documented source used here does not expose them.

## Widget behavior

- Drag any **edge or corner** to resize; drag the header/Compact drag handle to move. Qt's native sizing is preferred, with captured Qt geometry drags when unavailable. Nearly transparent resize margins remain hit-testable on Windows. Position and size are saved after a short move/resize debounce, on view switches, and on close. Off-screen saved positions and oversized saved dimensions are recovered against available screens.
- Click **Compact** in Detailed view to switch; the **expand arrows** icon in Compact returns to Detailed. Switching is immediate—no restart. Compact uses a small 20-pixel control strip with a drag handle, expand, minimize, and close icons, without the application's name; demo mode retains its DEMO label. The selected view and each view's own size are remembered between launches. Existing settings migrate without losing provider connections.
- Detailed view defaults to 380 × 560 (minimum 340 × 280); Compact view defaults to 320 × 190 (minimum 260 × 130), in Qt logical pixels. Cards wrap and scroll when needed; refresh/settings and header window controls stay outside the scrolling area and remain accessible at the minimum sizes.
- Compact rows show the provider logo beside exact-currency balance values or **separately labeled Codex windows** (for example, `5h` and `Week` when those durations are supplied). They use the same account snapshots as Detailed view, not example balances. Unknown windows display **Unknown**; missing account data displays a dash.
- Compact indicators: green dot = connected, `?` = setup required, `!` = stale/error, circular arrow = updating, `D` = demo. Hover a row/indicator for connection/error details, balance breakdown, reset times, and last successful update, or switch to Detailed. Failed refreshes retain the previous value as stale, including during a retry.
- Compact **Refresh** and **Settings** are reload/cog icons below the cards, with tooltips and accessible names. Detailed view retains labeled buttons. Compact chrome is partially translucent, while provider rows remain opaque for readable account values; nearly transparent resize margins stay hit-testable. Transparency depends on the desktop compositor.
- Optional **Settings → Minimize to system tray → Save behavior** (off by default). Minimize hides to the tray only when a usable native tray is available. Click the tray icon to restore; its menu has **Show widget, Refresh, Settings, Quit**. Provider timers continue while hidden. Disabling the option or losing the tray restores a hidden window; without a tray, minimize falls back to the taskbar. **Close/× always quits**, rather than silently hiding the app.
- Optional **Always on top** remains in settings. This is still a floating desktop window, not Windows Widgets board integration.
- **Refresh** requests fresh data manually. Settings control automatic refresh and the interval (1–1,440 minutes), defaulting to **five minutes**.
- Provider work runs in separate single-worker queues so the UI stays responsive and one provider cannot block the other. Per-provider state prevents overlapping refreshes.
- Failures trigger exponential backoff, capped at one hour, with bounded `Retry-After` handling. Manual refresh also respects the failure cooldown. Success resets backoff. Reconnecting resets that provider's configuration/state.
- DeepSeek has connect/read timeouts of 4/10 seconds, a 256 KiB response bound, no redirects, and a 20-second stream deadline (an outstanding socket read can add up to about 10 seconds). Codex RPC calls time out after 20 seconds each; browser sign-in waits at most three minutes. A dead Codex transport is recreated on the next refresh; ephemeral sessions then need a new sign-in.
- All supplied reset times and last-success timestamps are displayed in your local time with a numeric UTC offset. Scroll the cards if multiple currencies/windows exceed the compact window.

Preferences live in Qt's platform application-data location as `settings.json`; the adjacent `codex` directory is DoWidget's isolated Codex home. Preferences contain only window position, per-view sizes, selected view, refresh behavior, topmost, minimize-to-tray, and the nonsecret Codex-enabled flag. DeepSeek secrets are stored under `DoWidget.DeepSeek` in Windows Credential Manager or Linux Secret Service, not in settings. Raw provider bodies, keys, auth URLs, and upstream error text are not logged or shown in errors.

### Provider logos

Compact view packages the authentic DeepSeek whale from the [official DeepSeek favicon](https://www.deepseek.com/favicon.ico) and the official OpenAI Blossom from the [OpenAI brand page](https://openai.com/brand/)'s apple-touch icon. Original geometry, colors, padding, and backgrounds are retained, with aspect-preserving downscaling and neutral logo tiles. No network download is needed at runtime. Exact URLs, conversion details, trademark attribution, and usage terms are in [`dowidget/assets/SOURCES.md`](dowidget/assets/SOURCES.md). These identify the services; neither provider endorses DoWidget.

DoWidget also has its **own original D/gauge icon**, separate from provider branding, for the window, system tray, and Windows executable. PNG, multi-size ICO, and editable SVG sources are locally packaged; their provenance is in the same asset notice.

## Packaging

Build on each target OS; PyInstaller does not cross-compile. The **entire** output directory must be distributed, not just the executable. These are portable directory builds, not signed installers.

### Windows 11

```powershell
.\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --windowed --onedir --name DoWidget --distpath dist/v0.2.0 --collect-data dowidget --icon dowidget/assets/dowidget.ico --hidden-import keyring.backends.Windows run_widget.py
.\dist\v0.2.0\DoWidget\DoWidget.exe
# Preview:
.\dist\v0.2.0\DoWidget\DoWidget.exe --demo
```

The updated application is `dist/v0.2.0/DoWidget/DoWidget.exe`, with dependencies in that directory. A complete portable release ZIP and SHA-256 checksum are prepared under `dist/v0.2.0`. The separate output avoids overwriting files held open by the existing running application, which was left untouched. Close the old window and launch this updated executable once to load the changes; switching views or enabling tray minimization afterward needs no restart. Keep the complete application directory together. Unsigned builds may trigger Windows SmartScreen. Codex is optional and remains a separate installation, not bundled with the widget.

### Linux Mint

```bash
.venv/bin/python -m PyInstaller --noconfirm --clean --windowed --onedir \
  --name DoWidget --collect-data dowidget --hidden-import keyring.backends.SecretService run_widget.py
./dist/DoWidget/DoWidget
```

Package/build on the oldest Mint version you intend to support; Qt's system libraries and glibc compatibility still matter. Keep the `dist/DoWidget` directory together. You can add a desktop launcher pointing to its absolute executable path. Linux packaging is documented but **not verified**.

Linux tray support needs a notification-area/StatusNotifier/XEmbed implementation; transparent chrome needs a compositing desktop. If a tray is absent or disappears, DoWidget keeps an ordinary route back to the window. These Linux behaviors are implemented through Qt but not verified on Mint.

Qt is distributed under its applicable LGPL/GPL/commercial license. Review [Qt for Python licensing](https://doc.qt.io/qtforpython-6/licenses.html) and include applicable notices when distributing binaries.

## Checks and verification

```powershell
# Windows
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m compileall -q dowidget run_widget.py
```

```bash
# Linux
.venv/bin/python -m pytest -q
.venv/bin/python -m compileall -q dowidget run_widget.py
```

The regression suite uses synthetic/mocked provider responses and isolated credential backends. It covers exact balance parsing/currency preservation, malformed/missing data, percentage inputs and clamping, independent windows and resets, authentication/network/service/rate-limit failures, redaction, body bounds, stale retention/recovery, overlap/backoff, secure-storage failure/disconnect, preferences, and Codex process/protocol failure recovery. Additional update tests cover all resize directions and anchored minimum/maximum bounds, old-settings migration, both views' dimensions/selection, compact multi-currency precision, independently labeled windows, missing usage, stale/error indicators, and escaped tooltip labels. Test temporary directories use ordinary isolated folders rather than pytest's symlinks, which this Windows environment rejects under its untrusted-symlink policy.

Verified on **Windows 11 Pro x64 (build 26200), Python 3.14.7**:

- 355 regression tests pass; Python compilation passes; `pip check` reports no broken requirements.
- Updated native widget/settings shown and inspected using clearly labeled synthetic/demo data. Exercised reload/cog actions, the small unnamed control strip, actual alpha-channel transparency with opaque provider rows, native Windows tray registration, hide/restore and visible tray menu actions, continued refresh timer, saved tray option, missing-tray fallback, and Quit. Existing resize/view/window/currency/stale/credential regression coverage remains intact.
- Actual Windows Credential Manager round trip with an isolated synthetic entry, then deletion; no account credential was used or overwritten.
- Real DeepSeek balance endpoint rejects an unauthenticated GET with HTTP 401.
- Real official Codex CLI stdio initialization/account read in an isolated ephemeral home returns the honest sign-in-required state.
- Windows PyInstaller build embeds DoWidget's own multi-size icon and locally bundles control/provider assets. The packaged executable was launched with credential-free demo data and its icon resources were checked; translucent corner dragging and icon Close were exercised.

The working DeepSeek and Codex provider/authentication implementations are unchanged by this UI update. Authenticated live calls were not repeated or used for screenshots; the checks above used isolated synthetic data. Linux Mint runtime, credential storage, native/compositor resize behavior, and packaging **have not been verified**. The original release's real endpoint/keyring/CLI checks listed above are retained as historical evidence, not repeated for this update.

## GitHub publishing

Repository remote: `git@github.com:lewdoherz/DoWidget.git`. Commit author: `lewdoherz <lihp1987@gmail.com>`. No GitHub credential belongs in source or examples; revoke any token exposed in a chat and authenticate locally instead.

`.github/workflows/release.yml` builds a Windows x64 portable ZIP, runs the regression/compilation/dependency checks, creates `SHA256SUMS.txt`, and publishes a GitHub Release when a matching `vX.Y.Z` tag is pushed. It uses GitHub's short-lived built-in `GITHUB_TOKEN`, limited to repository-content writes in the release job—not a stored personal token. The tag must match `pyproject.toml`; `RELEASE_NOTES.md` supplies the published notes. The workflow YAML and local build commands were checked; the workflow cannot be exercised on GitHub until authenticated push is available.

With a working GitHub SSH key (and Actions enabled for the repository), publish the prepared version:

```powershell
git push --set-upstream origin main
git push origin v0.2.0
```

If using GitHub CLI instead, authenticate locally with `gh auth login` and include permission to update workflow files. Do not paste a replacement token into chat. The prepared local ZIP can also be attached to a release through GitHub's UI or `gh release create` after signing in.

## Official integration references

Documentation inspected before implementing the adapters:

- [DeepSeek Get User Balance](https://api-docs.deepseek.com/api/get-user-balance/)
- [DeepSeek base URL and Bearer authentication](https://api-docs.deepseek.com/)
- [OpenAI authentication: ChatGPT subscription versus API key](https://learn.chatgpt.com/docs/auth)
- [OpenAI subscription usage, pricing, dashboard, and `/status`](https://learn.chatgpt.com/docs/pricing)
- [Codex app-server: stdio, authentication, and quota schema](https://learn.chatgpt.com/docs/app-server)
- [Codex configuration and credential-store settings](https://learn.chatgpt.com/docs/config-file/config-reference)
