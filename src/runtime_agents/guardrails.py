from __future__ import annotations

from typing import Any

from runtime_agents.models import ContextState, GuardrailDecision, ToolTrace

BLOCKED_ACTION_TYPES = {"shell", "exec", "bash", "raw_command", "python_eval", "arbitrary_agentctl"}
EXTERNAL_EGRESS = {"telegram", "email", "web", "broker", "public_web", "private_network", "mixed"}
PRIVATE_DATA_CLASSES = {"workspace_files", "project_source", "private_data", "credentials", "secrets"}
UNTRUSTED_TRUST_LEVELS = {"untrusted_input", "untrusted_output", "mixed"}
BROKER_CAPABILITIES = {"broker_order_submit", "options_autotrade", "margin"}
PURCHASE_CAPABILITIES = {"external_purchase", "checkout", "payment", "captcha_bypass"}
DECISION_RANK = {"allow": 0, "approval_required": 1, "block": 2}


RULES = [
    {
        "rule_id": "block_arbitrary_shell",
        "decision": "block",
        "description": "Blocks arbitrary shell and raw execution action types.",
    },
    {
        "rule_id": "tool_disabled",
        "decision": "block",
        "description": "Blocks evaluation when the selected tool is disabled.",
    },
    {
        "rule_id": "block_untrusted_private_external_send",
        "decision": "block",
        "description": "Blocks external send when untrusted context and private data are combined.",
    },
    {
        "rule_id": "require_approval_private_external_summary",
        "decision": "approval_required",
        "description": "Requires approval for external summaries involving private data.",
    },
    {
        "rule_id": "block_broker_order_submit",
        "decision": "block",
        "description": "Blocks broker and trading order capabilities.",
    },
    {
        "rule_id": "block_external_purchase",
        "decision": "block",
        "description": "Blocks purchase, checkout, and payment capabilities.",
    },
    {
        "rule_id": "unknown_tool",
        "decision": "block",
        "description": "Blocks evaluation when the selected tool is not registered.",
    },
    {
        "rule_id": "tool_not_allowed_for_profile",
        "decision": "block",
        "description": "Blocks tools that are outside the profile allowed_tools scope.",
    },
    {
        "rule_id": "profile_blocked_capability",
        "decision": "block",
        "description": "Blocks capabilities listed in profile.blocked_capabilities.",
    },
    {
        "rule_id": "profile_approval_required",
        "decision": "approval_required",
        "description": "Requires approval for capabilities listed in profile.approval_required.",
    },
    {
        "rule_id": "default_allow",
        "decision": "allow",
        "description": "Allows requests when no blocking or approval rule matches.",
    },
]


def list_guardrail_rules() -> dict[str, Any]:
    return {"rules": RULES}


def _normalize_tool_trace(tool: dict[str, Any]) -> ToolTrace:
    return ToolTrace(
        tool_id=tool.get("id") or "unknown",
        trust_level=tool.get("trust_level") or "trusted",
        data_classes=list(tool.get("data_classes") or []),
        capabilities=list(tool.get("capabilities") or []),
        egress=tool.get("egress") or "none",
        source=tool.get("source"),
    )


def build_context_state(
    *,
    profile_id: str | None,
    workspace: str | None,
    selected_tools: list[dict[str, Any]] | None,
    considered_tools: list[dict[str, Any]] | None,
    action: str,
    saw_untrusted_input: bool | None = None,
) -> ContextState:
    selected_traces = [_normalize_tool_trace(tool) for tool in (selected_tools or [])]
    considered_traces = [_normalize_tool_trace(tool) for tool in (considered_tools or [])]
    tool_ids = sorted({trace.tool_id for trace in considered_traces})
    data_classes = sorted({item for trace in selected_traces for item in trace.data_classes})
    capabilities = sorted({action, *[item for trace in selected_traces for item in trace.capabilities]})
    saw_untrusted = bool(saw_untrusted_input) or any(trace.trust_level in UNTRUSTED_TRUST_LEVELS for trace in selected_traces)
    accessed_private = any(data_class in PRIVATE_DATA_CLASSES for data_class in data_classes)
    external_egress = any(trace.egress in EXTERNAL_EGRESS for trace in selected_traces)
    return ContextState(
        profile=profile_id,
        workspace=workspace,
        saw_untrusted_input=saw_untrusted,
        accessed_private_data=accessed_private,
        external_egress_used=external_egress,
        data_classes=data_classes,
        capabilities=capabilities,
        tool_trace=[trace for trace in selected_traces],
        tools_considered=tool_ids,
    )


def _decision(decision: str, rule_id: str, reason: str, action: str, severity: str) -> GuardrailDecision:
    return GuardrailDecision(decision=decision, rule_id=rule_id, reason=reason, action=action, severity=severity)


def _strongest(decisions: list[GuardrailDecision]) -> GuardrailDecision:
    return max(decisions, key=lambda item: DECISION_RANK.get(item.decision, -1))


def evaluate_guardrails(
    *,
    profile: dict[str, Any] | None,
    profile_id: str | None,
    tool: dict[str, Any] | None,
    requested_tool_id: str | None,
    action: str,
    context_state: ContextState,
) -> dict[str, Any]:
    decisions: list[GuardrailDecision] = []
    capabilities = set(context_state.capabilities)
    tool_capabilities = set(tool.get("capabilities") or []) if tool else set()
    blocked_capabilities = set((profile or {}).get("blocked_capabilities") or [])
    approval_capabilities = set((profile or {}).get("approval_required") or [])
    action_name = action or "unknown"

    if action_name in BLOCKED_ACTION_TYPES:
        decisions.append(_decision("block", "block_arbitrary_shell", f"action {action_name} is not allowed", action_name, "critical"))

    if requested_tool_id and tool is None:
        decisions.append(_decision("block", "unknown_tool", "tool is not registered", action_name, "critical"))

    if tool and not bool(tool.get("enabled", True)):
        decisions.append(_decision("block", "tool_disabled", f"tool {tool.get('id')} is disabled", action_name, "critical"))

    allowed_tools = set((profile or {}).get("allowed_tools") or [])
    if tool and allowed_tools and tool.get("id") not in allowed_tools:
        decisions.append(
            _decision(
                "block",
                "tool_not_allowed_for_profile",
                f"profile {profile_id} does not allow tool {tool.get('id')}",
                action_name,
                "critical",
            )
        )

    if context_state.saw_untrusted_input and context_state.accessed_private_data and context_state.external_egress_used:
        decisions.append(
            _decision(
                "block",
                "block_untrusted_private_external_send",
                "untrusted input + private data + external egress risk",
                action_name,
                "critical",
            )
        )
    elif context_state.accessed_private_data and context_state.external_egress_used:
        decisions.append(
            _decision(
                "approval_required",
                "require_approval_private_external_summary",
                "private data with external egress requires approval",
                action_name,
                "warning",
            )
        )

    if BROKER_CAPABILITIES & capabilities:
        decisions.append(_decision("block", "block_broker_order_submit", "broker and margin actions are blocked", action_name, "critical"))

    if PURCHASE_CAPABILITIES & capabilities:
        decisions.append(_decision("block", "block_external_purchase", "purchase and checkout actions are blocked", action_name, "critical"))

    blocked_matches = sorted((tool_capabilities | capabilities) & blocked_capabilities)
    if blocked_matches:
        decisions.append(
            _decision(
                "block",
                "profile_blocked_capability",
                f"profile {profile_id} blocks {', '.join(blocked_matches)}",
                action_name,
                "critical",
            )
        )

    approval_matches = sorted((tool_capabilities | capabilities) & approval_capabilities)
    if approval_matches:
        decisions.append(
            _decision(
                "approval_required",
                "profile_approval_required",
                f"profile {profile_id} requires approval for {', '.join(approval_matches)}",
                action_name,
                "warning",
            )
        )

    if not decisions:
        decisions.append(_decision("allow", "default_allow", "no blocking guardrail matched", action_name, "info"))

    primary = _strongest(decisions)
    return {
        "decision": primary.decision,
        "rule_id": primary.rule_id,
        "reason": primary.reason,
        "context_state": context_state.to_payload(),
        "policy_decisions": [item.to_payload() for item in decisions],
    }
