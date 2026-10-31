"""Set a user's password for the password sign-in, creating the user when new.

    docker compose exec -T api python -m scripts.set_password --username admin --role admin

Without --password a strong one is generated and printed once. The hash is stored; the
password is never written anywhere else.
"""

import argparse
import secrets
import sys

from core.config import Settings
from core.db import make_engine, make_session_factory
from core.models.identity import ROLES
from core.services.identity import IdentityError, IdentityService


def generated() -> str:
    return secrets.token_urlsafe(15)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--username", required=True)
    parser.add_argument("--role", choices=list(ROLES), default=None)
    parser.add_argument("--password", default=None, help="at least 12 characters; omit to generate")
    args = parser.parse_args(argv)
    settings = Settings()
    password = args.password or generated()
    factory = make_session_factory(make_engine(settings), settings.tenant_id)
    try:
        with factory() as session:
            user = IdentityService(settings).set_password(
                session, args.username, password, role=args.role, created_by="set_password"
            )
            role = user.role
    except IdentityError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    print(f"username: {args.username.strip().lower()}  role: {role}")
    if args.password is None:
        print(f"password: {password}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
