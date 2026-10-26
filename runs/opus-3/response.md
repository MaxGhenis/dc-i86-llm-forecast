I couldn't follow plan mode here: the plan file and ExitPlanMode tools weren't available, and the brief says this headless run must end with the completed forecast. I only used read-only web searches and changed no files. Three caveats: the DC foie gras baseline is an estimate between Pro-Animal DC's "about 50" and City Cast's "a couple dozen"; the liver pâté menu baseline is my guess, not a count; and the 2030 duck number is a rough anchor.

```json
{
 "forecaster": {
  "model": "claude-opus-5-5",
  "prior_context": "none",
  "notes": "Plan mode was on, but the plan file and ExitPlanMode tools weren't available, so I only did read-only web research and changed no files. Several pages wouldn't load (403 or connection refused): both Axios articles, Denverite, the CSU study page and Wikipedia's DC Michelin list. Where that happened I used the search-result snippets. Quantities with no direct data (pâté menu counts, US duck volumes) are rough estimates."
 },
 "research_summary": "I-86 made the ballot with a record 31,726 valid signatures. A poll paid for by supporters found 78% back a ban, and a CSU survey found 85% of Colorado voters back one. The Yes side (Pro-Animal DC, funded by Pro-Animal Future and Dr. Bronner's) had spent more than $336k by September. No opposition committee has filed reports, and the restaurant association's statement was weak. Opposition consists of José Andrés posting on X and Bart Hutchins of Butterworth's, who is holding a protest, raising money for a legal defense, and says he will keep serving foie gras. Pro-Animal DC counts about 50 DC restaurants serving foie gras; City Cast says 'a couple dozen'. CSU's April 2026 scrape ranked DC third of 21 metros for confirmed foie gras restaurants. Denver IO 311 has about 15 restaurants affected and opposition from the Colorado Restaurant Association, but Pro-Animal Future's 2024 Denver measures (fur and slaughterhouse bans) lost badly. The Michelin DC 2025 guide had 25 starred restaurants and added no new stars. Pro-Animal Future's 10-year plan aims to qualify several statewide measures by 2030, after a round of city measures.",
 "nodes": {
  "yes_share": {
   "forecasts": {
    "all": {
     "le_30": 0.005,
     "le_35": 0.01,
     "le_40": 0.025,
     "le_45": 0.05,
     "le_47": 0.065,
     "le_48": 0.075,
     "le_49": 0.085,
     "le_50": 0.1,
     "le_51": 0.115,
     "le_52": 0.13,
     "le_53": 0.15,
     "le_55": 0.2,
     "le_60": 0.37,
     "le_65": 0.58,
     "le_70": 0.78,
     "le_75": 0.91,
     "le_80": 0.97,
     "le_85": 0.99,
     "le_90": 0.998
    }
   },
   "reasoning": "Animal-welfare sales measures usually pass comfortably when there is little industry money: Massachusetts Question 3 got 78% and Prop 12 got 63%. DC voters reliably pass progressive initiatives. There is no funded No campaign, and the supporters' poll shows 78%, though such polls overstate support. Things that could pull Yes down: Andrés and chef pushback, voters' dislike of food bans, and the broad 'fattened through any method' definition. My median is about 63% Yes, with roughly a 90% chance it passes.",
   "sources": [
    "https://wjla.com/features/i-team/dc-voters-to-decide-foie-gras-ban-after-initiative-86-qualifies-for-november-ballot-controversial-cuisine-what-is-foie-gras-pro-animal-dc-august-2026",
    "https://www.axios.com/local/washington-dc/2026/10/21/dc-foie-gras-ban-ballot-initiative-fight",
    "https://www.axios.com/local/washington-dc/2026/10/23/jose-andres-dc-foie-gras-ban-chef-protest"
   ]
  },
  "turnout": {
   "forecasts": {
    "all": {
     "p05": 158000,
     "p25": 186000,
     "p50": 203000,
     "p75": 222000,
     "p95": 255000
    }
   },
   "reasoning": "DC's midterm general elections in 2018 and 2022 drew roughly 200–215k ballots, and initiatives get most of them (I-82 in 2022 drew close to 190k). Every voter is mailed a ballot. An open mayoral race and tension with the federal government may lift turnout a little, but the general election is not competitive.",
   "sources": [
    "https://51st.news/dc-general-election-2026-voter-guide/"
   ]
  },
  "denver_io311_passes": {
   "forecasts": {
    "yes_42.0": {
     "p": 0.25
    },
    "yes_49.5": {
     "p": 0.4
    },
    "yes_50.5": {
     "p": 0.42
    },
    "yes_60.0": {
     "p": 0.58
    },
    "yes_72.0": {
     "p": 0.78
    }
   },
   "reasoning": "Denver voters rejected Pro-Animal Future's 2024 fur and slaughterhouse measures by wide margins. Foie gras is a much easier target, though: polls run above 80%, only about 15 restaurants are affected, and the restaurant association opposes but appears to have little money in the fight. Unconditionally I put it at about 0.55. The two results are correlated through national sentiment toward these measures and through how good the campaign model is, so a strong DC result raises Denver's chance.",
   "sources": [
    "https://denverite.com/2026/09/25/vg-2026-initiated-ordinance-311-force-feeding-birds-ban-voter-guide/",
    "https://hoodline.com/2026/09/denver-voters-to-decide-foie-gras-ban-restaurants-face-5-000-fines/"
   ]
  },
  "ban_status": {
   "forecasts": {
    "yes_50.5": {
     "repealed": 0.12,
     "congress": 0.05,
     "court": 0.04,
     "not_certified": 0.29,
     "certified": 0.5
    },
    "yes_60.0": {
     "repealed": 0.07,
     "congress": 0.05,
     "court": 0.035,
     "not_certified": 0.29,
     "certified": 0.555
    },
    "yes_72.0": {
     "repealed": 0.04,
     "congress": 0.04,
     "court": 0.03,
     "not_certified": 0.29,
     "certified": 0.6
    }
   },
   "reasoning": "The Council has repealed or paused initiatives before (I-77, and part of I-82), but this one costs little and is low-stakes. The Council is more likely to amend it than repeal it, and repeal becomes more plausible the narrower the win. A congressional rider or disapproval resolution is possible given Republican interest in DC, but it gets harder if Democrats win the House in 2026. Courts upheld California's foie gras ban and Prop 12, and DC has no state agriculture law that could preempt it the way New York's did, so a court blocking the whole ban is unlikely. The cost is only about $109k a year, but whether the CFO publishes the section 8(b) certification is uncertain (I-83's funding was delayed), so I put not_certified at about 30% of the cases where the ban stands.",
   "sources": [
    "https://dcboe.org/getmedia/8ed77952-835c-4a11-9fa2-2ad447d82643/Final-FIS-Initiative-Prohibiting-the-Force-Feeding-of-Birds-Act-of-2026.pdf",
    "https://www.axios.com/local/washington-dc/2026/10/21/dc-foie-gras-ban-ballot-initiative-fight"
   ]
  },
  "lawsuit_filed": {
   "forecasts": {
    "yes_50.5|blocked": {
     "p": 1.0
    },
    "yes_50.5|not_blocked": {
     "p": 0.45
    },
    "yes_60.0|blocked": {
     "p": 1.0
    },
    "yes_60.0|not_blocked": {
     "p": 0.42
    },
    "yes_72.0|blocked": {
     "p": 1.0
    },
    "yes_72.0|not_blocked": {
     "p": 0.37
    }
   },
   "reasoning": "Butterworth's owner is raising money for a legal fight and says he will defy the ban. Producers such as Hudson Valley sued over New York's ban. On the other hand, the California precedent makes a suit look weak, and enforcement could be a long way off if funding is delayed. A court block requires a lawsuit, so that state is set to 1.",
   "sources": [
    "https://www.axios.com/local/washington-dc/2026/10/21/dc-foie-gras-ban-ballot-initiative-fight"
   ]
  },
  "fattened_narrowed": {
   "forecasts": {
    "yes_50.5|certified": {
     "p": 0.3
    },
    "yes_50.5|not_certified": {
     "p": 0.2
    }
   },
   "reasoning": "As written, 'fattened through any method' could cover ordinary liver pâté, which gives the Council or DOEE a reason to clarify it. But agencies often settle questions like this through guidance, which doesn't count, and a final rule by 2028 is more likely once funding is certified and DOEE is actively implementing the law.",
   "sources": [
    "https://proanimaldc.org/prohibit-force-feeding-of-birds-act/"
   ]
  },
  "pate_treated_banned": {
   "forecasts": {
    "yes_50.5|narrowed_certified": {
     "p": 0.005
    },
    "yes_50.5|narrowed_not_certified": {
     "p": 0.003
    },
    "yes_50.5|not_narrowed_certified": {
     "p": 0.03
    },
    "yes_50.5|not_narrowed_not_certified": {
     "p": 0.012
    }
   },
   "reasoning": "The summary statement and the sponsor both describe the target as force-fed products. DOEE has one inspector, handles complaints, and doesn't inspect kitchens, so a written determination against chicken-liver pâté is very unlikely. It is a little more likely if 'fattened' is never narrowed and enforcement is funded.",
   "sources": [
    "https://dcboe.org/getmedia/8ed77952-835c-4a11-9fa2-2ad447d82643/Final-FIS-Initiative-Prohibiting-the-Force-Feeding-of-Birds-Act-of-2026.pdf"
   ]
  },
  "foie_gras_menus": {
   "baseline": {
    "value": 45,
    "as_of": "2026-10",
    "source": "Pro-Animal DC says about 50 DC restaurants (via Axios, 2026-10-23); City Cast says 'a couple dozen'. CSU's April 2026 study ranks DC third among 21 metros. 45 is my estimate of what the brief's menu check would find."
   },
   "forecasts": {
    "yes_49.5|failed": {
     "p05": 28,
     "p25": 36,
     "p50": 42,
     "p75": 49,
     "p95": 60
    },
    "yes_50.5|removed": {
     "p05": 22,
     "p25": 31,
     "p50": 38,
     "p75": 45,
     "p95": 56
    },
    "yes_50.5|not_certified": {
     "p05": 2,
     "p25": 6,
     "p50": 11,
     "p75": 18,
     "p95": 30
    },
    "yes_50.5|certified": {
     "p05": 0,
     "p25": 2,
     "p50": 4,
     "p75": 7,
     "p95": 14
    }
   },
   "reasoning": "If the measure fails, menus drift slightly down from the current level. If it passes and is later removed, some restaurants will already have dropped the item. If the ban stands but isn't certified, enforceability is unclear, but most restaurants will still treat the July 2027 date as binding. If it's certified, only defiant restaurants or ones serving it off-menu remain, Butterworth's for example.",
   "sources": [
    "https://www.axios.com/local/washington-dc/2026/10/23/jose-andres-dc-foie-gras-ban-chef-protest",
    "https://sites.warnercnr.colostate.edu/animalhumanpolicy/ahpc-studies-document-the-prevalence-of-foie-gras-on-menus-and-denver-voters-support-of-a-foie-gras-ban/"
   ]
  },
  "liver_pate_menus": {
   "baseline": {
    "value": 150,
    "as_of": "2026-10",
    "source": "My own estimate; I found no published count. Chicken-liver mousse and pâté are common at DC bistros, wine bars and delis."
   },
   "forecasts": {
    "yes_49.5|failed": {
     "p05": 90,
     "p25": 125,
     "p50": 150,
     "p75": 180,
     "p95": 240
    },
    "yes_50.5|removed": {
     "p05": 88,
     "p25": 122,
     "p50": 148,
     "p75": 178,
     "p95": 238
    },
    "yes_50.5|standing_pate_allowed": {
     "p05": 85,
     "p25": 118,
     "p50": 144,
     "p75": 174,
     "p95": 232
    },
    "yes_50.5|standing_pate_banned": {
     "p05": 40,
     "p25": 70,
     "p50": 100,
     "p75": 130,
     "p95": 190
    }
   },
   "reasoning": "The count is mostly the existing stock of menus. If the ban stands and pâté is allowed, a small chilling effect is possible. If DOEE treats ordinary pâté as covered, many restaurants would drop or rename it, but enforcement would be thin.",
   "sources": []
  },
  "us_ducks_force_fed_2030": {
   "baseline": {
    "value": 400000,
    "as_of": "2024",
    "source": "Rough industry estimates for Hudson Valley Foie Gras and La Belle Farm. No official data exists."
   },
   "forecasts": {
    "yes_49.5|failed": {
     "p05": 150000,
     "p25": 270000,
     "p50": 340000,
     "p75": 410000,
     "p95": 520000
    },
    "yes_50.5|not_certified_or_removed": {
     "p05": 145000,
     "p25": 265000,
     "p50": 335000,
     "p75": 405000,
     "p95": 515000
    },
    "yes_50.5|certified": {
     "p05": 140000,
     "p25": 260000,
     "p50": 330000,
     "p75": 400000,
     "p95": 510000
    }
   },
   "reasoning": "Volumes come from two New York farms and are trending down. DC accounts for well under 2% of demand, so its effect is tiny.",
   "sources": []
  },
  "dc_restaurant_employment_2029": {
   "baseline": {
    "value": 51.5,
    "as_of": "2026-09",
    "source": "BLS SMU11000007072200001 via FRED (given in the brief)"
   },
   "forecasts": {
    "yes_49.5|failed": {
     "p05": 46.0,
     "p25": 49.5,
     "p50": 51.5,
     "p75": 53.4,
     "p95": 56.5
    },
    "yes_50.5|not_certified_or_removed": {
     "p05": 46.0,
     "p25": 49.5,
     "p50": 51.5,
     "p75": 53.4,
     "p95": 56.5
    },
    "yes_50.5|certified": {
     "p05": 45.98,
     "p25": 49.48,
     "p50": 51.48,
     "p75": 53.38,
     "p95": 56.48
    }
   },
   "reasoning": "DC restaurant employment has been flat and is under pressure from federal workforce cuts. Recession risk sets the width of the range. A ban covering one menu item has a negligible effect.",
   "sources": [
    "https://fred.stlouisfed.org/series/SMU11000007072200001"
   ]
  },
  "dc_restaurant_sales_tax_fy2029": {
   "baseline": {
    "value": 567.9,
    "as_of": "FY2025",
    "source": "ORA, 2026-04-14, https://ora-cfo.dc.gov/node/1824291"
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
     "p05": 539.8,
     "p25": 594.8,
     "p50": 627.8,
     "p75": 659.8,
     "p95": 714.8
    }
   },
   "reasoning": "I assume roughly 2.5% a year of nominal growth from FY2025, with risk of a downturn. Foie gras sales are trivial against the tax base.",
   "sources": [
    "https://ora-cfo.dc.gov/node/1824291"
   ]
  },
  "dc_michelin_starred_2029": {
   "baseline": {
    "value": 25,
    "as_of": "2025-11-18",
    "source": "MICHELIN Guide Washington D.C. 2025 (no new stars that year)"
   },
   "forecasts": {
    "yes_49.5|failed": {
     "p05": 19,
     "p25": 23,
     "p50": 25,
     "p75": 27,
     "p95": 31
    },
    "yes_50.5|not_certified_or_removed": {
     "p05": 19,
     "p25": 23,
     "p50": 25,
     "p75": 27,
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
   "reasoning": "The count has held around 23–25 for several years and changes slowly. California's ban didn't measurably reduce its stars, so I see no effect from the ban.",
   "sources": [
    "https://guide.michelin.com/us/en/article/michelin-guide-ceremony/all-the-stars-in-the-michelin-guide-washington-d.c.-2025",
    "https://wtop.com/business-finance/2025/11/michelin-guide-doesnt-include-any-new-stars-for-dc-restaurants/"
   ]
  },
  "dc_animal_initiative_filed": {
   "forecasts": {
    "yes_42.0": {
     "p": 0.12
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
   "reasoning": "Pro-Animal Future plans a sequence of measures and calls fur bans a stepping stone. A DC win would encourage a follow-up DC measure, such as a fur sales ban for 2028. A loss makes another DC filing less likely.",
   "sources": [
    "https://paxfauna.org/introducing-pro-animal-futures-10-year-plan/",
    "https://proanimal.org/can-ballot-initiatives-end-factory-farming/"
   ]
  },
  "dc_another_animal_law": {
   "forecasts": {
    "yes_42.0|filed": {
     "p": 0.25
    },
    "yes_42.0|not_filed": {
     "p": 0.06
    },
    "yes_49.5|filed": {
     "p": 0.3
    },
    "yes_49.5|not_filed": {
     "p": 0.07
    },
    "yes_50.5|filed": {
     "p": 0.35
    },
    "yes_50.5|not_filed": {
     "p": 0.08
    },
    "yes_60.0|filed": {
     "p": 0.42
    },
    "yes_60.0|not_filed": {
     "p": 0.09
    },
    "yes_72.0|filed": {
     "p": 0.5
    },
    "yes_72.0|not_filed": {
     "p": 0.11
    }
   },
   "reasoning": "A filed initiative still has to qualify and win, and then survive the Council. The Council itself rarely passes farmed-animal laws. A strong I-86 result raises the chance of both.",
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
     "p75": 2,
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
   "reasoning": "DC Council bills on farmed animals have historically been rare, at most about one per period. A strong win could prompt councilmembers to introduce related bills.",
   "sources": []
  },
  "paf_measures_2027_2028": {
   "forecasts": {
    "yes_42.0|denver_pass": {
     "0": 0.2,
     "1": 0.25,
     "2": 0.25,
     "3": 0.15,
     "4": 0.08,
     "5+": 0.07
    },
    "yes_42.0|denver_fail": {
     "0": 0.38,
     "1": 0.27,
     "2": 0.18,
     "3": 0.1,
     "4": 0.04,
     "5+": 0.03
    },
    "yes_49.5|denver_pass": {
     "0": 0.17,
     "1": 0.24,
     "2": 0.25,
     "3": 0.16,
     "4": 0.1,
     "5+": 0.08
    },
    "yes_49.5|denver_fail": {
     "0": 0.33,
     "1": 0.27,
     "2": 0.2,
     "3": 0.11,
     "4": 0.05,
     "5+": 0.04
    },
    "yes_50.5|denver_pass": {
     "0": 0.14,
     "1": 0.22,
     "2": 0.25,
     "3": 0.18,
     "4": 0.11,
     "5+": 0.1
    },
    "yes_50.5|denver_fail": {
     "0": 0.28,
     "1": 0.27,
     "2": 0.21,
     "3": 0.13,
     "4": 0.06,
     "5+": 0.05
    },
    "yes_60.0|denver_pass": {
     "0": 0.12,
     "1": 0.2,
     "2": 0.25,
     "3": 0.19,
     "4": 0.12,
     "5+": 0.12
    },
    "yes_60.0|denver_fail": {
     "0": 0.25,
     "1": 0.26,
     "2": 0.22,
     "3": 0.14,
     "4": 0.07,
     "5+": 0.06
    },
    "yes_72.0|denver_pass": {
     "0": 0.1,
     "1": 0.18,
     "2": 0.24,
     "3": 0.2,
     "4": 0.14,
     "5+": 0.14
    },
    "yes_72.0|denver_fail": {
     "0": 0.22,
     "1": 0.25,
     "2": 0.23,
     "3": 0.15,
     "4": 0.08,
     "5+": 0.07
    }
   },
   "reasoning": "Pro-Animal Future hoped for up to 10 chapters in the 2025–26 cycle but got only DC and Denver on the ballot. City measures are cheap, so a few in 2028 is plausible, especially after wins. Losses in both cities would push the group to regroup.",
   "sources": [
    "https://www.idausa.org/campaign/farmed-animal/latest-news/3-incredibly-ambitious-ballot-initiatives-for-animals/",
    "https://paxfauna.org/introducing-pro-animal-futures-10-year-plan/"
   ]
  },
  "paf_statewide_2028": {
   "forecasts": {
    "yes_42.0|denver_pass": {
     "p": 0.1
    },
    "yes_42.0|denver_fail": {
     "p": 0.05
    },
    "yes_49.5|denver_pass": {
     "p": 0.12
    },
    "yes_49.5|denver_fail": {
     "p": 0.06
    },
    "yes_50.5|denver_pass": {
     "p": 0.14
    },
    "yes_50.5|denver_fail": {
     "p": 0.07
    },
    "yes_60.0|denver_pass": {
     "p": 0.16
    },
    "yes_60.0|denver_fail": {
     "p": 0.08
    },
    "yes_72.0|denver_pass": {
     "p": 0.19
    },
    "yes_72.0|denver_fail": {
     "p": 0.1
    }
   },
   "reasoning": "The 10-year plan targets statewide measures 'by 2030', and qualifying one costs millions. A 2028 statewide measure is possible but early for a group this small, and more likely after wins in both cities.",
   "sources": [
    "https://paxfauna.org/introducing-pro-animal-futures-10-year-plan/"
   ]
  },
  "us_new_coverage_2027_2032": {
   "forecasts": {
    "yes_42.0|statewide": {
     "p05": 1,
     "p25": 6,
     "p50": 14,
     "p75": 30,
     "p95": 70
    },
    "yes_42.0|no_statewide": {
     "p05": 0,
     "p25": 3,
     "p50": 10,
     "p75": 24,
     "p95": 60
    },
    "yes_49.5|statewide": {
     "p05": 1,
     "p25": 6,
     "p50": 15,
     "p75": 31,
     "p95": 72
    },
    "yes_49.5|no_statewide": {
     "p05": 0,
     "p25": 3,
     "p50": 10,
     "p75": 25,
     "p95": 61
    },
    "yes_50.5|statewide": {
     "p05": 1,
     "p25": 7,
     "p50": 16,
     "p75": 32,
     "p95": 74
    },
    "yes_50.5|no_statewide": {
     "p05": 0,
     "p25": 3,
     "p50": 11,
     "p75": 25,
     "p95": 62
    },
    "yes_60.0|statewide": {
     "p05": 1,
     "p25": 7,
     "p50": 17,
     "p75": 33,
     "p95": 75
    },
    "yes_60.0|no_statewide": {
     "p05": 0,
     "p25": 4,
     "p50": 11,
     "p75": 26,
     "p95": 63
    },
    "yes_72.0|statewide": {
     "p05": 2,
     "p25": 8,
     "p50": 18,
     "p75": 35,
     "p95": 78
    },
    "yes_72.0|no_statewide": {
     "p05": 0,
     "p25": 4,
     "p50": 12,
     "p75": 27,
     "p95": 64
    }
   },
   "reasoning": "Over six years, a few states and cities will probably pass cage-free or confinement laws. Each mid-sized state adds 3–10M residents, and a single large state passing one is what makes the tail fat. A qualified Pro-Animal Future statewide measure adds the chance of one more state.",
   "sources": [
    "https://ballotpedia.org/Animal_treatment_laws_ballot_measures"
   ]
  },
  "other_foie_gras_bans_2030": {
   "baseline": {
    "value": 1,
    "as_of": "2026-10-25",
    "source": "California's state ban (upheld). New York City's Local Law 202 is blocked in state court, and Chicago repealed its ban in 2008. Sources: PETA and Ballotpedia trackers, plus news coverage."
   },
   "forecasts": {
    "yes_49.5": {
     "p05": 1,
     "p25": 1,
     "p50": 2,
     "p75": 3,
     "p95": 5
    },
    "yes_50.5": {
     "p05": 1,
     "p25": 1,
     "p50": 2,
     "p75": 3,
     "p95": 6
    }
   },
   "reasoning": "California stays. Denver adds one with probability around 0.5. Pro-Animal Future's later city foie gras campaigns could add a few, and a DC pass makes that slightly more likely.",
   "sources": [
    "https://denverite.com/2026/09/25/vg-2026-initiated-ordinance-311-force-feeding-birds-ban-voter-guide/"
   ]
  },
  "federal_preemption_2030": {
   "forecasts": {
    "yes_49.5": {
     "p": 0.2
    },
    "yes_50.5": {
     "p": 0.2
    }
   },
   "reasoning": "Prop 12 'fix' language has appeared in House farm bill drafts but hasn't been enacted, because the Senate resists. There are several more chances by 2030. A DC foie gras vote is irrelevant to pork preemption.",
   "sources": []
  },
  "dc_bans_other_food_2030": {
   "forecasts": {
    "yes_49.5": {
     "p": 0.14
    },
    "yes_50.5": {
     "p": 0.15
    }
   },
   "reasoning": "States are moving to ban food dyes and additives, though in some cases only in schools. DC could follow with a general ban on a dye or additive, but the Council hasn't moved on this so far.",
   "sources": []
  }
 }
}
```