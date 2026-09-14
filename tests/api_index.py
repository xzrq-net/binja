#!/usr/bin/env python3
"""Static declaration metadata, including unresolved enum expressions."""
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from binja.api import declarations


class IndexTests(unittest.TestCase):
    def test_properties_and_enum_members_without_importing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'binaryninja'
            root.mkdir()
            (root / 'example.py').write_text('''
raise RuntimeError("must not import")
class Function:
    @property
    def name(self) -> str:
        """Function name."""
    @name.setter
    def name(self, value): pass
    @property
    def hlil(self): pass
    def rename(self): pass
class SymbolType(enum.IntEnum):
    FunctionSymbol = 0
    Alias = 0
    Negative = -1
    Computed = enum.auto()
    _private = 7
''')
            records = {r['symbol'].split('example.')[-1]: r for r in declarations(root)}
            self.assertEqual(records['Function.name']['kind'], 'property')
            self.assertTrue(records['Function.name']['writable'])
            self.assertEqual(records['Function.name']['return_type'], 'str')
            self.assertFalse(records['Function.hlil']['writable'])
            self.assertNotIn('writable', records['Function.rename'])
            members = records['SymbolType']['members']
            self.assertEqual([m['name'] for m in members], ['FunctionSymbol', 'Alias', 'Negative', 'Computed'])
            self.assertEqual(members[2]['value'], -1)
            self.assertNotIn('value', members[3])
            self.assertEqual(members[3]['expression'], 'enum.auto()')


if __name__ == '__main__':
    unittest.main()
