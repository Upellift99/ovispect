"""CLI helper that prints a bcrypt hash of an interactively-entered password.

Usage::

    python -m ovispect.hash_password
    # or, if installed via pip:
    ovispect-hash-password

The output is meant to be pasted directly into the ``AUTH_PASSWORD_HASH``
environment variable.
"""

from __future__ import annotations

import getpass
import sys

import bcrypt

_MIN_LENGTH = 8
_BCRYPT_ROUNDS = 12


def main() -> int:
    try:
        password = getpass.getpass("Password: ")
        confirm = getpass.getpass("Confirm:  ")
    except (KeyboardInterrupt, EOFError):
        print("\nAborted.", file=sys.stderr)
        return 130

    if password != confirm:
        print("Passwords do not match.", file=sys.stderr)
        return 1
    if len(password) < _MIN_LENGTH:
        print(
            f"Password must be at least {_MIN_LENGTH} characters.",
            file=sys.stderr,
        )
        return 1

    hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=_BCRYPT_ROUNDS))
    print(hashed.decode("ascii"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
