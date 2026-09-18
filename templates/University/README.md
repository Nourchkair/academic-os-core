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
- `Ask an authorized external agent to inspect course sources — [course] — [week/module]` when the student has approved that agent's course-platform/browser workflow.

## Agent Setup Playbooks and workflow preferences

`TODAY.md` is an AI-generated dashboard, not an academic source. A student may choose the Daily Academic Brief playbook and save desired preferences under `.academia/workflow_preferences.json`. Academia OS does not create a scheduler or claim that a brief will run; an authorized external agent owns implementation, scheduling, delivery, and any optional source access.

The inbox gate scans active course `00_INBOX/` folders, ignores the reusable template, records state under rebuildable `.academia/` state, and emits `{"wakeAgent":false}` when no file changed. It is a local capability used by an agent or one-shot command, not a recurring Academia automation.

## External-agent access

Gmail/email, Calendar, Drive, school portals, browser sessions, research services, and recurring schedules are external-agent capabilities. The student authorizes them directly through the chosen agent. This folder never stores passwords, MFA codes, browser cookies, OAuth tokens, or API keys. School-site work remains read-only and must never submit coursework, quizzes, exams, forms, or discussions, send school-account messages, or modify portal content.

Read `ACADEMIC_OS_RULES.md` before changing academic material. Read `INTEGRATION_STATUS.md` for local capability and saved playbook intent, and `VERIFICATION.md` for local setup evidence.
