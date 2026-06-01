from __future__ import annotations

from dataclasses import dataclass

from google.cloud import kms_v1


@dataclass(frozen=True)
class EncryptedToken:
    ciphertext: bytes
    kms_key_name: str
    aad_version: str = "v1"


class KmsTokenCipher:
    def __init__(self, *, key_name: str, client: kms_v1.KeyManagementServiceClient | None = None) -> None:
        if not key_name:
            raise ValueError("KMS key name is required")
        self.key_name = key_name
        self.client = client or kms_v1.KeyManagementServiceClient()

    def encrypt(self, plaintext: str, *, aad: bytes) -> EncryptedToken:
        response = self.client.encrypt(
            request={
                "name": self.key_name,
                "plaintext": plaintext.encode("utf-8"),
                "additional_authenticated_data": aad,
            }
        )
        return EncryptedToken(ciphertext=response.ciphertext, kms_key_name=self.key_name)

    def decrypt(self, encrypted_token: EncryptedToken, *, aad: bytes) -> str:
        response = self.client.decrypt(
            request={
                "name": encrypted_token.kms_key_name,
                "ciphertext": encrypted_token.ciphertext,
                "additional_authenticated_data": aad,
            }
        )
        return response.plaintext.decode("utf-8")
