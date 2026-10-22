# Voice assistant and recordings: research status

Stove does not currently stream watch microphone audio or download saved recordings.

## Watch 3 Pro test

On firmware 1.0.1.77, with Stove authenticated over BLE and the Nothing X phone companion disconnected:

- Opening Voice Assistant displayed a request to connect to the phone.
- Starting a watch recording worked locally. Trying to upload it displayed a request to connect to the phone.
- A local decrypted capture saw a 20-byte watch message on opcode `ffff:a097` with a timestamp-shaped recording name. No audio payload arrived during the capture. This opcode's meaning and response are **not yet proven**.
- macOS listed the active watch link as BLE only. Stove currently has no watch microphone audio endpoint.

[Nothing's Watch 3 Pro support instructions](https://support.nothing.tech/hc/en-us/categories/31667489672209) say the ChatGPT assistant requires the phone's ChatGPT app, and recording upload must be initiated from the watch into Nothing X. [Gadgetbridge](https://freeyourgadget.codeberg.page/gadgetbridge_org/gadgets/wearables/nothing/) lists the Watch Pro 3 as partially supported and does not document voice or recording transfer support.

## Next experiment

Capture a watch-initiated recording upload while the official Android companion is connected. Compare the authenticated BLE messages and any separate audio transport with the watch-to-Mac capture. Identify the `a097` response and full file transfer framing before adding a downloader. Keep capture files private because they may contain microphone audio, pairing material, and other phone traffic. For a live agent, verify a usable microphone route to the Mac and a start/stop event first; then connect transcription and an agent with explicit microphone and network consent.

The Music control path remains separate and functional while this is researched.
