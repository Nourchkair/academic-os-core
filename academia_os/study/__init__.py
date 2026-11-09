"""Shared study domain for agents, CLI and dashboard. No model is required."""
from __future__ import annotations

import copy
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from ..activity import ActivityLog
from ..course_identity import resolve_course_directory
from ..state import JsonStateStore
from ..workflow_preferences import _validate_text as validate_preference_text
from .sources import fingerprint, retrieve, safe_path

KINDS = ('quiz', 'practice_exam', 'flashcards', 'mind_map', 'explanation')
ITEM_KINDS = ('multiple_choice', 'short_answer', 'flashcard', 'concept')
RATINGS = ('again', 'hard', 'good', 'easy')
STATE_RELATIVE = Path('06_KNOWLEDGE/STUDY/study.json')


def now() -> datetime:
    return datetime.now(timezone.utc)


def text(value: Any, field: str, maximum: int = 2000, *, optional: bool = False) -> str:
    if optional and value is None:
        return ''
    if not isinstance(value, str) or (not optional and not value.strip()) or len(value) > maximum or '\x00' in value:
        raise ValueError(f'{field} must be text of 1–{maximum} characters')
    return value.strip()


def strings(value: Any, field: str, maximum: int = 50) -> list[str]:
    if not isinstance(value, list) or len(value) > maximum:
        raise ValueError(f'{field} must be a list of at most {maximum} text values')
    return list(dict.fromkeys(text(item, field, 200) for item in value))


def date_value(value: Any, field: str) -> str:
    value = text(value, field, 10)
    try:
        result = datetime.strptime(value, '%Y-%m-%d').date().isoformat()
    except ValueError as exc:
        raise ValueError(f'{field} must use YYYY-MM-DD') from exc
    if result != value:
        raise ValueError(f'{field} must use YYYY-MM-DD')
    return result


class StudyService:
    def __init__(self, root: Path, semester: str, course: str) -> None:
        self.root = Path(root).resolve()
        self.semester = semester
        self.course = resolve_course_directory(self.root, semester, course).name
        self.directory = resolve_course_directory(self.root, semester, self.course)
        self.path = safe_path(self.root, self.directory / STATE_RELATIVE)
        self.store = JsonStateStore(self.path)

    def _empty(self) -> dict[str, Any]:
        return {'schema_version': 1, 'course_id': self.course, 'semester': self.semester,
                'sets': [], 'sessions': [], 'attempts': [], 'reviews': {}, 'annotations': [], 'exams': []}

    def _validate_state(self, state: Any) -> dict[str, Any]:
        if not isinstance(state, dict) or state.get('schema_version') != 1 or state.get('course_id') != self.course or state.get('semester') != self.semester:
            raise ValueError('unsupported study state; preserve and restore it from an export')
        if set(state) - {'schema_version', 'course_id', 'semester', 'sets', 'sessions', 'attempts', 'reviews', 'annotations', 'exams', 'preferences'}:
            raise ValueError('study state contains unsupported fields')
        for key in ('sets', 'sessions', 'attempts', 'annotations', 'exams'):
            if not isinstance(state.get(key), list):
                raise ValueError(f'invalid study state: {key}')
        if not isinstance(state.get('reviews'), dict):
            raise ValueError('invalid study review state')
        return state

    def read(self) -> dict[str, Any]:
        safe_path(self.root, self.path)
        if not self.path.exists():
            return self._empty()
        # Do not let JsonStateStore's forgiving default erase damaged student records.
        try:
            return self._validate_state(json.loads(self.path.read_text(encoding='utf-8')))
        except (json.JSONDecodeError, UnicodeError) as exc:
            raise ValueError('study state is unreadable; no records have been replaced') from exc

    def _write(self, event: str, transform: Callable[[dict[str, Any]], dict[str, Any]], actor: str = 'user') -> dict[str, Any]:
        actor = text(actor, 'actor', 80)
        safe_path(self.root, self.path)
        result: dict[str, Any] = {}
        if self.store.lock_path.is_symlink():
            raise ValueError('study lock cannot be a symbolic link')
        with self.store.locked():
            state = self.read()
            result = transform(state)
            self.store._write_unlocked(state)
        ActivityLog(self.root / '.academia/activity.jsonl').append(
            event_type=f'study.{event}', title=f"Study: {event.replace('_', ' ')}", course=self.course,
            source=self.path.relative_to(self.root).as_posix(), actor=actor, confidence='unverified' if event == 'set_created' else 'user-confirmed',
            details={'id': result.get('id'), 'academic_submission': False})
        return result

    @staticmethod
    def _find(records: list[dict[str, Any]], record_id: str) -> dict[str, Any]:
        found = next((item for item in records if item['id'] == record_id), None)
        if found is None:
            raise KeyError(f'study record not found in this course: {record_id}')
        return found

    @staticmethod
    def _preferences(patch: dict[str, Any]) -> dict[str, Any]:
        defaults = {'instructions': '', 'preferred_kind': 'quiz', 'question_count': 8,
                    'provider': 'codex', 'model': '', 'endpoint': 'http://127.0.0.1:11434', 'protocol': 'ollama'}
        if not isinstance(patch, dict) or set(patch) - set(defaults):
            raise ValueError('unsupported study preference; credentials and connection status are never stored')
        preferences = {**defaults, **patch}
        validate_preference_text(preferences['instructions'], 'instructions', max_length=2000)
        validate_preference_text(preferences['model'], 'model', max_length=200)
        if preferences['preferred_kind'] not in KINDS or type(preferences['question_count']) is not int or not 1 <= preferences['question_count'] <= 30:
            raise ValueError('select a supported study kind and 1–30 questions')
        if preferences['provider'] not in {'codex', 'local'} or preferences['protocol'] not in {'ollama', 'openai-compatible'}:
            raise ValueError('unsupported study provider or protocol')
        from urllib.parse import urlsplit
        endpoint = urlsplit(text(preferences['endpoint'], 'endpoint', 500))
        if endpoint.scheme != 'http' or endpoint.hostname not in {'localhost', '127.0.0.1', '::1'} or endpoint.username or endpoint.password or endpoint.query or endpoint.fragment:
            raise ValueError('local model endpoint must be an HTTP loopback URL without credentials')
        return preferences

    def preferences(self) -> dict[str, Any]:
        return self._preferences(self.read().get('preferences', {}))

    def configure(self, patch: dict[str, Any], *, actor: str = 'user') -> dict[str, Any]:
        self._preferences(patch)
        if not patch:
            raise ValueError('provide at least one study preference')
        def save(state: dict[str, Any]) -> dict[str, Any]:
            # Validate and merge under the lock so clients do not erase each other's edits.
            updated = {**state.get('preferences', {}), **patch}
            effective = self._preferences(updated)
            state['preferences'] = updated
            return {'id': self.course, 'preferences': effective}
        return self._write('preferences_saved', save, actor)

    def context(self, **selection: Any) -> dict[str, Any]:
        return retrieve(self.root, self.semester, self.course, **selection)

    def stale_sources(self, study_set: dict[str, Any], cache: dict[str, str | None] | None = None) -> list[dict[str, str]]:
        changed = []
        cache = {} if cache is None else cache
        for source in study_set['sources']:
            try:
                path = safe_path(self.root, Path(source['source_id']))
                if source['source_id'] not in cache:
                    cache[source['source_id']] = fingerprint(path)
                current = cache[source['source_id']]
            except (OSError, ValueError):
                current = None
            if current != source['sha256']:
                changed.append({'source_id': source['source_id'], 'reason': 'changed' if current else 'unavailable'})
        return changed

    def create(self, payload: dict[str, Any], context: dict[str, Any], *, actor: str = 'agent', supersedes: str | None = None) -> dict[str, Any]:
        if not isinstance(payload, dict) or payload.get('kind') not in KINDS:
            raise ValueError(f'study kind must be one of {KINDS}')
        title = text(payload.get('title'), 'title', 200)
        raw_items = payload.get('items')
        if not isinstance(raw_items, list) or not 1 <= len(raw_items) <= 50:
            raise ValueError('a study set requires 1–50 items')
        if context.get('course_id') != self.course or context.get('semester') != self.semester:
            raise ValueError('study context must match this course and semester')
        chunks = {chunk['id']: chunk for chunk in context['chunks']}
        items, used = [], {}
        for raw in raw_items:
            if not isinstance(raw, dict) or raw.get('kind') not in ITEM_KINDS:
                raise ValueError(f'item kind must be one of {ITEM_KINDS}')
            kind = raw['kind']
            if payload['kind'] == 'flashcards' and kind != 'flashcard':
                raise ValueError('flashcard sets contain only flashcards')
            if payload['kind'] == 'mind_map' and kind != 'concept':
                raise ValueError('mind maps contain only concepts')
            if payload['kind'] in {'quiz', 'practice_exam'} and kind not in {'multiple_choice', 'short_answer'}:
                raise ValueError('practice sets contain multiple-choice or short-answer questions')
            citation_ids = strings(raw.get('citation_ids'), 'citation_ids', 12)
            if not citation_ids or any(key not in chunks for key in citation_ids):
                raise ValueError('every item needs citation_ids from the current retrieved context')
            citations = [chunks[key] for key in citation_ids]
            for citation in citations:
                used[citation['source_id']] = {'source_id': citation['source_id'], 'sha256': citation['sha256']}
            options = strings(raw.get('options', []), 'options', 8)
            answer = text(raw.get('answer'), 'answer', 4000)
            if kind == 'multiple_choice' and (len(options) < 2 or answer not in options):
                raise ValueError('multiple-choice answers must exactly match one of 2–8 distinct options')
            if kind != 'multiple_choice' and options:
                raise ValueError('only multiple-choice items accept options')
            items.append({'id': str(uuid4()), 'kind': kind, 'topic': text(raw.get('topic'), 'topic', 120),
                          'prompt': text(raw.get('prompt'), 'prompt', 2000), 'options': options, 'answer': answer,
                          'explanation': text(raw.get('explanation'), 'explanation', 4000),
                          'citations': citations, 'flag': None})
        connections = payload.get('connections', [])
        if not isinstance(connections, list) or len(connections) > 100:
            raise ValueError('mind map connections must be a list of at most 100 edges')
        edges = []
        for edge in connections:
            if not isinstance(edge, dict) or any(type(edge.get(key)) is not int or not 0 <= edge[key] < len(items) for key in ('from', 'to')):
                raise ValueError('connections must reference valid zero-based item indexes')
            edges.append({'from': items[edge['from']]['id'], 'to': items[edge['to']]['id'], 'label': text(edge.get('label'), 'connection label', 120)})
        for source in used.values():
            if not source['source_id'].startswith(f'{self.semester}/{self.course}/'):
                raise ValueError('study citations must belong to this course and semester')
            if fingerprint(safe_path(self.root, Path(source['source_id']))) != source['sha256']:
                raise ValueError('a source changed during generation; retrieve fresh context')
        record = {'id': str(uuid4()), 'title': title, 'kind': payload['kind'], 'items': items, 'connections': edges,
                  'sources': list(used.values()), 'created_at': now().isoformat(), 'created_by': text(actor, 'actor', 80),
                  'provenance': 'AI-GENERATED', 'authoritative': False, 'citation_support': 'source-linked; semantic accuracy requires review',
                  'supersedes': supersedes}
        def save(state: dict[str, Any]) -> dict[str, Any]:
            if supersedes:
                self._find(state['sets'], supersedes)
            state['sets'].append(record)
            return copy.deepcopy(record)
        return self._write('set_created', save, actor)

    def revise(self, set_id: str, item_id: str, patch: dict[str, Any], *, actor: str = 'user') -> dict[str, Any]:
        if not isinstance(patch, dict) or not patch or set(patch) - {'prompt', 'answer', 'explanation', 'options', 'topic'}:
            raise ValueError('revision accepts prompt, answer, explanation, options and topic fields')
        original = self._find(self.read()['sets'], set_id)
        self._find(original['items'], item_id)
        chunks = {citation['id']: citation for item in original['items'] for citation in item['citations']}
        payload = {'title': original['title'] + ' · revised', 'kind': original['kind'], 'items': [], 'connections': []}
        indexes = {item['id']: index for index, item in enumerate(original['items'])}
        for item in original['items']:
            revised = {key: item[key] for key in ('kind', 'topic', 'prompt', 'options', 'answer', 'explanation')}
            revised['citation_ids'] = [citation['id'] for citation in item['citations']]
            if item['id'] == item_id:
                revised.update(patch)
            payload['items'].append(revised)
        payload['connections'] = [{'from': indexes[edge['from']], 'to': indexes[edge['to']], 'label': edge['label']} for edge in original['connections']]
        context = {'course_id': self.course, 'semester': self.semester, 'chunks': list(chunks.values())}
        return self.create(payload, context, actor=actor, supersedes=set_id)

    def get_set(self, set_id: str, *, reveal: bool = False) -> dict[str, Any]:
        record = copy.deepcopy(self._find(self.read()['sets'], set_id))
        record['stale_sources'] = self.stale_sources(record)
        if not reveal:
            for item in record['items']:
                for field in ('answer', 'explanation', 'citations'):
                    item.pop(field, None)
        return record

    def overview(self) -> dict[str, Any]:
        state, timestamp = self.read(), now().isoformat()
        sets = []
        fingerprints: dict[str, str | None] = {}
        topics: dict[str, dict[str, Any]] = {}
        flags = {item['id'] for record in state['sets'] for item in record['items'] if item['flag']}
        attempts = [attempt for attempt in state['attempts'] if attempt['item_id'] not in flags]
        for record in state['sets']:
            sets.append({key: record[key] for key in ('id', 'title', 'kind', 'created_at', 'created_by', 'supersedes')}
                        | {'item_count': len(record['items']), 'source_count': len(record['sources']),
                           'provenance': record['provenance'], 'authoritative': record['authoritative'],
                           'citation_support': record['citation_support'],
                           'stale_sources': self.stale_sources(record, fingerprints)})
            for item in record['items']:
                if item['kind'] == 'concept' or item['flag']:
                    continue
                entry = topics.setdefault(item['topic'], {'topic': item['topic'], 'item_count': 0, 'attempt_count': 0,
                                                          'correct_count': 0, 'self_review_count': 0, 'needs_review': False})
                entry['item_count'] += 1
                history = [attempt for attempt in attempts if attempt['item_id'] == item['id']]
                entry['attempt_count'] += len(history)
                entry['correct_count'] += sum(attempt['correct'] is True for attempt in history)
                entry['self_review_count'] += sum(attempt['basis'] == 'self-assessed' for attempt in history)
                entry['needs_review'] = entry['needs_review'] or bool(history and (history[-1]['correct'] is False or history[-1].get('rating') in {'again', 'hard'}))
        annotations = []
        for annotation in state['annotations'][-100:]:
            note = copy.deepcopy(annotation)
            citation = note['citation']
            source_id = citation['source_id']
            try:
                if source_id not in fingerprints:
                    fingerprints[source_id] = fingerprint(safe_path(self.root, Path(source_id)))
                current = fingerprints[source_id]
            except (OSError, ValueError):
                current = None
            note['stale_source'] = None if current == citation['sha256'] else {
                'source_id': source_id, 'reason': 'changed' if current else 'unavailable'}
            annotations.append(note)
        return {'schema_version': 1, 'course_id': self.course, 'semester': self.semester, 'sets': sets,
                'topics': list(topics.values()), 'attempt_count': len(attempts), 'due_count': sum(review['due_at'] <= timestamp for review in state['reviews'].values() if review['item_id'] not in flags),
                'sessions': [{key: item[key] for key in ('id', 'set_id', 'title', 'status', 'created_at')} for item in state['sessions'][-20:]],
                'annotations': annotations, 'exams': state['exams'],
                'preferences': self.preferences(),
                'progress_note': 'Practice and self-assessment only; no course grades or mastery claims.'}

    def start(self, set_id: str, *, mode: str = 'all', allow_stale: bool = False, actor: str = 'user') -> dict[str, Any]:
        if mode not in {'all', 'review', 'missed', 'exam'}:
            raise ValueError('mode must be all, review, missed or exam')
        def save(state: dict[str, Any]) -> dict[str, Any]:
            study_set = self._find(state['sets'], set_id)
            if self.stale_sources(study_set) and not allow_stale:
                raise ValueError('sources changed; regenerate this set or explicitly allow stale practice')
            if study_set['kind'] not in {'quiz', 'practice_exam', 'flashcards'}:
                raise ValueError('only questions and flashcards can start a practice session')
            items = []
            for item in study_set['items']:
                if item['flag']:
                    continue
                history = [attempt for attempt in state['attempts'] if attempt['set_id'] == set_id and attempt['item_id'] == item['id']]
                review = state['reviews'].get(f"{set_id}:{item['id']}")
                if mode == 'missed' and (not history or not (history[-1]['correct'] is False or history[-1].get('rating') in {'again', 'hard'})):
                    continue
                if mode == 'review' and review and review['due_at'] > now().isoformat():
                    continue
                items.append(copy.deepcopy(item))
            if not items:
                raise ValueError('no eligible questions for this practice mode')
            session = {'id': str(uuid4()), 'set_id': set_id, 'title': study_set['title'], 'mode': mode,
                       'status': 'active', 'created_at': now().isoformat(), 'items': items,
                       'revealed_ids': [], 'attempt_ids': [], 'allow_stale': allow_stale}
            state['sessions'].append(session)
            return {'id': session['id']}
        session = self._write('session_started', save, actor)
        return self.session(session['id'])

    def session(self, session_id: str) -> dict[str, Any]:
        state = self.read()
        session = copy.deepcopy(self._find(state['sessions'], session_id))
        session['attempts'] = [attempt for attempt in state['attempts'] if attempt['session_id'] == session_id]
        attempted = {attempt['item_id'] for attempt in session['attempts']}
        live_items = {item['id']: item for item in self._find(state['sets'], session['set_id'])['items']}
        for item in session['items']:
            item['flag'] = live_items[item['id']]['flag']
        for item in session['items']:
            if item['id'] not in session['revealed_ids'] and item['id'] not in attempted:
                for field in ('answer', 'explanation', 'citations'):
                    item.pop(field, None)
        graded = [attempt for attempt in session['attempts'] if attempt['basis'] == 'answer-key' and not attempt.get('excluded')]
        session['score'] = {'correct': sum(attempt['correct'] is True for attempt in graded), 'graded': len(graded),
                            'self_assessed': sum(attempt['basis'] == 'self-assessed' and not attempt.get('excluded') for attempt in session['attempts'])}
        return session

    def reveal(self, session_id: str, item_id: str, *, actor: str = 'user') -> dict[str, Any]:
        def save(state: dict[str, Any]) -> dict[str, Any]:
            session = self._find(state['sessions'], session_id)
            self._find(session['items'], item_id)
            if item_id not in session['revealed_ids']:
                session['revealed_ids'].append(item_id)
            return {'id': session_id}
        self._write('answer_revealed', save, actor)
        return self.session(session_id)

    def answer(self, session_id: str, item_id: str, answer: str, *, rating: str | None = None,
               feedback: str = '', actor: str = 'user') -> dict[str, Any]:
        answer = text(answer, 'answer', 4000, optional=True)
        feedback = text(feedback, 'feedback', 2000, optional=True)
        if rating is not None and rating not in RATINGS:
            raise ValueError(f'rating must be one of {RATINGS}')
        def save(state: dict[str, Any]) -> dict[str, Any]:
            session = self._find(state['sessions'], session_id)
            item = self._find(session['items'], item_id)
            live = self._find(self._find(state['sets'], session['set_id'])['items'], item_id)
            if live['flag']:
                raise ValueError('this item is flagged; it cannot count toward practice')
            if session['status'] != 'active' or any(attempt['session_id'] == session_id and attempt['item_id'] == item_id for attempt in state['attempts']):
                raise ValueError('this session item has already been answered')
            objective = item['kind'] == 'multiple_choice'
            if objective and answer not in item['options']:
                raise ValueError('answer must match an offered option')
            if not objective and (rating is None or item_id not in session['revealed_ids']):
                raise ValueError('reveal the reference answer, then submit a self-assessment rating')
            exposed = item_id in session['revealed_ids']
            basis = 'answer-key' if objective and not exposed else 'self-assessed'
            correct = answer == item['answer'] if basis == 'answer-key' else None
            effective_rating = rating if basis == 'self-assessed' else ('good' if correct else 'again')
            if effective_rating is None:
                raise ValueError('revealed answers require a self-assessment rating')
            attempt = {'id': str(uuid4()), 'session_id': session_id, 'set_id': session['set_id'], 'item_id': item_id,
                       'topic': item['topic'], 'answer': answer, 'correct': correct, 'basis': basis,
                       'rating': effective_rating, 'feedback': feedback, 'created_at': now().isoformat(), 'actor': actor}
            state['attempts'].append(attempt)
            session['attempt_ids'].append(attempt['id'])
            eligible_ids = {entry['id'] for entry in session['items'] if not self._find(self._find(state['sets'], session['set_id'])['items'], entry['id'])['flag']}
            answered_ids = {entry['item_id'] for entry in state['attempts'] if entry['session_id'] == session_id}
            if eligible_ids <= answered_ids:
                session['status'] = 'completed'
                session['completed_at'] = now().isoformat()
            key = f"{session['set_id']}:{item_id}"
            old = state['reviews'].get(key, {})
            step = old.get('step', 0)
            step = 0 if effective_rating == 'again' else max(0, step - 1) if effective_rating == 'hard' else min(5, step + (2 if effective_rating == 'easy' else 1))
            delay = timedelta(minutes=10) if effective_rating == 'again' else timedelta(days=[1, 3, 7, 14, 30, 60][step])
            state['reviews'][key] = {'set_id': session['set_id'], 'item_id': item_id, 'step': step, 'due_at': (now() + delay).isoformat(), 'last_rating': effective_rating}
            return copy.deepcopy(attempt)
        attempt = self._write('attempt_recorded', save, actor)
        return {'attempt': attempt, 'session': self.session(session_id)}

    def flag(self, set_id: str, item_id: str, reason: str, *, actor: str = 'user') -> dict[str, Any]:
        reason = text(reason, 'reason', 1000)
        def save(state: dict[str, Any]) -> dict[str, Any]:
            item = self._find(self._find(state['sets'], set_id)['items'], item_id)
            item['flag'] = {'reason': reason, 'actor': actor, 'created_at': now().isoformat()}
            for attempt in state['attempts']:
                if attempt['set_id'] == set_id and attempt['item_id'] == item_id:
                    attempt['excluded'] = True
            for session in state['sessions']:
                if session['set_id'] != set_id or session['status'] != 'active':
                    continue
                answered = {attempt['item_id'] for attempt in state['attempts'] if attempt['session_id'] == session['id']}
                eligible = {entry['id'] for entry in self._find(state['sets'], set_id)['items'] if not entry['flag']}
                if {entry['id'] for entry in session['items']} & eligible <= answered:
                    session['status'] = 'completed'
            return copy.deepcopy(item)
        return self._write('item_flagged', save, actor)

    def annotate(self, chunk: dict[str, Any], *, note: str, quote: str = '', kind: str = 'note', topic: str = '', actor: str = 'user') -> dict[str, Any]:
        if kind not in {'note', 'question', 'misconception', 'instructor_feedback', 'read'}:
            raise ValueError('unsupported annotation kind')
        if not chunk.get('source_id', '').startswith(f'{self.semester}/{self.course}/'):
            raise ValueError('annotation source must belong to this course')
        if fingerprint(safe_path(self.root, Path(chunk['source_id']))) != chunk.get('sha256'):
            raise ValueError('annotation source changed; retrieve a fresh excerpt')
        note = text(note, 'note', 4000)
        quote = text(quote, 'quote', 1200, optional=True)
        if quote and quote not in chunk['text']:
            raise ValueError('quoted text must occur verbatim in the selected excerpt')
        record = {'id': str(uuid4()), 'kind': kind, 'note': note, 'quote': quote, 'topic': text(topic, 'topic', 120, optional=True),
                  'citation': chunk, 'created_at': now().isoformat(), 'created_by': actor,
                  'basis': 'user-reported' if kind == 'instructor_feedback' else 'user-created'}
        def save(state: dict[str, Any]) -> dict[str, Any]:
            state['annotations'].append(record)
            return copy.deepcopy(record)
        return self._write('annotation_added', save, actor)

    def exam(self, payload: dict[str, Any], *, actor: str = 'user') -> dict[str, Any]:
        title = text(payload.get('title'), 'exam title', 200)
        topics = strings(payload.get('topics', []), 'exam topics')
        sources = strings(payload.get('source_ids', []), 'exam source IDs', 12)
        available = {item['id'] for item in self.context()['sources']}
        if any(source not in available for source in sources):
            raise ValueError('exam source IDs must belong to this course')
        record = {'id': payload.get('id') or str(uuid4()), 'title': title,
                  'date': date_value(payload['date'], 'exam date') if payload.get('date') else None,
                  'format': text(payload.get('format', ''), 'exam format', 500, optional=True),
                  'topics': topics, 'source_ids': sources, 'objectives': strings(payload.get('objectives', []), 'objectives'),
                  'basis': 'user-confirmed', 'updated_at': now().isoformat()}
        def save(state: dict[str, Any]) -> dict[str, Any]:
            if payload.get('id'):
                self._find(state['exams'], payload['id']).update(record)
            else:
                state['exams'].append(record)
            return copy.deepcopy(record)
        return self._write('exam_saved', save, actor)

    def exam_context(self, exam_id: str) -> dict[str, Any]:
        exam = copy.deepcopy(self._find(self.read()['exams'], exam_id))
        overview = self.overview()
        exam['coverage'] = [{'topic': topic,
                             'read_annotations': sum(note['kind'] == 'read' and note['topic'].casefold() == topic.casefold() for note in overview['annotations']),
                             'practice': next((entry for entry in overview['topics'] if entry['topic'].casefold() == topic.casefold()), None)} for topic in exam['topics']]
        exam['coverage_note'] = 'Recorded reading and practice only. Unpracticed topics remain unknown.'
        return exam

    def export(self, format: str = 'json') -> dict[str, Any]:
        state = copy.deepcopy(self.read())
        if format == 'json':
            return {'format': 'json', 'filename': f'{self.course}-study.json', 'content': json.dumps(state, indent=2, ensure_ascii=False)}
        if format != 'markdown':
            raise ValueError('export format must be json or markdown')
        lines = [f'# {self.course} — Study archive', f'Semester: {self.semester}', 'Practice material is AI-generated and not authoritative.']
        for record in state['sets']:
            lines.extend([f"\n## {record['title']}", f"Kind: {record['kind']}"])
            for item in record['items']:
                lines.extend([f"\n### {item['prompt']}", '\n'.join(f'- {option}' for option in item['options']),
                              f"Answer: {item['answer']}", item['explanation']])
                lines.extend(f"Source: {citation['source_id']} · {citation['locator']} · SHA256 {citation['sha256']}" for citation in item['citations'])
        lines.extend(['\n## Annotations', *[f"- {note['kind']}: {note['note']} ({note['citation']['source_id']} · {note['citation']['locator']})" for note in state['annotations']],
                      '\n## Practice history', '```json', json.dumps({'attempts': state['attempts'], 'reviews': state['reviews'], 'exams': state['exams']}, indent=2, ensure_ascii=False), '```'])
        return {'format': 'markdown', 'filename': f'{self.course}-study.md', 'content': '\n\n'.join(lines)}

    def restore(self, payload: dict[str, Any], *, actor: str = 'user') -> dict[str, Any]:
        self._validate_state(payload)
        prefix = f'{self.semester}/{self.course}/'
        set_ids, item_ids, session_ids, attempt_ids = set(), set(), set(), set()

        def identity(record: Any, seen: set[str]) -> str:
            if not isinstance(record, dict):
                raise ValueError('backup records must be JSON objects')
            key = text(record.get('id'), 'backup record ID', 80)
            if key in seen:
                raise ValueError('backup contains duplicate record IDs')
            seen.add(key)
            return key

        def reference(source_id: Any, digest: Any) -> None:
            if not isinstance(source_id, str) or not source_id.startswith(prefix):
                raise ValueError('backup source must belong to this course and semester')
            safe_path(self.root, Path(source_id))
            if not isinstance(digest, str) or not re.fullmatch('[0-9a-f]{64}', digest):
                raise ValueError('invalid source fingerprint in backup')

        def citation(value: Any) -> None:
            if not isinstance(value, dict):
                raise ValueError('invalid backup citation')
            reference(value.get('source_id'), value.get('sha256'))
            for key, maximum in (('id', 80), ('text', 1200), ('locator', 200), ('source_name', 500)):
                text(value.get(key), key, maximum)

        for record in payload['sets']:
            identity(record, set_ids)
            if record.get('kind') not in KINDS or record.get('authoritative') is not False or record.get('provenance') != 'AI-GENERATED':
                raise ValueError('backup study sets must remain AI-generated and non-authoritative')
            for key, maximum in (('title', 200), ('created_at', 80), ('created_by', 80)):
                text(record.get(key), key, maximum)
            if not isinstance(record.get('items'), list) or not 1 <= len(record['items']) <= 50 or not isinstance(record.get('sources'), list) or not isinstance(record.get('connections'), list):
                raise ValueError('invalid study set in backup')
            local_ids = set()
            for item in record['items']:
                item_id = identity(item, item_ids); local_ids.add(item_id)
                if item.get('kind') not in ITEM_KINDS or not isinstance(item.get('citations'), list) or not item['citations']:
                    raise ValueError('invalid backup study item')
                for key, maximum in (('prompt', 2000), ('answer', 4000), ('explanation', 4000), ('topic', 120)):
                    text(item.get(key), key, maximum)
                options = strings(item.get('options'), 'options', 8)
                if item['kind'] == 'multiple_choice' and (len(options) < 2 or item['answer'] not in options):
                    raise ValueError('invalid multiple-choice answer in backup')
                for entry in item['citations']:
                    citation(entry)
                if item.get('flag') is not None and not isinstance(item['flag'], dict):
                    raise ValueError('invalid item flag in backup')
            cited_sources = {entry['source_id']: entry['sha256'] for item in record['items'] for entry in item['citations']}
            recorded_sources = {}
            for source in record['sources']:
                if not isinstance(source, dict):
                    raise ValueError('invalid source in backup')
                reference(source.get('source_id'), source.get('sha256'))
                recorded_sources[source['source_id']] = source['sha256']
            if cited_sources != recorded_sources:
                raise ValueError('backup set sources must match its citations')
            for edge in record['connections']:
                if not isinstance(edge, dict) or edge.get('from') not in local_ids or edge.get('to') not in local_ids:
                    raise ValueError('invalid concept connection in backup')
                text(edge.get('label'), 'connection label', 120)
        for session in payload['sessions']:
            identity(session, session_ids)
            if session.get('set_id') not in set_ids or session.get('status') not in {'active', 'completed'} or not isinstance(session.get('items'), list):
                raise ValueError('invalid backup session')
            original = self._find(payload['sets'], session['set_id'])
            original_ids = {item['id'] for item in original['items']}
            if not session['items'] or any(not isinstance(item, dict) or item.get('id') not in original_ids for item in session['items']):
                raise ValueError('backup session items must belong to its set')
            # The source set is immutable; restore snapshots from its validated items.
            session['items'] = [copy.deepcopy(self._find(original['items'], item['id'])) for item in session['items']]
            for key in ('revealed_ids', 'attempt_ids'):
                strings(session.get(key), key, 100)
            text(session.get('title'), 'session title', 200)
            text(session.get('created_at'), 'session date', 80)
        for attempt in payload['attempts']:
            identity(attempt, attempt_ids)
            if attempt.get('session_id') not in session_ids or attempt.get('item_id') not in item_ids or attempt.get('set_id') not in set_ids:
                raise ValueError('invalid backup attempt reference')
            session = self._find(payload['sessions'], attempt['session_id'])
            if session['set_id'] != attempt['set_id'] or attempt['item_id'] not in {item['id'] for item in session['items']}:
                raise ValueError('backup attempt crosses study sets')
            if attempt.get('basis') not in {'answer-key', 'self-assessed'} or attempt.get('rating') not in RATINGS or attempt.get('correct') not in (True, False, None):
                raise ValueError('invalid backup assessment')
            text(attempt.get('answer'), 'attempt answer', 4000, optional=True)
            text(attempt.get('topic'), 'attempt topic', 120)
        for review in payload['reviews'].values():
            if not isinstance(review, dict) or review.get('item_id') not in item_ids or review.get('set_id') not in set_ids or type(review.get('step')) is not int or not 0 <= review['step'] <= 5:
                raise ValueError('invalid backup review schedule')
            try:
                if datetime.fromisoformat(review['due_at']).tzinfo is None:
                    raise ValueError('review timezone required')
            except (ValueError, TypeError, KeyError) as exc:
                raise ValueError('invalid backup review date') from exc
        annotation_ids = set()
        for note in payload['annotations']:
            identity(note, annotation_ids)
            citation(note.get('citation'))
            text(note.get('note'), 'annotation note', 4000)
            text(note.get('topic'), 'annotation topic', 120, optional=True)
            text(note.get('quote'), 'annotation quote', 1200, optional=True)
            if note.get('kind') not in {'note', 'question', 'misconception', 'instructor_feedback', 'read'}:
                raise ValueError('invalid backup annotation kind')
        exam_ids = set()
        for exam in payload['exams']:
            identity(exam, exam_ids)
            text(exam.get('title'), 'exam title', 200)
            strings(exam.get('topics'), 'exam topics')
            strings(exam.get('objectives'), 'exam objectives')
            for source in strings(exam.get('source_ids'), 'exam sources', 12):
                if not source.startswith(prefix):
                    raise ValueError('backup exam source must belong to this course')
                safe_path(self.root, Path(source))
            if exam.get('date'):
                date_value(exam['date'], 'exam date')
        self._preferences(payload.get('preferences', {}))
        # Restore only into an empty study workspace; no overwrites or silent merging.
        def save(state: dict[str, Any]) -> dict[str, Any]:
            if any(state[key] for key in ('sets', 'sessions', 'attempts', 'annotations', 'exams', 'reviews')):
                raise ValueError('restore requires an empty course study workspace; existing study records are preserved')
            for record in payload['sets']:
                if not isinstance(record, dict) or record.get('kind') not in KINDS or not isinstance(record.get('items'), list):
                    raise ValueError('invalid study set in backup')
                for source in record['sources']:
                    safe_path(self.root, Path(source['source_id']))
            state.update(copy.deepcopy(payload))
            return {'id': self.course, 'restored_sets': len(state['sets'])}
        return self._write('backup_restored', save, actor)
