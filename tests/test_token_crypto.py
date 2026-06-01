from app.token_crypto import EncryptedToken, KmsTokenCipher


class FakeKmsResponse:
    def __init__(self, *, ciphertext: bytes = b"ciphertext", plaintext: bytes = b"plaintext") -> None:
        self.ciphertext = ciphertext
        self.plaintext = plaintext


class FakeKmsClient:
    def __init__(self) -> None:
        self.encrypt_requests = []
        self.decrypt_requests = []

    def encrypt(self, *, request):
        self.encrypt_requests.append(request)
        return FakeKmsResponse(ciphertext=b"encrypted:" + request["plaintext"])

    def decrypt(self, *, request):
        self.decrypt_requests.append(request)
        return FakeKmsResponse(plaintext=b"decrypted-token")


def test_encrypt_uses_key_and_aad() -> None:
    client = FakeKmsClient()
    cipher = KmsTokenCipher(key_name="projects/p/locations/l/keyRings/r/cryptoKeys/k", client=client)

    encrypted = cipher.encrypt("secret-token", aad=b"aad")

    assert encrypted == EncryptedToken(
        ciphertext=b"encrypted:secret-token",
        kms_key_name="projects/p/locations/l/keyRings/r/cryptoKeys/k",
    )
    assert client.encrypt_requests == [
        {
            "name": "projects/p/locations/l/keyRings/r/cryptoKeys/k",
            "plaintext": b"secret-token",
            "additional_authenticated_data": b"aad",
        }
    ]


def test_decrypt_uses_stored_key_and_aad() -> None:
    client = FakeKmsClient()
    cipher = KmsTokenCipher(key_name="default-key", client=client)

    plaintext = cipher.decrypt(EncryptedToken(ciphertext=b"cipher", kms_key_name="stored-key"), aad=b"aad")

    assert plaintext == "decrypted-token"
    assert client.decrypt_requests == [
        {
            "name": "stored-key",
            "ciphertext": b"cipher",
            "additional_authenticated_data": b"aad",
        }
    ]


def test_decrypt_ciphertext_falls_back_to_default_key() -> None:
    client = FakeKmsClient()
    cipher = KmsTokenCipher(key_name="default-key", client=client)

    plaintext = cipher.decrypt_ciphertext(b"cipher", aad=b"aad")

    assert plaintext == "decrypted-token"
    assert client.decrypt_requests[0]["name"] == "default-key"
