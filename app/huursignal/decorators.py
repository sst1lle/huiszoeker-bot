import functools
from flask import session, redirect, url_for


def login_required(f):
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("auth.login"))
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("auth.login"))
        if not session.get("is_admin"):
            return redirect(url_for("dash.dashboard"))
        return f(*args, **kwargs)
    return decorated
    