"""
The QR encoder.

An encoder is a bad thing to test by inspection. Every symbol looks plausible,
and the failure mode is not a wrong-looking picture — it is a picture that
looks perfect and that no phone will read. While this one was being written it
had two bugs of exactly that shape: the format bits were placed
least-significant first, and the byte-mode length indicator stayed 8 bits at
version 10 where the specification widens it to 16. Both produced symbols that
were pixel-perfect in every visible respect and completely unreadable.

So the real test is a round trip through a decoder that was written by someone
else: generate, render to an image, and read it back. `tests/` gets OpenCV and
segno as development dependencies for this; neither is imported by the app and
neither ships. When they are absent the round-trip tests skip and the
structural ones still run.
"""

import pytest

from core import qrcode as qr


try:
    import numpy as np
    import cv2 as _cv2
except ImportError:                     # pragma: no cover - depends on the box
    np = None
    _cv2 = None

try:
    import segno as _segno
except ImportError:                     # pragma: no cover
    _segno = None

needs_decoder = pytest.mark.skipif(
    _cv2 is None, reason="OpenCV is not installed; install the dev extras",
)
needs_segno = pytest.mark.skipif(
    _segno is None, reason="segno is not installed; install the dev extras",
)


def render(matrix, scale: int = 8, quiet: int = 4):
    """
    The matrix as a greyscale image, with the quiet zone a decoder needs.

    The quiet zone is not decoration. Four modules of white around the symbol
    is what the specification requires, and without it most decoders find
    nothing at all — which would make this whole file fail for a reason that
    has nothing to do with the encoder.
    """
    size = (len(matrix) + quiet * 2) * scale
    image = np.full((size, size), 255, np.uint8)
    for row, cells in enumerate(matrix):
        for col, dark in enumerate(cells):
            if dark:
                top, left = (row + quiet) * scale, (col + quiet) * scale
                image[top:top + scale, left:left + scale] = 0
    return image


def decode(matrix) -> str:
    got, _points, _straight = _cv2.QRCodeDetector().detectAndDecode(render(matrix))
    return got


# ── The round trip, which is the test that matters ────────────────────────

@needs_decoder
class TestARealDecoderCanReadIt:

    @pytest.mark.parametrize("ecl", ["L", "M", "Q", "H"])
    def test_a_link_url_survives_every_error_level(self, ecl):
        text = "https://protbot.app/l#1.ABCD2345"
        assert decode(qr.encode(text, ecl)) == text

    @pytest.mark.parametrize("version", range(1, qr.MAX_VERSION + 1))
    def test_every_version_decodes(self, version):
        # At capacity, so the padding path and the block splitting are both
        # exercised rather than only the short-payload case.
        for ecl in ("L", "M", "Q", "H"):
            room = qr.data_capacity(version, ecl) - (2 if version <= 9 else 3)
            text = "b" * room
            assert decode(qr.encode(text, ecl, version=version)) == text, \
                f"version {version}, level {ecl}"

    def test_version_10_decodes(self):
        # Its own test because version 10 is where the byte-mode length
        # indicator widens from 8 bits to 16. Everything below it kept working
        # while this was wrong.
        text = "c" * 240
        matrix = qr.encode(text, "L")
        assert len(matrix) == 10 * 4 + 17
        assert decode(matrix) == text

    def test_non_ascii_survives(self):
        text = "Zažółć gęślą jaźń — ćšđž"
        assert decode(qr.encode(text)) == text

    def test_a_short_payload_decodes_at_every_size_it_fits(self):
        # The same text forced into progressively larger symbols. Catches
        # anything that only works when the data happens to fill the space.
        text = "ProtBot"
        for version in range(1, qr.MAX_VERSION + 1):
            assert decode(qr.encode(text, "M", version=version)) == text, \
                f"version {version}"


# ── Structure, checked without a decoder ──────────────────────────────────

class TestTheTables:
    """
    A mistyped number in the block table produces a symbol that is the right
    size, looks right, and is unreadable. The specification fixes the total
    codewords per version, so every row can be checked against it.
    """

    TOTAL_CODEWORDS = {
        1: 26, 2: 44, 3: 70, 4: 100, 5: 134,
        6: 172, 7: 196, 8: 242, 9: 292, 10: 346,
    }

    @pytest.mark.parametrize("version", range(1, 11))
    @pytest.mark.parametrize("ecl", ["L", "M", "Q", "H"])
    def test_every_row_totals_correctly(self, version, ecl):
        ec_per_block, g1_blocks, g1_cw, g2_blocks, g2_cw = qr._BLOCKS[(version, ecl)]
        blocks = g1_blocks + g2_blocks
        total = g1_blocks * g1_cw + g2_blocks * g2_cw + blocks * ec_per_block
        assert total == self.TOTAL_CODEWORDS[version]

    def test_error_levels_are_ordered_by_capacity(self):
        # More correction means less room, at every single version. If this
        # ever fails, two rows have been swapped.
        for version in range(1, 11):
            caps = [qr.data_capacity(version, ecl) for ecl in ("L", "M", "Q", "H")]
            assert caps == sorted(caps, reverse=True), f"version {version}"

    def test_the_error_level_bits_are_the_specified_ones(self):
        # Not in quality order, which looks like a mistake and is not. Writing
        # a tidier mapping produces symbols that decode at the wrong level.
        assert qr._ECL_BITS == {"L": 0b01, "M": 0b00, "Q": 0b11, "H": 0b10}


class TestReedSolomon:

    def test_a_known_generator_polynomial(self):
        # The degree-10 generator, which every version-1-M symbol uses.
        assert qr._generator_poly(10) == [
            1, 216, 194, 159, 111, 199, 94, 95, 113, 157, 193,
        ]

    def test_a_known_codeword_block(self):
        # "HELLO" at version 1, level M, with the padding the specification
        # calls for. The expected error correction was produced by an
        # independent implementation.
        data = [64, 84, 132, 84, 196, 196, 240, 236, 17, 236, 17, 236, 17, 236, 17, 236]
        assert qr._ec_codewords(data, 10) == [
            35, 115, 35, 153, 236, 8, 201, 247, 55, 223,
        ]

    def test_error_correction_length_always_matches_the_table(self):
        for _key, row in qr._BLOCKS.items():
            ec_per_block = row[0]
            block = [7] * row[2]
            assert len(qr._ec_codewords(block, ec_per_block)) == ec_per_block


class TestFunctionPatterns:

    def test_the_size_follows_the_version(self):
        for version in range(1, 11):
            assert len(qr.encode("x", "L", version=version)) == version * 4 + 17

    def test_the_three_finder_patterns_are_where_they_belong(self):
        matrix = qr.encode("ProtBot", "M", version=2)
        size = len(matrix)
        for top, left in ((0, 0), (0, size - 7), (size - 7, 0)):
            # The 7x7 finder: dark border, light ring, dark 3x3 core.
            assert matrix[top][left] is True
            assert matrix[top + 1][left + 1] is False
            assert matrix[top + 3][left + 3] is True

    def test_the_fourth_corner_is_not_a_finder(self):
        # Three finders, not four — that asymmetry is how a scanner works out
        # which way up the symbol is.
        matrix = qr.encode("ProtBot", "M", version=2)
        size = len(matrix)
        corner = [matrix[size - 7 + r][size - 7 + c] for r in range(7) for c in range(7)]
        assert not all(corner[:7])

    def test_the_timing_patterns_alternate(self):
        matrix = qr.encode("ProtBot", "M", version=3)
        size = len(matrix)
        for i in range(8, size - 8):
            assert matrix[6][i] == (i % 2 == 0)
            assert matrix[i][6] == (i % 2 == 0)

    def test_the_dark_module_is_always_set(self):
        for version in range(1, 11):
            matrix = qr.encode("x", "Q", version=version)
            assert matrix[len(matrix) - 8][8] is True


class TestFormatInformation:
    """
    Placed most-significant bit first. Getting this backwards leaves every
    other part of the symbol perfect and makes the whole thing unreadable,
    because the format is what tells a scanner which mask was applied.
    """

    KNOWN = {
        ("L", 0): 0x77C4, ("L", 7): 0x6976,
        ("M", 0): 0x5412, ("M", 7): 0x4AA0,
        ("Q", 0): 0x355F, ("Q", 7): 0x2BED,
        ("H", 0): 0x1689, ("H", 7): 0x083B,
    }

    @pytest.mark.parametrize("key,expected", sorted(KNOWN.items()))
    def test_against_the_published_format_strings(self, key, expected):
        ecl, mask = key
        assert qr._format_bits(ecl, mask) == expected

    def test_version_information_matches_the_published_values(self):
        # Only versions 7 and up carry it.
        assert qr._version_bits(7) == 0x07C94
        assert qr._version_bits(10) == 0x0A4D3


class TestCapacityAndErrors:

    def test_the_length_indicator_widens_at_version_10(self):
        assert qr.count_bits(9) == 8
        assert qr.count_bits(10) == 16

    def test_it_picks_the_smallest_version_that_fits(self):
        assert qr.smallest_version(10, "L") == 1
        assert qr.smallest_version(20, "L") == 2
        # More correction pushes the same payload to a larger symbol.
        assert qr.smallest_version(30, "H") > qr.smallest_version(30, "L")

    def test_too_much_data_raises_rather_than_dropping_the_error_level(self):
        # Quietly giving a caller L when they asked for H would be worse than
        # an error they can see.
        with pytest.raises(ValueError, match="does not fit"):
            qr.encode("x" * 5000, "H")

    def test_an_unknown_error_level_raises(self):
        with pytest.raises(ValueError, match="L, M, Q, H"):
            qr.encode("x", "Z")

    def test_an_out_of_range_version_raises(self):
        with pytest.raises(ValueError, match="version must be"):
            qr.encode("x", "M", version=41)

    def test_an_empty_string_still_produces_a_symbol(self):
        matrix = qr.encode("", "M")
        assert len(matrix) == 21


class TestMasking:

    def test_all_eight_masks_are_defined(self):
        # Each must differ from the others somewhere in a 6x6 window.
        patterns = {
            tuple(qr._mask_condition(m, r, c) for r in range(6) for c in range(6))
            for m in range(8)
        }
        assert len(patterns) == 8

    def test_the_chosen_mask_is_the_lowest_penalty(self):
        # Rebuild every candidate and confirm encode() returned the best one.
        text, ecl, version = "ProtBot links devices", "Q", 3
        chosen = qr.encode(text, ecl, version=version)
        best = min(
            qr._penalty(_candidate(text, ecl, version, mask)) for mask in range(8)
        )
        assert qr._penalty(chosen) == best

    def test_a_large_uniform_area_scores_badly(self):
        # Rule 2 exists to break up solid blocks, which are what confuse a
        # scanner trying to find the module grid.
        solid = [[True] * 21 for _ in range(21)]
        mixed = [[(r + c) % 2 == 0 for c in range(21)] for r in range(21)]
        assert qr._penalty(solid) > qr._penalty(mixed)


def _candidate(text, ecl, version, mask):
    """One masked candidate, for the mask-selection test."""
    codewords = qr._add_ec(qr._encode_data(text.encode(), version, ecl), version, ecl)
    size = version * 4 + 17
    modules, reserved = qr._new_matrix(size)
    qr._place_finder(modules, reserved, 0, 0)
    qr._place_finder(modules, reserved, 0, size - 7)
    qr._place_finder(modules, reserved, size - 7, 0)
    qr._place_alignment(modules, reserved, version)
    qr._place_timing(modules, reserved)
    qr._reserve_format(reserved, version)
    reserved[size - 8][8] = True
    qr._place_data(modules, reserved, codewords)

    for row in range(size):
        for col in range(size):
            if not reserved[row][col] and qr._mask_condition(mask, row, col):
                modules[row][col] = not modules[row][col]
    qr._apply_format(modules, ecl, mask, version)
    return modules


@needs_segno
class TestAgainstAnIndependentEncoder:
    """
    segno as a second opinion, with the mask pinned on both sides.

    Two things legitimately differ between conforming encoders and neither
    affects whether a symbol reads:

      * **Padding.** At short payloads segno emits an extra zero byte before
        the pad bytes. Padding sits past the data a decoder stops at, so both
        symbols decode identically. The comparison therefore runs at capacity,
        where there is no room to differ.
      * **Mask choice.** The penalty rules are specified, but implementations
        interpret rule 3 differently at the symbol edge, so two correct
        encoders can pick different masks. Any mask is valid as long as the
        format bits declare it — which is why the mask is forced here rather
        than compared.

    What is left after pinning those two is everything that has exactly one
    right answer: the data codewords, Reed-Solomon, block interleaving, all
    the function patterns, and the format bits. If any of those were wrong,
    this fails.
    """

    @pytest.mark.parametrize("mask", range(8))
    def test_every_mask_matches_module_for_module(self, mask):
        text = "b" * (qr.data_capacity(3, "Q") - 2)
        mine = qr.encode(text, "Q", version=3, mask=mask)
        theirs = _segno.make(text, error="q", version=3, mode="byte",
                             mask=mask, boost_error=False)
        assert mine == [[bool(m) for m in row] for row in theirs.matrix]

    @pytest.mark.parametrize("version", [1, 2, 5, 7, 9, 10])
    @pytest.mark.parametrize("ecl", ["L", "M", "Q", "H"])
    def test_a_full_symbol_matches_at_every_version(self, version, ecl):
        room = qr.data_capacity(version, ecl) - (2 if version <= 9 else 3)
        text = "b" * room

        mine = qr.encode(text, ecl, version=version, mask=0)
        theirs = _segno.make(text, error=ecl.lower(), version=version,
                             mode="byte", mask=0, boost_error=False)
        assert mine == [[bool(m) for m in row] for row in theirs.matrix]

    def test_the_version_information_block_matches(self):
        # Versions 7 and up carry an 18-bit version block in two corners.
        # Nothing below version 7 exercises it at all.
        for version in (7, 8, 9, 10):
            room = qr.data_capacity(version, "M") - (2 if version <= 9 else 3)
            text = "d" * room
            mine = qr.encode(text, "M", version=version, mask=1)
            theirs = _segno.make(text, error="m", version=version,
                                 mode="byte", mask=1, boost_error=False)
            assert mine == [[bool(m) for m in row] for row in theirs.matrix], \
                f"version {version}"


class TestTextRendering:

    def test_it_draws_two_characters_per_module(self):
        # One character per module produces a symbol twice as tall as it is
        # wide in a terminal, which will not scan.
        matrix = qr.encode("x", "M", version=1)
        lines = qr.to_text(matrix, quiet=0).splitlines()
        assert len(lines) == 21
        assert all(len(line) == 42 for line in lines)

    def test_the_quiet_zone_is_included(self):
        matrix = qr.encode("x", "M", version=1)
        lines = qr.to_text(matrix, quiet=4).splitlines()
        assert len(lines) == 21 + 8
        assert lines[0].strip() == ""
