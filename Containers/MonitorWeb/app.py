import os
from datetime import datetime
from flask import Flask, jsonify, render_template, request
from pymongo import MongoClient, ASCENDING, DESCENDING

DBHOST = os.environ.get("DBHOST", "localhost")
DBPORT = int(os.environ.get("DBPORT", "27017"))
DBNAME = os.environ.get("DBNAME", "cloneDetector")
PORT   = int(os.environ.get("PORT", "8000"))

SAMPLES  = "monitorSamples"
STATS    = "monitorStats"

TARGETS = ["files", "chunks", "candidates", "clones"]

app = Flask(__name__, template_folder="templates", static_folder="static")

def mongo():
    uri = f"mongodb://{DBHOST}:{DBPORT}"
    client = MongoClient(uri, serverSelectionTimeoutMS=3000)
    return client, client[DBNAME]

@app.get("/")
def index():
    return render_template("index.html", targets=TARGETS)

@app.get("/api/samples")
def api_samples():
    """
    Returns the last N samples of counts and tpu
    """
    n = int(request.args.get("n", "500"))
    _, db = mongo()
    cur = db[SAMPLES].find({}, {
        "ts": 1,
        "counts": 1,
        "tpu": 1
    }).sort("ts", DESCENDING).limit(n)
    rows = list(cur)[::-1]

    samples = []
    for r in rows:
        samples.append({
            "ts": r.get("ts"),
            "files": (r.get("counts") or {}).get("files"),
            "chunks": (r.get("counts") or {}).get("chunks"),
            "candidates": (r.get("counts") or {}).get("candidates"),
            "clones": (r.get("counts") or {}).get("clones"),
            "tpu": r.get("tpu") or {}
        })
    return jsonify({"samples": samples})

@app.get("/api/tpu")
def api_tpu():
    """
    Returns scatter series of (N, tpu) for a given target using samples
    """
    target = request.args.get("target", "chunks")
    if target not in TARGETS:
        return jsonify({"error": "invalid target"}), 400
    n = int(request.args.get("n", "1000"))
    _, db = mongo()
    cur = db[SAMPLES].find({}, {"ts":1, "counts."+target:1, "tpu."+target:1})\
                     .sort("ts", DESCENDING).limit(n)
    rows = list(cur)[::-1]
    pts = []
    for r in rows:
        counts = (r.get("counts") or {})
        tpu = (r.get("tpu") or {}).get(target)
        N = counts.get(target)
        if tpu is not None and N is not None:
            pts.append({"N": N, "tpu": tpu})
    return jsonify({"target": target, "points": pts})

@app.get("/api/model")
def api_model():
    """
    Returns the latest model fit for a target
    """
    target = request.args.get("target", "chunks")
    if target not in TARGETS:
        return jsonify({"error": "invalid target"}), 400
    _, db = mongo()
    doc = db[STATS].find_one({"target": target}, sort=[("ts", DESCENDING)])
    if not doc:
        return jsonify({"target": target, "model": None})
    # trim
    out = {
        "ts": doc.get("ts"),
        "target": target,
        "n_points": doc.get("n_points"),
        "preferred": doc.get("preferred"),
        "linear": doc.get("linear"),
        "exponential": doc.get("exponential"),
        "trend": doc.get("trend"),
    }
    return jsonify(out)

@app.get("/api/status")
def api_status():
    client, db = mongo()
    doc = db["statusupdates"].find_one({}, sort=[("timestamp", DESCENDING)])
    if not doc:
        return jsonify({"timestamp": None, "message": None})
    return jsonify({
        "timestamp": doc.get("timestamp"),
        "message": doc.get("message")
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT)
