import os
import base64
import cv2
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
from werkzeug.utils import secure_filename
import mysql.connector 
import traceback
import random
import string
import numpy as np
from io import BytesIO
from PIL import Image
import mediapipe as mp 
from mysql.connector import Error
from flask_mail import Mail, Message

# ---------------- CONFIG ----------------
UPLOAD_FACE = 'static/uploads/face'
UPLOAD_IRIS = 'static/uploads/iris'
TEMP_DIR = 'static/temp'

for folder in (UPLOAD_FACE, UPLOAD_IRIS, TEMP_DIR):
    os.makedirs(folder, exist_ok=True)

app = Flask(__name__)
app.secret_key = 'secret-key'
app.config['UPLOAD_FACE'] = UPLOAD_FACE
app.config['UPLOAD_IRIS'] = UPLOAD_IRIS
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024

# ------------------ SMTP CONFIG ------------------
# NOTE: If email is not working, double-check that the MAIL_PASSWORD is an
# App Password generated from your Google Account Security settings, and 2FA is enabled.
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USE_SSL'] = False
app.config['MAIL_USERNAME'] = 'smartvoting01@gmail.com'
app.config['MAIL_PASSWORD'] = 'zwas lmrq sqji cics'
app.config['MAIL_DEFAULT_SENDER'] = 'smartvoting01@gmail.com'

mail = Mail(app)

# ---------------- DATABASE ----------------
def get_db():
    return mysql.connector.connect(
        host="localhost",
        user="root",
        password="",     # XAMPP default → EMPTY PASSWORD
        database="voting_db",
        port=3306,
        connection_timeout=5
    )

# ------------- OTP GENERATION ---------------------
def generate_otp():
    return ''.join(random.choices(string.digits, k=6))

# ------------- SEND OTP --------------------------
@app.route("/send_otp", methods=["POST"])
def send_otp():
    # Use request.form to get data from the AJAX FormData object
    email = request.form.get('email')

    if not email:
        return jsonify({"status": "error", "msg": "Email is required to send OTP."}), 400

    # Check for existing voter with this email before sending OTP
    conn = None # Initialize conn and cursor
    cursor = None
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM voters WHERE email=%s", (email,))
        if cursor.fetchone():
            return jsonify({"status": "error", "msg": "A voter with this email is already registered."}), 409
    except Exception as e:
        traceback.print_exc()
        return jsonify({"status": "error", "msg": f"Database check failed: {str(e)}"}), 500
    finally:
        if cursor: cursor.close()
        if conn and conn.is_connected(): conn.close()


    otp = generate_otp()
    # Store the OTP in session associated with the email
    session['otp'] = otp
    session['otp_email'] = email
    session['otp_verified'] = False # Reset verification status
    
    # Debug: print OTP to console for local testing
    print(f"DEBUG: OTP for {email} is: {otp}")

    try:
        msg = Message("Your OTP Verification Code", recipients=[email])
        msg.body = f"Your OTP for voter registration is: {otp}"
        mail.send(msg)
        return jsonify({"status": "success", "msg": "OTP sent successfully to your email!"})
    except Exception as e:
        # Print full traceback to console for debugging
        traceback.print_exc()
        # Optionally clear the session OTP to prevent reuse after failure
        session.pop('otp', None)
        session.pop('otp_email', None)
        return jsonify({"status": "error", "msg": f"Failed to send OTP. Please check email address. Error: {str(e)}"}), 500

# ------------- VERIFY OTP ------------------------
@app.route("/verify_otp", methods=["POST"])
def verify_otp():
    # Use request.form to get data from the AJAX FormData object
    user_otp = request.form.get('otp')
    submitted_email = request.form.get('email')

    # Check for missing data
    if not all([user_otp, submitted_email]):
        return jsonify({"status": "error", "msg": "Missing OTP or Email data."}), 400

    # Check against session data
    stored_otp = session.get('otp')
    stored_email = session.get('otp_email')

    if stored_otp and user_otp == stored_otp and submitted_email == stored_email:
        # OTP matches and the email used to generate matches the one submitted
        session['otp_verified'] = True
        # IMPORTANT: Do NOT clear the OTP here. The admin_voter_register route needs to check this status.
        # It is cleared after final registration.
        return jsonify({"status": "success", "msg": "OTP verified successfully!"})
    
    # On failure, clear session OTP data to force resend/re-entry
    session.pop('otp', None)
    session.pop('otp_email', None)
    session.pop('otp_verified', None)

    return jsonify({"status": "error", "msg": "Invalid or expired OTP. Please click 'Resend OTP'."}), 401

# ---------------- BIOMETRIC HELPERS ----------------
mp_face = mp.solutions.face_mesh.FaceMesh(static_image_mode=True)

def save_base64_image(b64_data, folder, prefix='img'):
    """Decode base64 image and save to folder"""
    try:
        if ',' in b64_data:
            _, encoded = b64_data.split(',', 1)
        else:
            encoded = b64_data
        img_data = base64.b64decode(encoded)
        filename = f"{prefix}_{datetime.now().strftime('%Y%m%d%H%M%S%f')}.jpg"
        path = os.path.join(folder, secure_filename(filename))
        with open(path, 'wb') as f:
            f.write(img_data)
        return path
    except Exception as e:
        print("Error saving image:", e)
        return None

def match_images(img1_path, img2_path, threshold=0.2):
    """ORB feature matching for face or iris"""
    try:
        img1 = cv2.imread(img1_path, 0)
        img2 = cv2.imread(img2_path, 0)
        if img1 is None or img2 is None:
            return False
        orb = cv2.ORB_create(nfeatures=1000)
        kp1, des1 = orb.detectAndCompute(img1, None)
        kp2, des2 = orb.detectAndCompute(img2, None)
        if des1 is None or des2 is None:
            return False
        bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
        matches = bf.match(des1, des2)
        similarity = len(matches) / max(len(kp1), 1)
        return similarity > threshold
    except Exception as e:
        print("Matching error:", e)
        return False

def match_iris(img1_path, img2_path):
    try:
        img1 = cv2.imread(img1_path, 0)
        img2 = cv2.imread(img2_path, 0)
        if img1 is None or img2 is None: return False
        orb = cv2.ORB_create(nfeatures=1500)
        kp1, des1 = orb.detectAndCompute(img1, None)
        kp2, des2 = orb.detectAndCompute(img2, None)
        if des1 is None or des2 is None: return False
        FLANN_INDEX_LSH = 6
        flann = cv2.FlannBasedMatcher(
            dict(algorithm=FLANN_INDEX_LSH, table_number=6, key_size=12, multi_probe_level=1),
            dict(checks=100)
        )
        matches = flann.knnMatch(des1, des2, k=2)
        good_matches = [m for m,n in matches if m.distance < 0.8*n.distance]
        similarity = len(good_matches)/max(len(kp1),1)
        return similarity > 0.1
    except: return False

def crop_face_and_iris(img_path):
    """
    Given a saved image path, try to crop face and an iris patch.
    Returns: (face_img_rgb_bgr, iris_img_gray) or (None, None) on failure.
    """
    try:
        img = cv2.imread(img_path)
        if img is None:
            return None, None
        h, w = img.shape[:2]
        # create FaceMesh per-call to avoid global state issues
        with mp.solutions.face_mesh.FaceMesh(static_image_mode=True,
                                             max_num_faces=1,
                                             refine_landmarks=True,
                                             min_detection_confidence=0.5) as fm:
            rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            results = fm.process(rgb)
            if not results or not results.multi_face_landmarks:
                return None, None
            face_landmarks = results.multi_face_landmarks[0]

            # face bounding box
            xs = [int(lm.x * w) for lm in face_landmarks.landmark]
            ys = [int(lm.y * h) for lm in face_landmarks.landmark]
            x_min, y_min = max(0, min(xs)), max(0, min(ys))
            x_max, y_max = min(w, max(xs)), min(h, max(ys))
            if x_max - x_min < 20 or y_max - y_min < 20:
                return None, None
            face_img = img[y_min:y_max, x_min:x_max]

            # left eye iris/eye region using typical mediapipe landmarks
            # indices commonly used: 33, 133 (left outer corners), 159 (upper), 145 (lower)
            left_eye_idxs = [33, 133, 159, 145]
            pts = []
            for i in left_eye_idxs:
                lm = face_landmarks.landmark[i]
                pts.append((int(lm.x * w), int(lm.y * h)))
            pts = np.array(pts)
            x_e, y_e, w_e, h_e = cv2.boundingRect(pts)
            # expand slightly to include whole eye
            pad = int(max(4, 0.25 * max(w_e, h_e)))
            sx = max(0, x_e - pad)
            sy = max(0, y_e - pad)
            ex = min(w, x_e + w_e + pad)
            ey = min(h, y_e + h_e + pad)
            if ex - sx < 8 or ey - sy < 8:
                # fallback to small center crop of face
                center_x = (x_min + x_max)//2
                center_y = (y_min + y_max)//2
                s = min(120, w, h)
                sx = max(0, center_x - s//2)
                sy = max(0, center_y - s//2)
                ex = sx + s
                ey = sy + s

            iris_img = img[sy:ey, sx:ex]
            if iris_img.size == 0:
                return None, None
            # convert iris to gray to store/compare
            iris_gray = cv2.cvtColor(iris_img, cv2.COLOR_BGR2GRAY)
            return face_img, iris_gray
    except Exception as e:
        # don't crash the server; return failure indicator
        print("crop_face_and_iris error:", e)
        return None, None
        
# ---------------- EMAIL SENDER HELPER ----------------
def send_registration_email(recipient_email, voter_name, aadhaar_id):
    """Sends a confirmation email to the newly registered voter."""
    try:
        msg = Message(
            subject="Voter Registration Confirmation - E-Voting System",
            recipients=[recipient_email],
            body=f"""
Dear {voter_name},

Your registration for the E-Voting System has been successfully processed.

Details:
Aadhaar ID: {aadhaar_id}

You can now proceed to the verification page to cast your vote.

This is an automated message, please do not reply.
            """,
            html=f"""
            <p style="font-family: sans-serif;">Dear <b>{voter_name}</b>,</p>
            <p style="font-family: sans-serif;">Your registration for the E-Voting System has been successfully processed.</p>
            <p style="font-family: sans-serif;"><b>Details:</b></p>
            <ul style="font-family: sans-serif;">
                <li>Aadhaar ID: <b>{aadhaar_id}</b></li>
            </ul>
            <p style="font-family: sans-serif;">You can now proceed to the verification page to cast your vote.</p>
            <br>
            <p style="color:#888;font-size:0.9em;font-family: sans-serif;">This is an automated message, please do not reply.</p>
            """
        )
        mail.send(msg)
        return True
    except Exception as e:
        # LOGGING IMPROVEMENT: Print full traceback to console for detailed SMTP error debugging
        print(f"\n--- SMTP Error Diagnostic for {recipient_email} ---")
        print("Error details:")
        traceback.print_exc()
        print("--- End SMTP Diagnostic ---\n")
        return False


# ---------------- PUBLIC ROUTES ----------------
@app.route("/")
@app.route("/home")
def home():
    return render_template("index.html", is_admin=False)

@app.route("/about")
def about():
    return render_template("about.html", is_admin=False)

# ---------------- ADMIN ROUTES ----------------
@app.route("/admin", methods=['GET','POST'])
def admin_login():
    conn = None
    cur = None

    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        conn = get_db()
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT * FROM admins WHERE username=%s", (username,))
        row = cur.fetchone()

        if row:
            db_password = row.get("password_hash")   # your real column
            print("DB PASSWORD:", db_password)
            print("INPUT PASSWORD:", password)

            if password == db_password:
                session['admin'] = username
                return redirect(url_for("admin_home"))

        flash("Invalid credentials", "danger")

    return render_template("admin_login.html", is_admin=True)

@app.route("/admin/home")
def admin_home():
    if 'admin' not in session: return redirect(url_for('admin_login'))
    total_voters=total_candidates=0
    conn = None # Initialize conn and cur
    cur = None
    try:
        conn=get_db(); cur=conn.cursor()
        cur.execute("SELECT COUNT(*) FROM voters"); total_voters=cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM candidates"); total_candidates=cur.fetchone()[0]
    except: pass
    finally: 
        if cur: cur.close()
        if conn and conn.is_connected(): conn.close()
    return render_template("admin_home.html", total_voters=total_voters, total_candidates=total_candidates, is_admin=True)

@app.route("/admin_voter_register", methods=["GET", "POST"])
def admin_voter_register():
    if 'admin' not in session:
        return redirect(url_for('admin_login'))

    conn = None
    cursor = None

    try:
        conn = get_db()
        cursor = conn.cursor(dictionary=True)

        # ===========================
        # DELETE VOTER
        # ===========================
        if request.method == "GET" and request.args.get("delete_id"):
            delete_id = request.args.get("delete_id")
            try:
                cursor.execute("DELETE FROM voters WHERE id = %s", (delete_id,))
                conn.commit()
                flash("🗑️ Voter deleted successfully.", "success")
            except Exception as e:
                flash(f"❌ Error deleting voter: {e}", "danger")

        # ===========================
        # REGISTER VOTER
        # ===========================
        if request.method == "POST" and request.form.get("name"):

            name = request.form.get("name")
            aadhaar = request.form.get("aadhaar")
            phone = request.form.get("phone")
            email = request.form.get("email")
            face_image_b64 = request.form.get("face_image_b64")
            iris_image_b64 = request.form.get("iris_image_b64")

            # OTP Check
            if session.get('otp_verified') is not True or email != session.get('otp_email'):
                session.pop('otp', None)
                session.pop('otp_email', None)
                session.pop('otp_verified', None)
                flash("❌ OTP Verification required.", "danger")
                return redirect(url_for("admin_voter_register"))

            if not all([name, aadhaar, phone, email, face_image_b64]):
                flash("❌ Fill all fields & capture biometrics", "danger")
                return redirect(url_for("admin_voter_register"))

            try:
                # -------------------------
                # SAVE FACE IMAGE
                # -------------------------
                face_data = base64.b64decode(face_image_b64.split(',')[1])
                face_filename = f"{aadhaar}_face.jpg"
                face_path = os.path.join(UPLOAD_FACE, face_filename)
                with open(face_path, "wb") as f:
                    f.write(face_data)

                # -------------------------
                # SAVE IRIS IMAGE
                # -------------------------
                iris_filename = None
                if iris_image_b64:
                    iris_data = base64.b64decode(iris_image_b64.split(',')[1])
                    iris_filename = f"{aadhaar}_iris.jpg"
                    iris_path = os.path.join(UPLOAD_IRIS, iris_filename)
                    with open(iris_path, "wb") as f:
                        f.write(iris_data)

                # Duplicate check
                cursor.execute("SELECT id FROM voters WHERE aadhaar=%s OR email=%s",
                               (aadhaar, email))
                if cursor.fetchone():
                    flash("⚠️ Voter with this Aadhaar or Email exists", "warning")
                    os.remove(face_path)
                    if iris_filename:
                        os.remove(os.path.join(UPLOAD_IRIS, iris_filename))
                    return redirect(url_for("admin_voter_register"))

                # -------------------------
                # INSERT INTO DATABASE
                # -------------------------
                cursor.execute("""
                    INSERT INTO voters (name, aadhaar, phone, email, face_image, iris_image, verified, voted)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                """, (name, aadhaar, phone, email, face_filename, iris_filename, 0, 0))

                conn.commit()

                # Clear OTP after success
                session.pop('otp', None)
                session.pop('otp_email', None)
                session.pop('otp_verified', None)

                send_registration_email(email, name, aadhaar)
                flash("✅ Voter Registered Successfully!", "success")

            except Exception as e:
                traceback.print_exc()
                flash(f"❌ Registration Error: {e}", "danger")

            return redirect(url_for("admin_voter_register"))

        # ===========================
        # LIST VOTERS
        # ===========================
        search = request.args.get("search", "")
        cursor.execute("""
            SELECT * FROM voters
            WHERE name LIKE %s OR aadhaar LIKE %s OR phone LIKE %s
            ORDER BY id DESC
        """, (f"%{search}%", f"%{search}%", f"%{search}%"))

        voters = cursor.fetchall()
        return render_template("admin_voter_register.html", voters=voters, search=search)

    except Exception as e:
        flash(f"Database connection error: {e}", "danger")
        return render_template("admin_voter_register.html", voters=[], search="")

    finally:
        if cursor: cursor.close()
        if conn and conn.is_connected(): conn.close()

@app.route("/admin/register-candidate", methods=["GET","POST"])
def candidate_register():
    if 'admin' not in session: return redirect(url_for("admin_login"))
    
    conn = None # Initialize conn and cur
    cur = None
    
    try:
        conn=get_db(); cur=conn.cursor(dictionary=True)
        if request.method=="POST":
            action = request.form.get("action")
            if action=="add":
                name = request.form.get("c_name")
                party = request.form.get("c_party")
                symbol = request.form.get("c_symbol")
                cur.execute("INSERT INTO candidates (c_name,c_party,c_symbol) VALUES (%s,%s,%s)",(name,party,symbol))
                conn.commit(); flash(f"✅ Candidate '{name}' added!", "success")
            elif action=="delete":
                candidate_id = request.form.get("candidate_id")
                cur.execute("DELETE FROM candidates WHERE id=%s",(candidate_id,))
                conn.commit(); flash("🗑️ Candidate deleted!", "success")
        cur.execute("SELECT * FROM candidates"); candidates = cur.fetchall()
    except Exception as e: 
        flash(f"DB error: {e}", "danger"); candidates=[]
    finally: 
        if cur: cur.close()
        if conn and conn.is_connected(): conn.close()
        
    return render_template("candidate_register.html", candidates=candidates)

@app.route("/admin/vote-results")
def vote_results():
    if 'admin' not in session: return redirect(url_for('admin_login'))
    results=[]
    conn = None # Initialize conn and cur
    cur = None
    try:
        conn=get_db(); cur=conn.cursor(dictionary=True)
        cur.execute("""
            SELECT c.id, c.c_name, c.c_party, c.c_symbol, COUNT(v.voter_id) AS votes
            FROM candidates c
            LEFT JOIN votes v ON c.id = v.candidate_id
            GROUP BY c.id
            ORDER BY votes DESC, c.id ASC
        """); results = cur.fetchall()
        print(f"[VOTE RESULTS] Found {len(results)} candidates")
        for r in results:
            print(f"  {r['c_name']}: {r['votes']} votes")
    except Exception as e: 
        print(f"Vote query error: {e}")
        traceback.print_exc()
        flash(f"DB error: {e}", "danger")
    finally: 
        if cur: cur.close()
        if conn and conn.is_connected(): conn.close()
    return render_template("vote_results.html", results=results, is_admin=True)

@app.route("/manage_registration", methods=["GET", "POST"])
def manage_registration():
    if 'admin' not in session: return redirect(url_for('admin_login'))
    # Fetch voters and candidates from database
    conn = None
    cursor = None
    try:
        conn=get_db(); cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM voters")
        voters = cursor.fetchall()
        
        # Fetch candidates WITH vote counts
        cursor.execute("""
            SELECT c.id, c.c_name, c.c_party, c.c_symbol, COUNT(v.voter_id) AS vote_count
            FROM candidates c
            LEFT JOIN votes v ON c.id = v.candidate_id
            GROUP BY c.id
            ORDER BY c.id ASC
        """)
        candidates = cursor.fetchall()
        print(f"[MANAGE_REG] Fetched {len(candidates)} candidates")
        for c in candidates:
            print(f"  {c['c_name']}: {c['vote_count']} votes")
        
        # Handle POST actions (verify / delete)
        if request.method == "POST":
            voter_id = request.form.get("voter_id")
            action = request.form.get("action")

            if action == "verify":
                cursor.execute("UPDATE voters SET verified = 1 WHERE id = %s", (voter_id,))
                conn.commit()
                flash("✅ Voter verified successfully!", "success")

            elif action == "delete":
                cursor.execute("DELETE FROM voters WHERE id = %s", (voter_id,))
                conn.commit()
                flash("🗑️ Voter deleted successfully!", "danger")
            
            # Refetch voters after modification
            cursor.execute("SELECT * FROM voters")
            voters = cursor.fetchall()

    except Exception as e:
        print(f"[MANAGE_REG] Error: {e}")
        traceback.print_exc()
        flash(f"Database error: {e}", "danger")
        voters = []
        candidates = []
    finally:
        if cursor: cursor.close()
        if conn and conn.is_connected(): conn.close()

    return render_template("manage_registration.html", voters=voters, candidates=candidates, is_admin=True)

@app.route("/logout")
def logout():
    session.clear(); flash("✅ Logged out successfully","success")
    return redirect(url_for('home'))

# ---------------- VOTER ROUTES ----------------

def get_image_similarity(img1_path, img2_path):
    """Compare two images using ORB feature matching."""
    # Validate that both files exist
    if not os.path.exists(img1_path):
        print(f"[SIMILARITY] ❌ Image 1 not found: {img1_path}")
        return 0.0
    if not os.path.exists(img2_path):
        print(f"[SIMILARITY] ❌ Image 2 not found: {img2_path}")
        return 0.0
    
    img1 = cv2.imread(img1_path, cv2.IMREAD_GRAYSCALE)
    img2 = cv2.imread(img2_path, cv2.IMREAD_GRAYSCALE)
    
    if img1 is None:
        print(f"[SIMILARITY] ❌ Failed to read image 1: {img1_path}")
        return 0.0
    if img2 is None:
        print(f"[SIMILARITY] ❌ Failed to read image 2: {img2_path}")
        return 0.0

    # Resize images to common size
    img1 = cv2.resize(img1, (300, 300))
    img2 = cv2.resize(img2, (300, 300))

    # ORB feature detector (more robust than SSIM)
    orb = cv2.ORB_create()
    kp1, des1 = orb.detectAndCompute(img1, None)
    kp2, des2 = orb.detectAndCompute(img2, None)

    if des1 is None or des2 is None:
        print(f"[SIMILARITY] ⚠️ No descriptors found. kp1={len(kp1) if kp1 else 0}, kp2={len(kp2) if kp2 else 0}")
        return 0.0  # No match possible

    bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
    matches = bf.match(des1, des2)

    if not matches:
        print(f"[SIMILARITY] ⚠️ No matches found")
        return 0.0

    good_matches = [m for m in matches if m.distance < 50]
    score = len(good_matches) / max(len(matches), 1)



    print(f"[SIMILARITY] ✓ Matches: {len(good_matches)}/{len(matches)}, Score: {score:.3f}")
    return round(score, 2)  # Match score (0 to 1)


@app.route("/voter/verify", methods=["POST"])
def voter_verify():
    """Verify voter using facial and iris biometrics (strict: both must match, but with relaxed thresholds)."""
    temp_face = temp_iris = None
    conn = cur = None

    try:
        # 1️⃣ Get JSON Data from frontend
        data = request.get_json()
        face_b64 = data.get("face_image")
        iris_b64 = data.get("iris_image")

        if not face_b64 or not iris_b64:
            return jsonify({"status": "error", "message": "Missing face or iris data"}), 400

        # 2️⃣ Save temp images
        temp_face = save_base64_image(face_b64, TEMP_DIR, "live_face")
        temp_iris = save_base64_image(iris_b64, TEMP_DIR, "live_iris")

        if not temp_face or not temp_iris:
            return jsonify({"status": "error", "message": "Error saving captured images"}), 500

        print("\n[VERIFY] Temp face:", temp_face)
        print("[VERIFY] Temp iris:", temp_iris)

        # 3️⃣ DB Connection
        conn = get_db()
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT * FROM voters WHERE voted = 0")  # Only eligible voters (not yet voted)
        voters = cur.fetchall()

        print(f"[VERIFY] Found {len(voters)} voters with voted=0")

        matched_voter = None
        last_face_score = 0.0
        last_iris_score = 0.0

        # 4️⃣ Compare with each registered voter
        for voter in voters:
            f_path = voter.get("face_image")
            i_path = voter.get("iris_image")

            # --- Build absolute paths robustly ---
            # Handle all possible path formats stored in DB
            def resolve_biometric_path(stored_path, default_folder):
                if not stored_path:
                    return None
                # If path already has static/ or is absolute, use as-is (with Windows path sep)
                if stored_path.startswith("static/"):
                    return stored_path.replace("/", os.sep)
                elif stored_path.startswith("uploads/"):
                    return os.path.join("static", stored_path.replace("/", os.sep))
                elif os.path.isabs(stored_path):
                    return stored_path
                else:
                    # Assume it's just a filename, prepend default folder
                    return os.path.join(default_folder, stored_path)

            full_f_path = resolve_biometric_path(f_path, UPLOAD_FACE) if f_path else None
            full_i_path = resolve_biometric_path(i_path, UPLOAD_IRIS) if i_path else None

            print(f"[VERIFY] Checking voter id={voter['id']} face='{full_f_path}' iris='{full_i_path}'")

            # Only process paths that actually exist
            if full_f_path and not os.path.exists(full_f_path):
                print(f"[VERIFY] ⚠️ Face file not found: {full_f_path}")
                full_f_path = None
            if full_i_path and not os.path.exists(full_i_path):
                print(f"[VERIFY] ⚠️ Iris file not found: {full_i_path}")
                full_i_path = None
            if not full_f_path and not full_i_path:
                print(f"[VERIFY] ❌ No valid biometric files for voter {voter['id']}")
                continue

            # 5️⃣ Similarity scores (ORB-based)
            face_score = get_image_similarity(temp_face, full_f_path) if full_f_path else 0.0
            iris_score = get_image_similarity(temp_iris, full_i_path) if full_i_path else 0.0

            print(f"[VERIFY] → voter {voter['id']} face_score={face_score:.3f} iris_score={iris_score:.3f}")

            # Keep last scores for debug in response
            last_face_score = face_score
            last_iris_score = iris_score

            # 🔹 MATCHING LOGIC: At least one biometric must match
            # If only face exists, face score threshold is 0.05
            # If only iris exists, iris score threshold is 0.03
            # If both exist, either one matching with relaxed threshold counts as match
            face_match = full_f_path and (face_score >= 0.05)
            iris_match = full_i_path and (iris_score >= 0.03)

            print(f"[VERIFY] face_match={face_match} ({face_score:.3f} >= 0.05), iris_match={iris_match} ({iris_score:.3f} >= 0.03)")

            if face_match or iris_match:
                print(f"[VERIFY] ✅ MATCH: voter {voter['id']}")
                matched_voter = voter
                break

        # 6️⃣ No match found
        if not matched_voter:
            print("[VERIFY] ❌ No matching voter found with current thresholds.")
            return jsonify({
                "status": "error",
                "message": "Identity mismatch or you have already voted.",
                "face_score": round(last_face_score, 3),
                "iris_score": round(last_iris_score, 3)
            }), 401

        # 7️⃣ Mark as verified
        cur.execute("UPDATE voters SET verified = 1 WHERE id = %s", (matched_voter["id"],))
        conn.commit()

        # 8️⃣ Load Candidate List
        cur.execute("SELECT id, c_name, c_party FROM candidates")
        candidates = cur.fetchall()

        return jsonify({
            "status": "ok",
            "message": f"Voter {matched_voter['name']} verified successfully!",
            "voter_id": matched_voter["id"],
            "face_score": round(last_face_score, 3),
            "iris_score": round(last_iris_score, 3),
            "candidates": candidates
        })

    except Exception as e:
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500

    finally:
        # Cleanup temp images
        for file in [temp_face, temp_iris]:
            if file and os.path.exists(file):
                os.remove(file)

        if cur:
            cur.close()
        if conn and conn.is_connected():
            conn.close()

@app.route("/voter/vote", methods=["POST"])
def voter_vote():
    """Cast vote after verification"""
    # Client sends FormData, so we use request.form.get()
    voter_id = request.form.get("voter_id")
    candidate_id = request.form.get("candidate_id")

    if not voter_id or not candidate_id:
        return jsonify({"status": "error", "message": "Missing voter or candidate"}), 400

    conn = None # Initialize conn and cur
    cur = None
    try:
        conn = get_db()
        cur = conn.cursor()

        # Check if already voted (double check before casting)
        cur.execute("SELECT voted FROM voters WHERE id=%s", (voter_id,))
        result = cur.fetchone()
        if result and result[0] == 1:
            return jsonify({"status": "error", "message": "You have already voted."})

        # Record vote
        cur.execute("INSERT INTO votes (voter_id, candidate_id) VALUES (%s, %s)", (voter_id, candidate_id))
        cur.execute("UPDATE voters SET voted=1 WHERE id=%s", (voter_id,))
        conn.commit()

        return jsonify({"status": "ok", "message": "🎉 Vote recorded successfully! Thank you for voting."})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"status": "error", "message": f"Database error: {e}"}), 500
    finally:
        if cur: cur.close()
        if conn and conn.is_connected(): conn.close()
        
@app.route("/voter", methods=['GET'])
def voter_verification_page():
    # Only need to render the template for the initial page load
    # Candidates are fetched via the AJAX call after verification
    return render_template("voter_verification.html", is_admin=False)

# ---------------- IMAGE UPLOAD TEST ----------------
@app.route('/upload_image', methods=['POST'])
def upload_image():
    try:
        data = request.get_json()
        which = data.get('which')
        b64 = data.get('b64')
        if not b64:
            return jsonify({'status': 'error', 'message': 'No image data'}), 400
        folder = app.config['UPLOAD_FACE'] if which == 'face' else app.config['UPLOAD_IRIS']
        path = save_base64_image(b64, folder, prefix=which)
        return jsonify({'status': 'ok', 'path': path})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

    
# ---------------- RUN ----------------
if __name__ == "__main__":
    # Allow overriding via environment variables
    host = os.environ.get("FLASK_RUN_HOST", "0.0.0.0")
    port = int(os.environ.get("FLASK_RUN_PORT", 5000))

    # Try to determine a LAN-accessible IP address to show the URL
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # doesn't actually send packets
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
    except Exception:
        local_ip = "127.0.0.1"
    finally:
        s.close()

    print(f"\n* Flask app starting:\n  Local:   http://127.0.0.1:{port}/\n  Network: http://{local_ip}:{port}/\n")

    # Run the Flask app on the configured host and port
    app.run(host=host, port=port, debug=True)
