"""Re-edit encrypted drafts through selected, loss-preserving local model changes.

The installed JavaScript model normalizes/drops some unrelated native fields. Its
snapshot must never replace a whole native draft. Only requested segments and
their material dependencies are merged; all other data comes from the original.
"""
from __future__ import annotations
import copy
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
from uuid import uuid4

from native import DEFAULT_INSTALL, PROJECT, NativeError, NativeSession
from workflow import primary_media, resolve_media, source_file, sha256, summarize


def _one(items, label):
    items = list(items)
    if len(items) != 1:
        raise ValueError('Expected one ' + label)
    return items[0]


def _segment(snapshot, segment_id):
    return _one(((t, s) for t in snapshot.get('tracks', []) for s in t.get('segments', [])
                 if s.get('id') == segment_id), 'target segment')


def _materials(snapshot):
    result = {}
    for kind, items in snapshot.get('materials', {}).items():
        if not isinstance(items, list):
            continue
        for material in items:
            if not isinstance(material, dict) or not material.get('id'):
                continue
            if material['id'] in result:
                raise ValueError('Duplicate material ID')
            result[material['id']] = (kind, material)
    return result


def _text_material(snapshot, segment_id):
    track, segment = _segment(snapshot, segment_id)
    if track.get('type') != 'text':
        raise ValueError('Target must be a text segment')
    kind, material = _materials(snapshot)[segment['material_id']]
    if kind != 'texts':
        raise ValueError('Target text material is unsupported')
    if sum(s.get('material_id') == material['id'] for t in snapshot['tracks'] for s in t.get('segments', [])) != 1:
        raise ValueError('Shared text material requires an explicit split before editing')
    return segment, material


def edit_caption_snapshot(snapshot, segment_id, text):
    if not isinstance(text, str) or not text.strip() or len(text) > 200:
        raise ValueError('Replacement caption must contain 1–200 characters')
    updated = copy.deepcopy(snapshot)
    _, material = _text_material(updated, segment_id)
    rich = json.loads(material['content'])
    old = rich.get('text')
    styles = rich.get('styles', [])
    if not isinstance(old, str) or len(styles) != 1 or styles[0].get('range') != [0, len(old.encode('utf-16-le')) // 2]:
        raise ValueError('Caption replacement currently requires one uniform full-length style')
    if text == old:
        raise ValueError('Caption is unchanged')
    rich['text'] = text
    styles[0]['range'] = [0, len(text.encode('utf-16-le')) // 2]
    material['content'] = json.dumps(rich, ensure_ascii=False, separators=(',', ':'))
    for key in ('text', 'base_content'):
        if material.get(key):
            # Model-specific base content can carry rich styling; do not guess.
            if key == 'base_content':
                raise ValueError('Caption has base_content; this format is not supported for text replacement')
            material[key] = text
    # Existing voice clips remain exactly as supplied. No implicit TTS request.
    material['tts_auto_update'] = False
    for key in ('words', 'current_words'):
        if key in material:
            material[key] = {}
    return updated


def delta_overlay(original, before, after):
    """Apply actual action changes, retaining fields missing from SDK normalization."""
    if before == after:
        return copy.deepcopy(original)
    if not all(isinstance(x, dict) for x in (original, before, after)):
        return copy.deepcopy(after)
    result = copy.deepcopy(original)
    for key in before.keys() - after.keys():
        result.pop(key, None)
    for key, value in after.items():
        if key not in before:
            result[key] = copy.deepcopy(value)
        elif before[key] != value:
            result[key] = delta_overlay(result.get(key), before[key], value)
    return result


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)


def merge_model_result(original, before, after, kind, segment_id):
    updated = copy.deepcopy(original)
    after_track, generated = _segment(after, segment_id)
    materials = _materials(after)
    seeds = []
    if kind in ('sticker', 'stock-video'):
        if any(s.get('id') == segment_id for t in original['tracks'] for s in t.get('segments', [])):
            raise ValueError('New segment ID collides with an existing segment')
        if kind == 'sticker':
            if after_track.get('type') != 'sticker' or len(after_track.get('segments', [])) != 1:
                raise ValueError('Model did not produce one sticker track')
            if any(t['id'] == after_track['id'] for t in original['tracks']):
                raise ValueError('Sticker track ID collision')
            updated['tracks'].insert(1, copy.deepcopy(after_track))
        else:
            target = _one((t for t in updated['tracks'] if t['id'] == after_track['id'] and t.get('type') == 'video'), 'video track')
            target['segments'].append(copy.deepcopy(generated))
            time_range = generated['target_timerange']
            if time_range.get('start', 0) != original['duration']:
                raise ValueError('Stock video must append at the exact end of the draft')
            updated['duration'] = time_range.get('start', 0) + time_range['duration']
        seeds.append(generated)
    elif kind == 'subtitle-template':
        original_segment, original_material = _text_material(updated, segment_id)
        before_segment, before_material = _text_material(before, segment_id)
        after_segment, after_material = _text_material(after, segment_id)
        if before_segment == after_segment and before_material == after_material:
            raise ValueError('Model action made no subtitle change')
        if json.loads(original_material['content'])['text'] != json.loads(after_material['content'])['text']:
            raise ValueError('Template action unexpectedly changed caption text')
        merged_segment = delta_overlay(original_segment, before_segment, after_segment)
        merged_material = delta_overlay(original_material, before_material, after_material)
        # Applying typography must not sever existing narration relationships.
        for key in ('text_to_audio_ids', 'relevance_segment', 'words', 'current_words'):
            if key in original_material:
                merged_material[key] = copy.deepcopy(original_material[key])
        original_segment.clear(); original_segment.update(merged_segment)
        original_material.clear(); original_material.update(merged_material)
        seeds.extend((merged_segment, merged_material))
    else:
        raise ValueError('Unsupported local model operation')
    # Bring over ONLY materials reachable from changed/new fragments. The model
    # synthesizes unrelated vocal/effect defaults, which must not be imported.
    present = _materials(updated)
    pending = list(seeds)
    while pending:
        for value in _strings(pending.pop()):
            if value not in materials or value in present:
                continue
            material_kind, material = materials[value]
            added = copy.deepcopy(material)
            updated['materials'].setdefault(material_kind, []).append(added)
            present[value] = (material_kind, added)
            pending.append(added)
    for seed in seeds:
        for reference in seed.get('extra_material_refs', []):
            if reference not in present:
                raise ValueError('Missing material dependency')
        if seed.get('material_id') and seed['material_id'] not in present:
            raise ValueError('Missing primary material')
    if updated == original:
        raise ValueError('No effective draft change')
    return updated


def _manifest(path, effect_type):
    path = Path(path).resolve()
    if not path.is_file() or path.stat().st_size > 128 * 1024:
        raise ValueError('Expected a local asset verification.json manifest')
    asset = json.loads(path.read_text(encoding='utf-8-sig'))
    if asset.get('effect_type') != effect_type or not str(asset.get('id', '')).isdigit():
        raise ValueError('Asset manifest does not match the requested type')
    if asset.get('paid_type') not in ('free', 'subscribe') or asset.get('is_expired') is True:
        raise ValueError('Asset manifest entitlement is unsupported')
    if not Path(asset['resource_root']).is_dir():
        raise FileNotFoundError('Keep the downloaded resource directory in its original location')
    return asset


def _video_info(path, probe_path):
    probe = Path(probe_path).resolve()
    if not probe.is_file():
        raise FileNotFoundError('Stock-video insertion requires an existing local ffprobe executable')
    result = subprocess.run([str(probe), '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(path)],
        capture_output=True, timeout=20, creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode != 0:
        raise NativeError('Cannot read stock-video media information')
    info = json.loads(result.stdout)
    video = _one((s for s in info['streams'] if s.get('codec_type') == 'video'), 'video stream')
    numerator, denominator = video['avg_frame_rate'].split('/')
    return {'width':int(video['width']), 'height':int(video['height']),
            'duration':round(float(info['format']['duration']) * 1000000),
            'fps':float(numerator)/float(denominator), 'codec':video.get('codec_name', ''),
            'has_audio':any(s.get('codec_type') == 'audio' for s in info['streams'])}


def _model(snapshot, kind, params, install):
    with tempfile.TemporaryDirectory(prefix='jy-draft-model-') as temp:
        folder = Path(temp)
        source, target, request = folder/'source.json', folder/'result.json', folder/'request.json'
        source.write_text(json.dumps(snapshot, ensure_ascii=False), encoding='utf-8')
        request.write_text(json.dumps({'source':str(source), 'output':str(target),
            'install':str(Path(install).resolve()), 'kind':kind, 'params':params}, ensure_ascii=False), encoding='utf-8')
        result = subprocess.run([str(Path(install)/'bun.exe'), str(PROJECT/'data-sdk-host.cjs'), str(request)],
            capture_output=True, timeout=40, creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode != 0 or not target.is_file():
            raise NativeError('Installed draft model failed: ' + result.stderr.decode('utf-8', errors='replace')[:800])
        return json.loads(target.read_text(encoding='utf-8'))


def _prepare(source, output, native):
    source = source_file(source)
    output = Path(output).resolve()
    if output.exists():
        raise FileExistsError('Output already exists; source and existing drafts are never overwritten')
    if output.is_relative_to(source.parent):
        raise ValueError('Output must be outside the source draft folder')
    source_hash = sha256(source)
    readback = native.read(source)
    snapshot = json.loads(readback['content'])
    for media in primary_media(snapshot):
        resolved = resolve_media(media['path'], source.parent)
        if not resolved.is_file():
            raise FileNotFoundError('Missing source media: ' + str(resolved))
        # Independent output retains references to already-downloaded media.
        if not Path(media['path']).is_absolute():
            media['path'] = str(resolved)
    return source, output, source_hash, snapshot, bool(readback.get('encrypted'))


def _save(native, source, output, source_hash, snapshot, input_encrypted, changes):
    if sha256(source) != source_hash:
        raise NativeError('Source changed concurrently; close the editor and retry from a stable copy')
    snapshot.update(id=str(uuid4()).upper(), name=output.name)
    snapshot['path'] = str(output)
    summary = summarize(snapshot, output)
    if summary['missing_primary_media']:
        raise NativeError('Output would reference missing primary media')
    if output.exists():
        raise FileExistsError('Output already exists; refusing to overwrite')
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='.jy-draft-building-', dir=output.parent)).resolve()
    target = output / 'draft_content.json'
    report = {'output_draft':str(target), 'changes':changes, 'source_encrypted':input_encrypted,
              'encrypted_roundtrip_equal':True, 'source_unchanged':True,
              'source_sha256':source_hash, 'summary':summary, 'desktop_control_used':False,
              'visual_effect_verified':False, 'export_verified':False,
              'resources_portable':False}
    try:
        native.write_new(stage/'draft_content.json', snapshot)
        loaded = native.read(stage/'draft_content.json')
        if not loaded.get('encrypted') or json.loads(loaded['content']) != snapshot:
            raise NativeError('Encrypted draft roundtrip did not preserve the complete edited snapshot')
        if sha256(source) != source_hash:
            raise NativeError('Source changed during output validation')
        (stage/'verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        # Windows directory rename refuses an existing destination. The complete
        # validated draft and its verification report become visible together.
        stage.rename(output)
    finally:
        if stage.exists():
            if stage.parent != output.parent.resolve() or not stage.name.startswith('.jy-draft-building-'):
                raise NativeError('Refusing cleanup outside the owned staging directory')
            shutil.rmtree(stage)
    return report


def replace_caption(source, output, segment_id, text, install=DEFAULT_INSTALL):
    with NativeSession(install) as native:
        source, output, digest, original, encrypted = _prepare(source, output, native)
        updated = edit_caption_snapshot(original, segment_id, text)
        return _save(native, source, output, digest, updated, encrypted,
                     {'kind':'caption', 'segment_id':segment_id, 'new_text':text, 'narration_regenerated':False})


def apply_cached_asset_snapshot(original, kind, asset_manifest, segment_id='', start_ms=0,
                                duration_ms=2000, font_manifest='', source_start_ms=0,
                                probe_path='', install=DEFAULT_INSTALL, model_session=None):
    types = {'sticker':2, 'subtitle-template':48, 'stock-video':5}
    if kind not in types:
        raise ValueError('Supported local model assets: sticker, subtitle-template, stock-video')
    if any(type(v) is not int for v in (start_ms, duration_ms, source_start_ms)) or min(start_ms, source_start_ms) < 0 or not 1 <= duration_ms <= 30000:
        raise ValueError('Times must be integer milliseconds; duration must be 1–30000')
    asset = _manifest(asset_manifest, types[kind])
    if kind == 'sticker':
        if (start_ms+duration_ms)*1000 > original['duration']:
            raise ValueError('Sticker would extend past the current draft')
        segment_id = str(uuid4()).upper()
        params = {'trackIndex':1, 'segInfo':{'segId':segment_id,
            'timeRange':{'start':start_ms*1000, 'duration':duration_ms*1000},
            'material':{'name':asset['title'], 'path':asset['resource_root'],
                'resourceId':asset['id'], 'stickerId':asset['effect_id'], 'sourcePlatform':0},
            'clip':{'scaleX':0.4, 'scaleY':0.4, 'transformX':0.4, 'transformY':0.4,
                    'rotation':0, 'flipVertical':False, 'flipHorizontal':False}}}
    elif kind == 'subtitle-template':
        _text_material(original, segment_id)
        style_file = Path(asset['resource_root'])/'content.json'
        style = style_file.read_text(encoding='utf-8-sig')
        parsed = json.loads(style)
        if parsed.get('type') != 'ScriptTemplate' or not parsed.get('children'):
            raise ValueError('Unsupported subtitle template package')
        font = _manifest(font_manifest, 10)
        font_file = _one(Path(font['resource_root']).rglob('*.ttf'), 'downloaded font file')
        import re
        font_ids = set(re.findall(r'font id=\\?"(\d+)', style))
        if not font_ids or font_ids != {str(font['id'])}:
            raise ValueError('Template font dependencies do not match the supplied font manifest')
        params = {'segId':segment_id, 'syncToAll':False, 'applyKeywordsStyle':False, 'applyFontSize':False,
            'templateResource':{'resourceItemParam':{'resourceId':asset['id'], 'effectId':asset['effect_id'],
                'title':asset['title'], 'path':asset['resource_root'], 'sourcePlatform':0},
                'styleJson':style, 'resources':[{'panel':'fonts', 'resourceId':font['id'],
                    'path':str(font_file), 'title':font['title']}]}}
    else:
        media = _one((Path(p) for p in asset.get('media_files', []) if Path(p).suffix.lower() in ('.mp4', '.mov')), 'downloaded stock video')
        if not media.is_file():
            raise FileNotFoundError('Downloaded stock video is missing')
        info = _video_info(media, probe_path)
        if (source_start_ms+duration_ms)*1000 > info['duration']:
            raise ValueError('Requested source range exceeds the stock video')
        video_track = next((t for t in original['tracks'] if t.get('type') == 'video'), None)
        if video_track is None:
            raise ValueError('Appending stock video requires an existing video track')
        segment_id = str(uuid4()).upper()
        params = {'trackIndex':original['tracks'].index(video_track), 'videos':[{
            'path':str(media), 'segmentId':segment_id, 'materialName':asset['title'],
            'startTime':original['duration'], 'sourceStartTime':source_start_ms*1000,
            'sourceDuration':duration_ms*1000, 'duration':duration_ms*1000,
            'size':{'width':info['width'], 'height':info['height']},
            'clip':{'scaleX':1, 'scaleY':1, 'transformX':0, 'transformY':0, 'rotation':0},
            'hasAudio':info['has_audio'], 'mediaInfo':{'type':'AudioVideo',
                'width':info['width'], 'height':info['height'], 'rotation':0,
                'duration':info['duration'], 'bitrate':0, 'fps':info['fps'], 'codec':info['codec']},
            'materialId':asset['id'], 'source':asset.get('source',1), 'sourcePlatform':0}]}
    model = model_session.apply(original, kind, params) if model_session else _model(original, kind, params, install)
    updated = merge_model_result(original, model['before'], model['after'], kind, segment_id)
    _, saved_segment = _segment(updated, segment_id)
    material_kind, bound = _materials(updated)[saved_segment['material_id']]
    if kind == 'subtitle-template':
        binding = bound.get('caption_template_info') or {}
        if str(binding.get('resource_id')) != asset['id'] or binding.get('path') != asset['resource_root']:
            raise NativeError('Subtitle template resource binding is missing')
    else:
        id_key = 'resource_id' if kind == 'sticker' else 'material_id'
        expected_range = {'start':start_ms*1000 if kind=='sticker' else original['duration'], 'duration':duration_ms*1000}
        if str(bound.get(id_key)) != asset['id'] or saved_segment.get('target_timerange') != expected_range:
            raise NativeError('New material ID or time range does not match the request')
        if kind == 'stock-video':
            bound['has_audio'] = info['has_audio']
    return updated, (
        {'kind':kind, 'segment_id':segment_id, 'resource_id':asset['id'], 'asset_title':asset['title'],
         'model_action_and_references_verified':True})


def apply_cached_asset(source, output, kind, asset_manifest, segment_id='', start_ms=0,
                       duration_ms=2000, font_manifest='', source_start_ms=0,
                       probe_path='', install=DEFAULT_INSTALL):
    with NativeSession(install) as native:
        source, output, digest, original, encrypted = _prepare(source, output, native)
        updated, changes = apply_cached_asset_snapshot(original, kind, asset_manifest,
            segment_id, start_ms, duration_ms, font_manifest, source_start_ms, probe_path, install)
        return _save(native, source, output, digest, updated, encrypted, changes)
