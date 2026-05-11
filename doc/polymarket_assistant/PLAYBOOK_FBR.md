# Far Barrier Radar Playbook

This document contains non-binding review guidance for `far_dip_radar` and the future `far_barrier_radar` strategy family.

It is not the Beecthor thesis playbook. It should not force trades or ban trades by itself. The script remains responsible for hard filters such as allowed hours, generated candidates, stake limits, probability caps, cooldowns, market type, and exact candidate validation. The LLM uses this file only as a qualitative risk checklist before accepting or rejecting a generated candidate.

## Objective

Far Barrier Radar looks for daily BTC barriers that appear far enough away from current spot that the `No` side may be attractive.

The desired trade is not "predict the next BTC direction perfectly". The desired trade is "avoid a barrier that BTC is unlikely to touch before expiry, while the market still pays enough for that risk".

## Core Review

Before accepting a generated candidate, review:

- Weekly BTC behavior: has the last week been calm, directional, or unusually volatile?
- Last 48h behavior: is BTC drifting, trending, compressing, or expanding quickly?
- Current Polymarket day move: how far has BTC already moved since the 04:00 UTC board start?
- Distance to the candidate strike: is the barrier still meaningfully outside normal same-day displacement?
- Direction of recent candles: is BTC moving toward the barrier or away from it?
- Probability paid for the `No` side: is the compensation worth the remaining path risk?
- Time left to expiry: is there enough time for danger to develop, or has the day already proven its range?
- Nearby psychological levels: round numbers can attract late moves and liquidations.

## Direction Selection

Do not assume the correct side is always `No dip`.

For the current `far_dip_radar` implementation, only generated `No dip` candidates are valid. If the market regime makes lower barriers dangerous, return `NO_ACTION`.

For a future two-sided `far_barrier_radar`:

- Prefer `No dip` when BTC is bullish, grinding higher, or holding support cleanly.
- Prefer `No reach` when BTC is bearish, rejecting resistance, or losing support cleanly.
- In true lateral chop, compare both sides by distance, price, and volatility; if neither barrier is clearly safer, return `NO_ACTION`.
- Never choose a side only because it has worked recently. The current regime matters more than the last winning streak.

## Volatility Guidance

Elevated volatility is not an automatic ban, but it should raise the required margin of safety.

Prefer `NO_ACTION` when:

- Weekly volatility is clearly elevated versus recent context.
- BTC has already moved strongly toward the candidate barrier.
- The daily range is expanding instead of compressing.
- The candidate distance is only barely above the script minimum.
- The `No` probability is close to the maximum allowed cap.
- The market is reacting to macro news, exchange stress, ETF headlines, or unusually large candles.

Accepting a candidate during elevated volatility requires a stronger explanation: the barrier must be far, the price must compensate well, and recent structure must not be accelerating toward the strike.

## Same-Day Move Guidance

If BTC has already moved roughly `$1,000` or more from the 04:00 UTC board open in the same direction as the candidate barrier, be cautious. A second same-direction extension can happen, but the setup should not be treated as routine.

If BTC has already moved away from the candidate barrier and volatility is normal, the candidate may deserve more confidence.

## Probability Guidance

The script controls hard probability limits. The LLM should add judgment:

- Very cheap `No` can mean the barrier is genuinely dangerous.
- Very expensive `No` can mean the reward is too small.
- The sweet spot is a barrier that is statistically distant but not already priced as certain.
- Do not accept a candidate only because it passes the probability band.

## Acceptance Wording

When accepting or rejecting a candidate, the rationale should briefly mention:

- Weekly volatility regime.
- Last 48h structure.
- Distance to strike.
- Whether BTC is moving toward or away from the barrier.
- Why the offered probability is or is not worth the risk.

## Default Bias

The default answer is `NO_ACTION` unless the generated candidate remains attractive after this review.

Far Barrier Radar should feel boring, selective, and mechanical with a small layer of market awareness. If the LLM needs a heroic story to justify the trade, skip it.
