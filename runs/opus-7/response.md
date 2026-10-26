I estimate Initiative 86 is about 94% likely to pass, with a median Yes share near 65%. The opposition is unorganized: no group against it had filed expense reports, the DC restaurant association stopped short of opposing it, and José Andrés only spoke out in the last two weeks. Denver's measure looks less certain because Denver voters rejected two other Pro-Animal measures in 2024. Two baselines are my own estimates, not counts I found: the liver pâté menu count (about 150 places) and US ducks force-fed (about 400,000 a year). I didn't write a plan file because I don't have a write tool here, and the brief asks for the JSON as the final output.

```json
{
 "forecaster": {
  "model": "claude-opus-5-5",
  "prior_context": "none",
  "notes": "Headless run under plan mode; only read-only web research was done. No local files were read. Baselines for liver pate menus and US force-fed duck counts are my own estimates, not counts I verified."
 },
 "research_summary": "I-86 qualified with a record 31,726 valid signatures. Pro-Animal DC spent more than $336k by September, with backing from an Oregon group and Dr. Bronner's. No formal opposition committee has filed expenditure reports. The Restaurant Association of Metropolitan Washington (RAMW) criticized the measure but did not formally oppose it. José Andrés and Bart Hutchins of Butterworth's oppose it, and Hutchins is raising a legal defense fund. The only polls are the sponsors': a 2023 advocacy poll found about 80% support, and a CSU poll found 85% support in Colorado. Pro-Animal DC counts about 50 DC menus with foie gras, and CSU confirmed at least 17. Denver IO 311 has no organized opposition and about 15 restaurants serve foie gras there, but Denver rejected Pro-Animal Future's fur ban (about 43%) and slaughterhouse ban (about 36%) in 2024. NYC's foie gras ban was revived on appeal in March 2026 but remains enjoined until a final ruling. The House farm bill includes the Save Our Bacon Act, the Senate committee bill excludes it, and a prediction market prices preemption at about 5%. The 2025 DC Michelin guide had 26 starred restaurants. The CFO found the initiative unfunded, at $314k over four years.",
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
     "le_51": 0.07,
     "le_52": 0.08,
     "le_53": 0.095,
     "le_55": 0.13,
     "le_60": 0.27,
     "le_65": 0.5,
     "le_70": 0.73,
     "le_75": 0.88,
     "le_80": 0.96,
     "le_85": 0.99,
     "le_90": 0.998
    }
   },
   "reasoning": "DC voters are very progressive and pass most initiatives: I-71 got 65%, I-77 56%, I-82 74%. A foie gras ban polls far better than other animal measures, and there is no funded opposition campaign. The risks are late opposition from chefs led by Andrés, a freedom-to-choose message, and the poor results of Pro-Animal Future's Denver measures in 2024. My median is about 65% Yes, with roughly a 6% chance it fails.",
   "sources": [
    "https://www.axios.com/local/washington-dc/2026/10/21/dc-foie-gras-ban-ballot-initiative-fight",
    "https://washingtondcmagazine.substack.com/p/dc-voters-will-decide-november-3",
    "https://dc.citycast.fm/food-drink/i86-jose-andres-dc-foie-gras",
    "https://www.popville.com/2026/08/force-fed-foie-gras-prohibition-dc-i86-qualifies-for-nov-ballot/"
   ]
  },
  "turnout": {
   "forecasts": {
    "all": {
     "p05": 150000,
     "p25": 185000,
     "p50": 205000,
     "p75": 228000,
     "p95": 265000
    }
   },
   "reasoning": "The 2022 midterm general had about 205k ballots, and I-82 drew a similar number of Yes plus No votes. In 2026 the mayor's seat is open and every voter gets a mail ballot, which may raise turnout somewhat. Undervotes on initiatives typically run 5-10%.",
   "sources": [
    "https://en.wikipedia.org/wiki/Initiative_82",
    "https://en.wikipedia.org/wiki/2026_Washington,_D.C.,_mayoral_election"
   ]
  },
  "denver_io311_passes": {
   "forecasts": {
    "yes_42.0": {
     "p": 0.35
    },
    "yes_49.5": {
     "p": 0.6
    },
    "yes_50.5": {
     "p": 0.62
    },
    "yes_60.0": {
     "p": 0.76
    },
    "yes_72.0": {
     "p": 0.88
    }
   },
   "reasoning": "Denver has no organized opposition and only about 15 restaurants serve foie gras there. However, the 2024 Pro-Animal Future fur and slaughterhouse measures lost badly. Overall I put passage near 78%. A weak DC result signals that voters dislike the issue or the sponsor, so Denver's odds fall; a strong DC result raises them. The bare-fail and bare-pass DC cells differ only slightly.",
   "sources": [
    "https://hoodline.com/2026/09/denver-voters-to-decide-foie-gras-ban-restaurants-face-5-000-fines/",
    "https://www.westword.com/news/animal-rights-ballot-measures-lose-big-in-colorado-22451796/",
    "https://denverite.com/2026/09/25/vg-2026-initiated-ordinance-311-force-feeding-birds-ban-voter-guide/"
   ]
  },
  "ban_status": {
   "forecasts": {
    "yes_50.5": {
     "repealed": 0.14,
     "congress": 0.05,
     "court": 0.05,
     "not_certified": 0.28,
     "certified": 0.48
    },
    "yes_60.0": {
     "repealed": 0.07,
     "congress": 0.045,
     "court": 0.05,
     "not_certified": 0.27,
     "certified": 0.565
    },
    "yes_72.0": {
     "repealed": 0.04,
     "congress": 0.04,
     "court": 0.05,
     "not_certified": 0.25,
     "certified": 0.62
    }
   },
   "reasoning": "The Council repealed I-77 and has amended other initiatives, but foie gras matters little to it, so repeal is mainly a risk after a narrow win. A congressional rider is possible but this is a low-priority target. Courts have upheld similar bans: the Ninth Circuit upheld California's, and Pork Producers v. Ross weakens commerce-clause challenges. The only injunction precedent is NYC's, which rests on New York state law that does not apply in DC. The $109k a year in costs is small, but the DC budget is tight. I-83 (ranked-choice voting) was left unfunded for a year before it was funded, so funding and certification by December 2028 are likely but not assured.",
   "sources": [
    "https://dcboe.org/getmedia/8ed77952-835c-4a11-9fa2-2ad447d82643/Final-FIS-Initiative-Prohibiting-the-Force-Feeding-of-Birds-Act-of-2026.pdf",
    "https://hoodline.com/2026/03/foie-gras-war-flares-as-nyc-wins-big-in-ban-fight/",
    "https://en.wikipedia.org/wiki/Initiative_77"
   ]
  },
  "lawsuit_filed": {
   "forecasts": {
    "yes_50.5|blocked": {
     "p": 0.99
    },
    "yes_50.5|not_blocked": {
     "p": 0.5
    },
    "yes_60.0|blocked": {
     "p": 0.99
    },
    "yes_60.0|not_blocked": {
     "p": 0.47
    },
    "yes_72.0|blocked": {
     "p": 0.99
    },
    "yes_72.0|not_blocked": {
     "p": 0.45
    }
   },
   "reasoning": "Hudson Valley Foie Gras and La Belle Farm sued over both the California and NYC bans, and Hutchins is raising a legal fund. The broad definition of 'fattened' invites a vagueness or preemption challenge. On the other hand, producers' legal resources are stretched by the NYC fight and DC is a small market. A court block requires a lawsuit, so `blocked` is near 1.",
   "sources": [
    "https://www.axios.com/local/washington-dc/2026/10/21/dc-foie-gras-ban-ballot-initiative-fight",
    "https://hoodline.com/2026/03/foie-gras-war-flares-as-nyc-wins-big-in-ban-fight/"
   ]
  },
  "fattened_narrowed": {
   "forecasts": {
    "yes_50.5|certified": {
     "p": 0.42
    },
    "yes_50.5|not_certified": {
     "p": 0.22
    }
   },
   "reasoning": "Section 3(3) defines the product as liver from birds 'fattened through any method', which could literally reach chicken-liver pâté. That gives DOEE reason to narrow it in rules, or the Council in an amendment. But final DOEE rules often slip, and if the ban isn't certified, DOEE is less likely to act at all.",
   "sources": [
    "https://proanimaldc.org/prohibit-force-feeding-of-birds-act/"
   ]
  },
  "pate_treated_banned": {
   "forecasts": {
    "yes_50.5|narrowed_certified": {
     "p": 0.01
    },
    "yes_50.5|narrowed_not_certified": {
     "p": 0.005
    },
    "yes_50.5|not_narrowed_certified": {
     "p": 0.04
    },
    "yes_50.5|not_narrowed_not_certified": {
     "p": 0.015
    }
   },
   "reasoning": "The CFO says DOEE will not inspect kitchens, its enforcement is driven by complaints, and both the sponsor and the ballot summary describe a ban on force-fed products. A written ruling that treats chicken-liver pâté as covered is very unlikely, and even less so after the definition is narrowed or if the ban is unfunded.",
   "sources": [
    "https://dcboe.org/getmedia/8ed77952-835c-4a11-9fa2-2ad447d82643/Final-FIS-Initiative-Prohibiting-the-Force-Feeding-of-Birds-Act-of-2026.pdf"
   ]
  },
  "foie_gras_menus": {
   "baseline": {
    "value": 45,
    "as_of": "2026-10",
    "source": "Pro-Animal DC identified nearly 50 menus and CSU confirmed at least 17 (Washington DC Magazine substack; City Cast DC says about 50)"
   },
   "forecasts": {
    "yes_49.5|failed": {
     "p05": 22,
     "p25": 32,
     "p50": 40,
     "p75": 48,
     "p95": 60
    },
    "yes_50.5|removed": {
     "p05": 18,
     "p25": 28,
     "p50": 36,
     "p75": 45,
     "p95": 58
    },
    "yes_50.5|not_certified": {
     "p05": 2,
     "p25": 7,
     "p50": 14,
     "p75": 24,
     "p95": 38
    },
    "yes_50.5|certified": {
     "p05": 0,
     "p25": 1,
     "p50": 4,
     "p75": 8,
     "p95": 16
    }
   },
   "reasoning": "The baseline is about 45, based on Pro-Animal DC's count of nearly 50 menus. Protests and menu turnover cause a slow decline even if the measure fails. If the ban stands and is certified, most restaurants comply; the few left are holdouts or sell 'gavage-free' foie gras, which still counts. If the ban stands but is uncertified, its legal status is ambiguous and compliance is partial.",
   "sources": [
    "https://washingtondcmagazine.substack.com/p/dc-voters-will-decide-november-3",
    "https://dc.citycast.fm/food-drink/i86-jose-andres-dc-foie-gras"
   ]
  },
  "liver_pate_menus": {
   "baseline": {
    "value": 150,
    "as_of": "2026-10",
    "source": "My own estimate: chicken-liver mousse or pâté and chopped liver are common on DC bistro, deli and New American menus. No published count found."
   },
   "forecasts": {
    "yes_49.5|failed": {
     "p05": 90,
     "p25": 125,
     "p50": 150,
     "p75": 180,
     "p95": 230
    },
    "yes_50.5|removed": {
     "p05": 90,
     "p25": 125,
     "p50": 150,
     "p75": 180,
     "p95": 230
    },
    "yes_50.5|standing_pate_allowed": {
     "p05": 85,
     "p25": 118,
     "p50": 143,
     "p75": 172,
     "p95": 222
    },
    "yes_50.5|standing_pate_banned": {
     "p05": 30,
     "p25": 60,
     "p50": 90,
     "p75": 120,
     "p95": 170
    }
   },
   "reasoning": "This baseline is my estimate, not a count. Pâté is unaffected unless enforcement reaches it. Even then, one DOEE ruling would cause partial, uneven removal, not a full purge. If pâté is allowed, a slight chilling effect from the broad definition remains.",
   "sources": []
  },
  "us_ducks_force_fed_2030": {
   "baseline": {
    "value": 400000,
    "as_of": "2025",
    "source": "Rough estimate from press reports on Hudson Valley Foie Gras (about 300k+/yr) and La Belle Farm. Producers do not publish volumes."
   },
   "forecasts": {
    "yes_49.5|failed": {
     "p05": 150000,
     "p25": 250000,
     "p50": 320000,
     "p75": 390000,
     "p95": 480000
    },
    "yes_50.5|not_certified_or_removed": {
     "p05": 145000,
     "p25": 245000,
     "p50": 315000,
     "p75": 385000,
     "p95": 475000
    },
    "yes_50.5|certified": {
     "p05": 140000,
     "p25": 235000,
     "p50": 305000,
     "p75": 375000,
     "p95": 465000
    }
   },
   "reasoning": "Two New York farms dominate US production. The likely enforcement of NYC's ban by 2030 is the main driver of decline. DC is only a few percent of demand, so its effect on production is small.",
   "sources": [
    "https://hoodline.com/2026/03/foie-gras-war-flares-as-nyc-wins-big-in-ban-fight/"
   ]
  },
  "dc_restaurant_employment_2029": {
   "baseline": {
    "value": 51.5,
    "as_of": "2026-09",
    "source": "BLS SMU11000007072200001 via FRED (given in brief)"
   },
   "forecasts": {
    "yes_49.5|failed": {
     "p05": 45.5,
     "p25": 49.5,
     "p50": 51.8,
     "p75": 54.0,
     "p95": 57.5
    },
    "yes_50.5|not_certified_or_removed": {
     "p05": 45.5,
     "p25": 49.5,
     "p50": 51.8,
     "p75": 54.0,
     "p95": 57.5
    },
    "yes_50.5|certified": {
     "p05": 45.5,
     "p25": 49.5,
     "p50": 51.8,
     "p75": 54.0,
     "p95": 57.5
    }
   },
   "reasoning": "DC's economy is soft after federal job cuts, but restaurant employment has been flat to slowly growing; recession risk drives the tails. A product ban affecting about 45 menus has no measurable employment effect.",
   "sources": [
    "https://ora-cfo.dc.gov/node/1824291"
   ]
  },
  "dc_restaurant_sales_tax_fy2029": {
   "baseline": {
    "value": 567.9,
    "as_of": "FY2025",
    "source": "DC ORA, 'DC Restaurant Sector Lags Hotel and Other Retail in Post-pandemic Recovery', 2026-04-14"
   },
   "forecasts": {
    "yes_49.5|failed": {
     "p05": 540,
     "p25": 590,
     "p50": 618,
     "p75": 645,
     "p95": 690
    },
    "yes_50.5|not_certified_or_removed": {
     "p05": 540,
     "p25": 590,
     "p50": 618,
     "p75": 645,
     "p95": 690
    },
    "yes_50.5|certified": {
     "p05": 540,
     "p25": 590,
     "p50": 617.5,
     "p75": 645,
     "p95": 690
    }
   },
   "reasoning": "I assume about 2% a year nominal growth from FY2025's $567.9M. Diners substitute other dishes, so the ban's revenue effect is negligible.",
   "sources": [
    "https://ora-cfo.dc.gov/node/1824291"
   ]
  },
  "dc_michelin_starred_2029": {
   "baseline": {
    "value": 26,
    "as_of": "2025-11",
    "source": "WTOP on the 2025 DC Michelin Guide: 3 two-star and 23 one-star restaurants"
   },
   "forecasts": {
    "yes_49.5|failed": {
     "p05": 19,
     "p25": 23,
     "p50": 25,
     "p75": 28,
     "p95": 31
    },
    "yes_50.5|not_certified_or_removed": {
     "p05": 19,
     "p25": 23,
     "p50": 25,
     "p75": 28,
     "p95": 31
    },
    "yes_50.5|certified": {
     "p05": 19,
     "p25": 23,
     "p50": 25,
     "p75": 27,
     "p95": 31
    }
   },
   "reasoning": "The star count has been stable at 24-26 and the guide added no new stars in 2025. Closures pose a slight downside risk. Michelin stars restaurants in California and other places with foie gras bans, so the ban has essentially no effect.",
   "sources": [
    "https://wtop.com/business-finance/2025/11/michelin-guide-doesnt-include-any-new-stars-for-dc-restaurants/",
    "https://en.wikipedia.org/wiki/List_of_Michelin-starred_restaurants_in_Washington,_D.C."
   ]
  },
  "dc_animal_initiative_filed": {
   "forecasts": {
    "yes_42.0": {
     "p": 0.14
    },
    "yes_49.5": {
     "p": 0.2
    },
    "yes_50.5": {
     "p": 0.28
    },
    "yes_60.0": {
     "p": 0.36
    },
    "yes_72.0": {
     "p": 0.45
    }
   },
   "reasoning": "Pro-Animal Future escalates where it wins; after Denver it said it is 'in this for the long haul'. A strong DC win plus a record signature operation makes a second DC initiative (fur, cage-free and similar) plausible. A loss makes one less likely, and a refiled I-86 does not count.",
   "sources": [
    "https://www.westword.com/news/animal-rights-ballot-measures-lose-big-in-colorado-22451796/"
   ]
  },
  "dc_another_animal_law": {
   "forecasts": {
    "yes_42.0|filed": {
     "p": 0.1
    },
    "yes_42.0|not_filed": {
     "p": 0.04
    },
    "yes_49.5|filed": {
     "p": 0.14
    },
    "yes_49.5|not_filed": {
     "p": 0.05
    },
    "yes_50.5|filed": {
     "p": 0.2
    },
    "yes_50.5|not_filed": {
     "p": 0.06
    },
    "yes_60.0|filed": {
     "p": 0.26
    },
    "yes_60.0|not_filed": {
     "p": 0.07
    },
    "yes_72.0|filed": {
     "p": 0.33
    },
    "yes_72.0|not_filed": {
     "p": 0.08
    }
   },
   "reasoning": "A filed initiative still has to qualify, pass and survive congressional review by 2030, which roughly halves its chance. The DC Council rarely legislates on farmed animals, so the not-filed path is small and rises only slightly with a strong vote.",
   "sources": []
  },
  "dc_council_farmed_animal_bills": {
   "forecasts": {
    "yes_42.0": {
     "p05": 0,
     "p25": 0,
     "p50": 1,
     "p75": 2,
     "p95": 4
    },
    "yes_49.5": {
     "p05": 0,
     "p25": 0,
     "p50": 1,
     "p75": 2,
     "p95": 4
    },
    "yes_50.5": {
     "p05": 0,
     "p25": 1,
     "p50": 1,
     "p75": 2,
     "p95": 5
    },
    "yes_60.0": {
     "p05": 0,
     "p25": 1,
     "p50": 1,
     "p75": 3,
     "p95": 5
    },
    "yes_72.0": {
     "p05": 0,
     "p25": 1,
     "p50": 2,
     "p75": 3,
     "p95": 6
    }
   },
   "reasoning": "Few DC Council bills have been mainly about farmed animals; the base rate is roughly zero to one per Council period. A strong I-86 margin shows members there are votes in the issue and should prompt a few more bills (cage-free, fur, procurement).",
   "sources": []
  },
  "paf_measures_2027_2028": {
   "forecasts": {
    "yes_42.0|denver_pass": {
     "0": 0.33,
     "1": 0.3,
     "2": 0.2,
     "3": 0.1,
     "4": 0.04,
     "5+": 0.03
    },
    "yes_42.0|denver_fail": {
     "0": 0.5,
     "1": 0.26,
     "2": 0.13,
     "3": 0.06,
     "4": 0.03,
     "5+": 0.02
    },
    "yes_49.5|denver_pass": {
     "0": 0.3,
     "1": 0.3,
     "2": 0.21,
     "3": 0.11,
     "4": 0.05,
     "5+": 0.03
    },
    "yes_49.5|denver_fail": {
     "0": 0.45,
     "1": 0.27,
     "2": 0.15,
     "3": 0.07,
     "4": 0.03,
     "5+": 0.03
    },
    "yes_50.5|denver_pass": {
     "0": 0.25,
     "1": 0.29,
     "2": 0.23,
     "3": 0.13,
     "4": 0.06,
     "5+": 0.04
    },
    "yes_50.5|denver_fail": {
     "0": 0.38,
     "1": 0.29,
     "2": 0.17,
     "3": 0.09,
     "4": 0.04,
     "5+": 0.03
    },
    "yes_60.0|denver_pass": {
     "0": 0.22,
     "1": 0.27,
     "2": 0.24,
     "3": 0.14,
     "4": 0.07,
     "5+": 0.06
    },
    "yes_60.0|denver_fail": {
     "0": 0.35,
     "1": 0.29,
     "2": 0.18,
     "3": 0.1,
     "4": 0.04,
     "5+": 0.04
    },
    "yes_72.0|denver_pass": {
     "0": 0.18,
     "1": 0.25,
     "2": 0.25,
     "3": 0.16,
     "4": 0.08,
     "5+": 0.08
    },
    "yes_72.0|denver_fail": {
     "0": 0.3,
     "1": 0.29,
     "2": 0.2,
     "3": 0.11,
     "4": 0.05,
     "5+": 0.05
    }
   },
   "reasoning": "Pro-Animal Future put two Denver measures on the ballot in 2024 and two foie gras measures in 2026, about two per cycle in friendly cities, funded by a few donors. Wins in 2026 raise expected output for 2027-28, while losses push it toward zero or one.",
   "sources": [
    "https://www.westword.com/news/animal-rights-ballot-measures-lose-big-in-colorado-22451796/",
    "https://www.popville.com/2026/08/force-fed-foie-gras-prohibition-dc-i86-qualifies-for-nov-ballot/"
   ]
  },
  "paf_statewide_2028": {
   "forecasts": {
    "yes_42.0|denver_pass": {
     "p": 0.04
    },
    "yes_42.0|denver_fail": {
     "p": 0.025
    },
    "yes_49.5|denver_pass": {
     "p": 0.05
    },
    "yes_49.5|denver_fail": {
     "p": 0.03
    },
    "yes_50.5|denver_pass": {
     "p": 0.065
    },
    "yes_50.5|denver_fail": {
     "p": 0.04
    },
    "yes_60.0|denver_pass": {
     "p": 0.08
    },
    "yes_60.0|denver_fail": {
     "p": 0.05
    },
    "yes_72.0|denver_pass": {
     "p": 0.11
    },
    "yes_72.0|denver_fail": {
     "p": 0.07
    }
   },
   "reasoning": "Pro-Animal Future has run only city campaigns so far. Qualifying a statewide measure costs millions, and Oregon's IP-28, run by another group, failed to qualify in 2026. Broad wins in 2026 raise the low chance of a statewide attempt.",
   "sources": [
    "https://capitalpress.com/2026/07/27/oregon-farmers-relieved-ip-28-failed-to-make-ballot/"
   ]
  },
  "us_new_coverage_2027_2032": {
   "forecasts": {
    "yes_42.0|statewide": {
     "p05": 0.5,
     "p25": 4,
     "p50": 12,
     "p75": 30,
     "p95": 75
    },
    "yes_42.0|no_statewide": {
     "p05": 0,
     "p25": 1.5,
     "p50": 6,
     "p75": 18,
     "p95": 55
    },
    "yes_49.5|statewide": {
     "p05": 0.5,
     "p25": 4.5,
     "p50": 13,
     "p75": 32,
     "p95": 78
    },
    "yes_49.5|no_statewide": {
     "p05": 0,
     "p25": 1.8,
     "p50": 6.5,
     "p75": 19,
     "p95": 57
    },
    "yes_50.5|statewide": {
     "p05": 0.6,
     "p25": 5,
     "p50": 14,
     "p75": 34,
     "p95": 80
    },
    "yes_50.5|no_statewide": {
     "p05": 0,
     "p25": 2,
     "p50": 7,
     "p75": 20,
     "p95": 58
    },
    "yes_60.0|statewide": {
     "p05": 0.7,
     "p25": 5.5,
     "p50": 15,
     "p75": 36,
     "p95": 82
    },
    "yes_60.0|no_statewide": {
     "p05": 0,
     "p25": 2.2,
     "p50": 7.5,
     "p75": 21,
     "p95": 60
    },
    "yes_72.0|statewide": {
     "p05": 0.8,
     "p25": 6,
     "p50": 16,
     "p75": 38,
     "p95": 85
    },
    "yes_72.0|no_statewide": {
     "p05": 0,
     "p25": 2.5,
     "p50": 8,
     "p75": 22,
     "p95": 62
    }
   },
   "reasoning": "From 2017 to 2023 several states passed cage-free laws, adding roughly 1-3 states a cycle; the pace has slowed since. Local foie gras and fur ordinances add little population. A qualified statewide measure adds a state's population if it passes. The right tail comes from a large state acting.",
   "sources": [
    "https://www.humaneworld.org/en/news/whats-happening-california-prop-12-farm-bill-save-our-bacon-act"
   ]
  },
  "other_foie_gras_bans_2030": {
   "baseline": {
    "value": 1,
    "as_of": "2026-10-25",
    "source": "California's state sales ban is in force. NYC Local Law 202 is enjoined pending a final ruling (March 2026 appellate decision). Chicago repealed its ban in 2008."
   },
   "forecasts": {
    "yes_49.5": {
     "p05": 1,
     "p25": 2,
     "p50": 2,
     "p75": 3,
     "p95": 5
    },
    "yes_50.5": {
     "p05": 1,
     "p25": 2,
     "p50": 3,
     "p75": 3,
     "p95": 6
    }
   },
   "reasoning": "California's ban is in force. NYC's ban is likely, at about 60-65%, to be in force by 2030 after appeals. Denver passes at about 75%. A DC pass slightly raises the chance of copycat local bans.",
   "sources": [
    "https://hoodline.com/2026/03/foie-gras-war-flares-as-nyc-wins-big-in-ban-fight/",
    "https://hoodline.com/2026/09/denver-voters-to-decide-foie-gras-ban-restaurants-face-5-000-fines/"
   ]
  },
  "federal_preemption_2030": {
   "forecasts": {
    "yes_49.5": {
     "p": 0.12
    },
    "yes_50.5": {
     "p": 0.125
    }
   },
   "reasoning": "The House passed the Save Our Bacon Act, the Senate committee dropped it, and the market prices it at 5% for this farm bill. Later Congresses through 2030 add more chances. A DC foie gras result barely matters.",
   "sources": [
    "https://tech-insider.org/farm-bill-hr-7567-save-our-bacon-prediction-market/",
    "https://sentientmedia.org/senate-ag-committee-set-to-spare-this-animal-welfare-law/"
   ]
  },
  "dc_bans_other_food_2030": {
   "forecasts": {
    "yes_49.5": {
     "p": 0.15
    },
    "yes_50.5": {
     "p": 0.16
    }
   },
   "reasoning": "States are spreading food-additive and dye bans, such as West Virginia's 2028 dye ban, and the DC Council could follow, but it has no history of banning foods outright. A foie gras pass barely changes that.",
   "sources": []
  }
 }
}
```
