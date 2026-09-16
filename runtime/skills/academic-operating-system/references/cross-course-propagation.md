# Cross-course propagation checklist

Use this checklist when a user asks whether an Academic OS change works throughout the university root rather than in one course.

## Scope audit

1. Resolve the exact Academic OS root.
2. Enumerate semester directories and active course directories from the filesystem; do not rely on a remembered course list.
3. Treat `COURSE_TEMPLATE` as reusable infrastructure, not an active course.
4. For every active course, verify the standard directories and required first-read files exist.
5. Confirm each course README points to the global rules and contains the relevant workflow locally when course agents read it first.

## Execution-surface audit

1. Inspect the persisted scheduler/job definitions, not only the documentation.
2. Confirm every relevant job uses the same root/workdir and covers every active course.
3. Confirm jobs explicitly exclude `COURSE_TEMPLATE`.
4. Confirm pre-run gates discover all active-course `00_INBOX` folders and persist state outside academic source directories.
5. When a workflow changes, check that every relevant job prompt carries the new behavior, safety rules, confidence labels, and failure behavior.

## Reporting distinction

State separately:

- **Framework coverage:** rules, templates, folders, job prompts, and scripts are available across all courses.
- **Course-specific population:** only facts and source records supported by actual material exist for a course.
- **Evidence coverage:** a source-verification record exists only for sources actually retrieved or accessed; absence of a record does not mean the workflow is missing.

Never claim system-wide implementation solely because one course has a populated example. Preserve intentionally unresolved course identities or missing metadata as explicit uncertainty rather than normalizing them across courses.
