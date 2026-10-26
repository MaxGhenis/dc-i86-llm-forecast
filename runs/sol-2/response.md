```json
{
  "forecaster": {
    "model": "GPT-6 (Codex)",
    "prior_context": "none",
    "notes": "Evidence cutoff: 2026-10-25. Only the brief and public sources were used; no local files were read. Menu baselines are estimates because complete October censuses were not located. The domestic-bird baseline is an uncertain industry proxy. September employment comes from the brief because the retrieved FRED page was stale. Identical macroeconomic quantiles indicate effects too small to distinguish at the reported precision."
  },
  "research_summary": "Reviewed DCBOE historical results and legal opinions, the fiscal statement, sponsor polling and menu research, CSU surveys, campaign reporting, Michelin listings, ORA revenue data, PAF finances and strategy, existing ordinances and litigation, and federal farm-bill proposals. No recent independent DC ballot poll was located. The forecast favors passage, distinguishes certification from enforceability, and anticipates modest political spillovers with very small aggregate restaurant-sector effects.",
  "nodes": {
    "yes_share": {
      "forecasts": {
        "all": {
          "le_30": 0.003,
          "le_35": 0.009,
          "le_40": 0.025,
          "le_45": 0.057,
          "le_47": 0.082,
          "le_48": 0.098,
          "le_49": 0.116,
          "le_50": 0.136,
          "le_51": 0.158,
          "le_52": 0.181,
          "le_53": 0.206,
          "le_55": 0.260,
          "le_60": 0.415,
          "le_65": 0.595,
          "le_70": 0.765,
          "le_75": 0.892,
          "le_80": 0.964,
          "le_85": 0.992,
          "le_90": 0.999
        }
      },
      "reasoning": "The favorable Dynata survey is old, advocacy-commissioned and not a current ballot poll, so I discount it heavily. DC's initiative history and the narrow luxury-product target favor passage; chef opposition, broad operative language and survey-to-ballot erosion create a substantial failure tail. My distribution is more favorable than the published historical model but much less favorable than the sponsor's survey.",
      "sources": [
        "https://proanimal.org/78-of-dc-voters-want-to-end-the-sale-of-force-fed-foie-gras/",
        "https://www.onpointpolitics.us/forecast/measures/dc/initiative-86",
        "https://www.axios.com/local/washington-dc/2026/10/23/jose-andres-dc-foie-gras-ban-chef-protest",
        "https://electionresults.dcboe.org/Downloads/Reports/November_8_2022_General_Election_Certified_Results.pdf"
      ]
    },
    "turnout": {
      "forecasts": {
        "all": {
          "p05": 165000,
          "p25": 190000,
          "p50": 212000,
          "p75": 235000,
          "p95": 270000
        }
      },
      "reasoning": "The 2022 general election had 205774 ballots and 179786 valid I-82 votes; 2018 turnout was 231700 ballots. I expect stronger midterm participation than in 2022, tempered by ballot-question undervoting, population uncertainty and limited general-election competition.",
      "sources": [
        "https://electionresults.dcboe.org/Downloads/Reports/November_8_2022_General_Election_Certified_Results.pdf",
        "https://dcboe.org/getmedia/43b7cf66-9a77-45c5-8ee7-c8fe96d121d0/FINALDraft-2018GEAfterActionReport020219.pdf",
        "https://dc.citycast.fm/dc-politics/dc-2026-general-election-voter-guide"
      ]
    },
    "denver_io311_passes": {
      "forecasts": {
        "yes_42.0": {"p": 0.45},
        "yes_49.5": {"p": 0.62},
        "yes_50.5": {"p": 0.64},
        "yes_60.0": {"p": 0.82},
        "yes_72.0": {"p": 0.94}
      },
      "reasoning": "Favorable CSU survey evidence, the Denver Democrats endorsement and the limited commercial target favor passage, while the failed 2024 animal measures caution against taking abstract support literally. DC's margin updates shared uncertainty about voters' willingness to approve product bans. The difference between the two closest cells is entirely informational, with no causal effect on Denver.",
      "sources": [
        "https://sites.warnercnr.colostate.edu/animalhumanpolicy/ahpc-studies-document-the-prevalence-of-foie-gras-on-menus-and-denver-voters-support-of-a-foie-gras-ban/",
        "https://proanimal.org/new-csu-study-finds-87-percent-of-americans-support-ban-on-force-fed-foie-gras/",
        "https://denverdemsgotv.com/ballot-measures",
        "https://denverite.com/2026/09/25/vg-2026-initiated-ordinance-311-force-feeding-birds-ban-voter-guide/",
        "https://www.axios.com/local/denver/2024/11/06/colorado-election-results-mountain-lion-hunting-slaughterhouse-ban"
      ]
    },
    "ban_status": {
      "forecasts": {
        "yes_50.5": {
          "repealed": 0.16,
          "congress": 0.15,
          "court": 0.11,
          "not_certified": 0.17,
          "certified": 0.41
        },
        "yes_60.0": {
          "repealed": 0.10,
          "congress": 0.14,
          "court": 0.11,
          "not_certified": 0.13,
          "certified": 0.52
        },
        "yes_72.0": {
          "repealed": 0.05,
          "congress": 0.13,
          "court": 0.10,
          "not_certified": 0.10,
          "certified": 0.62
        }
      },
      "reasoning": "DC has altered voter-approved restaurant legislation, but this measure's small fiscal cost makes eventual funding plausible. Favorable DC legal opinions and California precedent reduce whole-ban injunction risk; Congress poses both DC-specific and broader preemption risks. Larger wins chiefly reduce Council reversal and noncertification, with probabilities following the question's priority order.",
      "sources": [
        "https://dcboe.org/getmedia/8ed77952-835c-4a11-9fa2-2ad447d82643/Final-FIS-Initiative-Prohibiting-the-Force-Feeding-of-Birds-Act-of-2026.pdf",
        "https://dcboe.org/getmedia/4de57ea1-74d2-4371-ba9f-75828c12c5a1/AL-25-339-C-20-20BOE-20-20Prohibiting-20Force-20Feeding-20of-20Birds-20Act-20of-202026-20Initiative.pdf",
        "https://dccouncil.gov/council-pushes-back-restoring-cut-funds-and-reasserting-appropriators-role/",
        "https://agriculture.house.gov/UploadedFiles/FINAL_2026_Prop12_OnePager.pdf",
        "https://cdn.ca9.uscourts.gov/datastore/opinions/2022/05/06/20-55882.pdf"
      ]
    },
    "lawsuit_filed": {
      "forecasts": {
        "yes_50.5|blocked": {"p": 1.0},
        "yes_50.5|not_blocked": {"p": 0.65},
        "yes_60.0|blocked": {"p": 1.0},
        "yes_60.0|not_blocked": {"p": 0.66},
        "yes_72.0|blocked": {"p": 1.0},
        "yes_72.0|not_blocked": {"p": 0.67}
      },
      "reasoning": "A qualifying court block entails a lawsuit. The announced prospective legal defense fund and persistent litigation over other foie gras bans make a filing fairly likely even without a lasting injunction. Stronger margins make implementation more certain and slightly increase incentives to litigate.",
      "sources": [
        "https://www.axios.com/local/washington-dc/2026/10/23/jose-andres-dc-foie-gras-ban-chef-protest",
        "https://dcboe.org/getmedia/4de57ea1-74d2-4371-ba9f-75828c12c5a1/AL-25-339-C-20-20BOE-20-20Prohibiting-20Force-20Feeding-20of-20Birds-20Act-20of-202026-20Initiative.pdf",
        "https://www.nycourts.gov/reporter/3dseries/2026/2026_01426.htm"
      ]
    },
    "fattened_narrowed": {
      "forecasts": {
        "yes_50.5|certified": {"p": 0.65},
        "yes_50.5|not_certified": {"p": 0.28}
      },
      "reasoning": "The operative definition is broad, but the summary and legislative purpose focus on force-feeding. Funded implementation creates an opportunity for a formal rule or corrective amendment. Without certification, officials are more likely to postpone the issue or rely on informal interpretations that do not satisfy resolution.",
      "sources": [
        "https://proanimaldc.org/prohibit-force-feeding-of-birds-act/",
        "https://dcboe.org/getmedia/4de57ea1-74d2-4371-ba9f-75828c12c5a1/AL-25-339-C-20-20BOE-20-20Prohibiting-20Force-20Feeding-20of-20Birds-20Act-20of-202026-20Initiative.pdf",
        "https://dcboe.org/getmedia/8ed77952-835c-4a11-9fa2-2ad447d82643/Final-FIS-Initiative-Prohibiting-the-Force-Feeding-of-Birds-Act-of-2026.pdf"
      ]
    },
    "pate_treated_banned": {
      "forecasts": {
        "yes_50.5|narrowed_certified": {"p": 0.025},
        "yes_50.5|narrowed_not_certified": {"p": 0.005},
        "yes_50.5|not_narrowed_certified": {"p": 0.22},
        "yes_50.5|not_narrowed_not_certified": {"p": 0.04}
      },
      "reasoning": "Purpose-based interpretation makes ordinary poultry-liver enforcement uncommon even without formal narrowing. Certification supplies enforcement capacity, and one qualifying determination could arise under the broad wording. Narrowing leaves a small positive probability because enforcement can precede the final rule or amendment.",
      "sources": [
        "https://proanimaldc.org/prohibit-force-feeding-of-birds-act/",
        "https://dcboe.org/getmedia/4de57ea1-74d2-4371-ba9f-75828c12c5a1/AL-25-339-C-20-20BOE-20-20Prohibiting-20Force-20Feeding-20of-20Birds-20Act-20of-202026-20Initiative.pdf",
        "https://dcboe.org/getmedia/8ed77952-835c-4a11-9fa2-2ad447d82643/Final-FIS-Initiative-Prohibiting-the-Force-Feeding-of-Birds-Act-of-2026.pdf"
      ]
    },
    "foie_gras_menus": {
      "baseline": {
        "value": 40,
        "as_of": "2026-10-25",
        "source": "Forecaster estimate, not a completed October census. Anchored to the 48-restaurant October–December 2025 census published August 18, 2026: https://proanimal.org/how-many-restaurants-in-dc-sell-foie-gras/ ; seasonal evidence: https://washingtonian.com/2025/07/23/it-just-got-a-little-harder-to-find-foie-gras-in-dc/"
      },
      "forecasts": {
        "yes_49.5|failed": {
          "p05": 22,
          "p25": 34,
          "p50": 45,
          "p75": 57,
          "p95": 75
        },
        "yes_50.5|removed": {
          "p05": 15,
          "p25": 29,
          "p50": 40,
          "p75": 53,
          "p95": 72
        },
        "yes_50.5|not_certified": {
          "p05": 0,
          "p25": 5,
          "p50": 20,
          "p75": 37,
          "p95": 58
        },
        "yes_50.5|certified": {
          "p05": 0,
          "p25": 0,
          "p50": 1,
          "p75": 3,
          "p95": 8
        }
      },
      "reasoning": "The latest published census found 48 restaurants in late 2025, while summer reporting found considerably fewer; the October baseline is therefore an estimate. December seasonality and turnover explain the broad unregulated range. Certification nearly eliminates explicit listings; noncertification leaves mixed legal interpretations and voluntary compliance, while removal still leaves campaign-related attrition.",
      "sources": [
        "https://proanimal.org/how-many-restaurants-in-dc-sell-foie-gras/",
        "https://washingtonian.com/2025/07/23/it-just-got-a-little-harder-to-find-foie-gras-in-dc/",
        "https://proanimaldc.org/prohibit-force-feeding-of-birds-act/",
        "https://dcboe.org/getmedia/8ed77952-835c-4a11-9fa2-2ad447d82643/Final-FIS-Initiative-Prohibiting-the-Force-Feeding-of-Birds-Act-of-2026.pdf"
      ]
    },
    "liver_pate_menus": {
      "baseline": {
        "value": 55,
        "as_of": "2026-10-25",
        "source": "Forecaster estimate, not an observed citywide count. Informed by a partial check of establishment menus including https://www.restaurantchloe.com/menu/dinner/ and https://www.riggsdc.com/eat-drink/cafe-riggs-menus/ . A complete October census was not available."
      },
      "forecasts": {
        "yes_49.5|failed": {
          "p05": 28,
          "p25": 42,
          "p50": 58,
          "p75": 78,
          "p95": 115
        },
        "yes_50.5|removed": {
          "p05": 25,
          "p25": 40,
          "p50": 55,
          "p75": 75,
          "p95": 110
        },
        "yes_50.5|standing_pate_allowed": {
          "p05": 25,
          "p25": 40,
          "p50": 57,
          "p75": 80,
          "p95": 120
        },
        "yes_50.5|standing_pate_banned": {
          "p05": 5,
          "p25": 15,
          "p50": 32,
          "p75": 55,
          "p95": 90
        }
      },
      "reasoning": "No citywide census was located; the baseline is an uncertain estimate informed by current own-menu listings. Substitution away from foie gras can support ordinary liver dishes when allowed. The banned state requires only one determination, so it need not imply universal enforcement, and pork or beef liver dishes can remain.",
      "sources": [
        "https://www.dauphinesdc.com/menu/raw-bar/",
        "https://ameliewinebar.com/dc/menus/dinner",
        "https://www.restaurantchloe.com/menu/dinner/",
        "https://www.riggsdc.com/eat-drink/cafe-riggs-menus/",
        "https://www.bistro-dujour.com/wp-content/uploads/sites/11/2026/03/Bistro-Cap-Hill_Dinner-Final.pdf",
        "https://proanimaldc.org/prohibit-force-feeding-of-birds-act/"
      ]
    },
    "us_ducks_force_fed_2030": {
      "baseline": {
        "value": 350000,
        "as_of": "2026-10-25",
        "source": "Current proxy, not a verified 2026 observation: approximately 350000 birds annually in a 2021 industry report, https://www.meatpoultry.com/articles/26258-specialty-processing-demand-versus-ethics , repeated in 2026 Portland testimony, https://www.portland.gov/sites/default/files/council-documents/2026/2026-149-testimony.pdf"
      },
      "forecasts": {
        "yes_49.5|failed": {
          "p05": 50000,
          "p25": 180000,
          "p50": 300000,
          "p75": 430000,
          "p95": 650000
        },
        "yes_50.5|not_certified_or_removed": {
          "p05": 50000,
          "p25": 178000,
          "p50": 298000,
          "p75": 428000,
          "p95": 648000
        },
        "yes_50.5|certified": {
          "p05": 45000,
          "p25": 175000,
          "p50": 294000,
          "p75": 424000,
          "p95": 645000
        }
      },
      "reasoning": "The baseline is an uncertain annual industry estimate rather than official current production data. National demand, avian influenza, producer survival, exports and New York litigation dominate the range. DC removes a modest amount of domestic demand when certified, with leakage and substitution limiting the effect.",
      "sources": [
        "https://www.meatpoultry.com/articles/26258-specialty-processing-demand-versus-ethics",
        "https://www.portland.gov/sites/default/files/council-documents/2026/2026-149-testimony.pdf",
        "https://proanimal.org/how-many-restaurants-in-dc-sell-foie-gras/"
      ]
    },
    "dc_restaurant_employment_2029": {
      "baseline": {
        "value": 51.5,
        "as_of": "2026-09",
        "source": "BLS series SMU11000007072200001 via https://fred.stlouisfed.org/series/SMU11000007072200001 . September value supplied in the brief; the retrieved public page still displayed August."
      },
      "forecasts": {
        "yes_49.5|failed": {
          "p05": 43,
          "p25": 48.5,
          "p50": 52,
          "p75": 55.5,
          "p95": 61
        },
        "yes_50.5|not_certified_or_removed": {
          "p05": 43,
          "p25": 48.5,
          "p50": 52,
          "p75": 55.5,
          "p95": 61
        },
        "yes_50.5|certified": {
          "p05": 43,
          "p25": 48.5,
          "p50": 52,
          "p75": 55.5,
          "p95": 61
        }
      },
      "reasoning": "Federal employment, tourism, office attendance, labor costs and the business cycle dominate employment through 2029. Diners mostly substitute other dishes, so I assign the same rounded distribution across scenarios. The baseline uses the brief's September observation because the retrieved FRED page was stale.",
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
        "source": "FY2025 collections in millions of dollars; ORA article published April 14, 2026 and revised April 23: https://ora-cfo.dc.gov/node/1824291"
      },
      "forecasts": {
        "yes_49.5|failed": {
          "p05": 480,
          "p25": 575,
          "p50": 650,
          "p75": 720,
          "p95": 850
        },
        "yes_50.5|not_certified_or_removed": {
          "p05": 480,
          "p25": 575,
          "p50": 650,
          "p75": 720,
          "p95": 850
        },
        "yes_50.5|certified": {
          "p05": 480,
          "p25": 575,
          "p50": 650,
          "p75": 720,
          "p95": 850
        }
      },
      "reasoning": "ORA documents weak real restaurant activity despite nominal revenue recovery. Inflation and modest recovery support a higher nominal median, while recession, federal retrenchment and dining-demand uncertainty create a broad range. Spending substitution makes the initiative's expected effect too small to distinguish at this precision.",
      "sources": [
        "https://ora-cfo.dc.gov/node/1824291",
        "https://proanimal.org/how-many-restaurants-in-dc-sell-foie-gras/"
      ]
    },
    "dc_michelin_starred_2029": {
      "baseline": {
        "value": 20,
        "as_of": "2026-10-25",
        "source": "Michelin's DC-only starred restaurant listing, excluding Virginia restaurants: https://guide.michelin.com/us/en/district-of-columbia/restaurants/all-starred"
      },
      "forecasts": {
        "yes_49.5|failed": {
          "p05": 13,
          "p25": 18,
          "p50": 21,
          "p75": 25,
          "p95": 31
        },
        "yes_50.5|not_certified_or_removed": {
          "p05": 13,
          "p25": 18,
          "p50": 21,
          "p75": 25,
          "p95": 31
        },
        "yes_50.5|certified": {
          "p05": 13,
          "p25": 18,
          "p50": 21,
          "p75": 25,
          "p95": 31
        }
      },
      "reasoning": "Michelin currently lists 20 starred restaurants within DC. Openings, closures and guide decisions dominate the next several editions; established starred dining under California's ban supports culinary substitution. I therefore use the same distribution across scenarios.",
      "sources": [
        "https://guide.michelin.com/us/en/district-of-columbia/restaurants/all-starred",
        "https://guide.michelin.com/ca/en/article/michelin-guide-ceremony/guide-michelin-california"
      ]
    },
    "dc_animal_initiative_filed": {
      "forecasts": {
        "yes_42.0": {"p": 0.16},
        "yes_49.5": {"p": 0.22},
        "yes_50.5": {"p": 0.34},
        "yes_60.0": {"p": 0.44},
        "yes_72.0": {"p": 0.58}
      },
      "reasoning": "The existing advocacy network and I-86 volunteer organization make another filing plausible, but no concrete qualifying successor surfaced. A narrow win validates the initiative route and helps fundraising; a larger win additionally signals a receptive electorate. Failure still leaves an organization capable of changing topics.",
      "sources": [
        "https://proanimaldc.org/about/",
        "https://proanimal.org/wp-content/uploads/paf-2025-financial-transparency-briefing.pdf",
        "https://legiscan.com/DC/text/B25-0122/id/2689178/Washington_D_C_-2023-B25-0122-Introduced.pdf"
      ]
    },
    "dc_another_animal_law": {
      "forecasts": {
        "yes_42.0|filed": {"p": 0.48},
        "yes_42.0|not_filed": {"p": 0.18},
        "yes_49.5|filed": {"p": 0.54},
        "yes_49.5|not_filed": {"p": 0.22},
        "yes_50.5|filed": {"p": 0.60},
        "yes_50.5|not_filed": {"p": 0.25},
        "yes_60.0|filed": {"p": 0.68},
        "yes_60.0|not_filed": {"p": 0.30},
        "yes_72.0|filed": {"p": 0.75},
        "yes_72.0|not_filed": {"p": 0.38}
      },
      "reasoning": "A filed initiative demonstrates organized pressure, though qualification and passage remain uncertain. The earlier fur bill supplies a legislative route even without another initiative, while its stalled progress cautions against assuming enactment. Passage and larger margins increase political permission; I-86 amendments themselves are excluded.",
      "sources": [
        "https://legiscan.com/DC/text/B25-0122/id/2689178/Washington_D_C_-2023-B25-0122-Introduced.pdf",
        "https://dccouncil.gov/wp-content/uploads/2024/09/10.9-JPS-PUB-HRNG-B25-245-Gun-Liability-and-B25-122-Fur-Hearing-Notice.pdf",
        "https://proanimaldc.org/about/"
      ]
    },
    "dc_council_farmed_animal_bills": {
      "forecasts": {
        "yes_42.0": {
          "p05": 0,
          "p25": 0,
          "p50": 0,
          "p75": 1,
          "p95": 4
        },
        "yes_49.5": {
          "p05": 0,
          "p25": 0,
          "p50": 0,
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
          "p95": 6
        },
        "yes_72.0": {
          "p05": 0,
          "p25": 1,
          "p50": 2,
          "p75": 4,
          "p95": 8
        }
      },
      "reasoning": "The baseline flow of qualifying legislation is sparse, particularly after excluding fur and I-86 bills. A successful campaign creates organizers, allies and a demonstrated constituency, with a strong win increasing the chance of multiple proposals. Reintroductions across Council periods contribute to the upper tail.",
      "sources": [
        "https://legiscan.com/DC/text/B25-0122/id/2689178/Washington_D_C_-2023-B25-0122-Introduced.pdf",
        "https://dccouncil.gov/wp-content/uploads/2024/09/10.9-JPS-PUB-HRNG-B25-245-Gun-Liability-and-B25-122-Fur-Hearing-Notice.pdf",
        "https://proanimaldc.org/campaign-endorsements/",
        "https://proanimal.org/wp-content/uploads/paf-2025-financial-transparency-briefing.pdf"
      ]
    },
    "paf_measures_2027_2028": {
      "forecasts": {
        "yes_42.0|denver_pass": {
          "0": 0.10,
          "1": 0.24,
          "2": 0.31,
          "3": 0.20,
          "4": 0.10,
          "5+": 0.05
        },
        "yes_42.0|denver_fail": {
          "0": 0.18,
          "1": 0.28,
          "2": 0.29,
          "3": 0.15,
          "4": 0.07,
          "5+": 0.03
        },
        "yes_49.5|denver_pass": {
          "0": 0.08,
          "1": 0.21,
          "2": 0.32,
          "3": 0.21,
          "4": 0.12,
          "5+": 0.06
        },
        "yes_49.5|denver_fail": {
          "0": 0.15,
          "1": 0.27,
          "2": 0.30,
          "3": 0.17,
          "4": 0.08,
          "5+": 0.03
        },
        "yes_50.5|denver_pass": {
          "0": 0.06,
          "1": 0.18,
          "2": 0.31,
          "3": 0.24,
          "4": 0.14,
          "5+": 0.07
        },
        "yes_50.5|denver_fail": {
          "0": 0.11,
          "1": 0.23,
          "2": 0.31,
          "3": 0.21,
          "4": 0.10,
          "5+": 0.04
        },
        "yes_60.0|denver_pass": {
          "0": 0.04,
          "1": 0.14,
          "2": 0.29,
          "3": 0.26,
          "4": 0.17,
          "5+": 0.10
        },
        "yes_60.0|denver_fail": {
          "0": 0.08,
          "1": 0.19,
          "2": 0.31,
          "3": 0.23,
          "4": 0.13,
          "5+": 0.06
        },
        "yes_72.0|denver_pass": {
          "0": 0.03,
          "1": 0.11,
          "2": 0.26,
          "3": 0.27,
          "4": 0.19,
          "5+": 0.14
        },
        "yes_72.0|denver_fail": {
          "0": 0.06,
          "1": 0.15,
          "2": 0.28,
          "3": 0.25,
          "4": 0.16,
          "5+": 0.10
        }
      },
      "reasoning": "PAF returned after its 2024 defeats and has demonstrated capacity for multiple local campaigns. Its financial briefing contemplated Oregon and Arizona work for 2028, but funding and qualification constrain expansion. Wins increase donor confidence and replication, while losses lower campaign counts without implying organizational collapse.",
      "sources": [
        "https://proanimal.org/wp-content/uploads/paf-2025-financial-transparency-briefing.pdf",
        "https://proanimal.org/about/",
        "https://www.westword.com/news/animal-rights-ballot-measures-lose-big-in-colorado-22451796/",
        "https://www.portland.gov/council/documents/ordinance/passed/192190"
      ]
    },
    "paf_statewide_2028": {
      "forecasts": {
        "yes_42.0|denver_pass": {"p": 0.10},
        "yes_42.0|denver_fail": {"p": 0.06},
        "yes_49.5|denver_pass": {"p": 0.12},
        "yes_49.5|denver_fail": {"p": 0.07},
        "yes_50.5|denver_pass": {"p": 0.17},
        "yes_50.5|denver_fail": {"p": 0.11},
        "yes_60.0|denver_pass": {"p": 0.23},
        "yes_60.0|denver_fail": {"p": 0.16},
        "yes_72.0|denver_pass": {"p": 0.33},
        "yes_72.0|denver_fail": {"p": 0.24}
      },
      "reasoning": "Statewide qualification requires substantially more funding and signatures than municipal qualification. The contemplated 2028 campaigns did not establish a qualifying species or statewide scope. Success in DC and Denver can attract resources, but even two strong wins leave most probability on no qualifying statewide measure.",
      "sources": [
        "https://proanimal.org/wp-content/uploads/paf-2025-financial-transparency-briefing.pdf",
        "https://proanimal.org/about/"
      ]
    },
    "us_new_coverage_2027_2032": {
      "forecasts": {
        "yes_42.0|statewide": {
          "p05": 0,
          "p25": 5,
          "p50": 20,
          "p75": 45,
          "p95": 100
        },
        "yes_42.0|no_statewide": {
          "p05": 0,
          "p25": 2,
          "p50": 12,
          "p75": 32,
          "p95": 80
        },
        "yes_49.5|statewide": {
          "p05": 0,
          "p25": 6,
          "p50": 22,
          "p75": 48,
          "p95": 105
        },
        "yes_49.5|no_statewide": {
          "p05": 0,
          "p25": 3,
          "p50": 14,
          "p75": 36,
          "p95": 85
        },
        "yes_50.5|statewide": {
          "p05": 0,
          "p25": 7,
          "p50": 24,
          "p75": 51,
          "p95": 110
        },
        "yes_50.5|no_statewide": {
          "p05": 0,
          "p25": 3.5,
          "p50": 15,
          "p75": 38,
          "p95": 90
        },
        "yes_60.0|statewide": {
          "p05": 0,
          "p25": 9,
          "p50": 29,
          "p75": 58,
          "p95": 120
        },
        "yes_60.0|no_statewide": {
          "p05": 0,
          "p25": 4,
          "p50": 18,
          "p75": 44,
          "p95": 100
        },
        "yes_72.0|statewide": {
          "p05": 0,
          "p25": 11,
          "p50": 35,
          "p75": 68,
          "p95": 140
        },
        "yes_72.0|no_statewide": {
          "p05": 0,
          "p25": 5,
          "p50": 23,
          "p75": 54,
          "p95": 115
        }
      },
      "reasoning": "Existing state-law diffusion supports additional coverage without a PAF statewide campaign. Qualification signals resources and opportunity but does not guarantee enactment; large-state laws create a long upper tail, while preemption and legislative resistance allow very low outcomes. Populations are counted once under the resolution definition, excluding the specified DC and Denver measures.",
      "sources": [
        "https://awionline.org/resources/enforcement-of-state-farmed-animal-welfare-laws/",
        "https://awionline.org/sites/default/files/publication/digital_download/awi-enforcement-of-state-farmed-animal-welfare-laws-2024.pdf",
        "https://awionline.org/awi-quarterly/spring-2025/cage-free-laws-in-the-crosshairs/",
        "https://proanimal.org/wp-content/uploads/paf-2025-financial-transparency-briefing.pdf",
        "https://agriculture.house.gov/UploadedFiles/FINAL_2026_Prop12_OnePager.pdf"
      ]
    },
    "other_foie_gras_bans_2030": {
      "baseline": {
        "value": 3,
        "as_of": "2026-10-25",
        "source": "California, Pittsburgh and Brookline. Pittsburgh code: https://ecode360.com/45472700 ; Brookline approval: https://www.brooklinema.gov/m/newsflash/Archive/Item/2502?arcId=4570 ; tracker: https://www.peta.org/features/foie-gras-bans/ . Excludes not-yet-effective Portland and enjoined NYC."
      },
      "forecasts": {
        "yes_49.5": {
          "p05": 0,
          "p25": 4,
          "p50": 7,
          "p75": 10,
          "p95": 18
        },
        "yes_50.5": {
          "p05": 0,
          "p25": 4,
          "p50": 8,
          "p75": 11,
          "p95": 20
        }
      },
      "reasoning": "California, Pittsburgh and Brookline form the current in-force baseline; Portland is scheduled for December 2026, and NYC remains subject to separate litigation. Municipal diffusion and possible Denver or NYC enforcement support additional bans. Broad federal preemption creates a lower tail below today's count, while DC passage modestly improves replication prospects.",
      "sources": [
        "https://ecode360.com/45472700",
        "https://www.brooklinema.gov/m/newsflash/Archive/Item/2502?arcId=4570",
        "https://www.portland.gov/council/documents/ordinance/passed/192190",
        "https://www.nycourts.gov/reporter/3dseries/2026/2026_01426.htm",
        "https://www.timesunion.com/food/article/nyc-foe-gras-ban-hudson-valley-courts-22364910.php",
        "https://www.peta.org/features/foie-gras-bans/",
        "https://agriculture.house.gov/UploadedFiles/FINAL_2026_Prop12_OnePager.pdf"
      ]
    },
    "federal_preemption_2030": {
      "forecasts": {
        "yes_49.5": {"p": 0.47},
        "yes_50.5": {"p": 0.47}
      },
      "reasoning": "The House-passed 2026 farm bill contains a live production-based sales preemption proposal, while Senate bargaining has left the issue unresolved. Agricultural-industry pressure and multiple legislative opportunities through 2030 create substantial enactment risk, tempered by opposition and changing congressional control. DC's one-point difference has negligible influence on this national outcome.",
      "sources": [
        "https://rules.house.gov/bill/119/hr-7567",
        "https://agriculture.house.gov/UploadedFiles/FINAL_2026_Prop12_OnePager.pdf",
        "https://www.ernst.senate.gov/news/press-releases/ernst-welcomes-farm-bill-progress-more-work-needed",
        "https://www.faama.org/dc-weekly-update-10-9-26/"
      ]
    },
    "dc_bans_other_food_2030": {
      "forecasts": {
        "yes_49.5": {"p": 0.24},
        "yes_50.5": {"p": 0.28}
      },
      "reasoning": "Food-additive restrictions spreading across states provide a route independent of animal advocacy, although no concrete qualifying DC proposal was located. Another animal-product restriction adds a smaller route. A bare I-86 victory modestly increases willingness to use a citywide food-sale prohibition without making another ban likely.",
      "sources": [
        "https://www.fda.gov/industry/color-additives",
        "https://chlpi.org/wp-content/uploads/2025/12/State-Regulation-of-Food-Additives-and-Chemicals_FINAL_.pdf",
        "https://legiscan.com/DC/text/B25-0122/id/2689178/Washington_D_C_-2023-B25-0122-Introduced.pdf"
      ]
    }
  }
}
```
