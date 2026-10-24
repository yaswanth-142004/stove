# Voice assistant and recordings: research status

Stove does not currently stream watch microphone audio or download saved recordings.

## Watch 3 Pro test

On firmware 1.0.1.77, with Stove authenticated over BLE and the Nothing X phone companion disconnected:

- Opening Voice Assistant displayed a request to connect to the phone.
- Starting a watch recording worked locally. Trying to upload it displayed a request to connect to the phone.
- A local decrypted capture saw a 20-byte watch message on opcode `ffff:a097` with a timestamp-shaped recording name. No audio payload arrived during the capture. This opcode's meaning and response are **not yet proven**.
- macOS listed the active watch link as BLE only. Stove currently has no watch microphone audio endpoint.

## Calling audio route (24 October 2026)

An Android 16 diagnostic from the user's OnePlus 13s shows the watch connected to the phone's Headset/HFP service over Bluetooth Classic, including an RFCOMM hands-free control connection. This is evidence for a standard call-control route, **not** yet proof that microphone audio was active in that capture. Its packaged HCI files contain only BTSnoop headers, so they cannot reveal the call audio packets or the recording-transfer protocol. The diagnostic stays local and is not part of this repository.

With the phone calling connection disconnected, macOS System Settings → Sound lists just the built-in MacBook microphone and speakers. `IOBluetoothDevice` reports the watch as paired, while Stove's BLE link remains connected; this does not establish that a separate Classic calling bond is active. A direct SDP query found Hands-Free (`0x111e`) service records with RFCOMM channel 1, even though `system_profiler` showed only the BLE service. `getLinkType` returned `0xff` (no Classic baseband link), and an authenticated Classic connection request returned the IOKit timeout code. Attempts to establish an HFP service-level connection through `IOBluetoothHandsFreeAudioGateway` and to open RFCOMM channel 1 directly also timed out. No SCO audio connection or macOS input/output device appeared. The watch advertises the calling profile, but does not yet provide a usable Mac audio route. The diagnostic source is `scripts/probe_voice_route.m`; it does not send AT commands or record audio.

Static analysis of the installed Nothing X 3.10.1 Android APK found a separate watch Bluetooth connection flow. Its Android connector requests the system Headset profile (`BluetoothProfile.HEADSET`, profile 1) and calls that profile's `connect(BluetoothDevice)` method. The app also has a distinct watch BLE connection path. This supports testing Classic calling setup separately from Stove's working BLE controls, but it does not reveal the watch's exact Voice Assistant trigger or prove that macOS has completed a Classic calling bond. The APK and decompiled output are private local research files and are not distributed with Stove.

The watch's built-in Voice Assistant is a separate path: while connected to Stove over BLE, both Voice Assistant and Calls ask to connect to a phone via Bluetooth. The exact condition used by those pages is still unknown. HFP pairing alone may provide call audio without making the built-in assistant page usable.

The standard HFP mechanism for a hands-free device to activate the host's voice assistant is `AT+BVRA`; an established HFP service-level connection and audio connection are involved ([Bluetooth SIG HFP 1.10, §4.25](https://docs.bluetooth.com/download/hfp_v1-10_showing_changes_since_hfp_v1-9/)). The watch's exact implementation has **not** been captured, so this is a protocol hypothesis rather than a decoded watch command. Nothing lists Voice Assistant and ChatGPT as separate features; its [ChatGPT setup instructions](https://support.nothing.tech/hc/en-us/categories/31667489672209) require Nothing X, the phone's ChatGPT app, and a Nothing phone. The user's OnePlus is not eligible for that specific ChatGPT integration, but its ordinary Android assistant may still work through the watch's Voice Assistant feature when the phone's call-audio profile is connected. That requires a phone-connected test.

After the watch was connected to the Mac, opening its Phone Call app also displayed "connect to phone". A Mac BLE connection therefore does not satisfy the watch's phone-dependent call UI. This does not establish whether a separate HFP audio pairing is possible; macOS still exposes no watch audio device.

[Nothing's Watch 3 Pro support instructions](https://support.nothing.tech/hc/en-us/categories/31667489672209) say the ChatGPT assistant requires the phone's ChatGPT app, and recording upload must be initiated from the watch into Nothing X. [Gadgetbridge](https://freeyourgadget.codeberg.page/gadgetbridge_org/gadgets/wearables/nothing/) lists the Watch Pro 3 as partially supported and does not document voice or recording transfer support.

## Recording-transfer experiment

Capture a watch-initiated recording upload while the official Android companion is connected. Compare the authenticated BLE messages and any separate audio transport with the watch-to-Mac capture. Identify the `a097` response and full file transfer framing before adding a downloader. Keep capture files private because they may contain microphone audio, pairing material, and other phone traffic. For a live agent, verify a usable microphone route to the Mac and a start/stop event first; then connect transcription and an agent with explicit microphone and network consent.

The Music control path remains separate and functional while this is researched.
