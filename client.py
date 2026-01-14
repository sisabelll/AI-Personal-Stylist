import os
import time
from typing import List, Dict, Optional, Type, Any, Union
from openai import OpenAI, RateLimitError
from pydantic import BaseModel

class OpenAIClient:
    """Thin wrapper around the OpenAI client with simple retry/backoff.

    If no API key is available, `client` will be None and `call_api` will raise a
    clear RuntimeError to avoid accidental requests.
    """
    def __init__(self, api_key: Optional[str] = None):
        api_key = api_key or os.getenv('OPENAI_API_KEY')
        if not api_key:
            print('Warning: OPENAI_API_KEY not set; OpenAI calls are disabled.')
            self.client = None
        else:
            self.client = OpenAI(api_key=api_key)

    def call_api(self, 
        model: str, 
        messages: List[Dict], 
        temperature: float = 0.1, 
        max_tokens: int = 2000, 
        json_mode: bool = False,
        response_model: Optional[Type[BaseModel]] = None
    ) -> Union[str, Dict[str, Any]]:
        if not self.client:
            raise RuntimeError('OpenAI client not configured. Set OPENAI_API_KEY or provide api_key.')

        params = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens
        }

        if json_mode:
            params["response_format"] = {"type": "json_object"}
            
        for attempt in range(3):
            try:
                if response_model:
                    # Note: Structured Outputs require specific models (gpt-4o-2024-08-06 or later)
                    completion = self.client.beta.chat.completions.parse(
                        **params,
                        response_format=response_model,
                    )

                    # Convert the valid Pydantic object back to a standard Python Dict
                    return completion.choices[0].message.parsed.model_dump()
                else:
                    if json_mode:
                        params["response_format"] = {"type": "json_object"}
                    response = self.client.chat.completions.create(**params)
                    return response.choices[0].message.content
            except RateLimitError:
                wait = 2 ** attempt
                print(f"⚠️ Rate limit hit, retrying in {wait}s...")
                time.sleep(wait)
            except Exception as e:
                # Catch parse errors or other API issues
                print(f"❌ API Call Failed: {e}")
                if attempt == 2: raise e
        raise RuntimeError('OpenAI requests failed after retries')