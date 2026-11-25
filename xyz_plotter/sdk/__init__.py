# SPDX-License-Identifier: MIT
"""PLC session layer of the XYZ plotter primitive.

This subpackage is private to ``primitive-hdu-cartesian-plotter-rbnx``.
Robonix consumers talk to the ``robonix/primitive/plotter/*`` contracts,
never to these modules.

The code was vendored from the upstream PLC SDK's ``protocol`` / ``client``
modules. The SDK's geometry layer (``image`` / ``trajectory`` / ``text``)
is deliberately not vendored here: it belongs to the skills and needs
numpy/Pillow.
"""

from .client import DEFAULT_PORT, ProtocolError, RobonixClient
from .protocol import (
    CMD_ACK,
    CMD_CLOSE,
    CMD_HOME,
    CMD_MOVE_LINEAR,
    CMD_PING,
    CMD_SET_PARAM,
    STATUS_BUSY,
    STATUS_ERROR,
    STATUS_OK,
    STATUS_UNKNOWN_CMD,
    Frame,
    build_frame,
    cmd_name,
    crc16_modbus,
    parse_frame,
    pack_f32,
    pack_f64,
    pack_move_linear,
    pack_set_param,
    unpack_ack,
    unpack_f32,
    unpack_f64,
)

__all__ = [
    "RobonixClient",
    "ProtocolError",
    "DEFAULT_PORT",
    "Frame",
    "build_frame",
    "parse_frame",
    "crc16_modbus",
    "cmd_name",
    "pack_f32",
    "pack_f64",
    "pack_move_linear",
    "pack_set_param",
    "unpack_ack",
    "unpack_f32",
    "unpack_f64",
    "CMD_PING",
    "CMD_MOVE_LINEAR",
    "CMD_HOME",
    "CMD_SET_PARAM",
    "CMD_CLOSE",
    "CMD_ACK",
    "STATUS_OK",
    "STATUS_BUSY",
    "STATUS_ERROR",
    "STATUS_UNKNOWN_CMD",
]