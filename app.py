"""
Teil-2-Raum-Prototyp: synchronisiert Aufnahme-Start zwischen Laptop (Host) und
Handy (Guest), damit zwei Sprecher getrennte Audiokanaele bekommen.

Der Server speichert NIE Audio oder Groq-Keys - jedes Geraet transkribiert
lokal mit seinem eigenen Key (gleiches Prinzip wie teil1_prototyp.html) und
schickt nur den Text + Segment-Zeiten an den Server. Der Host fuehrt am Ende
den Merge + die Bewertung (eigener Groq-Call) durch.
"""
import random
import time
from flask import Flask, jsonify, render_template, request

app = Flask(__name__)

# In-memory only - reicht fuer einen Klassenraum-Prototyp, kein Neustart-Schutz.
SESSIONS = {}
SESSION_TTL = 60 * 60  # 1 Stunde


def _new_code():
    while True:
        code = str(random.randint(100000, 999999))
        if code not in SESSIONS:
            return code


def _cleanup():
    now = time.time()
    stale = [c for c, s in SESSIONS.items() if now - s["created_at"] > SESSION_TTL]
    for c in stale:
        del SESSIONS[c]


@app.route("/")
def host_page():
    return render_template("index.html", role="host", preset_code="")


@app.route("/join/<code>")
def guest_page(code):
    return render_template("index.html", role="guest", preset_code=code)


@app.route("/api/create", methods=["POST"])
def api_create():
    _cleanup()
    code = _new_code()
    SESSIONS[code] = {
        "created_at": time.time(),
        "guest_joined": False,
        "status": "waiting_guest",  # waiting_guest -> ready -> armed -> recording -> done
        "start_at": None,
        "duration": None,
        "transcripts": {},  # "a" (host) / "b" (guest) -> {text, segments}
    }
    return jsonify({"code": code})


@app.route("/api/session/<code>", methods=["GET"])
def api_get(code):
    s = SESSIONS.get(code)
    if not s:
        return jsonify({"error": "not_found"}), 404
    return jsonify(s)


@app.route("/api/session/<code>/join", methods=["POST"])
def api_join(code):
    s = SESSIONS.get(code)
    if not s:
        return jsonify({"error": "not_found"}), 404
    s["guest_joined"] = True
    if s["status"] == "waiting_guest":
        s["status"] = "ready"
    return jsonify(s)


@app.route("/api/session/<code>/start", methods=["POST"])
def api_start(code):
    s = SESSIONS.get(code)
    if not s:
        return jsonify({"error": "not_found"}), 404
    body = request.get_json(force=True)
    duration = int(body.get("duration", 180))
    s["duration"] = duration
    s["start_at"] = time.time() + 3.0  # 3 Sek. Vorlauf, damit beide Geraete rechtzeitig starten
    s["status"] = "armed"
    s["transcripts"] = {}
    return jsonify(s)


@app.route("/api/session/<code>/transcript/<channel>", methods=["POST"])
def api_transcript(code, channel):
    if channel not in ("a", "b"):
        return jsonify({"error": "bad_channel"}), 400
    s = SESSIONS.get(code)
    if not s:
        return jsonify({"error": "not_found"}), 404
    body = request.get_json(force=True)
    s["transcripts"][channel] = {
        "text": body.get("text", ""),
        "segments": body.get("segments", []),
    }
    if "a" in s["transcripts"] and "b" in s["transcripts"]:
        s["status"] = "done"
    return jsonify(s)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
