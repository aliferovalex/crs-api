"""Bulk token scanning keeps escaped quotes, failures and source spans."""
import itertools
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src' / '\u0421\u0435\u0440\u0438\u0430\u043b\u0438\u0437\u0430\u0446\u0438\u044f'))
import native_metadata as s


def reference_string(text):
    pos = 1; chars = []
    while pos < len(text):
        char = text[pos]; pos += 1
        if char == '"':
            if pos < len(text) and text[pos] == '"':
                pos += 1; chars.append('"')
            else:
                return ''.join(chars), pos
        else:
            chars.append(char)
    raise ValueError('Unclosed quoted string')


class NativeParserTests(unittest.TestCase):
    def test_quote_scanner_matches_character_reference(self):
        for length in range(6):
            for tail in itertools.product('"a,}\n', repeat=length):
                text = '"' + ''.join(tail)
                parser = s.Parser(text)
                try:
                    value, end = reference_string(text)
                except ValueError:
                    with self.assertRaises(ValueError, msg=repr(text)):
                        parser.value()
                    self.assertEqual(parser.pos, len(text))
                else:
                    token = parser.value()
                    self.assertEqual((token.value, token.quoted, token.start, token.end, parser.pos),
                                     (value, True, 0, end, end), repr(text))

    def test_large_restriction_text_and_escaped_quotes(self):
        value = ('\u0442\u0435\u043a\u0441\u0442\n{column}, "quoted"\x00' * 40000)
        text = '{1,' + s.render(s.atom(value, True)) + ',0}'
        body = s.Parser(text).documents()[0]
        self.assertEqual(s.val(body[1]), value)
        self.assertEqual(text[body[1].start:body[1].end], s.render(body[1]))
        self.assertEqual(s.render(body), text)

    def test_offsets_of_nested_groups_and_whitespace_tokens(self):
        text = ' \n{ 1, {abc def , "a""b"}, 0 } '
        body = s.Parser(text).documents()[0]
        self.assertEqual((body.start, body.end), (2, len(text) - 1))
        self.assertEqual(s.val(body[1][0]), 'abc def')
        self.assertEqual(text[body[1][0].start:body[1][0].end], 'abc def ')
        self.assertEqual(text[body[1].start:body[1].end], '{abc def , "a""b"}')

    def test_invalid_unquoted_tokens_still_fail(self):
        for text in ('{1,abc{def}', '{1,abc"def}', '{1,,2}', 'abc,}'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                s.Parser(text).documents()


if __name__ == '__main__':
    unittest.main()
