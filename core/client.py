import os
import time
from typing import List, Dict, Optional, Type, Any, Union
from openai import OpenAI, RateLimitError
from pydantic import BaseModel
from core.config import Config

class OpenAIClient:
    """Thin wrapper around the OpenAI client with simple retry/backoff."""
    def __init__(self):
        # We assume Config handles the key internally or environment variable
        self.client = OpenAI(api_key=Config.OPENAI_API_KEY)

    def call_api(self, 
        model: str, 
        messages: List[Dict], 
        temperature: float = 0.1, 
        max_tokens: int = 2000, 
        json_mode: bool = False,
        response_model: Optional[Type[BaseModel]] = None
    ) -> Union[str, Dict[str, Any], BaseModel]:
        
        if not self.client:
            raise RuntimeError('OpenAI client not configured. Set OPENAI_API_KEY.')

        params = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens
        }

        # If strict JSON mode is requested for standard calls
        if json_mode and not response_model:
            params["response_format"] = {"type": "json_object"}
            
        for attempt in range(3):
            try:
                if response_model:
                    completion = self.client.beta.chat.completions.parse(
                        **params,
                        response_format=response_model,
                    )

                    return completion.choices[0].message.parsed
                
                else:
                    # 🗣️ STANDARD TEXT/JSON
                    response = self.client.chat.completions.create(**params)
                    return response.choices[0].message.content
                    
            except RateLimitError:
                wait = 2 ** attempt
                print(f"⚠️ Rate limit hit, retrying in {wait}s...")
                time.sleep(wait)
            except Exception as e:
                print(f"❌ API Call Failed: {e}")
                if attempt == 2: raise e
                
        raise RuntimeError('OpenAI requests failed after retries')