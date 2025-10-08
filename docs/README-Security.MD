README.MD

## 🔑 API Key Storage & Security

Chatti-Client never stores your OpenAI API key in plaintext.  
Instead, it uses **symmetric encryption** with a user-supplied *master password*:

1. **Encryption (first setup)**
   - You enter your OpenAI API key and choose a master password.
   - A random 16-byte **salt** is generated.
   - A 32-byte key is derived from (password + salt) using **PBKDF2-HMAC-SHA256** with 200k iterations.
   - With this key, the API key is encrypted via **Fernet (AES + HMAC)**.
   - The encrypted token and the base64-encoded salt are stored in `~/.config/chatti-cli/chatti-secrets.conf`.

2. **Decryption (normal run)**
   - You enter the same master password.
   - The stored salt is decoded and the same key is derived via PBKDF2.
   - Fernet verifies the integrity (HMAC) and decrypts the token back to the original API key.
   - If password or salt don’t match, Fernet raises `InvalidToken`.

3. **Why Base64?**
   - Both the salt and the ciphertext are binary data.
   - Base64 encoding makes them safe to store in text files.

4. **Why PBKDF2?**
   - Raw passwords are weak keys.
   - PBKDF2 strengthens them: 200,000 iterations make brute-force attacks costly.
   - Salt prevents rainbow table attacks and ensures that identical passwords yield different keys.

5. **Security model**
   - Anyone who steals your `chatti-secrets.conf` cannot decrypt it without your master password.
   - Your master password is never stored, only used to derive the decryption key at runtime.

---

⚠️ **Important:** If you forget your master password, there is no recovery.  
You must delete the secrets file and re-run setup with a new API key.
