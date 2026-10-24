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

With the phone calling connection disconnected, macOS currently lists `CMF Watch 3 Pro-9669` as a BLE watch with service `0x400000` only. System Settings → Sound lists just the built-in MacBook microphone and speakers. A separate discoverable calling device has not appeared yet, so no watch audio has been captured or played from the Mac. The next hardware step is to expose/pair the watch's calling profile to macOS and confirm that **both** an input and an output device appear. If they do, record a short consented microphone sample and play a test response through the watch. Only then wire an assistant to the audio route.

The watch's built-in Voice Assistant is a separate path: while connected to Stove over BLE, it asked to connect to the phone. HFP pairing alone may provide call audio without making that built-in assistant page usable.

After the watch was connected to the Mac, opening its Phone Call app also displayed "connect to phone". A Mac BLE connection therefore does not satisfy the watch's phone-dependent call UI. This does not establish whether a separate HFP audio pairing is possible; macOS still exposes no watch audio device.

[Nothing's Watch 3 Pro support instructions](https://support.nothing.tech/hc/en-us/categories/31667489672209) say the ChatGPT assistant requires the phone's ChatGPT app, and recording upload must be initiated from the watch into Nothing X. [Gadgetbridge](https://freeyourgadget.codeberg.page/gadgetbridge_org/gadgets/wearables/nothing/) lists the Watch Pro 3 as partially supported and does not document voice or recording transfer support.

## Recording-transfer experiment

Capture a watch-initiated recording upload while the official Android companion is connected. Compare the authenticated BLE messages and any separate audio transport with the watch-to-Mac capture. Identify the `a097` response and full file transfer framing before adding a downloader. Keep capture files private because they may contain microphone audio, pairing material, and other phone traffic. For a live agent, verify a usable microphone route to the Mac and a start/stop event first; then connect transcription and an agent with explicit microphone and network consent.

The Music control path remains separate and functional while this is researched.
