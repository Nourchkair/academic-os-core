# Academic OS Verification Record

Generated for **{{STUDENT_NAME}}** at **{{INSTITUTION}}**.

## Fresh-install checks

- [ ] Academic root was inspected before initialization.
- [ ] Existing user files were preserved; no differing file was overwritten.
- [ ] Root README, rules, integration status, and verification record exist.
- [ ] `COURSE_TEMPLATE` contains all required course directories and operating files.
- [ ] No course, week, deadline, grade, instructor, or reading was invented.
- [ ] Generated profile contains no passwords, tokens, cookies, or API keys.
- [ ] Runtime scripts compile successfully.
- [ ] Inbox gate ignores `COURSE_TEMPLATE` and suppresses unchanged scans.
- [ ] School-portal handoff skips unsupported/temporary files and identical hashes.
- [ ] Google authorization was tested under the user's own account, if enabled.
- [ ] Browser verification used the user's real visible profile, if enabled.
- [ ] Cron jobs were reviewed and deliver locally only.

## Evidence

Run:

```text
python3 installer/verify.py {{INSTALL_ROOT}}/profile.json
```

Record command output, dates, unresolved setup items, and manual authorization boundaries here. Do not paste secrets into this file.
