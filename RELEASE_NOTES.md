# DoWidget 0.3.0

- Multiple independent account/API connections for the same provider, with names and optional **display-only** model labels. Separate credentials, refresh state, errors and cards; no aggregation of potentially shared balances/quotas.
- Settings connection manager: add, configure, connect/sign in, stop monitoring, disconnect, remove. API keys stay masked and isolated in OS credential storage, with session-only fallback.
- Existing default DeepSeek key, Codex sign-in and window/view/tray preferences migrate. Additional Codex connections have isolated sign-in homes; complete one browser sign-in at a time.
- **Claude:** documented Enterprise read-scoped Admin API + member ID displays spend caps, not Pro/Max message allowance or an API wallet. Nullable/zero caps and ambiguous zero spend never fabricate full remaining usage.
- **Grok / xAI:** documented management key + team ID reads prepaid USD funds. Exact signed-cent conversion; not SuperGrok subscription allowance.
- **Gemini and GLM / Z.AI:** honest unavailable state for unsupported automatic remaining-usage access, plus explicitly selected local usage JSON snapshots. Ordinary generation keys are not assumed to reveal subscription quotas. Local observations retain their timestamp and become stale; rereading does not make them fresh.
- Authentic locally packaged Claude, Gemini, Grok and Z.AI logos join DeepSeek/OpenAI. Compact rows distinguish accounts, preserve currencies and keep separate usage windows. Spend-cap monetary details remain in tooltips/Detailed view.
- Codex monitoring explicitly rejects banked-reset consumption and model-work RPCs. It never buys credits or changes OpenAI spending permissions. Settings/help explains official account controls and the difference between purchased credits, banked resets and scheduled/global resets.
- Compact icon controls, translucent chrome, edge/corner resizing, saved geometry, tray behavior and the original DoWidget icon are preserved.

## Windows download

Extract the **entire Windows x64 ZIP** and launch `DoWidget/DoWidget.exe`. Keep its directory and dependencies together. Close the previous app and launch this version once; adding connections, switching views and changing tray settings afterward need no restart. The portable executable is unsigned and may trigger SmartScreen. `SHA256SUMS.txt` accompanies the ZIP.

Open **Settings → Add account / API connection** to add another key/account. For Claude provide the Enterprise Admin key and member ID; for Grok provide the management key and team ID. Gemini/GLM default to local-file sources; the documented JSON schema and supported-source limitations are in README.md. Codex remains optional and requires the separately installed official CLI.

## Verification and integration limits

606 regression tests passed on Windows 11 x64, along with compilation and dependency checks. Native application smoke used isolated settings and clearly labeled synthetic responses: two DeepSeek keys, currency precision, both Codex windows, Claude/Grok adapters, local Gemini/GLM, unknown/stale/error isolation, settings, resizing and saved profiles/view/geometry/restart. No real credential was included in screenshots or test sources.

The final Windows portable application was launched in credential-free demo mode. Its packaged logos/Compact surface were visually inspected, and native Windows mouse input exercised corner resize, header move, settings cog and clean icon-Close shutdown.

Authenticated live calls to new Claude/Grok privileged sources were not exercised because no credentials were supplied. Gemini/GLM are **local-source support, not fabricated live APIs**. OpenAI account-level credit permissions are not changed by a usage monitor; manage them in the official account/workspace controls. Banked resets require user confirmation per OpenAI's documentation.

Codex uses stable account methods over stdio; the app-server **command** has an experimental/production-support caveat. The subscription itself is not labeled preview, and percentages are service-reported, not estimates.

Linux Mint is intended to use the same source, but runtime, secure storage, visuals/tray/compositor and packaging were not tested there. No Linux binary is included.
