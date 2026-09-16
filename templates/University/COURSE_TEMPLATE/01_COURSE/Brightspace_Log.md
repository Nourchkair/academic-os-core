# Brightspace Retrieval Log — [COURSE CODE - COURSE NAME]

**Purpose:** concise record of on-demand Brightspace acquisitions. This is an operational log, not an academic source.

## Retrieval entry template

```text
YYYY-MM-DD
Requested: Fetch Brightspace — [course] — [week/module]
Course match: [exact code/title/semester/instructor evidence]
Brightspace source page: [URL or Not available]
Downloaded to 00_INBOX:
- [original filename]
Skipped:
- [filename] — [already present / duplicate hash / irrelevant / download failed]
Embedded pages captured:
- [filename or None]
Result: [N] new file(s) sent to 00_INBOX.
Notes/uncertainties: [None or concise description]
```

The retriever must not classify files beyond the acquisition handoff, invoke the Inbox Processor, submit work, answer quizzes, post messages, or modify course settings. Files in `00_INBOX/` are processed by the existing Academic OS Inbox Processor.
