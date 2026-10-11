# Documentation

This folder holds the repo's living documentation beyond the root `README.md`: deep dives and interactive diagrams.

## Layout

```
.documentation/
├── README.md        # this index
└── diagrams/        # interactive HTML diagrams (generated with the archify skill)
```

## Diagrams

| File | Type | Shows |
|------|------|-------|
| [`diagrams/event-flow.html`](diagrams/event-flow.html) | Workflow | How an inbound webhook is authenticated and routed to the stock or price sync branch, including reject and unsupported-event outcomes. |
| [`diagrams/stock-sync-sequence.html`](diagrams/stock-sync-sequence.html) | Sequence | End-to-end call order for a stock event: signature check, Holded availability lookup, and Wink `replace` update. |
| [`diagrams/module-dependencies.html`](diagrams/module-dependencies.html) | Architecture | Module-level dependency graph (`handler` → clients → `config`/`models`) of the Lambda package. |

Browse the interactive diagrams by opening the `.html` files above in a browser.
