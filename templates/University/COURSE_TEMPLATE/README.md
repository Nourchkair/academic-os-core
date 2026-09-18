# Course Template — [COURSE CODE - COURSE NAME]

Duplicate this directory only after the course identity is confirmed by a syllabus or official course source.

```text
[COURSE CODE - COURSE NAME]/
├── 00_INBOX/
├── 01_COURSE/
├── 02_WEEKS/
├── 03_ASSIGNMENTS/
├── 04_EXAMS/
├── 05_REFERENCE/
├── 06_KNOWLEDGE/
└── 99_ARCHIVE/
```

Start with `01_COURSE/README.md`, `USER_OVERRIDES.md`, `Course_Context.md`, and `Course_Status.md`. Keep unknown material in `00_INBOX/`; do not invent weeks, assignments, grades, deadlines, or instructors. Preserve original files and treat generated aids as secondary.

## AI-generated secondary material

Authorized agents create study guides, summaries, practice questions, and other secondary material through `academia artifact create`. Academia creates `06_KNOWLEDGE/AI_GENERATED/` lazily, writes Markdown only, records the artifact in `.academia/artifacts.json`, and links the source references. These files are visibly marked `AI-GENERATED`, are never authoritative, and are not allowed to overwrite course originals.
