#!/usr/bin/env python3
"""CMF Watch 3 Pro music controls as a local Mac remote."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import shutil
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from socketserver import TCPServer
from pathlib import Path
from urllib.parse import urlparse

from mac_actions import MacActions, PERMISSION_NAME
from watch import BleTransport, Session, ops, pl, scan

ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
APP_DATA = Path(os.environ.get("STOVE_DATA_DIR", Path.home() / "Library/Application Support/Stove"))
TRACKS_PATH = APP_DATA / "tracks.json"
WATCH_CODES = {b"\x03\x01": "up", b"\x03\x00": "down",
               b"\x01\x00": "pause", b"\x01\x01": "play",
               b"\x02\x01": "next", b"\x02\x00": "previous"}
KINDS = {"scroll_current", "brightness", "switch_apps", "system_volume",
         "scroll_horizontal", "slideshow", "scroll_app"}


def load_tracks() -> list[dict]:
    if not TRACKS_PATH.exists():
        APP_DATA.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / "tracks.json", TRACKS_PATH)
    tracks = json.loads(TRACKS_PATH.read_text(encoding="utf-8"))
    if not isinstance(tracks, list) or len(tracks) < 3 or len(tracks) > 20:
        raise ValueError("tracks.json must contain 3–20 tracks")
    ids = set()
    for track in tracks:
        if not isinstance(track, dict) or track.get("kind") not in KINDS:
            raise ValueError("Invalid track in tracks.json")
        if not isinstance(track.get("id"), str) or track["id"] in ids:
            raise ValueError("Track IDs must be unique strings")
        if not isinstance(track.get("title"), str) or not 1 <= len(track["title"]) <= 40:
            raise ValueError("Track titles must be 1–40 characters")
        if track["kind"] == "scroll_app" and not re.fullmatch(r"[A-Za-z0-9._-]{3,160}", str(track.get("bundle_id", ""))):
            raise ValueError("App tracks need a bundle ID")
        ids.add(track["id"])
    return tracks


def save_tracks(tracks: list[dict]) -> None:
    temporary = TRACKS_PATH.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(tracks, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, TRACKS_PATH)


def save_key(path: Path, key: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="ascii") as handle:
        handle.write(key.hex() + "\n")
    os.replace(temporary, path)


class State:
    def __init__(self, tracks: list[dict]) -> None:
        self.lock = threading.Lock()
        self.tracks = tracks
        self.index = 0
        self.playing = True
        self.feedback = 8
        self.status = "starting"
        self.detail = "Starting"
        self.active_app = "Unknown"
        self.app_cursor_bundle = ""
        self.app_cursor_name = ""
        self.brightness = None
        self.system_volume = None
        self.scroll_permission = False
        self.apps: list[dict] = []
        self.last_action = "Ready"
        self.error = ""
        self.counts = {name: 0 for name in ("up", "down", "play", "pause", "next", "previous", "find_phone", "other")}
        self.history: list[dict] = []
        self.loop: asyncio.AbstractEventLoop | None = None
        self.queue: asyncio.Queue[dict] | None = None
        self.stop_event: asyncio.Event | None = None
        self.show_window = None

    def snapshot(self) -> dict:
        with self.lock:
            return {"tracks": [t.copy() for t in self.tracks], "index": self.index,
                    "playing": self.playing, "feedback": self.feedback,
                    "status": self.status, "detail": self.detail,
                    "active_app": self.active_app, "app_cursor_name": self.app_cursor_name,
                    "brightness": self.brightness, "system_volume": self.system_volume,
                    "scroll_permission": self.scroll_permission, "permission_name": PERMISSION_NAME,
                    "apps": self.apps.copy(),
                    "last_action": self.last_action, "error": self.error,
                    "counts": self.counts.copy(), "history": self.history.copy()}

    def set(self, **values) -> None:
        with self.lock:
            for key, value in values.items():
                setattr(self, key, value)

    def log(self, name: str, source: str) -> None:
        with self.lock:
            if source == "watch":
                self.counts[name] = self.counts.get(name, 0) + 1
            self.history.insert(0, {"event": name, "source": source,
                                    "time": time.strftime("%H:%M:%S")})
            del self.history[16:]

    def enqueue(self, command: dict) -> None:
        if self.loop and self.queue:
            self.loop.call_soon_threadsafe(self.queue.put_nowait, command)


class LocalHTTPServer(ThreadingHTTPServer):
    def server_bind(self) -> None:
        TCPServer.server_bind(self)
        self.server_name = "localhost"
        self.server_port = self.socket.getsockname()[1]


class Handler(BaseHTTPRequestHandler):
    state: State

    def log_message(self, _format: str, *_args) -> None:
        return

    def reply(self, code: int, content: bytes, mime: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(content)

    def do_GET(self) -> None:
        route = urlparse(self.path).path
        if route == "/":
            self.reply(200, (ROOT / "index.html").read_bytes(), "text/html; charset=utf-8")
        elif route == "/style.css":
            self.reply(200, (ROOT / "style.css").read_bytes(), "text/css; charset=utf-8")
        elif route == "/state":
            self.reply(200, json.dumps(self.state.snapshot()).encode(), "application/json")
        elif route == "/app-id":
            self.reply(200, b"stove", "text/plain")
        else:
            self.reply(404, b"Not found", "text/plain")

    def do_POST(self) -> None:
        route = urlparse(self.path).path
        origin = self.headers.get("Origin")
        if origin not in (None, f"http://127.0.0.1:{self.server.server_port}",
                          f"http://localhost:{self.server.server_port}"):
            self.reply(403, b"Forbidden", "text/plain")
            return
        if route == "/focus" and self.state.show_window:
            self.state.show_window()
            self.reply(200, b"Focused", "text/plain")
            return
        if route != "/action":
            self.reply(404, b"Not found", "text/plain")
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 2 or length > 300:
                raise ValueError
            command = json.loads(self.rfile.read(length))
            if command.get("action") not in {"up", "down", "next", "previous", "play", "pause",
                                             "permission", "add_app", "remove_app", "quit"}:
                raise ValueError
            if command["action"] in {"add_app", "remove_app"} and not re.fullmatch(
                    r"[A-Za-z0-9._-]{3,160}", str(command.get("bundle_id", ""))):
                raise ValueError
        except (ValueError, AttributeError, json.JSONDecodeError):
            self.reply(400, b"Invalid action", "text/plain")
            return
        command["source"] = "web"
        self.state.enqueue(command)
        self.reply(202, b"Queued", "text/plain")


class Bridge:
    def __init__(self, state: State, actions: MacActions) -> None:
        self.state = state
        self.actions = actions
        self.session: Session | None = None
        self.send_lock = asyncio.Lock()
        self.last_card: tuple | None = None

    def card(self) -> tuple[str, str, int, int]:
        track = self.state.tracks[self.state.index]
        kind = track["kind"]
        if kind in ("scroll_current", "scroll_horizontal", "slideshow"):
            artist = self.state.active_app
        elif kind == "brightness":
            artist = f"Display {round((self.state.brightness or 0) * 100)}%"
        elif kind == "switch_apps":
            artist = self.state.app_cursor_name or self.state.active_app
        elif kind == "system_volume":
            artist = f"Mac volume {self.state.system_volume or 0}%"
        else:
            artist = track.get("app_name", "Mac app")
        return (track["title"], artist[:60],
                pl.MUSIC_PLAYING if self.state.playing else pl.MUSIC_PAUSED,
                self.state.feedback)

    async def send_card(self, force: bool = False) -> None:
        if not self.session:
            return
        card = self.card()
        if not force and card == self.last_card:
            return
        async with self.send_lock:
            await self.session.send(ops.MUSIC_INFO_SET, pl.music_info(
                card[0], card[1], state=card[2], volume=card[3], volume_max=16))
            self.last_card = card


async def process_events(state: State, actions: MacActions, bridge: Bridge) -> None:
    assert state.queue is not None
    last_turn = 0.0
    last_switch = 0.0
    last_find_phone = 0.0
    while True:
        command = await state.queue.get()
        name = command["action"]
        source = command.get("source", "watch")
        state.log(name, source)
        now = time.monotonic()
        try:
            if name == "quit":
                state.set(status="stopping", detail="Stove is shutting down")
                if state.stop_event:
                    state.stop_event.set()
                return
            if name == "permission":
                allowed = actions.request_scroll_permission()
                state.set(scroll_permission=allowed, error="" if allowed else f"Allow Stove in {PERMISSION_NAME}, then return here")
                continue
            if name == "add_app":
                bundle_id = command["bundle_id"]
                app = actions.app_for_bundle(bundle_id)
                if any(t.get("bundle_id") == bundle_id for t in state.tracks):
                    raise RuntimeError("This app already has a track")
                if len(state.tracks) >= 20:
                    raise RuntimeError("Maximum 20 tracks")
                app_name = str(app.localizedName() or "App")
                state.tracks.append({"id": f"app-{bundle_id}", "title": f"{app_name} scroll"[:40],
                                     "kind": "scroll_app", "bundle_id": bundle_id,
                                     "app_name": app_name})
                save_tracks(state.tracks)
                state.set(last_action=f"Added {app_name} track", error="")
                await bridge.send_card()
                continue
            if name == "remove_app":
                bundle_id = command["bundle_id"]
                found = next((i for i, t in enumerate(state.tracks) if t.get("bundle_id") == bundle_id), None)
                if found is None:
                    raise RuntimeError("App track not found")
                removed = state.tracks.pop(found)
                if state.index >= len(state.tracks):
                    state.index = 0
                elif found < state.index:
                    state.index -= 1
                save_tracks(state.tracks)
                state.set(last_action=f"Removed {removed['title']}", error="")
                await bridge.send_card()
                continue
            if name == "find_phone":
                if source == "watch" and now - last_find_phone < 5:
                    continue
                last_find_phone = now
                state.set(last_action="Putting Mac to sleep", error="")
                actions.sleep_mac()
                continue
            if name in ("next", "previous"):
                if source == "watch" and now - last_switch < 0.4:
                    continue
                last_switch = now
                direction = -1 if name == "previous" else 1
                state.index = (state.index + direction) % len(state.tracks)
                track = state.tracks[state.index]
                if track["kind"] == "brightness":
                    state.brightness = actions.brightness()
                    state.feedback = round(state.brightness * 16)
                elif track["kind"] == "system_volume":
                    state.system_volume = actions.system_volume()
                    state.feedback = round(state.system_volume / 100 * 16)
                elif track["kind"] == "switch_apps":
                    app_name, _, bundle_id = actions.frontmost()
                    state.app_cursor_bundle = bundle_id
                    state.app_cursor_name = app_name
                    state.feedback = 8
                elif track["kind"] == "scroll_app":
                    actions.activate_app(track["bundle_id"])
                    state.feedback = 8
                else:
                    state.feedback = 8
                state.set(last_action=f"Track: {track['title']}", error="")
                await bridge.send_card()
                continue
            if name in ("play", "pause"):
                state.set(playing=name == "play", last_action="Controls on" if name == "play" else "Controls paused", error="")
                await bridge.send_card()
                continue
            if name in ("up", "down"):
                track = state.tracks[state.index]
                kind = track["kind"]
                minimum_gap = 0.18 if kind == "switch_apps" else (0.12 if kind == "brightness" else 0.07)
                if source == "watch" and now - last_turn < minimum_gap:
                    continue
                last_turn = now
                if not state.playing:
                    state.set(last_action="Press Play on the watch to resume controls")
                    continue
                direction = 1 if name == "up" else -1
                if kind == "scroll_current":
                    target = actions.scroll(direction * 3)
                    state.feedback = (state.feedback + direction) % 17
                    label = f"Scrolled {target} {'up' if direction > 0 else 'down'}"
                elif kind == "scroll_app":
                    target = actions.scroll(direction * 3, track["bundle_id"])
                    state.feedback = (state.feedback + direction) % 17
                    label = f"Scrolled {target} {'up' if direction > 0 else 'down'}"
                elif kind == "scroll_horizontal":
                    target = actions.scroll_horizontal(-direction * 3)
                    state.feedback = (state.feedback + direction) % 17
                    label = f"Scrolled {target} {'right' if direction > 0 else 'left'}"
                elif kind == "slideshow":
                    target = actions.slideshow_arrow(direction)
                    state.feedback = (state.feedback + direction) % 17
                    label = f"{target}: {'next' if direction > 0 else 'previous'} slide"
                elif kind == "brightness":
                    state.brightness = actions.change_brightness(direction)
                    state.feedback = round(state.brightness * 16)
                    label = f"Brightness {round(state.brightness * 100)}%"
                elif kind == "system_volume":
                    state.system_volume = actions.change_system_volume(direction)
                    state.feedback = round(state.system_volume / 100 * 16)
                    label = f"System volume {state.system_volume}%"
                elif kind == "switch_apps":
                    apps = actions.running_apps()
                    if not apps:
                        raise RuntimeError("No running apps found")
                    cursor = state.app_cursor_bundle or actions.frontmost()[2]
                    current_index = next((i for i, a in enumerate(apps) if a["bundle_id"] == cursor), 0)
                    chosen_index = (current_index + direction) % len(apps)
                    chosen = apps[chosen_index]
                    state.app_cursor_bundle = chosen["bundle_id"]
                    state.app_cursor_name = chosen["name"]
                    target = actions.activate_app(chosen["bundle_id"])
                    state.active_app = target
                    state.feedback = (chosen_index % 16) + 1
                    label = f"Switched to {target}"
                state.set(last_action=label, error="")
                await bridge.send_card()
        except Exception as exc:
            safe = str(exc) if isinstance(exc, (RuntimeError, PermissionError)) else type(exc).__name__
            state.set(error=safe, last_action=f"Could not perform {name}")
            print(f"action {name}: {safe}", flush=True)


async def refresh_mac_state(state: State, actions: MacActions, bridge: Bridge) -> None:
    while True:
        try:
            app_name, _, _ = actions.frontmost()
            old_name = state.active_app
            state.set(active_app=app_name, scroll_permission=actions.can_scroll(),
                      brightness=actions.brightness(), apps=actions.running_apps())
            if old_name != app_name and state.tracks[state.index]["kind"] in (
                    "scroll_current", "scroll_horizontal", "slideshow"):
                await bridge.send_card()
        except Exception:
            pass
        await asyncio.sleep(1)


async def watch_loop(state: State, bridge: Bridge, args: argparse.Namespace) -> None:
    while True:
        transport = None
        session = None
        try:
            state.set(status="scanning", detail="Looking for CMF Watch 3 Pro")
            devices = await scan(timeout=8.0)
            watch = next((d for d in devices if "Watch 3 Pro" in (d.name or "")), None)
            if watch is None:
                raise RuntimeError("Watch not found. Disconnect the phone companion and keep the watch nearby.")
            state.set(status="connecting", detail="Connecting to watch")
            transport = BleTransport(watch.address)
            await transport.connect()
            session = Session(transport)
            if args.key_file.exists():
                state.set(status="authenticating", detail="Logging in with saved key")
                key = bytes.fromhex(args.key_file.read_text(encoding="ascii").strip())
                try:
                    await asyncio.wait_for(session.login(key), timeout=16)
                except Exception:
                    if not args.pair_if_needed:
                        raise RuntimeError("Saved login failed. Restart with --pair-if-needed.")
                    await transport.disconnect()
                    transport = BleTransport(watch.address)
                    await transport.connect()
                    session = Session(transport)
                    state.set(status="pairing", detail="Confirm the prompt on the watch")
                    key = await asyncio.wait_for(session.pair(), timeout=45)
                    save_key(args.key_file, key)
            elif args.pair_if_needed:
                state.set(status="pairing", detail="Confirm the prompt on the watch")
                key = await asyncio.wait_for(session.pair(), timeout=45)
                save_key(args.key_file, key)
            else:
                raise RuntimeError("No saved key. Restart with --pair-if-needed.")

            def on_message(msg) -> None:
                if msg.op == ops.MUSIC_BUTTON and len(msg.payload) >= 2:
                    name = WATCH_CODES.get(msg.payload[:2], "other")
                    if name == "other":
                        state.log("other", "watch")
                    elif state.queue:
                        state.queue.put_nowait({"action": name, "source": "watch"})
                elif msg.op == ops.FIND_PHONE and state.queue:
                    state.queue.put_nowait({"action": "find_phone", "source": "watch"})

            session.on_message(on_message)
            bridge.session = session
            bridge.last_card = None
            await bridge.send_card(force=True)
            state.set(status="connected", detail="Double-press the crown to open Music; next/previous changes tracks")
            print("watch connected", flush=True)
            while transport._client and transport._client.is_connected:
                await asyncio.sleep(0.3)
            raise RuntimeError("Watch disconnected")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            safe = str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__
            if type(exc).__name__ == "BleakBluetoothNotAvailableError":
                detail = "Bluetooth is unavailable. Turn it on to reconnect."
            else:
                detail = f"{safe} Retrying in 5 seconds."
            state.set(status="reconnecting", detail=detail)
            print(f"reconnecting: {safe}", flush=True)
            await asyncio.sleep(5)
        finally:
            if bridge.session is session:
                bridge.session = None
            if session:
                try:
                    await session.set_music("", "", state=pl.MUSIC_STOPPED)
                except Exception:
                    pass
            if transport:
                try:
                    await transport.disconnect()
                except Exception:
                    pass


async def run(state: State, args: argparse.Namespace) -> None:
    actions = MacActions()
    bridge = Bridge(state, actions)
    state.loop = asyncio.get_running_loop()
    state.queue = asyncio.Queue()
    state.stop_event = asyncio.Event()
    tasks = [asyncio.create_task(coro) for coro in (
        process_events(state, actions, bridge),
        refresh_mac_state(state, actions, bridge),
        watch_loop(state, bridge, args),
    )]
    try:
        await state.stop_event.wait()
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8790)
    parser.add_argument("--key-file", type=Path, default=APP_DATA / "watch.key")
    parser.add_argument("--pair-if-needed", action="store_true", default=True)
    parser.add_argument("--headless", "--no-browser", action="store_true")
    args = parser.parse_args()
    state = State(load_tracks())
    Handler.state = state
    try:
        server = LocalHTTPServer(("127.0.0.1", args.port), Handler)
    except OSError:
        from urllib.request import Request, urlopen
        try:
            with urlopen(f"http://127.0.0.1:{args.port}/app-id", timeout=1) as response:
                if response.read() == b"stove":
                    with urlopen(Request(f"http://127.0.0.1:{args.port}/focus", data=b"", method="POST"), timeout=2) as response:
                        if response.status == 200:
                            return
        except OSError:
            pass
        raise
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f"Stove: http://127.0.0.1:{args.port}", flush=True)
    try:
        if args.headless:
            asyncio.run(run(state, args))
        else:
            from native_window import run_native
            worker = threading.Thread(target=lambda: asyncio.run(run(state, args)), daemon=True)
            worker.start()
            run_native(state, args.port, worker)
            if state.loop and state.stop_event:
                state.loop.call_soon_threadsafe(state.stop_event.set)
            worker.join(timeout=10)
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()


if __name__ == "__main__":
    main()
