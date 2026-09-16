# Personal Academic Operating System

This local folder is a human- and agent-readable workspace for {{STUDENT_NAME}} at {{INSTITUTION}}. It organizes university material, study workflows, assignments, exams, grades, deadlines, communications, and planning without replacing original academic evidence.

## Initial state

This installation is intentionally initialized without invented courses, deadlines, grades, instructors, readings, or assignments. Add authoritative material—such as syllabi, schedules, assignment sheets, rubrics, announcements, or exported course files—to a real course's `00_INBOX/` after the course has been identified.

## Directory map

```text
University/
├── README.md
├── ACADEMIC_OS_RULES.md
├── INTEGRATION_STATUS.md
├── VERIFICATION.md
├── COURSE_TEMPLATE/
└── {{SEMESTER}}/
    ├── SEMESTER_STATUS.md
    ├── SEMESTER_TASKS.md
    └── TODAY.md
```

Each real course should be a direct child of the semester folder and should use `COURSE_TEMPLATE/`:

- `00_INBOX/` — temporary intake for files that still need classification.
- `01_COURSE/` — course context, status, preferences, grading, schedule, questions, weaknesses, and logs.
- `02_WEEKS/` — only weeks/topics established by reliable material.
- `03_ASSIGNMENTS/` — one non-destructive workspace per confirmed assignment.
- `04_EXAMS/` — confirmed midterm/final information and preparation.
- `05_REFERENCE/` — course-wide reference material.
- `06_KNOWLEDGE/` — source index, verification records, research, and history.
- `99_ARCHIVE/` — superseded material that remains worth preserving.

## Quick start

1. Duplicate `COURSE_TEMPLATE/` inside the correct semester folder only after the course identity is confirmed.
2. Rename it with the confirmed course code and title.
3. Put the syllabus and initial source files in `00_INBOX/`.
4. Read the course `01_COURSE/README.md` before processing material.
5. Populate facts from the actual source documents. Use `Not yet known`, `Unverified`, or an inbox uncertainty note when evidence is missing.

## Standard agent commands

- `Process inbox`
- `Course review`
- `Weekly review`
- `Study Week X`
- `Prepare for [exam]`
- `Start [assignment]`
- `Check [assignment]`
- `Semester review`
- `What should I work on today?`
- `Fetch Brightspace — [course] — [week/module]` when the configured school portal is Brightspace.

## Automation

`TODAY.md` is an AI-generated dashboard, not an academic source. The generated local installation contains parameterized cron definitions for a daily brief and a gated inbox processor. They deliver locally only; no messaging destination is copied from the builder.

The inbox gate scans active course `00_INBOX/` folders, ignores the reusable template, records state outside this academic root, and emits `{"wakeAgent":false}` when no file changed. The school-portal handoff snapshots Downloads and moves only new/changed supported files into a verified course inbox. It does not submit work or handle credentials.

## Integrations and credentials

Google services must be authorized in the user's own browser/account. School-portal authentication must be completed manually in the user's visible browser. This system never asks for, stores, or records passwords, MFA codes, browser cookies, or OAuth tokens in this folder or repository.

Read `ACADEMIC_OS_RULES.md` before changing academic material. Read `INTEGRATION_STATUS.md` for the current local authorization state and `VERIFICATION.md` for setup evidence.
