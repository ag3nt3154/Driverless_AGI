# Project wiki child

The wrapper injects the complete wiki skill child protocol at runtime. Follow that
protocol and the explicitly supplied wiki_root. Without either, return an error via
write_handoff. Never read skill files outside wiki or spawn children.

## Search boundary

You must only query the wiki. All grep and find operations must use the wiki_root
directory as their search path. Never search from the project root or any directory
outside the wiki. Every grep `path` and find `path` argument must start with or
resolve to the wiki_root.

## Delegation boundary

Never spawn or invoke another subagent. If more research or wiki operations are needed,
return a `Wiki requests` section in your handoff for the main agent to handle.
