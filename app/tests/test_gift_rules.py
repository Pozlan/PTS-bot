"""Gift prices, fees and the /mog 'cost versus power' goal."""
from app.services.gift_rules import (
    M, TIER_PRICE, TIER_SCORE, LISTING_MIN_PRICE, GIFT_FEE,
    limited_score, item_score, sale_fee, seller_proceeds, min_cost_low_mid_to_beat,
)


def test_official_prices():
    assert TIER_PRICE == {"low": 10 * M, "mid": 20 * M, "high": 50 * M}


def test_listing_floor_equals_low_price():
    assert LISTING_MIN_PRICE == TIER_PRICE["low"]


def test_sale_fee_is_10_percent_from_seller():
    assert sale_fee(10 * M) == 1 * M
    assert seller_proceeds(10 * M) == 9 * M
    assert sale_fee(15_000_000) == 1_500_000
    assert seller_proceeds(15_000_000) == 13_500_000
    assert sale_fee(10 * M) + seller_proceeds(10 * M) == 10 * M


def test_gift_fee_is_2m():
    assert GIFT_FEE == 2 * M


def test_limited_score_uses_official_price():
    assert limited_score(150 * M) == 255
    assert limited_score(500 * M) == 850
    assert item_score(None, 150 * M) == 255
    assert item_score("high", 50 * M) == 100


def test_high_is_best_value_per_pts():
    per_m = {t: TIER_SCORE[t] / (TIER_PRICE[t] / M) for t in TIER_PRICE}
    assert per_m["high"] > per_m["mid"] > per_m["low"]


def test_low_mid_set_that_beats_high_costs_more_than_high():
    cost = min_cost_low_mid_to_beat(TIER_SCORE["high"])
    assert cost > TIER_PRICE["high"]


def test_low_mid_set_that_beats_any_limited_costs_more_than_that_limited():
    for price_m in range(100, 1001, 10):
        price = price_m * M
        assert min_cost_low_mid_to_beat(limited_score(price)) > price, price_m
