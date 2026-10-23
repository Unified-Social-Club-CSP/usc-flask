#!/usr/bin/env python3
"""Verify the profile interest survey end-to-end through the real request stack.

Covers guests, pending (new) accounts, cross-user isolation, bad input, staff-only
results, revoked tokens, and database failures. Runs against a throwaway SQLite DB
with GitHub and Google faked, and checksums the real dev DB before and after to prove
it was never touched.

Usage:  python scripts/verify_interests.py        (from the flask repo root)
Exit:   0 all checks passed, 1 otherwise.
"""
import hashlib, json, os, shutil, sys, tempfile
from datetime import datetime, timedelta
from unittest.mock import patch

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(REPO)
sys.path.insert(0, REPO)
os.environ.setdefault("SECRET_KEY", "verify-interests")

REAL_DB = os.path.join(REPO, "instance", "volumes", "user_management.db")
PASSWORD = "Passw0rd!123"
_failures = []


def check(label, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + label + (f"   [{detail}]" if detail else ""))
    if not cond:
        _failures.append(label)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        h.update(fh.read())
    return h.hexdigest()


class Resp:
    status_code = 400

    def json(self):
        return {}


class FakeGitHub:
    def get(self, uid):
        return {}, 200


def main():
    real_before = sha256(REAL_DB) if os.path.exists(REAL_DB) else None
    tmp = tempfile.mkdtemp(prefix="interests-")

    import __init__ as pkg
    from sqlalchemy import create_engine
    from sqlalchemy.exc import OperationalError
    import jwt
    app, db = pkg.app, pkg.db
    with app.app_context():
        db.engines[None] = create_engine(f"sqlite:///{os.path.join(tmp, 'test.db')}")
    import main  # noqa: F401  registers every model and blueprint
    from model.user import User
    from model.fops_interests import InterestSurvey

    app.config["TESTING"] = True
    app.config["GOOGLE_CLIENT_ID"] = None
    with app.app_context():
        db.create_all()
        for uid, role, active in (("zz_admin", "Admin", True), ("zz_vol", "Volunteer", True),
                                  ("zz_member", "User", True), ("zz_pending_admin", "Admin", False),
                                  ("zz_pending_vol", "Volunteer", False)):
            u = User(name=f"Name {uid}", uid=uid, password=PASSWORD, role=role)
            db.session.add(u)
            db.session.commit()
            if active:
                u.activate()

    def user(uid):
        with app.app_context():
            u = User.query.filter_by(_uid=uid).first()
            return dict(id=u.id, role=u.role, active=u.active)

    def login(c, uid):
        r = c.post("/api/authenticate", json={"uid": uid, "password": PASSWORD})
        assert r.status_code == 200, (uid, r.status_code)

    def signup(c, uid):
        return c.post("/api/user", json=dict(name=f"Name {uid}", uid=uid, password=PASSWORD))

    def put(c, body=None, **kw):
        return c.put("/api/fops/profile/interests", json=body, **kw)

    with patch("api.user.GitHubUser", FakeGitHub), patch("model.google_token.requests.get", lambda *a, **k: Resp()):
        # Guests
        with app.test_client() as c:
            check("guest: GET me is 401", c.get("/api/fops/profile/me").status_code == 401)
            check("guest: GET interests is 401", c.get("/api/fops/profile/interests").status_code == 401)
            check("guest: PUT interests is 401", put(c, {"answers": {"comfort": "okay"}}).status_code == 401)
            check("guest: summary is 401", c.get("/api/fops/profile/interests/summary").status_code == 401)
            r = c.get("/fops/interests/")
            check("guest: results page redirects to sign in",
                  r.status_code == 302 and "/login" in r.headers.get("Location", ""), r.status_code)
            with app.app_context():
                check("guest: nothing was saved", InterestSurvey.query.count() == 0)

        # A new signup is pending and can use only its own profile endpoints
        a, b = app.test_client(), app.test_client()
        check("signup A created", signup(a, "zz_new_a").status_code == 200)
        check("signup B created", signup(b, "zz_new_b").status_code == 200)
        check("new accounts start pending as User",
              user("zz_new_a") == dict(id=user("zz_new_a")["id"], role="User", active=False), user("zz_new_a"))
        login(a, "zz_new_a")
        login(b, "zz_new_b")

        r = a.get("/api/fops/profile/me")
        me = r.get_json() or {}
        check("pending: GET me is 200", r.status_code == 200, r.status_code)
        check("pending: me has exactly id, uid, name, role, active",
              set(me) == {"id", "uid", "name", "role", "active"}, sorted(me))
        check("pending: me reports active false", me.get("active") is False and me.get("uid") == "zz_new_a", me)
        check("pending: me never includes a password", "password" not in r.get_data(as_text=True).lower())

        r = a.get("/api/fops/profile/interests")
        check("pending: GET before saving returns null answers and the questions",
              r.status_code == 200 and r.get_json()["answers"] is None and "goals" in r.get_json()["questions"])

        # Partial answers, scam question skipped, volunteer "yes"
        partial = {"goals": ["games", "events", "games"], "comfort": "starting", "volunteer": "yes"}
        r = put(a, {"answers": partial})
        check("pending: PUT partial answers is 200", r.status_code == 200, r.get_data(as_text=True))
        check("pending: repeats dropped, scam question left out",
              r.get_json().get("answers") == {"goals": ["games", "events"], "comfort": "starting", "volunteer": "yes"},
              r.get_json())
        r = a.get("/api/fops/profile/interests")
        check("pending: GET reads back own answers", r.get_json()["answers"]["comfort"] == "starting")
        check("volunteer 'yes' grants nothing: still User and pending",
              user("zz_new_a")["role"] == "User" and user("zz_new_a")["active"] is False, user("zz_new_a"))
        check("pending: empty answers are allowed", put(b, {"answers": {}}).status_code == 200)

        # Everything else still needs an active account
        check("pending: GET /api/fops/progress still 403", a.get("/api/fops/progress").status_code == 403)
        check("pending: PUT /api/fops/progress/<game> still 403",
              a.put("/api/fops/progress/scam", json={"data": {}}).status_code == 403)
        check("pending: GET /api/id still 403", a.get("/api/id").status_code == 403)
        check("pending: summary still 403", a.get("/api/fops/profile/interests/summary").status_code == 403)

        # Cross-user isolation
        a_id = user("zz_new_a")["id"]
        r = b.get("/api/fops/profile/interests")
        check("isolation: B sees its own empty answers, not A's", r.get_json()["answers"] == {}, r.get_json())
        r = b.get(f"/api/fops/profile/interests?user_id={a_id}&uid=zz_new_a")
        check("isolation: user_id in the query string is ignored", r.get_json()["answers"] == {}, r.get_json())
        r = put(b, {"answers": {"comfort": "comfortable"}, "user_id": a_id})
        check("isolation: user_id in the body is rejected (400)", r.status_code == 400, r.status_code)
        r = put(b, {"answers": {"comfort": "comfortable"}, "uid": "zz_new_a"})
        check("isolation: uid in the body is rejected (400)", r.status_code == 400, r.status_code)
        r = put(b, {"answers": {"user_id": a_id}})
        check("isolation: user_id inside answers is rejected (400)", r.status_code == 400, r.status_code)
        check("isolation: A's answers unchanged",
              a.get("/api/fops/profile/interests").get_json()["answers"]["comfort"] == "starting")
        r = b.put(f"/api/fops/profile/interests?user_id={a_id}", json={"answers": {"comfort": "okay"}})
        check("isolation: query user_id on PUT saves to B only",
              r.status_code == 200
              and a.get("/api/fops/profile/interests").get_json()["answers"]["comfort"] == "starting"
              and b.get("/api/fops/profile/interests").get_json()["answers"]["comfort"] == "okay")

        # Bad input
        bad = {
            "malformed JSON": dict(data="{not json", content_type="application/json"),
            "non-JSON content type": dict(data="answers=1", content_type="application/x-www-form-urlencoded"),
            "empty body": dict(data="", content_type="application/json"),
        }
        for label, kw in bad.items():
            r = b.put("/api/fops/profile/interests", **kw)
            check(f"input: {label} is 400", r.status_code == 400, r.status_code)
        for label, body in (("JSON list", [1, 2]), ("JSON string", "hi"), ("JSON number", 5), ("JSON null", None),
                            ("missing answers", {}), ("answers is a list", {"answers": ["games"]}),
                            ("answers is a string", {"answers": "games"}),
                            ("unknown question", {"answers": {"favorite_color": "blue"}}),
                            ("unknown single choice", {"answers": {"comfort": "expert"}}),
                            ("unknown list choice", {"answers": {"goals": ["games", "hacking"]}}),
                            ("list question given a string", {"answers": {"goals": "games"}}),
                            ("single question given a list", {"answers": {"comfort": ["okay"]}}),
                            ("null answer", {"answers": {"comfort": None}}),
                            ("object answer", {"answers": {"comfort": {"a": 1}}}),
                            ("role in body", {"answers": {}, "role": "Admin"}),
                            ("active in body", {"answers": {}, "active": True})):
            r = b.put("/api/fops/profile/interests", data=json.dumps(body),
                      content_type="application/json")
            check(f"input: {label} is 400", r.status_code == 400, r.status_code)
        check("input: B's answers survive all the bad requests",
              b.get("/api/fops/profile/interests").get_json()["answers"] == {"comfort": "okay"})
        check("input: nobody gained a role or activation",
              user("zz_new_b")["role"] == "User" and user("zz_new_b")["active"] is False)

        # Database failure rolls back and the next save still works
        with patch.object(db.session, "commit", side_effect=OperationalError("stmt", {}, Exception("disk full"))):
            r = put(a, {"answers": {"comfort": "okay"}})
        check("db failure: PUT returns 500", r.status_code == 500, r.status_code)
        check("db failure: old answers kept",
              a.get("/api/fops/profile/interests").get_json()["answers"]["comfort"] == "starting")
        check("db failure: next save works", put(a, {"answers": {"comfort": "okay"}}).status_code == 200)
        check("db failure: new answer stored",
              a.get("/api/fops/profile/interests").get_json()["answers"] == {"comfort": "okay"})

        # A pending account can sign out, and that is all sign-out unlocks
        name = app.config["JWT_TOKEN_NAME"]
        check("sign-out: pending B has a cookie before", b.get_cookie(name) is not None)
        r = b.delete("/api/authenticate")
        cleared = [h for h in r.headers.getlist("Set-Cookie") if h.startswith(f"{name}=")]
        check("sign-out: pending account gets 200", r.status_code == 200, r.status_code)
        check("sign-out: response expires the cookie",
              len(cleared) == 1 and ("Max-Age=0" in cleared[0] or "Expires=Thu, 01 Jan 1970" in cleared[0]), cleared)
        check("sign-out: cookie is gone from the client", b.get_cookie(name) is None)
        check("sign-out: then me is 401", b.get("/api/fops/profile/me").status_code == 401)
        check("sign-out: then interests is 401", b.get("/api/fops/profile/interests").status_code == 401)
        check("sign-out: signing out again is 401", b.delete("/api/authenticate").status_code == 401)
        check("sign-out: B stays User and pending", user("zz_new_b")["role"] == "User" and user("zz_new_b")["active"] is False)
        login(b, "zz_new_b")
        check("sign-out: B can sign back in and read its answers",
              b.get("/api/fops/profile/interests").get_json()["answers"] == {"comfort": "okay"})
        check("sign-out: B's progress is still 403", b.get("/api/fops/progress").status_code == 403)
        check("sign-out: B's /api/id is still 403", b.get("/api/id").status_code == 403)
        check("sign-out: B's summary is still 403", b.get("/api/fops/profile/interests/summary").status_code == 403)
        check("sign-out: guest sign-out is 401", app.test_client().delete("/api/authenticate").status_code == 401)
        c = app.test_client()
        login(c, "zz_member")
        check("sign-out: active member sign-out still 200",
              c.delete("/api/authenticate").status_code == 200 and c.get_cookie(name) is None)

        # Staff-only summary API
        summary_codes = {}
        for uid in ("zz_admin", "zz_vol", "zz_member", "zz_pending_admin", "zz_pending_vol"):
            with app.test_client() as c:
                login(c, uid)
                r = c.get("/api/fops/profile/interests/summary")
                summary_codes[uid] = r.status_code
                if uid == "zz_admin":
                    s = r.get_json()
                    text = r.get_data(as_text=True)
        check("summary: active Admin 200", summary_codes["zz_admin"] == 200, summary_codes)
        check("summary: active Volunteer 200", summary_codes["zz_vol"] == 200, summary_codes)
        check("summary: active member 403", summary_codes["zz_member"] == 403, summary_codes)
        check("summary: pending Admin 403", summary_codes["zz_pending_admin"] == 403, summary_codes)
        check("summary: pending Volunteer 403", summary_codes["zz_pending_vol"] == 403, summary_codes)
        check("summary: counts the two responses", s["responses"] == 2 and s["counts"]["comfort"]["okay"] == 2, s)
        check("summary: has no names or uids", "zz_new" not in text and "Name zz" not in text)

        # Staff-only results page (session sign-in)
        def page(uid):
            with app.test_client() as c:
                c.post("/login", data={"username": uid, "password": PASSWORD})
                return c.get("/fops/interests/")
        r = page("zz_admin")
        html = r.get_data(as_text=True)
        check("page: active Admin 200", r.status_code == 200, r.status_code)
        check("page: Admin sees named answers", "Name zz_new_a" in html and "zz_new_b" in html)
        check("page: Admin sees readable labels", "Very comfortable" in html and "Waiting for approval" in html)
        r = page("zz_vol")
        html = r.get_data(as_text=True)
        check("page: active Volunteer 200", r.status_code == 200, r.status_code)
        check("page: Volunteer sees totals but no names",
              "Members answered" in html and "zz_new_a" not in html and "Each Member" not in html)
        check("page: active member 403", page("zz_member").status_code == 403)
        r = page("zz_pending_admin")
        check("page: pending Admin cannot sign in, so is sent to sign in",
              r.status_code == 302 and "/login" in r.headers.get("Location", ""), r.status_code)
        with app.test_client() as c:
            c.post("/login", data={"username": "zz_admin", "password": PASSWORD})
            check("nav: Admin dashboard links the results page", "/fops/interests/" in c.get("/").get_data(as_text=True))
            with app.app_context():
                User.query.filter_by(_uid="zz_admin").first().deactivate()
            check("page: Admin deactivated mid-session gets 403", c.get("/fops/interests/").status_code == 403)
            check("nav: deactivated Admin no longer sees the link", "/fops/interests/" not in c.get("/").get_data(as_text=True))
            with app.app_context():
                User.query.filter_by(_uid="zz_admin").first().activate()
        with app.test_client() as c:
            c.post("/login", data={"username": "zz_member", "password": PASSWORD})
            check("nav: member dashboard has no results link", "/fops/interests/" not in c.get("/").get_data(as_text=True))

        # Revoked, expired, and orphaned tokens
        with app.test_client() as c:
            login(c, "zz_new_a")
            with app.app_context():
                u = User.query.filter_by(_uid="zz_new_a").first()
                u.set_password("AnotherPassw0rd!")
                db.session.commit()
            check("revoked: me after password change is 401", c.get("/api/fops/profile/me").status_code == 401)
            check("revoked: interests after password change is 401",
                  c.get("/api/fops/profile/interests").status_code == 401)
            check("revoked: PUT after password change is 401", put(c, {"answers": {}}).status_code == 401)
        expired = jwt.encode({"_uid": "zz_new_b", "token_version": 0, "exp": datetime.utcnow() - timedelta(minutes=1)},
                             app.config["SECRET_KEY"], algorithm="HS256")
        ghost = jwt.encode({"_uid": "zz_nobody", "token_version": 0, "exp": datetime.utcnow() + timedelta(minutes=5)},
                           app.config["SECRET_KEY"], algorithm="HS256")
        forged = jwt.encode({"_uid": "zz_new_b", "token_version": 0, "exp": datetime.utcnow() + timedelta(minutes=5)},
                            "wrong-secret", algorithm="HS256")
        for label, tok in (("expired", expired), ("unknown user", ghost), ("wrong signature", forged)):
            with app.test_client() as c:
                c.set_cookie(name, tok)
                check(f"token: {label} is 401 on interests", c.get("/api/fops/profile/interests").status_code == 401)
            with app.test_client() as c:
                r = c.get("/api/fops/profile/me", headers={"Authorization": f"Bearer {tok}"})
                check(f"token: {label} bearer is 401 on me", r.status_code == 401, r.status_code)

    real_after = sha256(REAL_DB) if os.path.exists(REAL_DB) else None
    check("real dev DB untouched", real_before == real_after)
    shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n{'ALL PASSED' if not _failures else f'{len(_failures)} FAILED'}")
    return 1 if _failures else 0


if __name__ == "__main__":
    sys.exit(main())
