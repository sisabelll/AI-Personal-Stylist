import time
import json
from typing import List, Dict, Optional, Type, Any, Union, TypeVar
from openai import OpenAI, RateLimitError
from pydantic import BaseModel
from core.config import Config

T = TypeVar("T", bound=BaseModel)

class OpenAIClient:
    """Thin wrapper around the OpenAI client with simple retry/backoff."""
    def __init__(self):
        self.client = OpenAI(api_key=Config.OPENAI_API_KEY)

    def call_api(
        self,
        model: str,
        messages: List[Dict[str, str]],
        temperature: float = 0.1,
        max_tokens: int = 2000,
        json_mode: bool = False,
        response_model: Optional[Type[BaseModel]] = None,
    ) -> Union[str, Dict[str, Any], BaseModel]:
        """
        Legacy method:
        - If response_model is provided: returns parsed Pydantic object
        - Else returns raw text content (or JSON string if json_mode)
        """
        if not self.client:
            raise RuntimeError("OpenAI client not configured. Set OPENAI_API_KEY.")

        params: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        if json_mode and not response_model:
            params["response_format"] = {"type": "json_object"}

        for attempt in range(3):
            try:
                if response_model:
                    completion = self.client.beta.chat.completions.parse(
                        **params,
                        response_format=response_model,
                    )
                    parsed = completion.choices[0].message.parsed
                    if parsed is None:
                        raise RuntimeError("Parsed response was None (schema parse failed).")
                    return parsed

                response = self.client.chat.completions.create(**params)
                content = response.choices[0].message.content
                if content is None:
                    raise RuntimeError("Model returned empty content.")
                return content

            except RateLimitError:
                wait = 2 ** attempt
                print(f"⚠️ Rate limit hit, retrying in {wait}s...")
                time.sleep(wait)
            except Exception as e:
                print(f"❌ API Call Failed: {e}")
                if attempt == 2:
                    raise

        raise RuntimeError("OpenAI requests failed after retries")

    def structured(
        self,
        *,
        model: str,
        system: str,
        user: Union[str, dict],
        response_model: Type[T],
        temperature: float = 0.3,
        max_tokens: int = 2500,
    ) -> T:
        """
        Schema-native helper.
        Always returns a validated Pydantic object of type response_model.
        """
        if isinstance(user, dict):
            # Keep dicts as JSON-like string for the model
            user_content = json.dumps(user, ensure_ascii=False)
        else:
            user_content = user

        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user_content},
        ]

        parsed = self.call_api(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_model=response_model,
        )
        return parsed