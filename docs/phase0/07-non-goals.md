# 07 — Explicit non-goals

Status: **frozen for Phase 1**

Phase 1 is a local deadline-change engine. The following are deliberately out of
scope. They may be designed later, but they are not implied by this work.

## Product and scope

- The full five-phase roadmap in one release.
- A general-purpose academic knowledge graph.
- Modeling every academic concept: prerequisites, degree audits, tuition,
  instructors, rooms, policies, accommodations, or institutional rules.
- Grade calculation, GPA calculation, or transcript reconstruction.
- Multi-user collaboration, shared workspaces, or role management.
- Mobile applications.
- A public API or remote service.
- A new primary navigation structure.
- A Home/Planner redesign.
- Replacing the existing Study, Library, Review, Activity, Import, or History
  features.

## External systems

- Google Calendar reads or writes.
- Gmail or other email access.
- Brightspace, Canvas, Moodle, Blackboard, or other LMS integrations.
- University portal automation.
- Browser scraping or background monitoring.
- Automatic submission of assignments, quizzes, exams, discussions, or forms.
- Contacting instructors, TAs, students, or staff.
- Payments.
- Authentication as the student.
- Collecting passwords, MFA codes, cookies, session tokens, or hidden API keys.
- Scheduler ownership, recurring background jobs, or automatic agent runs.

## Change execution

- Universal atomicity across unrelated stores.
- Universal undo.
- Automatic application without student approval for consequential academic
  changes.
- Trusted agent auto-approval for assessment deadlines, weights, linked task
  due dates, mirror links, or reversal.
- Agent self-approval.
- Silent conflict resolution.
- Overwriting a later student change during reversal.
- Deleting assertions, journal events, approvals, or historical records.
- Rewriting original source documents.

## Knowledge model

- A second editable copy of assessment or task values.
- A separate canonical `Deadline` record for an assessment deadline.
- Arbitrary JSON blobs as assertion values.
- Automatic task↔assessment links inferred from matching titles or dates.
- Automatic migration of existing records into `verified` or newly
  `user-confirmed` assertions.
- Treating AI extraction as independent authority.
- Treating a ChangeSet approval as source verification.

## Study plan

Phase 1 reserves `study_plan.reschedule` as a future operation type but does not
create a study-plan record, invent study sessions, or reschedule practice
reviews. The existing Study data remains read-only for this engine.

## UI

- A full visual redesign.
- A new dashboard navigation model.
- A fifth primary area for Review or Changes.
- Mobile optimization.
- A calendar view.
- A replacement for the existing coursework editor.
- An agent chat redesign.

## Release

- Merging `next/academic-engine` into `main`.
- Publishing a release or updating the installed app.
- Enabling the engine for the installed `/Applications/AcademiaOS.app` sidecar
  without a separate install/update step.

These require explicit approval after the local slice is validated.

## Related contracts

- [README.md](README.md)
- [08-acceptance-tests.md](08-acceptance-tests.md)
- [09-phase1-plan.md](09-phase1-plan.md)
