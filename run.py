import os

from app import create_app

app = create_app()

CERT = os.environ.get("TLS_CERT", "certs/cert.pem")
KEY = os.environ.get("TLS_KEY", "certs/key.pem")

if __name__ == "__main__":
    ssl_context = (CERT, KEY) if os.path.exists(CERT) and os.path.exists(KEY) else None
    app.run(host="127.0.0.1", port=5443, ssl_context=ssl_context)
