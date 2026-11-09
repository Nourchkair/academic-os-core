from __future__ import annotations

import copy
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from academia_os.config import save_config
from academia_os.study import STATE_RELATIVE, StudyService
from academia_os.study.cli import plan
from academia_os.study.providers import _local, generate
from tests.test_agent_neutral_core import minimal_config


@pytest.fixture
def workspace(tmp_path: Path):
    config = minimal_config(tmp_path)
    root = Path(config['academic']['root_directory'])
    course = root / 'Fall 2026' / 'POL 2103 - Politics'
    (course / '01_COURSE').mkdir(parents=True)
    (course / '05_REFERENCE').mkdir()
    source = course / '05_REFERENCE' / 'chapter.md'
    source.write_text('Sovereignty is supreme authority within a territory. Federalism divides authority between levels of government.\n', encoding='utf-8')
    service = StudyService(root, 'Fall 2026', 'POL 2103')
    return config, root, course, source, service


def context_and_payload(service: StudyService, source: Path, *, kind: str = 'quiz', item_kind: str = 'multiple_choice'):
    source_id = source.relative_to(service.root).as_posix()
    context = service.context(source_ids=[source_id])
    item = {'kind': item_kind, 'topic': 'Sovereignty', 'prompt': 'What is sovereignty?',
            'options': ['Supreme territorial authority', 'A voting system'] if item_kind == 'multiple_choice' else [],
            'answer': 'Supreme territorial authority', 'explanation': 'The chapter defines sovereignty as supreme authority within a territory.',
            'citation_ids': [context['chunks'][0]['id']]}
    return context, {'title': 'Chapter practice', 'kind': kind, 'items': [item], 'connections': []}


def test_reads_are_side_effect_free_and_sources_are_bounded(workspace):
    _, root, course, source, service = workspace
    assert service.overview()['sets'] == []
    assert not (course / '06_KNOWLEDGE').exists()
    assert not (root / '.academia').exists()
    assert service.context()['chunks'] == []
    context = service.context(source_ids=[source.relative_to(root).as_posix()])
    assert len(context['chunks']) == 1
    assert context['chunks'][0]['sha256']
    assert context['chunks'][0]['locator'].startswith('text · characters 1-')
    assert not (root / '.academia').exists()
    with pytest.raises(ValueError, match='belong'):
        service.context(source_ids=['Fall 2026/OTHER/secret.md'])
    with pytest.raises(ValueError, match='page selection'):
        service.context(source_ids=[source.relative_to(root).as_posix()], pages='1-2')['chunks'][0]


def test_agent_creates_then_resumes_and_grades_without_dashboard_or_model(workspace):
    config, root, course, source, service = workspace
    context, payload = context_and_payload(service, source)
    created = service.create(payload, context, actor='agent:codex')
    assert created['authoritative'] is False
    assert created['provenance'] == 'AI-GENERATED'
    assert (course / STATE_RELATIVE).is_file()
    assert 'answer' not in service.get_set(created['id'])['items'][0]
    session = service.start(created['id'])
    item_id = session['items'][0]['id']
    assert 'answer' not in session['items'][0]
    assert 'citations' not in session['items'][0]
    resumed = StudyService(root, 'Fall 2026', 'Politics').session(session['id'])
    assert resumed == session
    result = service.answer(session['id'], item_id, 'A voting system')
    assert result['attempt']['correct'] is False
    assert result['session']['status'] == 'completed'
    assert result['session']['items'][0]['answer'] == 'Supreme territorial authority'
    assert result['session']['score'] == {'correct': 0, 'graded': 1, 'self_assessed': 0}
    with pytest.raises(ValueError, match='already'):
        service.answer(session['id'], item_id, 'A voting system')
    assert service.overview()['topics'][0]['needs_review'] is True
    assert service.start(created['id'], mode='missed')['items'][0]['id'] == item_id
    assert not (course / '03_ASSIGNMENTS' / 'Assignment_History.json').exists()


def test_self_ratings_require_reveal_and_schedule_without_false_objective_score(workspace):
    _, _, _, source, service = workspace
    context, payload = context_and_payload(service, source, kind='flashcards', item_kind='flashcard')
    created = service.create(payload, context)
    session = service.start(created['id'])
    item_id = session['items'][0]['id']
    with pytest.raises(ValueError, match='reveal'):
        service.answer(session['id'], item_id, 'my answer', rating='good')
    service.reveal(session['id'], item_id)
    result = service.answer(session['id'], item_id, 'my answer', rating='good')
    assert result['attempt']['correct'] is None
    assert result['session']['score']['graded'] == 0
    assert result['session']['score']['self_assessed'] == 1
    review = next(iter(service.read()['reviews'].values()))
    assert review['due_at'] > datetime.now(timezone.utc).isoformat()
    with pytest.raises(ValueError, match='no eligible'):
        service.start(created['id'], mode='review')
    assert service.overview()['due_count'] == 0


def test_revealed_mcq_cannot_inflate_objective_score(workspace):
    _, _, _, source, service = workspace
    context, payload = context_and_payload(service, source)
    created = service.create(payload, context)
    session = service.start(created['id']); item_id = session['items'][0]['id']
    service.reveal(session['id'], item_id)
    with pytest.raises(ValueError, match='self-assessment'):
        service.answer(session['id'], item_id, 'Supreme territorial authority')
    attempt = service.answer(session['id'], item_id, 'Supreme territorial authority', rating='good')['attempt']
    assert attempt['basis'] == 'self-assessed'
    assert attempt['correct'] is None


def test_citations_and_source_versions_are_enforced_and_revisions_preserve_attempts(workspace):
    _, _, _, source, service = workspace
    context, payload = context_and_payload(service, source)
    invalid = copy.deepcopy(payload); invalid['items'][0]['citation_ids'] = ['fabricated']
    with pytest.raises(ValueError, match='citation_ids'):
        service.create(invalid, context)
    created = service.create(payload, context)
    session = service.start(created['id'])
    service.answer(session['id'], session['items'][0]['id'], 'Supreme territorial authority')
    source.write_text('Sovereignty means supreme territorial authority. New chapter edition.')
    assert service.overview()['sets'][0]['stale_sources'][0]['reason'] == 'changed'
    with pytest.raises(ValueError, match='sources changed'):
        service.start(created['id'])
    assert service.start(created['id'], allow_stale=True)['id']
    with pytest.raises(ValueError, match='source changed'):
        service.create(payload, context)
    fresh, new_payload = context_and_payload(service, source)
    revised = service.create(new_payload, fresh, supersedes=created['id'])
    assert revised['supersedes'] == created['id']
    assert len(service.read()['attempts']) == 1
    assert service.overview()['sets'][1]['stale_sources'] == []


def test_flagging_excludes_prior_scores_and_unblocks_a_session(workspace):
    _, _, _, source, service = workspace
    context, payload = context_and_payload(service, source)
    created = service.create(payload, context)
    session = service.start(created['id'])
    item_id = session['items'][0]['id']
    service.answer(session['id'], item_id, 'A voting system')
    service.flag(created['id'], item_id, 'Ambiguous wording')
    assert service.overview()['attempt_count'] == 0
    assert service.session(session['id'])['score']['graded'] == 0
    assert service.session(session['id'])['items'][0]['flag']['reason'] == 'Ambiguous wording'
    with pytest.raises(ValueError, match='no eligible'):
        service.start(created['id'])


def test_annotations_exams_coverage_and_backup_are_shared(workspace, tmp_path):
    _, _, _, source, service = workspace
    context, payload = context_and_payload(service, source)
    service.create(payload, context)
    citation = context['chunks'][0]
    with pytest.raises(ValueError, match='verbatim'):
        service.annotate(citation, note='wrong quote', quote='not present')
    service.annotate(citation, note='Read the definition', quote='Sovereignty', kind='read', topic='Sovereignty')
    service.annotate(citation, note='Explain definitions before applying them.', kind='instructor_feedback', topic='Sovereignty')
    exam = service.exam({'title': 'Midterm', 'date': '2026-10-25', 'format': 'Short essays', 'topics': ['Sovereignty', 'Federalism'], 'source_ids': [citation['source_id']]})
    coverage = service.exam_context(exam['id'])['coverage']
    assert coverage[0]['read_annotations'] == 1
    assert coverage[0]['practice']['attempt_count'] == 0
    assert coverage[1]['practice'] is None
    backup = service.export()
    archive = service.export('markdown')['content']
    assert 'SHA256' in archive and 'Explain definitions' in archive
    with pytest.raises(ValueError, match='empty'):
        service.restore(json.loads(backup['content']))
    other_root = tmp_path / 'restored'
    other_course = other_root / service.semester / service.course
    (other_course / '01_COURSE').mkdir(parents=True)
    restored = StudyService(other_root, service.semester, service.course)
    restored.restore(json.loads(backup['content']))
    assert restored.read()['sets'] == service.read()['sets']
    assert restored.overview()['sets'][0]['stale_sources'][0]['reason'] == 'unavailable'


def test_overview_marks_stale_notes_without_mutating_saved_provenance(workspace):
    _, _, _, source, service = workspace
    context, payload = context_and_payload(service, source)
    created = service.create(payload, context)
    citation = context['chunks'][0]
    service.annotate(citation, note='Recheck this definition before the midterm.', quote='Sovereignty', kind='note', topic='Sovereignty')

    fresh = service.overview()
    assert fresh['sets'][0]['source_count'] == 1
    assert fresh['sets'][0]['provenance'] == 'AI-GENERATED'
    assert fresh['sets'][0]['authoritative'] is False
    assert fresh['annotations'][0]['stale_source'] is None

    source.write_text('The updated chapter defines sovereignty as supreme authority over a territory.\n', encoding='utf-8')
    stale = service.overview()

    assert stale['sets'][0]['stale_sources'][0]['reason'] == 'changed'
    assert stale['annotations'][0]['stale_source']['reason'] == 'changed'
    assert stale['annotations'][0]['note'] == 'Recheck this definition before the midterm.'
    assert 'stale_source' not in service.read()['annotations'][0]
    assert service.read()['sets'][0]['id'] == created['id']


def test_corrupt_or_symlinked_study_state_is_never_overwritten(workspace, tmp_path):
    _, _, course, source, service = workspace
    service.path.parent.mkdir(parents=True)
    service.path.write_text('broken JSON')
    context, payload = context_and_payload(service, source)
    with pytest.raises(ValueError, match='unreadable'):
        service.create(payload, context)
    assert service.path.read_text() == 'broken JSON'
    outside = tmp_path / 'outside.json'; outside.write_text('{}')
    second = course / '05_REFERENCE' / 'linked.md'; second.symlink_to(outside)
    with pytest.raises(ValueError, match='belong'):
        service.context(source_ids=[second.relative_to(service.root).as_posix()])


def test_model_failures_never_save_and_local_transport_rejects_external_hosts(workspace, monkeypatch):
    _, _, _, source, service = workspace
    context, _ = context_and_payload(service, source)
    with pytest.raises(ValueError, match='loopback'):
        _local('prompt', {}, 'model', 'https://example.com', 'ollama')
    with pytest.raises(ValueError, match='no source'):
        generate({'chunks': []}, kind='quiz')
    def broken(*args, **kwargs):
        raise ValueError('provider failed')
    monkeypatch.setattr('academia_os.study.providers._codex', broken)
    with pytest.raises(ValueError, match='provider failed'):
        generate(context, kind='quiz')
    assert not service.path.exists()


def test_cli_contract_and_agent_context_work_with_no_dashboard(workspace):
    config, root, _, source, service = workspace
    profile = Path(config['runtime']['install_directory']) / 'profile.json'; save_config(profile, config)
    def cli(*args, payload=None):
        result = subprocess.run([sys.executable, '-m', 'academia_os', '--profile', str(profile), 'study', *args,
                                 '--course', 'POL 2103', '--json'], input=json.dumps(payload) if payload else None,
                                text=True, capture_output=True, cwd=Path(__file__).parents[1])
        assert result.returncode == 0, result.stdout + result.stderr
        return json.loads(result.stdout)
    source_id = source.relative_to(root).as_posix()
    context = cli('context', '--source', source_id)
    _, payload = context_and_payload(service, source)
    assert payload['items'][0]['citation_ids'][0] == context['chunks'][0]['id']
    created = cli('create', '--source', source_id, '--input', '-', payload=payload)
    started = cli('start', '--set', created['id'])
    assert 'answer' not in started['items'][0]
    cli('answer', '--session', started['id'], '--item', started['items'][0]['id'], '--answer', 'Supreme territorial authority')
    assert cli('overview')['attempt_count'] == 1
    result = subprocess.run([sys.executable, '-m', 'academia_os', '--profile', str(profile), 'agent', 'context', '--scope', 'course', '--course', 'POL 2103', '--json'], text=True, capture_output=True)
    assert result.returncode == 0, result.stdout + result.stderr
    summary = json.loads(result.stdout)['current_state']['study'][0]
    assert summary['attempt_count'] == 1
    assert 'items' not in summary['sets'][0]


def test_plan_respects_time_budget_and_exposes_unpracticed_scope(workspace):
    config, root, course, _, service = workspace
    today = datetime.now(timezone.utc).date()
    service.exam({'title': 'Midterm', 'date': (today + timedelta(days=2)).isoformat(), 'topics': ['Sovereignty']})
    snapshot = {'academic_root': str(root), 'semester': 'Fall 2026', 'courses': [{'id': course.name}], 'tasks': []}
    result = plan(config, snapshot, 40)
    assert result['minutes_planned'] <= 40
    assert result['blocks'][0]['exam_id']
    assert result['calendar_changes'] is False
    with pytest.raises(ValueError, match='between'):
        plan(config, snapshot, 0)


def test_plan_links_recommendations_to_current_sets_and_latest_attempts(workspace):
    config, root, course, source, service = workspace
    context, payload = context_and_payload(service, source)
    created = service.create(payload, context)
    session = service.start(created['id'])
    service.answer(session['id'], session['items'][0]['id'], 'A voting system')
    snapshot = {'academic_root': str(root), 'semester': 'Fall 2026', 'courses': [{'id': course.name}], 'tasks': []}

    result = plan(config, snapshot, 30)

    recommendation = next(block for block in result['blocks'] if block['action'] == 'missed')
    assert recommendation['set_id'] == created['id']
    assert 'Sovereignty' in recommendation['title']
    assert 'latest practice' in recommendation['reason']


def test_plan_recommends_due_review_for_the_matching_current_set(workspace):
    config, root, course, source, service = workspace
    context, payload = context_and_payload(service, source, kind='flashcards', item_kind='flashcard')
    created = service.create(payload, context)
    session = service.start(created['id'])
    item_id = session['items'][0]['id']
    service.reveal(session['id'], item_id)
    service.answer(session['id'], item_id, 'my answer', rating='again')
    state = service.read()
    state['reviews'][f"{created['id']}:{item_id}"]['due_at'] = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    service.store.write(state)
    snapshot = {'academic_root': str(root), 'semester': 'Fall 2026', 'courses': [{'id': course.name}], 'tasks': []}

    result = plan(config, snapshot, 30)

    recommendation = next(block for block in result['blocks'] if block['action'] == 'review')
    assert recommendation['set_id'] == created['id']
    assert '1 item is due' in recommendation['reason']


def test_manual_revision_preserves_old_attempts_and_validates_options(workspace):
    _, _, _, source, service = workspace
    context, payload = context_and_payload(service, source)
    original = service.create(payload, context)
    session = service.start(original['id'])
    item_id = session['items'][0]['id']
    service.answer(session['id'], item_id, 'A voting system')
    revised = service.revise(original['id'], item_id, {'prompt': 'Which definition matches the supplied chapter?'})
    assert revised['supersedes'] == original['id']
    assert service.session(session['id'])['items'][0]['prompt'] == 'What is sovereignty?'
    assert revised['items'][0]['prompt'] == 'Which definition matches the supplied chapter?'
    assert len(service.read()['attempts']) == 1
    with pytest.raises(ValueError, match='exactly match'):
        service.revise(original['id'], item_id, {'answer': 'not an offered option'})


def test_preferences_are_shared_and_reject_credentials(workspace):
    _, root, _, _, service = workspace
    assert service.preferences()['provider'] == 'codex'
    service.configure({'instructions': 'Ask me one question at a time.', 'preferred_kind': 'flashcards', 'question_count': 5})
    other_client = StudyService(root, service.semester, service.course)
    assert other_client.preferences()['question_count'] == 5
    assert other_client.overview()['preferences']['preferred_kind'] == 'flashcards'
    with pytest.raises(ValueError, match='credentials'):
        service.configure({'instructions': 'password=private-secret'})
    with pytest.raises(ValueError, match='credentials'):
        service.configure({'api_key': 'do-not-store'})
    with pytest.raises(ValueError, match='loopback'):
        service.configure({'endpoint': 'https://example.com'})
    assert other_client.preferences()['question_count'] == 5


def test_pdf_range_retrieval_preserves_page_and_does_not_search_other_pages(workspace):
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
    _, root, course, _, service = workspace
    source = course / '05_REFERENCE' / 'textbook.pdf'
    writer = PdfWriter()
    font = DictionaryObject({NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica')})
    for title in ('Sovereignty is supreme authority.', 'Federalism divides power.'):
        page = writer.add_blank_page(width=612, height=792)
        page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): writer._add_object(font)})})
        stream = DecodedStreamObject(); stream.set_data(f'BT /F1 12 Tf 72 720 Td ({title}) Tj ET'.encode())
        page[NameObject('/Contents')] = writer._add_object(stream)
    with source.open('wb') as handle:
        writer.write(handle)
    context = service.context(source_ids=[source.relative_to(root).as_posix()], pages='2')
    assert context['chunks'][0]['locator'].startswith('page 2')
    assert 'Federalism' in context['chunks'][0]['text']
    assert all('Sovereignty' not in chunk['text'] for chunk in context['chunks'])
    assert context['warnings']
    with pytest.raises(ValueError, match='existing range'):
        service.context(source_ids=[source.relative_to(root).as_posix()], pages='3')


def test_restore_rejects_cross_course_sources_and_false_authority(workspace, tmp_path):
    _, _, _, source, service = workspace
    context, payload = context_and_payload(service, source); service.create(payload, context)
    backup = json.loads(service.export()['content'])
    other_root = tmp_path / 'restore-invalid'
    (other_root / service.semester / service.course / '01_COURSE').mkdir(parents=True)
    destination = StudyService(other_root, service.semester, service.course)
    invalid = copy.deepcopy(backup); invalid['sets'][0]['sources'][0]['source_id'] = 'Fall 2026/OTHER/notes.md'
    with pytest.raises(ValueError, match='belong'):
        destination.restore(invalid)
    invalid = copy.deepcopy(backup); invalid['sets'][0]['authoritative'] = True
    with pytest.raises(ValueError, match='non-authoritative'):
        destination.restore(invalid)
    assert not destination.path.exists()


def test_course_and_semester_identity_never_fall_back(workspace):
    _, root, _, source, service = workspace
    context, payload = context_and_payload(service, source); service.create(payload, context)
    with pytest.raises(KeyError, match='not found'):
        StudyService(root, service.semester, 'UNKNOWN')
    with pytest.raises(KeyError, match='semester not found'):
        StudyService(root, 'Fall 2025', service.course)
    other = root / service.semester / 'HIS 101 - History' / '01_COURSE'; other.mkdir(parents=True)
    other_service = StudyService(root, service.semester, 'HIS 101')
    with pytest.raises(ValueError, match='match this course'):
        other_service.create(payload, context)
    assert other_service.overview()['sets'] == []
