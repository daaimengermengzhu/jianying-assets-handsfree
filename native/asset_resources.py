"""Fetch catalog-issued assets for a local Jianying test draft. No arbitrary URL input."""
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit
from urllib.request import build_opener, ProxyHandler
from uuid import uuid4
import zipfile

from client_services import client_request, material_summary
from host_bridge import HostBridge
from native import NativeError


def unpack_asset(package, target):
    target = Path(target).resolve()
    if target.exists():
        raise FileExistsError('资源目录已存在，拒绝覆盖。')
    with zipfile.ZipFile(io.BytesIO(package)) as archive:
        entries = archive.infolist()
        if sum(info.file_size for info in entries) > 100 * 1024 * 1024 or len(entries) > 10000:
            raise ValueError('解压资源超出单项验证上限。')
        seen = set()
        for info in entries:
            path = PurePosixPath(info.filename.replace('\\', '/'))
            normalized = str(path).casefold()
            if (path.is_absolute() or '..' in path.parts or ':' in str(path)
                    or any(part.endswith((' ', '.')) for part in path.parts)
                    or any(part.split('.')[0].upper() in {'CON', 'PRN', 'AUX', 'NUL',
                        *('COM' + str(i) for i in range(1, 10)),
                        *('LPT' + str(i) for i in range(1, 10))} for part in path.parts)
                    or (info.external_attr >> 16) & 0o170000 == 0o120000
                    or normalized in seen):
                raise ValueError('资源包含不安全的压缩路径。')
            seen.add(normalized)
        archive.extractall(target)
    configs = sorted(target.rglob('config.json'), key=lambda p: len(p.parts))
    media = [p for p in target.rglob('*') if p.suffix.lower() in ('.mp3', '.wav', '.m4a', '.mp4', '.mov')]
    return {'file_count': sum(not e.is_dir() for e in entries),
            'resource_root': str(configs[0].parent if configs else target),
            'config_files': [str(p) for p in configs], 'media_files': [str(p) for p in media]}


def _resource_url(item):
    common = item['common_attr']
    # Sticker download_info can be a GIF preview, while MD5 describes item_urls' ZIP.
    # Keep the checksum check; select the actual package instead of accepting the preview.
    if common.get('effect_type') == 2:
        first = next(iter(common.get('item_urls') or []), '')
        url = first.get('url') if isinstance(first, dict) else first
        if url:
            return url, True
    # Mirror the installed client's precedence for full stock-video resources.
    video = item.get('video') or {}
    candidates = [v for v in (video.get('transcoded_video') or {}).values() if v.get('video_url')]
    best = max(candidates, key=lambda v: v.get('size') or 0, default=video.get('origin_video') or {})
    if best.get('video_url'):
        return best['video_url'], False
    extra = json.loads(common.get('extra') or '{}')
    resources = extra.get('Resources')
    if isinstance(resources, str) and resources.startswith('https://'):
        return resources, False
    if isinstance(resources, list) and resources and isinstance(resources[0], dict):
        first = resources[0]
        if first.get('url') or first.get('uri'):
            return first.get('url') or first['uri'], False
    url = (common.get('download_info') or {}).get('url')
    if not url:
        first = next(iter(common.get('item_urls') or []), '')
        url = first.get('url') if isinstance(first, dict) else first
    return url or common.get('file_url'), True


def retrieve_asset(resource_id, effect_type, source, output_root):
    if not isinstance(resource_id, str) or not resource_id.isdigit():
        raise ValueError('需要目录返回的数字素材 ID。')
    if type(effect_type) is not int or effect_type not in (2, 3, 4, 5, 6, 7, 10, 12, 19, 48):
        raise ValueError('当前资源验证不支持此素材类型。')
    if type(source) is not int or source not in (1, 2, 3):
        raise ValueError('需要目录返回的素材来源。')
    output = Path(output_root).resolve() / (resource_id + '-' + uuid4().hex[:8])
    with HostBridge() as host:
        account = host._jsb('getUserSubcriptionInfo', {}).get('user_info') or {}
        data = client_request(host, '/artist/v1/effect/mget_item', {
            'app_id': 3704, 'items': [{'id': resource_id, 'effect_type': effect_type, 'source': source}],
            'pack_optional': {'need_contract': True, 'need_favorite_info': True}})
        item = next((row for row in data.get('effect_item_list', [])
                     if str((row.get('common_attr') or {}).get('id')) == resource_id), None)
        if item is None:
            raise NativeError('服务未返回该素材，未下载。')
        summary = material_summary(item)
        if summary['effect_type'] != effect_type or summary['is_expired'] is True:
            raise NativeError('素材类型不符或已经过期，未下载。')
        if summary['paid_type'] not in ('free', 'subscribe'):
            raise NativeError('素材不是已识别的免费或会员订阅资源，未下载。')
        if summary['is_vip'] and not any(account.get(k) for k in ('is_vip', 'is_svip', 'is_ultra')):
            raise NativeError('未确认当前会员权益，未下载。')
        url, checksum_applies = _resource_url(item)
        if not isinstance(url, str) or urlsplit(url).scheme != 'https':
            raise NativeError('素材没有正常发放的 HTTPS 资源地址。')
        expected_md5 = item['common_attr'].get('md5') if checksum_applies else None
        try:
            with build_opener(ProxyHandler({})).open(url, timeout=30) as response:
                package = response.read(50 * 1024 * 1024 + 1)
        except Exception:
            raise NativeError('素材资源下载失败。') from None
    if not package or len(package) > 50 * 1024 * 1024:
        raise ValueError('资源为空或超过 50 MB 单项验证上限。')
    digest = hashlib.md5(package).hexdigest()
    if expected_md5 and digest.lower() != expected_md5.lower():
        raise NativeError('素材包与目录校验值不符。')
    result = {**summary, 'bytes': len(package), 'md5_verified': bool(expected_md5),
              'applied': False, 'visual_effect_verified': False}
    audio = item.get('audio_effect') or item.get('song') or {}
    if isinstance(audio.get('duration_ms'), (int, float)) and audio['duration_ms'] > 0:
        result['duration_ms'] = audio['duration_ms']
    elif isinstance(audio.get('duration'), (int, float)) and audio['duration'] > 0:
        result['duration_ms'] = audio['duration'] * 1000
    output.mkdir(parents=True, exist_ok=False)
    if zipfile.is_zipfile(io.BytesIO(package)):
        result.update(format='zip', **unpack_asset(package, output / 'resource'))
    else:
        extension = ('.m4a' if effect_type in (3, 4) else '.mp4') if package[4:8] == b'ftyp' else '.wav' if package[:4] == b'RIFF' else '.mp3' if (
            package.startswith(b'ID3') or (len(package) > 1 and package[0] == 255 and package[1] & 224 == 224)) else '.bin'
        target = output / ('resource' + extension)
        target.write_bytes(package)
        result.update(format=extension[1:], media_files=[str(target)], resource_root=str(output))
    (output / 'verification.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    return result
