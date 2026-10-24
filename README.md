# Stove

[Website and Mac download](https://yaswanth-142004.github.io/stove/) · [GitHub Releases](https://github.com/yaswanth-142004/stove/releases)

Turn a CMF Watch 3 Pro into a Mac remote. Double-press the watch crown to open Music; each music “track” is a control mode. Next/previous selects a mode, and turning the crown performs its action.

## Modes

1. Vertical scroll
2. Switch apps
3. Brightness
4. Sound
5. Horizontal scroll
6. Slideshow (Right/Left arrow keys)

Find Phone puts the Mac to sleep. Play enables controls and Pause suspends crown actions. You can add tracks for running apps in the dashboard.

## Install

Download the Apple Silicon DMG from [Releases](https://github.com/yaswanth-142004/stove/releases), drag Stove to Applications, and open it. Stove opens a native Mac window with its local dashboard.

### Install from Terminal with curl

On another Apple Silicon Mac running macOS 13 or later, quit any running copy of Stove, then paste this into Terminal. It downloads the v0.2.4 DMG from GitHub Releases, checks its SHA-256 checksum, and installs Stove for the current user in `~/Applications` without an administrator password.

```sh
(
  set -e
  stove_tmp="$(mktemp -d)"
  trap 'hdiutil detach -quiet "$stove_tmp/mount" >/dev/null 2>&1 || true' EXIT
  curl -fL 'https://github.com/yaswanth-142004/stove/releases/download/v0.2.4/Stove-0.2.4-macos-arm64.dmg' -o "$stove_tmp/Stove.dmg"
  printf '%s  %s\n' '0ede3574476a67dc8112de7fa37cbc8f7cd2d00450dfbe6a089613187083767f' "$stove_tmp/Stove.dmg" | shasum -a 256 -c -
  mkdir -p "$stove_tmp/mount" "$HOME/Applications"
  hdiutil attach -quiet -nobrowse -readonly -mountpoint "$stove_tmp/mount" "$stove_tmp/Stove.dmg"
  ditto "$stove_tmp/mount/Stove.app" "$HOME/Applications/Stove.app"
)
```

Open `~/Applications/Stove.app` afterward. The release is ad hoc signed but not notarized, so the first launch may require System Settings → Privacy & Security → Open Anyway. Allow Bluetooth and the Mac control permission when prompted. On macOS 27, find Stove under System Settings → Privacy & Security → **Device Control and Data Access**; on macOS 13–26, use **Accessibility**. If Stove is missing, click Add and select `Stove.app` from Applications. Keep the phone companion disconnected while using Stove, and confirm pairing on the watch the first time. Each Mac pairs separately; its pairing key is saved only in `~/Library/Application Support/Stove/watch.key` on that Mac.

The watch crown shortcut must be set to open Music in Nothing X. Stove has been tested with a CMF Watch 3 Pro on firmware 1.0.1.77 and macOS on Apple Silicon. Other watch models and Intel Macs are untested. Brightness is for the built-in display. Find Phone sleep can interrupt an active session.

## Run from source

Requires macOS, Python 3.12, and Bluetooth hardware. Install `requirements.txt`, then run `python stove/app.py`. See `scripts/build_macos.sh` for a local app build. The embedded dashboard listens only on loopback. To quit, close the Mac window or use the dashboard’s Quit Stove button.

## Privacy and protocol

Stove does not send events to a server. The website only serves downloads; the Mac app talks to the watch over Bluetooth and serves its dashboard locally. No watch key, address, or capture is in this repository or app bundle. Protocol behavior was researched against [CMF-Open](https://github.com/TechJeeper/CMF-Open); Stove's BLE implementation is independently written.

## Limitations

The release is ad hoc signed, not Developer ID notarized. Scrolling and slideshow need Device Control and Data Access permission on macOS 27, or Accessibility permission on older macOS versions. Switch apps cycles through running apps and can skip background-only apps. Watch face crown taps are handled by watch firmware and are not exposed through the observed BLE events.

## Voice Assistant and recordings

The watch's Voice Assistant button starts a Bluetooth Hands-Free voice recognition session. We confirmed that it opens the Android assistant with the watch's calling connection active. Stove's Mac connection currently handles the watch's BLE music controls; it does not yet provide a Bluetooth Hands-Free audio endpoint, so the watch microphone and speaker are not available to a Mac agent through Stove.

Recordings can be received directly in Stove's **Recordings** section. When connected to Stove, tap **Send to phone** on any recording on the watch; Stove accepts the transfer over BLE, downloads the audio chunks, and saves the `.mp3` file to `~/Library/Application Support/Stove/recordings`, where it can be played and saved. You can also import existing audio files directly using **Import audio**.

## License

MIT. See [LICENSE](LICENSE).
