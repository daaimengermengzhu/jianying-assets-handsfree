"""Verified local media extraction through the running Jianying host.

This previews an existing media file, never an unrendered draft timeline.
"""
import base64
import binascii
import math
from pathlib import Path
import struct
import uuid
import zlib

from host_bridge import HostBridge
from native import NativeError

VIDEO_EXTENSIONS = {'.mp4', '.mov', '.mkv', '.webm', '.avi', '.m4v'}
AUDIO_EXTENSIONS = VIDEO_EXTENSIONS | {'.mp3', '.wav', '.aac', '.m4a', '.flac', '.ogg'}


def _integer(value, name, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ValueError(f'{name} 必须为 {minimum}–{maximum} 的整数。')
    return value


def _media_path(value, extensions):
    if not isinstance(value, (str, Path)) or '://' in str(value) or str(value).startswith(('\\\\', '//')):
        raise ValueError('只能读取已有的本地媒体文件。')
    path = Path(value).resolve()
    if not path.is_file() or path.suffix.lower() not in extensions:
        raise ValueError('本地媒体文件不存在或扩展名不支持。')
    return path


def _decode_png(value, max_width, max_height):
    if not isinstance(value, str) or len(value) > 4 * 1024 * 1024:
        raise NativeError('剪映没有返回有效的图片数据。')
    if value.startswith('data:image/png;base64,'):
        value = value.removeprefix('data:image/png;base64,')
    try:
        raw = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error) as error:
        raise NativeError('剪映抽帧返回的不是 PNG 数据。') from error
    if not raw.startswith(b'\x89PNG\r\n\x1a\n'):
        raise NativeError('剪映抽帧缺少 PNG 文件头。')
    pos, width, height, saw_data, saw_end = 8, 0, 0, False, False
    while pos + 12 <= len(raw):
        length = struct.unpack('>I', raw[pos:pos + 4])[0]
        end = pos + length + 12
        if end > len(raw):
            raise NativeError('剪映抽帧 PNG 文件不完整。')
        kind, content = raw[pos + 4:pos + 8], raw[pos + 8:end - 4]
        if zlib.crc32(kind + content) != struct.unpack('>I', raw[end - 4:end])[0]:
            raise NativeError('剪映抽帧 PNG 校验失败。')
        if pos == 8:
            if kind != b'IHDR' or length != 13:
                raise NativeError('剪映抽帧 PNG 格式异常。')
            width, height = struct.unpack('>II', content[:8])
            if not 0 < width <= max_width or not 0 < height <= max_height:
                raise NativeError('剪映抽帧尺寸超出请求范围。')
        saw_data |= kind == b'IDAT' and length > 0
        pos = end
        if kind == b'IEND':
            saw_end = length == 0 and end == len(raw)
            break
    if not saw_data or not saw_end:
        raise NativeError('剪映抽帧 PNG 缺少完整图像数据。')
    return raw, width, height


def extract_video_frame(media_path, output_root, timestamp_ms=0, width=320, height=180):
    path = _media_path(media_path, VIDEO_EXTENSIONS)
    _integer(timestamp_ms, 'timestamp_ms', 0, 86_400_000)
    _integer(width, 'width', 1, 1280)
    _integer(height, 'height', 1, 1280)
    if width * height > 921_600:
        raise ValueError('单帧尺寸不能超过 921600 像素。')
    with HostBridge() as bridge:
        data = bridge._jsb('extractMediaFrames', {'path': str(path), 'width': width, 'height': height,
                                                'timestamps': [timestamp_ms]})
        frames = data.get('images')
        if not isinstance(frames, list) or len(frames) != 1 or not isinstance(frames[0], dict):
            raise NativeError('剪映没有返回单帧图片。')
        frame = frames[0]
        if frame.get('timestamp') != timestamp_ms:
            raise NativeError('剪映未确认请求的抽帧时间点。')
        raw, actual_width, actual_height = _decode_png(frame.get('url'), width, height)
    output_root = Path(output_root).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    target = output_root / ('frame-' + uuid.uuid4().hex + '.png')
    with target.open('xb') as stream:
        stream.write(raw)
    return {'output': str(target), 'source': str(path), 'timestamp_ms': timestamp_ms,
            'width': actual_width, 'height': actual_height, 'bytes': len(raw),
            'backend': 'Jianying host extractMediaFrames', 'timeline_rendered': False}


def audio_waveform(media_path, start_ms=0, duration_ms=5000, max_points=128):
    path = _media_path(media_path, AUDIO_EXTENSIONS)
    _integer(start_ms, 'start_ms', 0, 86_400_000)
    _integer(duration_ms, 'duration_ms', 1, 600_000)
    _integer(max_points, 'max_points', 16, 4096)
    with HostBridge() as bridge:
        data = bridge._jsb('getAudioWaveformData', {'path': str(path), 'start_ms': start_ms,
                                                   'duration_ms': duration_ms, 'max_points': max_points})
    values = data.get('values')
    if (data.get('fulfilled') is not True or data.get('partial') is not False
            or data.get('wave_data_enable') is not True or not isinstance(values, list)
            or not 0 < len(values) <= max_points or data.get('point_count') != len(values)
            or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0 for v in values)):
        raise NativeError('剪映未返回完整、有效的音频波形。')
    if (data.get('start_ms') != start_ms or isinstance(data.get('duration_ms'), bool)
            or not isinstance(data.get('duration_ms'), (int, float))
            or not 0 < data['duration_ms'] <= duration_ms):
        raise NativeError('剪映未确认请求的波形时间范围。')
    return {'source': str(path), 'start_ms': start_ms, 'duration_ms': data['duration_ms'],
            'point_count': len(values), 'values': values, 'backend': 'Jianying host getAudioWaveformData',
            'generation_triggered': False}
