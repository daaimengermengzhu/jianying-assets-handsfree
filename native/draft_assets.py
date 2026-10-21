"""Verified native insertion of one official asset into a NEW encrypted draft."""
import copy
import json
from pathlib import Path
from uuid import uuid4

from asset_resources import retrieve_asset
from native import NativeSession, NativeError, DEFAULT_INSTALL
from workflow import primary_media, resolve_media, source_file, sha256, summarize

KINDS = {'effect': 7, 'sound': 3, 'music': 4, 'transition': 19}


def add_catalog_asset(source, output, kind, resource_id, resource_source=1,
                      start_ms=0, duration_ms=2000, segment_id='', install=DEFAULT_INSTALL):
    if not isinstance(kind, str) or kind not in KINDS:
        raise ValueError('已验证写入类型：effect、sound、music、transition。')
    if not isinstance(resource_id, str) or not resource_id.isdigit():
        raise ValueError('需要检索结果中的数字素材 ID。')
    if type(resource_source) is not int or resource_source not in (1, 2, 3):
        raise ValueError('需要目录返回的素材来源。')
    if type(start_ms) is not int or start_ms < 0 or type(duration_ms) is not int or not 1 <= duration_ms <= 30000:
        raise ValueError('start_ms 必须非负；duration_ms 必须为 1–30000 整数毫秒。')
    source = source_file(source)
    output = Path(output).resolve()
    if output.exists():
        raise FileExistsError('输出目录已存在，拒绝覆盖。')
    if output.is_relative_to(source.parent):
        raise ValueError('输出必须位于源草稿目录之外。')
    source_hash = sha256(source)
    start_us, duration_us = start_ms * 1000, duration_ms * 1000
    with NativeSession(install, timeout=20) as native:
        snapshot = json.loads(native.read(source)['content'])
        for media in primary_media(snapshot):
            path = resolve_media(media['path'], source.parent)
            if not path.is_file():
                raise FileNotFoundError('源草稿主媒体缺失：' + str(path))
            media['path'] = str(path)
        if kind == 'transition':
            target = following = None
            for track in snapshot.get('tracks', []):
                if track.get('type') != 'video':
                    continue
                for index, segment in enumerate(track.get('segments', [])):
                    if segment.get('id') == segment_id and index + 1 < len(track['segments']):
                        target, following = segment, track['segments'][index + 1]
            if target is None:
                raise ValueError('转场需要指定同轨中后面还有画面的 segment_id。')
            first_range, second_range = target['target_timerange'], following['target_timerange']
            if first_range['start'] + first_range['duration'] != second_range['start']:
                raise ValueError('转场两侧的画面必须相邻。')
            if duration_us * 2 > min(first_range['duration'], second_range['duration']):
                raise ValueError('转场时长不得超过两侧较短片段的一半。')
        elif start_us + duration_us > snapshot.get('duration', 0):
            raise ValueError('素材片段超出当前草稿时长。')
        output.mkdir(parents=True, exist_ok=False)
        asset = retrieve_asset(resource_id, KINDS[kind], resource_source, output / 'Resources')
        if kind in ('sound', 'music'):
            if not asset.get('media_files') or not asset.get('duration_ms'):
                raise NativeError('音频缺少可用文件或可靠时长，未写入草稿。')
            duration_us = min(duration_us, int(asset['duration_ms'] * 1000))
        snapshot = copy.deepcopy(snapshot)
        snapshot.update(id=str(uuid4()).upper(), name='官方素材_' + asset['title'])
        prepared = output / 'source/draft_content.json'
        native.write_new(prepared, snapshot)
        sid = native.call('player', 'create', {'kind': 'draft', 'serviceGeneration': 1})['sessionId']
        native.call('player', 'load', {'draftPath': str(prepared), 'workspacePath': str(prepared.parent)}, sid)
        if kind == 'effect':
            operation = 'effect.add'
            params = {'trackIndex': len(snapshot['tracks']), 'trackId': str(uuid4()).upper(),
                'segmentId': str(uuid4()).upper(), 'targetTimeRange': {'start': start_us, 'duration': duration_us},
                'applyType': 0, 'material': {'path': asset['resource_root'], 'name': asset['title'],
                    'resId': asset['id'], 'resourceId': asset['id'], 'effectId': asset['effect_id'],
                    'type': 18, 'sourcePlatform': 0, 'adjustParams': []}}
            material_key, expected_type, expected_path = 'video_effects', 'video_effect', asset['resource_root']
        elif kind in ('sound', 'music'):
            operation = 'audio.add'
            params = {'audioPath': asset['media_files'][0], 'audioTitle': asset['title'],
                'audioId': asset['id'], 'resourceId': asset['id'], 'type': 6 if kind == 'sound' else 4,
                'duration': duration_us, 'sourceDuration': duration_us, 'sourceStartTime': 0, 'startTime': start_us,
                'trackId': str(uuid4()).upper(),
                'targetTrackIndex': sum(t.get('type') == 'audio' for t in snapshot['tracks']),
                'needInsertTargetTrack': True, 'segmentId': str(uuid4()).upper(),
                'volume': 0.5 if kind == 'sound' else 0.15}
            material_key, expected_type, expected_path = 'audios', kind, asset['media_files'][0]
        else:
            operation = 'video.setTransition'
            params = {'segId': segment_id, 'segmentId': segment_id, 'duration': duration_us,
                'path': asset['resource_root'], 'name': asset['title'], 'resourceId': asset['id'],
                'effectId': asset['effect_id'], 'sourcePlatform': 0, 'isOverlap': False}
            material_key, expected_type, expected_path = 'transitions', 'transition', asset['resource_root']
        old_ids = {m['id'] for m in snapshot['materials'].get(material_key, [])}
        result = native.call('edit', operation, params, sid)
        updated = result['draftSnapshot']
        candidates = [m for m in updated['materials'].get(material_key, [])
                      if m.get('resource_id') == resource_id and m.get('path') == expected_path
                      and m.get('type') == expected_type]
        if kind == 'transition':
            segment = next(s for t in updated['tracks'] for s in t['segments'] if s['id'] == segment_id)
            valid = [m for m in candidates if m['id'] in segment.get('extra_material_refs', [])
                     and m.get('duration') == duration_us]
        else:
            valid = [m for m in candidates if m['id'] not in old_ids]
            linked = [s for t in updated['tracks'] for s in t['segments']
                      if s.get('material_id') in {m['id'] for m in valid}]
            if len(linked) != 1 or linked[0].get('target_timerange') != {'start': start_us, 'duration': duration_us}:
                raise NativeError('原生片段时长或引用校验未通过，未交付最终草稿。')
        if len(valid) != 1:
            raise NativeError('原生素材类型、路径或资源 ID 校验未通过，未交付最终草稿。')
        target = output / 'draft_content.json'
        native.write_new(target, updated)
        readback = native.read(target)
        if not readback.get('encrypted') or json.loads(readback['content']) != updated:
            raise NativeError('加密保存读回校验失败。')
        summary = summarize(updated, output)
        if summary['missing_primary_media']:
            raise NativeError('输出草稿主媒体检查未通过。')
    if sha256(source) != source_hash:
        raise NativeError('源草稿在操作期间变化。')
    report = {'output_draft': str(target), 'kind': kind, 'asset': {**asset, 'applied': True},
              'native_binding_verified': True, 'encrypted_roundtrip_equal': True, 'source_unchanged': True,
              'summary': summary, 'visual_effect_verified': False, 'export_verified': False}
    (output / 'verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return report
