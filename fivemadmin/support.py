"""Authenticated profile-local support routes; photographs never use token URLs."""
import asyncio
from functools import wraps
import hashlib
import re
from pathlib import Path
from aiohttp import web
from . import db, support_store as store

PHOTO_LIMIT = 4 * 1024 * 1024

def image_metadata(content):
    """Bounded image signatures/dimensions, no image decoder or remote URL fetch."""
    if not isinstance(content, bytes) or not 24 <= len(content) <= PHOTO_LIMIT:
        raise store.SupportError('invalid_photo_size', 413)
    width = height = 0
    if content.startswith(b'\x89PNG\r\n\x1a\n') and content[12:16] == b'IHDR' and b'IEND' in content[-16:]:
        width, height = int.from_bytes(content[16:20], 'big'), int.from_bytes(content[20:24], 'big')
        mime, extension = 'image/png', '.png'
    elif content[:3] == b'\xff\xd8\xff' and content[-2:] == b'\xff\xd9':
        offset = 2
        for _ in range(512):
            if offset + 4 > len(content) or content[offset] != 0xff:
                break
            while offset < len(content) and content[offset] == 0xff:
                offset += 1
            if offset >= len(content):
                break
            marker = content[offset]; offset += 1
            if marker in (0xd9, 0xda):
                break
            if marker in (0x01, *range(0xd0, 0xd8)):
                continue
            if offset + 2 > len(content):
                break
            length = int.from_bytes(content[offset:offset+2], 'big')
            if length < 2 or offset + length > len(content):
                break
            if marker in (0xc0,0xc1,0xc2,0xc3,0xc5,0xc6,0xc7,0xc9,0xca,0xcb,0xcd,0xce,0xcf) and length >= 8:
                height, width = int.from_bytes(content[offset+3:offset+5], 'big'), int.from_bytes(content[offset+5:offset+7], 'big')
                break
            offset += length
        mime, extension = 'image/jpeg', '.jpg'
    elif content[:4] == b'RIFF' and content[8:12] == b'WEBP' and int.from_bytes(content[4:8], 'little') + 8 == len(content):
        kind = content[12:16]
        if kind == b'VP8X' and len(content) >= 30 and not content[20] & 2:
            width, height = int.from_bytes(content[24:27], 'little') + 1, int.from_bytes(content[27:30], 'little') + 1
        elif kind == b'VP8L' and len(content) >= 25 and content[20] == 0x2f:
            bits = int.from_bytes(content[21:25], 'little')
            width, height = (bits & 0x3fff) + 1, ((bits >> 14) & 0x3fff) + 1
        elif kind == b'VP8 ' and len(content) >= 30 and content[23:26] == b'\x9d\x01\x2a':
            width, height = int.from_bytes(content[26:28], 'little') & 0x3fff, int.from_bytes(content[28:30], 'little') & 0x3fff
        mime, extension = 'image/webp', '.webp'
    else:
        raise store.SupportError('unsupported_photo_format')
    if not 1 <= width <= 8192 or not 1 <= height <= 8192 or width * height > 24000000:
        raise store.SupportError('invalid_photo_dimensions')
    return {'mime': mime, 'extension': extension, 'bytes': len(content),
            'sha256': hashlib.sha256(content).hexdigest()}

def _allowed(request):
    if 'support_cases' not in request.get('perms', ()):
        raise store.SupportError('no_support_permission', 403)
    profile = request.get('profile')
    if not isinstance(profile, dict) or profile.get('id') != db.current_profile():
        raise store.SupportError('server_selection_required', 409)
    if str(request['member'].guild.id) != str(profile.get('guild_id')):
        raise store.SupportError('profile_access_denied', 403)

def endpoint(function):
    @wraps(function)
    async def guarded(self, request):
        try:
            _allowed(request)
            return await function(self, request)
        except store.SupportError as error:
            return web.json_response({'error': error.code}, status=error.status)
    return guarded

class Routes:
    def __init__(self, cog):
        self.cog = cog
        self.store = store.Store(db.get_conn)

    async def actor(self, request):
        return {'id': str(request['member'].id), 'name': str(request['member'].display_name)[:128],
                'admin': await self.cog.is_panel_admin(request['member'])}

    async def assignee(self, request, user_id):
        if not isinstance(user_id, str) or not re.fullmatch(r'[0-9]{1,24}', user_id):
            raise store.SupportError('invalid_assignee')
        guild = request['member'].guild
        # Only currently confirmed guild members with support access; no external lookup.
        member = guild.get_member(int(user_id))
        if member is None or 'support_cases' not in await self.cog.member_permissions(member):
            raise store.SupportError('assignee_not_authorized', 403)
        return {'id': user_id, 'name': str(member.display_name)[:128]}

    @endpoint
    async def cases(self, request):
        if request.method == 'GET':
            result = await asyncio.to_thread(self.store.list, request.query.get('q', ''), request.query.get('status', ''))
        else:
            body = await self.cog._read_json(request)
            result = await asyncio.to_thread(self.store.create, await self.actor(request), body)
        return web.json_response(result)

    @endpoint
    async def staff(self, request):
        from .adminpanel import PRESETS
        from .permissions import role_permissions
        guild = request['member'].guild
        members = guild.members
        role_map = await self.cog.config.guild(guild).role_map()
        user_map = await self.cog.config.guild(guild).user_map()
        support_presets = {name for name, permissions in PRESETS.items() if 'support_cases' in permissions}
        owners = set(getattr(self.cog.bot, 'owner_ids', ()) or ())
        if getattr(self.cog.bot, 'owner_id', None):
            owners.add(self.cog.bot.owner_id)
        result = []
        # Bounded local guild member cache, no HTTP loop.
        for member in members[:2000]:
            if getattr(member, 'bot', False):
                continue
            candidate = (member.id in owners
                or bool(getattr(getattr(member, 'guild_permissions', None), 'administrator', False))
                or user_map.get(str(member.id)) in support_presets
                or any('support_cases' in role_permissions(role_map.get(str(role.id)), PRESETS) for role in member.roles))
            if not candidate:
                continue
            if 'support_cases' in await self.cog.member_permissions(member):
                result.append({'id': str(member.id), 'name': str(member.display_name)[:128]})
            if len(result) >= 200:
                break
        return web.json_response({'staff': sorted(result, key=lambda row: row['name'].lower()),
                                  'limitedToConfirmedMembers': True})

    @endpoint
    async def case(self, request):
        case_id = int(request.match_info['case_id'])
        if request.method == 'GET':
            return web.json_response(await asyncio.to_thread(self.store.detail, case_id))
        body = await self.cog._read_json(request)
        if not isinstance(body, dict):
            raise store.SupportError('invalid_case_payload')
        kwargs = {}
        if body.get('operation') == 'assign':
            kwargs['assignee'] = await self.assignee(request, body.get('assignedTo'))
        if body.get('operation') == 'report':
            action_id = body.get('actionId')
            if not isinstance(action_id, str) or len(action_id) > 128:
                raise store.SupportError('invalid_action_id')
            action = await asyncio.to_thread(db.get_action, action_id)
            required = 'support_diagnostics' if action and action.get('action_type') == 'support_diagnose' else 'support_vehicles'
            if required not in request['perms']:
                raise store.SupportError('no_report_permission', 403)
            kwargs['report'] = store.trusted_report(action, request['profile']['id'])
        result = await asyncio.to_thread(self.store.update, await self.actor(request), case_id, body, **kwargs)
        return web.json_response(result)

    @endpoint
    async def upload(self, request):
        case_id = int(request.match_info['case_id'])
        request_id = store._request_id(request.headers.get('X-Request-ID'))
        try:
            version = int(request.headers.get('X-Case-Version', ''))
        except (TypeError, ValueError):
            raise store.SupportError('invalid_version')
        if not request.content_type.startswith('multipart/'):
            raise store.SupportError('multipart_required')
        try:
            reader = await request.multipart()
            part = await reader.next()
            if part is None or part.name != 'file' or part.headers.get('Content-Encoding'):
                raise store.SupportError('photo_file_required')
            data = bytearray()
            while True:
                chunk = await part.read_chunk(65536)
                if not chunk:
                    break
                data.extend(chunk)
                if len(data) > PHOTO_LIMIT:
                    raise store.SupportError('photo_too_large', 413)
            # No hidden extra fields/files. File bytes are never decoded as text.
            if await reader.next() is not None:
                raise store.SupportError('one_photo_per_request')
        except (ValueError, AssertionError):
            raise store.SupportError('invalid_photo_upload')
        content = bytes(data)
        meta = image_metadata(content)
        meta['name'] = str(part.filename or 'Support-Foto').replace('\\', '/').split('/')[-1][:128] or 'Support-Foto'
        meta['name'] = ''.join(char for char in meta['name'] if ord(char) >= 32)
        actor = await self.actor(request)
        root = Path(db.profile_data_dir()) / 'support_media'
        written = []
        def write(filename):
            root.mkdir(parents=True, exist_ok=True)
            target = root / filename
            if target.resolve().parent != root.resolve():
                raise store.SupportError('invalid_photo_path')
            with target.open('xb') as file:
                file.write(content)
            written.append(target)
        try:
            result = await asyncio.to_thread(self.store.add_photo, actor, case_id, request_id, version, meta, write)
        except Exception:
            # Remove only the new generated photo from this failed transaction.
            for target in written:
                if target.resolve().parent == root.resolve():
                    target.unlink(missing_ok=True)
            raise
        return web.json_response(result)

    @endpoint
    async def photo(self, request):
        photo = await asyncio.to_thread(self.store.photo, request.match_info['photo_id'])
        root = Path(db.profile_data_dir()) / 'support_media'
        path = root / photo['filename']
        if path.resolve().parent != root.resolve() or not path.is_file():
            raise store.SupportError('photo_file_unavailable', 404)
        def bounded_read():
            with path.open('rb') as file:
                return file.read(PHOTO_LIMIT + 1)
        content = await asyncio.to_thread(bounded_read)
        if len(content) != photo['bytes'] or hashlib.sha256(content).hexdigest() != photo['sha256']:
            raise store.SupportError('photo_integrity_unconfirmed', 409)
        return web.Response(body=content, content_type=photo['mime'], headers={
            'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
            'Content-Disposition': 'inline; filename="support-foto' + path.suffix + '"',
            'Content-Security-Policy': "default-src 'none'; sandbox"})

def register_routes(cog, app):
    routes = Routes(cog)
    base = '/api/panel/support'
    app.router.add_get(base + '/cases', routes.cases)
    app.router.add_post(base + '/cases', routes.cases)
    app.router.add_get(base + '/staff', routes.staff)
    app.router.add_get(base + '/cases/{case_id:[1-9][0-9]{0,9}}', routes.case)
    app.router.add_post(base + '/cases/{case_id:[1-9][0-9]{0,9}}', routes.case)
    app.router.add_post(base + '/cases/{case_id:[1-9][0-9]{0,9}}/photos', routes.upload)
    app.router.add_get(base + '/photos/{photo_id:[a-f0-9]{32}}', routes.photo)
