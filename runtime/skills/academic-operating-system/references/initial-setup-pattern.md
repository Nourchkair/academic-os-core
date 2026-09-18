# Reference: Empty-Root Academic OS Initialization Pattern

## Session-derived setup pattern

Use this when the requested academic root is sparse or empty:

1. Inspect recursively before creating anything. Distinguish actual academic content from OS metadata such as `.DS_Store`.
2. Record the observed baseline: semesters, courses, files, and relevant file categories. If only metadata exists, state explicitly that there is no academic material to reorganize.
3. Create the root manual, universal rules, integration-status note, and a semester shell only when the semester is supported by the user's context or current date. Keep the shell free of course facts.
4. Build a reusable course template with all standard course-wide files and empty operational directories. Use harmless directory markers only if needed to retain empty directories.
5. Put assignment/week/exam working templates in a clearly labelled template area; do not create fictional weeks or assignments in the reusable structure.
6. Make all dashboards and context files explicitly say `Not yet known` when source data is absent.
7. Test relative links from the locations where files will actually be read after template duplication. A root-level course README and an `01_COURSE/README.md` have different relative depths to the root rules file.
8. Run a structural audit after writing, then correct path or layout inconsistencies and rerun it.
9. Review the Agent Setup Playbook and local workflow preferences. External agents perform their own provider checks; do not claim Gmail/Calendar access, an audit, or a write occurred unless that agent reports and verifies it.
10. Perform conceptual dry runs for inbox processing, assignment intake, changed deadlines, forwarded email, week study, exam preparation, essay/citation verification, weekly review, and structural repair.

## Useful verification assertions

For a template duplicated under `<root>/<semester>/<course>/`, verify:

- `<course>/README.md` resolves the root rules file via `../../ACADEMIC_OS_RULES.md`.
- `<course>/01_COURSE/README.md` resolves the root rules file via `../../../ACADEMIC_OS_RULES.md`.
- `<course>/01_COURSE/README.md` resolves the course source index via `../06_KNOWLEDGE/Source_Index.md`.
- `<course>/01_COURSE/Course_Context.md` resolves the course source index via `../06_KNOWLEDGE/Source_Index.md`.
- `02_WEEKS/` and `03_ASSIGNMENTS/` contain no invented content in the reusable template.
- The semester shell contains no course directory until a real course is identified.

## Preservation note

Do not delete an existing academic file merely because the root is sparse. If setup causes clearly generated OS metadata to appear inside a reusable template, identify it separately from user content before cleaning it. Retain the user's original root metadata unless there is a specific, safe reason to remove it.

## Integration note

A documented workflow is not an authenticated integration. Before Gmail/Calendar work, perform the provider setup check. If it reports missing authorization, record the exact status and stop before reads or writes. When authorization becomes available, start with a read-only audit; require confirmation before Calendar writes or email modifications.
