# LCC Calculator: user manual

## What the app is for

Estimate the cost of making a batch of solar cells (life cycle costing): the cost of the processes,
the materials, the equipment (gloveboxes and tools), overhead items such as rent and disposal, and
labour. The processes and materials are read from the entries of the selected batches in NOMAD;
the prices come from one shared file, `cost_reference.xlsx`, kept by an administrator in this
app's folder. The app only reads from NOMAD.

**Read the figures with the warning marks in mind.** A cost that is not in the reference file is
unknown, not zero. Totals that leave out unknown items are shown as a lower bound
("≥ ... (incomplete)").

## Data it needs

- Batches in NOMAD with their process entries (spin coating, evaporation, annealing and so on)
  and the materials used in them.
- The cost reference file `cost_reference.xlsx` (sheets *Materials*, *Processes*, *Labor* and
  *Capital_Overhead_Disposal*, plus a *Guide* for administrators). You do not upload anything; the
  app reads the shared file when you load batches.

## Step by step

1. **Select batches.** *Filter by user* and *Search Batch* narrow the list; select one or more
   batches and click *Load Data*. The status box then says how many process types and materials
   were found and how many entries of the cost reference were applied. It also says if the file is
   missing, if none of its costs is filled in, or which cells could not be used (those count as
   missing).
2. **Processes.** One row per batch and process type with the number of steps, the location(s)
   (gloveboxes or tools as typed in NOMAD), the *Process Cost* and the *Equipment Cost*.
   - The process cost is the cost the reference gives for that process type, once per batch.
   - The equipment cost belongs to a location and is counted **once per batch and location**, even
     if several process types ran there (it is shown on the first process row that used the
     location). It is scaled by the location's allocation method: *per batch* (once), *per sample*
     (times the number of samples of the batch) or *per hour* (times the labour hours you enter
     below; unknown until you enter hours).
   - A warning mark ⚠ after a number means the entry in the reference is not marked as verified.
3. **Materials.** One row per batch and material: the roles it has, how many times it was used, the
   CAS number, the quantity in grams, the price per gram and the total. The quantity is the
   *Average_Quantity_Grams* of the reference, counted **once per batch** ("how many grams a batch
   typically consumes"); NOMAD does not record a usable gram amount, so there is no measured
   quantity. A material without a price or quantity in the reference has no total. A price taken
   from the app's built-in table of common chemicals is a rough estimate and says so in the notes.
4. **Labor.** NOMAD does not record who ran a process, so for every batch you choose a *role*
   (PhD Researcher, Postdoc, Engineer, HiWi) and enter the estimated *Hours*. The cost is the hours
   times the hourly rate of the role in the reference. Everything is recalculated when you change
   them.
5. **Summary.** One row per batch: number of samples, materials, processes, equipment, overhead
   (reference rows without a location, such as rent or disposal, by their allocation method),
   labour, the grand total and the cost per sample, plus the number of unverified and of missing
   items. A last row sums all selected batches. A total with missing items is marked "incomplete"
   and is a lower bound.
6. **Download Report** gives an Excel file (`LCC_Calculator_<time>.xlsx`) with the Processes,
   Materials, Labor and Summary sheets; it is a read-only snapshot of the tables on the page.

## Admin: cost reference template

For the person who maintains the cost file. Load a broad set of batches, then *Generate Cost
Reference Template*: you get a `cost_reference.xlsx` pre-filled with the real process, material
and item names found, with the cost columns empty and a guide sheet. Fill in the costs, mark
verified entries, and save the file as `apps/LCC_Calculator/cost_reference.xlsx`; from then on
every session uses it.

## Known limits

- Costs per process are one flat figure per batch from the reference, not derived from the
  durations or rates in the NOMAD entries.
- Equipment locations are matched by the exact text that was typed in NOMAD; variants of the same
  box (different spelling) are separate locations.
- Prices and quantities are estimates until marked verified.

## Contact

Questions and problems: open an issue on
[nomad-pv-analysis-apps](https://github.com/nomad-hzb/nomad-pv-analysis-apps/issues).
