# Talking mascot release

Live now uses an articulated SVG adaptation of the approved browser-window mascot. Listening tilts its head; thinking shifts the eyes; actual audio playback drives mouth opening through a Web Audio analyser. The mouth begins only on the audio playing event. An explicit Interrupt control stops playback. Reduced-motion mode keeps the character static with visible status text.

Microphone access still requires Start talking. Mute disables the microphone track and discards an in-progress utterance. End stops tracks, recording, timers, playback and the audio context. A session generation guard ignores late answers and late microphone permissions after cancellation; starting twice is guarded. Playback and audio setup errors are recoverable. The latest exchange remains readable.

Production build/TypeScript and eight local browser scenarios passed: idle permission boundary, denied-permission recovery, speech detection/playback-level mouth movement, interruption, mute during capture, End during a pending answer, 320/390px layouts, and dark/reduced-motion states. The browser scenarios use synthetic microphone/audio APIs and intercepted voice responses. They do not establish live speech recognition quality or real-device echo cancellation. Real microphone, speaker and spoken interruption acceptance remains the user's production test.

This release also includes the reviewed Home, Tasks Flow, mascot palette and streamlined Memory already on the UI branch. Existing backend changes are integrated from main. Screenshot files: `screenshots/wilco-live-desktop.png`, `wilco-live-speaking.png`, `wilco-live-mobile.png`, `wilco-live-dark.png`.
