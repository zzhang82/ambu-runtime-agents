---
id: show_task
title: Show task
risk: read_only
requires_confirmation: false
description: Show task details.
phrases:
  - show task {task_id}
inputs:
  task_id:
    type: task_id
    required: true
actions:
  - type: show_task
    task_id: "{task_id}"
response:
  matched: "Showing task {task_id}."
---

Show task details.
