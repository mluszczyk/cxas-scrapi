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

import sys
import unittest
from unittest.mock import MagicMock
import types
from dataclasses import dataclass
from typing import Any, List
import tempfile
import shutil

# 1. Mock absl if missing
try:
    import absl
    import absl.testing.absltest
    import absl.testing.parameterized
    import absl.testing.flagsaver
    import absl.flags
    import absl.logging
except ImportError:
    absl = MagicMock()
    sys.modules['absl'] = absl
    sys.modules['absl.testing'] = absl.testing
    sys.modules['absl.testing.absltest'] = absl.testing.absltest
    sys.modules['absl.testing.parameterized'] = absl.testing.parameterized
    sys.modules['absl.testing.flagsaver'] = absl.testing.flagsaver
    sys.modules['absl.flags'] = absl.flags
    sys.modules['absl.logging'] = absl.logging

    # Custom flag implementation
    class Flag:
        def __init__(self, name, default, required=False):
            self.name = name
            self.default = default
            self._value = default
            self.required = required

        @property
        def value(self):
            return self._value

        @value.setter
        def value(self, val):
            self._value = val

    class Flags:
        def __init__(self):
            self._flags = {}
            
        def DEFINE_string(self, name, default, help=None, required=False):
            flag = Flag(name, default, required)
            self._flags[name] = flag
            return flag
            
        def DEFINE_integer(self, name, default, help=None, required=False):
            flag = Flag(name, default, required)
            self._flags[name] = flag
            return flag
            
        def DEFINE_bool(self, name, default, help=None, required=False):
            flag = Flag(name, default, required)
            self._flags[name] = flag
            return flag

        def DEFINE_enum(self, name, default, enum_values, help=None, required=False):
            flag = Flag(name, default, required)
            self._flags[name] = flag
            return flag
            
        def __getattr__(self, name):
            if name == 'FLAGS':
                return self
            if name in self._flags:
                return self._flags[name]
            raise AttributeError(name)
            
        def __call__(self, argv, *args, **kwargs):
            return argv

    class FlagError(Exception):
        pass

    FLAGS = Flags()
    absl.flags.FLAGS = FLAGS
    absl.flags.DEFINE_string = FLAGS.DEFINE_string
    absl.flags.DEFINE_integer = FLAGS.DEFINE_integer
    absl.flags.DEFINE_bool = FLAGS.DEFINE_bool
    absl.flags.DEFINE_enum = FLAGS.DEFINE_enum
    absl.flags.Error = FlagError

    # Implement flagsaver
    class FakeFlagSaver:
        def __init__(self, **flag_values):
            self.flag_values = flag_values
            self.old_values = {}

        def __enter__(self):
            for name, value in self.flag_values.items():
                if name in FLAGS._flags:
                    self.old_values[name] = FLAGS._flags[name].value
                    FLAGS._flags[name].value = value
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            for name, value in self.old_values.items():
                FLAGS._flags[name].value = value

    absl.testing.flagsaver.flagsaver = FakeFlagSaver

    # Custom TestCase that implements absl-specific methods like create_tempdir
    class AbslFakeTestCase(unittest.TestCase):
        def setUp(self):
            super().setUp()
            self._tempdirs = []
            
        def tearDown(self):
            for d in self._tempdirs:
                shutil.rmtree(d, ignore_errors=True)
            super().tearDown()
            
        def create_tempdir(self):
            temp_dir = tempfile.mkdtemp()
            self._tempdirs.append(temp_dir)
            
            class TempDir:
                def __init__(self, path):
                    self.full_path = path
            return TempDir(temp_dir)

        def assertLen(self, container, expected_len, msg=None):
            self.assertEqual(len(container), expected_len, msg)

    absl.testing.absltest.TestCase = AbslFakeTestCase

    # Parameterized TestCase implementation
    class ParameterizedTestCase(AbslFakeTestCase):
        @classmethod
        def __init_subclass__(cls, **kwargs):
            super().__init_subclass__(**kwargs)
            for name, value in list(cls.__dict__.items()):
                if hasattr(value, '_parameter_sets'):
                    parameter_sets = value._parameter_sets
                    delattr(value, '_parameter_sets')
                    for p in parameter_sets:
                        if isinstance(p, dict):
                            testcase_name = p.get('testcase_name')
                            func_params = {k: v for k, v in p.items() if k != 'testcase_name'}
                            
                            def make_test_method(func, params):
                                def test_method(self):
                                    return func(self, **params)
                                return test_method
                            
                            new_name = f"{name}_{testcase_name}"
                            setattr(cls, new_name, make_test_method(value, func_params))
                    
                    # Remove the original parameterized method
                    delattr(cls, name)

    absl.testing.parameterized.TestCase = ParameterizedTestCase

    # Decorator
    def named_parameters(*parameter_sets):
        def decorator(func):
            func._parameter_sets = parameter_sets
            return func
        return decorator
    absl.testing.parameterized.named_parameters = named_parameters

# Ensure 'google' module exists in sys.modules
try:
    import google
except ImportError:
    google = types.ModuleType('google')
    sys.modules['google'] = google

# Mock google.auth if missing
try:
    import google.auth
except ImportError:
    google_auth = MagicMock()
    mock_credentials = MagicMock()
    mock_credentials.token = "mock-gcp-token-from-conftest"
    mock_credentials.valid = True
    google_auth.default.return_value = (mock_credentials, "mock-project-id")
    sys.modules['google.auth'] = google_auth
    sys.modules['google.auth.transport'] = google_auth.transport
    sys.modules['google.auth.transport.requests'] = google_auth.transport.requests
    setattr(google, 'auth', google_auth)

# Mock google.antigravity if missing
try:
    import google.antigravity
except ImportError:
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
    sys.modules['google.antigravity'] = google_antigravity
    sys.modules['google.antigravity.hooks'] = google_antigravity.hooks
    google_antigravity.LocalAgentConfig = LocalAgentConfig
    google_antigravity.Agent = MagicMock()
    setattr(google, 'antigravity', google_antigravity)

# Mock google.genai if missing
try:
    import google.genai
except ImportError:
    google_genai = MagicMock()
    sys.modules['google.genai'] = google_genai
    setattr(google, 'genai', google_genai)

# Mock markdown if missing
try:
    import markdown
except ImportError:
    mock_markdown = MagicMock()
    mock_markdown.markdown = lambda text, *args, **kwargs: text
    sys.modules['markdown'] = mock_markdown
