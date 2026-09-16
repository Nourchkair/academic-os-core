# Reference: Syllabus-Driven Course Population and Verification

Use this reference when initializing courses from supplied syllabi or other authoritative course documents.

## Evidence-first extraction

1. Preserve each supplied document as an `ORIGINAL` copy inside the course's `01_COURSE/` area; never edit the copy used as the source record.
2. Extract searchable text from PDFs/DOCX files before populating dashboards. Prefer a structured extractor (for example, PyMuPDF for PDFs and `python-docx` or platform text conversion for DOCX) and retain the extracted text outside the academic root when it is only an intermediate artifact.
3. Read the extracted material in sections: identity, instructor/contact, meetings, evaluation, schedule, assignments, exams, readings, policies, citation requirements, and integrity/tool restrictions.
4. Treat only explicit syllabus statements as course-confirmed. Use `Not yet known`, `TBA`, or a visible `[VERIFY]` marker for absent or ambiguous values.

## Safe population pattern

1. Create the reusable template first, then instantiate one course at a time.
2. Derive week folders only from named/dated syllabus topics. If the syllabus has dates but no topic, do not invent a topic; use a neutral date-based label or leave the week unmaterialized according to the course policy.
3. Create assignment/exam workspaces only for assessments actually named in the authoritative source.
4. Populate `Course_Context.md`, `Schedule.md`, `Grading.md`, assignment contexts, exam knowledge bases, `Course_Status.md`, and `Source_Index.md` from the same evidence pass, but keep dashboards concise and clearly secondary.
5. Copy syllabus facts into semester status only after the course-level files exist, so the semester dashboard has a single course-level source of truth.

## Ambiguity and provenance

- Do not normalize an unclear course code, section, title, instructor identity, deadline time, or delivery mode by guessing. Preserve the observed value and flag it for confirmation.
- Keep exact source filenames and hashes in the verification record when a supplied source is copied. A hash comparison verifies byte preservation; it does not prove the extracted interpretation is correct.
- Distinguish `ORIGINAL`, `USER-CREATED`, `AI-GENERATED`, and `EXTERNAL` material in filenames or frontmatter where confusion is possible.
- Do not index every trivial file. Prioritize syllabi, assignment sheets, rubrics, exam instructions, assigned readings, textbooks, and lecture material likely to matter for assessments or citations.

## Idempotent and interruption-safe execution

Bulk file generation can be interrupted or partially completed. Make the population process recoverable:

1. Generate and verify one course at a time, or use clearly separated batches.
2. After each batch, audit required files, week counts, assignment/exam workspaces, and placeholder leakage.
3. If a batch stops, do not rerun destructive replacement blindly. Compare the current tree with the intended manifest and write only missing or intentionally incomplete files.
4. Re-run the complete structural audit after repairs.
5. Treat template placeholders in instantiated courses as verification failures; retain templates only in `COURSE_TEMPLATE`.

## Minimum final audit

Confirm all of the following:

- Every configured course has the standard top-level directories and required `01_COURSE` files.
- Every created week and assessment is supported by authoritative material.
- No unresolved ambiguity is presented as confirmed fact.
- Supplied originals remain byte-identical after copying.
- No user academic file was overwritten, deleted, or moved without clear classification and an explicit preservation record.
- Semester status reflects current known dates and explicitly labels unknown dates.
- Calendar/Gmail claims reflect actual authentication and observed actions; documentation alone is not an integration audit.
