"""
qrcode.py - A QR encoder, in the standard library only.

ProtBot links a phone to a PC by showing a code on one screen and pointing the
other at it. That needs a QR encoder, and every Python QR library either pulls
in Pillow to draw or drags a dependency tree behind it. Pillow is exactly what
was removed when pystray went (AUDIT BL-05), and re-adding it for one dialog
would be a poor trade — so this is the encoder, and it draws with Tk rectangles.

Scope is deliberately narrow: **byte mode, versions 1-10, all four error
correction levels.** That covers a link URL several times over and stops well
short of the parts of the specification nobody here needs — kanji mode, ECI,
structured append, micro QR. Anything longer than version 10 raises rather than
guessing.

Correctness is not taken on trust, because an encoder is a bad thing to check
by looking at it: a wrong symbol looks exactly like a right one. So
`tests/test_qrcode.py` renders what this produces and reads it back with
OpenCV's decoder, and separately compares it module-for-module against `segno`
with the mask pinned. Both are test dependencies; neither is imported here and
neither ships.

That test found two bugs during development, each of which produced symbols
that were pixel-perfect in every visible respect and unreadable by anything:
format bits placed least-significant first, and the byte-mode length indicator
left at 8 bits where version 10 widens it to 16.

The pieces, in the order the encoder uses them:

    encode()          text -> a boolean matrix, True meaning a dark module
      _encode_data()    mode, length, payload, padding
      _add_ec()         Reed-Solomon over GF(256), then block interleaving
      _draw()           function patterns, then the data zigzag
      _best_mask()      all eight masks, scored, lowest penalty wins

Every reference to "the specification" below means ISO/IEC 18004.
"""

# ── GF(256), the field Reed-Solomon works in ──────────────────────────────
#
# QR uses the primitive polynomial x^8 + x^4 + x^3 + x^2 + 1 (0x11D) with 2 as
# the generator. Exponent and log tables turn multiplication into addition,
# which is what makes the rest of this readable.

_EXP = [0] * 512
_LOG = [0] * 256


def _build_tables() -> None:
    value = 1
    for power in range(255):
        _EXP[power] = value
        _LOG[value] = power
        value <<= 1
        if value & 0x100:            # overflowed 8 bits: reduce by the polynomial
            value ^= 0x11D
    for power in range(255, 512):    # doubled so multiply never needs a modulo
        _EXP[power] = _EXP[power - 255]


_build_tables()


def _mul(a: int, b: int) -> int:
    if a == 0 or b == 0:
        return 0
    return _EXP[_LOG[a] + _LOG[b]]


def _generator_poly(degree: int) -> list:
    """
    The generator polynomial for `degree` error-correction codewords:
    (x - 2^0)(x - 2^1)...(x - 2^(degree-1)), coefficients high-order first.
    """
    poly = [1]
    for power in range(degree):
        # Multiply by (x - 2^power). Subtraction is XOR here, so the sign the
        # textbook formula carries makes no difference.
        nxt = [0] * (len(poly) + 1)
        for i, coeff in enumerate(poly):
            nxt[i] ^= coeff
            nxt[i + 1] ^= _mul(coeff, _EXP[power])
        poly = nxt
    return poly


def _ec_codewords(data: list, count: int) -> list:
    """Polynomial division remainder: the error-correction codewords."""
    generator = _generator_poly(count)
    remainder = list(data) + [0] * count

    for i in range(len(data)):
        lead = remainder[i]
        if lead == 0:
            continue
        for j, coeff in enumerate(generator):
            remainder[i + j] ^= _mul(coeff, lead)

    return remainder[len(data):]


# ── Capacity tables ───────────────────────────────────────────────────────
#
# For each version and error level: how many EC codewords each block carries,
# and how the data codewords split into blocks. Larger versions use two group
# sizes because the data does not divide evenly.
#
#   (ec_per_block, group1_blocks, group1_data_cw, group2_blocks, group2_data_cw)
#
# test_qrcode.py checks every row against the specification's total-codeword
# count for its version, which catches a mistyped number immediately.

L, M, Q, H = "L", "M", "Q", "H"

_BLOCKS = {
    (1, L): (7, 1, 19, 0, 0),    (1, M): (10, 1, 16, 0, 0),
    (1, Q): (13, 1, 13, 0, 0),   (1, H): (17, 1, 9, 0, 0),

    (2, L): (10, 1, 34, 0, 0),   (2, M): (16, 1, 28, 0, 0),
    (2, Q): (22, 1, 22, 0, 0),   (2, H): (28, 1, 16, 0, 0),

    (3, L): (15, 1, 55, 0, 0),   (3, M): (26, 1, 44, 0, 0),
    (3, Q): (18, 2, 17, 0, 0),   (3, H): (22, 2, 13, 0, 0),

    (4, L): (20, 1, 80, 0, 0),   (4, M): (18, 2, 32, 0, 0),
    (4, Q): (26, 2, 24, 0, 0),   (4, H): (16, 4, 9, 0, 0),

    (5, L): (26, 1, 108, 0, 0),  (5, M): (24, 2, 43, 0, 0),
    (5, Q): (18, 2, 15, 2, 16),  (5, H): (22, 2, 11, 2, 12),

    (6, L): (18, 2, 68, 0, 0),   (6, M): (16, 4, 27, 0, 0),
    (6, Q): (24, 4, 19, 0, 0),   (6, H): (28, 4, 15, 0, 0),

    (7, L): (20, 2, 78, 0, 0),   (7, M): (18, 4, 31, 0, 0),
    (7, Q): (18, 2, 14, 4, 15),  (7, H): (26, 4, 13, 1, 14),

    (8, L): (24, 2, 97, 0, 0),   (8, M): (22, 2, 38, 2, 39),
    (8, Q): (22, 4, 18, 2, 19),  (8, H): (26, 4, 14, 2, 15),

    (9, L): (30, 2, 116, 0, 0),  (9, M): (22, 3, 36, 2, 37),
    (9, Q): (20, 4, 16, 4, 17),  (9, H): (24, 4, 12, 4, 13),

    (10, L): (18, 2, 68, 2, 69), (10, M): (26, 4, 43, 1, 44),
    (10, Q): (24, 6, 19, 2, 20), (10, H): (28, 6, 15, 2, 16),
}

MAX_VERSION = 10

# Row and column centres of the alignment patterns. Version 1 has none.
_ALIGNMENT = {
    1: [], 2: [6, 18], 3: [6, 22], 4: [6, 26], 5: [6, 30],
    6: [6, 34], 7: [6, 22, 38], 8: [6, 24, 42], 9: [6, 26, 46],
    10: [6, 28, 50],
}

# Two bits each, and deliberately not in quality order — that ordering is what
# the specification assigns, and inventing a tidier one would silently produce
# codes that decode at the wrong level.
_ECL_BITS = {L: 0b01, M: 0b00, Q: 0b11, H: 0b10}

_BYTE_MODE = 0b0100
_PAD_BYTES = (0xEC, 0x11)


def data_capacity(version: int, ecl: str) -> int:
    """How many data codewords fit at this version and error level."""
    ec_per_block, g1_blocks, g1_cw, g2_blocks, g2_cw = _BLOCKS[(version, ecl)]
    return g1_blocks * g1_cw + g2_blocks * g2_cw


def _fits(length: int, version: int, ecl: str) -> bool:
    """Whether `length` bytes fit, counting the mode and length overhead."""
    overhead = 4 + count_bits(version)
    return overhead + length * 8 <= data_capacity(version, ecl) * 8


def count_bits(version: int) -> int:
    """
    Width of the character-count indicator in byte mode.

    8 bits up to version 9 and 16 from version 10 — a detail that costs
    nothing until the day a payload crosses into version 10, and then breaks
    every symbol at that size while every smaller one still works.
    """
    return 8 if version <= 9 else 16


def smallest_version(length: int, ecl: str) -> int:
    """
    The smallest version that holds `length` bytes at this error level.

    Raising rather than silently dropping to a lower error level: a caller
    asking for H and quietly getting L would be a worse outcome than an error
    it can see.
    """
    for version in range(1, MAX_VERSION + 1):
        if _fits(length, version, ecl):
            return version
    raise ValueError(
        f"{length} bytes does not fit in a version-{MAX_VERSION} code at "
        f"error level {ecl}. This encoder deliberately stops at version "
        f"{MAX_VERSION}; shorten the payload."
    )


# ── Encoding ──────────────────────────────────────────────────────────────

def _encode_data(payload: bytes, version: int, ecl: str) -> list:
    """Mode indicator, length, payload, terminator and padding, as codewords."""
    capacity_bits = data_capacity(version, ecl) * 8

    bits = []

    def push(value: int, width: int) -> None:
        for shift in range(width - 1, -1, -1):
            bits.append((value >> shift) & 1)

    push(_BYTE_MODE, 4)
    push(len(payload), count_bits(version))
    for byte in payload:
        push(byte, 8)

    # Terminator: up to four zero bits, or fewer if the code is nearly full.
    push(0, min(4, capacity_bits - len(bits)))

    # Pad to a byte boundary, then alternate the two specified pad bytes.
    while len(bits) % 8:
        bits.append(0)

    codewords = [int("".join(str(b) for b in bits[i:i + 8]), 2)
                 for i in range(0, len(bits), 8)]

    pad = 0
    while len(codewords) < data_capacity(version, ecl):
        codewords.append(_PAD_BYTES[pad % 2])
        pad += 1

    return codewords


def _add_ec(codewords: list, version: int, ecl: str) -> list:
    """
    Split into blocks, compute error correction, and interleave.

    Interleaving is what makes a QR survive a scratch: a damaged patch of the
    symbol spreads its errors across every block instead of destroying one.
    """
    ec_per_block, g1_blocks, g1_cw, g2_blocks, g2_cw = _BLOCKS[(version, ecl)]

    blocks, ec_blocks, offset = [], [], 0
    for count, size in ((g1_blocks, g1_cw), (g2_blocks, g2_cw)):
        for _ in range(count):
            block = codewords[offset:offset + size]
            offset += size
            blocks.append(block)
            ec_blocks.append(_ec_codewords(block, ec_per_block))

    result = []
    for i in range(max(len(b) for b in blocks)):
        for block in blocks:
            if i < len(block):
                result.append(block[i])
    for i in range(ec_per_block):
        for block in ec_blocks:
            result.append(block[i])

    return result


# ── Drawing ───────────────────────────────────────────────────────────────

def _new_matrix(size: int):
    """(modules, reserved) — reserved marks anything data must not overwrite."""
    return ([[False] * size for _ in range(size)],
            [[False] * size for _ in range(size)])


def _place_finder(modules, reserved, top: int, left: int) -> None:
    """One 7x7 finder pattern plus its one-module separator."""
    size = len(modules)
    for row in range(-1, 8):
        for col in range(-1, 8):
            r, c = top + row, left + col
            if not (0 <= r < size and 0 <= c < size):
                continue
            border = row in (0, 6) and 0 <= col <= 6
            side = col in (0, 6) and 0 <= row <= 6
            core = 2 <= row <= 4 and 2 <= col <= 4
            modules[r][c] = border or side or core
            reserved[r][c] = True


def _place_alignment(modules, reserved, version: int) -> None:
    centres = _ALIGNMENT[version]
    last = len(centres) - 1
    for i, row in enumerate(centres):
        for j, col in enumerate(centres):
            # The three corners hold finder patterns instead.
            if (i, j) in ((0, 0), (0, last), (last, 0)):
                continue
            for dr in range(-2, 3):
                for dc in range(-2, 3):
                    modules[row + dr][col + dc] = max(abs(dr), abs(dc)) != 1
                    reserved[row + dr][col + dc] = True


def _place_timing(modules, reserved) -> None:
    size = len(modules)
    for i in range(8, size - 8):
        on = i % 2 == 0
        modules[6][i] = on
        reserved[6][i] = True
        modules[i][6] = on
        reserved[i][6] = True


def _reserve_format(reserved, version: int) -> None:
    size = len(reserved)
    for i in range(9):
        reserved[8][i] = True
        reserved[i][8] = True
    for i in range(8):
        reserved[8][size - 1 - i] = True
        reserved[size - 1 - i][8] = True

    if version >= 7:
        for i in range(6):
            for j in range(3):
                reserved[size - 11 + j][i] = True
                reserved[i][size - 11 + j] = True


def _place_data(modules, reserved, codewords: list) -> None:
    """
    The zigzag: upward then downward in two-column strips, from bottom-right.

    Column 6 is skipped entirely — it is the vertical timing pattern, and
    treating it as a normal column shifts every module after it.
    """
    size = len(modules)
    bits = []
    for codeword in codewords:
        for shift in range(7, -1, -1):
            bits.append((codeword >> shift) & 1)

    index = 0
    col = size - 1
    upward = True

    while col > 0:
        if col == 6:
            col -= 1
        rows = range(size - 1, -1, -1) if upward else range(size)
        for row in rows:
            for c in (col, col - 1):
                if reserved[row][c]:
                    continue
                modules[row][c] = index < len(bits) and bits[index] == 1
                index += 1
        upward = not upward
        col -= 2


# ── Masking ───────────────────────────────────────────────────────────────
#
# A QR is masked so the symbol has no large uniform areas and nothing that
# looks like a finder pattern. All eight are tried and the least-penalised
# wins, which is what the specification requires — picking a fixed mask
# produces codes that scan badly on some payloads and fine on others, which is
# a miserable bug to chase.

def _mask_condition(mask: int, row: int, col: int) -> bool:
    if mask == 0:
        return (row + col) % 2 == 0
    if mask == 1:
        return row % 2 == 0
    if mask == 2:
        return col % 3 == 0
    if mask == 3:
        return (row + col) % 3 == 0
    if mask == 4:
        return (row // 2 + col // 3) % 2 == 0
    if mask == 5:
        return (row * col) % 2 + (row * col) % 3 == 0
    if mask == 6:
        return ((row * col) % 2 + (row * col) % 3) % 2 == 0
    return ((row + col) % 2 + (row * col) % 3) % 2 == 0


def _penalty(modules) -> int:
    size = len(modules)
    score = 0

    # Rule 1: runs of five or more identical modules, in both directions.
    for line in list(modules) + [list(col) for col in zip(*modules, strict=True)]:
        run, previous = 1, line[0]
        for module in line[1:]:
            if module == previous:
                run += 1
            else:
                if run >= 5:
                    score += 3 + (run - 5)
                run, previous = 1, module
        if run >= 5:
            score += 3 + (run - 5)

    # Rule 2: every 2x2 block of one colour.
    for row in range(size - 1):
        for col in range(size - 1):
            block = (modules[row][col], modules[row][col + 1],
                     modules[row + 1][col], modules[row + 1][col + 1])
            if all(block) or not any(block):
                score += 3

    # Rule 3: the finder-like sequence, which a scanner could mistake for a
    # real finder pattern. The four light modules may fall outside the symbol —
    # the quiet zone is light — so each line is padded before the search.
    pattern_a = [True, False, True, True, True, False, True,
                 False, False, False, False]
    pattern_b = list(reversed(pattern_a))
    for line in list(modules) + [list(col) for col in zip(*modules, strict=True)]:
        padded = [False] * 4 + list(line) + [False] * 4
        for i in range(len(padded) - 10):
            window = padded[i:i + 11]
            if window == pattern_a or window == pattern_b:
                score += 40

    # Rule 4: deviation from an even split of dark and light. k is the
    # smallest integer for which the dark proportion sits inside
    # 50% ± 5(k+1), which is the specification's wording turned into
    # arithmetic that avoids floating point.
    dark = sum(sum(1 for m in row if m) for row in modules)
    total = size * size
    k = (abs(dark * 20 - total * 10) + total - 1) // total - 1
    score += max(0, k) * 10

    return score


def _format_bits(ecl: str, mask: int) -> int:
    """15-bit format information: BCH(15,5), then the specified XOR mask."""
    value = (_ECL_BITS[ecl] << 3) | mask
    remainder = value << 10
    for shift in range(14, 9, -1):
        if remainder & (1 << shift):
            remainder ^= 0x537 << (shift - 10)
    return ((value << 10) | remainder) ^ 0x5412


def _version_bits(version: int) -> int:
    """18-bit version information for version 7 and up: BCH(18,6)."""
    remainder = version << 12
    for shift in range(17, 11, -1):
        if remainder & (1 << shift):
            remainder ^= 0x1F25 << (shift - 12)
    return (version << 12) | remainder


def _apply_format(modules, ecl: str, mask: int, version: int) -> None:
    size = len(modules)
    bits = _format_bits(ecl, mask)

    # Most significant bit first. This is the one thing in the whole encoder
    # that cannot be reasoned out from the surrounding code — get the order
    # backwards and every function pattern is still perfect, the data is still
    # perfect, and no scanner will read the symbol, because the format tells it
    # the wrong mask. It cost an afternoon; the cross-check against a real
    # decoder in tests/test_qrcode.py is what found it.
    for i in range(15):
        on = (bits >> (14 - i)) & 1 == 1
        # Copy one: around the top-left finder, skipping the timing row/column.
        if i < 6:
            modules[8][i] = on
        elif i == 6:
            modules[8][7] = on
        elif i == 7:
            modules[8][8] = on
        elif i == 8:
            modules[7][8] = on
        else:
            modules[14 - i][8] = on

        # Copy two: split between the other two finders, so a damaged corner
        # does not take the format information with it.
        #
        # The halves overlap at bit 7 rather than meeting cleanly at 7/8.
        # Bit 7's place in the column is (size-8, 8) — which is the dark
        # module, overwritten below — so the bit has to appear again at the
        # start of the row half or it is simply lost. Writing the row half
        # from bit 8 leaves one reserved module blank, which is a single
        # wrong cell in the whole symbol and enough to make it unreadable.
        if i < 8:
            modules[size - 1 - i][8] = on
        if i >= 7:
            modules[8][size - 15 + i] = on

    # The dark module. Always set, always in the same place, and written last
    # because it sits on top of bit 7's position in the column half.
    modules[size - 8][8] = True

    if version >= 7:
        bits = _version_bits(version)
        for i in range(18):
            on = (bits >> i) & 1 == 1
            row, col = i // 3, i % 3
            modules[size - 11 + col][row] = on
            modules[row][size - 11 + col] = on


def _masked(modules, reserved, ecl: str, mask: int, version: int):
    """One masked candidate with its format information written in."""
    candidate = [row[:] for row in modules]
    for row in range(len(candidate)):
        for col in range(len(candidate)):
            if not reserved[row][col] and _mask_condition(mask, row, col):
                candidate[row][col] = not candidate[row][col]
    _apply_format(candidate, ecl, mask, version)
    return candidate


def _best_mask(modules, reserved, ecl: str, version: int):
    best, best_score = None, None
    for mask in range(8):
        candidate = _masked(modules, reserved, ecl, mask, version)
        score = _penalty(candidate)
        if best_score is None or score < best_score:
            best, best_score = candidate, score
    return best


# ── The one function callers need ─────────────────────────────────────────

def encode(text: str, ecl: str = Q, version: int = 0, mask: int = -1) -> list:
    """
    Encode `text` as a QR matrix. True is a dark module.

    Defaults to error level Q — 25% recoverable. That is higher than most
    libraries default to, and deliberate: this code is read off one screen by
    a camera held at whatever angle, in whatever light, and the payload is
    short enough that the extra correction costs nothing anyone will notice.

    `version` forces a size; 0 picks the smallest that fits. `mask` forces one
    of the eight patterns; -1 scores all eight and takes the best, which is
    what the specification asks for and what callers want. Forcing one is for
    tests that need a deterministic symbol to compare against.
    """
    if ecl not in _ECL_BITS:
        raise ValueError(f"error level must be one of L, M, Q, H, not {ecl!r}")

    payload = text.encode("utf-8")

    if version == 0:
        version = smallest_version(len(payload), ecl)
    elif not 1 <= version <= MAX_VERSION:
        raise ValueError(f"version must be 1..{MAX_VERSION}, not {version}")
    elif not _fits(len(payload), version, ecl):
        raise ValueError(
            f"{len(payload)} bytes does not fit in version {version} at "
            f"error level {ecl}"
        )

    codewords = _add_ec(_encode_data(payload, version, ecl), version, ecl)

    size = version * 4 + 17
    modules, reserved = _new_matrix(size)

    _place_finder(modules, reserved, 0, 0)
    _place_finder(modules, reserved, 0, size - 7)
    _place_finder(modules, reserved, size - 7, 0)
    _place_alignment(modules, reserved, version)
    _place_timing(modules, reserved)
    _reserve_format(reserved, version)
    reserved[size - 8][8] = True         # the dark module

    _place_data(modules, reserved, codewords)

    if mask == -1:
        return _best_mask(modules, reserved, ecl, version)
    if not 0 <= mask <= 7:
        raise ValueError(f"mask must be 0..7 or -1 to choose, not {mask}")
    return _masked(modules, reserved, ecl, mask, version)


def to_text(matrix, dark: str = "██", light: str = "  ", quiet: int = 2) -> str:
    """
    The matrix as text, for logs and terminals.

    Two characters per module because terminal cells are about twice as tall
    as they are wide; one character per module produces a squashed code that
    will not scan.
    """
    size = len(matrix)
    width = size + quiet * 2
    blank = light * width

    lines = [blank] * quiet
    for row in matrix:
        cells = "".join(dark if module else light for module in row)
        lines.append(light * quiet + cells + light * quiet)
    lines.extend([blank] * quiet)
    return "\n".join(lines)
