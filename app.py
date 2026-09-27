"""Examination Management Portal — Flask application entry point."""
from flask import Flask, render_template, redirect, url_for, session

from config import Config
from models import init_db, close_db


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    init_db(app)
    app.teardown_appcontext(close_db)

    from auth import bp as auth_bp
    from admin import bp as admin_bp
    from examiner import bp as examiner_bp
    from student import bp as student_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(examiner_bp)
    app.register_blueprint(student_bp)

    @app.route("/")
    def index():
        user = session.get("user")
        if user:
            return redirect(url_for(f"{user['role']}.dashboard"))
        return render_template("index.html")

    @app.errorhandler(404)
    def not_found(e):
        return render_template("errors/404.html"), 404

    @app.errorhandler(500)
    def server_error(e):
        return render_template("errors/500.html"), 500

    return app


if __name__ == "__main__":
    application = create_app()
    application.run(host="127.0.0.1", port=5000, debug=True)
