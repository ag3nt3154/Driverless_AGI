---
title: 'Startup splash showed a black box before the video played'
description: 'Fix: build DagiMainWindow before the splash; splash stays at opacity 0 until the first video frame, 3 s no-frame timeout skips it.'
tags: [startup_splash, StartupSplash, QVideoWidget, QMediaPlayer, videoFrameChanged, windowOpacity, splash, startup, black-rectangle, gui]
updated: 2026-10-12
---
Symptom: on GUI launch, an empty black rectangle showed for some time before the startup video played.

## Cause
`pyside_gui.py` showed the splash (black stylesheet), called `processEvents()` once, then built
`DagiMainWindow`. The build is slow and blocks the Qt event loop. Qt Multimedia loads and decodes
video on the event loop, so no frames came until `qt_app.exec()`. `processEvents()` paints one
time only; it does not keep the loop alive during later synchronous work. Even after the loop
runs, the first frame needs approximately 350 ms (measured with `.dagi/emotes/startup/1.mp4`).

## Fix
- `pyside_gui.py`: build `DagiMainWindow` first, connect `intro.fading` to `window.show`, then
  `intro.start()`. Connect before `start()`: a synchronous player error in `start()` still shows the window.
- `StartupSplash.start()`: show at `windowOpacity(0)` (not hidden, so the video widget still
  renders) and set opacity 1 on the first `videoSink().videoFrameChanged`, unless a fade started.
- Fade-out is `_FADE_MS` = 200 ms (reduced from 450 ms on 2026-10-12 at the Admiral's request).
- `_FIRST_FRAME_MS` (3 s): no frame by then → `skip()`, so the main window always shows.
- Tests: `tests/pyside_gui/test_startup_splash.py`.

Trade-off (approved by the Admiral): the splash appears only after the main window is built, so
launch-to-first-pixel is longer, but nothing black shows.
