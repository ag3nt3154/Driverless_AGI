---
title: 'Todo: @-mentions do not reach spawned agents in the GUI'
description: 'In the GUI, @-mentioning a spawned agent on the board does not appear to deliver to / wake that agent. Investigate and fix.'
tags: [gui, board, mentions, '@-mention', spawned-agents, BoardController, todo]
updated: 2026-10-12
---
Next round. Observed: @-mentions don't seem to reach spawned agents in the GUI. Not yet reproduced or diagnosed.

Related, but a different issue: `board-queued-events-need-generation.md` covers the mention hook firing for stale posts after a board switch.
