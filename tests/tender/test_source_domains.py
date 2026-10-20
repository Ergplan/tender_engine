"""The source allowlist: the agency's own domain and its subdomains qualify, nothing else."""

from pathlib import Path

import pytest

from tender.services.source_domains import DEFAULT_PATH, SourceAllowlist, host_of


def test_the_committed_allowlist_names_the_agencies_and_the_regulator() -> None:
    allowlist = SourceAllowlist.load(DEFAULT_PATH)
    assert {"seci.co.in", "cercind.gov.in", "sjvn.nic.in", "ireda.in"} <= set(allowlist.domains)


def test_a_listed_domain_a_subdomain_and_http_qualify_an_unlisted_host_does_not() -> None:
    allowlist = SourceAllowlist(("seci.co.in", "cercind.gov.in"))
    assert allowlist.admissible("https://seci.co.in/tender-details/YQ")
    assert allowlist.admissible("https://www.seci.co.in/Upload/Bidder/637505570251415734.pdf")
    assert allowlist.admissible("http://cercind.gov.in/2025/orders/721-AT-2020.pdf")
    assert not allowlist.admissible("https://jmkresearch.com/seci-results.pdf")
    # A host that merely ends with the letters of a listed domain is not a subdomain of it.
    assert not allowlist.admissible("https://notseci.co.in/x.pdf")
    assert not allowlist.admissible("https://seci.co.in.evil.example/x.pdf")
    assert not allowlist.admissible("not a url")
    assert host_of("HTTPS://WWW.SECI.CO.IN:443/a") == "www.seci.co.in"


def test_hosts_lists_every_host_once_with_its_verdict() -> None:
    allowlist = SourceAllowlist(("seci.co.in",))
    verdicts = allowlist.hosts(
        ["https://www.seci.co.in/a.pdf", "https://www.seci.co.in/b.pdf", "https://mercom.example/c"]
    )
    assert verdicts == {"mercom.example": False, "www.seci.co.in": True}


def test_a_malformed_allowlist_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "domains.yaml"
    path.write_text("domains:\n  - https://seci.co.in/\n", encoding="utf-8")
    with pytest.raises(ValueError):
        SourceAllowlist.load(path)
    path.write_text("domains: []\n", encoding="utf-8")
    with pytest.raises(ValueError):
        SourceAllowlist.load(path)
