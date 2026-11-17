"""exefs_mods.py: IPS / IPS32 patches by build ID, a record in a segment's page padding, modules a mod adds (from a folder or a .zip), and the refusals"""
import struct, sys, tempfile, unittest, zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import exefs_mods, nso   # noqa: E402

BID = bytes.fromhex('e0f3ccfaf50065ae4ea01eb5aeb13b1a') + bytes(16)


def make_nso(text=b'\x1f\x20\x03\xd5' * 0x200, ro=b'RO' * 0x100, data=b'DA' * 0x80, bid=BID, bss=0x40):
    """An uncompressed NSO: text at 0 (0x800 bytes, so its page has 0x800 of padding), ro at 0x1000, data at 0x2000"""
    h = bytearray(0x100); h[:4] = b'NSO0'
    segs = [(0, text), (0x1000, ro), (0x2000, data)]; fo = 0x100; body = b''
    for i, (mo, b) in enumerate(segs):
        struct.pack_into('<III', h, 0x10 + 0x10 * i, fo, mo, len(b)); struct.pack_into('<I', h, 0x60 + 4 * i, len(b)); fo += len(b); body += b
    struct.pack_into('<I', h, 0x3c, bss); h[0x40:0x60] = bid
    return bytes(h) + body


def ips(records, wide=False):
    w = 4 if wide else 3
    out = b'IPS32' if wide else b'PATCH'
    for off, b in records: out += (off + 0x100).to_bytes(w, 'big') + len(b).to_bytes(2, 'big') + b
    return out + (b'EEOF' if wide else b'EOF')


class ExefsMods(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.exefs = self.tmp / 'ExeFS'; self.exefs.mkdir()
        (self.exefs / 'main').write_bytes(make_nso()); (self.exefs / 'sdk').write_bytes(make_nso(bid=b'\x11' * 32)); (self.exefs / 'main.npdm').write_bytes(b'META')
        self.mods = self.tmp / 'mods'; self.mods.mkdir()

    def run_mods(self):
        return exefs_mods.apply(self.exefs, self.mods, self.tmp / 'out')

    def test_ips_by_build_id_and_padding(self):
        d = self.mods / 'Cheat' / 'exefs'; d.mkdir(parents=True)
        (d / (BID[:20].hex().upper() + '.ips')).write_bytes(ips([(0x10, b'\xaa\xbb\xcc\xdd'), (0xc00, b'\x01\x02\x03\x04')], wide=True))   # 0xc00: past text's 0x800, in its page
        rows, added = self.run_mods()
        m = nso.read(self.tmp / 'out' / 'main')
        self.assertEqual(m.image[0x10:0x14], b'\xaa\xbb\xcc\xdd')
        self.assertEqual(m.image[0xc00:0xc04], b'\x01\x02\x03\x04')
        self.assertEqual(m.segments[0], (0, 0x1000))   # text grew to its page end
        self.assertEqual(m.image[0x1000:0x1004], b'RORO')   # ro where it was
        self.assertEqual(m.build_id, BID)
        self.assertEqual((self.tmp / 'out' / 'sdk').read_bytes(), (self.exefs / 'sdk').read_bytes())   # untouched modules are copied as they are
        self.assertTrue((self.tmp / 'out' / 'main.npdm').is_file())
        self.assertEqual(added, [])
        self.assertIn('2 patch records', rows[0][2])

    def test_zip_adds_a_module_and_skips_other_files(self):
        with zipfile.ZipFile(self.mods / 'Wayfarer-v1.zip', 'w') as z:
            z.writestr('Wayfarer/exefs/subsdk8', make_nso(bid=b'\x22' * 32))
            z.writestr('Wayfarer/exefs/' + BID[:20].hex().upper() + '.ips', ips([(0x20, b'\x00\x00\x00\x14')]))
            z.writestr('Wayfarer/exefs/readme.txt', 'hi')
            z.writestr('Wayfarer/README.md', 'hi')
        rows, added = self.run_mods()
        self.assertEqual(added, ['subsdk8'])
        self.assertEqual(nso.read(self.tmp / 'out' / 'subsdk8').build_id, b'\x22' * 32)
        self.assertEqual(nso.read(self.tmp / 'out' / 'main').image[0x20:0x24], b'\x00\x00\x00\x14')
        what = {r[1]: r[2] for r in rows}
        self.assertEqual(what['subsdk8'], 'added'); self.assertTrue(what['readme.txt'].startswith('left out'))
        self.assertIn('subsdk8\tadded', (self.tmp / 'out' / 'mods.tsv').read_text())

    def test_patch_for_another_build_is_left_out(self):
        d = self.mods / 'Old' / 'exefs'; d.mkdir(parents=True)
        (d / ('ab' * 16 + '.ips')).write_bytes(ips([(0x10, b'\x00')]))
        rows, _ = self.run_mods()
        self.assertIn('another update', rows[0][2])
        self.assertEqual((self.tmp / 'out' / 'main').read_bytes(), (self.exefs / 'main').read_bytes())

    def test_refusals(self):
        d = self.mods / 'Bad' / 'exefs'; d.mkdir(parents=True)
        (d / (BID[:16].hex() + '.ips')).write_bytes(ips([(0x3000, b'\x00' * 8)], wide=True))   # past data's page: bss
        with self.assertRaises(exefs_mods.ModError): self.run_mods()
        (d / (BID[:16].hex() + '.ips')).write_bytes(b'PATCH' + b'\x00\x01')   # cut short
        with self.assertRaises(exefs_mods.ModError): self.run_mods()
        (d / (BID[:16].hex() + '.ips')).unlink()
        for name in ('A', 'B'):
            e = self.mods / name / 'exefs'; e.mkdir(parents=True); (e / 'subsdk8').write_bytes(make_nso(bid=b'\x33' * 32))
        with self.assertRaises(exefs_mods.ModError): self.run_mods()   # two mods in one slot

    def test_rle_record(self):
        recs = exefs_mods.ips_records(b'PATCH' + (0x110).to_bytes(3, 'big') + b'\x00\x00' + b'\x00\x04' + b'\x90' + b'EOF', 'rle')
        self.assertEqual(recs, [(0x10, b'\x90' * 4)])


if __name__ == '__main__':
    unittest.main()
