"""Run only Hachi's Academic Studio, without voice or smart-home dependencies."""
import argparse
from pathlib import Path
import sys

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))
from flask import Flask, redirect
from hachi_academic import AcademicService, create_academic_blueprint


def make_app(data_dir=None, caller=None):
    app = Flask(__name__, template_folder=str(APP / "templates"), static_folder=str(APP / "static"))
    service = AcademicService(data_dir or APP / "data/academic/runs", caller)
    app.extensions["academic_service"] = service
    app.register_blueprint(create_academic_blueprint(service))
    app.add_url_rule('/', 'home', lambda: redirect('/academic'))
    return app


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=5055)
    args = parser.parse_args()
    app = make_app()
    print(f"Academic Studio: http://127.0.0.1:{args.port}/academic", flush=True)
    app.run(host="127.0.0.1", port=args.port, threaded=True, use_reloader=False)
