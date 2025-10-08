
# 🩺 Chatti Doctor – Quick Guide

The **Chatti Doctor** checks if your Chatti setup works correctly.  
Think of it as a medical check-up for your installation.

---

## 🔧 How to run

```bash
./chatti --doc
```

If you installed in a virtual environment:

```bash
(.venv) ./chatti --doc
```

---

## ✅ What it does

The Doctor checks step by step:

1. **Configuration files**  
   - Shows where your `chatti.conf` and secrets file are located.

2. **Secrets**  
   - Verifies that an encrypted API key and salt are stored.

3. **Cryptography**  
   - Confirms that the `cryptography` package is installed.

4. **Decryption**  
   - If a master password (`CHATTI_MASTER`) is set, tries to decrypt your key.  
   - If not set, gives instructions how to provide it.

5. **Client setup** (optional)  
   - Builds a client and runs a small "smoke test".  
   - Lists available models for your API key.

---

## 🗝️ Master Password

Normally you type your master password when you start Chatti.  
For automated checks, you can set it as an environment variable **just for one command**:

- **Linux/macOS**  
  ```bash
  CHATTI_MASTER="mypassword" ./chatti --doc
  ```

- **Windows PowerShell**  
  ```powershell
  $env:CHATTI_MASTER="mypassword"; .\chatti --doc
  ```

- **Windows CMD**  
  ```cmd
  set CHATTI_MASTER=mypassword && chatti --doc
  ```

---

## 🟢 Symbols

- ✅ = OK, all good  
- ⚠️ = Warning, something is missing but not fatal  
- ❌ = Error, you need to fix this  
- ℹ️ = Information or hint

---

## 🛠️ Typical fixes

- `❌ cryptography missing` → run `pip install cryptography`  
- `⚠️ Secrets file missing` → start Chatti normally (`./chatti`) and follow the setup  
- `⚠️ Decryption failed` → check your master password  

---

👉 After the Doctor runs, you will know **exactly what works** and **what needs fixing**.
