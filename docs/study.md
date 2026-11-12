# Agent-first studying

Academia OS is the academic harness. An authorized agent—Codex, a local model with a tool runner, or another agent—does the reasoning. Academia owns course identity, bounded source retrieval, citations, study sets, practice sessions, student answers, review schedules, exam scope, and the audit trail. The dashboard is a second client of the same `academia study` commands. No dashboard process or model provider is needed to use the domain.

## Study in conversation

A student can ask: “Quiz me on chapter 3, one question at a time, and remember what I miss.” The agent should:

1. Read `academia agent context --scope course --course "POL 2103" --json`. The `current_state.study` summaries expose existing sets, practice, topics, exams, and due counts without exposing answer keys.
2. Discover the contract with `academia study capabilities --json`, then read `academia study preferences --course "POL 2103" --json`.
3. List source metadata using `academia study context --course "POL 2103" --json`. Choose actual Library IDs from that response. Retrieve selected material with `--source ID`, optional `--query TOPIC`, and `--pages 12-25` for a PDF chapter. Use `--deep` when a question requires searching an entire selected reading or the full class selection; it scans all extractable text and PDF pages, locally OCRs textless pages when Poppler and Tesseract are installed, then returns ranked page-addressed passages with a coverage record. OCR is bounded to 180 pages and 180 seconds per retrieval; the dashboard reports incomplete coverage when a bound or extraction error leaves pages unread. A single deep retrieval call accepts up to 300 selected sources and returns up to 128 passages; the dashboard batches larger checked-source selections automatically. IDs are workspace-relative Library paths, not arbitrary filesystem access.
4. Generate a structured study payload using its own model. Submit through `study create --course "POL 2103" --source ID --input - --actor agent:codex --json`, passing the JSON through stdin. Use the same source/query/pages/limit selection used to retrieve the context, and include `--deep` again when the context was retrieved with deep search. This route does not invoke another model or consume an extra generation request.
5. Start with `study start --course "POL 2103" --set SET_ID --json`. Present one returned question at a time and wait for the student's response. Do not fetch or disclose the reference answer before an answer unless the student requests it.
6. Record the actual response with `study answer --course "POL 2103" --session SESSION_ID --item ITEM_ID --answer "EXACT OPTION" --actor agent:codex --json`. Multiple-choice answers are scored against the generated key, not an authoritative school grading system.
7. For written responses or flashcards, collect the response, call `study reveal`, explain the reference answer, and ask the student for `again`, `hard`, `good`, or `easy`. Record with `--rating`. These are explicitly self-assessed; never silently convert a model judgment into the student's rating. Revealed multiple-choice answers are also self-assessed rather than objective scores.
8. Resume the same records with `study session --course "POL 2103" --session SESSION_ID --json`. The dashboard can resume these sessions too.
9. Use `study overview`, `study plan --minutes 40`, and `agent changes` to keep the next session grounded in recorded progress.

Agents may retrieve a key explicitly with `study show --set SET_ID --reveal` when preparing teaching, editing, or reviewing. Ordinary `show` and unrevealed session questions omit answers, explanations and answer-bearing citation excerpts. This is a teaching contract, not an exam-security boundary.

### Example payload

`citation_ids` must come from the retrieved `chunks[].id`; they are checked against the selected source version. The following citation ID is illustrative and must be replaced.

```json
{
  "title": "Chapter 3 recall",
  "kind": "quiz",
  "items": [{
    "kind": "multiple_choice",
    "topic": "Sovereignty",
    "prompt": "Which definition matches sovereignty in this chapter?",
    "options": ["Supreme authority within a territory", "A method of counting votes"],
    "answer": "Supreme authority within a territory",
    "explanation": "The supplied chapter defines sovereignty in terms of supreme territorial authority.",
    "citation_ids": ["REPLACE_WITH_RETRIEVED_CHUNK_ID"]
  }],
  "connections": []
}
```

Set kinds: `quiz`, `practice_exam`, `flashcards`, `mind_map`, `explanation`. Item kinds: `multiple_choice`, `short_answer`, `flashcard`, `concept`. Flashcard sets contain flashcards; mind maps contain concepts. Map `connections` use zero-based item indexes with `from`, `to`, and `label`. Stored edges use stable item IDs. Practice exams are generated practice material, never actual or predicted school questions.

## Optional generation connections

## Dashboard chat

The dashboard Study chat currently uses the installed Codex CLI signed in with ChatGPT. Claude subscription sign-in is intentionally unavailable inside Academia: Anthropic says subscription OAuth is for Claude Code and other native Anthropic apps and does not permit third-party apps to route those credentials on users' behalf. Use Claude Code as a separate external agent with Academia's documented CLI/MCP interface, or use an Anthropic-approved integration if one becomes available. The disabled Claude option explains this in the provider menu. Academia does not read or store provider credentials and does not fall back to API billing. Codex offers model/reasoning controls and Standard/Fast speed; Fast may consume plan allowance faster. Selecting a class makes its readable source catalog available to the chat by default; the student can exclude individual sources or add material from another class. The chat retrieves a bounded, relevant subset of excerpts for each submitted message rather than sending every source body. It may also send bounded local task/coursework records and saved study/exam scope for the selected class so the assistant can help identify what to study. Source catalog entries are metadata only. Codex accepts PDF, DOCX/PPTX, plain-text, Markdown, CSV, JSON, and YAML files, plus common image attachments; up to five files and 32 MB total. PDFs are locally text-extracted from up to 50 pages (up to 120,000 characters); blank pages are locally OCRed when Poppler and Tesseract are installed. OCR text is flagged for verification. DOCX/PPTX and text files are locally extracted with bounded text limits. If the OCR tools are unavailable or limits are reached, omitted pages are identified.

Dashboard chat conversations are saved in browser IndexedDB on the current device and browser profile so they remain available after reloads and app restarts. The browser may clear local data, and the student can delete saved conversations from Chat History. Chat transcripts are not stored by the Academia API, in `.academia/`, or in the course workspace, and they are not included in study export/restore. Selected class/source references and lightweight action-proposal summaries with Review ids are retained with each conversation; uploaded attachments, extracted text, and image previews are not retained and need to be added again when reopening a chat. Each submitted message starts a short-lived session through the selected CLI; the current text conversation is sent as bounded context with the new turn. Before the model runs, the shared `study context --deep` interface scans every selected source in full, including all extractable PDF pages and blank pages OCRed locally. The dashboard batches large source selections into groups of at most 300; each source is limited to 64 million extracted characters, deep OCR is limited to 180 pages and 180 seconds per retrieval, and DOCX/PPTX extraction also honors the archive's XML safety limits. Academia sends up to 128 relevance-ranked, page-addressed passages, not the entire source corpus. The coverage record reports how many selected sources, PDF pages, and OCR pages were scanned, and any extraction or size limit is passed to the model so it can disclose incomplete coverage. Uploaded attachments are staged in a temporary directory and removed after the response. The model receives selected class metadata, bounded local coursework/study context, retrieved passages, and attached files only when the student submits. Ordinary chat uses temporary working directories and disables built-in tools, MCP servers, browser access, and session persistence. When Proposal mode is enabled, chat instead uses the Codex app-server with an isolated `CODEX_HOME` and only Academia's read tools plus independently granted task and/or import proposal tools; it may create exact Review/Action proposals but cannot approve, execute, copy, or write. Browser proposal runs stream tool and proposal progress into the conversation, provide a Stop control that interrupts the model run, and refresh each proposal card from Review. Task proposals can be edited in Review before approval. Settings provides an app-level ChatGPT device-code sign-in using Codex's official login flow; Academia never reads or stores credentials. Proposal runs stream tool and proposal progress and provide Stop in both the browser dashboard and the packaged Tauri shell. The app still cannot call external tools or perform Academia or school actions from chat.

`study generate` uses the same retrieval and create validation. Add `--deep` to scan all extractable text and PDF pages across up to 300 selected sources, with up to 128 ranked passages sent to the provider. Its response reports source and page coverage plus any extraction warnings; the durable study set remains source-linked in the course Study store. The dashboard creates study material through Study Chat and its Studio modes. The class-level Study history page is an archive for saved chats, generated sets, practice sessions, exam scope, and progress; it does not run source retrieval or generation when opened. Generation is explicitly invoked, never triggered by scanning, opening a class, reading context, or inspecting capabilities.

In dashboard Study chat, each Studio mode opens a setup panel for class, topic, source scope, and mode-specific options. The student can start with the whole class selected, use saved exam scope or topics marked for review as a focus, and refine the source selection. Generated quizzes and flashcards open as interactive practice sessions; explanations, study guides, comparisons, and mind maps open as saved source-linked material. Quiz answers and flashcard self-ratings are recorded through `study start/answer/reveal` and remain available with the class after the chat closes. The Studio generation action uses `study generate --deep`; incomplete source coverage is surfaced after generation.

```bash
academia study providers --json
academia study generate --course "POL 2103" --source LIBRARY_ID \
  --deep --limit 128 --kind quiz --count 8 --provider codex --instructions "Use comparisons and explain each answer." --json
academia study generate --course "POL 2103" --source LIBRARY_ID \
  --kind flashcards --provider local --model INSTALLED_MODEL \
  --protocol ollama --endpoint http://127.0.0.1:11434 --json
academia study generate --course "POL 2103" --source LIBRARY_ID \
  --provider local --model INSTALLED_MODEL --protocol openai-compatible \
  --endpoint http://127.0.0.1:1234/v1 --json
```

The Codex transport selects the newest installed Codex CLI from PATH or the standard ChatGPT macOS application bundle, uses its own ChatGPT login, removes API-key environment overrides, preserves an explicit study model, uses the inherited configured model when it is still in the current client catalog, otherwise uses that catalog's recommended model (shown in provider status), ignores other user configuration/tool integrations, disables shell/multi-agent/apps/plugins/web search, uses read-only execution in a temporary directory, requests schema-constrained output, and uses ephemeral sessions. Academia never reads, copies, stores, or handles Codex credentials. It fails instead of falling back to API billing. Plan limits and model access apply. A binary detection or login check does not prove an inference will succeed. Set `ACADEMIA_CODEX_CLI` to an executable path to choose a specific client. Selection does not change shell PATH, install software, edit global Codex configuration, or switch accounts.

Claude subscription credentials are not an Academia provider. An external Claude Code session may retrieve context and submit generated structured study material through `academia study create`, so reasoning and subscription use remain inside the native Claude Code client.

Local transports support Ollama's `/api/chat` schema format and OpenAI-compatible `/chat/completions` structured output. They accept HTTP loopback endpoints only, bypass environment HTTP proxies, reject redirects, and require an explicitly selected installed model. They do not download models or configure a local server. Detection does not claim a connection.

Only the bounded requested excerpts, recorded course task metadata, relevant study topics, selected exam scope, and recent student learning notes go to the requested provider. Original course files, profiles, credentials, and chat transcripts are not sent wholesale. Provider failures/invalid output save no set. Text extraction and keyword retrieval are local; no embedding API is needed. Non-deep PDF retrieval is limited to 100 selected pages; deep retrieval scans all pages, subject to text and OCR bounds. Scanned-page OCR uses local Poppler and Tesseract when available, marks OCR passages, and never alters source files. Citations prove source traceability, not that every generated claim is correct.

Official references: [Codex sign-in and local app-server](https://developers.openai.com/siwc/token-sharing-open-source/codex-app-server), [Anthropic Claude Code legal and compliance](https://code.claude.com/docs/en/legal-and-compliance), [Ollama chat](https://docs.ollama.com/api/chat).

## Preferences, edits and review

```bash
academia study configure --course "POL 2103" --payload-json \
  '{"instructions":"Ask one question at a time. Prefer application questions.","preferred_kind":"quiz","question_count":8,"provider":"codex"}' --json
academia study preferences --course "POL 2103" --json
academia study start --course "POL 2103" --set SET_ID --mode missed --json
academia study start --course "POL 2103" --set SET_ID --mode review --json
academia study flag --course "POL 2103" --set SET_ID --item ITEM_ID --reason "Two answers are defensible" --json
academia study revise --course "POL 2103" --set SET_ID --item ITEM_ID \
  --payload-json '{"prompt":"A clearer question","answer":"An existing exact option","explanation":"A corrected explanation."}' --json
```

`configure` stores desired study style/provider/model, not credentials or connection state. `generate` uses saved preferences unless an option overrides them. External agents should read them too.

`review` selects due and unseen eligible items; `missed` selects items whose latest result was incorrect or self-rated again/hard. Reviews use a transparent finite interval schedule; these are not mastery or validated learning-outcome predictions. Flagged questions are excluded from progress and scores, including past attempts, without deleting history. Edits create a new set version. `generate --supersedes SET_ID` can regenerate from current sources; the old set and attempts remain intact. Source fingerprints are rechecked; stale sets require an explicit `--allow-stale` for new sessions. Existing sessions retain their original question snapshots.

`study overview` reports source count and generation provenance for each set, and computes a `stale_source` warning for saved annotations when their cited source has changed or is unavailable. These freshness flags are read-time checks; they do not edit or delete student records. Keep the original note, citation, generated set, and attempts. Treat stale notes as historical context and verify them against current retrieved excerpts before relying on them; source-linked study material remains AI-generated and non-authoritative. The Study chat exposes a refresh control to recompute these checks while the class is open.

## Reading, feedback and exam scope

Use `study annotate` with the same selection arguments plus `--chunk CHUNK_ID --kind note|question|read|misconception|instructor_feedback --note TEXT`, optional `--topic` and `--quote`. Quotes must occur in the selected excerpt. Instructor feedback is student-reported unless independently confirmed; notes do not become institutional facts. The dashboard supports selecting text from excerpts and saving the same records.

`study exam-save --course COURSE --payload-json JSON --json` accepts `title`, optional `date` (`YYYY-MM-DD`), `format`, `topics`, `objectives`, and course `source_ids`. Supply an existing `id` to update the record. `study exam --course COURSE --exam ID --json` shows recorded reading and practice coverage, including unknown/unpracticed topics. `study generate --exam ID` uses that scope and its sources; it does not infer new exam requirements. The study planner combines due reviews, approaching recorded exams, difficult topics and existing coursework deadlines within the student's time budget. Plans are advisory and do not change a calendar.

## Local ownership, export and recovery

Durable student records live in `<semester>/<course>/06_KNOWLEDGE/STUDY/study.json`, outside rebuildable indexes. Writes use process locking and atomic replacement. Reads create no folders. All successful transitions append Activity. Course and semester identity are enforced on every command. Study records, answers and notes are academic learning data, not stored agent conversations. Study never submits coursework or modifies course grades.

`study export --course COURSE --format json|markdown --json` returns a suggested filename and `content`. Save it at a student-chosen destination; the dashboard downloads it. JSON includes sets, source excerpts/fingerprints, sessions, attempts, schedules, exam scope, preferences, and annotations. Markdown is a readable archive. Export is explicit and contains student learning data. Sources themselves still need the normal workspace backup.

`study restore --course COURSE --input BACKUP.json --json` restores a same-course/same-semester backup only into an empty study workspace. It never overwrites existing study records. Source paths are revalidated against the destination workspace and missing/changed source versions stay visibly stale.
