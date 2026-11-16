import os

from app import create_app

app = create_app()

CERT = os.environ.get("TLS_CERT", "certs/cert.pem")
KEY = os.environ.get("TLS_KEY", "certs/key.pem")
HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "5443"))

if __name__ == "__main__":
    ssl_context = (CERT, KEY) if os.path.exists(CERT) and os.path.exists(KEY) else None
    app.run(host=HOST, port=PORT, ssl_context=ssl_context)
