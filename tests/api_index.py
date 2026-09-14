#!/usr/bin/env python3
"""Static declaration metadata and inheritance, without importing vendor code."""
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from binja.api import declarations


class IndexTests(unittest.TestCase):
    def index(self, sources):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name) / 'binaryninja'
        for filename, source in sources.items():
            path = root / filename
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('raise RuntimeError("must not import")\n' + source)
        return {r['symbol']: r for r in declarations(root)}

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

    def test_diamond_imports_and_nested_classes(self):
        records = self.index({
            'base.py': '''
class Root:
    @property
    def name(self) -> str: pass
    @name.setter
    def name(self, value): pass
class Left(Root): pass
class Right(Root):
    @property
    def name(self) -> int: pass
''',
            'exports/__init__.py': 'from ..base import Right as Renamed\n',
            'child.py': '''
from . import base as source
from .exports import Renamed
class Diamond(source.Left, Renamed):
    class Nested(source.Root):
        def nested_only(self): pass
''',
        })
        child = records['binaryninja.child.Diamond']
        self.assertEqual(child['bases'], ['binaryninja.base.Left', 'binaryninja.base.Right'])
        self.assertEqual(child['mro'], ['binaryninja.child.Diamond', 'binaryninja.base.Left',
            'binaryninja.base.Right', 'binaryninja.base.Root', 'builtins.object'])
        self.assertEqual(child['unresolved_bases'], [])
        nested = records['binaryninja.child.Diamond.Nested']
        self.assertEqual(nested['bases'], ['binaryninja.base.Root'])
        self.assertTrue(records['binaryninja.base.Root.name']['writable'])
        self.assertFalse(records['binaryninja.base.Right.name']['writable'])
        self.assertIn('binaryninja.child.Diamond.Nested.nested_only', records)

    def test_annotated_class_fields_preserve_source_without_execution(self):
        records = self.index({'example.py': '''
from dataclasses import dataclass, field
from typing import ClassVar
module_value: int = must_not_run()
@dataclass(frozen=True)
class RegisterValue:
    value: int
    offset: int
    type: RegisterValueType = RegisterValueType.UndeterminedValue
    confidence: int = core.max_confidence
    size: int = 0
    optional: 'RegisterValue | None' = None
    items: list[int] = field(default_factory=must_not_run)
    registry: ClassVar[dict[str, int]] = must_not_run()
    _private: int = 1
    unannotated = 2
    def method(self):
        local: int = 3
        self.instance: int = 4
@dataclass
class ConstantPointerRegisterValue(RegisterValue):
    """A constant pointer."""
    offset: int = 0
    type: RegisterValueType = RegisterValueType.ConstantPointerValue
class Plain:
    name: str
    class Nested:
        value: int = 7
class Choice(enum.IntEnum):
    First: int = 1
'''})
        prefix = 'binaryninja.example.'
        fields = {symbol.removeprefix(prefix): record for symbol, record in records.items()
            if record['kind'] == 'field'}
        self.assertEqual(set(fields), {
            'RegisterValue.value', 'RegisterValue.offset', 'RegisterValue.type',
            'RegisterValue.confidence', 'RegisterValue.size', 'RegisterValue.optional',
            'RegisterValue.items', 'RegisterValue.registry',
            'ConstantPointerRegisterValue.offset', 'ConstantPointerRegisterValue.type',
            'Plain.name', 'Plain.Nested.value',
        })
        value = fields['RegisterValue.value']
        self.assertEqual(value['alias'], 'binaryninja.RegisterValue.value')
        self.assertEqual(value['signature'], 'value: int')
        self.assertEqual(value['annotation'], 'int')
        self.assertNotIn('default', value)
        self.assertNotIn('writable', value)
        source_line = Path(value['source']).read_text().splitlines()[value['line'] - 1]
        self.assertEqual(source_line.strip(), 'value: int')
        self.assertEqual(fields['RegisterValue.type']['default'], 'RegisterValueType.UndeterminedValue')
        self.assertEqual(fields['RegisterValue.confidence']['default'], 'core.max_confidence')
        self.assertEqual(fields['RegisterValue.size']['default'], '0')
        self.assertEqual(fields['RegisterValue.optional']['annotation'], "'RegisterValue | None'")
        self.assertEqual(fields['RegisterValue.optional']['default'], 'None')
        self.assertEqual(fields['RegisterValue.items']['default'], 'field(default_factory=must_not_run)')
        self.assertEqual(fields['RegisterValue.registry']['annotation'], 'ClassVar[dict[str, int]]')
        self.assertEqual(fields['RegisterValue.registry']['default'], 'must_not_run()')
        self.assertEqual(fields['ConstantPointerRegisterValue.offset']['default'], '0')
        self.assertEqual(records[prefix + 'RegisterValue']['doc'], '')
        child = records[prefix + 'ConstantPointerRegisterValue']
        self.assertEqual(child['doc'], 'A constant pointer.')
        self.assertEqual(child['mro'], [prefix + 'ConstantPointerRegisterValue', prefix + 'RegisterValue', 'builtins.object'])
        self.assertEqual(records[prefix + 'Choice']['members'], [{'name': 'First', 'expression': '1', 'value': 1}])
        self.assertNotIn(prefix + 'Choice.First', records)

    def test_unindexed_bases_are_explicit_and_transitive(self):
        records = self.index({'example.py': '''
from native import Extension as Native
from typing import Generic
class _Private: pass
class Partial(Native, Generic[T], _Private):
    def known(self): pass
class Child(Partial): pass
class Empty(object): pass
'''})
        child = records['binaryninja.example.Child']
        self.assertEqual(child['unresolved_bases'], ['native.Extension', 'typing.Generic', '_Private'])
        self.assertEqual(records['binaryninja.example.Empty']['unresolved_bases'], [])
        self.assertIn('binaryninja.example.Partial.known', records)
        self.assertNotIn('binaryninja.example._Private', records)

    def test_invalid_inheritance_fails_without_recursing_forever(self):
        for source, error in [
            ('class A(B): pass\nclass B(A): pass\n', 'Cyclic'),
            ('class A: pass\nclass B(A): pass\nclass C(A, B): pass\n', 'Inconsistent'),
        ]:
            with self.subTest(error=error), self.assertRaisesRegex(ValueError, error):
                self.index({'example.py': source})


if __name__ == '__main__':
    unittest.main()
