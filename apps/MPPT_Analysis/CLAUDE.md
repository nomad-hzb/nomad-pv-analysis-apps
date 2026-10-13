# MPPT_Analysis: traps of this app

Read `FITTING.md` before changing any fitting maths: it defines T95/T80/Ts95/Ts80, the stabilization time, and the lifetime energy yield, and says which units go to NOMAD (times in seconds, LEY in kWh/m²).
- The fit results written back to NOMAD change stored numbers; a change to a definition needs the manual and `FITTING.md` updated in the same PR.
- Power is positive inside the app (the sign is detected per entry); NOMAD stores generated power as negative.
- A fit already stored in NOMAD is shown in the results table (`stored_fit_from_archive`); the processed archive may lack `fit_method` and `fit_parameters`.
