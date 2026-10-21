import importlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class DraftAssetsTest(unittest.TestCase):
    def test_bad_asset_or_timing_does_not_reach_native_or_network(self):
        module = importlib.import_module('draft_assets')
        with tempfile.TemporaryDirectory() as folder, patch.object(module, 'NativeSession') as native, \
                patch.object(module, 'retrieve_asset') as fetch:
            for kwargs in ({'kind': 'sticker'}, {'duration_ms': 0}, {'start_ms': -1},
                           {'resource_id': '../x'}, {'duration_ms': True}):
                args = {'source': Path(folder) / 'source.json', 'output': Path(folder) / 'new',
                        'kind': 'effect', 'resource_id': '7399494783254760744', **kwargs}
                with self.assertRaises(ValueError):
                    module.add_catalog_asset(**args)
            native.assert_not_called()
            fetch.assert_not_called()


if __name__ == '__main__':
    unittest.main()
