```json
{
  "forecaster": {
    "model": "GPT-6 (Codex)",
    "prior_context": "none",
    "notes": "Forecast cutoff is 2026-10-25, regardless of the later session date. Public web research only; no local files read. Foie gras menus, ordinary liver menus and annual force-fed birds have explicitly estimated or carried-forward baselines rather than verified October 2026 censuses. Identical macroeconomic quantiles express an effect too small to distinguish at this precision."
  },
  "research_summary": "Reviewed DCBOE election history, survey methodology, campaign reporting, the fiscal trigger, Council precedents, restaurant menus, Michelin listings, DC revenue data, PAF strategy and finances, existing bans and House/Senate Farm Bill texts. The headline DC support survey was fielded in 2023, and Denver's informed-opinion studies also require substantial discounting as election forecasts. Passage looks likely, but funding and political intervention remain material uncertainties. Baseline limitations are disclosed individually.",
  "nodes": {
    "yes_share": {
      "forecasts": {
        "all": {
          "le_30": 0.001,
          "le_35": 0.004,
          "le_40": 0.014,
          "le_45": 0.04,
          "le_47": 0.06,
          "le_48": 0.074,
          "le_49": 0.09,
          "le_50": 0.108,
          "le_51": 0.128,
          "le_52": 0.15,
          "le_53": 0.175,
          "le_55": 0.235,
          "le_60": 0.405,
          "le_65": 0.605,
          "le_70": 0.79,
          "le_75": 0.915,
          "le_80": 0.976,
          "le_85": 0.996,
          "le_90": 0.9997
        }
      },
      "reasoning": "The sponsor reports 78% support in a 438-person survey fielded in 2023; I discount its age, sampling and abstract policy wording substantially. DC's recent initiative approvals and a narrow target support passage, while chef opposition and preference for consumer choice create a substantial downside tail. The distribution centers near 62% Yes and assigns 0.892 probability to passage.",
      "sources": [
        "https://proanimal.org/78-of-dc-voters-want-to-end-the-sale-of-force-fed-foie-gras/",
        "https://electionresults.dcboe.org/election_results/2024-General-Election",
        "https://www.ballotready.org/measures/intiative-86",
        "https://www.axios.com/local/washington-dc/2026/10/23/jose-andres-dc-foie-gras-ban-chef-protest"
      ]
    },
    "turnout": {
      "forecasts": {
        "all": {
          "p05": 170000,
          "p25": 195000,
          "p50": 217000,
          "p75": 239000,
          "p95": 275000
        }
      },
      "reasoning": "DC cast about 206,000 ballots in the 2022 midterm and 232,000 in 2018, with appreciable initiative undervoting in recent elections. I expect a relatively engaged 2026 electorate, but retain uncertainty over turnout and ballot-question completion. These quantiles count only Yes plus No votes.",
      "sources": [
        "https://wearedcaction.org/dc-kids-count/key-measures/voting-democracy/",
        "https://dccouncil.gov/wp-content/uploads/2021/03/JPS-Performance-Oversight-Responses-2021-BOE.pdf",
        "https://electionresults.dcboe.org/election_results/2024-General-Election",
        "https://en.wikipedia.org/wiki/2022_District_of_Columbia_elections"
      ]
    },
    "denver_io311_passes": {
      "forecasts": {
        "yes_42.0": {"p": 0.31},
        "yes_49.5": {"p": 0.45},
        "yes_50.5": {"p": 0.47},
        "yes_60.0": {"p": 0.65},
        "yes_72.0": {"p": 0.83}
      },
      "reasoning": "Denver's 2024 fur and slaughterhouse defeats temper the favorable informed-opinion studies; the foie proposal affects a much smaller economic constituency. Shared attitudes and campaign effectiveness make a stronger DC result informative about Denver, but local opposition leaves considerable independent uncertainty. The difference across 50% represents information from one point of DC vote share, with no causal passage effect.",
      "sources": [
        "https://denverite.com/2026/09/25/vg-2026-initiated-ordinance-311-force-feeding-birds-ban-voter-guide/",
        "https://sites.warnercnr.colostate.edu/animalhumanpolicy/ahpc-studies-document-the-prevalence-of-foie-gras-on-menus-and-denver-voters-support-of-a-foie-gras-ban/",
        "https://denverite.com/2024/11/05/denver-ballot-measure-308-results-2024-elections/",
        "https://www.progressivevotersguide.com/colorado/2026/general/city/denver"
      ]
    },
    "ban_status": {
      "forecasts": {
        "yes_50.5": {
          "repealed": 0.18,
          "congress": 0.1,
          "court": 0.08,
          "not_certified": 0.24,
          "certified": 0.4
        },
        "yes_60.0": {
          "repealed": 0.1,
          "congress": 0.09,
          "court": 0.07,
          "not_certified": 0.19,
          "certified": 0.55
        },
        "yes_72.0": {
          "repealed": 0.05,
          "congress": 0.08,
          "court": 0.06,
          "not_certified": 0.15,
          "certified": 0.66
        }
      },
      "reasoning": "The CFO's unfunded implementation estimate and DC's history of revising initiatives make certification and Council intervention important risks. California precedent limits my probability of a whole-ban court block, while congressional intervention includes possible broad federal preemption. A larger mandate principally reduces repeal and makes funding more likely; probabilities follow the specified ordering.",
      "sources": [
        "https://www.dcboe.org/getmedia/8ed77952-835c-4a11-9fa2-2ad447d82643/Final-FIS-Initiative-Prohibiting-the-Force-Feeding-of-Birds-Act-of-2026.pdf",
        "https://dccouncil.gov/council-pushes-back-restoring-cut-funds-and-reasserting-appropriators-role/",
        "https://www.dcboe.org/getmedia/e2c35b07-3dc5-4f17-b4dc-fae4af9d8544/Council-OGC-Opinion-Prohibiting-Force-Feeding-of-Birds-Act.pdf",
        "https://www.govinfo.gov/content/pkg/BILLS-119hr7567eh/html/BILLS-119hr7567eh.htm"
      ]
    },
    "lawsuit_filed": {
      "forecasts": {
        "yes_50.5|blocked": {"p": 1},
        "yes_50.5|not_blocked": {"p": 0.62},
        "yes_60.0|blocked": {"p": 1},
        "yes_60.0|not_blocked": {"p": 0.65},
        "yes_72.0|blocked": {"p": 1},
        "yes_72.0|not_blocked": {"p": 0.67}
      },
      "reasoning": "A qualifying whole-ban court block logically requires a challenge, so blocked-state probabilities are one. Litigation against comparable bans and prospective local legal organizing support a substantial filing probability even without a successful block. Larger mandates modestly shift opponents toward litigation because legislative reversal becomes less promising.",
      "sources": [
        "https://stetsonlawreview.org/wp-content/uploads/2024/04/12-VanAllen.373-403.pdf",
        "https://www.axios.com/local/washington-dc/2026/10/23/jose-andres-dc-foie-gras-ban-chef-protest"
      ]
    },
    "fattened_narrowed": {
      "forecasts": {
        "yes_50.5|certified": {"p": 0.65},
        "yes_50.5|not_certified": {"p": 0.27}
      },
      "reasoning": "The supplied statutory definition is substantially broader than the force-feeding summary, creating pressure for clarification. Sponsors reject ordinary chicken-liver coverage. A funded implementation is more likely to produce a final rule or enacted clarification; informal assurances alone do not satisfy this event.",
      "sources": [
        "https://proanimaldc.org/prohibit-force-feeding-of-birds-act/",
        "https://www.washingtonpost.com/dc-md-va/2026/10/25/meet-olivia-duck-quacking-keep-foie-gras-off-dc-menus/",
        "https://proanimaldc.org/faq/"
      ]
    },
    "pate_treated_banned": {
      "forecasts": {
        "yes_50.5|narrowed_certified": {"p": 0.02},
        "yes_50.5|narrowed_not_certified": {"p": 0.005},
        "yes_50.5|not_narrowed_certified": {"p": 0.12},
        "yes_50.5|not_narrowed_not_certified": {"p": 0.035}
      },
      "reasoning": "The broad definition permits disputes about ordinary poultry liver, but the force-feeding framing makes expansive enforcement unlikely. Certification increases the opportunity for a written determination; absent formal narrowing, informal restraint can still prevent one. Small positive probabilities after narrowing allow for a qualifying determination issued before the final clarification.",
      "sources": [
        "https://proanimaldc.org/prohibit-force-feeding-of-birds-act/",
        "https://proanimaldc.org/faq/"
      ]
    },
    "foie_gras_menus": {
      "baseline": {
        "value": 48,
        "as_of": "2026-10-25",
        "source": "Estimate carried forward from the October-December 2025 menu count published August 18, 2026: https://proanimal.org/how-many-restaurants-in-dc-sell-foie-gras/; an October 2026 census was not located."
      },
      "forecasts": {
        "yes_49.5|failed": {
          "p05": 25, "p25": 38, "p50": 48, "p75": 60, "p95": 80
        },
        "yes_50.5|removed": {
          "p05": 22, "p25": 34, "p50": 44, "p75": 57, "p95": 78
        },
        "yes_50.5|not_certified": {
          "p05": 0, "p25": 6, "p50": 22, "p75": 38, "p95": 59
        },
        "yes_50.5|certified": {
          "p05": 0, "p25": 0, "p50": 1, "p75": 3, "p95": 10
        }
      },
      "reasoning": "The October baseline is a proxy: the latest published local count found 48 restaurants using late-2025 regular, seasonal and holiday menus. I allow for menu turnover, incomplete retail coverage and residual deterrence even if a passed ban is removed. Certification should eliminate nearly all explicit offers; without certification, uncertain applicability and voluntary compliance produce a broad intermediate distribution.",
      "sources": [
        "https://proanimal.org/how-many-restaurants-in-dc-sell-foie-gras/",
        "https://sites.warnercnr.colostate.edu/animalhumanpolicy/ahpc-studies-document-the-prevalence-of-foie-gras-on-menus-and-denver-voters-support-of-a-foie-gras-ban/",
        "https://www.dcboe.org/getmedia/8ed77952-835c-4a11-9fa2-2ad447d82643/Final-FIS-Initiative-Prohibiting-the-Force-Feeding-of-Birds-Act-of-2026.pdf"
      ]
    },
    "liver_pate_menus": {
      "baseline": {
        "value": 65,
        "as_of": "2026-10-25",
        "source": "Forecaster estimate, not a citywide census; informed by nine establishments' own menus, including https://www.dauphinesdc.com/menus/, https://www.ameliedc.com/dc/menus/dinner and https://www.bistro-dujour.com/."
      },
      "forecasts": {
        "yes_49.5|failed": {
          "p05": 35, "p25": 50, "p50": 67, "p75": 88, "p95": 120
        },
        "yes_50.5|removed": {
          "p05": 33, "p25": 48, "p50": 64, "p75": 86, "p95": 118
        },
        "yes_50.5|standing_pate_allowed": {
          "p05": 35, "p25": 53, "p50": 72, "p75": 95, "p95": 130
        },
        "yes_50.5|standing_pate_banned": {
          "p05": 15, "p25": 27, "p50": 42, "p75": 62, "p95": 100
        }
      },
      "reasoning": "No citywide census was located: 65 is an uncertain extrapolation from a nonexhaustive sample confirming dishes at nine establishments, with allowances for delis, Vietnamese shops and retail. Substitution can increase ordinary liver offerings when allowed. One adverse DOEE determination signals greater enforcement risk but does not imply universal removal, and mammal liver remains outside the ban.",
      "sources": [
        "https://www.dauphinesdc.com/menus/",
        "https://www.morrisbardc.com/menu/food-menu/",
        "https://www.riggsdc.com/eat-drink/cafe-riggs-menus/",
        "https://www.ameliedc.com/dc/menus/dinner",
        "https://mikeyandmelsdeli.com/wp-content/uploads/2025/08/100756-Carryout-Menu-New-DC-Location-1-2-1.pdf",
        "https://www.bistro-dujour.com/wp-content/uploads/sites/11/2026/07/Bistro-Wharf_All-Day-Final-7.7.26.pdf",
        "https://www.bistro-dujour.com/wp-content/uploads/sites/11/2026/03/Bistro-Cap-Hill_Dinner-Final.pdf"
      ]
    },
    "us_ducks_force_fed_2030": {
      "baseline": {
        "value": 500000,
        "as_of": "2026-10-25",
        "source": "Approximate annual bird estimate carried forward from a 2024 literature anchor citing an advocacy source accessed in 2023, not observed 2026 output: https://stetsonlawreview.org/wp-content/uploads/2024/04/12-VanAllen.373-403.pdf, page 389."
      },
      "forecasts": {
        "yes_49.5|failed": {
          "p05": 100000, "p25": 280000, "p50": 450000, "p75": 625000, "p95": 900000
        },
        "yes_50.5|not_certified_or_removed": {
          "p05": 95000, "p25": 275000, "p50": 445000, "p75": 620000, "p95": 895000
        },
        "yes_50.5|certified": {
          "p05": 90000, "p25": 265000, "p50": 435000, "p75": 610000, "p95": 880000
        }
      },
      "reasoning": "The annual 500,000-bird baseline is an old, approximate literature anchor carried forward, not an audited current production count. Disease, national demand and the unresolved NYC market dominate the wide 2030 interval. DC removes a comparatively small market, with modest additional effects through voluntary changes and political momentum.",
      "sources": [
        "https://stetsonlawreview.org/wp-content/uploads/2024/04/12-VanAllen.373-403.pdf",
        "https://www.timesunion.com/food/article/nyc-foe-gras-ban-hudson-valley-courts-22364910.php",
        "https://proanimal.org/how-many-restaurants-in-dc-sell-foie-gras/"
      ]
    },
    "dc_restaurant_employment_2029": {
      "baseline": {
        "value": 51.5,
        "as_of": "2026-09",
        "source": "https://fred.stlouisfed.org/series/SMU11000007072200001; September observation supplied by the brief, retrieved there on 2026-10-25; the accessible public page was older."
      },
      "forecasts": {
        "yes_49.5|failed": {
          "p05": 43, "p25": 49, "p50": 53, "p75": 56.5, "p95": 62
        },
        "yes_50.5|not_certified_or_removed": {
          "p05": 43, "p25": 49, "p50": 53, "p75": 56.5, "p95": 62
        },
        "yes_50.5|certified": {
          "p05": 43, "p25": 49, "p50": 53, "p75": 56.5, "p95": 62
        }
      },
      "reasoning": "I use the brief's September employment observation because the accessible FRED page was older. Weak real restaurant activity favors slow recovery, with recession risk, federal employment and benchmark revisions dominating uncertainty. Substitution for a niche ingredient produces an effect too small to distinguish in these sector-wide quantiles, which are identical across states.",
      "sources": [
        "https://fred.stlouisfed.org/series/SMU11000007072200001",
        "https://ora-cfo.dc.gov/node/1824291",
        "https://proanimal.org/how-many-restaurants-in-dc-sell-foie-gras/"
      ]
    },
    "dc_restaurant_sales_tax_fy2029": {
      "baseline": {
        "value": 567.871,
        "as_of": "2025-09-30",
        "source": "https://ora-cfo.dc.gov/node/1824291; FY2025 collections in millions of dollars, published April 14, 2026, revised April 23."
      },
      "forecasts": {
        "yes_49.5|failed": {
          "p05": 500, "p25": 590, "p50": 650, "p75": 715, "p95": 830
        },
        "yes_50.5|not_certified_or_removed": {
          "p05": 500, "p25": 590, "p50": 650, "p75": 715, "p95": 830
        },
        "yes_50.5|certified": {
          "p05": 500, "p25": 590, "p50": 650, "p75": 715, "p95": 830
        }
      },
      "reasoning": "The ORA table gives FY2025 collections of $567.871 million and documents weak real restaurant activity despite nominal price growth. Continued menu inflation and modest recovery yield a $650 million median, with broad macroeconomic tails. Ingredient substitution makes the I-86 effect too small to distinguish at this precision, so scenario quantiles are identical.",
      "sources": [
        "https://ora-cfo.dc.gov/node/1824291",
        "https://proanimal.org/how-many-restaurants-in-dc-sell-foie-gras/"
      ]
    },
    "dc_michelin_starred_2029": {
      "baseline": {
        "value": 20,
        "as_of": "2026-10-25",
        "source": "https://guide.michelin.com/us/en/district-of-columbia/restaurants/all-starred"
      },
      "forecasts": {
        "yes_49.5|failed": {
          "p05": 14, "p25": 18, "p50": 21, "p75": 24, "p95": 30
        },
        "yes_50.5|not_certified_or_removed": {
          "p05": 14, "p25": 18, "p50": 21, "p75": 24, "p95": 30
        },
        "yes_50.5|certified": {
          "p05": 14, "p25": 18, "p50": 21, "p75": 24, "p95": 30
        }
      },
      "reasoning": "The current official DC listing contains 20 starred restaurants, excluding Virginia establishments. Openings, closures and guide judgments create substantial variation over three years. Foie gras is unnecessary for earning stars, so menu substitution leaves my scenario distributions unchanged.",
      "sources": [
        "https://guide.michelin.com/us/en/district-of-columbia/restaurants/all-starred",
        "https://washingtonian.com/2026/09/17/michelin-adds-4-new-restaurants-to-its-dc-guide/"
      ]
    },
    "dc_animal_initiative_filed": {
      "forecasts": {
        "yes_42.0": {"p": 0.24},
        "yes_49.5": {"p": 0.33},
        "yes_50.5": {"p": 0.41},
        "yes_60.0": {"p": 0.54},
        "yes_72.0": {"p": 0.67}
      },
      "reasoning": "An established local campaign lowers the cost of filing another initiative, even after defeat, while the stalled fur proposal supplies a plausible next target. A bare victory improves perceived feasibility and fundraising; a large victory signals a broader receptive electorate. Filing is much easier than qualifying or enacting a measure.",
      "sources": [
        "https://proanimal.org/wp-content/uploads/paf-2025-financial-transparency-briefing.pdf",
        "https://lims.dccouncil.gov/Legislation/B25-0122",
        "https://www.dcvfa.com/blog/dc-elections-candidates-share-views-on-animals"
      ]
    },
    "dc_another_animal_law": {
      "forecasts": {
        "yes_42.0|filed": {"p": 0.5},
        "yes_42.0|not_filed": {"p": 0.2},
        "yes_49.5|filed": {"p": 0.57},
        "yes_49.5|not_filed": {"p": 0.25},
        "yes_50.5|filed": {"p": 0.64},
        "yes_50.5|not_filed": {"p": 0.29},
        "yes_60.0|filed": {"p": 0.74},
        "yes_60.0|not_filed": {"p": 0.38},
        "yes_72.0|filed": {"p": 0.83},
        "yes_72.0|not_filed": {"p": 0.48}
      },
      "reasoning": "DC's fur proposal attracted substantial sponsorship without enactment, illustrating both political interest and legislative friction. A new filing signals organization and creates a direct path to law, so conditional enactment is appreciably higher. Stronger I-86 support increases both electoral feasibility and Council willingness, while the bare-pass increment remains modest.",
      "sources": [
        "https://lims.dccouncil.gov/Legislation/B25-0122",
        "https://lims.dccouncil.gov/downloads/LIMS/52298/Introduction/B25-0122-Introduction.pdf",
        "https://www.dcvfa.com/blog/dc-elections-candidates-share-views-on-animals"
      ]
    },
    "dc_council_farmed_animal_bills": {
      "forecasts": {
        "yes_42.0": {
          "p05": 0, "p25": 0, "p50": 0, "p75": 1, "p95": 3
        },
        "yes_49.5": {
          "p05": 0, "p25": 0, "p50": 1, "p75": 2, "p95": 4
        },
        "yes_50.5": {
          "p05": 0, "p25": 0, "p50": 1, "p75": 2, "p95": 4
        },
        "yes_60.0": {
          "p05": 0, "p25": 0, "p50": 1, "p75": 3, "p95": 6
        },
        "yes_72.0": {
          "p05": 0, "p25": 1, "p50": 2, "p75": 4, "p95": 8
        }
      },
      "reasoning": "The eligible base rate is low in an urban jurisdiction, especially after excluding pets, wildlife, fur and all I-86-related bills. Campaign organization can generate a small number of broader proposals, and stronger public support expands that opportunity. Integer quantiles need not move after a bare passage even when underlying probabilities do.",
      "sources": [
        "https://www.dcvfa.com/blog/dc-elections-candidates-share-views-on-animals",
        "https://lims.dccouncil.gov/Legislation/B25-0122",
        "https://paxfauna.org/introducing-pro-animal-futures-10-year-plan/"
      ]
    },
    "paf_measures_2027_2028": {
      "forecasts": {
        "yes_42.0|denver_pass": {
          "0": 0.08, "1": 0.25, "2": 0.31, "3": 0.21, "4": 0.1, "5+": 0.05
        },
        "yes_42.0|denver_fail": {
          "0": 0.18, "1": 0.3, "2": 0.28, "3": 0.15, "4": 0.06, "5+": 0.03
        },
        "yes_49.5|denver_pass": {
          "0": 0.06, "1": 0.22, "2": 0.31, "3": 0.23, "4": 0.12, "5+": 0.06
        },
        "yes_49.5|denver_fail": {
          "0": 0.15, "1": 0.29, "2": 0.29, "3": 0.17, "4": 0.07, "5+": 0.03
        },
        "yes_50.5|denver_pass": {
          "0": 0.04, "1": 0.18, "2": 0.3, "3": 0.25, "4": 0.15, "5+": 0.08
        },
        "yes_50.5|denver_fail": {
          "0": 0.1, "1": 0.25, "2": 0.31, "3": 0.2, "4": 0.09, "5+": 0.05
        },
        "yes_60.0|denver_pass": {
          "0": 0.03, "1": 0.14, "2": 0.27, "3": 0.28, "4": 0.17, "5+": 0.11
        },
        "yes_60.0|denver_fail": {
          "0": 0.07, "1": 0.21, "2": 0.3, "3": 0.23, "4": 0.12, "5+": 0.07
        },
        "yes_72.0|denver_pass": {
          "0": 0.02, "1": 0.1, "2": 0.23, "3": 0.29, "4": 0.21, "5+": 0.15
        },
        "yes_72.0|denver_fail": {
          "0": 0.05, "1": 0.16, "2": 0.28, "3": 0.26, "4": 0.15, "5+": 0.1
        }
      },
      "reasoning": "PAF has demonstrated capacity for multiple local campaigns, but its financial briefing makes expansion dependent on funding. Existing infrastructure means further attempts remain likely after losses; wins plausibly attract grants and organizers. These distributions count ballot appearances, excluding Portland-style Council wins and any DC foie gras refiling.",
      "sources": [
        "https://proanimal.org/wp-content/uploads/paf-2025-financial-transparency-briefing.pdf",
        "https://paxfauna.org/introducing-pro-animal-futures-10-year-plan/",
        "https://www.portland.gov/council/documents/ordinance/passed/192190"
      ]
    },
    "paf_statewide_2028": {
      "forecasts": {
        "yes_42.0|denver_pass": {"p": 0.11},
        "yes_42.0|denver_fail": {"p": 0.04},
        "yes_49.5|denver_pass": {"p": 0.14},
        "yes_49.5|denver_fail": {"p": 0.06},
        "yes_50.5|denver_pass": {"p": 0.18},
        "yes_50.5|denver_fail": {"p": 0.1},
        "yes_60.0|denver_pass": {"p": 0.25},
        "yes_60.0|denver_fail": {"p": 0.16},
        "yes_72.0|denver_pass": {"p": 0.34},
        "yes_72.0|denver_fail": {"p": 0.23}
      },
      "reasoning": "PAF has discussed eventual statewide campaigns, but qualification requires substantially greater resources than local measures. Public Oregon and Arizona expansion plans do not establish a qualifying campaign involving the specified species. Success in DC and Denver improves capacity and confidence, but the short timetable keeps probabilities below even odds.",
      "sources": [
        "https://proanimal.org/wp-content/uploads/paf-2025-financial-transparency-briefing.pdf",
        "https://paxfauna.org/introducing-pro-animal-futures-10-year-plan/",
        "https://www.ourhenhouse.org/ep765/",
        "https://proanimaloregon.org/about/"
      ]
    },
    "us_new_coverage_2027_2032": {
      "forecasts": {
        "yes_42.0|statewide": {
          "p05": 0.2, "p25": 8, "p50": 29, "p75": 62, "p95": 125
        },
        "yes_42.0|no_statewide": {
          "p05": 0.1, "p25": 3, "p50": 18, "p75": 42, "p95": 100
        },
        "yes_49.5|statewide": {
          "p05": 0.3, "p25": 10, "p50": 33, "p75": 66, "p95": 130
        },
        "yes_49.5|no_statewide": {
          "p05": 0.1, "p25": 4, "p50": 20, "p75": 46, "p95": 105
        },
        "yes_50.5|statewide": {
          "p05": 0.3, "p25": 11, "p50": 35, "p75": 68, "p95": 132
        },
        "yes_50.5|no_statewide": {
          "p05": 0.1, "p25": 4.5, "p50": 21, "p75": 47, "p95": 107
        },
        "yes_60.0|statewide": {
          "p05": 0.5, "p25": 14, "p50": 40, "p75": 75, "p95": 142
        },
        "yes_60.0|no_statewide": {
          "p05": 0.2, "p25": 6, "p50": 25, "p75": 53, "p95": 115
        },
        "yes_72.0|statewide": {
          "p05": 0.8, "p25": 18, "p50": 48, "p75": 85, "p95": 155
        },
        "yes_72.0|no_statewide": {
          "p05": 0.3, "p25": 8, "p50": 30, "p75": 62, "p95": 128
        }
      },
      "reasoning": "State trackers show episodic expansion alongside delays and repeal pressure; a few populous-state enactments can dominate resident coverage. A qualifying PAF statewide campaign signals movement capacity but need not pass, so even that state's lower tail remains small. Stronger DC results modestly update broader momentum; much legislation proceeds independently, and all specified DC and Denver exclusions are applied.",
      "sources": [
        "https://www.aspca.org/improving-laws-animals/public-policy/farm-animal-confinement-bans",
        "https://www.aspca.org/news/what-lawmakers-did-farm-animals-2025",
        "https://awionline.org/content/farmed-animal-anti-confinement-legislation"
      ]
    },
    "other_foie_gras_bans_2030": {
      "baseline": {
        "value": 3,
        "as_of": "2026-10-25",
        "source": "California, Pittsburgh and Brookline: https://ecode360.com/45472691 and https://ecode360.com/50175714; Portland's prohibition starts December 31, 2026: https://www.portland.gov/council/documents/ordinance/passed/192190; NYC remains enjoined."
      },
      "forecasts": {
        "yes_49.5": {
          "p05": 0, "p25": 4, "p50": 6, "p75": 9, "p95": 16
        },
        "yes_50.5": {
          "p05": 0, "p25": 4, "p50": 7, "p75": 10, "p95": 18
        }
      },
      "reasoning": "The baseline counts California, Pittsburgh and Brookline; Portland's prohibition starts after the cutoff and NYC remains enjoined. Scheduled implementation, possible NYC and Denver additions, and further local campaigns raise the median. A DC win modestly accelerates diffusion, while broad federal preemption or reversals create a zero lower tail.",
      "sources": [
        "https://clerk.assembly.ca.gov/sites/clerk.assembly.ca.gov/files/archive/Statutes/2004/2004_Statutes_1669_Vol_5.pdf",
        "https://ecode360.com/45472691",
        "https://ecode360.com/50175714",
        "https://www.portland.gov/council/documents/ordinance/passed/192190",
        "https://news.bloomberglaw.com/new-york-brief/ny-ag-james-takes-nyc-foie-gras-ban-fight-to-top-state-court",
        "https://www.govinfo.gov/content/pkg/BILLS-119hr7567eh/html/BILLS-119hr7567eh.htm"
      ]
    },
    "federal_preemption_2030": {
      "forecasts": {
        "yes_49.5": {"p": 0.36},
        "yes_50.5": {"p": 0.36}
      },
      "reasoning": "The House-passed 2026 Farm Bill contains production-standard preemption, while the reported Senate bill omits an analogous provision. Senate resistance and negotiations make enactment uncertain, but repeated legislative opportunities through 2030 leave substantial risk, including a pork-only compromise. A bare DC result has negligible influence on this national contest, so probabilities are equal.",
      "sources": [
        "https://repcloakroom.house.gov/floor/thursday-april-30th-2026/",
        "https://www.govinfo.gov/content/pkg/BILLS-119hr7567eh/html/BILLS-119hr7567eh.htm",
        "https://www.govinfo.gov/content/pkg/BILLS-119s5526rs/html/BILLS-119s5526rs.htm",
        "https://www.schiff.senate.gov/news/press-releases/statement-sens-schiff-booker-urge-removal-of-farm-bill-language-that-preempts-state-laws/"
      ]
    },
    "dc_bans_other_food_2030": {
      "forecasts": {
        "yes_49.5": {"p": 0.22},
        "yes_50.5": {"p": 0.23}
      },
      "reasoning": "Broad additive bans in other states provide a plausible model for DC, although no pending citywide qualifying prohibition was located. Federal ingredient action can reduce the need for local legislation. Most probability comes from these independent developments; a bare I-86 victory adds only a small precedent effect.",
      "sources": [
        "https://www.gov.ca.gov/wp-content/uploads/2023/10/AB-418-Signing.pdf",
        "https://governor.wv.gov/article/governor-patrick-morrisey-signs-food-dye-legislation-law",
        "https://lims.dccouncil.gov/"
      ]
    }
  }
}
```
