# SPDX-License-Identifier: MIT
"""Frame and payload tests for the vendored PLC protocol layer."""

from __future__ import annotations

import struct

import pytest

from xyz_plotter.sdk import protocol as p


def test_ping_frame_matches_documented_layout():
    data = p.build_frame(p.CMD_PING, seq=1)
    assert data[:2] == b"\xaa\x55"
    cmd, length, seq = struct.unpack_from("<BHB", data, 2)
    assert cmd == p.CMD_PING
    assert length == 0
    assert seq == 1
    assert len(data) == p.FRAME_OVERHEAD


def test_frame_roundtrip():
    data = p.build_frame(p.CMD_MOVE_LINEAR, 42, b"abc")
    frame, consumed = p.parse_frame(data)
    assert frame is not None
    assert consumed == len(data)
    assert frame.cmd == p.CMD_MOVE_LINEAR
    assert frame.seq == 42
    assert frame.payload == b"abc"


def test_half_packet_waits_for_more_bytes():
    data = p.build_frame(p.CMD_HOME, 7)
    frame, consumed = p.parse_frame(data[:5])
    assert frame is None
    assert consumed == 0


def test_sticky_packets_are_split():
    first = p.build_frame(p.CMD_PING, 1)
    second = p.build_frame(p.CMD_HOME, 2)
    frame, consumed = p.parse_frame(first + second)
    assert frame is not None and frame.seq == 1
    assert consumed == len(first)
    frame, consumed = p.parse_frame((first + second)[consumed:])
    assert frame is not None and frame.cmd == p.CMD_HOME
    assert frame.seq == 2


def test_bad_sof_is_rejected():
    data = bytearray(p.build_frame(p.CMD_PING, 1))
    data[0] = 0x00
    with pytest.raises(ValueError, match="SOF"):
        p.parse_frame(bytes(data))


def test_crc_detects_corruption():
    data = bytearray(p.build_frame(p.CMD_MOVE_LINEAR, 1, p.pack_move_linear(1, 2, 3)))
    data[-1] ^= 0xFF
    with pytest.raises(ValueError, match="CRC"):
        p.parse_frame(bytes(data))


def test_move_payload_is_three_f64():
    payload = p.pack_move_linear(10.0, 20.0, -46.0)
    assert len(payload) == 24
    assert p.unpack_f64(payload, 3) == pytest.approx((10.0, 20.0, -46.0))


def test_set_param_payload_is_six_f32():
    payload = p.pack_set_param(20.0, 300.0, 300.0, 3000.0, -46.0, -50.0)
    assert len(payload) == 24
    assert p.unpack_f32(payload, 6) == pytest.approx(
        (20.0, 300.0, 300.0, 3000.0, -46.0, -50.0)
    )


def test_ack_payload():
    status, err, busy = p.unpack_ack(struct.pack("<BHB", p.STATUS_ERROR, 2001, 1))
    assert status == p.STATUS_ERROR
    assert err == 2001
    assert busy == 1


def test_short_ack_is_rejected():
    with pytest.raises(ValueError):
        p.unpack_ack(b"\x00\x00")