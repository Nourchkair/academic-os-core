---
name: academia-os-hermes-adapter
description: Optional Hermes integration for scheduling neutral Academia OS jobs. Load only when Hermes is explicitly configured.
version: 1.0.0
author: Academia OS contributors
---

# Optional Hermes adapter

Academia OS works without Hermes. This adapter translates explicitly marked legacy compatibility job specifications into Hermes scheduling commands only when the user explicitly enables the adapter. New installations start from Agent Setup Playbooks and local workflow preferences; they do not create recurring jobs here.

## Boundaries

- Do not add Hermes paths, cron state, messaging destinations, or skill assumptions to `academia_os` core.
- Never copy a user's Hermes profile, memory, sessions, OAuth state, logs, or credentials into a workspace or repository.
- Keep delivery local unless the user has separately approved an integration; never send school-account messages.
- The inbox gate only detects work. The worker must complete processing, verify side effects, and acknowledge through the Academia OS lifecycle.
- Do not submit academic work, answer quizzes, post messages, or authenticate as the user.
- Academia OS does not implement payments. Agents must never infer payment authorization. Any future payment capability would require explicit student confirmation.

## Adapter operations

1. Detect whether the `hermes` executable is present.
2. Report `available`, `configured`, `connected`, or `unavailable` honestly.
3. Translate neutral job specifications with local workdir and local delivery.
4. Keep adapter failures retryable and visible in Activity/Review.
5. Use the adapter-specific acquisition reference only for explicitly enabled visible Chromium handoff.
