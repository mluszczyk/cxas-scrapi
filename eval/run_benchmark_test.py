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
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

import benchmark
import run_benchmark
import scenario


class FakeAgentHead(benchmark.BaseAgentHead):

  def __init__(self, name: str):
    self._name = name

  async def send_message(self, message: str) -> str:
    return f"Response to {message}"

  def get_tool_calls_count_last_turn(self) -> int:
    return 0

  def get_tool_interactions_last_turn(self) -> list[benchmark.ToolInteraction]:
    return []

  async def reset(self) -> None:
    pass

  @property
  def name(self) -> str:
    return self._name

  def get_log_files(self) -> list[str]:
    return []

  async def close(self) -> None:
    pass


class BenchmarkRunnerTest(unittest.TestCase):

  def test_init_sets_scenario_fields(self):
    scen = scenario.Scenario(
        name="test", text="dummy", context="dummy", steps=[], rubric=[]
    )
    runner = benchmark.BenchmarkRunner(
        scen=scen,
        simulator_factory=lambda x: None,  # type: ignore[arg-type,return-value]
    )
    self.assertEqual(runner.scenario_name, "test")
    self.assertEqual(runner.scenario_text, "dummy")
    self.assertEqual(runner.scenario, scen)


class BenchmarkOrchestratorTest(unittest.TestCase):

  def setUp(self):
    super().setUp()
    self.test_dir = tempfile.mkdtemp()

  def tearDown(self):
    shutil.rmtree(self.test_dir)
    super().tearDown()

  @mock.patch("google.genai.Client")
  def test_orchestrator_updates_reports_on_progress(self, mock_client_class):
    orchestrator = run_benchmark.BenchmarkOrchestrator(
        report_dir=self.test_dir, location="us-central1"
    )

    # Mock runner
    mock_runner = mock.MagicMock(spec=benchmark.BenchmarkRunner)
    mock_runner.scenario_name = "test.yaml"
    mock_runner.scenario_text = "# Scenario\nHello"
    mock_runner.run.return_value = benchmark.ConversationResult(
        scenario_name="test.yaml",
        scenario_text="# Scenario\nHello",
        head_name="TestHead",
        turns=1,
        total_time_sec=1.0,
        messages=[],
        turn_metrics=[],
        status=benchmark.ExecutionStatus.FINISHED,
        success=True,
    )

    head = FakeAgentHead("TestHead")
    asyncio.run(orchestrator.run_head(head, mock_runner))

    # Verify artifacts
    self.assertTrue(os.path.exists(os.path.join(self.test_dir, "index.html")))
    self.assertTrue(
        os.path.exists(os.path.join(self.test_dir, "test_yaml_TestHead.json"))
    )




if __name__ == "__main__":
  unittest.main()
