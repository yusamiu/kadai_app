from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization
import base64

# 安全な暗号化の鍵（VAPID用）を生成します
private_key = ec.generate_private_key(ec.SECP256R1())
public_key = private_key.public_key()

# 鍵データをWebプッシュ通知で使える文字の形式に変換します
private_bytes = private_key.private_numbers().private_value.to_bytes(32, byteorder='big')
public_bytes = public_key.public_bytes(
    encoding=serialization.Encoding.X962,
    format=serialization.PublicFormat.UncompressedPoint
)

def base64url_encode(b):
    return base64.urlsafe_b64encode(b).decode('utf-8').rstrip('=')

print("----- あなたの公開鍵 (HTML用) -----")
print(base64url_encode(public_bytes))

print("\n----- あなたの秘密鍵 (Python用) -----")
print(base64url_encode(private_bytes))