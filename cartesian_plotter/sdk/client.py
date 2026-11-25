# SPDX-License-Identifier: MIT
"""RobonixClient — TCP session layer for the XYZ plotter PLC.

Semantics that matter when swapping protocol or PLC vendor:

1. The PLC is the server (``SktTCPAccept`` on port 2000); this class is
   the client.
2. One frame in flight: send a frame, wait for the ACK with the same
   ``seq``, then send the next. ``MOVE_LINEAR`` and ``HOME`` ACK only
   after the motion reports Done, so they are synchronous.
3. Close with ``CMD_CLOSE(0x0A)`` and wait for its ACK before dropping
   the socket. Dropping the socket directly leaves the PLC stuck in the
   ``20 <-> 60`` state loop and it stops accepting new connections.
4. Motion parameters are global on the PLC: set them with
   ``SET_PARAM(0x04, 6 x f32)`` before moving. This client never applies
   them implicitly.
5. Only one motion command can be in flight, so the PLC's ``BufferMode``
   has no effect. Continuous interpolation needs a batch command.

The primitive is the only consumer; skills talk to it over gRPC.
"""

from __future__ import annotations

import math
import socket
import sys
import time
from collections.abc import Callable, Iterable

from . import protocol as proto

DEFAULT_PORT = 2000

# Conservative speed (mm/s) used to estimate the per-point ACK timeout.
_TIMEOUT_SPEED_MM_S = 5.0


class ProtocolError(Exception):
    """Protocol-level failure (bad frame / CRC error / non-OK ACK)."""


class RobonixClient:
    def __init__(self, host: str, port: int = DEFAULT_PORT, timeout: float = 30.0):
        self.host = host
        self.port = port
        self.timeout = timeout
        self._sock: socket.socket | None = None
        self._seq = 0
        self._buf = b""

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------
    def connect(self) -> None:
        sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        sock.settimeout(self.timeout)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self._sock = sock
        self._buf = b""

    def close(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            finally:
                self._sock = None

    def __enter__(self) -> "RobonixClient":
        self.connect()
        return self

    def __exit__(self, *exc) -> None:
        # Graceful close: CMD_CLOSE lets the PLC run 50 -> 90 -> 0 -> 10.
        # A bare socket close leaves SktTCPRcv erroring while
        # SktGetTCPStatus still reports a valid link, so the state machine
        # loops in 20 <-> 60 and never accepts again.
        try:
            self.close_session()
        except Exception as e:  # noqa: BLE001 - teardown must not raise
            print(
                "[WARN] session not closed cleanly (%s: %s); socket dropped. "
                "If the PLC stops accepting connections, set Tcp.TCP_State = 0 "
                "in the CASS project." % (type(e).__name__, e),
                file=sys.stderr,
            )
        finally:
            self.close()

    @property
    def connected(self) -> bool:
        return self._sock is not None

    # ------------------------------------------------------------------
    # Low-level send / receive
    # ------------------------------------------------------------------
    def _set_timeout(self, seconds: float) -> None:
        """Temporarily change the receive timeout (long moves need longer)."""
        if self._sock is not None:
            self._sock.settimeout(max(0.5, float(seconds)))

    def _next_seq(self) -> int:
        seq = self._seq
        self._seq = (self._seq + 1) & 0xFF
        return seq

    def _send(self, cmd: int, payload: bytes = b"") -> int:
        if self._sock is None:
            raise RuntimeError("not connected; call connect() first")
        seq = self._next_seq()
        frame = proto.build_frame(cmd, seq, payload)
        self._sock.sendall(frame)
        return seq

    def _recv_frame(self) -> proto.Frame:
        if self._sock is None:
            raise RuntimeError("not connected")
        while True:
            try:
                frame, consumed = proto.parse_frame(self._buf)
            except ValueError as exc:
                # A corrupt stream cannot be trusted; surface it as a
                # protocol error so the caller can close and reconnect.
                raise ProtocolError(str(exc)) from exc
            if frame is not None:
                self._buf = self._buf[consumed:]
                return frame
            try:
                chunk = self._sock.recv(4096)
            except socket.timeout:
                raise TimeoutError(
                    "timed out waiting for PLC reply (socket timeout %.1fs). "
                    "MOVE_LINEAR is synchronous; the PLC ACKs only after the "
                    "move completes. Raise timeout for long moves."
                    % (self._sock.gettimeout() or 0)
                ) from None
            if not chunk:
                raise ConnectionError("PLC closed the connection")
            self._buf += chunk

    def _request(self, cmd: int, payload: bytes = b"") -> proto.Frame:
        """Send one frame and wait for the ACK carrying the same seq."""
        seq = self._send(cmd, payload)
        while True:
            frame = self._recv_frame()
            if frame.cmd != proto.CMD_ACK:
                continue
            if frame.seq != seq:
                continue
            return frame

    def _expect_ack_ok(
        self, cmd: int, payload: bytes = b"", what: str = "command"
    ) -> tuple[int, int, int]:
        ack = self._request(cmd, payload)
        status, err, busy = proto.unpack_ack(ack.payload)
        if status != proto.STATUS_OK:
            raise ProtocolError(
                "%s failed: status=%d err=0x%04X busy=%d"
                % (what, status, err, busy)
            )
        return status, err, busy

    # ------------------------------------------------------------------
    # High-level commands
    # ------------------------------------------------------------------
    def ping(self) -> bool:
        try:
            self._expect_ack_ok(proto.CMD_PING, what="PING")
            return True
        except (ProtocolError, TimeoutError, ConnectionError):
            return False

    def move_linear(self, x: float, y: float, z: float) -> None:
        """World-coordinate linear move; speed comes from SET_PARAM."""
        self._expect_ack_ok(
            proto.CMD_MOVE_LINEAR,
            proto.pack_move_linear(x, y, z),
            what="MOVE_LINEAR",
        )

    def set_param(
        self, vel: float, acc: float, dec: float, jerk: float, z_up: float, z_down: float
    ) -> None:
        """CMD_SET_PARAM(0x04): vel, acc, dec, jerk, z_up, z_down (6 x f32).

        Parameters are global on the PLC until the next SET_PARAM or a
        PLC restart. z_up / z_down do not affect motion on the current
        PLC: z is already encoded in every MOVE_LINEAR coordinate.
        """
        self._expect_ack_ok(
            proto.CMD_SET_PARAM,
            proto.pack_set_param(vel, acc, dec, jerk, z_up, z_down),
            what="SET_PARAM",
        )

    def home(self) -> None:
        self._expect_ack_ok(proto.CMD_HOME, what="HOME")

    def close_session(self) -> None:
        """Request CMD_CLOSE(0x0A) and drop the link after the ACK.

        The PLC answers the CLOSE only after it leaves its busy state, so
        this waits up to 3 seconds and then fails loudly. Skipping this
        step can wedge the PLC's connection state machine.
        """
        if self._sock is None:
            return
        old_timeout = self.timeout
        self._set_timeout(3.0)
        try:
            self._expect_ack_ok(proto.CMD_CLOSE, what="CLOSE")
        except TimeoutError:
            raise TimeoutError(
                "PLC did not acknowledge CLOSE within 3s "
                "(busy moving, or the link is already gone)"
            ) from None
        finally:
            self._set_timeout(old_timeout)
            self.close()

    # ------------------------------------------------------------------
    # Drawing
    # ------------------------------------------------------------------
    def draw_waypoints(
        self,
        points: Iterable[tuple[float, float, float]],
        on_progress: Callable[[int, int, tuple[float, float, float]], None] | None = None,
    ) -> None:
        """Send MOVE_LINEAR for every point, one synchronous ACK at a time.

        ``points`` is a sequence of ``(x, y, z)`` tuples with pen state
        already encoded in ``z``. The per-point timeout is estimated from
        the distance at a conservative 5 mm/s, with the constructor's
        ``timeout`` as the floor. The first point always gets 30 s.
        """
        pts = list(points)
        total = len(pts)
        prev: tuple[float, float, float] | None = None
        for i, (x, y, z) in enumerate(pts):
            if prev is None:
                self._set_timeout(max(self.timeout, 30.0))
            else:
                dist = math.dist(prev, (x, y, z))
                self._set_timeout(
                    min(300.0, max(self.timeout, 2.0 + dist / _TIMEOUT_SPEED_MM_S))
                )
            self.move_linear(x, y, z)
            prev = (x, y, z)
            if on_progress is not None:
                on_progress(i + 1, total, (x, y, z))