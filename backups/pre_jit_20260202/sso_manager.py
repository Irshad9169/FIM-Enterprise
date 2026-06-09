import os, time, logging, hashlib, urllib.parse, base64, re
from subprocess import Popen, PIPE
from typing import Optional

logger = logging.getLogger("sso_debug")

class SSOManager:
    def __init__(self):
        self.OPENSSL_BIN = '/usr/bin/openssl'
        self.SSO_SERVER_URL = 'https://auth.qa.int.untd.com/bin/sso'
        self.PUBLIC_KEY_PATH = '/opt/fim/config/sso-public.pem'
        self.APP_ID = 'FIM_ENTERPRISE' 

    def run_openssl_decrypt(self, data: bytes) -> Optional[bytes]:
        """Uses rsautl with -raw to see the entire decrypted block"""
        cmd = [self.OPENSSL_BIN, 'rsautl', '-verify', '-pubin', '-inkey', self.PUBLIC_KEY_PATH, '-raw']
        try:
            p = Popen(cmd, stdin=PIPE, stdout=PIPE, stderr=PIPE)
            stdout, stderr = p.communicate(input=data)
            if p.returncode != 0:
                logger.error(f"OpenSSL Error: {stderr.decode().strip()}")
                return None
            return stdout
        except Exception as e:
            logger.error(f"Subprocess crash: {e}")
            return None

    def verify_signature(self, data: str, signature_b64: str) -> bool:
        try:
            # 1. CLEAN THE BASE64 STRING
            # Remove URL encoding artifacts and whitespace
            clean_b64 = re.sub(r'[^A-Za-z0-9+/=]', '', signature_b64)
            
            # 2. DECODE BASE64
            decoded_sig = base64.b64decode(clean_b64)
            
            # 3. ENSURE 64-BYTE ALIGNMENT (For 512-bit RSA)
            if len(decoded_sig) > 64:
                decoded_sig = decoded_sig[:64]
            elif len(decoded_sig) < 64:
                logger.error(f"Sig too short: {len(decoded_sig)} bytes")
                return False

            # 4. DECRYPT (RAW MODE)
            decrypted_block = self.run_openssl_decrypt(decoded_sig)
            if not decrypted_block:
                return False

            # 5. CALCULATE LOCAL MD5
            expected_digest = hashlib.md5(data.encode('utf-8')).digest()
            
            # 6. SEARCH FOR DIGEST IN DECRYPTED BLOCK
            # This handles ASN.1 prefixes, Null padding, and unconventional alignments
            if expected_digest in decrypted_block:
                logger.info("SSO Signature Verified via Deep Search")
                return True
            else:
                logger.warning("SSO Signature Mismatch")
                logger.debug(f"Input Data: {data}")
                logger.debug(f"Expected Digest (Hex): {expected_digest.hex()}")
                logger.debug(f"Decrypted Block (Hex): {decrypted_block.hex()}")
                return False

        except Exception as e:
            logger.error(f"Verification process failed: {e}")
            return False

    def get_user_from_token(self, sso_token: str) -> Optional[str]:
        if not sso_token: return None
        try:
            # Decode URL twice just in case of double encoding
            token = urllib.parse.unquote(urllib.parse.unquote(sso_token)).strip()
            
            parts = token.split('|')
            if len(parts) < 4:
                logger.error(f"Format error. Parts: {len(parts)}")
                return None

            username, app_id, ts = parts[0], parts[1], parts[2]
            signature = "|".join(parts[3:]) 
            
            # Verify Application ID
            if app_id != self.APP_ID:
                logger.error(f"AppID mismatch: {app_id} != {self.APP_ID}")
                return None

            # Verify the signature
            data_to_verify = f"{username}|{app_id}|{ts}"
            if self.verify_signature(data_to_verify, signature):
                return username
                
        except Exception as e:
            logger.error(f"Token extraction failed: {e}")
            
        return None

    def get_login_url(self, redirect_url: str) -> str:
        params = {
            'origin_name': 'FIM Enterprise',
            'origin_url': redirect_url,
            'origin_id': self.APP_ID
        }
        return f"{self.SSO_SERVER_URL}?{urllib.parse.urlencode(params)}"
