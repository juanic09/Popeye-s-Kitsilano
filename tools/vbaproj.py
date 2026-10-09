"""Build an Excel vbaProject.bin from VBA source text (MS-OVBA + MS-CFB).

The _VBA_PROJECT stream carries no compiled p-code (version 0xFFFF), so Excel
compiles the modules from source the first time the workbook is opened.
"""
import random
import struct
import uuid

# ---------------------------------------------------------------- compression
def _copy_token_help(diff):
    bit_count = 4
    while (1 << bit_count) < diff:
        bit_count += 1
    length_mask = 0xFFFF >> bit_count
    max_length = length_mask + 3
    return bit_count, length_mask, max_length


def _compress_chunk(chunk):
    out = bytearray()
    pos = 0
    n = len(chunk)
    while pos < n:
        flag_index = len(out)
        out.append(0)
        flags = 0
        for bit in range(8):
            if pos >= n:
                break
            bit_count, _, max_length = _copy_token_help(pos)
            best_len, best_off = 0, 0
            if pos > 0:
                limit = min(max_length, n - pos)
                for cand in range(pos - 1, -1, -1):
                    length = 0
                    while length < limit and chunk[cand + length] == chunk[pos + length]:
                        length += 1
                    if length > best_len:
                        best_len, best_off = length, pos - cand
                        if length == limit:
                            break
            if best_len >= 3:
                token = ((best_off - 1) << (16 - bit_count)) | (best_len - 3)
                out += struct.pack('<H', token)
                flags |= 1 << bit
                pos += best_len
            else:
                out.append(chunk[pos])
                pos += 1
        out[flag_index] = flags
    return bytes(out)


def compress(data):
    out = bytearray(b'\x01')
    for start in range(0, len(data), 4096):
        chunk = data[start:start + 4096]
        packed = _compress_chunk(chunk)
        if len(packed) <= 4096:
            out += struct.pack('<H', 0xB000 | (len(packed) + 2 - 3))
            out += packed
        else:
            assert len(chunk) == 4096, 'incompressible partial chunk'
            out += struct.pack('<H', 0x3000 | 4095)
            out += chunk
    return bytes(out)


def decompress(data):
    assert data[0] == 1
    out = bytearray()
    pos = 1
    while pos < len(data):
        header = struct.unpack_from('<H', data, pos)[0]
        size = (header & 0x0FFF) + 3
        assert (header >> 12) & 0x7 == 0b011
        compressed = header >> 15
        chunk_end = pos + size
        pos += 2
        start = len(out)
        if not compressed:
            out += data[pos:pos + 4096]
            pos += 4096
            continue
        while pos < chunk_end:
            flags = data[pos]
            pos += 1
            for bit in range(8):
                if pos >= chunk_end:
                    break
                if flags & (1 << bit):
                    token = struct.unpack_from('<H', data, pos)[0]
                    pos += 2
                    bit_count, length_mask, _ = _copy_token_help(len(out) - start)
                    length = (token & length_mask) + 3
                    offset = (token >> (16 - bit_count)) + 1
                    for _ in range(length):
                        out.append(out[-offset])
                else:
                    out.append(data[pos])
                    pos += 1
    return bytes(out)


# ----------------------------------------------------------- PROJECT crypto
def encrypt(project_id, data, seed=None):
    seed = random.randrange(256) if seed is None else seed
    version = 2
    proj_key = sum(project_id.encode('ascii')) & 0xFF
    out = bytearray([seed, version ^ seed, proj_key ^ seed])
    unenc1, enc1, enc2 = proj_key, proj_key ^ seed, version ^ seed
    ignored = [random.randrange(256) for _ in range((seed & 6) // 2)]
    for b in ignored + list(struct.pack('<I', len(data))) + list(data):
        e = b ^ ((enc2 + unenc1) & 0xFF)
        out.append(e)
        enc2, enc1, unenc1 = enc1, e, b
    return out.hex().upper()


def decrypt(hex_text):
    raw = bytes.fromhex(hex_text)
    seed, version_enc, proj_key_enc = raw[0], raw[1], raw[2]
    version = seed ^ version_enc
    proj_key = seed ^ proj_key_enc
    unenc1, enc1, enc2 = proj_key, proj_key_enc, version_enc
    plain = []
    for e in raw[3:]:
        b = e ^ ((enc2 + unenc1) & 0xFF)
        plain.append(b)
        enc2, enc1, unenc1 = enc1, e, b
    ignored = (seed & 6) // 2
    length = struct.unpack('<I', bytes(plain[ignored:ignored + 4]))[0]
    return version, proj_key, bytes(plain[ignored + 4:ignored + 4 + length])


# ------------------------------------------------------------------ streams
WORKBOOK_BASE = '0{00020819-0000-0000-C000-000000000046}'
SHEET_BASE = '0{00020820-0000-0000-C000-000000000046}'
CODEPAGE = 1252


def _module_source(name, base, body):
    lines = [f'Attribute VB_Name = "{name}"']
    if base:
        lines += [
            f'Attribute VB_Base = "{base}"',
            'Attribute VB_GlobalNameSpace = False',
            'Attribute VB_Creatable = False',
            'Attribute VB_PredeclaredId = True',
            'Attribute VB_Exposed = True',
            'Attribute VB_TemplateDerived = False',
            'Attribute VB_Customizable = True',
        ]
    text = '\r\n'.join(lines) + '\r\n'
    body = body.replace('\r\n', '\n').strip('\n')
    if body:
        text += body.replace('\n', '\r\n') + '\r\n'
    return text.encode('cp1252')


def _rec(rec_id, payload):
    return struct.pack('<HI', rec_id, len(payload)) + payload


def _dir_stream(modules):
    enc = lambda s: s.encode('cp1252')
    u16 = lambda s: s.encode('utf-16-le')
    d = bytearray()
    d += _rec(0x0001, struct.pack('<I', 1))            # SYSKIND win32
    d += _rec(0x0002, struct.pack('<I', 0x0409))       # LCID
    d += _rec(0x0014, struct.pack('<I', 0x0409))       # LCIDINVOKE
    d += _rec(0x0003, struct.pack('<H', CODEPAGE))     # CODEPAGE
    d += _rec(0x0004, enc('VBAProject'))               # NAME
    d += _rec(0x0005, b'') + _rec(0x0040, b'')         # DOCSTRING
    d += _rec(0x0006, b'') + _rec(0x003D, b'')         # HELPFILEPATH
    d += _rec(0x0007, struct.pack('<I', 0))            # HELPCONTEXT
    d += _rec(0x0008, struct.pack('<I', 0))            # LIBFLAGS
    d += struct.pack('<HIIH', 0x0009, 4, 1, 0)         # VERSION
    d += _rec(0x000C, b'') + _rec(0x003C, b'')         # CONSTANTS
    # Reference: OLE Automation (stdole), as Excel writes it.
    libid = enc('*\\G{00020430-0000-0000-C000-000000000046}#2.0#0#'
                'C:\\Windows\\System32\\stdole2.tlb#OLE Automation')
    d += _rec(0x0016, enc('stdole')) + _rec(0x003E, u16('stdole'))
    d += _rec(0x000D, struct.pack('<I', len(libid)) + libid + struct.pack('<IH', 0, 0))
    # Modules
    d += _rec(0x000F, struct.pack('<H', len(modules)))
    d += _rec(0x0013, struct.pack('<H', 0xFFFF))
    for name, kind, _ in modules:
        d += _rec(0x0019, enc(name))
        d += _rec(0x0047, u16(name))
        d += _rec(0x001A, enc(name)) + _rec(0x0032, u16(name))
        d += _rec(0x001C, b'') + _rec(0x0048, b'')
        d += _rec(0x0031, struct.pack('<I', 0))        # source at offset 0
        d += _rec(0x001E, struct.pack('<I', 0))
        d += _rec(0x002C, struct.pack('<H', 0xFFFF))
        d += _rec(0x0021 if kind == 'module' else 0x0022, b'')
        d += _rec(0x002B, b'')
    d += _rec(0x0010, b'')
    return bytes(d)


def _project_stream(project_id, modules):
    lines = [f'ID="{project_id}"']
    for name, kind, _ in modules:
        if kind == 'module':
            lines.append(f'Module={name}')
        else:
            lines.append(f'Document={name}/&H00000000')
    lines += [
        'Name="VBAProject"',
        'HelpContextID="0"',
        'VersionCompatible32="393222000"',
        f'CMG="{encrypt(project_id, struct.pack("<I", 0))}"',
        f'DPB="{encrypt(project_id, bytes([0]))}"',
        f'GC="{encrypt(project_id, bytes([0xFF]))}"',
        '',
        '[Host Extender Info]',
        '&H00000001={3832D640-CF90-11CF-8E43-00A0C911005A};VBE;&H00000000',
        '',
        '[Workspace]',
    ]
    lines += [f'{name}=0, 0, 0, 0, C' for name, _, _ in modules]
    return ('\r\n'.join(lines) + '\r\n').encode('cp1252')


def _project_wm(modules):
    out = bytearray()
    for name, _, _ in modules:
        out += name.encode('cp1252') + b'\x00' + name.encode('utf-16-le') + b'\x00\x00'
    return bytes(out + b'\x00\x00')


def build_streams(modules):
    """modules: list of (name, kind, body); kind in workbook|sheet|module."""
    project_id = '{' + str(uuid.uuid4()).upper() + '}'
    streams = {
        'PROJECT': _project_stream(project_id, modules),
        'PROJECTwm': _project_wm(modules),
        'VBA/_VBA_PROJECT': bytes([0xCC, 0x61, 0xFF, 0xFF, 0x00, 0x00, 0x00]),
        'VBA/dir': compress(_dir_stream(modules)),
    }
    for name, kind, body in modules:
        base = {'workbook': WORKBOOK_BASE, 'sheet': SHEET_BASE}.get(kind)
        streams['VBA/' + name] = compress(_module_source(name, base, body))
    return streams


# ---------------------------------------------------------------------- CFB
SECTOR = 512
MINI = 64
CUTOFF = 4096
FREESECT, ENDOFCHAIN, FATSECT = 0xFFFFFFFF, 0xFFFFFFFE, 0xFFFFFFFD
NOSTREAM = 0xFFFFFFFF


def _cfb_key(name):
    return (len(name), name.upper())


class _Entry:
    def __init__(self, name, kind, data=None):
        self.name, self.kind, self.data = name, kind, data  # kind: 5 root, 1 storage, 2 stream
        self.children = []
        self.left = self.right = self.child = NOSTREAM
        self.start, self.size = ENDOFCHAIN, 0
        self.id = None


def _balanced(nodes):
    if not nodes:
        return NOSTREAM
    mid = len(nodes) // 2
    node = nodes[mid]
    node.left = _balanced(nodes[:mid])
    node.right = _balanced(nodes[mid + 1:])
    return node.id


def build_cfb(streams):
    root = _Entry('Root Entry', 5)
    storages = {'': root}
    for path in sorted(streams):
        parts = path.split('/')
        parent = root
        for i, part in enumerate(parts[:-1]):
            key = '/'.join(parts[:i + 1])
            if key not in storages:
                st = _Entry(part, 1)
                parent.children.append(st)
                storages[key] = st
            parent = storages[key]
        parent.children.append(_Entry(parts[-1], 2, streams[path]))

    entries = []
    def number(e):
        e.id = len(entries)
        entries.append(e)
        for c in sorted(e.children, key=lambda x: _cfb_key(x.name)):
            number(c)
    number(root)
    for e in entries:
        if e.children:
            e.child = _balanced(sorted(e.children, key=lambda x: _cfb_key(x.name)))

    # Small streams live in the mini stream; big ones get regular sectors.
    mini_data, minifat = bytearray(), []
    big = []
    for e in entries:
        if e.kind != 2:
            continue
        e.size = len(e.data)
        if e.size == 0:
            e.start = ENDOFCHAIN
        elif e.size < CUTOFF:
            first = len(mini_data) // MINI
            count = -(-e.size // MINI)
            e.start = first
            minifat += [first + i + 1 for i in range(count - 1)] + [ENDOFCHAIN]
            mini_data += e.data + b'\x00' * (count * MINI - e.size)
        else:
            big.append(e)

    def nsec(nbytes):
        return -(-nbytes // SECTOR)

    dir_secs = nsec(len(entries) * 128)
    minifat_secs = nsec(len(minifat) * 4)
    mini_secs = nsec(len(mini_data))
    big_secs = sum(nsec(len(e.data)) for e in big)
    fat_secs = 1
    while True:
        total = fat_secs + dir_secs + minifat_secs + mini_secs + big_secs
        if fat_secs * (SECTOR // 4) >= total:
            break
        fat_secs += 1
    assert fat_secs <= 109

    fat = []
    body = bytearray()
    def chain(count):
        start = len(fat)
        fat.extend(range(start + 1, start + count))
        fat.append(ENDOFCHAIN)
        return start
    fat.extend([FATSECT] * fat_secs)
    dir_start = chain(dir_secs)
    minifat_start = chain(minifat_secs) if minifat_secs else ENDOFCHAIN
    mini_start = chain(mini_secs) if mini_secs else ENDOFCHAIN
    for e in big:
        e.start = chain(nsec(len(e.data)))
    root.start = mini_start
    root.size = len(mini_data)

    def pad(b):
        return bytes(b) + b'\x00' * (-len(b) % SECTOR)

    dir_bytes = bytearray()
    for e in entries:
        name = e.name.encode('utf-16-le') + b'\x00\x00'
        dir_bytes += name.ljust(64, b'\x00')
        dir_bytes += struct.pack('<HBB', len(name), e.kind, 1)
        dir_bytes += struct.pack('<III', e.left, e.right, e.child)
        dir_bytes += b'\x00' * 16 + struct.pack('<I', 0) + b'\x00' * 16
        dir_bytes += struct.pack('<IQ', e.start, e.size)
    while len(dir_bytes) % SECTOR:
        dir_bytes += b'\x00' * 64 + struct.pack('<HBB', 0, 0, 0)
        dir_bytes += struct.pack('<III', NOSTREAM, NOSTREAM, NOSTREAM)
        dir_bytes += b'\x00' * 36 + struct.pack('<IQ', 0, 0)

    minifat_bytes = struct.pack(f'<{len(minifat)}I', *minifat)
    minifat_bytes += struct.pack('<I', FREESECT) * (-len(minifat) % (SECTOR // 4))

    fat += [FREESECT] * (fat_secs * (SECTOR // 4) - len(fat))
    body += struct.pack(f'<{len(fat)}I', *fat)
    body += pad(dir_bytes)
    if minifat_secs:
        body += minifat_bytes
    if mini_secs:
        body += pad(mini_data)
    for e in big:
        body += pad(e.data)

    header = bytearray()
    header += bytes.fromhex('D0CF11E0A1B11AE1') + b'\x00' * 16
    header += struct.pack('<HHHHH', 0x003E, 0x0003, 0xFFFE, 9, 6)
    header += b'\x00' * 6
    header += struct.pack('<IIIIIIIII', 0, fat_secs, dir_start, 0, CUTOFF,
                          minifat_start, minifat_secs, ENDOFCHAIN, 0)
    difat = list(range(fat_secs)) + [FREESECT] * (109 - fat_secs)
    header += struct.pack('<109I', *difat)
    assert len(header) == 512
    return bytes(header) + bytes(body)


def build_vba_project(modules):
    return build_cfb(build_streams(modules))
