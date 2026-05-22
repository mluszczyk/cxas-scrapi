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

import unittest

import scenario


class ScenarioTest(unittest.TestCase):

  def test_from_yaml_valid(self):
    yaml_text = """
context: This is context.
steps:
  - Step 1
  - Step 2
rubric:
  - criteria: C1
    perfect: p
    good: g
    failed: f
"""
    s = scenario.Scenario.from_yaml("test_scenario", yaml_text)
    expected_text = """This is context.

## Steps
- Step 1
- Step 2

## Rubric
- **Criteria**: C1
  - **Perfect**: p
  - **Good**: g
  - **Failed**: f"""
    expected = scenario.Scenario(
        name="test_scenario",
        text=expected_text,
        context="This is context.",
        steps=["Step 1", "Step 2"],
        rubric=[
            scenario.Rubric(criteria="C1", perfect="p", good="g", failed="f")
        ],
    )
    self.assertEqual(s, expected)

  def test_from_yaml_missing_context(self):
    yaml_text = """
steps:
  - Step 1
rubric:
  - criteria: C1
"""
    with self.assertRaisesRegex(ValueError, "Missing 'context'"):
      scenario.Scenario.from_yaml("test", yaml_text)

  def test_from_yaml_invalid_context_type(self):
    yaml_text = """
context: 123
steps:
  - Step 1
rubric:
  - criteria: C1
"""
    with self.assertRaisesRegex(
        ValueError, "Invalid 'context'.*expected string"
    ):
      scenario.Scenario.from_yaml("test", yaml_text)

  def test_from_yaml_invalid_steps_type(self):
    yaml_text = """
context: This is context.
steps: "Step 1"
rubric:
  - criteria: C1
"""
    with self.assertRaisesRegex(ValueError, "Invalid 'steps'.*expected list"):
      scenario.Scenario.from_yaml("test", yaml_text)

  def test_from_yaml_empty_rubric(self):
    yaml_text = """
context: This is context.
steps:
  - Step 1
rubric: []
"""
    with self.assertRaisesRegex(ValueError, "Empty rubric"):
      scenario.Scenario.from_yaml("test", yaml_text)

  def test_from_yaml_invalid_assets_type(self):
    yaml_text = """
context: This is context.
steps:
  - Step 1
rubric:
  - criteria: C1
    perfect: p
assets: "asset1.txt"
"""
    with self.assertRaisesRegex(ValueError, "Invalid 'assets'.*expected list"):
      scenario.Scenario.from_yaml("test", yaml_text)

  def test_from_yaml_edge_cases(self):
    yaml_text = """
context: This is context.
steps:
  - Step 1
rubric:
  - criteria: "C1 with | pipe"
    perfect: |
      p with
      newline
assets: null
"""
    s = scenario.Scenario.from_yaml("test_edge", yaml_text)
    self.assertEqual(s.assets, [])
    expected_text = """This is context.

## Steps
- Step 1

## Rubric
- **Criteria**: C1 with | pipe
  - **Perfect**: p with
                 newline
  - **Good**: Met only after nudging or with errors
  - **Failed**: Not met"""
    self.assertEqual(s.text, expected_text)


if __name__ == "__main__":
  unittest.main()
