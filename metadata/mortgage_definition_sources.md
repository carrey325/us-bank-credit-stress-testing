# Closed-end Mortgage Definition and Sources

Batch 1 defines the Mortgage segment as **closed-end loans secured by 1-4 family residential properties**, excluding revolving/open-end HELOC exposure. The definition follows the Proposal Appendix B and is applied consistently to the balance and RI-B net-charge-off numerator.

| Component | MDRMs | Treatment |
|---|---|---|
| Closed-end exposure | RCON/RCFD5367 (first lien), RCON/RCFD5368 (junior lien) | Sum both liens. |
| Closed-end charge-offs | RIADC234 (first lien), RIADC235 (junior lien) | Quarterize each YTD series, then sum. |
| Closed-end recoveries | RIADC217 (first lien), RIADC218 (junior lien) | Quarterize each YTD series, then sum. |
| Excluded open-end exposure | RCON/RCFD1797 | Do not map to Mortgage. |

The FFIEC MDRM/validation material identifies RCON1797 as revolving, open-end 1-4 family lending and identifies RCON5367/5368 as the closed-end first- and junior-lien components. The Federal Reserve MDRM definitions for RIADC235 and RIADC218 identify them as the corresponding closed-end junior-lien RI-B charge-off and recovery items. These MDRMs are available in every retained archive from the project start, so this repair uses 2005Q1--2025Q4 rather than treating 2020 as the beginning of Mortgage NCO coverage.

Sources:

- [FFIEC validation information for RC-C closed-end and revolving 1-4 family items](https://www.ffiec.gov/PDF/FFIEC_forms/FFIEC031_041edits_200203.pdf)
- [Federal Reserve MDRM: RIADC235](https://www.federalreserve.gov/apps/mdrm/data-dictionary/search/item?keyword=C235)
- [Federal Reserve MDRM: RIADC218](https://www.federalreserve.gov/apps/mdrm/data-dictionary/search/item?keyword=C218)
- [FFIEC 031/041 historical reporting materials](https://www.ffiec.gov/resources/reporting-forms/ffiec041)
