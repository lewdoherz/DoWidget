# DoWidget

A small native floating desktop widget for **multiple independent AI account/API connections**. Python + PySide6 Qt Widgets; no web frontend or local HTTP server. Provider adapters, connection/refresh state, secure credential storage, and presentation stay separate.

**Desktop assumption:** a draggable standalone floating window, not the Windows Widgets board. Board integration is a separate requirement. Windows 11 is the verified target; the same source is intended for Linux Mint, which has not been tested.

## Supported usage sources

| Provider | Automatic source | Required authentication / scope | What it actually displays |
|---|---|---|---|
| DeepSeek | Documented `GET /user/balance` | Your DeepSeek API key | Account-wide available balance and optional breakdown. Returned currency and decimal precision preserved. |
| Codex | Official local app-server `account/rateLimits/read` | Official Codex CLI and a separate ChatGPT sign-in for each connection | Codex subscription windows, separately labeled, with supplied reset times. Not general ChatGPT message limits or OpenAI API billing. |
| Claude | Documented `GET /v1/organizations/spend_limits/effective` | Claude Enterprise scoped Admin key with `read:spend_limits`, usage credits enabled, and member `user_…` ID | The member's spend caps and reported spend, not Claude Pro/Max message allowance or a Console API wallet. |
| Grok / xAI | Documented management API `GET /v1/billing/teams/{team_id}/prepaid/balance` | Separate xAI management key with billing-read permission and team ID | Team prepaid USD funds, not SuperGrok subscription allowance. |
| Gemini | No supported ordinary-API-key remaining-balance/subscription source established | Explicitly selected local usage JSON file | Clearly labeled local observations; otherwise unavailable/setup required. |
| GLM / Z.AI | Official usage plugin exists, but no standalone public quota API established | Explicitly selected local usage JSON file | Clearly labeled local observations; otherwise unavailable/setup required. |

All six also support **explicit local usage snapshots**. These are not automatic live integrations. An ordinary API key must not be assumed to expose a consumer subscription allowance. No private account endpoints, browser cookies, other applications' credentials, model-generation probes, or app-local token totals are used to manufacture account-wide percentages.

Multiple keys on one account/team/project can show the **same shared balance or quota**. Connections are displayed independently, never summed. Optional model labels are **display-only**; they do not create model-specific budgets or change request endpoints.

### Monetary and missing-data behavior

DeepSeek's original CNY/USD currency and all supplied decimal digits are preserved using `Decimal`. Grok's documented signed USD-cent ledger uses negative purchases and positive spending: its available funds are the opposite sign, converted exactly to USD; debt stays negative, not converted with `abs()`.

Claude distinguishes **spend caps** from wallet balances. Each returned period is separate. Monetary values use the returned currency's known minor-unit exponent; unrecognized exponents remain explicitly labeled **minor units**, rather than guessing. A null cap means unlimited; a zero cap means included-usage-only, not a percentage denominator. The official API can report zero spend when its spend read is temporarily unavailable, so zero spend cannot produce a misleading 100% remaining value. Monthly reset is first-of-month 00:00 UTC per the official guide; unestablished reset rules are not invented.

Percentages are calculated only from valid source used percentages or valid used/total values, clamped to 0–100. Missing/invalid usage is **Unknown**, never zero or full. Request-per-minute throughput limits are not represented as subscription allowance.

### Why Codex no longer says “preview”

The previous `Codex · subscription (preview)` heading described this application's dependency on the experimental **app-server command**, not a subscription plan or an estimated percentage. The heading is **Codex · subscription**; the caveat remains in Settings/help.

The [official app-server documentation](https://learn.chatgpt.com/docs/app-server) says the app-server command and WebSocket transport are experimental and not supported for production workloads. It separately documents stdio and a stable API surface without `experimentalApi`. DoWidget uses that stdio/stable account surface, not WebSocket or experimental API opt-in. **Practical consequence:** CLI/protocol changes may require a DoWidget update. Service-reported `usedPercent` is not an estimate.

## Codex extra credits and resets

**DoWidget does not generate tasks, purchase credits, consume banked resets, or change account spending permissions.** Its Codex RPC boundary permits only initialization, authentication, account read and quota read; quota-reset consumption and model work are rejected before sending an RPC. Monitoring does not authorize paid overage in another client.

OpenAI's [banked-reset documentation](https://help.openai.com/en/articles/20001498-how-banked-codex-resets-work) says banked resets must be applied by you: Settings → Usage → available reset → review → confirm. Do not confirm one if you want to keep it unused. Scheduled/global resets are different provider-side changes; DoWidget cannot disable them.

For Business, [official spend controls](https://help.openai.com/en/articles/20001155-managing-credits-and-spend-controls-in-chatgpt-business) are in **Workspace settings → Billing**. Owners/admins set monthly credit-usage limits by seat type or per-user override; owners manage Automatic reload. **Turning off reload stops automatic purchases, not consumption of credits already present.** Review the actual controls for your plan and stop Codex work at included limits if additional usage is not desired. No supported quota-read API was established that lets DoWidget switch off service-side paid-credit use; the application does not claim to have changed it. Settings includes links to the official account controls.

## Windows 11 setup and launch

Install 64-bit [Python](https://www.python.org/downloads/) **3.11+**, then in PowerShell:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m dowidget.app
# Clearly labeled offline preview:
.\.venv\Scripts\python.exe -m dowidget.app --demo
```

Demo mode does not read account credentials, make provider requests, start Codex, or save preferences. Its additional providers and same-company sample connection use clearly marked synthetic values.

## Linux Mint setup and launch

**Not verified on Mint.** Mint 22's Python 3.12 is suitable. In a normal graphical desktop session:

```bash
sudo apt update
sudo apt install python3-venv libgl1 libegl1 libxkbcommon-x11-0 \
  libxcb-cursor0 libxcb-icccm4 libxcb-keysyms1 libxcb-shape0 \
  libxcb-xinerama0 libxcb-render-util0 libxcb-xkb1 gnome-keyring
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m dowidget.app
.venv/bin/python -m dowidget.app --demo
```

Use an unlocked Secret Service keyring and a working session D-Bus for secure storage; otherwise choose session-only credentials. Do not run the GUI with `sudo`. Mint's X11 desktop is the initial practical target; Wayland/compositor policies can restrict saved positions, transparency and always-on-top. Tray behavior needs a usable notification area/StatusNotifier/XEmbed implementation.

## Add and manage connections

1. Open **Settings** (the cog in Compact view).
2. Choose **Add account / API connection**, company/product, source, and a distinguishing name such as Personal or Work. Add the same company again for another key/account. Gemini and GLM default to the explicit local-file source.
3. Select a connection in the list. Set its name and optional model label. For Claude's automatic source, enter the Enterprise member ID; for Grok enter the team ID. Choose **Save connection** for metadata/source changes.
4. For DeepSeek/Claude/Grok, enter your own credential in the **masked key field** and choose **Connect / replace key**. Keys are never prefilled, included in settings JSON, or shown in error messages. Claude needs the privileged read-scoped Admin key, not an ordinary inference key; Grok needs the management key, not an inference key.
5. **Remember in operating system credential store** uses only Windows Credential Manager or Linux Secret Service. Uncheck for session-only. Replacing with session-only first removes a saved key; deletion/save failures are reported rather than hidden or silently falling back to plaintext.
6. **Monitor this connection** controls refreshes without revoking its credential. **Disconnect** removes that connection's saved/session credential; **Remove connection** disconnects and removes the card. Other connections are unaffected.

Changes apply immediately; **no restart is needed to add a connection, change its labels, switch views or enable tray behavior**. To upgrade the executable, close the old window and launch the new version once. Existing default DeepSeek key and Codex sign-in, geometry, view and tray settings migrate. Removed/empty connection lists stay empty after restart.

### Codex connections

Install the [official CLI](https://learn.chatgpt.com/docs/cli) on PATH:

```bash
npm install -g @openai/codex
```

Restart DoWidget after installation so it gets the updated PATH. Select a Codex automatic connection in Settings → **Sign in with ChatGPT**, then complete the official browser flow. Finish one browser sign-in before starting another, and choose the intended account in the browser. Different connections are not guaranteed to represent different accounts if you sign them into the same account.

Each connection owns an isolated DoWidget `CODEX_HOME`. The migrated default retains `codex`; additional homes are `codex-connections/<connection-id>`. Codex itself owns OAuth, keyring storage and token refresh. Remember uses `cli_auth_credentials_store="keyring"`, never plaintext fallback; unavailable secure storage offers `"ephemeral"`. Switching storage modes first logs out the old mode; a failed logout stops the switch. Disconnect logs out **only this DoWidget connection**, not another installation. Inherited provider tokens/keys are stripped from the server environment.

Missing CLI, sign-in, entitlement or returned quota produces an honest setup/unavailable state. Other providers keep working.

### Gemini and GLM local sources

[Gemini's official rate-limit documentation](https://ai.google.dev/gemini-api/docs/rate-limits) says API quotas are per **project**, not per key, and directs users to [AI Studio](https://aistudio.google.com/rate-limit?timeRange=last-28-days) for active limits. This does not establish an ordinary-key API for Gemini subscription remaining percentages or an API wallet balance.

[Z.AI documents the Personal-plan usage plugin](https://docs.z.ai/devpack/extension/usage-query-plugin) `/glm-plan-usage:usage-query` inside Claude Code, installed from [zai-org/zai-coding-plugins](https://github.com/zai-org/zai-coding-plugins). That is a supported tool integration, not documentation authorizing arbitrary standalone monitor-endpoint access. DoWidget does not run Claude/model work to query it, import plugin credentials, or call private monitor APIs.

Select **Explicit local usage JSON file**, then **Browse… → Save connection**. Supply observations you explicitly obtained from your own supported source/dashboard. There is no automatic dashboard export implied; manually author or independently export the following schema. All amounts/quantities are **decimal strings**, not JSON numbers. Example is **DEMO**, not real usage:

```json
{
  "provider": "glm",
  "product": "GLM Coding Plan plugin — demonstration data",
  "observed_at": "2026-01-01T00:00:00Z",
  "demo": true,
  "windows": [
    {"name": "5h", "used_percent": "25", "resets_at": "2026-01-01T05:00:00Z"},
    {"name": "Week", "used": "40", "total": "100"}
  ],
  "note": "Illustrative values only; not live account usage."
}
```

- `provider` must match the connection: `deepseek`, `codex`, `claude`, `gemini`, `grok`, or `glm`.
- `product` labels the actual source/product; `observed_at` must include a time-zone offset. Replace it only when you obtain a new observation, not when rereading old data.
- Set `demo: false` only for actual account observations. Demo files retain the **D/DEMO** markers. No secrets belong in these files.
- Each window has `name`, either `used_percent` **or** `used`/`total`, and optional aware ISO8601 `resets_at`. Missing/invalid usage remains Unknown. Do not supply a precomputed `remaining` field.
- Optional `balances` rows use `{"currency":"CNY","total":"24.8400","granted":"0","topped_up":"24.8400"}` in **major currency units**; values are illustrative. Currency spelling/precision are retained.
- At least one balance/window is required. Files are bounded to 256 KiB and 32 rows per array; unknown fields, duplicate keys and credential-file formats are rejected. Observations more than five minutes in the future are rejected.
- Original observation time is retained as the data-update timestamp. An observation older than the refresh interval is marked **stale**, even with automatic refresh disabled. Rereading it does not make it fresh. Updating a valid file recovers the card; malformed/unreadable files retain prior data as stale.

## Widget behavior

- Drag **edges/corners** to resize and the header/Compact drag handle to move. Position, selected view and each view's size are remembered. Saved off-screen/oversized geometry is recovered against current screens.
- **Compact** in Detailed view switches immediately; Compact's **expand** icon returns to Detailed. Compact keeps the small unnamed control strip, reload/cog icons, partially translucent chrome and opaque rows. Account/model labels distinguish multiple connections; windows remain separate. Claude Compact rows identify **spend caps**; monetary details are in tooltips/Detailed view.
- Detailed defaults to 380 × 560, minimum 340 × 280. Compact defaults to 320 × 190, minimum 260 × 130 (Qt logical pixels). Cards wrap/scroll; window, refresh and settings controls remain outside the scroll area.
- Green dot = connected, `?` = setup required, `!` = stale/error, circular arrow = updating, `D` = demo. Hover for source, errors, resets, breakdown and last successful data update; Detailed view shows these directly. Unknown usage never turns into zero/full.
- Optional **Settings → Minimize to system tray → Save behavior**. Tray click restores; menu provides Show, Refresh, Settings, Quit. Timers continue hidden. Missing/disappearing tray restores/falls back to the taskbar. **Close/× quits**, not silently hides. Always-on-top remains optional.
- Automatic refresh defaults to **five minutes**, configurable 1–1,440 minutes; manual refresh is available. A bounded four-worker pool and per-connection busy state prevent overlapping operations on a connection. Independent states prevent one account's failure from replacing another account's value.
- Failures retain the last successful snapshot/timestamp as stale, with exponential backoff capped at one hour and bounded Retry-After. Manual refresh respects failure cooldown. Reconnecting resets that connection's state.
- HTTP uses bounded bodies, connect/read timeouts and no redirects. DeepSeek retains its 4/10-second timeouts and 20-second stream deadline; an outstanding socket read can add up to 10 seconds. New administrative HTTP callers have a 20-second overall deadline, including Claude pagination; blocked transport cleanup can finish afterward under its socket timeout. Codex RPCs time out after 20 seconds each; sign-in waits at most three minutes. Dead transports are recreated; ephemeral sessions may then need sign-in again.
- Times are displayed in your local timezone with numeric UTC offset. Account values are not cached to disk.

Preferences live in Qt's platform application-data `settings.json`: geometry/view/behavior and validated **nonsecret** connection metadata (ID, provider, name, model label, source, monitor/remember flags and source fields). API credentials are isolated under `DoWidget.Connections.<provider>` by connection ID. The old default DeepSeek slot is migrated only on explicit credential retrieval, saving the new slot before deleting the old. Raw response bodies, keys, auth URLs and upstream error text are not logged or shown.

### Icons and logos

Authentic DeepSeek, OpenAI, Claude, Gemini, Grok and Z.AI logos are locally packaged from official favicons/apple-touch icons. No runtime downloads, invented imitation marks, recoloring or distorted geometry. Exact source URLs and attribution are in [`dowidget/assets/SOURCES.md`](dowidget/assets/SOURCES.md). Providers do not endorse DoWidget. The window/tray/executable use DoWidget's **own original D/gauge icon**, not provider branding.

## Packaging

Build separately on each target OS; PyInstaller does not cross-compile. Distribute the **entire** output directory. Portable builds are unsigned, not installers.

Windows 11:

```powershell
.\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --windowed --onedir --name DoWidget --distpath dist/v0.3.0 --collect-data dowidget --icon dowidget/assets/dowidget.ico --hidden-import keyring.backends.Windows run_widget.py
.\dist\v0.3.0\DoWidget\DoWidget.exe
.\dist\v0.3.0\DoWidget\DoWidget.exe --demo
```

Close the old application and launch this version once. Keep the complete `DoWidget` directory together; SmartScreen may warn because the executable is unsigned. Codex is optional and separately installed, not bundled.

Linux Mint (documented, **not verified**):

```bash
.venv/bin/python -m PyInstaller --noconfirm --clean --windowed --onedir \
  --name DoWidget --collect-data dowidget --hidden-import keyring.backends.SecretService run_widget.py
./dist/DoWidget/DoWidget
```

Build on the oldest supported Mint target; glibc/Qt libraries still matter. An optional desktop launcher can point to the absolute executable. Review [Qt for Python licensing](https://doc.qt.io/qtforpython-6/licenses.html) and include applicable notices when distributing binaries.

## Checks and verification

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m compileall -q dowidget run_widget.py
.\.venv\Scripts\python.exe -m pip check
```

On Linux, use `.venv/bin/python` with the same arguments.

Verified on **Windows 11 Pro x64 build 26200, Python 3.14.7**:

- **606 regression tests passed**; compilation and dependency checks passed. Synthetic/mocked sources cover exact balances/currencies, valid/missing/clamped percentages, both Codex windows, read-only RPC policy, Claude nullable/zero/ambiguous caps, Grok signed ledgers, bounded HTTP/pagination/auth/rate-limit/offline failures, secure per-account storage/migration, stale retention, local timestamps, empty-list persistence, geometry/view/tray behavior and account isolation.
- Native application smoke, using isolated temporary settings and **clearly labeled synthetic data**, exercised Settings adding/connecting two DeepSeek keys, distinct balances/currencies, model metadata, both Codex windows, Claude/Grok adapters, local Gemini/GLM files, unknown data, one-account stale failure without changing another, minimum resizing, saved connections/view/geometry and restart. Native Compact/settings surfaces were inspected; no real credential was used in screenshots.
- Final Windows PyInstaller application launched in credential-free demo mode. Its six company logos and Compact surface were visually inspected; physical Windows input exercised corner resizing, header dragging, the settings cog and clean icon-Close shutdown. The complete portable ZIP and SHA-256 checksum were generated.

Working DeepSeek/Codex authentication and usage sources were preserved; new account scoping and the no-consumption RPC guard were added. **Authenticated live calls for the new privileged Claude/Grok sources were not exercised**: no such credentials were supplied. Gemini/GLM automatic remaining-usage retrieval remains unavailable; local sources are explicit. **Linux Mint runtime, secure storage, visuals/compositor/tray and packaging have not been verified.**

## GitHub Releases

Repository: `git@github.com:lewdoherz/DoWidget.git`. Matching `vX.Y.Z` tags trigger `.github/workflows/release.yml`: Windows x64 build, regression/compilation/dependency checks, complete portable ZIP and `SHA256SUMS.txt`, then GitHub Release using the short-lived built-in `GITHUB_TOKEN` with repository-content write permission. No personal token belongs in source or examples.

```powershell
git push --set-upstream origin main
git push origin v0.3.0
```

`RELEASE_NOTES.md` supplies the published notes. Use a locally authenticated Git/CLI credential; do not paste tokens into chat or commit them.

## Official integration references

- [DeepSeek balance API](https://api-docs.deepseek.com/api/get-user-balance/) and [Bearer authentication](https://api-docs.deepseek.com/).
- [OpenAI authentication](https://learn.chatgpt.com/docs/auth), [pricing/usage](https://learn.chatgpt.com/docs/pricing), [app-server](https://learn.chatgpt.com/docs/app-server), [credential-store configuration](https://learn.chatgpt.com/docs/config-file/config-reference).
- [OpenAI banked resets](https://help.openai.com/en/articles/20001498-how-banked-codex-resets-work), [Business credits/spend controls](https://help.openai.com/en/articles/20001155-managing-credits-and-spend-controls-in-chatgpt-business).
- [Claude spend limits guide](https://platform.claude.com/docs/en/manage-claude/spend-limits-api), [effective-limit schema](https://platform.claude.com/docs/en/api/beta/organization/spend_limits/effective/list), [Admin key authentication](https://platform.claude.com/docs/en/manage-claude/admin-api-keys). Console limits in early-access preview are not treated as ordinary supported Console-key access.
- [xAI management authentication](https://docs.x.ai/developers/management-api-guide), [prepaid billing schema](https://docs.x.ai/developers/rest-api-reference/management/billing).
- [Gemini quota/rate-limit documentation](https://ai.google.dev/gemini-api/docs/rate-limits).
- [Z.AI official usage-query plugin](https://docs.z.ai/devpack/extension/usage-query-plugin), [usage policy](https://docs.z.ai/devpack/usage-policy).
