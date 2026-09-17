---
name: academic-operating-system
description: "Use when building, initializing, maintaining, or operating a personal academic file system that must support human navigation, AI agents, source provenance, study workflows, assignments, exams, grades, deadlines, email, Calendar, and research without destroying original material."
version: 1.0.0
author: Academia OS contributors
license: MIT
metadata:
  academia_os:
    tags: [academics, university, study, provenance, assignments, exams, calendar, research]
---

# Personal Academic Operating System

## Overview

This skill governs the creation and ongoing operation of a local academic workspace that is useful to both a student and autonomous agents. The goal is not merely folders: it is a provenance-aware operating system that converts course material, readings, lectures, notes, assignments, exams, communications, Calendar data, and carefully filtered web research into reliable study and planning support.

The central invariant is **preserve first, interpret second**. Original academic material must remain distinguishable from user-created notes, AI-generated aids, external research, historical reports, and inference. The system should act when evidence is sufficient, do nothing when nothing changed, and surface uncertainty rather than inventing course facts.

Session-specific setup evidence and the dry-run pattern are in `references/initial-setup-pattern.md`. Brightspace retrieval, authentication-boundary handling, Downloads diffing, and deterministic inbox handoff are detailed in `references/brightspace-acquisition.md`. Cross-course propagation and scheduled-job parity checks are in `references/cross-course-propagation.md`.

## Delivery Modes and Durable Automation

When a course system needs modality awareness, use the explicit values `In Person`, `Online — Synchronous`, `Online — Asynchronous`, `Hybrid`, and `Unknown`. Determine the course default and each session exception from current authoritative evidence, in priority order: professor announcements, current syllabus, official university information, current class schedule, professor email, then other reliable course material. Never infer online or in-person status from a missing room or link. Course context should record meeting pattern, physical location, online platform, recurring times, asynchronous components, known exceptions, source, last verification, and confidence. Calendar event location/descriptions and study strategy must follow the session-level mode.

For durable academic processing, use the local Academia OS inbox gate before any agent or worker. It inventories active-course `00_INBOX/` files, ignores harmless metadata such as `.DS_Store` and `.gitkeep`, compares file signatures against retryable records in the workspace's `.academia/processing.json`, and reports only new or retryable work. The lifecycle is `DETECTED → PENDING → PROCESSING → VERIFIED → ACKNOWLEDGED`; failures remain retryable and a scan never acknowledges work. Pair this with a processor that preserves originals, leaves uncertainty visible, verifies side effects, and records activity. Any scheduler or agent may invoke the interface; the core does not assume a specific scheduler.

## Optional Source Acquisition Layer

School-site/browser acquisition is optional and must never define the core. Manual imports and watched folders are the preferred supported paths. A future browser companion may support explicit actions such as “Send to Academia OS,” “Save reading,” and “Import this page.” Browser adapters must accept a normalized source record containing source type, browser/profile label when relevant, source URL, acquisition time, and original file path.

The current Chromium capability is limited to an optional visible handoff when explicitly configured. Firefox, Safari, and browser-companion adapters are planned rather than implemented. Never imply that a browser profile is a school account, never read passwords, MFA codes, cookies, or hidden session tokens, and keep school sites read-only. If a user explicitly enables an adapter, verify the page itself, exact course/module identity, local file hashes, and the requested source version. If access, identity, legality, or download status is uncertain, stop and report rather than guess.

For legitimate readings, prefer university library, institution, publisher, DOI/open-access, repository, or author-released sources. Discovery-only results do not authorize downloading unclear copies. Never pay without explicit confirmation, and never silently substitute an edition. Record `EXACT MATCH — HIGH CONFIDENCE`, `PROBABLE MATCH — VERIFY MANUALLY`, `MISMATCH`, or `NOT RETRIEVED`.

## When to Use

Use this skill when the user asks to:

- create or rebuild a university/academic folder system;
- turn an existing academic directory into an agent-readable operating system;
- organize syllabi, lectures, readings, notes, assignments, exams, and submissions;
- maintain course dashboards, grades, weak areas, source indexes, or semester reviews;
- define inbox, email, Calendar, research, citation, or version-control behavior for academic material;
- process new academic files or detect changes to course documents;
- prepare a reusable course template or academic operating manual.

Do not use it to infer missing courses, fabricate syllabi or deadlines, replace original sources with summaries, or silently bypass mandatory submission or academic-integrity requirements.

## Phase 1: Inspect Before Editing

1. Resolve the exact requested root; do not create a second root with a similar name.
2. Recursively inventory directories, files, file types, sizes, and obvious source categories.
3. Identify semesters, course folders, syllabi, schedules, lectures, readings, notes, assignments, exams, submissions, feedback, and miscellaneous downloads.
4. Establish a preservation baseline for existing content. Do not overwrite, rename, move, or delete anything until its identity and role are understood.
5. Record what is absent. An empty academic root is a valid state; it means create infrastructure, not fictional courses.
6. If available, check integration readiness separately from local filesystem readiness. Missing authorization is a setup state, not evidence that a capability is impossible.

Use exact observed course names and codes. If classification is uncertain, keep the item in an inbox or ask for clarification. Never infer a course from a generic filename, an ambiguous folder, or a similarly named course at another institution.

## Phase 2: Build the Root Operating System

For a requested root, create only the requested root and its documented children:

```text
University/
├── README.md
├── ACADEMIC_OS_RULES.md
├── INTEGRATION_STATUS.md
├── COURSE_TEMPLATE/
└── [semester]/
    ├── SEMESTER_STATUS.md
    └── SEMESTER_TASKS.md
```

The root README is a short human quick-start. The global rules file is the complete agent contract. Integration status must say which services are actually authorized, which were not audited, and the minimum action needed to enable them. A semester shell may be created from reliable temporal/user context, but it must not contain invented course facts. Avoid creating future semesters or empty week folders without a reason.

## Phase 3: Create the Reusable Course Template

Every real course should follow this architecture:

```text
[COURSE CODE - COURSE NAME]/
├── 00_INBOX/
├── 01_COURSE/
│   ├── README.md
│   ├── Course_Context.md
│   ├── Course_Status.md
│   ├── USER_OVERRIDES.md
│   ├── Grading.md
│   ├── Schedule.md
│   ├── Questions.md
│   ├── Weak_Areas.md
│   ├── Calendar_Log.md
│   └── Communications_Log.md
├── 02_WEEKS/
├── 03_ASSIGNMENTS/
├── 04_EXAMS/
│   ├── Midterm/
│   └── Final/
├── 05_REFERENCE/
├── 06_KNOWLEDGE/
└── 99_ARCHIVE/
```

Include template versions of assignment context, week summaries, active-recall questions, and exam knowledge bases. Keep `02_WEEKS/` and `03_ASSIGNMENTS/` free of fictional content. Empty directories may use harmless directory markers when the filesystem requires a file to retain them, but do not allow OS metadata to pollute a reusable template.

The course `01_COURSE/README.md` is the course operating manual and must be the first read for course work. It should explain folder purposes, naming, intake, authority, provenance, Calendar, email, web research, assignments, exams, overrides, status, uncertainty, version safety, and commands. Ensure relative links are correct from the file's actual depth; test them after duplicating the template into a semester/course path.

For syllabus-driven initialization, follow `references/syllabus-population-and-verification.md`: preserve byte-identical originals, extract evidence before populating, derive only evidenced weeks/assessments, visibly flag ambiguity, and use an interruption-safe manifest/audit loop.

## Cross-course propagation and execution-surface parity

An Academic OS upgrade requested from the evidence of one course is a system-level change unless the user explicitly scopes it to one course. Do not infer that a one course example proves all courses are covered. After changing a global rule, audit the root rules/README, the reusable `COURSE_TEMPLATE`, every active course's required directories and operating files, and each course's first-read README. Exclude `COURSE_TEMPLATE` from active-course processing, but ensure the template contains the same reusable behavior.

Treat scheduled jobs and pre-run scripts as separate execution surfaces from the filesystem documentation and loaded skill. When adding or changing a workflow, inspect the persisted job definitions and verify that every relevant job prompt explicitly carries the new behavior, scope, exclusions, confidence labels, and safety boundaries. Verify the gate implementation separately, including its active-course discovery and template exclusion. Report framework coverage separately from course-specific population: a course can have the capability and template while lacking a source-specific record because no source has been retrieved.

## Phase 4: Populate Only Verified Course Facts

For each existing course, read authoritative material before filling operational files. Prefer current professor announcements, current assignment/exam instructions and rubrics, current syllabus, official university information, assigned material, then older and external sources. Record missing values as `Not yet known` rather than guessing.

`Course_Context.md` is a concise current summary of identity, instructor, meetings, description, themes, required material, assessment, dates, citation style, and current week. `Course_Status.md` is a live dashboard of progress, unprocessed material, deadlines, grades, weak areas, announcements, questions, and next actions; it is not a source. `Grading.md` contains only reliable grades and weights. `Schedule.md` contains confirmed recurring and dated events. `Questions.md` and `Weak_Areas.md` remain concise and evidence-based.

## Inbox and Change-Detection Protocol

For each new item in `00_INBOX/`:

1. Inspect the actual content and metadata.
2. Identify semester, course, source type, and course component.
3. Compare against existing sources to detect a new version or conflict.
4. Preserve the original and avoid same-name overwrite.
5. Rename only when identity remains clear and retrieval improves.
6. Move only when classification is clear; otherwise leave it in place with an uncertainty note.
7. Update only dependent context, status, schedule, assignment/exam context, semester status, source index, and logs.
8. Check for Calendar implications.
9. Verify the result and preserve the prior version when the change is meaningful.

A revised syllabus, assignment, rubric, schedule, exam instruction, or professor email should produce a small, explicit change record, not an unnecessary rebuild of all generated material. Newer authoritative information supersedes older information; older sources remain historical when useful.

## Provenance, exact-version proof, and source-first academic writing

Maintain `06_KNOWLEDGE/Source_Index.md` for important original readings, textbooks, syllabi, lectures, assignment sheets, rubrics, and articles. Record author, title, year, type, week/topic, original file, URL, DOI, pages, useful passages, relevant assessments, authority, confidence, and access date where possible. For every retrieved reading, chapter, book, article, textbook, or other potentially citable source, also create a linked record in `06_KNOWLEDGE/Source_Verification/`.

The professor's current syllabus, assignment instructions, Brightspace reading list/content page, or current announcement is the authoritative target specification. The verification record must separately show what was requested, what was retrieved, its source/provenance, edition/year/publisher, ISBN/DOI, chapter/pages, authorization, every match/mismatch/unavailable/non-comparable field, and a final result. Compare author/editor, exact title/subtitle, edition, year, publisher, ISBN-10/ISBN-13, DOI, volume/issue, chapter, required pages, language, page count where useful, file identity, source URL, and access date. Use only `EXACT MATCH — HIGH CONFIDENCE`, `PROBABLE MATCH — VERIFY MANUALLY`, `MISMATCH`, or `NOT RETRIEVED`. A lecture deck can match a course topic while remaining a mismatch for an assigned book/article. Never use a different edition or source type as a silent substitute; report `MISMATCH — different edition`, list the differences and page-shift risk, and wait for approval.

Anna's Archive is discovery-only unless a copy is clearly public domain, openly licensed, author-released, publisher-released for free, or otherwise legitimately and freely distributable. If legality is unclear, do not download; use metadata to search Brightspace, the configured institution library/Omni, OpenAthens, the publisher, DOI/official open access, repositories, or author-posted manuscripts. Never pay without explicit user confirmation.

Use these labels whenever ambiguity matters:

- `ORIGINAL` — professor, university, assigned reading, or official source.
- `USER-CREATED` — user's notes, drafts, questions, preferences, or submissions.
- `AI-GENERATED` — dashboards, summaries, plans, practice questions, interpretations, and verification records.
- `EXTERNAL` — web research or other outside material.

For essays and research assignments, follow: instructions → rubric → user overrides → original course sources → verified evidence and page numbers → permitted external scholarship → outline → draft → rubric/citation/submission review. Never use a generated dashboard, summary, internal path, AI note, or verification record as the final citation endpoint. Never fabricate a quotation, author, page, DOI, URL, or publication detail. If a claim cannot be verified, say so.

## Study, Exams, Weak Areas, and Spaced Review

Create week folders only after a week/topic is known. A `Week_Summary.md` should synthesize lectures, readings, notes, professor emphasis, concepts, arguments, examples, disagreements, and cross-week connections while separating course-confirmed facts, user notes, external enrichment, and uncertainty.

`Study_Questions.md` should favor active recall: definitions, explanations, applications, comparisons, cases, calculations, graphs/models, and essay prompts as appropriate. Exam knowledge bases should be built throughout the semester, with official scope marked confirmed when announced. Weak areas require evidence such as repeated errors, requests for explanation, performance, note confusion, or rubric weaknesses; they are not permanent labels. Use weak areas, forgetting risk, high-value topics, and confirmed scope in spaced-review plans.

## Assignments, Submissions, and Integrity

For every assignment, read the actual instructions and rubric before planning. Populate `Assignment_Context.md` with prompt, deadline, weight, word count, format, citation style, allowed/required sources, rubric, submission method, file format, restrictions, clarifications, checklist, and status.

Use statuses `Not started`, `In progress`, `Ready for review`, `Ready to submit`, `Submitted`, and `Graded`. Preserve sequential drafts, the exact final submitted version, receipt/confirmation, feedback, and grade. Never replace a submitted file with a later revision.

Personal study preferences are customizable. Professor preferences may be adapted for private notes. Mandatory submission requirements and academic-integrity restrictions must remain visible. If the user asks to ignore one, explain the academic/grading risk and never imply that the resulting work is compliant.

## Gmail and Google Calendar Integration

Use the configured Google Workspace skill for Gmail/Calendar access when available. Check authentication before use. If authorization is unavailable, build and document the workflow but do not claim the integration is configured; do not fabricate audits or event changes.

For relevant forwarded university email: confirm relevance, identify the course, extract actionable changes, compare against current sources, and make updates only when something changed. Record meaningful changes in `Communications_Log.md`. Do not modify email without explicit approval.

For Calendar: search for an equivalent before any create/update; compare course, event type, date, time, location, and recurrence; avoid duplicates; update only when newer information is more accurate; never delete unless explicitly instructed. Use `the configured timezone` unless the course says otherwise. Date-only events are all-day; exact times are timed. Use clear course-specific titles and short descriptions. Regular meetings get a 24-hour reminder; assessments and important due dates get 1-week, 3-day, and 24-hour reminders. Calendar writes require user confirmation. Log audits/actions in `Calendar_Log.md`.

## Semester Planning and Decision Logic

`SEMESTER_STATUS.md` should aggregate confirmed deadlines, exams, assignments in progress, readings/tasks, grades, courses falling behind, schedule changes, and recommended focus. Rank work using deadline proximity, workload, assessment weight, difficulty, dependencies, lateness, weak areas, exam proximity, progress, and future importance. A nearer small task is not automatically more important than a larger high-weight assessment.

State confidence and assumptions for estimates. Keep `SEMESTER_TASKS.md` actionable and update it during weekly reviews. Recommendations should name concrete next actions rather than giving generic productivity advice.

## Common Pitfalls

1. **Inspecting after reorganizing.** Inventory and preserve first; use the initial file list as the safety baseline.
2. **Inventing courses, weeks, dates, grades, or instructors.** Use observed names and explicit unknown markers.
3. **Treating generated summaries as sources.** Trace claims back to original files and record page-level provenance.
4. **Creating duplicate Calendar events.** Search and compare before every proposed write.
5. **Letting historical student reports override current course material.** Keep them in course history with confidence labels.
6. **Overwriting submissions or drafts.** Use sequential versions and preserve receipts/feedback.
7. **Blending external research into course truth.** Label it `EXTERNAL` and record URL/date/relevance.
8. **Using only deadline proximity for weekly priorities.** Include workload, weight, weakness, dependency, progress, and exam scope.
9. **Creating folders for unknown weeks or assignments.** Wait for evidence.
10. **Assuming OAuth setup succeeded because a workflow is documented.** Separately verify authentication and report unavailable access.
11. **Trusting relative links in a template without testing the duplicated depth.** Resolve links from their actual future locations in a temporary clone.
12. **Over-cleaning a sparse root.** Preserve metadata and all user content; remove only clearly generated non-academic clutter that appeared during setup and is safe to identify.
13. **Looping on scanned-PDF extraction.** First check whether PyMuPDF exposes text/metadata. If the PDF is image-only, use a bounded local OCR fallback such as rendered pages plus Tesseract for identification. Do not repeatedly retry a failing Swift/compiler or package-install command, do not install dependencies during inbox processing without an explicit need, and record the extraction limitation in the log while preserving the original scan.

## Verification Checklist

- [ ] Requested root was inspected recursively before changes.
- [ ] Existing content baseline is accounted for and preserved.
- [ ] No second root, speculative course, or premature week folder exists.
- [ ] Root README, global rules, integration status, and semester status/tasks exist.
- [ ] Course template contains every required operating file and directory.
- [ ] Course `01_COURSE/README.md` is the first-read manual.
- [ ] Relative links are tested after a temporary template duplication.
- [ ] Context/status files distinguish unknowns from confirmed facts.
- [ ] Source index and provenance labels exist.
- [ ] Assignment, exam, weak-area, grading, Calendar, and communication workflows are documented.
- [ ] Gmail/Calendar status reflects actual authorization, not intended setup.
- [ ] No Calendar or email write happened without user confirmation.
- [ ] Conceptual workflows are dry-run against the documented structure.
- [ ] Final report names configured courses, reorganized files, integration status, uncertainty, and next actions.
