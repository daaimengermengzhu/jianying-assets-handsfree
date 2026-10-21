"""Small local CLI. MCP is optional; the CLI uses Python's standard library only."""
import argparse
import os
import shutil
import json
import sys
from pathlib import Path
from workflow import DEFAULT_INSTALL, RATIOS, doctor, inspect_draft, make_portrait
from host_bridge import host_status, voice_categories, search_voices
from client_services import material_categories, list_materials, search_materials, SEARCH_TYPES
from tts import synthesize, VOICES
from native import PROJECT
from draft_assets import add_catalog_asset, KINDS
from host_media import extract_video_frame, audio_waveform
from model_edits import replace_caption, apply_cached_asset
from batch_edits import edit_batch, timeline


def main():
    parser = argparse.ArgumentParser(description='Jianying native draft bridge — no desktop control')
    parser.add_argument('--install', default=str(DEFAULT_INSTALL))
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('doctor')
    commands.add_parser('host-status')
    commands.add_parser('voice-categories')
    batch = commands.add_parser('edit-batch')
    batch.add_argument('--source', required=True)
    batch.add_argument('--output', required=True)
    batch.add_argument('--operations-file', required=True)
    batch.add_argument('--ffprobe', default=os.environ.get('JY_FFPROBE') or shutil.which('ffprobe') or 'ffprobe.exe')
    tracks = commands.add_parser('timeline')
    tracks.add_argument('source')
    tracks.add_argument('--offset', type=int, default=0)
    tracks.add_argument('--limit', type=int, default=30)
    caption = commands.add_parser('replace-caption')
    caption.add_argument('--source', required=True)
    caption.add_argument('--output', required=True)
    caption.add_argument('--segment-id', required=True)
    caption.add_argument('--text', required=True)
    model = commands.add_parser('apply-cached-asset')
    model.add_argument('--source', required=True)
    model.add_argument('--output', required=True)
    model.add_argument('--kind', choices=['sticker', 'subtitle-template', 'stock-video'], required=True)
    model.add_argument('--asset-manifest', required=True)
    model.add_argument('--segment-id', default='')
    model.add_argument('--start-ms', type=int, default=0)
    model.add_argument('--duration-ms', type=int, default=2000)
    model.add_argument('--font-manifest', default='')
    model.add_argument('--source-start-ms', type=int, default=0)
    model.add_argument('--ffprobe', default=os.environ.get('JY_FFPROBE') or shutil.which('ffprobe') or 'ffprobe.exe')
    frame = commands.add_parser('extract-frame')
    frame.add_argument('media')
    frame.add_argument('--timestamp-ms', type=int, default=0)
    frame.add_argument('--width', type=int, default=320)
    frame.add_argument('--height', type=int, default=180)
    frame.add_argument('--output-root', default=str(PROJECT / 'output' / 'frames'))
    waveform = commands.add_parser('audio-waveform')
    waveform.add_argument('media')
    waveform.add_argument('--start-ms', type=int, default=0)
    waveform.add_argument('--duration-ms', type=int, default=5000)
    waveform.add_argument('--max-points', type=int, default=128)
    voices = commands.add_parser('search-voices')
    voices.add_argument('keyword')
    voices.add_argument('--limit', type=int, default=5)
    categories = commands.add_parser('material-categories')
    categories.add_argument('kind', choices=['filter', 'sticker', 'text-template'])
    materials = commands.add_parser('list-materials')
    materials.add_argument('category_id', type=int)
    materials.add_argument('--limit', type=int, default=5)
    materials.add_argument('--offset', type=int, default=0)
    tts = commands.add_parser('synthesize')
    tts.add_argument('text')
    tts.add_argument('--output-root', default=str(PROJECT / 'output' / 'audio'))
    tts.add_argument('--voice', choices=VOICES, default='解说小帅')
    search = commands.add_parser('search-materials')
    search.add_argument('kind', choices=SEARCH_TYPES)
    search.add_argument('keyword')
    search.add_argument('--limit', type=int, default=5)
    search.add_argument('--offset', type=int, default=0)
    add = commands.add_parser('add-catalog-asset')
    add.add_argument('--source', required=True)
    add.add_argument('--output', required=True)
    add.add_argument('--kind', choices=KINDS, required=True)
    add.add_argument('--resource-id', required=True)
    add.add_argument('--resource-source', type=int, default=1)
    add.add_argument('--start-ms', type=int, default=0)
    add.add_argument('--duration-ms', type=int, default=2000)
    add.add_argument('--segment-id', default='')
    inspect = commands.add_parser('inspect')
    inspect.add_argument('draft')
    edit = commands.add_parser('make-portrait')
    edit.add_argument('--source', required=True)
    edit.add_argument('--output', required=True)
    edit.add_argument('--image')
    edit.add_argument('--ratio', choices=RATIOS, default='9:16')
    args = parser.parse_args()
    try:
        if args.command == 'doctor':
            result = doctor(args.install)
        elif args.command == 'host-status':
            result = host_status()
        elif args.command == 'voice-categories':
            result = voice_categories()
        elif args.command == 'edit-batch':
            path = Path(args.operations_file)
            if path.stat().st_size > 1024 * 1024:
                raise ValueError('Operations file exceeds 1 MB')
            result = edit_batch(args.source, args.output, json.loads(path.read_text(encoding='utf-8-sig')), args.ffprobe, args.install)
        elif args.command == 'timeline':
            result = timeline(args.source, args.offset, args.limit, args.install)
        elif args.command == 'replace-caption':
            result = replace_caption(args.source, args.output, args.segment_id, args.text, args.install)
        elif args.command == 'apply-cached-asset':
            result = apply_cached_asset(args.source, args.output, args.kind, args.asset_manifest,
                args.segment_id, args.start_ms, args.duration_ms, args.font_manifest,
                args.source_start_ms, args.ffprobe, args.install)
        elif args.command == 'extract-frame':
            result = extract_video_frame(args.media, args.output_root, args.timestamp_ms, args.width, args.height)
        elif args.command == 'audio-waveform':
            result = audio_waveform(args.media, args.start_ms, args.duration_ms, args.max_points)
        elif args.command == 'search-voices':
            result = search_voices(args.keyword, args.limit)
        elif args.command == 'material-categories':
            result = material_categories(args.kind)
        elif args.command == 'list-materials':
            result = list_materials(args.category_id, args.limit, args.offset)
        elif args.command == 'synthesize':
            result = synthesize(args.text, args.output_root, args.voice)
        elif args.command == 'search-materials':
            result = search_materials(args.kind, args.keyword, args.limit, args.offset)
        elif args.command == 'add-catalog-asset':
            result = add_catalog_asset(args.source, args.output, args.kind, args.resource_id,
                                       args.resource_source, args.start_ms, args.duration_ms, args.segment_id, args.install)
        elif args.command == 'inspect':
            result = inspect_draft(args.draft, args.install)
        else:
            result = make_portrait(args.source, args.output, args.image, args.ratio, args.install)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except Exception as error:
        print(json.dumps({'error':str(error), 'type':type(error).__name__}, ensure_ascii=False), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
