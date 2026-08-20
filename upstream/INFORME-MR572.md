# focaltech_moh: matcher retuning, measured on a second device

Tested MR !572 on hardware other than the author's: an **Alurin
ALU-BAR-R75825-000-156** (Ryzen 7 5825U) with the same **2808:9338** sensor,
on Arch (CachyOS), kernel 7.1.4, libfprint at `mr572` HEAD (1852477).

The USB side of the driver is solid — the chip opens in ~150 ms, INT_STATUS
polling works, and the frames it returns are clean 64x80 fingerprints. What
did not work was matching: nothing ever verified reliably.

## What was wrong

Three parameters, measured rather than guessed:

| | MR !572 | proposed |
|---|---|---|
| `FT9201_SEARCH_RADIUS` | 3 | **16** |
| `FT9201_NUM_ENROLL_STAGES` | 5 | **15** |
| `FT9201_NCC_THRESHOLD` | 0.30 | **0.55** |

### Search radius

This is the main one. Real finger placement on a 3x4 mm sensor varies by
roughly 16 px between presses, so a +-3 px search never finds the alignment.
Radius sweep on the measured set, at 15 templates:

```
radius  3: EER 8.83%      radius 12: EER 4.26%
radius  8: EER 4.23%      radius 16: EER 0.07%
radius 20: EER 0.15%   (no gain, 1.5x the cost)
```

16 is the knee. 20 costs 1.5x more and is slightly worse.

### Enrollment stages

Each template only covers part of the finger, so stage count matters nearly as
much as the radius. At radius 16:

```
 5 templates: EER 7.4%     (what the MR does today)
10 templates: EER 1.6%
15 templates: EER 0.07%
```

Raising this needs the templates off the instance struct — see below.

### Threshold

Set to 0.55 rather than the 0.50 that minimises FRR. The highest impostor
score observed was 0.468 and the 1st percentile of genuine scores 0.496; with
impostors drawn from only three fingers that FAR estimate is optimistic, so
0.55 buys margin at the cost of a 4.5% false reject rate.

## Result on hardware

Live, after the change:

```
genuine : 8/8 accepted   scores 0.874 - 0.951
impostor: 0/10 accepted  scores 0.111 - 0.446
```

Before: 4/9 genuine, and genuine/impostor score ranges overlapped, so no
threshold was safe at all.

## identify was missing

The driver only implemented `verify`. Anything authenticating without knowing
which finger will be presented — a lock screen — has nothing to call, and ends
up matching against a single stored print. The symptom is that enrolling a
finger looks like it erases the previous one, because fprintd lists the newest
print first and that is the only one still recognised. Nothing is lost; it just
is not consulted. Patch 3 adds it, scoring against every gallery print and
keeping the highest rather than returning the first over threshold.

## Three things worth knowing

**1. GObject caps instance size at 64K.** `enroll_images` as a fixed array is
15 * 5120 = 76800 bytes, which overflows it. The build fails during metainfo
generation with `g_type_register_static_simple: assertion 'instance_size <=
G_MAXUINT16' failed` — not an obvious error message for this cause. Patch
1 moves the templates to the heap.

**2. `FpImageDevice` / NBIS is not viable for this sensor.** Worth recording
so nobody spends time on it: `nbis-bench` (patch 2) runs libfprint's own NBIS
over raw frames. This sensor yields **2-4 minutiae per image** where bozorth3
needs ~12, so every score in the matrix is 0. That holds across ppmm from 8 to
40 and both ridge polarities, so it is an area limit, not a tuning problem.
This is presumably why the driver went match-on-host in the first place, but
the measurement makes it defensible.

**3. The thermal model counts waiting for a finger as active time.** On a
press-type reader, `fpi_device_update_temp` accumulates heat while the device
sits idle polling INT_STATUS, so capturing frames in a loop trips
`FP_DEVICE_ERROR_TOO_HOT` on a sensor that never warmed up. It cost 72
consecutive failed captures before it was obvious. Not this driver's bug, but
it makes bulk capture impractical without a workaround.

## Patches

- `0001` — the retuning, plus templates to the heap.
- `0003` — `dev_class->identify`.
- `0002` — `dev_class->capture` returning the **raw** frame rather than the
  preprocessed one, without which none of the above could be measured offline,
  plus the two evaluation tools (`fp-collect`, `nbis-bench`). The tools are
  offered separately in case they are not wanted in-tree.

## Reproducing this

Tooling, evaluation scripts and the tuned driver are at
<https://github.com/Dgmtnz/ft9201-fingerprint-linux>, along with an Arch
PKGBUILD. The capture set itself is deliberately not published — they are real
fingerprints, and unlike a password they cannot be rotated if they leak.
`fp-collect` from patch 2 gathers an equivalent set in a couple of minutes.

## Method

25 genuine + 24 impostor captures (3 fingers), raw frames off the sensor.
Scoring replicates `ft9201_ncc()` exactly, including the `n < w*h/2` overlap
guard, and uses the driver's real decision rule (max over templates), with
leave-one-out for genuine trials.

One caveat on the numbers: an earlier dataset collected by deliberately
*varying* finger position produced EER ~45% for every matcher tried, including
BLPOC. On a 3x4 mm sensor, varying placement captures disjoint regions of the
finger that genuinely do not correlate. Datasets for this device have to be
collected with natural, repeated placement or the results are meaningless.
The 0.07% figure above is from a naturally-placed set; a deliberately adverse
set would look far worse, and neither is wrong, they measure different things.
