"""
Teil-2-Raum-Prototyp: zwei Schueler sprechen jeweils in ihr EIGENES Handy
(Kanal A und B), synchron gestartet ueber diesen Server. Start kann von
JEDEM Geraet (Lehrer-Laptop ODER einem der beiden Schueler) ausgeloest
werden, sobald beide verbunden sind.

Der Server speichert NIE Audio oder Groq-Keys - jedes Handy transkribiert
lokal mit seinem eigenen Key und schickt nur Text-Schnipsel (push-to-talk
Fragmente mit eigener Zeit) an den Server. Die abschliessende Bewertung
macht irgendein Geraet, das die Seite offen hat, mit seinem EIGENEN Key
(reiner Text-Call, kein Audio) und schickt nur das Bewertungs-JSON an den
Server. Aus Transkript+Namen+Bewertung baut der Server bei Bedarf ein
herunterladbares Word-Dokument fuer die Lehrkraft.
"""
import io
import random
import time

from flask import Flask, jsonify, render_template, request, send_file
from docx import Document

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


def _fmt_time(seconds):
    m = int(seconds // 60)
    sec = int(seconds % 60)
    return f"{m:02d}:{sec:02d}"


def _merged_fragments(s):
    a_name = s["names"].get("a") or "Schueler A"
    b_name = s["names"].get("b") or "Schueler B"
    a = [{**f, "speaker": f"{a_name} (A)"} for f in s["transcripts"].get("a", {}).get("fragments", [])]
    b = [{**f, "speaker": f"{b_name} (B)"} for f in s["transcripts"].get("b", {}).get("fragments", [])]
    merged = sorted(a + b, key=lambda f: f["start"])
    return merged, a_name, b_name


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
        "names": {"a": None, "b": None},
        "status": "waiting_phones",  # waiting_phones -> ready -> armed -> done
        "start_at": None,
        "duration": None,
        "transcripts": {},  # "a" / "b" -> {fragments: [{start, end, text}]}
        "eval": None,
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
    body = request.get_json(silent=True) or {}
    s["joined"][channel] = True
    s["names"][channel] = (body.get("name") or "").strip() or f"Schueler {channel.upper()}"
    if s["joined"]["a"] and s["joined"]["b"]:
        s["status"] = "ready"
    return jsonify({"channel": channel, "session": s})


@app.route("/api/session/<code>/start", methods=["POST"])
def api_start(code):
    s = SESSIONS.get(code)
    if not s:
        return jsonify({"error": "not_found"}), 404
    if s["status"] != "ready":
        # Schon gestartet (z.B. beide Seiten haben fast gleichzeitig gedrueckt) - ignorieren.
        return jsonify(s)
    body = request.get_json(force=True)
    duration = int(body.get("duration", 180))
    s["duration"] = duration
    s["start_at"] = time.time() + 3.0  # 3 Sek. Vorlauf, damit beide Handys rechtzeitig starten
    s["status"] = "armed"
    s["transcripts"] = {}
    s["eval"] = None
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
        "fragments": body.get("fragments", []),  # [{start, end, text}] - push-to-talk Schnipsel, eigene Geraet-Zeit
    }
    if "a" in s["transcripts"] and "b" in s["transcripts"]:
        s["status"] = "done"
    return jsonify(s)


@app.route("/api/session/<code>/eval", methods=["POST"])
def api_eval(code):
    s = SESSIONS.get(code)
    if not s:
        return jsonify({"error": "not_found"}), 404
    if not s.get("eval"):
        s["eval"] = request.get_json(force=True)
    return jsonify(s)


@app.route("/api/session/<code>/docx")
def api_docx(code):
    s = SESSIONS.get(code)
    if not s or not s.get("eval"):
        return jsonify({"error": "not_ready"}), 404

    merged, a_name, b_name = _merged_fragments(s)
    ev = s["eval"]

    doc = Document()
    doc.add_heading("DTB B2 — Sprechen Teil 2 — Ergebnis", level=1)
    doc.add_paragraph(f"Sitzungscode: {code}")
    doc.add_paragraph(f"Teilnehmer: {a_name} & {b_name}")

    doc.add_heading("Dialog-Transkript", level=2)
    for frag in merged:
        doc.add_paragraph(f"[{_fmt_time(round(frag['start']))}] {frag['speaker']}: {frag['text']}")

    for key, name in (("schueler_a", a_name), ("schueler_b", b_name)):
        res = ev.get(key, {})
        doc.add_heading(f"Bewertung — {name}", level=2)
        for krit, label in (
            ("ki", "K-I Kommunikative Aufgabenbewaeltigung"),
            ("kii", "K-II Aussprache/Intonation"),
            ("kiii", "K-III Formale Richtigkeit"),
            ("kiv", "K-IV Spektrum sprachlicher Mittel"),
        ):
            k = res.get(krit, {})
            p = doc.add_paragraph()
            p.add_run(f"{label}: Stufe {k.get('stufe', '-')}").bold = True
            doc.add_paragraph(k.get("kommentar", ""))

        p = doc.add_paragraph()
        p.add_run("Einschaetzung: ").bold = True
        p.add_run(
            "ausreichend fuer Teil 2"
            if res.get("bestanden_einschaetzung")
            else "noch nicht ausreichend fuer Teil 2"
        )

        if res.get("staerken"):
            doc.add_heading("Staerken", level=3)
            for st in res["staerken"]:
                doc.add_paragraph(st, style="List Bullet")

        if res.get("verbesserungen"):
            doc.add_heading("Verbesserungsvorschlaege", level=3)
            for v in res["verbesserungen"]:
                doc.add_paragraph(v, style="List Bullet")

        doc.add_heading("Feedback", level=3)
        doc.add_paragraph(res.get("feedback", ""))

    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    return send_file(
        buf,
        as_attachment=True,
        download_name=f"DTB_B2_Teil2_{code}.docx",
        mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
