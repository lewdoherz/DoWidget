"""Product labels and setup guidance, separate from account presentation."""
PROVIDERS = {
    "deepseek": ("DeepSeek", "DeepSeek · API balance", "deepseek", "https://platform.deepseek.com/api_keys", "Your DeepSeek API key reads the account-wide balance. Multiple keys on one account can show the same balance."),
    "codex": ("Codex", "Codex · subscription", "openai", "https://chatgpt.com/codex/settings/usage", "Sign in with ChatGPT using the official Codex CLI. Each connection has its own DoWidget sign-in. Not OpenAI API billing or general ChatGPT message limits. The documented app-server command is experimental; protocol changes may require an update, but percentages are service-reported, not estimates."),
    "claude": ("Claude", "Claude Enterprise · spend cap", "claude", "https://platform.claude.com/docs/en/manage-claude/spend-limits-api", "Automatic retrieval requires a Claude Enterprise scoped Admin key with read:spend_limits, usage credits enabled, and the member's user_ ID. Shows the member's spend cap, not Pro/Max message allowance or a Console API wallet. Ordinary API keys cannot reveal those subscription limits. The service can report zero spend while its spend reading is unavailable; that case stays Unknown."),
    "gemini": ("Gemini", "Gemini · usage unavailable", "gemini", "https://aistudio.google.com/rate-limit?timeRange=last-28-days", "An ordinary Gemini API key does not expose a supported remaining-balance or subscription-percentage source. API quotas belong to a project, not each key; RPM/TPM are not subscription allowance. Select an explicit local usage snapshot from your own usage source. DoWidget does not scrape AI Studio or use browser credentials."),
    "grok": ("Grok / xAI", "Grok / xAI · API prepaid balance", "grok", "https://console.x.ai/", "Requires an xAI management key with billing-read access and the team ID, not an ordinary inference key. Reads team-wide prepaid USD credit; not SuperGrok subscription limits. Different keys on one team can show the same balance. Negative available balance indicates debt."),
    "glm": ("GLM / Z.AI", "GLM · usage unavailable", "glm", "https://z.ai/manage-apikey/coding-plan/personal/my-plan", "Z.AI documents a Personal-plan usage plugin in Claude Code, not a supported standalone public quota API. Select an explicit local usage snapshot from your own dashboard or plugin output. DoWidget does not run model calls, inspect another tool's credentials, or use private monitor endpoints."),
}


def product_title(connection):
    if connection.source == "local":
        return PROVIDERS[connection.provider][0] + " · local usage snapshot"
    return PROVIDERS[connection.provider][1]


def connection_title(connection):
    return connection.name + " — " + product_title(connection)


def connection_caption(connection):
    return connection.name + (" · model label: " + connection.model_label if connection.model_label else "")
