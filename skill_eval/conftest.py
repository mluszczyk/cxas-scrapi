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

"""Test configuration and global stubs."""

import sys
from unittest.mock import MagicMock
from dataclasses import dataclass
from typing import Any, List

import google

# Stub google.antigravity since it is an internal library not on PyPI
@dataclass
class LocalAgentConfig:
    workspaces: List[str] = None
    policies: List[Any] = None
    model: str = None
    system_instructions: str = None
    vertex: bool = False
    project: str = None
    location: str = None
    skills_paths: List[str] = None

google_antigravity = MagicMock()
google_antigravity.LocalAgentConfig = LocalAgentConfig
google_antigravity.Agent = MagicMock()

sys.modules["google.antigravity"] = google_antigravity
sys.modules["google.antigravity.hooks"] = google_antigravity.hooks

# Add it to the google namespace module
setattr(google, "antigravity", google_antigravity)
