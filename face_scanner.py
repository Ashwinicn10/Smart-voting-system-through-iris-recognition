# face_scanner.py
import cv2
import os
from datetime import datetime

def scan_face():
    cap = cv2.VideoCapture(0)
    face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")

    verified = False
    face_path = None

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = face_cascade.detectMultiScale(gray, 1.3, 5)

        for (x, y, w, h) in faces:
            roi_face = frame[y:y+h, x:x+w]

            # Save face image
            folder = "static/uploads/faces"
            os.makedirs(folder, exist_ok=True)
            face_path = os.path.join(folder, f"face_{datetime.now().strftime('%Y%m%d%H%M%S')}.jpg")
            cv2.imwrite(face_path, roi_face)

            verified = True
            cap.release()
            cv2.destroyAllWindows()
            return verified, face_path

        cv2.imshow("Face Scan - Press Q to quit", frame)
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()
    return verified, face_path
