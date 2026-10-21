"""Verified native draft operations, isolated from the user's running editor."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import re
import shutil
import time
import uuid

from native import DEFAULT_INSTALL, NativeError, NativeSession

RATIOS = ('9:16', '16:9', '1:1', '4:3', '3:4')
PLACEHOLDER = re.compile(r'^##_draftpath_placeholder_[^#]+_##[/\\]?')


def sha256(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def source_file(path: str | Path) -> Path:
    result = Path(path).expanduser().resolve()
    if result.is_dir():
        result /= 'draft_content.json'
    if not result.is_file():
        raise FileNotFoundError(f'Draft file not found: {result}')
    return result


def resolve_media(value: str, root: Path) -> Path:
    if PLACEHOLDER.match(value):
        result = (root / PLACEHOLDER.sub('', value)).resolve()
        if not result.is_relative_to(root.resolve()):
            raise ValueError('Draft-relative media path escapes its folder')
        return result
    if '://' in value:
        raise ValueError('Only local media are supported; no implicit downloads')
    result = Path(value)
    return (result if result.is_absolute() else root / result).resolve()


def primary_media(snapshot: dict):
    for kind in ('videos', 'audios'):
        for material in snapshot.get('materials', {}).get(kind, []):
            if material.get('path'):
                yield material


def summarize(snapshot: dict, root: Path) -> dict:
    counts = {}
    for track in snapshot.get('tracks', []):
        kind = track.get('type', 'unknown')
        counts[kind] = counts.get(kind, 0) + len(track.get('segments', []))
    missing = [str(resolve_media(m['path'], root)) for m in primary_media(snapshot)
               if not resolve_media(m['path'], root).is_file()]
    return {'duration_us': snapshot.get('duration'), 'canvas': snapshot.get('canvas_config'),
            'segments': counts, 'missing_primary_media': missing}


def doctor(install=DEFAULT_INSTALL) -> dict:
    with NativeSession(install) as native:
        return {'install': str(native.install), 'version': native.install.name,
                'initialization': native.ready, 'desktop_control_used': False,
                'verified_capabilities': ['encrypted_draft_read', 'encrypted_draft_write',
                                          'draft_session', 'canvas_ratio', 'local_image_add',
                                          'catalog_effect_bind', 'catalog_transition_bind',
                                          'catalog_sound_bind', 'catalog_music_bind',
                                          'saved_encrypted_draft_reedit', 'uniform_caption_replace',
                                          'cached_sticker_apply', 'cached_subtitle_template_apply',
                                          'cached_stock_video_append', 'offline_batch_edit',
                                          'compact_timeline_and_dependency_check',
                                          'segment_transform_and_volume_roundtrip'],
                'online_services': 'Catalog, TTS, source-video frame extraction and audio waveform require the separately running host bridge.',
                'gui_fallback': 'Historical 11.5 GUI export verified. Current workflow: user opens, previews and exports; assistant edits offline without desktop control.',
                'export_workflow': 'manual; installed CLI export was denied by host -100015, no headless file produced',
                'unverified_or_unavailable': ['headless_native_mp4_export', 'headless_timeline_frame_capture',
                                              'text_template_apply',
                                              'digital_human_generation', 'smart_packaging', 'edit_live_gui_project']}


def inspect_draft(path, install=DEFAULT_INSTALL) -> dict:
    source = source_file(path)
    before = sha256(source)
    with NativeSession(install) as native:
        result = native.read(source)
        snapshot = json.loads(result['content'])
    if before != sha256(source):
        raise NativeError('Source changed during inspection; inspect it again when idle')
    return {'path': str(source), 'encrypted': result.get('encrypted'),
            'cipher_type': result.get('cipherType'), 'source_sha256': before,
            **summarize(snapshot, source.parent)}


def _replace_values(value, replacements):
    if isinstance(value, str):
        return replacements.get(value, value)
    if isinstance(value, list):
        return [_replace_values(v, replacements) for v in value]
    if isinstance(value, dict):
        return {k: _replace_values(v, replacements) for k, v in value.items()}
    return value


def make_portrait(source, output, image=None, ratio='9:16', install=DEFAULT_INSTALL) -> dict:
    """Create a new encrypted native draft; never update source or the GUI index."""
    if ratio not in RATIOS:
        raise ValueError(f'Unsupported ratio; choose one of {RATIOS}')
    source = source_file(source)
    output = Path(output).expanduser().resolve()
    if output.is_relative_to(source.parent):
        raise ValueError('Output must be outside the source draft folder')
    if output.exists():
        raise FileExistsError(f'Refusing to overwrite output: {output}')
    picture = Path(image).expanduser().resolve() if image else None
    if picture and (not picture.is_file() or picture.suffix.lower() not in ('.jpg', '.jpeg', '.png')):
        raise ValueError('Image must be an existing local JPG or PNG')
    before = sha256(source)
    with NativeSession(install) as native:
        original = json.loads(native.read(source)['content'])
        assets = [(m['path'], resolve_media(m['path'], source.parent)) for m in primary_media(original)]
        missing = [str(p) for _, p in assets if not p.is_file()]
        if missing:
            raise FileNotFoundError('Missing source media: ' + ', '.join(missing))
        duration = original.get('duration', 0)
        if picture and (not isinstance(duration, int) or duration <= 0):
            raise ValueError('Adding a portrait requires an existing positive draft duration')
        # mkdir(exist_ok=False) also prevents concurrent calls from sharing an output.
        output.mkdir(parents=True, exist_ok=False)
        resources = output / 'Resources'
        resources.mkdir()
        replacements = {}
        for index, (value, path) in enumerate(assets):
            if value in replacements:
                continue
            destination = resources / f'{index:03d}_{path.name}'
            shutil.copy2(path, destination)
            replacements[value] = destination.as_posix()
        snapshot = _replace_values(copy.deepcopy(original), replacements)
        snapshot['id'] = str(uuid.uuid4()).upper()
        snapshot['name'] = output.name
        snapshot['path'] = output.as_posix()
        stage = output / '.native-input' / 'draft_content.json'
        native.write_new(stage, snapshot)
        session = native.call('player', 'create', {'kind':'draft', 'serviceGeneration':1})['sessionId']
        native.call('player', 'load', {'draftPath':str(stage), 'workspacePath':str(stage.parent)}, session)
        edited = native.call('edit', 'draft.setCanvasSize', {'ratio':ratio}, session)
        snapshot = edited['draftSnapshot']
        if picture:
            destination = resources / ('portrait' + picture.suffix.lower())
            shutil.copy2(picture, destination)
            edited = native.call('edit', 'video.add', {
                'path':str(destination), 'duration':duration, 'sourceDuration':duration,
                'sourceStartTime':0, 'startTime':0, 'trackIndex':0,
                'needInsertTargetTrack':False, 'segmentId':str(uuid.uuid4()).upper()}, session)
            snapshot = edited['draftSnapshot']
        target = output / 'draft_content.json'
        native.write_new(target, snapshot)
        loaded = native.read(target)
        reread = json.loads(loaded['content'])
        if reread != snapshot:
            raise NativeError('Native save/read roundtrip mismatch')
        summary = summarize(reread, output)
        if summary['canvas']['ratio'] != ratio or summary['missing_primary_media']:
            raise NativeError('Saved draft failed canvas or local media validation')
        old_counts = summarize(original, source.parent)['segments']
        for kind in ('audio', 'text'):
            if summary['segments'].get(kind, 0) != old_counts.get(kind, 0):
                raise NativeError(f'Native edit unexpectedly changed {kind} segment count')
        if picture and summary['segments'].get('video', 0) != old_counts.get('video', 0) + 1:
            raise NativeError('Image segment was not added')
        if sha256(source) != before:
            raise NativeError('Source changed while editing; original was not written by this tool')
        # Minimal local metadata; GUI discovery/import is deliberately not claimed as verified.
        meta = {'draft_id':snapshot['id'], 'draft_name':output.name,
                'draft_fold_path':output.as_posix(), 'draft_root_path':str(output.parent),
                'draft_type':'', 'draft_cover':'', 'draft_materials':[],
                'tm_duration':reread.get('duration', 0),
                'tm_draft_create':int(time.time()*1_000_000),
                'tm_draft_modified':int(time.time()*1_000_000), 'tm_draft_removed':0}
        native.write_new(output / 'draft_meta_info.json', meta)
        report = {'status':'verified_native_draft', 'draft_path':str(target),
                  'desktop_control_used':False, 'roundtrip_equal':True,
                  'encrypted':loaded.get('encrypted'), 'cipher_type':loaded.get('cipherType'),
                  'source_unchanged':True, 'source_sha256':before,
                  'source':str(source), 'install':str(native.install),
                  'native_operations':native.trace, **summary,
                  'gui_open_verified':False, 'native_mp4_export_verified':False}
        (output / 'verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        return report
