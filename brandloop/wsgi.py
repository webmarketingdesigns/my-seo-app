"""WSGI entrypoint. Run with: gunicorn wsgi:app (from the brandloop/ directory)."""
import os

from brandloop import create_app

app = create_app()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5001)), debug=True)
