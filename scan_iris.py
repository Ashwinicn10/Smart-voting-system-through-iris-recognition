import cv2
import os

def scan_iris(save_path="static/uploads", filename="iris.jpg"):
    # Open webcam
    cap = cv2.VideoCapture(0)

    if not cap.isOpened():
        print("Error: Could not open webcam")
        return None

    while True:
        ret, frame = cap.read()
        if not ret:
            print("Failed to capture image")
            break

        # Show live webcam feed
        cv2.imshow("Iris Scanner - Press SPACE to Capture / ESC to Exit", frame)

        key = cv2.waitKey(1) & 0xFF  # Safer key capture

        # Press SPACE to capture iris
        if key == 32:  # Space key
            # Resize the frame to 400x400 (to zoom in & standardize)
            resized = cv2.resize(frame, (400, 400))

            # Ensure save directory exists
            os.makedirs(save_path, exist_ok=True)

            file_path = os.path.join(save_path, filename)

            # Save resized image with good quality
            cv2.imwrite(file_path, resized, [cv2.IMWRITE_JPEG_QUALITY, 90])

            print(f"[INFO] Iris captured and saved at {file_path}")
            cap.release()
            cv2.destroyAllWindows()
            return file_path

        # Press ESC to exit without saving
        elif key == 27:  # ESC key
            print("[INFO] Capture cancelled by user.")
            break

    cap.release()
    cv2.destroyAllWindows()
    return None
