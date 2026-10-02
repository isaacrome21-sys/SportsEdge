import pytest

from sportsedge.run_it_market_intelligence import (
    BENCHMARK_HIERARCHY_ID,
    CONTEXT_HIERARCHY_ID,
    FROZEN_BENCHMARK_ORDER,
    POLICY_STATUS,
    POLICY_VERSION,
    RunItPolicyError,
    SourcedMarketRole,
    assert_footer_unchanged,
    stamp_run_it_row,
    validate_hierarchy_contract,
)

SHA = "a" * 40


def test_v2_row_is_partitionable_and_has_zero_authority():
    row = stamp_run_it_row({"game_id": "g1", "signal": "RLM_CANDIDATE"}, working_commit_sha=SHA)
    assert row["policy_version"] == POLICY_VERSION
    assert row["policy_status"] == "UNMERGED"
    assert row["policy_commit_sha"] == SHA
    assert row["context_hierarchy_id"] == CONTEXT_HIERARCHY_ID
    assert row["benchmark_hierarchy_id"] == BENCHMARK_HIERARCHY_ID
    assert row["model_p_authority"] is False
    assert row["truth_gate_authority"] is False
    assert row["promotion_authority"] is False
    assert row["official_authority"] is False


def test_unversioned_or_wrong_status_cannot_be_silently_stamped():
    with pytest.raises(RunItPolicyError, match="40-char"):
        stamp_run_it_row({}, working_commit_sha="short")
    with pytest.raises(RunItPolicyError, match="UNMERGED"):
        stamp_run_it_row({}, working_commit_sha=SHA, policy_status="MERGED")
    with pytest.raises(RunItPolicyError, match="override reserved"):
        stamp_run_it_row({"policy_version": "V1"}, working_commit_sha=SHA)


def test_context_hierarchy_cannot_collide_with_or_reorder_benchmark():
    validate_hierarchy_contract(
        context_hierarchy_id=CONTEXT_HIERARCHY_ID,
        benchmark_hierarchy_id=BENCHMARK_HIERARCHY_ID,
        benchmark_order=FROZEN_BENCHMARK_ORDER,
    )
    with pytest.raises(RunItPolicyError, match="distinct namespaces"):
        validate_hierarchy_contract(
            context_hierarchy_id=BENCHMARK_HIERARCHY_ID,
            benchmark_hierarchy_id=BENCHMARK_HIERARCHY_ID,
            benchmark_order=FROZEN_BENCHMARK_ORDER,
        )
    with pytest.raises(RunItPolicyError, match="reordered"):
        validate_hierarchy_contract(
            context_hierarchy_id=CONTEXT_HIERARCHY_ID,
            benchmark_hierarchy_id=BENCHMARK_HIERARCHY_ID,
            benchmark_order=tuple(reversed(FROZEN_BENCHMARK_ORDER)),
        )


def test_market_maker_label_requires_real_provenance():
    SourcedMarketRole("PINNACLE", "MARKET_MAKER", "source-registry-2026-09-13", "ROLE_V1", "2026-09-13T04:00:00Z").validate()
    with pytest.raises(RunItPolicyError, match="sourced"):
        SourcedMarketRole("PINNACLE", "MARKET_MAKER", "ASSERTED", "ROLE_V1", "2026-09-13T04:00:00Z").validate()
    with pytest.raises(RunItPolicyError, match="requires"):
        SourcedMarketRole("PINNACLE", "MARKET_MAKER", "", "ROLE_V1", "2026-09-13T04:00:00Z").validate()


def test_cfb_footer_cannot_drift_because_model_groundwork_exists():
    frozen = "frozen CFB RUN IT footer"
    assert_footer_unchanged(rendered_footer=frozen, frozen_footer=frozen)
    with pytest.raises(RunItPolicyError, match="footer drifted"):
        assert_footer_unchanged(rendered_footer="model-backed now", frozen_footer=frozen)
