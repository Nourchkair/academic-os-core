# Phase 3 — Student workspace

Status: **implemented on `next/workspace-ui`; merged and tagged only after review; not released**

Phase 1 added the local academic knowledge engine and ChangeSet approval path.
Phase 2 added pasted and imported-document intake. Phase 3 makes those layers
legible as a student workspace without introducing a second academic store.

## Goal

> Give the student one calm place to see today, open a class, plan the week, and
> talk to the agent — while every academic change still passes through the same
> evidence, approval, execution, and audit rules.

Phase 3 is a presentation and navigation change. It does not add a task database,
a deadline database, or a new write path.

## Information architecture

Primary navigation:

| Area | Purpose |
| --- | --- |
| **Home** | Today's verified deadline, open tasks, class cards, attention items, and recent Activity. |
| **Courses** | The class workspace: material, Grades, History, and Study. Course intake belongs to its class. |
| **Planner** | A view over existing course deadlines and `SEMESTER_TASKS.md` personal tasks, plus pending changes and intake candidates. |
| **Agent** | The existing local Study chat, now a primary area with a visible **Workspace** return control. |

Global surfaces:

| Surface | Entry point |
| --- | --- |
| **Search** | Top action pill; local search across the loaded semester. |
| **Changes** | Top action pill with an attention count; combines Review decisions, approved actions waiting for execution, and intake candidate facts. |
| **Import** | Top action pill; existing copy-first import and migration panel. |
| **Settings** | Profile button in the sidebar; connection, model, and workflow settings. |
| **Activity** | Reachable from Home and Changes; the append-only audit view. |

Tasks and Review are no longer separate primary destinations. Their existing
components and endpoints remain the implementation behind Planner and Changes.

## Surface contracts

### Home

- Shows the next verified deadline and its urgency.
- Shows open tasks for the next seven days and links to Planner.
- Shows one card per class with material counts and a direct class link.
- Shows attention cards for **Changes & approvals** and **Processing**.
- Keeps recent Activity and a link to the full audit view.

### Courses

- Preserves the semester picker, course browser, material filters, processing
  status, previews, Grades, History, and Study.
- Keeps **Paste announcement** and document scanning inside the selected class.
- Accepts an intake-open request from Changes so a candidate can open the exact
  course intake dialog.
- Accepts a course-open request from Home and Search.

### Planner

- Reuses the existing `Tasks` component and task API with `intro={false}`.
- Keeps the All / Next 7 days / Open / Completed filters and personal-task editor.
- Is a view over:
  - structured course assessments and deadlines from the domain projection;
  - Markdown checkboxes in `Course_Status.md`;
  - personal tasks in the semester `SEMESTER_TASKS.md`.
- Adds attention cards for open Review decisions, pending intake candidates, and
  Course Study.
- Does not create a second task or deadline record.

### Changes

- Combines:
  - open Review decisions (existing `ReviewView`, embedded with `showIntro=false`);
  - approved actions waiting for the separate execution step;
  - intake candidate facts that still need a decision.
- Shows the review/decision/execution timeline from Activity.
- Opens the exact course intake dialog for a candidate when the candidate has a
  course. A candidate without a course routes to Courses so the student can pick
  the class.
- Approving a decision and executing an approved action remain separate actions.
- After execution, courses, tasks, Library, and intake are reloaded so Planner and
  Home reflect the verified result without a manual refresh.

### Search

- Runs locally over already-loaded semester data; it does not read the workspace
  tree or call a search service.
- Searches courses, tasks/deadlines, Library metadata, Review/intake records, and
  Activity titles.
- Links results to Courses, Planner, Changes, or Activity.
- Shows a clear empty state and never claims to search outside the selected
  semester.

### Agent

- Keeps the existing Study chat, model controls, source selection, Proposal mode,
  and Review links.
- Adds a visible **← Workspace** control in the conversation header so Agent is a
  peer area rather than a one-way destination.
- Proposals created in chat still open in Changes and cannot be approved by the
  agent.

## Data and safety boundaries

- Academic files remain canonical. Phase 3 adds no mutable copy of deadlines,
  tasks, grades, or study records.
- Planner reads the same task payload as the previous Tasks view. Personal-task
  edits continue to target `SEMESTER_TASKS.md`.
- Changes reads the existing Review and intake stores. It never writes a value
  directly; execution still uses the Phase 1 ChangeSet path.
- Search is read-only and client-side over the loaded surface.
- Agent proposals remain reviewable actions. Phase 3 does not grant the agent
  approval or execution authority.
- No school submission, messaging, payment, credential access, portal connector,
  or automatic background monitoring is added.

## Responsive, dark mode, and accessibility

- New surfaces reuse the existing page, card, and button vocabulary.
- Changes summary and Planner attention cards collapse to one column below 900px.
- Intake cards stack their action below the copy on narrow screens.
- Search exposes a labeled textbox and focus-visible buttons.
- The Agent Workspace control has an explicit `aria-label` and keeps its text at
  narrow widths.
- New colors define light defaults and `prefers-color-scheme: dark` overrides.
- Primary navigation buttons expose visible labels, hover states, and focus rings.

## Preserved behavior

The following continue to work through their existing components and APIs:

- semester switching and workspace validation;
- Library browsing, filters, previews, and preserved-source labels;
- Grades and Coursework History create/update flows;
- Study history, saved chats, sets, and practice;
- Import, migration, and processing status;
- Review decision, amendment, execution, and audit timeline;
- Agent chat, attachments, Proposal mode, and Review links;
- Settings, connections, MCP tools, and workflow preferences;
- Activity filters and archive behavior.

## Validation

- `npm run typecheck` in `frontend/`: passes.
- `npm test` in `frontend/`: 60 tests across 19 files.
- `npm run build` in `frontend/`: passes.
- Full Python suite: 658 tests pass.
- ESLint: 32 remaining problems in pre-existing, unrelated frontend files; the
  Phase 3 files add no findings (the change also removed three old App.tsx
  findings).
- Browser walkthrough on a copied three-course workspace:
  1. Home renders the four-area navigation and attention cards.
  2. Courses opens material, History, and Study without regressions.
  3. Planner renders the existing task list and filters.
  4. Changes renders intake candidates and an open task proposal.
  5. Approving the task proposal exposes the separate execution step.
  6. Executing verifies the task and refreshes Planner without a manual reload.
  7. Changes opens the exact course intake dialog for a candidate.
  8. Search finds a task, Library file, intake candidate, and Activity event.
  9. Agent chat opens, and **Workspace** returns to Home.
  10. Settings and Import remain reachable and load normally.
- Lighthouse accessibility score: 1.0 on Home, Planner, and Changes in the
  browser dashboard.

## Acceptance criteria

1. Home, Courses, Planner, and Agent are the only primary navigation items.
2. Planner is visibly a view over existing tasks and deadlines, not a new store.
3. Changes shows both Review decisions and pending intake candidates.
4. Nothing is applied without an explicit student decision; execution stays a
   separate step.
5. A task approved and executed from Changes appears in Planner without a manual
   reload.
6. Search is local, bounded to the selected semester, and routes to the right
   surface.
7. Agent remains a chat surface and cannot approve its own proposals.
8. Existing History, Study, Library, Import, Review, Intake, Activity, and Settings
   flows still work.
9. Reduced-width and dark-mode layouts remain readable.
10. No release is produced from this phase without explicit approval.

## Explicit non-goals

- A new backend task, deadline, or search database.
- A drag-and-drop calendar or timetable editor.
- Automatic schedule generation or background agents.
- New external connectors, portal access, or submission automation.
- Replacing the Phase 1 ChangeSet engine or the Phase 2 intake pipeline.
- A release, version bump, or signed build.

## Baseline

Phase 3 branches from `main` at `c28b83d` (Phase 2 merge). Previous rollback
points remain:

```text
baseline-pre-phase1-engine   # pre-Phase 1
phase1-academic-engine       # validated Phase 1 merge
phase2-academic-intake       # validated Phase 2 merge
```

The installed app remains the existing release until a signed build is produced
and installed with explicit approval.
