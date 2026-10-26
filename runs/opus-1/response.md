I've finished the forecast set and filled in every field of the template; the JSON is below. The things I couldn't pin down are mostly about how DC resolves the vote and the ban after it:

- **Vote:** my median Yes share is about 62%, and I put the chance it passes at about 87%. The only polls are ones commissioned by supporters (78–79% support), so I discounted them. I also weighed Pro-Animal Future's two Denver measures in 2024, which lost with 35% and 42%.
- **Turnout:** this is anchored on 2022, when 179,786 people voted Yes or No on Initiative 82.
- **Funding:** whether the CFO ever certifies the measure's fiscal effect depends on the Council funding about $104,000 a year. I put that at roughly 50–60% if the ban survives, and it is the most uncertain link in the map.
- **Baselines that are my estimates, not counts:**
  - **Foie gras menus:** about 40. City Cast says about 50 DC places serve it, and the Colorado State study confirmed only 17.
  - **Liver pâté menus:** about 120. I found no published count.
  - **US ducks force-fed:** about 350,000. Producers don't publish volumes.
- **Michelin baseline:** 25 is the 2025 guide's total, and that includes the Inn at Little Washington in Virginia. The DC-address count is about 24.

```json
{
 "forecaster": {
  "model": "claude-opus-5-5",
  "prior_context": "none",
  "notes": "Plan-mode and headless instructions were both present; I did only read-only web research and produced no files. Menu baselines for foie gras and liver pate are estimates, not a fresh platform crawl. The Michelin baseline counts the whole 2025 DC guide, including the Inn at Little Washington in Virginia; the DC-address count is about 24."
 },
 "research_summary": "I-86 qualified on 2026-08-05 with a record 31,726 valid signatures. Pro-Animal DC had spent more than $336k by Sept 10, mostly from Pro-Animal Future (about $224k) and Dr. Bronner's (about $85k). The only polls are ones commissioned by supporters: 78% support (DC Voters for Animals, 2023) and 79% once informed (Colorado State University study). Opposition is thin and unfunded: Butterworth's chef Bart Hutchins is fundraising for a legal defense, and Jose Andres criticised the ban on Oct 23; Councilmember Robert White endorses it. It is the only initiative on the DC ballot. Turnout benchmark: I-82 in 2022 drew 179,786 Yes+No votes (74% Yes) from 205,509 ballots. The CFO estimates $314k over FY26-29 and says it is unfunded, so applicability depends on budget inclusion. Denver IO 311 is a parallel Pro-Animal Future measure. The group's 2024 Denver measures failed (fur 42%, slaughterhouse 35%), but a CSU survey reports 85% Colorado support for ending force-fed foie gras sales. Other foie gras bans: California is in force. NYC's ban was revived on appeal in March 2026 but remains enjoined pending a final ruling. Portland's council ban takes effect 2026-12-01. CSU found nearly 50 DC places listing foie gras, of which 17 were confirmed; City Cast says about 50. The 2025 Michelin DC guide has 25 starred restaurants, including the Inn at Little Washington in Virginia. FY2025 restaurant-meals tax was $567.9M and September 2026 employment was 51.5k, both from the brief.",
 "nodes": {
  "yes_share": {
   "forecasts": {
    "all": {
     "le_30": 0.005,
     "le_35": 0.01,
     "le_40": 0.025,
     "le_45": 0.055,
     "le_47": 0.075,
     "le_48": 0.09,
     "le_49": 0.105,
     "le_50": 0.125,
     "le_51": 0.145,
     "le_52": 0.165,
     "le_53": 0.19,
     "le_55": 0.245,
     "le_60": 0.41,
     "le_65": 0.61,
     "le_70": 0.79,
     "le_75": 0.915,
     "le_80": 0.972,
     "le_85": 0.994,
     "le_90": 0.999
    }
   },
   "reasoning": "Animal-welfare ballot measures that target a niche practice usually pass comfortably: Mass Q3 got 78%, Prop 12 got 63%, and DC's progressive electorate gave I-82 74%. The 78-79% polls were commissioned by supporters and opposition money is minimal. On the other side, Jose Andres and the restaurant community are pushing back with a backlash against 'outside activists', and Pro-Animal Future's Denver measures lost. I put the median at about 62% and P(pass) at about 87%.",
   "sources": [
    "https://www.idausa.org/campaign/farmed-animal/latest-news/washington-dc-residents-vote-to-ban-foie-gras-on-nov-3/",
    "https://www.axios.com/local/washington-dc/2026/10/21/dc-foie-gras-ban-ballot-initiative-fight",
    "https://dc.citycast.fm/food-drink/i86-jose-andres-dc-foie-gras",
    "https://en.wikipedia.org/wiki/Initiative_82",
    "https://hoodline.com/2026/08/foie-gras-ban-storms-d-c-ballot-as-city-faces-unfunded-314k-bill/"
   ]
  },
  "turnout": {
   "forecasts": {
    "all": {
     "p05": 150000,
     "p25": 175000,
     "p50": 190000,
     "p75": 205000,
     "p95": 232000
    }
   },
   "reasoning": "In the 2022 midterm, 205,509 ballots were cast and 179,786 voted Yes or No on I-82, an undervote of about 12.5%. The 2026 midterm has an open mayoral seat and a sole, well-publicised initiative, so I expect slightly higher ballots and a similar undervote.",
   "sources": [
    "https://en.wikipedia.org/wiki/Initiative_82",
    "https://en.wikipedia.org/wiki/2022_District_of_Columbia_elections"
   ]
  },
  "denver_io311_passes": {
   "forecasts": {
    "yes_42.0": {"p": 0.25},
    "yes_49.5": {"p": 0.4},
    "yes_50.5": {"p": 0.42},
    "yes_60.0": {"p": 0.6},
    "yes_72.0": {"p": 0.78}
   },
   "reasoning": "Unconditionally I put Denver at about 60%. Its electorate is more moderate than DC's, and Pro-Animal Future's 2024 Denver measures lost by wide margins; but a foie gras ban is far more popular than a slaughterhouse or fur ban, and CSU reports 85% support. Because both votes share the same campaign model and message, the two results are strongly correlated. Moving one point across 50% in DC changes Denver only slightly.",
   "sources": [
    "https://denverite.com/2026/09/25/vg-2026-initiated-ordinance-311-force-feeding-birds-ban-voter-guide/",
    "https://www.coloradopolitics.com/2024/11/06/animal-related-measures-fail-in-colorado-including-proposed-bans-on-trophy-hunting-and-denver-slaughterhouse-9f68d22a-9c68-11ef-99b8-fbbe5f58a9cd/",
    "https://hoodline.com/2026/09/denver-voters-to-decide-foie-gras-ban-restaurants-face-5-000-fines/"
   ]
  },
  "ban_status": {
   "forecasts": {
    "yes_50.5": {"repealed": 0.12, "congress": 0.05, "court": 0.03, "not_certified": 0.33, "certified": 0.47},
    "yes_60.0": {"repealed": 0.06, "congress": 0.045, "court": 0.03, "not_certified": 0.32, "certified": 0.545},
    "yes_72.0": {"repealed": 0.03, "congress": 0.04, "court": 0.025, "not_certified": 0.3, "certified": 0.605}
   },
   "reasoning": "The Council has repealed an initiative before (I-77) and amended I-82, so a bare pass carries real repeal risk. Repeal becomes unlikely at large margins, and a Councilmember endorses the measure. A congressional rider or disapproval is possible in a lame-duck or GOP-led Congress, but foie gras is a low priority. Courts rarely block sales bans after National Pork Producers v. Ross, though NYC shows state-preemption risk. The main remaining uncertainty is whether the Council funds about $104k a year in the FY2028 or FY2029 budget so the CFO can certify. Tight DC budgets make this roughly 55-65% conditional on the ban standing.",
   "sources": [
    "https://hoodline.com/2026/08/foie-gras-ban-storms-d-c-ballot-as-city-faces-unfunded-314k-bill/",
    "https://news.bloomberglaw.com/ip-law/new-york-citys-foie-gras-ban-is-revived-by-state-appeals-court",
    "https://en.wikipedia.org/wiki/Initiative_82"
   ]
  },
  "lawsuit_filed": {
   "forecasts": {
    "yes_50.5|blocked": {"p": 1.0},
    "yes_50.5|not_blocked": {"p": 0.6},
    "yes_60.0|blocked": {"p": 1.0},
    "yes_60.0|not_blocked": {"p": 0.58},
    "yes_72.0|blocked": {"p": 1.0},
    "yes_72.0|not_blocked": {"p": 0.55}
   },
   "reasoning": "Foie gras producers (Hudson Valley Foie Gras and La Belle Farm) sued over both the California and NYC bans. Butterworth's is already fundraising for a legal defense, and the broad 'fattened' definition invites a vagueness claim. A suit is less likely if the Council repeals the ban or never funds it, which partly explains the decline at higher margins together with weaker prospects for a challenge.",
   "sources": [
    "https://www.nbcwashington.com/news/local/dc-voters-to-decide-whether-a-controversial-luxury-food-should-be-banned/4171352/",
    "https://upc-online.org/ducks/260314_court_clears_way_for_nyc_foie_gras_ban-but_obstacles_remain.html"
   ]
  },
  "fattened_narrowed": {
   "forecasts": {
    "yes_50.5|certified": {"p": 0.25},
    "yes_50.5|not_certified": {"p": 0.12}
   },
   "reasoning": "The definition covers livers of birds 'fattened through any method', which literally could reach ordinary pate. In practice, a narrowing needs either a final DOEE rule or a Council amendment. DOEE rulemaking is slow and needs funding, and the Council tends to clarify only when there is a dispute. Narrowing is more likely when the ban is funded and active.",
   "sources": [
    "https://proanimaldc.org/faq/"
   ]
  },
  "pate_treated_banned": {
   "forecasts": {
    "yes_50.5|narrowed_certified": {"p": 0.01},
    "yes_50.5|narrowed_not_certified": {"p": 0.005},
    "yes_50.5|not_narrowed_certified": {"p": 0.05},
    "yes_50.5|not_narrowed_not_certified": {"p": 0.02}
   },
   "reasoning": "The sponsors, the CFO and the press all describe the measure as targeting force-fed products. DOEE enforces front-of-house, complaint-driven bans and will not pursue chicken-liver pate absent an activist complaint and literal reading. The chance is small, and smaller still if narrowed or unfunded.",
   "sources": [
    "https://hoodline.com/2026/08/foie-gras-ban-storms-d-c-ballot-as-city-faces-unfunded-314k-bill/"
   ]
  },
  "foie_gras_menus": {
   "baseline": {
    "value": 40,
    "as_of": "2026-10",
    "source": "Estimate from the CSU Animal-Human Policy Center report (nearly 50 DC places listing foie gras, 17 confirmed) and City Cast DC (about 50 establishments), October 2026"
   },
   "forecasts": {
    "yes_49.5|failed": {"p05": 20, "p25": 30, "p50": 38, "p75": 47, "p95": 62},
    "yes_50.5|removed": {"p05": 16, "p25": 26, "p50": 34, "p75": 43, "p95": 58},
    "yes_50.5|not_certified": {"p05": 1, "p25": 5, "p50": 12, "p75": 22, "p95": 38},
    "yes_50.5|certified": {"p05": 0, "p25": 1, "p50": 3, "p75": 7, "p95": 15}
   },
   "reasoning": "Without a ban, foie gras menus drift with restaurant churn and seasonality. With a funded ban, compliance looks like California, where nearly all menus dropped it, with a few holdouts and 'gifted' workarounds. If the ban is unfunded, its legal status is ambiguous, but stigma and caution still remove many listings.",
   "sources": [
    "https://sites.warnercnr.colostate.edu/animalhumanpolicy/ahpc-study-finds-strong-public-support-for-and-limited-impacts-to-restaurants-from-foie-gras-bans",
    "https://dc.citycast.fm/food-drink/i86-jose-andres-dc-foie-gras"
   ]
  },
  "liver_pate_menus": {
   "baseline": {
    "value": 120,
    "as_of": "2026-10",
    "source": "Own estimate: about 2,500 DC food establishments, with chicken liver mousse or pate common at bistros, wine bars and delis; no published count"
   },
   "forecasts": {
    "yes_49.5|failed": {"p05": 70, "p25": 100, "p50": 120, "p75": 145, "p95": 190},
    "yes_50.5|removed": {"p05": 70, "p25": 100, "p50": 120, "p75": 145, "p95": 190},
    "yes_50.5|standing_pate_allowed": {"p05": 65, "p25": 95, "p50": 116, "p75": 140, "p95": 185},
    "yes_50.5|standing_pate_banned": {"p05": 15, "p25": 40, "p50": 65, "p75": 95, "p95": 140}
   },
   "reasoning": "The baseline is highly uncertain. The ban should barely touch ordinary pate unless DOEE treats it as covered, in which case caution would cut listings substantially, though many places would relabel or keep them.",
   "sources": []
  },
  "us_ducks_force_fed_2030": {
   "baseline": {
    "value": 350000,
    "as_of": "2026",
    "source": "Rough estimate: Hudson Valley Foie Gras and La Belle Farm, historically about 350-400k ducks a year combined; producers do not publish volumes"
   },
   "forecasts": {
    "yes_49.5|failed": {"p05": 180000, "p25": 260000, "p50": 320000, "p75": 380000, "p95": 460000},
    "yes_50.5|not_certified_or_removed": {"p05": 170000, "p25": 245000, "p50": 305000, "p75": 365000, "p95": 450000},
    "yes_50.5|certified": {"p05": 140000, "p25": 210000, "p50": 265000, "p75": 330000, "p95": 420000}
   },
   "reasoning": "There are only two producers. A Hudson Valley Foie Gras owner says a DC ban could cost at least a third of its 150 jobs, which implies DC is a large market share. Possible NYC enforcement and more city bans push volumes down in every scenario.",
   "sources": [
    "https://www.france24.com/en/live-news/20260928-in-washington-s-political-cauldron-a-fight-over-foie-gras"
   ]
  },
  "dc_restaurant_employment_2029": {
   "baseline": {
    "value": 51.5,
    "as_of": "2026-09",
    "source": "BLS SMU11000007072200001 via FRED (given in the brief)"
   },
   "forecasts": {
    "yes_49.5|failed": {"p05": 46.0, "p25": 49.5, "p50": 51.3, "p75": 53.0, "p95": 55.8},
    "yes_50.5|not_certified_or_removed": {"p05": 46.0, "p25": 49.5, "p50": 51.3, "p75": 53.0, "p95": 55.8},
    "yes_50.5|certified": {"p05": 45.9, "p25": 49.4, "p50": 51.25, "p75": 52.95, "p95": 55.75}
   },
   "reasoning": "Macro conditions dominate: federal workforce cuts, the I-82 wage phase-in and recession risk. A foie gras ban affects a few dozen menu items, so its employment effect is negligible.",
   "sources": [
    "https://fred.stlouisfed.org/series/SMU11000007072200001"
   ]
  },
  "dc_restaurant_sales_tax_fy2029": {
   "baseline": {
    "value": 567.9,
    "as_of": "FY2025",
    "source": "DC ORA, 'DC Restaurant Sector Lags Hotel and Other Retail in Post-pandemic Recovery', 2026-04-14"
   },
   "forecasts": {
    "yes_49.5|failed": {"p05": 535, "p25": 590, "p50": 625, "p75": 660, "p95": 720},
    "yes_50.5|not_certified_or_removed": {"p05": 535, "p25": 590, "p50": 625, "p75": 660, "p95": 720},
    "yes_50.5|certified": {"p05": 534, "p25": 589, "p50": 624, "p75": 659, "p95": 719},
  "dc_michelin_starred_2029": {
   "baseline": {
    "value": 25,
    "as_of": "2025-11-18",
    "source": "Michelin Guide Washington DC 2025: 3 two-star and 22 one-star restaurants, including the Inn at Little Washington (VA)"
   },
   "forecasts": {
    "yes_49.5|failed": {"p05": 17, "p25": 21, "p50": 23, "p75": 26, "p95": 30},
    "yes_50.5|not_certified_or_removed": {"p05": 17, "p25": 21, "p50": 23, "p75": 26, "p95": 30},
    "yes_50.5|certified": {"p05": 17, "p25": 21, "p50": 23, "p75": 26, "p95": 30}
   },
   "reasoning": "There are about 24 DC-address stars, and the 2025 guide added none. Counts drift with closures. California's ban did not dent its star counts, so foie gras is irrelevant to Michelin.",
   "sources": [
    "https://en.wikipedia.org/wiki/List_of_Michelin-starred_restaurants_in_Washington,_D.C.",
    "https://wtop.com/business-finance/2025/11/michelin-guide-doesnt-include-any-new-stars-for-dc-restaurants/"
   ]
  },
  "dc_animal_initiative_filed": {
   "forecasts": {
    "yes_42.0": {"p": 0.12},
    "yes_49.5": {"p": 0.18},
    "yes_50.5": {"p": 0.28},
    "yes_60.0": {"p": 0.38},
    "yes_72.0": {"p": 0.45}
   },
   "reasoning": "Pro-Animal Future runs serial city campaigns and its goal is escalation toward factory-farm measures. A DC win, especially a big one, makes a 2028 DC follow-on (for example fur or confinement) plausible. A loss pushes the group elsewhere.",
   "sources": [
    "https://meatingplace.com/answers-to-come-soon-on-activist-driven-ballot-measures/",
    "https://manifund.org/projects/pro-animal-future"
   ]
  },
  "dc_another_animal_law": {
   "forecasts": {
    "yes_42.0|filed": {"p": 0.12},
    "yes_42.0|not_filed": {"p": 0.05},
    "yes_49.5|filed": {"p": 0.15},
    "yes_49.5|not_filed": {"p": 0.05},
    "yes_50.5|filed": {"p": 0.22},
    "yes_50.5|not_filed": {"p": 0.06},
    "yes_60.0|filed": {"p": 0.3},
    "yes_60.0|not_filed": {"p": 0.07},
    "yes_72.0|filed": {"p": 0.35},
    "yes_72.0|not_filed": {"p": 0.08}
   },
   "reasoning": "The DC Council rarely legislates on farmed animals. The main route is a filed initiative, which must qualify, pass and survive by 2030. A filed initiative that reaches the 2028 ballot would have perhaps a 40-60% path to law.",
   "sources": []
  },
  "dc_council_farmed_animal_bills": {
   "forecasts": {
    "yes_42.0": {"p05": 0, "p25": 0, "p50": 1, "p75": 2, "p95": 5},
    "yes_49.5": {"p05": 0, "p25": 0, "p50": 1, "p75": 2, "p95": 5},
    "yes_50.5": {"p05": 0, "p25": 1, "p50": 1, "p75": 3, "p95": 6},
    "yes_60.0": {"p05": 0, "p25": 1, "p50": 2, "p75": 3, "p95": 6},
    "yes_72.0": {"p05": 0, "p25": 1, "p50": 2, "p75": 3, "p95": 7}
   },
   "reasoning": "The base rate is low, at a few bills per Council period. A strong vote signals salience and invites members to introduce cage-free, fur or similar bills.",
   "sources": []
  },
  "paf_measures_2027_2028": {
   "forecasts": {
    "yes_42.0|denver_pass": {"0": 0.18, "1": 0.22, "2": 0.2, "3": 0.16, "4": 0.1, "5+": 0.14},
    "yes_42.0|denver_fail": {"0": 0.33, "1": 0.25, "2": 0.18, "3": 0.11, "4": 0.06, "5+": 0.07},
    "yes_49.5|denver_pass": {"0": 0.15, "1": 0.2, "2": 0.2, "3": 0.17, "4": 0.12, "5+": 0.16},
    "yes_49.5|denver_fail": {"0": 0.3, "1": 0.25, "2": 0.19, "3": 0.12, "4": 0.06, "5+": 0.08},
    "yes_50.5|denver_pass": {"0": 0.1, "1": 0.17, "2": 0.2, "3": 0.19, "4": 0.14, "5+": 0.2},
    "yes_50.5|denver_fail": {"0": 0.22, "1": 0.24, "2": 0.2, "3": 0.15, "4": 0.08, "5+": 0.11},
    "yes_60.0|denver_pass": {"0": 0.08, "1": 0.15, "2": 0.19, "3": 0.2, "4": 0.15, "5+": 0.23},
    "yes_60.0|denver_fail": {"0": 0.19, "1": 0.23, "2": 0.21, "3": 0.16, "4": 0.09, "5+": 0.12},
    "yes_72.0|denver_pass": {"0": 0.07, "1": 0.13, "2": 0.18, "3": 0.2, "4": 0.16, "5+": 0.26},
    "yes_72.0|denver_fail": {"0": 0.17, "1": 0.22, "2": 0.21, "3": 0.17, "4": 0.1, "5+": 0.13}
   },
   "reasoning": "Pro-Animal Future has a named target list (Columbus, St. Louis, Ann Arbor, Madison, Austin and others) and a cheap signature model, so several 2027-28 measures are plausible. Two wins attract donors and accelerate expansion, while losses (as after Denver 2024) slow it. Odd-year local ballots are fewer.",
   "sources": [
    "https://meatingplace.com/answers-to-come-soon-on-activist-driven-ballot-measures/",
    "https://manifund.org/projects/pro-animal-future"
   ]
  },
  "paf_statewide_2028": {
   "forecasts": {
    "yes_42.0|denver_pass": {"p": 0.13},
    "yes_42.0|denver_fail": {"p": 0.07},
    "yes_49.5|denver_pass": {"p": 0.17},
    "yes_49.5|denver_fail": {"p": 0.1},
    "yes_50.5|denver_pass": {"p": 0.22},
    "yes_50.5|denver_fail": {"p": 0.13},
    "yes_60.0|denver_pass": {"p": 0.26},
    "yes_60.0|denver_fail": {"p": 0.16},
    "yes_72.0|denver_pass": {"p": 0.3},
    "yes_72.0|denver_fail": {"p": 0.19}
   },
   "reasoning": "The group's stated goal is several statewide measures by 2030, but qualifying statewide is expensive and the group has only run city campaigns so far. Wins raise both money and the odds of a 2028 attempt, in a state such as Colorado, Oregon or Washington.",
   "sources": [
    "https://manifund.org/projects/pro-animal-future",
    "https://www.metaculus.com/c/dorsalheart/38809/of-state-ballots-with-a-factory-farm-ban-on-them-by-the-end-of-2030"
   ]
  },
  "us_new_coverage_2027_2032": {
   "forecasts": {
    "yes_42.0|statewide": {"p05": 2, "p25": 8, "p50": 18, "p75": 35, "p95": 80},
    "yes_42.0|no_statewide": {"p05": 0.5, "p25": 4, "p50": 11, "p75": 26, "p95": 65},
    "yes_49.5|statewide": {"p05": 2, "p25": 9, "p50": 19, "p75": 37, "p95": 82},
    "yes_49.5|no_statewide": {"p05": 0.6, "p25": 4, "p50": 12, "p75": 27, "p95": 66},
    "yes_50.5|statewide": {"p05": 2.5, "p25": 10, "p50": 21, "p75": 39, "p95": 85},
    "yes_50.5|no_statewide": {"p05": 0.8, "p25": 5, "p50": 13, "p75": 28, "p95": 68},
    "yes_60.0|statewide": {"p05": 3, "p25": 10, "p50": 22, "p75": 40, "p95": 86},
    "yes_60.0|no_statewide": {"p05": 1, "p25": 5, "p50": 14, "p75": 29, "p95": 70},
    "yes_72.0|statewide": {"p05": 3, "p25": 11, "p50": 23, "p75": 42, "p95": 88},
    "yes_72.0|no_statewide": {"p05": 1, "p25": 5, "p50": 15, "p75": 30, "p95": 72}
   },
   "reasoning": "Over six years, a few state cage-free or confinement laws plus city foie gras bans are typical. One large state, such as New York or Pennsylvania, could add 13-20M people on its own. A qualified Pro-Animal Future statewide measure adds roughly a 50% chance of a mid-size state.",
   "sources": []
  },
  "other_foie_gras_bans_2030": {
   "baseline": {
    "value": 1,
    "as_of": "2026-10-25",
    "source": "California is in force. NYC's Local Law 202 is enjoined pending a final ruling (Bloomberg Law, March 2026). Portland, OR's ban was enacted June 2026 and takes effect 2026-12-01."
   },
   "forecasts": {
    "yes_49.5": {"p05": 1, "p25": 2, "p50": 3, "p75": 4, "p95": 6},
    "yes_50.5": {"p05": 1, "p25": 2, "p50": 3, "p75": 5, "p95": 7}
   },
   "reasoning": "California and Portland are near-certain by 2030. NYC is about 55% likely, pending the Court of Appeals. Denver is about 45% from the same-day vote, and more Pro-Animal Future cities are possible. A DC pass slightly raises the momentum for other cities.",
   "sources": [
    "https://news.bloomberglaw.com/ip-law/new-york-citys-foie-gras-ban-is-revived-by-state-appeals-court",
    "https://www.opb.org/article/2026/06/04/portland-approves-foie-gras-ban/",
    "https://upc-online.org/ducks/260314_court_clears_way_for_nyc_foie_gras_ban-but_obstacles_remain.html"
   ]
  },
  "federal_preemption_2030": {
   "forecasts": {
    "yes_49.5": {"p": 0.2},
    "yes_50.5": {"p": 0.21}
   },
   "reasoning": "House farm bill drafts have repeatedly carried Prop 12 preemption (the EATS Act and Save Our Bacon Act), but the Senate has blocked it. Enactment by 2030 is plausible through a farm bill deal but not likely. DC's result is nearly irrelevant, with only a slight backlash effect.",
   "sources": []
  },
  "dc_bans_other_food_2030": {
   "forecasts": {
    "yes_49.5": {"p": 0.15},
    "yes_50.5": {"p": 0.16}
   },
   "reasoning": "States are increasingly banning additives and dyes, as California did, and the DC Council could follow, but DC has no such law pending that I found. The base rate is modest, and the foie gras result has little effect.",
   "sources": []
  }
 }
}
```
