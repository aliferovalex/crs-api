"""Keep the architecture map current and low-level readers independent."""
import importlib.util
import json
import os
import re
import sys
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('module_map_builder', ROOT / 'tools' / 'build_module_map.py')
mapping = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mapping)


class ModuleMapTests(unittest.TestCase):
    def test_documented_transformations_execute_with_current_converters(self):
        examples = mapping.transformation_examples().split('### 5.', 1)[0]
        blocks = re.findall(r'```python\n(.*?)\n```', examples, re.S)
        self.assertEqual(len(blocks), 4)
        scope = {'__name__': 'module_map_examples'}
        previous_directory = Path.cwd()
        previous_path = list(sys.path)
        try:
            os.chdir(ROOT)
            for index, code in enumerate(blocks, 1):
                with self.subTest(example=index):
                    exec(compile(code, 'module-map-example-' + str(index), 'exec'), scope)
        finally:
            os.chdir(previous_directory)
            sys.path[:] = previous_path

    def test_generated_map_matches_current_sources(self):
        current = mapping.extract()
        saved = json.loads((ROOT / 'docs' / 'module-map.json').read_text(encoding='utf-8'))
        self.assertEqual(saved, current)
        self.assertEqual((ROOT / 'docs' / 'module-map.md').read_text(encoding='utf-8'),
                         mapping.markdown(current))

    def test_readers_do_not_import_packet_builders_or_xml_converters(self):
        dependencies = mapping.extract()['imports']
        for name, allowed in [('native_metadata', {'python:v8unpack_backend'}),
                              ('metadata_context', {'python:native_metadata'}),
                              ('xml_namespaces', set())]:
            actual = {edge['callee'] for edge in dependencies if edge['caller'] == 'python:' + name}
            self.assertLessEqual(actual, allowed)
        forbidden = {'python:object_creation_serializer', 'python:configuration_serializer',
                     'python:packet_builder'}
        for name in ['configuration_xml', 'metadata_common_xml', 'inline_attribute_xml', 'metadata_object_xml']:
            actual = {edge['callee'] for edge in dependencies if edge['caller'] == 'python:' + name}
            self.assertFalse(actual & forbidden, (name, actual & forbidden))

    def test_onescript_to_python_bridge_is_included(self):
        edges = mapping.extract()['calls']
        targets = {edge['callee'] for edge in edges
                   if edge['caller'] == 'onescript:СериализаторОбъектаХранилища'
                   and 'JSON CLI' in edge['functions']}
        self.assertTrue({'python:configuration_serializer', 'python:object_creation_serializer',
                         'python:configuration_commit'}.issubset(targets))
        self.assertNotIn('python:native_metadata', targets)


if __name__ == '__main__':
    unittest.main()
