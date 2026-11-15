from app import create_app, db
from app.models import User

app = create_app()
with app.app_context():
    if not User.query.filter_by(email="perf@example.com").first():
        u = User(name="Perf User", email="perf@example.com")
        u.set_password("Test-password-123")
        db.session.add(u)
        db.session.commit()
        print("created")
    else:
        print("exists")
