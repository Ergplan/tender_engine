from tender.services.packs import Catalog
from tender.services.versioning import groups_for_role, plan_groups, touched_groups


def test_the_original_version_reads_each_document_for_the_groups_of_its_role(
    catalog: Catalog,
) -> None:
    fdre = catalog.get("fdre")
    rfs = plan_groups(fdre, version_no=1, role="rfs", page_texts=["anything"])
    assert rfs == [section.name for section in fdre.sections]
    assert plan_groups(fdre, version_no=1, role="ppa", page_texts=[""]) == [
        "commercial",
        "penalties",
    ]
    assert plan_groups(fdre, version_no=1, role="psa", page_texts=["tariff"]) == []
    epc = catalog.get("epc")
    assert plan_groups(epc, version_no=1, role="technical", page_texts=[""]) == ["epc_scope"]
    assert "epc_scope" in plan_groups(epc, version_no=1, role="contractual", page_texts=[""])


def test_an_amendment_may_touch_any_group_but_the_summary(catalog: Catalog) -> None:
    solar = catalog.get("solar")
    groups = groups_for_role(solar, "amendment")
    assert "summary" not in groups and len(groups) == len(solar.sections) - 1
    assert groups_for_role(solar, "clarification") == groups


def test_a_later_version_is_read_only_for_the_groups_its_text_touches(catalog: Catalog) -> None:
    solar = catalog.get("solar")
    text = ["AMENDMENT-01", "The last date of bid submission is extended to 15.04.2026."]
    assert plan_groups(solar, version_no=2, role="amendment", page_texts=text) == ["key_dates"]
    emd = ["Clause 16: the Earnest Money Deposit is revised to INR 10,00,000 per MW."]
    assert plan_groups(solar, version_no=2, role="amendment", page_texts=emd) == ["guarantees"]
    assert plan_groups(solar, version_no=3, role="amendment", page_texts=["Nothing here."]) == []


def test_a_later_document_of_another_role_is_limited_to_its_roles_groups(catalog: Catalog) -> None:
    epc = catalog.get("epc")
    drawing = ["Revised single line diagram. Scope of work unchanged. EMD as before."]
    assert plan_groups(epc, version_no=3, role="technical", page_texts=drawing) == ["epc_scope"]


def test_touched_groups_match_keywords_case_insensitively(catalog: Catalog) -> None:
    schema = catalog.get("wind").schema
    names = [group.name for group in schema.groups if group.name != "summary"]
    assert touched_groups(schema, names, ["PERFORMANCE BANK GUARANTEE shall be"]) == ["guarantees"]
    assert touched_groups(schema, ["key_dates"], ["performance bank guarantee"]) == []


def test_the_summary_is_written_from_the_base_documents_not_from_a_notice(
    catalog: Catalog,
) -> None:
    solar = catalog.get("solar")
    notice = ["Tender notice. Earnest money deposit and scope of work as per the RfS."]

    def planned(version_no: int, roles: list[str]) -> list[str]:
        return plan_groups(
            solar, version_no=version_no, role="nit", page_texts=notice, version_roles=roles
        )

    assert "summary" in planned(1, ["nit"]), "a tender known only by its notice"
    assert "summary" not in planned(1, ["rfs", "nit"]) and "key_dates" in planned(1, ["rfs", "nit"])
    assert "summary" not in planned(2, ["nit"])
    rfs = plan_groups(
        solar, version_no=1, role="rfs", page_texts=notice, version_roles=["rfs", "nit"]
    )
    assert "summary" in rfs
    revised = plan_groups(solar, version_no=2, role="rfs", page_texts=notice, version_roles=["rfs"])
    assert "summary" in revised, "a revised RfS in a later version is summarised again"
