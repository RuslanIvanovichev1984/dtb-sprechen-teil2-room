"""
Teil-2-Raum-Prototyp: Lehrer-Laptop ist nur Steuerzentrale (zeigt Code,
Impulskarten, startet die Sitzung, zeigt am Ende das Ergebnis) - er nimmt
KEIN Audio auf. Beide Schueler sprechen jeweils in ihr EIGENES Handy
(Kanal A und B), synchron gestartet ueber diesen Server.

Der Server speichert NIE Audio oder Groq-Keys - jedes Handy transkribiert
lokal mit seinem eigenen Key und schickt nur den Text + Segment-Zeiten an
den Server. Der Laptop holt sich am Ende beide Transkripte, merged sie und
ruft mit seinem EIGENEN Key die Bewertung auf (reiner Text-Call, kein Audio).
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
def control_page():
    return render_template("index.html", role="control", preset_code="")


@app.route("/join/<code>")
def phone_page(code):
    return render_template("index.html", role="phone", preset_code=code)


@app.route("/api/create", methods=["POST"])
def api_create():
    _cleanup()
    code = _new_code()
    SESSIONS[code] = {
        "created_at": time.time(),
        "joined": {"a": False, "b": False},
        "status": "waiting_phones",  # waiting_phones -> ready -> armed -> done
        "start_at": None,
        "duration": None,
        "transcripts": {},  # "a" / "b" -> {text, segments}
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
    if not s["joined"]["a"]:
        channel = "a"
    elif not s["joined"]["b"]:
        channel = "b"
    else:
        return jsonify({"error": "full"}), 409
    s["joined"][channel] = True
    if s["joined"]["a"] and s["joined"]["b"]:
        s["status"] = "ready"
    return jsonify({"channel": channel, "session": s})


@app.route("/api/session/<code>/start", methods=["POST"])
def api_start(code):
    s = SESSIONS.get(code)
    if not s:
        return jsonify({"error": "not_found"}), 404
    body = request.get_json(force=True)
    duration = int(body.get("duration", 180))
    s["duration"] = duration
    s["start_at"] = time.time() + 3.0  # 3 Sek. Vorlauf, damit beide Handys rechtzeitig starten
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
