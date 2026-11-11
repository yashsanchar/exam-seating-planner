"""Computer Architecture: pack a seat's identity into ONE 32-bit word.

Layout (like a tiny instruction format):

    bit 31          24 23          16 15           8 7            0
        +--------------+--------------+--------------+--------------+
        |   room idx   |     row      |     column   |    flags     |
        +--------------+--------------+--------------+--------------+

Fields are extracted with shifts and masks, exactly like decoding an instruction.
Flags: bit0 = BLOCKED, bit1 = OCCUPIED, bit2 = RESERVED.
"""

from __future__ import annotations

from typing import NamedTuple

ROOM_SHIFT, ROW_SHIFT, COL_SHIFT = 24, 16, 8
FIELD_MASK = 0xFF

FLAG_BLOCKED = 0b001
FLAG_OCCUPIED = 0b010
FLAG_RESERVED = 0b100


class SeatWord(NamedTuple):
    room: int
    row: int
    col: int
    flags: int


def pack(room: int, row: int, col: int, flags: int = 0) -> int:
    """Build the 32-bit seat word. Every field must fit in 8 bits (0..255)."""
    for label, value in (("room", room), ("row", row), ("col", col), ("flags", flags)):
        if not 0 <= value <= FIELD_MASK:
            raise ValueError(f"{label} = {value} does not fit in 8 bits")
    return (room << ROOM_SHIFT) | (row << ROW_SHIFT) | (col << COL_SHIFT) | flags


def unpack(word: int) -> SeatWord:
    """Decode a seat word back into its four fields."""
    return SeatWord(
        (word >> ROOM_SHIFT) & FIELD_MASK,
        (word >> ROW_SHIFT) & FIELD_MASK,
        (word >> COL_SHIFT) & FIELD_MASK,
        word & FIELD_MASK,
    )


def has_flag(word: int, flag: int) -> bool:
    return bool(word & flag)


def set_flag(word: int, flag: int) -> int:
    return word | flag


def clear_flag(word: int, flag: int) -> int:
    return word & ~flag & 0xFFFFFFFF


def seat_code(room_index: int, row: int, col: int, flags: int = 0) -> str:
    """Hex string such as '0x01030500' used in exported files."""
    return f"0x{pack(room_index, row, col, flags):08X}"
