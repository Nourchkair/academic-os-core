"""One command contract shared by external agents and human-facing clients."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from ..config import load_config
from ..workspace import build_workspace_snapshot
from . import KINDS, RATINGS, StudyService
from .providers import generate, output_schema, status


def capabilities() -> dict[str, Any]:
    return {'schema_version': 1, 'agent_first': True, 'dashboard_required': False,
            'generation_optional': True, 'kinds': list(KINDS),
            'commands': ['overview', 'preferences', 'configure', 'context', 'create', 'generate', 'revise', 'show', 'start', 'session', 'reveal', 'answer', 'flag',
                         'annotate', 'exam-save', 'exam', 'plan', 'export', 'restore'],
            'agent_loop': ['study context --course COURSE --source LIBRARY_ID --json',
                           'study create --course COURSE --source LIBRARY_ID --input - --json',
                           'study start --course COURSE --set SET_ID --json',
                           'study answer --course COURSE --session SESSION_ID --item ITEM_ID --answer ANSWER --json',
                           'study overview --course COURSE --json'],
            'answer_policy': 'Answers are hidden by default. MCQ is answer-key graded before reveal; free responses and flashcards require reveal then self-rating. Practice never modifies course grades.',
            'source_policy': 'Choose course Library IDs; context retrieves bounded, fingerprinted excerpts by default. context --deep, create --deep, or generate --deep scans all pages/text of up to 300 selected sources and returns ranked, page-addressed passages. Keep the same source/query/pages/limit/deep selection when submitting a create payload so its citations can be validated against retrieved context. Cite chunk IDs. Changed sources are flagged. Citations establish traceability, not semantic verification.',
            'storage': '<course>/06_KNOWLEDGE/STUDY/study.json (durable student-owned records)',
            'create_schema': output_schema('quiz'),
            'preferences': 'Read study preferences; configure saves desired study style and provider without credentials or a connection claim.',
            'external_agent': 'Any authorized agent can generate a payload itself and call create; no nested model call or provider connection is required.'}


def add_parser(sub: Any) -> None:
    study = sub.add_parser('study', help='Agent-first study material, practice, review and exam preparation')
    commands = study.add_subparsers(dest='study_command', required=True)
    for name in ('capabilities', 'providers'):
        commands.add_parser(name).add_argument('--json', action='store_true')
    for name in capabilities()['commands']:
        parser = commands.add_parser(name)
        parser.add_argument('--course', dest='course_id', required=name != 'plan')
        parser.add_argument('--semester')
        parser.add_argument('--json', action='store_true')
        if name in {'create', 'generate', 'start', 'reveal', 'answer', 'flag', 'annotate', 'exam-save', 'restore', 'revise', 'configure'}:
            parser.add_argument('--actor', default='user')
        if name in {'context', 'create', 'generate', 'annotate'}:
            parser.add_argument('--source', action='append', default=[], help='Exact course Library source ID; repeat for several sources')
            parser.add_argument('--query', default='')
            parser.add_argument('--pages', help='PDF page or page range, maximum 100 pages')
            parser.add_argument('--limit', type=int, default=12)
            if name in {'context', 'create', 'generate'}:
                parser.add_argument('--deep', action='store_true', help='Search the full text of every selected source, including all PDF pages')
        if name in {'create', 'exam-save', 'restore', 'revise', 'configure'}:
            group = parser.add_mutually_exclusive_group(required=True)
            group.add_argument('--payload-json', help='Structured JSON payload')
            group.add_argument('--input', help='JSON file, or - to read stdin')
        if name in {'create', 'generate'}:
            parser.add_argument('--supersedes', help='Create a revision while retaining the original set and attempts')
        if name == 'generate':
            parser.add_argument('--kind', choices=KINDS)
            parser.add_argument('--count', type=int)
            parser.add_argument('--title', help='Use this title for the saved study set')
            parser.add_argument('--instructions')
            parser.add_argument('--provider', choices=('codex', 'local'))
            parser.add_argument('--model')
            parser.add_argument('--endpoint')
            parser.add_argument('--protocol', choices=('ollama', 'openai-compatible'))
            parser.add_argument('--exam')
        if name in {'show', 'start', 'flag', 'revise'}:
            parser.add_argument('--set', dest='set_id', required=True)
        if name == 'show':
            parser.add_argument('--reveal', action='store_true')
        if name == 'start':
            parser.add_argument('--mode', choices=('all', 'review', 'missed', 'exam'), default='all')
            parser.add_argument('--allow-stale', action='store_true')
        if name in {'session', 'reveal', 'answer'}:
            parser.add_argument('--session', dest='session_id', required=True)
        if name in {'reveal', 'answer', 'flag', 'revise'}:
            parser.add_argument('--item', dest='item_id', required=True)
        if name == 'answer':
            parser.add_argument('--answer', default='')
            parser.add_argument('--rating', choices=RATINGS)
            parser.add_argument('--feedback', default='', help='Student-reported misconception or feedback')
        if name == 'flag':
            parser.add_argument('--reason', required=True)
        if name == 'annotate':
            parser.add_argument('--chunk', required=True, help='Chunk ID from context')
            parser.add_argument('--note', required=True)
            parser.add_argument('--quote', default='')
            parser.add_argument('--topic', default='')
            parser.add_argument('--kind', choices=('note', 'question', 'misconception', 'instructor_feedback', 'read'), default='note')
        if name == 'exam':
            parser.add_argument('--exam', required=True)
        if name == 'plan':
            parser.add_argument('--minutes', type=int, default=40)
        if name == 'export':
            parser.add_argument('--format', choices=('json', 'markdown'), default='json')


def _payload(args: argparse.Namespace) -> dict[str, Any]:
    if args.payload_json is not None:
        raw = args.payload_json
    elif args.input == '-':
        raw = sys.stdin.read(2 * 1024 * 1024 + 1)
    else:
        path = Path(args.input).expanduser()
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 2 * 1024 * 1024:
            raise ValueError('study input must be a regular JSON file of at most 2 MB')
        raw = path.read_text(encoding='utf-8')
    if len(raw.encode('utf-8')) > 2 * 1024 * 1024:
        raise ValueError('study payload is too large')
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError('study payload must be a JSON object')
    return value


def plan(config: dict[str, Any], snapshot: dict[str, Any], minutes: int, course_id: str | None = None) -> dict[str, Any]:
    if not 5 <= minutes <= 240:
        raise ValueError('study time must be between 5 and 240 minutes')
    root = Path(snapshot['academic_root'])
    courses = snapshot['courses']
    if course_id:
        service = StudyService(root, snapshot['semester'], course_id)
        courses = [course for course in courses if course['id'] == service.course]
    today = datetime.now(ZoneInfo(config['academic']['timezone'])).date()
    current_time = datetime.now(timezone.utc).isoformat()
    candidates = []
    for course in courses:
        service = StudyService(root, snapshot['semester'], course['id'])
        overview = service.overview()
        state = service.read()
        sets = [record for record in overview['sets'] if record['kind'] in {'quiz', 'practice_exam', 'flashcards'} and not record['stale_sources']]
        set_ids = {record['id'] for record in sets}
        flagged = {item['id'] for record in state['sets'] for item in record['items'] if item['flag']}
        due_by_set: dict[str, int] = {}
        for review in state['reviews'].values():
            if review['set_id'] in set_ids and review['item_id'] not in flagged and review['due_at'] <= current_time:
                due_by_set[review['set_id']] = due_by_set.get(review['set_id'], 0) + 1
        sets_by_id = {record['id']: record for record in state['sets'] if record['id'] in set_ids}
        for set_id, due_count in due_by_set.items():
            record = sets_by_id[set_id]
            candidates.append({'course_id': service.course, 'set_id': set_id,
                               'title': f"Review {record['title']}",
                               'reason': f'{due_count} item' + (' is' if due_count == 1 else 's are') + ' due from your saved practice schedule',
                               'priority': 0, 'suggested_minutes': 10, 'action': 'review'})
        latest_attempts: dict[tuple[str, str], dict[str, Any]] = {}
        for attempt in state['attempts']:
            if attempt['set_id'] in set_ids and attempt['item_id'] not in flagged:
                latest_attempts[(attempt['set_id'], attempt['item_id'])] = attempt
        missed_recommendation_count = 0
        for record_summary in sets:
            record = sets_by_id[record_summary['id']]
            missed_topics = []
            for item in record['items']:
                if item['flag']:
                    continue
                latest = latest_attempts.get((record['id'], item['id']))
                if latest and (latest['correct'] is False or latest.get('rating') in {'again', 'hard'}):
                    if item['topic'] not in missed_topics:
                        missed_topics.append(item['topic'])
            if missed_topics:
                missed_recommendation_count += 1
                candidates.append({'course_id': service.course, 'set_id': record['id'],
                                   'title': f"Revisit {', '.join(missed_topics[:2])}",
                                   'reason': f"Your latest practice in {record['title']} suggests these topics could use another pass",
                                   'priority': 2, 'suggested_minutes': 15, 'action': 'missed'})
        for exam in overview['exams']:
            if exam['date']:
                days = (datetime.strptime(exam['date'], '%Y-%m-%d').date() - today).days
                if 0 <= days <= 14:
                    candidates.append({'course_id': service.course, 'title': f"Prepare for {exam['title']}", 'reason': f'Exam in {days} days; use its recorded scope', 'priority': 1 + days / 14, 'suggested_minutes': 20, 'action': 'exam', 'exam_id': exam['id']})
        tasks = [task for task in snapshot.get('tasks', []) if task.get('course') == service.course and not task.get('completed') and task.get('due_date')]
        for task in sorted(tasks, key=lambda task: task['due_date'])[:2]:
            candidates.append({'course_id': service.course, 'title': f"Prepare for {task['title']}", 'reason': f"Upcoming coursework deadline recorded for {task['due_date']}", 'priority': 3, 'suggested_minutes': 15, 'action': 'prepare_coursework'})
        if not sets:
            candidates.append({'course_id': service.course, 'title': 'Choose material and start practicing', 'reason': 'No current practice sets yet', 'priority': 4, 'suggested_minutes': 15, 'action': 'select_sources'})
        elif not missed_recommendation_count and not due_by_set:
            candidates.append({'course_id': service.course, 'title': 'Practice a course topic', 'reason': 'Build evidence of recall on material you have not practiced recently', 'priority': 5, 'suggested_minutes': 15, 'action': 'practice'})
    remaining, blocks = minutes, []
    for candidate in sorted(candidates, key=lambda item: item['priority']):
        if remaining < 5:
            break
        duration = min(remaining, candidate.pop('suggested_minutes'))
        blocks.append({**candidate, 'minutes': duration})
        remaining -= duration
    return {'minutes_available': minutes, 'minutes_planned': minutes - remaining, 'blocks': blocks,
            'advisory': True, 'calendar_changes': False, 'note': 'Adjust freely. This is a suggestion based on recorded deadlines and practice, not a claim that every requirement is known.'}


def dispatch(args: argparse.Namespace, profile: Path) -> Any:
    action = args.study_command
    if action == 'capabilities':
        return capabilities()
    if action == 'providers':
        return status()
    config = load_config(profile)
    semester = args.semester or config['academic']['semester']
    root = Path(config['academic']['root_directory']).expanduser().resolve()
    if action == 'plan':
        snapshot = build_workspace_snapshot(config, persist=False, semester_override=semester)
        from ..assignment_history import apply_history_to_tasks, list_assignment_history
        for course in snapshot['courses']:
            snapshot['tasks'] = apply_history_to_tasks(snapshot['tasks'], list_assignment_history(root, semester, course['id']), course_name=course['name'])
        return plan(config, snapshot, args.minutes, args.course_id)
    service = StudyService(root, semester, args.course_id)
    actor = getattr(args, 'actor', 'user')
    if action == 'preferences':
        return service.preferences()
    if action == 'configure':
        return service.configure(_payload(args), actor=actor)
    if action == 'overview':
        return service.overview()
    if action in {'context', 'create', 'generate', 'annotate'}:
        selection = {'source_ids': args.source, 'query': args.query, 'pages': args.pages, 'limit': args.limit,
                     'deep': bool(getattr(args, 'deep', False))}
        exam = service.exam_context(args.exam) if action == 'generate' and args.exam else None
        if exam and not args.source:
            selection['source_ids'] = exam['source_ids']
        context = service.context(**selection)
        if action == 'context':
            return context
        if action == 'create':
            return service.create(_payload(args), context, actor=actor, supersedes=args.supersedes)
        if action == 'generate':
            overview = service.overview()
            # Send bounded academic context; do not forward personal chat, credentials or full histories.
            snapshot = build_workspace_snapshot(config, persist=False, semester_override=semester)
            course_tasks = [{key: task.get(key) for key in ('title', 'due_date', 'due_time', 'weight', 'confidence')} for task in snapshot['tasks'] if task.get('course') == service.course][:12]
            learning_context = {'exam': exam, 'topics': overview['topics'][:30], 'course_tasks': course_tasks,
                                'notes': [{'kind': note['kind'], 'topic': note['topic'], 'note': note['note'],
                                           'source_name': note['citation']['source_name'], 'locator': note['citation']['locator'],
                                           'stale_source': note['stale_source']}
                                          for note in overview['annotations'][-12:]]}
            preferences = service.preferences()
            selected = {key: getattr(args, key) if getattr(args, key) is not None else preferences[pref] for key, pref in
                        (('kind', 'preferred_kind'), ('count', 'question_count'), ('instructions', 'instructions'), ('provider', 'provider'),
                         ('model', 'model'), ('endpoint', 'endpoint'), ('protocol', 'protocol'))}
            payload = generate(context, **selected, study_context=learning_context)
            if args.title:
                payload['title'] = args.title
            created = service.create(payload, context, actor=f"provider:{selected['provider']}", supersedes=args.supersedes)
            return {**created, 'coverage': context.get('coverage'), 'warnings': context.get('warnings', [])}
        chunk = next((chunk for chunk in context['chunks'] if chunk['id'] == args.chunk), None)
        if chunk is None:
            raise ValueError('annotation chunk must come from this retrieved context')
        return service.annotate(chunk, note=args.note, quote=args.quote, kind=args.kind, topic=args.topic, actor=actor)
    if action == 'revise':
        return service.revise(args.set_id, args.item_id, _payload(args), actor=actor)
    if action == 'show':
        return service.get_set(args.set_id, reveal=args.reveal)
    if action == 'start':
        return service.start(args.set_id, mode=args.mode, allow_stale=args.allow_stale, actor=actor)
    if action == 'session':
        return service.session(args.session_id)
    if action == 'reveal':
        return service.reveal(args.session_id, args.item_id, actor=actor)
    if action == 'answer':
        return service.answer(args.session_id, args.item_id, args.answer, rating=args.rating, feedback=args.feedback, actor=actor)
    if action == 'flag':
        return service.flag(args.set_id, args.item_id, args.reason, actor=actor)
    if action == 'exam-save':
        return service.exam(_payload(args), actor=actor)
    if action == 'exam':
        return service.exam_context(args.exam)
    if action == 'export':
        return service.export(args.format)
    if action == 'restore':
        return service.restore(_payload(args), actor=actor)
    raise ValueError(f'unsupported study command: {action}')
