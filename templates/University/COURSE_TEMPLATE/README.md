# Course Template — [COURSE CODE - COURSE NAME]

Duplicate this directory only after the course identity is confirmed by a syllabus or official course source.

```text
[COURSE CODE - COURSE NAME]/
├── 00_INBOX/
├── 01_COURSE/
├── 02_WEEKS/
├── 03_ASSIGNMENTS/
│   ├── README.md
│   ├── Assignment_History.json   # created when the first coursework record is added
│   └── [assignment folders]/
├── 04_EXAMS/
├── 05_REFERENCE/
├── 06_KNOWLEDGE/
└── 99_ARCHIVE/
```

Start with `01_COURSE/README.md`, `USER_OVERRIDES.md`, `Course_Context.md`, and `Course_Status.md`. Keep unknown material in `00_INBOX/`; do not invent weeks, assignments, grades, deadlines, or instructors. Preserve original files and treat generated aids as secondary.

Read this course's coursework archive with `academia history list --course "COURSE ID" --semester "TERM" --json`. The course History section in the dashboard and the same CLI support adding and updating user-confirmed assignment, essay, project, exam, presentation, quiz, and other records. `Assignment_History.json` stores academic state, not conversation history. A Submitted record reflects a user report or authorized confirmation; it does not mean an AI submitted work to the school. Keep assignment files and submission versions in their own assignment folders and reference them using course-relative paths.

## AI-generated secondary material

Authorized agents create study guides, summaries, practice questions, and other secondary material through `academia artifact create`. Academia creates `06_KNOWLEDGE/AI_GENERATED/` lazily, writes Markdown only, records the artifact in `.academia/artifacts.json`, and links the source references. These files are visibly marked `AI-GENERATED`, are never authoritative, and are not allowed to overwrite course originals.
