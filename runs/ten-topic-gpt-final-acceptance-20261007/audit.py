"""Independent acceptance: raw graph, own sampler/ranker/draw/ledger/statistics; no Provider."""

import ast
import csv
import hashlib
import json
import math
import random
from collections import Counter, defaultdict
from decimal import Decimal
from pathlib import Path

W = Path("/Users/liuqingyuan/.codex/worktrees/ten-topic-offline-replay/llm-abm-marketing-sim")
R = W / "runs/ten-topic-gpt-studies-20261006"
OUT = Path(__file__).resolve().parent
OLD = Path("/Users/liuqingyuan/work/llm-abm-marketing-sim/runs")
ARMS = (
    "baseline",
    "activity_weights",
    "activity_p99",
    "local_weights_fixed",
    "local_weights_rebuilt",
    "local_p99_fixed",
    "local_p99_rebuilt",
)
WEIGHTS = (
    (0.5, 0.3, 0.2),
    (0.65, 0.15, 0.2),
    (0.35, 0.45, 0.2),
    (0.65, 0.3, 0.05),
    (0.35, 0.3, 0.35),
    (0.5, 0.45, 0.05),
    (0.5, 0.15, 0.35),
)
CONFIG = None
SEEDS = list(range(2026091700, 2026091800))
RULE = "sha256-bank-seed-user-message-first53-v1"
issues = []
passes = {}
checks = Counter()
artifacts = {}


def canonical(x):
    return json.dumps(x, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def fp(x):
    return hashlib.sha256(canonical(x)).hexdigest()


def digest(p):
    h = hashlib.sha256()
    with Path(p).open("rb") as f:
        for b in iter(lambda: f.read(1024 * 1024), b""):
            h.update(b)
    return h.hexdigest()


def read(p):
    return json.loads(Path(p).read_bytes())


def rows(p):
    with Path(p).open() as f:
        return [json.loads(item) for item in f if item.strip()]


def csvrows(p):
    with Path(p).open(newline="") as f:
        return list(csv.DictReader(f))


def write(name, obj):
    (OUT / name).write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n")


def require(ok, label):
    if not ok:
        raise ValueError(label)
    checks[label] += 1


def pct(values, p):
    v = sorted(values)
    x = (len(v) - 1) * p
    item = int(x)
    h = min(item + 1, len(v) - 1)
    return v[item] + (v[h] - v[item]) * (x - item)


def logscore(v, ref):
    return min(1.0, math.log1p(v) / math.log1p(ref)) if v > 0 and ref > 0 else 0.0


def key(r):
    return r["user_id"], r["message_id"], r["client_condition_sha256"]


def cf(a, b, x):
    tiny = 1e-300
    qab = a + b
    qap = a + 1
    qam = a - 1
    c = 1.0
    d = 1 - qab * x / qap
    d = 1 / (d if abs(d) > tiny else tiny)
    h = d
    for m in range(1, 401):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1 + aa * d
        d = d if abs(d) > tiny else tiny
        c = 1 + aa / c
        c = c if abs(c) > tiny else tiny
        d = 1 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1 + aa * d
        d = d if abs(d) > tiny else tiny
        c = 1 + aa / c
        c = c if abs(c) > tiny else tiny
        d = 1 / d
        delta = d * c
        h *= delta
        if abs(delta - 1) < 1e-14:
            return h
    raise ValueError("beta fraction did not converge")


def ibeta(a, b, x):
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    bt = math.exp(math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log1p(-x))
    return bt * cf(a, b, x) / a if x < (a + 1) / (a + b + 2) else 1 - bt * cf(b, a, 1 - x) / b


def tq(prob):
    lo = 0.0
    hi = 12.0
    for _ in range(65):
        z = (lo + hi) / 2
        cdf = 1 - 0.5 * ibeta(49.5, 0.5, 99 / (99 + z * z))
        if cdf < prob:
            lo = z
        else:
            hi = z
    return (lo + hi) / 2


def estimate(v, t):
    n = len(v)
    mean = sum(v) / n
    sd = math.sqrt(sum((x - mean) ** 2 for x in v) / (n - 1))
    se = sd / math.sqrt(n)
    return dict(mean=mean, sd=sd, mcse=se, lower=mean - t * se, upper=mean + t * se)


def close(a, b, label, tol=2e-9):
    require(math.isclose(float(a), float(b), rel_tol=tol, abs_tol=tol), label)


def ledger(stage, explicit=False):
    root = R / stage
    anchor = digest(root / ("authorization.json" if explicit else "preparation.json"))
    previous = anchor
    pending = {}
    success = {}
    unknown = []
    settled = []
    intents = []
    qualified = explicit
    peak = 0
    for ordinal, e in enumerate(rows(root / ("attempts.jsonl" if explicit else "collection/attempts.jsonl"))):
        require(e["sequence"] == ordinal and e["previous_sha256"] == previous, "ledger_chain")
        require(e["sha256"] == fp({k: v for k, v in e.items() if k != "sha256"}), "ledger_checksum")
        previous = e["sha256"]
        p = e["payload"]
        if e["kind"] == "intent":
            require(
                p["intent_sequence"] == ordinal and not any(q["pair_key"] == p["pair_key"] for q in pending.values()),
                "intent_unique",
            )
            require(qualified or p["purpose"] == "qualification", "qualification_before_judgment")
            pending[ordinal] = p
            intents.append(p)
            peak = max(peak, len(pending))
            require(peak <= 5, "maximum_five_inflight")
            if not explicit:
                require(
                    p["concurrency_authorization_sha256"] == digest(root / "collection/concurrency-authorization.json"),
                    "concurrency_binding",
                )
        else:
            require(e["kind"] == "settled" and p["intent_sequence"] in pending, "settlement_bound")
            intent = pending.pop(p["intent_sequence"])
            settled.append(p)
            if p["outcome"] == "succeeded":
                a = p["accounting"]
                require(
                    a["observed_model_counts"] == {"gpt-5.6-sol": 1}
                    and a["provider_response_count"]
                    == a["successful_decision_count"]
                    == a["usage_complete_response_count"]
                    == 1,
                    "real_model_usage",
                )
                require(
                    a["input_tokens"] + a["output_tokens"] == a["total_tokens"] and a["output_tokens"] <= 256,
                    "usage_and_ceiling",
                )
                if intent["purpose"] == "qualification":
                    qualified = True
                else:
                    r = p["bank_entry"]
                    require(
                        fp([r["user_id"], r["message_id"], r["client_condition_sha256"]]) == intent["pair_key"],
                        "response_exact_input",
                    )
                    require(key(r) not in success, "success_unique")
                    success[key(r)] = {
                        **r,
                        "collection_event_sha256": e["sha256"],
                        "collected_at_utc": e["recorded_at_utc"],
                    }
                    if explicit:
                        success[key(r)]["explicit_unknown_reissue_authorization_sha256"] = anchor
            elif p["outcome"] == "unknown":
                unknown.append({"key": intent["pair_key"], "event_sha256": e["sha256"]})
                require(p["subscription_nominal_cost_usd"] is None, "unknown_cost_not_zero")
            else:
                require(p["outcome"] == "retryable_failure", "failure_preserved")
    require(not pending, "no_pending_requests")
    return success, unknown, intents, settled, peak


def raw_graph(dataset, holdout, eligible):
    vids = {r["video_id"]: r for r in csvrows(dataset / "videos.csv")}
    allcomments = csvrows(dataset / "all_comments.csv")
    require(len({r["comment_id"] for r in allcomments}) == len(allcomments), "comment_ids_unique")
    comments = [r for r in allcomments if r["video_id"] != holdout]
    parents = {r["comment_id"]: r for r in comments}
    edges = Counter()
    degrees = Counter()
    neighbors = defaultdict(set)
    count = defaultdict(Counter)
    likes = Counter()

    def add(a, b):
        if a and b and a != b:
            edges[tuple(sorted((a, b)))] += 1
            degrees[a] += 1
            degrees[b] += 1
            neighbors[a].add(b)
            neighbors[b].add(a)

    for r in comments:
        u = r["commenter_user_id"]
        level = r["comment_level"].lower()
        if level not in ["comment", "reply"]:
            level = "reply" if r["parent_comment_id"] not in ["", "0", "-1"] else "comment"
        if u:
            count[u][level] += 1
            likes[u] += max(0, int(r["like_count"] or 0))
        target = (
            vids.get(r["video_id"], {}).get("creator_user_id", "")
            if level == "comment"
            else parents.get(r["parent_comment_id"], {}).get("commenter_user_id", "")
        )
        add(u, target)
        try:
            mentioned = json.loads(r["mentioned_user_ids"]) if r["mentioned_user_ids"] else []
        except json.JSONDecodeError:
            mentioned = ast.literal_eval(r["mentioned_user_ids"])
        for v in mentioned:
            add(u, str(v).strip())
    p95 = pct([degrees.get(u, 0) for u in eligible], 0.95)
    return vids, comments, edges, degrees, neighbors, count, likes, p95


def seeds(users, ids):
    g = sorted(ids, key=lambda u: (-users[u].global_influence_score, u))[:10]
    item = sorted(ids, key=lambda u: (-users[u].local_influence_score, u))[:10]
    return sorted(set(g + item))


def sample(users, vids, comments, edges, neighbors, seed):
    selected = seeds(users, list(users))
    chosen = set(selected)
    strength = Counter()
    for u in selected:
        for v in neighbors[u]:
            if v in users and v not in chosen:
                strength[v] += edges[tuple(sorted((u, v)))]
    near = sorted(strength, key=lambda u: (-strength[u], u))[: 1000 - len(selected)]
    chosen.update(near)
    scope_rank = {}
    for v in vids.values():
        scope_rank[v["source_challenge_name"]] = min(
            int(v["source_challenge_rank"]), scope_rank.get(v["source_challenge_name"], 10**9)
        )
    order = sorted(scope_rank, key=lambda x: (scope_rank[x], x))
    position = {x: i for i, x in enumerate(order)}
    hist = defaultdict(Counter)
    for c in comments:
        if c["commenter_user_id"] in users and c["video_id"] in vids:
            hist[c["commenter_user_id"]][vids[c["video_id"]]["source_challenge_name"]] += 1
    scopes = {}
    for u in sorted(users):
        c = hist[u]
        mx = max(c.values()) if c else 0
        scopes[u] = (
            min([x for x, n in c.items() if n == mx], key=lambda x: (position[x], x)) if c else "remaining_users"
        )
    pre = Counter(scopes[u] for u in chosen)
    ordinary = []

    def shuffle(ids, label):
        random.Random(int.from_bytes(hashlib.sha256(f"{seed}:{label}".encode()).digest()[:8], "big")).shuffle(ids)

    for sc in order:
        candidates = sorted(u for u in users if scopes[u] == sc and u not in chosen)
        shuffle(candidates, "seed-first-scope:" + sc)
        addition = candidates[: min(max(0, 100 - pre[sc]), 1000 - len(chosen))]
        ordinary += addition
        chosen.update(addition)
    fallback = sorted(set(users) - chosen)
    shuffle(fallback, "seed-first-scope-fallback")
    ordinary += fallback[: 1000 - len(chosen)]
    return selected + near + ordinary, selected


def run():
    global CONFIG
    require(not (OUT / "evidence-accepted.json").exists(), "fresh_acceptance_output")
    # Shared readers/types/renderer only. No production execution, verification, statistics or graph/sampling helpers.
    from llm_abm_sim import _parameter_judgment_bank as shared
    from llm_abm_sim.concurrent_message_experiment import _primary_variant_profile
    from llm_abm_sim.decision import DecisionInput
    from llm_abm_sim.prompting import build_engagement_prompt
    from llm_abm_sim.providers.pi_subscription import PiSubscriptionProviderClient
    from llm_abm_sim.schemas import PeerContext, PlatformContext

    PiSubscriptionProviderClient.__init__ = lambda *a, **k: (_ for _ in ()).throw(
        RuntimeError("PROVIDER_FORBIDDEN_IN_ACCEPTANCE")
    )
    original = read(OLD / "gpt-p0-dynamic-parameters-20260917-formal-01/study.json")
    CONFIG = original["configurations"]
    require(original["seeds"] == SEEDS and len(CONFIG) == 21, "original_protocol_matrix_seeds")
    require(
        CONFIG == [[f"w{i}-h{h}", list(w), h] for i, w in enumerate(WEIGHTS) for h in [1, 3, 6]],
        "original_exact_matrix",
    )
    # Original matrix is hash-bound and read as data, not treated as dynamic code.
    prep = read(R / "final-bank/preparation.json")
    cfg, legacy, _ = shared._inputs(read(Path(prep["audit"]["path"])))
    users = legacy.cohort.users_by_id
    eligible = list(users)
    dataset = cfg.dataset_dir
    holdout = cfg.sample_holdout_video_id
    vids, comments, edges, degrees, neighbors, counts, likes, p95 = raw_graph(dataset, holdout, eligible)
    require(p95 == 5 and len(edges) == 39779, "raw_merged_graph")
    require(all(c["video_id"] != holdout for c in comments), "holdout_excluded")
    mainmanifest = read(W / "runs/ten-topic-full-pool-20261006/main/manifest.json")
    graphid = fp(
        {
            "scope": mainmanifest["network"]["policy"],
            "holdout": holdout,
            "edges": [[a, b, w] for (a, b), w in sorted(edges.items())],
            "degrees": sorted(degrees.items()),
            "neighbors": [[u, sorted(n)] for u, n in sorted(neighbors.items())],
            "p95": p95,
        }
    )
    require(graphid == mainmanifest["network"]["graph_identity"], "raw_graph_identity")
    finaldataset = Path(mainmanifest["final_dataset"])
    for name in ["videos.csv", "all_comments.csv"]:
        require(
            digest(dataset / name)
            == digest(finaldataset / name)
            == read(finaldataset / "final_collection_report.json")["tables"][name]["sha256"],
            "actual_final_dataset_lineage",
        )
    topics = Counter((v["source_challenge_id"], v["source_challenge_name"]) for v in csvrows(dataset / "videos.csv"))
    require(len(topics) == 10, "actual_ten_topic_lineage")
    require(
        {n for i, n in topics}
        == {n.lstrip("#") for n in read(finaldataset / "scope_change_audit.json")["corrected_caption_hashtags"]},
        "corrected_final_topics_not_candidates",
    )
    for row in csvrows(dataset / "users.csv"):
        close(
            users[row["user_id"]].global_influence_score,
            float(row["global_influence_score"] or 0),
            "global_influence_unchanged",
        )
    histvids = {k: v for k, v in vids.items() if k != holdout}
    signals = {
        u: {
            "video_count": users[u].video_count,
            "comment_count": counts[u]["comment"],
            "reply_count": counts[u]["reply"],
            "edge_degree": degrees.get(u, 0),
            "comment_like_sum": likes.get(u, 0),
        }
        for u in eligible
    }
    thresholds = {f: round(pct([r[f] for r in signals.values()], 0.95), 6) for f in next(iter(signals.values()))}
    require(thresholds == legacy.cohort.thresholds, "raw_proxy_thresholds")
    for u, user in users.items():
        require(
            round(
                0.25 * logscore(signals[u]["video_count"], thresholds["video_count"])
                + 0.45 * logscore(signals[u]["comment_count"], thresholds["comment_count"])
                + 0.3 * logscore(signals[u]["reply_count"], thresholds["reply_count"]),
                6,
            )
            == user.activity_score,
            "activity_unchanged",
        )
        require(
            round(
                0.6 * logscore(degrees.get(u, 0), thresholds["edge_degree"])
                + 0.4 * logscore(likes.get(u, 0), thresholds["comment_like_sum"]),
                6,
            )
            == user.local_influence_score,
            "local_unchanged",
        )
    base_ids, base_seeds = sample(users, histvids, comments, edges, neighbors, cfg.random_seed)
    snapshots = {r["arm"]: r for r in read(R / "preflight-final/samples.json")}
    require(base_ids == snapshots["baseline"]["sample_user_ids"], "independent_sample_baseline")
    arms = {}
    inputs = {}
    allrequired = set()
    for arm in ARMS:
        armusers = dict(users)
        if arm != "baseline":
            fields = (
                ("video_count", "comment_count", "reply_count")
                if arm.startswith("activity")
                else ("edge_degree", "comment_like_sum")
            )
            weights = (
                (0.2, 0.4, 0.4)
                if arm == "activity_weights"
                else (0.25, 0.45, 0.3)
                if arm.startswith("activity")
                else (0.7, 0.3)
                if "weights" in arm
                else (0.6, 0.4)
            )
            refs = {f: pct([r[f] for r in signals.values()], 0.99) if "p99" in arm else thresholds[f] for f in fields}
            for u, user in users.items():
                armusers[u] = user.model_copy(
                    update={
                        ("activity_score" if arm.startswith("activity") else "local_influence_score"): round(
                            sum(w * logscore(signals[u][f], refs[f]) for f, w in zip(fields, weights, strict=True)), 6
                        )
                    }
                )
        ids, ss = (
            sample(armusers, histvids, comments, edges, neighbors, cfg.random_seed)
            if arm.endswith("rebuilt")
            else (base_ids, seeds(armusers, base_ids))
        )
        require(
            ids == snapshots[arm]["sample_user_ids"] and ss == snapshots[arm]["seed_user_ids"], "independent_arm_sample"
        )
        arms[arm] = (armusers, ids, set(ss))
        mapping = {}
        for u in ids:
            for msg in cfg.messages:
                data = DecisionInput(
                    post=msg.as_post(),
                    profile=_primary_variant_profile(armusers[u]),
                    peer_context=PeerContext(),
                    platform_context=PlatformContext(),
                    time_step=0,
                    prompt_version=prep["request_condition"]["prompt_version"],
                )
                rendered = build_engagement_prompt(data)
                mh = fp(rendered)
                ch = fp({"client_messages_sha256": mh, "request_condition": prep["request_condition"]})
                # Identity specification belongs to shared renderer/transport; compare shared identity spelling as a transparent dependency.
                mapping[u, msg.message_id] = (mh, ch)
                allrequired.add((u, msg.message_id, ch))
        inputs[arm] = mapping
    final = rows(R / "final-bank/closed-bank.jsonl")
    bankindex = {key(r): r for r in final}
    require(
        len(final) == len(bankindex) == len(allrequired) == 17520 and set(bankindex) == allrequired,
        "complete_exact_bank",
    )
    inherited = rows(R / "formal-bank/accepted-bank.jsonl")
    require(len(inherited) == 10308, "reuse_count")
    oldpool = {}
    for file in [
        OLD / "gpt-p0-bank-topup-20260917-authorized-01/closed-bank.jsonl",
        OLD / "gpt-p0-index-sensitivity-20260920-formal-01/unattempted-stage-01/closed-bank.jsonl",
    ]:
        for record in rows(file):
            if key(record) in oldpool:
                require(oldpool[key(record)]["decision"] == record["decision"], "old_duplicate_decision_consistency")
            oldpool[key(record)] = record
    for record in inherited:
        require(key(record) in oldpool, "reused_input_original_library")
        originalrecord = oldpool[key(record)]
        for field in [
            "user_id",
            "message_id",
            "client_messages_sha256",
            "client_condition_sha256",
            "decision",
            "source",
            "acceptance_policy",
        ]:
            require(record[field] == originalrecord[field], "old_judgment_not_rewritten")
    expected_records = {key(r): r for r in inherited}
    unknowns = []
    totalintents = []
    settlements = []
    newcount = 0
    previous_old = inherited
    for stage in ["formal-bank", "unattempted-stage-01", "unattempted-stage-02", "unattempted-stage-03"]:
        require(rows(R / stage / "accepted-bank.jsonl") == previous_old, "recovery_prefix_exact")
        successes, un, intents, settled, peak = ledger(stage)
        unknowns += un
        totalintents += intents
        settlements += settled
        newcount += len(successes)
        previous_old = previous_old + list(successes.values())
        expected_records.update(successes)
    fresh, un, intents, settled, peak = ledger("explicit-unknown-reissue", True)
    require(not un and len(fresh) == 3, "three_new_observed_reissues")
    auth = read(R / "explicit-unknown-reissue/authorization.json")
    require(auth["original_unknowns"] == unknowns and len(unknowns) == 3, "original_unknowns_retained")
    expected_records.update(fresh)
    newcount += len(fresh)
    totalintents += intents
    settlements += settled
    require(expected_records == bankindex, "bank_record_origin_exact")
    require(newcount == 7212 and len(totalintents) == 7219, "provider_totals")
    known_cost = sum(
        Decimal(str(v["subscription_nominal_cost_usd"]))
        for v in settlements
        if v["subscription_nominal_cost_usd"] is not None
    )
    require(abs(known_cost - Decimal("47.021844")) < Decimal("0.000000001"), "known_nominal_decimal_sum")
    require(sum(v["subscription_nominal_cost_usd"] is None for v in settlements) == 3, "three_unknown_costs")
    # New responses are represented by normalized structured provider evidence, not raw wire payload (which was not retained).
    condition = prep["request_condition"]
    require(
        condition
        == read(OLD / "gpt-p0-bank-topup-20260917-authorized-01/preparation.json")["request_condition"]
        == read(OLD / "gpt-p0-index-sensitivity-20260920-formal-01/prepared/preparation.json")["request_condition"],
        "cross_study_request_condition",
    )
    fits = {}
    for arm, (au, ids, _ss) in arms.items():
        fits[arm] = {}
        for msg in cfg.messages:
            a = msg.vector()
            dims = __import__(
                "llm_abm_sim.concurrent_message_experiment", fromlist=["LATENT_VALUE_DIMENSIONS"]
            ).LATENT_VALUE_DIMENSIONS
            fits[arm][msg.message_id] = {}
            for u in ids:
                b = [float(au[u].latent_attributes[f"latent_{d}_value_weight"]) for d in dims]
                fits[arm][msg.message_id][u] = (
                    sum(x * y for x, y in zip(a, b, strict=True))
                    / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)))
                    + 1
                ) / 2
    basenetwork = {u: logscore(degrees.get(u, 0), p95) for u in eligible}
    manifest = read(R / "formal-paths/manifest.json")
    expected = {f"parameters/{label}-s{s}.json" for label, w, h in CONFIG for s in SEEDS} | {
        f"index/{a}-s{s}.json" for a in ARMS for s in SEEDS
    }
    require(set(manifest["paths"]) == expected, "all_path_matrix")
    metrics = {}
    oldmetrics = {}
    curve_aggr = defaultdict(list)
    raw_curve_expected = {}
    reuse = 0
    for study in ["parameters", "index"]:
        configurations = CONFIG if study == "parameters" else [(a, [0.5, 0.3, 0.2], 3) for a in ARMS]
        for label, weights, h in configurations:
            arm = "baseline" if study == "parameters" else label
            au, ids, ss = arms[arm]
            entries = {(u, m): bankindex[u, m, ch] for (u, m), (mh, ch) in inputs[arm].items()}
            for seed in SEEDS:
                relative = f"{study}/{label}-s{seed}.json"
                doc = read(R / "formal-paths" / relative)
                require(digest(R / "formal-paths" / relative) == manifest["paths"][relative], "path_file_hash")
                require(fp(doc["path"]) == doc["path_sha256"], "path_payload_hash")
                ident = doc["identity"]
                require(
                    ident["study"] == study
                    and ident["configuration"] == label
                    and ident["seed"] == seed
                    and ident["weights"] == list(weights)
                    and ident["neighbor_saturation"] == h
                    and ident["draw_anchor"] == prep["draw_anchor"],
                    "path_identity",
                )
                if "reused_execution_source" in doc:
                    ref = doc["reused_execution_source"]
                    origin = read(ref["root"])
                    require(
                        digest(ref["root"]) == ref["sha256"] and origin["path"] == doc["path"],
                        "actual_2700_source_trace",
                    )
                    required = sorted(
                        entries.values(), key=lambda r: (r["user_id"], r["message_id"], r["client_condition_sha256"])
                    )
                    require(
                        fp(required) == ref["scope_bank_sha256"] == origin["identity"]["scope_bank_sha256"],
                        "reused_scope_exact_inputs",
                    )
                    reuse += 1
                path = doc["path"]
                require(len(path["terminals"]) == 1800 and len(path["barriers"]) == 30, "path_topology")
                exposed = {m.message_id: set() for m in cfg.messages}
                active = set()
                cursor = 0
                for step in range(30):
                    before = set(active)
                    positive = set()
                    for msg in cfg.messages:
                        m = msg.message_id
                        ordered = []
                        for u in ids:
                            if u not in exposed[m]:
                                n = len(neighbors[u] & before)
                                score = (
                                    weights[0] * basenetwork[u]
                                    + weights[1] * min(1.0, n / h)
                                    + weights[2] * fits[arm][m][u]
                                )
                                ordered.append((u, score, n))
                        ordered.sort(key=lambda q: (-q[1], q[0]))
                        chosen = (
                            [q for q in ordered if q[0] in ss] + [q for q in ordered if q[0] not in ss][: 20 - len(ss)]
                            if step == 0
                            else ordered[:20]
                        )
                        require(len(chosen) == 20, "capacity_twenty")
                        for u, score, n in chosen:
                            r = path["terminals"][cursor]
                            entry = entries[u, m]
                            decision = entry["decision"]
                            raw = hashlib.sha256(canonical([RULE, prep["draw_anchor"], seed, u, m])).digest()
                            uniform = (int.from_bytes(raw[:7], "big") >> 3) / 2**53 if decision["engage"] else None
                            engage = uniform is not None and uniform < decision["probability"]
                            expectedrow = {
                                "time_step": step,
                                "user_id": u,
                                "message_id": m,
                                "uniform_draw": uniform,
                                "realized_engage": engage,
                                "realized_action": decision["action"] if engage else "ignore",
                                "ranking_score": score,
                                "engaged_neighbor_count": n,
                                "bank_source": entry["source"],
                                "client_condition_sha256": entry["client_condition_sha256"],
                                "selection_reason": ("seed_union" if u in ss else "personalized_topup")
                                if step == 0
                                else "personalized_top20",
                            }
                            require(r == expectedrow, "independent_rank_draw_action")
                            exposed[m].add(u)
                            cursor += 1
                            if engage:
                                positive.add(u)
                    active.update(positive)
                    require(
                        path["barriers"][step]
                        == {
                            "time_step": step,
                            "exposure_count": 60,
                            "frozen_positive_user_ids": sorted(before),
                            "committed_positive_user_ids": sorted(positive),
                            "campaign_positive_user_count": len(active),
                        },
                        "independent_batch_barrier",
                    )
                require(all(len(v) == 600 for v in exposed.values()), "deduplicated_600_each_message")
                oldpath = (
                    OLD
                    / (
                        "gpt-p0-dynamic-parameters-20260917-formal-01"
                        if study == "parameters"
                        else "gpt-p0-index-sensitivity-20260920-formal-01/paths"
                    )
                    / f"{label}-s{seed}.json"
                )
                old = read(oldpath)["path"]["terminals"]
                for message in ["message_1", "message_2", "message_3", "all"]:
                    newrows = [r for r in path["terminals"] if message == "all" or r["message_id"] == message]
                    oldrows = [r for r in old if message == "all" or r["message_id"] == message]

                    def score(rows):
                        counts = Counter(r["realized_action"] for r in rows)
                        en = sum(counts[k] for k in ["like", "comment", "share"])
                        return {
                            **{k: counts[k] for k in ["like", "comment", "share"]},
                            "engagement": en,
                            "engagement_rate": en / len(rows),
                        }

                    metrics[study, label, seed, message] = score(newrows)
                    oldmetrics[study, label, seed, message] = score(oldrows)
                    for batch in range(1, 31):
                        x = sum(r["realized_action"] != "ignore" for r in oldrows if r["time_step"] < batch)
                        y = sum(r["realized_action"] != "ignore" for r in newrows if r["time_step"] < batch)
                        den = (60 if message == "all" else 20) * batch
                        curve_aggr[study, label, message, batch].append((x, y, den))
                        ccold = Counter(r["realized_action"] for r in oldrows if r["time_step"] < batch)
                        ccnew = Counter(r["realized_action"] for r in newrows if r["time_step"] < batch)
                        raw_curve_expected[study, label, seed, message, batch] = {
                            "exposures": den,
                            "old_engagement": x,
                            "new_engagement": y,
                            "old_rate": x / den,
                            "new_rate": y / den,
                            **{("old_" + a): ccold[a] for a in ["like", "comment", "share", "ignore"]},
                            **{("new_" + a): ccnew[a] for a in ["like", "comment", "share", "ignore"]},
                        }
            print("accepted", study, label, "100 paths", flush=True)
    require(reuse == 2700, "2700_reused_and_100_new")
    ordinary = tq(0.975)
    pc = tq(1 - 0.05 / (2 * 123))
    ic = tq(1 - 0.05 / (2 * 120))
    for r in csvrows(R / "formal-report/arm-parameter-estimates.csv"):
        s, item, m, k = r["study"], r["configuration"], r["message"], r["metric"]
        v = [metrics[s, item, t, m][k] for t in SEEDS]
        e = estimate(v, ordinary)
        for f, value in e.items():
            close(r[f], value, "statistic_" + f)
        close(r["old_mean"], sum(oldmetrics[s, item, t, m][k] for t in SEEDS) / 100, "old_statistic_mean")
    for r in csvrows(R / "formal-report/old-new-paired-estimates.csv"):
        s, item, m, k = r["study"], r["configuration"], r["message"], r["metric"]
        e = estimate([metrics[s, item, t, m][k] - oldmetrics[s, item, t, m][k] for t in SEEDS], ordinary)
        for f, value in e.items():
            close(r[f], value, "old_new_paired_" + f)
    for r in csvrows(R / "formal-report/index-paired-estimates.csv"):
        item, m, k = r["arm"], r["message"], r["metric"]
        v = [metrics["index", item, t, m][k] - metrics["index", "baseline", t, m][k] for t in SEEDS]
        e = estimate(v, ordinary)
        adj = estimate(v, ic)
        for f, value in e.items():
            close(r[f], value, "index_paired_" + f)
        close(r["family_lower"], adj["lower"], "index_family120_lower")
        close(r["family_upper"], adj["upper"], "index_family120_upper")
    for r in csvrows(R / "formal-report/parameter-message-contrasts.csv"):
        label = r["configuration"]
        a, b = r["contrast"].split("-")
        v = [
            metrics["parameters", label, t, a]["engagement_rate"]
            - metrics["parameters", label, t, b]["engagement_rate"]
            for t in SEEDS
        ]
        delta = [
            d
            - (
                metrics["parameters", "w0-h3", t, a]["engagement_rate"]
                - metrics["parameters", "w0-h3", t, b]["engagement_rate"]
            )
            for d, t in zip(v, SEEDS, strict=True)
        ]
        e = estimate(v, pc)
        de = estimate(delta, pc)
        for f, value in e.items():
            close(r["difference_" + f], value, "parameter_family123_difference")
        for f, value in de.items():
            close(r["delta_" + f], value, "parameter_family123_delta")
    for r in csvrows(R / "formal-report/old-new-mean-curves.csv"):
        values = curve_aggr[r["study"], r["configuration"], r["message"], int(r["batch"])]
        for f, v in [
            ("old_engagement_mean", sum(x[0] for x in values) / 100),
            ("new_engagement_mean", sum(x[1] for x in values) / 100),
            ("old_rate_mean", sum(x[0] / x[2] for x in values) / 100),
            ("new_rate_mean", sum(x[1] / x[2] for x in values) / 100),
        ]:
            close(r[f], v, "mean_curve")
    for r in csvrows(R / "formal-report/old-new-cumulative-curves.csv"):
        expected = raw_curve_expected.pop(
            (r["study"], r["configuration"], int(r["seed"]), r["message"], int(r["batch"]))
        )
        for field, value in expected.items():
            close(r[field], value, "raw_cumulative_curve")
    require(not raw_curve_expected, "all_raw_curves_closed")
    for t in SEEDS:
        require(
            read(R / f"formal-paths/index/local_weights_fixed-s{t}.json")["path"]
            == read(R / f"formal-paths/index/local_weights_rebuilt-s{t}.json")["path"],
            "Local_fixed_rebuilt_identical",
        )
        require(
            read(R / f"formal-paths/index/baseline-s{t}.json")["path"]
            == read(R / f"formal-paths/parameters/w0-h3-s{t}.json")["path"],
            "shared_baseline_identical",
        )
    base_new = sum(metrics["parameters", "w0-h3", t, "all"]["engagement_rate"] for t in SEEDS) / 100
    base_old = sum(oldmetrics["parameters", "w0-h3", t, "all"]["engagement_rate"] for t in SEEDS) / 100
    params = [
        sum(metrics["parameters", item, t, "all"]["engagement_rate"] for t in SEEDS) / 100 for item, w, h in CONFIG
    ]
    require(len(set(base_ids) & set(legacy.cohort.sample_user_ids)) == 646, "sample_old_new_646")
    require(
        len(set(snapshots["local_p99_rebuilt"]["sample_user_ids"]) & set(base_ids)) == 23, "sample_rebuilt_baseline_23"
    )
    summary = {
        "status": "pass",
        "provider_calls_this_acceptance": 0,
        "judgments": 17520,
        "reused": 10308,
        "new_success": 7212,
        "physical_requests": 7219,
        "retained_unknown": 3,
        "explicit_new_responses": 3,
        "known_nominal_usd": str(known_cost),
        "cash_fee": None,
        "paths": 2800,
        "exposures": 5040000,
        "barriers": 84000,
        "checks": dict(checks),
        "baseline_old_mean": base_old,
        "baseline_new_mean": base_new,
        "parameter_min_mean": min(params),
        "parameter_max_mean": max(params),
        "df99_critical_independent": ordinary,
        "parameter_family123_critical": pc,
        "index_family120_critical": ic,
        "network": {
            "p95": p95,
            "edges": len(edges),
            "edge_weight_sum": sum(edges.values()),
            "topic_counts": [{"id": i, "name": n, "videos": c} for (i, n), c in sorted(topics.items())],
        },
        "shared_parts": [
            "immutable original cohort reader and data types",
            "canonical client renderer and identity specification only",
        ],
        "independent_parts": [
            "raw historical graph, normalization and proxy recalculation",
            "arm variants and seed-first sample construction",
            "ledger hash chain, request/success origin and decimal accounting",
            "full eligible ranking/ties/seed selection, uniform/action and barriers",
            "terminal statistics, paired intervals and beta-function t quantile",
            "path reuse source and exact-input scope hashes",
        ],
    }
    write("evidence-accepted.json", summary)
    print(
        json.dumps(
            {
                k: summary[k]
                for k in [
                    "status",
                    "paths",
                    "exposures",
                    "physical_requests",
                    "known_nominal_usd",
                    "provider_calls_this_acceptance",
                ]
            },
            sort_keys=True,
        ),
        flush=True,
    )


if __name__ == "__main__":
    run()
