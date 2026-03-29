# Polymarket Operator Run

- Timestamp: 2026-03-29T18:32:14Z
- Dry run: False
- BTC price: 66406.32
- Decision action: CLOSE_POSITION
- Decision summary: Close the expired 66k dip Yes remainder on stop-loss and keep the active 67k reach Yes position.
- Validation: True (ok)
- Open positions before: 3
- Open positions after: 3

## Execution

```json
{
  "performed": true,
  "details": {
    "status": "skipped_market_resolved",
    "market_slug": "will-bitcoin-dip-to-66k-on-march-28",
    "reason": "PolyApiException[status_code=404, error_message={'error': 'No orderbook exists for the requested token id'}]"
  }
}
```
