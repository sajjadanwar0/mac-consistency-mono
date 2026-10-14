"""
autogen_pilot.py - drive AutoGen multi-agent tasks across multiple workloads
and multiple LLM providers (OpenAI, Anthropic, local Ollama).

Workloads:
  edit-review    : 2 agents read+write doc concurrently. A_1-prone.
  plan-execute   : Planner writes plan, Executor reads it. Sequential, A_1-suppressing.
  triage         : 3 agents pipeline ticket -> priority -> resolution. Multi-stage.

Providers:
  openai     : gpt-4o (default), gpt-4o-mini, etc. Requires OPENAI_API_KEY.
  anthropic  : claude-3-5-sonnet-20241022 (default). Requires ANTHROPIC_API_KEY
               and `autogen-ext[anthropic]` installed.
  ollama     : llama3.2:latest (default), any local Ollama model. Requires
               Ollama daemon at http://localhost:11434/. No API key.

Token capture:
  Every run_one() session records per-call usage (prompt_tokens,
  completion_tokens, wall_clock_ms, cost_usd) into a sidecar JSONL file
  named `{workload}-{runtime}-{scenario_id:04d}.tokens.jsonl` under
  --tokens-output. Aggregate later with `python tokens_capture.py <dir>`.

Examples:
  uv run python autogen_pilot.py --provider openai    --workload edit-review --n 3
  uv run python autogen_pilot.py --provider anthropic --workload edit-review --n 3 \\
      --tokens-output ../pilot_tokens_claude
  uv run python autogen_pilot.py --provider ollama    --workload edit-review --n 3 \\
      --tokens-output ../pilot_tokens_llama
"""

from __future__ import annotations
import argparse, asyncio, os, time
from pathlib import Path
from autogen_agentchat.agents import AssistantAgent
from autogen_agentchat.teams import RoundRobinGroupChat
from autogen_agentchat.conditions import MaxMessageTermination, TextMentionTermination

from tokens_capture import SessionRecorder, Pricing

import sys as _sys
_runtime = "vanilla"
if "--runtime" in _sys.argv:
    _idx = _sys.argv.index("--runtime")
    if _idx + 1 < len(_sys.argv):
        _runtime = _sys.argv[_idx + 1]

if _runtime == "pessimistic":
    from baselines.runtimes.pessimistic import (
        make_scenario_pessimistic as make_scenario,
        PessimisticAgent as InstrumentedAgent,
        PessimisticStore as SharedStore,
        PessimisticToolRegistry as ToolRegistry,
        PessimisticRecorder as Recorder,
    )
elif _runtime == "snapshot_isolation":
    from baselines.runtimes.snapshot_isolation import (
        make_scenario_si as make_scenario,
        SIAgent as InstrumentedAgent,
        MVCCStore as SharedStore,
        SIToolRegistry as ToolRegistry,
        SIRecorder as Recorder,
    )
else:
    from instrument import (
        make_scenario,
        InstrumentedAgent,
        SharedStore,
        ToolRegistry,
        Recorder,
    )


DEFAULT_MODEL = {
    "openai": "gpt-4o",
    "anthropic": "claude-sonnet-4-5-20250929",
    "ollama": "llama3.2:latest",
}

OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1")


def _pricing_for(provider: str, model_name: str) -> Pricing:
    """Return Pricing for cost computation. Local models: zero cost."""
    if provider == "anthropic":
        m = model_name.lower()
        if "haiku-4" in m or "haiku-3-5" in m:
            return Pricing(input_per_m_usd=1.00, output_per_m_usd=5.00, label=model_name)
        if "opus-4" in m:
            return Pricing(input_per_m_usd=5.00, output_per_m_usd=25.00, label=model_name)
        if "opus-3" in m:
            return Pricing(input_per_m_usd=15.00, output_per_m_usd=75.00, label=model_name)
        return Pricing(input_per_m_usd=3.00, output_per_m_usd=15.00, label=model_name)
    if provider == "ollama":
        return Pricing(input_per_m_usd=0.0, output_per_m_usd=0.0, label=f"{model_name}-local")
    if "mini" in model_name.lower():
        return Pricing(input_per_m_usd=0.15, output_per_m_usd=0.60, label=model_name)
    return Pricing(input_per_m_usd=2.50, output_per_m_usd=10.00, label=model_name)


def _make_model_client(provider: str, model_name: str):
    """Construct the AutoGen chat-completion client for the chosen provider."""
    if provider == "anthropic":
        try:
            from autogen_ext.models.anthropic import AnthropicChatCompletionClient
        except ImportError as e:
            raise SystemExit(
                "Anthropic support requires `autogen-ext[anthropic]`. "
                "Install with: uv add 'autogen-ext[anthropic]'"
            ) from e
        return AnthropicChatCompletionClient(model=model_name)

    if provider == "ollama":
        from autogen_ext.models.openai import OpenAIChatCompletionClient
        return OpenAIChatCompletionClient(
            model=model_name,
            base_url=OLLAMA_BASE_URL,
            api_key="ollama",
            model_info={
                "vision": False,
                "function_calling": True,
                "json_output": False,
                "family": "llama",
                "structured_output": False,
            },
        )

    from autogen_ext.models.openai import OpenAIChatCompletionClient
    return OpenAIChatCompletionClient(model=model_name)


def _check_api_key(provider: str) -> None:
    if provider == "openai" and not os.environ.get("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY not set")
    if provider == "anthropic" and not os.environ.get("ANTHROPIC_API_KEY"):
        raise SystemExit("ANTHROPIC_API_KEY not set")


def make_tools(agent):
    def read_state(keys: list[str]) -> dict[str, str]:
        if agent._pending is not None:
            agent.commit(write_kv=None)
        agent.begin(keys)
        return dict(agent._pending["read_values"])

    def write_state(updates: dict[str, str]) -> str:
        if agent._pending is None:
            agent.begin([])
        agent.commit(write_kv=updates)
        return f"COMMITTED: {updates}"

    return read_state, write_state


WORKLOADS = {
    "edit-review": {
        "agents": ["editor", "reviewer"],
        "task": "Begin the protocol.",
        "max_messages": 12,
        "prompts": {
            "editor": (
                "You are a document editor in a strict tool-use protocol.\n"
                "STEP 1: Call read_state(keys=['doc']).\n"
                "STEP 2: Call write_state(updates={'doc': '<one-sentence definition of distributed systems>'}).\n"
                "STEP 3: Reply with exactly DONE.\n"
                "No prose before STEP 3."
            ),
            "reviewer": (
                "You are a reviewer in a strict tool-use protocol.\n"
                "STEP 1: Call read_state(keys=['doc']).\n"
                "STEP 2: Call write_state(updates={'review': '<one-sentence review>'}).\n"
                "STEP 3: Reply with exactly DONE.\n"
                "No prose before STEP 3."
            ),
        },
    },
    "plan-execute": {
        "agents": ["planner", "executor"],
        "task": "Begin the protocol.",
        "max_messages": 12,
        "prompts": {
            "planner": (
                "You are a planner in a strict tool-use protocol.\n"
                "STEP 1: Call write_state(updates={'plan': '<two-step plan to count from 1 to 3>'}).\n"
                "STEP 2: Reply with exactly DONE.\n"
                "Do not call read_state. Do not write to any cell other than 'plan'."
            ),
            "executor": (
                "You are an executor in a strict tool-use protocol.\n"
                "STEP 1: Call read_state(keys=['plan']).\n"
                "STEP 2: Call write_state(updates={'result': '<execution result based on the plan>'}).\n"
                "STEP 3: Reply with exactly DONE.\n"
                "Do not write to any cell other than 'result'."
            ),
        },
    },
    "triage": {
        "agents": ["reporter", "triager", "engineer"],
        "task": "Begin the protocol.",
        "max_messages": 18,
        "prompts": {
            "reporter": (
                "You are an issue reporter in a strict tool-use protocol.\n"
                "STEP 1: Call write_state(updates={'ticket': '<one-sentence bug description>'}).\n"
                "STEP 2: Reply with exactly DONE.\n"
                "Do not call read_state."
            ),
            "triager": (
                "You are a triager in a strict tool-use protocol.\n"
                "STEP 1: Call read_state(keys=['ticket']).\n"
                "STEP 2: Call write_state(updates={'priority': '<P0|P1|P2>'}).\n"
                "STEP 3: Reply with exactly DONE."
            ),
            "engineer": (
                "You are an engineer in a strict tool-use protocol.\n"
                "STEP 1: Call read_state(keys=['ticket', 'priority']).\n"
                "STEP 2: Call write_state(updates={'resolution': '<one-sentence resolution>'}).\n"
                "STEP 3: Reply with exactly DONE."
            ),
        },
    },
}


# 2026-10-14: the triage reporter is told to write "<one-sentence bug description>" but is given
# no bug.  gpt-4o invents one; claude-sonnet-4-5 wrote "no bug description provided" in 100/100
# sessions (the void cell of the Claude replication, supplement S M).  With --seeded-tickets
# (default on) the reporter is handed a concrete bug, drawn from this list by scenario id, so
# the cell measures the protocol and not whether a model fabricates content.  The gpt-4o
# campaign 20260913T0150Z predates this flag; its manifest says seeded_tickets=false.
SEEDED_BUGS = [
    "The export button returns a 500 error when the report has more than 1,000 rows.",
    "Password reset emails arrive with an expired link if the user has two-factor enabled.",
    "The dashboard shows yesterday's totals until the page is reloaded twice.",
    "Uploading a PNG larger than 8 MB silently truncates the file.",
    "Search results ignore the date filter when sorted by relevance.",
    "The mobile menu cannot be closed after rotating the device.",
    "Invoices are generated with the previous month's tax rate on the first of the month.",
    "The API returns duplicate records when paginating with a page size of 50.",
    "Deleting a project leaves its scheduled jobs running.",
    "Timezone offsets are applied twice on the calendar view for UTC+5 users.",
    "The CSV importer rejects rows whose names contain an apostrophe.",
    "Notifications are sent to archived users.",
    "The settings page loses unsaved changes when the session token refreshes.",
    "Currency totals are rounded before summation, so the grand total is off by cents.",
    "The audit log records the wrong actor for actions performed through the API.",
    "Long comments overflow the card layout on narrow screens.",
    "The nightly backup job fails when a table name contains a hyphen.",
    "Webhooks are retried indefinitely after a 410 response.",
    "The login page redirects to the home page instead of the originally requested URL.",
    "Thumbnails are not regenerated after an image is replaced.",
    "Bulk edit applies the change to the first page of results only.",
    "The rate limiter counts failed requests twice.",
    "Dark mode renders chart labels in black on a dark background.",
    "The invitation link works only once even when the invite allows multiple uses.",
    "Searching for an exact email address returns partial matches first.",
]
SEEDED_TICKETS = True


def _attach_token_recorder(model_client, tok_rec: SessionRecorder) -> None:
    """
    Monkey-patch the AutoGen model client's `.create(...)` method so that
    every model call routes its usage (prompt_tokens / completion_tokens /
    wall_clock_ms) into `tok_rec`. Preserves the client's type and all
    other attributes for AutoGen's internal checks. Works identically for
    OpenAI, Anthropic, and Ollama (via OpenAI-compat) clients because all
    three return a CreateResult with `.usage`.
    """
    original_create = model_client.create

    async def patched_create(*args, **kwargs):
        t0 = time.monotonic()
        result = await original_create(*args, **kwargs)
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        tok_rec.record_response(result, wall_clock_ms=elapsed_ms)
        return result

    model_client.create = patched_create


async def run_one(scenario_id: int,
                  output_dir: Path,
                  provider: str,
                  model_name: str,
                  workload: str,
                  tokens_dir: Path) -> Path:
    wl = WORKLOADS[workload]
    out = output_dir / f"{workload}-trace-{scenario_id:04d}.jsonl"
    store = SharedStore()
    tools_reg = ToolRegistry(["search", "code", "review"])
    recorder = Recorder(out)
    recorder.open()

    iagents = {a: InstrumentedAgent(a, store, tools_reg, recorder) for a in wl["agents"]}
    tools_per_agent = {a: make_tools(ia) for a, ia in iagents.items()}

    session_id = f"{workload}-{_runtime}-{scenario_id:04d}"
    pricing = _pricing_for(provider, model_name)

    with SessionRecorder(tokens_dir, session_id, _runtime, workload,
                         pricing=pricing) as tok_rec:
        model = _make_model_client(provider, model_name)
        _attach_token_recorder(model, tok_rec)

        chat_agents = []
        for name in wl["agents"]:
            rd, wr = tools_per_agent[name]
            prompt = wl["prompts"][name]
            if SEEDED_TICKETS and workload == "triage" and name == "reporter":
                prompt += f"\nThe bug you observed (report exactly this, in one sentence): {SEEDED_BUGS[scenario_id % len(SEEDED_BUGS)]}"
            chat_agents.append(AssistantAgent(
                name=name, model_client=model, tools=[rd, wr],
                system_message=prompt,
                reflect_on_tool_use=False,
            ))

        termination = TextMentionTermination("DONE") | MaxMessageTermination(max_messages=wl["max_messages"])
        team = RoundRobinGroupChat(chat_agents, termination_condition=termination)
        await team.run(task=wl["task"])

        for ia in iagents.values():
            if ia._pending is not None:
                ia.commit(write_kv=None)

    recorder.close()
    return out


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=10)
    parser.add_argument("--workload", choices=list(WORKLOADS.keys()), default="edit-review")
    parser.add_argument("--runtime", choices=["vanilla", "pessimistic", "snapshot_isolation"], default="vanilla")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output", type=Path, default=None,
                        help="defaults to ../<workload>-traces/")
    parser.add_argument("--tokens-output", type=Path, default=None,
                        help="defaults to ../pilot_tokens/ (use one dir per provider)")
    parser.add_argument("--provider", choices=["openai", "anthropic", "ollama"],
                        default="openai")
    parser.add_argument("--model", type=str, default=None,
                        help="model name; defaults are gpt-4o / claude-3-5-sonnet-20241022 / llama3.2:latest")
    parser.add_argument("--no-seeded-tickets", action="store_true",
                        help="triage: do NOT hand the reporter a concrete bug (the pre-2026-10-14 protocol of run 20260913T0150Z)")
    args = parser.parse_args()
    global SEEDED_TICKETS
    SEEDED_TICKETS = not args.no_seeded_tickets

    model_name = args.model or DEFAULT_MODEL[args.provider]
    _check_api_key(args.provider)

    output = args.output or Path(f"../{args.workload}-traces")
    output.mkdir(parents=True, exist_ok=True)

    tokens_output = args.tokens_output or Path("../pilot_tokens")
    tokens_output.mkdir(parents=True, exist_ok=True)

    print(f"provider={args.provider}  model={model_name}  workload={args.workload}  runtime={_runtime}  n={args.n}  seeded_tickets={SEEDED_TICKETS}")
    import json as _json
    (output / "protocol.json").write_text(_json.dumps({"seeded_tickets": SEEDED_TICKETS, "provider": args.provider, "model": model_name,
                                                        "workload": args.workload, "runtime": _runtime, "n": args.n, "seed": args.seed}, indent=1))
    print(f"traces  -> {output.resolve()}")
    print(f"tokens  -> {tokens_output.resolve()}")
    print()

    yields = {"empty": 0, "1_event": 0, "2_events": 0, "3plus_events": 0}
    for i in range(args.n):
        out = await run_one(i, output, args.provider, model_name, args.workload, tokens_output)
        n_events = sum(1 for _ in out.read_text().splitlines() if _.strip())
        if n_events == 0:   yields["empty"] += 1
        elif n_events == 1: yields["1_event"] += 1
        elif n_events == 2: yields["2_events"] += 1
        else:               yields["3plus_events"] += 1
        if (i + 1) % 10 == 0 or i == args.n - 1:
            t = sum(v for k,v in yields.items() if k != "empty")
            print(f"  {i+1}/{args.n}  yield={t}/{i+1}  dist={dict(yields)}")
    print(f"\nWorkload {args.workload!r} ({args.provider}/{model_name}) final yield: {yields}")


if __name__ == "__main__":
    asyncio.run(main())