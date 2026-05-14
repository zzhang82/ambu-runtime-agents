---
id: profile_plan
title: Profile plan
risk: read_only
requires_confirmation: false
description: Create a plan from a profile-aware goal.
phrases:
  - plan with profile {profile_id} {goal}
  - create plan with profile {profile_id} {goal}
inputs:
  profile_id:
    type: id
    required: true
  goal:
    type: text
    required: true
actions:
  - type: profile_plan
    profile_id: "{profile_id}"
    goal: "{goal}"
response:
  matched: Creating a plan for profile {profile_id}.
---

Resolve a profile-aware planning request.
