"""Source admissibility (DECISIONS.md, 2026-10-07): only a publication on the procuring
agency's or the regulator's own domain may supply a value. The allowlist is the committed
file `infra/source-domains.yaml`; a subdomain of a listed domain qualifies, nothing else
does. The scheme is not the criterion: an http URL of a listed domain is admissible, since
several agencies still publish over plain http."""

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import yaml

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PATH = ROOT / "infra" / "source-domains.yaml"


def host_of(url: str) -> str:
    """The host of a URL, lower case, without a port. Empty for a URL without one."""
    host = urlparse(url.strip()).hostname or ""
    return host.lower().rstrip(".")


@dataclass(frozen=True)
class SourceAllowlist:
    domains: tuple[str, ...]

    @classmethod
    def load(cls, path: Path = DEFAULT_PATH) -> "SourceAllowlist":
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        domains = tuple(
            str(domain).strip().lower().rstrip(".") for domain in data.get("domains", [])
        )
        if not domains or any(not domain or "/" in domain for domain in domains):
            raise ValueError(f"{path}: `domains` must list bare domain names")
        return cls(domains)

    def admissible(self, url: str) -> bool:
        host = host_of(url)
        return bool(host) and any(
            host == domain or host.endswith(f".{domain}") for domain in self.domains
        )

    def hosts(self, urls: list[str]) -> dict[str, bool]:
        """Every distinct host among the URLs, with whether it is admissible."""
        return {
            host: self.admissible(f"https://{host}") for host in sorted({host_of(u) for u in urls})
        }
