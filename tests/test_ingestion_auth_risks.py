"""
Authentication that only looks like authentication.

Measured on a real FastAPI app: its login accepted any password, its token was
``hash(email)`` and 17 POST routes had no authentication.  Ingestion reported
one unrelated risk.  These checks find that pattern and stay quiet on a
correct implementation.
"""

from ingestion.analyzer import _auth_risks

FAKE = '''
from fastapi import FastAPI
app = FastAPI()

@app.post("/api/auth/login")
def login(creds: LoginRequest):
    """Authenticate a cloud administrator."""
    email_clean = creds.email.strip().lower()
    if not creds.password or len(creds.password) < 3:
        raise HTTPException(status_code=400, detail="Invalid password provided.")
    return {"status": "success", "token": f"opt_session_{abs(hash(email_clean)) % 1000000:06d}"}

@app.post("/api/apply")
def apply(req: ApplyRequest):
    return run(req)

@app.post("/api/undo")
def undo():
    return rollback()

@app.post("/api/settings")
def settings(req: dict):
    return save(req)
'''

REAL = '''
import secrets
from fastapi import Depends, FastAPI
from passlib.hash import bcrypt
app = FastAPI()

@app.post("/api/auth/login")
def login(creds: LoginRequest, db=Depends(get_db)):
    user = db.find(creds.email)
    if not user or not bcrypt.verify(creds.password, user.password_hash):
        raise HTTPException(401)
    return {"token": secrets.token_urlsafe(32)}

@app.post("/api/apply")
def apply(req: ApplyRequest, user=Depends(current_user)):
    return run(req)

@app.post("/api/undo")
def undo(user=Depends(current_user)):
    return rollback()

@app.post("/api/settings")
def settings(req: dict, user=Depends(current_user)):
    return save(req)
'''

DELEGATED = '''
@router.post("/login")
async def login(form: LoginForm):
    return await auth_service.sign_in(form.email, form.password)
'''

EXPRESS = '''
app.post("/api/login", (req, res) => {
  const { email, password } = req.body;
  if (!password) return res.status(400).end();
  res.json({ token: `tok_${email}` });
});
'''


def kinds(text, rel="api/main.py"):
    return sorted({r.kind for r in _auth_risks(text, rel)})


def test_the_fake_login_pattern_is_reported():
    assert kinds(FAKE) == ["Guessable session token", "Login does not check the password",
                           "State-changing routes without authentication"]
    login = next(r for r in _auth_risks(FAKE, "api/main.py") if r.kind == "Login does not check the password")
    assert login.line == 5 and "/api/auth/login" in login.detail


def test_express_is_checked_too():
    assert kinds(EXPRESS, "server/app.js") == ["Guessable session token", "Login does not check the password"]


def test_a_real_login_and_protected_routes_raise_nothing():
    assert kinds(REAL) == []
    # A login that hands the password to a service is assumed to check it there
    assert kinds(DELEGATED) == []


def test_routes_are_counted_once():
    risk = next(r for r in _auth_risks(FAKE, "api/main.py") if r.kind.startswith("State-changing"))
    assert risk.detail.startswith("4 POST")


def test_a_firebase_web_key_is_not_a_leaked_secret():
    from ingestion.analyzer import _secrets

    web = 'const firebaseConfig = { apiKey: "AIzaSyAZ2aPq_4edc02aRQFLRnsvihK5mnASrxc", authDomain: "x.firebaseapp.com" };'
    assert _secrets(web, "index.html") == []
    # The same key outside a Firebase web config is still reported
    assert _secrets('api_key = "AIzaSyAZ2aPq_4edc02aRQFLRnsvihK5mnASrxc"', "server.py")
