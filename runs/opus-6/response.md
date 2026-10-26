I couldn't create the plan-mode plan file because no Write or ExitPlanMode tool is available in this session. All the research below used read-only web searches and fetches. The forecast follows.

```json
{
 "forecaster": {
  "model": "claude-opus-5-5 (Opus 5.5)",
  "prior_context": "No prior forecasts or substantive information about Initiative 86 or foie gras in my context besides the brief. The only related mentions: the working directory path '/Users/maxghenis/.cache/dc-i86-llm-forecast/opus-6', a '<!-- subfleet:headless -->' header, and a plan-mode system instruction (no plan file could be written; only read-only tools were used).",
  "notes": "Main judgement: I-86 passes comfortably, since organized opposition is absent. Most of the downstream uncertainty is about CFO certification and funding, and about Council amendment of the over-broad 'fattened' definition. Spillover effects of DC's margin are modest."
 },
 "research_summary": "I-86 qualified with a record 31,726 valid signatures. Pro-Animal DC spent over $336k through Sept 10 (about $224k from Pro-Animal Future, about $85k from Dr. Bronner's). City Cast reports that no opposition committee exists or has filed reports. Opposition consists of José Andrés's posts and Butterworth's chef Bart Hutchins, who is running a legal-defense fundraiser and plans protests. The Restaurant Association of Metropolitan Washington is mildly critical but not formally opposed. Councilmember Robert White endorses. The only polling is advocacy polling: 79% of DC voters in 2023 (DC Voters for Animals) and 79% in a Colorado State University urban survey. Comparable DC initiatives passed with 65-74% (I-71, I-82). About 50 DC restaurants serve foie gras. Denver IO311 is narrower (force-fed only), on the same day, about 11k valid signatures, unopposed in practice; in 2024 PAF's Denver fur and slaughterhouse measures failed. Portland OR passed a council foie gras ban in June 2026 (180-day phase-in). NYC's ban was revived by the Court of Appeals in March 2026 but remains enjoined in separate producer litigation. California's ban is in force. The House farm bill (passed April 2026) includes Prop 12 preemption; the Senate Ag draft omits it. Hudson Valley plus La Belle force-feed about 350k birds a year. DC food services employment was 51.5k in Sept 2026. DC's restaurant sales tax was $567.9M in FY2025. The 2025 Michelin DC guide has about 20 starred restaurants, with no new stars in 2025. The mayoral general is uncompetitive (Lewis George won the Democratic primary).",
 "nodes": {
  "yes_share": {
   "forecasts": {
    "all": {
     "le_30": 0.005,
     "le_35": 0.01,
     "le_40": 0.02,
     "le_45": 0.04,
     "le_47": 0.05,
     "le_48": 0.06,
     "le_49": 0.07,
     "le_50": 0.08,
     "le_51": 0.09,
     "le_52": 0.10,
     "le_53": 0.115,
     "le_55": 0.15,
     "le_60": 0.29,
     "le_65": 0.50,
     "le_70": 0.70,
     "le_75": 0.86,
     "le_80": 0.95,
     "le_85": 0.985,
     "le_90": 0.997
    }
   },
   "reasoning": "Base rate: DC progressive-leaning initiatives with weak opposition pass 60-75% (I-71 65%, I-82 74%). I-86 has heavy Yes spending, no registered No campaign, advocacy polls near 79% and record signatures. Discounts: the poll source, the culture-war framing (José Andrés, 'pâté' breadth) and possible late chef-led backlash. Median about 65%, P(pass) about 92%.",
   "sources": ["https://dc.citycast.fm/opinion/dc-foie-gras-ban-initiative", "https://dc.citycast.fm/food-drink/i86-jose-andres-dc-foie-gras", "https://www.idausa.org/campaign/farmed-animal/latest-news/washington-dc-residents-vote-to-ban-foie-gras-on-nov-3/", "https://en.wikipedia.org/wiki/Initiative_82", "https://www.axios.com/local/washington-dc/2026/10/21/dc-foie-gras-ban-ballot-initiative-fight"]
  },
  "turnout": {
   "forecasts": {
    "all": {
     "p05": 150000,
     "p25": 185000,
     "p50": 205000,
     "p75": 225000,
     "p95": 260000
    }
   },
   "reasoning": "In the 2022 midterm general, about 205k ballots were cast and I-82 drew about 185-195k Yes+No votes. 2026 has an open but uncompetitive mayoral race and a delegate seat, so turnout should be similar or slightly higher. Ballot roll-off on initiatives is small.",
   "sources": ["https://en.wikipedia.org/wiki/2026_Washington,_D.C.,_mayoral_election", "https://en.wikipedia.org/wiki/Initiative_82"]
  },
  "denver_io311_passes": {
   "forecasts": {
    "yes_42.0": {"p": 0.42},
    "yes_49.5": {"p": 0.55},
    "yes_50.5": {"p": 0.57},
    "yes_60.0": {"p": 0.68},
    "yes_72.0": {"p": 0.82}
   },
   "reasoning": "IO311 is narrower (force-fed only), unopposed in practice, and polls advertise 85% support. PAF's 2024 Denver fur (about 43%) and slaughterhouse measures failed. Unconditional P is about 0.70. The same organization runs both campaigns with similar messaging, so a weak DC result signals the message underperformed, and the correlation is meaningful.",
   "sources": ["https://denverite.com/2026/09/25/vg-2026-initiated-ordinance-311-force-feeding-birds-ban-voter-guide/", "https://hoodline.com/2026/09/denver-voters-to-decide-foie-gras-ban-restaurants-face-5-000-fines/", "https://veganfta.com/2023/12/19/its-official-fur-ban-and-slaughterhouse-ban-to-be-placed-on-denvers-2024-ballot/"]
  },
  "ban_status": {
   "forecasts": {
    "yes_50.5": {"repealed": 0.12, "congress": 0.05, "court": 0.06, "not_certified": 0.35, "certified": 0.42},
    "yes_60.0": {"repealed": 0.06, "congress": 0.05, "court": 0.05, "not_certified": 0.34, "certified": 0.50},
    "yes_72.0": {"repealed": 0.03, "congress": 0.04, "court": 0.05, "not_certified": 0.32, "certified": 0.56},
    "_note": null
   },
   "reasoning": "The Council has repealed or gutted initiatives before (I-77, I-82), but a $314k item that voters endorse is a low priority to repeal, especially at large margins. Amendment (narrowing the definition) is likelier than repeal. A congressional rider is possible given Republican interest, but a likely Democratic House after 2026 makes an enacted bar unlikely. Commerce-clause challenges fail after National Pork Producers v. Ross, and the vagueness issue invites a narrowing amendment rather than a whole-ban injunction. CFO certification needs the cost included in an approved budget. DC often leaves 'subject to appropriations' laws unfunded under tight FY2027-28 budgets, so certification is only modestly better than even.",
   "sources": ["https://hoodline.com/2026/08/foie-gras-ban-storms-d-c-ballot-as-city-faces-unfunded-314k-bill/", "https://en.wikipedia.org/wiki/Initiative_82", "https://www.nbcwashington.com/news/local/dc-voters-to-decide-whether-a-controversial-luxury-food-should-be-banned/4171352/"]
  },
  "lawsuit_filed": {
   "forecasts": {
    "yes_50.5|blocked": {"p": 0.99},
    "yes_50.5|not_blocked": {"p": 0.45},
    "yes_60.0|blocked": {"p": 0.99},
    "yes_60.0|not_blocked": {"p": 0.42},
    "yes_72.0|blocked": {"p": 0.99},
    "yes_72.0|not_blocked": {"p": 0.40},
    "_note": null
   },
   "reasoning": "Butterworth's is raising a legal-defense fund and threatening suit. Foie gras producers (Hudson Valley, La Belle) have sued California and NYC repeatedly, and the over-broad pâté definition offers a vagueness hook. A slightly lower chance at larger margins and when unblocked (a suit that exists more often produces some block).",
   "sources": ["https://www.nbcwashington.com/news/local/dc-voters-to-decide-whether-a-controversial-luxury-food-should-be-banned/4171352/", "https://upc-online.org/ducks/260314_court_clears_way_for_nyc_foie_gras_ban-but_obstacles_remain.html"]
  },
  "fattened_narrowed": {
   "forecasts": {
    "yes_50.5|certified": {"p": 0.30},
    "yes_50.5|not_certified": {"p": 0.15}
   },
   "reasoning": "The definition reaches livers 'fattened through any method', which could sweep in ordinary chicken-liver pâté. The Council could fix this in a Budget Support Act or a technical amendment, and DOEE could define it by rulemaking. Both are slow. Engagement (funding, rulemaking) correlates with certification, so narrowing is likelier in the certified state.",
   "sources": ["https://proanimaldc.org/prohibit-force-feeding-of-birds-act/"]
  },
  "pate_treated_banned": {
   "forecasts": {
    "yes_50.5|narrowed_certified": {"p": 0.005},
    "yes_50.5|narrowed_not_certified": {"p": 0.003},
    "yes_50.5|not_narrowed_certified": {"p": 0.04},
    "yes_50.5|not_narrowed_not_certified": {"p": 0.015}
   },
   "reasoning": "DOEE does not inspect back-of-house and will have one inspector. The sponsor's intent and the summary target force-feeding, so treating chicken-liver pâté as a violation would be a surprising written determination. Somewhat possible only if the definition is not narrowed and enforcement is funded.",
   "sources": ["https://dcboe.org/getmedia/8ed77952-835c-4a11-9fa2-2ad447d82643/Final-FIS-Initiative-Prohibiting-the-Force-Feeding-of-Birds-Act-of-2026.pdf"]
  },
  "foie_gras_menus": {
   "baseline": {"value": 50, "as_of": "2026-10-23", "source": "City Cast DC ('approximately 50 D.C. restaurants serve foie gras'), https://dc.citycast.fm/food-drink/i86-jose-andres-dc-foie-gras"},
   "forecasts": {
    "yes_49.5|failed": {"p05": 30, "p25": 39, "p50": 45, "p75": 52, "p95": 64},
    "yes_50.5|removed": {"p05": 18, "p25": 28, "p50": 35, "p75": 43, "p95": 55},
    "yes_50.5|not_certified": {"p05": 1, "p25": 4, "p50": 8, "p75": 15, "p95": 28},
    "yes_50.5|certified": {"p05": 0, "p25": 1, "p50": 3, "p75": 6, "p95": 12}
   },
   "reasoning": "About 50 today, with natural churn and a slight downward trend. Without the law, counts drift slightly lower. If the ban is removed, some restaurants delisted early and do not return. If the ban stands, most comply even without CFO certification, because the sale ban arguably applies from July 2027. Stragglers and stale menus remain, more so if enforcement is unfunded.",
   "sources": ["https://dc.citycast.fm/food-drink/i86-jose-andres-dc-foie-gras"]
  },
  "liver_pate_menus": {
   "baseline": {"value": 120, "as_of": "2026-10-25", "source": "Own estimate (no published count); scaled from DC's roughly 2,500 full-service restaurants and the prevalence of chicken-liver pâté/mousse on bistro and New American menus"},
   "forecasts": {
    "yes_49.5|failed": {"p05": 70, "p25": 100, "p50": 120, "p75": 145, "p95": 190},
    "yes_50.5|removed": {"p05": 70, "p25": 100, "p50": 120, "p75": 145, "p95": 190},
    "yes_50.5|standing_pate_allowed": {"p05": 65, "p25": 95, "p50": 116, "p75": 140, "p95": 185},
    "yes_50.5|standing_pate_banned": {"p05": 35, "p25": 60, "p50": 82, "p75": 108, "p95": 150}
   },
   "reasoning": "The baseline is uncertain. Liver pâté is unaffected unless DOEE treats it as covered. With the ban standing, there is slight chilling. If enforcement against pâté occurs, a sizable minority drop or rename it, but many continue.",
   "sources": ["https://proanimaldc.org/prohibit-force-feeding-of-birds-act/"]
  },
  "us_ducks_force_fed_2030": {
   "baseline": {"value": 350000, "as_of": "2019 (latest public estimate)", "source": "Hudson Valley Foie Gras and La Belle Farm combined, about 350,000 birds/yr (NBC New York / AP), https://www.nbcnewyork.com/news/local/farms-worry-as-new-york-city-considers-foie-gras-ban/1488285/"},
   "forecasts": {
    "yes_49.5|failed": {"p05": 120000, "p25": 220000, "p50": 290000, "p75": 340000, "p95": 420000},
    "yes_50.5|not_certified_or_removed": {"p05": 115000, "p25": 215000, "p50": 285000, "p75": 335000, "p95": 415000},
    "yes_50.5|certified": {"p05": 110000, "p25": 205000, "p50": 275000, "p75": 325000, "p95": 405000}
   },
   "reasoning": "Two NY farms dominate. NYC ban enforcement, if the injunction lifts, is the main threat (NYC is about 30% of sales). DC is a meaningful market (proponents call it #2), so an enforced ban trims volume by a few percent.",
   "sources": ["https://www.nbcnewyork.com/news/local/farms-worry-as-new-york-city-considers-foie-gras-ban/1488285/", "https://upc-online.org/ducks/260314_court_clears_way_for_nyc_foie_gras_ban-but_obstacles_remain.html"]
  },
  "dc_restaurant_employment_2029": {
   "baseline": {"value": 51.5, "as_of": "2026-09", "source": "BLS SMU11000007072200001 via FRED (per brief)"},
   "forecasts": {
    "yes_49.5|failed": {"p05": 46.0, "p25": 49.5, "p50": 51.8, "p75": 53.8, "p95": 56.5},
    "yes_50.5|not_certified_or_removed": {"p05": 46.0, "p25": 49.5, "p50": 51.8, "p75": 53.8, "p95": 56.5},
    "yes_50.5|certified": {"p05": 45.9, "p25": 49.4, "p50": 51.75, "p75": 53.75, "p95": 56.45}
   },
   "reasoning": "Macro factors and the federal workforce dominate. The sector has been flat to slightly down since the pandemic, and recession risk adds a left tail. A foie gras ban affects one menu item at about 50 restaurants, so its effect is negligible (under 50 jobs).",
   "sources": ["https://fred.stlouisfed.org/series/SMU11000007072200001", "https://ora-cfo.dc.gov/node/1824291"]
  },
  "dc_restaurant_sales_tax_fy2029": {
   "baseline": {"value": 567.9, "as_of": "FY2025", "source": "DC CFO ORA, 2026-04-14, https://ora-cfo.dc.gov/node/1824291"},
   "forecasts": {
    "yes_49.5|failed": {"p05": 555, "p25": 600, "p50": 630, "p75": 660, "p95": 710},
    "yes_50.5|not_certified_or_removed": {"p05": 555, "p25": 600, "p50": 630, "p75": 660, "p95": 710},
    "yes_50.5|certified": {"p05": 554, "p25": 599, "p50": 629, "p75": 659, "p95": 709},
    "_note": null
   },
   "reasoning": "Nominal growth of 2-3% a year from $567.9M over four years, with weak real recovery and federal cuts. The ban's effect is about $1M at most (foie gras dishes are a tiny share of sales, and diners substitute).",
   "sources": ["https://ora-cfo.dc.gov/node/1824291"]
  },
  "dc_michelin_starred_2029": {
   "baseline": {"value": 20, "as_of": "2025 guide (Nov 2025); 2026 stars due Dec 2026", "source": "Michelin Guide Washington DC 2025, per WTOP/The Points Guy summaries, https://wtop.com/business-finance/2025/11/michelin-guide-doesnt-include-any-new-stars-for-dc-restaurants/"},
   "forecasts": {
    "yes_49.5|failed": {"p05": 14, "p25": 18, "p50": 20, "p75": 23, "p95": 27},
    "yes_50.5|not_certified_or_removed": {"p05": 14, "p25": 18, "p50": 20, "p75": 23, "p95": 27},
    "yes_50.5|certified": {"p05": 14, "p25": 18, "p50": 20, "p75": 23, "p95": 27}
   },
   "reasoning": "The count has been stable at about 20 with little churn, plus some risk that the guide is discontinued or shrinks. Starred kitchens can substitute easily (California's and NYC's fine dining did not shrink from foie gras bans), so there is no effect across cells.",
   "sources": ["https://wtop.com/business-finance/2025/11/michelin-guide-doesnt-include-any-new-stars-for-dc-restaurants/", "https://washingtonian.com/2025/11/19/why-does-the-dc-michelin-guide-feel-so-stale/"]
  },
  "dc_animal_initiative_filed": {
   "forecasts": {
    "yes_42.0": {"p": 0.14},
    "yes_49.5": {"p": 0.24},
    "yes_50.5": {"p": 0.30},
    "yes_60.0": {"p": 0.38},
    "yes_72.0": {"p": 0.50}
   },
   "reasoning": "PAF's model is to escalate from a winnable local measure to bigger asks, and DC is cheap to qualify with a large volunteer base. A strong win invites a 2028 follow-up (fur, cage or confinement standards). A loss pushes PAF to other cities. A bare pass gives a modest bump over a bare fail.",
   "sources": ["https://manifund.org/projects/pro-animal-future", "https://paxfauna.org/introducing-pro-animal-futures-10-year-plan/"]
  },
  "dc_another_animal_law": {
   "forecasts": {
    "yes_42.0|filed": {"p": 0.22},
    "yes_42.0|not_filed": {"p": 0.06},
    "yes_49.5|filed": {"p": 0.27},
    "yes_49.5|not_filed": {"p": 0.07},
    "yes_50.5|filed": {"p": 0.30},
    "yes_50.5|not_filed": {"p": 0.08},
    "yes_60.0|filed": {"p": 0.35},
    "yes_60.0|not_filed": {"p": 0.09},
    "yes_72.0|filed": {"p": 0.42},
    "yes_72.0|not_filed": {"p": 0.10}
   },
   "reasoning": "A filed initiative must qualify, pass and take effect by 2030. Many filings never qualify, and congressional review and funding add delay. Without an initiative, the Council rarely legislates on farmed animals, though a fur-sales bill has been floated. Strong I-86 margins raise both channels.",
   "sources": ["https://ballotpedia.org/Animal_treatment_laws_ballot_measures"]
  },
  "dc_council_farmed_animal_bills": {
   "forecasts": {
    "yes_42.0": {"p05": 0, "p25": 1, "p50": 1, "p75": 3, "p95": 6},
    "yes_49.5": {"p05": 0, "p25": 1, "p50": 2, "p75": 3, "p95": 6},
    "yes_50.5": {"p05": 0, "p25": 1, "p50": 2, "p75": 3, "p95": 7},
    "yes_60.0": {"p05": 0, "p25": 1, "p50": 2, "p75": 4, "p95": 7},
    "yes_72.0": {"p05": 0, "p25": 1, "p50": 3, "p75": 4, "p95": 8}
   },
   "reasoning": "Over two Council periods, a handful of bills (fur, cage-free, procurement) are introduced. A strong vote signals constituency demand and prompts a few more introductions.",
   "sources": ["https://lims.dccouncil.gov/"]
  },
  "paf_measures_2027_2028": {
   "forecasts": {
    "yes_42.0|denver_pass": {"0": 0.20, "1": 0.25, "2": 0.22, "3": 0.15, "4": 0.08, "5+": 0.10},
    "yes_42.0|denver_fail": {"0": 0.35, "1": 0.27, "2": 0.18, "3": 0.10, "4": 0.05, "5+": 0.05},
    "yes_49.5|denver_pass": {"0": 0.17, "1": 0.24, "2": 0.23, "3": 0.16, "4": 0.09, "5+": 0.11},
    "yes_49.5|denver_fail": {"0": 0.30, "1": 0.27, "2": 0.20, "3": 0.11, "4": 0.06, "5+": 0.06},
    "yes_50.5|denver_pass": {"0": 0.15, "1": 0.23, "2": 0.23, "3": 0.17, "4": 0.10, "5+": 0.12},
    "yes_50.5|denver_fail": {"0": 0.28, "1": 0.27, "2": 0.20, "3": 0.12, "4": 0.06, "5+": 0.07},
    "yes_60.0|denver_pass": {"0": 0.13, "1": 0.22, "2": 0.23, "3": 0.18, "4": 0.11, "5+": 0.13},
    "yes_60.0|denver_fail": {"0": 0.25, "1": 0.27, "2": 0.21, "3": 0.12, "4": 0.07, "5+": 0.08},
    "yes_72.0|denver_pass": {"0": 0.10, "1": 0.20, "2": 0.23, "3": 0.19, "4": 0.12, "5+": 0.16},
    "yes_72.0|denver_fail": {"0": 0.22, "1": 0.26, "2": 0.22, "3": 0.13, "4": 0.08, "5+": 0.09}
   },
   "reasoning": "PAF ran 2 Denver measures in 2024 and 2 in 2026. It listed about 7 target cities and aims for statewide measures by 2030. Many targets slip, and Portland was done by the Council instead. Typical output is 1-3 measures per cycle, scaled up by wins (fundraising, credibility) and down by losses.",
   "sources": ["https://manifund.org/projects/pro-animal-future", "https://paxfauna.org/introducing-pro-animal-futures-10-year-plan/", "https://ballotpedia.org/Endorsements_by_Pro-Animal_Future"]
  },
  "paf_statewide_2028": {
   "forecasts": {
    "yes_42.0|denver_pass": {"p": 0.08},
    "yes_42.0|denver_fail": {"p": 0.05},
    "yes_49.5|denver_pass": {"p": 0.10},
    "yes_49.5|denver_fail": {"p": 0.06},
    "yes_50.5|denver_pass": {"p": 0.11},
    "yes_50.5|denver_fail": {"p": 0.07},
    "yes_60.0|denver_pass": {"p": 0.13},
    "yes_60.0|denver_fail": {"p": 0.08},
    "yes_72.0|denver_pass": {"p": 0.17},
    "yes_72.0|denver_fail": {"p": 0.10}
   },
   "reasoning": "PAF's stated goal is several statewide measures by 2030. Qualifying a 2028 statewide measure (millions of dollars, or a large volunteer drive in OR, CO or MA) is a big step up from city campaigns costing about $300k. Wins raise both feasibility and funding.",
   "sources": ["https://paxfauna.org/introducing-pro-animal-futures-10-year-plan/", "https://manifund.org/projects/pro-animal-future"]
  },
  "us_new_coverage_2027_2032": {
   "forecasts": {
    "yes_42.0|statewide": {"p05": 2, "p25": 6, "p50": 12, "p75": 25, "p95": 55},
    "yes_42.0|no_statewide": {"p05": 0.3, "p25": 2.5, "p50": 7, "p75": 18, "p95": 45},
    "yes_49.5|statewide": {"p05": 2, "p25": 6.5, "p50": 13, "p75": 26, "p95": 57},
    "yes_49.5|no_statewide": {"p05": 0.4, "p25": 2.8, "p50": 7.5, "p75": 19, "p95": 46},
    "yes_50.5|statewide": {"p05": 2, "p25": 7, "p50": 13.5, "p75": 27, "p95": 58},
    "yes_50.5|no_statewide": {"p05": 0.4, "p25": 3, "p50": 8, "p75": 19.5, "p95": 47},
    "yes_60.0|statewide": {"p05": 2.5, "p25": 7.5, "p50": 14, "p75": 28, "p95": 60},
    "yes_60.0|no_statewide": {"p05": 0.5, "p25": 3, "p50": 8.5, "p75": 20, "p95": 48},
    "yes_72.0|statewide": {"p05": 3, "p25": 8, "p50": 15, "p75": 30, "p95": 62},
    "yes_72.0|no_statewide": {"p05": 0.5, "p25": 3.5, "p50": 9, "p75": 21, "p95": 50}
   },
   "reasoning": "Over 6 years, a few state cage-free or confinement laws plus local foie gras and fur-type sales bans are likely; one mid-size state adds 5-12M. A qualified statewide PAF measure adds a 4-7M state if it passes (about 50%). Federal preemption risk caps the momentum. The DC margin has only a small signalling effect.",
   "sources": ["https://ballotpedia.org/Animal_treatment_laws_ballot_measures", "https://aldf.org/project/oppose-the-farm-food-and-national-security-act-of-2026-house-farm-bill-federal"]
  },
  "other_foie_gras_bans_2030": {
   "baseline": {"value": 2, "as_of": "2026-10-25", "source": "California state ban (in force) and Portland, OR (council ban passed June 2026, 180-day phase-in, so not yet in force strictly). NYC's 2019 ban is enjoined despite the March 2026 Court of Appeals win. https://opb.org/article/2026/06/04/portland-approves-foie-gras-ban/ ; https://upc-online.org/ducks/260314_court_clears_way_for_nyc_foie_gras_ban-but_obstacles_remain.html"},
   "forecasts": {
    "yes_49.5": {"p05": 2, "p25": 3, "p50": 4, "p75": 5, "p95": 8},
    "yes_50.5": {"p05": 2, "p25": 3, "p50": 4, "p75": 6, "p95": 9}
   },
   "reasoning": "California and Portland are near-certain to be in force. NYC is about 65% likely to be enforceable by 2030. Denver is about 65% likely (it votes the same day). Another 0-3 cities are possible via PAF campaigns or councils. A DC pass slightly raises copycat odds.",
   "sources": ["https://opb.org/article/2026/06/04/portland-approves-foie-gras-ban/", "https://upc-online.org/ducks/260314_court_clears_way_for_nyc_foie_gras_ban-but_obstacles_remain.html", "https://denverite.com/2026/09/25/vg-2026-initiated-ordinance-311-force-feeding-birds-ban-voter-guide/"]
  },
  "federal_preemption_2030": {
   "forecasts": {
    "yes_49.5": {"p": 0.22},
    "yes_50.5": {"p": 0.225}
   },
   "reasoning": "The House farm bill (passed April 2026, 224-200) contains Prop 12 preemption, but the Senate Ag draft omits it, and 60-vote dynamics plus a likely Democratic House in 2027 cut the odds. A lame-duck or 2029+ farm bill could carry a pork-only fix. A DC foie gras vote barely matters.",
   "sources": ["https://aldf.org/project/oppose-the-farm-food-and-national-security-act-of-2026-house-farm-bill-federal", "https://veganfta.com/articles/2026/07/07/us-senate-farm-bill-proposal-leaves-prop-12-intact-for-now/"]
  },
  "dc_bans_other_food_2030": {
   "forecasts": {
    "yes_49.5": {"p": 0.14},
    "yes_50.5": {"p": 0.15}
   },
   "reasoning": "State food-additive bans (dyes, potassium bromate) are spreading, and DC could follow, though the Council has not prioritized them. Most such laws are school-only or phased in, and those don't count. A foie gras pass slightly normalizes content-based sales bans.",
   "sources": ["https://lims.dccouncil.gov/"]
  }
 }
}
```
