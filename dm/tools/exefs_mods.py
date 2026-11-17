#!/usr/bin/env python3
"""ExeFS mods applied before the rewrite: the build's own copy of a version's ExeFS with each mod's code patches (IPS) applied and its code modules added, for
patch_nso.py to rewrite like the game's own (the NSP script's mods step, --mods / MODS). The rewrite works on the code offline, so a code mod cannot be dropped into a folder
at run time: it is built into the app.

A mod is a folder or a .zip of one in the mods folder, in the layout the Switch's mod loaders read (Atmosphère's contents/<title ID>/exefs/, a Ryujinx or yuzu-family mod folder):
any folder named exefs inside it holds
  · <build ID>.ips: an IPS ("PATCH" … "EOF", 24-bit offsets) or IPS32 ("IPS32" … "EEOF", 32-bit offsets) patch of the module of that build ID (the name is the build ID's hex,
    16 to 32 bytes; it is matched by prefix, as Atmosphère does). Offsets count from the NSO header, so a record at 0x100 + o writes the module's memory image at o. A record
    may write the padding after a segment (a mod's trampolines at the end of main's text page, Wayfarer): that segment then grows to its page end, as Horizon maps it.
  · subsdk<N> (or another module name): a code module the mod adds, loaded in Horizon's order (main, the subsdks by number, sdk); one the game has already is replaced.
Other files (main.npdm, a romfs folder, text files) are left out and listed.

Usage: exefs_mods.py <ExeFS folder> <mods folder> <out folder>. Writes <out>/ with every module of the ExeFS (patched ones as uncompressed NSOs with the flags cleared, which
Horizon and nso.py load without the hash check) and <out>/mods.tsv: mod, module, what was done. Exit 1 when a mod cannot be applied (a patch past its module's image, two mods
adding the same module, a damaged file), naming it, so a build never runs a half-applied mod."""
import io, re, shutil, struct, sys, zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import nso   # noqa: E402

PAGE = 0x1000
NSO_HEADER = 0x100
SKIP = {'main.npdm', 'rtld'}   # the process's metadata and Horizon's loader module: never a mod's to change here


class ModError(Exception):
    pass


def ips_records(data, what):
    """(memory offset, bytes) of an IPS or IPS32 patch; offsets made relative to the module's image (minus the NSO header)"""
    if data[:5] == b'PATCH': wide, at, end = False, 5, b'EOF'
    elif data[:5] == b'IPS32': wide, at, end = True, 5, b'EEOF'
    else: raise ModError(f'{what}: not an IPS patch (starts {bytes(data[:5])!r})')
    out, w = [], 4 if wide else 3
    while True:
        if data[at:at + len(end)] == end and at + len(end) == len(data): return out
        if data[at:at + len(end)] == end and not wide and at + 3 + 3 == len(data): return out   # an IPS may carry a truncation size after EOF; it does not apply to a module
        if at + w + 2 > len(data): raise ModError(f'{what}: cut short at {at:#x} (no {end.decode()} marker)')
        off = int.from_bytes(data[at:at + w], 'big'); size = int.from_bytes(data[at + w:at + w + 2], 'big'); at += w + 2
        if size == 0:   # RLE: a 16-bit count of one byte
            if at + 3 > len(data): raise ModError(f'{what}: an RLE record is cut short at {at:#x}')
            n, b = int.from_bytes(data[at:at + 2], 'big'), data[at + 2]; at += 3; body = bytes([b]) * n
        else:
            if at + size > len(data): raise ModError(f'{what}: a record of {size} bytes is cut short at {at:#x}')
            body = bytes(data[at:at + size]); at += size
        if off < NSO_HEADER: raise ModError(f'{what}: a record at {off:#x} writes the NSO header, not the module')
        out.append((off - NSO_HEADER, body))


def write_nso(header, image, segments, bss):
    """An uncompressed NSO of the image: the original header (build ID, module name, the rodata extents) with each segment stored after it at its (new) size, the
    compression and hash flags cleared"""
    h = bytearray(header[:NSO_HEADER]); body = bytearray(); fo = NSO_HEADER
    struct.pack_into('<I', h, 0xc, 0)
    for i, (mo, sz) in enumerate(segments):
        struct.pack_into('<III', h, 0x10 + 0x10 * i, fo, mo, sz)
        struct.pack_into('<I', h, 0x60 + 4 * i, sz)
        h[0xa0 + 0x20 * i:0xc0 + 0x20 * i] = bytes(0x20)
        body += image[mo:mo + sz]; fo += sz
    struct.pack_into('<I', h, 0x3c, bss)
    return bytes(h + body)


def apply_ips(mod_bytes, records, what):
    """The module's NSO with the records applied: a record in the gap after a segment grows that segment to its page end (where Horizon maps it zeroed)"""
    m = nso.load(mod_bytes, what)
    segs = [list(s) for s in m.segments]; img = bytearray(m.image)
    for off, body in records:
        end = off + len(body)
        for i, (mo, sz) in enumerate(segs):
            limit = segs[i + 1][0] if i + 1 < len(segs) else (mo + sz + PAGE - 1) & ~(PAGE - 1)
            if mo <= off and end <= limit:
                if end > mo + sz: segs[i][1] = min(limit, (end + PAGE - 1) & ~(PAGE - 1)) - mo
                break
        else: raise ModError(f'{what}: a record at {off:#x}..{end:#x} is outside the module\'s segments ({", ".join(f"{a:#x}+{b:#x}" for a, b in segs)})')
        if len(img) < end: img.extend(bytes(end - len(img)))
        img[off:end] = body
    return write_nso(mod_bytes, img, [tuple(s) for s in segs], m.bss), sum(len(b) for _, b in records)


def mod_files(src):
    """{name in exefs: bytes} of every exefs folder in a mod (a folder or a .zip), read in memory; names are lower-cased for matching, as the mod loaders match"""
    out = {}
    if src.is_file() and src.suffix.lower() == '.zip':
        with zipfile.ZipFile(src) as z:
            for info in z.infolist():
                parts = Path(info.filename).parts
                if info.is_dir() or len(parts) < 2 or parts[-2].lower() != 'exefs' or '..' in parts: continue
                out[parts[-1]] = z.read(info)
    elif src.is_dir():
        for p in sorted(src.rglob('*')):
            if p.is_file() and p.parent.name.lower() == 'exefs': out[p.name] = p.read_bytes()
    return out


def module_ids(exefs):
    """{module: build ID hex} of the ExeFS's code modules"""
    ids = {}
    for p in sorted(exefs.iterdir()):
        if not p.is_file() or p.name in SKIP: continue
        try: ids[p.name] = nso.read(p).build_id.hex()
        except (nso.Error, OSError): pass
    return ids


def apply(exefs, mods_dir, out):
    exefs, mods_dir, out = Path(exefs), Path(mods_dir), Path(out)
    ids = module_ids(exefs)
    data = {m: (exefs / m).read_bytes() for m in ids}
    rows, added = [], {}
    for src in sorted(p for p in mods_dir.iterdir() if not p.name.startswith('.') and (p.is_dir() or p.suffix.lower() == '.zip')):
        name = src.stem if src.is_file() else src.name
        files = mod_files(src)
        if not files: rows.append((name, '-', 'no exefs folder: nothing to build in (a RomFS-only mod is read at run time: DM_ROMFS_OVERLAY)')); continue
        for f, b in sorted(files.items()):
            what = f'{name}/exefs/{f}'
            if f.lower().endswith('.ips'):
                bid = f[:-4].lower()
                if not re.fullmatch(r'[0-9a-f]{16,64}', bid): rows.append((name, f, 'left out: not named after a build ID')); continue
                mod = next((m for m, i in ids.items() if i.startswith(bid) or bid.startswith(i[:32])), None)
                if mod is None: rows.append((name, f, f'left out: no module of build {bid[:16]}… in this version (the mod is for another update)')); continue
                data[mod], n = apply_ips(data[mod], ips_records(b, what), what)
                rows.append((name, mod, f'{len(ips_records(b, what))} patch records, {n} bytes ({f})'))
            elif f in SKIP or f.lower() in SKIP or '.' in f:
                rows.append((name, f, 'left out (not a code module)'))
            else:
                try: nso.load(b, what)
                except nso.Error as e: raise ModError(str(e)) from None
                if f in added: raise ModError(f'{what}: {added[f]} adds {f} too; two mods cannot share a module slot')
                rows.append((name, f, 'replaces the game\'s module' if f in data else 'added'))
                data[f] = b; added[f] = name
    if out.exists(): shutil.rmtree(out)
    out.mkdir(parents=True)
    for p in exefs.iterdir():
        if p.is_file() and p.name not in data: shutil.copy2(p, out / p.name)
    for m, b in data.items(): (out / m).write_bytes(b)
    (out / 'mods.tsv').write_text('# mod\tmodule\twhat was done (exefs_mods.py)\n' + ''.join('\t'.join(r) + '\n' for r in rows), encoding='utf-8')
    return rows, sorted(m for m in added if m not in ids)


if __name__ == '__main__':
    if len(sys.argv) != 4: sys.exit(__doc__.split('Usage: ')[1].split('\n')[0])
    try: rows, new = apply(*sys.argv[1:])
    except (ModError, nso.Error, zipfile.BadZipFile, OSError) as e: sys.exit(f'[RED] mods: {e}')
    for r in rows: print('\t'.join(r))
    print('added modules:', ' '.join(new) or 'none')
