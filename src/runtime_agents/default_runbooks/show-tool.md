---
id: show_tool
title: Show tool
risk: read_only
requires_confirmation: false
description: Show one configured local tool.
phrases:
  - show tool {tool_id}
  - tool {tool_id}
inputs:
  tool_id:
    type: id
    required: true
actions:
  - type: show_tool
    tool_id: "{tool_id}"
response:
  matched: Showing tool {tool_id}.
---

Show one configured local tool.
