# Optional Hermes adapter

Academia OS is usable without Hermes. This directory contains the optional adapter that:

- detects whether Hermes is installed;
- reports `available`, `configured`, or `connected` honestly;
- translates neutral local job specifications into Hermes cron commands;
- keeps Hermes skill/cron registration separate from core workspace/configuration behavior.

The adapter does not receive passwords, MFA codes, cookies, or session tokens. It does not submit academic work, send school-account messages, or change Calendar without explicit approval.

Future adapters may live beside this one:

```text
adapters/
├── hermes/
├── codex/       # foundation only; not implemented
├── claude/      # foundation only; not implemented
└── chatgpt/     # foundation only; not implemented
```
