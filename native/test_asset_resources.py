import io
import tempfile
import unittest
import zipfile
from pathlib import Path


class AssetResourcesTest(unittest.TestCase):
    def test_sticker_uses_original_package_not_gif_preview_for_checksum(self):
        from asset_resources import _resource_url
        item = {'common_attr': {'effect_type': 2, 'download_info': {
            'url': 'https://example.invalid/preview.gif', 'format': 'gif'},
            'item_urls': ['https://example.invalid/package.zip']}}
        self.assertEqual(_resource_url(item), ('https://example.invalid/package.zip', True))

    def test_zip_cannot_write_outside_asset_directory(self):
        from asset_resources import unpack_asset
        for name in ('../escape.txt', '/escape.txt', 'C:/escape.txt', '..\\escape.txt'):
            archive = io.BytesIO()
            with zipfile.ZipFile(archive, 'w') as out:
                out.writestr(name, 'untrusted')
            with tempfile.TemporaryDirectory() as folder:
                with self.assertRaises(ValueError):
                    unpack_asset(archive.getvalue(), Path(folder) / 'asset')
                self.assertFalse(list(Path(folder).rglob('*')))

    def test_package_extraction_preserves_asset_files(self):
        from asset_resources import unpack_asset
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, 'w') as out:
            out.writestr('config.json', '{}')
            out.writestr('data/curve.bin', b'123')
        with tempfile.TemporaryDirectory() as folder:
            result = unpack_asset(archive.getvalue(), Path(folder) / 'asset')
            self.assertEqual(result['file_count'], 2)
            self.assertEqual((Path(folder) / 'asset/data/curve.bin').read_bytes(), b'123')


if __name__ == '__main__':
    unittest.main()
