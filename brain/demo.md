# Forkcast — Demo Script (3 min)

## Pre-demo checklist
- [ ] `docker compose up` clean; `GET /api/meta` returns backtest ρ and N.
- [ ] Three example chips parse from cache (no live LLM dependency for parse).
- [ ] Explain endpoint responds < 4 s on zone #1 of each example.
- [ ] Reverse-mode pin location chosen and tested.
- [ ] Browser zoom 110%, map centered on Oakland, 3 mi radius.

## Script
1. "Cheap Korean street food under $15 for college students, open late." Pin Oakland, 3 mi. Show heatmap. Click #1: student fit, late-night traffic, zero direct Korean competitors, White-Space bars.
2. Refine: "Turn this into premium Korean BBQ, $50/person, groups, parking." Map moves toward Shadyside / Downtown / suburban strips. Point at Cost and Parking sub-scores.
3. "Family steak & seafood, big dining room, parking, weekend dinners." Map shifts to suburban retail corridors.
4. Toggle Competition and Rent layers. Flip to reverse mode on a vacant storefront → top concepts.
5. Footer: "Backtested against N open Pittsburgh restaurants, ρ = 0.xx." One-line disclaimer.
