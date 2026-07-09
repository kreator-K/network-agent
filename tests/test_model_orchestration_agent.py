"""Tests for ModelOrchestrationAgent and Nvidia gateway routing."""

from types import SimpleNamespace

import pytest
import pytest_mock

from agents import model_orchestration_agent as orchestration_module
from agents.model_orchestration_agent import (
    ModelOrchestrationAgent,
    UnsupportedTaskTypeError,
)
from integrations import nvidia_model_gateway


EXPECTED_SCHEMA = {"draft": str, "safety_notes": list}


def _settings(
    *,
    mock_mode: bool = True,
    api_key: str = "test-key",
) -> SimpleNamespace:
    return SimpleNamespace(
        mock_mode=mock_mode,
        nvidia_model="test-model",
        nvidia_max_tokens=123,
        nvidia_temperature=0.4,
        nvidia_api_key=api_key,
        nvidia_timeout_seconds=9,
    )


def test_mock_mode_returns_deterministic_response_without_calling_gateway(
    mocker: pytest_mock.MockerFixture,
) -> None:
    gateway = mocker.patch.object(
        orchestration_module.nvidia_model_gateway,
        "call_nvidia_llm",
    )
    mocker.patch.object(orchestration_module, "settings", _settings(mock_mode=True))

    result = ModelOrchestrationAgent().run_task(
        "outreach_draft",
        "Draft intro",
        expected_schema=EXPECTED_SCHEMA,
    )

    assert result == {
        "task_type": "outreach_draft",
        "mode": "mock",
        "fallback_used": False,
        "result": {"draft": "mock", "safety_notes": []},
    }
    gateway.assert_not_called()


def test_real_mode_calls_gateway_with_correct_parameters(
    mocker: pytest_mock.MockerFixture,
) -> None:
    mocker.patch.object(
        orchestration_module,
        "settings",
        _settings(mock_mode=False, api_key="secret-key"),
    )
    gateway = mocker.patch.object(
        orchestration_module.nvidia_model_gateway,
        "call_nvidia_llm",
        return_value={
            "choices": [
                {"message": {"content": '{"draft": "hello", "safety_notes": []}'}}
            ]
        },
    )

    result = ModelOrchestrationAgent().run_task(
        "outreach_draft",
        "Draft intro",
        expected_schema=EXPECTED_SCHEMA,
        mock_mode=False,
    )

    gateway.assert_called_once_with(
        model="test-model",
        messages=[{"role": "user", "content": "Draft intro"}],
        max_tokens=123,
        temperature=0.4,
        api_key="secret-key",
        timeout_seconds=9,
    )
    assert result["mode"] == "model"
    assert result["fallback_used"] is False
    assert result["result"] == {"draft": "hello", "safety_notes": []}


def test_real_mode_falls_back_to_mock_on_timeout(
    mocker: pytest_mock.MockerFixture,
) -> None:
    mocker.patch.object(orchestration_module, "settings", _settings(mock_mode=False))
    mocker.patch.object(
        orchestration_module.nvidia_model_gateway,
        "call_nvidia_llm",
        side_effect=nvidia_model_gateway.NvidiaRequestTimeoutError("request timed out"),
    )

    result = ModelOrchestrationAgent().run_task(
        "followup_draft",
        "Draft follow-up",
        expected_schema=EXPECTED_SCHEMA,
        mock_mode=False,
    )

    assert result["mode"] == "mock"
    assert result["fallback_used"] is True
    assert result["fallback_reason"] == "request timed out"
    assert result["result"] == {"draft": "mock", "safety_notes": []}


def test_real_mode_falls_back_to_mock_on_missing_api_key(
    mocker: pytest_mock.MockerFixture,
) -> None:
    mocker.patch.object(orchestration_module, "settings", _settings(mock_mode=False))
    mocker.patch.object(
        orchestration_module.nvidia_model_gateway,
        "call_nvidia_llm",
        side_effect=nvidia_model_gateway.MissingNvidiaApiKeyError(
            "Nvidia API key is missing."
        ),
    )

    result = ModelOrchestrationAgent().run_task(
        "content_post_draft",
        "Draft post",
        expected_schema={"post": str},
        mock_mode=False,
    )

    assert result["fallback_used"] is True
    assert result["fallback_reason"] == "Nvidia API key is missing."
    assert result["result"] == {"post": "mock"}


def test_real_mode_falls_back_to_mock_on_malformed_response(
    mocker: pytest_mock.MockerFixture,
) -> None:
    mocker.patch.object(orchestration_module, "settings", _settings(mock_mode=False))
    mocker.patch.object(
        orchestration_module.nvidia_model_gateway,
        "call_nvidia_llm",
        return_value={"unexpected": "shape"},
    )

    result = ModelOrchestrationAgent().run_task(
        "refinement_analysis",
        "Analyze",
        expected_schema={"analysis": str},
        mock_mode=False,
    )

    assert result["mode"] == "mock"
    assert result["fallback_used"] is True
    assert "chat message content" in result["fallback_reason"]
    assert result["result"] == {"analysis": "mock"}


def test_fallback_to_mock_false_raises_instead_of_falling_back(
    mocker: pytest_mock.MockerFixture,
) -> None:
    mocker.patch.object(orchestration_module, "settings", _settings(mock_mode=False))
    mocker.patch.object(
        orchestration_module.nvidia_model_gateway,
        "call_nvidia_llm",
        side_effect=nvidia_model_gateway.NvidiaRequestTimeoutError("request timed out"),
    )

    with pytest.raises(nvidia_model_gateway.NvidiaRequestTimeoutError):
        ModelOrchestrationAgent().run_task(
            "outreach_draft",
            "Draft",
            mock_mode=False,
            fallback_to_mock=False,
        )


def test_markdown_fenced_json_is_repaired_before_fallback(
    mocker: pytest_mock.MockerFixture,
) -> None:
    mocker.patch.object(orchestration_module, "settings", _settings(mock_mode=False))
    mocker.patch.object(
        orchestration_module.nvidia_model_gateway,
        "call_nvidia_llm",
        return_value={
            "choices": [
                {
                    "message": {
                        "content": '```json\n{"draft": "fixed", "safety_notes": []}\n```'
                    }
                }
            ]
        },
    )

    result = ModelOrchestrationAgent().run_task(
        "outreach_draft",
        "Draft",
        expected_schema=EXPECTED_SCHEMA,
        mock_mode=False,
    )

    assert result["mode"] == "model"
    assert result["fallback_used"] is False
    assert result["result"] == {"draft": "fixed", "safety_notes": []}


def test_unsupported_task_type_raises_clear_error() -> None:
    with pytest.raises(UnsupportedTaskTypeError, match="Unsupported task_type"):
        ModelOrchestrationAgent().run_task("bad_task", "Prompt")  # type: ignore[arg-type]


def test_api_key_never_appears_in_error_messages_or_logs(
    mocker: pytest_mock.MockerFixture,
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret = "super-secret-api-key"
    mocker.patch.object(
        orchestration_module,
        "settings",
        _settings(mock_mode=False, api_key=secret),
    )
    mocker.patch.object(
        orchestration_module.nvidia_model_gateway,
        "call_nvidia_llm",
        side_effect=RuntimeError(f"provider failed with {secret}"),
    )

    result = ModelOrchestrationAgent().run_task(
        "outreach_draft",
        "Draft",
        expected_schema=EXPECTED_SCHEMA,
        mock_mode=False,
    )

    assert secret not in result["fallback_reason"]
    assert "[redacted]" in result["fallback_reason"]
    assert secret not in caplog.text


def test_response_always_includes_required_metadata_fields(
    mocker: pytest_mock.MockerFixture,
) -> None:
    mocker.patch.object(orchestration_module, "settings", _settings(mock_mode=True))

    result = ModelOrchestrationAgent().run_task("outreach_draft", "Draft")

    assert {"task_type", "mode", "fallback_used", "result"}.issubset(result)
