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

"""Orchestrator for automated CES skill benchmarking."""

import asyncio
import datetime
import json
import os
import sys
import traceback
from typing import Any, List, Optional, Sequence

import agent_heads
import benchmark
import reporting
import scenario
import scorer
import user_simulator
from absl import app, flags, logging

_SCENARIO_PATH = flags.DEFINE_string(
    "scenario_path",
    "scenarios",
    "Path to the scenario .yaml/.yml file or a directory containing them.",
)
_TIMEOUT = flags.DEFINE_integer(
    "timeout", 1200, "Global timeout in seconds for each agent head run."
)

_PROJECT = flags.DEFINE_string(
    "project",
    "",
    "Google Cloud Project ID for Vertex AI evaluation.",
)
_LOCATION = flags.DEFINE_string(
    "location",
    "global",
    "Google Cloud Location for Vertex AI evaluation.",
)
_SIMULATOR_MODEL = flags.DEFINE_string(
    "simulator_model",
    "gemini-3.5-flash",
    "Gemini model for user simulator.",
)
_SCORER_MODEL = flags.DEFINE_string(
    "scorer_model",
    "gemini-3.5-flash",
    "Gemini model for scoring/rubric.",
)
_OUTPUT_DIR = flags.DEFINE_string(
    "output_dir",
    "./reports/",
    "Base directory to store reports. A timestamped subdirectory will be "
    "created automatically for each run.",
)
_RUN_FAKE = flags.DEFINE_bool(
    "run_fake", False, "Whether to run the fake scaffolding head."
)
_RUN_ANTIGRAVITY = flags.DEFINE_bool(
    "run_antigravity", True, "Whether to run the Antigravity head."
)
_WORKSPACE_ROOT = flags.DEFINE_string(
    "workspace_root",
    "",
    "Override for workspace root path.",
)
_ANTIGRAVITY_MODEL = flags.DEFINE_string(
    "antigravity_model",
    "gemini-3.5-flash",
    "The model to use for Antigravity head.",
)
_INPUT_REPORT_DIR = flags.DEFINE_string(
    "input_report_dir",
    "",
    "Path to an existing report directory. If provided, skips experiment"
    " execution and regenerates the report.",
)
_KEEP_WORKSPACES = flags.DEFINE_bool(
    "keep_workspaces",
    False,
    "Whether to keep temporary workspaces after successful runs for debugging.",
)


async def _validate_environment() -> None:
    """Validates GCP Application Default Credentials before starting the benchmark."""
    try:
        import google.auth
        from google.auth.exceptions import DefaultCredentialsError

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, google.auth.default)
    except ImportError:
        logging.warning(
            "google-auth package not found. Skipping GCP credentials validation."
        )
    except Exception as e:
        raise RuntimeError(
            "Google Cloud Application Default Credentials (ADC) not found. Please"
            " configure credentials by running 'gcloud auth application-default"
            " login'."
        ) from e


def _get_workspace_root() -> str:
    """Returns the absolute path to the workspace root."""
    if flags.FLAGS.is_parsed() and _WORKSPACE_ROOT.value:
        return _WORKSPACE_ROOT.value

    build_workspace = os.environ.get("BUILD_WORKSPACE_DIRECTORY")
    if build_workspace:
        return build_workspace

    return os.getcwd()


def _dump_reproducibility_metadata(
    output_dir: str, workspace_root: str
) -> None:
    """Dumps reproducibility metadata to the report folder."""
    metadata: dict[str, Any] = {}

    metadata["cli_args"] = sys.argv
    metadata["cwd"] = os.getcwd()
    metadata["workspace_root"] = workspace_root

    env_filtered = {}
    for k, v in os.environ.items():
        lower_k = k.lower()
        if k == "SSH_AUTH_KEY":
            env_filtered[k] = v
        elif any(
            secret_term in lower_k
            for secret_term in ["token", "auth", "key", "password", "secret"]
        ):
            env_filtered[k] = "[REDACTED]"
        else:
            env_filtered[k] = v
    metadata["env"] = env_filtered

    repro_path = os.path.join(output_dir, "reproducibility.json")
    with open(repro_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)


class BenchmarkOrchestrator:
    """Orchestrates parallel execution of benchmark scenarios."""

    def __init__(self, report_dir: str, location: str = "global"):
        self._report_dir = report_dir
        self._results: List[benchmark.ConversationResult] = []
        self._lock = asyncio.Lock()
        self._init_semaphore = asyncio.Semaphore(
            1
        )  # Strict sequential initialization
        self._run_semaphore = asyncio.Semaphore(
            2
        )  # Limit concurrent active evaluations to respect Vertex AI burst limits
        project_val = (
            _PROJECT.value if flags.FLAGS.is_parsed() else "fake-project"
        )
        model_val = (
            _SCORER_MODEL.value
            if flags.FLAGS.is_parsed()
            else "gemini-3.5-flash"
        )
        self._scorer = scorer.Scorer(
            project=project_val,
            location=location,
            model_name=model_val,
        )

    async def initialize_reports(
        self,
        *,
        scenarios: Sequence[scenario.Scenario],
        enabled_heads: Sequence[str],
    ) -> None:
        """Creates the initial hub (index.html) immediately with all scenarios as pending."""
        for scen in scenarios:
            for head in enabled_heads:
                self._results.append(
                    benchmark.ConversationResult(
                        scenario_name=scen.name,
                        scenario_text=scen.text,
                        head_name=head,
                        turns=0,
                        total_time_sec=0.0,
                        messages=[],
                        turn_metrics=[],
                        status=benchmark.ExecutionStatus.PENDING,
                        success=None,
                    )
                )
        await self.update_reports()

    async def report_crash(self, error_msg: str) -> None:
        """Updates index.html with a critical failure message."""
        async with self._lock:
            index_html = reporting.generate_index_html(self._results)
            crash_html = (
                '<div style="background: #fce8e6; color: #c5221f; padding: 2rem;'
                " border-radius: 8px; border: 1px solid #f5c6cb; margin-bottom:"
                ' 2rem; font-weight: bold;">'
                f"CRITICAL SUITE FAILURE: {error_msg}</div>"
            )
            index_html = index_html.replace(
                "<h1>Agent Evaluation Benchmark</h1>",
                f"<h1>Agent Evaluation Benchmark</h1>{crash_html}",
            )
            reporting.save_report(
                index_html, os.path.join(self._report_dir, "index.html")
            )

    async def run_head(
        self,
        head: benchmark.BaseAgentHead,
        runner: benchmark.BenchmarkRunner,
    ) -> None:
        """Runs a single agent head with a timeout and updates reports."""
        scenario_name = runner.scenario_name
        scenario_text = runner.scenario_text

        success = False
        async with self._run_semaphore:
            logging.info(
                "[%s] [%s] Starting evaluation...", scenario_name, head.name
            )

            try:
                timeout_val = (
                    float(_TIMEOUT.value) if flags.FLAGS.is_parsed() else 1200.0
                )
                final_res = await asyncio.wait_for(
                    runner.run(
                        head,
                        on_turn_completed=self.update_reports,
                        init_semaphore=self._init_semaphore,
                    ),
                    timeout=timeout_val,
                )

                await self.update_reports(final_res)
                if final_res and final_res.success:
                    success = True
                logging.info(
                    "[%s] [%s] Finished successfully.", scenario_name, head.name
                )

            except asyncio.TimeoutError:
                logging.error(
                    "[%s] [%s] Timed out after %ds.",
                    scenario_name,
                    head.name,
                    timeout_val,
                )
                await self._handle_error(
                    head,
                    scenario_name,
                    scenario_text,
                    f"Timed out after {timeout_val}s.",
                )
            except Exception as e:
                logging.exception(
                    "[%s] [%s] Unexpected failure: %s",
                    scenario_name,
                    head.name,
                    e,
                )
                await self._handle_error(
                    head, scenario_name, scenario_text, f"Crashed: {e}"
                )
            finally:
                await head.close()

    async def update_reports(
        self, partial_res: Optional[benchmark.ConversationResult] = None
    ) -> None:
        """Updates internal state and writes reporting files."""
        async with self._lock:
            if partial_res:
                found = False
                for i, r in enumerate(self._results):
                    if (
                        r.scenario_name == partial_res.scenario_name
                        and r.head_name == partial_res.head_name
                    ):
                        self._results[i] = partial_res
                        found = True
                        break
                if not found:
                    self._results.append(partial_res)

            # Generate Summary Report (index.html)
            index_html = reporting.generate_index_html(self._results)
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(
                None,
                reporting.save_report,
                index_html,
                os.path.join(self._report_dir, "index.html"),
            )

            # Generate Individual Detailed Reports (.html and .json)
            if partial_res:
                detail_html = reporting.generate_detail_html(partial_res)
                safe_name = scenario.get_safe_filename(
                    partial_res.scenario_name
                )
                filename_base = f"{safe_name}_{partial_res.head_name}"
                await loop.run_in_executor(
                    None,
                    reporting.save_report,
                    detail_html,
                    os.path.join(
                        self._report_dir, f"detail_{filename_base}.html"
                    ),
                )
                json_report = reporting.generate_json_report(partial_res)
                await loop.run_in_executor(
                    None,
                    reporting.save_report,
                    json_report,
                    os.path.join(self._report_dir, f"{filename_base}.json"),
                )

    async def _handle_error(
        self,
        head: benchmark.BaseAgentHead,
        scenario_name: str,
        scenario_text: str,
        msg: str,
    ) -> None:
        """Updates the reporting state with a failure result."""
        res = benchmark.ConversationResult(
            scenario_name=scenario_name,
            scenario_text=scenario_text,
            head_name=head.name,
            turns=0,
            total_time_sec=0.0,
            messages=[],
            turn_metrics=[],
            status=benchmark.ExecutionStatus.FAILED,
            success=False,
            failure_reason=msg,
        )
        await self.update_reports(res)

    def _create_simulator(self, text: str) -> benchmark.UserSimulatorProtocol:
        """Creates a new user simulator instance."""
        project_val = _PROJECT.value if flags.FLAGS.is_parsed() else None
        loc_val = _LOCATION.value if flags.FLAGS.is_parsed() else None
        model_val = (
            _SIMULATOR_MODEL.value
            if flags.FLAGS.is_parsed()
            else "gemini-3.5-flash"
        )
        return user_simulator.UserSimulator(
            text,
            project=project_val,
            location=loc_val,
            model_name=model_val,
        )


async def main_async() -> None:
    """Main entry point for the benchmark orchestrator."""
    if not _RUN_FAKE.value:
        await _validate_environment()

    workspace_root = _get_workspace_root()
    if workspace_root:
        logging.info(
            "Changing global CWD to workspace root: %s", workspace_root
        )
        os.chdir(workspace_root)

    scenario_files = []
    raw_paths = _SCENARIO_PATH.value.split(",")

    for raw_path in raw_paths:
        path = raw_path
        if not os.path.isabs(path):
            path = os.path.join(workspace_root, raw_path)

        if not os.path.exists(path) and os.path.isabs(raw_path):
            path = raw_path

        if os.path.isdir(path):
            scenario_files.extend(
                [
                    os.path.join(path, f)
                    for f in os.listdir(path)
                    if (f.endswith(".yaml") or f.endswith(".yml"))
                ]
            )
        elif os.path.isfile(path):
            scenario_files.append(path)
        else:
            raise ValueError(
                f"Scenario path not found: {raw_path} (resolved to {path})"
            )

    if not scenario_files:
        raise ValueError(f"No YAML scenarios found in {_SCENARIO_PATH.value}")

    scenario_files.sort()

    output_dir = _OUTPUT_DIR.value
    timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    output_dir = os.path.join(output_dir, f"run-{timestamp}")

    if not output_dir.startswith("/"):
        output_dir = os.path.join(workspace_root, output_dir)
    os.makedirs(output_dir, exist_ok=True)
    _dump_reproducibility_metadata(output_dir, workspace_root)

    orchestrator = BenchmarkOrchestrator(
        report_dir=output_dir, location=_LOCATION.value
    )

    if _INPUT_REPORT_DIR.value:
        input_dir = _INPUT_REPORT_DIR.value
        if not os.path.isabs(input_dir):
            input_dir = os.path.join(workspace_root, input_dir)

        logging.info(
            "Regenerating report from existing directory: %s", input_dir
        )
        count = 0
        try:
            files = os.listdir(input_dir)
        except Exception as e:
            logging.error("Failed to list directory %s: %s", input_dir, e)
            sys.exit(1)

        for f in sorted(files):
            if f.endswith(".json") and f != "reproducibility.json":
                full_path = os.path.join(input_dir, f)
                try:
                    res = reporting.load_json_report(full_path)
                    await orchestrator.update_reports(res)
                    count += 1
                except Exception as e:
                    logging.error(
                        "Failed reading report file %s: %s", full_path, e
                    )
                    sys.exit(1)

        if count == 0:
            logging.error(
                "CRITICAL: Found 0 .json report files in %s. Aborting.",
                input_dir,
            )
            sys.exit(1)

        logging.info("Successfully loaded %d conversation results.", count)
        await orchestrator.update_reports()
        logging.info("Successfully regenerated reports into %s", output_dir)
        return

    # Immediate hub creation for better UX
    enabled_heads = [
        head_name
        for head_name, is_enabled in [
            ("ScaffoldingTestAgent", _RUN_FAKE.value),
            ("Antigravity", _RUN_ANTIGRAVITY.value),
        ]
        if is_enabled
    ]

    scenarios_with_paths = []
    for scenario_path in scenario_files:
        try:
            scen = scenario.Scenario.from_file(scenario_path)
            scenarios_with_paths.append((scen, scenario_path))
        except ValueError:
            logging.exception("Failed to parse scenario %s", scenario_path)
            sys.exit(1)

    seen_names = set()
    for scen, path in scenarios_with_paths:
        if scen.name in seen_names:
            logging.error(
                "Duplicate scenario name detected: %s. File: %s",
                scen.name,
                path,
            )
            sys.exit(1)
        seen_names.add(scen.name)

    scenarios = [s for s, _ in scenarios_with_paths]

    await orchestrator.initialize_reports(
        scenarios=scenarios, enabled_heads=enabled_heads
    )

    tasks = []
    for scen, scenario_path in scenarios_with_paths:
        runner = benchmark.BenchmarkRunner(
            scen=scen,
            simulator_factory=orchestrator._create_simulator,
            scorer_instance=orchestrator._scorer,
            max_turns=30,
        )

        if _RUN_FAKE.value:
            tasks.append(
                orchestrator.run_head(
                    agent_heads.ScaffoldingTestAgent(
                        scenario_name=scen.name,
                        name="ScaffoldingTestAgent",
                    ),
                    runner,
                )
            )

        if _RUN_ANTIGRAVITY.value:
            keep_workspaces_val = (
                _KEEP_WORKSPACES.value if flags.FLAGS.is_parsed() else False
            )
            tasks.append(
                orchestrator.run_head(
                    agent_heads.AntigravityAgentHead(
                        scenario_name=scen.name,
                        model=_ANTIGRAVITY_MODEL.value,
                        project=_PROJECT.value,
                        assets=scen.assets,
                        scenario_path=scenario_path,
                        keep_workspaces=keep_workspaces_val,
                    ),
                    runner,
                )
            )

    if tasks:
        logging.info(
            "Executing %d total benchmarks concurrently...", len(tasks)
        )
        try:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for idx, task_res in enumerate(results):
                if isinstance(task_res, Exception):
                    logging.error(
                        "Scenario task %d failed with an unhandled exception: %s",
                        idx,
                        task_res,
                        exc_info=task_res,
                    )
        except Exception as e:
            logging.exception("Suite execution failed")
            await orchestrator.report_crash(str(e))

    print(f"\nFinal report available at: {output_dir}/index.html\n")


def main(argv: Sequence[str]) -> None:
    if len(argv) > 1:
        raise app.UsageError("Too many command-line arguments.")

    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as e:
        logging.exception("Benchmark failed: %s", e)
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    app.run(main)
