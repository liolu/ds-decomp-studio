import struct
import sys
import unittest
from pathlib import Path

from ndspy import _common

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rom_build import secure_area_crc_fix, title_fix, unused_areas_fix


class SecureAreaChecksumTests(unittest.TestCase):
    def setUp(self):
        self.original = bytearray(0x8000)
        self.original[0x0c:0x10] = b"AL7E"
        struct.pack_into("<I", self.original, 0x20, 0x4000)
        self.original[0x4000:] = bytes(range(256)) * 64
        struct.pack_into("<H", self.original, 0x6c, 0x1234)
        self.header_crc(self.original)
        self.rebuilt = bytearray(self.original)
        struct.pack_into("<H", self.rebuilt, 0x6c, 0)
        self.header_crc(self.rebuilt)

    @staticmethod
    def header_crc(image):
        struct.pack_into("<H", image, 0x15e, _common.crc16(image[:0x15e]))

    def test_unchanged_secure_area_preserves_only_missing_metadata(self):
        self.assertTrue(secure_area_crc_fix(bytes(self.original), self.rebuilt))
        self.assertEqual(self.rebuilt, self.original)

    def test_changed_secure_area_is_never_repaired(self):
        self.rebuilt[0x4567] ^= 1
        before = bytes(self.rebuilt)
        self.assertFalse(secure_area_crc_fix(bytes(self.original), self.rebuilt))
        self.assertEqual(self.rebuilt, before)

    def test_existing_nonzero_checksum_is_not_overwritten(self):
        struct.pack_into("<H", self.rebuilt, 0x6c, 0x5678)
        self.header_crc(self.rebuilt)
        before = bytes(self.rebuilt)
        self.assertFalse(secure_area_crc_fix(bytes(self.original), self.rebuilt))
        self.assertEqual(self.rebuilt, before)

    def test_other_header_changes_remain_visible(self):
        self.rebuilt[0] = ord("L")
        self.assertTrue(secure_area_crc_fix(bytes(self.original), self.rebuilt))
        self.assertEqual(self.rebuilt[0], ord("L"))
        self.assertNotEqual(self.rebuilt, self.original)
        self.assertEqual(struct.unpack_from("<H", self.rebuilt, 0x15e)[0],
                         _common.crc16(self.rebuilt[:0x15e]))

    def test_different_game_or_arm9_location_is_not_repaired(self):
        for offset, value in [(0x0c, b"TEST"), (0x20, struct.pack("<I", 0x8000))]:
            with self.subTest(offset=offset):
                rebuilt = bytearray(self.rebuilt)
                rebuilt[offset:offset + len(value)] = value
                before = bytes(rebuilt)
                self.assertFalse(secure_area_crc_fix(bytes(self.original), rebuilt))
                self.assertEqual(rebuilt, before)

    def test_truncated_input_is_not_repaired(self):
        before = bytes(self.rebuilt)
        self.assertFalse(secure_area_crc_fix(bytes(self.original[:0x4000]), self.rebuilt))
        self.assertEqual(self.rebuilt, before)


if __name__ == "__main__":
    unittest.main()


class TitleAndUnusedAreaTests(unittest.TestCase):
    """title_fix and unused_areas_fix on a small NTR image: header, ARM9, ARM7, FNT, FAT with two files."""

    def setUp(self):
        r = bytearray(b"\xff" * 0x10000)
        r[:0x4000] = bytes(0x4000)
        r[0:12] = b"PVZ        \0"
        r[0x0c:0x10] = b"BWBP"
        struct.pack_into("<IIII", r, 0x20, 0x4000, 0x02000000, 0x02000000, 0x1000)  # ARM9
        struct.pack_into("<IIII", r, 0x30, 0x5200, 0x02380000, 0x02380000, 0x800)   # ARM7
        struct.pack_into("<II", r, 0x40, 0x6000, 0x10)                               # FNT
        struct.pack_into("<II", r, 0x48, 0x6200, 0x10)                               # FAT: 2 files
        struct.pack_into("<IIII", r, 0x6200, 0x7000, 0x7100, 0x7200, 0x7300)
        for start, size in [(0x4000, 0x1000), (0x5200, 0x800), (0x6000, 0x10), (0x7000, 0x100), (0x7200, 0x100)]:
            r[start:start + size] = bytes((start + i) & 0xff for i in range(size))
        struct.pack_into("<IIII", r, 0x6200, 0x7000, 0x7100, 0x7200, 0x7300)
        r[0x5000:0x5200] = bytes(0x200)          # the original pads with zeros here
        r[0x8000:] = bytes(range(256)) * 0x80    # mastering leftovers at the end
        struct.pack_into("<H", r, 0x15e, _common.crc16(r[:0x15e]))
        self.original = bytes(r)
        self.rebuilt = bytearray(r)
        self.rebuilt[0:12] = b"PVZ" + bytes(9)
        self.rebuilt[0x5000:0x5200] = b"\xff" * 0x200
        self.rebuilt[0x8000:] = b"\xff" * 0x8000
        struct.pack_into("<H", self.rebuilt, 0x15e, _common.crc16(self.rebuilt[:0x15e]))

    def test_title_padded_with_spaces_comes_back(self):
        self.assertTrue(title_fix(self.original, self.rebuilt))
        self.assertEqual(self.rebuilt[:0x160], self.original[:0x160])

    def test_other_title_is_kept(self):
        self.rebuilt[0:12] = b"ABC" + bytes(9)
        self.assertFalse(title_fix(self.original, self.rebuilt))
        self.assertEqual(self.rebuilt[0:3], b"ABC")

    def test_gaps_and_end_come_back_but_not_structures(self):
        self.rebuilt[0x4010] ^= 1   # ARM9
        self.rebuilt[0x7050] ^= 1   # a file
        # (gaps taken back, their whole size): the gap after the ARM7 and the end of the ROM
        self.assertEqual(unused_areas_fix(self.original, self.rebuilt), (2, 0x200 + 0x10000 - 0x7300))
        self.assertEqual(self.rebuilt[0x5000:0x5200], self.original[0x5000:0x5200])
        self.assertEqual(self.rebuilt[0x8000:], self.original[0x8000:])
        self.assertNotEqual(self.rebuilt[0x4010], self.original[0x4010])
        self.assertNotEqual(self.rebuilt[0x7050], self.original[0x7050])

    def test_other_layout_is_left_alone(self):
        struct.pack_into("<I", self.rebuilt, 0x6204, 0x7104)  # a file of another size
        before = bytes(self.rebuilt)
        self.assertEqual(unused_areas_fix(self.original, self.rebuilt), (0, 0))
        self.assertEqual(self.rebuilt, before)
