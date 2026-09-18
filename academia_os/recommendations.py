"""Agent Setup Playbook registry.

The module name remains ``recommendations`` for import compatibility with the
first public registry contract. New callers should use ``list_playbooks`` and
``get_playbook``.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Mapping


RECOMMENDATION_IDS = (
    "daily_academic_brief",
    "course_source_sync",
    "academic_research_access",
    "calendar_awareness",
    "academic_email_awareness",
    "web_research",
    "community_research",
    "practice_material_discovery",
    "visual_learning_sources",
)

# Canonical public vocabulary. RECOMMENDATION_IDS remains as a compatibility
# alias for existing agents and scripts that consumed the original registry.
PLAYBOOK_IDS = RECOMMENDATION_IDS

PLAYBOOK_OWNERSHIP_MODEL = {
    "academia_os": "owns local academic state, student preferences, provenance, review, and safety boundaries",
    "playbook": "describes a desired student workflow and its safe implementation contract",
    "external_agent": "checks its own tools, obtains authorization, and implements or adapts the playbook",
    "student": "chooses workflows and authorizes external access or automation",
}

# Legacy response shape retained for existing integrations. New callers should
# use list_playbooks() and get_playbook().
OWNERSHIP_MODEL = {
    "academia": "defines capabilities, recommendations, recipes, and safety boundaries",
    "external_agent": "checks its own tools and implements an approved recipe",
    "student": "authorizes optional access and automations",
}


@dataclass(frozen=True)
class WorkflowRecipe:
    id: str
    title: str
    summary: str
    why_useful: str
    level: str
    requires: tuple[str, ...]
    optional_capabilities: tuple[str, ...]
    student_choices: tuple[str, ...]
    suggested_defaults: Mapping[str, Any]
    setup_steps: tuple[Mapping[str, Any], ...]
    safety_rules: tuple[str, ...]
    verification_steps: tuple[str, ...]
    maintenance: tuple[str, ...]
    academia_interfaces: tuple[str, ...]
    adaptation_notes: tuple[str, ...]
    authority_notes: Mapping[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        value: dict[str, Any] = {
            "id": self.id,
            "title": self.title,
            "summary": self.summary,
            "why_useful": self.why_useful,
            "level": self.level,
            "requires": list(self.requires),
            "optional_capabilities": list(self.optional_capabilities),
            "student_choices": list(self.student_choices),
            "suggested_defaults": deepcopy(dict(self.suggested_defaults)),
            "setup_steps": [deepcopy(dict(step)) for step in self.setup_steps],
            "safety_rules": list(self.safety_rules),
            "verification_steps": list(self.verification_steps),
            "maintenance": list(self.maintenance),
            "academia_interfaces": list(self.academia_interfaces),
            "adaptation_notes": list(self.adaptation_notes),
        }
        if self.authority_notes is not None:
            value["authority_notes"] = deepcopy(dict(self.authority_notes))
        return value


def _step(step_id: str, instruction: str, *, approval: bool = False) -> dict[str, Any]:
    return {
        "id": step_id,
        "instruction": instruction,
        "student_approval_required": approval,
        "owner": "external_agent",
    }


_RECIPES = (
    WorkflowRecipe(
        id="daily_academic_brief",
        title="Daily Academic Brief",
        summary="A concise recurring briefing built from Academia context, attention, and approved optional sources.",
        why_useful="Gives the student one calm place to see what is due, what changed, and what deserves attention without manufacturing urgency.",
        level="recommended",
        requires=("academia_cli", "scheduler_or_automation"),
        optional_capabilities=("calendar_read", "academic_email_read", "course_platform_read", "local_delivery"),
        student_choices=("brief time", "daily or weekdays cadence", "detail level", "include calendar", "include academic email", "check course sources first"),
        suggested_defaults={"time": "09:00", "timezone": "local", "cadence": "daily", "detail": "compact", "include_calendar": False, "include_academic_email": False, "check_course_sources_first": False},
        setup_steps=(
            _step("inspect", "Read Academia capabilities and Agent Setup Playbooks, then compare them with the agent's own tools."),
            _step("choose", "Show the student the schedule, cadence, detail, and optional source choices before proposing automation.", approval=True),
            _step("schedule", "After approval, create the recurring job using the agent's own scheduler or automation mechanism.", approval=True),
            _step("collect", "At each run, read the changes cursor, today compact context, and attention; read optional sources only when authorized and available."),
            _step("deliver", "Deliver one concise briefing that separates confirmed, likely, unverified, and historical information."),
        ),
        safety_rules=(
            "Do not manufacture urgency or turn an unverified item into a confirmed deadline.",
            "Do not submit coursework, quizzes, exams, forms, or discussions.",
            "Do not send school-account messages or contact academic people.",
            "Do not change external systems without the required student approval.",
            "Academia OS does not create or own the schedule; the external agent owns the automation.",
        ),
        verification_steps=(
            "Confirm the agent's schedule and next run are understood by the student.",
            "Run the Academia context and attention commands successfully before the first scheduled delivery.",
            "Show the student exactly which optional sources will and will not be included.",
            "Confirm the change cursor advances only after a brief is successfully produced.",
        ),
        maintenance=("Review the cadence and included sources each term.", "Preserve and resume from the last successful changes cursor.", "Report failed runs instead of silently skipping them."),
        academia_interfaces=("academia agent capabilities --json", "academia agent playbooks --json", "academia agent changes --json", "academia agent context --scope today --detail compact --json", "academia agent attention --json"),
        adaptation_notes=("A scheduler, task runner, or agent-native automation mechanism may be used.", "The implementation may change delivery mechanics while preserving the briefing contents, authorization, provenance, and verification behavior."),
        authority_notes={"course_authoritative_sources_outrank": ["official course material", "verified student records", "general web or community context"]},
    ),
    WorkflowRecipe(
        id="course_source_sync",
        title="Course Source Sync",
        summary="A vendor-neutral playbook for an external agent to check authorized course portals and import meaningful new material.",
        why_useful="Keeps syllabi, announcements, readings, slides, and assignment instructions discoverable without making Academia OS responsible for school-platform access.",
        level="recommended",
        requires=("academia_cli", "course_platform_read", "file_download"),
        optional_capabilities=("browser_read", "scheduler_or_automation", "course_platform_source_urls"),
        student_choices=("which course platforms", "which courses", "which material categories", "manual or recurring checks", "whether downloaded files may be imported"),
        suggested_defaults={"cadence": "student_choice", "read_only": True, "import_new_material": True, "preserve_original": True},
        setup_steps=(
            _step("authorize", "Ask the student to authorize the external agent's read-only course-platform access in that agent's own environment.", approval=True),
            _step("scope", "Confirm the allowed platforms, courses, material types, and whether file downloads and Academia imports are wanted.", approval=True),
            _step("check", "Inspect announcements and course pages, detect new or changed material, and retrieve only permitted files."),
            _step("import", "Preserve source URL, course, retrieval time, and provenance where available, then use the existing Academia import path."),
            _step("surface", "Use supported extraction where appropriate and surface meaningful changes to the agent and student."),
        ),
        safety_rules=(
            "Read course sources only through the student's authorized external agent environment.",
            "Never submit assignments, quizzes, exams, or forms; post discussions; or send course messages.",
            "Never change course settings, enrollment, payments, or other external records.",
            "Never expose passwords, MFA codes, cookies, session tokens, or API keys to Academia OS.",
            "Preserve originals, provenance, source authority, and uncertainty during import.",
        ),
        verification_steps=("Confirm the external agent can read the selected course source without sending writes.", "Verify a retrieved file's source URL/course/time metadata before import.", "Confirm the imported copy and original source remain distinct.", "Show the student what changed and what remains unverified."),
        maintenance=("Review course scope after enrollment changes.", "Remove stale source permissions in the external agent when a course ends.", "Use a student-chosen cadence; one or two checks per day is only a suggestion."),
        academia_interfaces=("academia agent context --scope semester --json", "academia agent attention --json", "academia import", "academia agent changes --json", "academia file-preview"),
        adaptation_notes=("Brightspace, Canvas, Moodle, Blackboard, and similar portals are examples, not core dependencies.", "The external agent may use a visible browser handoff, an approved platform API, or another read-only tool it controls."),
        authority_notes={"official_course_sources_are_authoritative": True, "general_web_is_not_a_substitute": True},
    ),
    WorkflowRecipe(
        id="academic_research_access",
        title="Academic Library / Scholarly Research",
        summary="A source-faithful playbook for an external agent using legitimate library, publisher, DOI, repository, and open-access routes.",
        why_useful="Improves research quality by helping the agent find legitimate sources and preserve edition, authority, and retrieval information.",
        level="recommended",
        requires=("academia_cli", "academic_research_access"),
        optional_capabilities=("university_library_search", "browser_read", "source_download", "doi_lookup", "open_access_search"),
        student_choices=("which library or discovery system", "whether browser handoff is allowed", "source types", "download and import scope", "edition verification strictness"),
        suggested_defaults={"preferred_source_order": ["university_library", "publisher", "doi", "institutional_repository", "legitimate_open_access", "reputable_public_web"], "verify_edition_when_material": True},
        setup_steps=(_step("scope", "Ask which research sources and library routes the student wants the agent to use.", approval=True), _step("search", "Search the preferred hierarchy and record the source/version identity before retrieval."), _step("verify", "Compare requested and retrieved edition metadata when the edition matters."), _step("preserve", "Keep source authority, URL or identifier, version, retrieval time, and uncertainty with the research result."), _step("share", "Offer a bounded source reference or import through Academia without dumping source bodies into agent context.")),
        safety_rules=("Do not bypass paywalls, access controls, or institutional restrictions.", "Do not obtain unauthorized copies.", "Do not claim an unverified edition is the required edition.", "Keep official course evidence above general research material for course-specific facts.", "Do not expose library credentials or session data to Academia OS."),
        verification_steps=("Confirm the source route and access scope with the student.", "Verify requested versus retrieved title, author, edition, and publication metadata when relevant.", "Confirm source references and provenance are preserved in any Academia import or artifact."),
        maintenance=("Recheck edition requirements when an assignment or syllabus changes.", "Prefer stable identifiers such as DOI or library record IDs over copied search snippets."),
        academia_interfaces=("academia agent context --scope course --json", "academia library", "academia file-preview", "academia verify-source", "academia artifact create"),
        adaptation_notes=("Omni is an example of a university discovery system, not an Academia integration.", "The external agent may adapt the hierarchy to the library and tools available to the student."),
        authority_notes={"preferred_hierarchy": ["university_library", "publisher", "doi", "institutional_repository", "legitimate_open_access", "reputable_public_web"], "course_facts_require_authority": True},
    ),
    WorkflowRecipe(
        id="calendar_awareness",
        title="Calendar Awareness",
        summary="A planning playbook that lets an external agent incorporate classes, exams, deadlines, appointments, and study blocks.",
        why_useful="Adds time-aware planning while keeping calendar ownership and any writes with the student's authorized external agent.",
        level="optional",
        requires=("calendar_read",),
        optional_capabilities=("calendar_write", "scheduler_or_automation"),
        student_choices=("read only or read/write", "which calendars", "whether study blocks may be suggested", "whether event creation may occur after approval"),
        suggested_defaults={"access": "read_only", "calendars": "student_choice", "suggest_study_blocks": False, "create_events_after_approval": False},
        setup_steps=(_step("scope", "Ask which calendars and whether the agent may read or propose calendar changes.", approval=True), _step("read", "Read calendar context through the external agent and distinguish it from Academia-confirmed academic facts."), _step("propose", "For any write, check duplicates and show the exact proposed event before asking for approval.", approval=True), _step("write", "If approved and supported, perform the change through the external calendar tool and not through Academia OS.", approval=True), _step("verify", "Read the external calendar again and report the result.")),
        safety_rules=("Academia OS does not claim calendar read or write access merely because this playbook exists.", "Calendar writes require duplicate checking, explicit approval, and post-write verification.", "Do not create events silently or treat an external calendar item as authoritative course evidence without provenance."),
        verification_steps=("Confirm selected calendars and access mode.", "Show the next read or proposed event to the student.", "For writes, verify the event ID or equivalent external result after approval."),
        maintenance=("Review calendar scope each term.", "Recheck duplicate behavior after changing external calendar tooling.", "Keep read-only access as the fallback when writes are not supported."),
        academia_interfaces=("academia agent context --scope today --json", "academia agent attention --json", "academia agent changes --json"),
        adaptation_notes=("The external agent chooses its calendar client and write mechanism.", "A calendar provider is never inferred from Academia configuration."),
    ),
    WorkflowRecipe(
        id="academic_email_awareness",
        title="Academic Email Awareness",
        summary="A read/search-oriented playbook for noticing relevant academic email changes without sending school messages.",
        why_useful="Helps an authorized agent notice course announcements, deadline updates, and forwarded school messages that the student wants included in planning.",
        level="optional",
        requires=("academic_email_read",),
        optional_capabilities=("email_search", "local_message_import"),
        student_choices=("which mailbox or labels", "which senders or courses", "lookback window", "whether messages may become source references"),
        suggested_defaults={"access": "read_search_only", "lookback": "student_choice", "include_message_bodies": False},
        setup_steps=(_step("scope", "Ask which academic mail sources, labels, senders, and lookback window are permitted.", approval=True), _step("search", "Search or read relevant messages through the external agent's own mail tools."), _step("classify", "Separate confirmed message facts from agent interpretation and preserve sender/date/source references."), _step("surface", "Include only relevant changes in the agent's briefing or attention response.")),
        safety_rules=("Academia's school-message rule remains in force: do not send school-account messages or contact professors, students, TAs, or staff.", "Favor read/search access over broad mail permissions.", "Do not expose passwords, MFA codes, cookies, session tokens, or API keys to Academia OS.", "Email evidence does not automatically override official course material without authority and verification."),
        verification_steps=("Confirm read/search scope with the student.", "Show which messages or labels will be considered.", "Verify each surfaced academic change has a sender/date reference and an uncertainty label."),
        maintenance=("Review sender and label scope after each term.", "Remove stale mailbox permissions in the external agent when no longer needed.", "Keep message retrieval bounded and avoid unnecessary body retention."),
        academia_interfaces=("academia agent context --scope today --json", "academia agent attention --json", "academia agent changes --json"),
        adaptation_notes=("Gmail is an example external mail source, not an Academia integration.", "Forwarded messages may be imported manually through the normal provenance-preserving import path."),
        authority_notes={"email_is_contextual_until_verified": True},
    ),
    WorkflowRecipe(
        id="web_research",
        title="General Web Research",
        summary="A source-aware playbook for supplementing academic work with legitimate public and current information.",
        why_useful="Provides background, official public information, definitions, and current context when course-authoritative sources do not answer the question.",
        level="optional",
        requires=("public_web_search",),
        optional_capabilities=("official_source_lookup", "web_page_retrieval", "source_download"),
        student_choices=("whether public web research is allowed", "source domains", "current-information topics", "whether source references should be preserved"),
        suggested_defaults={"prefer_official_sources": True, "preserve_source_references": True, "course_facts_require_course_source": True},
        setup_steps=(_step("scope", "Ask whether public web research is wanted and which source domains or topics are in scope.", approval=True), _step("search", "Search legitimate public sources and prefer official or primary sources."), _step("compare", "Keep general web context separate from official course evidence."), _step("cite", "Preserve URLs, titles, retrieval time, and authority notes in the agent response or selected Academia artifact.")),
        safety_rules=("Do not present general web material as official course truth.", "Do not bypass access controls or claim unsupported freshness.", "Preserve source authority and distinguish current, likely, unverified, and historical information.", "Do not expose private browsing credentials or session data to Academia OS."),
        verification_steps=("Confirm source authority and retrieval date.", "Check that course-specific claims are supported by official or verified course evidence.", "Verify any imported or generated material retains source references."),
        maintenance=("Recheck current-information sources when facts can change.", "Review domain allowlists or search scope with the student."),
        academia_interfaces=("academia agent context --scope course --json", "academia agent attention --json", "academia artifact create"),
        adaptation_notes=("The external agent chooses its web search and retrieval tools.", "Public web research supplements rather than replaces the course source hierarchy."),
        authority_notes={"course_specific_authority": "official_course_evidence_outranks_general_web", "current_public_information": "must_include_retrieval_date"},
    ),
    WorkflowRecipe(
        id="community_research",
        title="Community Research",
        summary="A bounded playbook for using Reddit, student forums, and public course communities as informal context.",
        why_useful="Can reveal common student questions, study strategies, difficult topics, and potentially useful public resources.",
        level="optional",
        requires=("community_search",),
        optional_capabilities=("public_forum_read", "web_retrieval"),
        student_choices=("which communities", "topic scope", "whether informal tips may appear in briefings", "whether links should be preserved"),
        suggested_defaults={"authority": "non_authoritative_context", "read_only": True, "include_in_course_facts": False},
        setup_steps=(_step("scope", "Ask which public communities and topics are acceptable for informal context.", approval=True), _step("search", "Search public discussions without treating participation as course authority."), _step("label", "Label community claims as informal, contextual, and unverified unless independently supported."), _step("surface", "Offer strategies or questions for student review, not official deadlines or requirements.")),
        safety_rules=("Community information is non-authoritative context.", "It cannot establish official deadlines, professor requirements, grading policy, textbook edition, or exam rules.", "Do not post, reply, vote, message, or impersonate the student.", "Respect public-site rules, privacy, copyright, and access restrictions."),
        verification_steps=("Confirm the source is a public community the student approved.", "Check any important claim against official course evidence.", "Verify the response labels community material as informal and non-authoritative."),
        maintenance=("Review community scope and relevance each term.", "Discard stale advice when official course information changes."),
        academia_interfaces=("academia agent context --scope course --json", "academia agent attention --json", "academia artifact create"),
        adaptation_notes=("Reddit and student forums are examples only.", "The external agent may use any public community reader that preserves the same authority and no-post boundaries."),
        authority_notes={"authority": "non_authoritative_context", "cannot_establish": ["official deadline", "professor requirement", "grading policy", "required textbook edition", "exam rules"]},
    ),
    WorkflowRecipe(
        id="practice_material_discovery",
        title="Practice Material Discovery",
        summary="A provenance-preserving playbook for finding legitimate public practice material and creating clearly labeled new study aids.",
        why_useful="Expands study options with practice exams, sample questions, study guides, drills, and flashcards without confusing unofficial material with professor-issued work.",
        level="optional",
        requires=("academia_cli", "public_practice_search"),
        optional_capabilities=("course_platform_read", "library_search", "public_web_search", "document_download"),
        student_choices=("practice topics", "material sources", "official versus unofficial preference", "artifact type", "whether generated material may be saved"),
        suggested_defaults={"prefer_legitimate_public_sources": True, "label_unofficial_material": True, "generate_new_material_only": True, "preserve_provenance": True},
        setup_steps=(_step("scope", "Ask what topics and legitimate public material types the student wants.", approval=True), _step("discover", "Find past exams, sample exams, practice tests, public assignments, study guides, question banks, or similar material without bypassing restrictions."), _step("classify", "Record whether each source is official, unofficial, public, or unverified."), _step("generate", "Create new AI-generated practice material only through Academia's create-only artifact path.", approval=True), _step("review", "Show source references, provenance, and the disclaimer that generated material is not a professor-issued exam.")),
        safety_rules=("Respect copyright, access restrictions, and source licenses.", "Never claim AI-generated practice material is an actual professor-issued exam.", "Never claim a found document belongs to the current course unless verified.", "Preserve provenance and distinguish official from unofficial material.", "Do not retrieve restricted exams or use material to submit coursework."),
        verification_steps=("Verify the source is legitimately accessible.", "Confirm course and edition identity when making a course-specific claim.", "Inspect the generated artifact's provenance, source references, and AI-generated label.", "Confirm the student understands the artifact is practice material, not an official assessment."),
        maintenance=("Retire or relabel material when a course edition changes.", "Keep generated practice artifacts separate from original or external sources.", "Recheck public source availability instead of retaining unauthorized copies."),
        academia_interfaces=("academia agent context --scope course --json", "academia agent attention --json", "academia artifact create", "academia agent changes --json"),
        adaptation_notes=("The external agent may use a search tool, library route, or public repository.", "The generation mechanics may vary, but the create-only provenance contract must remain unchanged."),
        authority_notes={"official_assessment_status": "must_be_verified", "generated_material": "AI_GENERATED_non_authoritative"},
    ),
    WorkflowRecipe(
        id="visual_learning_sources",
        title="Visual / Media Learning Sources",
        summary="A supplementary-learning playbook for finding public diagrams, videos, lectures, maps, charts, documentaries, and demonstrations.",
        why_useful="Some concepts become easier to understand through visual explanations or demonstrations alongside written course material.",
        level="optional",
        requires=("public_media_search",),
        optional_capabilities=("video_retrieval", "image_retrieval", "public_web_search", "media_download"),
        student_choices=("media types", "topic scope", "source domains", "whether links or notes should be preserved", "whether generated visual study aids are wanted"),
        suggested_defaults={"supplementary_only": True, "preserve_provenance": True, "download": False, "prefer_public_sources": True},
        setup_steps=(_step("scope", "Ask which visual formats and topics would improve the student's learning.", approval=True), _step("discover", "Find legitimate public media and record title, creator, URL, date, and authority context."), _step("label", "Mark media as supplementary unless it is verified as an assigned or official course source."), _step("integrate", "Summarize or link the material without replacing course-authoritative evidence.")),
        safety_rules=("Supplementary media does not become an official course source without verification.", "Respect copyright, access restrictions, and public-site rules.", "Preserve provenance and distinguish external media from AI-generated material.", "Do not use media retrieval to access restricted course content or submit work."),
        verification_steps=("Verify the public source and creator where relevant.", "Confirm any course-specific claim against official course material.", "Check that saved notes or artifacts retain the source link and supplementary label."),
        maintenance=("Recheck public links when a study plan is reused.", "Remove stale or unavailable references rather than presenting them as current."),
        academia_interfaces=("academia agent context --scope course --json", "academia agent attention --json", "academia artifact create"),
        adaptation_notes=("The external agent may use video, image, map, or public media search tools.", "A media source is an input to learning, not an integration owned by Academia OS."),
        authority_notes={"default": "supplementary_unless_official", "course_authority": "verified_course_source"},
    ),
)


def _validate_recipe(recipe: WorkflowRecipe) -> None:
    if recipe.id not in RECOMMENDATION_IDS or not recipe.title.strip():
        raise ValueError(f"invalid recommended workflow identity: {recipe.id}")
    if recipe.level not in {"recommended", "optional", "advanced"}:
        raise ValueError(f"invalid recommended workflow level: {recipe.id}")
    if not recipe.requires or not recipe.safety_rules or not recipe.verification_steps or not recipe.academia_interfaces:
        raise ValueError(f"recommended workflow is missing required contract fields: {recipe.id}")
    if any(not isinstance(value, str) or not value.strip() for value in (*recipe.requires, *recipe.optional_capabilities, *recipe.safety_rules, *recipe.verification_steps, *recipe.maintenance, *recipe.academia_interfaces, *recipe.adaptation_notes)):
        raise ValueError(f"recommended workflow contains an empty contract value: {recipe.id}")


for _recipe_definition in _RECIPES:
    _validate_recipe(_recipe_definition)
if tuple(recipe.id for recipe in _RECIPES) != RECOMMENDATION_IDS:
    raise ValueError("recommended workflow registry order is unstable")


def list_recommendations() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "ownership": deepcopy(OWNERSHIP_MODEL),
        "workflows": [recipe.as_dict() for recipe in _RECIPES],
    }


def get_recipe(workflow_id: str) -> dict[str, Any]:
    for recipe in _RECIPES:
        if recipe.id == workflow_id:
            return recipe.as_dict()
    raise KeyError(f"unknown recommended workflow: {workflow_id}")


def _playbook_payload(recipe: WorkflowRecipe) -> dict[str, Any]:
    value = recipe.as_dict()
    value["kind"] = "agent_setup_playbook"
    value["execution_owner"] = "external_agent"
    value["ownership"] = deepcopy(PLAYBOOK_OWNERSHIP_MODEL)
    return value


def list_playbooks() -> dict[str, Any]:
    """Return the canonical, read-only Agent Setup Playbook registry."""
    return {
        "schema_version": 1,
        "kind": "agent_setup_playbook_registry",
        "ownership": deepcopy(PLAYBOOK_OWNERSHIP_MODEL),
        "playbooks": [_playbook_payload(recipe) for recipe in _RECIPES],
    }


def get_playbook(playbook_id: str) -> dict[str, Any]:
    """Return one canonical Agent Setup Playbook without touching workspace state."""
    for recipe in _RECIPES:
        if recipe.id == playbook_id:
            return _playbook_payload(recipe)
    raise KeyError(f"unknown agent setup playbook: {playbook_id}")
