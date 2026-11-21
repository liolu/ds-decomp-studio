#!/usr/bin/env python3
"""Builds the ROM with dsd, working around what dsd cannot rebuild byte for byte. What ninja runs:

    python tools/rom_build.py <dsd> [dsd flags] rom build --config <rom_config.yaml> --rom <rom> [...]

Before the build: overlays protected by DSProtect (Nintendo's anti-piracy: some functions are stored encrypted).
dsd decrypts them when extracting and encrypts them again when building, but its encryption of the integrity
check functions differs from the original (Professor Layton and the Spectre's Call, overlay 3), so the
compressed overlay changes size and the whole ROM after it moves. When the linked overlay is exactly the extracted
one (its code was not changed), dsd gets the original encrypted bytes instead (taken from extract/baserom_*.nds)
with the protection removed from its config: nothing left to encrypt, same bytes as the original. A changed
overlay is left to dsd.

After the build:
  - the banner icon (banner_fix.py: palettes with the same colour twice);
  - empty files: Nintendo's tool gave them another address than dsd does (Tom and Jerry Tales: structor3/adf/...).
    They hold no data, so their FAT entry takes the original address back;
  - the cartridge size: dsd picks the smallest chip, the original may be bigger and padded with 0xFF;
  - the recorded secure-area CRC, when no BIOS was supplied and the secure area
    is unchanged. dsd otherwise writes zero; the header CRC is then recomputed.
  - DSi-enhanced ROMs without a BIOS (arm7_bios.bin): dsd needs the BIOS Blowfish key to encrypt the ARM9 secure
    area, which some DSi hashes cover. It gets a placeholder key, then each value computed from the encrypted secure
    area takes the base ROM's value back, only when what that value covers is byte-identical to the base ROM
    (dsi_no_bios_fix). A changed ARM9 or secure area keeps the placeholder's values: the build says so.
"""
import re
import struct
import subprocess
import sys
from pathlib import Path


def _game_root() -> Path:
    """The game: $DSD_PROJECT, else <game>/ above tools/, else the current folder (the shared tools/ of
    All-nds-decomp-games run with cwd = games/<LETTER>/<game>/)."""
    import os
    if os.environ.get("DSD_PROJECT"):
        return Path(os.environ["DSD_PROJECT"]).resolve()
    up = Path(__file__).resolve().parent.parent
    return up if (up / "config").is_dir() else Path.cwd().resolve()


from ndspy import _common

ROOT = _game_root()
sys.path.insert(0, str(Path(__file__).resolve().parent))
import banner_fix  # noqa: E402


def u32(b, o):
    return struct.unpack_from("<I", b, o)[0]


def blz_decompress(data: bytes) -> bytes:
    """Nintendo's backward LZ (compressed ARM9 and overlays)."""
    if len(data) < 8:
        return data
    footer, extra = u32(data, len(data) - 8), u32(data, len(data) - 4)
    hdr, comp_len = footer >> 24, footer & 0xFFFFFF
    out = bytearray(data) + bytearray(extra)
    src, dst, end = len(data) - hdr, len(out), len(data) - comp_len
    while src > end:
        src -= 1
        flags = data[src]
        for _ in range(8):
            if src <= end:
                break
            if flags & 0x80:
                src -= 2
                v = data[src] | (data[src + 1] << 8)
                ln, disp = (v >> 12) + 3, (v & 0xFFF) + 3
                for _ in range(ln):
                    dst -= 1
                    out[dst] = out[dst + disp]
            else:
                src -= 1
                dst -= 1
                out[dst] = data[src]
            flags <<= 1
    return bytes(out)


def original_overlay(rom: bytes, ov_id: int) -> bytes | None:
    """Decompressed contents of an ARM9 overlay of the original ROM (still encrypted where it was)."""
    table, n, fat = u32(rom, 0x50), u32(rom, 0x54) // 32, u32(rom, 0x48)
    if ov_id >= n:
        return None
    e = table + ov_id * 32
    fid, flag = u32(rom, e + 24), u32(rom, e + 28)
    data = rom[u32(rom, fat + fid * 8): u32(rom, fat + fid * 8 + 4)]
    return blz_decompress(data) if flag & 0x01000000 else data


def dsprot_config(config: Path) -> Path:
    """A copy of rom_config.yaml where the unchanged DSProtect overlays come already encrypted. Returns the config
    to give dsd (the original one when there is nothing to do)."""
    base = next((ROOT / "extract").glob("baserom*.nds"), None)
    text = config.read_text(encoding="utf-8")
    m = re.search(r"^arm9_overlays: (\S+)", text, re.M)
    if base is None or not m or m.group(1) == "null":
        return config
    ov_yaml = config.parent / m.group(1)
    ovs = ov_yaml.read_text(encoding="utf-8")
    if "dsprot:" not in ovs:
        return config
    version = config.parent.parent.name  # build/<version>/build/rom_config.yaml
    rom = base.read_bytes()
    blocks = re.split(r"(?m)^(?=  - id: )", ovs)
    changed = 0
    for k, b in enumerate(blocks):
        mid = re.match(r"  - id: (\d+)\n", b)
        if not mid or "\n    dsprot:" not in b:
            continue
        ov_id = int(mid.group(1))
        fname = re.search(r"^    file_name: (\S+)", b, re.M).group(1)
        built = config.parent / fname
        extracted = ROOT / "extract" / version / "arm9_overlays" / f"ov{ov_id:03d}.bin"
        if not (built.exists() and extracted.exists()) or built.read_bytes() != extracted.read_bytes():
            continue  # the code changed: dsd has to encrypt it
        enc = original_overlay(rom, ov_id)
        code_size = int(re.search(r"^    code_size: (\d+)", b, re.M).group(1))
        if enc is None or len(enc) < code_size:
            continue
        out = config.parent / "dsprot" / fname
        out.parent.mkdir(exist_ok=True)
        out.write_bytes(enc[:code_size])
        b = re.sub(r"^    file_name: \S+", f"    file_name: dsprot/{fname}", b, flags=re.M)
        b = re.sub(r"(?m)^    dsprot:\n(?:      .*\n?)*", "", b)
        blocks[k] = b
        changed += 1
    if not changed:
        return config
    new_ov = ov_yaml.with_name(ov_yaml.stem + ".dsprot.yaml")
    new_ov.write_text("".join(blocks), encoding="utf-8", newline="\n")
    new_cfg = config.with_name(config.stem + ".dsprot.yaml")
    new_cfg.write_text(text.replace(f"arm9_overlays: {m.group(1)}", f"arm9_overlays: {new_ov.name}", 1),
                       encoding="utf-8", newline="\n")
    print(f"rom_build: {changed} DSProtect overlay(s) unchanged, original encrypted bytes used")
    return new_cfg


def empty_files_fix(orig: bytes, rom: bytearray) -> int:
    """FAT entries of empty files (start == end in both ROMs) set to the original address."""
    fo, fn = u32(orig, 0x48), u32(rom, 0x48)
    if u32(orig, 0x4C) != u32(rom, 0x4C):
        return 0
    n = 0
    for i in range(u32(orig, 0x4C) // 8):
        so, eo = u32(orig, fo + i * 8), u32(orig, fo + i * 8 + 4)
        sn, en = u32(rom, fn + i * 8), u32(rom, fn + i * 8 + 4)
        if so == eo and sn == en and so != sn:
            struct.pack_into("<II", rom, fn + i * 8, so, eo)
            n += 1
    return n


def secure_area_crc_fix(orig: bytes, rom: bytearray) -> bool:
    """Preserve missing checksum metadata only for an unchanged secure area.

    The decrypted input still records the encrypted secure area's checksum.
    Without a BIOS, the builder cannot recompute it. Preserve that field only
    when the secure area, game code and ARM9 location agree with the input.
    Recompute the header CRC so other header changes are not hidden.
    """
    if min(len(orig), len(rom)) < 0x8000:
        return False
    if u32(orig, 0x20) != 0x4000 or u32(rom, 0x20) != 0x4000:
        return False
    if orig[0x0c:0x10] != rom[0x0c:0x10] or orig[0x4000:0x8000] != rom[0x4000:0x8000]:
        return False
    recorded = struct.unpack_from("<H", orig, 0x6c)[0]
    if not recorded or struct.unpack_from("<H", rom, 0x6c)[0] != 0:
        return False
    if _common.crc16(orig[:0x15e]) != struct.unpack_from("<H", orig, 0x15e)[0]:
        return False
    struct.pack_into("<H", rom, 0x6c, recorded)
    struct.pack_into("<H", rom, 0x15e, _common.crc16(rom[:0x15e]))
    return True


HASH = 0x14                 # SHA1-HMAC
DSI_HMAC_ARM9_SA = 0x300    # header: SHA1-HMAC of the ARM9 with its secure area encrypted
DSI_HMAC_DIGEST = 0x328     # header: SHA1-HMAC of the digest block hashtable
SECURE_AREA = 0x4000        # encrypted secure area: the first 16 KB of the ARM9 (only 2 KB really change)


def is_dsi(header: bytes) -> bool:
    """DSi-enhanced or DSi-only ROM (unit code)."""
    return len(header) > 0x12 and bool(header[0x12] & 0x02)


def dsi_no_bios_fix(orig: bytes, rom: bytearray, arm9i_unchanged: bool) -> list[str]:
    """DSi ROM built with a placeholder Blowfish key: the values computed from the encrypted secure area are wrong.
    Each one takes the base ROM's value back, only when everything it covers is byte-identical to the base ROM (so
    the real key would give that value too). Returns what was restored."""
    if not (is_dsi(orig) and is_dsi(rom)) or min(len(orig), len(rom)) < 0x8000:
        return []
    # Same game code, ARM9 place and size, DSi program/digest/modcrypt tables (0x1c0-0x230)
    if orig[0x0c:0x10] != rom[0x0c:0x10] or orig[0x20:0x30] != rom[0x20:0x30] or orig[0x1c0:0x230] != rom[0x1c0:0x230]:
        return []
    arm9_off, arm9_size = u32(rom, 0x20), u32(rom, 0x2c)
    if arm9_size < SECURE_AREA or orig[arm9_off:arm9_off + SECURE_AREA] != rom[arm9_off:arm9_off + SECURE_AREA]:
        return []
    done = []

    def restore(start: int, size: int) -> bool:
        if rom[start:start + size] == orig[start:start + size]:
            return False
        rom[start:start + size] = orig[start:start + size]
        return True

    if restore(0x6c, 2):  # NTR secure-area CRC: CRC16 of the encrypted secure area
        done.append("secure-area CRC")
    if orig[arm9_off:arm9_off + arm9_size] == rom[arm9_off:arm9_off + arm9_size] and restore(DSI_HMAC_ARM9_SA, HASH):
        done.append("ARM9 SHA1-HMAC")
    # Digest: one hash per sector (the secure area's sectors are hashed encrypted), one per block of sectors, then
    # the master hash of the block hashtable
    ds_off = u32(rom, 0x1e0)
    sht_off, sht_size, bht_off, bht_size = u32(rom, 0x1f0), u32(rom, 0x1f4), u32(rom, 0x1f8), u32(rom, 0x1fc)
    sector_size, per_block = u32(rom, 0x200), u32(rom, 0x204)
    if sector_size and per_block and sht_size and bht_size and ds_off <= arm9_off:
        n = 0
        for s in range((arm9_off - ds_off) // sector_size, (arm9_off + SECURE_AREA - 1 - ds_off) // sector_size + 1):
            sector = ds_off + s * sector_size
            if orig[sector:sector + sector_size] == rom[sector:sector + sector_size]:
                n += restore(sht_off + s * HASH, HASH)
        if n:
            done.append(f"{n} digest sector hash(es)")
        n = 0
        for b in range(bht_size // HASH):
            hashes = slice(sht_off + b * per_block * HASH, min(sht_off + (b + 1) * per_block * HASH, sht_off + sht_size))
            if orig[hashes] == rom[hashes]:
                n += restore(bht_off + b * HASH, HASH)
        if n:
            done.append(f"{n} digest block hash(es)")
        if orig[bht_off:bht_off + bht_size] == rom[bht_off:bht_off + bht_size] and restore(DSI_HMAC_DIGEST, HASH):
            done.append("digest master hash")
    # Modcrypt area 1 (ARM9i): AES-CTR whose counter is the ARM9 SHA1-HMAC above. Same counter + same ARM9i as the
    # one extracted from the base ROM = the base ROM's bytes
    m_off, m_size = u32(rom, 0x220), u32(rom, 0x224)
    if m_size and arm9i_unchanged and orig[DSI_HMAC_ARM9_SA:DSI_HMAC_ARM9_SA + HASH] == rom[DSI_HMAC_ARM9_SA:DSI_HMAC_ARM9_SA + HASH]:
        if restore(m_off, m_size):
            done.append("ARM9i modcrypt area")
    if done:
        struct.pack_into("<H", rom, 0x15e, _common.crc16(rom[:0x15e]))
    return done


def dsi_key_fields_differ(orig: bytes, rom: bytes) -> bool:
    """Whether a value that needs the real Blowfish key still differs from the base ROM (after dsi_no_bios_fix)."""
    if min(len(orig), len(rom)) < 0x8000:
        return True
    spans = [(0x6c, 2), (DSI_HMAC_ARM9_SA, HASH), (DSI_HMAC_DIGEST, HASH), (u32(rom, 0x220), u32(rom, 0x224))]
    return any(orig[a:a + n] != rom[a:a + n] for a, n in spans)


def arm9i_unchanged(config: Path) -> bool:
    """The ARM9i the build used is the one extracted from the base ROM (build/<version>/build/rom_config.yaml)."""
    m = re.search(r"^  arm9i_bin: (\S+)", config.read_text(encoding="utf-8"), re.M)
    extracted = ROOT / "extract" / config.parent.parent.name / "dsi" / "arm9i.bin"
    if not m or not extracted.exists():
        return False
    used = config.parent / m.group(1)
    return used.exists() and used.read_bytes() == extracted.read_bytes()


def capacity_fix(orig: bytes, rom: bytearray) -> bool:
    """dsd picks the smallest cartridge that holds the files (header byte 0x14) and writes no padding after them;
    Nintendo's tool may have chosen a bigger chip and filled the rest with 0xFF (Sudokumaniacs: 8 MB, dsd 4 MB).
    When the original ends with nothing but 0xFF after our ROM's length, its capacity byte and padding come back."""
    if len(orig) <= len(rom) or orig[0x14] <= rom[0x14]:
        return False
    if orig[len(rom):].strip(b"\xff"):
        return False
    rom[0x14] = orig[0x14]
    rom.extend(b"\xff" * (len(orig) - len(rom)))
    struct.pack_into("<H", rom, 0x15e, _common.crc16(rom[:0x15e]))
    return True


def main():
    cmd = sys.argv[1:]
    config = None
    if "--config" in cmd:
        i = cmd.index("--config") + 1
        config = Path(cmd[i])
        cmd[i] = str(dsprot_config(config))
    has_bios = any(arg == "--arm7-bios" or arg.startswith("--arm7-bios=") or arg.startswith("-7") for arg in cmd)
    base = next((ROOT / "extract").glob("baserom*.nds"), None)
    placeholder_key = False
    if not has_bios and base is not None and config is not None and "--rom" in cmd:
        with base.open("rb") as f:
            if is_dsi(f.read(0x200)):
                # A DSi ROM cannot be built without a Blowfish key: a placeholder one, fixed after the build
                key = config.parent / "placeholder_arm7_bios.bin"
                if not key.exists():
                    key.write_bytes(bytes(0x4000))
                cmd += ["--arm7-bios", str(key)]
                placeholder_key = True
    r = subprocess.run(cmd)
    if r.returncode:
        sys.exit(r.returncode)
    if "--rom" in cmd:
        rom_path = Path(cmd[cmd.index("--rom") + 1])
        if base is not None and rom_path.exists():
            rom, orig = bytearray(rom_path.read_bytes()), base.read_bytes()
            n = banner_fix.fix(orig, rom)
            if n > 0:
                print(f"rom_build: {n} icon pixels given their original palette index back")
            e = empty_files_fix(orig, rom)
            if e:
                print(f"rom_build: {e} empty files given their original address back")
            c = not has_bios and not placeholder_key and secure_area_crc_fix(orig, rom)
            if c:
                print("rom_build: preserved recorded secure-area CRC for unchanged secure area; recomputed header CRC")
            d = placeholder_key and dsi_no_bios_fix(orig, rom, arm9i_unchanged(config))
            if d:
                print(f"rom_build: DSi ROM without arm7_bios.bin: {', '.join(d)} of the base ROM kept (unchanged "
                      "secure area / ARM9 / ARM9i); recomputed header CRC")
            if placeholder_key and dsi_key_fields_differ(orig, rom):
                print("rom_build: WARNING: DSi ROM built without arm7_bios.bin and its secure area or ARM9 changed: "
                      "the hashes that need the BIOS key are wrong. Put your ARM7 BIOS in arm7_bios.bin to get them.")
            p = capacity_fix(orig, rom)
            if p:
                print(f"rom_build: cartridge size and 0xFF padding of the original kept ({len(orig) >> 20} MB)")
            if n > 0 or e or c or d or p:
                rom_path.write_bytes(rom)


if __name__ == "__main__":
    main()
