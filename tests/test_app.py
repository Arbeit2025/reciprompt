import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["RECIPROMPT_DB"] = _tmp.name

import app as app_module  # noqa: E402


class ReciPromptTest(unittest.TestCase):
    def setUp(self):
        app_module.init_db()
        self.client = app_module.app.test_client()
        with app_module.app.app_context():
            conn = app_module.get_db()
            conn.execute("DELETE FROM sets")
            conn.commit()

    def test_healthz(self):
        res = self.client.get("/healthz")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["status"], "ok")

    def test_index_ok(self):
        self.assertEqual(self.client.get("/").status_code, 200)

    def test_build_prompt(self):
        p = app_module.build_prompt("鶏肉、キャベツ", 2, "時短", "和", "辛いのは苦手")
        self.assertIn("鶏肉、キャベツ", p)
        self.assertIn("2人分", p)
        self.assertIn("和風", p)
        self.assertIn("時短", p)
        self.assertIn("辛いのは苦手", p)

    def test_build_prompt_omakase(self):
        p = app_module.build_prompt("卵", 1, "さっぱり", "おまかせ", "")
        self.assertNotIn("おまかせ風", p)
        self.assertIn("1人分", p)

    def test_generate_page(self):
        res = self.client.post(
            "/generate",
            data={"ingredients": "豚肉、玉ねぎ", "servings": "3", "mood": "がっつり", "style": "洋", "note": ""},
        )
        body = res.get_data(as_text=True)
        self.assertIn("豚肉、玉ねぎ", body)
        self.assertIn("3人分", body)

    def test_save_load_delete_set(self):
        self.client.post("/sets", data={"name": "いつもの", "ingredients": "じゃがいも、玉ねぎ"})
        with app_module.app.app_context():
            conn = app_module.get_db()
            row = conn.execute("SELECT * FROM sets").fetchone()
            self.assertIsNotNone(row)
            sid = row["id"]
        res = self.client.get(f"/?set_id={sid}")
        self.assertIn("じゃがいも、玉ねぎ", res.get_data(as_text=True))
        self.client.post(f"/sets/{sid}/delete")
        with app_module.app.app_context():
            conn = app_module.get_db()
            self.assertIsNone(conn.execute("SELECT * FROM sets").fetchone())


if __name__ == "__main__":
    unittest.main()
