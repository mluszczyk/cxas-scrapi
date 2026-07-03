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

"""Reporting logic for CXAS skill benchmarking."""

import dataclasses
import datetime
import json
import os
import pathlib
import re
import urllib.parse
from collections.abc import Sequence
from typing import Any

import markdown

from htbuilder import a, body, code, details, div, footer, h1, h3, h5, head, html, li, p, pre, span, style, strong, summary, table, tbody, td, th, thead, title, tr, ul
from skill_eval import benchmark, scenario

_TRAJECTORY_URL_TEMPLATE = os.environ.get("TRAJECTORY_VIEWER_URL", "")

_INDEX_CSS = """
    body { font-family: 'Google Sans', sans-serif; margin: 2rem; background: #f8f9fa; color: #3c4043; display: flex; flex-direction: column; min-height: 90vh; }
    h1 { color: #1a73e8; margin-bottom: 2rem; }
    .summary-card { background: white; border-radius: 8px; padding: 1.5rem; box-shadow: 0 1px 3px rgba(0,0,0,0.12); margin-bottom: 2rem; flex-grow: 1; }
    table { width: 100%; border-collapse: collapse; background: white; }
    th, td { padding: 12px 16px; text-align: left; border-bottom: 1px solid #e0e0e0; }
    th { background-color: #f1f3f4; font-weight: 500; color: #5f6368; text-transform: uppercase; font-size: 0.85rem; letter-spacing: 0.5px; }
    tr:hover { background-color: #f8f9fa; }
    .scenario-cell { font-weight: 500; color: #202124; min-width: 200px; }
    .status-badge { display: inline-block; padding: 4px 12px; border-radius: 16px; font-size: 0.8rem; font-weight: 500; min-width: 80px; text-align: center; }
    .status-pending { background: #f1f3f4; color: #5f6368; }
    .status-running { background: #e8f0fe; color: #1967d2; animation: pulse 2s infinite; }
    .status-pass { background: #e6f4ea; color: #137333; }
    .status-warning { background: #fef7e0; color: #b05e00; }
    .status-fail { background: #fce8e6; color: #c5221f; }
    .metric-line { font-size: 0.8rem; color: #5f6368; margin-top: 2px; }
    .details-link { color: #1a73e8; text-decoration: none; font-size: 0.9rem; font-weight: 500; display: inline-block; margin-top: 8px; margin-right: 8px; }
    .details-link:hover { text-decoration: underline; }
    footer { margin-top: 3rem; padding: 1.5rem; border-top: 1px solid #e0e0e0; color: #70757a; font-size: 0.85rem; text-align: center; }
    @keyframes pulse {
      0% { opacity: 1; }
      50% { opacity: 0.6; }
      100% { opacity: 1; }
    }
"""

_DETAIL_CSS = """
    body { font-family: 'Roboto', sans-serif; margin: 2rem; background: #f8f9fa; line-height: 1.6; color: #3c4043; }
    h1 { color: #1a73e8; }
    .summary-card { background: white; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.12); padding: 1.5rem; margin-bottom: 2rem; }
    .turn-container { margin-bottom: 1.5rem; border-left: 4px solid #e0e0e0; padding-left: 1rem; }
    .turn-header { font-size: 0.85rem; color: #70757a; margin-bottom: 0.25rem; display: flex; justify-content: space-between; }
    .turn-title { margin: 0; font-weight: 500; color: #1a73e8; }
    .turn { padding: 0.75rem; border-radius: 4px; position: relative; }
    .user { background: #e8f0fe; border-left: 4px solid #1a73e8; }
    .agent { background: #f1f3f4; border-left: 4px solid #70757a; margin-top: 0.5rem; }
    .turn-meta { display: flex; gap: 1rem; font-size: 0.75rem; color: #70757a; margin-top: 0.25rem; }
    .timing-pill { background: #e8eaed; padding: 2px 8px; border-radius: 10px; }
    .tool-interactions { margin-top: 1rem; background: #fff; border: 1px solid #dadce0; border-radius: 6px; padding: 1rem; }
    .tool-interactions details { margin-bottom: 0.5rem; }
    .tool-interactions summary { cursor: pointer; color: #1a73e8; font-weight: 500; padding: 4px; }
    .tool-details { padding: 1rem; background: #f8f9fa; border-top: 1px solid #eee; margin-top: 0.5rem; }
    .markdown-body pre { background: #f8f9fa; padding: 1rem; border-radius: 4px; overflow-x: auto; }
    .status-badge { padding: 4px 12px; border-radius: 12px; font-size: 0.85rem; font-weight: 500; display: inline-block; }
    .status-pass { background: #e6f4ea; color: #137333; }
    .status-fail { background: #fce8e6; color: #c5221f; }
    .status-warning { background: #fef7e0; color: #b05e00; }
    .status-running { background: #e8f0fe; color: #1a73e8; animation: pulse 2s infinite; }
    .status-initializing { background: #e8f0fe; color: #1a73e8; animation: pulse 2s infinite; }
    .status-conversing { background: #e8f0fe; color: #1a73e8; animation: pulse 2s infinite; }
    .status-grading { background: #e6f4ea; color: #137333; animation: pulse 2s infinite; }
    @keyframes pulse { 0% { opacity: 1; } 50% { opacity: 0.5; } 100% { opacity: 1; } }
    pre { background: #f8f9fa; padding: 0.5rem; overflow-x: auto; border: 1px solid #dee2e6; border-radius: 3px; max-height: 300px; font-size: 0.85rem; }
    .scenario-intro { background: #e8f0fe; padding: 1.5rem; border-radius: 8px; margin-bottom: 2rem; border: 1px solid #d2e3fc; }
    .termination-signal { color: #c5221f; background: #fce8e6; padding: 1rem; border-radius: 4px; border: 1px solid #f5c6cb; margin-top: 1rem; font-weight: bold; }
    footer { margin-top: 3rem; padding: 1.5rem; border-top: 1px solid #e0e0e0; color: #70757a; font-size: 0.85rem; }
    .time-stats { display: flex; gap: 2rem; color: #5f6368; font-size: 0.85rem; margin-top: 0.5rem; }
"""


class _ReportEncoder(json.JSONEncoder):
    """Custom JSON encoder for benchmark results."""

    def default(self, o: Any) -> Any:
        if isinstance(o, benchmark.ExecutionStatus):
            return o.value
        if isinstance(o, datetime.timedelta):
            return o.total_seconds()
        return super().default(o)


def generate_json_report(result: benchmark.ConversationResult) -> str:
    """Generates a serialized JSON representation of the result."""
    return json.dumps(dataclasses.asdict(result), indent=2, cls=_ReportEncoder)


def _escape_html(text: Any) -> str:
    """Escapes text for safe HTML rendering."""
    if text is None:
        return ""
    s = str(text)
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def _format_ts(ts: float) -> str:
    """Formats a unix timestamp for display."""
    if ts <= 0:
        return "N/A"
    return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")


def generate_index_html(
    results: Sequence[benchmark.ConversationResult],
    suite_duration: datetime.timedelta = datetime.timedelta(),
) -> str:
    """Generates the main index.html summary page."""
    by_scenario = _group_by_scenario(results)
    all_heads = sorted(list(set(r.head_name for r in results)))

    eval_start_val = min(
        (r.start_time for r in results if r.start_time > 0), default=0
    )
    eval_end_val = max(
        (r.end_time for r in results if r.end_time > 0), default=0
    )

    eval_start = _format_ts(eval_start_val)
    eval_end = _format_ts(eval_end_val)

    # Build headers
    headers = [th("Scenario")] + [th(_escape_html(h)) for h in all_heads]

    # Build rows
    rows = []
    if not results:
        rows.append(
            tr(
                td(colspan="100%", style="text-align: center; padding: 2rem; color: #70757a;")(
                    "Initializing benchmark suite..."
                )
            )
        )
    else:
        for scenario_name in sorted(by_scenario.keys()):
            row_cells = [td(_class="scenario-cell")(_escape_html(scenario_name))]
            head_map = {r.head_name: r for r in by_scenario[scenario_name]}

            for head_name in all_heads:
                res = head_map.get(head_name)
                if not res:
                    row_cells.append(td("-"))
                    continue

                status_class = f"status-{res.status.value.lower()}"
                status_text = res.status.value

                if res.status == benchmark.ExecutionStatus.FINISHED:
                    earned, total = 0, 0
                    if res.rubric_results:
                        earned = res.rubric_results.total_score
                        total = res.rubric_results.max_score
                        status_text = f"Score: {earned}/{total}"
                        pct = (earned / total) if total > 0 else 0
                        if pct >= 1.0:
                            status_class = "status-pass"
                        elif pct >= 0.5:
                            status_class = "status-warning"
                        else:
                            status_class = "status-fail"
                    else:
                        status_class = "status-fail"
                        status_text = "FAILED"

                safe_scenario_name = scenario.get_safe_filename(res.scenario_name)

                # Links
                links = [
                    a(
                        href=f"detail_{safe_scenario_name}_{_escape_html(res.head_name)}.html",
                        _class="details-link"
                    )("Details")
                ]
                if getattr(res, "trajectory_id", None) and _TRAJECTORY_URL_TEMPLATE:
                    url = _TRAJECTORY_URL_TEMPLATE.replace(
                        "{id}", _escape_html(res.trajectory_id)
                    )
                    links.append(
                        a(
                            href=url,
                            target="_blank",
                            _class="details-link"
                        )("Trajectory")
                    )

                row_cells.append(
                    td(
                        div(_class=f"status-badge {status_class}")(status_text),
                        div(_class="metric-line")(
                            f"Turns: {res.turns} | Time: {res.total_time_sec:.1f}s"
                        ),
                        links
                    )
                )
            rows.append(tr(row_cells))

    # Footer elements
    footer_children = [
        "Evaluation Period: ",
        strong(eval_start),
        " — ",
        strong(eval_end)
    ]
    if suite_duration.total_seconds() > 0:
        footer_children += [
            " — Suite Duration: ",
            strong(f"{suite_duration.total_seconds():.1f}s")
        ]

    # Assemble document
    doc = html(
        head(
            title("Agent Evaluation Benchmark"),
            style(_INDEX_CSS)
        ),
        body(
            h1("Agent Evaluation Benchmark"),
            div(_class="summary-card")(
                table(
                    thead(tr(headers)),
                    tbody(rows)
                )
            ),
            footer(footer_children)
        )
    )

    return f"<!DOCTYPE html>\n{doc}"


def generate_detail_html(
    result: benchmark.ConversationResult,
    report_dir: str | None = None,
) -> str:
    """Generates the detailed per-agent HTML report."""
    banners = None
    if result.status in (
        benchmark.ExecutionStatus.RUNNING,
        benchmark.ExecutionStatus.INITIALIZING,
        benchmark.ExecutionStatus.CONVERSING,
        benchmark.ExecutionStatus.GRADING,
    ):
        banners = div(
            _class=f"status-badge status-{result.status.value.lower()}",
            style="margin-bottom: 1rem;",
        )(result.status.value)

    intro = None
    if result.scenario_text:
        match = re.split(
            r"##\s*Steps|#\s*Reference|##\s*Rubric", result.scenario_text
        )
        if match:
            intro_content = markdown.markdown(
                match[0].strip(), extensions=["fenced_code", "tables", "nl2br"]
            )
            intro = div(_class="scenario-intro")(
                h3("Goal & Context"),
                intro_content
            )

    links = []
    if getattr(result, "trajectory_id", None) and _TRAJECTORY_URL_TEMPLATE:
        url = _TRAJECTORY_URL_TEMPLATE.replace(
            "{id}", _escape_html(result.trajectory_id)
        )
        links.append(
            li(
                strong("Trajectory Viewer: "),
                a(href=url, target="_blank")(_escape_html(result.trajectory_id))
            )
        )

    if result.log_files:
        for f in result.log_files:
            abs_path = os.path.abspath(f)
            file_uri = pathlib.Path(abs_path).as_uri()
            href = file_uri
            display_name = abs_path

            if report_dir:
                try:
                    rel_path = os.path.relpath(
                        abs_path, start=os.path.abspath(report_dir)
                    )
                    href = urllib.parse.quote(rel_path.replace(os.sep, "/"))
                    display_name = rel_path
                except Exception:
                    pass

            links.append(
                li(
                    a(href=href, target="_blank")(_escape_html(display_name)),
                    " (",
                    a(href=file_uri, target="_blank")("absolute fallback"),
                    ")"
                )
            )

    log_links = None
    if links:
        log_links = div(_class="scenario-intro", style="margin-top: 2rem;")(
            h3("Raw Diagnostic Logs & Links"),
            ul(links)
        )

    rubric = None
    if result.rubric_results:
        res = result.rubric_results
        earned, total = res.total_score, res.max_score
        pct = (earned / total) if total > 0 else 0
        if pct >= 1.0:
            s_cls, s_txt = "status-pass", "PASSED"
        elif pct >= 0.5:
            s_cls, s_txt = "status-warning", "WARNING"
        else:
            s_cls, s_txt = "status-fail", "FAILED"

        rows = []
        for s in res.scores:
            score_color = (
                "#137333" if s.score == 2
                else ("#b05e00" if s.score == 1 else "#c5221f")
            )
            score_weight = "bold" if s.score == 2 else "normal"
            score_style = f"border: 1px solid #e0e0e0; padding: 12px; text-align: center; color: {score_color}; font-weight: {score_weight};"

            rows.append(
                tr(
                    td(style="border: 1px solid #e0e0e0; padding: 12px;")(
                        _escape_html(s.criteria)
                    ),
                    td(style=score_style)(f"{s.score}/2"),
                    td(
                        style="border: 1px solid #e0e0e0; padding: 12px; color: #5f6368; font-size: 0.9rem;"
                    )(_escape_html(s.reasoning))
                )
            )

        rubric = div(_class="summary-card")(
            div(
                style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 1rem;"
            )(
                h3(style="margin: 0; color: #1a73e8;")("Rubric Assessment"),
                div(
                    _class=f"status-badge {s_cls}",
                    style="font-size: 1rem; padding: 8px 24px;"
                )(f"{s_txt} ({earned}/{total})")
            ),
            p(style="color: #5f6368; margin-bottom: 1.5rem;")(
                strong("Overall: "),
                _escape_html(res.summary)
            ),
            table(style="width: 100%; border-collapse: collapse; border: 1px solid #e0e0e0;")(
                thead(
                    tr(style="background: #f1f3f4;")(
                        th(style="padding: 12px;")("Criterion"),
                        th(style="padding: 12px; text-align: center;")("Score"),
                        th(style="padding: 12px;")("Reasoning")
                    )
                ),
                tbody(rows)
            )
        )

    history_turns = []
    num_turns = (len(result.messages) + 1) // 2
    for i in range(num_turns):
        m = result.turn_metrics[i] if i < len(result.turn_metrics) else None

        timing = None
        if m:
            timing = div(_class="turn-meta")(
                span(_class="timing-pill")(f"Sim: {m.simulator_latency_sec:.2f}s"),
                span(_class="timing-pill")(f"Agent: {m.latency_sec:.2f}s")
            )

        turn_children = [
            div(_class="turn-header")(
                h5(_class="turn-title")(f"Turn {i + 1}")
            )
        ]

        if (2 * i) < len(result.messages):
            turn_children.append(
                div(_class="turn user")(
                    strong("User:"),
                    f" {_escape_html(result.messages[2 * i]['content'])}"
                )
            )
            if timing:
                turn_children.append(timing)

        if m and (getattr(m, "events", None) or m.tool_interactions):
            event_details = []
            if getattr(m, "events", None):
                for ev in m.events:
                    if isinstance(ev, benchmark.ToolCallEvent):
                        summary_content = [f"Tool Call: {_escape_html(ev.name)}"]
                        if ev.name == "run_command":
                            command_line = ev.args.get(
                                "command_line"
                            ) or ev.args.get("CommandLine")
                            if command_line:
                                summary_content += [
                                    " - ",
                                    code(_escape_html(command_line))
                                ]

                        escaped_args = _escape_html(
                            json.dumps(ev.args, indent=2)
                        )
                        event_details.append(
                            details(
                                summary(summary_content),
                                div(_class="tool-details")(
                                    p(strong("Source: "), ev.source),
                                    p(strong("Call ID: "), ev.call_id),
                                    p(strong("Args: ")),
                                    pre(escaped_args)
                                )
                            )
                        )
                    elif isinstance(ev, benchmark.ToolResultEvent):
                        event_details.append(
                            details(
                                summary(code(f"Tool Result for {ev.call_id}")),
                                div(_class="tool-details")(
                                    p(strong("Source: "), ev.source),
                                    p(strong("Status: "), 'Error' if ev.is_error else 'Success'),
                                    p(strong("Output: ")),
                                    pre(_escape_html(ev.output))
                                )
                            )
                        )
                    elif (
                        isinstance(ev, benchmark.AgentMessageEvent)
                        and ev.is_thought
                    ):
                        event_details.append(
                            details(
                                summary(code(f"Thought ({ev.source})")),
                                div(_class="tool-details")(
                                    pre(_escape_html(ev.text))
                                )
                            )
                        )
                    elif isinstance(ev, benchmark.SubagentEvent):
                        event_details.append(
                            details(
                                summary(code(f"Subagent {ev.action}")),
                                div(_class="tool-details")(
                                    p(strong("Subagent ID: "), ev.subagent_id),
                                    p(strong("Prompt: "), _escape_html(ev.prompt))
                                )
                            )
                        )
            elif m.tool_interactions:
                for ti in m.tool_interactions:
                    thought_element = None
                    if ti.thought:
                        thought_element = p(style="color: #666; font-style: italic;")(
                            strong("Thought: "),
                            _escape_html(ti.thought)
                        )

                    details_children = [
                        thought_element,
                        p(strong("Args: ")),
                        pre(_escape_html(json.dumps(ti.args, indent=2)))
                    ]
                    if ti.output:
                        details_children += [
                            p(strong("Output: ")),
                            pre(_escape_html(ti.output))
                        ]

                    event_details.append(
                        details(
                            summary(code(_escape_html(ti.name))),
                            div(_class="tool-details")(details_children)
                        )
                    )

            turn_children.append(
                details(_class="tool-interactions")(
                    summary(strong("Execution Events")),
                    event_details
                )
            )

        if (2 * i + 1) < len(result.messages):
            rendered = markdown.markdown(
                result.messages[2 * i + 1]["content"],
                extensions=["fenced_code", "tables", "nl2br"],
            )
            turn_children.append(
                div(_class="turn agent")(
                    strong("Agent:"),
                    div(_class="markdown-body")(rendered)
                )
            )
        elif (
            i < num_turns - 1
            or result.status == benchmark.ExecutionStatus.FAILED
        ):
            turn_children.append(
                div(_class="turn agent", style="color: red; border-left-color: red;")(
                    strong("Agent:"), " [FAILED]"
                )
            )

        history_turns.append(div(_class="turn-container")(turn_children))

    final_failure = result.failure_reason
    if (
        not final_failure
        and result.messages
        and "[[FAIL" in result.messages[-1]["content"]
    ):
        final_failure = result.messages[-1]["content"]
    if final_failure:
        history_turns.append(
            div(_class="termination-signal")(
                "Termination Signal: ",
                _escape_html(final_failure)
            )
        )

    scoring_latency = None
    if result.scoring_latency.total_seconds() > 0:
        scoring_latency = span(
            "Scoring Duration: ",
            strong(f"{result.scoring_latency.total_seconds():.1f}s")
        )

    latency_table = div(_class="summary-card")(
        h3(style="margin-top: 0; color: #1a73e8;")("Orchestration Latency Profile"),
        table(
            style="width: auto; min-width: 450px; border: 1px solid #dadce0; border-radius: 6px; border-collapse: collapse;"
        )(
            thead(
                tr(style="background: #f1f3f4;")(
                    th(
                        style="padding: 8px 16px; text-align: left; border-bottom: 1px solid #dee2e6;"
                    )("Phase"),
                    th(
                        style="padding: 8px 16px; text-align: right; border-bottom: 1px solid #dee2e6;"
                    )("Duration")
                )
            ),
            tbody(
                tr(style="border-bottom: 1px solid #eee;")(
                    td(style="padding: 8px 16px;")(
                        strong("Initialization Queue"), " (waiting for slot)"
                    ),
                    td(style="padding: 8px 16px; text-align: right;")(
                        f"{result.init_queued_latency.total_seconds():.2f}s"
                    )
                ),
                tr(style="border-bottom: 1px solid #eee;")(
                    td(style="padding: 8px 16px;")(
                        strong("Active Initialization"),
                        " (asset copy, pip/uv setup, LS bootstrap)"
                    ),
                    td(style="padding: 8px 16px; text-align: right;")(
                        f"{result.init_active_latency.total_seconds():.2f}s"
                    )
                ),
                tr(style="border-bottom: 1px solid #eee;")(
                    td(style="padding: 8px 16px;")(
                        strong("Agent Execution"), " (turns and tools)"
                    ),
                    td(style="padding: 8px 16px; text-align: right;")(
                        f"{result.conversing_latency.total_seconds():.2f}s"
                    )
                ),
                tr(style="border-bottom: 1px solid #eee;")(
                    td(style="padding: 8px 16px;")(
                        strong("Rubric Grading"), " (Gemini evaluation)"
                    ),
                    td(style="padding: 8px 16px; text-align: right;")(
                        f"{result.scoring_latency.total_seconds():.2f}s"
                    )
                ),
                tr(style="border-bottom: 1px solid #eee;")(
                    td(style="padding: 8px 16px;")(
                        strong("Teardown & Cleanup"),
                        " (sandbox application deletion)"
                    ),
                    td(style="padding: 8px 16px; text-align: right;")(
                        f"{result.cleanup_latency.total_seconds():.2f}s"
                    )
                ),
                tr(
                    style="font-weight: bold; background: #e8f0fe; border-top: 2px solid #1a73e8;"
                )(
                    td(style="padding: 8px 16px;")("Total Orchestrated Duration"),
                    td(style="padding: 8px 16px; text-align: right; color: #1a73e8;")(
                        f"{result.total_time_sec:.2f}s"
                    )
                )
            )
        )
    )

    doc = html(
        head(
            title(f"Details: {_escape_html(result.scenario_name)} - {_escape_html(result.head_name)}"),
            style(_DETAIL_CSS)
        ),
        body(
            h1(
                "Details: ",
                _escape_html(result.scenario_name),
                " ",
                span(style="color: #70757a; font-weight: normal;")(
                    "— ",
                    _escape_html(result.head_name)
                )
            ),
            p(
                a(href="index.html", style="color: #1a73e8; text-decoration: none; font-weight: 500;")(
                    "← Back to Summary"
                )
            ),
            banners,
            intro,
            rubric,
            h3("Conversation History"),
            history_turns,
            log_links,
            latency_table,
            footer(
                div(_class="time-stats")(
                    span("Started: ", strong(_format_ts(result.start_time))),
                    span("Ended: ", strong(_format_ts(result.end_time))),
                    span("Total Duration: ", strong(f"{result.total_time_sec:.1f}s")),
                    scoring_latency
                )
            )
        )
    )

    return f"<!DOCTYPE html>\n{doc}"


def _group_by_scenario(results: Sequence[benchmark.ConversationResult]):
    grouped = {}
    for r in results:
        grouped.setdefault(r.scenario_name, []).append(r)
    return grouped


def save_report(content: str, path: str) -> None:
    """Saves report content to disk."""
    dir_path = os.path.dirname(path)
    if dir_path:
        os.makedirs(dir_path, mode=0o755, exist_ok=True)
        os.chmod(dir_path, 0o755)
    with open(path, "w") as f:
        f.write(content)
    os.chmod(path, 0o644)


def _parse_timedelta(val: Any) -> datetime.timedelta:
    """Helper to parse serialized float seconds back to datetime.timedelta."""
    if val is None:
        return datetime.timedelta()
    try:
        return datetime.timedelta(seconds=float(val))
    except (ValueError, TypeError):
        return datetime.timedelta()


def load_json_report(file_path: str) -> benchmark.ConversationResult:
    """Loads a JSON file from disk and reconstructs the ConversationResult dataclass tree."""
    with open(file_path) as f:
        data = json.load(f)

    # 1. Parse TurnMetrics list
    turn_metrics = []
    for tm_dict in data.get("turn_metrics", []):
        # Parse ToolInteractions
        tool_interactions = []
        for ti_dict in tm_dict.get("tool_interactions", []):
            tool_interactions.append(
                benchmark.ToolInteraction(
                    name=ti_dict.get("name", ""),
                    args=ti_dict.get("args", {}),
                    output=ti_dict.get("output"),
                    thought=ti_dict.get("thought"),
                )
            )

        # Parse TrajectoryEvents
        events = []
        for ev_dict in tm_dict.get("events", []):
            if "subagent_id" in ev_dict:
                events.append(
                    benchmark.SubagentEvent(
                        subagent_id=ev_dict.get("subagent_id", ""),
                        action=ev_dict.get("action", ""),
                        prompt=ev_dict.get("prompt"),
                        source=ev_dict.get("source", "main"),
                    )
                )
            elif "text" in ev_dict:
                events.append(
                    benchmark.AgentMessageEvent(
                        text=ev_dict.get("text", ""),
                        is_thought=ev_dict.get("is_thought", False),
                        source=ev_dict.get("source", "main"),
                    )
                )
            elif "output" in ev_dict:
                events.append(
                    benchmark.ToolResultEvent(
                        call_id=ev_dict.get("call_id", ""),
                        output=ev_dict.get("output", ""),
                        is_error=ev_dict.get("is_error", False),
                        source=ev_dict.get("source", "main"),
                    )
                )
            elif "call_id" in ev_dict:
                events.append(
                    benchmark.ToolCallEvent(
                        call_id=ev_dict.get("call_id", ""),
                        name=ev_dict.get("name", ""),
                        args=ev_dict.get("args", {}),
                        source=ev_dict.get("source", "main"),
                    )
                )

        turn_metrics.append(
            benchmark.TurnMetrics(
                latency_sec=tm_dict.get("latency_sec", 0.0),
                simulator_latency_sec=tm_dict.get("simulator_latency_sec", 0.0),
                tool_calls=tm_dict.get("tool_calls", 0),
                tool_interactions=tool_interactions,
                events=events,
            )
        )

    # 2. Parse RubricResult
    rubric_results = None
    rr_dict = data.get("rubric_results")
    if rr_dict:
        scores = [
            benchmark.RubricCriterion(
                criteria=rc.get("criteria", ""),
                score=rc.get("score", 0),
                reasoning=rc.get("reasoning", ""),
            )
            for rc in rr_dict.get("scores", [])
        ]
        rubric_results = benchmark.RubricResult(
            scores=scores,
            summary=rr_dict.get("summary", ""),
            total_score=rr_dict.get("total_score", 0),
            max_score=rr_dict.get("max_score", 0),
        )

    # 3. Parse execution status enum
    status_val = data.get("status", "FINISHED")
    try:
        status = benchmark.ExecutionStatus(status_val)
    except ValueError:
        status = benchmark.ExecutionStatus.FINISHED

    return benchmark.ConversationResult(
        scenario_name=data.get("scenario_name", ""),
        scenario_text=data.get("scenario_text", ""),
        head_name=data.get("head_name", ""),
        turns=data.get("turns", 0),
        total_time_sec=data.get("total_time_sec", 0.0),
        messages=data.get("messages", []),
        turn_metrics=turn_metrics,
        status=status,
        success=data.get("success"),
        failure_reason=data.get("failure_reason"),
        rubric_results=rubric_results,
        scoring_latency_sec=data.get("scoring_latency_sec", 0.0),
        start_time=data.get("start_time", 0.0),
        end_time=data.get("end_time", 0.0),
        log_files=data.get("log_files", []),
        trajectory_id=data.get("trajectory_id"),
        init_queued_latency=_parse_timedelta(data.get("init_queued_latency")),
        init_active_latency=_parse_timedelta(data.get("init_active_latency")),
        conversing_latency=_parse_timedelta(data.get("conversing_latency")),
        scoring_latency=_parse_timedelta(
            data.get("scoring_latency") or data.get("scoring_latency_sec")
        ),
        cleanup_latency=_parse_timedelta(data.get("cleanup_latency")),
    )
