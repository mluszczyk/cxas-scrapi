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

import asyncio
import unittest
from unittest import mock

import exceptions
import user_simulator


class UserSimulatorTest(unittest.TestCase):

  @mock.patch("google.genai.Client")
  def test_get_next_prompt_constructs_correct_prompt(self, mock_client_class):
    mock_client = mock_client_class.return_value
    mock_response = mock.MagicMock()
    mock_response.text = "Hello world"
    mock_client.models.generate_content.return_value = mock_response

    simulator = user_simulator.UserSimulator(
        scenario_text="Test Scenario with [RANDOM_ID]",
        project="p",
        location="l",
    )

    # Initial prompt
    prompt = asyncio.run(simulator.get_next_prompt(None))

    self.assertEqual(prompt, "Hello world")
    mock_client.models.generate_content.assert_called_once()

  @mock.patch("google.genai.Client")
  def test_get_next_prompt_handles_end(self, mock_client_class):
    mock_client = mock_client_class.return_value
    mock_response = mock.MagicMock()
    mock_response.text = "That is all [[END]]"
    mock_client.models.generate_content.return_value = mock_response

    simulator = user_simulator.UserSimulator("scenario")
    prompt = asyncio.run(simulator.get_next_prompt("agent response"))

    self.assertIsNone(prompt)

  @mock.patch("google.genai.Client")
  def test_get_next_prompt_raises_error_on_empty_response(
      self, mock_client_class
  ):
    mock_client = mock_client_class.return_value
    mock_response = mock.MagicMock()
    mock_response.text = ""  # Empty response
    mock_client.models.generate_content.return_value = mock_response

    simulator = user_simulator.UserSimulator("scenario")

    with self.assertRaises(exceptions.UserSimulatorError):
      asyncio.run(simulator.get_next_prompt(None))
    self.assertEqual(mock_client.models.generate_content.call_count, 3)


if __name__ == "__main__":
  unittest.main()
