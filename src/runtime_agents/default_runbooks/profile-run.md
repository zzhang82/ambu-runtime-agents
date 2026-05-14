---
id: profile_run
title: Profile run
risk: read_only
requires_confirmation: false
description: Resolve a profile and show the run payload.
phrases:
  - run profile {profile_id} {goal}
  - use profile {profile_id} to {goal}
inputs:
  profile_id:
    type: id
    required: true
  goal:
    type: text
    required: true
actions:
  - type: profile_run
    profile_id: "{profile_id}"
    goal: "{goal}"
response:
  matched: Resolving profile {profile_id} for run.
---

Resolve a profile-aware run request.
