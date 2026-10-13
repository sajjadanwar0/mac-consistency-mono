#!/usr/bin/env python3
"""301_a6_toolnode_real_latency.py -- A6 on LangGraph's released ToolNode with
REAL tool effects and REAL latency, replaying the model-emitted call batches the
paper already recorded.  No API key.

Why.  Sec 5.10's reorder is driven by `await asyncio.sleep(rng.uniform(0.01,
0.20))` -- a modeled latency.  A referee reads "co = argsort(latency)" and
concludes the experiment measured asyncio, not LangGraph.  This probe keeps the
executor and the emitted call orders (recorded in results/langgraph_a6_natural/
<model>/sess-NNNN.jsonl, field `emitted`) and replaces the sleep with the kind
of effect a real pipeline step performs:

  sqlite   each tool is an INSERT + fsync into its own on-disk SQLite file
           (create_database creates the file; run_migrations adds a table; ...),
           so the COMMIT ORDER is the order rows reach disk -- a real external
           effect with real, unmodeled latency variance.
  http     each tool POSTs to a local threaded HTTP server whose handler does a
           proportional amount of real work (hashing) -- a stand-in for a
           network service with service-time variance that nobody chose.

Both are order-dependent in the obvious way (migrations before seed, index
before traffic), and both are irreversible once issued.  The probe records,
per replayed batch, the committed effect order under the default ToolNode
(asyncio.gather) and under the L3 commit-order sequencer (issue, await, next),
and the ToolMessage order the transcript shows.

    uv run --project envs/langgraph-1.2.5 python probes/301_a6_toolnode_real_latency.py \
        --batches results/langgraph_a6_natural --effect sqlite --reps 5 \
        --out results/a6_real_latency/sqlite.jsonl

    python3 probes/301_a6_toolnode_real_latency.py --selftest   # no langgraph: exercises
                                                                 # the effect backends and
                                                                 # the scoring only

Receipt (one JSON line per replay):
  {"model","session","rep","effect","emitted":[...],"io":[...],
   "baseline_co":[...],"baseline_a6":bool,"baseline_inversions":int,
   "toolmessage_preserved":bool,"l3_co":[...],"l3_a6":false,
   "effect_ms":{tool: [dispatch_ms, commit_ms]}}

What a referee can then read: a reorder rate under latency the harness did not
pick, per backend; and whether the transcript still hides it.
"""
from __future__ import annotations
from typing import Annotated, TypedDict
add_messages = None   # bound in build(); LangGraph evaluates the state schema's (string) annotations in module globals
import argparse, asyncio, glob, hashlib, json, os, sqlite3, sys, tempfile, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PIPELINE = ["create_database", "run_migrations", "seed_reference_data", "build_search_index", "enable_live_traffic"]
PURPOSE = {
    "create_database":     "Create the empty production database instance. Must run first.",
    "run_migrations":      "Apply schema migrations. Requires the database to already exist.",
    "seed_reference_data": "Load reference data. Requires migrations to have been applied.",
    "build_search_index":  "Build the search index. Requires reference data to be present.",
    "enable_live_traffic": "Route live traffic to the database. Requires the search index to be built.",
}
# how much real work each step does (rows for sqlite, bytes hashed for http) --
# deliberately NOT tuned to produce reorders; a migration simply does more than a flag flip
WORK = {"create_database": 1, "run_migrations": 40, "seed_reference_data": 200,
        "build_search_index": 120, "enable_live_traffic": 1}

SINK: list[tuple[str, float, float]] = []   # (tool, dispatch_ms, commit_ms) in COMMIT order
T0 = 0.0


# ----------------------------------------------------------------------------- effects
class SqliteEffects:
    """Each tool commits rows into ONE shared on-disk database; the commit order
    is the order the transactions reach the WAL.  Real fsync, real contention."""
    def __init__(self, directory: str):
        self.path = os.path.join(directory, "pipeline.db")
        self.lock = threading.Lock()

    def reset(self):
        for ext in ("", "-wal", "-shm", "-journal"):
            try: os.remove(self.path + ext)
            except FileNotFoundError: pass
        con = sqlite3.connect(self.path)
        con.execute("PRAGMA journal_mode=WAL"); con.execute("PRAGMA synchronous=FULL")
        con.execute("CREATE TABLE effects(seq INTEGER PRIMARY KEY, tool TEXT, payload BLOB)")
        con.commit(); con.close()

    def do(self, tool: str) -> None:   # runs in a worker thread
        con = sqlite3.connect(self.path, timeout=30)
        con.execute("PRAGMA synchronous=FULL")
        with con:
            for k in range(WORK[tool]):
                con.execute("INSERT INTO effects(tool, payload) VALUES (?, ?)", (tool, os.urandom(256)))
        con.close()

    def committed_order(self) -> list[str]:
        con = sqlite3.connect(self.path)
        rows = con.execute("SELECT tool FROM effects ORDER BY seq").fetchall(); con.close()
        order, seen = [], set()
        for (t,) in rows:
            if t not in seen: seen.add(t); order.append(t)
        return order


class HttpEffects:
    """A local threaded HTTP service with real service-time variance: each
    request hashes WORK[tool] KiB before acknowledging.  Commit order is the
    order acknowledgements leave the server."""
    class H(BaseHTTPRequestHandler):
        log: list = []; lock = threading.Lock()
        def do_POST(self):
            n = int(self.headers.get("Content-Length", "0")); body = self.rfile.read(n)
            tool = body.decode()
            buf = os.urandom(1024 * WORK[tool]); hashlib.sha256(buf).hexdigest()
            with self.lock: self.log.append((tool, time.perf_counter()))
            self.send_response(200); self.end_headers(); self.wfile.write(b"ok")
        def log_message(self, *a): pass

    def __init__(self, directory: str):
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), self.H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.port = self.srv.server_address[1]

    def reset(self): self.H.log.clear()

    def do(self, tool: str) -> None:
        import http.client
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        c.request("POST", "/effect", body=tool.encode()); c.getresponse().read(); c.close()

    def committed_order(self) -> list[str]:
        return [t for t, _ in sorted(self.H.log, key=lambda x: x[1])]


def make_backend(kind: str, directory: str):
    return SqliteEffects(directory) if kind == "sqlite" else HttpEffects(directory)


# ----------------------------------------------------------------------------- scoring
def a6_witness(io, co): return len(io) >= 2 and len(io) == len(co) and io != co
def inversions(co): return sum(1 for i in range(len(co)) for j in range(i + 1, len(co)) if co[i] > co[j])


def load_batches(root: str):
    """yield (model, session, emitted) for every batched turn the paper recorded"""
    for mdir in sorted(glob.glob(os.path.join(root, "*"))):
        model = os.path.basename(mdir)
        for fp in sorted(glob.glob(os.path.join(mdir, "sess-*.jsonl"))):
            d = json.load(open(fp))
            if d.get("batched") and len(d.get("emitted", [])) >= 2:
                yield model, int(d.get("session", os.path.basename(fp)[5:9])), list(d["emitted"])


# ----------------------------------------------------------------------------- langgraph
def build(backend):
    global add_messages
    from langchain_core.tools import tool
    from langgraph.prebuilt import ToolNode
    from langgraph.graph import StateGraph, START, END
    from langgraph.graph.message import add_messages as _add_messages
    add_messages = _add_messages

    def make_tool(name):
        async def _f(target: str = "production") -> str:
            disp = (time.perf_counter() - T0) * 1000.0
            await asyncio.to_thread(backend.do, name)          # REAL effect, real latency
            SINK.append((name, disp, (time.perf_counter() - T0) * 1000.0))
            return f"{name}: completed for {target}"
        _f.__name__ = name; _f.__doc__ = PURPOSE[name]
        return tool(_f)
    tools = [make_tool(n) for n in PIPELINE]

    class S(TypedDict):
        messages: Annotated[list, add_messages]
    g = StateGraph(S); g.add_node("tools", ToolNode(tools)); g.add_edge(START, "tools"); g.add_edge("tools", END)
    return g.compile(), {n: t for n, t in zip(PIPELINE, tools)}


async def baseline(app, calls):
    from langchain_core.messages import AIMessage, ToolMessage
    global SINK, T0
    SINK = []; T0 = time.perf_counter()
    out = await app.ainvoke({"messages": [AIMessage(content="", tool_calls=calls)]})
    return list(SINK), [m.name for m in out["messages"] if isinstance(m, ToolMessage)]


async def l3(toolmap, calls):
    global SINK, T0
    SINK = []; T0 = time.perf_counter()
    for c in calls:
        await toolmap[c["name"]].ainvoke(c["args"])
    return [s[0] for s in SINK]


async def replay(args):
    tmp = tempfile.mkdtemp(prefix="a6real_")
    backend = make_backend(args.effect, tmp)
    app, toolmap = build(backend)
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    n = reord = 0
    with open(args.out, "w") as out:
        for model, session, emitted in load_batches(args.batches):
            if args.models and model not in args.models: continue
            calls = [{"name": nm, "args": {"target": "production"}, "id": f"c{i}"} for i, nm in enumerate(emitted)]
            pos = {nm: i for i, nm in enumerate(emitted)}; io = list(range(len(emitted)))
            for rep in range(args.reps):
                backend.reset()
                sink, tmsgs = await baseline(app, calls)
                co_sink = [pos[t] for t, _, _ in sink]
                co_store = [pos[t] for t in backend.committed_order()]    # what the WORLD recorded
                backend.reset()
                l3_co = [pos[t] for t in await l3(toolmap, calls)]
                rec = {"model": model, "session": session, "rep": rep, "effect": args.effect,
                       "emitted": emitted, "io": io,
                       "baseline_co": co_store, "baseline_co_by_return": co_sink,
                       "baseline_a6": a6_witness(io, co_store), "baseline_inversions": inversions(co_store),
                       "toolmessage_preserved": [pos[t] for t in tmsgs] == io,
                       "l3_co": l3_co, "l3_a6": a6_witness(io, l3_co),
                       "effect_ms": {t: [round(d, 2), round(c, 2)] for t, d, c in sink}}
                out.write(json.dumps(rec) + "\n"); n += 1; reord += rec["baseline_a6"]
                assert not rec["l3_a6"], "L3 sequencer reordered -- impossible by construction"
    print(f"{n} replays, effect={args.effect}: baseline A6 in {reord} ({100*reord/max(n,1):.1f}%), L3 in 0; receipt {args.out}")


def selftest():
    """no langgraph: dispatch the pipeline through asyncio.gather on each real
    backend and show that the committed order is whatever the world decided."""
    tmp = tempfile.mkdtemp(prefix="a6self_")
    for kind in ("sqlite", "http"):
        b = make_backend(kind, tmp); b.reset()
        async def go():
            await asyncio.gather(*(asyncio.to_thread(b.do, t) for t in PIPELINE))
        asyncio.run(go())
        co = [PIPELINE.index(t) for t in b.committed_order()]
        print(f"selftest {kind:6s}: io={list(range(5))} co={co} a6={a6_witness(list(range(5)), co)} inversions={inversions(co)}")
    print("selftest ok (scoring + both effect backends work without langgraph)")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--batches", default="results/langgraph_a6_natural")
    ap.add_argument("--effect", choices=["sqlite", "http"], default="sqlite")
    ap.add_argument("--reps", type=int, default=5)
    ap.add_argument("--models", nargs="*", default=None)
    ap.add_argument("--out", default="results/a6_real_latency/sqlite.jsonl")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        selftest(); return 0
    try:
        import langgraph  # noqa: F401
    except ImportError:
        print("langgraph not importable; run inside envs/langgraph-1.2.5 (uv run --project ...) or use --selftest", file=sys.stderr)
        return 2
    asyncio.run(replay(a)); return 0


if __name__ == "__main__":
    sys.exit(main())
