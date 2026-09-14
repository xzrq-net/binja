#!/usr/bin/env python3
"""Protocol framing checks; no Binary Ninja installation needed."""
import json
from pathlib import Path
import socket
import sys
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from binja.common import CHUNK_BYTES, Error, receive, send


class FramingTests(unittest.TestCase):
    def pair(self):
        a, b = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        a.settimeout(2)
        b.settimeout(2)
        self.addCleanup(a.close)
        self.addCleanup(b.close)
        return a, b

    def test_multiple_messages_and_unicode(self):
        a, b = self.pair()
        values = [{"source": "print('λ')\n" * 40000}, {"done": True}]
        errors = []
        def write():
            try:
                for value in values:
                    send(a, value)
            except BaseException as exc:
                errors.append(exc)
        thread = threading.Thread(target=write)
        thread.start()
        for value in values:
            self.assertEqual(receive(b), value)
        thread.join()
        self.assertEqual(errors, [])

    def test_utf8_character_split_across_packets(self):
        a, b = self.pair()
        value = {"x": "a" * (CHUNK_BYTES - 7) + "λ" * 10}
        raw = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()
        a.send(b'\x01' + raw[:CHUNK_BYTES])
        a.send(b'\x01' + raw[CHUNK_BYTES:])
        a.send(b'\x00')
        self.assertEqual(receive(b), value)

    def test_invalid_packets(self):
        for packet in (b'\x02oops', b'\x01', b'\x00extra', b'\x01' + b'x' * (CHUNK_BYTES + 1)):
            with self.subTest(packet=packet[:10]):
                a, b = self.pair()
                a.send(packet)
                with self.assertRaises(Error):
                    receive(b)

    def test_disconnect_and_missing_terminator(self):
        a, b = self.pair()
        a.send(b'\x01{}')
        a.close()
        with self.assertRaisesRegex(Error, 'Incomplete'):
            receive(b)

    def test_bounds_and_json_object(self):
        a, b = self.pair()
        with self.assertRaisesRegex(Error, 'exceeds'):
            send(a, {'x': 'x' * 100}, limit=10)
        a.send(b'\x01' + b'x' * 11)
        with self.assertRaisesRegex(Error, 'exceeds'):
            receive(b, limit=10)
        a, b = self.pair()
        a.send(b'\x01[]')
        a.send(b'\x00')
        with self.assertRaisesRegex(Error, 'JSON object'):
            receive(b)


if __name__ == '__main__':
    unittest.main()
