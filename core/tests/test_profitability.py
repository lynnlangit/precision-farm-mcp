"""Phase 3 verification: computed profit matches ground truth for every
field/season not affected by an undetected-by-design defect, and the two
query functions v1 exists to answer classify the two known cases correctly.

One field/season (the transposed-digit defect) is deliberately excluded from
the exact-match check: profitability.py uses the farmer's own ledger figures
as recorded, discrepancies and all -- reconciliation (Phase 2) is what
surfaces that this one is wrong, not silent auto-correction here. Excluding
known defects, remaining differences are realistic currency-rounding noise
(prices and per-load bushels round to display precision in the raw files,
the same way a real settlement sheet would), never more than ~0.2% of
revenue.
"""

from farm_core import profitability

REVENUE_TOLERANCE_PCT = 0.005  # 0.5% -- generous margin above observed ~0.2% rounding noise


def _gt_lookup(ground_truth):
    lookup = {}
    for fid, seasons in ground_truth["profitability"].items():
        for season_str, rec in seasons.items():
            name = ground_truth["canonical_fields"][fid]["display_name_by_season"][season_str]
            lookup[(int(season_str), name)] = rec
    return lookup


def _known_defect_field_seasons(ground_truth):
    """(display_name, season) pairs where profitability.py is expected to
    diverge from ground truth because it doesn't auto-correct a detected
    defect -- currently just the transposed digit.
    """
    out = set()
    for d in ground_truth["defects"]:
        if d["type"] == "transposed_digit":
            name = ground_truth["canonical_fields"][d["field_id"]]["display_name_by_season"][
                str(d["season"])
            ]
            out.add((name, d["season"]))
    return out


def test_profit_matches_ground_truth_within_realistic_rounding(profit_records, ground_truth):
    gt = _gt_lookup(ground_truth)
    excluded = _known_defect_field_seasons(ground_truth)

    checked = 0
    for (_cid, season), rec in profit_records.items():
        if (rec.display_name, season) in excluded:
            continue
        gt_rec = gt.get((season, rec.display_name))
        assert gt_rec is not None, f"no ground truth for {rec.display_name} {season}"
        tolerance = max(50.0, abs(gt_rec["revenue"]) * REVENUE_TOLERANCE_PCT)
        assert abs(rec.profit - gt_rec["profit"]) < tolerance, (
            f"{rec.display_name} {season}: {rec.profit} vs {gt_rec['profit']}"
        )
        checked += 1

    assert checked > 100  # sanity: most of the 116 field-seasons were actually checked


def test_transposed_digit_field_season_diverges_as_expected(profit_records, ground_truth):
    """The one field/season we excluded above must actually still be present
    and computed -- it should differ substantially from ground truth,
    proving the exclusion isn't hiding a computation that never ran.
    """
    gt = _gt_lookup(ground_truth)
    excluded = _known_defect_field_seasons(ground_truth)
    assert excluded, "expected at least one transposed-digit defect in ground truth"

    for name, season in excluded:
        rec = next(
            r for (_cid, s), r in profit_records.items() if r.display_name == name and s == season
        )
        gt_rec = gt[(season, name)]
        assert abs(rec.profit - gt_rec["profit"]) > 500


def test_marginal_field_classified_as_bad_field(profit_records, ground_truth):
    marginal_name = ground_truth["canonical_fields"][ground_truth["marginal_field_id"]][
        "display_name_by_season"
    ]["2016"]
    canonical_id = next(
        r.canonical_id for r in profit_records.values() if r.display_name == marginal_name
    )
    verdict = profitability.bad_field_or_bad_year(profit_records, canonical_id)
    assert verdict["verdict"] == "bad_field"
    assert verdict["evidence"]["loss_rate"] >= 0.5


def test_catastrophic_field_classified_as_bad_year(profit_records, ground_truth):
    cat = ground_truth["catastrophic_year"]
    field_name = ground_truth["canonical_fields"][cat["field_id"]]["display_name_by_season"][
        str(cat["season"])
    ]
    canonical_id = next(
        r.canonical_id for r in profit_records.values() if r.display_name == field_name
    )
    verdict = profitability.bad_field_or_bad_year(profit_records, canonical_id)
    assert verdict["verdict"] == "bad_year"
    assert cat["season"] in verdict["evidence"]["outlier_seasons"]


def test_which_fields_made_money_ranks_marginal_field_last(profit_records, ground_truth):
    seasons = ground_truth["generator"]["seasons"]
    ranked = profitability.which_fields_made_money(profit_records, seasons)
    assert ranked[-1]["display_name"] == "Marginal Eighty"
    assert ranked[-1]["total_profit"] < 0
    assert ranked[0]["total_profit"] > ranked[-1]["total_profit"]


def test_which_fields_made_money_never_blends_across_a_split(profit_records, ground_truth):
    """South 160 split into North and South in 2020 -- a window spanning the
    split must report the parent and both children as separate lineages,
    never merge their acreage into one misleading total.
    """
    seasons = ground_truth["generator"]["seasons"]
    ranked = profitability.which_fields_made_money(profit_records, seasons)
    names = {r["display_name"] for r in ranked}
    assert "South 160" in names
    assert "South 160 North" in names
    assert "South 160 South" in names
