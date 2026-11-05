"""Anthropic Claude LLM provider implementation using httpx."""

import json
import os
import time
from contextlib import suppress
from typing import Any

import httpx
from pydantic import BaseModel

from backend.app.core.errors import ModelError, TransientError
from backend.app.llm.base import BaseLLMProvider, LLMMessage, LLMResponse, LLMToolCall


class AnthropicLLMProvider(BaseLLMProvider):
    def __init__(self, api_key: str | None = None, model: str = "claude-3-5-sonnet-20241022"):
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self.model = model
        self.base_url = "https://api.anthropic.com/v1/messages"

    async def generate(
        self,
        messages: list[LLMMessage],
        tools: list[dict[str, Any]] | None = None,
        response_schema: type[BaseModel] | None = None,
        temperature: float = 0.0,
    ) -> LLMResponse:
        if not self.api_key:
            raise ModelError("Anthropic API key is not configured")

        # Format system prompt and conversation messages
        system_prompt = next((m.content for m in messages if m.role == "system"), "")
        anthropic_messages: list[dict[str, Any]] = []

        for m in messages:
            if m.role == "system":
                continue
            if m.role == "user":
                anthropic_messages.append({"role": "user", "content": m.content})
            elif m.role == "assistant":
                content_blocks: list[dict[str, Any]] = []
                if m.content:
                    content_blocks.append({"type": "text", "text": m.content})
                if m.tool_calls:
                    for tc in m.tool_calls:
                        content_blocks.append(
                            {"type": "tool_use", "id": tc["id"], "name": tc["name"], "input": tc["arguments"]}
                        )
                anthropic_messages.append({"role": "assistant", "content": content_blocks or m.content})
            elif m.role == "tool":
                anthropic_messages.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": m.tool_call_id or "unknown",
                                "content": m.content,
                            }
                        ],
                    }
                )

        payload: dict[str, Any] = {
            "model": self.model,
            "max_tokens": 4096,
            "temperature": temperature,
            "messages": anthropic_messages,
        }
        if system_prompt:
            payload["system"] = system_prompt

        if tools:
            payload["tools"] = [
                {"name": t["name"], "description": t["description"], "input_schema": t["input_schema"]}
                for t in tools
            ]

        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

        start_time = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                res = await client.post(self.base_url, json=payload, headers=headers)
                latency_ms = (time.perf_counter() - start_time) * 1000

                if res.status_code in (429, 500, 502, 503, 504):
                    raise TransientError(f"Anthropic returned status {res.status_code}: {res.text}")
                if res.status_code != 200:
                    raise ModelError(f"Anthropic API error {res.status_code}: {res.text}")

                data = res.json()
                text_content = ""
                tool_calls: list[LLMToolCall] = []

                for block in data.get("content", []):
                    if block.get("type") == "text":
                        text_content += block.get("text", "")
                    elif block.get("type") == "tool_use":
                        tool_calls.append(
                            LLMToolCall(
                                id=block["id"],
                                name=block["name"],
                                arguments=block.get("input", {}),
                            )
                        )

                usage = data.get("usage", {})
                tokens_in = usage.get("input_tokens", 0)
                tokens_out = usage.get("output_tokens", 0)
                total = tokens_in + tokens_out
                cost = (tokens_in * 3.0 / 1_000_000) + (tokens_out * 15.0 / 1_000_000)

                # Try parsing structured output if requested
                structured = None
                if response_schema and text_content:
                    with suppress(json.JSONDecodeError):
                        structured = json.loads(text_content)

                return LLMResponse(
                    content=text_content,
                    tool_calls=tool_calls,
                    structured_output=structured,
                    prompt_tokens=tokens_in,
                    completion_tokens=tokens_out,
                    total_tokens=total,
                    estimated_cost_usd=cost,
                    latency_ms=latency_ms,
                )
        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            raise TransientError(f"Connection failure to Anthropic: {str(exc)}") from exc
