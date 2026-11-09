import base64
import hashlib
import hmac
import os

SECRET_KEY = os.environ["HMAC_SECRET"].encode()

def generate_hmac(id_value: int) -> str:
    mac = hmac.new(SECRET_KEY, str(id_value).encode(), hashlib.sha256)
    return base64.urlsafe_b64encode(mac.digest())[:12].decode()

if __name__ == "__main__":
    user_id = int(input("Enter the ID provided by the locked workstation: "))
    print(f"The key to unlock the workstation is: {generate_hmac(user_id)}")
