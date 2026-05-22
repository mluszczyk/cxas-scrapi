# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""User Simulator for automated agent benchmarking."""

import asyncio
import json
import os
import random
import string
import time
from typing import Any, Dict, Final, List, Optional

from absl import logging
import benchmark
import exceptions
from google import genai

# Ensure SSL certificates are found for Vertex AI client
if "SSL_CERT_FILE" not in os.environ:
  for _path in [
      "/etc/ssl/certs/ca-certificates.crt",
      "/etc/pki/tls/certs/ca-bundle.crt",
  ]:
    if os.path.exists(_path):
      os.environ["SSL_CERT_FILE"] = _path
      break

_DEFAULT_MODEL: Final[str] = "gemini-3.5-flash"
_RANDOM_ID_LENGTH: Final[int] = 7


class UserSimulator(benchmark.UserSimulatorProtocol):
  """Simulates a user interacting with a chatbot based on a scenario."""

  def __init__(
      self,
      scenario_text: str,
      project: str | None = None,
      location: str | None = "us-central1",
      model_name: str = _DEFAULT_MODEL,
  ):
    """Initializes the simulator.

    Args:
      scenario_text: The YAML text describing the test scenario.
      project: GCP Project ID for Gemini calls.
      location: GCP Location for Gemini calls.
      model_name: The Gemini model to use for simulation.
    """
    self._model_name = model_name
    self._history: List[Dict[str, Any]] = []

    # Inject unique ID into scenario to avoid resource name collisions
    random_id = "".join(
        random.choices(
            string.ascii_lowercase + string.digits, k=_RANDOM_ID_LENGTH
        )
    )
    self._scenario = scenario_text.replace("[RANDOM_ID]", random_id)

    if project and location:
      self._client = genai.Client(
          vertexai=True, project=project, location=location
      )
    else:
      self._client = genai.Client()

  async def get_next_prompt(
      self, agent_last_response: Optional[str]
  ) -> Optional[str]:
    """Determines the user's next action based on the agent's last response."""
    is_start = agent_last_response is None

    prompt = self._build_simulation_prompt(agent_last_response)

    # Run the blocking Gemini call in a thread pool to avoid freezing the loop
    loop = asyncio.get_running_loop()
    response_text = await loop.run_in_executor(None, self._call_gemini, prompt)

    if not is_start:
      self._history.append({
          "role": "model",
          "parts": [{"text": agent_last_response or "(Start)"}],
      })

    if response_text and "[[END]]" in response_text:
      logging.info("[UserSimulator] Scenario satisfied.")
      return None

    logging.info("[UserSimulator] Next action: %s", response_text)
    self._history.append({"role": "user", "parts": [{"text": response_text}]})
    return response_text

  def _build_simulation_prompt(self, last_response: Optional[str]) -> str:
    """Constructs the system prompt for the simulator LLM."""
    return f"""
You are a User testing a Chatbot.
Your goal is to follow the SCENARIO below strictly.
You will interact with the Chatbot to test if it behaves correctly.

SCENARIO:
{self._scenario}

CURRENT CONVERSATION HISTORY:
{json.dumps(self._history, indent=2)}

LAST AGENT RESPONSE:
{json.dumps(last_response) if last_response else "(Start of conversation)"}

INSTRUCTIONS:
- You must act as the User described in the SCENARIO.
- Output ONLY your next message to the Chatbot as a plain text string.
- If the SCENARIO says the conversation ends or you are satisfied, output exactly: "[[END]]"
- If you spot a critical failure (e.g. refusal to follow scenario), output "[[FAIL: reason]]". This will be recorded as debug info.
"""

  def _call_gemini(self, prompt: str) -> str:
    """Executes Gemini generation with retries."""
    max_retries = 3
    for attempt in range(1, max_retries + 1):
      try:
        start_time = time.time()
        response = self._client.models.generate_content(
            model=self._model_name,
            contents=prompt,
            config={
                "temperature": 0.1,  # Low temperature for consistency
                "max_output_tokens": 1024,
            },
        )
        if not response.text:
          logging.error("[UserSimulator] Raw response: %r", response)
          raise exceptions.UserSimulatorError("Empty response from Gemini")

        elapsed = time.time() - start_time
        logging.info("[UserSimulator] Gemini responded in %.2fs.", elapsed)
        return response.text.strip()

      except Exception:
        logging.exception("[UserSimulator] Attempt %d failed", attempt)
        if attempt == max_retries:
          raise
        time.sleep(attempt)

    raise exceptions.UserSimulatorError(
        "UserSimulator failed after maximum retries."
    )
