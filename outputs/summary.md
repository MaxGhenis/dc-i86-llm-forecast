# Pooled forecasts

8 independent forecaster runs, 20,000 Monte Carlo draws each (seed 0). Each column weights every forecaster's own conditional forecast equally, whatever that forecaster thinks the chance of passing is. Quantities show the mean and the 5th–95th percentile range; yes/no questions show a probability.

'Fails' and 'Passes' differ for two reasons: what passing does, and what the result says about voters. Their gap is not an effect. 'At 49.5%' and 'At 50.5%' fix the certified Yes share, with shared random numbers. Their difference, the cutoff effect, is the forecasters' estimate of what a bare pass changes; it does not show what passing does in a typical passing world. 'Per Yes ballot' averages, over forecasters, each one's cutoff effect times its chance that one ballot decides the measure, in the question's unit (a probability for yes/no questions). Forecasters who expect a close vote weigh more in it, so its sign can differ from the pooled cutoff effect. All are model forecasts under stated scenarios.

## The vote

- P(passes): 89.7%
- P(passes with 50–53%): 5.7%; P(fails with 47–50%): 4.1%
- Density of the Yes share at 50%: 1.62 per unit share
- Chance one ballot decides it: 1 in 250,398

| Run | Model | P(passes) | Mean Yes share | 1 ballot decides | Same at every cell | Same at 49.5% and 50.5% | Suspect calls | Prior context | Flags |
|---|---|---:|---:|---:|---:|---:|---:|---|---|
| opus-2 | claude-opus-5-5 | 91% | 62.5% | 1 in 258,537 | 6% | 0% | 0 | none |  |
| opus-3 | claude-opus-5-5 | 90% | 62.6% | 1 in 268,026 | 12% | 8% | 0 | none | recovered |
| opus-5 | claude-opus-5-5 | 87% | 59.8% | 1 in 195,314 | 6% | 0% | 0 | none | late |
| opus-7 | claude-opus-5-5 | 94% | 64.7% | 1 in 400,828 | 6% | 0% | 0 | none | late |
| sol-1 | gpt-6.1-sol | 89% | 62.1% | 1 in 225,336 | 12% | 15% | 0 | none |  |
| sol-2 | gpt-6.1-sol | 86% | 62.0% | 1 in 199,377 | 12% | 8% | 0 | none |  |
| sol-3 | gpt-6.1-sol | 90% | 63.7% | 1 in 257,432 | 12% | 15% | 0 | none |  |
| sol-4 | gpt-6.1-sol | 90% | 63.4% | 1 in 294,337 | 12% | 15% | 0 | none |  |

'Same at every cell' and 'Same at 49.5% and 50.5%' are the shares of a run's question-and-state groups whose answers are identical across cells; high values can mean copied answers. 'Suspect calls' counts tool calls the audit flagged for reading without excluding the run. 'Prior context' is what the forecaster reported seeing, before research, beyond the brief. 'late' runs were dispatched after other answers were in the repository; 'recovered' runs were reported lost by their supervisor, and their answer is the final message in the run's own transcript.

## Vote

| Question | Unit | Fails | Passes | Fails narrowly (47–50%) | Passes narrowly (50–53%) | At 49.5% | At 50.5% | Cutoff effect | Per Yes ballot | Effect by run |
|---|---|---|---|---|---|---|---|---|---|---|
| `turnout` Yes plus No votes on Initiative 86. | votes (Yes plus No) | 207,305 [160,504–259,518] | 207,317 [160,680–259,562] | 207,237 [160,463–259,752] | 207,525 [160,796–259,894] | 207,349 [160,708–259,759] | 207,349 [160,708–259,759] | +0.00 | – | opus-2 +0.00, opus-3 +0.00, opus-5 +0.00, opus-7 +0.00, sol-1 +0.00, sol-2 +0.00, sol-3 +0.00, sol-4 +0.00 |
| `denver_io311_passes` Denver Initiated Ordinance 311, Denver's 2026 foie gras sales ban measure, passes. | probability | 42% | 73% | 49% | 54% | 52% | 52% | +0.0 pts | – | opus-2 +0.0 pts, opus-3 +0.0 pts, opus-5 +0.0 pts, opus-7 +0.0 pts, sol-1 +0.0 pts, sol-2 +0.0 pts, sol-3 +0.0 pts, sol-4 +0.0 pts |

## If it passes

| Question | Unit | Fails | Passes | Fails narrowly (47–50%) | Passes narrowly (50–53%) | At 49.5% | At 50.5% | Cutoff effect | Per Yes ballot | Effect by run |
|---|---|---|---|---|---|---|---|---|---|---|
| `ban_status.repealed` The status of the sale ban on 2028-12-01: repealed | probability | n/a | 8% | n/a | 14% | n/a | 15% | +15.0 pts | +6.1e-07 | opus-2 +14.9 pts, opus-3 +11.6 pts, opus-5 +14.9 pts, opus-7 +13.7 pts, sol-1 +18.1 pts, sol-2 +16.4 pts, sol-3 +14.0 pts, sol-4 +16.8 pts |
| `ban_status.congress` The status of the sale ban on 2028-12-01: congress | probability | n/a | 7% | n/a | 8% | n/a | 8% | +8.0 pts | +3.3e-07 | opus-2 +7.9 pts, opus-3 +5.1 pts, opus-5 +4.9 pts, opus-7 +4.9 pts, sol-1 +10.0 pts, sol-2 +15.0 pts, sol-3 +8.2 pts, sol-4 +8.1 pts |
| `ban_status.court` The status of the sale ban on 2028-12-01: court | probability | n/a | 7% | n/a | 8% | n/a | 8% | +7.8 pts | +3.2e-07 | opus-2 +4.1 pts, opus-3 +4.0 pts, opus-5 +7.0 pts, opus-7 +5.0 pts, sol-1 +8.1 pts, sol-2 +10.7 pts, sol-3 +10.0 pts, sol-4 +13.0 pts |
| `ban_status.not_certified` The status of the sale ban on 2028-12-01: not_certified | probability | n/a | 22% | n/a | 25% | n/a | 25% | +24.8 pts | +9.8e-07 | opus-2 +32.6 pts, opus-3 +28.5 pts, opus-5 +30.1 pts, opus-7 +28.3 pts, sol-1 +23.8 pts, sol-2 +17.1 pts, sol-3 +18.3 pts, sol-4 +20.0 pts |
| `ban_status.certified` The status of the sale ban on 2028-12-01: certified | probability | n/a | 57% | n/a | 46% | n/a | 44% | +44.4 pts | +1.8e-06 | opus-2 +40.6 pts, opus-3 +50.8 pts, opus-5 +43.2 pts, opus-7 +48.2 pts, sol-1 +40.0 pts, sol-2 +40.7 pts, sol-3 +49.6 pts, sol-4 +42.2 pts |
| `ban_standing` The sale ban passed and is not repealed or blocked on 2028-12-01. | probability | 0% | 78% | 0% | 70% | 0% | 69% | +69.2 pts | +2.7e-06 | opus-2 +73.1 pts, opus-3 +79.3 pts, opus-5 +73.2 pts, opus-7 +76.5 pts, sol-1 +63.8 pts, sol-2 +57.8 pts, sol-3 +67.8 pts, sol-4 +62.1 pts |
| `ban_certified` The sale ban stands and the CFO has certified its fiscal effect by 2028-12-01. | probability | 0% | 57% | 0% | 46% | 0% | 44% | +44.4 pts | +1.8e-06 | opus-2 +40.6 pts, opus-3 +50.8 pts, opus-5 +43.2 pts, opus-7 +48.2 pts, sol-1 +40.0 pts, sol-2 +40.7 pts, sol-3 +49.6 pts, sol-4 +42.2 pts |
| `lawsuit_filed` A lawsuit challenging I-86 is filed between 2026-11-03 and 2028-12-01. | probability | n/a | 61% | n/a | 62% | n/a | 62% | +62.1 pts | +2.5e-06 | opus-2 +56.8 pts, opus-3 +47.6 pts, opus-5 +63.5 pts, opus-7 +52.4 pts, sol-1 +65.0 pts, sol-2 +68.8 pts, sol-3 +69.9 pts, sol-4 +73.0 pts |
| `fattened_narrowed` By 2028-12-01, 'fattened' is narrowed so liver from birds that were not force-fed is excluded. † | probability | n/a | 42% (joint 32%) | n/a | 40% (joint 28%) | n/a | 40% (joint 27%) | +26.9 pts | +1.1e-06 | opus-2 +20.8 pts, opus-3 +20.9 pts, opus-5 +20.4 pts, opus-7 +26.3 pts, sol-1 +32.6 pts, sol-2 +30.9 pts, sol-3 +33.0 pts, sol-4 +30.3 pts |
| `pate_treated_banned` By 2028-12-01, DOEE treats liver from birds that were not force-fed as covered. † | probability | n/a | 5% (joint 4%) | n/a | 5% (joint 3%) | n/a | 5% (joint 3%) | +3.1 pts | +1.2e-07 | opus-2 +2.5 pts, opus-3 +1.4 pts, opus-5 +2.3 pts, opus-7 +1.8 pts, sol-1 +2.8 pts, sol-2 +4.5 pts, sol-3 +3.4 pts, sol-4 +6.0 pts |

## Direct outcomes

| Question | Unit | Fails | Passes | Fails narrowly (47–50%) | Passes narrowly (50–53%) | At 49.5% | At 50.5% | Cutoff effect | Per Yes ballot | Effect by run |
|---|---|---|---|---|---|---|---|---|---|---|
| `foie_gras_menus` DC establishments listing foie gras on a current menu in December 2028. † | DC establishments | 42.6 [21–72] | 14.5 [0.00–54] | 42.5 [21–72] | 18.2 [0.00–58] | 42.5 [21–72] | 18.5 [0.00–58] | -23.99 | -9.5e-05 | opus-2 -16.49, opus-3 -28.53, opus-5 -19.39, opus-7 -24.34, sol-1 -26.17, sol-2 -23.89, sol-3 -25.60, sol-4 -27.48 |
| `liver_pate_menus` DC establishments listing a liver pate, mousse or terrine other than foie gras in December 2028. † | DC establishments | 103 [27–215] | 99.4 [25–207] | 103 [27–216] | 99.5 [25–209] | 102 [27–215] | 99.5 [26–208] | -2.95 | -1.1e-05 | opus-2 -7.62, opus-3 -6.14, opus-5 -4.42, opus-7 -6.35, sol-1 +1.58, sol-2 -2.38, sol-3 +1.73, sol-4 -0.04 |
| `us_ducks_force_fed_2030` Ducks and geese force-fed for foie gras in the United States in 2030. † | birds | 386,206 [134,147–799,991] | 376,440 [126,718–785,541] | 386,304 [135,135–797,318] | 377,927 [127,983–786,725] | 386,509 [134,768–798,352] | 378,624 [128,596–787,401] | -7,885 | -0.031 | opus-2 -7,028, opus-3 -7,542, opus-5 -8,715, opus-7 -9,456, sol-1 -8,999, sol-2 -3,229, sol-3 -14,849, sol-4 -3,265 |
| `dc_restaurant_employment_2029` DC food services and drinking places employment, 2029 annual average. † | thousands of jobs | 51.9 [44.1–60.5] | 51.9 [44.2–60.5] | 51.9 [44.2–60.4] | 51.9 [44.2–60.4] | 51.9 [44.2–60.4] | 51.9 [44.2–60.4] | -0.01 | -2.2e-08 | opus-2 -0.03, opus-3 -0.01, opus-5 -0.01, opus-7 +0.00, sol-1 +0.00, sol-2 +0.00, sol-3 +0.00, sol-4 +0.00 |
| `dc_restaurant_sales_tax_fy2029` DC sales tax collections on food and drink for immediate consumption, FY2029. † | millions of dollars | 631 [492–794] | 631 [492–793] | 631 [492–792] | 631 [493–792] | 631 [492–794] | 631 [492–794] | -0.12 | -4.5e-07 | opus-2 -0.41, opus-3 -0.10, opus-5 -0.11, opus-7 -0.06, sol-1 +0.00, sol-2 +0.00, sol-3 -0.25, sol-4 +0.00 |
| `dc_michelin_starred_2029` DC restaurants with one or more Michelin stars in the guide released in 2029. † | restaurants | 22.2 [14–30] | 22.2 [14–30] | 22.2 [14–30] | 22.1 [14–30] | 22.2 [14–30] | 22.2 [14–30] | -0.01 | -3.3e-08 | opus-2 +0.00, opus-3 +0.00, opus-5 +0.00, opus-7 -0.10, sol-1 +0.00, sol-2 +0.00, sol-3 +0.00, sol-4 +0.00 |

## Political spillovers

| Question | Unit | Fails | Passes | Fails narrowly (47–50%) | Passes narrowly (50–53%) | At 49.5% | At 50.5% | Cutoff effect | Per Yes ballot | Effect by run |
|---|---|---|---|---|---|---|---|---|---|---|
| `dc_animal_initiative_filed` A new DC initiative on farmed animals or animal products is filed between 2026-11-04 and 2028-12-31. | probability | 18% | 45% | 21% | 33% | 22% | 31% | +9.1 pts | +3.7e-07 | opus-2 +9.8 pts, opus-3 +7.7 pts, opus-5 +11.8 pts, opus-7 +7.9 pts, sol-1 +7.8 pts, sol-2 +12.0 pts, sol-3 +9.0 pts, sol-4 +6.7 pts |
| `dc_another_animal_law` DC enacts another law restricting farmed-animal treatment or animal-product sales by 2030-12-31. | probability | 17% | 37% | 19% | 26% | 20% | 25% | +5.5 pts | +2.3e-07 | opus-2 +4.0 pts, opus-3 +4.2 pts, opus-5 +4.1 pts, opus-7 +3.0 pts, sol-1 +7.5 pts, sol-2 +7.9 pts, sol-3 +7.5 pts, sol-4 +6.2 pts |
| `dc_council_farmed_animal_bills` DC Council bills on farmed animals introduced 2027-2030. | bills | 1.22 [0.00–4.00] | 2.19 [0.00–6.00] | 1.34 [0.00–4.00] | 1.62 [0.00–5.00] | 1.38 [0.00–4.00] | 1.57 [0.00–5.00] | +0.19 | +7.6e-07 | opus-2 +0.17, opus-3 +0.40, opus-5 +0.16, opus-7 +0.40, sol-1 +0.00, sol-2 +0.42, sol-3 +0.00, sol-4 +0.00 |
| `paf_measures_2027_2028` Pro-Animal Future ballot measures on 2027-2028 ballots. |  | 1.63 [0.00–4.00] | 2.31 [0.00–5.00] | 1.73 [0.00–4.00] | 1.99 [0.00–5.00] | 1.75 [0.00–4.00] | 1.95 [0.00–5.00] | +0.19 | +7.7e-07 | opus-2 +0.24, opus-3 +0.17, opus-5 +0.10, opus-7 +0.17, sol-1 +0.24, sol-2 +0.19, sol-3 +0.22, sol-4 +0.20 |
| `paf_statewide_2028` Pro-Animal Future qualifies a 2028 statewide measure on chickens, pigs, cattle or fish. | probability | 8% | 20% | 9% | 13% | 10% | 13% | +2.9 pts | +1.2e-07 | opus-2 +3.5 pts, opus-3 +1.5 pts, opus-5 +0.7 pts, opus-7 +1.5 pts, sol-1 +4.4 pts, sol-2 +4.6 pts, sol-3 +3.6 pts, sol-4 +3.6 pts |
| `us_new_coverage_2027_2032` US residents newly covered by farmed-animal laws enacted 2027-2032. | millions of US residents | 23.5 [0.14–85.1] | 30.0 [0.33–107] | 24.3 [0.17–87.8] | 25.9 [0.22–92.9] | 24.6 [0.17–88.6] | 25.7 [0.20–92.3] | +1.15 | +4.8e-06 | opus-2 +0.90, opus-3 +0.54, opus-5 +0.67, opus-7 +0.71, sol-1 +1.53, sol-2 +2.06, sol-3 +1.62, sol-4 +1.17 |
| `other_foie_gras_bans_2030` US states and localities other than DC with a foie gras sales ban in force on 2030-12-31. † | US states and localities | 5.40 [1.00–15] | 5.92 [1.00–16] | 5.39 [1.00–15] | 5.92 [1.00–16] | 5.39 [1.00–15] | 5.93 [1.00–16] | +0.53 | +2.1e-06 | opus-2 +0.40, opus-3 +0.17, opus-5 +0.15, opus-7 +0.42, sol-1 +0.79, sol-2 +0.78, sol-3 +0.78, sol-4 +0.79 |
| `federal_preemption_2030` Federal law preempts Prop 12-style sales standards by 2030-12-31. † | probability | 29% | 29% | 29% | 30% | 29% | 30% | +0.2 pts | +9e-09 | opus-2 +0.9 pts, opus-3 +0.0 pts, opus-5 +0.5 pts, opus-7 +0.5 pts, sol-1 +0.0 pts, sol-2 +0.0 pts, sol-3 +0.0 pts, sol-4 +0.0 pts |
| `dc_bans_other_food_2030` DC bans the sale of another food product by 2030-12-31. † | probability | 17% | 19% | 17% | 19% | 17% | 19% | +2.0 pts | +8.2e-08 | opus-2 +1.0 pts, opus-3 +1.0 pts, opus-5 +0.9 pts, opus-7 +1.0 pts, sol-1 +0.9 pts, sol-2 +4.3 pts, sol-3 +3.0 pts, sol-4 +4.1 pts |

For a question defined only under a condition (the measure passing, or the ban still standing), a cell shows the probability given that condition, and the joint probability P(condition and event) in parentheses where the two differ. The conditional is each forecaster's own, from draws restricted to worlds where the condition holds and weighted by that forecaster's probability of it, so every forecaster that gives the condition any probability counts equally. The cutoff effect and the per-ballot figure use the joint. 'n/a' marks conditions where the question is undefined; '(k of n runs)' marks a cell to which only k forecasters contribute. `certified` means the CFO's section 8(b) certification by 2028-12-01, not a legal finding about when the ban is enforceable.

† Asked only at a bare fail and a bare pass (49.5% and 50.5%). The Fails and Passes columns apply those answers at every failing and every passing margin. They still vary with the margin through upstream questions answered at every cell, such as the ban's status, but not through the question's own answers.

In count distributions the top label ('5+') counts as 5 in means. Quantity tails beyond the 5th and 95th percentiles continue the neighbouring segment's slope, so means of heavy right tails are understated.
