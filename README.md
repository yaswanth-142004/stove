# Stove

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

Download the Apple Silicon DMG from [Releases](https://github.com/yaswanth-142004/stove/releases), drag Stove to Applications, and open it. Stove opens its local dashboard at `http://127.0.0.1:8790`. If macOS blocks the unsigned app, use System Settings → Privacy & Security → Open Anyway. Allow Bluetooth and Accessibility when prompted. Keep the phone companion disconnected while using Stove, and confirm pairing on the watch the first time. The pairing key is saved only in `~/Library/Application Support/Stove/watch.key`.

The watch crown shortcut must be set to open Music in Nothing X. Stove has been tested with a CMF Watch 3 Pro on firmware 1.0.1.77 and macOS on Apple Silicon. Other watch models and Intel Macs are untested. Brightness is for the built-in display. Find Phone sleep can interrupt an active session.

## Run from source

Requires macOS, Python 3.12, and Bluetooth hardware. Install `requirements.txt`, then run `python stove/app.py`. See `scripts/build_macos.sh` for a local app build. The dashboard listens only on loopback. To quit, use the dashboard’s Quit Stove button.

## Privacy and protocol

Stove does not send events to a server. The website only serves downloads; the Mac app talks to the watch over Bluetooth and serves its dashboard locally. No watch key, address, or capture is in this repository or app bundle. Protocol behavior was researched against [CMF-Open](https://github.com/TechJeeper/CMF-Open); Stove's BLE implementation is independently written.

## Limitations

The release is ad hoc signed, not Developer ID notarized. Scrolling and slideshow need Accessibility permission. Switch apps cycles through running apps and can skip background-only apps. Watch face crown taps are handled by watch firmware and are not exposed through the observed BLE events.

## License

MIT. See [LICENSE](LICENSE).
