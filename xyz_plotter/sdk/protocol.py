# SPDX-License-Identifier: MIT
"""Robonix XYZ plotter wire protocol — vendored from the upstream SDK.

Frame format (little-endian)::

    offset  size  field
    0       2     SOF   = 0xAA 0x55
    2       1     CMD   command code (U8)
    3       2     LEN   payload length (U16)
    5       1     SEQ   sequence number (U8, echoed by the ACK)
    6       LEN   PAYLOAD
    6+LEN   2     CRC16-Modbus over CMD..PAYLOAD

Implemented commands (matching the PLC's ``tcp_test.XML``):

    0x00 PING / 0x01 MOVE_LINEAR / 0x03 HOME / 0x04 SET_PARAM / 0x0A CLOSE
    0x80 ACK (status U8, err U16, busy U8)

MOVE_LINEAR carries ``x, y, z = 3 x f64``; SET_PARAM carries
``vel, acc, dec, jerk, z_up, z_down = 6 x f32``.

This module is transport-only: it knows bytes, not sockets and not
Robonix. The deployment-side protocol summary lives in
``docs/PLC_PROTOCOL.md`` of the robot repository.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Frame constants
# ---------------------------------------------------------------------------
SOF = b"\xaa\x55"
HEADER_LEN = 6
CRC_LEN = 2
FRAME_OVERHEAD = HEADER_LEN + CRC_LEN

# Command codes
CMD_PING = 0x00
CMD_MOVE_LINEAR = 0x01
CMD_HOME = 0x03
CMD_SET_PARAM = 0x04
CMD_CLOSE = 0x0A
CMD_ACK = 0x80

# ACK status
STATUS_OK = 0
STATUS_BUSY = 1
STATUS_ERROR = 2
STATUS_UNKNOWN_CMD = 3

_CMD_NAMES = {
    CMD_PING: "PING",
    CMD_MOVE_LINEAR: "MOVE_LINEAR",
    CMD_HOME: "HOME",
    CMD_SET_PARAM: "SET_PARAM",
    CMD_CLOSE: "CLOSE",
    CMD_ACK: "ACK",
}


def cmd_name(cmd: int) -> str:
    return _CMD_NAMES.get(cmd, "UNKNOWN(0x%02X)" % cmd)


# ---------------------------------------------------------------------------
# CRC16-Modbus
# ---------------------------------------------------------------------------
_CRC_TABLE = None


def _make_crc_table() -> list[int]:
    table = []
    for i in range(256):
        crc = i
        for _ in range(8):
            if crc & 0x0001:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
        table.append(crc)
    return table


def crc16_modbus(data: bytes) -> int:
    """CRC16-Modbus (poly 0x8005, reflected), returned as an unsigned 16-bit int."""
    global _CRC_TABLE
    if _CRC_TABLE is None:
        _CRC_TABLE = _make_crc_table()
    crc = 0xFFFF
    for byte in data:
        crc = (crc >> 8) ^ _CRC_TABLE[(crc ^ byte) & 0xFF]
    return crc


# ---------------------------------------------------------------------------
# Frame construction / parsing
# ---------------------------------------------------------------------------
@dataclass
class Frame:
    cmd: int
    seq: int
    payload: bytes

    @property
    def payload_len(self) -> int:
        return len(self.payload)


def build_frame(cmd: int, seq: int, payload: bytes = b"") -> bytes:
    """Wrap one command in a complete frame (SOF + header + payload + CRC)."""
    if not 0 <= cmd <= 0xFF:
        raise ValueError("cmd out of range: %r" % cmd)
    if not 0 <= seq <= 0xFF:
        raise ValueError("seq out of range: %r" % seq)
    if len(payload) > 0xFFFF:
        raise ValueError("payload too long: %d" % len(payload))

    head = struct.pack("<BHB", cmd, len(payload), seq)
    crc = crc16_modbus(head + payload)
    return SOF + head + payload + struct.pack("<H", crc)


def parse_frame(buf: bytes) -> tuple[Frame | None, int]:
    """Try to parse one frame from ``buf``.

    Returns ``(frame, consumed)``. An incomplete buffer returns
    ``(None, 0)``; the caller should read more bytes. A wrong SOF or a
    CRC mismatch raises :class:`ValueError` (the stream is corrupt).
    """
    if len(buf) < FRAME_OVERHEAD:
        return None, 0

    if buf[:2] != SOF:
        raise ValueError("bad SOF: %s" % buf[:2].hex())

    cmd, length, seq = struct.unpack_from("<BHB", buf, 2)
    total = FRAME_OVERHEAD + length
    if len(buf) < total:
        return None, 0

    head = buf[2:6]
    payload = buf[6 : 6 + length]
    crc_rx = struct.unpack_from("<H", buf, 6 + length)[0]
    crc_calc = crc16_modbus(head + payload)
    if crc_rx != crc_calc:
        raise ValueError(
            "CRC mismatch: received 0x%04X, computed 0x%04X" % (crc_rx, crc_calc)
        )

    return Frame(cmd=cmd, seq=seq, payload=payload), total


# ---------------------------------------------------------------------------
# Payload packing / unpacking
# ---------------------------------------------------------------------------
def pack_f32(*values: float) -> bytes:
    return struct.pack("<%df" % len(values), *values)


def unpack_f32(data: bytes, count: int) -> tuple[float, ...]:
    return struct.unpack("<%df" % count, data[: 4 * count])


def pack_f64(*values: float) -> bytes:
    return struct.pack("<%dd" % len(values), *values)


def unpack_f64(data: bytes, count: int) -> tuple[float, ...]:
    return struct.unpack("<%dd" % count, data[: 8 * count])


def pack_move_linear(x: float, y: float, z: float) -> bytes:
    """MOVE_LINEAR payload: x, y, z (3 x f64, PLC ``LREAL``)."""
    return pack_f64(x, y, z)


def pack_set_param(
    vel: float, acc: float, dec: float, jerk: float, z_up: float, z_down: float
) -> bytes:
    """SET_PARAM payload: vel, acc, dec, jerk, z_up, z_down (6 x f32)."""
    return pack_f32(vel, acc, dec, jerk, z_up, z_down)


def unpack_ack(payload: bytes) -> tuple[int, int, int]:
    """ACK payload: status(U8), err(U16), busy(U8)."""
    if len(payload) < 4:
        raise ValueError("ACK payload too short: %d" % len(payload))
    status, err, busy = struct.unpack_from("<BHB", payload, 0)
    return status, err, busy