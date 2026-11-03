# EduPage Keyring

An MCP server that reads and acts on EduPage school accounts using a browser sign-in session kept in the operating system's protected secret store, never a password.

## Language

**Saved Session**:
The EduPage cookies from one browser sign-in, together with the EduPage account they belong to, stored for one school (and optionally one account label).
_Avoid_: Credentials, token, login

**Credential Store**:
The operating system's own protected secret store where Saved Sessions live: the macOS Keychain or Windows Credential Manager. Third-party password managers and file-based keyrings are not Credential Stores.
_Avoid_: Keychain (when meaning any platform), keyring, password manager, vault
