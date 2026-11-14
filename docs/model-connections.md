# AI model connections

Academia OS separates two model paths.

## Subscription

- **ChatGPT / Codex** uses the installed Codex CLI and the official device-code sign-in.
- **OpenCode Go** is a $10/month subscription that issues an API key. Academia sends the required identifying user agent and `x-opencode-session` header. It is listed with the API providers because connecting it requires pasting a key.
- Academia never reads or stores Codex credentials.
- The ChatGPT subscription never silently falls back to API billing.
- Claude subscription sign-in is not offered inside Academia because Anthropic restricts it to Claude Code and native Anthropic apps. Use Claude Code as an external agent or an Anthropic API key.
- Grok and Muse have no third-party subscription sign-in. Grok is available through the xAI API preset; Muse models are resold by OpenCode Zen over the Responses API, which this client does not speak yet.

## API providers

Supported presets:

- OpenAI
- Anthropic
- Google Gemini
- OpenRouter
- xAI (Grok)
- OpenCode Zen
- OpenCode Go
- Groq
- DeepSeek
- Mistral
- Together AI
- Cerebras
- Moonshot (Kimi)
- Z.ai (GLM)
- Ollama (local)
- LM Studio (local)
- Custom OpenAI-compatible endpoint

OpenCode Zen lists GPT, Claude, and Gemini models that require the Responses or
Messages protocols. Only models Zen serves over OpenAI-compatible chat
completions are shown, because other entries would fail at request time.

Adding a provider:

1. Choose a provider preset.
2. Paste its API key.
3. Academia validates the key and fetches the model list.
4. The key is stored in the macOS Keychain through the local sidecar.
5. Enable the models you want and set task routing.

No API key is written to `profile.json`, the academic workspace, connection
metadata, logs, or the repository.

## Model routing

The Connections hub stores a provider/model reference for:

- Default chat
- Fast
- Deep reasoning
- Vision
- Image generation

The current API chat path uses the selected per-chat model, or the default chat
model, and exposes Academia's read tools. API-backed chat is non-streaming in
this slice. Proposal mode, Codex web search, and Codex reasoning controls remain
Codex-only.

## Billing rules

- Subscription requests use the ChatGPT plan.
- API requests use the provider key and the provider's billing.
- Academia never silently switches between the two.
- Each response reports which provider/model handled it.
