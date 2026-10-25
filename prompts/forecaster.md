# Forecasting brief: DC Initiative 86 and what follows from it

You are one of several forecasters working independently on the same questions. Your forecasts will be
pooled with the others' and logged before the vote on 2026-11-03. Forecast with what is known as of
2026-10-25. Research the questions yourself with web search, reason from base rates and current facts, and
give your own numbers.

## Rules

1. Work from public sources and this brief. Polls, prediction markets, campaign filings and published
   analyses are all fair game. Do not read local files, other than this brief, on the machine you run on.
2. Every number is an absolute level in the unit stated (establishments, votes, dollars, jobs,
   probabilities), never a ratio or a change.
3. Each forecast is conditional on its scenario. A *cell* such as `yes_50.5` means: DCBOE certifies
   Initiative 86 with exactly that Yes share. Everything else about the world is whatever you think is
   consistent with that result, so a 72% win can imply stronger public support than a 50.5% win.
   The `yes_49.5` and `yes_50.5` cells differ almost only in whether the measure passed; the difference
   between them is your estimate of what a bare pass changes. Denver votes the same day, so DC's result
   cannot change Denver's: there the two cells should differ only by what one point of DC margin says.
4. A *state* such as `applies` conditions on other questions in this map, defined below. When a
   question has both, forecast it for every cell and state pair.
5. A question with states but no cells is forecast under each state only. For it, average over your own
   distribution of the Yes share within that state (and within any "defined only if" condition).
6. Questions marked "defined only if" are forecast assuming their condition holds.
7. Quantities take five quantiles (p05, p25, p50, p75, p95): your 5th percentile, quartiles, median and
   95th percentile. Quantiles must not decrease and must lie within the stated bounds.
8. `yes_share` takes your cumulative probability that the certified Yes share is at or below each grid
   value (`le_50` is P(Yes share <= 50%)). These must not decrease.
9. A distribution over counts (`pmf`) or over named options (`categorical`) takes a probability for each
   label or option; they must sum to 1.
10. Where a question has a `baseline`, report the current value you found with its date and source.
11. Keep each question's `reasoning` to a few sentences: the base rate, the main mechanism, and what
    moves the forecast across cells or states. List the URLs you relied on in `sources`.
12. Before you research, record in `forecaster.prior_context` anything in your context other than this
    brief (system prompt, memory, instructions, earlier conversation) that mentions Initiative 86, foie
    gras, or forecasts of these questions. Quote it, or write "none".

## Output

Your final message must be the completed template below as a single JSON object in one ```json fenced
block, with every null replaced. Put your model name in `forecaster.model` and a short summary of your
research in `research_summary`. Nothing after the block.

## The questions

The questions form a causal map. The vote sets the cells; what happens to the law if it passes feeds the menu, sales and employment outcomes; the vote and Denver's result feed the political spillovers. Read every question before forecasting any, so your answers cohere.

## Vote

### `yes_share`: Initiative 86's certified Yes share.

- Forecast: cumulative probabilities at `le_30`, `le_35`, `le_40`, `le_45`, `le_47`, `le_48`, `le_49`, `le_50`, `le_51`, `le_52`, `le_53`, `le_55`, `le_60`, `le_65`, `le_70`, `le_75`, `le_80`, `le_85`, `le_90`.
- Conditions: one forecast (`all`).
- Resolution: DCBOE certified results for the 2026-11-03 general election: Yes votes divided by Yes plus No votes on Initiative 86, excluding over- and under-votes. Source: electionresults.dcboe.org (the certified results CSV).

### `turnout`: Yes plus No votes on Initiative 86.

- Forecast: quantity in votes (Yes plus No), bounds [50000, 500000], a whole number; give p05, p25, p50, p75, p95.
- Conditions: one forecast (`all`).
- Resolution: DCBOE certified results, as for yes_share.

### `denver_io311_passes`: Denver Initiated Ordinance 311, Denver's 2026 foie gras sales ban measure, passes.

- Forecast: probability.
- Conditions: cells yes_42.0, yes_49.5, yes_50.5, yes_60.0, yes_72.0.
- Resolution: City and County of Denver certified results for the 2026-11-03 election.
- Note: Forecast at each DC cell so the two results can be correlated. Denver votes the same day, so DC's result cannot cause Denver's: the 49.5% and 50.5% cells should differ only by what one point of DC margin says about voters. The simulator interpolates this question across 50%.

## What happens to Initiative 86 if it passes

### `ban_status`: The status of the sale ban on 2028-12-01: the first of these options that holds.

- Forecast: probability for each option (they are exclusive and sum to 1).
- Conditions: cells yes_50.5, yes_60.0, yes_72.0.
  - `repealed`: A Council act in effect on 2028-12-01 repeals I-86 section 4(b) (the sale ban), or delays or suspends it so that it does not apply on that date.
  - `congress`: Not repealed, but an enacted federal law in effect on 2028-12-01 (an appropriations rider, or a joint resolution of disapproval under the Home Rule Act) bars DC from implementing or enforcing I-86.
  - `court`: Neither of those, but an injunction or judgment in effect on 2028-12-01 bars enforcement of section 4(b) as a whole. An order limited to some products or some sellers does not count.
  - `unfunded`: None of those, and by 2028-12-01 the CFO has not certified that I-86's fiscal effect is included in an approved budget and financial plan, so under section 8(a) its provisions with a fiscal effect do not yet apply.
  - `applies`: None of those, and the CFO has certified the fiscal effect's inclusion by 2028-12-01, so the sale ban applies.
- Defined only if `passes`.
- Resolution: The first option that holds on 2028-12-01. Sources: DC Council LIMS and the DC Register (Council acts, and the section 8(c) notice of the CFO's certification); Congress.gov; PACER and DC court records.
- Note: The options are exclusive and ordered: give each a probability, summing to 1.

### `ban_applies`: The sale ban applies on 2028-12-01.

- Computed, not forecast: true when `ban_status.applies`.

### `lawsuit_filed`: A lawsuit challenging I-86 is filed between 2026-11-03 and 2028-12-01.

- Forecast: probability.
- Conditions: cells yes_50.5, yes_60.0, yes_72.0.
- Defined only if `passes`.
- Resolution: Between 2026-11-03 and 2028-12-01, a complaint is filed in any court challenging I-86's validity, or seeking to bar its enforcement, in whole or in part. Sources: PACER; DC Superior Court records; news.

### `fattened_narrowed`: By 2028-12-01, 'fattened' is narrowed so liver from birds that were not force-fed is excluded.

- Forecast: probability.
- Conditions: one forecast (`all`).
- Defined only if `ban_applies`.
- Resolution: By 2028-12-01, a final DOEE rule published in the DC Register, or an enacted Council act, defines 'fattened' or 'fattened bird liver product' so that liver from birds that were not force-fed is excluded. Guidance, forms and FAQs do not count. Sources: DC Register; DC Council LIMS.

### `pate_treated_banned`: By 2028-12-01, DOEE treats liver from birds that were not force-fed as covered.

- Forecast: probability.
- Conditions: states `narrowed` = fattened_narrowed; `not_narrowed` = not fattened_narrowed.
- Defined only if `ban_applies`.
- Resolution: Between 2027-07-01 and 2028-12-01, DOEE issues at least one notice of violation, penalty or written determination that treats a liver product from birds that were not force-fed (for example chicken-liver pate) as a fattened bird liver product. Sources: the DOEE violations database required by I-86 section 5(a)(5); DC Register; court records.

## Direct outcomes

### `foie_gras_menus`: DC establishments listing foie gras on a current menu in December 2028.

- Forecast: quantity in DC establishments, bounds [0, 400], a whole number; give p05, p25, p50, p75, p95.
- Conditions: states `failed` = not passes; `removed` = passes and (ban_status.repealed or ban_status.congress or ban_status.court); `unfunded` = ban_status.unfunded; `applies` = ban_applies.
- Resolution: Menu check run 2028-12-01 to 2028-12-31: search Resy, OpenTable, Google Maps and Yelp for DC-address food service and retail establishments listing 'foie gras', and check each establishment on any 2026 list published by Pro-Animal DC or in the Colorado State University study of US cities. Count an establishment if its own current menu (its website, or a platform menu updated in the check window) offers foie gras or a dish containing it. Faux, vegan, plant-based and '-style' foie gras do not count. Baseline: the same count as of October 2026.
- Report a baseline (current value, date, source).

### `liver_pate_menus`: DC establishments listing a liver pate, mousse or terrine other than foie gras in December 2028.

- Forecast: quantity in DC establishments, bounds [0, 1000], a whole number; give p05, p25, p50, p75, p95.
- Conditions: states `failed` = not passes; `not_applied` = passes and not ban_applies; `applies_pate_allowed` = ban_applies and not pate_treated_banned; `applies_pate_banned` = ban_applies and pate_treated_banned.
- Resolution: The foie_gras_menus check, counting establishments whose own current menu lists liver pate, liver mousse, liver terrine, chopped liver or pate de foie that is not foie gras. Baseline: the same count as of October 2026.
- Report a baseline (current value, date, source).

### `us_ducks_force_fed_2030`: Ducks and geese force-fed for foie gras in the United States in 2030.

- Forecast: quantity in birds, bounds [0, 2e+06], a whole number; give p05, p25, p50, p75, p95.
- Conditions: states `failed` = not passes; `not_applied` = passes and not ban_applies; `applies` = ban_applies.
- Resolution: No official source: producers do not publish volumes. Logged and not scored.
- Report a baseline (current value, date, source).
- Not scored: no source can settle it, so it is logged as an anchor.

### `dc_restaurant_employment_2029`: DC food services and drinking places employment, 2029 annual average.

- Forecast: quantity in thousands of jobs, bounds [20, 90]; give p05, p25, p50, p75, p95.
- Conditions: states `failed` = not passes; `not_applied` = passes and not ban_applies; `applies` = ban_applies.
- Resolution: Mean of the twelve 2029 monthly values of BLS State and Metro Area employment series SMU11000007072200001 (all employees, food services and drinking places, District of Columbia, not seasonally adjusted, thousands), as published after the March 2030 benchmark. The September 2026 value was 51.5 (FRED, retrieved 2026-10-25).
- Report a baseline (current value, date, source).

### `dc_restaurant_sales_tax_fy2029`: DC sales tax collections on food and drink for immediate consumption, FY2029.

- Forecast: quantity in millions of dollars, bounds [200, 1500]; give p05, p25, p50, p75, p95.
- Conditions: states `failed` = not passes; `not_applied` = passes and not ban_applies; `applies` = ban_applies.
- Resolution: FY2029 (October 2028 to September 2029) collections in the sales tax category 'Food & Drink for Immediate Consumption' (10% rate), as reported by the DC CFO's Office of Revenue Analysis. FY2025 collections were $567.9 million (ORA, 'DC Restaurant Sector Lags Hotel and Other Retail in Post-pandemic Recovery', 2026-04-14, https://ora-cfo.dc.gov/node/1824291).
- Report a baseline (current value, date, source).

### `dc_michelin_starred_2029`: DC restaurants with one or more Michelin stars in the guide released in 2029.

- Forecast: quantity in restaurants, bounds [0, 60], a whole number; give p05, p25, p50, p75, p95.
- Conditions: states `failed` = not passes; `not_applied` = passes and not ban_applies; `applies` = ban_applies.
- Resolution: The Michelin Guide Washington, D.C. edition released in 2029.
- Report a baseline (current value, date, source).

## Political spillovers

### `dc_animal_initiative_filed`: A new DC animal-protection initiative is filed between 2026-11-04 and 2028-12-31.

- Forecast: probability.
- Conditions: cells yes_42.0, yes_49.5, yes_50.5, yes_60.0, yes_72.0.
- Resolution: Between 2026-11-04 and 2028-12-31, an initiative is filed with DCBOE that would add restrictions on the treatment, confinement, slaughter or sale of animals or animal products (fur included). Measures about force-feeding or fattened bird liver products, and measures that would repeal or relax animal-protection laws, do not count. Source: DCBOE initiative filings.

### `dc_another_animal_law`: DC enacts another law restricting farmed-animal treatment or animal-product sales by 2030-12-31.

- Forecast: probability.
- Conditions: cells yes_42.0, yes_49.5, yes_50.5, yes_60.0, yes_72.0 × states `filed` = dc_animal_initiative_filed; `not_filed` = not dc_animal_initiative_filed.
- Resolution: Between 2026-11-04 and 2030-12-31, a new DC law (a Council act that becomes law, or a voter initiative that takes effect) restricts the confinement, treatment or slaughter of farmed animals, or the sale of animals or animal products (fur included). Laws only about pets, cruelty to individual animals, wildlife, or force-feeding and fattened bird liver products (I-86 and amendments to it included) do not count. Sources: DC Council LIMS; DC Register; DCBOE certified results.

### `dc_council_farmed_animal_bills`: DC Council bills on farmed animals introduced 2027-2030.

- Forecast: quantity in bills, bounds [0, 40], a whole number; give p05, p25, p50, p75, p95.
- Conditions: cells yes_42.0, yes_49.5, yes_50.5, yes_60.0, yes_72.0.
- Resolution: Bills introduced 2027-01-01 to 2030-12-31 whose main subject is the treatment, confinement, slaughter or sale of farmed animals or their products (fur, pets and wildlife excluded). Bills whose main subject is I-86, force-feeding or fattened bird liver products (to amend, repeal, delay or fund I-86, for example) do not count. Source: DC Council LIMS.

### `paf_measures_2027_2028`: Pro-Animal Future ballot measures on 2027-2028 ballots.

- Forecast: probability for each of `0`, `1`, `2`, `3`, `4`, `5+`.
- Conditions: cells yes_42.0, yes_49.5, yes_50.5, yes_60.0, yes_72.0 × states `denver_pass` = denver_io311_passes; `denver_fail` = not denver_io311_passes.
- Resolution: Number of ballot measures sponsored by Pro-Animal Future or its affiliates (such as Pro-Animal DC) on any US ballot, local or statewide, with an election date in 2027 or 2028. DC measures about force-feeding or fattened bird liver products (a refiled or amended I-86) do not count. Sources: Ballotpedia; Pro-Animal Future announcements; local election offices.

### `paf_statewide_2028`: Pro-Animal Future qualifies a 2028 statewide measure on chickens, pigs, cattle or fish.

- Forecast: probability.
- Conditions: cells yes_42.0, yes_49.5, yes_50.5, yes_60.0, yes_72.0 × states `denver_pass` = denver_io311_passes; `denver_fail` = not denver_io311_passes.
- Resolution: A statewide ballot measure sponsored by Pro-Animal Future or an affiliate, restricting the confinement, slaughter or sale of chickens, pigs, cattle or fish or their products, is certified for a 2028 statewide ballot in any US state. Sources: Ballotpedia; secretary of state certifications.

### `us_new_coverage_2027_2032`: US residents newly covered by farmed-animal laws enacted 2027-2032.

- Forecast: quantity in millions of US residents, bounds [0, 340]; give p05, p25, p50, p75, p95.
- Conditions: cells yes_42.0, yes_49.5, yes_50.5, yes_60.0, yes_72.0 × states `statewide` = paf_statewide_2028; `no_statewide` = not paf_statewide_2028.
- Resolution: Residents (Census Bureau 2030 population estimates) of states and localities that enact, from 2027-01-01 to 2032-12-31, a new law setting confinement, slaughter or sales standards for farmed animals or their products, or banning foie gras sales; each person counted once. I-86 and Denver Initiated Ordinance 311 never count. A ballot measure is enacted on the date its result is certified. Sources: ASPCA and AWI state law trackers; state and local legislative records.

### `other_foie_gras_bans_2030`: US states and localities other than DC with a foie gras sales ban in force on 2030-12-31.

- Forecast: quantity in US states and localities, bounds [0, 100], a whole number; give p05, p25, p50, p75, p95.
- Conditions: cells yes_49.5, yes_50.5.
- Resolution: Count of US states, counties and cities other than DC with a law banning foie gras sales that is in force (not enjoined or repealed) on 2030-12-31. Baseline: the same count on 2026-10-25. Sources: state and local legislative records; PETA and Ballotpedia trackers as leads.
- Report a baseline (current value, date, source).

### `federal_preemption_2030`: Federal law preempts Prop 12-style sales standards by 2030-12-31.

- Forecast: probability.
- Conditions: cells yes_49.5, yes_50.5.
- Resolution: Between 2026-11-03 and 2030-12-31, a federal law is enacted that preempts state or local sales standards for farmed animal products of the California Proposition 12 type, in whole or for pork. Source: Congress.gov.

### `dc_bans_other_food_2030`: DC bans the sale of another food product by 2030-12-31.

- Forecast: probability.
- Conditions: cells yes_49.5, yes_50.5.
- Resolution: Between 2026-11-03 and 2030-12-31, DC enacts a law banning the sale, to all buyers, of a food or drink for human consumption defined by its content, an ingredient or additive (foods containing a named dye, for example), or how it was produced, other than fattened bird liver products. Age limits, licensing, packaging rules, school-only rules, alcohol, tobacco, cannabis and hemp products, temporary public-health orders and recalls do not count. Sources: DC Council LIMS; DC Register.

## Context: the measure

# Initiative Measure No. 86: Board of Elections formulation

The text below is the Board of Elections' formulation of February 3, 2026, as reproduced by the sponsor at
https://proanimaldc.org/prohibit-force-feeding-of-birds-act/ (retrieved 2026-10-24). The CFO's fiscal impact
statement is in `i86-fiscal-impact-statement.txt` (source:
https://dcboe.org/getmedia/8ed77952-835c-4a11-9fa2-2ad447d82643/Final-FIS-Initiative-Prohibiting-the-Force-Feeding-of-Birds-Act-of-2026.pdf).

Pursuant to D.C. Official Code § 1-1001.16(c), the following formulations of Initiative Measure No. 86 were prepared this 3rd day of February, 2026.

INITIATIVE MEASURE

NO. 86

SHORT TITLE

“Prohibiting Force-Feeding of Birds Act of 2026.”

SUMMARY STATEMENT

If enacted, this Initiative would:

(a) Prohibit any person from force-feeding a bird for the purpose of enlarging the bird’s liver beyond normal size;

(b) Ban the sale or distribution of any product resulting from force-feeding a bird, including foie gras;

(c) Define force-feeding as inserting a tube into the bird’s throat to deliver excessive feed;

(d) Provide for enforcement by the Department of Energy and Environment during routine food safety inspections;

(e) Provide for civil penalties.

LEGISLATIVE TEXT

BE IT ENACTED BY THE ELECTORS OF THE DISTRICT OF COLUMBIA, That this act maybe cited as the “Prohibiting Force-Feeding of Birds Act”

Sec. 2. Legislative intent.

The people of the District of Columbia hereby find and declare:

(1) That fattened bird liver products are ‘luxury’ food items produced from the diseased

and enlarged liver of a bird, typically a duck or goose, typically produced through systematically force-feeding the animal until their liver becomes diseased and expands up to ten times its natural size;

(2) That the method typically used to force-feed these birds for production of food items is inhumane and involves inserting a foot-long metal or plastic tube into the bird’s throat and administering excessive quantities of feed directly into the stomach, resulting in extreme pain and various health issues;

(3) That force-feeding induces liver disease in the birds, which is both painful and often fatal, causing the animals significant injury and illness, including bacterial and fungal infections, malnourishment, and/or lameness;(4) That veterinary professionals widely regard the typical practice of force-feeding birds for food product production as inhumane;

(5) That the intensive confinement of these birds for food product production exacerbates environmental degradation and climate change through the necessitation of substantial water and energy consumption and polluting our city’s air and waterways;

(6) That runoff from fattened bird liver production facilities contains high concentrations

of phosphorus and nitrogen, two of the most common forms of water pollution in the United States;

(7) That workers in fattened bird liver production facilities face occupational hazards, including exposure to respiratory irritants and zoonotic diseases, posing risks to worker health and public health; and

(8) That eliminating the production and sale of fattened bird liver products from the marketplace is in our city’s interest and authority to reduce animal cruelty, unsustainable environmental practices, and spread of zoonotic, and to uphold the District’s values of humane animal treatment, public health, and environmental stewardship.

Sec. 3. Definitions.

For the purposes of this act, the term:

(1) “Bird” means any species of poultry, including ducks, geese, chickens, turkeys, guineas, or squabs.

(2) “Director” means the duly appointed Director of the Department of Energy and Environment (“the Department”), or the lawfully designated subordinate of the Director of the Department acting under the orders of the Director of the Department.

(3) “Fattened bird liver product” means any food product or by-product made from the livers of birds fattened through any method or practice, including foie gras, pâtés, spreads, and processed meat products derived from such livers, regardless of marketing terminology.

(4) “Food service establishment” means any place offering prepared food to be consumed by customers on or off premises, including restaurants, cafeterias, pushcarts, stands, or vehicles.

(5) “Force-feeding” means any process, whether by hand or machine, by which a bird is caused to ingest more food than it would consume voluntarily, including the use of a tube or device inserted into the esophagus.

(6) “Person” means any individual, corporation, partnership, joint venture, trust, government agency, organization, or other entity.

(7) “Retail establishment” means any store, shop, sales outlet, farmers’ market, or other place that sells or offers for sale food products to the public.

(8) “Sell” or “sale” means any act of selling, trading, distributing, bartering, or transferring for monetary or nonmonetary consideration, occurring where the recipient takes physical possession of the item.

Sec. 4. Prohibited conduct.

(a) No person shall force-feed a bird, or hire or direct another person to force-feed a bird, for the purpose of enlarging the bird’s liver beyond its normal size. This subsection shall not apply to force-feeding directed by a licensed veterinarian solely for therapeutic purposes.

(b) No person, food service establishment, or retail establishment shall sell, offer for sale, distribute, or otherwise provide any fattened bird liver product within the District of Columbia, whether as a standalone item or as an ingredient in any product or dish.

(c) No person shall import, transport, or receive a fattened bird liver product into the District for sale, distribution, or any other commercial purpose, regardless of the jurisdiction where the product was produced or originated.

Sec. 5. Authority of Director.

(a) The Director is hereby authorized to administer and enforce the provisions of this Act.

Thereby, the Department:

(1) Is authorized to adopt procedures and forms to implement the provisions of this act;

(2) Shall ensure compliance with the provisions of this act during routine inspections of retail establishments;

(3) Shall also have the authority to issue subpoenas for records related to the purchase, storage, and sale of poultry products;

(4) Shall ensure members of the public are able to submit complaints notifying the Department of possible violations; and

(5) Shall maintain a publicly available online database of violations and penalties issued under this act, updated quarterly.

(b) The Director is authorized to adopt rules, procedures, and forms to implement the provisions of this act.

(c) The Director shall ensure compliance with this act during routine inspections of food service establishments and retail establishments.

Sec. 6. Enforcement and penalties.

(a) Any person or establishment that violates any provision of this act shall be subject to a civil penalty of not less than $1,000 and not more than $5,000 per violation. Each day a violation continues shall constitute a separate violation.

(b) Repeated violations within a 12-month period may result in suspension or revocation of the violator’s business license in accordance with applicable District law.

(c) In addition to civil penalties, the District may enforce this act through a civil action, including an action for injunctive relief.

Sec. 7. Severability.

If any provision of this act, or its application to any person or circumstance, is held invalid, the remainder of the act, and the application of its provisions to other persons or circumstances, shall not be affected.

Sec. 8. Applicability.

This act shall apply as of July 1, 2027; except that:

(a) The provisions of this act with any fiscal effect shall apply upon the date of inclusion of the fiscal effect in an approved budget and financial plan, if that date is later than July 1, 2027.

(b) The Chief Financial Officer shall certify the date of the inclusion of the fiscal effect in an approved budget and financial plan and provide notice to the Budget Director of the Council of the certification.

(c)(1) The Budget Director shall cause the notice of the certification to be published in the District of Columbia Register. (2) The date of publication of the notice of the certification shall not affect the applicability of this act.

Sec. 9. Effective Date.

This act shall take effect after a 30-day period of congressional review as provided in section 602(c)(1) of the District of Columbia Home Rule Act, approved December 24, 1973 (87 Stat. 813; D.C. Official Code § 1-206.02(c)(1)), and publication in the District of Columbia Register.


## Context: the CFO's fiscal impact statement

```text
Government of the District of Columbia
                            Office of the Chief Financial Officer


Glen Lee
Chief Financial Officer




MEMORANDUM

TO:                        The Honorable Phil Mendelson
                           Chairman, Council of the District of Columbia

FROM:                      Glen Lee
                           Chief Financial Officer

DATE:                      January 21, 2026

SUBJECT:                   Fiscal Impact Statement – Prohibiting the Force-Feeding of Birds Act of
                           2026

REFERENCE:                 Initiative Measure No. 86 as provided to the Office of Revenue Analysis
                           on January 16, 2026


Conclusion

Funds are not sufficient in the fiscal year 2026 through fiscal year 2029 budget and financial plan to
implement the proposed initiative. The initiative’s implementation will cost $314,000 over the four-
year financial plan period. The initiative’s implementation is subject to the inclusion of these costs in
an approved budget and financial plan.

Background

The proposed initiative prohibits the artificial fattening of a bird’s liver and the importation,
distribution, sale, offer for sale, or receipt of any fattened bird liver product in the District of
Columbia. The initiative directs the Department of Energy and Environment (DOEE) to ensure
compliance with the prohibition. Under the initiative, DOEE can subpoena any relevant records,
receive complaints, and issue civil violations. The initiative establishes a civil penalty of between
$1,000 and $5,000 per day for a discovered violation and authorizes DOEE to direct the suspension
or revocation of a business’ operating license for repeat violations in a twelve-month period. The
prohibition begins July 1, 2027.

Financial Plan Impact

Funds are not sufficient in the fiscal year 2026 through fiscal year 2029 budget and financial plan to
implement the proposed initiative. DOEE has experience inspecting food service businesses and
retail establishments under existing non-food product bans such as Styrofoam containers, straws,

              1350 Pennsylvania Avenue, NW, Suite 203, Washington, DC 20004 (202)727-2476
                                            www.cfo.dc.gov
The Honorable Phil Mendelson
FIS: “Prohibiting the Force-Feeding of Birds Act of 2026,” Initiative Measure No. 86 as provided to the Office
of Revenue Analysis on January 16, 2026

and plastic shopping bags. The initiative is expected to expand the number and type of
establishments that DOEE must inspect. DOEE must also publicize the law and educate relevant
businesses on the prohibition. DOEE does not currently and is unlikely to inspect kitchen or other
back-of-house operations at any establishment under the initiative. As it does with other prohibited
activities, DOEE will also work with the Department of Health (DOH) to get referrals of potential
violations. DOEE requires an additional food establishment inspector to receive and investigate
complaints, proactively inspect new establishments, coordinate with DOH and other external
entities, and issue and adjudicate violations beginning in fiscal year 2027. The inspector will cost
$89,000 in fiscal year 2027 and $274,000 over the four-year financial plan period. DOEE will also
need to educate businesses and the public on the prohibition before the prohibition is effectuated.
This will cost $20,000 in fiscal year 2027 and $10,000 each year thereafter.

                          Initiative Prohibiting the Force-Feeding of Birds
                                        Implementation Costs
                                 Fiscal Year 2026 – Fiscal Year 2029
                       FY 2026         FY 2027         FY 2028        FY 2029                      Total
 Staff                         $0         $89,000         $91,000        $94,000                    $274,000
 Education                     $0         $20,000         $10,000        $10,000                     $40,000
 Total                         $0       $109,000        $101,000       $104,000                    $314,000

The Office of Revenue Analysis is not aware of any bird farms or bird feeding operations in the District
and has not included any potential costs related to the inspection or enforcement of live animal
establishments.




                                                                                                   Page 2 of 2
```

## Response template

```json
{
 "forecaster": {
  "model": null,
  "prior_context": null,
  "notes": null
 },
 "research_summary": null,
 "nodes": {
  "yes_share": {
   "forecasts": {
    "all": {
     "le_30": null,
     "le_35": null,
     "le_40": null,
     "le_45": null,
     "le_47": null,
     "le_48": null,
     "le_49": null,
     "le_50": null,
     "le_51": null,
     "le_52": null,
     "le_53": null,
     "le_55": null,
     "le_60": null,
     "le_65": null,
     "le_70": null,
     "le_75": null,
     "le_80": null,
     "le_85": null,
     "le_90": null
    }
   },
   "reasoning": null,
   "sources": []
  },
  "turnout": {
   "forecasts": {
    "all": {
     "p05": null,
     "p25": null,
     "p50": null,
     "p75": null,
     "p95": null
    }
   },
   "reasoning": null,
   "sources": []
  },
  "denver_io311_passes": {
   "forecasts": {
    "yes_42.0": {
     "p": null
    },
    "yes_49.5": {
     "p": null
    },
    "yes_50.5": {
     "p": null
    },
    "yes_60.0": {
     "p": null
    },
    "yes_72.0": {
     "p": null
    }
   },
   "reasoning": null,
   "sources": []
  },
  "ban_status": {
   "forecasts": {
    "yes_50.5": {
     "repealed": null,
     "congress": null,
     "court": null,
     "unfunded": null,
     "applies": null
    },
    "yes_60.0": {
     "repealed": null,
     "congress": null,
     "court": null,
     "unfunded": null,
     "applies": null
    },
    "yes_72.0": {
     "repealed": null,
     "congress": null,
     "court": null,
     "unfunded": null,
     "applies": null
    }
   },
   "reasoning": null,
   "sources": []
  },
  "lawsuit_filed": {
   "forecasts": {
    "yes_50.5": {
     "p": null
    },
    "yes_60.0": {
     "p": null
    },
    "yes_72.0": {
     "p": null
    }
   },
   "reasoning": null,
   "sources": []
  },
  "fattened_narrowed": {
   "forecasts": {
    "all": {
     "p": null
    }
   },
   "reasoning": null,
   "sources": []
  },
  "pate_treated_banned": {
   "forecasts": {
    "narrowed": {
     "p": null
    },
    "not_narrowed": {
     "p": null
    }
   },
   "reasoning": null,
   "sources": []
  },
  "foie_gras_menus": {
   "baseline": {
    "value": null,
    "as_of": null,
    "source": null
   },
   "forecasts": {
    "failed": {
     "p05": null,
     "p25": null,
     "p50": null,
     "p75": null,
     "p95": null
    },
    "removed": {
     "p05": null,
     "p25": null,
     "p50": null,
     "p75": null,
     "p95": null
    },
    "unfunded": {
     "p05": null,
     "p25": null,
     "p50": null,
     "p75": null,
     "p95": null
    },
    "applies": {
     "p05": null,
     "p25": null,
     "p50": null,
     "p75": null,
     "p95": null
    }
   },
   "reasoning": null,
   "sources": []
  },
  "liver_pate_menus": {
   "baseline": {
    "value": null,
    "as_of": null,
    "source": null
   },
   "forecasts": {
    "failed": {
     "p05": null,
     "p25": null,
     "p50": null,
     "p75": null,
     "p95": null
    },
    "not_applied": {
     "p05": null,
     "p25": null,
     "p50": null,
     "p75": null,
     "p95": null
    },
    "applies_pate_allowed": {
     "p05": null,
     "p25": null,
     "p50": null,
     "p75": null,
     "p95": null
    },
    "applies_pate_banned": {
     "p05": null,
     "p25": null,
     "p50": null,
     "p75": null,
     "p95": null
    }
   },
   "reasoning": null,
   "sources": []
  },
  "us_ducks_force_fed_2030": {
   "baseline": {
    "value": null,
    "as_of": null,
    "source": null
   },
   "forecasts": {
    "failed": {
     "p05": null,
     "p25": null,
     "p50": null,
     "p75": null,
     "p95": null
    },
    "not_applied": {
     "p05": null,
     "p25": null,
     "p50": null,
     "p75": null,
     "p95": null
    },
    "applies": {
     "p05": null,
     "p25": null,
     "p50": null,
     "p75": null,
     "p95": null
    }
   },
   "reasoning": null,
   "sources": []
  },
  "dc_restaurant_employment_2029": {
   "baseline": {
    "value": null,
    "as_of": null,
    "source": null
   },
   "forecasts": {
    "failed": {
     "p05": null,
     "p25": null,
     "p50": null,
     "p75": null,
     "p95": null
    },
    "not_applied": {
     "p05": null,
     "p25": null,
     "p50": null,
     "p75": null,
     "p95": null
    },
    "applies": {
     "p05": null,
     "p25": null,
     "p50": null,
     "p75": null,
     "p95": null
    }
   },
   "reasoning": null,
   "sources": []
  },
  "dc_restaurant_sales_tax_fy2029": {
   "baseline": {
    "value": null,
    "as_of": null,
    "source": null
   },
   "forecasts": {
    "failed": {
     "p05": null,
     "p25": null,
     "p50": null,
     "p75": null,
     "p95": null
    },
    "not_applied": {
     "p05": null,
     "p25": null,
     "p50": null,
     "p75": null,
     "p95": null
    },
    "applies": {
     "p05": null,
     "p25": null,
     "p50": null,
     "p75": null,
     "p95": null
    }
   },
   "reasoning": null,
   "sources": []
  },
  "dc_michelin_starred_2029": {
   "baseline": {
    "value": null,
    "as_of": null,
    "source": null
   },
   "forecasts": {
    "failed": {
     "p05": null,
     "p25": null,
     "p50": null,
     "p75": null,
     "p95": null
    },
    "not_applied": {
     "p05": null,
     "p25": null,
     "p50": null,
     "p75": null,
     "p95": null
    },
    "applies": {
     "p05": null,
     "p25": null,
     "p50": null,
     "p75": null,
     "p95": null
    }
   },
   "reasoning": null,
   "sources": []
  },
  "dc_animal_initiative_filed": {
   "forecasts": {
    "yes_42.0": {
     "p": null
    },
    "yes_49.5": {
     "p": null
    },
    "yes_50.5": {
     "p": null
    },
    "yes_60.0": {
     "p": null
    },
    "yes_72.0": {
     "p": null
    }
   },
   "reasoning": null,
   "sources": []
  },
  "dc_another_animal_law": {
   "forecasts": {
    "yes_42.0|filed": {
     "p": null
    },
    "yes_42.0|not_filed": {
     "p": null
    },
    "yes_49.5|filed": {
     "p": null
    },
    "yes_49.5|not_filed": {
     "p": null
    },
    "yes_50.5|filed": {
     "p": null
    },
    "yes_50.5|not_filed": {
     "p": null
    },
    "yes_60.0|filed": {
     "p": null
    },
    "yes_60.0|not_filed": {
     "p": null
    },
    "yes_72.0|filed": {
     "p": null
    },
    "yes_72.0|not_filed": {
     "p": null
    }
   },
   "reasoning": null,
   "sources": []
  },
  "dc_council_farmed_animal_bills": {
   "forecasts": {
    "yes_42.0": {
     "p05": null,
     "p25": null,
     "p50": null,
     "p75": null,
     "p95": null
    },
    "yes_49.5": {
     "p05": null,
     "p25": null,
     "p50": null,
     "p75": null,
     "p95": null
    },
    "yes_50.5": {
     "p05": null,
     "p25": null,
     "p50": null,
     "p75": null,
     "p95": null
    },
    "yes_60.0": {
     "p05": null,
     "p25": null,
     "p50": null,
     "p75": null,
     "p95": null
    },
    "yes_72.0": {
     "p05": null,
     "p25": null,
     "p50": null,
     "p75": null,
     "p95": null
    }
   },
   "reasoning": null,
   "sources": []
  },
  "paf_measures_2027_2028": {
   "forecasts": {
    "yes_42.0|denver_pass": {
     "0": null,
     "1": null,
     "2": null,
     "3": null,
     "4": null,
     "5+": null
    },
    "yes_42.0|denver_fail": {
     "0": null,
     "1": null,
     "2": null,
     "3": null,
     "4": null,
     "5+": null
    },
    "yes_49.5|denver_pass": {
     "0": null,
     "1": null,
     "2": null,
     "3": null,
     "4": null,
     "5+": null
    },
    "yes_49.5|denver_fail": {
     "0": null,
     "1": null,
     "2": null,
     "3": null,
     "4": null,
     "5+": null
    },
    "yes_50.5|denver_pass": {
     "0": null,
     "1": null,
     "2": null,
     "3": null,
     "4": null,
     "5+": null
    },
    "yes_50.5|denver_fail": {
     "0": null,
     "1": null,
     "2": null,
     "3": null,
     "4": null,
     "5+": null
    },
    "yes_60.0|denver_pass": {
     "0": null,
     "1": null,
     "2": null,
     "3": null,
     "4": null,
     "5+": null
    },
    "yes_60.0|denver_fail": {
     "0": null,
     "1": null,
     "2": null,
     "3": null,
     "4": null,
     "5+": null
    },
    "yes_72.0|denver_pass": {
     "0": null,
     "1": null,
     "2": null,
     "3": null,
     "4": null,
     "5+": null
    },
    "yes_72.0|denver_fail": {
     "0": null,
     "1": null,
     "2": null,
     "3": null,
     "4": null,
     "5+": null
    }
   },
   "reasoning": null,
   "sources": []
  },
  "paf_statewide_2028": {
   "forecasts": {
    "yes_42.0|denver_pass": {
     "p": null
    },
    "yes_42.0|denver_fail": {
     "p": null
    },
    "yes_49.5|denver_pass": {
     "p": null
    },
    "yes_49.5|denver_fail": {
     "p": null
    },
    "yes_50.5|denver_pass": {
     "p": null
    },
    "yes_50.5|denver_fail": {
     "p": null
    },
    "yes_60.0|denver_pass": {
     "p": null
    },
    "yes_60.0|denver_fail": {
     "p": null
    },
    "yes_72.0|denver_pass": {
     "p": null
    },
    "yes_72.0|denver_fail": {
     "p": null
    }
   },
   "reasoning": null,
   "sources": []
  },
  "us_new_coverage_2027_2032": {
   "forecasts": {
    "yes_42.0|statewide": {
     "p05": null,
     "p25": null,
     "p50": null,
     "p75": null,
     "p95": null
    },
    "yes_42.0|no_statewide": {
     "p05": null,
     "p25": null,
     "p50": null,
     "p75": null,
     "p95": null
    },
    "yes_49.5|statewide": {
     "p05": null,
     "p25": null,
     "p50": null,
     "p75": null,
     "p95": null
    },
    "yes_49.5|no_statewide": {
     "p05": null,
     "p25": null,
     "p50": null,
     "p75": null,
     "p95": null
    },
    "yes_50.5|statewide": {
     "p05": null,
     "p25": null,
     "p50": null,
     "p75": null,
     "p95": null
    },
    "yes_50.5|no_statewide": {
     "p05": null,
     "p25": null,
     "p50": null,
     "p75": null,
     "p95": null
    },
    "yes_60.0|statewide": {
     "p05": null,
     "p25": null,
     "p50": null,
     "p75": null,
     "p95": null
    },
    "yes_60.0|no_statewide": {
     "p05": null,
     "p25": null,
     "p50": null,
     "p75": null,
     "p95": null
    },
    "yes_72.0|statewide": {
     "p05": null,
     "p25": null,
     "p50": null,
     "p75": null,
     "p95": null
    },
    "yes_72.0|no_statewide": {
     "p05": null,
     "p25": null,
     "p50": null,
     "p75": null,
     "p95": null
    }
   },
   "reasoning": null,
   "sources": []
  },
  "other_foie_gras_bans_2030": {
   "baseline": {
    "value": null,
    "as_of": null,
    "source": null
   },
   "forecasts": {
    "yes_49.5": {
     "p05": null,
     "p25": null,
     "p50": null,
     "p75": null,
     "p95": null
    },
    "yes_50.5": {
     "p05": null,
     "p25": null,
     "p50": null,
     "p75": null,
     "p95": null
    }
   },
   "reasoning": null,
   "sources": []
  },
  "federal_preemption_2030": {
   "forecasts": {
    "yes_49.5": {
     "p": null
    },
    "yes_50.5": {
     "p": null
    }
   },
   "reasoning": null,
   "sources": []
  },
  "dc_bans_other_food_2030": {
   "forecasts": {
    "yes_49.5": {
     "p": null
    },
    "yes_50.5": {
     "p": null
    }
   },
   "reasoning": null,
   "sources": []
  }
 }
}
```
