"""Nvidia NIM chat-completions gateway."""

from typing import Any

import requests


NVIDIA_NIM_BASE_URL = "https://integrate.api.nvidia.com/v1"


class NvidiaModelGatewayError(RuntimeError):
    """Base exception for Nvidia gateway failures."""


class MissingNvidiaApiKeyError(NvidiaModelGatewayError):
    """Raised when no Nvidia API key is configured."""


class NvidiaRequestTimeoutError(NvidiaModelGatewayError):
    """Raised when the Nvidia request times out."""


class NvidiaMalformedResponseError(NvidiaModelGatewayError):
    """Raised when Nvidia returns an unexpected response shape."""


class NvidiaNon200StatusError(NvidiaModelGatewayError):
    """Raised when Nvidia returns a non-200 response."""


def call_nvidia_llm(
    model: str,
    messages: list[dict[str, str]],
    max_tokens: int,
    temperature: float,
    api_key: str,
    timeout_seconds: int,
) -> dict[str, Any]:
    """Call Nvidia NIM chat completions and return the parsed JSON response.

    The API key is only used in the Authorization header and is never included
    in raised exception messages.
    """
    if not api_key:
        raise MissingNvidiaApiKeyError("Nvidia API key is missing.")

    try:
        response = requests.post(
            f"{NVIDIA_NIM_BASE_URL}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
            },
            timeout=timeout_seconds,
        )
    except requests.Timeout as exc:
        raise NvidiaRequestTimeoutError("Nvidia NIM request timed out.") from exc

    if response.status_code != 200:
        raise NvidiaNon200StatusError(
            f"Nvidia NIM returned non-200 status code {response.status_code}."
        )

    try:
        payload = response.json()
    except ValueError as exc:
        raise NvidiaMalformedResponseError(
            "Nvidia NIM returned a response that was not valid JSON."
        ) from exc

    _validate_chat_completion_payload(payload)
    return dict(payload)


def _validate_chat_completion_payload(payload: Any) -> None:
    if not isinstance(payload, dict):
        raise NvidiaMalformedResponseError("Nvidia NIM response was not an object.")
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise NvidiaMalformedResponseError("Nvidia NIM response did not include choices.")
    first_choice = choices[0]
    if not isinstance(first_choice, dict):
        raise NvidiaMalformedResponseError("Nvidia NIM choice was malformed.")
    message = first_choice.get("message")
    if not isinstance(message, dict):
        raise NvidiaMalformedResponseError("Nvidia NIM choice did not include a message.")
    content = message.get("content")
    if not isinstance(content, str):
        raise NvidiaMalformedResponseError("Nvidia NIM message content was missing.")
