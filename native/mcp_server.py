"""Local stdio MCP endpoint. No listener, account cookies, or arbitrary native-call tool."""
import os
import shutil
from pathlib import Path
from typing import Any
from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from native import DEFAULT_INSTALL, PROJECT, NativeError
from workflow import doctor, inspect_draft, make_portrait
from host_bridge import host_status, voice_categories, search_voices
from client_services import material_categories, list_materials, search_materials
from tts import synthesize
from draft_assets import add_catalog_asset
from host_media import extract_video_frame, audio_waveform
from model_edits import replace_caption, apply_cached_asset
from batch_edits import edit_batch, timeline

server = MCPServer('Jianying Native')
INSTALL = Path(os.environ.get('JY_INSTALL_DIR', str(DEFAULT_INSTALL)))
OUTPUT_ROOT = Path(os.environ.get('JY_OUTPUT_ROOT', str(PROJECT / 'output'))).resolve()
FFPROBE = Path(os.environ.get('JY_FFPROBE') or shutil.which('ffprobe') or 'ffprobe.exe')


def new_output_folder(output_name):
    if not output_name or output_name in ('.', '..') or any(c in output_name for c in '/\\:<>"|?*'):
        raise ToolError('output_name must be one local folder name')
    target = (OUTPUT_ROOT / output_name).resolve()
    if target.parent != OUTPUT_ROOT:
        raise ToolError('Output escapes the configured root')
    return target


@server.tool(structured_output=True, annotations=ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=False))
def jianying_replace_caption(source_draft: str, output_name: str, segment_id: str, text: str) -> dict[str, Any]:
    """Re-edit a saved encrypted draft into a NEW output. Replace one uniform-style caption, preserving audio and other tracks. Supports 1–200 characters including emoji; no implicit narration regeneration. Does not edit an open GUI project, register it in the GUI, or export MP4."""
    return checked_call(replace_caption, source_draft, new_output_folder(output_name), segment_id, text, INSTALL)


@server.tool(structured_output=True, annotations=ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=False))
def jianying_apply_cached_asset(source_draft: str, output_name: str, kind: str, asset_manifest: str,
                                segment_id: str = '', start_ms: int = 0, duration_ms: int = 2000,
                                font_manifest: str = '', source_start_ms: int = 0) -> dict[str, Any]:
    """Apply an already legitimately downloaded official resource to a NEW encrypted draft, without UI or network. kind: sticker, subtitle-template, stock-video. asset_manifest is retrieve_asset's local verification.json. Subtitle template requires a text segment_id and the matching downloaded font_manifest. Stock video appends at the exact draft end; source_start_ms selects trim. Only selected fragments are merged; unrelated native data is preserved. Verifies binding and encrypted readback, not visual appearance; no live-GUI mutation or export."""
    return checked_call(apply_cached_asset, source_draft, new_output_folder(output_name), kind, asset_manifest,
                        segment_id, start_ms, duration_ms, font_manifest, source_start_ms, FFPROBE, INSTALL)


def checked_call(operation, *args):
    try:
        return operation(*args)
    except (OSError, ValueError, NativeError) as error:
        raise ToolError(str(error)) from error


@server.tool(structured_output=True, annotations=ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=False))
def jianying_edit_batch(source_draft: str, output_name: str, operations: list[dict[str, Any]]) -> dict[str, Any]:
    """Apply 1–100 offline actions in order to one NEW encrypted draft. Actions: replace-caption(segment_id,text); apply-cached-asset(kind,asset_manifest, optional segment_id,start_ms,duration_ms,font_manifest,source_start_ms); transform(segment_id, optional scale,x,y,rotation); volume(segment_id,volume 0–2). Use timeline for existing segment IDs. scale is uniform 0.01–10; positions use native normalized coordinates -2–2. Asset kinds: sticker, subtitle-template, stock-video. One private worker pair, dependency preflight, full encrypted readback, atomic publication; failure leaves no final draft. No downloads, voice regeneration, GUI, registration or export. Preview/export belong to the user."""
    return checked_call(edit_batch, source_draft, new_output_folder(output_name), operations, FFPROBE, INSTALL)


@server.tool(structured_output=True, annotations=ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False))
def jianying_timeline(source_draft: str, offset: int = 0, limit: int = 30) -> dict[str, Any]:
    """Read saved encrypted timeline into compact paged segments: IDs, text preview, timing, transforms and volume. Also checks reachable materials' recognized local paths (including fonts), not visual render or package contents. No GUI or changes; limit 1–100."""
    return checked_call(timeline, source_draft, offset, limit, INSTALL)


@server.tool(structured_output=True, annotations=ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False))
def jianying_native_status() -> dict[str, Any]:
    """Initialize the installed Jianying native engine and report tested capability limits."""
    return checked_call(doctor, INSTALL)


@server.tool(structured_output=True, annotations=ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=True))
def jianying_host_status() -> dict[str, Any]:
    """Query the running Jianying client's bridge health, membership and credits. No UI control or generation. Balance does not establish per-use cost."""
    return checked_call(host_status)


@server.tool(structured_output=True, annotations=ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=False))
def jianying_extract_video_frame(media_path: str, timestamp_ms: int = 0, width: int = 320, height: int = 180) -> dict[str, Any]:
    """Extract one PNG from an existing local video using running Jianying, without UI control. Saves a unique file under output/frames. Max 921600 pixels, dimensions 1–1280, timestamp in milliseconds. Source media preview only: does not render a draft timeline."""
    return checked_call(extract_video_frame, media_path, OUTPUT_ROOT / 'frames', timestamp_ms, width, height)


@server.tool(structured_output=True, annotations=ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False))
def jianying_audio_waveform(media_path: str, start_ms: int = 0, duration_ms: int = 5000, max_points: int = 128) -> dict[str, Any]:
    """Read an existing local audio/video file's waveform via running Jianying without UI control or generation. Returns 16–4096 requested points over at most 600000 ms; rejects partial or invalid responses."""
    return checked_call(audio_waveform, media_path, start_ms, duration_ms, max_points)


@server.tool(structured_output=True, annotations=ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=True))
def jianying_voice_categories() -> dict[str, Any]:
    """Read voice category names from the running Jianying client; no narration generated."""
    return checked_call(voice_categories)


@server.tool(structured_output=True, annotations=ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=True))
def jianying_search_voices(keyword: str, limit: int = 5) -> dict[str, Any]:
    """Search public voices via Jianying's native host; return at most 20. Omits private clones and media URLs. Does not synthesize speech or establish generation entitlement."""
    return checked_call(search_voices, keyword, limit)


@server.tool(structured_output=True, annotations=ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=True))
def jianying_material_categories(kind: str) -> dict[str, Any]:
    """Read official material categories. Verified kinds: filter, sticker, text-template. Requires running logged-in Jianying; no UI or downloads."""
    return checked_call(material_categories, kind)


@server.tool(structured_output=True, annotations=ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=True))
def jianying_list_materials(category_id: int, limit: int = 5, offset: int = 0) -> dict[str, Any]:
    """List official material IDs, titles and membership labels from a returned category ID. Collection entries are bundles, not individual effects. No download or timeline mutation."""
    return checked_call(list_materials, category_id, limit, offset)


@server.tool(structured_output=True, annotations=ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False))
def jianying_inspect_draft(draft_path: str) -> dict[str, Any]:
    """Read a local encrypted draft; report canvas, segment counts and missing primary media."""
    return checked_call(inspect_draft, draft_path, INSTALL)


@server.tool(structured_output=True, annotations=ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=True))
def jianying_synthesize(text: str, voice_name: str = '解说小帅') -> dict[str, Any]:
    """Generate one 1–120 character narration using 解说小帅 or VIP 真人播客男 and save MP3 under output/audio. Requires logged-in Jianying and membership for VIP voices. Creates a remote task; no automatic create retries. Balance observations are not an unlimited-use guarantee. Allow up to 120 seconds."""
    return checked_call(synthesize, text, OUTPUT_ROOT / 'audio', voice_name)


@server.tool(structured_output=True, annotations=ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=True))
def jianying_search_materials(kind: str, keyword: str, limit: int = 5, offset: int = 0) -> dict[str, Any]:
    """Search official materials and membership labels: effect, transition, subtitle-template, material (stock video/images), sound, music, sticker, text-template, recipe (material combinations). Uses running client's normal signed service. Does not download or apply assets."""
    return checked_call(search_materials, kind, keyword, limit, offset)


@server.tool(structured_output=True, annotations=ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=True))
def jianying_add_catalog_asset(source_draft: str, output_name: str, kind: str, resource_id: str,
                               resource_source: int = 1, start_ms: int = 0, duration_ms: int = 2000,
                               segment_id: str = '') -> dict[str, Any]:
    """Fetch one official effect, sound, music or transition through the logged-in client and natively insert it into a NEW encrypted draft. Requires current membership for VIP assets; pass resource_source from search results (music often uses 3). Transition requires a non-last adjacent video segment_id; duration in ms. Verifies IDs, paths, ranges and encrypted readback, not visual rendering or export. Original draft preserved; unique output_name required. Allow 120 seconds."""
    if not output_name or output_name in ('.', '..') or any(c in output_name for c in '/\\:<>"|?*'):
        raise ToolError('output_name must be one local folder name')
    target = (OUTPUT_ROOT / output_name).resolve()
    if target.parent != OUTPUT_ROOT:
        raise ToolError('Output escapes the configured root')
    return checked_call(add_catalog_asset, source_draft, target, kind, resource_id,
                        resource_source, start_ms, duration_ms, segment_id, INSTALL)


@server.tool(structured_output=True, annotations=ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=False))
def jianying_make_portrait(source_draft: str, output_name: str, image_path: str = '', ratio: str = '9:16') -> dict[str, Any]:
    """Create and verify a NEW encrypted draft under the configured output root. Preserve source audio/captions, change canvas, optionally add a local image. Does not export MP4 or edit the live GUI."""
    # One folder name, no traversal or arbitrary destinations exposed through MCP.
    if not output_name or output_name in ('.', '..') or any(c in output_name for c in '/\\:<>"|?*'):
        raise ToolError('output_name must be one local folder name')
    target = (OUTPUT_ROOT / output_name).resolve()
    if target.parent != OUTPUT_ROOT:
        raise ToolError('Output escapes the configured root')
    return checked_call(make_portrait, source_draft, target, image_path or None, ratio, INSTALL)


if __name__ == '__main__':
    server.run(transport='stdio')
