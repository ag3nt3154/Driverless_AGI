from __future__ import annotations

import pytest

from agent.parent_context import ParentFork, build_fork_context_v2


def _fork(request: dict) -> ParentFork:
    return ParentFork(
        branch_id="worker_ab12",
        parent_cut_seq=12,
        parent_surface_generation=3,
        request=request,
    )


def test_build_fork_context_v2_has_exact_contract_fields() -> None:
    result = build_fork_context_v2(_fork({"model": "test-model"}), "worker", ["read"])

    assert result == {
        "version": 2,
        "branch": {
            "id": "worker_ab12",
            "parent_cut_seq": 12,
            "parent_surface_generation": 3,
        },
        "request": {"model": "test-model"},
        "child": {"type": "worker", "allowed_tools": ["read"]},
    }


def test_build_fork_context_v2_deep_copies_request() -> None:
    request = {"messages": [{"role": "user", "content": "hello"}]}
    result = build_fork_context_v2(_fork(request), "worker", ["read"])

    request["messages"][0]["content"] = "changed"
    assert result["request"]["messages"][0]["content"] == "hello"


def test_build_fork_context_v2_result_mutation_does_not_change_inputs() -> None:
    request = {"messages": [{"role": "user", "content": "hello"}]}
    allowed_tools = ["read"]
    fork = _fork(request)
    result = build_fork_context_v2(fork, "worker", allowed_tools)

    result["request"]["messages"][0]["content"] = "changed"
    result["child"]["allowed_tools"].append("write")

    assert fork.request["messages"][0]["content"] == "hello"
    assert allowed_tools == ["read"]


@pytest.mark.parametrize("secret", ["api_key", "authorization", "credentials"])
def test_build_fork_context_v2_rejects_top_level_secret(secret: str) -> None:
    with pytest.raises(ValueError, match=secret):
        build_fork_context_v2(_fork({secret: "secret"}), "worker", ["read"])


@pytest.mark.parametrize(
    "nested_request",
    [
        {"extra_body": {"headers": {"Authorization": "Bearer secret"}}},
        {"extra_body": {"provider": {"credentials": {"api_key": "secret"}}}},
        {"extra_body": {"auth": {"accessToken": "secret"}}},
    ],
)
def test_build_fork_context_v2_rejects_nested_credential_fields(nested_request: dict) -> None:
    with pytest.raises(ValueError, match="secret field"):
        build_fork_context_v2(_fork(nested_request), "worker", ["read"])


def test_build_fork_context_v2_allows_provider_routing_options() -> None:
    request = {
        "extra_body": {
            "provider": {
                "order": ["Parent"],
                "allow_fallbacks": False,
                "require_parameters": True,
            }
        }
    }

    result = build_fork_context_v2(_fork(request), "worker", ["read"])

    assert result["request"]["extra_body"] == request["extra_body"]


def test_subagent_api_reexports_v2_builder() -> None:
    from tools.subagent_api import build_fork_context_v2 as exported

    assert exported is build_fork_context_v2
