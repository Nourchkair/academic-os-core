# Phase 2 — Universal academic intake

Status: **pasted and imported-document intake merged at `main` (`d85b704`) and tagged `phase2-academic-intake`; not released**

This branch begins Phase 2 on top of the merged and tagged Phase 1 engine.

Phase 1 established the academic knowledge layer and the local ChangeSet engine.
Phase 2 adds the front door:

> Turn pasted academic announcements and imported documents into candidate facts
> and reviewable ChangeSets.

The intake layer never writes an academic value directly. It produces candidate
facts. A candidate becomes an effective academic change only through the Phase 1
ChangeSet approval and execution path.

## Core boundary

```text
pasted text / document / screenshot
  → preserved source
  → candidate facts
  → course and entity resolution
  → conflict and evidence check
  → reviewable ChangeSet
  → student approval
  → existing Phase 1 execution, verification, recovery, reversal
```

Intake is not a second source of truth. It records what a source appeared to
say, with evidence, so the student can decide what is true.

## First vertical slice

Paste one announcement:

> “My professor moved the Second Essay deadline to November 20.”

Expected:

1. The exact pasted text is preserved as a readable source note.
2. A candidate deadline fact is created with that source and its confidence.
3. The course and assessment are resolved exactly, or the student is asked.
4. The candidate is compared with the canonical deadline and any active
   assertions.
5. A reviewable ChangeSet is proposed through the Phase 1 engine.
6. Nothing changes until the student approves.
7. The student sees the evidence, the conflict, the affected linked tasks, and
   the same approval/skip/undo states as Phase 1.

If the course or assessment cannot be resolved safely, intake returns a question,
not a guess.

## Source preservation

Pasted text is a source, not a fact.

- Save the exact text in a readable note in the resolved course's `00_INBOX/`.
  If the course is unresolved, use the semester-level `00_INBOX/`.
- Name it with a timestamp and a short title, for example:
  `00_INBOX/Announcement - 2026-11-16 - Second Essay deadline.md`.
- Preserve the original text verbatim, plus acquisition time, course context, and
  an explicit `student-provided` or `imported-document` label.
- Do not rewrite an original document. Imported documents remain in place.
- The note is evidence. It is not a second academic record.

## Candidate fact

```json
{
  "id": "candidate:...",
  "intake_id": "intake:...",
  "source": {
    "kind": "pasted_text | imported_document | screenshot",
    "path": "Fall 2026/.../00_INBOX/Announcement - ....md",
    "locator": "paragraph 1",
    "excerpt": "My professor moved the Second Essay deadline to November 20."
  },
  "course_hint": null,
  "entity_hint": {
    "type": "assessment",
    "title": "Second Essay"
  },
  "field": "due_date",
  "value": "2026-11-20",
  "confidence": "likely | unverified",
  "specificity": "exact | partial | approximate",
  "status": "candidate | resolved | needs_course | needs_entity | conflict | proposed | rejected",
  "resolution": {
    "course_id": null,
    "assessment_id": null,
    "why": null
  },
  "proposed_change_id": null,
  "created_at": "...",
  "created_by": "user | agent:..."
}
```

Rules:

- Candidate facts are append-only records with status transitions.
- A candidate is never treated as an active academic value.
- `confidence` describes extraction quality, not truth.
- A candidate from a paste is `student-provided`; a document extraction is
  `AI-GENERATED` or `EXTERNAL` as appropriate.
- The source excerpt and locator are mandatory.
- Unknown or ambiguous course/assessment resolution is a visible state.

## Parsing and extraction

Phase 2 starts with deterministic, explainable extraction:

- recognize explicit date phrases (`November 20`, `Nov 20`, `2026-11-20`);
- recognize change verbs (`moved`, `extended`, `due`, `postponed`);
- recognize an assessment-title hint from the sentence;
- never infer a course from a filename alone.

An AI provider may later propose the same candidate records through the same
interface. It must not write academic values directly, and it must preserve the
source excerpt. A parser failure is reported, not guessed.

Imported documents follow the same candidate path:

```text
existing import → preserved original → existing bounded extraction
  → candidate facts → resolution → ChangeSet
```

The existing syllabus extraction and domain projection remain evidence sources;
they are not bypassed.

## Course and entity resolution

- Use exact canonical course IDs, codes, names, and display-name suffixes.
- Reject ambiguous identifiers with a structured error.
- Prefer an exact assessment title within the resolved course.
- If only one assessment matches, resolve it.
- If none or multiple match, ask the student; do not pick one.
- A candidate that cannot be resolved remains visible and retryable.

## Conflict handling

When a candidate disagrees with the canonical owner or an active assertion:

- preserve both;
- show the candidate value, the current value, the source excerpt, and the
  verification state;
- produce a ChangeSet with the conflict in its preview;
- never auto-apply the candidate.

The Phase 1 approval, execution, crash recovery, and conditional reversal rules
apply unchanged.

## UI contract

The first intake surface is intentionally small:

- a paste box;
- a source preview showing the exact text;
- candidate cards with course/assessment resolution;
- a button to prepare a ChangeSet;
- the existing Phase 1 impact preview and approval dialog.

The UI must show:

- why the candidate was extracted;
- whether the course/assessment is resolved or needs a decision;
- what is a candidate versus an approved value;
- that approval is not source verification.

No broad navigation redesign in Phase 2.

## Permissions

| Capability | Agent | Student |
| --- | --- | --- |
| Submit a paste/document as an intake source | Yes | Yes |
| Create candidate facts | Yes | Yes |
| Resolve an ambiguous course/entity | No | Yes |
| Create a ChangeSet from a candidate | Yes | Yes |
| Approve/execute/reverse | No | Yes, through Phase 1 |
| Mark a candidate as verified | No | Only with evidence |

Agents may prepare intake, but cannot turn a candidate into an approved academic
record.

## Acceptance tests for the first slice

1. Paste `My professor moved the Second Essay deadline to November 20.` in a
   course with `Second Essay` due `2026-11-12`.
2. The exact text is saved in the course `00_INBOX/`.
3. One candidate deadline fact is created with source excerpt and `2026-11-20`.
4. The assessment resolves uniquely; the candidate links to it.
5. A ChangeSet is created with the candidate as evidence.
6. The preview shows the current value, candidate value, and evidence.
7. The student can approve or reject; no value changes before approval.
8. If the course is ambiguous, no ChangeSet is created and a question is shown.
9. If the assessment is ambiguous, no ChangeSet is created and a question is shown.
10. Re-running intake on the same text does not create duplicate candidates.
11. A candidate cannot be approved by an agent.
12. Imported documents preserve the original and produce the same candidate
    model.
13. Existing Phase 1 tests, migration, and copy-first behavior still pass.

## Explicit non-goals

- School portal, Brightspace, Canvas, Moodle, or Blackboard integrations.
- Gmail, calendar, browser scraping, or background monitoring.
- Automatic submission of work or messages to instructors.
- Treating an AI extraction as verified truth.
- Applying a candidate without student approval.
- Replacing the Phase 1 knowledge/ChangeSet engine.
- A broad UI or navigation redesign.
- A general-purpose NLP system in the first slice.

## Phase 2 task breakdown

1. Intake store and candidate model.
2. Pasted-text source preservation.
3. Deterministic announcement parser.
4. Course and assessment resolution.
5. Candidate review surface.
6. Candidate → ChangeSet bridge.
7. Imported-document candidate path.
8. Tests for ambiguity, duplicates, conflicts, and permissions.
9. Manual validation on a copied real workspace.

## Implemented intake slice

```text
academia intake paste --course COURSE --text "..." --semester TERM --json
academia intake document --course COURSE --source PATH --semester TERM --json
academia intake list --semester TERM --json
academia intake show CANDIDATE_ID --semester TERM --json
academia intake resolve CANDIDATE_ID --assessment ASSESSMENT_ID --semester TERM --json
academia intake propose CANDIDATE_ID --semester TERM --json
academia intake reject CANDIDATE_ID --semester TERM --json
```

The dashboard adds **Paste announcement** in the course workspace. It preserves
the exact text in the course `00_INBOX/`, shows a persistent candidate inbox,
resolves an exact assessment, and opens the existing Phase 1 preview/approval
dialog.

The same dialog can scan an imported PDF, DOCX, PPTX, Markdown, or text document
already in the course. The original document is preserved; candidates retain the
document path and passage locator. The deterministic parser handles explicit
dates, date changes with `from … to`, month-name and ISO dates, quoted titles, and
common deadline-change verbs. It returns `needs_entity` or `needs_confirmation`
instead of guessing.

Candidate display states follow the linked ChangeSet: **Proposed**, **Applied**,
**Reverted**, **Needs attention**, or **Cancelled**. Preserved announcement notes
appear in Course material as **Preserved source**, not as queued imports.

Validation performed on a copied real three-course workspace:

- exact source preservation;
- resolved candidate and ChangeSet creation;
- approval and verified execution;
- duplicate paste and duplicate document reuse;
- ambiguous assessment requiring student resolution;
- course-code inference from pasted text;
- no-candidate text preserving its source;
- imported-document candidate with passage locator;
- candidate inbox showing applied status after execution;
- browser walkthrough from paste → candidate inbox → verified change;
- browser walkthrough scanning an imported document and leaving its candidate
  unapproved.

Lint has no new findings versus the Phase 1 baseline (35 pre-existing problems).

## Baseline

Phase 1 is merged at `main` (`02fc461`) and tagged:

```text
baseline-pre-phase1-engine   # pre-merge rollback point
phase1-academic-engine       # validated Phase 1 merge
```

Phase 2 is merged at `main` (`d85b704`) and tagged:

```text
phase2-academic-intake       # validated Phase 2 intake merge
```

The installed app is still the existing release until a signed build is produced
and installed.
