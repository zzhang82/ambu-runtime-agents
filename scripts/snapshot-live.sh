#!/usr/bin/env bash
set -euo pipefail

ts="$(date +%Y%m%dT%H%M%S)"
backup_dir="${RUNTIME_AGENTS_STATE_HOME:-$HOME/.local/share/runtime-agents}/backups/pre-repo-migration-${ts}"
mkdir -p "$backup_dir/bin" "$backup_dir/config"
cp "$HOME/.local/bin/agentctl" "$backup_dir/bin/"
cp "$HOME/.local/bin/agentd" "$backup_dir/bin/"
cp "$HOME/.local/bin/agentbot" "$backup_dir/bin/"
cp -R "$HOME/.config/runtime-agents/." "$backup_dir/config/"
printf 'Snapshot created at %s\n' "$backup_dir"
