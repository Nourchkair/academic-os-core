# Academic Operating System Rules

**Student:** {{STUDENT_NAME}}
**Institution:** {{INSTITUTION}}
**Program:** {{PROGRAM}}
**Semester:** {{SEMESTER}}
**Timezone:** {{TIMEZONE}}
**Scope:** this local University folder and its active semester/course folders.

## 1. Core principles

1. Preserve academic material. Never delete, casually overwrite, or destructively reorganize original professor, university, reading, assignment, submission, feedback, or personal-note files.
2. Prefer reliable source provenance over convenience. Generated summaries are secondary aids, not evidence.
3. Act when classification or change is clear; do nothing when no change is needed; ask rather than guess when uncertainty affects organization, deadlines, grades, citations, or compliance.
4. Keep current course truth separate from historical reports, external enrichment, user preferences, and AI inference.
5. Recommendations must consider workload, weight, difficulty, dependencies, progress, weak areas, and exam proximity—not just the nearest deadline.
6. Preserve meaningful revisions, drafts, submitted versions, receipts, feedback, and superseded authoritative sources.
7. Treat this folder as both a human filing system and an agent-readable knowledge base.

## 2. Authority and labels

Use this conflict priority unless a current user instruction would create a mandatory compliance risk:

1. Explicit current user instructions and course overrides where appropriate.
2. Current instructor announcements and clarifications.
3. Current assignment/exam instructions and rubrics.
4. Current syllabus.
5. Current official institution or department information.
6. Assigned academic material.
7. Older course material.
8. Reputable external research.
9. Student resources, forums, and anonymous reports.
10. AI-generated summaries or inferences.

Use confidence labels when useful: `Current-confirmed`, `Likely`, `Unverified`, and `Historical`.

Use provenance labels:

- `ORIGINAL` — supplied professor, institution, assigned reading, or official source.
- `USER-CREATED` — notes, drafts, questions, preferences, or submissions.
- `AI-GENERATED` — summaries, dashboards, study questions, plans, or interpretations.
- `EXTERNAL` — web research not supplied as course material.

Never state that an external or historical point was taught or required unless a current course source verifies it.

## 3. Course structure

Every configured course uses:

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

Only create week/topic folders when reliable material establishes them. Only create assignment folders when an assignment exists. Keep unclear material in `00_INBOX/`.

## 4. Intake and classification

For every new inbox item:

1. Inspect its actual content and metadata.
2. Identify semester, course, source type, and component if possible.
3. Compare it with current authoritative material and detect new versions or conflicts.
4. Preserve the original and avoid same-name overwrites.
5. Move it only when classification is clear; otherwise leave it in place with an uncertainty note.
6. Update dependent context/status/schedule/assignment/exam/semester/source/log files only when supported.
7. Check for Calendar implications.
8. Verify the resulting paths and file contents.

## 5. Delivery mode and schedule

Allowed delivery modes are `In Person`, `Online — Synchronous`, `Online — Asynchronous`, `Hybrid`, and `Unknown`. Determine them from authoritative evidence. Never infer a mode from a missing room or link. Record course-level and session-level exceptions separately, with source, date, and confidence.

Calendar writes require explicit user confirmation. Search for an equivalent before creating or updating an event. Do not create duplicates or delete events without explicit instruction. Date-only information is all-day; exact times are timed events. Log audits and actions in `Calendar_Log.md`.

## 6. Gmail and school communications

Process only relevant university/course communications when Gmail is authorized. Extract actionable changes, compare them with current sources, and update only what changed. Record meaningful changes in `Communications_Log.md`. Do not send, delete, archive, or modify email without explicit approval.

## 7. Assignments and academic integrity

Read the actual instructions and rubric before planning. Track prompt, deadline, weight, format, citation style, allowed/required sources, submission method, restrictions, checklist, and status. Use statuses `Not started`, `In progress`, `Ready for review`, `Ready to submit`, `Submitted`, and `Graded`.

Preserve sequential drafts and the exact final submitted version, receipt, feedback, and grade. Never overwrite a submitted file with a later revision. Mandatory submission requirements and academic-integrity restrictions remain visible even when personal study preferences differ.

Use the source-first workflow: instructions → rubric → overrides → original course sources → verified evidence/page numbers → permitted external scholarship → outline → draft → rubric/citation/submission review.

Never fabricate authors, quotations, page numbers, publication details, URLs, DOIs, grades, deadlines, or course facts. Never cite a generated dashboard or internal path as the final academic source.

## 8. Sources and exact-version verification

Maintain `06_KNOWLEDGE/Source_Index.md` for important sources and a linked verification record for every potentially citable retrieved source. Compare author, title, edition, year, publisher, ISBN/DOI, chapter/pages, source type, URL, language, file identity, and access date where available.

Use exactly these result labels: `EXACT MATCH — HIGH CONFIDENCE`, `PROBABLE MATCH — VERIFY MANUALLY`, `MISMATCH`, and `NOT RETRIEVED`. A related source, summary, different edition, or lecture deck must not silently substitute for an assigned reading. If legality or authorization of a copy is unclear, do not download or cite it; use legitimate library, institution, publisher, DOI, repository, or author sources.

## 9. Study and exams

Build week summaries, active-recall questions, weak-area records, and exam knowledge bases from original material plus clearly labelled generated aids. Weak areas require evidence such as repeated errors, confusion, poor performance, or rubric feedback; they are not permanent labels. Confirmed exam scope overrides guesses and historical reports.

## 10. School-portal acquisition boundary

The browser helper may verify and attach to the user's real visible Chromium-family profile and the handoff utility may move newly downloaded supported files into a verified course inbox. The workflow is read-only with respect to the school portal. It must never enter or store passwords/MFA codes, read cookies, submit assignments, answer quizzes, post messages, change settings, or delete content.

## 11. Safe automation

The inbox gate must run before the agent. It must ignore `COURSE_TEMPLATE`, persist signatures outside the academic root, and emit no wake when nothing changed. The processor must preserve uncertain files and verify side effects. Scheduled jobs must use the configured local paths and local delivery only.
