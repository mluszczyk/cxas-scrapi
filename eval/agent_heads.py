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

"""Agent Head implementations for CES skill benchmarking."""

from __future__ import annotations

import asyncio
import glob
import os
import pathlib
import re
import shutil

# Dynamic alias mapping for internal google3 runtimes
import sys
import textwrap
import uuid
from typing import Final, Sequence

import benchmark
import scenario
import trajectory_extractor
from absl import logging
from google.antigravity import Agent, LocalAgentConfig
from google.antigravity.hooks import policy


class ScaffoldingTestAgent(benchmark.BaseAgentHead):
    """A mock agent head that returns pre-defined scaffolding responses."""

    def __init__(self, scenario_name: str, name: str = "ScaffoldingTestAgent"):
        self._name = name
        self._scenario_name = scenario_name
        self._session_id = uuid.uuid4().hex
        self._turn = 0

    async def send_message(self, message: str) -> str:
        self._turn += 1
        # Simulate a tool call on Turn 2
        if self._turn == 2:
            logging.info("[%s] Simulating background tool call...", self.name)

        return (
            f"Mock response from {self._name} to: {message[:50]}... (Turn"
            f" {self._turn})"
        )

    def get_tool_calls_count_last_turn(self) -> int:
        return 1 if self._turn == 2 else 0

    def get_tool_interactions_last_turn(
        self,
    ) -> Sequence[benchmark.ToolInteraction]:
        if self._turn == 2:
            return [
                benchmark.ToolInteraction(
                    name="mock_tool_call",
                    args={"param": "value"},
                    output='{"status": "ok"}',
                    thought="I should call a tool to verify this.",
                )
            ]
        return []

    def get_events_last_turn(self) -> Sequence[benchmark.TrajectoryEvent]:
        if self._turn == 2:
            return [
                benchmark.ToolCallEvent(
                    call_id="mock_call_1",
                    name="mock_tool_call",
                    args={"param": "value"},
                    source="main",
                ),
                benchmark.ToolResultEvent(
                    call_id="mock_call_1",
                    output='{"status": "ok"}',
                    is_error=False,
                    source="main",
                ),
            ]
        return []

    async def initialize(self) -> None:
        self._turn = 0

    @property
    def name(self) -> str:
        return self._name

    def get_log_files(self) -> Sequence[str]:
        del self  # Unused in this implementation.
        return []

    async def close(self) -> None:
        pass


class AntigravityAgentHead(benchmark.BaseAgentHead):
    """Agent head powered by the public Google Antigravity SDK."""

    _TIMEOUT_SECONDS: Final[int] = 600

    def __init__(
        self,
        scenario_name: str,
        scenario_path: str,
        *,
        ls_address: str | None = None,
        ls_csrf_token: str | None = None,
        model: str = "gemini-3.5-flash",
        project: str | None = None,
        assets: list[str] | None = None,
        keep_workspaces: bool = False,
    ):
        self._scenario_name = scenario_name
        self._session_id = uuid.uuid4().hex
        path_obj = pathlib.Path(scenario_path)
        clean_name = re.sub(r"[^a-zA-Z0-9_]+", "_", path_obj.stem).strip("_")
        self._base_prefix = (
            f"/tmp/ces_skill_eval/antigravity_{clean_name}_{self._session_id}"
        )
        self._model = model
        self._project = project
        self._assets = assets or []
        self._scenario_path = scenario_path
        self._agent: Agent | None = None
        self._tool_calls_last_turn = 0
        self._tool_interactions_last_turn: list[benchmark.ToolInteraction] = []
        self._events_last_turn: Sequence[benchmark.TrajectoryEvent] = []
        self._name = "Antigravity"
        self._trajectory_extractor = trajectory_extractor.TrajectoryExtractor()
        self._keep_workspaces = keep_workspaces

    @property
    def _workspace_dir(self) -> str:
        """The absolute path to the workspace directory where the agent operates."""
        return f"{self._base_prefix}_ws"

    async def _run_subprocess_cmd(self, args: list[str], cwd: str) -> None:
        """Executes a subprocess command inside the given directory."""
        logging.info("[%s] Running command: %s", self.name, " ".join(args))
        env = os.environ.copy()
        process = await asyncio.create_subprocess_exec(
            args[0],
            *args[1:],
            cwd=cwd,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            stdout_str = stdout.decode().strip()
            stderr_str = stderr.decode().strip()
            logging.error(
                "[%s] Command failed: %s\nSTDOUT:\n%s\nSTDERR:\n%s",
                self.name,
                " ".join(args),
                stdout_str,
                stderr_str,
            )
            raise RuntimeError(
                f"Command '{' '.join(args)}' failed with exit code"
                f" {process.returncode}"
            )

    async def initialize(self) -> None:
        """Initializes the conversation session and the agent."""
        await self.close()
        self._trajectory_extractor = trajectory_extractor.TrajectoryExtractor()

        # Resolve absolute paths to the root repository directory
        eval_dir = pathlib.Path(__file__).parent.resolve()
        root_repo_dir = eval_dir.parent.resolve()

        os.makedirs(self._workspace_dir, exist_ok=True)

        for asset in self._assets:
            src_path = scenario.get_asset_path(self._scenario_path, asset)
            try:
                dst_path = os.path.join(self._workspace_dir, asset)
                os.makedirs(os.path.dirname(dst_path), exist_ok=True)
                shutil.copy(src_path, dst_path)
                logging.info(
                    "[%s] Copied asset %s to %s", self.name, src_path, dst_path
                )
            except Exception as e:
                logging.exception(
                    "[%s] Failed to copy asset %s", self.name, asset
                )
                raise RuntimeError(f"Failed to copy asset {asset}: {e}") from e

        # Execute isolated workspace environment setup

        await self._run_subprocess_cmd(
            ["uv", "venv", "--system-site-packages"], self._workspace_dir
        )

        local_venv_path = os.path.join(self._workspace_dir, ".venv")
        site_packages_glob = glob.glob(
            os.path.join(local_venv_path, "lib", "python*", "site-packages")
        )
        if not site_packages_glob:
            raise RuntimeError(
                "Could not find site-packages directory inside isolated venv:"
                f" {local_venv_path}"
            )
        local_site_packages = site_packages_glob[0]

        # 1. Zero-Build local package linkage (.pth file)
        src_dir = os.path.join(root_repo_dir, "src")
        pth_file = os.path.join(local_site_packages, "cxas-scrapi.pth")

        # Resolve active parent virtualenv site-packages directory dynamically
        parent_site_packages = None
        for p in sys.path:
            if "site-packages" in p:
                parent_site_packages = p
                break

        with open(pth_file, "w") as f:
            f.write(f"{src_dir}\n")
            if parent_site_packages:
                f.write(f"{parent_site_packages}\n")

        logging.info(
            "[%s] Wrote local .pth link file: %s -> %s (parent venv: %s)",
            self.name,
            pth_file,
            src_dir,
            parent_site_packages,
        )

        # 2. Programmatic cxas CLI wrap script
        local_venv_bin = os.path.join(local_venv_path, "bin")
        local_venv_cxas = os.path.join(local_venv_bin, "cxas")
        local_venv_python = os.path.join(local_venv_bin, "python3")

        cxas_script_content = textwrap.dedent(f"""\
        #!{local_venv_python}
        import sys
        sys.path.insert(0, {repr(src_dir)})
        from cxas_scrapi.cli.main import main
        if __name__ == '__main__':
            sys.exit(main())
        """)

        with open(local_venv_cxas, "w") as f:
            f.write(cxas_script_content)

        # Make CLI script executable
        os.chmod(local_venv_cxas, 0o755)
        logging.info(
            "[%s] Registered local cxas executable: %s",
            self.name,
            local_venv_cxas,
        )

        # Symlink or copy parent virtualenv's share/cxas-scrapi to child venv
        parent_skills_dir = os.path.join(sys.prefix, "share", "cxas-scrapi")
        local_share_dir = os.path.join(local_venv_path, "share", "cxas-scrapi")

        if os.path.exists(parent_skills_dir):
            os.makedirs(os.path.dirname(local_share_dir), exist_ok=True)
            try:
                os.symlink(parent_skills_dir, local_share_dir)
                logging.info(
                    "[%s] Symlinked parent shared skills: %s -> %s",
                    self.name,
                    local_share_dir,
                    parent_skills_dir,
                )
            except FileExistsError:
                pass
            except Exception as e:
                shutil.copytree(
                    parent_skills_dir, local_share_dir, dirs_exist_ok=True
                )
                logging.info(
                    "[%s] Copied parent shared skills: %s -> %s due to: %s",
                    self.name,
                    local_share_dir,
                    parent_skills_dir,
                    e,
                )

        instructions = (
            "You are a specialized virtual agent for designing and deploying "
            "virtual agents. You have the `cxas` CLI tool in your PATH and the "
            "GCP project is initialized."
        )

        # Prepare local agent configuration
        config = LocalAgentConfig(
            workspaces=[self._workspace_dir],
            policies=[policy.allow_all()],
            model=self._model,
            system_instructions=instructions,
        )

        # Capture original environment values for temporary injection
        original_path = os.environ.get("PATH")
        original_virtual_env = os.environ.get("VIRTUAL_ENV")
        original_gcloud_project = os.environ.get("GCLOUD_PROJECT")
        original_google_cloud_project = os.environ.get("GOOGLE_CLOUD_PROJECT")

        local_venv_path = os.path.join(self._workspace_dir, ".venv")
        local_venv_bin = os.path.join(local_venv_path, "bin")

        os.environ["VIRTUAL_ENV"] = local_venv_path
        if original_path:
            os.environ["PATH"] = f"{local_venv_bin}{os.pathsep}{original_path}"
        else:
            os.environ["PATH"] = local_venv_bin

        if self._project:
            os.environ["GCLOUD_PROJECT"] = self._project
            os.environ["GOOGLE_CLOUD_PROJECT"] = self._project

        try:
            self._agent = Agent(config)
            await self._agent.__aenter__()
        finally:
            # Restore original environment values
            if original_path is not None:
                os.environ["PATH"] = original_path
            elif "PATH" in os.environ:
                del os.environ["PATH"]

            if original_virtual_env is not None:
                os.environ["VIRTUAL_ENV"] = original_virtual_env
            elif "VIRTUAL_ENV" in os.environ:
                del os.environ["VIRTUAL_ENV"]

            if original_gcloud_project is not None:
                os.environ["GCLOUD_PROJECT"] = original_gcloud_project
            elif "GCLOUD_PROJECT" in os.environ:
                del os.environ["GCLOUD_PROJECT"]

            if original_google_cloud_project is not None:
                os.environ["GOOGLE_CLOUD_PROJECT"] = (
                    original_google_cloud_project
                )
            elif "GOOGLE_CLOUD_PROJECT" in os.environ:
                del os.environ["GOOGLE_CLOUD_PROJECT"]

    async def send_message(self, message: str) -> str:
        """Sends a message to the agent and returns its response string."""
        if not self._agent:
            raise RuntimeError(
                "Antigravity agent not initialized. Call initialize()."
            )

        self._tool_calls_last_turn = 0
        self._events_last_turn = []
        self._tool_interactions_last_turn = []

        # Chat with the agent
        chat_response = await self._agent.chat(message)
        response_text = await chat_response.text()

        # Walk step history to extract events
        self._events_last_turn = self._trajectory_extractor.extract_new_events(
            self._agent.conversation.history
        )
        self._tool_calls_last_turn = len(
            [
                e
                for e in self._events_last_turn
                if isinstance(e, benchmark.ToolCallEvent)
            ]
        )

        # Populate legacy tool interactions for backward compatibility
        for ev in self._events_last_turn:
            if isinstance(ev, benchmark.ToolCallEvent):
                output_val = ""
                for rev in self._events_last_turn:
                    if (
                        isinstance(rev, benchmark.ToolResultEvent)
                        and rev.call_id == ev.call_id
                    ):
                        output_val = rev.output
                        break
                self._tool_interactions_last_turn.append(
                    benchmark.ToolInteraction(
                        name=ev.name,
                        args=ev.args,
                        output=output_val or None,
                        thought=None,
                    )
                )

        logging.info("[%s] Response: %s", self.name, response_text)
        return response_text

    def get_tool_calls_count_last_turn(self) -> int:
        return self._tool_calls_last_turn

    def get_tool_interactions_last_turn(
        self,
    ) -> Sequence[benchmark.ToolInteraction]:
        return self._tool_interactions_last_turn

    def get_events_last_turn(self) -> Sequence[benchmark.TrajectoryEvent]:
        return self._events_last_turn

    def get_log_files(self) -> Sequence[str]:
        return []

    def get_trajectory_id(self) -> str | None:
        """Returns the trajectory ID associated with this head."""
        if self._agent and self._agent.conversation:
            return self._agent.conversation.conversation_id
        return None

    async def close(self) -> None:
        """Closes the conversation and the agent session."""
        if self._agent:
            try:
                await self._agent.__aexit__(None, None, None)
            except Exception:
                pass
            self._agent = None
            self._events_last_turn = []

    @property
    def name(self) -> str:
        return self._name
