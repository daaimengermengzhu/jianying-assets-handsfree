"""Host media boundaries: reject unsafe inputs and unusable native results."""
import base64
import struct
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest.mock import patch

import host_media
from native import NativeError


def png():
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 1, 1, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(b'\x00\xff\x00\x00')) + chunk(b'IEND', b''))


class HostMediaTest(unittest.TestCase):
    def test_invalid_input_never_reaches_host(self):
        with tempfile.TemporaryDirectory() as root, patch.object(host_media, 'HostBridge') as bridge:
            media = Path(root) / 'test.mp4'
            media.write_bytes(b'fixture')
            for params in [(-1, 320, 180), (True, 320, 180), (0, 0, 180), (0, 4096, 4096)]:
                with self.assertRaises(ValueError):
                    host_media.extract_video_frame(str(media), root, *params)
            for path in ['https://example.invalid/a.mp4', str(Path(root) / 'missing.mp4')]:
                with self.assertRaises(ValueError):
                    host_media.extract_video_frame(path, root)
            with self.assertRaises(ValueError):
                host_media.audio_waveform(str(media), 0, 0, 32)
            bridge.assert_not_called()

    def test_frame_rejects_remote_url_or_corrupt_png_without_output(self):
        with tempfile.TemporaryDirectory() as root, patch.object(host_media, 'HostBridge') as bridge:
            media = Path(root) / 'test.mp4'
            media.write_bytes(b'fixture')
            output = Path(root) / 'frames'
            raw = bytearray(png())
            raw[-1] ^= 1
            for value in ['https://example.invalid/PRIVATE', base64.b64encode(raw).decode()]:
                bridge.return_value.__enter__.return_value._jsb.return_value = {
                    'images': [{'timestamp': 0, 'url': value}]}
                with self.assertRaises(NativeError):
                    host_media.extract_video_frame(str(media), output)
                self.assertFalse(output.exists())

    def test_real_png_saved_uniquely_without_returning_base64(self):
        with tempfile.TemporaryDirectory() as root, patch.object(host_media, 'HostBridge') as bridge:
            media = Path(root) / 'test.mp4'
            media.write_bytes(b'fixture')
            bridge.return_value.__enter__.return_value._jsb.return_value = {
                'images': [{'timestamp': 1000, 'url': base64.b64encode(png()).decode()}]}
            first = host_media.extract_video_frame(str(media), Path(root) / 'frames', 1000)
            second = host_media.extract_video_frame(str(media), Path(root) / 'frames', 1000)
            self.assertNotEqual(first['output'], second['output'])
            self.assertEqual(Path(first['output']).read_bytes(), png())
            self.assertFalse(first['timeline_rendered'])
            self.assertNotIn('base64', str(first))

    def test_waveform_rejects_partial_or_nonfinite_data(self):
        with tempfile.TemporaryDirectory() as root, patch.object(host_media, 'HostBridge') as bridge:
            media = Path(root) / 'test.mp3'
            media.write_bytes(b'fixture')
            native = bridge.return_value.__enter__.return_value
            baseline = {'fulfilled': True, 'partial': False, 'wave_data_enable': True,
                        'point_count': 2, 'values': [0.1, 0.2], 'duration_ms': 1000, 'start_ms': 0}
            for changes in [{'partial': True}, {'values': [float('nan'), 0.2]}, {'point_count': 3}]:
                native._jsb.return_value = baseline | changes
                with self.assertRaises(NativeError):
                    host_media.audio_waveform(str(media), 0, 1000, 32)
            native._jsb.return_value = baseline | {'internal_token': 'PRIVATE'}
            result = host_media.audio_waveform(str(media), 0, 1000, 32)
            self.assertEqual(result['values'], [0.1, 0.2])
            self.assertNotIn('PRIVATE', str(result))


if __name__ == '__main__':
    unittest.main()
