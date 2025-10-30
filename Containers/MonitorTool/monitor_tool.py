import os
import time
from datetime import datetime, timezone
from pymongo import MongoClient, ASCENDING

DBHOST = os.environ.get("DBHOST", "localhost")
DBPORT = int(os.environ.get("DBPORT", "27017"))
DBNAME = os.environ.get("DBNAME", "cloneDetector")
POLL_SECONDS = float(os.environ.get("POLL_SECONDS", "5"))

# collumns and ids
TARGET_COLLS = ["files", "chunks", "candidates", "clones"]
STATUS_COL = "statusupdates"
SAMPLES_COLL = "monitorSamples"
SNAPSHOT_COLL = "monitorSnapshots"
STATE_COLL = "monitorState"
STATS_COLL = "monitorStats"
STATE_ID = "MonitorToolState"

# minimum points
MIN_POINTS_FOR_FIT = 6
TREND_WINDOW = 6

def utc_iso_now():
    return datetime.now(timezone.utc).isoformat()

def lin_reg(x, y):
    """
    Ordinary least squares for y = a + b*x
    """
    n = len(x)
    if n == 0:
        return {"a": None, "b": None, "r2": None, "n": 0}
    sx = sum(x)
    sy = sum(y)
    sxx = sum(v*v for v in x)
    sxy = sum(x[i]*y[i] for i in range(n))
    denom = n*sxx - sx*sx
    if denom == 0:
        return {"a": None, "b": None, "r2": None, "n": n}
    b = (n*sxy - sx*sy) / denom
    a = (sy - b*sx) / n
    # R^2
    ybar = sy / n
    ss_tot = sum((v - ybar)**2 for v in y)
    ss_res = sum((y[i] - (a + b*x[i]))**2 for i in range(n))
    r2 = 1 - (ss_res/ss_tot) if ss_tot != 0 else 1.0
    return {"a": a, "b": b, "r2": r2, "n": n}

def exp_reg(x, y):
    """
    linearizing: ln(y) = ln(c) + d*x
    Only uses points with y > 0
    """
    import math
    x2, ly = [], []
    for xi, yi in zip(x, y):
        if yi is not None and yi > 0:
            x2.append(xi)
            ly.append(math.log(yi))
    if len(x2) < 2:
        return {"c": None, "d": None, "r2": None, "n_used": len(x2), "n_total": len(x)}
    lin = lin_reg(x2, ly)
    if lin["a"] is None:
        return {"c": None, "d": None, "r2": None, "n_used": len(x2), "n_total": len(x)}
    c = math.exp(lin["a"])
    d = lin["b"]
    return {"c": c, "d": d, "r2": lin["r2"], "n_used": len(x2), "n_total": len(x)}

def quick_slope_last_k(x, y, k):
    """
    Cheap slope estimate of the last k points
    """
    if len(x) < 2:
        return None
    xk = x[-k:] if len(x) >= k else x[:]
    yk = y[-k:] if len(y) >= k else y[:]
    lr = lin_reg(xk, yk)
    return lr["b"]

def main():
    mongo_uri = f"mongodb://{DBHOST}:{DBPORT}"
    myclient = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
    db = myclient[DBNAME]

    try:
        db[STATUS_COL].create_index([("timestamp", ASCENDING)], name="ts_asc")
    except Exception:
        pass
    try:
        db[SAMPLES_COLL].create_index([("ts", ASCENDING)], name="ts_asc")
    except Exception:
        pass
    try:
        db[STATS_COLL].create_index([("ts", ASCENDING)], name="ts_asc")
    except Exception:
        pass

    state = db[STATE_COLL].find_one({"_id": STATE_ID}) or {}
    last_ts_status = state.get("last_ts", "1970-01-01T00:00:00Z")
    prev_counts = None
    prev_sample_time = None

    history = {t: {"N": [], "tpu": []} for t in TARGET_COLLS}

    print(f"Connected to {mongo_uri}/{DBNAME}. Poll={POLL_SECONDS}s, last_ts_status={last_ts_status}", flush=True)

    while True:
        loop_start = datetime.now(timezone.utc)

        try:
            counts = {}
            for col in TARGET_COLLS:
                counts[col] = db[col].count_documents({})

            new_updates = list(
                db[STATUS_COL]
                .find({"timestamp": {"$gt": last_ts_status}})
                .sort("timestamp", ASCENDING)
            )
            if new_updates:
                for update in new_updates:
                    ts = update.get("timestamp")
                    msg = update.get("message")
                    print(f"  statusUpdate @ {ts}: {msg}", flush=True)
                last_ts_status = new_updates[-1].get("timestamp", last_ts_status)
                db[STATE_COLL].update_one(
                    {"_id": STATE_ID},
                    {"$set": {"last_ts": last_ts_status, "updated_at": utc_iso_now()}},
                    upsert=True,
                )

            now = datetime.now(timezone.utc)
            if prev_sample_time is None:
                dt_seconds = None
            else:
                dt_seconds = (now - prev_sample_time).total_seconds()

            if prev_counts is None or dt_seconds is None or dt_seconds <= 0:
                sample_doc = {
                    "ts": utc_iso_now(),
                    "counts": counts,
                    "deltas": {k: 0 for k in TARGET_COLLS},
                    "dt_seconds": None,
                    "tpu": {k: None for k in TARGET_COLLS},
                    "rate": {k: None for k in TARGET_COLLS},
                }
                db[SAMPLES_COLL].insert_one(sample_doc)
                print(f"[{sample_doc['ts']}] counts: {counts}", flush=True)
            else:
                deltas = {k: max(0, counts[k] - prev_counts.get(k, 0)) for k in TARGET_COLLS}
                # time per unit in seconds and units per second
                tpu = {k: (dt_seconds / deltas[k] if deltas[k] > 0 else None) for k in TARGET_COLLS}
                rate = {k: (deltas[k] / dt_seconds if dt_seconds > 0 else None) for k in TARGET_COLLS}

                sample_doc = {
                    "ts": utc_iso_now(),
                    "counts": counts,
                    "deltas": deltas,
                    "dt_seconds": dt_seconds,
                    "tpu": tpu,
                    "rate": rate,
                }
                db[SAMPLES_COLL].insert_one(sample_doc)

                if any(deltas[k] != 0 for k in TARGET_COLLS):
                    db[SNAPSHOT_COLL].insert_one({"ts": sample_doc["ts"], "counts": counts})

                # update histories
                for target in TARGET_COLLS:
                    N = counts[target]
                    t = tpu[target]
                    if t is not None and N is not None:
                        history[target]["N"].append(N)
                        history[target]["tpu"].append(t)

                # fit models and store stats
                for target in TARGET_COLLS:
                    N_series = history[target]["N"]
                    tpu_series = history[target]["tpu"]

                    if len(N_series) >= MIN_POINTS_FOR_FIT:
                        lin = lin_reg(N_series, tpu_series) # linear
                        expf = exp_reg(N_series, tpu_series) # exponential

                        # choose preferred model
                        candidates = []
                        if lin["r2"] is not None:
                            candidates.append(("linear", lin["r2"]))
                        if expf["r2"] is not None:
                            candidates.append(("exponential", expf["r2"]))
                        preferred = "insufficient"
                        if candidates:
                            preferred = max(candidates, key=lambda p: p[1])[0]

                        slope_k = quick_slope_last_k(N_series, tpu_series, TREND_WINDOW)

                        stats_doc = {
                            "ts": utc_iso_now(),
                            "target": target,
                            "n_points": len(N_series),
                            "linear": {"a": lin["a"], "b": lin["b"], "r2": lin["r2"]},
                            "exponential": {"c": expf["c"], "d": expf["d"], "r2": expf["r2"]},
                            "preferred": preferred,
                            "trend": {"slope_last_k": slope_k},
                        }
                        db[STATS_COLL].insert_one(stats_doc)

                        def fmt(v):
                            return "nan" if v is None else f"{v:.6g}"
                        print(
                            f"[{stats_doc['ts']}] [{target}] "
                            f"n={stats_doc['n_points']}  "
                            f"lin: a={fmt(lin['a'])}, b={fmt(lin['b'])}, R2={fmt(lin['r2'])}  "
                            f"exp: c={fmt(expf['c'])}, d={fmt(expf['d'])}, R2={fmt(expf['r2'])}  "
                            f"preferred={preferred}  "
                            f"trend.slope_last_k={fmt(slope_k)}",
                            flush=True
                        )

            prev_counts = counts
            prev_sample_time = now

        except Exception as e:
            print(f"[MonitorTool] WARN loop error: {e}", flush=True)

        # sleep until next poll
        elapsed = (datetime.now(timezone.utc) - loop_start).total_seconds()
        delay = max(0.0, POLL_SECONDS - elapsed)
        time.sleep(delay)

if __name__ == "__main__":
    main()
