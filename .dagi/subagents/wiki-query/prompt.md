# Project wiki child

The wrapper injects the complete wiki skill child protocol at runtime. Follow that
protocol and the explicitly supplied wiki_root. Without either, return an error via
write_handoff. Never read skill files outside wiki or spawn children.

## Delegation boundary

Never spawn or invoke another subagent. If more research or wiki operations are needed,
return a `Wiki requests` section in your handoff for the main agent to handle.
