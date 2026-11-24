
import os
import getpass
from werkzeug.security import generate_password_hash
from app import db

email = input("Admin email: ").strip().lower()
password = getpass.getpass("New password (minimum 12 characters): ")
confirm = getpass.getpass("Confirm new password: ")

if not email or len(password) < 12:
    raise SystemExit("Email required; password must be at least 12 characters.")

if password != confirm:
    raise SystemExit("Passwords do not match.")

with db() as connection:
    user = connection.execute(
        "SELECT id FROM admin_users WHERE email = ?",
        (email,)
    ).fetchone()

    if not user:
        raise SystemExit("Admin email not found. No changes made.")

    connection.execute(
        "UPDATE admin_users SET password_hash = ? WHERE id = ?",
        (generate_password_hash(password), user["id"])
    )

print("Admin password reset successfully.")
