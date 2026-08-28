"""Model orchestration gateway for all LLM, VLM, and image-provider calls."""

import json
import re
from typing import Any, Literal, get_args

from config.settings import settings
from integrations import nvidia_model_gateway


TaskType = Literal[
    "outreach_draft",
    "followup_draft",
    "content_post_draft",
    "refinement_analysis",
    "signal_semantic_scoring",
    "content_opportunity_generation",
    "content_package_generation",
    "content_hook_generation",
    "carousel_generation",
    "caption_generation",
    "content_hook_regeneration",
    "content_personalization_revision",
    "content_analytical_revision",
    "content_humor_revision",
    "content_risk_review",
    "image_brief_generation",
]
SUPPORTED_TASK_TYPES = set(get_args(TaskType))


class ModelOrchestrationError(RuntimeError):
    """Base exception for model orchestration failures."""


class UnsupportedTaskTypeError(ModelOrchestrationError):
    """Raised when an unknown task type is requested."""


class ModelResponseValidationError(ModelOrchestrationError):
    """Raised when a model response cannot satisfy the expected schema."""


class ModelOrchestrationAgent:
    """Route all model-like requests through a single mockable boundary.

    Purpose:
        Keep specialist agents, Telegram handlers, and business logic from
        calling model providers directly.
    Inputs:
        A supported task type, prompt, optional expected schema, and explicit
        mock/fallback controls.
    Outputs:
        A metadata-wrapped response containing deterministic mock content or a
        repaired/validated model result.
    """

    def run_task(
        self,
        task_type: TaskType,
        prompt: str,
        expected_schema: dict[str, Any] | None = None,
        mock_mode: bool | None = None,
        fallback_to_mock: bool = True,
    ) -> dict[str, Any]:
        """Run a model task with mock-first defaults and safe fallback."""
        self._validate_task_type(task_type)
        use_mock = settings.mock_mode if mock_mode is None else mock_mode

        if use_mock:
            return self._wrap_response(
                task_type=task_type,
                mode="mock",
                fallback_used=False,
                result=self._mock_result(task_type, prompt, expected_schema),
            )

        try:
            raw_response = nvidia_model_gateway.call_nvidia_llm(
                model=settings.nvidia_model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=settings.nvidia_max_tokens,
                temperature=settings.nvidia_temperature,
                api_key=settings.nvidia_api_key,
                timeout_seconds=settings.nvidia_timeout_seconds,
            )
            result = self._extract_result(raw_response)
            result = self._repair_and_validate_result(result, expected_schema)
            return self._wrap_response(
                task_type=task_type,
                mode="model",
                fallback_used=False,
                result=result,
            )
        except Exception as exc:
            if not fallback_to_mock:
                raise
            return self._wrap_response(
                task_type=task_type,
                mode="mock",
                fallback_used=True,
                fallback_reason=_safe_error_message(exc),
                result=self._mock_result(task_type, prompt, expected_schema),
            )

    def _validate_task_type(self, task_type: str) -> None:
        if task_type not in SUPPORTED_TASK_TYPES:
            allowed = ", ".join(sorted(SUPPORTED_TASK_TYPES))
            raise UnsupportedTaskTypeError(
                f"Unsupported task_type '{task_type}'. Allowed values: {allowed}."
            )

    def _mock_result(
        self,
        task_type: str,
        prompt: str,
        expected_schema: dict[str, Any] | None,
    ) -> dict[str, Any]:
        if expected_schema is not None:
            return _mock_from_schema(expected_schema)
        return {
            "text": f"Mock response for {task_type}.",
            "prompt": prompt,
        }

    def _extract_result(self, response: dict[str, Any]) -> Any:
        try:
            return response["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ModelResponseValidationError(
                "Model response did not include chat message content."
            ) from exc

    def _repair_and_validate_result(
        self,
        result: Any,
        expected_schema: dict[str, Any] | None,
    ) -> dict[str, Any]:
        repaired = _repair_json_like_content(result)
        if not isinstance(repaired, dict):
            if expected_schema is None:
                return {"text": str(repaired)}
            raise ModelResponseValidationError("Model result was not a JSON object.")

        if expected_schema is None:
            return repaired

        missing_keys = [key for key in expected_schema if key not in repaired]
        if missing_keys:
            raise ModelResponseValidationError(
                f"Model result missing expected keys: {', '.join(missing_keys)}."
            )
        return repaired

    def _wrap_response(
        self,
        task_type: str,
        mode: Literal["mock", "model"],
        fallback_used: bool,
        result: dict[str, Any],
        fallback_reason: str | None = None,
    ) -> dict[str, Any]:
        response: dict[str, Any] = {
            "task_type": task_type,
            "mode": mode,
            "fallback_used": fallback_used,
            "result": result,
        }
        if fallback_reason is not None:
            response["fallback_reason"] = fallback_reason
        return response


def _mock_from_schema(expected_schema: dict[str, Any]) -> dict[str, Any]:
    return {key: _mock_value(value) for key, value in expected_schema.items()}


def _mock_value(schema_value: Any) -> Any:
    if isinstance(schema_value, dict):
        return _mock_from_schema(schema_value)
    if schema_value is list or isinstance(schema_value, list):
        return []
    if schema_value is str or isinstance(schema_value, str):
        return "mock"
    if schema_value is int or isinstance(schema_value, int):
        return 0
    if schema_value is float or isinstance(schema_value, float):
        return 0.0
    if schema_value is bool or isinstance(schema_value, bool):
        return False
    return None


def _repair_json_like_content(content: Any) -> Any:
    if not isinstance(content, str):
        return content
    stripped = content.strip()
    fenced_match = re.search(
        r"```(?:json)?\s*(?P<json>.*?)\s*```",
        stripped,
        flags=re.DOTALL,
    )
    if fenced_match is not None:
        stripped = fenced_match.group("json").strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        return content


def _safe_error_message(exc: Exception) -> str:
    message = str(exc)
    api_key = settings.nvidia_api_key
    if api_key:
        message = message.replace(api_key, "[redacted]")
    return message
