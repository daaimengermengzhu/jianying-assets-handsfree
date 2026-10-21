"""Bounded offline edits: one read, private workers, one validated publication."""
import copy
from contextlib import ExitStack
import json
import math
from pathlib import Path

from native import DEFAULT_INSTALL, NativeError, NativeSession
from model_session import ModelSession
from model_edits import (_prepare, _save, _segment, _materials, _strings,
                         edit_caption_snapshot, apply_cached_asset_snapshot)
from workflow import source_file, sha256, resolve_media


FIELDS = {
    'replace-caption': ({'segment_id', 'text'}, set()),
    'apply-cached-asset': ({'kind', 'asset_manifest'},
        {'segment_id', 'start_ms', 'duration_ms', 'font_manifest', 'source_start_ms'}),
    'transform': ({'segment_id'}, {'scale', 'x', 'y', 'rotation'}),
    'volume': ({'segment_id', 'volume'}, set()),
}


def _number(value, low, high, label):
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f'{label} must be a finite number from {low} to {high}')


def validate_operations(operations):
    if not isinstance(operations, list) or not 1 <= len(operations) <= 100:
        raise ValueError('A batch requires 1–100 operations')
    for op in operations:
        if not isinstance(op, dict) or not isinstance(op.get('action'), str) or op['action'] not in FIELDS:
            raise ValueError('Unsupported batch action')
        required, optional = FIELDS[op['action']]
        if not required <= op.keys() or op.keys() - (required | optional | {'action'}):
            raise ValueError('Missing or unknown fields in ' + op['action'])
        if 'segment_id' in required and (not isinstance(op['segment_id'], str) or not op['segment_id']):
            raise ValueError('segment_id must identify an existing segment')
        if op['action'] == 'volume':
            _number(op['volume'], 0, 2, 'volume')
        elif op['action'] == 'transform':
            if not optional.intersection(op):
                raise ValueError('Transform requires scale, x, y or rotation')
            for key, bounds in {'scale':(0.01, 10), 'x':(-2, 2), 'y':(-2, 2), 'rotation':(-360, 360)}.items():
                if key in op:
                    _number(op[key], *bounds, key)
        elif op['action'] == 'replace-caption':
            if not isinstance(op['text'], str) or not op['text'].strip() or len(op['text']) > 200:
                raise ValueError('Replacement caption must contain 1–200 characters')
        elif op['kind'] not in ('sticker', 'subtitle-template', 'stock-video'):
            raise ValueError('Unsupported cached asset kind')


def apply_basic_edit(snapshot, operation):
    validate_operations([operation])
    result = copy.deepcopy(snapshot)
    track, segment = _segment(result, operation['segment_id'])
    if operation['action'] == 'volume':
        if track.get('type') not in ('audio', 'video'):
            raise ValueError('Volume requires an audio or video segment')
        segment['volume'] = operation['volume']
    elif operation['action'] == 'transform':
        if track.get('type') not in ('video', 'text', 'sticker'):
            raise ValueError('Transform requires a video, text or sticker segment')
        clip = segment.setdefault('clip', {})
        if not isinstance(clip, dict):
            raise ValueError('Unsupported clip transform structure')
        if 'scale' in operation:
            clip.setdefault('scale', {}).update(x=operation['scale'], y=operation['scale'])
        for key in ('x', 'y'):
            if key in operation:
                clip.setdefault('transform', {})[key] = operation[key]
        if 'rotation' in operation:
            clip['rotation'] = operation['rotation']
    else:
        raise ValueError('Unsupported basic edit')
    if result == snapshot:
        raise ValueError('Operation would make no change')
    return result


def _used_resources(snapshot):
    materials = _materials(snapshot)
    fragments = [s for t in snapshot.get('tracks', []) for s in t.get('segments', [])]
    pending = list(fragments)
    found = set()
    missing_refs = {str(ref) for value in fragments
                    for ref in [value.get('material_id'), *value.get('extra_material_refs', [])]
                    if ref and ref not in materials}
    while pending:
        value = pending.pop()
        for ref in _strings(value):
            if ref in materials and ref not in found:
                found.add(ref)
                fragment = materials[ref][1]
                pending.append(fragment)
                fragments.append(fragment)
    return fragments, missing_refs


def _paths(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(item, str) and item:
                if key == 'path' or key.endswith('_path'):
                    yield item
                elif key in ('content', 'style_json') and item.lstrip().startswith(('{', '[')):
                    try:
                        yield from _paths(json.loads(item))
                    except ValueError:
                        pass
            if isinstance(item, (dict, list)):
                yield from _paths(item)
    elif isinstance(value, list):
        for item in value:
            yield from _paths(item)


def resource_issues(snapshot, root):
    """Check recognized local paths and references in reachable materials only."""
    fragments, refs = _used_resources(snapshot)
    missing, remote, relative = set(), set(), set()
    for raw in set(_paths(fragments)):
        if '://' in raw:
            remote.add(raw.split('?', 1)[0])
            continue
        resolved = resolve_media(raw, Path(root))
        if not resolved.exists():
            missing.add(str(resolved))
        if not Path(raw).is_absolute():
            relative.add(raw)
    return {'missing_paths':sorted(missing), 'missing_material_refs':sorted(refs),
            'relative_paths':sorted(relative), 'remote_paths_unchecked':sorted(remote),
            'scope':'Recognized local paths and material references; not a render or deep package validation'}


def _require_resources(snapshot, root):
    issues = resource_issues(snapshot, root)
    if issues['missing_paths'] or issues['missing_material_refs']:
        raise NativeError('Draft resource preflight failed: ' + json.dumps(issues, ensure_ascii=False))
    # Primary relative media were normalized by _prepare. Other relative resource
    # formats must not silently point at a different folder in the new draft.
    if issues['relative_paths'] or issues['remote_paths_unchecked']:
        raise ValueError('Batch needs existing absolute local dependency paths; inspect with timeline first')
    return issues


def edit_batch(source, output, operations, probe_path='', install=DEFAULT_INSTALL):
    validate_operations(operations)
    with ExitStack() as stack:
        native = stack.enter_context(NativeSession(install))
        source, output, digest, snapshot, encrypted = _prepare(source, output, native)
        _require_resources(snapshot, source.parent)
        model = None
        changes = []
        for index, operation in enumerate(operations):
            op = dict(operation)
            action = op.pop('action')
            if action == 'replace-caption':
                snapshot = edit_caption_snapshot(snapshot, op['segment_id'], op['text'])
                changed = {'kind':'caption', 'segment_id':op['segment_id'], 'narration_regenerated':False}
            elif action == 'apply-cached-asset':
                if model is None:
                    model = stack.enter_context(ModelSession(install))
                snapshot, changed = apply_cached_asset_snapshot(snapshot, **op,
                    probe_path=probe_path, install=install, model_session=model)
            else:
                snapshot = apply_basic_edit(snapshot, operation)
                changed = {'kind':action, **op}
            changes.append({'index':index, **changed})
        _require_resources(snapshot, source.parent)
        return _save(native, source, output, digest, snapshot, encrypted,
            {'kind':'batch', 'operation_count':len(changes), 'operations':changes,
             'dependency_preflight_passed':True, 'atomic_publication':True})


def timeline(source, offset=0, limit=30, install=DEFAULT_INSTALL):
    if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError('offset must be nonnegative; limit must be 1–100')
    source = source_file(source)
    before = sha256(source)
    with NativeSession(install) as native:
        read = native.read(source)
        snapshot = json.loads(read['content'])
    if sha256(source) != before:
        raise NativeError('Source changed during timeline inspection')
    materials = _materials(snapshot)
    rows = []
    for track in snapshot.get('tracks', []):
        for segment in track.get('segments', []):
            row = {'segment_id':segment['id'], 'track_id':track['id'], 'type':track.get('type'),
                   'material_id':segment.get('material_id'),
                   'start_ms':segment.get('target_timerange', {}).get('start', 0) / 1000,
                   'duration_ms':segment.get('target_timerange', {}).get('duration', 0) / 1000}
            if track.get('type') == 'text' and segment.get('material_id') in materials:
                try:
                    row['text_preview'] = json.loads(materials[segment['material_id']][1]['content']).get('text', '')[:120]
                except (ValueError, KeyError):
                    row['text_preview'] = '[unsupported rich text]'
            if isinstance(segment.get('clip'), dict):
                row['transform'] = {k:v for k, v in segment['clip'].items() if k in ('scale', 'transform', 'rotation')}
            if 'volume' in segment:
                row['volume'] = segment['volume']
            rows.append(row)
    return {'draft':str(source), 'encrypted':bool(read.get('encrypted')), 'source_unchanged':True,
            'duration_ms':snapshot.get('duration', 0) / 1000, 'segments_total':len(rows),
            'segments':rows[offset:offset+limit], 'next_offset':offset+limit if offset+limit < len(rows) else None,
            'resources':resource_issues(snapshot, source.parent), 'desktop_control_used':False}
