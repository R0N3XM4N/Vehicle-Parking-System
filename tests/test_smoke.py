from app import create_app

def test_login_page_loads():
    app = create_app()
    client = app.test_client()
    assert client.get("/login").status_code == 200