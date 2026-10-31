"""Local web app: python -m conferences.app  ->  http://localhost:5050"""
from flask import Flask, abort, g, jsonify, render_template, request

from . import config, db


def create_app(db_path=None) -> Flask:
    app = Flask(__name__, template_folder=str(config.ROOT / "templates"),
                static_folder=str(config.ROOT / "static"))
    app.config["DB_PATH"] = db_path or config.DB_PATH

    def get_conn():
        if "conn" not in g:
            g.conn = db.connect(app.config["DB_PATH"])
        return g.conn

    @app.teardown_appcontext
    def close_conn(_exc):
        conn = g.pop("conn", None)
        if conn is not None:
            conn.close()

    with app.app_context():
        conn = get_conn()
        db.init_db(conn)
        db.prune(conn)

    @app.get("/")
    def index():
        return render_template("index.html", tier_labels=config.TIER_LABELS)

    @app.get("/api/conferences")
    def api_list():
        rows = db.list_ranked(get_conn(), category=request.args.get("category"),
                              region=request.args.get("region"))
        last = get_conn().execute("SELECT MAX(last_seen) FROM conferences").fetchone()[0]
        return jsonify({"conferences": rows, "last_updated": last})

    @app.post("/api/conferences/<int:conf_id>/hide")
    def api_hide(conf_id):
        if not db.hide(get_conn(), conf_id):
            abort(404)
        return jsonify({"ok": True})

    return app


if __name__ == "__main__":
    create_app().run(host=config.APP_HOST, port=config.APP_PORT, debug=False)
