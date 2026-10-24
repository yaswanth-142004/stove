"""The subset of the CMF Watch 3 Pro BLE protocol used by Stove.

Stove implements its own transport for music controls and pairing. Protocol
field values are documented by the community Watch Pro 2 specification.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import re
import struct
import time
import zlib
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Callable

from bleak import BleakClient, BleakScanner
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


Op = tuple[int, int]
ops = SimpleNamespace(
    AUTH_PAIR_REQUEST=(0xFFFF, 0x8047),
    AUTH_PAIR_REPLY=(0xFFFF, 0x0048),
    AUTH_PHONE_NAME=(0xFFFF, 0x8049),
    AUTH_WATCH_MAC=(0xFFFF, 0x0049),
    AUTH_NONCE_REQUEST=(0xFFFF, 0x804B),
    AUTH_NONCE_REPLY=(0xFFFF, 0x004C),
    AUTH_CONFIRM_REQUEST=(0xFFFF, 0x804D),
    AUTH_CONFIRM_REPLY=(0xFFFF, 0x0004),
    AUTH_FAILED=(0xFFFF, 0xA061),
    TIME=(0xFFFF, 0x8004),
    MUSIC_INFO_SET=(0xFFFF, 0x905C),
    MUSIC_BUTTON=(0xFFFF, 0xA05D),
    FIND_PHONE=(0x005B, 0x0001),
    RECORDING_ANNOUNCE=(0xFFFF, 0xA097),
    RECORDING_ACCEPT=(0xFFFF, 0x9097),
    RECORDING_READ=(0xFFFF, 0x9098),
    RECORDING_DATA=(0xFFFF, 0xA098),
    RECORDING_END=(0xFFFF, 0x9099),
)
_PLAIN_OPS = {ops.AUTH_PAIR_REQUEST, ops.AUTH_PAIR_REPLY, ops.RECORDING_DATA}
_IV = bytes.fromhex("5051525354555657606162636465665A")
_HEADER = struct.Struct(">BHHHHH")
_COMMAND_WRITE = "0000fff2-0000-1000-8000-00805f9b34fb"
_COMMAND_NOTIFY = "0000fff1-0000-1000-8000-00805f9b34fb"
_SHELL_WRITE = "77d4ff01-2fe2-2334-0d35-9ccd078f529c"
_SHELL_NOTIFY = "77d4ff02-2fe2-2334-0d35-9ccd078f529c"


def _digest(*parts: bytes) -> bytes:
    return hashlib.sha256(b"".join(parts)).digest()


def _crc(data: bytes) -> bytes:
    return (zlib.crc32(data) & 0xFFFFFFFF).to_bytes(4, "little")


def _seal(key: bytes, data: bytes) -> bytes:
    pad = padding.PKCS7(128).padder()
    data = pad.update(data) + pad.finalize()
    cipher = Cipher(algorithms.AES(key), modes.CBC(_IV)).encryptor()
    return cipher.update(data) + cipher.finalize()


def _unseal(key: bytes, data: bytes) -> bytes:
    cipher = Cipher(algorithms.AES(key), modes.CBC(_IV)).decryptor()
    data = cipher.update(data) + cipher.finalize()
    unpad = padding.PKCS7(128).unpadder()
    return unpad.update(data) + unpad.finalize()


class pl:
    MUSIC_STOPPED = 0
    MUSIC_PAUSED = 1
    MUSIC_PLAYING = 2
    POLL = b"\xa5"

    @staticmethod
    def music_info(title: str, detail: str, state: int = 2,
                   volume: int = 8, volume_max: int = 16) -> bytes:
        def field(value: str) -> bytes:
            return value.encode("utf-8")[:64].ljust(64, b"\x00")
        return bytes((state, volume, volume_max)) + field(title) + field(detail)

    @staticmethod
    def time_sync() -> bytes:
        now = time.time()
        return struct.pack(">ii", int(now), time.localtime(now).tm_gmtoff * 1000)


@dataclass(frozen=True)
class Message:
    op: Op
    payload: bytes


class FrameReader:
    def __init__(self) -> None:
        self.key: bytes | None = None
        self.buffer = bytearray()
        self.parts: dict[Op, list[bytes]] = {}

    def feed(self, data: bytes) -> list[Message]:
        self.buffer.extend(data)
        result: list[Message] = []
        while True:
            start = self.buffer.find(0xF5)
            if start < 0:
                self.buffer.clear()
                break
            del self.buffer[:start]
            if len(self.buffer) < _HEADER.size:
                break
            _, advertised, cmd1, count, index, cmd2 = _HEADER.unpack_from(self.buffer)
            op = (cmd1, cmd2)
            encrypted = self.key is not None and op not in _PLAIN_OPS
            if len(self.buffer) < _HEADER.size + advertised:
                break
            body = bytes(self.buffer[_HEADER.size:_HEADER.size + advertised])
            del self.buffer[:_HEADER.size + advertised]
            if encrypted:
                assert self.key is not None
                opened = _unseal(self.key, body)
                if len(opened) < 4 or opened[-4:] != _crc(opened[:-4]):
                    raise ValueError("Watch frame checksum failed")
                chunk = opened[:-4]
            elif op == ops.RECORDING_DATA:
                chunk = body[:-4] if len(body) >= 4 else body
            else:
                chunk = body
            if count <= 1:
                result.append(Message(op, chunk))
                continue
            if index == 1:
                self.parts[op] = []
            self.parts.setdefault(op, []).append(chunk)
            if index == count:
                result.append(Message(op, b"".join(self.parts.pop(op))))
        return result


async def scan(timeout: float = 8.0):
    found = await BleakScanner.discover(timeout=timeout)
    return [device for device in found if "Watch 3 Pro" in (device.name or "")]


class BleTransport:
    def __init__(self, address: str):
        self.address = address
        self._client: BleakClient | None = None
        self.on_command: Callable[[bytes], None] | None = None
        self.on_shell: Callable[[bytes], None] | None = None

    @property
    def mtu(self) -> int:
        return self._client.mtu_size if self._client else 23

    async def connect(self) -> None:
        self._client = BleakClient(self.address)
        await self._client.connect()
        services = {c.uuid for service in self._client.services for c in service.characteristics}
        if _COMMAND_NOTIFY not in services or _COMMAND_WRITE not in services:
            raise RuntimeError("Watch command service is unavailable")
        await self._client.start_notify(_COMMAND_NOTIFY,
                                        lambda _, data: self.on_command and self.on_command(bytes(data)))
        if _SHELL_NOTIFY in services:
            await self._client.start_notify(_SHELL_NOTIFY,
                                            lambda _, data: self.on_shell and self.on_shell(bytes(data)))

    async def disconnect(self) -> None:
        if self._client:
            await self._client.disconnect()
            self._client = None

    async def write(self, data: bytes, shell: bool = False) -> None:
        if not self._client:
            raise RuntimeError("Watch is disconnected")
        await self._client.write_gatt_char(_SHELL_WRITE if shell else _COMMAND_WRITE,
                                           data, response=False)


class Session:
    def __init__(self, transport: BleTransport):
        self.transport = transport
        self.reader = FrameReader()
        self.waiters: list[tuple[set[Op], asyncio.Future[Message]]] = []
        self.listeners: list[Callable[[Message], None]] = []
        self.shell_waiter: asyncio.Future[str] | None = None
        self.shell_text = ""
        transport.on_command = self._received
        transport.on_shell = self._shell_received

    def on_message(self, handler: Callable[[Message], None]) -> None:
        self.listeners.append(handler)

    def _received(self, data: bytes) -> None:
        try:
            messages = self.reader.feed(data)
        except (ValueError, AssertionError):
            return
        for message in messages:
            for wanted, future in list(self.waiters):
                if message.op in wanted and not future.done():
                    future.set_result(message)
                    self.waiters.remove((wanted, future))
                    break
            else:
                for listener in self.listeners:
                    listener(message)

    def _shell_received(self, data: bytes) -> None:
        self.shell_text += data.decode("utf-8", "replace")
        if self.shell_waiter and not self.shell_waiter.done() and re.search(r"(OK|ERROR)\s*$", self.shell_text):
            self.shell_waiter.set_result(self.shell_text)

    async def send(self, op: Op, payload: bytes = b"") -> None:
        key = self.reader.key if op not in _PLAIN_OPS else None
        max_write = self.transport.mtu - 3
        if key:
            capacity = ((max_write - _HEADER.size) // 16) * 16 - 5
        else:
            capacity = max_write - _HEADER.size - 6
        if capacity < 1:
            raise RuntimeError("Watch BLE MTU is too small")
        pieces = [payload[i:i + capacity] for i in range(0, len(payload), capacity)] or [b""]
        for number, piece in enumerate(pieces, 1):
            body = piece + _crc(piece)
            if key:
                body = _seal(key, body)
            header = _HEADER.pack(0xF5, len(body), op[0], len(pieces), number, op[1])
            await self.transport.write(header + body)

    async def request(self, op: Op, payload: bytes, *replies: Op,
                      timeout: float = 8.0) -> Message:
        future = asyncio.get_running_loop().create_future()
        entry = (set(replies), future)
        self.waiters.append(entry)
        try:
            await self.send(op, payload)
            return await asyncio.wait_for(future, timeout)
        finally:
            if entry in self.waiters:
                self.waiters.remove(entry)

    async def shell(self, command: str) -> str:
        self.shell_text = ""
        self.shell_waiter = asyncio.get_running_loop().create_future()
        try:
            await self.transport.write((command + "\r\n").encode(), shell=True)
            return await asyncio.wait_for(self.shell_waiter, 8.0)
        finally:
            self.shell_waiter = None

    async def pair(self) -> bytes:
        reply = await self.shell("AT GETSECRET")
        match = re.search(r"GETSECRET:([0-9A-Fa-f]{32})", reply)
        if not match:
            raise RuntimeError("Watch did not provide its pairing secret")
        secret = bytes.fromhex(match.group(1))
        first = os.urandom(16)
        response = await self.request(ops.AUTH_PAIR_REQUEST,
                                      first + _digest(first, secret),
                                      ops.AUTH_PAIR_REPLY, ops.AUTH_FAILED)
        if response.op == ops.AUTH_FAILED or len(response.payload) < 48:
            raise RuntimeError("Watch declined pairing")
        second = response.payload[:16]
        if response.payload[16:48] != _digest(second, secret):
            raise RuntimeError("Watch pairing signature did not match")
        authkey = _digest(first, second, secret)[:16]
        await self.login(authkey, hello_timeout=60.0)
        return authkey

    async def login(self, authkey: bytes, hello_timeout: float = 16.0) -> None:
        self.reader.key = authkey
        hello = await self.request(ops.AUTH_PHONE_NAME,
                                   b"\xa5CMF Watch 3 Pro",
                                   ops.AUTH_WATCH_MAC, ops.AUTH_FAILED,
                                   timeout=hello_timeout)
        if hello.op == ops.AUTH_FAILED:
            raise RuntimeError("Watch declined saved pairing key")
        challenge = await self.request(ops.AUTH_NONCE_REQUEST, pl.POLL,
                                       ops.AUTH_NONCE_REPLY, ops.AUTH_FAILED)
        if challenge.op == ops.AUTH_FAILED:
            raise RuntimeError("Watch declined authentication")
        self.reader.key = _digest(challenge.payload, authkey)[:16]
        confirmed = await self.request(ops.AUTH_CONFIRM_REQUEST, pl.POLL,
                                       ops.AUTH_CONFIRM_REPLY, ops.AUTH_FAILED)
        if confirmed.op == ops.AUTH_FAILED:
            raise RuntimeError("Watch session confirmation failed")
        await self.send(ops.TIME, pl.time_sync())

    async def set_music(self, title: str, detail: str, state: int = 2) -> None:
        await self.send(ops.MUSIC_INFO_SET, pl.music_info(title, detail, state))

    async def reject_recording(self) -> None:
        await self.send(ops.RECORDING_ACCEPT, b"\x01")

    async def receive_recording(self, announcement_payload: bytes,
                                on_progress: Callable[[int, int], None] | None = None) -> tuple[str, bytes]:
        if len(announcement_payload) < 6 or announcement_payload[0] not in (0, 2):
            raise RuntimeError(f"Unexpected recording announcement format (state={announcement_payload[0] if announcement_payload else 'empty'})")
        total = int.from_bytes(announcement_payload[1:5], "little")
        filename = announcement_payload[5:].decode("utf-8", "replace").strip("\x00")
        if not 0 < total <= 64 * 1024 * 1024:
            raise RuntimeError(f"Invalid recording size: {total}")

        # Send ACCEPT (0x02 = ready to receive). The watch does not ACK this frame.
        await self.send(ops.RECORDING_ACCEPT, b"\x02")
        await asyncio.sleep(0.05)

        chunks = bytearray()
        while len(chunks) < total:
            amount = min(2048, total - len(chunks))
            request = len(chunks).to_bytes(4, "little") + amount.to_bytes(4, "little")
            response = None
            for attempt in range(3):
                try:
                    response = await self.request(ops.RECORDING_READ, request, ops.RECORDING_DATA, timeout=4.0)
                    if response.payload:
                        break
                except asyncio.TimeoutError:
                    if attempt == 2:
                        raise
                    await asyncio.sleep(0.05)
            if not response or not response.payload:
                raise RuntimeError("Empty recording chunk received")
            chunks.extend(response.payload)
            if on_progress:
                on_progress(len(chunks), total)

        # Send END status (0x00 = success)
        await self.send(ops.RECORDING_END, b"\x00")
        return filename, bytes(chunks)

