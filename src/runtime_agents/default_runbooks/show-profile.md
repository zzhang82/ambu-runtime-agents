---
id: show_profile
title: Show profile
risk: read_only
requires_confirmation: false
description: Show one configured profile.
phrases:
  - show profile {profile_id}
  - profile {profile_id}
inputs:
  profile_id:
    type: id
    required: true
actions:
  - type: show_profile
    profile_id: "{profile_id}"
response:
  matched: Showing profile {profile_id}.
---

Show one configured profile.
