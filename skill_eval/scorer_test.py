# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Tests for rubric scorer."""

import asyncio
from absl.testing import absltest
from google import genai

from skill_eval import scenario, scorer


class FakeResponse:
    def __init__(self, text):
        self.text = text


class ScorerTest(absltest.TestCase):
    def test_score_calls_gemini_and_parses_json(self):
        response_text = (
            '{"scores": [{"criteria": "C1", "score": 2, "reasoning": "r"}],'
            ' "summary": "s"}'
        )
        
        calls = []
        
        class FakeClient:
            def __init__(self, *args, **kwargs):
                self.models = self
                
            def generate_content(self, model, contents, config=None):
                calls.append(self)
                self.called_model = model
                self.called_contents = contents
                self.called_config = config
                return FakeResponse(response_text)

        original_client = genai.Client
        genai.Client = FakeClient
        self.addCleanup(setattr, genai, 'Client', original_client)

        scen = scenario.Scenario(
            name="test",
            text="dummy",
            prompt="dummy",
            rubric=[
                scenario.Rubric(
                    criteria="C1", perfect="perfect", good="good", failed="fail"
                )
            ],
            assets=[],
        )
        s = scorer.Scorer(project="p")

        result = asyncio.run(
            s.grade_conversation(
                scen,
                [
                    scorer.ScorerTurn(
                        user_message="hi",
                        agent_response="ok",
                        tool_interactions=[],
                    )
                ],
            )
        )

        self.assertEqual(result.total_score, 2)
        self.assertEqual(result.scores[0].criteria, "C1")
        self.assertEqual(result.summary, "s")
        
        # Verify the call to the client
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].called_model, "gemini-3.1-pro-preview")
        self.assertIn("RUBRIC CRITERIA:", calls[0].called_contents)


if __name__ == "__main__":
    absltest.main()
