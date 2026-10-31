"""レシピ依頼プロンプトメーカー reciprompt

食材・人数・気分・系統を選ぶと、生成 AI に貼るためのレシピ依頼文を
組み立てるツール。よく使う食材セットを SQLite に保存できる。
単一ファイル Flask + SQLite。
"""
import os
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

from flask import Flask, g, jsonify, redirect, render_template_string, request, url_for

app = Flask(__name__)
JST = ZoneInfo("Asia/Tokyo")
DB_PATH = os.environ.get("RECIPROMPT_DB", os.path.join(os.path.dirname(__file__), "reciprompt.db"))

MOODS = ["さっぱり", "がっつり", "時短", "節約", "ヘルシー"]
STYLES = ["和", "洋", "中", "エスニック", "おまかせ"]

MOOD_HINTS = {
    "さっぱり": "味付けはさっぱりめで、油控えめにしてください。",
    "がっつり": "ボリューム重視で、満足感のある一皿にしてください。",
    "時短": "調理時間は20分以内を目安に、手順はできるだけ簡潔にしてください。",
    "節約": "安価な食材と家にある調味料でまかなえる内容にしてください。",
    "ヘルシー": "野菜多め・塩分控えめなど、栄養バランスに配慮してください。",
}


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = sqlite3.connect(DB_PATH)
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS sets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            ingredients TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        """
    )
    db.commit()
    db.close()


def build_prompt(ingredients, servings, mood, style, note):
    lines = []
    lines.append(f"冷蔵庫に、{ingredients} があります。")
    style_part = "" if style == "おまかせ" else f"{style}風の"
    lines.append(f"これらの食材を中心に、{servings}人分の{style_part}料理のレシピを1つ提案してください。")
    lines.append(f"今日の気分は「{mood}」です。{MOOD_HINTS.get(mood, '')}")
    lines.append("材料は分量つきで、手順は番号つきで具体的に書いてください。")
    lines.append("足りない調味料などがあれば「買い足し」として分けて書いてください。")
    if note:
        lines.append(f"補足：{note}")
    return "\n".join(lines)


PAGE = """<!doctype html>
<html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>レシピ依頼プロンプトメーカー</title>
<style>body{font-family:sans-serif;max-width:680px;margin:2em auto;padding:0 1em}
textarea{width:100%}pre{background:#f4f4f4;padding:1em;white-space:pre-wrap}</style>
</head><body>
<h1>レシピ依頼プロンプトメーカー</h1>
<p>生成 AI にレシピを頼むための依頼文を組み立てます。できた文をコピーして AI に貼ってください。</p>
<form method="post" action="{{ url_for('generate') }}">
  <label>食材（カンマ区切り）<br>
  <textarea name="ingredients" rows="2" placeholder="例：鶏もも肉、キャベツ、卵">{{ ingredients or '' }}</textarea></label><br>
  <label>人数 <input type="number" name="servings" value="{{ servings or 2 }}" min="1" max="12"></label>
  <label>気分
    <select name="mood">{% for m in moods %}<option {% if mood == m %}selected{% endif %}>{{ m }}</option>{% endfor %}</select></label>
  <label>系統
    <select name="style">{% for s in styles %}<option {% if style == s %}selected{% endif %}>{{ s }}</option>{% endfor %}</select></label><br>
  <label>補足 <input type="text" name="note" value="{{ note or '' }}" placeholder="例：辛いのは苦手"></label>
  <button type="submit">依頼文を作る</button>
</form>

{% if prompt %}
<h2>依頼文</h2>
<pre id="prompt">{{ prompt }}</pre>
<button type="button" onclick="navigator.clipboard.writeText(document.getElementById('prompt').innerText)">コピー</button>
{% endif %}

<h2>食材セット</h2>
<form method="post" action="{{ url_for('save_set') }}">
  <label>セット名 <input type="text" name="name" placeholder="例：いつもの野菜"></label>
  <label>食材 <input type="text" name="ingredients" placeholder="例：じゃがいも、玉ねぎ、人参"></label>
  <button type="submit">保存</button>
</form>
<ul>
{% for s in sets %}
<li>{{ s.name }}：{{ s.ingredients }}
  <a href="{{ url_for('index', set_id=s.id) }}">読み込む</a>
  <form method="post" action="{{ url_for('delete_set', sid=s.id) }}" style="display:inline"><button>削除</button></form></li>
{% else %}<li>保存されたセットはありません</li>{% endfor %}
</ul>
</body></html>"""


@app.route("/healthz")
def healthz():
    return jsonify({"status": "ok"})


@app.route("/")
def index():
    db = get_db()
    sets = db.execute("SELECT * FROM sets ORDER BY id DESC").fetchall()
    ingredients = ""
    set_id = request.args.get("set_id")
    if set_id:
        row = db.execute("SELECT * FROM sets WHERE id = ?", (set_id,)).fetchone()
        if row:
            ingredients = row["ingredients"]
    return render_template_string(
        PAGE, sets=sets, moods=MOODS, styles=STYLES,
        ingredients=ingredients, servings=2, mood=None, style=None, note="", prompt=None,
    )


@app.route("/generate", methods=["POST"])
def generate():
    ingredients = (request.form.get("ingredients") or "").strip()
    try:
        servings = int(request.form.get("servings", "2"))
    except ValueError:
        servings = 2
    servings = min(max(servings, 1), 12)
    mood = request.form.get("mood", MOODS[0])
    if mood not in MOODS:
        mood = MOODS[0]
    style = request.form.get("style", STYLES[0])
    if style not in STYLES:
        style = STYLES[0]
    note = (request.form.get("note") or "").strip()
    prompt = build_prompt(ingredients, servings, mood, style, note) if ingredients else None
    db = get_db()
    sets = db.execute("SELECT * FROM sets ORDER BY id DESC").fetchall()
    return render_template_string(
        PAGE, sets=sets, moods=MOODS, styles=STYLES,
        ingredients=ingredients, servings=servings, mood=mood, style=style, note=note, prompt=prompt,
    )


@app.route("/sets", methods=["POST"])
def save_set():
    name = (request.form.get("name") or "").strip()
    ingredients = (request.form.get("ingredients") or "").strip()
    if name and ingredients:
        db = get_db()
        db.execute(
            "INSERT INTO sets(name, ingredients, created_at) VALUES(?, ?, ?)",
            (name, ingredients, datetime.now(JST).strftime("%Y-%m-%d %H:%M")),
        )
        db.commit()
    return redirect(url_for("index"))


@app.route("/sets/<int:sid>/delete", methods=["POST"])
def delete_set(sid):
    db = get_db()
    db.execute("DELETE FROM sets WHERE id = ?", (sid,))
    db.commit()
    return redirect(url_for("index"))


init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")))
