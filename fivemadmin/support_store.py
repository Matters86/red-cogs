"""Profile-local support cases. No bot, network, or database path discovery."""
from contextlib import closing
import hashlib
import json
import re
import time
import uuid

STATUSES = {'open', 'working', 'waiting', 'closed'}
REPORT_ACTIONS = {'support_vehicle_search', 'support_vehicle_case', 'support_diagnose'}

class SupportError(Exception):
    def __init__(self, code, status=400):
        self.code, self.status = code, status
        super().__init__(code)

def install(conn):
    # Individual statements preserve the caller's transaction boundaries.
    for statement in [
        '''CREATE TABLE IF NOT EXISTS support_cases (
            id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL,
            description TEXT NOT NULL, citizenid TEXT, qa_bug_id INTEGER,
            status TEXT NOT NULL DEFAULT 'open', assigned_to TEXT, assigned_name TEXT,
            created_by TEXT NOT NULL, created_name TEXT NOT NULL,
            version INTEGER NOT NULL DEFAULT 1, created_at REAL NOT NULL, updated_at REAL NOT NULL)''',
        '''CREATE TABLE IF NOT EXISTS support_case_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT, case_id INTEGER NOT NULL,
            type TEXT NOT NULL, text TEXT NOT NULL, actor_id TEXT NOT NULL,
            actor_name TEXT NOT NULL, report TEXT, at REAL NOT NULL)''',
        '''CREATE INDEX IF NOT EXISTS support_case_events_case ON support_case_events(case_id, id)''',
        '''CREATE TABLE IF NOT EXISTS support_case_photos (
            id TEXT PRIMARY KEY, case_id INTEGER NOT NULL, name TEXT NOT NULL,
            filename TEXT NOT NULL, mime TEXT NOT NULL, bytes INTEGER NOT NULL,
            sha256 TEXT NOT NULL, created_by TEXT NOT NULL, created_at REAL NOT NULL)''',
        '''CREATE TABLE IF NOT EXISTS support_case_requests (
            request_id TEXT PRIMARY KEY, actor_id TEXT NOT NULL,
            fingerprint TEXT NOT NULL, response TEXT NOT NULL, created_at REAL NOT NULL)''',
    ]:
        conn.execute(statement)

def _text(value, name, minimum=0, maximum=4000):
    if not isinstance(value, str) or '\x00' in value:
        raise SupportError('invalid_' + name)
    value = value.strip()
    if not minimum <= len(value) <= maximum:
        raise SupportError('invalid_' + name)
    return value

def _integer(value, name, minimum=1, maximum=2147483647):
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise SupportError('invalid_' + name)
    return value

def _request_id(value):
    try:
        if not isinstance(value, str) or str(uuid.UUID(value)) != value.lower():
            raise ValueError()
    except (ValueError, TypeError, AttributeError):
        raise SupportError('invalid_request_id')
    return value.lower()

def _actor(actor):
    if not isinstance(actor, dict) or not re.fullmatch(r'[0-9]{1,24}', str(actor.get('id', ''))):
        raise SupportError('invalid_actor', 403)
    return {'id': str(actor['id']), 'name': _text(actor.get('name'), 'actor_name', 1, 128),
            'admin': actor.get('admin') is True}

def public_case(row):
    return {'id': row['id'], 'title': row['title'], 'description': row['description'],
            'citizenid': row['citizenid'], 'qaBugId': row['qa_bug_id'], 'status': row['status'],
            'assignedTo': row['assigned_to'], 'assignedName': row['assigned_name'],
            'createdBy': row['created_by'], 'createdName': row['created_name'],
            'version': row['version'], 'createdAt': row['created_at'], 'updatedAt': row['updated_at']}

class Store:
    def __init__(self, get_conn):
        self.get_conn = get_conn

    def _find(self, conn, case_id):
        row = conn.execute('SELECT * FROM support_cases WHERE id = ?', (_integer(case_id, 'case_id'),)).fetchone()
        if row is None:
            raise SupportError('case_not_found', 404)
        return dict(row)

    def _event(self, conn, case_id, actor, kind, text, report=None):
        conn.execute('INSERT INTO support_case_events(case_id,type,text,actor_id,actor_name,report,at) VALUES(?,?,?,?,?,?,?)',
                     (case_id, kind, text, actor['id'], actor['name'],
                      json.dumps(report, ensure_ascii=False, allow_nan=False) if report is not None else None, time.time()))

    def _mutate(self, actor, request_id, payload, callback):
        actor, request_id = _actor(actor), _request_id(request_id)
        fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False,
                                                allow_nan=False, separators=(',', ':')).encode()).hexdigest()
        with closing(self.get_conn()) as conn:
            conn.execute('BEGIN IMMEDIATE')
            previous = conn.execute('SELECT * FROM support_case_requests WHERE request_id = ?', (request_id,)).fetchone()
            if previous:
                if previous['actor_id'] != actor['id'] or previous['fingerprint'] != fingerprint:
                    raise SupportError('request_conflict', 409)
                return json.loads(previous['response'])
            response = callback(conn, actor)
            conn.execute('INSERT INTO support_case_requests VALUES(?,?,?,?,?)',
                         (request_id, actor['id'], fingerprint, json.dumps(response, ensure_ascii=False, allow_nan=False), time.time()))
            conn.commit()
            return response

    def list(self, query='', status=''):
        query = _text(query, 'query', maximum=100)
        if status and status not in STATUSES:
            raise SupportError('invalid_status')
        conditions, values = [], []
        if status:
            conditions.append('status = ?'); values.append(status)
        if query:
            # Literal search, no SQL wildcards supplied by a user.
            pattern = '%' + query.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
            conditions.append("(title LIKE ? ESCAPE '\\' OR citizenid LIKE ? ESCAPE '\\' OR CAST(id AS TEXT) = ?)")
            values.extend([pattern, pattern, query])
        clause = ' WHERE ' + ' AND '.join(conditions) if conditions else ''
        with closing(self.get_conn()) as conn:
            rows = conn.execute('SELECT * FROM support_cases' + clause + ' ORDER BY updated_at DESC,id DESC LIMIT 101', values).fetchall()
        return {'cases': [public_case(dict(row)) for row in rows[:100]], 'truncated': len(rows) > 100}

    def detail(self, case_id):
        with closing(self.get_conn()) as conn:
            case = self._find(conn, case_id)
            events = conn.execute('SELECT * FROM support_case_events WHERE case_id=? ORDER BY id DESC LIMIT 101', (case_id,)).fetchall()
            photos = conn.execute('SELECT * FROM support_case_photos WHERE case_id=? ORDER BY created_at LIMIT 8', (case_id,)).fetchall()
        return {'case': public_case(case), 'eventsTruncated': len(events) > 100,
                'events': [{'id': row['id'], 'type': row['type'], 'text': row['text'],
                            'actorName': row['actor_name'], 'at': row['at'],
                            'report': json.loads(row['report']) if row['report'] else None} for row in reversed(events[:100])],
                'photos': [{'id': row['id'], 'url': '/api/panel/support/photos/' + row['id'],
                            'name': row['name'], 'createdAt': row['created_at']} for row in photos]}

    def create(self, actor, body):
        if not isinstance(body, dict) or set(body) - {'requestId', 'title', 'description', 'citizenid', 'qaBugId'}:
            raise SupportError('invalid_case_payload')
        title = _text(body.get('title'), 'title', 3, 140)
        description = _text(body.get('description'), 'description', 3, 6000)
        citizenid = body.get('citizenid')
        if citizenid not in (None, ''):
            citizenid = _text(citizenid, 'citizenid', 1, 50)
            if not re.fullmatch(r'[A-Za-z0-9_-]+', citizenid):
                raise SupportError('invalid_citizenid')
        else:
            citizenid = None
        bug = body.get('qaBugId')
        if bug not in (None, ''):
            bug = _integer(bug, 'qa_bug_id')
        else:
            bug = None
        payload = {'operation': 'create', 'title': title, 'description': description, 'citizenid': citizenid, 'qaBugId': bug}
        def create(conn, actor):
            at = time.time()
            cursor = conn.execute('INSERT INTO support_cases(title,description,citizenid,qa_bug_id,created_by,created_name,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)',
                                  (title, description, citizenid, bug, actor['id'], actor['name'], at, at))
            case_id = cursor.lastrowid
            self._event(conn, case_id, actor, 'created', 'Supportfall erstellt.')
            return {'case': public_case(self._find(conn, case_id))}
        return self._mutate(actor, body.get('requestId'), payload, create)

    def update(self, actor, case_id, body, *, assignee=None, report=None):
        if not isinstance(body, dict) or set(body) - {'requestId', 'version', 'operation', 'text', 'assignedTo', 'status', 'actionId'}:
            raise SupportError('invalid_case_payload')
        version = _integer(body.get('version'), 'version')
        operation = body.get('operation')
        if operation not in {'claim', 'assign', 'status', 'comment', 'report'}:
            raise SupportError('invalid_operation')
        case_id = _integer(case_id, 'case_id')
        payload = {'caseId': case_id, **body}
        def update(conn, actor):
            case = self._find(conn, case_id)
            if case['version'] != version:
                raise SupportError('case_version_conflict', 409)
            if operation != 'status' and case['status'] == 'closed' and operation != 'comment':
                raise SupportError('case_closed', 409)
            if operation == 'claim':
                if case['assigned_to'] not in (None, actor['id']):
                    raise SupportError('case_already_assigned', 409)
                conn.execute("UPDATE support_cases SET assigned_to=?,assigned_name=?,status=CASE WHEN status='open' THEN 'working' ELSE status END WHERE id=?",
                             (actor['id'], actor['name'], case_id))
                self._event(conn, case_id, actor, 'claimed', 'Fall übernommen.')
            elif operation == 'assign':
                if not actor['admin'] and case['assigned_to'] not in (None, actor['id']):
                    raise SupportError('handover_requires_assignee', 403)
                if not assignee or str(assignee['id']) != str(body.get('assignedTo')):
                    raise SupportError('assignee_not_authorized', 403)
                note = _text(body.get('text', ''), 'handover_note', 0, 4000)
                conn.execute('UPDATE support_cases SET assigned_to=?,assigned_name=? WHERE id=?',
                             (str(assignee['id']), _text(assignee['name'], 'assignee_name', 1, 128), case_id))
                self._event(conn, case_id, actor, 'assigned', 'Zugewiesen an ' + assignee['name'] + (': ' + note if note else '.'))
            elif operation == 'status':
                if not actor['admin'] and case['assigned_to'] != actor['id']:
                    raise SupportError('status_requires_assignee', 403)
                if body.get('status') not in STATUSES:
                    raise SupportError('invalid_status')
                conn.execute('UPDATE support_cases SET status=? WHERE id=?', (body['status'], case_id))
                labels = {'open': 'Offen', 'working': 'In Bearbeitung', 'waiting': 'Wartet auf Rückmeldung', 'closed': 'Abgeschlossen'}
                self._event(conn, case_id, actor, 'status', 'Status: ' + labels[body['status']])
            elif operation == 'comment':
                self._event(conn, case_id, actor, 'comment', _text(body.get('text'), 'comment', 1, 4000))
            elif operation == 'report':
                if not isinstance(report, dict) or report.get('actionId') != body.get('actionId'):
                    raise SupportError('report_unconfirmed', 409)
                if case['citizenid'] and report.get('citizenid') and case['citizenid'] != report['citizenid']:
                    raise SupportError('report_citizenid_mismatch', 409)
                self._event(conn, case_id, actor, 'report', 'Lesender Prüfbericht gespeichert.', report)
            conn.execute('UPDATE support_cases SET version=version+1,updated_at=? WHERE id=?', (time.time(), case_id))
            return {'case': public_case(self._find(conn, case_id))}
        return self._mutate(actor, body.get('requestId'), payload, update)

    def add_photo(self, actor, case_id, request_id, version, meta, write_file):
        case_id, version = _integer(case_id, 'case_id'), _integer(version, 'version')
        payload = {'operation': 'photo', 'caseId': case_id, 'version': version,
                   'sha256': meta['sha256'], 'bytes': meta['bytes'], 'name': meta['name'], 'mime': meta['mime']}
        def add(conn, actor):
            case = self._find(conn, case_id)
            if case['version'] != version:
                raise SupportError('case_version_conflict', 409)
            if case['status'] == 'closed':
                raise SupportError('case_closed', 409)
            if conn.execute('SELECT COUNT(*) FROM support_case_photos WHERE case_id=?', (case_id,)).fetchone()[0] >= 8:
                raise SupportError('photo_limit_reached', 409)
            photo_id = uuid.uuid4().hex
            filename = photo_id + meta['extension']
            write_file(filename)
            conn.execute('INSERT INTO support_case_photos VALUES(?,?,?,?,?,?,?,?,?)',
                         (photo_id, case_id, meta['name'], filename, meta['mime'], meta['bytes'], meta['sha256'], actor['id'], time.time()))
            self._event(conn, case_id, actor, 'photo', 'Foto hinzugefügt: ' + meta['name'])
            conn.execute('UPDATE support_cases SET version=version+1,updated_at=? WHERE id=?', (time.time(), case_id))
            return {'case': public_case(self._find(conn, case_id)), 'photoId': photo_id}
        return self._mutate(actor, request_id, payload, add)

    def photo(self, photo_id):
        if not isinstance(photo_id, str) or not re.fullmatch(r'[a-f0-9]{32}', photo_id):
            raise SupportError('photo_not_found', 404)
        with closing(self.get_conn()) as conn:
            row = conn.execute('SELECT * FROM support_case_photos WHERE id=?', (photo_id,)).fetchone()
        if row is None:
            raise SupportError('photo_not_found', 404)
        return dict(row)

def trusted_report(action, profile_id):
    if not action or action.get('status') != 'done' or action.get('action_type') not in REPORT_ACTIONS:
        raise SupportError('report_unconfirmed', 409)
    if action.get('result_review_required') or action.get('profile_queue_hold'):
        raise SupportError('report_requires_review', 409)
    raw = action.get('result')
    if not isinstance(raw, str) or len(raw.encode('utf8')) > 128 * 1024:
        raise SupportError('report_too_large', 409)
    try:
        data = json.loads(raw, parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()))
        params = json.loads(action.get('params') or '{}')
    except (ValueError, TypeError):
        raise SupportError('report_invalid', 409)
    if not isinstance(data, dict) or data.get('readOnly') is not True or type(data.get('schema_version')) is not int or data.get('schema_version') != 1 or data.get('server_id') != profile_id:
        raise SupportError('report_profile_unconfirmed', 409)
    if not isinstance(params, dict) or params.get('server_id') != profile_id or params.get('profile') != profile_id:
        raise SupportError('report_profile_unconfirmed', 409)
    if action['action_type'] == 'support_diagnose' and data.get('topic') != params.get('topic'):
        raise SupportError('report_identity_mismatch', 409)
    if action['action_type'] == 'support_diagnose' and params.get('topic') == 'civil_jobs' and data.get('citizenid') != params.get('citizenid'):
        raise SupportError('report_identity_mismatch', 409)
    if params.get('vehicle_id') is not None and (not isinstance(data.get('vehicle'), dict)
            or type(data['vehicle'].get('id')) is not int or data['vehicle']['id'] != params['vehicle_id']):
        raise SupportError('report_identity_mismatch', 409)
    if params.get('citizenid') and data.get('citizenid') not in (None, params['citizenid']):
        raise SupportError('report_identity_mismatch', 409)
    return {'actionId': action['id'], 'actionType': action['action_type'], 'profileId': profile_id,
            'completedAt': action.get('completed_at'), 'citizenid': params.get('citizenid'), 'data': data}
