I made the forecasts below from public reporting as of 2026-10-25 and the base rates noted in each question. Two caveats:

- **Plan mode:** this session was in plan mode, so I only searched the web and read pages. I didn't write the plan file or call ExitPlanMode because neither tool was available. Per the headless brief, the forecast below is my final output.
- **Weak evidence:** some inputs rest on thin evidence. The 78% DC poll and the 85% Colorado poll were both commissioned by the campaigns, and I found no independent poll. I couldn't load the Axios articles of 2026-10-21 and 10-23 or Denverite's voter guide, so I relied on their headlines and search snippets. The menu counts and the duck count are my own estimates, not counts I made.

```json
{
 "forecaster": {
  "model": "claude-opus-5-5",
  "prior_context": "none",
  "notes": "Session ran under a plan-mode instruction; only read-only web research was performed. Michelin count treats the DC guide's starred list as including the Inn at Little Washington (VA). Menu baselines are estimates from published counts (Pro-Animal DC ~50 over a year; CSU study 17), not a fresh menu crawl."
 },
 "research_summary": "Initiative 86 qualified with a record 31,726 valid signatures. The only poll is sponsor-commissioned and shows 78% support. No opposition committee has filed with OCF, while Pro-Animal DC raised about $363k (Pro-Animal Future, Dr. Bronner's). The Restaurant Association of Metropolitan Washington declined to fully oppose. Opposition is late and comes from chefs: Bart Hutchins of Butterworth's, plus José Andrés on 10/23. Axios reports legal threats. CM Robert White endorsed. Mendelson raised a procedural objection on funding, and the CFO found $314k unfunded through FY2029. Recent DC initiatives mostly passed comfortably (I-82 74%, I-83 ~73%, I-81 76%, I-71 65%); I-77 passed with 55% and the Council repealed it. About 50 DC restaurants served foie gras in the past year by the sponsor's count, versus 17 confirmed by CSU. Denver IO 311 (Pro-Animal Colorado) is on the same ballot and exempts non-force-fed foie gras. In 2024 Pro-Animal measures in Denver lost badly: fur ban ~42%, slaughterhouse ban ~36%. A state appeals court revived NYC's foie gras ban in March 2026, but enforcement stays enjoined until a final ruling. California's ban is in force. The House farm bill includes the Save Our Bacon Act, which would preempt Prop 12; the Senate draft omits it. DC's Michelin guide lists 20 starred restaurants plus the Inn at Little Washington, with the next ceremony on Dec 14, 2026.",
 "nodes": {
  "yes_share": {
   "forecasts": {
    "all": {
     "le_30": 0.002,
     "le_35": 0.004,
     "le_40": 0.01,
     "le_45": 0.025,
     "le_47": 0.035,
     "le_48": 0.042,
     "le_49": 0.05,
     "le_50": 0.06,
     "le_51": 0.069,
     "le_52": 0.079,
     "le_53": 0.092,
     "le_55": 0.125,
     "le_60": 0.245,
     "le_65": 0.45,
     "le_70": 0.69,
     "le_75": 0.87,
     "le_80": 0.96,
     "le_85": 0.99,
     "le_90": 0.998
    }
   },
   "reasoning": "DC voters are very progressive, and recent initiatives passed with 55-76%. There is no funded No campaign, the industry association is ambivalent, and the sponsor's poll shows 78%. Polls on animal measures usually overstate final support, and chef opposition (José Andrés) plus 'nanny state' framing could cut into the margin. Median ~66% with a ~6% chance of failing.",
   "sources": [
    "https://washingtonian.com/2026/08/05/foie-gras-ban-will-be-on-dcs-ballot-this-november/",
    "https://www.idausa.org/campaign/farmed-animal/latest-news/washington-dc-residents-vote-to-ban-foie-gras-on-nov-3/",
    "https://dc.citycast.fm/food-drink/i86-jose-andres-dc-foie-gras",
    "https://www.axios.com/local/washington-dc/2026/10/21/dc-foie-gras-ban-ballot-initiative-fight",
    "https://washingtondcmagazine.substack.com/p/dc-voters-will-decide-november-3"
   ]
  },
  "turnout": {
   "forecasts": {
    "all": {
     "p05": 148000,
     "p25": 175000,
     "p50": 192000,
     "p75": 210000,
     "p95": 240000
    }
   },
   "reasoning": "In the 2022 midterm, roughly 175-185k votes were cast on I-82, and in 2018 about 200k were cast on I-77. The 2026 midterm has an open mayoral seat, but the Democratic primary largely decides that race. Ballot roll-off on initiatives is modest.",
   "sources": [
    "https://en.wikipedia.org/wiki/Initiative_77",
    "https://51st.news/dc-general-election-2026-voter-guide/"
   ]
  },
  "denver_io311_passes": {
   "forecasts": {
    "yes_42.0": {"p": 0.35},
    "yes_49.5": {"p": 0.5},
    "yes_50.5": {"p": 0.52},
    "yes_60.0": {"p": 0.64},
    "yes_72.0": {"p": 0.8}
   },
   "reasoning": "Denver is progressive, and foie gras is a much easier target than the 2024 fur ban (~42%) and slaughterhouse ban (~36%), both of which failed. The sponsor cites polls of 85%+, and the measure exempts non-force-fed product. My unconditional estimate is ~0.7. DC's margin acts as a correlated signal of national sentiment and campaign quality.",
   "sources": [
    "https://denverite.com/2026/09/25/vg-2026-initiated-ordinance-311-force-feeding-birds-ban-voter-guide/",
    "https://hoodline.com/2026/09/denver-voters-to-decide-foie-gras-ban-restaurants-face-5-000-fines/",
    "https://www.axios.com/local/denver/2026/10/16/denver-ballot-measures-explained-2026"
   ]
  },
  "ban_status": {
   "forecasts": {
    "yes_50.5": {"repealed": 0.15, "congress": 0.045, "court": 0.04, "not_certified": 0.27, "certified": 0.495},
    "yes_60.0": {"repealed": 0.09, "congress": 0.04, "court": 0.035, "not_certified": 0.25, "certified": 0.585},
    "yes_72.0": {"repealed": 0.05, "congress": 0.04, "court": 0.03, "not_certified": 0.23, "certified": 0.65}
   },
   "reasoning": "The Council repealed I-77 after a 55% win, but it funded I-82 and I-83 and amended rather than repealed them. Foie gras has a small constituency, and the cost is only ~$100k/yr, so funding by the FY2028 budget is likely, especially at large margins. A significant share falls in not_certified because the Council may fund the ban through Budget Support Act language without a formal section 8(b) CFO notice, or Mendelson may delay it. A congressional rider is possible given the 2025-26 House appetite for overriding DC, but foie gras is low priority. A whole-statute injunction is unlikely after National Pork Producers v. Ross.",
   "sources": [
    "https://hoodline.com/2026/08/foie-gras-ban-storms-d-c-ballot-as-city-faces-unfunded-314k-bill/",
    "https://en.wikipedia.org/wiki/Initiative_77",
    "https://www.axios.com/local/washington-dc/2026/10/21/dc-foie-gras-ban-ballot-initiative-fight"
   ]
  },
  "lawsuit_filed": {
   "forecasts": {
    "yes_50.5|blocked": {"p": 1.0},
    "yes_50.5|not_blocked": {"p": 0.45},
    "yes_60.0|blocked": {"p": 1.0},
    "yes_60.0|not_blocked": {"p": 0.42},
    "yes_72.0|blocked": {"p": 0.99},
    "yes_72.0|not_blocked": {"p": 0.4}
   },
   "reasoning": "Foie gras producers (Hudson Valley Foie Gras, and Association des Éleveurs in California) have sued over the California and NYC bans. Axios reports legal threats in DC, and the broad 'fattened' definition invites a vagueness challenge. But DC is a small market, and the Ross precedent weakens commerce-clause claims. A court block requires a lawsuit.",
   "sources": [
    "https://www.axios.com/local/washington-dc/2026/10/21/dc-foie-gras-ban-ballot-initiative-fight",
    "https://news.bloomberglaw.com/ip-law/new-york-citys-foie-gras-ban-is-revived-by-state-appeals-court"
   ]
  },
  "fattened_narrowed": {
   "forecasts": {
    "yes_50.5|certified": {"p": 0.35},
    "yes_50.5|not_certified": {"p": 0.2}
   },
   "reasoning": "Read literally, section 3(3) covers liver from birds 'fattened through any method'. DOEE or the Council would likely clarify that it targets force-feeding, but DC final rulemaking is slow, and guidance or FAQs don't count. A funded, active DOEE program makes a final rule within ~18 months more plausible.",
   "sources": [
    "https://proanimaldc.org/faq/"
   ]
  },
  "pate_treated_banned": {
   "forecasts": {
    "yes_50.5|narrowed_certified": {"p": 0.01},
    "yes_50.5|narrowed_not_certified": {"p": 0.01},
    "yes_50.5|not_narrowed_certified": {"p": 0.04},
    "yes_50.5|not_narrowed_not_certified": {"p": 0.02}
   },
   "reasoning": "The sponsor, the CFO and DOEE all frame the ban as covering force-fed products. One enforcement inspector who doesn't check back-of-house is very unlikely to cite chicken-liver pâté. The only real risk is an over-literal complaint-driven determination when the definition hasn't been narrowed.",
   "sources": [
    "https://dcboe.org/getmedia/8ed77952-835c-4a11-9fa2-2ad447d82643/Final-FIS-Initiative-Prohibiting-the-Force-Feeding-of-Birds-Act-of-2026.pdf"
   ]
  },
  "foie_gras_menus": {
   "baseline": {
    "value": 35,
    "as_of": "2026-10",
    "source": "Estimate between Pro-Animal DC's ~50 served over the past year (many seasonal) and the CSU Animal-Human Policy Center's 17 confirmed; via Washingtonian/NOTUS and City Cast DC"
   },
   "forecasts": {
    "yes_49.5|failed": {"p05": 18, "p25": 26, "p50": 32, "p75": 39, "p95": 50},
    "yes_50.5|removed": {"p05": 14, "p25": 22, "p50": 28, "p75": 35, "p95": 46},
    "yes_50.5|not_certified": {"p05": 1, "p25": 4, "p50": 8, "p75": 14, "p95": 25},
    "yes_50.5|certified": {"p05": 0, "p25": 1, "p50": 2, "p75": 4, "p95": 9}
   },
   "reasoning": "Without a ban, slow voluntary attrition continues under activist pressure. If the ban is removed, some restaurants that dropped foie gras in 2027 never bring it back. When the ban stands, most restaurants comply because of reputational risk and $1-5k per-day fines. Uncertainty about enforceability under not_certified leaves more holdouts.",
   "sources": [
    "https://www.notus.org/metro/foie-gras-ban-washington-dc",
    "https://dc.citycast.fm/food-drink/i86-jose-andres-dc-foie-gras"
   ]
  },
  "liver_pate_menus": {
   "baseline": {
    "value": 150,
    "as_of": "2026-10",
    "source": "Own estimate: chicken-liver pâté/mousse is common on DC bistro, wine-bar and deli menus (~2,500+ food service establishments)"
   },
   "forecasts": {
    "yes_49.5|failed": {"p05": 90, "p25": 125, "p50": 150, "p75": 180, "p95": 230},
    "yes_50.5|removed": {"p05": 90, "p25": 125, "p50": 150, "p75": 180, "p95": 230},
    "yes_50.5|standing_pate_allowed": {"p05": 80, "p25": 115, "p50": 142, "p75": 172, "p95": 222},
    "yes_50.5|standing_pate_banned": {"p05": 30, "p25": 60, "p50": 90, "p75": 125, "p95": 180}
   },
   "reasoning": "Liver pâté is widespread and unaffected unless DOEE treats it as covered. A small chilling effect is possible from the broad definition. If enforcement against pâté actually happens, many venues would relabel or drop it, but not all within the window.",
   "sources": []
  },
  "us_ducks_force_fed_2030": {
   "baseline": {
    "value": 350000,
    "as_of": "2026",
    "source": "Own estimate: Hudson Valley Foie Gras and La Belle Farms are the two main US producers, reported at a few hundred thousand ducks per year combined; no official data"
   },
   "forecasts": {
    "yes_49.5|failed": {"p05": 150000, "p25": 260000, "p50": 320000, "p75": 380000, "p95": 470000},
    "yes_50.5|not_certified_or_removed": {"p05": 140000, "p25": 250000, "p50": 312000, "p75": 372000, "p95": 465000},
    "yes_50.5|certified": {"p05": 130000, "p25": 245000, "p50": 305000, "p75": 365000, "p95": 460000},
    "yes_49.5|failed_placeholder_removed": null
   },
   "reasoning": "US production is concentrated at two New York farms. DC is a top market but a small share of national volume. NYC enforcement (possible by 2030) and Denver matter more, and DC's effect is a few percent at most.",
   "sources": [
    "https://news.bloomberglaw.com/ip-law/new-york-citys-foie-gras-ban-is-revived-by-state-appeals-court"
   ]
  },
  "dc_restaurant_employment_2029": {
   "baseline": {
    "value": 51.5,
    "as_of": "2026-09",
    "source": "BLS SMU11000007072200001 via FRED (per brief)"
   },
   "forecasts": {
    "yes_49.5|failed": {"p05": 46.0, "p25": 50.0, "p50": 52.3, "p75": 54.3, "p95": 57.5},
    "yes_50.5|not_certified_or_removed": {"p05": 46.0, "p25": 50.0, "p75": 54.3, "p50": 52.3, "p95": 57.5},
    "yes_50.5|certified": {"p05": 45.9, "p25": 49.9, "p50": 52.25, "p75": 54.25, "p95": 57.45}
   },
   "reasoning": "Recovery is slow after federal workforce cuts, and the recession risk is broad. A foie gras ban affects a few dozen menu items and has negligible employment effect (<0.1k).",
   "sources": [
    "https://fred.stlouisfed.org/series/SMU11000007072200001",
    "https://ora-cfo.dc.gov/node/1824291"
   ]
  },
  "dc_restaurant_sales_tax_fy2029": {
   "baseline": {
    "value": 567.9,
    "as_of": "FY2025",
    "source": "DC CFO ORA, 'DC Restaurant Sector Lags Hotel and Other Retail in Post-pandemic Recovery', 2026-04-14"
   },
   "forecasts": {
    "yes_49.5|failed": {"p05": 525, "p25": 585, "p50": 618, "p75": 650, "p95": 705},
    "yes_50.5|not_certified_or_removed": {"p05": 525, "p25": 585, "p50": 618, "p75": 650, "p95": 705},
    "yes_50.5|certified": {"p05": 524, "p25": 584, "p50": 617.5, "p75": 649.5, "p95": 704.5}
   },
   "reasoning": "I assume ~2-2.5%/yr nominal growth from the FY2025 base, given a lagging restaurant sector and federal cuts, with recession downside. Foie gras sales are worth well under $1M/yr in tax and mostly substitute into other dishes.",
   "sources": [
    "https://ora-cfo.dc.gov/node/1824291"
   ]
  },
  "dc_michelin_starred_2029": {
   "baseline": {
    "value": 21,
    "as_of": "2026-09-17",
    "source": "Washingtonian: DC guide lists 20 starred restaurants plus the Inn at Little Washington (Gravitas closed); next ceremony 2026-12-14"
   },
   "forecasts": {
    "yes_49.5|failed": {"p05": 14, "p25": 18, "p50": 20, "p75": 23, "p95": 27},
    "yes_50.5|not_certified_or_removed": {"p05": 14, "p25": 18, "p50": 20, "p75": 23, "p95": 27},
    "yes_50.5|certified": {"p05": 14, "p25": 18, "p50": 20, "p75": 23, "p95": 27}
   },
   "reasoning": "The count has been stable at ~20-25 for years, with closures balanced by additions, and the 2025 edition added no new stars. Michelin doesn't penalize foie gras bans; California and NYC keep many stars.",
   "sources": [
    "https://washingtonian.com/2026/09/17/michelin-adds-4-new-restaurants-to-its-dc-guide/",
    "https://wtop.com/business-finance/2025/11/michelin-guide-doesnt-include-any-new-stars-for-dc-restaurants/",
    "https://en.wikipedia.org/wiki/List_of_Michelin-starred_restaurants_in_Washington,_D.C."
   ]
  },
  "dc_animal_initiative_filed": {
   "forecasts": {
    "yes_42.0": {"p": 0.1},
    "yes_49.5": {"p": 0.15},
    "yes_50.5": {"p": 0.24},
    "yes_60.0": {"p": 0.32},
    "yes_72.0": {"p": 0.4}
   },
   "reasoning": "Pro-Animal Future runs serial city ballot campaigns (Portland, Denver, DC, with Portland and others next). A big DC win could prompt a follow-up filing, such as a fur sales ban, by 2028. DC has no farms or slaughterhouses, which limits targets, and the group may prefer new cities.",
   "sources": [
    "https://news.ballotpedia.org/2026/08/06/voters-in-washington-d-c-and-denver-colorado-will-decide-on-foie-gras-ban-ballot-initiatives-in-november/",
    "https://washingtonian.com/2025/11/07/a-foie-gras-ban-could-potentially-end-up-on-dcs-ballot-next-year/"
   ]
  },
  "dc_another_animal_law": {
   "forecasts": {
    "yes_42.0|filed": {"p": 0.2},
    "yes_42.0|not_filed": {"p": 0.09},
    "yes_49.5|filed": {"p": 0.25},
    "yes_49.5|not_filed": {"p": 0.1},
    "yes_50.5|filed": {"p": 0.3},
    "yes_50.5|not_filed": {"p": 0.12},
    "yes_60.0|filed": {"p": 0.35},
    "yes_60.0|not_filed": {"p": 0.13},
    "yes_72.0|filed": {"p": 0.4},
    "yes_72.0|not_filed": {"p": 0.15}
   },
   "reasoning": "The Council base rate for farmed-animal or fur sales laws is low; past fur-ban bills stalled. A filed initiative must still qualify (~50%) and pass by 2030. A large I-86 margin signals voter appetite, both for an initiative and for Council action.",
   "sources": []
  },
  "dc_council_farmed_animal_bills": {
   "forecasts": {
    "yes_42.0": {"p05": 0, "p25": 1, "p50": 1, "p75": 3, "p95": 6},
    "yes_49.5": {"p05": 0, "p25": 1, "p50": 2, "p75": 3, "p95": 6},
    "yes_50.5": {"p05": 0, "p25": 1, "p50": 2, "p75": 3, "p95": 7},
    "yes_60.0": {"p05": 0, "p25": 1, "p50": 2, "p75": 4, "p95": 7},
    "yes_72.0": {"p05": 0, "p25": 1, "p50": 2, "p75": 4, "p95": 8}
   },
   "reasoning": "There are two Council periods in the window. Animal bills (fur, cage-free procurement, wildlife) show up occasionally, and the farmed-animal ones are rare. A strong vote nudges members to introduce bills.",
   "sources": []
  },
  "paf_measures_2027_2028": {
   "forecasts": {
    "yes_42.0|denver_pass": {"0": 0.2, "1": 0.33, "2": 0.27, "3": 0.12, "4": 0.05, "5+": 0.03},
    "yes_42.0|denver_fail": {"0": 0.35, "1": 0.33, "2": 0.2, "3": 0.08, "4": 0.03, "5+": 0.01},
    "yes_49.5|denver_pass": {"0": 0.18, "1": 0.32, "2": 0.28, "3": 0.13, "4": 0.06, "5+": 0.03},
    "yes_49.5|denver_fail": {"0": 0.32, "1": 0.33, "2": 0.21, "3": 0.09, "4": 0.04, "5+": 0.01},
    "yes_50.5|denver_pass": {"0": 0.15, "1": 0.3, "2": 0.29, "3": 0.15, "4": 0.07, "5+": 0.04},
    "yes_50.5|denver_fail": {"0": 0.28, "1": 0.33, "2": 0.22, "3": 0.1, "4": 0.05, "5+": 0.02},
    "yes_60.0|denver_pass": {"0": 0.13, "1": 0.29, "2": 0.3, "3": 0.16, "4": 0.08, "5+": 0.04},
    "yes_60.0|denver_fail": {"0": 0.26, "1": 0.33, "2": 0.23, "3": 0.11, "4": 0.05, "5+": 0.02},
    "yes_72.0|denver_pass": {"0": 0.1, "1": 0.27, "2": 0.31, "3": 0.18, "4": 0.09, "5+": 0.05},
    "yes_72.0|denver_fail": {"0": 0.23, "1": 0.32, "2": 0.25, "3": 0.12, "4": 0.06, "5+": 0.02}
   },
   "reasoning": "Pro-Animal Future has run ~1-2 city measures per cycle: Denver 2024 and DC plus Denver in 2026, with Portland flagged as next. Odd-year ballots are less common. Wins draw donors (Dr. Bronner's) and replication, and losses push the group back toward legislative work.",
   "sources": [
    "https://news.ballotpedia.org/2026/08/06/voters-in-washington-d-c-and-denver-colorado-will-decide-on-foie-gras-ban-ballot-initiatives-in-november/",
    "https://donorbox.org/foie-gras-free-future",
    "https://www.yahoo.com/news/politics/articles/two-us-cities-could-soon-110000398.html"
   ]
  },
  "paf_statewide_2028": {
   "forecasts": {
    "yes_42.0|denver_pass": {"p": 0.06},
    "yes_42.0|denver_fail": {"p": 0.04},
    "yes_49.5|denver_pass": {"p": 0.07},
    "yes_49.5|denver_fail": {"p": 0.045},
    "yes_50.5|denver_pass": {"p": 0.075},
    "yes_50.5|denver_fail": {"p": 0.05},
    "yes_60.0|denver_pass": {"p": 0.085},
    "yes_60.0|denver_fail": {"p": 0.055},
    "yes_72.0|denver_pass": {"p": 0.1},
    "yes_72.0|denver_fail": {"p": 0.065}
   },
   "reasoning": "The group works at the city level with a budget of a few hundred thousand dollars. Statewide qualification costs millions, and the question requires a measure on chickens, pigs, cattle or fish. Two wins raise the odds modestly, e.g., an Oregon or Colorado effort.",
   "sources": [
    "https://www.yahoo.com/news/politics/articles/two-us-cities-could-soon-110000398.html"
   ]
  },
  "us_new_coverage_2027_2032": {
   "forecasts": {
    "yes_42.0|statewide": {"p05": 3, "p25": 9, "p50": 20, "p75": 42, "p95": 95},
    "yes_42.0|no_statewide": {"p05": 2, "p25": 7, "p50": 15, "p75": 32, "p95": 75},
    "yes_49.5|statewide": {"p05": 3, "p25": 9, "p50": 21, "p75": 43, "p95": 96},
    "yes_49.5|no_statewide": {"p05": 2, "p25": 7, "p50": 15, "p75": 33, "p95": 76},
    "yes_50.5|statewide": {"p05": 3, "p25": 10, "p50": 22, "p75": 45, "p95": 98},
    "yes_50.5|no_statewide": {"p05": 2, "p25": 7, "p50": 16, "p75": 34, "p95": 78},
    "yes_60.0|statewide": {"p05": 3, "p25": 10, "p50": 23, "p75": 46, "p95": 100},
    "yes_60.0|no_statewide": {"p05": 2, "p25": 8, "p50": 17, "p75": 35, "p95": 80},
    "yes_72.0|statewide": {"p05": 3, "p25": 11, "p50": 24, "p75": 48, "p95": 104},
    "yes_72.0|no_statewide": {"p05": 2, "p25": 8, "p50": 18, "p75": 37, "p95": 82}
   },
   "reasoning": "From 2016 to 2023, about ten states adopted cage-free or crate laws, but the pace has slowed. Federal preemption (Save Our Bacon Act) could chill new laws. Over six years, expect a few mid-size states or cities, e.g., cage-free laws in NJ/NY-type legislatures. A qualified PAF statewide measure adds a state's population if it passes.",
   "sources": [
    "https://www.spotlightpa.org/news/2026/06/farm-bill-save-our-bacon-act-animal-welfare-state-laws-federal-government/"
   ]
  },
  "other_foie_gras_bans_2030": {
   "baseline": {
    "value": 1,
    "as_of": "2026-10-25",
    "source": "California (in force). NYC's 2019 ban was revived on appeal in March 2026 but remains enjoined pending a final ruling (Bloomberg Law; UPC)"
   },
   "forecasts": {
    "yes_49.5": {"p05": 1, "p25": 2, "p50": 2, "p75": 3, "p95": 5},
    "yes_50.5": {"p05": 1, "p25": 2, "p50": 2, "p75": 3, "p95": 6}
   },
   "reasoning": "California is near-certain to remain in force. NYC enforcement by 2030 is ~60% likely. Denver counts if IO 311 passes (~0.65) and survives, and Portland or other cities are possible. A DC pass slightly increases replication.",
   "sources": [
    "https://news.bloomberglaw.com/ip-law/new-york-citys-foie-gras-ban-is-revived-by-state-appeals-court",
    "https://upc-online.org/ducks/260314_court_clears_way_for_nyc_foie_gras_ban-but_obstacles_remain.html"
   ]
  },
  "federal_preemption_2030": {
   "forecasts": {
    "yes_49.5": {"p": 0.22},
    "yes_50.5": {"p": 0.22}
   },
   "reasoning": "The House passed the Save Our Bacon Act in its 2026 farm bill (224-200), but the Senate draft omits it, and Boozman says no Democrat supports it. A pork-only compromise in a later farm bill or appropriations bill by 2030 is plausible but faces the filibuster. DC's foie gras vote is irrelevant to this.",
   "sources": [
    "https://www.spotlightpa.org/news/2026/06/farm-bill-save-our-bacon-act-animal-welfare-state-laws-federal-government/",
    "https://meatingplace.com/house-passes-farm-bill-saves-its-bacon/",
    "https://www.brownfieldagnews.com/news/lawmakers-continue-debate-over-proposition-12-in-farm-bill/"
   ]
  },
  "dc_bans_other_food_2030": {
   "forecasts": {
    "yes_49.5": {"p": 0.1},
    "yes_50.5": {"p": 0.11}
   },
   "reasoning": "The main path is an additive or dye ban in the style of California AB 418, as states follow the MAHA-era trend. DC has not moved on this, and FDA action on dyes reduces the need. A foie gras pass barely changes the Council's appetite.",
   "sources": []
  }
 }
}
```