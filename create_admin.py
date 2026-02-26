import mysql.connector
from werkzeug.security import generate_password_hash

# Connect to DB
conn = mysql.connector.connect(
    host="localhost",
    user="root",      # root works for updating
    password="",      # OR your root password
    database="voting_db"
)
cur = conn.cursor()

# Admin credentials to reset
username = "admin"
password = "admin123"

# Generate correct hash
hashed_pw = generate_password_hash(password)

# Update DB
cur.execute("UPDATE admins SET password_hash=%s WHERE username=%s", (hashed_pw, username))
conn.commit()

cur.close()
conn.close()

print("✔ Admin password updated successfully!")
