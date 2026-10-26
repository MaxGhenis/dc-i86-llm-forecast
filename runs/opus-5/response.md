```json
{
 "forecaster": {
  "model": "claude-opus-5-5",
  "prior_context": "none",
  "notes": "Only read-only web research was used, and no local files were read. Several news pages (Axios, Denverite, NOTUS) could not be fetched, so I relied on search-result summaries for them. The Oct 2026 menu-count baselines are my estimates between the CSU count (17) and Pro-Animal DC's count (~50); I did not run a menu check myself."
 },
 "research_summary": "Initiative 86 qualified on 2026-08-05 with a record number of valid signatures. Pro-Animal DC had spent more than $336k by September (Dr. Bronner's and an Oregon group were major backers) and cites polls with about 78% support; those polls are sponsor-affiliated. Opponents are mostly high-profile chefs (Butterworth's Bart Hutchins, José Andrés). Axios reports outside spending and legal threats; Hutchins is raising money for a 'foie gras legal defense fund'. Councilmember Robert White endorsed the measure. I found no Council or congressional move to block it yet. The CFO says the measure is unfunded ($314k over 4 years), so section 8(a) makes provisions with a fiscal effect contingent on appropriation. DC initiatives usually pass with 56-76% (I-82 got 73.9% on 179,786 valid votes), but the Council has repealed or rewritten I-77 and I-82. Denver's IO 311 is run by a sister chapter of Pro-Animal Future, whose 2024 Denver measures lost (fur ban 42%, slaughterhouse ban 36%). Foie gras bans are narrower and more popular. California's ban is in force; NYC's is enjoined under state law; Chicago repealed its ban. Hudson Valley Foie Gras and La Belle raise about 350k birds a year. The House farm bill includes Prop 12 preemption (Save Our Bacon); the Senate version omits it and the bill is stalled. DC has about 20 Michelin-starred restaurants.",
 "nodes": {
  "yes_share": {
   "forecasts": {
    "all": {
     "le_30": 0.005,
     "le_35": 0.01,
     "le_40": 0.025,
     "le_45": 0.06,
     "le_47": 0.08,
     "le_48": 0.095,
     "le_49": 0.11,
     "le_50": 0.13,
     "le_51": 0.15,
     "le_52": 0.17,
     "le_53": 0.2,
     "le_55": 0.27,
     "le_60": 0.5,
     "le_65": 0.72,
     "le_70": 0.88,
     "le_75": 0.96,
     "le_80": 0.99,
     "le_85": 0.997,
     "le_90": 0.999
    }
   },
   "reasoning": "Base rate: DC voter initiatives usually pass with 56-76%, and the electorate is progressive. Sponsor polls near 78% overstate support, and the chef-led opposition, José Andrés included, has had a lot of media attention. Pro-Animal Future's 2024 Denver measures underperformed. My median is about 60%, with roughly an 87% chance of passing.",
   "sources": [
    "https://www.axios.com/local/washington-dc/2026/10/21/dc-foie-gras-ban-ballot-initiative-fight",
    "https://dc.citycast.fm/food-drink/i86-jose-andres-dc-foie-gras",
    "https://www.idausa.org/campaign/farmed-animal/latest-news/washington-dc-residents-vote-to-ban-foie-gras-on-nov-3/",
    "https://en.wikipedia.org/wiki/Initiative_82"
   ]
  },
  "turnout": {
   "forecasts": {
    "all": {
     "p05": 158000,
     "p25": 182000,
     "p50": 198000,
     "p75": 214000,
     "p95": 240000
    }
   },
   "reasoning": "In the 2022 midterm, I-82 drew 179,786 Yes+No votes, with about 12% of ballots skipping it. The 2026 midterm should have high national energy and a larger roll, while the general-election mayoral race is uncompetitive. My median is about 198k.",
   "sources": [
    "https://en.wikipedia.org/wiki/Initiative_82"
   ]
  },
  "denver_io311_passes": {
   "forecasts": {
    "yes_42.0": {
     "p": 0.22
    },
    "yes_49.5": {
     "p": 0.4
    },
    "yes_50.5": {
     "p": 0.42
    },
    "yes_60.0": {
     "p": 0.63
    },
    "yes_72.0": {
     "p": 0.85
    }
   },
   "reasoning": "Denver is less progressive than DC, and Pro-Animal Future lost there in 2024 with 42% and 36%. Still, a foie gras ban is the movement's most popular kind of ask and affects only 15-24 restaurants. Unconditionally I put it at about 60%. DC's result is a correlated signal of how voters feel about the same pitch, so the probability rises steeply with DC's Yes share; the 49.5 and 50.5 cells differ by only one point of signal.",
   "sources": [
    "https://hoodline.com/2026/09/denver-voters-to-decide-foie-gras-ban-restaurants-face-5-000-fines/",
    "https://coloradosun.com/2024/11/05/denver-ordinance-309-result/",
    "https://denverite.com/2026/09/25/vg-2026-initiated-ordinance-311-force-feeding-birds-ban-voter-guide/"
   ]
  },
  "ban_status": {
   "forecasts": {
    "yes_50.5": {
     "repealed": 0.15,
     "congress": 0.05,
     "court": 0.07,
     "not_certified": 0.3,
     "certified": 0.43
    },
    "yes_60.0": {
     "repealed": 0.07,
     "congress": 0.05,
     "court": 0.07,
     "not_certified": 0.28,
     "certified": 0.53
    },
    "yes_72.0": {
     "repealed": 0.03,
     "congress": 0.05,
     "court": 0.06,
     "not_certified": 0.25,
     "certified": 0.61
    }
   },
   "reasoning": "Repeal: the Council repealed I-77 and rewrote I-82, but foie gras is low-stakes and has a Council endorser, so repeal is likely only after a bare win. Congress: riders target DC crime and drug policy far more than food, and the House may flip in 2027. Court: California's ban survived its challenges, and DC has no state-preemption route like NYC's, though the broad 'fattened' definition invites a vagueness suit. Certification: the cost is small ($109k a year), but DC budgets are tight and initiatives often wait a cycle or more to be funded. Two budget cycles fall before 2028-12, so certification is more likely than not when the margin is larger.",
   "sources": [
    "https://hoodline.com/2026/08/foie-gras-ban-storms-d-c-ballot-as-city-faces-unfunded-314k-bill/",
    "https://en.wikipedia.org/wiki/Initiative_77",
    "https://www.acludc.org/app/uploads/2025/07/D.C.-Disapproval-Resolutions-and-Riders-5.pdf",
    "https://rollcall.com/2025/07/22/from-traffic-to-vasectomies-congress-takes-aim-at-dc/"
   ]
  },
  "lawsuit_filed": {
   "forecasts": {
    "yes_50.5|blocked": {
     "p": 0.99
    },
    "yes_50.5|not_blocked": {
     "p": 0.6
    },
    "yes_60.0|blocked": {
     "p": 0.99
    },
    "yes_60.0|not_blocked": {
     "p": 0.56
    },
    "yes_72.0|blocked": {
     "p": 0.99
    },
    "yes_72.0|not_blocked": {
     "p": 0.52
    }
   },
   "reasoning": "A court block requires a lawsuit. The New York producers sued over both the California and NYC bans, a DC chef is raising a legal defense fund, and the 'any method' definition of fattened liver is an easy target. Without a block, I put a filing at a bit above even odds. It is somewhat less likely if the ban stays unfunded and unenforced, or if a big win discourages a challenge.",
   "sources": [
    "https://www.axios.com/local/washington-dc/2026/10/21/dc-foie-gras-ban-ballot-initiative-fight",
    "https://www.nbcnewyork.com/entertainment/the-scene/new-york-live/food/nyc-foie-gras-ban-would-be-financially-devastating-farms-say-in-lawsuit/3706656/?amp=1"
   ]
  },
  "fattened_narrowed": {
   "forecasts": {
    "yes_50.5|certified": {
     "p": 0.35
    },
    "yes_50.5|not_certified": {
     "p": 0.18
    }
   },
   "reasoning": "As written, the section 3(3) definition ('fattened through any method') could cover ordinary chicken-liver pâté, and the sponsors' intent is clearly force-feeding only. A DOEE rule or Council technical amendment to fix this is plausible, but agencies are slow and often settle such questions through guidance, which does not count. A narrowing is less likely if no funding has been certified and DOEE has no inspector or rulemaking budget.",
   "sources": [
    "https://proanimaldc.org/faq/"
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
     "p": 0.06
    },
    "yes_50.5|not_narrowed_not_certified": {
     "p": 0.02
    }
   },
   "reasoning": "DOEE inspects front-of-house only and will follow the sponsors' force-feeding focus. Citing chicken-liver pâté would draw a political backlash. Such a citation is a small risk only if the definition is not narrowed and enforcement is funded.",
   "sources": [
    "https://dcboe.org/getmedia/8ed77952-835c-4a11-9fa2-2ad447d82643/Final-FIS-Initiative-Prohibiting-the-Force-Feeding-of-Birds-Act-of-2026.pdf"
   ]
  },
  "foie_gras_menus": {
   "baseline": {
    "value": 35,
    "as_of": "2026-10",
    "source": "Estimate between the CSU Animal-Human Policy Center's confirmed count (17) and Pro-Animal DC's count (~50, many seasonal), as reported by Washingtonian, City Cast DC and NOTUS"
   },
   "forecasts": {
    "yes_49.5|failed": {
     "p05": 18,
     "p25": 26,
     "p50": 32,
     "p75": 40,
     "p95": 52
    },
    "yes_50.5|removed": {
     "p05": 14,
     "p25": 23,
     "p50": 29,
     "p75": 37,
     "p95": 50
    },
    "yes_50.5|not_certified": {
     "p05": 2,
     "p25": 6,
     "p50": 11,
     "p75": 19,
     "p95": 33
    },
    "yes_50.5|certified": {
     "p05": 0,
     "p25": 1,
     "p50": 3,
     "p75": 6,
     "p95": 12
    }
   },
   "reasoning": "If the measure fails, menus stay near the baseline with a mild downward drift. If the ban is removed, a small chilling effect remains. If the ban stands but is uncertified, enforceability is ambiguous: most restaurants drop foie gras, but some keep it while citing section 8(a). If enforcement is funded, compliance should be near-total, as in California, apart from a few holdouts.",
   "sources": [
    "https://washingtonian.com/2026/08/05/foie-gras-ban-will-be-on-dcs-ballot-this-november/",
    "https://dc.citycast.fm/food-drink/i86-jose-andres-dc-foie-gras"
   ]
  },
  "liver_pate_menus": {
   "baseline": {
    "value": 120,
    "as_of": "2026-10",
    "source": "Own estimate, not verified by a menu check: chicken-liver mousse and pâté are common in DC bistros, wine bars and delis"
   },
   "forecasts": {
    "yes_49.5|failed": {
     "p05": 80,
     "p25": 103,
     "p50": 120,
     "p75": 140,
     "p95": 170
    },
    "yes_50.5|removed": {
     "p05": 80,
     "p25": 103,
     "p50": 120,
     "p75": 140,
     "p95": 170
    },
    "yes_50.5|standing_pate_allowed": {
     "p05": 75,
     "p25": 98,
     "p50": 115,
     "p75": 135,
     "p95": 165
    },
    "yes_50.5|standing_pate_banned": {
     "p05": 40,
     "p25": 62,
     "p50": 82,
     "p75": 103,
     "p95": 135
    }
   },
   "reasoning": "Liver pâté is widespread and unaffected unless DOEE treats it as covered. If pâté is allowed, a small chilling effect remains from the ambiguous definition. If DOEE starts citing non-foie-gras pâté, many places pull it or rename it.",
   "sources": []
  },
  "us_ducks_force_fed_2030": {
   "baseline": {
    "value": 350000,
    "as_of": "2019",
    "source": "Hudson Valley Foie Gras and La Belle Farm combined, about 350,000 birds a year (NBC New York / AP)"
   },
   "forecasts": {
    "yes_49.5|failed": {
     "p05": 150000,
     "p25": 250000,
     "p50": 320000,
     "p75": 380000,
     "p95": 470000
    },
    "yes_50.5|not_certified_or_removed": {
     "p05": 145000,
     "p25": 245000,
     "p50": 315000,
     "p75": 375000,
     "p95": 465000
    },
    "yes_50.5|certified": {
     "p05": 140000,
     "p25": 238000,
     "p50": 305000,
     "p75": 365000,
     "p95": 455000
    }
   },
   "reasoning": "US production is concentrated in two New York farms that sell mostly to NYC and other big markets. DC is one market of several, so an enforced DC ban cuts output by only a few percent. There is long-run downside risk from more bans and farm finances.",
   "sources": [
    "https://www.nbcnewyork.com/entertainment/the-scene/new-york-live/food/nyc-foie-gras-ban-would-be-financially-devastating-farms-say-in-lawsuit/3706656/?amp=1"
   ]
  },
  "dc_restaurant_employment_2029": {
   "baseline": {
    "value": 51.5,
    "as_of": "2026-09",
    "source": "BLS SMU11000007072200001 via FRED (per brief)"
   },
   "forecasts": {
    "yes_49.5|failed": {
     "p05": 45.5,
     "p25": 49.3,
     "p50": 51.3,
     "p75": 53.3,
     "p95": 56.5
    },
    "yes_50.5|not_certified_or_removed": {
     "p05": 45.5,
     "p25": 49.3,
     "p50": 51.3,
     "p75": 53.3,
     "p95": 56.5
    },
    "yes_50.5|certified": {
     "p05": 45.5,
     "p25": 49.3,
     "p50": 51.25,
     "p75": 53.3,
     "p95": 56.5
    }
   },
   "reasoning": "Federal workforce cuts hold DC demand down, so employment stays roughly flat from 51.5k. A ban on one ingredient at about 35 restaurants has a negligible effect on employment.",
   "sources": [
    "https://fred.stlouisfed.org/series/SMU11000007072200001"
   ]
  },
  "dc_restaurant_sales_tax_fy2029": {
   "baseline": {
    "value": 567.9,
    "as_of": "FY2025",
    "source": "DC CFO ORA, 'DC Restaurant Sector Lags Hotel and Other Retail in Post-pandemic Recovery', 2026-04-14"
   },
   "forecasts": {
    "yes_49.5|failed": {
     "p05": 540,
     "p25": 595,
     "p50": 628,
     "p75": 660,
     "p95": 715
    },
    "yes_50.5|not_certified_or_removed": {
     "p05": 540,
     "p25": 595,
     "p50": 628,
     "p75": 660,
     "p95": 715
    },
    "yes_50.5|certified": {
     "p05": 540,
     "p25": 595,
     "p50": 627,
     "p75": 660,
     "p95": 715
    }
   },
   "reasoning": "I assume about 2.5% a year of nominal growth from FY2025, with a weak real economy and recession risk. Foie gras is a tiny share of restaurant spending, and diners switch to other dishes, so the ban's effect is negligible.",
   "sources": [
    "https://ora-cfo.dc.gov/node/1824291"
   ]
  },
  "dc_michelin_starred_2029": {
   "baseline": {
    "value": 20,
    "as_of": "2025 guide (Nov 2025)",
    "source": "Michelin Guide DC as summarized by WTOP and Washingtonian: 20 starred DC restaurants plus the Inn at Little Washington (in Virginia)"
   },
   "forecasts": {
    "yes_49.5|failed": {
     "p05": 15,
     "p25": 18,
     "p50": 20,
     "p75": 22,
     "p95": 25
    },
    "yes_50.5|not_certified_or_removed": {
     "p05": 15,
     "p25": 18,
     "p50": 20,
     "p75": 22,
     "p95": 25
    },
    "yes_50.5|certified": {
     "p05": 15,
     "p25": 18,
     "p50": 20,
     "p75": 22,
     "p95": 25
    }
   },
   "reasoning": "The star count is stable at about 20, with closures balanced by additions. California's foie gras ban did not reduce its stars, so I see no ban effect.",
   "sources": [
    "https://wtop.com/business-finance/2025/11/michelin-guide-doesnt-include-any-new-stars-for-dc-restaurants/",
    "https://washingtonian.com/2026/09/17/michelin-adds-4-new-restaurants-to-its-dc-guide/"
   ]
  },
  "dc_animal_initiative_filed": {
   "forecasts": {
    "yes_42.0": {
     "p": 0.1
    },
    "yes_49.5": {
     "p": 0.18
    },
    "yes_50.5": {
     "p": 0.3
    },
    "yes_60.0": {
     "p": 0.38
    },
    "yes_72.0": {
     "p": 0.45
    }
   },
   "reasoning": "Pro-Animal Future runs a sequence of escalating local measures (fur and slaughter in Denver) and now has a DC volunteer base. A win, especially a big one, makes a follow-up DC filing (fur, cage-free, etc.) for 2028 or 2030 plausible. A loss makes them likely to pivot elsewhere.",
   "sources": [
    "https://paxfauna.org/introducing-pro-animal-futures-10-year-plan/",
    "https://www.ourhenhouse.org/ep765/"
   ]
  },
  "dc_another_animal_law": {
   "forecasts": {
    "yes_42.0|filed": {
     "p": 0.12
    },
    "yes_42.0|not_filed": {
     "p": 0.04
    },
    "yes_49.5|filed": {
     "p": 0.15
    },
    "yes_49.5|not_filed": {
     "p": 0.04
    },
    "yes_50.5|filed": {
     "p": 0.22
    },
    "yes_50.5|not_filed": {
     "p": 0.05
    },
    "yes_60.0|filed": {
     "p": 0.28
    },
    "yes_60.0|not_filed": {
     "p": 0.05
    },
    "yes_72.0|filed": {
     "p": 0.35
    },
    "yes_72.0|not_filed": {
     "p": 0.06
    }
   },
   "reasoning": "The DC Council rarely legislates on farmed animals; for example, a fur ban bill stalled. A filed initiative would have to qualify, pass in 2028 or 2030 and take effect by the end of 2030, so even the filed cells are well below 50%. A strong I-86 result raises both the initiative's odds and the Council's appetite.",
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
     "p25": 0,
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
   "reasoning": "DC introduces very few farmed-animal bills. A strong vote signals constituent demand and could prompt a few bills on fur-adjacent or cage-free topics over two Council periods.",
   "sources": []
  },
  "paf_measures_2027_2028": {
   "forecasts": {
    "yes_42.0|denver_pass": {
     "0": 0.25,
     "1": 0.28,
     "2": 0.22,
     "3": 0.12,
     "4": 0.07,
     "5+": 0.06
    },
    "yes_42.0|denver_fail": {
     "0": 0.35,
     "1": 0.3,
     "2": 0.18,
     "3": 0.09,
     "4": 0.04,
     "5+": 0.04
    },
    "yes_49.5|denver_pass": {
     "0": 0.2,
     "1": 0.27,
     "2": 0.24,
     "3": 0.14,
     "4": 0.08,
     "5+": 0.07
    },
    "yes_49.5|denver_fail": {
     "0": 0.3,
     "1": 0.3,
     "2": 0.2,
     "3": 0.1,
     "4": 0.05,
     "5+": 0.05
    },
    "yes_50.5|denver_pass": {
     "0": 0.17,
     "1": 0.26,
     "2": 0.25,
     "3": 0.15,
     "4": 0.09,
     "5+": 0.08
    },
    "yes_50.5|denver_fail": {
     "0": 0.27,
     "1": 0.3,
     "2": 0.21,
     "3": 0.11,
     "4": 0.06,
     "5+": 0.05
    },
    "yes_60.0|denver_pass": {
     "0": 0.15,
     "1": 0.25,
     "2": 0.25,
     "3": 0.16,
     "4": 0.1,
     "5+": 0.09
    },
    "yes_60.0|denver_fail": {
     "0": 0.25,
     "1": 0.29,
     "2": 0.22,
     "3": 0.12,
     "4": 0.06,
     "5+": 0.06
    },
    "yes_72.0|denver_pass": {
     "0": 0.12,
     "1": 0.23,
     "2": 0.25,
     "3": 0.18,
     "4": 0.11,
     "5+": 0.11
    },
    "yes_72.0|denver_fail": {
     "0": 0.22,
     "1": 0.28,
     "2": 0.23,
     "3": 0.13,
     "4": 0.07,
     "5+": 0.07
    }
   },
   "reasoning": "Pro-Animal Future ran 2 measures in 2024 and 2 in 2026, prefers even years and plans to expand slowly to more cities. For 2028 I expect 1-2 measures, with a right tail if wins attract donors. Wins in both cities shift the mass upward.",
   "sources": [
    "https://www.ourhenhouse.org/ep765/",
    "https://paxfauna.org/introducing-pro-animal-futures-10-year-plan/",
    "https://news.ballotpedia.org/2026/08/06/voters-in-washington-d-c-and-denver-colorado-will-decide-on-foie-gras-ban-ballot-initiatives-in-november/"
   ]
  },
  "paf_statewide_2028": {
   "forecasts": {
    "yes_42.0|denver_pass": {
     "p": 0.07
    },
    "yes_42.0|denver_fail": {
     "p": 0.035
    },
    "yes_49.5|denver_pass": {
     "p": 0.09
    },
    "yes_49.5|denver_fail": {
     "p": 0.045
    },
    "yes_50.5|denver_pass": {
     "p": 0.1
    },
    "yes_50.5|denver_fail": {
     "p": 0.05
    },
    "yes_60.0|denver_pass": {
     "p": 0.12
    },
    "yes_60.0|denver_fail": {
     "p": 0.06
    },
    "yes_72.0|denver_pass": {
     "p": 0.15
    },
    "yes_72.0|denver_fail": {
     "p": 0.075
    }
   },
   "reasoning": "A statewide campaign is a stated long-run goal, but the group is small, and qualifying a statewide measure in a state like Colorado or Oregon costs millions. It must also cover chickens, pigs, cattle or fish, not foie gras. The probability is low and roughly doubles with momentum from Denver.",
   "sources": [
    "https://www.ourhenhouse.org/ep765/"
   ]
  },
  "us_new_coverage_2027_2032": {
   "forecasts": {
    "yes_42.0|statewide": {
     "p05": 2,
     "p25": 9,
     "p50": 19,
     "p75": 38,
     "p95": 85
    },
    "yes_42.0|no_statewide": {
     "p05": 0.5,
     "p25": 5,
     "p50": 13,
     "p75": 28,
     "p95": 65
    },
    "yes_49.5|statewide": {
     "p05": 2,
     "p25": 9,
     "p50": 19.5,
     "p75": 39,
     "p95": 87
    },
    "yes_49.5|no_statewide": {
     "p05": 0.5,
     "p25": 5,
     "p50": 13.5,
     "p75": 29,
     "p95": 67
    },
    "yes_50.5|statewide": {
     "p05": 2,
     "p25": 9.5,
     "p50": 20,
     "p75": 40,
     "p95": 88
    },
    "yes_50.5|no_statewide": {
     "p05": 0.5,
     "p25": 5.5,
     "p50": 14,
     "p75": 30,
     "p95": 68
    },
    "yes_60.0|statewide": {
     "p05": 2.5,
     "p25": 10,
     "p50": 21,
     "p75": 41,
     "p95": 90
    },
    "yes_60.0|no_statewide": {
     "p05": 0.5,
     "p25": 6,
     "p50": 15,
     "p75": 31,
     "p95": 70
    },
    "yes_72.0|statewide": {
     "p05": 3,
     "p25": 11,
     "p50": 23,
     "p75": 44,
     "p95": 95
    },
    "yes_72.0|no_statewide": {
     "p05": 1,
     "p25": 6.5,
     "p50": 16,
     "p75": 33,
     "p95": 72
    }
   },
   "reasoning": "Over six years, a few states and localities will probably pass cage-free, octopus-farming or similar sales standards, adding millions of residents covered, but federal preemption risk caps the upside. A qualified Pro-Animal Future statewide measure adds the chance (about half) of one more state's population. I-86's result is a weak signal of national momentum.",
   "sources": [
    "https://www.humaneworld.org/en/news/whats-happening-california-prop-12-farm-bill-save-our-bacon-act"
   ]
  },
  "other_foie_gras_bans_2030": {
   "baseline": {
    "value": 1,
    "as_of": "2026-10-25",
    "source": "California's statewide ban is in force. NYC's Local Law 202/2019 is enjoined by a New York state court ruling (2022, upheld 2024). Chicago repealed its ban in 2008."
   },
   "forecasts": {
    "yes_49.5": {
     "p05": 1,
     "p25": 1,
     "p50": 1,
     "p75": 2,
     "p95": 3
    },
    "yes_50.5": {
     "p05": 1,
     "p25": 1,
     "p50": 1,
     "p75": 2,
     "p95": 4
    }
   },
   "reasoning": "California stays. Denver adds one if IO 311 passes, which the DC result implies is about 40%, and NYC could revive on appeal (small chance). Other new bans are rare. A DC pass slightly raises the odds of copycats.",
   "sources": [
    "https://markets.financialcontent.com/pennwell.industriallaser/article/send2press-2024-6-21-new-york-supreme-court-upholds-la-belle-farm-and-hudson-foie-grass-right-to-sell-the-duck-delicacy-in-nyc"
   ]
  },
  "federal_preemption_2030": {
   "forecasts": {
    "yes_49.5": {
     "p": 0.15
    },
    "yes_50.5": {
     "p": 0.155
    }
   },
   "reasoning": "The House passed Save Our Bacon preemption in its 2026 farm bill, but the Senate version omits it, a 60-vote threshold applies and the bill is stalled; markets put this Congress at about 5%. Over two more Congresses, through 2030, I put it at about 15%. A DC pass barely matters.",
   "sources": [
    "https://www.dtnpf.com/agriculture/web/ag/news/article/2026/06/23/farm-bill-draft-updates-farm-leaves",
    "https://tech-insider.org/farm-bill-hr-7567-save-our-bacon-prediction-market/",
    "https://hoodline.com/2026/09/california-s-prop-12-pork-rules-face-federal-override-as-farm-bill-fight-heats-up/"
   ]
  },
  "dc_bans_other_food_2030": {
   "forecasts": {
    "yes_49.5": {
     "p": 0.12
    },
    "yes_50.5": {
     "p": 0.13
    }
   },
   "reasoning": "State food-additive bans are spreading (for example West Virginia's dye ban), and DC could follow with an all-buyer additive ban. School-only and labeling rules do not count, though, and the DC Council has been slow on this. A food-ban precedent from I-86 nudges the odds up slightly.",
   "sources": []
  }
 }
}
```
