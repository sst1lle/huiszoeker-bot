import os
import requests as req
from flask import Blueprint, session, redirect, url_for, request, jsonify, render_template

from db import new_auth_client

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/")
def login():
    if "user_id" in session:
        return redirect(url_for("dash.dashboard"))
    return render_template("login.html")


@auth_bp.route("/register")
def register():
    if "user_id" in session:
        return redirect(url_for("dash.dashboard"))
    return render_template("register.html")


@auth_bp.route("/api/login", methods=["POST"])
def api_login():
    data = request.json or {}
    try:
        result = new_auth_client().auth.sign_in_with_password(
            {"email": data["email"], "password": data["password"]}
        )
        session["user_id"] = result.user.id
        admin_email = os.environ.get("ADMIN_EMAIL", "").strip()
        if admin_email and result.user.email == admin_email:
            session["is_admin"] = True
        return jsonify({"ok": True})
    except Exception:
        return jsonify({"ok": False, "error": "E-mail of wachtwoord onjuist"}), 401


@auth_bp.route("/api/register", methods=["POST"])
def api_register():
    data = request.json or {}
    try:
        result = new_auth_client().auth.sign_up(
            {"email": data["email"], "password": data["password"]}
        )
        if result.user:
            session["user_id"] = result.user.id
            session["naam"] = data.get("naam", "")
            return jsonify({"ok": True})
        return jsonify({"ok": False, "error": "Registratie mislukt"}), 400
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@auth_bp.route("/api/logout", methods=["POST"])
def api_logout():
    session.clear()
    return jsonify({"ok": True})


@auth_bp.route("/forgot-password")
def forgot_password():
    return render_template("forgot_password.html")


@auth_bp.route("/api/forgot-password", methods=["POST"])
def api_forgot_password():
    data = request.json or {}
    email = data.get("email", "").strip()
    if not email:
        return jsonify({"ok": False, "error": "E-mailadres vereist"}), 400
    try:
        supabase_url = os.environ["SUPABASE_URL"]
        supabase_key = os.environ["SUPABASE_KEY"]
        req.post(
            f"{supabase_url}/auth/v1/recover",
            json={"email": email},
            params={"redirect_to": "https://huursignal.com/reset-password"},
            headers={"apikey": supabase_key, "Content-Type": "application/json"},
            timeout=10,
        )
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@auth_bp.route("/reset-password", strict_slashes=False)
def reset_password():
    return render_template("reset_password.html")


@auth_bp.route("/api/reset-password", methods=["POST"])
def api_reset_password():
    data = request.json or {}
    access_token  = data.get("access_token", "")
    refresh_token = data.get("refresh_token", "")
    password      = data.get("password", "")
    if not access_token or not password:
        return jsonify({"ok": False, "error": "Ongeldige aanvraag"}), 400
    try:
        client = new_auth_client()
        client.auth.set_session(access_token, refresh_token)
        client.auth.update_user({"password": password})
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400
