# Bitmap Image Generator: user manual

## What the app is for

Create black and white bitmap images for combinatorial inkjet printing: an image of a chosen size
and resolution in which a chosen share of the pixels is black (a droplet), arranged in one of
several patterns, with white margins. You download it as a BMP, PNG or TIFF file for the printer.
The app does not use NOMAD.

## Step by step

1. **Image Size.** *Width (mm)* and *Height (mm)* of the whole image (default 25 x 25).
2. **Margins.** *Top*, *Bottom*, *Left* and *Right* (mm, default 3). The margins stay white. With
   *Sync all margins* ticked (the default) changing the top margin sets the other three to the same
   value.
3. **Resolution.** *DPI* (default 350). The size in pixels is the size in mm at this resolution;
   it is shown under the preview after you generate.
4. **Pattern Settings.**
   - *Pattern*: how the black pixels are arranged:
     - *Random*: black pixels at random positions;
     - *Ordered (Bayer Matrix)*: a regular ordered-dither pattern;
     - *Blue Noise*: random but without clusters of black pixels;
     - *Complementary A* and *B*: two patterns that are designed to be printed over each other
       (superposition);
     - *Poisson Disk Sampling*: points with a minimum distance between them;
     - *Floyd-Steinberg Dither*: the classic error-diffusion dither;
     - *Void-and-Cluster*: a very even distribution;
     - *Jittered Grid*: a regular grid with random displacement;
     - *Multi-Level Halftone*: a halftone-style pattern;
     - *Publication (Base 3)* and *(Base 4)*: repeating tiles of 3 x 3 or 4 x 4 pixels with
       droplet positions chosen to keep the droplets as far apart as possible (for combinatorial
       printing). The black share is set in steps; the tile closest to your value is used, so
       check the achieved value shown after generating.
     The text under the list says which patterns suit chemical mixing.
   - *Black %* (0 to 100, in steps of 0.5): the share of black in the area inside the margins.
5. **Output Format.** *Format* is BMP, PNG or TIFF. *Also download inverted* adds a second
   image with black and white swapped inside the margins (the margins stay white).
6. **Generate Image** draws the preview (the original, and the inverted one if ticked) and shows
   under it the size in pixels and the pattern, together with the black share **actually
   achieved** and the share you asked for. **Download** (enabled after generating) shows a
   download button for the file (and for the inverted file); the file name contains the size, the
   DPI and the achieved black share, for example `bitmap_25x25mm_350dpi_50.0pct.bmp`.

The images are saved as 1-bit black and white, so a printer that thresholds the image gets exactly
the pattern you see.

## Known limits

- The achieved black share can differ slightly from the one requested; the app reports the real
  value, and the Publication patterns only offer a limited number of steps.
- The Publication pattern with base 5 is not available (it needs more memory than the server has).
- Very large images or very high DPI make a large file and take longer to generate.

## Contact

Questions and problems: open an issue on
[nomad-pv-analysis-apps](https://github.com/nomad-hzb/nomad-pv-analysis-apps/issues).
